import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  Activity, AlertTriangle, BarChart3, Database, Cpu,
  Radio, Shield, PhoneCall, Bell, Loader2, RefreshCw, Clock,
  TrendingUp, Server, Wifi, WifiOff,
} from 'lucide-react';
import api from '../api';

const StatCard = ({ label, value, icon: Icon, color = 'teal', sub }) => (
  <div className="bg-white rounded-lg border border-slate-200 p-4 flex items-start gap-3" data-testid={`stat-${label.toLowerCase().replace(/\s+/g, '-')}`}>
    <div className={`w-9 h-9 rounded-lg bg-${color}-50 flex items-center justify-center shrink-0`}>
      <Icon className={`w-4.5 h-4.5 text-${color}-500`} />
    </div>
    <div className="min-w-0">
      <p className="text-xs text-slate-500 truncate">{label}</p>
      <p className="text-xl font-bold text-slate-800">{value}</p>
      {sub && <p className="text-xs text-slate-400 mt-0.5">{sub}</p>}
    </div>
  </div>
);

const AlertRow = ({ alert }) => {
  const sevColors = {
    critical: 'bg-red-100 text-red-700 border-red-200',
    high: 'bg-amber-100 text-amber-700 border-amber-200',
    medium: 'bg-yellow-100 text-yellow-700 border-yellow-200',
    low: 'bg-slate-100 text-slate-600 border-slate-200',
  };
  return (
    <div className="flex items-center justify-between py-2 px-3 rounded-md bg-slate-50 border border-slate-100" data-testid="monitoring-alert-row">
      <div className="flex items-center gap-2 min-w-0">
        <AlertTriangle className="w-3.5 h-3.5 text-amber-500 shrink-0" />
        <span className="text-sm text-slate-700 truncate">{alert.message}</span>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <Badge className={`text-[10px] px-1.5 py-0 ${sevColors[alert.severity] || sevColors.low}`}>{alert.severity}</Badge>
        <span className="text-[10px] text-slate-400">{new Date(alert.timestamp).toLocaleTimeString()}</span>
      </div>
    </div>
  );
};

