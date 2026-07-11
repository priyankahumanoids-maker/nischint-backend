import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { operatorApi } from '../api';
import { toast } from 'sonner';
import {
  TrendingDown, Moon, MapPin, HeartPulse, Loader2, AlertTriangle,
  Clock, ChevronDown,
} from 'lucide-react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine,
} from 'recharts';

const PREDICTION_META = {
  activity_decline: {
    label: 'Activity Decline', icon: TrendingDown, color: 'text-orange-600',
    bg: 'bg-orange-50 border-orange-200', badge: 'bg-orange-100 text-orange-700',
    chartColor: '#f97316',
  },
  sleep_disruption: {
    label: 'Sleep Disruption', icon: Moon, color: 'text-indigo-600',
    bg: 'bg-indigo-50 border-indigo-200', badge: 'bg-indigo-100 text-indigo-700',
    chartColor: '#6366f1',
  },
  wandering_risk: {
    label: 'Wandering Risk', icon: MapPin, color: 'text-purple-600',
    bg: 'bg-purple-50 border-purple-200', badge: 'bg-purple-100 text-purple-700',
    chartColor: '#9333ea',
  },
  health_decline: {
    label: 'Health Decline', icon: HeartPulse, color: 'text-red-600',
    bg: 'bg-red-50 border-red-200', badge: 'bg-red-100 text-red-700',
    chartColor: '#ef4444',
  },
};

function PredictionItem({ prediction }) {
  const [expanded, setExpanded] = useState(false);
  const meta = PREDICTION_META[prediction.prediction_type] || PREDICTION_META.health_decline;
  const Icon = meta.icon;
  const isAlert = prediction.meets_alert_threshold ?? (prediction.prediction_score >= 0.7 && prediction.confidence >= 0.6);

  const trendData = prediction.trend_data || {};
  const days = trendData.days || [];
  const chartData = days.map((day, i) => ({
    day: day?.slice(5) || `D${i}`,
    movement: trendData.daily_movement?.[i] ?? 0,
    interaction: trendData.daily_interaction?.[i] ?? 0,
  }));

  return (
    <div className={`rounded-lg border p-3 ${isAlert ? meta.bg : 'bg-slate-50 border-slate-200'}`}
      data-testid={`prediction-${prediction.prediction_type}`}>
      <div className="flex items-center justify-between cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <div className="flex items-center gap-2">
          <Icon className={`w-4 h-4 ${meta.color}`} />
          <span className="text-sm font-semibold text-slate-800">{meta.label}</span>
          <Badge variant="outline" className={`text-[10px] ${meta.badge}`}>
            {(prediction.prediction_score * 100).toFixed(0)}% risk
          </Badge>
          {isAlert && (
            <Badge variant="outline" className="text-[10px] bg-red-100 text-red-700 border-red-300">
              <AlertTriangle className="w-2.5 h-2.5 mr-0.5" /> Alert
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <Clock className="w-3 h-3" />
          <span>{prediction.prediction_window_hours}h window</span>
          <span className="text-slate-300">|</span>
          <span>{(prediction.confidence * 100).toFixed(0)}% conf</span>
          <ChevronDown className={`w-3 h-3 transition-transform ${expanded ? 'rotate-180' : ''}`} />
        </div>
      </div>

      <p className="text-xs text-slate-600 mt-1.5" data-testid={`prediction-explanation-${prediction.prediction_type}`}>
        {prediction.explanation}
      </p>

      {expanded && chartData.length > 0 && (
        <div className="mt-3 h-[120px]" data-testid={`prediction-chart-${prediction.prediction_type}`}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 5, right: 5, left: -20, bottom: 5 }}>
              <defs>
                <linearGradient id={`grad-${prediction.prediction_type}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={meta.chartColor} stopOpacity={0.3} />
                  <stop offset="100%" stopColor={meta.chartColor} stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="day" tick={{ fontSize: 9 }} />
              <YAxis tick={{ fontSize: 9 }} />
              <Tooltip content={<TrendTooltip />} />
              <Area type="monotone" dataKey="movement" name="Movement"
                stroke={meta.chartColor} fill={`url(#grad-${prediction.prediction_type})`}
                strokeWidth={2} dot={false} />
              {trendData.daily_interaction && (
                <Area type="monotone" dataKey="interaction" name="Interaction"
                  stroke="#94a3b8" fill="none" strokeWidth={1} strokeDasharray="3 3" dot={false} />
              )}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

function TrendTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white/95 backdrop-blur border rounded-lg shadow-lg p-2 text-xs">
      <p className="font-semibold text-slate-700">{label}</p>
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color }}>{p.name}: {p.value?.toFixed(2)}</p>
      ))}
    </div>
  );
}

export function PredictiveRiskCard({ deviceId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetch = useCallback(async () => {
    if (!deviceId) return;
    setLoading(true);
    try {
      const res = await operatorApi.getDevicePredictiveRisk(deviceId);
      setData(res.data);
    } catch {
      // Silent — predictive data is supplementary
    } finally {
      setLoading(false);
    }
  }, [deviceId]);

  useEffect(() => { fetch(); }, [fetch]);

  if (loading) {
    return (
      <Card className="border border-amber-100">
        <CardContent className="p-4 flex items-center justify-center gap-2 text-slate-400">
          <Loader2 className="w-4 h-4 animate-spin" /> Analyzing trends...
        </CardContent>
      </Card>
    );
  }

  if (!data) return null;

  const predictions = data.live_predictions || [];
  const alerts = predictions.filter(p => p.meets_alert_threshold);

  if (predictions.length === 0) {
    return (
      <Card className="border border-slate-200" data-testid="predictive-no-data">
        <CardContent className="p-4 text-center text-slate-400 text-xs">
          <TrendingDown className="w-6 h-6 mx-auto mb-1 opacity-30" />
          Insufficient trend data for predictions
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className={`border ${alerts.length > 0 ? 'border-amber-300 bg-gradient-to-br from-white to-amber-50/30' : 'border-slate-200'}`}
      data-testid="predictive-risk-card">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <TrendingDown className="w-4 h-4 text-amber-600" />
            <CardTitle className="text-sm">Predictive Risk</CardTitle>
            {alerts.length > 0 && (
              <Badge variant="outline" className="text-[10px] bg-amber-100 text-amber-700 border-amber-300">
                {alerts.length} alert{alerts.length > 1 ? 's' : ''}
              </Badge>
            )}
          </div>
          <span className="text-[10px] text-slate-400">{predictions.length} signal{predictions.length > 1 ? 's' : ''}</span>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {predictions.map((p, i) => (
          <PredictionItem key={i} prediction={p} />
        ))}
      </CardContent>
    </Card>
  );
}
