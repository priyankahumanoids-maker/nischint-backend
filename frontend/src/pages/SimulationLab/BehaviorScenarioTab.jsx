import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Badge } from '../../components/ui/badge';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../components/ui/select';
import { Switch } from '../../components/ui/switch';
import { Separator } from '../../components/ui/separator';
import { ScrollArea } from '../../components/ui/scroll-area';
import api, { operatorApi } from '../../api';
import { toast } from 'sonner';
import {
  Brain, Play, Loader2, AlertTriangle, CheckCircle, Plus, Trash2,
  Clock, Activity, TrendingDown, MapPin, Navigation, UserX, ChevronDown, ChevronUp,
} from 'lucide-react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine, ComposedChart, Bar,
} from 'recharts';

const SCENARIOS = {
  prolonged_inactivity: {
    label: 'Prolonged Inactivity',
    icon: UserX,
    desc: 'Fall or unconsciousness — senior stops responding',
    color: 'text-red-600',
    bg: 'bg-red-50 border-red-200',
    badgeColor: 'bg-red-100 text-red-700',
    defaults: { duration_minutes: 120, intensity: 0.8, ramp_minutes: 20 },
  },
  movement_drop: {
    label: 'Movement Drop',
    icon: TrendingDown,
    desc: 'Gradual health deterioration — decreasing mobility',
    color: 'text-orange-600',
    bg: 'bg-orange-50 border-orange-200',
    badgeColor: 'bg-orange-100 text-orange-700',
    defaults: { duration_minutes: 180, intensity: 0.7, ramp_minutes: 60 },
  },
  routine_disruption: {
    label: 'Routine Disruption',
    icon: Activity,
    desc: 'Unusual daily pattern — behavioral change indicator',
    color: 'text-amber-600',
    bg: 'bg-amber-50 border-amber-200',
    badgeColor: 'bg-amber-100 text-amber-700',
    defaults: { duration_minutes: 90, intensity: 0.6, ramp_minutes: 30 },
  },
  location_wandering: {
    label: 'Location Wandering',
    icon: MapPin,
    desc: 'Erratic high movement — elder wandering detection',
    color: 'text-purple-600',
    bg: 'bg-purple-50 border-purple-200',
    badgeColor: 'bg-purple-100 text-purple-700',
    defaults: { duration_minutes: 60, intensity: 0.75, ramp_minutes: 15 },
  },
  route_deviation: {
    label: 'Route Deviation',
    icon: Navigation,
    desc: 'Sudden location pattern change — child safety concern',
    color: 'text-blue-600',
    bg: 'bg-blue-50 border-blue-200',
    badgeColor: 'bg-blue-100 text-blue-700',
    defaults: { duration_minutes: 45, intensity: 0.65, ramp_minutes: 10 },
  },
};

const TIER_COLORS = { L1: '#f59e0b', L2: '#f97316', L3: '#ef4444' };

