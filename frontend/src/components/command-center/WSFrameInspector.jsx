// Phase 5 Hardening — WS Frame Inspector (dev-mode only)
//
// Floating bottom-right card that lists the last N COMMAND_CENTER_DELTA
// frames received over the WebSocket. Helps developers + investor demos
// confirm the system is genuinely live, not mocked.
//
// Toggle:  add `?debug_ws=true` to the URL (or set localStorage.debug_ws)

import React, { useEffect, useState, useMemo } from 'react';
import { Activity, X } from 'lucide-react';
import { subscribeFrames, deltaMetrics } from '../../utils/applyDelta';
import api from '../../api';

function isEnabled() {
  if (typeof window === 'undefined') return false;
  try {
    const url = new URL(window.location.href);
    if (url.searchParams.get('debug_ws') === 'true') return true;
    if (window.localStorage && window.localStorage.getItem('debug_ws') === 'true') return true;
  } catch (_) { /* ignore */ }
  return false;
}

export const WSFrameInspector = () => {
  const [open, setOpen] = useState(true);
  const [frames, setFrames] = useState([]);
  const [metrics, setMetrics] = useState(deltaMetrics.snapshot());
  const [serverMetrics, setServerMetrics] = useState(null);
  const enabled = useMemo(() => isEnabled(), []);

  useEffect(() => {
    if (!enabled) return;
    const unsub = subscribeFrames((next) => setFrames(next));
    const iv = setInterval(() => setMetrics(deltaMetrics.snapshot()), 1000);

    // Phase 6 — server-side fleet metrics (dev-mode only). Polled every
    // 12s so the operator can watch emit/skip rates climb without
    // hammering the API.
    let svIv = null;
    const fetchServer = () => {
      api.get('/operator/cc-delta/metrics')
        .then(r => setServerMetrics(r.data || null))
        .catch(() => setServerMetrics(null));
    };
    fetchServer();
    svIv = setInterval(fetchServer, 12000);

    return () => { unsub(); clearInterval(iv); if (svIv) clearInterval(svIv); };
  }, [enabled]);

  if (!enabled || !open) {
    return enabled ? (
      <button
        onClick={() => setOpen(true)}
        data-testid="ws-inspector-open"
        className="fixed bottom-4 right-4 z-[9999] flex items-center gap-1.5 rounded-full bg-emerald-500/90 hover:bg-emerald-500 px-3 py-1.5 text-[11px] font-mono text-white shadow-lg backdrop-blur"
      >
        <Activity className="h-3.5 w-3.5 animate-pulse" />
        WS · {frames.length}
      </button>
    ) : null;
  }

  return (
    <div
      data-testid="ws-frame-inspector"
      className="fixed bottom-4 right-4 z-[9999] w-[380px] max-h-[60vh] flex flex-col rounded-lg border border-emerald-500/30 bg-slate-950/95 shadow-2xl backdrop-blur"
    >
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-emerald-500/20">
        <div className="flex items-center gap-1.5">
          <Activity className="h-3.5 w-3.5 text-emerald-400 animate-pulse" />
          <span className="text-[11px] font-mono text-emerald-300 tracking-wide">WS Frame Inspector</span>
        </div>
        <button
          onClick={() => setOpen(false)}
          data-testid="ws-inspector-close"
          className="text-slate-500 hover:text-slate-300"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="grid grid-cols-3 gap-2 px-3 py-2 border-b border-emerald-500/10 text-[10px] font-mono">
        <Stat label="frames" value={metrics.framesReceived} color="text-slate-300" />
        <Stat label="applied" value={`${metrics.applied}${metrics.successRate !== null ? ` (${metrics.successRate}%)` : ''}`} color="text-emerald-400" />
        <Stat label="rejected" value={metrics.rejected} color="text-amber-400" />
        <Stat label="stale" value={metrics.staleRejected} color="text-amber-300" />
        <Stat label="version" value={metrics.versionMismatch} color="text-rose-400" />
        <Stat label="reconnects" value={metrics.reconnects} color="text-cyan-400" />
      </div>

      {/* Phase 6 — Server-side fleet metrics row */}
      {serverMetrics && (
        <div
          className="grid grid-cols-4 gap-2 px-3 py-2 border-b border-emerald-500/10 bg-slate-900/30 text-[10px] font-mono"
          data-testid="ws-inspector-server-metrics"
        >
          <Stat label="fleet/min" value={serverMetrics.rate_per_min ?? 0} color="text-cyan-300" />
          <Stat label="emitted" value={serverMetrics.emitted ?? 0} color="text-emerald-300" />
          <Stat label="skipped" value={serverMetrics.skipped ?? 0} color="text-slate-400" />
          <Stat label="failed" value={serverMetrics.failed ?? 0} color="text-rose-400" />
        </div>
      )}

      <div className="flex-1 overflow-y-auto" data-testid="ws-frame-list">
        {frames.length === 0 ? (
          <div className="p-3 text-[10px] text-slate-500 font-mono italic">
            Waiting for COMMAND_CENTER_DELTA frames…
          </div>
        ) : (
          frames.map((f) => (
            <div
              key={f.id}
              data-testid="ws-frame-row"
              className="px-3 py-1.5 border-b border-slate-800/60 hover:bg-slate-900/50"
            >
              <div className="flex items-center justify-between text-[10px] font-mono">
                <span className="text-slate-400">{relTime(f.received_at)}</span>
                <span className="text-slate-600 truncate max-w-[140px]" title={f.user_id}>
                  {f.user_id ? f.user_id.slice(0, 8) : '—'}
                </span>
              </div>
              <div className="mt-1 flex flex-wrap gap-1">
                {f.paths.map((p) => (
                  <span
                    key={p}
                    className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/20"
                  >
                    {p}
                  </span>
                ))}
                {f.paths.length === 0 && (
                  <span className="text-[9px] font-mono text-slate-600 italic">
                    (no paths)
                  </span>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

const Stat = ({ label, value, color }) => (
  <div className="flex items-baseline gap-1">
    <span className="text-slate-500">{label}</span>
    <span className={color}>{value}</span>
  </div>
);

function relTime(receivedAtMs) {
  const diff = Math.max(0, Date.now() - receivedAtMs);
  if (diff < 1000) return 'now';
  if (diff < 60000) return `${Math.round(diff / 1000)}s ago`;
  return `${Math.round(diff / 60000)}m ago`;
}
