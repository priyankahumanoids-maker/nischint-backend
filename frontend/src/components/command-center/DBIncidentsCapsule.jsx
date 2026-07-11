// REL-04 — DB Incidents capsule.
//
// Lives alongside the other Command Center status chips. Polls
// `/api/monitoring/incidents?status=active&limit=10` every 60 s and:
//   * shows a count badge of active `database_pool` incidents,
//   * tone-grades the chip (rose when any active, slate when none),
//   * on click opens the SystemIncidentDetailModal pre-loaded with
//     the most recent active incident — that's where the operator
//     sees pg_stat_activity_top and can press Kill.
//
// If there are no active `database_pool` incidents, the chip still
// reveals the most recent resolved one so the operator can review
// the post-mortem after the fact.

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Database, ChevronDown } from 'lucide-react';
import { useDashboardSummary, refetchDashboardSummary } from '../../hooks/useDashboardSummary';
import { SystemIncidentDetailModal } from './SystemIncidentDetailModal';

export const DBIncidentsCapsule = () => {
  const [selected, setSelected] = useState(null);
  const [open, setOpen]         = useState(false);
  const ref = useRef(null);

  // REL-08 — Subscribe to the batched dashboard-summary. We only need
  // active incidents for the chip count + flyout, so the selector
  // returns just that slice. The batched endpoint pre-filters to
  // `trigger_source == "database_pool"` server-side.
  const slice = useDashboardSummary((s) => ({
    incidents: s.data?.db?.active_incidents || [],
    error:     s.error,
  }));
  const { incidents, error } = slice;

  // Kept for the modal's onRefresh callback (e.g. after a kill).
  const fetchIncidents = () => refetchDashboardSummary();

  useEffect(() => {
    if (!open) return undefined;
    const handler = (ev) => {
      if (ref.current && !ref.current.contains(ev.target)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const activeCount = useMemo(
    () => incidents.filter((i) => i.status === 'active').length,
    [incidents],
  );

  if (error === 'forbidden') return null;

  const tone =
    activeCount > 0
      ? { label: 'DB INCIDENT',
          cls:   'text-rose-300',
          dot:   'bg-rose-500',
          ring:  'animate-ping bg-rose-400 opacity-75' }
      : incidents.length > 0
      ? { label: 'DB OK',
          cls:   'text-slate-300',
          dot:   'bg-slate-500',
          ring:  null }
      : { label: 'DB OK',
          cls:   'text-emerald-300',
          dot:   'bg-emerald-500',
          ring:  null };

  return (
    <>
      <div ref={ref} className="relative" data-testid="db-incidents-capsule">
        <button
          type="button"
          data-testid="db-incidents-chip"
          onClick={() => setOpen((v) => !v)}
          className={`group flex items-center gap-2 rounded-full border border-slate-700/70 bg-slate-900/70 px-3 py-1.5 text-xs font-medium tracking-wide ${tone.cls} hover:border-slate-500/70`}
        >
          <span className="relative inline-flex h-2 w-2">
            {tone.ring && <span className={`absolute inline-flex h-full w-full rounded-full ${tone.ring}`} />}
            <span className={`relative inline-flex h-2 w-2 rounded-full ${tone.dot}`} />
          </span>
          <Database size={12} className="opacity-70" />
          <span>{tone.label}</span>
          {activeCount > 0 && (
            <span className="rounded-full bg-rose-500/20 px-1.5 py-0.5 text-[10px] tabular-nums">
              {activeCount}
            </span>
          )}
          <ChevronDown size={12} className={`opacity-70 transition-transform ${open ? 'rotate-180' : ''}`} />
        </button>

        {open && (
          <div
            data-testid="db-incidents-flyout"
            style={{ zIndex: 1000 }}
            className="absolute right-0 mt-2 w-80 rounded-md border border-slate-700/70 bg-slate-950/95 p-3 text-xs text-slate-200 shadow-xl backdrop-blur"
          >
            <div className="mb-2 border-b border-slate-800 pb-2 font-semibold tracking-wide text-slate-300">
              Database pool incidents
            </div>
            {incidents.length === 0 && (
              <div className="py-3 text-center text-slate-500">No incidents on record.</div>
            )}
            <ul className="space-y-1.5">
              {incidents.slice(0, 6).map((inc) => (
                <li
                  key={inc.id}
                  data-testid={`db-incident-row-${inc.id}`}
                >
                  <button
                    type="button"
                    onClick={() => { setSelected(inc); setOpen(false); }}
                    className={`w-full rounded-md border px-2 py-1.5 text-left ${
                      inc.status === 'active'
                        ? 'border-rose-500/40 bg-rose-500/10 hover:bg-rose-500/15'
                        : 'border-slate-700/50 bg-slate-900/60 hover:bg-slate-800/60'
                    }`}
                  >
                    <div className="flex items-baseline justify-between">
                      <span className="text-[11px] font-semibold">{inc.severity_peak}</span>
                      <span className="text-[10px] text-slate-500">
                        {inc.status === 'active' ? 'active' : 'resolved'}
                      </span>
                    </div>
                    <div className="mt-0.5 text-[10px] text-slate-400">
                      {new Date(inc.started_at).toLocaleString()}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
            <div className="mt-2 border-t border-slate-800 pt-2 text-[10px] text-slate-500">
              Click any row to view top queries + kill backends.
            </div>
          </div>
        )}
      </div>

      {selected && (
        <SystemIncidentDetailModal
          incident={selected}
          onClose={() => setSelected(null)}
          onRefresh={fetchIncidents}
        />
      )}
    </>
  );
};

export default DBIncidentsCapsule;