function ScenarioCard({ scenario, index, devices, onUpdate, onRemove }) {
  const meta = SCENARIOS[scenario.scenario_type] || SCENARIOS.prolonged_inactivity;
  const Icon = meta.icon;

  return (
    <Card className={`border ${meta.bg}`} data-testid={`scenario-card-${index}`}>
      <CardContent className="p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Icon className={`w-4 h-4 ${meta.color}`} />
            <span className="font-semibold text-sm text-slate-800">{meta.label}</span>
            <Badge variant="outline" className={`text-[10px] ${meta.badgeColor}`}>{meta.desc}</Badge>
          </div>
          <Button variant="ghost" size="sm" onClick={() => onRemove(index)}
            className="text-slate-400 hover:text-red-500 h-7 w-7 p-0" data-testid={`remove-scenario-${index}`}>
            <Trash2 className="w-3.5 h-3.5" />
          </Button>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div>
            <Label className="text-[10px] text-slate-500">Device</Label>
            <Select value={scenario.device_identifier}
              onValueChange={v => onUpdate(index, 'device_identifier', v)}>
              <SelectTrigger className="h-8 text-xs" data-testid={`scenario-device-${index}`}>
                <SelectValue placeholder="Select device" />
              </SelectTrigger>
              <SelectContent>
                {devices.map(d => (
                  <SelectItem key={d.device_identifier} value={d.device_identifier}>
                    {d.device_identifier}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-[10px] text-slate-500">Duration (min)</Label>
            <Input type="number" min={10} max={720} value={scenario.duration_minutes}
              onChange={e => onUpdate(index, 'duration_minutes', parseInt(e.target.value) || 10)}
              className="h-8 text-xs" data-testid={`scenario-duration-${index}`} />
          </div>
          <div>
            <Label className="text-[10px] text-slate-500">Intensity (0.1–1.0)</Label>
            <Input type="number" min={0.1} max={1.0} step={0.1} value={scenario.intensity}
              onChange={e => onUpdate(index, 'intensity', parseFloat(e.target.value) || 0.5)}
              className="h-8 text-xs" data-testid={`scenario-intensity-${index}`} />
          </div>
          <div>
            <Label className="text-[10px] text-slate-500">Ramp (min)</Label>
            <Input type="number" min={0} max={360} value={scenario.ramp_minutes}
              onChange={e => onUpdate(index, 'ramp_minutes', parseInt(e.target.value) || 0)}
              className="h-8 text-xs" data-testid={`scenario-ramp-${index}`} />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function EscalationTimeline({ result }) {
  const { timeline, scenario_type, device_identifier, peak_behavior_score, peak_combined_score,
    final_escalation_tier, time_to_first_escalation_minutes } = result;
  const meta = SCENARIOS[scenario_type] || SCENARIOS.prolonged_inactivity;

  const chartData = timeline.map(t => ({
    minute: t.minute,
    behavior: Math.round(t.behavior_score * 100),
    combined: t.combined_risk_score ?? 0,
    tier: t.escalation_tier,
  }));

  return (
    <Card className="border border-slate-200" data-testid={`timeline-${device_identifier}-${scenario_type}`}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Brain className={`w-4 h-4 ${meta.color}`} />
            <CardTitle className="text-sm">{meta.label} — {device_identifier}</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            {final_escalation_tier ? (
              <Badge className="text-xs font-semibold"
                style={{ backgroundColor: TIER_COLORS[final_escalation_tier] + '22',
                  color: TIER_COLORS[final_escalation_tier], border: `1px solid ${TIER_COLORS[final_escalation_tier]}` }}>
                Escalation: {final_escalation_tier}
              </Badge>
            ) : (
              <Badge variant="outline" className="text-xs text-green-700 bg-green-50 border-green-200">
                No Escalation
              </Badge>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* KPI Row */}
        <div className="grid grid-cols-4 gap-3">
          <KpiCard label="Peak Behavior" value={`${(peak_behavior_score * 100).toFixed(0)}%`}
            sub="risk score" color="text-violet-600" testId={`kpi-peak-beh-${device_identifier}`} />
          <KpiCard label="Peak Combined" value={peak_combined_score?.toFixed(1) ?? 'N/A'}
            sub="out of 100" color="text-rose-600" testId={`kpi-peak-comb-${device_identifier}`} />
          <KpiCard label="Final Tier" value={final_escalation_tier || 'None'}
            sub="escalation" color={final_escalation_tier ? 'text-orange-600' : 'text-green-600'}
            testId={`kpi-tier-${device_identifier}`} />
          <KpiCard label="Time to Escalation"
            value={time_to_first_escalation_minutes != null ? `${time_to_first_escalation_minutes}m` : '—'}
            sub="from start" color="text-blue-600" testId={`kpi-time-esc-${device_identifier}`} />
        </div>

        {/* Timeline Chart */}
        <div className="h-[220px]" data-testid={`timeline-chart-${device_identifier}`}>
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
              <defs>
                <linearGradient id="behaviorGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#8b5cf6" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#8b5cf6" stopOpacity={0.05} />
                </linearGradient>
                <linearGradient id="combinedGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#ef4444" stopOpacity={0.25} />
                  <stop offset="100%" stopColor="#ef4444" stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="minute" tick={{ fontSize: 10 }} label={{ value: 'Minutes', position: 'insideBottom', offset: -2, fontSize: 10 }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} />
              <Tooltip content={<TimelineTooltip />} />
              <ReferenceLine y={60} stroke="#f59e0b" strokeDasharray="5 3" label={{ value: 'Threshold', fill: '#f59e0b', fontSize: 10 }} />
              <Area type="monotone" dataKey="behavior" name="Behavior Score"
                stroke="#8b5cf6" fill="url(#behaviorGrad)" strokeWidth={2} dot={false} />
              <Area type="monotone" dataKey="combined" name="Combined Risk"
                stroke="#ef4444" fill="url(#combinedGrad)" strokeWidth={2} dot={false} />
              {chartData.filter(d => d.tier).map((d, i) => (
                <ReferenceLine key={i} x={d.minute} stroke={TIER_COLORS[d.tier] || '#888'}
                  strokeDasharray="2 2" strokeWidth={1.5} />
              ))}
            </ComposedChart>
          </ResponsiveContainer>
        </div>

        {/* Step Detail Table */}
        <details className="group">
          <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-700 flex items-center gap-1"
            data-testid={`timeline-details-toggle-${device_identifier}`}>
            <ChevronDown className="w-3 h-3 group-open:rotate-180 transition-transform" />
            Step-by-step detail ({timeline.length} steps)
          </summary>
          <div className="max-h-[200px] mt-2 overflow-y-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b text-slate-500">
                  <th className="text-left py-1 pr-2">Min</th>
                  <th className="text-left py-1 pr-2">Behavior</th>
                  <th className="text-left py-1 pr-2">Combined</th>
                  <th className="text-left py-1 pr-2">Tier</th>
                  <th className="text-left py-1">Reason</th>
                </tr>
              </thead>
              <tbody>
                {timeline.map((t, i) => (
                  <tr key={i} className={`border-b border-slate-100 ${t.escalation_tier ? 'bg-red-50/50' : ''}`}>
                    <td className="py-1 pr-2 font-mono">{t.minute}</td>
                    <td className="py-1 pr-2">{(t.behavior_score * 100).toFixed(0)}%</td>
                    <td className="py-1 pr-2 font-semibold">{t.combined_risk_score?.toFixed(1) ?? '—'}</td>
                    <td className="py-1 pr-2">
                      {t.escalation_tier ? (
                        <span className="font-bold" style={{ color: TIER_COLORS[t.escalation_tier] }}>
                          {t.escalation_tier}
                        </span>
                      ) : '—'}
                    </td>
                    <td className="py-1 text-slate-500 truncate max-w-[200px]" title={t.escalation_reason}>
                      {t.escalation_reason || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </CardContent>
    </Card>
  );
}

function TimelineTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const data = payload[0]?.payload;
  return (
    <div className="bg-white/95 backdrop-blur border rounded-lg shadow-lg p-2.5 text-xs">
      <p className="font-semibold text-slate-700">t = {label} min</p>
      <p className="text-violet-600">Behavior: {data?.behavior}%</p>
      <p className="text-rose-600">Combined: {data?.combined?.toFixed(1)}</p>
      {data?.tier && <p className="font-bold" style={{ color: TIER_COLORS[data.tier] }}>Tier: {data.tier}</p>}
    </div>
  );
}

function KpiCard({ label, value, sub, color, testId }) {
  return (
    <div className="bg-slate-50 rounded-lg p-2.5 text-center" data-testid={testId}>
      <p className="text-[10px] text-slate-400 uppercase tracking-wide">{label}</p>
      <p className={`text-lg font-bold ${color}`}>{value}</p>
      <p className="text-[9px] text-slate-400">{sub}</p>
    </div>
  );
}

export function BehaviorScenarioTab() {
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);

  const [scenarios, setScenarios] = useState([]);
  const [triggerEscalation, setTriggerEscalation] = useState(true);
  const [stepInterval, setStepInterval] = useState(5);

  const fetchDevices = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/operator/device-health?window_hours=24');
      setDevices(res.data || []);
    } catch {
      toast.error('Failed to load devices');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchDevices(); }, [fetchDevices]);

  const addScenario = (type) => {
    const meta = SCENARIOS[type];
    setScenarios(prev => [...prev, {
      scenario_type: type,
      device_identifier: devices[0]?.device_identifier || '',
      ...meta.defaults,
    }]);
  };

  const updateScenario = (index, key, value) => {
    setScenarios(prev => prev.map((s, i) => i === index ? { ...s, [key]: value } : s));
  };

  const removeScenario = (index) => {
    setScenarios(prev => prev.filter((_, i) => i !== index));
  };

  const handleRun = async () => {
    if (!scenarios.length) { toast.error('Add at least one scenario'); return; }
    const invalid = scenarios.find(s => !s.device_identifier);
    if (invalid) { toast.error('All scenarios must have a device selected'); return; }

    setSubmitting(true);
    setResult(null);
    try {
      const res = await operatorApi.simulateBehavior({
        scenarios,
        trigger_escalation: triggerEscalation,
        step_interval_minutes: stepInterval,
      });
      setResult(res.data);
      toast.success(`Behavior simulation complete — ${res.data.total_behavior_anomalies} anomalies generated`);
    } catch (err) {
      const detail = err.response?.data?.detail || 'Simulation failed';
      toast.error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-5" data-testid="behavior-scenario-tab">
      {/* Scenario Type Selector */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Brain className="w-4 h-4 text-violet-600" />
            Add Behavior Scenario
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            {Object.entries(SCENARIOS).map(([key, meta]) => {
              const Icon = meta.icon;
              return (
                <Button key={key} variant="outline" size="sm"
                  className={`h-auto py-2 px-3 flex flex-col items-start gap-1 text-left ${meta.bg} hover:opacity-80`}
                  onClick={() => addScenario(key)}
                  data-testid={`add-scenario-${key}`}>
                  <div className="flex items-center gap-1.5">
                    <Icon className={`w-3.5 h-3.5 ${meta.color}`} />
                    <span className="text-xs font-semibold text-slate-700">{meta.label}</span>
                  </div>
                  <span className="text-[10px] text-slate-500 leading-tight">{meta.desc}</span>
                </Button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Active Scenarios */}
      {scenarios.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-700">
              Active Scenarios ({scenarios.length})
            </h3>
            <Button variant="ghost" size="sm" className="text-xs text-red-500" onClick={() => setScenarios([])}
              data-testid="clear-all-scenarios">
              <Trash2 className="w-3 h-3 mr-1" /> Clear All
            </Button>
          </div>
          {scenarios.map((s, i) => (
            <ScenarioCard key={i} scenario={s} index={i} devices={devices}
              onUpdate={updateScenario} onRemove={removeScenario} />
          ))}
        </div>
      )}

      {/* Controls */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-6">
              <div className="flex items-center gap-2">
                <Switch checked={triggerEscalation} onCheckedChange={setTriggerEscalation}
                  data-testid="behavior-trigger-escalation" />
                <Label className="text-xs text-slate-600">Evaluate Escalation</Label>
              </div>
              <div className="flex items-center gap-2">
                <Label className="text-xs text-slate-500">Step Interval:</Label>
                <Select value={String(stepInterval)} onValueChange={v => setStepInterval(parseInt(v))}>
                  <SelectTrigger className="h-7 w-20 text-xs" data-testid="behavior-step-interval">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="1">1 min</SelectItem>
                    <SelectItem value="5">5 min</SelectItem>
                    <SelectItem value="10">10 min</SelectItem>
                    <SelectItem value="15">15 min</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <Button onClick={handleRun} disabled={submitting || !scenarios.length}
              className="bg-violet-600 hover:bg-violet-700 text-white"
              data-testid="run-behavior-sim">
              {submitting ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Play className="w-4 h-4 mr-2" />}
              {submitting ? 'Running...' : 'Run Simulation'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Results */}
      {result && (
        <div className="space-y-4" data-testid="behavior-sim-results">
          {/* Summary Banner */}
          <div className="rounded-lg border border-violet-200 bg-violet-50 px-4 py-3 flex items-center justify-between"
            data-testid="behavior-sim-summary">
            <div className="flex items-center gap-3">
              <CheckCircle className="w-5 h-5 text-violet-600" />
              <div>
                <p className="text-sm font-semibold text-violet-800">Simulation Complete</p>
                <p className="text-xs text-violet-600">
                  {result.total_scenarios} scenario{result.total_scenarios > 1 ? 's' : ''} ·
                  {' '}{result.total_behavior_anomalies} anomalies ·
                  {' '}{result.total_escalations} escalation{result.total_escalations !== 1 ? 's' : ''}
                </p>
              </div>
            </div>
            <Badge variant="outline" className="text-[10px] text-violet-600 border-violet-300">
              {result.simulation_run_id}
            </Badge>
          </div>

          {/* Scenario Timelines */}
          {result.scenario_results.map((sr, i) => (
            <EscalationTimeline key={i} result={sr} />
          ))}
        </div>
      )}

      {/* Empty State */}
      {!scenarios.length && !result && (
        <div className="text-center py-12 text-slate-400" data-testid="behavior-empty-state">
          <Brain className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm font-medium">No scenarios configured</p>
          <p className="text-xs mt-1">Click a scenario type above to begin testing behavioral risk responses</p>
        </div>
      )}
    </div>
  );
}
