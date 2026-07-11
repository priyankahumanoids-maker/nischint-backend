import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../components/ui/select';
import { operatorApi } from '../../api';
import { toast } from 'sonner';
import {
  Radio, TrendingUp, TrendingDown, ArrowUpRight, Minus, Shield,
  Loader2, Play, ChevronRight, AlertTriangle, Eye, Users, MapPin,
} from 'lucide-react';

const SCENARIO_ICONS = {
  incident_surge: <TrendingUp className="w-4 h-4 text-red-500" />,
  patrol_deployment: <Shield className="w-4 h-4 text-blue-500" />,
  new_hazard: <AlertTriangle className="w-4 h-4 text-orange-500" />,
  time_shift: <Radio className="w-4 h-4 text-purple-500" />,
};

const FORECAST_BG = {
  escalating: 'bg-red-100 text-red-700',
  emerging: 'bg-orange-100 text-orange-700',
  stable: 'bg-amber-100 text-amber-700',
  cooling: 'bg-green-100 text-green-700',
};

function DeltaCell({ value }) {
  if (Math.abs(value) < 0.1) return <span className="text-slate-400">—</span>;
  return (
    <span className={`font-semibold ${value > 0 ? 'text-red-600' : 'text-green-600'}`}>
      {value > 0 ? '+' : ''}{value}
    </span>
  );
}

