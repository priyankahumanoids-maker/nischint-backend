import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { operatorApi } from '../api';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts';
import {
  TrendingDown, TrendingUp, Minus, Loader2, Activity, Clock,
  AlertTriangle, Heart, Battery, Wifi, Brain,
} from 'lucide-react';

const METRICS = [
  { key: 'movement_frequency', label: 'Movement', color: '#8b5cf6', icon: Activity },
  { key: 'active_hours', label: 'Active Hours', color: '#06b6d4', icon: Clock },
  { key: 'avg_inactivity_minutes', label: 'Inactivity', color: '#f97316', icon: Minus },
  { key: 'avg_battery', label: 'Battery', color: '#22c55e', icon: Battery },
  { key: 'avg_signal', label: 'Signal', color: '#3b82f6', icon: Wifi },
  { key: 'anomaly_count', label: 'Anomalies', color: '#ef4444', icon: AlertTriangle },
];

const SHIFT_SEVERITY = {
  high: { bg: 'bg-red-50', border: 'border-red-200', text: 'text-red-700', badge: 'bg-red-100 text-red-700' },
  medium: { bg: 'bg-amber-50', border: 'border-amber-200', text: 'text-amber-700', badge: 'bg-amber-100 text-amber-700' },
};

function TrendIcon({ direction }) {
  if (direction === 'increasing') return <TrendingUp className="w-3 h-3 text-amber-500" />;
  if (direction === 'decreasing') return <TrendingDown className="w-3 h-3 text-red-500" />;
  return <Minus className="w-3 h-3 text-slate-400" />;
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-slate-200 rounded-lg shadow-lg p-3 text-xs">
      <p className="font-semibold text-slate-700 mb-1">{label}</p>
      {payload.map((p) => (
        <div key={p.dataKey} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: p.color }} />
          <span className="text-slate-600">{p.name}: <b>{typeof p.value === 'number' ? p.value.toFixed(1) : p.value}</b></span>
        </div>
      ))}
    </div>
  );
}

