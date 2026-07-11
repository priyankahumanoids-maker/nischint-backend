import React from 'react';
import { Activity, Database, Wifi, WifiOff, Server, BarChart3 } from 'lucide-react';

const MetricRow = ({ label, value, color = 'slate' }) => (
  <div className="flex items-center justify-between py-1.5">
    <span className="text-[11px] text-slate-500">{label}</span>
    <span className={`text-[11px] font-medium text-${color}-400`}>{value}</span>
  </div>
);

export const SystemMetrics = ({ metrics }) => {
  const db = metrics?.database || {};
  const redis = metrics?.redis || {};
  const ph = metrics?.platform_health || {};
  const queues = metrics?.queues || {};

  const formatMs = (v) => v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${Math.round(v)}ms`;
  const poolPct = db.pool_size ? Math.round((db.checked_out || 0) / db.pool_size * 100) : 0;

  return (
    <div className="bg-slate-800/40 rounded-lg border border-slate-700/50 flex flex-col h-full" data-testid="cc-system-metrics">
      <div className="px-4 py-3 border-b border-slate-700/50 flex items-center gap-2 shrink-0">
        <Server className="w-4 h-4 text-slate-400" />
        <h3 className="text-sm font-semibold text-white">System Metrics</h3>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {/* API Performance */}
        <div>
          <div className="flex items-center gap-1.5 mb-1">
            <Activity className="w-3 h-3 text-teal-400" />
            <span className="text-[10px] uppercase tracking-wider text-teal-400 font-semibold">API</span>
          </div>
          <MetricRow label="Latency p50" value={formatMs(ph.api_latency_p50_ms || 0)} color="teal" />
          <MetricRow label="Latency p95" value={formatMs(ph.api_latency_p95_ms || 0)} color={ph.api_latency_p95_ms > 2000 ? 'red' : 'teal'} />
          <MetricRow label="Requests" value={ph.total_requests || 0} color="slate" />
          <MetricRow label="Error Rate" value={`${ph.error_rate_pct || 0}%`} color={ph.error_rate_pct > 5 ? 'red' : 'emerald'} />
        </div>

        {/* Database */}
        <div>
          <div className="flex items-center gap-1.5 mb-1">
            <Database className="w-3 h-3 text-blue-400" />
            <span className="text-[10px] uppercase tracking-wider text-blue-400 font-semibold">Database</span>
          </div>
          <MetricRow label="Pool Usage" value={`${db.checked_out || 0}/${db.pool_size || 20}`} color={poolPct > 80 ? 'red' : 'blue'} />
          <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden mt-1 mb-1">
            <div className={`h-full rounded-full transition-all ${poolPct > 80 ? 'bg-red-500' : 'bg-blue-500'}`}
              style={{ width: `${Math.min(100, poolPct)}%` }} />
          </div>
          <MetricRow label="Status" value={db.status || 'unknown'} color={db.status === 'healthy' ? 'emerald' : 'red'} />
        </div>

        {/* Redis */}
        <div>
          <div className="flex items-center gap-1.5 mb-1">
            {redis.status === 'connected' ? <Wifi className="w-3 h-3 text-emerald-400" /> : <WifiOff className="w-3 h-3 text-slate-500" />}
            <span className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Redis</span>
          </div>
          <MetricRow label="Status" value={redis.status || 'disconnected'} color={redis.status === 'connected' ? 'emerald' : 'slate'} />
          {redis.used_memory_mb && <MetricRow label="Memory" value={`${redis.used_memory_mb}MB`} />}
        </div>

        {/* Queue Health */}
        {queues.incident && (
          <div>
            <div className="flex items-center gap-1.5 mb-1">
              <BarChart3 className="w-3 h-3 text-amber-400" />
              <span className="text-[10px] uppercase tracking-wider text-amber-400 font-semibold">Queues</span>
            </div>
            <MetricRow label="Incident" value={`${queues.incident?.depth || 0} pending`} color="amber" />
            <MetricRow label="AI Signal" value={`${queues.ai_signal?.depth || 0} pending`} />
            <MetricRow label="Notification" value={`${queues.notification?.depth || 0} pending`} />
          </div>
        )}
      </div>
    </div>
  );
};
