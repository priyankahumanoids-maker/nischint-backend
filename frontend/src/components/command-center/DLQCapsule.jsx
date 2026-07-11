// DLQ Reconciler capsule chip.
//
// Renders a single chip in the Command Center header showing the
// drain pressure across the four audit-row DLQs produced by the
// 2026-02 reliability ratchet pass:
//
//   * dlq:notification_history
//   * dlq:failsafe_audit
//   * dlq:voice_distress_audit
//   * dlq:checkin_audit
//
// Locked thresholds (mirror the backend `get_dlq_stats()` contract):
//   * any DLQ ≥ 50 % of MAX → red    ("DLQ CRITICAL")
//   * any DLQ ≥ 10 % of MAX → amber  ("DLQ PRESSURE")
//   * otherwise            → green  ("DLQ IDLE")
//   * Redis unavailable    → grey   ("DLQ NO DATA")
//
// Poll interval: 30 s. The reconciler ticks every 60 s server-side
// so anything tighter is wasted load.

import React, { useEffect, useRef, useState } from 'react';
import { Archive, ChevronDown } from 'lucide-react';
import api from '../../api';
import { useDashboardSummary, refetchDashboardSummary } from '../../hooks/useDashboardSummary';

const STATE_TONE = {
  idle:     { label: 'DLQ IDLE',     cls: 'text-emerald-300', dot: 'bg-emerald-500', ring: null },
  pressure: { label: 'DLQ PRESSURE', cls: 'text-amber-300',   dot: 'bg-amber-500',   ring: null },
  critical: { label: 'DLQ CRITICAL', cls: 'text-rose-300',    dot: 'bg-rose-500',
              ring: 'animate-ping bg-rose-400 opacity-75' },
  nodata:   { label: 'DLQ NO DATA',  cls: 'text-slate-400',   dot: 'bg-slate-600',   ring: null },
};

// REL-08: polling now lives in useDashboardSummary (30s shared interval).

function deriveTone(stats) {
  if (!stats || stats.redis_available === false) return 'nodata';
  if (stats.any_red) return 'critical';
  if (stats.any_amber) return 'pressure';
  return 'idle';
}

function shortKey(k) {
  // dlq:notification_history → notification_history
  return (k || '').replace(/^dlq:/, '');
}

