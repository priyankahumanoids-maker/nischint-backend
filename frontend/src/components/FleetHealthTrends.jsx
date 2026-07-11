import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Loader2, Activity, Battery, Wifi, AlertTriangle, Cpu, TrendingUp } from 'lucide-react';
import { operatorApi } from '../api';
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, CartesianGrid, BarChart, Bar,
} from 'recharts';

const WINDOWS = [
  { value: 360, label: '6h' },
  { value: 1440, label: '24h' },
  { value: 10080, label: '7d' },
];

function formatShortTime(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
}

function FleetTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;

  return (
    <div className="bg-white/95 backdrop-blur border border-slate-200 rounded-lg px-3 py-2 shadow-lg text-xs max-w-[200px]">
      <p className="text-slate-400 font-mono text-[10px] mb-1">{formatShortTime(d.timestamp)}</p>
      <div className="space-y-0.5">
        {d.avg_battery_score !== null && (
          <div className="flex justify-between gap-3">
            <span className="text-emerald-600">Battery</span>
            <span className="font-medium">{d.avg_battery_score} <span className="text-slate-300">/ {d.max_battery_score}</span></span>
          </div>
        )}
        {d.avg_signal_score !== null && (
          <div className="flex justify-between gap-3">
            <span className="text-blue-600">Signal</span>
            <span className="font-medium">{d.avg_signal_score} <span className="text-slate-300">/ {d.max_signal_score}</span></span>
          </div>
        )}
        {d.avg_combined_score !== null && (
          <div className="flex justify-between gap-3">
            <span className="text-red-600">Combined</span>
            <span className="font-medium">{d.avg_combined_score} <span className="text-slate-300">/ {d.max_combined_score}</span></span>
          </div>
        )}
        <div className="flex justify-between gap-3 pt-1 border-t border-slate-100 mt-1">
          <span className="text-slate-400">Devices</span>
          <span className="font-medium">{d.devices_reporting}</span>
        </div>
      </div>
    </div>
  );
}

