import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  Brain, TrendingUp, Shield, AlertTriangle, Loader2, RefreshCw,
  Zap, Phone, BellRing, Eye, Clock, ChevronDown, ChevronUp,
  CheckCircle, XCircle, Save, Activity, Target, Sliders,
  History, Lightbulb, MapPin,
} from 'lucide-react';
import api from '../api';
import { toast } from 'sonner';

const LEVEL_STYLES = {
  low: { bg: 'bg-green-50', border: 'border-green-300', text: 'text-green-700', badge: 'bg-green-100 text-green-800', color: '#22c55e', label: 'LOW' },
  moderate: { bg: 'bg-amber-50', border: 'border-amber-300', text: 'text-amber-700', badge: 'bg-amber-100 text-amber-800', color: '#f59e0b', label: 'MODERATE' },
  high: { bg: 'bg-orange-50', border: 'border-orange-300', text: 'text-orange-700', badge: 'bg-orange-100 text-orange-800', color: '#f97316', label: 'HIGH' },
  critical: { bg: 'bg-red-50', border: 'border-red-300', text: 'text-red-700', badge: 'bg-red-100 text-red-800', color: '#ef4444', label: 'CRITICAL' },
};

const ACTION_META = {
  monitor: { icon: Eye, color: '#22c55e', label: 'Monitor' },
  fake_notification: { icon: BellRing, color: '#7c3aed', label: 'Escape Notification' },
  fake_call: { icon: Phone, color: '#2563eb', label: 'Escape Call' },
  sos_prearm: { icon: Shield, color: '#ef4444', label: 'Pre-arm SOS' },
};

const LayerScoreBar = ({ label, icon: Icon, score, color, children }) => {
  const pct = Math.round((score || 0) * 100);
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-slate-600 flex items-center gap-1">
          <Icon className="w-3.5 h-3.5" style={{ color }} /> {label}
        </span>
        <span className="text-xs font-bold" style={{ color }}>{pct}%</span>
      </div>
      <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all duration-700" style={{ width: `${pct}%`, background: color }} />
      </div>
      {children}
    </div>
  );
};

