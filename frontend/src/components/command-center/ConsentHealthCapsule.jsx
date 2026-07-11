// DPDP-04-DASH — Consent Health capsule for the Command Center.
//
// Surfaces the per-category grant-rate aggregated by
// `GET /api/admin/consents/health` so operators can spot a copy
// regression (a UX change drops grant rate from 90% → 60%) the
// moment it starts.
//
// Tone mapping (mirrors the backend `overall_state` field):
//   • critical — at least one category < 50 % with meaningful sample.
//   • warning  — at least one category < 80 % with meaningful sample.
//   • ok       — every category healthy (or samples too small to tell).
//   • nodata   — no user has been prompted yet.
//
// Poll interval: 60 s. The aggregate moves slowly, so anything tighter
// is wasted query load on the consents table.

import React, { useEffect, useRef, useState } from 'react';
import { ShieldCheck, ChevronDown } from 'lucide-react';
import { useDashboardSummary } from '../../hooks/useDashboardSummary';

const STATE_TONE = {
  ok:       { label: 'CONSENT OK',     cls: 'text-emerald-300', dot: 'bg-emerald-500', ring: null },
  warning:  { label: 'CONSENT WARN',   cls: 'text-amber-300',   dot: 'bg-amber-500',   ring: null },
  critical: { label: 'CONSENT DROP',   cls: 'text-rose-300',    dot: 'bg-rose-500',
              ring: 'animate-ping bg-rose-400 opacity-75' },
  nodata:   { label: 'CONSENT N/A',    cls: 'text-slate-400',   dot: 'bg-slate-600',   ring: null },
};

function pct(rate) {
  return `${Math.round((rate ?? 0) * 100)}%`;
}

export const ConsentHealthCapsule = () => {
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);

  // REL-08 — Subscribe to the shared dashboard-summary stream
  // (consolidated batch endpoint, single poll across all capsules).
  const slice = useDashboardSummary((s) => ({
    health: s.data?.consent || null,
    error:  s.error,
  }));
  const { health, error } = slice;

  // Close flyout on outside click — same pattern as DLQCapsule.
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

  const state = health?.overall_state || 'nodata';
  const tone  = STATE_TONE[state] || STATE_TONE.nodata;
  const cats  = health?.categories || [];
  const healthyPct = health?.healthy_threshold
    ? Math.round(health.healthy_threshold * 100)
    : 80;
  const criticalPct = health?.critical_threshold
    ? Math.round(health.critical_threshold * 100)
    : 50;

  return (
    <div ref={containerRef} className="relative" data-testid="consent-health-capsule">
      <button
        type="button"
        data-testid="consent-health-chip"
        onClick={() => setOpen((v) => !v)}
        className={`group flex items-center gap-2 rounded-full border border-slate-700/70 bg-slate-900/70 px-3 py-1.5 text-xs font-medium tracking-wide ${tone.cls} hover:border-slate-500/70`}
      >
        <span className="relative inline-flex h-2 w-2">
          {tone.ring && (
            <span className={`absolute inline-flex h-full w-full rounded-full ${tone.ring}`} />
          )}
          <span className={`relative inline-flex h-2 w-2 rounded-full ${tone.dot}`} />
        </span>
        <ShieldCheck size={12} className="opacity-70" />
        <span data-testid="consent-health-label">{tone.label}</span>
        {health?.total_users_prompted > 0 && (
          <span
            data-testid="consent-health-users"
            className="rounded-full bg-slate-800/80 px-1.5 py-0.5 text-[10px] tabular-nums"
          >
            {health.total_users_prompted}
          </span>
        )}
        <ChevronDown
          size={12}
          className={`opacity-70 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div
          data-testid="consent-health-flyout"
          // Lift above Leaflet's pane range — same as DLQCapsule.
          style={{ zIndex: 1000 }}
          className="absolute right-0 mt-2 w-80 rounded-md border border-slate-700/70 bg-slate-950/95 p-3 text-xs text-slate-200 shadow-xl backdrop-blur"
        >
          <div className="mb-2 flex items-baseline justify-between border-b border-slate-800 pb-2">
            <span className="font-semibold tracking-wide text-slate-300">
              DPDP §6 consent grant rates
            </span>
            <span className="text-[10px] text-slate-500 tabular-nums">
              n={health?.total_users_prompted ?? 0}
            </span>
          </div>

          {error && error !== 'forbidden' && (
            <div className="mb-2 rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1.5 text-[11px] text-rose-200">
              Could not load: {String(error)}
            </div>
          )}

          {cats.length === 0 && !error && (
            <div className="text-slate-500">No consent rows yet.</div>
          )}

          <ul className="space-y-2">
            {cats.map((c) => {
              const lowSample = c.decided < (health?.min_sample_size ?? 10);
              // Visual classification — the backend already returns
              // `healthy` so we honour it, but for the per-row colour
              // we need finer granularity to tell warning vs critical
              // apart.
              let itemTone = 'border-slate-700/40 bg-slate-900/40';
              if (!lowSample) {
                if (c.grant_rate < (health?.critical_threshold ?? 0.5)) {
                  itemTone = 'border-rose-500/40 bg-rose-500/10';
                } else if (c.grant_rate < (health?.healthy_threshold ?? 0.8)) {
                  itemTone = 'border-amber-500/40 bg-amber-500/10';
                } else {
                  itemTone = 'border-emerald-500/30 bg-emerald-500/5';
                }
              }
              return (
                <li
                  key={c.category}
                  data-testid={`consent-health-row-${c.category}`}
                  className={`rounded-md border px-2 py-1.5 ${itemTone}`}
                >
                  <div className="flex items-baseline justify-between">
                    <span className="text-[11px] text-slate-200">
                      {c.label_en}
                    </span>
                    <span
                      data-testid={`consent-health-rate-${c.category}`}
                      className="text-[11px] tabular-nums font-medium"
                    >
                      {pct(c.grant_rate)}
                    </span>
                  </div>
                  <div className="mt-0.5 flex items-baseline justify-between text-[10px] text-slate-400">
                    <span className="tabular-nums">
                      {c.granted}/{c.decided} users granted
                    </span>
                    {lowSample && (
                      <span className="italic text-slate-500">low sample</span>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>

          <div className="mt-3 border-t border-slate-800 pt-2 text-[10px] text-slate-500">
            Healthy ≥ {healthyPct}% · Critical &lt; {criticalPct}% ·
            min sample = {health?.min_sample_size ?? 10}.
            <br />
            Polls /admin/monitoring/dashboard-summary every 30 s (batched).
          </div>
        </div>
      )}
    </div>
  );
};

export default ConsentHealthCapsule;
