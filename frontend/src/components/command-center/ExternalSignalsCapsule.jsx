// NISCH-012.4 — External Signals capsule (Sachet feed health +
// active modifier surface).
//
// Mirrors the V2ParityChip pattern:
//   * Polls /api/admin/monitoring/sachet-prewarmer every 30 s.
//   * Listens for `cc:system_health_delta` events with
//     `source === "sachet_health"` and patches state optimistically
//     within <1 s of a server-side transition.
//   * 30-s REST poll is the reconciliation layer.
//
// Locked invariants:
//   * Same four-state machine as the backend:
//       healthy / stale / degraded / unknown
//     Colours: green / amber / red / grey.
//   * Hides itself for non-admin/non-operator users (403).
//   * Click-to-open flyout shows the operationally critical fields:
//       cache_age_seconds, parse_failure_rate (rolling-10),
//       active_alert_count, and the list of currently-active
//       Sachet modifiers (zone, severity, strength, raw_url).

import React, { useEffect, useRef, useState } from 'react';
import { ChevronDown, Cloud } from 'lucide-react';
import api from '../../api';

const STATE_TONE = {
  healthy:  { label: 'NDMA HEALTHY',  cls: 'text-emerald-300', dot: 'bg-emerald-500', ring: null },
  stale:    { label: 'NDMA STALE',    cls: 'text-amber-300',   dot: 'bg-amber-500',   ring: null },
  degraded: { label: 'NDMA DEGRADED', cls: 'text-rose-300',    dot: 'bg-rose-500',
              ring: 'animate-ping bg-rose-400 opacity-75' },
  unknown:  { label: 'NDMA NO DATA',  cls: 'text-slate-400',   dot: 'bg-slate-600',   ring: null },
};

const SEVERITY_TONE = {
  extreme:  'bg-rose-500/15 border-rose-500/40 text-rose-200',
  severe:   'bg-amber-500/15 border-amber-500/40 text-amber-200',
  moderate: 'bg-sky-500/15 border-sky-500/40 text-sky-200',
  minor:    'bg-slate-700/40 border-slate-600/40 text-slate-300',
};

function fmtAge(sec) {
  if (sec === null || sec === undefined) return '—';
  if (sec < 60) return `${Math.round(sec)}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m${Math.round(sec % 60)}s`;
  return `${Math.floor(sec / 3600)}h${Math.round((sec % 3600) / 60)}m`;
}

function fmtPct(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `${(v * 100).toFixed(0)}%`;
}