export function ForecastScenarioTab() {
  const [scenarioType, setScenarioType] = useState('incident_surge');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [zones, setZones] = useState([]);
  const [selectedZones, setSelectedZones] = useState([]);

  // Params
  const [multiplier, setMultiplier] = useState(2.0);
  const [reductionPct, setReductionPct] = useState(40);
  const [hazardLat, setHazardLat] = useState('12.971');
  const [hazardLng, setHazardLng] = useState('77.594');
  const [hazardSeverity, setHazardSeverity] = useState('high');
  const [hazardRate, setHazardRate] = useState(8);
  const [targetHour, setTargetHour] = useState(22);
  const [scenarioName, setScenarioName] = useState('');

  useEffect(() => {
    operatorApi.getRiskLearningStats().then(r => {
      const z = (r.data?.learned_zones || []).map((z, i) => ({
        ...z, zone_id: z.zone_id || String(i),
      }));
      setZones(z);
    }).catch(() => {});
  }, []);

  const toggleZone = (zid) => {
    setSelectedZones(prev => prev.includes(zid) ? prev.filter(x => x !== zid) : [...prev, zid]);
  };

  const runScenario = async () => {
    setRunning(true);
    try {
      const params = {};
      if (scenarioType === 'incident_surge') {
        params.zone_ids = selectedZones.length > 0 ? selectedZones : undefined;
        params.multiplier = multiplier;
      } else if (scenarioType === 'patrol_deployment') {
        params.zone_ids = selectedZones.length > 0 ? selectedZones : undefined;
        params.reduction_pct = reductionPct;
      } else if (scenarioType === 'new_hazard') {
        params.lat = parseFloat(hazardLat);
        params.lng = parseFloat(hazardLng);
        params.severity = hazardSeverity;
        params.incident_rate = hazardRate;
      } else if (scenarioType === 'time_shift') {
        params.target_hour = targetHour;
      }

      const res = await operatorApi.runForecastScenario({
        type: scenarioType,
        params,
        name: scenarioName || undefined,
      });
      setResult(res.data);
      toast.success('Forecast scenario complete');
    } catch {
      toast.error('Scenario simulation failed');
    } finally {
      setRunning(false);
    }
  };

  const summary = result?.summary || {};
  const comparisons = result?.comparisons || [];

  return (
    <div className="space-y-4" data-testid="forecast-scenario-tab">
      {/* Scenario Builder */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base font-semibold text-slate-800 flex items-center gap-2">
            <Radio className="w-5 h-5 text-purple-500" /> Build Forecast Scenario
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Scenario Type */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2" data-testid="scenario-type-selector">
            {[
              { id: 'incident_surge', label: 'Incident Surge', desc: 'What if incidents increase?' },
              { id: 'patrol_deployment', label: 'Patrol Deploy', desc: 'What if we deploy patrols?' },
              { id: 'new_hazard', label: 'New Hazard', desc: 'What if a new hazard appears?' },
              { id: 'time_shift', label: 'Time Shift', desc: 'Forecast at different hour' },
            ].map(s => (
              <button key={s.id} onClick={() => setScenarioType(s.id)}
                className={`p-3 rounded-lg border text-left transition-all ${
                  scenarioType === s.id ? 'border-purple-400 bg-purple-50 ring-2 ring-purple-200' : 'border-slate-200 hover:border-slate-300'
                }`} data-testid={`scenario-${s.id}`}>
                <div className="flex items-center gap-2 mb-1">
                  {SCENARIO_ICONS[s.id]}
                  <span className="text-sm font-medium text-slate-700">{s.label}</span>
                </div>
                <p className="text-[10px] text-slate-400">{s.desc}</p>
              </button>
            ))}
          </div>

          {/* Scenario Parameters */}
          <div className="rounded-lg border border-slate-200 p-4 bg-slate-50/50">
            <Label className="text-xs text-slate-500 mb-2 block">Scenario Parameters</Label>

            {scenarioType === 'incident_surge' && (
              <div className="space-y-3">
                <div>
                  <Label className="text-xs">Incident Multiplier ({multiplier}x)</Label>
                  <input type="range" min="1.5" max="5" step="0.5" value={multiplier}
                    onChange={e => setMultiplier(parseFloat(e.target.value))}
                    className="w-full mt-1" data-testid="surge-multiplier" />
                  <p className="text-[10px] text-slate-400 mt-1">Simulates {multiplier}x increase in incident rate</p>
                </div>
              </div>
            )}

            {scenarioType === 'patrol_deployment' && (
              <div>
                <Label className="text-xs">Incident Reduction ({reductionPct}%)</Label>
                <input type="range" min="10" max="90" step="10" value={reductionPct}
                  onChange={e => setReductionPct(parseInt(e.target.value))}
                  className="w-full mt-1" data-testid="patrol-reduction" />
                <p className="text-[10px] text-slate-400 mt-1">Patrol expected to reduce incidents by {reductionPct}%</p>
              </div>
            )}

            {scenarioType === 'new_hazard' && (
              <div className="grid grid-cols-2 gap-3">
                <div><Label className="text-xs">Latitude</Label><Input value={hazardLat} onChange={e => setHazardLat(e.target.value)} className="mt-1 h-8 text-xs" data-testid="hazard-lat" /></div>
                <div><Label className="text-xs">Longitude</Label><Input value={hazardLng} onChange={e => setHazardLng(e.target.value)} className="mt-1 h-8 text-xs" data-testid="hazard-lng" /></div>
                <div>
                  <Label className="text-xs">Severity</Label>
                  <Select value={hazardSeverity} onValueChange={setHazardSeverity}>
                    <SelectTrigger className="mt-1 h-8 text-xs" data-testid="hazard-severity"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="critical">Critical</SelectItem>
                      <SelectItem value="high">High</SelectItem>
                      <SelectItem value="medium">Medium</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div><Label className="text-xs">Incident Rate</Label><Input type="number" value={hazardRate} onChange={e => setHazardRate(parseInt(e.target.value) || 5)} className="mt-1 h-8 text-xs" data-testid="hazard-rate" /></div>
              </div>
            )}

            {scenarioType === 'time_shift' && (
              <div>
                <Label className="text-xs">Target Hour (0-23)</Label>
                <div className="flex gap-2 mt-1">
                  <Input type="number" min="0" max="23" value={targetHour}
                    onChange={e => setTargetHour(parseInt(e.target.value) || 0)}
                    className="h-8 text-xs w-20" data-testid="time-shift-hour" />
                  <span className="text-xs text-slate-400 self-center">{targetHour}:00 — {targetHour >= 22 || targetHour < 6 ? 'Night' : targetHour >= 17 ? 'Evening' : targetHour >= 12 ? 'Afternoon' : 'Morning'}</span>
                </div>
              </div>
            )}

            {/* Zone selector for surge/patrol */}
            {(scenarioType === 'incident_surge' || scenarioType === 'patrol_deployment') && zones.length > 0 && (
              <div className="mt-3">
                <Label className="text-xs text-slate-500">Target Zones (optional — leave empty for all)</Label>
                <div className="flex flex-wrap gap-1 mt-1 max-h-24 overflow-y-auto">
                  {zones.slice(0, 12).map((z, i) => (
                    <button key={i} onClick={() => toggleZone(z.zone_id || String(i))}
                      className={`text-[10px] px-2 py-1 rounded border transition-colors ${
                        selectedZones.includes(z.zone_id || String(i))
                          ? 'bg-purple-100 border-purple-400 text-purple-700'
                          : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300'
                      }`}>{z.zone_name?.replace('Learned Hotspot ', 'H') || `Zone ${i + 1}`}</button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Name + Run */}
          <div className="flex items-center gap-3">
            <Input placeholder="Scenario name (optional)" value={scenarioName}
              onChange={e => setScenarioName(e.target.value)}
              className="h-9 text-sm flex-1" data-testid="scenario-name" />
            <Button onClick={runScenario} disabled={running}
              className="bg-purple-600 hover:bg-purple-700 h-9" data-testid="run-scenario-btn">
              {running ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Play className="w-4 h-4 mr-2" />}
              {running ? 'Simulating...' : 'Run Scenario'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Results */}
      {result && (
        <>
          {/* Summary */}
          <Card data-testid="scenario-results">
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-semibold text-slate-800 flex items-center gap-2">
                {SCENARIO_ICONS[result.scenario_type]}
                {result.scenario_name}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 mb-4" data-testid="scenario-summary">
                {[
                  { label: 'Worsened', value: summary.zones_worsened, color: 'text-red-600' },
                  { label: 'Improved', value: summary.zones_improved, color: 'text-green-600' },
                  { label: 'Category Changes', value: summary.category_changes, color: 'text-amber-600' },
                  { label: 'Priority Changes', value: summary.priority_changes, color: 'text-purple-600' },
                  { label: 'New P1', value: summary.new_p1_zones, color: 'text-red-600' },
                  { label: 'Resolved P1', value: summary.resolved_p1_zones, color: 'text-green-600' },
                ].map(s => (
                  <div key={s.label} className="text-center p-2 rounded-lg bg-slate-50 border border-slate-100">
                    <p className={`text-lg font-bold ${s.color}`}>{s.value}</p>
                    <p className="text-[10px] text-slate-400">{s.label}</p>
                  </div>
                ))}
              </div>

              {/* Comparison Table */}
              <div className="overflow-x-auto">
                <table className="w-full text-xs" data-testid="scenario-comparison-table">
                  <thead>
                    <tr className="border-b border-slate-200">
                      <th className="text-left py-2 px-2 text-slate-500 font-medium">Zone</th>
                      <th className="text-center py-2 px-1 text-slate-500 font-medium">Now</th>
                      <th className="text-center py-2 px-1 text-slate-500 font-medium">Base 48h</th>
                      <th className="text-center py-2 px-1 text-slate-500 font-medium">Sim 48h</th>
                      <th className="text-center py-2 px-1 text-slate-500 font-medium">Delta</th>
                      <th className="text-center py-2 px-1 text-slate-500 font-medium">Category</th>
                      <th className="text-center py-2 px-1 text-slate-500 font-medium">Priority</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparisons.slice(0, 20).map((c, i) => (
                      <tr key={i} className={`border-b border-slate-50 ${c.affected ? 'bg-purple-50/30' : ''} ${c.priority_changed ? 'bg-amber-50/30' : ''}`}>
                        <td className="py-1.5 px-2">
                          <span className="font-medium text-slate-700 truncate block max-w-[140px]">{c.zone_name}</span>
                          {c.affected && <span className="text-[9px] text-purple-500">targeted</span>}
                        </td>
                        <td className="text-center py-1.5 px-1 font-semibold text-slate-700">{c.risk_score}</td>
                        <td className="text-center py-1.5 px-1">{c.baseline.predicted_48h}</td>
                        <td className="text-center py-1.5 px-1 font-semibold">{c.scenario.predicted_48h}</td>
                        <td className="text-center py-1.5 px-1"><DeltaCell value={c.delta_48h} /></td>
                        <td className="text-center py-1.5 px-1">
                          {c.category_changed ? (
                            <span className="flex items-center justify-center gap-0.5">
                              <Badge className={`${FORECAST_BG[c.baseline.forecast_category]} text-[9px] px-1`}>{c.baseline.forecast_category}</Badge>
                              <ChevronRight className="w-3 h-3 text-slate-300" />
                              <Badge className={`${FORECAST_BG[c.scenario.forecast_category]} text-[9px] px-1`}>{c.scenario.forecast_category}</Badge>
                            </span>
                          ) : <Badge className={`${FORECAST_BG[c.scenario.forecast_category]} text-[9px] px-1`}>{c.scenario.forecast_category}</Badge>}
                        </td>
                        <td className="text-center py-1.5 px-1">
                          {c.priority_changed ? (
                            <span className="flex items-center justify-center gap-0.5">
                              <span className="text-[9px] text-slate-400">P{c.baseline.forecast_priority}</span>
                              <ChevronRight className="w-3 h-3 text-slate-300" />
                              <span className={`text-[9px] font-bold ${c.scenario.forecast_priority === 1 ? 'text-red-600' : 'text-green-600'}`}>P{c.scenario.forecast_priority}</span>
                            </span>
                          ) : <span className="text-[9px] text-slate-400">P{c.scenario.forecast_priority}</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