const GuardianAIPage = ({ latestAlert }) => {
  const [config, setConfig] = useState(null);
  const [editConfig, setEditConfig] = useState(null);
  const [prediction, setPrediction] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [predicting, setPredicting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [cfgRes, histRes] = await Promise.all([
        api.get('/guardian-ai/config'),
        api.get('/guardian-ai/history?limit=15'),
      ]);
      setConfig(cfgRes.data);
      setEditConfig(cfgRes.data);
      const preds = histRes.data?.predictions || [];
      setHistory(preds);
      if (preds.length > 0 && !prediction) setPrediction(preds[0]);
    } catch {
      toast.error('Failed to load Guardian AI data');
    } finally {
      setLoading(false);
    }
  }, [prediction]);

  useEffect(() => { fetchData(); }, [fetchData]);

  useEffect(() => {
    if (latestAlert) setPrediction(latestAlert);
  }, [latestAlert]);

  const runPrediction = async () => {
    setPredicting(true);
    try {
      const res = await api.post('/guardian-ai/predict-risk', { lat: 28.6139, lng: 77.2090 });
      setPrediction(res.data);
      fetchData();
      toast.success('Prediction complete');
    } catch {
      toast.error('Prediction failed');
    } finally {
      setPredicting(false);
    }
  };

  const handleAction = async (predId, action) => {
    try {
      const endpoint = action === 'accept' ? 'accept-action' : 'dismiss';
      await api.post(`/guardian-ai/${endpoint}/${predId}`);
      toast.success(action === 'accept' ? 'Action accepted — triggering escape sequence' : 'Prediction dismissed');
      fetchData();
    } catch {
      toast.error('Failed to respond');
    }
  };

  const handleSave = async () => {
    if (!editConfig) return;
    setSaving(true);
    try {
      const res = await api.put('/guardian-ai/config', {
        enabled: editConfig.enabled,
        sensitivity: editConfig.sensitivity,
        notification_threshold: editConfig.notification_threshold,
        call_threshold: editConfig.call_threshold,
        sos_threshold: editConfig.sos_threshold,
        auto_trigger: editConfig.auto_trigger,
        cooldown_minutes: editConfig.cooldown_minutes,
      });
      setConfig(res.data);
      toast.success('Configuration saved');
    } catch {
      toast.error('Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const updateField = (key, value) => setEditConfig(p => ({ ...p, [key]: value }));

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64" data-testid="guardian-ai-loading">
        <Loader2 className="w-8 h-8 animate-spin text-teal-600" />
      </div>
    );
  }

  const pred = prediction || {};
  const style = LEVEL_STYLES[pred.risk_level] || LEVEL_STYLES.low;
  const actionMeta = ACTION_META[pred.recommended_action] || ACTION_META.monitor;
  const ActionIcon = actionMeta.icon;
  const layers = pred.layer_scores || {};

  return (
    <div className="space-y-6" data-testid="guardian-ai-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-black text-slate-800 flex items-center gap-2">
            <Brain className="w-6 h-6 text-teal-600" />
            Guardian AI
          </h1>
          <p className="text-sm text-slate-500 mt-1">Predictive intelligence — forecasts risk before it happens</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={handleSave} disabled={saving} className="text-xs" data-testid="save-guardian-config-btn">
            {saving ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> : <Save className="w-3.5 h-3.5 mr-1" />}
            Save
          </Button>
          <Button size="sm" onClick={runPrediction} disabled={predicting} className="text-xs bg-teal-600 hover:bg-teal-700" data-testid="run-prediction-btn">
            {predicting ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> : <TrendingUp className="w-3.5 h-3.5 mr-1" />}
            Run Prediction
          </Button>
        </div>
      </div>

      {/* Prediction Result */}
      {prediction ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Risk Score Card */}
          <Card className={`${style.bg} ${style.border} shadow-md`} data-testid="prediction-score-card">
            <CardContent className="p-5 flex flex-col items-center">
              <div className="relative w-28 h-28 rounded-full border-4 flex items-center justify-center mb-3" style={{ borderColor: style.color }}>
                <div className="text-3xl font-black" style={{ color: style.color }}>{Math.round(pred.risk_score * 100)}%</div>
              </div>
              <Badge className={`${style.badge} text-xs font-bold`} data-testid="prediction-level-badge">{style.label} RISK</Badge>
              <div className="text-xs text-slate-500 mt-2">Confidence: {Math.round((pred.confidence || 0) * 100)}%</div>
              {pred.lat && (
                <div className="text-[10px] text-slate-400 mt-1 flex items-center gap-1">
                  <MapPin className="w-3 h-3" /> {pred.lat?.toFixed(4)}, {pred.lng?.toFixed(4)}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Recommended Action */}
          <Card className="shadow-md" data-testid="recommended-action-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-bold text-slate-700">Recommended Action</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-3 p-3 rounded-lg border mb-3" style={{ borderColor: actionMeta.color, background: `${actionMeta.color}08` }}>
                <div className="w-10 h-10 rounded-full flex items-center justify-center" style={{ background: `${actionMeta.color}15` }}>
                  <ActionIcon className="w-5 h-5" style={{ color: actionMeta.color }} />
                </div>
                <div>
                  <div className="text-sm font-bold text-slate-800">{actionMeta.label}</div>
                  <div className="text-xs text-slate-500">{pred.action_detail?.action}</div>
                  {pred.action_detail?.urgency && (
                    <Badge variant="outline" className="text-[9px] mt-1" style={{ borderColor: actionMeta.color, color: actionMeta.color }}>
                      {pred.action_detail.urgency} urgency
                    </Badge>
                  )}
                </div>
              </div>
              {pred.status === 'pending' && (
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => handleAction(pred.id, 'accept')} className="flex-1 text-xs bg-teal-600 hover:bg-teal-700 text-white" data-testid="accept-action-btn">
                    <CheckCircle className="w-3.5 h-3.5 mr-1" /> Accept
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => handleAction(pred.id, 'dismiss')} className="flex-1 text-xs" data-testid="dismiss-action-btn">
                    <XCircle className="w-3.5 h-3.5 mr-1" /> Dismiss
                  </Button>
                </div>
              )}
              {pred.status !== 'pending' && (
                <Badge className={`text-[10px] ${pred.status === 'accepted' ? 'bg-green-100 text-green-700' : pred.status === 'dismissed' ? 'bg-slate-100 text-slate-600' : 'bg-blue-100 text-blue-700'}`}>
                  {pred.status}
                </Badge>
              )}
            </CardContent>
          </Card>

          {/* Layer Breakdown */}
          <Card className="shadow-md" data-testid="layer-breakdown-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-bold text-slate-700">Layer Breakdown</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <LayerScoreBar label="Real-time (50%)" icon={Zap} score={layers.realtime?.score} color="#f59e0b">
                {layers.realtime?.primary_event && layers.realtime.primary_event !== 'none' && (
                  <span className="text-[10px] text-slate-400">Primary: {layers.realtime.primary_event}</span>
                )}
              </LayerScoreBar>
              <LayerScoreBar label="Location (25%)" icon={Target} score={layers.location?.score} color="#3b82f6">
                {layers.location?.nearby_incidents > 0 && (
                  <span className="text-[10px] text-slate-400">{layers.location.nearby_incidents} nearby incidents</span>
                )}
              </LayerScoreBar>
              <LayerScoreBar label="Behavioral (25%)" icon={Activity} score={layers.behavioral?.score} color="#8b5cf6">
                {layers.behavioral?.stability && (
                  <span className="text-[10px] text-slate-400">Stability: {layers.behavioral.stability}</span>
                )}
              </LayerScoreBar>
            </CardContent>
          </Card>
        </div>
      ) : (
        <Card className="border-dashed" data-testid="no-prediction-card">
          <CardContent className="p-8 text-center">
            <TrendingUp className="w-10 h-10 text-slate-300 mx-auto mb-3" />
            <p className="text-sm text-slate-400">Click "Run Prediction" to analyze current risk</p>
          </CardContent>
        </Card>
      )}

      {/* Risk Factors + Narrative */}
      {prediction && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Risk Factors */}
          <Card data-testid="risk-factors-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-bold text-slate-700 flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-500" /> Risk Factors
              </CardTitle>
            </CardHeader>
            <CardContent>
              {(pred.risk_factors || []).length === 0 ? (
                <p className="text-xs text-slate-400 text-center py-4">No significant risk factors detected</p>
              ) : (
                <div className="space-y-2">
                  {pred.risk_factors.map((f, i) => (
                    <div key={i} className="flex items-start gap-2 p-2 rounded-lg bg-slate-50 border" data-testid={`risk-factor-${i}`}>
                      <Badge variant="outline" className={`text-[9px] mt-0.5 ${f.severity === 'high' ? 'border-red-300 text-red-700' : 'border-amber-300 text-amber-700'}`}>
                        {f.severity}
                      </Badge>
                      <div>
                        <div className="text-xs font-semibold text-slate-700">{f.type?.replace(/_/g, ' ')}</div>
                        <div className="text-[10px] text-slate-500">{f.detail}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* AI Narrative */}
          <Card data-testid="ai-narrative-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-bold text-slate-700 flex items-center gap-2">
                <Lightbulb className="w-4 h-4 text-teal-600" /> AI Narrative
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="p-3 bg-teal-50 border border-teal-200 rounded-lg text-xs text-slate-700 leading-relaxed whitespace-pre-line" data-testid="narrative-text">
                {pred.narrative || 'No narrative available'}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Sensitivity Config */}
      {editConfig && (
        <Card data-testid="sensitivity-config-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-bold text-slate-700 flex items-center gap-2">
              <Sliders className="w-4 h-4 text-teal-600" /> Sensitivity & Thresholds
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {/* Sensitivity */}
              <div>
                <label className="text-[10px] text-slate-500 font-semibold uppercase">Sensitivity</label>
                <select value={editConfig.sensitivity} onChange={e => updateField('sensitivity', e.target.value)}
                  className="mt-1 w-full px-3 py-2 text-sm border rounded-lg" data-testid="sensitivity-select">
                  <option value="low">Low (conservative)</option>
                  <option value="medium">Medium (balanced)</option>
                  <option value="high">High (aggressive)</option>
                </select>
              </div>
              {/* Notification Threshold */}
              <div>
                <label className="text-[10px] text-slate-500 font-semibold uppercase">Notification Threshold</label>
                <div className="flex items-center gap-2 mt-1">
                  <input type="range" min="0" max="100" value={Math.round(editConfig.notification_threshold * 100)}
                    onChange={e => updateField('notification_threshold', parseInt(e.target.value) / 100)}
                    className="flex-1" data-testid="notif-threshold-slider" />
                  <span className="text-xs font-bold text-slate-600 w-10 text-right">{Math.round(editConfig.notification_threshold * 100)}%</span>
                </div>
              </div>
              {/* Call Threshold */}
              <div>
                <label className="text-[10px] text-slate-500 font-semibold uppercase">Call Threshold</label>
                <div className="flex items-center gap-2 mt-1">
                  <input type="range" min="0" max="100" value={Math.round(editConfig.call_threshold * 100)}
                    onChange={e => updateField('call_threshold', parseInt(e.target.value) / 100)}
                    className="flex-1" data-testid="call-threshold-slider" />
                  <span className="text-xs font-bold text-slate-600 w-10 text-right">{Math.round(editConfig.call_threshold * 100)}%</span>
                </div>
              </div>
              {/* SOS Threshold */}
              <div>
                <label className="text-[10px] text-slate-500 font-semibold uppercase">SOS Threshold</label>
                <div className="flex items-center gap-2 mt-1">
                  <input type="range" min="0" max="100" value={Math.round(editConfig.sos_threshold * 100)}
                    onChange={e => updateField('sos_threshold', parseInt(e.target.value) / 100)}
                    className="flex-1" data-testid="sos-threshold-slider" />
                  <span className="text-xs font-bold text-slate-600 w-10 text-right">{Math.round(editConfig.sos_threshold * 100)}%</span>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-6 mt-4 pt-3 border-t">
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={editConfig.enabled} onChange={e => updateField('enabled', e.target.checked)}
                  className="w-4 h-4 rounded text-teal-600" data-testid="guardian-enabled-toggle" />
                <span className="text-xs font-bold text-slate-700">AI Enabled</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={editConfig.auto_trigger} onChange={e => updateField('auto_trigger', e.target.checked)}
                  className="w-4 h-4 rounded text-teal-600" data-testid="auto-trigger-toggle" />
                <span className="text-xs font-bold text-slate-700">Auto-trigger Actions</span>
              </label>
              <div className="flex items-center gap-2">
                <Clock className="w-3.5 h-3.5 text-slate-400" />
                <span className="text-[10px] text-slate-500">Cooldown:</span>
                <input type="number" min="5" max="1440" value={editConfig.cooldown_minutes}
                  onChange={e => updateField('cooldown_minutes', parseInt(e.target.value) || 30)}
                  className="w-16 px-2 py-1 text-xs border rounded" data-testid="cooldown-input" />
                <span className="text-[10px] text-slate-400">min</span>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Prediction History */}
      <Card data-testid="prediction-history-card">
        <CardHeader className="pb-2 cursor-pointer" onClick={() => setShowHistory(!showHistory)}>
          <CardTitle className="text-sm font-bold text-slate-700 flex items-center gap-2">
            <History className="w-4 h-4" /> Prediction History ({history.length})
            {showHistory ? <ChevronUp className="w-4 h-4 ml-auto" /> : <ChevronDown className="w-4 h-4 ml-auto" />}
          </CardTitle>
        </CardHeader>
        {showHistory && (
          <CardContent>
            {history.length === 0 ? (
              <p className="text-xs text-slate-400 text-center py-4">No predictions yet</p>
            ) : (
              <div className="space-y-2">
                {history.map(h => {
                  const hStyle = LEVEL_STYLES[h.risk_level] || LEVEL_STYLES.low;
                  const hAction = ACTION_META[h.recommended_action] || ACTION_META.monitor;
                  const HIcon = hAction.icon;
                  return (
                    <div key={h.id} className={`flex items-center gap-3 p-3 rounded-lg border ${hStyle.border} ${hStyle.bg}`} data-testid={`pred-history-${h.id}`}>
                      <div className="flex flex-col items-center min-w-[50px]">
                        <span className="text-lg font-black" style={{ color: hStyle.color }}>{Math.round(h.risk_score * 100)}%</span>
                        <Badge className={`text-[9px] ${hStyle.badge}`}>{hStyle.label}</Badge>
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <HIcon className="w-3.5 h-3.5" style={{ color: hAction.color }} />
                          <span className="text-xs font-bold text-slate-700">{hAction.label}</span>
                          <Badge variant="outline" className={`text-[9px] ${h.status === 'accepted' ? 'border-green-300 text-green-700' : h.status === 'dismissed' ? 'border-slate-300 text-slate-500' : 'border-blue-300 text-blue-700'}`}>
                            {h.status}
                          </Badge>
                        </div>
                        <div className="text-[10px] text-slate-400 mt-0.5">
                          {new Date(h.created_at).toLocaleString()} | Confidence: {Math.round(h.confidence * 100)}%
                          {h.risk_factors?.length > 0 && ` | ${h.risk_factors.length} factors`}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        )}
      </Card>
    </div>
  );
};

export default GuardianAIPage;
