/**
 * NetworkHealthCapsule — operator-facing TTFA snapshot + audible alert.
 *
 * Tiny pill rendered in the Command Center status strip. Pulls
 * `/api/_dev/alert-ttfa/stats?since=3600&include_redis=true` every 30s
 * and surfaces:
 *   - SOS p95 (ms) / Help p95 (ms) / alert volume in the last hour
 *   - rolled-up status badge (🟢 healthy / 🟠 degraded / ⚪ low-data)
 *
 * Threshold (KRA): SOS p95 < 5000ms = healthy. Above → degraded.
 *
 * NISCH-008c — operator intelligence layer:
 *   - On ANY transition into 🟠 degraded → flash + single soft chime
 *     (debounced, plays at most once per 30s per state transition).
 *   - On ANY transition back to 🟢 → silent recovery (no chime).
 *
 * Sound asset: `/sounds/alert-soft.mp3` (lazy-loaded). If the asset is
 * missing or autoplay is blocked, the visual flash still fires.
 */
import React, { useEffect, useRef, useState } from 'react';
import { Activity, AlertTriangle, CheckCircle2 } from 'lucide-react';
import api from '../../api';

const HEALTHY_P95_MS = 5000;
const POLL_MS = 30_000;
const CHIME_DEBOUNCE_MS = 30_000;
const CHIME_URL = '/sounds/alert.wav';

export const NetworkHealthCapsule = () => {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);
  const [flash, setFlash] = useState(false);
  const prevVariantRef = useRef(null);
  const lastChimeAtRef = useRef(0);
  const audioRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    let timer = null;

    const fetchStats = async () => {
      try {
        const res = await api.get(
          '/_dev/alert-ttfa/stats?since=3600&include_redis=true',
        );
        if (!cancelled) {
          setStats(res?.data || null);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err?.message || 'fetch failed');
      } finally {
        if (!cancelled) timer = setTimeout(fetchStats, POLL_MS);
      }
    };
    fetchStats();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  // Lazy-load audio once.
  useEffect(() => {
    try {
      const a = new Audio(CHIME_URL);
      a.preload = 'auto';
      a.volume = 0.4;
      audioRef.current = a;
    } catch {
      // ignore — audio support is optional
    }
  }, []);

  // Compute variant *before* the chime effect so it stays unconditional.
  const sosP95 = stats?.by_kind?.sos?.p95 ?? 0;
  const helpP95 = stats?.by_kind?.help_requested?.p95 ?? 0;
  const total1h = stats?.samples_considered ?? 0;
  const lowData = stats?.confidence === 'low';
  const sosHealthy = sosP95 === 0 || sosP95 < HEALTHY_P95_MS;
  const helpHealthy = helpP95 === 0 || helpP95 < HEALTHY_P95_MS;
  const healthy = sosHealthy && helpHealthy;
  const styleMap = {
    healthy:  { border: 'border-emerald-500/30', icon: 'text-emerald-400', text: 'text-emerald-300' },
    degraded: { border: 'border-amber-500/30',   icon: 'text-amber-400',   text: 'text-amber-300'   },
    lowData:  { border: 'border-slate-700/50',   icon: 'text-slate-500',   text: 'text-slate-400'   },
  };
  const variant = !stats ? null : (lowData ? 'lowData' : (healthy ? 'healthy' : 'degraded'));

  // NISCH-008c — chime + flash on transition INTO 'degraded'. Hook is
  // unconditional (runs every render); the *body* is gated on `variant`.
  useEffect(() => {
    if (variant === null) return;
    const prev = prevVariantRef.current;
    if (prev !== null && variant !== prev && variant === 'degraded') {
      const now = Date.now();
      if (now - lastChimeAtRef.current > CHIME_DEBOUNCE_MS) {
        lastChimeAtRef.current = now;
        setFlash(true);
        setTimeout(() => setFlash(false), 1200);
        try {
          if (audioRef.current) {
            audioRef.current.currentTime = 0;
            const playPromise = audioRef.current.play();
            if (playPromise && typeof playPromise.catch === 'function') {
              playPromise.catch(() => {});
            }
          }
        } catch {
          // never block on audio errors
        }
      }
    }
    prevVariantRef.current = variant;
  }, [variant]);

  if (error) {
    return (
      <div
        className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-800/40 border border-slate-700/50"
        data-testid="cc-network-health-error"
        title={`Network health unavailable: ${error}`}
      >
        <Activity className="w-3 h-3 text-slate-500" />
        <span className="text-[9px] text-slate-500 font-medium">NET HEALTH —</span>
      </div>
    );
  }

  if (!stats) {
    return (
      <div
        className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-800/40 border border-slate-700/50"
        data-testid="cc-network-health-loading"
      >
        <Activity className="w-3 h-3 text-slate-500 animate-pulse" />
        <span className="text-[9px] text-slate-500 font-medium">NET HEALTH …</span>
      </div>
    );
  }

  const s = styleMap[variant];
  const Icon = lowData ? Activity : (healthy ? CheckCircle2 : AlertTriangle);
  const label = lowData ? 'NET LOW DATA' : (healthy ? 'NET HEALTHY' : 'NET DEGRADED');

  return (
    <div
      className={`flex items-center gap-2 px-2.5 py-1 rounded-full bg-slate-800/40 border ${s.border} ${flash ? 'animate-pulse ring-2 ring-amber-500/60' : ''} transition-shadow duration-300`}
      data-testid="cc-network-health"
      data-variant={variant}
      title={
        `TTFA last hour\n` +
        `SOS p95: ${sosP95}ms (target <${HEALTHY_P95_MS}ms)\n` +
        `Help p95: ${helpP95}ms\n` +
        `Total alerts: ${total1h}\n` +
        `Confidence: ${stats?.confidence || 'n/a'}`
      }
    >
      <Icon className={`w-3 h-3 ${s.icon}`} />
      <span className={`text-[9px] font-bold tracking-wider ${s.text}`}>
        {label}
      </span>
      <span className="text-[9px] text-slate-400 font-mono" data-testid="cc-network-health-sos">
        SOS {sosP95}ms
      </span>
      <span className="text-[9px] text-slate-400 font-mono" data-testid="cc-network-health-help">
        HELP {helpP95}ms
      </span>
      <span className="text-[9px] text-slate-500 font-mono" data-testid="cc-network-health-volume">
        {total1h}/h
      </span>
    </div>
  );
};

export default NetworkHealthCapsule;
