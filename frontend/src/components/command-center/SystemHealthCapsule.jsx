// System Health Capsule — multi-signal truth tile for the operator console.
// Polls /api/admin/monitoring/system-health every 30s. Renders a compact
// at-a-glance verdict + per-domain numbers. Treat as "system truth layer
// UI", not as decoration.

import React, { useEffect, useState, useRef } from 'react';
import { Activity, ChevronDown, RefreshCw } from 'lucide-react';
import api from '../../api';
import { useAuth } from '../../contexts/AuthContext';

const STATUS_TONE = {
  healthy:  { dot: 'bg-emerald-500', ring: 'animate-ping bg-emerald-400 opacity-75', label: 'HEALTHY',  labelClass: 'text-emerald-300' },
  warning:  { dot: 'bg-amber-500',   ring: null,                                      label: 'WARNING',  labelClass: 'text-amber-300' },
  degraded: { dot: 'bg-red-500',     ring: 'animate-ping bg-red-400 opacity-75',      label: 'DEGRADED', labelClass: 'text-red-300' },
  unknown:  { dot: 'bg-slate-500',   ring: null,                                      label: 'UNKNOWN',  labelClass: 'text-slate-400' },
};

const fmt = (v, suffix = '') => (v === null || v === undefined ? '—' : `${v}${suffix}`);
const fmtMs = (v) => (v === null || v === undefined ? '—' : v >= 1000 ? `${(v / 1000).toFixed(2)}s` : `${Math.round(v)}ms`);

// Relative-time formatter for the baselines flyout — mirrors how the
// scheduler / risk-engine rows render `last_run_at`. Keeps it compact
// so the 3-column flyout stays at 300px.
const fmtAgo = (iso) => {
  if (!iso) return '—';
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return '—';
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60)   return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
};

