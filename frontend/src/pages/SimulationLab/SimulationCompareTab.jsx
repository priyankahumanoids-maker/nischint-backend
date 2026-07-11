import React, { useState, useRef } from 'react';
import { Card, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../components/ui/select';
import { operatorApi } from '../../api';
import { toast } from 'sonner';
import { Loader2, GitCompare, RefreshCw, Radio, History, Clock, Database, Cpu } from 'lucide-react';
import { CompareConfigCard } from './CompareConfigCard';
import { CompareResultsPanel } from './CompareResultsPanel';
import { CompareApplyDialog } from './CompareApplyDialog';
import { ReplayTimelinePanel } from './ReplayTimelinePanel';

const DEFAULT_CONFIG = {
  weight_battery: 0.5, weight_signal: 0.3, weight_behavior: 0.2,
  trigger_threshold: 60, correlation_bonus: 10, persistence_minutes: 15,
  recovery_minutes: 15, recovery_buffer: 5, min_clear_cycles: 2,
  instability_cooldown_minutes: 30,
  escalation_tiers: { '60-75': 'L1', '75-90': 'L2', '90-100': 'L3' },
};

const DEFAULT_CONFIG_B = {
  ...DEFAULT_CONFIG,
  trigger_threshold: 55, persistence_minutes: 10,
};

function configsEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

const REPLAY_PRESETS = {
  '15': '15 min',
  '60': '1 hour',
  '360': '6 hours',
  '1440': '24 hours',
  '4320': '3 days',
  '10080': '7 days',
  'custom': 'Custom',
};

function getDefaultReplayEnd() {
  const d = new Date();
  return d.toISOString().slice(0, 16);
}

function getDefaultReplayStart(minutes) {
  const d = new Date(Date.now() - minutes * 60 * 1000);
  return d.toISOString().slice(0, 16);
}

export function SimulationCompareTab() {
  const [cfgA, setCfgA] = useState({ ...DEFAULT_CONFIG });
  const [cfgB, setCfgB] = useState({ ...DEFAULT_CONFIG_B });
  const [windowMin, setWindowMin] = useState(60);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [hasRun, setHasRun] = useState(false);
  const [applying, setApplying] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmChecked, setConfirmChecked] = useState(false);
  const [isStale, setIsStale] = useState(false);
  const [productionConfig, setProductionConfig] = useState(null);

  // Replay mode state
  const [mode, setMode] = useState('live');
  const [replayPreset, setReplayPreset] = useState('1440');
  const [replayStart, setReplayStart] = useState(getDefaultReplayStart(1440));
  const [replayEnd, setReplayEnd] = useState(getDefaultReplayEnd());

  const lastRunSnapshot = useRef(null);

  const handleCfgAChange = (updater) => {
    setCfgA(updater);
    setTimeout(() => setIsStale(prev => !hasRun ? false : true), 0);
  };

  const handleCfgBChange = (updater) => {
    setCfgB(updater);
    setTimeout(() => setIsStale(prev => !hasRun ? false : true), 0);
  };

  const handleWindowChange = (v) => {
    setWindowMin(parseInt(v));
    if (hasRun) setIsStale(true);
  };

  const handleModeChange = (newMode) => {
    setMode(newMode);
    if (hasRun) setIsStale(true);
  };

  const handleReplayPresetChange = (v) => {
    setReplayPreset(v);
    if (v !== 'custom') {
      const mins = parseInt(v);
      setReplayStart(getDefaultReplayStart(mins));
      setReplayEnd(getDefaultReplayEnd());
    }
    if (hasRun) setIsStale(true);
  };

  const loadProduction = async () => {
    try {
      const res = await operatorApi.getHealthRules();
      const rule = (res.data || []).find(r => r.rule_name === 'combined_anomaly');
      if (rule?.threshold_json) {
        const t = rule.threshold_json;
        const prodCfg = {
          weight_battery: t.weight_battery ?? 0.5,
          weight_signal: t.weight_signal ?? 0.3,
          weight_behavior: t.weight_behavior ?? 0.2,
          trigger_threshold: t.trigger_threshold ?? 60,
          correlation_bonus: t.correlation_bonus ?? 10,
          persistence_minutes: t.persistence_minutes ?? 15,
          recovery_minutes: t.recovery_minutes ?? 15,
          recovery_buffer: t.recovery_buffer ?? 5,
          min_clear_cycles: t.min_clear_cycles ?? 2,
          instability_cooldown_minutes: t.instability_cooldown_minutes ?? 30,
          escalation_tiers: t.escalation_tiers ?? { '60-75': 'L1', '75-90': 'L2', '90-100': 'L3' },
        };
        setCfgA(prodCfg);
        setProductionConfig(prodCfg);
        if (hasRun) setIsStale(true);
        toast.success('Loaded production config into Config A');
      }
    } catch {
      toast.error('Failed to load production config');
    }
  };

  const validateConfig = (cfg, label) => {
    const wSum = Math.round((cfg.weight_battery + cfg.weight_signal + (cfg.weight_behavior || 0)) * 100) / 100;
    if (Math.abs(wSum - 1.0) > 0.01) return `${label}: Weights must sum to 1.0 (currently ${wSum})`;
    if (cfg.trigger_threshold < 0 || cfg.trigger_threshold > 100) return `${label}: Threshold must be 0-100`;
    if (cfg.persistence_minutes <= 0) return `${label}: Persistence must be > 0`;
    if (cfg.recovery_minutes <= 0) return `${label}: Recovery minutes must be > 0`;
    if (cfg.recovery_buffer < 0) return `${label}: Recovery buffer must be >= 0`;
    if (cfg.min_clear_cycles <= 0) return `${label}: Clear cycles must be > 0`;
    if (cfg.instability_cooldown_minutes <= 0) return `${label}: Cooldown must be > 0`;
    const tierErr = validateTierRanges(cfg.escalation_tiers, label);
    if (tierErr) return tierErr;
    return null;
  };

  const validateTierRanges = (tiers, label) => {
    if (!tiers || typeof tiers !== 'object') return `${label}: Escalation tiers required`;
    const entries = Object.entries(tiers);
    if (entries.length === 0) return `${label}: At least one escalation tier required`;
    const ranges = [];
    for (const [rangeStr, tier] of entries) {
      const parts = rangeStr.split('-').map(Number);
      if (parts.length !== 2 || isNaN(parts[0]) || isNaN(parts[1])) {
        return `${label}: Invalid tier range format "${rangeStr}"`;
      }
      const [lo, hi] = parts;
      if (lo >= hi) return `${label}: Tier ${tier} lower bound (${lo}) must be < upper bound (${hi})`;
      if (lo < 0 || hi > 100) return `${label}: Tier ${tier} range must be within 0-100`;
      ranges.push({ lo, hi, tier });
    }
    ranges.sort((a, b) => a.lo - b.lo);
    for (let i = 1; i < ranges.length; i++) {
      if (ranges[i].lo < ranges[i - 1].hi) {
        return `${label}: Tier ranges overlap (${ranges[i - 1].tier} and ${ranges[i].tier})`;
      }
    }
    return null;
  };

  const runComparison = async () => {
    const errA = validateConfig(cfgA, 'Config A');
    const errB = validateConfig(cfgB, 'Config B');
    if (errA) { toast.error(errA); return; }
    if (errB) { toast.error(errB); return; }

    // Validate replay dates
    if (mode === 'replay') {
      if (!replayStart || !replayEnd) {
        toast.error('Start and end times are required for replay mode');
        return;
      }
      const s = new Date(replayStart);
      const e = new Date(replayEnd);
      if (e <= s) {
        toast.error('End time must be after start time');
        return;
      }
      if ((e - s) > 7 * 24 * 60 * 60 * 1000) {
        toast.error('Replay window cannot exceed 7 days');
        return;
      }
      if (e > new Date()) {
        toast.error('End time cannot be in the future');
        return;
      }
    }

    setLoading(true);
    setResult(null);
    try {
      const payload = {
        config_a: { combined_anomaly: cfgA },
        config_b: { combined_anomaly: cfgB },
        mode,
      };

      if (mode === 'live') {
        payload.window_minutes = windowMin;
      } else {
        // Replay mode — compute window_minutes from the date range
        const s = new Date(replayStart);
        const e = new Date(replayEnd);
        payload.window_minutes = Math.ceil((e - s) / 60000);
        payload.start_time = new Date(replayStart).toISOString();
        payload.end_time = new Date(replayEnd).toISOString();
      }

      const res = await operatorApi.compareMultiMetric(payload);
      setResult(res.data);
      setHasRun(true);
      setIsStale(false);
      lastRunSnapshot.current = JSON.stringify({ cfgA, cfgB, windowMin, mode, replayStart, replayEnd });
      toast.success(mode === 'replay' ? 'Historical replay complete' : 'Comparison complete');
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Comparison failed');
    } finally {
      setLoading(false);
    }
  };

  const swapConfigs = () => {
    const tmp = { ...cfgA };
    setCfgA({ ...cfgB });
    setCfgB(tmp);
    if (hasRun) setIsStale(true);
  };

  const clearResults = () => {
    setResult(null);
    setHasRun(false);
    setIsStale(false);
    lastRunSnapshot.current = null;
  };

  const canApply = () => {
    if (!hasRun || !result || isStale) return false;
    if (configsEqual(cfgA, cfgB)) return false;
    return true;
  };

  const applyConfigB = async () => {
    setApplying(true);
    try {
      const currentRes = await operatorApi.getHealthRules();
      const rule = (currentRes.data || []).find(r => r.rule_name === 'combined_anomaly');
      const existing = rule?.threshold_json || {};
      await operatorApi.updateHealthRule('combined_anomaly', {
        threshold_json: {
          ...existing,
          weight_battery: cfgB.weight_battery,
          weight_signal: cfgB.weight_signal,
          weight_behavior: cfgB.weight_behavior,
          trigger_threshold: cfgB.trigger_threshold,
          correlation_bonus: cfgB.correlation_bonus,
          persistence_minutes: cfgB.persistence_minutes,
          recovery_minutes: cfgB.recovery_minutes,
          recovery_buffer: cfgB.recovery_buffer,
          min_clear_cycles: cfgB.min_clear_cycles,
          instability_cooldown_minutes: cfgB.instability_cooldown_minutes,
          escalation_tiers: cfgB.escalation_tiers,
        },
      });
      toast.success('Config B applied to production');
      setConfirmOpen(false);
      setConfirmChecked(false);
      setProductionConfig({ ...cfgB });
    } catch {
      toast.error('Failed to apply config');
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="space-y-5" data-testid="sim-compare-tab">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[10px] font-bold tracking-[0.2em] text-slate-400 uppercase" data-testid="compare-label">
            Sensitivity Comparison Lab
          </p>
          <p className="text-xs text-slate-400 mt-0.5">
            Compare two multi-metric configs against {mode === 'replay' ? 'historical' : 'live'} telemetry. Read-only.
          </p>
        </div>
      </div>

      {/* Mode Selector + Window Controls */}
      <Card>
        <CardContent className="p-4 space-y-4">
          <div className="flex items-center gap-2" data-testid="cmp-mode-selector">
            <Label className="text-[10px] uppercase tracking-wide text-slate-400 mr-2">Comparison Mode</Label>
            <button
              onClick={() => handleModeChange('live')}
              className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all ${
                mode === 'live' ? 'bg-teal-100 text-teal-800 ring-2 ring-teal-300' : 'text-slate-500 hover:bg-slate-100'
              }`}
              data-testid="cmp-mode-live"
            >
              <Radio className="w-3.5 h-3.5" /> Live Telemetry
            </button>
            <button
              onClick={() => handleModeChange('replay')}
              className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all ${
                mode === 'replay' ? 'bg-indigo-100 text-indigo-800 ring-2 ring-indigo-300' : 'text-slate-500 hover:bg-slate-100'
              }`}
              data-testid="cmp-mode-replay"
            >
              <History className="w-3.5 h-3.5" /> Historical Replay
            </button>
          </div>

          {mode === 'live' ? (
            <div className="flex items-center gap-3">
              <Label className="text-[10px] uppercase tracking-wide text-slate-400">Window</Label>
              <Select value={String(windowMin)} onValueChange={handleWindowChange}>
                <SelectTrigger className="w-[120px] h-8 text-xs" data-testid="compare-window-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="15">15 min</SelectItem>
                  <SelectItem value="60">1 hour</SelectItem>
                  <SelectItem value="360">6 hours</SelectItem>
                  <SelectItem value="1440">24 hours</SelectItem>
                </SelectContent>
              </Select>
            </div>
          ) : (
            <div className="space-y-3" data-testid="cmp-replay-controls">
              <div className="flex items-center gap-3">
                <Label className="text-[10px] uppercase tracking-wide text-slate-400">Replay Window</Label>
                <Select value={replayPreset} onValueChange={handleReplayPresetChange}>
                  <SelectTrigger className="w-[140px] h-8 text-xs" data-testid="cmp-window-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(REPLAY_PRESETS).map(([k, v]) => (
                      <SelectItem key={k} value={k}>{v}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {replayPreset === 'custom' && (
                <div className="grid grid-cols-2 gap-4" data-testid="cmp-custom-dates">
                  <div>
                    <Label className="text-[10px] text-slate-500">Start</Label>
                    <Input
                      type="datetime-local"
                      value={replayStart}
                      onChange={e => { setReplayStart(e.target.value); if (hasRun) setIsStale(true); }}
                      className="h-8 text-xs"
                      data-testid="cmp-start-time"
                    />
                  </div>
                  <div>
                    <Label className="text-[10px] text-slate-500">End</Label>
                    <Input
                      type="datetime-local"
                      value={replayEnd}
                      onChange={e => { setReplayEnd(e.target.value); if (hasRun) setIsStale(true); }}
                      className="h-8 text-xs"
                      data-testid="cmp-end-time"
                    />
                  </div>
                </div>
              )}
              {replayPreset !== 'custom' && (
                <p className="text-[10px] text-slate-400">
                  From {new Date(replayStart).toLocaleString()} to {new Date(replayEnd).toLocaleString()}
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Stale Indicator */}
      {isStale && hasRun && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-2.5 flex items-center gap-3" data-testid="compare-stale-banner">
          <RefreshCw className="w-4 h-4 text-amber-600 shrink-0" />
          <p className="text-xs text-amber-700 font-medium flex-1">
            Configuration changed since last run. Results are outdated.
          </p>
          <Button size="sm" variant="outline" className="h-7 text-xs border-amber-300 text-amber-700 hover:bg-amber-100"
            onClick={runComparison} disabled={loading} data-testid="compare-rerun-btn">
            {loading ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <RefreshCw className="w-3 h-3 mr-1" />}
            Re-run
          </Button>
        </div>
      )}

      {/* Config Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4" data-testid="compare-config-cards">
        <CompareConfigCard label="Config A" sublabel="Current / Baseline" config={cfgA} setConfig={handleCfgAChange}
          accent="blue" onLoadProd={loadProduction} testPrefix="cfg-a" />
        <CompareConfigCard label="Config B" sublabel="Proposed / Variant" config={cfgB} setConfig={handleCfgBChange}
          accent="teal" testPrefix="cfg-b" showPresets />
      </div>

      {/* Controls */}
      <div className="flex items-center gap-3" data-testid="compare-controls">
        <Button onClick={runComparison} disabled={loading}
          className={mode === 'replay' ? 'bg-indigo-600 hover:bg-indigo-700' : 'bg-teal-600 hover:bg-teal-700'}
          data-testid="compare-run-btn">
          {loading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> :
            mode === 'replay' ? <History className="w-4 h-4 mr-2" /> : <GitCompare className="w-4 h-4 mr-2" />}
          {mode === 'replay' ? 'Run Replay' : 'Run Comparison'}
        </Button>
        <Button variant="outline" onClick={swapConfigs} disabled={loading} data-testid="compare-swap-btn">
          Swap A/B
        </Button>
        <Button variant="ghost" onClick={clearResults} disabled={loading} data-testid="compare-clear-btn">
          Clear
        </Button>
      </div>

      {/* Results */}
      {result && (
        <>
          {/* Replay Metadata */}
          {result.replay_metadata && (
            <ReplayMetadataPanel metadata={result.replay_metadata} devicesEvaluated={result.devices_evaluated} />
          )}

          {/* Replay Timeline Visualization */}
          {result.replay_metadata && (
            <ReplayTimelinePanel
              startTime={result.replay_metadata.start_time}
              endTime={result.replay_metadata.end_time}
              threshold={cfgA.trigger_threshold}
            />
          )}

          <CompareResultsPanel result={result} />

          {/* Apply Config B */}
          <div className="flex items-center justify-end gap-3" data-testid="compare-apply-section">
            {!canApply() && hasRun && !isStale && configsEqual(cfgA, cfgB) && (
              <span className="text-xs text-slate-400">Config A and B are identical — nothing to apply.</span>
            )}
            {isStale && (
              <span className="text-xs text-amber-600">Re-run comparison to enable apply.</span>
            )}
            <Button
              variant="destructive"
              disabled={!canApply()}
              onClick={() => { setConfirmOpen(true); setConfirmChecked(false); }}
              data-testid="compare-apply-btn"
            >
              Apply Config B to Production
            </Button>
          </div>

          <CompareApplyDialog
            open={confirmOpen}
            onClose={() => setConfirmOpen(false)}
            confirmChecked={confirmChecked}
            setConfirmChecked={setConfirmChecked}
            applying={applying}
            onApply={applyConfigB}
          />
        </>
      )}
    </div>
  );
}

function ReplayMetadataPanel({ metadata, devicesEvaluated }) {
  const formatWindow = () => {
    const mins = metadata.window_span_minutes;
    if (mins >= 1440) return `${(mins / 1440).toFixed(1)} days`;
    if (mins >= 60) return `${(mins / 60).toFixed(1)} hours`;
    return `${Math.round(mins)} min`;
  };

  const formatDate = (iso) => {
    const d = new Date(iso);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  };

  return (
    <Card className="border-indigo-200 bg-indigo-50/30" data-testid="replay-metadata-panel">
      <CardContent className="p-4">
        <div className="flex items-center gap-2 mb-3">
          <History className="w-4 h-4 text-indigo-600" />
          <span className="text-xs font-semibold text-indigo-700 uppercase tracking-wide">Historical Replay Results</span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="flex items-center gap-2" data-testid="replay-meta-window">
            <Clock className="w-3.5 h-3.5 text-indigo-400" />
            <div>
              <p className="text-[10px] text-indigo-400 uppercase">Replay Window</p>
              <p className="text-sm font-medium text-indigo-800">{formatWindow()}</p>
              <p className="text-[10px] text-indigo-400">{formatDate(metadata.start_time)} — {formatDate(metadata.end_time)}</p>
            </div>
          </div>
          <div className="flex items-center gap-2" data-testid="replay-meta-events">
            <Database className="w-3.5 h-3.5 text-indigo-400" />
            <div>
              <p className="text-[10px] text-indigo-400 uppercase">Telemetry Events</p>
              <p className="text-sm font-medium text-indigo-800">{metadata.telemetry_events_analyzed?.toLocaleString()}</p>
            </div>
          </div>
          <div className="flex items-center gap-2" data-testid="replay-meta-anomalies">
            <GitCompare className="w-3.5 h-3.5 text-indigo-400" />
            <div>
              <p className="text-[10px] text-indigo-400 uppercase">Anomaly Records</p>
              <p className="text-sm font-medium text-indigo-800">{metadata.anomaly_records_evaluated?.toLocaleString()}</p>
            </div>
          </div>
          <div className="flex items-center gap-2" data-testid="replay-meta-devices">
            <Cpu className="w-3.5 h-3.5 text-indigo-400" />
            <div>
              <p className="text-[10px] text-indigo-400 uppercase">Devices Analyzed</p>
              <p className="text-sm font-medium text-indigo-800">{devicesEvaluated}</p>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
