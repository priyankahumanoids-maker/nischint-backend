// REL-04 — System Incident detail modal with operator pg_terminate_backend action.
//
// Surfaces the most recent `database_pool` incident's
// `snapshot_json.pg_stat_activity_top` rows so an operator can:
//   1. See the top-5 longest-running queries that were burning the
//      pool when it tipped over 85%.
//   2. Click "Kill" on any row to fire pg_terminate_backend(pid).
//      Two-step confirmation guards against fat-finger.
//   3. Every kill goes through `POST /api/admin/db/terminate-backend/{pid}`
//      and is audited with who/when/why server-side.
//
// Trigger: opens when the parent (`DBIncidentsCapsule`) calls
// `setOpen(true)`. Self-contained — the modal does its own data
// fetching to keep the parent capsule small.

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { X, Skull, Loader2, AlertTriangle, ShieldOff } from 'lucide-react';
import { toast } from 'sonner';
import api from '../../api';

function fmtMs(ms) {
  if (ms == null) return '—';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}

function fmtTime(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

function shortQuery(q, max = 80) {
  if (!q) return '';
  const cleaned = q.replace(/\s+/g, ' ').trim();
  return cleaned.length > max ? `${cleaned.slice(0, max - 1)}…` : cleaned;
}

// Confirm-modal step — separate component so its state is isolated.
const KillConfirm = ({ row, onCancel, onConfirm }) => {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  return (
    <div
      data-testid="kill-confirm-modal"
      style={{ zIndex: 1100 }}
      className="fixed inset-0 flex items-center justify-center bg-black/70 backdrop-blur-sm"
    >
      <div className="w-full max-w-md rounded-lg border border-rose-500/40 bg-slate-950 p-5 text-slate-100 shadow-2xl">
        <div className="mb-3 flex items-center gap-2">
          <AlertTriangle size={18} className="text-rose-400" />
          <h3 className="text-sm font-semibold tracking-wide">
            Terminate pg backend?
          </h3>
        </div>

        <div className="mb-3 space-y-1 rounded-md border border-slate-700/60 bg-slate-900 p-3 text-xs">
          <div><span className="text-slate-500">pid</span> <span className="tabular-nums text-rose-300">{row.pid}</span></div>
          <div><span className="text-slate-500">duration</span> <span className="tabular-nums">{fmtMs(row.duration_ms)}</span></div>
          <div><span className="text-slate-500">state</span> {row.state || '—'}</div>
          {row.wait_event && (
            <div><span className="text-slate-500">wait</span> {row.wait_event_type}/{row.wait_event}</div>
          )}
          <div className="pt-1">
            <span className="text-slate-500">query</span>
            <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-words text-[11px] text-slate-200">{row.query || ''}</pre>
          </div>
        </div>

        <label className="mb-1 block text-[11px] uppercase tracking-wider text-slate-500">
          Reason (optional, audited)
        </label>
        <input
          type="text"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          maxLength={500}
          placeholder="e.g. stuck idle-in-tx during deploy"
          data-testid="kill-reason-input"
          className="mb-4 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-100 focus:border-rose-500 focus:outline-none"
        />

        <div className="flex justify-end gap-2">
          <button
            type="button"
            data-testid="kill-cancel-btn"
            disabled={busy}
            onClick={onCancel}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
          >
            Cancel
          </button>
          <button
            type="button"
            data-testid="kill-confirm-btn"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try { await onConfirm(reason); } finally { setBusy(false); }
            }}
            className="inline-flex items-center gap-1 rounded-md bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-500 disabled:opacity-60"
          >
            {busy ? <Loader2 size={12} className="animate-spin" /> : <Skull size={12} />}
            Terminate
          </button>
        </div>
      </div>
    </div>
  );
};