export const SystemHealthCapsule = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(false);
  const [lastSource, setLastSource] = useState('poll'); // 'poll' | 'ws'
  const [lastDelta, setLastDelta] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshErr, setRefreshErr] = useState(null);
  const containerRef = useRef(null);

  // SB-02 — admin-only manual matview refresh. Optimistically patches the
  // baselines block on success so the operator sees the new timestamp
  // without waiting for the next 30s poll. Errors are surfaced inline.
  const onRefreshBaselines = async (e) => {
    e.stopPropagation();
    if (!isAdmin || refreshing) return;
    setRefreshing(true);
    setRefreshErr(null);
    try {
      const res = await api.post('/admin/monitoring/baselines/refresh');
      setData(prev => prev ? ({
        ...prev,
        domains: { ...(prev.domains || {}), baselines: res.data?.status === 'success' ? 'healthy' : 'degraded' },
        baselines: {
          ...(prev.baselines || {}),
          last_refreshed_at:        res.data?.refreshed_at,
          last_refresh_duration_ms: res.data?.duration_ms,
          last_refresh_rows:        res.data?.rows,
          last_status:              res.data?.status,
          last_error:               res.data?.error,
          freshness:                res.data?.status === 'success' ? 'fresh' : (prev.baselines?.freshness || 'unknown'),
        },
      }) : prev);
    } catch (err) {
      setRefreshErr(err.response?.status === 403 ? 'forbidden' : 'failed');
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    let alive = true;
    const fetchHealth = async () => {
      try {
        const res = await api.get('/admin/monitoring/system-health');
        if (alive) { setData(res.data); setError(null); setLastSource('poll'); }
      } catch (e) {
        if (alive) setError(e.response?.status === 403 ? 'no-access' : 'unreachable');
      }
    };
    fetchHealth();
    const iv = setInterval(fetchHealth, 30000);

    // Hybrid: instant WS push for state-transitions, REST as recovery
    // safety net. The WS event ONLY fires on threshold crossings.
    const onDelta = (ev) => {
      const d = ev?.detail || {};
      if (!d.severity || !d.source) return;
      // Optimistic patch: bump capsule color immediately so the operator
      // sees the change in <1s. The next 30s poll reconciles to authoritative.
      setData(prev => {
        const base = prev || { domains: {}, status: 'healthy' };
        const domains = { ...(base.domains || {}), [d.source]: d.severity };
        const next = { ...base, domains };
        if (Object.values(domains).includes('degraded')) next.status = 'degraded';
        else if (Object.values(domains).includes('warning')) next.status = 'warning';
        else next.status = 'healthy';
        // Patch the relevant subtree so the flyout numbers reflect it too
        if (d.source === 'scheduler' && d.metric === 'drift_p95') {
          next.schedulers = { ...(base.schedulers || {}), drift_p95_ms: d.value };
        } else if (d.source === 'ai' && d.metric === 'p95_ms') {
          next.ai = { ...(base.ai || {}), p95_ms: d.value };
        } else if (d.source === 'auth' && d.metric === 'p95_ms') {
          next.auth = { ...(base.auth || {}), p95_ms: d.value };
        } else if (d.source === 'queue' && d.metric === 'pending_total') {
          next.queue = { ...(base.queue || {}), pending_total: d.value };
        } else if (d.source === 'baselines') {
          // SB-02 — patch the baselines subtree so the flyout reflects
          // the new state without waiting for the next REST poll.
          next.baselines = { ...(base.baselines || {}) };
          if (d.metric === 'last_status')   next.baselines.last_status = d.value === 1.0 ? 'failure' : (next.baselines.last_status || 'unknown');
          if (d.metric === 'staleness_s')   next.baselines.freshness   = 'stale';
        }
        return next;
      });
      setLastSource('ws');
      setLastDelta(d);
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
    const onClick = (e) => { if (!containerRef.current?.contains(e.target)) setOpen(false); };
    const onEsc = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onEsc);
    return () => { document.removeEventListener('mousedown', onClick); document.removeEventListener('keydown', onEsc); };
  }, [open]);

  // 403 (operator without admin role) → render nothing
  if (error === 'no-access') return null;

  if (!data && !error) {
    return (
      <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-slate-800/60 border border-slate-700/40" data-testid="system-health-capsule-loading">
        <span className="w-1.5 h-1.5 rounded-full bg-slate-600 animate-pulse" />
        <span className="text-[10px] font-mono text-slate-500 tracking-wider">SYSTEM —</span>
      </div>
    );
  }

  const tone = STATUS_TONE[data?.status || 'unknown'];

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-slate-800/70 border border-slate-700/50 hover:bg-slate-700/60 transition-colors"
        data-testid="system-health-capsule"
        title={data?.status === 'healthy' ? 'All subsystems healthy' : `System status: ${tone.label}`}
      >
        <span className="relative inline-flex w-1.5 h-1.5">
          {tone.ring && <span className={`absolute inline-flex w-full h-full rounded-full ${tone.ring}`} />}
          <span className={`relative inline-flex w-1.5 h-1.5 rounded-full ${tone.dot}`} />
        </span>
        <Activity className="w-3 h-3 text-slate-400" />
        <span className={`text-[10px] font-mono font-bold tracking-wider ${tone.labelClass}`} data-testid="system-health-status">
          {tone.label}
        </span>
        {data?.schedulers?.drift_p95_ms !== undefined && data?.schedulers?.drift_p95_ms !== null && (
          <span className="text-[9px] font-mono text-slate-500">· {fmtMs(data.schedulers.drift_p95_ms)}</span>
        )}
        <ChevronDown className={`w-3 h-3 text-slate-500 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && data && (
        <div
          className="absolute right-0 top-full mt-1.5 z-[1500] w-[300px] max-w-[calc(100vw-1.5rem)] rounded-md border border-slate-700 bg-slate-900/95 backdrop-blur shadow-xl"
          data-testid="system-health-capsule-flyout"
        >
          <div className="px-3 py-2 border-b border-slate-700/60 flex items-center justify-between">
            <span className="text-[10px] font-mono font-bold tracking-wider text-slate-200">SYSTEM TRUTH LAYER</span>
            <span className={`text-[9px] font-mono font-bold tracking-wider ${tone.labelClass}`}>{tone.label}</span>
          </div>
          <div className="p-2 space-y-1">
            <Row
              label="Schedulers"
              value={`drift p95 ${fmtMs(data.schedulers?.drift_p95_ms)}`}
              extra={`${data.schedulers?.count ?? '—'} jobs · role=${data.schedulers?.role || '—'}`}
              status={data.domains?.schedulers}
              testid="sh-row-schedulers"
            />
            <Row
              label="AI Inference"
              value={data.ai?.samples > 0 ? `p95 ${fmtMs(data.ai?.p95_ms)}` : 'no samples yet'}
              extra={`${fmt(data.ai?.calls_total)} calls · ${fmt(data.ai?.error_count)} errors`}
              status={data.domains?.ai}
              testid="sh-row-ai"
            />
            <Row
              label="Auth Latency"
              value={data.auth?.samples > 0 ? `p95 ${fmtMs(data.auth?.p95_ms)}` : 'no samples yet'}
              extra={
                data.auth?.samples > 0
                  ? `${data.auth.samples} req · cache ${data.auth.hit_rate != null ? Math.round(data.auth.hit_rate * 100) + '%' : '—'} (30s)`
                  : 'rolling 30s window'
              }
              status={data.domains?.auth}
              testid="sh-row-auth"
            />
            <Row
              label="Queue"
              value={`${fmt(data.queue?.pending_total)} pending`}
              extra={Object.entries(data.queue?.by_stream || {})
                .map(([k, v]) => `${k}=${(v?.depth ?? 0)}`)
                .join(' · ')}
              status={data.domains?.queue}
              testid="sh-row-queue"
            />
            <Row
              label="WebSocket"
              value={`${fmt(data.websocket?.command_center_active)} active`}
              extra="Command Center"
              status={data.domains?.ws}
              testid="sh-row-ws"
            />
            <Row
              label="Risk Engine"
              value={(data.risk_engine?.state || 'unknown').toUpperCase()}
              extra={data.risk_engine?.last_run_at ? new Date(data.risk_engine.last_run_at).toLocaleTimeString() : '—'}
              status={data.domains?.risk_engine}
              testid="sh-row-risk"
            />
            <Row
              label="Baselines"
              value={
                data.baselines?.last_refresh_duration_ms != null
                  ? `${(data.baselines.freshness || 'unknown').toUpperCase()} · ${fmtMs(data.baselines.last_refresh_duration_ms)}`
                  : (data.baselines?.freshness || 'unknown').toUpperCase()
              }
              extra={
                data.baselines?.last_refreshed_at
                  ? `${fmtAgo(data.baselines.last_refreshed_at)} · ${fmt(data.baselines.last_refresh_rows)} rows`
                  : 'no refresh on record'
              }
              status={data.domains?.baselines}
              testid="sh-row-baselines"
              action={
                isAdmin ? (
                  <button
                    type="button"
                    onClick={onRefreshBaselines}
                    disabled={refreshing}
                    className="ml-2 shrink-0 inline-flex items-center justify-center w-5 h-5 rounded hover:bg-slate-700/70 text-slate-400 hover:text-slate-200 disabled:opacity-40 disabled:cursor-wait"
                    data-testid="sh-baselines-refresh-btn"
                    title={refreshErr === 'forbidden' ? 'Forbidden' : refreshErr === 'failed' ? 'Refresh failed — retry' : 'Refresh matview (admin)'}
                  >
                    <RefreshCw className={`w-3 h-3 ${refreshing ? 'animate-spin' : ''}`} />
                  </button>
                ) : null
              }
            />
          </div>
          <div className="px-3 py-1.5 border-t border-slate-700/60 flex items-center justify-between gap-2">
            <p className="text-[8px] text-slate-500 tracking-wider">
              {lastSource === 'ws' ? 'last update via WS' : 'polled every 30s'} · read-only
            </p>
            {lastDelta && (
              <p className="text-[8px] font-mono text-slate-400 truncate max-w-[180px]" data-testid="sh-last-transition">
                {lastDelta.previous_severity || '∅'} → <span className={STATUS_TONE[lastDelta.severity]?.labelClass}>{lastDelta.severity}</span> ({lastDelta.source})
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

const Row = ({ label, value, extra, status, testid, action }) => {
  const tone = STATUS_TONE[status || 'unknown'];
  return (
    <div className="flex items-center justify-between gap-2 px-1.5 py-1 rounded hover:bg-slate-800/60" data-testid={testid}>
      <div className="flex items-center gap-1.5 min-w-0">
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${tone.dot}`} />
        <span className="text-[10px] text-slate-300 font-medium">{label}</span>
      </div>
      <div className="flex items-center min-w-0">
        <div className="flex flex-col items-end min-w-0">
          <span className="text-[10px] font-mono text-slate-200">{value}</span>
          {extra && <span className="text-[8px] font-mono text-slate-500 truncate max-w-[180px]">{extra}</span>}
        </div>
        {action}
      </div>
    </div>
  );
};
