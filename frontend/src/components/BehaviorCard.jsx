import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { Loader2, Brain, AlertTriangle, Shield, Activity, Clock } from 'lucide-react';
import { operatorApi } from '../api';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts';

const STATUS_CONFIG = {
  normal: { color: 'text-emerald-600', bg: 'bg-emerald-50 border-emerald-200', label: 'Normal', icon: Shield },
  mild: { color: 'text-amber-600', bg: 'bg-amber-50 border-amber-200', label: 'Mild Anomaly', icon: Activity },
  moderate: { color: 'text-orange-600', bg: 'bg-orange-50 border-orange-200', label: 'Moderate Anomaly', icon: AlertTriangle },
  critical: { color: 'text-red-600', bg: 'bg-red-50 border-red-200', label: 'Critical', icon: AlertTriangle },
};

const ANOMALY_TYPE_LABELS = {
  extended_inactivity: 'Extended Inactivity',
  low_interaction: 'Low Interaction',
  movement_drop: 'Movement Drop',
  unusual_movement: 'Unusual Movement',
  hyperactivity: 'Hyperactivity',
  routine_break: 'Routine Break',
  twin_active_expected: 'Twin: Active Expected',
  twin_inactivity_exceeded: 'Twin: Inactivity Exceeded',
  twin_sleep_disruption: 'Twin: Sleep Disruption',
  expected_inactivity: 'Expected Rest',
};

function BaselineTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
  return (
    <div className="bg-white/95 backdrop-blur border border-slate-200 rounded-lg px-3 py-2 shadow-lg text-xs">
      <p className="text-slate-400 mb-1">Hour {d.hour}:00</p>
      <p>Movement: <span className="font-medium">{d.avg_movement}</span></p>
      <p>Interaction: <span className="font-medium">{d.avg_interaction_rate}/30min</span></p>
      <p className="text-slate-400 text-[10px]">{d.sample_count} samples</p>
    </div>
  );
}

export default function BehaviorCard({ deviceId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!deviceId) return;
    setLoading(true);
    operatorApi.getDeviceBehaviorPattern(deviceId, 168)
      .then(res => setData(res.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [deviceId]);

  if (loading) {
    return (
      <Card data-testid="behavior-card-loading">
        <CardContent className="flex items-center justify-center py-6">
          <Loader2 className="w-4 h-4 animate-spin text-slate-400 mr-2" />
          <span className="text-sm text-slate-400">Analyzing behavior...</span>
        </CardContent>
      </Card>
    );
  }

  if (!data) return null;

  const risk = data.current_risk;
  const statusCfg = STATUS_CONFIG[risk.status] || STATUS_CONFIG.normal;
  const StatusIcon = statusCfg.icon;
  const hasBaseline = data.baseline_profile?.length > 0;
  const hasAnomalies = data.recent_anomalies?.length > 0;

  return (
    <Card className={`border ${statusCfg.bg.split(' ')[1]}`} data-testid="behavior-card">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold text-slate-700 flex items-center gap-2">
            <Brain className="w-4 h-4 text-indigo-500" /> Behavior Pattern AI
          </CardTitle>
          <Badge
            variant="outline"
            className={`text-xs ${statusCfg.color} border-current`}
            data-testid="behavior-status-badge"
          >
            <StatusIcon className="w-3 h-3 mr-1" />
            {statusCfg.label}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Risk Score */}
        <div className={`rounded-lg p-3 ${statusCfg.bg.split(' ')[0]}`} data-testid="behavior-risk-panel">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] uppercase tracking-wide text-slate-400">Current Risk</span>
            <span className={`text-xl font-bold ${statusCfg.color}`} data-testid="behavior-risk-score">
              {(risk.score * 100).toFixed(0)}%
            </span>
          </div>
          <p className="text-xs text-slate-600" data-testid="behavior-risk-reason">{risk.reason}</p>
          {risk.twin_aware && data.twin_context && (
            <div className="flex items-center gap-1.5 mt-1.5" data-testid="behavior-twin-context">
              <Badge variant="outline" className="text-[10px] bg-indigo-50 text-indigo-600 border-indigo-200">
                Twin-Aware
              </Badge>
              {data.twin_context.expected_active_now !== null && (
                <span className="text-[10px] text-slate-500">
                  {data.twin_context.expected_active_now ? 'Expected Active' : 'Expected Rest'}
                </span>
              )}
              {data.twin_context.personality_tag && (
                <span className="text-[10px] text-indigo-400">{data.twin_context.personality_tag}</span>
              )}
            </div>
          )}
          {data.inactivity_minutes !== null && (
            <div className="flex items-center gap-1 mt-1.5">
              <Clock className="w-3 h-3 text-slate-400" />
              <span className="text-[10px] text-slate-400">
                Last heartbeat: {data.inactivity_minutes < 60
                  ? `${Math.round(data.inactivity_minutes)} min ago`
                  : `${(data.inactivity_minutes / 60).toFixed(1)}h ago`}
              </span>
            </div>
          )}
        </div>

        {/* Baseline Profile Chart */}
        {hasBaseline && (
          <div data-testid="behavior-baseline-chart">
            <p className="text-[10px] font-bold tracking-[0.15em] text-slate-400 uppercase mb-1">
              24h Activity Baseline
            </p>
            <ResponsiveContainer width="100%" height={60}>
              <BarChart data={_buildFullProfile(data.baseline_profile)} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
                <XAxis dataKey="hour" tick={{ fontSize: 8, fill: '#94a3b8' }} tickLine={false} axisLine={false} interval={5} />
                <YAxis hide />
                <Tooltip content={<BaselineTooltip />} />
                <Bar dataKey="avg_interaction_rate" fill="#818cf8" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Recent Anomalies */}
        {hasAnomalies && (
          <div data-testid="behavior-anomalies-list">
            <p className="text-[10px] font-bold tracking-[0.15em] text-slate-400 uppercase mb-1.5">
              Recent Anomalies ({data.total_anomalies_in_window})
            </p>
            <div className="space-y-1.5 max-h-[120px] overflow-y-auto">
              {data.recent_anomalies.slice(0, 5).map((a, i) => (
                <div key={i} className="flex items-start gap-2 text-xs p-1.5 rounded bg-white/60" data-testid={`behavior-anomaly-${i}`}>
                  <Badge variant="outline" className="text-[10px] shrink-0 mt-0.5">
                    {(a.behavior_score * 100).toFixed(0)}%
                  </Badge>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-slate-700">{ANOMALY_TYPE_LABELS[a.anomaly_type] || a.anomaly_type}</p>
                    <p className="text-[10px] text-slate-400 truncate">{a.reason}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function _buildFullProfile(profile) {
  // Build a 24-hour array filling missing hours with 0
  const hourMap = {};
  profile.forEach(p => { hourMap[p.hour] = p; });
  return Array.from({ length: 24 }, (_, i) => hourMap[i] || {
    hour: i, avg_movement: 0, avg_location_switch: 0, avg_interaction_rate: 0, sample_count: 0,
  });
}
