import { useState, useEffect } from 'react';
import { Card, CardContent } from './ui/card';
import { Badge } from './ui/badge';
import { Loader2, Battery, Wifi, AlertTriangle } from 'lucide-react';
import { operatorApi } from '../api';
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts';

const METRIC_CONFIG = {
  battery: {
    key: 'battery_score',
    rawKey: 'battery_level',
    label: 'Battery Score',
    color: '#22c55e',
    gradientId: 'batteryGrad',
    icon: Battery,
    unit: '',
  },
  signal: {
    key: 'signal_score',
    rawKey: 'signal_strength',
    label: 'Signal Score',
    color: '#3b82f6',
    gradientId: 'signalGrad',
    icon: Wifi,
    unit: '',
  },
  combined: {
    key: 'combined_score',
    rawKey: null,
    label: 'Combined Risk',
    color: '#ef4444',
    gradientId: 'combinedGrad',
    icon: AlertTriangle,
    unit: '',
  },
};

function formatTime(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white/95 backdrop-blur border border-slate-200 rounded-lg px-3 py-2 shadow-lg text-xs">
      <p className="text-slate-400 mb-1">{formatTime(label)}</p>
      {payload.map((p, i) => (
        <p key={i} className="font-medium" style={{ color: p.color }}>
          {p.name}: {p.value !== null && p.value !== undefined ? p.value : 'N/A'}
        </p>
      ))}
    </div>
  );
}

export function MetricSparkline({ metricType, data, threshold, height = 60 }) {
  const cfg = METRIC_CONFIG[metricType];
  if (!cfg) return null;

  const dataKey = cfg.key;
  const fallbackKey = cfg.rawKey;

  // Use score if available, fallback to raw value
  const chartData = data.map(p => ({
    ts: p.timestamp,
    value: p[dataKey] ?? p[fallbackKey] ?? null,
  })).filter(p => p.value !== null);

  if (chartData.length < 2) {
    return (
      <div className="flex items-center gap-2 h-[40px]">
        <cfg.icon className="w-3.5 h-3.5 text-slate-300" />
        <span className="text-[10px] text-slate-300">Insufficient data</span>
      </div>
    );
  }

  const latest = chartData[chartData.length - 1]?.value;
  const hasThresholdExceeded = threshold && chartData.some(p => p.value >= threshold);

  return (
    <div data-testid={`sparkline-${metricType}`}>
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-1.5">
          <cfg.icon className="w-3 h-3" style={{ color: cfg.color }} />
          <span className="text-[10px] font-medium text-slate-500">{cfg.label}</span>
        </div>
        {latest !== undefined && (
          <Badge
            variant="outline"
            className={`text-[10px] px-1.5 py-0 ${
              hasThresholdExceeded ? 'border-red-300 text-red-600' : 'text-slate-500'
            }`}
            data-testid={`sparkline-${metricType}-value`}
          >
            {typeof latest === 'number' ? latest.toFixed(1) : latest}
          </Badge>
        )}
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={chartData} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id={cfg.gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={cfg.color} stopOpacity={0.3} />
              <stop offset="100%" stopColor={cfg.color} stopOpacity={0.05} />
            </linearGradient>
          </defs>
          <XAxis dataKey="ts" hide />
          <YAxis hide domain={['auto', 'auto']} />
          <Tooltip content={<CustomTooltip />} />
          {threshold && (
            <ReferenceLine
              y={threshold}
              stroke="#ef4444"
              strokeDasharray="3 3"
              strokeOpacity={0.6}
            />
          )}
          <Area
            type="monotone"
            dataKey="value"
            stroke={cfg.color}
            fill={`url(#${cfg.gradientId})`}
            strokeWidth={1.5}
            dot={false}
            name={cfg.label}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function MetricTrendsCard({ deviceId, windowMinutes = 1440, threshold, compact = false }) {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!deviceId) return;
    setLoading(true);
    operatorApi.getDeviceMetricTrends(deviceId, windowMinutes)
      .then(res => setData(res.data?.points || []))
      .catch(() => setData([]))
      .finally(() => setLoading(false));
  }, [deviceId, windowMinutes]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-4" data-testid="metric-trends-loading">
        <Loader2 className="w-4 h-4 animate-spin text-slate-400" />
      </div>
    );
  }

  if (!data.length) {
    return (
      <div className="text-center py-3 text-[10px] text-slate-400" data-testid="metric-trends-empty">
        No telemetry data available for this window
      </div>
    );
  }

  const chartHeight = compact ? 45 : 60;

  return (
    <Card className="border-slate-200" data-testid="metric-trends-card">
      <CardContent className={compact ? 'p-3 space-y-2' : 'p-4 space-y-3'}>
        {!compact && (
          <p className="text-[10px] font-bold tracking-[0.15em] text-slate-400 uppercase">
            Metric Trends ({windowMinutes >= 1440 ? `${Math.round(windowMinutes / 1440)}d` : windowMinutes >= 60 ? `${Math.round(windowMinutes / 60)}h` : `${windowMinutes}m`})
          </p>
        )}
        <MetricSparkline metricType="battery" data={data} threshold={threshold} height={chartHeight} />
        <MetricSparkline metricType="signal" data={data} threshold={threshold} height={chartHeight} />
        <MetricSparkline metricType="combined" data={data} threshold={threshold} height={chartHeight} />
      </CardContent>
    </Card>
  );
}

export function IncidentMetricTrends({ deviceId, incidentCreatedAt }) {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!deviceId) return;
    setLoading(true);
    // For incidents, show last 60 min
    operatorApi.getDeviceMetricTrends(deviceId, 60)
      .then(res => setData(res.data?.points || []))
      .catch(() => setData([]))
      .finally(() => setLoading(false));
  }, [deviceId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-3" data-testid="incident-trends-loading">
        <Loader2 className="w-4 h-4 animate-spin text-slate-400" />
      </div>
    );
  }

  if (!data.length) return null;

  return (
    <div className="space-y-2 py-2" data-testid="incident-metric-trends">
      <p className="text-[10px] font-bold tracking-[0.15em] text-slate-400 uppercase">Pre-Escalation Metrics (60 min)</p>
      <MetricSparkline metricType="battery" data={data} height={45} />
      <MetricSparkline metricType="signal" data={data} height={45} />
      <MetricSparkline metricType="combined" data={data} threshold={60} height={45} />
    </div>
  );
}
