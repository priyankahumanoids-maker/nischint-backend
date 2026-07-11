import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Switch } from '../components/ui/switch';
import { Separator } from '../components/ui/separator';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '../components/ui/sheet';
import { ScrollArea } from '../components/ui/scroll-area';
import api, { operatorApi } from '../api';
import { toast } from 'sonner';
import {
  FlaskConical, Radio, Cpu, Users, Loader2, Play, Eye,
  CheckCircle, AlertTriangle, Database, Clock, Hash, ChevronDown, ChevronUp,
  History, ChevronLeft, ChevronRight, FileJson, Calendar, User, Zap,
  GitCompare, Brain
} from 'lucide-react';
import { SimulationCompareTab } from './SimulationLab/SimulationCompareTab';
import { BehaviorScenarioTab } from './SimulationLab/BehaviorScenarioTab';
import { ForecastScenarioTab } from './SimulationLab/ForecastScenarioTab';

const PATTERN_PRESETS = {
  normal: {
    label: 'Normal Drain',
    battery: { start_value: 90, normal_rate_per_minute: -0.08, anomaly: null },
    signal: { start_value: -55, normal_rate_per_minute: -0.02, anomaly: null },
  },
  aggressive: {
    label: 'Aggressive Drain',
    battery: { start_value: 85, normal_rate_per_minute: -0.05, anomaly: { start_at_minute: 40, rate_per_minute: -3.0 } },
    signal: { start_value: -50, normal_rate_per_minute: -0.02, anomaly: { start_at_minute: 40, rate_per_minute: -4.0 } },
  },
  critical: {
    label: 'Critical Failure',
    battery: { start_value: 80, normal_rate_per_minute: -0.02, anomaly: { start_at_minute: 50, rate_per_minute: -8.0 } },
    signal: { start_value: -45, normal_rate_per_minute: -0.01, anomaly: { start_at_minute: 50, rate_per_minute: -10.0 } },
  },
};

const FLEET_STRATEGIES = {
  uniform_aggressive: {
    label: 'Uniform Aggressive',
    getPatterns: () => ({
      metric_patterns: [
        { metric: 'battery_level', ...PATTERN_PRESETS.aggressive.battery },
        { metric: 'signal_strength', ...PATTERN_PRESETS.aggressive.signal },
      ],
    }),
  },
  mixed: {
    label: 'Mixed (Varied per device)',
    getPatterns: (index) => {
      const presets = ['normal', 'aggressive', 'critical'];
      const key = presets[index % presets.length];
      return {
        metric_patterns: [
          { metric: 'battery_level', ...PATTERN_PRESETS[key].battery },
          { metric: 'signal_strength', ...PATTERN_PRESETS[key].signal },
        ],
      };
    },
  },
};