export const SystemIncidentDetailModal = ({ incident, onClose, onRefresh }) => {
  const [confirmRow, setConfirmRow] = useState(null);
  const [killing, setKilling] = useState({}); // pid -> bool

  const rows = useMemo(() => {
    return incident?.snapshot?.pg_stat_activity_top || [];
  }, [incident]);

  const handleKill = useCallback(async (row, reason) => {
    setKilling((s) => ({ ...s, [row.pid]: true }));
    try {
      const res = await api.post(
        `/admin/db/terminate-backend/${row.pid}`,
        {
          query_text: row.query,
          duration_ms: row.duration_ms != null ? Math.round(row.duration_ms) : null,
          wait_event: row.wait_event,
          state: row.state,
          reason: reason || null,
          incident_id: incident?.id || null,
        }
      );
      const data = res.data || {};
      if (data.success) {
        toast.success(`pid ${row.pid} terminated (audit ${data.audit_log_id?.slice(0, 8)})`);
      } else if (data.pg_terminate_backend_returned === false) {
        // Postgres returned false — the pid was likely already gone.
        toast.warning(`pid ${row.pid} no longer running (Postgres returned false)`);
      } else {
        toast.error(`pid ${row.pid} not terminated: ${data.error || 'unknown'}`);
      }
      setConfirmRow(null);
      if (onRefresh) onRefresh();
    } catch (e) {
      const msg = e?.response?.data?.detail || e?.message || 'request failed';
      toast.error(`Kill failed: ${msg}`);
    } finally {
      setKilling((s) => {
        const copy = { ...s };
        delete copy[row.pid];
        return copy;
      });
    }
  }, [incident, onRefresh]);

  if (!incident) return null;

  return (
    <div
      data-testid="incident-detail-modal"
      style={{ zIndex: 1050 }}
      className="fixed inset-0 flex items-start justify-center overflow-auto bg-black/70 p-4 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="my-8 w-full max-w-3xl rounded-lg border border-slate-700 bg-slate-950 text-slate-100 shadow-2xl">

        <header className="flex items-start justify-between border-b border-slate-800 px-5 py-4">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wider text-cyan-300">
              {incident.trigger_source}
              {incident.root_cause_domain && (
                <span className="ml-2 text-slate-500">· {incident.root_cause_domain}</span>
              )}
            </div>
            <h2 className="mt-1 text-lg font-semibold">
              Incident <span className="text-slate-400">#{(incident.id || '').slice(0, 8)}</span>
            </h2>
            <div className="mt-1 text-xs text-slate-400">
              {fmtTime(incident.started_at)}
              {incident.resolved_at && <> → {fmtTime(incident.resolved_at)}</>}
              {incident.duration_ms != null && (
                <span className="ml-2 text-slate-500">({fmtMs(incident.duration_ms)})</span>
              )}
            </div>
          </div>
          <button
            type="button"
            data-testid="incident-detail-close"
            onClick={onClose}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
          >
            <X size={18} />
          </button>
        </header>

        <section className="px-5 py-3">
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Top long-running queries at incident open
          </h3>
          {rows.length === 0 && (
            <div className="rounded-md border border-slate-800 bg-slate-900/50 px-3 py-4 text-center text-xs text-slate-500">
              No pg_stat_activity capture for this incident.
              <br />
              (Snapshot only fires when pool util ≥ 85% or wait_count &gt; 0.)
            </div>
          )}
          {rows.length > 0 && (
            <div className="space-y-2">
              {rows.map((row) => (
                <div
                  key={row.pid}
                  data-testid={`pg-stat-row-${row.pid}`}
                  className="rounded-md border border-slate-800 bg-slate-900/60 p-3"
                >
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <div className="flex items-baseline gap-3 text-xs">
                      <span className="text-slate-500">pid</span>
                      <span className="font-semibold tabular-nums text-rose-300">{row.pid}</span>
                      <span className="text-slate-500">·</span>
                      <span className="tabular-nums">{fmtMs(row.duration_ms)}</span>
                      <span className="text-slate-500">·</span>
                      <span className="text-slate-300">{row.state || 'unknown'}</span>
                      {row.wait_event && (
                        <>
                          <span className="text-slate-500">·</span>
                          <span className="text-amber-300">{row.wait_event_type}/{row.wait_event}</span>
                        </>
                      )}
                    </div>
                    <button
                      type="button"
                      data-testid={`kill-btn-${row.pid}`}
                      disabled={!!killing[row.pid]}
                      onClick={() => setConfirmRow(row)}
                      className="inline-flex items-center gap-1 rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-[11px] font-semibold text-rose-300 hover:bg-rose-500/20 disabled:opacity-50"
                      title="pg_terminate_backend"
                    >
                      {killing[row.pid] ? (
                        <Loader2 size={11} className="animate-spin" />
                      ) : (
                        <ShieldOff size={11} />
                      )}
                      Kill
                    </button>
                  </div>
                  <div className="text-[11px] text-slate-400">
                    {row.application_name || '—'} · {row.usename || '—'}
                  </div>
                  <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950/60 p-2 font-mono text-[11px] text-slate-200">
                    {shortQuery(row.query, 500)}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </section>

        {incident.snapshot?.db_pool && (
          <section className="border-t border-slate-800 px-5 py-3 text-[11px] text-slate-400">
            <span className="text-slate-500">pool</span>{' '}
            <span className="tabular-nums">
              {incident.snapshot.db_pool.pg_pool_checked_out}/{incident.snapshot.db_pool.pg_pool_total_capacity} checked-out
            </span>{' · '}
            <span className="tabular-nums">{incident.snapshot.db_pool.pg_pool_utilization_pct}% util</span>
            {incident.snapshot.db_pool.pg_pool_wait_count > 0 && (
              <>
                {' · '}
                <span className="font-semibold text-rose-300">
                  {incident.snapshot.db_pool.pg_pool_wait_count} waiting
                </span>
              </>
            )}
          </section>
        )}
      </div>

      {confirmRow && (
        <KillConfirm
          row={confirmRow}
          onCancel={() => setConfirmRow(null)}
          onConfirm={(reason) => handleKill(confirmRow, reason)}
        />
      )}
    </div>
  );
};

export default SystemIncidentDetailModal;
