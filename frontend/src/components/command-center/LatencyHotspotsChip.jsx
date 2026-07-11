// Latency Hotspots Chip — the 3 slowest API endpoints right now.
// Polls /api/admin/monitoring/latency every 30s and renders the worst
// p95 inline. Click to expand the top-3 flyout.
//
// Color thresholds (locked by product spec):
//   < 500ms       → green   (healthy)
//   500–1999ms    → amber   (slow, watch)
//   ≥ 2000ms      → red     (hotspot, investigate now)
//
// Honest behaviour notes:
// - Hidden entirely for non-operator users (403 → null).
// - When there's no traffic yet, renders "NO DATA" in muted slate
//   rather than fake-green — operators should never see "healthy"
//   for a system they don't have data on.

import React, { useEffect, useState, useRef } from 'react';
import { Gauge, ChevronDown } from 'lucide-react';
import api from '../../api';

const POLL_INTERVAL_MS = 30_000;
const TOP_N = 3;

// Single source of truth for the latency → tone mapping. Used by both
// the chip and each row in the flyout, so the visual language stays
// consistent end-to-end.
const toneForMs = (ms) => {
  if (ms === null || ms === undefined) {
    return { dot: 'bg-slate-500', text: 'text-slate-400', label: 'NO DATA' };
  }
  if (ms < 500)   return { dot: 'bg-emerald-500', text: 'text-emerald-300', label: 'FAST' };
  if (ms < 2000)  return { dot: 'bg-amber-500',   text: 'text-amber-300',   label: 'SLOW' };
  return                  { dot: 'bg-red-500',     text: 'text-red-300',     label: 'HOTSPOT' };
};

const fmtMs = (v) => {
  if (v === null || v === undefined) return '—';
  if (v >= 1000) return `${(v / 1000).toFixed(2)}s`;
  return `${Math.round(v)}ms`;
};

// Endpoint label gets truncated in the flyout so a long
// `/api/operator/command-center/{user_id}` doesn't blow the row.
const fmtEndpoint = (s) => {
  if (!s) return '—';
  if (s.length <= 36) return s;
  return s.slice(0, 33) + '…';
};

export const LatencyHotspotsChip = () => {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);

  useEffect(() => {
    let alive = true;
    const fetchLatency = async () => {
      try {
        const res = await api.get('/admin/monitoring/latency', {
          params: { top_n: TOP_N, sort_by: 'p95_ms' },
        });
        if (alive) { setData(res.data); setError(null); }
      } catch (e) {
        if (alive) setError(e.response?.status === 403 ? 'no-access' : 'unreachable');
      }
    };
    fetchLatency();
    const iv = setInterval(fetchLatency, POLL_INTERVAL_MS);
    return () => { alive = false; clearInterval(iv); };
  }, []);

  // Outside-click + ESC close the flyout — same pattern as the
  // SystemHealthCapsule / LastCityUpdateChip.
  useEffect(() => {
    if (!open) return;
    const onClick = (e) => { if (!containerRef.current?.contains(e.target)) setOpen(false); };
    const onEsc   = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onEsc);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onEsc);
    };
  }, [open]);

  // 403 (e.g. non-operator viewer) → render nothing. The endpoint is
  // operator+admin only; this chip should match that gate exactly.
  if (error === 'no-access') return null;

  if (!data && !error) {
    return (
      <div
        className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-slate-800/60 border border-slate-700/40"
        data-testid="latency-hotspots-chip-loading"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-slate-600 animate-pulse" />
        <span className="text-[10px] font-mono text-slate-500 tracking-wider">LATENCY —</span>
      </div>
    );
  }

  const endpoints = data?.endpoints || [];
  // Worst p95 across the top-3 sets the chip color. Endpoints with
  // null p95 (no samples yet) are skipped — we don't want a brand-new
  // endpoint to drag the chip into NO DATA when other endpoints have
  // real numbers to show.
  const worstP95 = endpoints
    .map(e => e.p95_ms)
    .filter(v => v !== null && v !== undefined)[0] ?? null;
  const tone = toneForMs(worstP95);

  const title = worstP95 === null
    ? 'No traffic recorded yet'
    : `Worst p95: ${fmtMs(worstP95)} — click to see top ${TOP_N}`;

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-slate-800/70 border border-slate-700/50 hover:bg-slate-700/60 transition-colors"
        data-testid="latency-hotspots-chip"
        title={title}
      >
        <span className={`relative inline-flex w-1.5 h-1.5 rounded-full ${tone.dot}`} />
        <Gauge className="w-3 h-3 text-slate-400" />
        <span
          className={`text-[10px] font-mono font-bold tracking-wider ${tone.text}`}
          data-testid="latency-hotspots-status"
        >
          {tone.label}
        </span>
        {worstP95 !== null && (
          <span
            className="text-[9px] font-mono text-slate-500"
            data-testid="latency-hotspots-worst-p95"
          >· {fmtMs(worstP95)}</span>
        )}
        <ChevronDown className={`w-3 h-3 text-slate-500 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-1.5 z-[1500] w-[340px] max-w-[calc(100vw-1.5rem)] rounded-md border border-slate-700 bg-slate-900/95 backdrop-blur shadow-xl"
          data-testid="latency-hotspots-flyout"
        >
          <div className="px-3 py-2 border-b border-slate-700/60 flex items-center justify-between">
            <span className="text-[10px] font-mono font-bold tracking-wider text-slate-200">
              LATENCY HOTSPOTS · top {TOP_N} by p95
            </span>
            <span className={`text-[9px] font-mono font-bold tracking-wider ${tone.text}`}>
              {tone.label}
            </span>
          </div>

          <div className="p-2 space-y-1">
            {endpoints.length === 0 && (
              <p
                className="text-[10px] text-slate-500 italic px-1.5 py-2"
                data-testid="latency-hotspots-empty"
              >
                No API traffic recorded yet — the rolling window is empty.
              </p>
            )}
            {endpoints.map((e, idx) => {
              const rowTone = toneForMs(e.p95_ms);
              return (
                <div
                  key={e.endpoint}
                  className="flex items-center justify-between gap-2 px-1.5 py-1 rounded hover:bg-slate-800/60"
                  data-testid={`latency-row-${idx}`}
                >
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${rowTone.dot}`} />
                    <span
                      className="text-[10px] text-slate-300 font-mono truncate"
                      title={e.endpoint}
                      data-testid={`latency-row-endpoint-${idx}`}
                    >
                      {fmtEndpoint(e.endpoint)}
                    </span>
                  </div>
                  <div className="flex flex-col items-end shrink-0">
                    <span
                      className={`text-[10px] font-mono font-bold ${rowTone.text}`}
                      data-testid={`latency-row-p95-${idx}`}
                    >
                      {fmtMs(e.p95_ms)}
                    </span>
                    <span className="text-[8px] font-mono text-slate-500">
                      p50 {fmtMs(e.p50_ms)} · p99 {fmtMs(e.p99_ms)} · n={e.samples}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="px-3 py-1.5 border-t border-slate-700/60">
            <p className="text-[8px] text-slate-500 tracking-wider">
              rolling last-{data?.max_samples_per_endpoint ?? 500} samples · polled every 30s · read-only
            </p>
          </div>
        </div>
      )}
    </div>
  );
};
