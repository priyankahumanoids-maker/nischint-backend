// LoopHealthCapsule — event-loop saturation early-warning tile.
//
// Polls /api/admin/monitoring/runtime-info every 5s and renders a
// compact verdict tile that turns AMBER above 100ms loop lag and RED
// above 500ms. Operators see saturation BEFORE Cloudflare surfaces
// 520s. Backed by the same endpoint that fed our LT-01 load test.
//
// Verdict thresholds (LT-01 — May 30, 2026):
//   GREEN  loop_lag < 100ms   AND task_count < 50    → healthy
//   AMBER  loop_lag < 500ms   OR  task_count < 150   → degraded
//   RED    loop_lag >= 500ms  OR  task_count >= 150  → saturated
//
// Reference data from LT-01 60-VU saturation test:
//   - baseline:  loop_lag = 0.08ms, tasks = 10
//   - saturated: loop_lag = 2228ms, tasks = 358
// The thresholds above sit comfortably between the two states.

import React, { useEffect, useState } from 'react';
import { Activity, Cpu, Loader2, AlertTriangle } from 'lucide-react';
import api from '../../api';

const TONE = {
  healthy:  { dot: 'bg-emerald-500', ring: 'animate-ping bg-emerald-400 opacity-75', text: 'text-emerald-300', label: 'GREEN' },
  degraded: { dot: 'bg-amber-500',   ring: null,                                      text: 'text-amber-300',   label: 'AMBER' },
  saturated:{ dot: 'bg-red-500',     ring: 'animate-ping bg-red-400 opacity-75',      text: 'text-red-300',     label: 'RED' },
  unknown:  { dot: 'bg-slate-500',   ring: null,                                      text: 'text-slate-400',   label: '—'   },
};

const POLL_MS = 5000;

function classify(loopLagMs, taskCount) {
  if (loopLagMs == null || taskCount == null) return 'unknown';
  if (loopLagMs >= 500 || taskCount >= 150) return 'saturated';
  if (loopLagMs >= 100 || taskCount >= 50)  return 'degraded';
  return 'healthy';
}

function fmtMs(v) {
  if (v == null) return '—';
  if (v >= 1000) return `${(v / 1000).toFixed(2)}s`;
  if (v >= 10)   return `${Math.round(v)}ms`;
  return `${v.toFixed(2)}ms`;
}

function fmtMb(v) {
  if (v == null) return '—';
  return `${Math.round(v)} MB`;
}

export const LoopHealthCapsule = () => {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await api.get('/admin/monitoring/runtime-info');
        if (!cancelled) { setData(res.data); setErr(null); }
      } catch (e) {
        if (!cancelled) setErr(e?.response?.data?.detail || e?.message || 'fetch failed');
      }
    };
    poll();
    const t = setInterval(poll, POLL_MS);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  const lag   = data?.asyncio_loop_lag_ms;
  const tasks = data?.asyncio_task_count;
  const rss   = data?.memory_rss_mb;
  const fds   = data?.num_fds;
  const poolPct = data?.pg_pool_utilization_pct;
  const poolWait = data?.pg_pool_wait_count;
  const verdict = err ? 'unknown' : classify(lag, tasks);
  const tone = TONE[verdict];

  return (
    <div
      className="relative"
      data-testid="loop-health-capsule"
    >
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 rounded-full bg-slate-900/70 border border-slate-700 hover:border-slate-500 px-3 py-1.5 text-xs transition-colors"
        data-testid="loop-health-toggle"
      >
        <span className="relative inline-flex items-center justify-center w-2.5 h-2.5">
          {tone.ring && <span className={`absolute inline-flex h-full w-full rounded-full ${tone.ring}`}></span>}
          <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${tone.dot}`}></span>
        </span>
        <Cpu className="w-3.5 h-3.5 text-slate-300" />
        <span className="text-slate-300">Loop</span>
        <span
          className={`font-semibold tabular-nums ${tone.text}`}
          data-testid="loop-health-lag"
        >
          {err ? 'err' : fmtMs(lag)}
        </span>
        {verdict === 'saturated' && (
          <AlertTriangle className="w-3.5 h-3.5 text-red-400 ml-0.5" />
        )}
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-1.5 w-72 z-50 rounded-lg border border-slate-700 bg-slate-900 shadow-xl p-3 text-xs"
          data-testid="loop-health-flyout"
        >
          {err ? (
            <div className="text-red-400 text-[11px]">
              <strong>Fetch error:</strong><br />{err}
            </div>
          ) : !data ? (
            <div className="flex items-center gap-2 text-slate-400">
              <Loader2 className="w-3 h-3 animate-spin" /> Loading runtime…
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-1.5">
                  <Activity className="w-3.5 h-3.5 text-slate-300" />
                  <span className="text-slate-200 font-semibold">Event Loop Health</span>
                </div>
                <span
                  className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${tone.text} bg-slate-800`}
                  data-testid="loop-health-verdict"
                >
                  {tone.label}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-y-1.5 gap-x-3 text-slate-400">
                <span>Loop lag</span>
                <span className={`text-right tabular-nums ${tone.text}`} data-testid="loop-flyout-lag">
                  {fmtMs(lag)}
                </span>

                <span>Tasks</span>
                <span className="text-right tabular-nums text-slate-200" data-testid="loop-flyout-tasks">
                  {tasks ?? '—'}
                </span>

                <span>RSS</span>
                <span className="text-right tabular-nums text-slate-200">{fmtMb(rss)}</span>

                <span>FDs</span>
                <span className="text-right tabular-nums text-slate-200">{fds ?? '—'}</span>

                <span>PG pool</span>
                <span className="text-right tabular-nums text-slate-200">
                  {poolPct == null ? '—' : `${poolPct}%`}
                  {poolWait > 0 ? (
                    <span className="text-amber-400 ml-1">wait={poolWait}</span>
                  ) : null}
                </span>

                <span>Workers</span>
                <span className="text-right tabular-nums text-slate-200">{data?.workers ?? '—'}</span>
              </div>

              {verdict === 'saturated' && (
                <div className="mt-2 pt-2 border-t border-slate-700 text-[10px] text-red-300 leading-snug">
                  <strong>Saturation detected.</strong> Loop lag &gt;= 500ms or task queue &gt;= 150.
                  Expect upstream 520s within seconds. Check worker count and CPU-sync hot paths.
                </div>
              )}
              {verdict === 'degraded' && (
                <div className="mt-2 pt-2 border-t border-slate-700 text-[10px] text-amber-300 leading-snug">
                  <strong>Loop pressure rising.</strong> Not yet impacting users but trending toward saturation.
                </div>
              )}

              <div className="mt-2 pt-2 border-t border-slate-700 text-[10px] text-slate-500">
                Polled every {POLL_MS / 1000}s · source <code className="text-slate-400">/admin/monitoring/runtime-info</code>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default LoopHealthCapsule;
