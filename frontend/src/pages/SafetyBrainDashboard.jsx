import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  Brain, Activity, AlertTriangle, Shield, Clock, Loader2,
  RefreshCw, Zap, Navigation, Radio, MapPin, TrendingUp,
  Layers, Eye, Lightbulb, ChevronDown, ChevronUp, Target,
} from 'lucide-react';
import api from '../api';
import { useAuth } from '../contexts/AuthContext';
import { toast } from 'sonner';

const SIGNAL_META = {
  fall: { label: 'Fall', color: '#f97316', icon: AlertTriangle, weight: 0.35 },
  voice: { label: 'Voice', color: '#dc2626', icon: Radio, weight: 0.30 },
  route: { label: 'Route', color: '#3b82f6', icon: Navigation, weight: 0.15 },
  wander: { label: 'Wander', color: '#8b5cf6', icon: MapPin, weight: 0.10 },
  pickup: { label: 'Pickup', color: '#06b6d4', icon: Shield, weight: 0.10 },
};

const LEVEL_STYLES = {
  normal: { bg: 'bg-green-50', border: 'border-green-300', text: 'text-green-700', badge: 'bg-green-100 text-green-800', label: 'NORMAL', color: '#22c55e' },
  suspicious: { bg: 'bg-amber-50', border: 'border-amber-300', text: 'text-amber-700', badge: 'bg-amber-100 text-amber-800', label: 'SUSPICIOUS', color: '#f59e0b' },
  dangerous: { bg: 'bg-orange-50', border: 'border-orange-400', text: 'text-orange-700', badge: 'bg-orange-100 text-orange-800', label: 'DANGEROUS', color: '#f97316' },
  critical: { bg: 'bg-red-50', border: 'border-red-400', text: 'text-red-700', badge: 'bg-red-100 text-red-800', label: 'CRITICAL', color: '#ef4444' },
};

const RiskGauge = ({ score, level }) => {
  const pct = Math.round(score * 100);
  const style = LEVEL_STYLES[level] || LEVEL_STYLES.normal;
  const rotation = -90 + (score * 180);
  return (
    <div className="flex flex-col items-center" data-testid="risk-gauge">
      <div className="relative w-40 h-20 overflow-hidden">
        <svg viewBox="0 0 200 100" className="w-full h-full">
          <path d="M 10 100 A 90 90 0 0 1 190 100" fill="none" stroke="#e2e8f0" strokeWidth="16" strokeLinecap="round" />
          <path d="M 10 100 A 90 90 0 0 1 190 100" fill="none"
            stroke={style.color} strokeWidth="16" strokeLinecap="round"
            strokeDasharray={`${score * 283} 283`}
          />
          <line x1="100" y1="100" x2="100" y2="20"
            stroke="#1e293b" strokeWidth="3" strokeLinecap="round"
            transform={`rotate(${rotation}, 100, 100)`}
          />
          <circle cx="100" cy="100" r="6" fill="#1e293b" />
        </svg>
      </div>
      <div className="text-3xl font-black mt-1" data-testid="risk-score-display">{pct}%</div>
      <Badge className={`mt-1 text-xs font-bold ${style.badge}`} data-testid="risk-level-badge">{style.label}</Badge>
    </div>
  );
};

const SignalBar = ({ type, value, rawValue }) => {
  const meta = SIGNAL_META[type];
  if (!meta) return null;
  const Icon = meta.icon;
  const pct = Math.round((value || 0) * 100);
  const rawPct = Math.round((rawValue || 0) * 100);
  const decayed = rawValue && value < rawValue;
  return (
    <div className="flex items-center gap-3" data-testid={`signal-bar-${type}`}>
      <div className="w-20 flex items-center gap-1.5 text-xs font-semibold text-slate-600">
        <Icon className="w-3.5 h-3.5" style={{ color: meta.color }} />
        {meta.label}
      </div>
      <div className="flex-1 h-3 bg-slate-100 rounded-full overflow-hidden relative">
        {decayed && (
          <div className="absolute inset-y-0 left-0 rounded-full opacity-25" style={{ width: `${rawPct}%`, background: meta.color }} />
        )}
        <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: meta.color }} />
      </div>
      <div className="w-10 text-right text-xs font-bold text-slate-700">{pct}%</div>
      <div className="w-8 text-right text-[10px] text-slate-400 font-mono">{meta.weight * 100}%</div>
    </div>
  );
};