function MiniSparkline({ data, dataKey, color, gradientId, height = 48 }) {
  const chartData = data.filter(p => p[dataKey] !== null && p[dataKey] !== undefined);
  if (chartData.length < 2) {
    return <div className="h-[48px] flex items-center justify-center text-[10px] text-slate-300">No data</div>;
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={chartData} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.25} />
            <stop offset="100%" stopColor={color} stopOpacity={0.03} />
          </linearGradient>
        </defs>
        <Area type="monotone" dataKey={dataKey} stroke={color} fill={`url(#${gradientId})`} strokeWidth={1.5} dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export default function FleetHealthTrends() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [window, setWindow] = useState(1440);

  useEffect(() => {
    setLoading(true);
    operatorApi.getFleetHealthTrends(window)
      .then(res => setData(res.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [window]);

  if (loading) {
    return (
      <Card data-testid="fleet-health-loading">
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="w-5 h-5 animate-spin text-slate-400 mr-2" />
          <span className="text-sm text-slate-400">Loading fleet health...</span>
        </CardContent>
      </Card>
    );
  }

  if (!data || !data.points?.length) {
    return (
      <Card data-testid="fleet-health-empty">
        <CardContent className="flex items-center justify-center py-8 text-sm text-slate-400">
          <Activity className="w-4 h-4 mr-2" />
          No fleet health data available
        </CardContent>
      </Card>
    );
  }

  const pts = data.points;
  const { summary } = data;
  const hasBattery = pts.some(p => p.avg_battery_score !== null);
  const hasSignal = pts.some(p => p.avg_signal_score !== null);
  const hasCombined = pts.some(p => p.avg_combined_score !== null);
  const hasReporting = pts.some(p => p.devices_reporting > 0);

  return (
    <Card data-testid="fleet-health-trends">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-semibold text-slate-800 flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-indigo-500" />
            Fleet Health Trends
          </CardTitle>
          <div className="flex items-center gap-1" data-testid="fleet-health-window-selector">
            {WINDOWS.map(w => (
              <Button
                key={w.value}
                variant={window === w.value ? 'default' : 'ghost'}
                size="sm"
                className={`h-7 text-xs px-2.5 ${window === w.value ? 'bg-indigo-600 hover:bg-indigo-700 text-white' : 'text-slate-500'}`}
                onClick={() => setWindow(w.value)}
                data-testid={`fleet-health-window-${w.label}`}
              >
                {w.label}
              </Button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Peak Summary */}
        <div className="grid grid-cols-4 gap-3" data-testid="fleet-health-peaks">
          <PeakStat icon={Battery} label="Peak Battery" value={summary.peak_battery_score} color="emerald" testId="peak-battery" />
          <PeakStat icon={Wifi} label="Peak Signal" value={summary.peak_signal_score} color="blue" testId="peak-signal" />
          <PeakStat icon={AlertTriangle} label="Peak Combined" value={summary.peak_combined_score} color="red" testId="peak-combined" />
          <PeakStat icon={Cpu} label="Devices Reporting" value={summary.peak_devices_reporting} color="indigo" testId="peak-devices" />
        </div>

        {/* Metric Sparklines Grid */}
        <div className={`grid gap-4 ${hasCombined && hasReporting ? 'grid-cols-1 md:grid-cols-2' : 'grid-cols-1 md:grid-cols-3'}`}>
          {hasBattery && (
            <MetricMiniCard
              icon={Battery}
              label="Battery Score"
              color="#22c55e"
              data={pts}
              avgKey="avg_battery_score"
              maxKey="max_battery_score"
              gradientId="fleetBatGrad"
              testId="fleet-battery-chart"
            />
          )}
          {hasSignal && (
            <MetricMiniCard
              icon={Wifi}
              label="Signal Score"
              color="#3b82f6"
              data={pts}
              avgKey="avg_signal_score"
              maxKey="max_signal_score"
              gradientId="fleetSigGrad"
              testId="fleet-signal-chart"
            />
          )}
          {hasCombined && (
            <MetricMiniCard
              icon={AlertTriangle}
              label="Combined Risk"
              color="#ef4444"
              data={pts}
              avgKey="avg_combined_score"
              maxKey="max_combined_score"
              gradientId="fleetCombGrad"
              testId="fleet-combined-chart"
            />
          )}
        </div>

        {/* Devices Reporting Band */}
        {hasReporting && (
          <div data-testid="fleet-devices-band">
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-1.5">
                <Cpu className="w-3 h-3 text-indigo-500" />
                <span className="text-[10px] font-medium text-slate-500">Devices Reporting</span>
              </div>
              <span className="text-[10px] text-slate-400">{data.total_points} data points</span>
            </div>
            <ResponsiveContainer width="100%" height={40}>
              <BarChart data={pts} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="devReportGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#6366f1" stopOpacity={0.5} />
                    <stop offset="100%" stopColor="#6366f1" stopOpacity={0.15} />
                  </linearGradient>
                </defs>
                <Bar dataKey="devices_reporting" fill="url(#devReportGrad)" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function PeakStat({ icon: Icon, label, value, color, testId }) {
  const colorMap = {
    emerald: 'text-emerald-600 bg-emerald-50',
    blue: 'text-blue-600 bg-blue-50',
    red: 'text-red-600 bg-red-50',
    indigo: 'text-indigo-600 bg-indigo-50',
  };
  const cls = colorMap[color] || 'text-slate-600 bg-slate-50';

  return (
    <div className={`rounded-lg p-3 ${cls.split(' ')[1]}`} data-testid={testId}>
      <div className="flex items-center gap-1.5 mb-1">
        <Icon className={`w-3 h-3 ${cls.split(' ')[0]}`} />
        <span className="text-[10px] text-slate-400 uppercase tracking-wide">{label}</span>
      </div>
      <p className={`text-lg font-bold ${cls.split(' ')[0]}`}>
        {value !== null && value !== undefined ? value : '--'}
      </p>
    </div>
  );
}

function MetricMiniCard({ icon: Icon, label, color, data, avgKey, maxKey, gradientId, testId }) {
  const latest = [...data].reverse().find(p => p[avgKey] !== null);
  const latestVal = latest ? latest[avgKey] : null;

  return (
    <div className="rounded-lg border border-slate-100 p-3" data-testid={testId}>
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-1.5">
          <Icon className="w-3 h-3" style={{ color }} />
          <span className="text-[10px] font-medium text-slate-500">{label}</span>
        </div>
        {latestVal !== null && (
          <Badge variant="outline" className="text-[10px] px-1.5 py-0" style={{ borderColor: color, color }}>
            {latestVal}
          </Badge>
        )}
      </div>
      <MiniSparkline data={data} dataKey={avgKey} color={color} gradientId={gradientId} />
    </div>
  );
}