export function TwinEvolutionTimeline({ deviceId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeMetrics, setActiveMetrics] = useState(['movement_frequency', 'active_hours']);

  const fetchEvolution = useCallback(async () => {
    if (!deviceId) return;
    setLoading(true);
    try {
      const res = await operatorApi.getTwinEvolution(deviceId);
      setData(res.data);
    } catch {
      // supplementary
    } finally {
      setLoading(false);
    }
  }, [deviceId]);

  useEffect(() => { fetchEvolution(); }, [fetchEvolution]);

  const toggleMetric = (key) => {
    setActiveMetrics((prev) =>
      prev.includes(key) ? prev.filter((m) => m !== key) : [...prev, key]
    );
  };

  if (loading) {
    return (
      <Card className="border border-slate-200">
        <CardContent className="p-4 flex items-center justify-center gap-2 text-slate-400">
          <Loader2 className="w-4 h-4 animate-spin" /> Analyzing behavioral evolution...
        </CardContent>
      </Card>
    );
  }

  if (!data || !data.snapshots || data.snapshots.length === 0) {
    return (
      <Card className="border border-slate-200">
        <CardContent className="p-4 text-center text-sm text-slate-400">
          <Brain className="w-5 h-5 mx-auto mb-1 text-slate-300" />
          Insufficient data for evolution analysis
        </CardContent>
      </Card>
    );
  }

  const { snapshots, trends, shifts, interpretation } = data;
  const hasShifts = shifts && shifts.length > 0;
  const highShifts = shifts?.filter((s) => s.severity === 'high') || [];

  return (
    <Card
      className={`border ${hasShifts ? (highShifts.length > 0 ? 'border-red-200 bg-gradient-to-br from-white to-red-50/10' : 'border-amber-200') : 'border-slate-200'}`}
      data-testid="twin-evolution-card"
    >
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Heart className="w-4 h-4 text-rose-500" />
            <CardTitle className="text-sm">Twin Evolution Timeline</CardTitle>
            <Badge className="bg-slate-100 text-slate-600 text-[10px] border border-slate-200">
              {data.weeks_analyzed} weeks
            </Badge>
            {highShifts.length > 0 && (
              <Badge className="bg-red-100 text-red-700 border border-red-200 text-[10px]">
                <AlertTriangle className="w-2.5 h-2.5 mr-0.5" />
                {highShifts.length} shift{highShifts.length > 1 ? 's' : ''} detected
              </Badge>
            )}
          </div>
          <span className="text-[10px] text-slate-400">{data.device_identifier}</span>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* Metric toggles */}
        <div className="flex flex-wrap gap-1.5" data-testid="evolution-metric-toggles">
          {METRICS.map((m) => {
            const active = activeMetrics.includes(m.key);
            const Icon = m.icon;
            return (
              <Button
                key={m.key}
                variant={active ? 'default' : 'outline'}
                size="sm"
                className={`h-6 px-2 text-[10px] gap-1 ${active ? '' : 'opacity-50'}`}
                style={active ? { backgroundColor: m.color, borderColor: m.color } : {}}
                onClick={() => toggleMetric(m.key)}
                data-testid={`toggle-${m.key}`}
              >
                <Icon className="w-2.5 h-2.5" /> {m.label}
              </Button>
            );
          })}
        </div>

        {/* Chart */}
        <div className="h-48" data-testid="evolution-chart">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={snapshots} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis
                dataKey="week_label"
                tick={{ fontSize: 10, fill: '#94a3b8' }}
                axisLine={{ stroke: '#e2e8f0' }}
              />
              <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} axisLine={{ stroke: '#e2e8f0' }} />
              <Tooltip content={<CustomTooltip />} />
              {activeMetrics.map((key) => {
                const metric = METRICS.find((m) => m.key === key);
                if (!metric) return null;
                return (
                  <Line
                    key={key}
                    type="monotone"
                    dataKey={key}
                    name={metric.label}
                    stroke={metric.color}
                    strokeWidth={2}
                    dot={{ r: 3, fill: metric.color }}
                    activeDot={{ r: 5 }}
                    connectNulls
                  />
                );
              })}
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Shift Detections */}
        {hasShifts && (
          <div className="space-y-1.5" data-testid="evolution-shifts">
            <p className="text-xs font-semibold text-slate-600 flex items-center gap-1">
              <AlertTriangle className="w-3 h-3 text-amber-500" /> Behavioral Shifts Detected
            </p>
            {shifts.map((s, i) => {
              const sev = SHIFT_SEVERITY[s.severity] || SHIFT_SEVERITY.medium;
              return (
                <div key={i} className={`flex items-center gap-2 px-3 py-2 rounded-md border text-xs ${sev.bg} ${sev.border}`}
                  data-testid={`shift-${s.metric}`}>
                  {s.type === 'decline' ? (
                    <TrendingDown className={`w-3.5 h-3.5 ${sev.text} shrink-0`} />
                  ) : (
                    <TrendingUp className={`w-3.5 h-3.5 ${sev.text} shrink-0`} />
                  )}
                  <div className="flex-1">
                    <span className={`font-semibold ${sev.text}`}>{s.interpretation}</span>
                    <span className="text-slate-500 ml-1.5">
                      {s.label}: {s.from_value} → {s.to_value} ({s.change_percent > 0 ? '+' : ''}{s.change_percent}%)
                    </span>
                  </div>
                  <Badge className={`${sev.badge} text-[10px] border ${sev.border}`}>{s.severity}</Badge>
                </div>
              );
            })}
          </div>
        )}

        {/* Trends Summary */}
        {trends && trends.length > 0 && (
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2" data-testid="evolution-trends">
            {trends.map((t) => (
              <div key={t.metric} className="flex items-center gap-1.5 text-xs px-2 py-1.5 bg-slate-50 rounded border border-slate-100">
                <TrendIcon direction={t.direction} />
                <span className="text-slate-600 truncate">{t.label.split('(')[0].trim()}</span>
                <span className={`ml-auto font-mono text-[10px] ${
                  t.change_percent > 5 ? 'text-amber-600' : t.change_percent < -5 ? 'text-red-600' : 'text-slate-400'
                }`}>
                  {t.change_percent > 0 ? '+' : ''}{t.change_percent}%
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Interpretation */}
        {interpretation && (
          <div className="px-3 py-2 bg-indigo-50/50 border border-indigo-100 rounded-md" data-testid="evolution-interpretation">
            <p className="text-xs text-indigo-700 flex items-start gap-1.5">
              <Brain className="w-3.5 h-3.5 mt-0.5 shrink-0 text-indigo-500" />
              {interpretation}
            </p>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between pt-1 border-t border-slate-100">
          <span className="text-[10px] text-slate-400">
            {snapshots[0]?.week_start} → {snapshots[snapshots.length - 1]?.week_end}
          </span>
          <span className="text-[10px] text-slate-400">
            {data.generated_at ? new Date(data.generated_at).toLocaleTimeString() : ''}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

export default TwinEvolutionTimeline;