const LayerCard = ({ index, title, icon: Icon, color, score, weight, children }) => {
  const pct = Math.round((score || 0) * 100);
  const weighted = Math.round((score || 0) * weight * 100);
  return (
    <div className="rounded-lg border bg-white shadow-sm overflow-hidden" data-testid={`layer-${index}-card`}>
      <div className="flex items-center gap-3 p-3 border-b" style={{ borderLeftWidth: 4, borderLeftColor: color }}>
        <div className="w-8 h-8 rounded-full flex items-center justify-center" style={{ backgroundColor: `${color}15` }}>
          <Icon className="w-4 h-4" style={{ color }} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-xs font-bold text-slate-700">Layer {index}: {title}</div>
          <div className="text-[10px] text-slate-400">Weight: {Math.round(weight * 100)}%</div>
        </div>
        <div className="text-right">
          <div className="text-lg font-black" style={{ color }}>{pct}%</div>
          <div className="text-[10px] text-slate-400">Contrib: {weighted}%</div>
        </div>
      </div>
      <div className="p-3 text-xs text-slate-600">{children}</div>
    </div>
  );
};

const WindowBar = ({ label, days, data }) => {
  const total = (data?.wandering || 0) + (data?.falls || 0) + (data?.voice_distress || 0) + (data?.safety_events || 0);
  const maxEvents = 20;
  const fill = Math.min(100, (total / maxEvents) * 100);
  return (
    <div className="flex items-center gap-2" data-testid={`window-${label}`}>
      <div className="w-16 text-[10px] font-semibold text-slate-500">{days}d</div>
      <div className="flex-1 h-5 bg-slate-100 rounded-full overflow-hidden flex">
        {data?.wandering > 0 && <div className="h-full" style={{ width: `${(data.wandering / Math.max(total, 1)) * fill}%`, background: '#8b5cf6' }} title={`Wander: ${data.wandering}`} />}
        {data?.falls > 0 && <div className="h-full" style={{ width: `${(data.falls / Math.max(total, 1)) * fill}%`, background: '#f97316' }} title={`Falls: ${data.falls}`} />}
        {data?.voice_distress > 0 && <div className="h-full" style={{ width: `${(data.voice_distress / Math.max(total, 1)) * fill}%`, background: '#dc2626' }} title={`Voice: ${data.voice_distress}`} />}
        {data?.safety_events > 0 && <div className="h-full" style={{ width: `${(data.safety_events / Math.max(total, 1)) * fill}%`, background: '#64748b' }} title={`Safety: ${data.safety_events}`} />}
      </div>
      <div className="w-8 text-right text-[10px] font-bold text-slate-600">{total}</div>
    </div>
  );
};

