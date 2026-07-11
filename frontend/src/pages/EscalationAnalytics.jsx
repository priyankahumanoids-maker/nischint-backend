import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Separator } from '../components/ui/separator';
import { operatorApi } from '../api';
import { toast } from 'sonner';
import {
  Shield, AlertTriangle, Clock, CheckCircle, Loader2, RefreshCw,
  Activity, Zap, Users, TrendingUp, ShieldAlert, Gauge,
  Timer, Ban, Repeat, ArrowUpRight, Cpu, Heart
} from 'lucide-react';

const WINDOWS = [
  { value: '15', label: '15 min' },
  { value: '60', label: '1 hour' },
  { value: '360', label: '6 hours' },
  { value: '1440', label: '24 hours' },
  { value: '4320', label: '3 days' },
  { value: '10080', label: '7 days' },
];

export default function EscalationAnalytics() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [window, setWindow] = useState('1440');

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await operatorApi.getEscalationAnalytics(parseInt(window));
      setData(res.data);
    } catch {
      toast.error('Failed to load escalation analytics');
    } finally {
      setLoading(false);
    }
  }, [window]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const formatDuration = (seconds) => {
    if (seconds === null || seconds === undefined) return '—';
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    return `${(seconds / 3600).toFixed(1)}h`;
  };

  return (
    <div className="space-y-6" data-testid="escalation-analytics">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-900 flex items-center gap-2" data-testid="analytics-title">
            <Shield className="w-6 h-6 text-amber-600" />
            Safety Ops Dashboard
          </h2>
          <p className="text-sm text-slate-500 mt-1">Escalation performance, recovery quality, and alert fatigue metrics.</p>
        </div>
        <div className="flex items-center gap-3">
          <Select value={window} onValueChange={(v) => setWindow(v)}>
            <SelectTrigger className="w-[130px] h-9 text-xs" data-testid="analytics-window-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {WINDOWS.map(w => (
                <SelectItem key={w.value} value={w.value}>{w.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <button
            onClick={fetchData}
            disabled={loading}
            className="p-2 rounded-lg hover:bg-slate-100 transition-colors text-slate-500"
            data-testid="analytics-refresh"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {loading && !data ? (
        <div className="flex items-center justify-center py-24" data-testid="analytics-loading">
          <Loader2 className="w-8 h-8 animate-spin text-slate-300" />
        </div>
      ) : data ? (
        <>
          {/* Row 1: Volume KPIs */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4" data-testid="analytics-volume-row">
            <KpiCard
              icon={<AlertTriangle className="w-4 h-4" />}
              label="Total Incidents"
              value={data.total_incidents}
              accent="amber"
              testId="kpi-total-incidents"
            />
            <KpiCard
              icon={<ShieldAlert className="w-4 h-4" />}
              label="Open"
              value={data.open_incidents}
              accent={data.open_incidents > 0 ? 'red' : 'slate'}
              testId="kpi-open-incidents"
            />
            <KpiCard
              icon={<Zap className="w-4 h-4" />}
              label="Device Instability"
              value={data.device_instability?.total || 0}
              accent="violet"
              testId="kpi-instability-total"
            />
            <KpiCard
              icon={<Repeat className="w-4 h-4" />}
              label="Repeat Device Rate"
              value={`${data.device_instability?.repeat_device_rate_percent || 0}%`}
              accent={data.device_instability?.repeat_device_rate_percent > 30 ? 'orange' : 'slate'}
              testId="kpi-repeat-rate"
            />
          </div>

          {/* Row 2: Tier Distribution + Timing Metrics */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Tier Distribution */}
            <Card data-testid="analytics-tier-card">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold text-slate-600 flex items-center gap-2">
                  <TrendingUp className="w-4 h-4 text-amber-500" />
                  Escalation Tier Distribution
                </CardTitle>
              </CardHeader>
              <CardContent>
                <TierBar tiers={data.tier_counts} total={data.total_incidents} />
                <div className="grid grid-cols-3 gap-3 mt-4">
                  <TierStat tier="L1" count={data.tier_counts?.l1 || 0} color="amber" />
                  <TierStat tier="L2" count={data.tier_counts?.l2 || 0} color="orange" />
                  <TierStat tier="L3" count={data.tier_counts?.l3 || 0} color="red" />
                </div>
              </CardContent>
            </Card>

            {/* Timing Metrics */}
            <Card data-testid="analytics-timing-card">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold text-slate-600 flex items-center gap-2">
                  <Timer className="w-4 h-4 text-blue-500" />
                  Response Timings
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <TimingRow
                  label="Avg Time to Acknowledge"
                  value={formatDuration(data.timings?.avg_time_to_ack_seconds)}
                  icon={<CheckCircle className="w-3.5 h-3.5 text-blue-500" />}
                  testId="timing-ack"
                />
                <TimingRow
                  label="Avg Time to Resolve"
                  value={formatDuration(data.timings?.avg_time_to_resolve_seconds)}
                  icon={<Clock className="w-3.5 h-3.5 text-emerald-500" />}
                  testId="timing-resolve"
                />
                <TimingRow
                  label="Avg Time to First Escalation"
                  value={formatDuration(data.timings?.avg_time_to_first_escalation_seconds)}
                  icon={<ArrowUpRight className="w-3.5 h-3.5 text-amber-500" />}
                  testId="timing-first-esc"
                />
              </CardContent>
            </Card>
          </div>

          {/* Row 3: Recovery Quality + Noise Indicators */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Recovery Quality */}
            <Card data-testid="analytics-recovery-card">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold text-slate-600 flex items-center gap-2">
                  <Heart className="w-4 h-4 text-emerald-500" />
                  Recovery Quality
                </CardTitle>
              </CardHeader>
              <CardContent>
                <RecoveryBreakdown instability={data.device_instability} />
              </CardContent>
            </Card>

            {/* Noise / Fatigue */}
            <Card data-testid="analytics-noise-card">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold text-slate-600 flex items-center gap-2">
                  <Ban className="w-4 h-4 text-slate-500" />
                  Alert Fatigue Indicators
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center justify-between" data-testid="noise-cooldown-blocks">
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded-lg bg-slate-100 flex items-center justify-center">
                      <Ban className="w-4 h-4 text-slate-500" />
                    </div>
                    <div>
                      <p className="text-xs text-slate-500">Cooldown Blocks</p>
                      <p className="text-sm text-slate-400">Escalations prevented by cooldown</p>
                    </div>
                  </div>
                  <span className="text-2xl font-bold text-slate-800">{data.device_instability?.cooldown_blocks_count || 0}</span>
                </div>
                <Separator />
                <div className="flex items-center justify-between" data-testid="noise-repeat-rate">
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded-lg bg-orange-50 flex items-center justify-center">
                      <Repeat className="w-4 h-4 text-orange-500" />
                    </div>
                    <div>
                      <p className="text-xs text-slate-500">Repeat Device Rate</p>
                      <p className="text-sm text-slate-400">Devices with multiple instability events</p>
                    </div>
                  </div>
                  <span className={`text-2xl font-bold ${(data.device_instability?.repeat_device_rate_percent || 0) > 30 ? 'text-orange-600' : 'text-slate-800'}`}>
                    {data.device_instability?.repeat_device_rate_percent || 0}%
                  </span>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Row 4: Top Devices */}
          <Card data-testid="analytics-top-devices-card">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold text-slate-600 flex items-center gap-2">
                <Cpu className="w-4 h-4 text-red-500" />
                Top Devices by Instability
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {(data.top_devices_by_instability || []).length === 0 ? (
                <div className="flex items-center justify-center py-10 text-sm text-slate-400" data-testid="top-devices-empty">
                  No instability events in this window
                </div>
              ) : (
                <Table data-testid="top-devices-table">
                  <TableHeader>
                    <TableRow className="bg-slate-50">
                      <TableHead className="text-[10px] uppercase tracking-wider font-semibold">Device</TableHead>
                      <TableHead className="text-[10px] uppercase tracking-wider font-semibold">Senior</TableHead>
                      <TableHead className="text-[10px] uppercase tracking-wider font-semibold">Guardian</TableHead>
                      <TableHead className="text-[10px] uppercase tracking-wider font-semibold text-center">Incidents</TableHead>
                      <TableHead className="text-[10px] uppercase tracking-wider font-semibold text-center">Avg Score</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.top_devices_by_instability.map((d, i) => (
                      <TableRow key={i} data-testid={`top-device-row-${i}`}>
                        <TableCell className="font-mono text-xs text-slate-700">{d.device_identifier}</TableCell>
                        <TableCell className="text-sm text-slate-600">{d.senior_name || '—'}</TableCell>
                        <TableCell className="text-sm text-slate-500">{d.guardian_name || '—'}</TableCell>
                        <TableCell className="text-center">
                          <Badge variant="outline" className={`text-xs ${d.instability_count >= 3 ? 'border-red-300 text-red-700 bg-red-50' : 'border-slate-200'}`}>
                            {d.instability_count}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-center">
                          <ScoreBadge score={d.avg_score} />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}

// ── Sub-components ──

function KpiCard({ icon, label, value, accent, testId }) {
  const colors = {
    amber: 'bg-amber-50 text-amber-600',
    red: 'bg-red-50 text-red-600',
    violet: 'bg-violet-50 text-violet-600',
    orange: 'bg-orange-50 text-orange-600',
    slate: 'bg-slate-50 text-slate-500',
  };
  const iconBg = colors[accent] || colors.slate;

  return (
    <Card className="border border-slate-100" data-testid={testId}>
      <CardContent className="p-4">
        <div className="flex items-center gap-2 mb-2">
          <div className={`w-7 h-7 rounded-lg flex items-center justify-center ${iconBg}`}>{icon}</div>
          <span className="text-[10px] uppercase tracking-wider font-semibold text-slate-400">{label}</span>
        </div>
        <p className="text-3xl font-bold text-slate-900">{value}</p>
      </CardContent>
    </Card>
  );
}

function TierBar({ tiers, total }) {
  if (!tiers || total === 0) {
    return <div className="h-6 rounded-full bg-slate-100 w-full" data-testid="tier-bar-empty" />;
  }
  const l1p = (tiers.l1 / total * 100) || 0;
  const l2p = (tiers.l2 / total * 100) || 0;
  const l3p = (tiers.l3 / total * 100) || 0;

  return (
    <div className="flex h-6 rounded-full overflow-hidden bg-slate-100" data-testid="tier-bar">
      {l1p > 0 && <div className="bg-amber-400 transition-all" style={{ width: `${l1p}%` }} data-testid="tier-bar-l1" />}
      {l2p > 0 && <div className="bg-orange-400 transition-all" style={{ width: `${l2p}%` }} data-testid="tier-bar-l2" />}
      {l3p > 0 && <div className="bg-red-500 transition-all" style={{ width: `${l3p}%` }} data-testid="tier-bar-l3" />}
    </div>
  );
}

function TierStat({ tier, count, color }) {
  const colors = { amber: 'bg-amber-400', orange: 'bg-orange-400', red: 'bg-red-500' };
  return (
    <div className="flex items-center gap-2" data-testid={`tier-stat-${tier.toLowerCase()}`}>
      <span className={`w-3 h-3 rounded-sm ${colors[color]}`} />
      <span className="text-xs text-slate-500">{tier}</span>
      <span className="text-sm font-bold text-slate-800 ml-auto">{count}</span>
    </div>
  );
}

function TimingRow({ label, value, icon, testId }) {
  return (
    <div className="flex items-center justify-between" data-testid={testId}>
      <div className="flex items-center gap-2">
        {icon}
        <span className="text-sm text-slate-600">{label}</span>
      </div>
      <span className={`text-lg font-bold ${value === '—' ? 'text-slate-300' : 'text-slate-800'}`}>{value}</span>
    </div>
  );
}

function RecoveryBreakdown({ instability }) {
  if (!instability) return null;
  const { auto_recovered, manual_resolved, recovery_paths, total } = instability;
  const autoPercent = total > 0 ? Math.round(auto_recovered / total * 100) : 0;
  const manualPercent = total > 0 ? Math.round(manual_resolved / total * 100) : 0;

  return (
    <div className="space-y-4">
      {/* Auto vs Manual bar */}
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs text-slate-500">
          <span>Auto-recovered: {auto_recovered}</span>
          <span>Manual: {manual_resolved}</span>
        </div>
        <div className="flex h-4 rounded-full overflow-hidden bg-slate-100" data-testid="recovery-bar">
          {autoPercent > 0 && (
            <div className="bg-emerald-400 transition-all flex items-center justify-center text-[9px] font-bold text-white"
              style={{ width: `${autoPercent}%` }} data-testid="recovery-bar-auto">
              {autoPercent > 15 ? `${autoPercent}%` : ''}
            </div>
          )}
          {manualPercent > 0 && (
            <div className="bg-blue-400 transition-all flex items-center justify-center text-[9px] font-bold text-white"
              style={{ width: `${manualPercent}%` }} data-testid="recovery-bar-manual">
              {manualPercent > 15 ? `${manualPercent}%` : ''}
            </div>
          )}
        </div>
        <div className="flex items-center gap-4 text-[10px] text-slate-400">
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-emerald-400" /> Auto-recovered</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-blue-400" /> Manual</span>
        </div>
      </div>

      <Separator />

      {/* Recovery paths */}
      <div className="space-y-2" data-testid="recovery-paths">
        <p className="text-[10px] font-bold tracking-[0.15em] text-slate-400 uppercase">Recovery Paths</p>
        <div className="grid grid-cols-2 gap-3">
          <div className="p-3 rounded-lg bg-slate-50 border border-slate-100" data-testid="recovery-path-a">
            <p className="text-xs text-slate-500">Case A</p>
            <p className="text-[10px] text-slate-400">No anomaly in window</p>
            <p className="text-xl font-bold text-slate-800 mt-1">{recovery_paths?.case_a_no_anomaly_window || 0}</p>
          </div>
          <div className="p-3 rounded-lg bg-slate-50 border border-slate-100" data-testid="recovery-path-b">
            <p className="text-xs text-slate-500">Case B</p>
            <p className="text-[10px] text-slate-400">Clear cycles below hysteresis</p>
            <p className="text-xl font-bold text-slate-800 mt-1">{recovery_paths?.case_b_clear_cycles_below_hysteresis || 0}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function ScoreBadge({ score }) {
  if (score === null || score === undefined || score === 0) return <span className="text-xs text-slate-400">—</span>;
  let cls = 'border-slate-200 text-slate-600';
  if (score >= 75) cls = 'border-red-300 text-red-700 bg-red-50';
  else if (score >= 60) cls = 'border-orange-300 text-orange-700 bg-orange-50';
  return <Badge variant="outline" className={`text-xs ${cls}`}>{score}</Badge>;
}
