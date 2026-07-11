// REL-07 — SACHET (NDMA) prewarmer status capsule.
//
// Polls `/api/monitoring/sachet-prewarmer` every 30 s and surfaces
// the prewarmer's health alongside the live alert count. Tones:
//
//   • healthy  → emerald, count badge in slate (we have fresh data)
//   • stale    → amber  (last_success_ts older than warn threshold)
//   • degraded → rose, pulsing ring (consecutive failures, no fresh
//                data — this is the state we want operators to see
//                the moment NDMA goes dark)
//   • disabled → slate, no badge (SACHET_PROXY_URL unset is the
//                most common cause in dev pods)
//   • unknown  → slate (first 30 s after boot, before the first tick)
//
// Click → flyout shows: state, alert count, cache age, last success
// timestamp, parse-failure rate, and a tiny "About" footnote pointing
// to the underlying source (NDMA SACHET via CF Worker).

import React, { useEffect, useRef, useState } from 'react';
import { Siren, ChevronDown } from 'lucide-react';
import { useDashboardSummary } from '../../hooks/useDashboardSummary';

// REL-08: polling now lives in useDashboardSummary (30s interval, shared
// across all capsules). This file only consumes the slice it cares about.

const TONES = {
  healthy:  { label: 'NDMA OK',     cls: 'text-emerald-300', dot: 'bg-emerald-500', ring: null },
  stale:    { label: 'NDMA STALE',  cls: 'text-amber-300',   dot: 'bg-amber-500',   ring: null },
  degraded: { label: 'NDMA DOWN',   cls: 'text-rose-300',    dot: 'bg-rose-500',
              ring: 'animate-ping bg-rose-400 opacity-75' },
  disabled: { label: 'NDMA OFF',    cls: 'text-slate-400',   dot: 'bg-slate-600',   ring: null },
  unknown:  { label: 'NDMA …',      cls: 'text-slate-400',   dot: 'bg-slate-600',   ring: null },
};

function fmtAge(seconds) {
  if (seconds == null) return '—';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

function fmtTs(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleTimeString(); } catch { return iso; }
}

export const SachetStatusCapsule = () => {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  // REL-08 — Subscribe to the batched dashboard-summary stream.
  // The selector projects only the slice we care about so unrelated
  // updates (DLQ, consent, etc.) don't trigger re-renders here.
  const slice = useDashboardSummary((s) => ({
    tele:  s.data?.sachet || null,
    error: s.error,
  }));
  const { tele, error } = slice;

  // Click-outside dismiss — same pattern as the neighbouring chips.
  useEffect(() => {
    if (!open) return undefined;
    const handler = (ev) => {
      if (ref.current && !ref.current.contains(ev.target)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  if (error === 'forbidden') return null;

  const state = tele?.health_state || 'unknown';
  const tone  = TONES[state] || TONES.unknown;
  const count = tele?.active_alert_count;

  return (
    <div ref={ref} className="relative" data-testid="sachet-status-capsule">
      <button
        type="button"
        data-testid="sachet-status-chip"
        onClick={() => setOpen((v) => !v)}
        className={`group flex items-center gap-2 rounded-full border border-slate-700/70 bg-slate-900/70 px-3 py-1.5 text-xs font-medium tracking-wide ${tone.cls} hover:border-slate-500/70`}
      >
        <span className="relative inline-flex h-2 w-2">
          {tone.ring && <span className={`absolute inline-flex h-full w-full rounded-full ${tone.ring}`} />}
          <span className={`relative inline-flex h-2 w-2 rounded-full ${tone.dot}`} />
        </span>
        <Siren size={12} className="opacity-70" />
        <span data-testid="sachet-status-label">{tone.label}</span>
        {count != null && state !== 'disabled' && (
          <span
            data-testid="sachet-status-count"
            className="rounded-full bg-slate-800/80 px-1.5 py-0.5 text-[10px] tabular-nums"
          >
            {count}
          </span>
        )}
        <ChevronDown size={12} className={`opacity-70 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div
          data-testid="sachet-status-flyout"
          style={{ zIndex: 1000 }}
          className="absolute right-0 mt-2 w-72 rounded-md border border-slate-700/70 bg-slate-950/95 p-3 text-xs text-slate-200 shadow-xl backdrop-blur"
        >
          <div className="mb-2 flex items-baseline justify-between border-b border-slate-800 pb-2">
            <span className="font-semibold tracking-wide text-slate-300">
              NDMA SACHET prewarmer
            </span>
            <span className={`rounded-full px-1.5 py-0.5 text-[10px] uppercase ${tone.cls}`}>
              {state}
            </span>
          </div>

          {error && error !== 'forbidden' && (
            <div className="mb-2 rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1.5 text-[11px] text-rose-200">
              Could not load: {String(error)}
            </div>
          )}

          {tele && (
            <dl className="space-y-1.5">
              <Row label="Active alerts" value={
                <span data-testid="sachet-flyout-alert-count" className="font-semibold tabular-nums">
                  {count ?? '—'}
                </span>
              } />
              <Row label="Cache age" value={
                <span className="tabular-nums">{fmtAge(tele.cache_age_seconds)}</span>
              } />
              <Row label="Last success" value={
                <span className="tabular-nums text-slate-400">{fmtTs(tele.last_success_ts)}</span>
              } />
              {tele.parse_failure_rate != null && (
                <Row label="Failure rate (recent)" value={
                  <span className="tabular-nums">
                    {(tele.parse_failure_rate * 100).toFixed(1)}%
                  </span>
                } />
              )}
              {state === 'degraded' && tele.recovery_progress != null && (
                <Row label="Recovery progress" value={
                  <span className="tabular-nums text-amber-300">
                    {tele.recovery_progress} clean ticks
                  </span>
                } />
              )}
            </dl>
          )}

          <div className="mt-3 border-t border-slate-800 pt-2 text-[10px] text-slate-500">
            Source: sachet.ndma.gov.in via CF Worker.
            <br />
            Source: batched /admin/monitoring/dashboard-summary (10 s cache).
          </div>
        </div>
      )}
    </div>
  );
};

// Tiny row helper — kept inline to avoid creating a separate file.
const Row = ({ label, value }) => (
  <div className="flex items-baseline justify-between text-[11px]">
    <span className="text-slate-500">{label}</span>
    {value}
  </div>
);

export default SachetStatusCapsule;