export default function SimulationLab() {
  const [activeTab, setActiveTab] = useState('simulate');
  const [mode, setMode] = useState('single');
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [expandedDevices, setExpandedDevices] = useState(false);

  // Single device form state
  const [selectedDevice, setSelectedDevice] = useState('');
  const [patternType, setPatternType] = useState('aggressive');
  const [duration, setDuration] = useState(60);
  const [interval, setInterval_] = useState(60);
  const [randomSeed, setRandomSeed] = useState('');
  const [includeSignal, setIncludeSignal] = useState(true);
  const [includeGap, setIncludeGap] = useState(false);
  const [triggerEval, setTriggerEval] = useState(true);

  // Fleet form state
  const [fleetScope, setFleetScope] = useState('all');
  const [fleetSelected, setFleetSelected] = useState([]);
  const [fleetStrategy, setFleetStrategy] = useState('uniform_aggressive');
  const [fleetDuration, setFleetDuration] = useState(60);
  const [fleetInterval, setFleetInterval] = useState(60);
  const [fleetSeed, setFleetSeed] = useState('');
  const [fleetEval, setFleetEval] = useState(true);

  const fetchDevices = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/operator/device-health?window_hours=24');
      setDevices(res.data || []);
      if (res.data?.length > 0 && !selectedDevice) {
        setSelectedDevice(res.data[0].device_identifier);
      }
    } catch {
      toast.error('Failed to load devices');
    } finally {
      setLoading(false);
    }
  }, [selectedDevice]);

  useEffect(() => { fetchDevices(); }, [fetchDevices]);

  const buildSinglePayload = (dryRun = false) => {
    const preset = PATTERN_PRESETS[patternType];
    const metric_patterns = [{ metric: 'battery_level', ...preset.battery }];
    if (includeSignal) metric_patterns.push({ metric: 'signal_strength', ...preset.signal });
    const gap_patterns = includeGap ? [{ start_at_minute: Math.floor(duration * 0.4), duration_minutes: Math.max(1, Math.floor(duration * 0.08)) }] : [];
    return {
      device_identifier: selectedDevice,
      duration_minutes: duration,
      interval_seconds: interval,
      metric_patterns,
      gap_patterns,
      random_seed: randomSeed ? parseInt(randomSeed) : undefined,
      noise_percent: 1.5,
      trigger_evaluation: dryRun ? false : triggerEval,
    };
  };

  const buildFleetPayload = (dryRun = false) => {
    const targetDevices = fleetScope === 'all' ? devices : devices.filter(d => fleetSelected.includes(d.device_identifier));
    const strategy = FLEET_STRATEGIES[fleetStrategy];
    return {
      device_patterns: targetDevices.map((d, i) => ({
        device_identifier: d.device_identifier,
        ...strategy.getPatterns(i),
      })),
      duration_minutes: fleetDuration,
      interval_seconds: fleetInterval,
      random_seed: fleetSeed ? parseInt(fleetSeed) : undefined,
      noise_percent: 1.5,
      trigger_evaluation: dryRun ? false : fleetEval,
    };
  };

  const handleSubmit = async (dryRun = false) => {
    setSubmitting(true);
    setResult(null);
    try {
      let res;
      if (mode === 'single') {
        res = await api.post('/operator/simulate/heartbeat-seed', buildSinglePayload(dryRun));
      } else {
        const payload = buildFleetPayload(dryRun);
        if (!payload.device_patterns.length) {
          toast.error('No devices selected');
          setSubmitting(false);
          return;
        }
        res = await api.post('/operator/simulate/fleet', payload);
      }
      setResult(res.data);
      toast.success(`Simulation complete — ${dryRun ? 'Dry Run' : 'Full Run'}`);
    } catch (err) {
      const detail = err.response?.data?.detail || 'Simulation failed';
      toast.error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setSubmitting(false);
    }
  };

  const toggleFleetDevice = (id) => {
    setFleetSelected(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  };

  return (
    <div className="space-y-6" data-testid="simulation-lab">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-bold text-slate-900 flex items-center gap-2" data-testid="sim-lab-title">
          <FlaskConical className="w-6 h-6 text-violet-600" />
          Simulation Lab
        </h2>
        <p className="text-sm text-slate-500 mt-1">Generate synthetic telemetry to test anomaly intelligence safely.</p>
      </div>

      {/* Safety Banner */}
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 flex items-center gap-3" data-testid="sim-safety-banner">
        <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0" />
        <p className="text-sm text-amber-800">Simulated telemetry is isolated and will not affect production baselines or anomaly history.</p>
      </div>

      {/* Tab Selector */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-4" data-testid="sim-tab-selector">
            <button
              onClick={() => setActiveTab('simulate')}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-lg font-medium text-sm transition-all ${activeTab === 'simulate' ? 'bg-violet-100 text-violet-800 ring-2 ring-violet-300' : 'text-slate-500 hover:bg-slate-100'}`}
              data-testid="sim-tab-simulate"
            >
              <Play className="w-4 h-4" /> Run Simulation
            </button>
            <button
              onClick={() => setActiveTab('history')}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-lg font-medium text-sm transition-all ${activeTab === 'history' ? 'bg-slate-800 text-white ring-2 ring-slate-400' : 'text-slate-500 hover:bg-slate-100'}`}
              data-testid="sim-tab-history"
            >
              <History className="w-4 h-4" /> Simulation History
            </button>
            <button
              onClick={() => setActiveTab('compare')}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-lg font-medium text-sm transition-all ${activeTab === 'compare' ? 'bg-teal-100 text-teal-800 ring-2 ring-teal-300' : 'text-slate-500 hover:bg-slate-100'}`}
              data-testid="sim-tab-compare"
            >
              <GitCompare className="w-4 h-4" /> Compare
            </button>
            <button
              onClick={() => setActiveTab('behavior')}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-lg font-medium text-sm transition-all ${activeTab === 'behavior' ? 'bg-violet-100 text-violet-800 ring-2 ring-violet-300' : 'text-slate-500 hover:bg-slate-100'}`}
              data-testid="sim-tab-behavior"
            >
              <Brain className="w-4 h-4" /> Behavior Scenarios
            </button>
            <button
              onClick={() => setActiveTab('forecast')}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-lg font-medium text-sm transition-all ${activeTab === 'forecast' ? 'bg-red-100 text-red-800 ring-2 ring-red-300' : 'text-slate-500 hover:bg-slate-100'}`}
              data-testid="sim-tab-forecast"
            >
              <Radio className="w-4 h-4" /> Forecast Scenarios
            </button>
          </div>
        </CardContent>
      </Card>

      {activeTab === 'simulate' ? (
        <>
          {/* Mode Selector */}
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center gap-6" data-testid="sim-mode-selector">
                <button
                  onClick={() => setMode('single')}
                  className={`flex items-center gap-2 px-4 py-2.5 rounded-lg font-medium text-sm transition-all ${mode === 'single' ? 'bg-violet-100 text-violet-800 ring-2 ring-violet-300' : 'text-slate-500 hover:bg-slate-100'}`}
                  data-testid="sim-mode-single"
                >
                  <Cpu className="w-4 h-4" /> Single Device
                </button>
                <button
                  onClick={() => setMode('fleet')}
                  className={`flex items-center gap-2 px-4 py-2.5 rounded-lg font-medium text-sm transition-all ${mode === 'fleet' ? 'bg-blue-100 text-blue-800 ring-2 ring-blue-300' : 'text-slate-500 hover:bg-slate-100'}`}
                  data-testid="sim-mode-fleet"
                >
                  <Users className="w-4 h-4" /> Fleet Simulation
                </button>
              </div>
            </CardContent>
          </Card>

          {/* Form */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">{mode === 'single' ? 'Single Device Configuration' : 'Fleet Configuration'}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              {mode === 'single' ? (
                <SingleDeviceForm
                  devices={devices} loading={loading}
                  selectedDevice={selectedDevice} setSelectedDevice={setSelectedDevice}
                  patternType={patternType} setPatternType={setPatternType}
                  duration={duration} setDuration={setDuration}
                  interval_={interval} setInterval_={setInterval_}
                  randomSeed={randomSeed} setRandomSeed={setRandomSeed}
                  includeSignal={includeSignal} setIncludeSignal={setIncludeSignal}
                  includeGap={includeGap} setIncludeGap={setIncludeGap}
                  triggerEval={triggerEval} setTriggerEval={setTriggerEval}
                />
              ) : (
                <FleetForm
                  devices={devices} loading={loading}
                  fleetScope={fleetScope} setFleetScope={setFleetScope}
                  fleetSelected={fleetSelected} toggleFleetDevice={toggleFleetDevice}
                  fleetStrategy={fleetStrategy} setFleetStrategy={setFleetStrategy}
                  fleetDuration={fleetDuration} setFleetDuration={setFleetDuration}
                  fleetInterval={fleetInterval} setFleetInterval={setFleetInterval}
                  fleetSeed={fleetSeed} setFleetSeed={setFleetSeed}
                  fleetEval={fleetEval} setFleetEval={setFleetEval}
                />
              )}

              <Separator />

              {/* Submit */}
              <div className="flex items-center gap-3" data-testid="sim-submit-section">
                <Button
                  onClick={() => handleSubmit(false)}
                  disabled={submitting || (mode === 'single' && !selectedDevice)}
                  className="bg-violet-600 hover:bg-violet-700"
                  data-testid="sim-run-btn"
                >
                  {submitting ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Play className="w-4 h-4 mr-2" />}
                  Run Simulation
                </Button>
                <Button
                  variant="outline"
                  onClick={() => handleSubmit(true)}
                  disabled={submitting || (mode === 'single' && !selectedDevice)}
                  data-testid="sim-dry-run-btn"
                >
                  <Eye className="w-4 h-4 mr-2" />
                  Dry Run
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Results */}
          {result && (
            <ResultsPanel result={result} mode={mode} expanded={expandedDevices} setExpanded={setExpandedDevices} />
          )}
        </>
      ) : activeTab === 'history' ? (
        <SimulationHistoryTab />
      ) : activeTab === 'behavior' ? (
        <BehaviorScenarioTab />
      ) : activeTab === 'forecast' ? (
        <ForecastScenarioTab />
      ) : (
        <SimulationCompareTab />
      )}
    </div>
  );
}

// ── Simulation History Tab ──

function SimulationHistoryTab() {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [typeFilter, setTypeFilter] = useState('all');
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const limit = 20;

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    try {
      const runType = typeFilter === 'all' ? null : typeFilter;
      const res = await operatorApi.getSimulationHistory(page, limit, runType);
      setRuns(res.data.items || []);
      setTotalCount(res.data.total_count || 0);
    } catch {
      toast.error('Failed to load simulation history');
    } finally {
      setLoading(false);
    }
  }, [page, typeFilter]);

  useEffect(() => { fetchHistory(); }, [fetchHistory]);

  const totalPages = Math.max(1, Math.ceil(totalCount / limit));

  const openDetail = async (simulationRunId) => {
    setSelectedRunId(simulationRunId);
    setDrawerOpen(true);
    setDetailLoading(true);
    setDetail(null);
    try {
      const res = await operatorApi.getSimulationDetail(simulationRunId);
      setDetail(res.data);
    } catch {
      toast.error('Failed to load simulation details');
    } finally {
      setDetailLoading(false);
    }
  };

  const formatDate = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) +
      ' ' + d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  return (
    <div className="space-y-4" data-testid="sim-history-tab">
      {/* Section Label */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[10px] font-bold tracking-[0.2em] text-slate-400 uppercase" data-testid="sim-history-label">
            Simulation History (Research Log)
          </p>
          <p className="text-xs text-slate-400 mt-0.5">Immutable audit trail of all simulation experiments.</p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={typeFilter} onValueChange={(v) => { setTypeFilter(v); setPage(1); }}>
            <SelectTrigger className="w-[140px] h-8 text-xs" data-testid="sim-history-filter">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Types</SelectItem>
              <SelectItem value="single">Single Device</SelectItem>
              <SelectItem value="fleet">Fleet</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-16" data-testid="sim-history-loading">
              <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
            </div>
          ) : runs.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-slate-400" data-testid="sim-history-empty">
              <History className="w-10 h-10 mb-3 opacity-40" />
              <p className="text-sm font-medium">No simulation runs yet</p>
              <p className="text-xs mt-1">Run a simulation from the "Run Simulation" tab to see history here.</p>
            </div>
          ) : (
            <Table data-testid="sim-history-table">
              <TableHeader>
                <TableRow className="bg-slate-50">
                  <TableHead className="text-[10px] uppercase tracking-wider font-semibold">Run ID</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-wider font-semibold">Type</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-wider font-semibold text-center">Devices</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-wider font-semibold text-center">Anomalies</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-wider font-semibold text-center">DB Writes</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-wider font-semibold">Executed By</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-wider font-semibold">Date</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.map((r) => (
                  <TableRow
                    key={r.simulation_run_id}
                    className="cursor-pointer hover:bg-slate-50 transition-colors"
                    onClick={() => openDetail(r.simulation_run_id)}
                    data-testid={`sim-history-row-${r.simulation_run_id}`}
                  >
                    <TableCell className="font-mono text-xs text-violet-700">{r.simulation_run_id}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className={`text-[10px] ${r.run_type === 'fleet' ? 'border-blue-300 text-blue-700 bg-blue-50' : 'border-violet-300 text-violet-700 bg-violet-50'}`}>
                        {r.run_type === 'fleet' ? 'Fleet' : 'Single'}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-center text-sm font-medium">{r.total_devices_affected}</TableCell>
                    <TableCell className="text-center">
                      <span className={`text-sm font-medium ${r.anomalies_triggered > 0 ? 'text-red-600' : 'text-slate-500'}`}>
                        {r.anomalies_triggered}
                      </span>
                    </TableCell>
                    <TableCell className="text-center text-sm text-slate-500">{r.db_write_volume}</TableCell>
                    <TableCell className="text-xs text-slate-500 truncate max-w-[140px]">{r.executed_by_name}</TableCell>
                    <TableCell className="text-xs text-slate-400 whitespace-nowrap">{formatDate(r.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Pagination */}
      {totalCount > 0 && (
        <div className="flex items-center justify-between text-xs text-slate-500" data-testid="sim-history-pagination">
          <span>{totalCount} total run{totalCount !== 1 ? 's' : ''}</span>
          <div className="flex items-center gap-2">
            <Button
              variant="outline" size="sm"
              disabled={page <= 1}
              onClick={() => setPage(p => p - 1)}
              className="h-7 px-2"
              data-testid="sim-history-prev"
            >
              <ChevronLeft className="w-3 h-3" />
            </Button>
            <span className="text-xs font-medium">Page {page} of {totalPages}</span>
            <Button
              variant="outline" size="sm"
              disabled={page >= totalPages}
              onClick={() => setPage(p => p + 1)}
              className="h-7 px-2"
              data-testid="sim-history-next"
            >
              <ChevronRight className="w-3 h-3" />
            </Button>
          </div>
        </div>
      )}

      {/* Detail Drawer */}
      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent className="w-full sm:max-w-xl overflow-hidden flex flex-col" data-testid="sim-history-drawer">
          <SheetHeader className="shrink-0">
            <SheetTitle className="flex items-center gap-2 text-base">
              <FileJson className="w-4 h-4 text-violet-600" />
              Simulation Run Detail
            </SheetTitle>
          </SheetHeader>

          {detailLoading ? (
            <div className="flex items-center justify-center flex-1">
              <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
            </div>
          ) : detail ? (
            <ScrollArea className="flex-1 pr-2 mt-4">
              <div className="space-y-5 pb-6">
                {/* Run metadata */}
                <div className="space-y-2" data-testid="sim-detail-meta">
                  <div className="flex items-center gap-2">
                    <code className="font-mono text-sm text-violet-700 bg-violet-50 px-2 py-1 rounded">{detail.simulation_run_id}</code>
                    <Badge variant="outline" className={`text-[10px] ${detail.run_type === 'fleet' ? 'border-blue-300 text-blue-700 bg-blue-50' : 'border-violet-300 text-violet-700 bg-violet-50'}`}>
                      {detail.run_type === 'fleet' ? 'Fleet' : 'Single'}
                    </Badge>
                  </div>
                  <div className="grid grid-cols-2 gap-3 mt-3">
                    <MetaItem icon={<Cpu className="w-3.5 h-3.5" />} label="Devices" value={detail.total_devices_affected} />
                    <MetaItem icon={<Zap className="w-3.5 h-3.5" />} label="Anomalies" value={detail.anomalies_triggered} highlight={detail.anomalies_triggered > 0} />
                    <MetaItem icon={<Database className="w-3.5 h-3.5" />} label="DB Writes" value={detail.db_write_volume} />
                    <MetaItem icon={<Clock className="w-3.5 h-3.5" />} label="Scheduler" value={detail.scheduler_execution_ms ? `${detail.scheduler_execution_ms}ms` : '—'} />
                    <MetaItem icon={<User className="w-3.5 h-3.5" />} label="Executed By" value={detail.executed_by_name} />
                    <MetaItem icon={<Calendar className="w-3.5 h-3.5" />} label="Date" value={formatDate(detail.created_at)} />
                  </div>
                </div>

                <Separator />

                {/* Config JSON */}
                <div data-testid="sim-detail-config">
                  <p className="text-[10px] font-bold tracking-[0.15em] text-slate-400 uppercase mb-2">Configuration</p>
                  <pre className="bg-slate-900 text-slate-100 p-4 rounded-lg text-xs font-mono overflow-x-auto max-h-[300px] overflow-y-auto whitespace-pre-wrap break-words">
                    {JSON.stringify(detail.config_json, null, 2)}
                  </pre>
                </div>

                <Separator />

                {/* Summary JSON */}
                <div data-testid="sim-detail-summary">
                  <p className="text-[10px] font-bold tracking-[0.15em] text-slate-400 uppercase mb-2">Full Summary</p>
                  <pre className="bg-slate-900 text-slate-100 p-4 rounded-lg text-xs font-mono overflow-x-auto max-h-[400px] overflow-y-auto whitespace-pre-wrap break-words">
                    {JSON.stringify(detail.summary_json, null, 2)}
                  </pre>
                </div>
              </div>
            </ScrollArea>
          ) : (
            <div className="flex items-center justify-center flex-1 text-sm text-slate-400">
              No data available
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}

function MetaItem({ icon, label, value, highlight = false }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-slate-400">{icon}</span>
      <span className="text-slate-500 text-xs">{label}:</span>
      <span className={`font-medium text-xs ${highlight ? 'text-red-600' : 'text-slate-800'}`}>{value}</span>
    </div>
  );
}

function formatDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) +
    ' ' + d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

// ── Existing Sub-components (unchanged) ──

function SingleDeviceForm({ devices, loading, selectedDevice, setSelectedDevice, patternType, setPatternType, duration, setDuration, interval_, setInterval_, randomSeed, setRandomSeed, includeSignal, setIncludeSignal, includeGap, setIncludeGap, triggerEval, setTriggerEval }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-5" data-testid="sim-single-form">
      <div className="space-y-2">
        <Label>Device</Label>
        <Select value={selectedDevice} onValueChange={setSelectedDevice} data-testid="sim-device-select">
          <SelectTrigger data-testid="sim-device-trigger">
            <SelectValue placeholder={loading ? 'Loading...' : 'Select device'} />
          </SelectTrigger>
          <SelectContent>
            {devices.map(d => (
              <SelectItem key={d.device_identifier} value={d.device_identifier} data-testid={`sim-device-${d.device_identifier}`}>
                {d.device_identifier} — {d.senior_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <Label>Pattern Type</Label>
        <Select value={patternType} onValueChange={setPatternType}>
          <SelectTrigger data-testid="sim-pattern-trigger">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {Object.entries(PATTERN_PRESETS).map(([k, v]) => (
              <SelectItem key={k} value={k}>{v.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <Label>Duration (minutes)</Label>
        <Input type="number" min={1} max={1440} value={duration} onChange={e => setDuration(parseInt(e.target.value) || 60)} data-testid="sim-duration" />
      </div>

      <div className="space-y-2">
        <Label>Interval (seconds)</Label>
        <Input type="number" min={10} max={600} value={interval_} onChange={e => setInterval_(parseInt(e.target.value) || 60)} data-testid="sim-interval" />
      </div>

      <div className="space-y-2">
        <Label>Random Seed (optional)</Label>
        <Input type="number" placeholder="e.g. 42" value={randomSeed} onChange={e => setRandomSeed(e.target.value)} data-testid="sim-seed" />
      </div>

      <div className="space-y-4 pt-2">
        <div className="flex items-center gap-3">
          <Switch checked={includeSignal} onCheckedChange={setIncludeSignal} data-testid="sim-include-signal" />
          <Label className="cursor-pointer">Include Signal Simulation</Label>
        </div>
        <div className="flex items-center gap-3">
          <Switch checked={includeGap} onCheckedChange={setIncludeGap} data-testid="sim-include-gap" />
          <Label className="cursor-pointer">Include Gap Pattern (Reboot)</Label>
        </div>
        <div className="flex items-center gap-3">
          <Switch checked={triggerEval} onCheckedChange={setTriggerEval} data-testid="sim-trigger-eval" />
          <Label className="cursor-pointer">Trigger Anomaly Evaluation</Label>
        </div>
      </div>
    </div>
  );
}

function FleetForm({ devices, loading, fleetScope, setFleetScope, fleetSelected, toggleFleetDevice, fleetStrategy, setFleetStrategy, fleetDuration, setFleetDuration, fleetInterval, setFleetInterval, fleetSeed, setFleetSeed, fleetEval, setFleetEval }) {
  return (
    <div className="space-y-5" data-testid="sim-fleet-form">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        <div className="space-y-2">
          <Label>Device Scope</Label>
          <Select value={fleetScope} onValueChange={setFleetScope}>
            <SelectTrigger data-testid="sim-fleet-scope-trigger">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Devices ({devices.length})</SelectItem>
              <SelectItem value="subset">Select Subset</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label>Pattern Strategy</Label>
          <Select value={fleetStrategy} onValueChange={setFleetStrategy}>
            <SelectTrigger data-testid="sim-fleet-strategy-trigger">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(FLEET_STRATEGIES).map(([k, v]) => (
                <SelectItem key={k} value={k}>{v.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label>Duration (minutes)</Label>
          <Input type="number" min={1} max={1440} value={fleetDuration} onChange={e => setFleetDuration(parseInt(e.target.value) || 60)} data-testid="sim-fleet-duration" />
        </div>

        <div className="space-y-2">
          <Label>Interval (seconds)</Label>
          <Input type="number" min={10} max={600} value={fleetInterval} onChange={e => setFleetInterval(parseInt(e.target.value) || 60)} data-testid="sim-fleet-interval" />
        </div>

        <div className="space-y-2">
          <Label>Random Seed (optional)</Label>
          <Input type="number" placeholder="e.g. 42" value={fleetSeed} onChange={e => setFleetSeed(e.target.value)} data-testid="sim-fleet-seed" />
        </div>

        <div className="flex items-center gap-3 pt-6">
          <Switch checked={fleetEval} onCheckedChange={setFleetEval} data-testid="sim-fleet-eval" />
          <Label className="cursor-pointer">Evaluate After Run</Label>
        </div>
      </div>

      {fleetScope === 'subset' && (
        <div className="space-y-2">
          <Label>Select Devices ({fleetSelected.length} selected)</Label>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2 max-h-48 overflow-y-auto p-2 border rounded-lg bg-slate-50" data-testid="sim-fleet-device-list">
            {devices.map(d => (
              <button
                key={d.device_identifier}
                onClick={() => toggleFleetDevice(d.device_identifier)}
                className={`px-3 py-2 rounded-md text-xs font-mono text-left transition-all ${
                  fleetSelected.includes(d.device_identifier)
                    ? 'bg-blue-100 text-blue-800 ring-1 ring-blue-300'
                    : 'bg-white text-slate-600 hover:bg-slate-100 border border-slate-200'
                }`}
                data-testid={`sim-fleet-dev-${d.device_identifier}`}
              >
                {d.device_identifier}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ResultsPanel({ result, mode, expanded, setExpanded }) {
  const isFleet = mode === 'fleet';
  const runId = result.simulation_run_id;
  const recordsCreated = isFleet ? result.total_records_created : result.records_created;
  const recordsSkipped = isFleet ? result.total_records_skipped : result.records_skipped_by_gaps;
  const devicesAffected = isFleet ? result.total_devices_affected : 1;
  const anomaliesTriggered = isFleet ? result.anomalies_triggered : (result.anomalies_detected ?? 0);
  const schedulerMs = isFleet ? result.scheduler_execution_ms : null;
  const dbWrites = isFleet ? result.db_write_volume : recordsCreated;
  const distribution = isFleet ? result.anomaly_distribution : null;
  const perDevice = isFleet ? result.per_device_results : null;

  return (
    <Card className="border-violet-200 relative overflow-hidden" data-testid="sim-results-panel">
      <div className="absolute top-3 right-3 px-2 py-1 bg-violet-100 text-violet-600 text-[10px] font-bold tracking-widest rounded">
        SIMULATION MODE
      </div>

      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <CheckCircle className="w-5 h-5 text-emerald-600" />
          Execution Summary
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-2 text-sm" data-testid="sim-result-run-id">
          <Hash className="w-4 h-4 text-slate-400" />
          <span className="text-slate-500">Simulation Run ID:</span>
          <code className="font-mono text-violet-700 bg-violet-50 px-2 py-0.5 rounded text-xs">{runId}</code>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3" data-testid="sim-result-metrics">
          <MetricCard icon={<Cpu className="w-4 h-4" />} label="Devices Affected" value={devicesAffected} testId="sim-result-devices" />
          <MetricCard icon={<Database className="w-4 h-4" />} label="Records Created" value={recordsCreated} testId="sim-result-records" />
          <MetricCard icon={<AlertTriangle className="w-4 h-4" />} label="Anomalies Triggered" value={anomaliesTriggered} color={anomaliesTriggered > 0 ? 'text-red-700 bg-red-50' : ''} testId="sim-result-anomalies" />
          {schedulerMs !== null && (
            <MetricCard icon={<Clock className="w-4 h-4" />} label="Scheduler Time" value={`${schedulerMs}ms`} testId="sim-result-scheduler" />
          )}
          <MetricCard icon={<Database className="w-4 h-4" />} label="DB Writes" value={dbWrites} testId="sim-result-db-writes" />
        </div>

        {distribution && distribution.some(b => b.count > 0) && (
          <div data-testid="sim-result-distribution">
            <p className="text-sm font-medium text-slate-600 mb-2">Score Distribution</p>
            <div className="flex gap-2">
              {distribution.map((b, i) => (
                <div key={i} className="flex-1 text-center p-2 rounded-md bg-slate-50 border border-slate-100" data-testid={`sim-dist-${b.range_label}`}>
                  <p className="text-xs text-slate-400">{b.range_label}</p>
                  <p className="text-lg font-bold text-slate-700">{b.count}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="text-xs text-slate-400 flex items-center gap-2">
          <Clock className="w-3 h-3" />
          {new Date(result.time_range_start).toLocaleString()} — {new Date(result.time_range_end || result.time_range_start).toLocaleString()}
          {recordsSkipped > 0 && <span className="text-amber-500">({recordsSkipped} skipped by gaps)</span>}
        </div>

        {perDevice && perDevice.length > 0 && (
          <div>
            <button
              onClick={() => setExpanded(!expanded)}
              className="flex items-center gap-1 text-sm text-violet-600 hover:text-violet-800 font-medium"
              data-testid="sim-result-expand-devices"
            >
              {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              Per-Device Results ({perDevice.length})
            </button>
            {expanded && (
              <div className="mt-2 space-y-1 max-h-60 overflow-y-auto" data-testid="sim-result-per-device-list">
                {perDevice.map((d, i) => (
                  <div key={i} className="flex items-center justify-between px-3 py-2 rounded bg-slate-50 text-xs" data-testid={`sim-per-device-${d.device_identifier}`}>
                    <span className="font-mono font-medium text-slate-700">{d.device_identifier}</span>
                    <span className="text-slate-500">
                      {d.records_created} records
                      {d.records_skipped_by_gaps > 0 && <span className="text-amber-500 ml-1">({d.records_skipped_by_gaps} gaps)</span>}
                      <span className="text-slate-300 mx-1">|</span>
                      {d.metrics_seeded?.join(', ')}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {result.baselines_updated && typeof result.baselines_updated === 'object' && !result.baselines_updated.error && (
          <div className="text-xs text-slate-400" data-testid="sim-result-baselines">
            Baselines updated: {Object.entries(result.baselines_updated).map(([k, v]) => `${k}: ${v}`).join(', ')}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function MetricCard({ icon, label, value, color = '', testId }) {
  return (
    <div className={`p-3 rounded-lg border border-slate-100 ${color || 'bg-white'}`} data-testid={testId}>
      <div className="flex items-center gap-1.5 text-slate-400 mb-1">{icon}<span className="text-[10px] uppercase tracking-wide">{label}</span></div>
      <p className="text-xl font-bold text-slate-800">{value}</p>
    </div>
  );
}

// SimulationCompareTab is now imported from ./SimulationLab/SimulationCompareTab