const SafetyBrainDashboard = ({ predictiveAlert }) => {
  const { user } = useAuth();
  const [riskStatus, setRiskStatus] = useState(null);
  const [events, setEvents] = useState([]);
  const [fusedData, setFusedData] = useState(null);
  const [predictive, setPredictive] = useState(null);
  const [heatmapData, setHeatmapData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [predictiveLoading, setPredictiveLoading] = useState(false);
  const [showNarrative, setShowNarrative] = useState(false);

  const userId = user?.id || user?.user_id;

  const fetchData = useCallback(async () => {
    try {
      const [statusRes, eventsRes] = await Promise.all([
        userId ? api.get(`/safety-brain/status/${userId}`).catch(() => ({ data: null })) : Promise.resolve({ data: null }),
        api.get('/safety-brain/events?limit=20').catch(() => ({ data: { events: [] } })),
      ]);
      setRiskStatus(statusRes.data);
      setEvents(eventsRes.data?.events || []);

      // Fetch 3-layer fused risk (fast mode, skip behavior for auto-refresh)
      if (userId) {
        const fusedRes = await api.get(`/safety-brain/v2/fused-risk/${userId}?lat=28.6139&lng=77.2090&skip_behavior=true`).catch(() => ({ data: null }));
        setFusedData(fusedRes.data);
      }

      // Fetch heatmap
      const heatRes = await api.get('/safety-brain/v2/heatmap?limit=50').catch(() => ({ data: null }));
      setHeatmapData(heatRes.data);
    } catch {
      toast.error('Failed to load Safety Brain data');
    } finally {
      setLoading(false);
    }
  }, [userId]);

  const runPredictiveAnalysis = useCallback(async () => {
    if (!userId) return;
    setPredictiveLoading(true);
    try {
      const res = await api.get(`/safety-brain/v2/predictive/${userId}?lat=28.6139&lng=77.2090`);
      setPredictive(res.data);
      setShowNarrative(true);
      toast.success('Predictive analysis complete');
    } catch {
      toast.error('Failed to run predictive analysis');
    } finally {
      setPredictiveLoading(false);
    }
  }, [userId]);

  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => {
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // Update from SSE predictive alert
  useEffect(() => {
    if (predictiveAlert) {
      setPredictive(prev => ({ ...prev, ...predictiveAlert }));
    }
  }, [predictiveAlert]);

  const riskLevel = riskStatus?.risk_level || 'normal';
  const riskScore = riskStatus?.risk_score || 0;
  const signals = riskStatus?.signals || {};
  const rawSignals = riskStatus?.raw_signals || {};
  const style = LEVEL_STYLES[riskLevel] || LEVEL_STYLES.normal;
  const fusedLevel = fusedData?.fused_level || 'normal';
  const fusedScore = fusedData?.fused_score || 0;
  const fusedStyle = LEVEL_STYLES[fusedLevel] || LEVEL_STYLES.normal;

  const pred = predictive || {};
  const alertLevel = pred.alert_level || 'low';
  const alertBadge = alertLevel === 'high' ? 'bg-red-100 text-red-800' : alertLevel === 'medium' ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-600';

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64" data-testid="safety-brain-loading">
        <Loader2 className="w-8 h-8 animate-spin text-teal-600" />
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="safety-brain-dashboard">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-black text-slate-800 flex items-center gap-2">
            <Brain className="w-6 h-6 text-teal-600" />
            NISCHINT Safety Brain
          </h1>
          <p className="text-sm text-slate-500 mt-1">3-Layer Predictive Safety Intelligence</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={fetchData} className="text-xs" data-testid="refresh-brain-btn">
            <RefreshCw className="w-3.5 h-3.5 mr-1" /> Refresh
          </Button>
          <Button size="sm" onClick={runPredictiveAnalysis} disabled={predictiveLoading}
            className="text-xs bg-teal-600 hover:bg-teal-700" data-testid="run-predictive-btn">
            {predictiveLoading ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> : <TrendingUp className="w-3.5 h-3.5 mr-1" />}
            Run Predictive Analysis
          </Button>
        </div>
      </div>

      {/* TOP ROW: Risk Gauge + 3-Layer Fused Score */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Real-time Risk Gauge */}
        <Card className={`${style.bg} ${style.border} shadow-md`} data-testid="risk-score-card">
          <CardHeader className="pb-2">
            <CardTitle className={`text-sm font-bold ${style.text} flex items-center gap-2`}>
              <Zap className="w-4 h-4" /> Real-time Risk
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col items-center pb-4">
            <RiskGauge score={riskScore} level={riskLevel} />
            {riskStatus?.primary_event && riskStatus.primary_event !== 'none' && (
              <div className="text-xs text-slate-500 mt-2">
                Primary: <span className="font-bold" style={{ color: SIGNAL_META[riskStatus.primary_event]?.color }}>{SIGNAL_META[riskStatus.primary_event]?.label || riskStatus.primary_event}</span>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Signal Breakdown */}
        <Card className="col-span-1 lg:col-span-2 shadow-md" data-testid="signal-breakdown-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-bold text-slate-700 flex items-center gap-2">
              <Activity className="w-4 h-4 text-teal-600" /> Signal Breakdown (with Decay)
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {Object.keys(SIGNAL_META).map(type => (
              <SignalBar key={type} type={type} value={signals[type]} rawValue={rawSignals[type]} />
            ))}
            <div className="text-[10px] text-slate-400 pt-2 border-t border-slate-100">
              Faded bars = raw signal. Solid = decayed value. Weights show contribution to unified score.
            </div>
          </CardContent>
        </Card>
      </div>

      {/* 3-LAYER FUSION BREAKDOWN */}
      {fusedData && (
        <div data-testid="three-layer-section">
          <div className="flex items-center gap-2 mb-3">
            <Layers className="w-5 h-5 text-teal-600" />
            <h2 className="text-lg font-bold text-slate-800">3-Layer Fused Risk</h2>
            <Badge className={fusedStyle.badge} data-testid="fused-risk-badge">{fusedStyle.label} ({Math.round(fusedScore * 100)}%)</Badge>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <LayerCard index={1} title="Real-time Signals" icon={Zap} color="#f59e0b" score={fusedData.layer1_realtime?.score} weight={0.5}>
              {Object.keys(fusedData.layer1_realtime?.signals || {}).length > 0 ? (
                <div className="space-y-1">
                  {Object.entries(fusedData.layer1_realtime.signals).map(([k, v]) => (
                    <div key={k} className="flex justify-between">
                      <span>{SIGNAL_META[k]?.label || k}</span>
                      <span className="font-bold">{Math.round((v || 0) * 100)}%</span>
                    </div>
                  ))}
                </div>
              ) : <span className="text-slate-400">No active signals</span>}
            </LayerCard>

            <LayerCard index={2} title="Location Intelligence" icon={Target} color="#3b82f6" score={fusedData.layer2_location?.score} weight={0.25}>
              <div className="space-y-1">
                <div className="flex justify-between">
                  <span>Incident density</span>
                  <span className="font-bold">{Math.round((fusedData.layer2_location?.details?.incident_density || 0) * 100)}%</span>
                </div>
                <div className="flex justify-between">
                  <span>Time-of-day risk</span>
                  <span className="font-bold">{Math.round((fusedData.layer2_location?.details?.night_time_risk || 0) * 100)}%</span>
                </div>
                <div className="flex justify-between">
                  <span>Recent incidents</span>
                  <span className="font-bold">{fusedData.layer2_location?.details?.recent_incidents || 0}</span>
                </div>
                <div className="flex justify-between">
                  <span>Nearby incidents</span>
                  <span className="font-bold">{fusedData.layer2_location?.details?.nearby_incidents || 0}</span>
                </div>
              </div>
            </LayerCard>

            <LayerCard index={3} title="Behavioral Patterns" icon={Eye} color="#8b5cf6" score={fusedData.layer3_behavior?.score} weight={0.25}>
              {fusedData.layer3_behavior?.skipped ? (
                <span className="text-slate-400">Skipped (fast mode). Click "Run Predictive Analysis" for full analysis.</span>
              ) : fusedData.layer3_behavior?.patterns?.length > 0 ? (
                <div className="space-y-1">
                  {fusedData.layer3_behavior.patterns.slice(0, 3).map((p, i) => (
                    <div key={i} className="flex items-center gap-1">
                      <Badge variant="outline" className="text-[9px]">{p.severity}</Badge>
                      <span>{p.type?.replace(/_/g, ' ')}</span>
                    </div>
                  ))}
                  {fusedData.layer3_behavior.stability && (
                    <div className="pt-1 text-[10px] text-slate-400">Stability: {fusedData.layer3_behavior.stability} | Confidence: {Math.round((fusedData.layer3_behavior.confidence || 0) * 100)}%</div>
                  )}
                </div>
              ) : <span className="text-slate-400">No anomalies detected</span>}
            </LayerCard>
          </div>

          {/* Overrides */}
          {fusedData.overrides?.length > 0 && (
            <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg" data-testid="overrides-section">
              <div className="text-xs font-bold text-red-700 mb-1">Override Rules Applied</div>
              {fusedData.overrides.map((o, i) => (
                <div key={i} className="text-xs text-red-600">{o.reason}</div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* PREDICTIVE ANALYSIS */}
      <Card className={`shadow-md ${pred.alert_level === 'high' ? 'border-red-300 bg-red-50/30' : pred.alert_level === 'medium' ? 'border-amber-300 bg-amber-50/30' : ''}`} data-testid="predictive-section">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-bold text-slate-700 flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-teal-600" /> Predictive Safety Analysis
            </CardTitle>
            {predictive && (
              <Badge className={alertBadge} data-testid="predictive-alert-badge">{alertLevel.toUpperCase()} CONFIDENCE</Badge>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {!predictive ? (
            <div className="text-center py-6">
              <TrendingUp className="w-8 h-8 text-slate-300 mx-auto mb-2" />
              <p className="text-xs text-slate-400">Click "Run Predictive Analysis" to generate AI-powered risk forecast</p>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Confidence & Score */}
              <div className="grid grid-cols-3 gap-3">
                <div className="bg-white rounded-lg p-3 border" data-testid="pred-anomaly-score">
                  <div className="text-[10px] text-slate-400 uppercase tracking-wide">Anomaly Score</div>
                  <div className="text-xl font-black text-slate-800">{Math.round((pred.anomaly_score || 0) * 100)}%</div>
                </div>
                <div className="bg-white rounded-lg p-3 border" data-testid="pred-confidence">
                  <div className="text-[10px] text-slate-400 uppercase tracking-wide">Confidence</div>
                  <div className="text-xl font-black text-slate-800">{pred.confidence_pct || 0}%</div>
                </div>
                <div className="bg-white rounded-lg p-3 border" data-testid="pred-stability">
                  <div className="text-[10px] text-slate-400 uppercase tracking-wide">Stability</div>
                  <div className={`text-xl font-black ${pred.stability === 'high' ? 'text-red-600' : pred.stability === 'medium' ? 'text-amber-600' : 'text-green-600'}`}>
                    {(pred.stability || 'low').toUpperCase()}
                  </div>
                </div>
              </div>

              {/* Behavioral Window Timeline */}
              {pred.window_data && (
                <div data-testid="behavior-timeline">
                  <div className="text-xs font-bold text-slate-600 mb-2 flex items-center gap-1">
                    <Clock className="w-3.5 h-3.5" /> Behavioral Event Timeline
                  </div>
                  <div className="space-y-1.5">
                    {Object.entries(pred.window_data).map(([key, data]) => (
                      <WindowBar key={key} label={key} days={data.days} data={data} />
                    ))}
                  </div>
                  <div className="flex gap-3 mt-2 text-[9px] text-slate-400">
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-purple-500 inline-block" /> Wander</span>
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-orange-500 inline-block" /> Falls</span>
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500 inline-block" /> Voice</span>
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-slate-500 inline-block" /> Safety</span>
                  </div>
                </div>
              )}

              {/* Detected Patterns */}
              {pred.patterns?.length > 0 && (
                <div data-testid="detected-patterns">
                  <div className="text-xs font-bold text-slate-600 mb-2">Detected Patterns</div>
                  <div className="space-y-1.5">
                    {pred.patterns.map((p, i) => (
                      <div key={i} className="flex items-center gap-2 p-2 bg-white rounded border text-xs" data-testid={`pattern-${i}`}>
                        <Badge variant="outline" className={`text-[9px] ${p.severity === 'high' ? 'border-red-300 text-red-700' : 'border-amber-300 text-amber-700'}`}>
                          {p.severity}
                        </Badge>
                        <span className="font-medium text-slate-700">{p.type?.replace(/_/g, ' ')}</span>
                        <span className="text-slate-400">({p.count} events in {p.window} window)</span>
                        {p.peak_hour != null && <span className="text-slate-400 ml-auto">Peak: {p.peak_hour}:00</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* AI Narrative */}
              {pred.narrative && (
                <div data-testid="ai-narrative">
                  <button
                    onClick={() => setShowNarrative(!showNarrative)}
                    className="flex items-center gap-1 text-xs font-bold text-teal-700 hover:text-teal-900 mb-1"
                    data-testid="toggle-narrative-btn"
                  >
                    <Lightbulb className="w-3.5 h-3.5" />
                    AI Safety Narrative (GPT-5.2)
                    {showNarrative ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                  </button>
                  {showNarrative && (
                    <div className="p-3 bg-teal-50 border border-teal-200 rounded-lg text-xs text-slate-700 leading-relaxed whitespace-pre-line" data-testid="narrative-content">
                      {pred.narrative}
                    </div>
                  )}
                </div>
              )}

              {/* Recommendations */}
              {pred.recommendations?.length > 0 && (
                <div data-testid="recommendations">
                  <div className="text-xs font-bold text-slate-600 mb-2 flex items-center gap-1">
                    <Lightbulb className="w-3.5 h-3.5 text-amber-500" /> Recommendations
                  </div>
                  <div className="space-y-1">
                    {pred.recommendations.map((r, i) => (
                      <div key={i} className="p-2 bg-amber-50 border border-amber-100 rounded text-xs text-amber-800" data-testid={`recommendation-${i}`}>
                        {r}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* HEATMAP DATA */}
      {heatmapData?.heatmap?.length > 0 && (
        <Card data-testid="heatmap-data-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-bold text-slate-700 flex items-center gap-2">
              <Target className="w-4 h-4 text-red-500" /> Danger Hotspots ({heatmapData.count} zones)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2">
              {heatmapData.heatmap.slice(0, 10).map((h, i) => (
                <div key={i} className="p-2 bg-white border rounded-lg text-center" data-testid={`hotspot-${i}`}>
                  <div className="text-[10px] text-slate-400">Zone</div>
                  <div className="text-xs font-mono text-slate-600">{h.lat.toFixed(4)}, {h.lng.toFixed(4)}</div>
                  <div className="mt-1 flex items-center justify-center gap-1">
                    <div className="w-2 h-2 rounded-full" style={{ background: `rgba(239, 68, 68, ${h.intensity})` }} />
                    <span className="text-xs font-bold" style={{ color: h.intensity > 0.7 ? '#ef4444' : h.intensity > 0.4 ? '#f97316' : '#64748b' }}>
                      {Math.round(h.intensity * 100)}%
                    </span>
                  </div>
                  <div className="text-[9px] text-slate-400">{h.count} events ({h.recent} recent)</div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Risk Classification Legend */}
      <Card data-testid="risk-levels-legend">
        <CardContent className="p-4">
          <div className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-3">Risk Classification</div>
          <div className="grid grid-cols-4 gap-2">
            {[
              { level: 'Normal', range: '0-30%', action: 'Monitor', color: 'bg-green-500' },
              { level: 'Suspicious', range: '30-60%', action: 'Notify guardian', color: 'bg-amber-500' },
              { level: 'Dangerous', range: '60-85%', action: 'Escalate', color: 'bg-orange-500' },
              { level: 'Critical', range: '85-100%', action: 'Auto SOS', color: 'bg-red-500' },
            ].map(r => (
              <div key={r.level} className="flex items-center gap-2 text-xs" data-testid={`legend-${r.level.toLowerCase()}`}>
                <div className={`w-3 h-3 rounded-full ${r.color}`} />
                <div>
                  <span className="font-bold text-slate-700">{r.level}</span>
                  <span className="text-slate-400 ml-1">({r.range})</span>
                  <div className="text-[10px] text-slate-400">{r.action}</div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Recent Safety Events */}
      <Card data-testid="safety-events-list">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-bold text-slate-700 flex items-center gap-2">
            <Clock className="w-4 h-4" /> Recent Safety Events
          </CardTitle>
        </CardHeader>
        <CardContent>
          {events.length === 0 ? (
            <p className="text-xs text-slate-400 text-center py-6">No safety events recorded</p>
          ) : (
            <div className="space-y-2 max-h-96 overflow-y-auto">
              {events.map((evt, i) => {
                const evtStyle = LEVEL_STYLES[evt.risk_level] || LEVEL_STYLES.normal;
                return (
                  <div key={evt.event_id || i}
                       className={`flex items-center gap-3 p-3 rounded-lg border ${evtStyle.border} ${evtStyle.bg}`}
                       data-testid={`safety-event-${i}`}>
                    <div className="flex flex-col items-center min-w-[50px]">
                      <span className="text-lg font-black" style={{ color: evtStyle.color }}>
                        {Math.round(evt.risk_score * 100)}%
                      </span>
                      <Badge className={`text-[9px] ${evtStyle.badge}`}>{evtStyle.label}</Badge>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-slate-700">Primary: {SIGNAL_META[evt.primary_event]?.label || evt.primary_event}</span>
                        <Badge variant="outline" className="text-[9px]">{evt.status}</Badge>
                      </div>
                      <div className="text-[10px] text-slate-400 mt-0.5">
                        {evt.created_at ? new Date(evt.created_at).toLocaleString() : ''}
                        {' | '}{evt.lat?.toFixed(4)}, {evt.lng?.toFixed(4)}
                      </div>
                      <div className="flex gap-1 mt-1">
                        {Object.entries(evt.signals || {}).filter(([, v]) => v > 0).map(([k, v]) => (
                          <span key={k} className="text-[9px] px-1.5 py-0.5 rounded" style={{ background: `${SIGNAL_META[k]?.color}20`, color: SIGNAL_META[k]?.color }}>
                            {SIGNAL_META[k]?.label}: {Math.round(v * 100)}%
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default SafetyBrainDashboard;
