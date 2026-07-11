import React, { useState, useEffect } from 'react';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import api from '../api';
import { operatorApi } from '../api';
import { toast } from 'sonner';
import {
  Activity, AlertTriangle, Loader2, RefreshCw, Zap, Wifi,
} from 'lucide-react';
import { MetricTrendsCard } from '../components/MetricSparkline';
import BehaviorCard from '../components/BehaviorCard';
import { DigitalTwinCard } from '../components/DigitalTwinCard';
import { PredictiveRiskCard } from '../components/PredictiveRiskCard';
import { RiskForecastTimeline } from '../components/RiskForecastTimeline';
import { DeviceSafetyScore } from '../components/DeviceSafetyScore';
import { TwinEvolutionTimeline } from '../components/TwinEvolutionTimeline';
import { LifePatternHeatmap } from '../components/LifePatternHeatmap';
import { DeviceEnvironmentRisk } from '../components/DeviceEnvironmentRisk';
import { DependentVitalsCard } from '../components/DependentVitalsCard';

const DeviceHealthPage = () => {
  const [healthData, setHealthData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [sortBy, setSortBy] = useState('reliability_score');
  const [sortDir, setSortDir] = useState('asc');
  const [anomalyData, setAnomalyData] = useState({ anomalies: [], baselines: [] });
  const [selectedDeviceId, setSelectedDeviceId] = useState(null);
  // HC-02 — operator-side dependent picker for vitals-by-device
  const [dependents, setDependents] = useState([]);
  const [selectedDependentId, setSelectedDependentId] = useState('');
  const [dependentsLoading, setDependentsLoading] = useState(false);

  const fetchHealth = async () => {
    setLoading(true);
    try {
      const [healthRes, anomalyRes] = await Promise.all([
        api.get('/operator/device-health?window_hours=24'),
        operatorApi.getDeviceAnomalies(24),
      ]);
      setHealthData(healthRes.data);
      setAnomalyData(anomalyRes.data);
    } catch {
      toast.error('Failed to load device health data');
    } finally {
      setLoading(false);
    }
  };

  const fetchDependents = async () => {
    setDependentsLoading(true);
    try {
      const res = await api.get('/health-signals/admin/dependents', { params: { hours: 168 } });
      const list = res.data?.dependents || [];
      setDependents(list);
      // Auto-select the most-recently-active dependent so the card is
      // not empty on first render. Operator can switch via the picker.
      if (list.length > 0 && !selectedDependentId) {
        setSelectedDependentId(list[0].user_id);
      }
    } catch {
      // Silent — HC-02 picker degrades to empty state without toasting.
    } finally {
      setDependentsLoading(false);
    }
  };

  useEffect(() => { fetchHealth(); fetchDependents(); }, []);

  const sorted = [...healthData].sort((a, b) => {
    const av = a[sortBy] ?? 0;
    const bv = b[sortBy] ?? 0;
    return sortDir === 'asc' ? av - bv : bv - av;
  });

  const handleSort = (col) => {
    if (sortBy === col) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortBy(col);
      setSortDir('asc');
    }
  };

  const reliabilityBadge = (score) => {
    if (score >= 80) return <Badge className="bg-green-100 text-green-700" data-testid="reliability-healthy">{score}</Badge>;
    if (score >= 60) return <Badge className="bg-yellow-100 text-yellow-700" data-testid="reliability-warning">{score}</Badge>;
    return <Badge className="bg-red-100 text-red-700" data-testid="reliability-at-risk">{score}</Badge>;
  };

  const SortHeader = ({ col, label }) => (
    <TableHead
      className="cursor-pointer select-none hover:text-slate-700"
      onClick={() => handleSort(col)}
      data-testid={`sort-${col}`}
    >
      <span className="flex items-center gap-1">
        {label}
        {sortBy === col && <span className="text-xs">{sortDir === 'asc' ? '\u25B2' : '\u25BC'}</span>}
      </span>
    </TableHead>
  );

  return (
    <div className="space-y-6" data-testid="op-device-health-page">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-slate-800">Device Health Overview</h2>
        <Button variant="outline" size="sm" onClick={fetchHealth} disabled={loading} data-testid="refresh-device-health">
          <RefreshCw className={`w-4 h-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Device</TableHead>
                <TableHead>Senior</TableHead>
                <TableHead>Guardian</TableHead>
                <TableHead>Status</TableHead>
                <SortHeader col="uptime_percent" label="Uptime %" />
                <SortHeader col="battery_latest" label="Battery" />
                <SortHeader col="offline_count" label="Offline" />
                <SortHeader col="reliability_score" label="Reliability" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow><TableCell colSpan={8} className="text-center py-8"><Loader2 className="w-5 h-5 animate-spin mx-auto" /></TableCell></TableRow>
              ) : sorted.length === 0 ? (
                <TableRow><TableCell colSpan={8} className="text-center text-slate-400 py-8">No devices found</TableCell></TableRow>
              ) : sorted.map((d) => (
                <React.Fragment key={d.device_id}>
                <TableRow
                  className={`cursor-pointer transition-colors hover:bg-slate-50 ${selectedDeviceId === d.device_id ? 'bg-slate-50' : ''}`}
                  onClick={() => setSelectedDeviceId(selectedDeviceId === d.device_id ? null : d.device_id)}
                  data-testid={`op-device-row-${d.device_id}`}
                >
                  <TableCell className="font-mono text-sm font-medium">{d.device_identifier}</TableCell>
                  <TableCell>{d.senior_name}</TableCell>
                  <TableCell className="text-sm text-slate-500">{d.guardian_name}</TableCell>
                  <TableCell>
                    <Badge className={d.status === 'online' ? 'bg-green-100 text-green-700' : d.status === 'offline' ? 'bg-red-100 text-red-700' : 'bg-slate-100 text-slate-600'}>
                      {d.status}
                    </Badge>
                  </TableCell>
                  <TableCell className={d.uptime_percent >= 80 ? 'text-green-600 font-medium' : d.uptime_percent >= 60 ? 'text-yellow-600' : 'text-red-600 font-medium'}>
                    {d.uptime_percent}%
                  </TableCell>
                  <TableCell>
                    {d.battery_latest !== null && d.battery_latest !== undefined ? (
                      <span className={d.battery_latest >= 60 ? 'text-green-600' : d.battery_latest >= 20 ? 'text-yellow-600' : 'text-red-600 font-bold'}>
                        {d.battery_latest}%
                      </span>
                    ) : <span className="text-slate-400">N/A</span>}
                  </TableCell>
                  <TableCell>
                    {d.offline_count > 0 ? (
                      <span className="text-red-600 font-medium">{d.offline_count}</span>
                    ) : <span className="text-slate-400">0</span>}
                  </TableCell>
                  <TableCell>{reliabilityBadge(d.reliability_score)}</TableCell>
                </TableRow>
                {selectedDeviceId === d.device_id && (
                  <TableRow>
                    <TableCell colSpan={8} className="bg-slate-50/50 p-4" data-testid={`device-trends-${d.device_id}`}>
                      <div className="mb-4">
                        <DeviceSafetyScore deviceId={d.device_id} />
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <MetricTrendsCard deviceId={d.device_id} windowMinutes={1440} threshold={60} />
                        <BehaviorCard deviceId={d.device_id} />
                      </div>
                      <div className="mt-4">
                        <DigitalTwinCard deviceId={d.device_id} />
                      </div>
                      <div className="mt-4">
                        <PredictiveRiskCard deviceId={d.device_id} />
                      </div>
                      <div className="mt-4">
                        <RiskForecastTimeline deviceId={d.device_id} />
                      </div>
                      <div className="mt-4">
                        <TwinEvolutionTimeline deviceId={d.device_id} />
                      </div>
                      <div className="mt-4">
                        <LifePatternHeatmap deviceId={d.device_id} />
                      </div>
                      <div className="mt-4">
                        <DeviceEnvironmentRisk deviceId={d.device_id} lat={d.latitude} lng={d.longitude} />
                      </div>
                    </TableCell>
                  </TableRow>
                )}
                </React.Fragment>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* HC-02 — Wearable Vitals by Device */}
      <Card data-testid="hc02-vitals-section">
        <CardContent className="p-6 space-y-4">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div>
              <h3 className="text-lg font-semibold text-slate-800 flex items-center gap-2">
                <Activity className="w-5 h-5 text-rose-500" />
                Wearable Vitals by Device (HC-02)
              </h3>
              <p className="text-xs text-slate-500 mt-0.5">
                Per-device HR / SpO₂ timelines for dependents that paired multiple wearables.
                Sourced from the <code className="text-[11px] bg-slate-100 px-1 rounded">health_signals_pg</code> mirror.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <label htmlFor="hc02-dependent-picker" className="text-xs text-slate-500">Dependent</label>
              <select
                id="hc02-dependent-picker"
                className="text-sm border border-slate-200 rounded px-2 py-1 bg-white max-w-[260px]"
                value={selectedDependentId}
                onChange={(e) => setSelectedDependentId(e.target.value)}
                disabled={dependentsLoading || dependents.length === 0}
                data-testid="hc02-dependent-picker"
              >
                {dependents.length === 0 ? (
                  <option value="">— no dependents with signals —</option>
                ) : (
                  <>
                    <option value="">— select dependent —</option>
                    {dependents.map((d) => (
                      <option key={d.user_id} value={d.user_id}>
                        {d.full_name || d.email || d.user_id.slice(0, 8)}
                        {' · '}
                        {d.device_count} dev · {d.sample_count} samples
                        {d.breach_count > 0 ? ` · ${d.breach_count} ⚠` : ''}
                      </option>
                    ))}
                  </>
                )}
              </select>
            </div>
          </div>

          <DependentVitalsCard
            dependentId={selectedDependentId}
            dependentName={
              dependents.find(d => d.user_id === selectedDependentId)?.full_name ||
              dependents.find(d => d.user_id === selectedDependentId)?.email ||
              null
            }
            hours={24}
          />
        </CardContent>
      </Card>

      {/* Battery Anomaly Intelligence Section */}
      <Card>
        <CardContent className="p-6 space-y-4">
          <h3 className="text-lg font-semibold text-slate-800 flex items-center gap-2" data-testid="anomaly-section-title">
            <AlertTriangle className="w-5 h-5 text-amber-500" />
            Battery Anomaly Intelligence
          </h3>

          {(() => {
            const batAnomalies = anomalyData.anomalies.filter(a => a.metric === 'battery_slope');
            const batBaselines = anomalyData.baselines.filter(b => b.metric === 'battery_slope');
            if (batBaselines.length === 0 && batAnomalies.length === 0) {
              return (
                <div className="text-center py-6" data-testid="anomaly-empty">
                  <p className="text-slate-400 text-sm">No battery baseline data yet. The system builds adaptive baselines from heartbeat telemetry every 5 minutes.</p>
                </div>
              );
            }
            return (
              <div className="space-y-4">
                {batAnomalies.length > 0 && (
                  <div className="space-y-2" data-testid="battery-anomaly-list">
                    <p className="text-sm font-medium text-red-600">Active Battery Anomalies ({batAnomalies.length})</p>
                    {batAnomalies.slice(0, 10).map((a, i) => (
                      <div key={i} className="flex items-center gap-3 p-3 rounded-lg border border-red-100 bg-red-50" data-testid={`battery-anomaly-item-${i}`}>
                        <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center shrink-0">
                          <span className="text-sm font-bold text-red-700" data-testid={`battery-anomaly-score-${i}`}>{a.score}</span>
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-slate-800">{a.device_identifier} — {a.senior_name}</p>
                          <p className="text-xs text-red-600">
                            Drop rate {a.reason_json?.current_slope?.toFixed(3)}%/min vs expected {a.reason_json?.expected_slope?.toFixed(3)}%/min
                          </p>
                        </div>
                        <span className="text-xs text-slate-400 shrink-0">{new Date(a.created_at).toLocaleString()}</span>
                      </div>
                    ))}
                  </div>
                )}
                {batAnomalies.length === 0 && batBaselines.length > 0 && (
                  <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 flex items-center gap-2" data-testid="battery-anomaly-clear">
                    <div className="w-2 h-2 rounded-full bg-emerald-500" />
                    <p className="text-sm text-emerald-800">All devices within normal battery behavior. {batBaselines.length} baselines active.</p>
                  </div>
                )}
                {batBaselines.length > 0 && (
                  <div data-testid="battery-baseline-summary">
                    <p className="text-sm font-medium text-slate-600 mb-2">Battery Slope Baselines ({batBaselines.length} devices)</p>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                      {batBaselines.slice(0, 6).map((b, i) => (
                        <div key={i} className="p-2 rounded border border-slate-100 bg-slate-50 text-xs" data-testid={`battery-baseline-item-${i}`}>
                          <p className="font-mono font-medium text-slate-700">{b.device_identifier}</p>
                          <p className="text-slate-500">
                            Expected: {b.expected_value?.toFixed(4)}%/min
                            <span className="text-slate-300 mx-1">|</span>
                            Band: [{b.lower_band?.toFixed(4)}, {b.upper_band?.toFixed(4)}]
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })()}
        </CardContent>
      </Card>

      {/* Signal Strength Anomaly Intelligence Section */}
      <Card>
        <CardContent className="p-6 space-y-4">
          <h3 className="text-lg font-semibold text-slate-800 flex items-center gap-2" data-testid="signal-anomaly-section-title">
            <Wifi className="w-5 h-5 text-blue-500" />
            Signal Strength Anomaly Intelligence
          </h3>

          {(() => {
            const sigAnomalies = anomalyData.anomalies.filter(a => a.metric === 'signal_strength');
            const sigBaselines = anomalyData.baselines.filter(b => b.metric === 'signal_strength');
            if (sigBaselines.length === 0 && sigAnomalies.length === 0) {
              return (
                <div className="text-center py-6" data-testid="signal-anomaly-empty">
                  <p className="text-slate-400 text-sm">No signal baseline data yet. Signal baselines are computed from a rolling 24-hour window of heartbeat telemetry.</p>
                </div>
              );
            }
            return (
              <div className="space-y-4">
                {sigAnomalies.length > 0 && (
                  <div className="space-y-2" data-testid="signal-anomaly-list">
                    <p className="text-sm font-medium text-red-600">Active Signal Anomalies ({sigAnomalies.length})</p>
                    {sigAnomalies.slice(0, 10).map((a, i) => (
                      <div key={i} className="flex items-center gap-3 p-3 rounded-lg border border-orange-100 bg-orange-50" data-testid={`signal-anomaly-item-${i}`}>
                        <div className="w-10 h-10 rounded-full bg-orange-100 flex items-center justify-center shrink-0">
                          <span className="text-sm font-bold text-orange-700" data-testid={`signal-anomaly-score-${i}`}>{a.score}</span>
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-slate-800">{a.device_identifier} — {a.senior_name}</p>
                          <p className="text-xs text-orange-600">
                            Signal {a.reason_json?.observed_mean?.toFixed(1)} dBm vs expected {a.reason_json?.expected_mean?.toFixed(1)} dBm
                            <span className="text-orange-400 mx-1">|</span>
                            {a.reason_json?.sigma_deviation?.toFixed(1)}σ deviation sustained {a.reason_json?.sustain_minutes} min
                          </p>
                        </div>
                        <span className="text-xs text-slate-400 shrink-0">{new Date(a.created_at).toLocaleString()}</span>
                      </div>
                    ))}
                  </div>
                )}
                {sigAnomalies.length === 0 && sigBaselines.length > 0 && (
                  <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 flex items-center gap-2" data-testid="signal-anomaly-clear">
                    <div className="w-2 h-2 rounded-full bg-emerald-500" />
                    <p className="text-sm text-emerald-800">Signal strength stable across fleet. {sigBaselines.length} signal baselines active.</p>
                  </div>
                )}
                {sigBaselines.length > 0 && (
                  <div data-testid="signal-baseline-summary">
                    <p className="text-sm font-medium text-slate-600 mb-2">Signal Strength Baselines ({sigBaselines.length} devices)</p>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                      {sigBaselines.slice(0, 6).map((b, i) => (
                        <div key={i} className="p-2 rounded border border-blue-50 bg-blue-50/50 text-xs" data-testid={`signal-baseline-item-${i}`}>
                          <p className="font-mono font-medium text-slate-700">{b.device_identifier}</p>
                          <p className="text-slate-500">
                            Expected: {b.expected_value?.toFixed(1)} dBm
                            <span className="text-slate-300 mx-1">|</span>
                            Band: [{b.lower_band?.toFixed(1)}, {b.upper_band?.toFixed(1)}]
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })()}
        </CardContent>
      </Card>

      {/* Multi-Metric Combined Anomaly Intelligence */}
      <Card>
        <CardContent className="p-6 space-y-4">
          <h3 className="text-lg font-semibold text-slate-800 flex items-center gap-2" data-testid="combined-anomaly-section-title">
            <Zap className="w-5 h-5 text-purple-500" />
            Multi-Metric Combined Intelligence
          </h3>

          {(() => {
            const combinedAnomalies = anomalyData.anomalies.filter(a => a.metric === 'multi_metric');
            if (combinedAnomalies.length === 0) {
              return (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 flex items-center gap-2" data-testid="combined-anomaly-clear">
                  <div className="w-2 h-2 rounded-full bg-emerald-500" />
                  <p className="text-sm text-emerald-800">No combined anomalies detected. Devices are within acceptable multi-metric thresholds.</p>
                </div>
              );
            }
            return (
              <div className="space-y-2" data-testid="combined-anomaly-list">
                <p className="text-sm font-medium text-purple-700">Active Combined Anomalies ({combinedAnomalies.length})</p>
                {combinedAnomalies.slice(0, 10).map((a, i) => {
                  const r = a.reason_json || {};
                  return (
                    <div key={i} className="flex items-center gap-3 p-3 rounded-lg border border-purple-100 bg-purple-50" data-testid={`combined-anomaly-item-${i}`}>
                      <div className="w-10 h-10 rounded-full bg-purple-100 flex items-center justify-center shrink-0">
                        <span className="text-sm font-bold text-purple-700" data-testid={`combined-anomaly-score-${i}`}>{a.score}</span>
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-slate-800">{a.device_identifier} — {a.senior_name}</p>
                        <p className="text-xs text-purple-600">
                          Battery: {r.battery_score?.toFixed(1)} × {r.weights?.battery}
                          <span className="text-purple-300 mx-1">+</span>
                          Signal: {r.signal_score?.toFixed(1)} × {r.weights?.signal}
                          {r.weights?.behavior > 0 && (
                            <>
                              <span className="text-purple-300 mx-1">+</span>
                              Behavior: {r.behavior_score?.toFixed(1) ?? '0.0'} × {r.weights?.behavior}
                            </>
                          )}
                          {r.correlation_flag && (
                            <span className="ml-1 px-1.5 py-0.5 bg-purple-200 text-purple-800 rounded text-[10px] font-semibold">
                              +{r.correlation_bonus} CORR ({r.active_metrics || 2}m)
                            </span>
                          )}
                          <span className="text-purple-300 mx-1">=</span>
                          <span className="font-semibold">{r.combined_score?.toFixed(1)}</span>
                        </p>
                      </div>
                      <span className="text-xs text-slate-400 shrink-0">{new Date(a.created_at).toLocaleString()}</span>
                    </div>
                  );
                })}
              </div>
            );
          })()}
        </CardContent>
      </Card>
    </div>
  );
};

export default DeviceHealthPage;