export const ExternalSignalsCapsule = () => {
  const [telemetry, setTelemetry] = useState(null);
  const [active, setActive] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(false);
  const [wsState, setWsState] = useState(null); // optimistic WS override
  const containerRef = useRef(null);

  useEffect(() => {
    let alive = true;
    const fetchAll = async () => {
      try {
        // Single roll-up call replaces the previous 4-call fan-out.
        // The roll-up's `sachet` block matches the per-provider
        // telemetry shape we care about; modifier lists come from
        // the separate `active` endpoint (one extra call total,
        // not four).
        const [rRes, aRes] = await Promise.all([
          api.get('/admin/monitoring/prewarmers'),
          api.get('/admin/monitoring/external-signals/active'),
        ]);
        if (!alive) return;
        const sachet = rRes.data?.sachet || {};
        // Map the slim roll-up shape onto the legacy telemetry
        // shape the rest of this component expects.
        setTelemetry({
          health_state:        sachet.health_state,
          cache_age_seconds:   sachet.cache_age_seconds,
          parse_failure_rate:  sachet.parse_failure_rate,
          last_success_ts:     sachet.last_success_ts,
          recovery_progress:   sachet.recovery_progress,
          recovery_required:   sachet.recovery_required,
          active_alert_count:  aRes.data?.sachet?.active_count ?? 0,
        });
        setActive(aRes.data);
        setError(null);
        setWsState((prev) =>
          prev && prev !== sachet.health_state ? null : prev,
        );
      } catch (e) {
        if (alive) {
          setError(e.response?.status === 403 ? 'no-access' : 'unreachable');
        }
      }
    };
    fetchAll();
    const iv = setInterval(fetchAll, 30000);

    const onDelta = (e) => {
      const d = e.detail || {};
      if (d.source !== 'sachet_health' || !d.sachet_health) return;
      const sh = d.sachet_health;
      // Optimistic patch — flips the chip within ~1 s of a server
      // transition. Next REST poll reconciles to authoritative.
      setWsState(sh.state || null);
      setTelemetry((prev) => ({
        ...(prev || {}),
        health_state:        sh.state ?? prev?.health_state,
        cache_age_seconds:   sh.cache_age_seconds ?? prev?.cache_age_seconds,
        parse_failure_rate:  sh.parse_failure_rate ?? prev?.parse_failure_rate,
        active_alert_count:  sh.active_alert_count ?? prev?.active_alert_count,
        last_success_ts:     sh.last_success_ts ?? prev?.last_success_ts,
      }));
    };
    window.addEventListener('cc:system_health_delta', onDelta);

    return () => {
      alive = false;
      clearInterval(iv);
      window.removeEventListener('cc:system_health_delta', onDelta);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    const onClick = (e) => {
      if (!containerRef.current?.contains(e.target)) setOpen(false);
    };
    const onEsc = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onEsc);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onEsc);
    };
  }, [open]);

  if (error === 'no-access') return null;

  if (!telemetry) {
    return (
      <div
        className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-slate-800/60 border border-slate-700/40"
        data-testid="external-signals-capsule-loading"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-slate-600 animate-pulse" />
        <span className="text-[10px] font-mono text-slate-500 tracking-wider">NDMA —</span>
      </div>
    );
  }

  const state = wsState || telemetry.health_state || 'unknown';
  const tone = STATE_TONE[state] || STATE_TONE.unknown;
  const modifiers = active?.sachet?.modifiers || [];

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-slate-800/70 border border-slate-700/50 hover:bg-slate-700/60 transition-colors"
        data-testid="external-signals-capsule"
        title="NDMA Sachet feed — pre-warmer health + active modifiers"
      >
        <span className="relative inline-flex w-1.5 h-1.5">
          {tone.ring && (
            <span className={`absolute inline-flex w-full h-full rounded-full ${tone.ring}`} />
          )}
          <span className={`relative inline-flex w-1.5 h-1.5 rounded-full ${tone.dot}`} />
        </span>
        <Cloud className="w-3 h-3 text-slate-400" />
        <span
          className={`text-[10px] font-mono font-bold tracking-wider ${tone.cls}`}
          data-testid="external-signals-state"
        >
          {tone.label}
        </span>
        {modifiers.length > 0 && (
          <span
            className="text-[9px] font-mono font-bold text-sky-200"
            data-testid="external-signals-modifier-count"
            title="Active modifiers in last successful parse"
          >
            · {modifiers.length} mods
          </span>
        )}
        <ChevronDown
          className={`w-3 h-3 text-slate-500 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-1.5 z-[1500] w-[380px] max-w-[calc(100vw-1.5rem)] rounded-md border border-slate-700 bg-slate-900/95 backdrop-blur shadow-xl"
          data-testid="external-signals-flyout"
        >
          <div className="px-3 py-2 border-b border-slate-700/60 flex items-center justify-between">
            <span className="text-[10px] font-mono font-bold tracking-wider text-slate-200">
              NDMA SACHET FEED
            </span>
            <span className="text-[9px] font-mono text-slate-500">
              state={state} · poll=30s · jitter=4m±45s
            </span>
          </div>

          {/* Health row */}
          <div className="p-2 space-y-2">
            <div className="bg-slate-800/40 border border-slate-700/30 rounded p-2"
                 data-testid="external-signals-health-row">
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-1.5">
                  <span className={`w-1.5 h-1.5 rounded-full ${tone.dot}`} />
                  <span className="text-[10px] font-mono font-bold tracking-wider text-slate-200">
                    PRE-WARMER HEALTH
                  </span>
                </div>
                <span className={`text-[9px] font-mono font-bold tracking-wider ${tone.cls}`}>
                  · {tone.label}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-x-2 text-[10px] font-mono">
                <Stat
                  label="cache age"
                  value={fmtAge(telemetry.cache_age_seconds)}
                  tone={state === 'healthy' ? 'slate' : 'amber'}
                  testid="external-signals-cache-age"
                />
                <Stat
                  label="failure rate"
                  value={fmtPct(telemetry.parse_failure_rate)}
                  tone={(telemetry.parse_failure_rate || 0) >= 0.20 ? 'rose' : 'slate'}
                  testid="external-signals-failure-rate"
                />
                <Stat
                  label="active alerts"
                  value={`${telemetry.active_alert_count ?? 0}`}
                  tone="slate"
                  testid="external-signals-active-count"
                />
              </div>
              {state === 'degraded' && (
                <div className="mt-1 text-[9px] font-mono text-rose-300"
                     data-testid="external-signals-degraded-warning">
                  ⚠ NDMA feed is stale or failing — external modifiers
                  may not reflect current ground truth.
                </div>
              )}
              {(telemetry.recovery_progress || 0) > 0 && (
                <div className="mt-1 text-[9px] font-mono text-amber-300"
                     data-testid="external-signals-recovery-progress">
                  recovering · {telemetry.recovery_progress}/
                  {telemetry.recovery_required} clean reads
                </div>
              )}
            </div>

            {/* Active modifiers */}
            <div className="bg-slate-800/40 border border-slate-700/30 rounded p-2"
                 data-testid="external-signals-modifiers-row">
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] font-mono font-bold tracking-wider text-slate-200">
                  ACTIVE MODIFIERS
                </span>
                <span className="text-[9px] font-mono text-slate-500">
                  {modifiers.length} active · TTL {Math.round((modifiers[0]?.expiry_window_s || 0) / 60)}m
                </span>
              </div>
              {modifiers.length === 0 ? (
                <div className="text-[9px] font-mono text-slate-500"
                     data-testid="external-signals-modifiers-empty">
                  No active NDMA modifiers — alert confidence runs on
                  base signals only.
                </div>
              ) : (
                <div className="max-h-[240px] overflow-y-auto space-y-1">
                  {modifiers.slice(0, 20).map((m, i) => (
                    <ModifierRow key={`${m.zone}-${i}`} m={m} />
                  ))}
                  {modifiers.length > 20 && (
                    <div className="text-[9px] font-mono text-slate-500 text-center pt-1">
                      …{modifiers.length - 20} more
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="px-3 py-1.5 border-t border-slate-700/60 text-[9px] font-mono text-slate-500 flex justify-between">
            <span>Source: sachet.ndma.gov.in</span>
            <span data-testid="external-signals-recovery-rule">
              regress fast · recover after {telemetry.recovery_required ?? 3}
            </span>
          </div>
        </div>
      )}
    </div>
  );
};

const ModifierRow = ({ m }) => {
  const sevTone = SEVERITY_TONE[m.severity] || SEVERITY_TONE.minor;
  return (
    <div
      className="text-[10px] font-mono flex items-center justify-between gap-2 py-0.5 px-1 hover:bg-slate-800/40 rounded"
      data-testid="external-signals-modifier-row"
    >
      <div className="flex items-center gap-1.5 min-w-0">
        <span className={`px-1 py-0 rounded border ${sevTone} text-[9px] font-bold uppercase tracking-wider`}>
          {m.severity}
        </span>
        <span className="text-slate-300 truncate" title={m.title}>
          {m.zone}
        </span>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <span className="text-slate-400">str {m.strength?.toFixed?.(2) ?? '—'}</span>
        {m.raw_url && (
          <a
            href={m.raw_url}
            target="_blank"
            rel="noreferrer"
            className="text-sky-400 hover:text-sky-300 underline"
            data-testid="external-signals-modifier-link"
          >
            CAP
          </a>
        )}
      </div>
    </div>
  );
};

const Stat = ({ label, value, tone = 'slate', testid }) => {
  const cls =
    tone === 'rose' ? 'text-rose-300' :
    tone === 'amber' ? 'text-amber-300' :
    'text-slate-200';
  return (
    <div className="flex flex-col" data-testid={testid}>
      <span className="text-[8px] tracking-wider text-slate-500 uppercase">{label}</span>
      <span className={`font-bold ${cls}`}>{value}</span>
    </div>
  );
};

export default ExternalSignalsCapsule;
