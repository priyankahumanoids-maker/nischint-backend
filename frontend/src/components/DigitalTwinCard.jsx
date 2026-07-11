import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { operatorApi } from '../api';
import { toast } from 'sonner';
import {
  Fingerprint, RefreshCw, Loader2, Sun, Moon, TrendingUp,
  Clock, Activity, AlertTriangle, CheckCircle, Minus,
} from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, Cell,
} from 'recharts';

const CONFIDENCE_COLORS = {
  high: { bg: 'bg-emerald-50', text: 'text-emerald-700', border: 'border-emerald-200', bar: '#10b981' },
  medium: { bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200', bar: '#f59e0b' },
  low: { bg: 'bg-slate-50', text: 'text-slate-500', border: 'border-slate-200', bar: '#94a3b8' },
};

const DEVIATION_ICONS = {
  aligned: { icon: CheckCircle, color: 'text-emerald-500', label: 'Aligned with Twin' },
  deviation: { icon: AlertTriangle, color: 'text-red-500', label: 'Deviation Detected' },
  positive_deviation: { icon: Activity, color: 'text-blue-500', label: 'Positive Deviation' },
  unknown: { icon: Minus, color: 'text-slate-400', label: 'Unknown State' },
};

function ConfidenceBadge({ score, quality }) {
  const style = CONFIDENCE_COLORS[quality] || CONFIDENCE_COLORS.low;
  return (
    <Badge variant="outline" className={`text-[10px] ${style.bg} ${style.text} ${style.border}`}
      data-testid="twin-confidence-badge">
      {(score * 100).toFixed(0)}% confidence · {quality}
    </Badge>
  );
}

function RhythmChart({ dailyRhythm, wakeHour, sleepHour, currentHour }) {
  const data = Array.from({ length: 24 }, (_, h) => {
    const entry = dailyRhythm[String(h)];
    return {
      hour: h,
      label: `${h}:00`,
      interaction: entry?.avg_interaction || 0,
      active: entry?.expected_active || false,
    };
  });

  return (
    <div className="h-[160px]" data-testid="twin-rhythm-chart">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 5 }}>
          <XAxis dataKey="hour" tick={{ fontSize: 9 }} interval={2}
            tickFormatter={h => `${h}`} />
          <YAxis tick={{ fontSize: 9 }} />
          <Tooltip content={<RhythmTooltip wakeHour={wakeHour} sleepHour={sleepHour} />} />
          {wakeHour != null && (
            <ReferenceLine x={wakeHour} stroke="#f59e0b" strokeDasharray="3 3"
              label={{ value: 'Wake', fill: '#f59e0b', fontSize: 9, position: 'top' }} />
          )}
          {sleepHour != null && (
            <ReferenceLine x={sleepHour} stroke="#6366f1" strokeDasharray="3 3"
              label={{ value: 'Sleep', fill: '#6366f1', fontSize: 9, position: 'top' }} />
          )}
          {currentHour != null && (
            <ReferenceLine x={currentHour} stroke="#ef4444" strokeWidth={2}
              label={{ value: 'Now', fill: '#ef4444', fontSize: 9, position: 'top' }} />
          )}
          <Bar dataKey="interaction" radius={[2, 2, 0, 0]}>
            {data.map((d, i) => (
              <Cell key={i} fill={d.active ? '#8b5cf6' : '#e2e8f0'} opacity={d.hour === currentHour ? 1 : 0.7} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function RhythmTooltip({ active, payload, wakeHour, sleepHour }) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  return (
    <div className="bg-white/95 backdrop-blur border rounded-lg shadow-lg p-2 text-xs">
      <p className="font-semibold">{d.hour}:00</p>
      <p>Interaction: {d.interaction?.toFixed(1)}/hr</p>
      <p>{d.active ? '✦ Expected Active' : 'Expected Inactive'}</p>
    </div>
  );
}

function ActivityWindows({ windows }) {
  if (!windows?.length) return null;
  const typeColors = {
    morning_routine: 'bg-amber-100 text-amber-700 border-amber-200',
    midday_activity: 'bg-blue-100 text-blue-700 border-blue-200',
    afternoon_activity: 'bg-teal-100 text-teal-700 border-teal-200',
    evening_routine: 'bg-violet-100 text-violet-700 border-violet-200',
    late_night: 'bg-slate-100 text-slate-600 border-slate-200',
    activity: 'bg-slate-100 text-slate-600 border-slate-200',
  };

  return (
    <div className="flex flex-wrap gap-1.5" data-testid="twin-activity-windows">
      {windows.map((w, i) => (
        <Badge key={i} variant="outline" className={`text-[10px] ${typeColors[w.type] || typeColors.activity}`}>
          {w.start_hour}:00–{w.end_hour}:00 · {w.type.replace('_', ' ')}
        </Badge>
      ))}
    </div>
  );
}

export function DigitalTwinCard({ deviceId }) {
  const [twin, setTwin] = useState(null);
  const [loading, setLoading] = useState(true);
  const [rebuilding, setRebuilding] = useState(false);

  const fetchTwin = useCallback(async () => {
    if (!deviceId) return;
    setLoading(true);
    try {
      const res = await operatorApi.getDeviceDigitalTwin(deviceId);
      setTwin(res.data);
    } catch {
      toast.error('Failed to load digital twin');
    } finally {
      setLoading(false);
    }
  }, [deviceId]);

  useEffect(() => { fetchTwin(); }, [fetchTwin]);

  const handleRebuild = async () => {
    setRebuilding(true);
    try {
      await operatorApi.rebuildDeviceDigitalTwin(deviceId);
      toast.success('Digital twin rebuilt successfully');
      fetchTwin();
    } catch (err) {
      const detail = err.response?.data?.detail || 'Rebuild failed';
      toast.error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setRebuilding(false);
    }
  };

  if (loading) {
    return (
      <Card className="border border-indigo-100">
        <CardContent className="p-6 flex items-center justify-center gap-2 text-slate-400">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading digital twin...
        </CardContent>
      </Card>
    );
  }

  if (!twin || !twin.twin_exists) {
    return (
      <Card className="border border-slate-200" data-testid="twin-not-built">
        <CardContent className="p-6 text-center text-slate-400">
          <Fingerprint className="w-8 h-8 mx-auto mb-2 opacity-30" />
          <p className="text-sm font-medium">Digital Twin Not Yet Built</p>
          <p className="text-xs mt-1">Requires sufficient behavioral baseline data</p>
          <Button variant="outline" size="sm" className="mt-3" onClick={handleRebuild}
            disabled={rebuilding} data-testid="twin-rebuild-btn">
            {rebuilding ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <RefreshCw className="w-3 h-3 mr-1" />}
            Build Now
          </Button>
        </CardContent>
      </Card>
    );
  }

  const summary = twin.profile_summary || {};
  const quality = summary.data_quality || 'low';
  const devInfo = DEVIATION_ICONS[twin.current_state?.deviation_status] || DEVIATION_ICONS.unknown;
  const DevIcon = devInfo.icon;

  return (
    <Card className="border border-indigo-200 bg-gradient-to-br from-white to-indigo-50/30"
      data-testid="digital-twin-card">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Fingerprint className="w-4 h-4 text-indigo-600" />
            <CardTitle className="text-sm">Digital Twin</CardTitle>
            <Badge variant="outline" className="text-[10px] text-indigo-500 border-indigo-200">
              v{twin.twin_version}
            </Badge>
            <ConfidenceBadge score={twin.confidence_score} quality={quality} />
          </div>
          <Button variant="ghost" size="sm" onClick={handleRebuild} disabled={rebuilding}
            className="h-7 text-xs text-indigo-500" data-testid="twin-rebuild-btn">
            {rebuilding ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <RefreshCw className="w-3 h-3 mr-1" />}
            Rebuild
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Current State Banner */}
        <div className={`rounded-lg px-3 py-2 flex items-center gap-2 border ${
          twin.current_state?.deviation_status === 'deviation'
            ? 'bg-red-50 border-red-200' : twin.current_state?.deviation_status === 'positive_deviation'
            ? 'bg-blue-50 border-blue-200' : 'bg-emerald-50 border-emerald-200'
        }`} data-testid="twin-current-state">
          <DevIcon className={`w-4 h-4 ${devInfo.color}`} />
          <div>
            <p className={`text-xs font-semibold ${devInfo.color}`}>{devInfo.label}</p>
            {twin.current_state?.deviation_reason && (
              <p className="text-[10px] text-slate-600">{twin.current_state.deviation_reason}</p>
            )}
          </div>
        </div>

        {/* Profile KPIs */}
        <div className="grid grid-cols-5 gap-2">
          <KpiMini icon={Sun} label="Wake" value={summary.wake_time || '—'} color="text-amber-500" testId="twin-kpi-wake" />
          <KpiMini icon={Moon} label="Sleep" value={summary.sleep_time || '—'} color="text-indigo-500" testId="twin-kpi-sleep" />
          <KpiMini icon={TrendingUp} label="Peak" value={summary.peak_activity || '—'} color="text-violet-500" testId="twin-kpi-peak" />
          <KpiMini icon={Clock} label="Mov. Interval"
            value={twin.movement_interval_minutes ? `${twin.movement_interval_minutes}m` : '—'}
            color="text-teal-500" testId="twin-kpi-interval" />
          <KpiMini icon={Activity} label="Max Inactivity"
            value={twin.typical_inactivity_max_minutes ? `${Math.round(twin.typical_inactivity_max_minutes)}m` : '—'}
            color="text-rose-500" testId="twin-kpi-inactivity" />
        </div>

        {/* Personality Tag */}
        {summary.personality_tag && (
          <div className="text-center">
            <Badge variant="outline" className="text-[10px] text-indigo-600 border-indigo-200 bg-indigo-50"
              data-testid="twin-personality-tag">
              {summary.personality_tag}
            </Badge>
          </div>
        )}

        {/* 24h Rhythm Chart */}
        <div>
          <p className="text-[10px] uppercase tracking-wide text-slate-400 mb-1">24-Hour Activity Rhythm</p>
          <RhythmChart dailyRhythm={twin.daily_rhythm || {}}
            wakeHour={twin.wake_hour} sleepHour={twin.sleep_hour}
            currentHour={twin.current_state?.hour} />
        </div>

        {/* Activity Windows */}
        {twin.activity_windows?.length > 0 && (
          <div>
            <p className="text-[10px] uppercase tracking-wide text-slate-400 mb-1.5">Activity Windows</p>
            <ActivityWindows windows={twin.activity_windows} />
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between text-[9px] text-slate-400 pt-1 border-t border-slate-100">
          <span>{twin.training_data_points} training data points</span>
          <span>Last trained: {twin.last_trained_at
            ? new Date(twin.last_trained_at).toLocaleString()
            : 'Never'}</span>
        </div>
      </CardContent>
    </Card>
  );
}

function KpiMini({ icon: Icon, label, value, color, testId }) {
  return (
    <div className="text-center" data-testid={testId}>
      <Icon className={`w-3.5 h-3.5 mx-auto mb-0.5 ${color}`} />
      <p className="text-xs font-bold text-slate-700">{value}</p>
      <p className="text-[9px] text-slate-400">{label}</p>
    </div>
  );
}