export const DLQCapsule = () => {
  const [open, setOpen] = useState(false);
  const [draining, setDraining] = useState(null);  // dlq key being drained
  const [drainResult, setDrainResult] = useState(null);
  const containerRef = useRef(null);

  // REL-08 — Subscribe to the batched dashboard-summary instead of
  // owning our own poll. The drain action still talks to the
  // dedicated POST endpoint and forces a refetch on success.
  const slice = useDashboardSummary((s) => ({
    stats: s.data?.dlqs || null,
    error: s.error,
  }));
  const { stats, error } = slice;

  const fetchStats = () => refetchDashboardSummary();

  const handleDrain = async (key, mode) => {
    // mode: 'discard' (replay=false) | 'replay' (replay=true)
    const replay = mode === 'replay';
    const confirmMsg = replay
      ? `Re-route poisoned entries from ${key} through their replay function. Continue?`
      : `HARD-DISCARD poisoned entries from ${key}. They will be returned in the response for CSV export but removed from Redis. Continue?`;
    // eslint-disable-next-line no-alert
    if (!window.confirm(confirmMsg)) return;
    setDraining(key);
    setDrainResult(null);
    try {
      const res = await api.post(
        `/admin/monitoring/dlqs/${encodeURIComponent(key)}/poison/drain`,
        null,
        { params: { replay, max_drain: 100 } },
      );
      setDrainResult({ key, mode, data: res.data });
      await fetchStats();
    } catch (e) {
      setDrainResult({ key, mode, error: e?.response?.data?.detail || e?.message || 'drain failed' });
    } finally {
      setDraining(null);
    }
  };

  // Close flyout on outside click.
  useEffect(() => {
    if (!open) return undefined;
    const handler = (ev) => {
      if (containerRef.current && !containerRef.current.contains(ev.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  if (error === 'forbidden') return null;

  const tone = STATE_TONE[deriveTone(stats)] || STATE_TONE.nodata;
  const dlqs = stats?.dlqs || [];
  const totalDepth = dlqs.reduce((acc, d) => acc + (d.depth || 0), 0);
  const totalPoison = dlqs.reduce((acc, d) => acc + (d.poison_depth || 0), 0);

  return (
    <div ref={containerRef} className="relative" data-testid="dlq-capsule">
      <button
        type="button"
        data-testid="dlq-capsule-chip"
        onClick={() => setOpen((v) => !v)}
        className={`group flex items-center gap-2 rounded-full border border-slate-700/70 bg-slate-900/70 px-3 py-1.5 text-xs font-medium tracking-wide ${tone.cls} hover:border-slate-500/70`}
      >
        <span className="relative inline-flex h-2 w-2">
          {tone.ring && (
            <span className={`absolute inline-flex h-full w-full rounded-full ${tone.ring}`} />
          )}
          <span className={`relative inline-flex h-2 w-2 rounded-full ${tone.dot}`} />
        </span>
        <Archive size={12} className="opacity-70" />
        <span data-testid="dlq-capsule-label">{tone.label}</span>
        {totalDepth > 0 && (
          <span
            data-testid="dlq-capsule-depth"
            className="rounded-full bg-slate-800/80 px-1.5 py-0.5 text-[10px] tabular-nums"
          >
            {totalDepth}
          </span>
        )}
        <ChevronDown
          size={12}
          className={`opacity-70 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div
          data-testid="dlq-capsule-flyout"
          // z-[1000] lifts the panel above Leaflet's pane range (400-650);
          // tile pane=200, overlay=400, shadow=500, marker=600, tooltip=650,
          // popup=700 — so 1000 is safely above the highest map layer.
          style={{ zIndex: 1000 }}
          className="absolute right-0 mt-2 w-80 rounded-md border border-slate-700/70 bg-slate-950/95 p-3 text-xs text-slate-200 shadow-xl backdrop-blur"
        >
          <div className="mb-2 flex items-baseline justify-between border-b border-slate-800 pb-2">
            <span className="font-semibold tracking-wide text-slate-300">
              Audit-row DLQs
            </span>
            <span className="text-[10px] text-slate-500 tabular-nums">
              max_attempts={stats?.max_attempts ?? '—'}
            </span>
          </div>

          {dlqs.length === 0 && (
            <div className="text-slate-500">No DLQs registered.</div>
          )}

          <ul className="space-y-2">
            {dlqs.map((d) => {
              const itemTone = d.red
                ? 'border-rose-500/40 bg-rose-500/10'
                : d.amber
                  ? 'border-amber-500/40 bg-amber-500/10'
                  : 'border-slate-700/40 bg-slate-900/40';
              const isDraining = draining === d.key;
              return (
                <li
                  key={d.key}
                  data-testid={`dlq-row-${shortKey(d.key)}`}
                  className={`rounded-md border px-2 py-1.5 ${itemTone}`}
                >
                  <div className="flex items-baseline justify-between">
                    <span className="font-mono text-[11px] text-slate-200">
                      {shortKey(d.key)}
                    </span>
                    <span className="text-[10px] tabular-nums text-slate-400">
                      {d.depth}/{d.max_size} ({d.pressure_pct?.toFixed?.(1) ?? d.pressure_pct}%)
                    </span>
                  </div>
                  {d.poison_depth > 0 && (
                    <>
                      <div className="mt-1 flex items-baseline justify-between text-[10px] text-rose-300">
                        <span>poison</span>
                        <span className="tabular-nums">
                          {d.poison_depth}/{d.poison_max}
                        </span>
                      </div>
                      <div className="mt-1.5 flex gap-1.5">
                        <button
                          type="button"
                          data-testid={`dlq-poison-replay-${shortKey(d.key)}`}
                          disabled={isDraining}
                          onClick={() => handleDrain(d.key, 'replay')}
                          className="flex-1 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[10px] font-medium text-amber-200 hover:bg-amber-500/20 disabled:opacity-50"
                        >
                          {isDraining ? '…' : 'Replay'}
                        </button>
                        <button
                          type="button"
                          data-testid={`dlq-poison-discard-${shortKey(d.key)}`}
                          disabled={isDraining}
                          onClick={() => handleDrain(d.key, 'discard')}
                          className="flex-1 rounded border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-[10px] font-medium text-rose-200 hover:bg-rose-500/20 disabled:opacity-50"
                        >
                          {isDraining ? '…' : 'Discard'}
                        </button>
                      </div>
                    </>
                  )}
                </li>
              );
            })}
          </ul>

          {drainResult && (
            <div
              data-testid="dlq-drain-result"
              className={`mt-3 rounded-md border px-2 py-1.5 text-[11px] ${
                drainResult.error
                  ? 'border-rose-500/50 bg-rose-500/10 text-rose-200'
                  : 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
              }`}
            >
              {drainResult.error ? (
                <>Error draining {shortKey(drainResult.key)}: {String(drainResult.error)}</>
              ) : (
                <>
                  {drainResult.mode === 'replay' ? 'Replayed' : 'Discarded'}{' '}
                  {shortKey(drainResult.key)}: attempted={drainResult.data?.attempted ?? 0}
                  {drainResult.mode === 'replay'
                    ? `, drained=${drainResult.data?.drained ?? 0}, requeued=${drainResult.data?.requeued ?? 0}`
                    : `, discarded=${drainResult.data?.discarded ?? 0}`}
                </>
              )}
            </div>
          )}

          {totalPoison > 0 && (
            <div
              data-testid="dlq-capsule-poison-warning"
              className="mt-3 rounded-md border border-rose-500/50 bg-rose-500/10 px-2 py-1.5 text-[11px] text-rose-200"
            >
              {totalPoison} payload{totalPoison === 1 ? '' : 's'} past
              {' '}
              {stats?.max_attempts ?? 3}
              {' '}attempts — operator drain required.
            </div>
          )}

          <div className="mt-3 text-[10px] text-slate-500">
            Polls /admin/monitoring/dlqs every 30 s · reconciler ticks every 60 s.
          </div>
        </div>
      )}
    </div>
  );
};

export default DLQCapsule;