export const MonitoringTab = () => {
  const [metrics, setMetrics] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    try {
      const [mRes, aRes] = await Promise.all([
        api.get('/admin/monitoring/metrics'),
        api.get('/admin/monitoring/alerts'),
      ]);
      setMetrics(mRes.data);
      setAlerts(aRes.data.alerts || []);
    } catch { /* fail silently */ }
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Auto-refresh every 15s
  useEffect(() => {
    const iv = setInterval(() => fetchData(true), 15000);
    return () => clearInterval(iv);
  }, [fetchData]);

  if (loading) return <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin text-teal-500" /></div>;
  if (!metrics) return <p className="text-sm text-slate-400 text-center py-8">Failed to load monitoring data</p>;

  const ph = metrics.platform_health || {};
  const em1h = metrics.emergency_activity?.last_1h || {};
  const em24h = metrics.emergency_activity?.last_24h || {};
  const ai = metrics.ai_safety || {};
  const db = metrics.database || {};
  const redis = metrics.redis || {};
  const gs = metrics.guardian_sessions || {};

  const formatMs = (v) => v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${Math.round(v)}ms`;
  const uptimeStr = () => {
    const s = metrics.uptime_seconds || 0;
    if (s < 3600) return `${Math.floor(s / 60)}m`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
    return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
  };

  return (
    <div className="space-y-6" data-testid="monitoring-tab">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-800">Platform Monitoring</h2>
          <p className="text-xs text-slate-400">Live metrics — auto-refreshes every 15s</p>
        </div>
        <Button size="sm" variant="outline" onClick={() => fetchData(true)} disabled={refreshing} data-testid="refresh-monitoring">
          <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${refreshing ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      {/* Platform Health */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold flex items-center gap-2"><Activity className="w-4 h-4 text-teal-500" /> Platform Health</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard label="API Latency p50" value={formatMs(ph.api_latency_p50_ms)} icon={TrendingUp} color="blue" />
            <StatCard label="API Latency p95" value={formatMs(ph.api_latency_p95_ms)} icon={TrendingUp} color="amber" />
            <StatCard label="Total Requests" value={ph.total_requests || 0} icon={BarChart3} color="teal" />
            <StatCard label="Error Rate" value={`${ph.error_rate_pct || 0}%`} icon={AlertTriangle} color={ph.error_rate_pct > 5 ? 'red' : 'emerald'} sub={`${ph.total_errors_5xx || 0} errors`} />
          </div>
          {/* Top endpoints */}
          {ph.top_endpoints?.length > 0 && (
            <div className="mt-4">
              <p className="text-xs font-medium text-slate-500 mb-2">Top Endpoints by Latency</p>
              <div className="space-y-1.5">
                {ph.top_endpoints.map((ep, i) => (
                  <div key={i} className="flex items-center justify-between text-xs py-1.5 px-2 rounded bg-slate-50" data-testid={`endpoint-row-${i}`}>
                    <span className="text-slate-700 font-mono truncate mr-3">{ep.endpoint}</span>
                    <div className="flex gap-3 shrink-0 text-slate-500">
                      <span>p50: {formatMs(ep.p50_ms)}</span>
                      <span>p95: <span className={ep.p95_ms > 2000 ? 'text-red-600 font-medium' : ''}>{formatMs(ep.p95_ms)}</span></span>
                      <span>{ep.requests} req</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Emergency Activity + AI Safety */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold flex items-center gap-2"><Shield className="w-4 h-4 text-red-500" /> Emergency Activity</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-3 mb-3">
              <StatCard label="SOS (1h)" value={em1h.sos_triggers || 0} icon={Radio} color="red" sub={`${em24h.sos_triggers || 0} in 24h`} />
              <StatCard label="Alerts (1h)" value={em1h.guardian_alerts || 0} icon={AlertTriangle} color="amber" sub={`${em24h.guardian_alerts || 0} in 24h`} />
            </div>
            <div className="grid grid-cols-3 gap-2">
              <div className="text-center p-2 rounded bg-slate-50">
                <p className="text-lg font-bold text-slate-700">{em1h.escalations || 0}</p>
                <p className="text-[10px] text-slate-500">Escalations</p>
              </div>
              <div className="text-center p-2 rounded bg-slate-50">
                <PhoneCall className="w-3.5 h-3.5 mx-auto text-slate-400 mb-1" />
                <p className="text-lg font-bold text-slate-700">{em1h.fake_calls || 0}</p>
                <p className="text-[10px] text-slate-500">Fake Calls</p>
              </div>
              <div className="text-center p-2 rounded bg-slate-50">
                <Bell className="w-3.5 h-3.5 mx-auto text-slate-400 mb-1" />
                <p className="text-lg font-bold text-slate-700">{em1h.fake_notifications || 0}</p>
                <p className="text-[10px] text-slate-500">Fake Notifs</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold flex items-center gap-2"><Cpu className="w-4 h-4 text-violet-500" /> AI Safety Brain</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 gap-3">
              <StatCard label="Risk Spikes" value={ai.risk_spikes || 0} icon={TrendingUp} color="red" />
              <StatCard label="Heatmap" value={ai.heatmap_alerts || 0} icon={Activity} color="amber" />
              <StatCard label="Anomalies" value={ai.behavior_anomalies || 0} icon={AlertTriangle} color="violet" />
            </div>
            <div className="mt-3 p-3 rounded bg-slate-50 flex items-center gap-3">
              <Shield className="w-5 h-5 text-teal-500" />
              <div>
                <p className="text-sm font-medium text-slate-700">Active Guardian Sessions</p>
                <p className="text-xl font-bold text-teal-600">{gs.active || 0}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Database + Redis + Uptime */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold flex items-center gap-2"><Database className="w-4 h-4 text-blue-500" /> Database Pool</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">Pool Size</span>
                <span className="font-medium text-slate-700">{db.pool_size || '-'}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">Checked Out</span>
                <span className={`font-medium ${(db.checked_out || 0) >= (db.pool_size || 20) ? 'text-red-600' : 'text-slate-700'}`}>{db.checked_out || 0}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">Available</span>
                <span className="font-medium text-emerald-600">{db.checked_in || 0}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">Overflow</span>
                <span className="font-medium text-slate-700">{db.overflow || 0} / {db.max_overflow || '-'}</span>
              </div>
              {/* Pool usage bar */}
              <div className="mt-2">
                <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                  <div className={`h-full rounded-full transition-all ${db.status === 'healthy' ? 'bg-emerald-500' : 'bg-amber-500'}`}
                    style={{ width: `${Math.min(100, ((db.checked_out || 0) / (db.pool_size || 20)) * 100)}%` }} />
                </div>
                <Badge className={`mt-1.5 text-[10px] ${db.status === 'healthy' ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}>{db.status || 'unknown'}</Badge>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold flex items-center gap-2">
              {redis.status === 'connected' ? <Wifi className="w-4 h-4 text-emerald-500" /> : <WifiOff className="w-4 h-4 text-slate-400" />}
              Redis
            </CardTitle>
          </CardHeader>
          <CardContent>
            {redis.status === 'connected' ? (
              <div className="space-y-2">
                <div className="flex justify-between text-xs"><span className="text-slate-500">Version</span><span className="font-medium">{redis.redis_version}</span></div>
                <div className="flex justify-between text-xs"><span className="text-slate-500">Memory</span><span className="font-medium">{redis.used_memory_mb}MB</span></div>
                <div className="flex justify-between text-xs"><span className="text-slate-500">Peak Memory</span><span className="font-medium">{redis.peak_memory_mb}MB</span></div>
                <div className="flex justify-between text-xs"><span className="text-slate-500">Clients</span><span className="font-medium">{redis.connected_clients}</span></div>
                <Badge className="mt-1.5 text-[10px] bg-emerald-50 text-emerald-700">Connected</Badge>
              </div>
            ) : (
              <div className="text-center py-4">
                <WifiOff className="w-8 h-8 text-slate-300 mx-auto mb-2" />
                <p className="text-xs text-slate-400">Redis not available</p>
                <Badge className="mt-1.5 text-[10px] bg-slate-100 text-slate-500">{redis.status || 'disconnected'}</Badge>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold flex items-center gap-2"><Server className="w-4 h-4 text-slate-500" /> System</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              <div className="flex justify-between text-xs"><span className="text-slate-500">Uptime</span><span className="font-medium text-slate-700">{uptimeStr()}</span></div>
              <div className="flex items-center gap-2">
                <Clock className="w-3.5 h-3.5 text-slate-400" />
                <span className="text-xs text-slate-500">{new Date(metrics.timestamp).toLocaleString()}</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Recent Alerts */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold flex items-center gap-2"><AlertTriangle className="w-4 h-4 text-amber-500" /> Recent Alerts ({alerts.length})</CardTitle>
        </CardHeader>
        <CardContent>
          {alerts.length === 0 ? (
            <p className="text-xs text-slate-400 text-center py-4">No alerts recorded</p>
          ) : (
            <div className="space-y-1.5 max-h-64 overflow-y-auto">
              {alerts.map((a, i) => <AlertRow key={i} alert={a} />)}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
