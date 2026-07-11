import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
import { Loader2, Clock, AlertTriangle, Shield, TrendingDown } from 'lucide-react';
import { operatorApi } from '../../api';
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, Bar, ComposedChart, CartesianGrid,
} from 'recharts';

function formatTime(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleTimeString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
}

function formatShortTime(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
}

const EVENT_CONFIG = {
  device_instability_detected: { label: 'Instability Detected', color: '#f59e0b', icon: AlertTriangle },
  device_instability_recovered: { label: 'Recovery', color: '#22c55e', icon: Shield },
  escalation_l1: { label: 'Escalation L1', color: '#f59e0b' },
  escalation_l2: { label: 'Escalation L2', color: '#f97316' },
  escalation_l3: { label: 'Escalation L3', color: '#ef4444' },
  device_instability_escalation_blocked: { label: 'Blocked', color: '#94a3b8' },
};

function TimelineTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;

  return (
    <div className="bg-white/95 backdrop-blur border border-slate-200 rounded-lg px-3 py-2.5 shadow-lg text-xs max-w-[220px]">
      <p className="text-slate-400 font-mono text-[10px] mb-1.5">{formatTime(d.timestamp)}</p>
      {d.max_combined !== undefined && (
        <div className="space-y-1">
          <div className="flex justify-between gap-4">
            <span className="text-slate-500">Max Score</span>
            <span className="font-semibold text-red-600">{d.max_combined}</span>
          </div>
          <div className="flex justify-between gap-4">
            <span className="text-slate-500">Avg Score</span>
            <span className="font-medium text-slate-700">{d.avg_combined}</span>
          </div>
          <div className="flex justify-between gap-4">
            <span className="text-slate-500">Devices Above</span>
            <span className="font-medium text-amber-600">{d.devices_above_threshold}/{d.total_devices}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function EventMarkerList({ events }) {
  if (!events?.length) return null;

  // Group events by type and count
  const grouped = {};
  events.forEach(e => {
    const key = e.event_type;
    if (!grouped[key]) grouped[key] = { count: 0, devices: new Set() };
    grouped[key].count++;
    if (e.device_identifier) grouped[key].devices.add(e.device_identifier);
  });

  return (
    <div className="space-y-1.5" data-testid="timeline-events-summary">
      <p className="text-[10px] font-bold tracking-[0.15em] text-slate-400 uppercase">Events in Window</p>
      <div className="flex flex-wrap gap-2">
        {Object.entries(grouped).map(([type, data]) => {
          const cfg = EVENT_CONFIG[type] || { label: type, color: '#94a3b8' };
          return (
            <Badge
              key={type}
              variant="outline"
              className="text-[10px] gap-1 px-2 py-1"
              style={{ borderColor: cfg.color, color: cfg.color }}
              data-testid={`timeline-event-badge-${type}`}
            >
              <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: cfg.color }} />
              {cfg.label}: {data.count}
              <span className="text-slate-400 ml-0.5">({data.devices.size} devices)</span>
            </Badge>
          );
        })}
      </div>
    </div>
  );
}

function EventTimeline({ events, startTime, endTime }) {
  if (!events?.length) return null;

  const start = new Date(startTime).getTime();
  const end = new Date(endTime).getTime();
  const span = end - start;

  // Limit visible event markers to avoid clutter
  const visibleEvents = events.slice(0, 50);

  return (
    <div className="relative h-8 bg-slate-50 rounded-lg border border-slate-100 overflow-hidden" data-testid="timeline-event-bar">
      {visibleEvents.map((e, i) => {
        const ts = new Date(e.timestamp).getTime();
        const pct = Math.max(0, Math.min(100, ((ts - start) / span) * 100));
        const cfg = EVENT_CONFIG[e.event_type] || { color: '#94a3b8' };
        return (
          <div
            key={i}
            className="absolute top-0 bottom-0 w-0.5"
            style={{ left: `${pct}%`, backgroundColor: cfg.color }}
            title={`${cfg.label || e.event_type} | ${e.device_identifier || ''} | ${formatShortTime(e.timestamp)}`}
          />
        );
      })}
      <div className="absolute inset-0 flex items-center justify-between px-2">
        <span className="text-[9px] text-slate-400 font-mono">{formatShortTime(startTime)}</span>
        <span className="text-[9px] text-slate-400 font-mono">{formatShortTime(endTime)}</span>
      </div>
    </div>
  );
}

export function ReplayTimelinePanel({ startTime, endTime, threshold = 60 }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!startTime || !endTime) return;
    setLoading(true);
    operatorApi.getReplayTimeline(startTime, endTime, threshold)
      .then(res => setData(res.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [startTime, endTime, threshold]);

  if (loading) {
    return (
      <Card className="border-indigo-100" data-testid="replay-timeline-loading">
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="w-5 h-5 animate-spin text-indigo-400 mr-2" />
          <span className="text-sm text-indigo-400">Loading timeline...</span>
        </CardContent>
      </Card>
    );
  }

  if (!data) return null;

  const hasScoreData = data.score_timeline?.length > 0;
  const hasEvents = data.events?.length > 0;

  if (!hasScoreData && !hasEvents) {
    return (
      <Card className="border-slate-200" data-testid="replay-timeline-empty">
        <CardContent className="flex items-center justify-center py-8 text-sm text-slate-400">
          <TrendingDown className="w-4 h-4 mr-2" />
          No anomaly data or events in this replay window
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-indigo-200" data-testid="replay-timeline-panel">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold text-indigo-700 flex items-center gap-2">
            <Clock className="w-4 h-4" /> Replay Timeline
          </CardTitle>
          <div className="flex items-center gap-3">
            <span className="text-[10px] text-slate-400">{data.total_score_points} data points</span>
            <span className="text-[10px] text-slate-400">{data.total_events} events</span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Combined Score Chart */}
        {hasScoreData && (
          <div data-testid="replay-timeline-chart">
            <p className="text-[10px] font-bold tracking-[0.15em] text-slate-400 uppercase mb-2">Combined Risk Score</p>
            <ResponsiveContainer width="100%" height={160}>
              <ComposedChart data={data.score_timeline} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
                <defs>
                  <linearGradient id="riskGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#ef4444" stopOpacity={0.3} />
                    <stop offset="50%" stopColor="#f59e0b" stopOpacity={0.15} />
                    <stop offset="100%" stopColor="#22c55e" stopOpacity={0.05} />
                  </linearGradient>
                  <linearGradient id="devGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#6366f1" stopOpacity={0.4} />
                    <stop offset="100%" stopColor="#6366f1" stopOpacity={0.1} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis
                  dataKey="timestamp"
                  tickFormatter={formatShortTime}
                  tick={{ fontSize: 10, fill: '#94a3b8' }}
                  axisLine={{ stroke: '#e2e8f0' }}
                  tickLine={false}
                />
                <YAxis
                  yAxisId="score"
                  domain={[0, 100]}
                  tick={{ fontSize: 10, fill: '#94a3b8' }}
                  axisLine={false}
                  tickLine={false}
                  width={30}
                />
                <YAxis
                  yAxisId="count"
                  orientation="right"
                  tick={{ fontSize: 10, fill: '#94a3b8' }}
                  axisLine={false}
                  tickLine={false}
                  width={25}
                />
                <Tooltip content={<TimelineTooltip />} />
                <ReferenceLine
                  yAxisId="score"
                  y={threshold}
                  stroke="#ef4444"
                  strokeDasharray="4 4"
                  strokeOpacity={0.7}
                  label={{ value: 'Threshold', position: 'right', fontSize: 9, fill: '#ef4444' }}
                />
                <Area
                  yAxisId="score"
                  type="monotone"
                  dataKey="max_combined"
                  stroke="#ef4444"
                  fill="url(#riskGrad)"
                  strokeWidth={2}
                  dot={false}
                  name="Max Risk"
                />
                <Area
                  yAxisId="score"
                  type="monotone"
                  dataKey="avg_combined"
                  stroke="#f59e0b"
                  fill="none"
                  strokeWidth={1}
                  strokeDasharray="3 3"
                  dot={false}
                  name="Avg Risk"
                />
                <Bar
                  yAxisId="count"
                  dataKey="devices_above_threshold"
                  fill="url(#devGrad)"
                  radius={[2, 2, 0, 0]}
                  maxBarSize={20}
                  name="Devices Above"
                />
              </ComposedChart>
            </ResponsiveContainer>
            <div className="flex items-center justify-center gap-4 mt-1">
              <div className="flex items-center gap-1.5">
                <div className="w-3 h-0.5 bg-red-500 rounded" />
                <span className="text-[9px] text-slate-400">Max Score</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="w-3 h-0.5 bg-amber-500 rounded border-dashed" style={{ borderTop: '1px dashed #f59e0b' }} />
                <span className="text-[9px] text-slate-400">Avg Score</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="w-2.5 h-2.5 bg-indigo-400/30 rounded-sm" />
                <span className="text-[9px] text-slate-400">Devices Above Threshold</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="w-3 h-0 border-t-2 border-red-500 border-dashed" />
                <span className="text-[9px] text-slate-400">Threshold ({threshold})</span>
              </div>
            </div>
          </div>
        )}

        {/* Event Timeline Bar */}
        {hasEvents && (
          <div>
            <p className="text-[10px] font-bold tracking-[0.15em] text-slate-400 uppercase mb-2">Event Distribution</p>
            <EventTimeline
              events={data.events}
              startTime={data.window.start_time}
              endTime={data.window.end_time}
            />
          </div>
        )}

        {/* Event Summary */}
        {hasEvents && <EventMarkerList events={data.events} />}
      </CardContent>
    </Card>
  );
}
