import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { MapContainer, TileLayer, Polyline, CircleMarker, Marker, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { operatorApi } from '../api';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, ReferenceLine } from 'recharts';
import {
  Loader2, Play, Pause, SkipForward, SkipBack, Zap, Brain, Bell,
  Flag, AlertTriangle, Battery, MapPin, Clock, ChevronRight,
} from 'lucide-react';

const SPEED_OPTIONS = [1, 2, 5, 10];

const ICON_MAP = {
  zap: Zap, brain: Brain, bell: Bell, flag: Flag, alert: AlertTriangle,
  battery: Battery, pause: MapPin,
};

const SEV_COLORS = {
  critical: 'text-red-600 bg-red-50 border-red-200',
  high: 'text-orange-600 bg-orange-50 border-orange-200',
  medium: 'text-amber-600 bg-amber-50 border-amber-200',
  low: 'text-slate-600 bg-slate-50 border-slate-200',
};

// Map auto-panner
function MapFollower({ position }) {
  const map = useMap();
  useEffect(() => {
    if (position) map.setView(position, map.getZoom(), { animate: true, duration: 0.3 });
  }, [position, map]);
  return null;
}

export function IncidentReplayViewer({ incidentId, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [frameIdx, setFrameIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [activeEvent, setActiveEvent] = useState(null);
  const intervalRef = useRef(null);

  // Prepare chart data from frames
  const chartData = useMemo(() => {
    if (!data?.frames) return [];
    // Sample every 3rd frame to keep chart performant
    const step = Math.max(1, Math.floor(data.frames.length / 120));
    return data.frames.filter((_, i) => i % step === 0).map((f, i) => ({
      idx: Math.round(i * step),
      time: f.timestamp?.substring(11, 16) || '',
      location: f.risk_overlay?.location_risk || 0,
      environment: f.risk_overlay?.environment_risk || 0,
      behavior: f.risk_overlay?.behavior_score || 0,
      hasEvent: f.events?.length > 0,
    }));
  }, [data]);

  useEffect(() => {
    if (!incidentId) return;
    setLoading(true);
    operatorApi.getIncidentReplay(incidentId)
      .then(r => { setData(r.data); setLoading(false); })
      .catch(e => { setError(e.response?.data?.detail || 'Failed to load replay'); setLoading(false); });
  }, [incidentId]);

  // Playback logic
  useEffect(() => {
    if (!playing || !data) return;
    intervalRef.current = setInterval(() => {
      setFrameIdx(prev => {
        if (prev >= data.frames.length - 1) { setPlaying(false); return prev; }
        return prev + 1;
      });
    }, 1000 / speed);
    return () => clearInterval(intervalRef.current);
  }, [playing, speed, data]);

  const jumpToEvent = useCallback((eventTime) => {
    if (!data) return;
    const idx = data.frames.findIndex(f => f.timestamp >= eventTime);
    if (idx >= 0) { setFrameIdx(idx); setActiveEvent(eventTime); }
  }, [data]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96" data-testid="replay-loading">
        <div className="text-center space-y-2">
          <Loader2 className="w-8 h-8 animate-spin text-amber-500 mx-auto" />
          <p className="text-sm text-slate-500">Reconstructing incident timeline...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <Card className="border border-red-200">
        <CardContent className="p-6 text-center">
          <AlertTriangle className="w-6 h-6 text-red-500 mx-auto mb-2" />
          <p className="text-sm text-red-600">{error}</p>
          {onClose && <Button variant="outline" size="sm" onClick={onClose} className="mt-3">Close</Button>}
        </CardContent>
      </Card>
    );
  }

  if (!data) return null;

  const frame = data.frames[frameIdx] || {};
  const position = frame.location ? [frame.location.lat, frame.location.lng] : null;
  const progress = data.frames.length > 1 ? (frameIdx / (data.frames.length - 1)) * 100 : 0;
  const trailSoFar = data.location_trail?.slice(0, Math.max(1,
    data.location_trail.findIndex(t => t.timestamp > frame.timestamp) || data.location_trail.length
  )).map(t => [t.lat, t.lng]) || [];

  return (
    <div className="space-y-3" data-testid="incident-replay-viewer">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-bold text-slate-800 flex items-center gap-2">
            <Zap className="w-5 h-5 text-amber-500" />
            Incident Replay — {data.device_identifier}
          </h3>
          <p className="text-xs text-slate-500">
            {data.incident_type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())} |
            {data.senior_name} |
            {new Date(data.incident_time).toLocaleString()}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge className={SEV_COLORS[data.severity] + ' border text-xs'}>{data.severity}</Badge>
          {onClose && <Button variant="outline" size="sm" onClick={onClose} data-testid="replay-close">Close</Button>}
        </div>
      </div>

      {/* Main layout */}
      <div className="grid grid-cols-12 gap-3" style={{ height: 520 }}>
        {/* Left: Timeline */}
        <div className="col-span-3 border border-slate-200 rounded-lg overflow-y-auto bg-white" data-testid="replay-timeline">
          <div className="px-3 py-2 border-b border-slate-100 sticky top-0 bg-white z-10">
            <p className="text-[10px] font-semibold text-slate-600">
              <Clock className="w-3 h-3 inline mr-1" />
              {data.events.length} Events
            </p>
          </div>
          <div className="divide-y divide-slate-50">
            {data.events.map((evt, i) => {
              const Icon = ICON_MAP[evt.icon] || Flag;
              const isActive = activeEvent === evt.time;
              const isCurrent = frame.events?.some(fe => fe.label === evt.label);
              return (
                <button
                  key={i}
                  onClick={() => jumpToEvent(evt.time)}
                  className={`w-full px-3 py-2 text-left hover:bg-slate-50 transition-colors flex items-start gap-2 ${
                    isActive || isCurrent ? 'bg-amber-50 border-l-2 border-amber-500' : ''
                  }`}
                  data-testid={`replay-event-${i}`}
                >
                  <Icon className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${
                    evt.severity === 'critical' ? 'text-red-500' :
                    evt.severity === 'high' ? 'text-orange-500' :
                    'text-slate-400'
                  }`} />
                  <div>
                    <p className="text-[10px] font-mono text-slate-400">{evt.time.substring(11, 19)}</p>
                    <p className="text-[11px] text-slate-700 leading-tight">{evt.label}</p>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Center: Map + Signal Graph */}
        <div className="col-span-6 flex flex-col gap-2">
          {/* Map */}
          <div className="flex-1 rounded-lg overflow-hidden border border-slate-200" data-testid="replay-map">
            <MapContainer
              center={position || [12.9716, 77.5946]}
              zoom={15}
              style={{ height: '100%', width: '100%' }}
              zoomControl={false}
            >
              <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
              {position && <MapFollower position={position} />}

              {/* Trail */}
              {trailSoFar.length > 1 && (
                <Polyline positions={trailSoFar} color="#3b82f6" weight={3} opacity={0.7} dashArray="6" />
              )}

              {/* Current position */}
              {position && (
                <CircleMarker center={position} radius={8}
                  pathOptions={{
                    fillColor: frame.events?.length ? '#ef4444' : '#3b82f6',
                    fillOpacity: 0.9, color: '#fff', weight: 2,
                  }}
                >
                  <Popup>
                    <div className="text-xs">
                      <strong>{data.device_identifier}</strong>
                      <br />Time: {frame.timestamp?.substring(11, 19)}
                      <br />Speed: {frame.speed?.toFixed(1)} m/s
                      {frame.battery != null && <><br />Battery: {frame.battery}%</>}
                    </div>
                  </Popup>
                </CircleMarker>
              )}

              {/* Event markers on trail */}
              {data.events.filter(e => e.icon === 'zap' || e.severity === 'critical').map((evt, i) => {
                const loc = data.location_trail?.[0];
                if (!loc) return null;
                return (
                  <CircleMarker key={i} center={[loc.lat, loc.lng]} radius={12}
                    pathOptions={{ fillColor: '#ef4444', fillOpacity: 0.3, color: '#ef4444', weight: 1 }}
                  />
                );
              })}
            </MapContainer>
          </div>

          {/* Signal Overlay Graph */}
          <div className="h-[130px] border border-slate-200 rounded-lg bg-white px-2 pt-1 pb-0" data-testid="replay-signal-graph">
            <div className="flex items-center justify-between mb-0.5 px-1">
              <p className="text-[9px] font-semibold text-slate-500">RISK SIGNALS</p>
              <div className="flex gap-3 text-[9px]">
                <span className="flex items-center gap-1"><span className="w-2 h-0.5 bg-red-500 inline-block rounded" />Location</span>
                <span className="flex items-center gap-1"><span className="w-2 h-0.5 bg-blue-500 inline-block rounded" />Environment</span>
                <span className="flex items-center gap-1"><span className="w-2 h-0.5 bg-purple-500 inline-block rounded" />Behavior</span>
              </div>
            </div>
            <ResponsiveContainer width="100%" height="85%">
              <AreaChart data={chartData} margin={{ top: 2, right: 4, left: -20, bottom: 0 }}
                onClick={(e) => {
                  if (e?.activePayload?.[0]?.payload?.idx != null) {
                    setFrameIdx(e.activePayload[0].payload.idx);
                  }
                }}
              >
                <defs>
                  <linearGradient id="locGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="envGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="behGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="time" tick={{ fontSize: 8 }} interval="preserveStartEnd" stroke="#94a3b8" />
                <YAxis domain={[0, 10]} tick={{ fontSize: 8 }} stroke="#94a3b8" />
                <Tooltip
                  contentStyle={{ fontSize: 10, padding: '4px 8px', borderRadius: 6, border: '1px solid #e2e8f0' }}
                  formatter={(val, name) => [val.toFixed(1), name === 'location' ? 'Location Risk' : name === 'environment' ? 'Environment' : 'Behavior']}
                  labelFormatter={(v) => `Time: ${v}`}
                />
                <Area type="monotone" dataKey="location" stroke="#ef4444" strokeWidth={1.5} fill="url(#locGrad)" dot={false} />
                <Area type="monotone" dataKey="environment" stroke="#3b82f6" strokeWidth={1.5} fill="url(#envGrad)" dot={false} />
                <Area type="monotone" dataKey="behavior" stroke="#8b5cf6" strokeWidth={1.5} fill="url(#behGrad)" dot={false} />
                {/* Playback cursor */}
                {chartData.length > 0 && (() => {
                  const cursorEntry = chartData.reduce((prev, curr) =>
                    Math.abs(curr.idx - frameIdx) < Math.abs(prev.idx - frameIdx) ? curr : prev
                  );
                  return <ReferenceLine x={cursorEntry.time} stroke="#f59e0b" strokeWidth={2} strokeDasharray="3 3" />;
                })()}
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Right: Info panels */}
        <div className="col-span-3 space-y-2 overflow-y-auto">
          {/* Current frame info */}
          <Card className="border border-slate-200">
            <CardContent className="p-3 space-y-2">
              <p className="text-[10px] font-semibold text-slate-500">FRAME {frameIdx + 1}/{data.frames.length}</p>
              <p className="text-xs font-mono text-slate-700">{frame.timestamp?.substring(11, 19)}</p>
              <div className="grid grid-cols-2 gap-1.5 text-[10px]">
                {frame.speed != null && (
                  <div className="bg-slate-50 rounded px-1.5 py-1">
                    <span className="text-slate-400">Speed</span>
                    <p className="font-semibold text-slate-700">{frame.speed.toFixed(1)} m/s</p>
                  </div>
                )}
                {frame.battery != null && (
                  <div className="bg-slate-50 rounded px-1.5 py-1">
                    <span className="text-slate-400">Battery</span>
                    <p className="font-semibold text-slate-700">{frame.battery}%</p>
                  </div>
                )}
                {frame.anomaly_score > 0 && (
                  <div className="bg-red-50 rounded px-1.5 py-1">
                    <span className="text-red-400">Anomaly</span>
                    <p className="font-semibold text-red-700">{frame.anomaly_score.toFixed(2)}</p>
                  </div>
                )}
                {frame.signal != null && (
                  <div className="bg-slate-50 rounded px-1.5 py-1">
                    <span className="text-slate-400">Signal</span>
                    <p className="font-semibold text-slate-700">{frame.signal}%</p>
                  </div>
                )}
              </div>
              {/* Frame events */}
              {frame.events?.length > 0 && (
                <div className="space-y-1">
                  {frame.events.map((fe, i) => (
                    <div key={i} className={`text-[10px] px-2 py-1 rounded border ${SEV_COLORS[fe.severity] || SEV_COLORS.medium}`}>
                      {fe.label}
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* AI Narrative */}
          <Card className="border border-amber-200 bg-amber-50/30">
            <CardContent className="p-3">
              <p className="text-[10px] font-semibold text-amber-700 mb-1 flex items-center gap-1">
                <Brain className="w-3 h-3" /> AI Analysis
              </p>
              <p className="text-[11px] text-slate-700 leading-relaxed" data-testid="replay-narrative">
                {data.ai_narrative}
              </p>
            </CardContent>
          </Card>

          {/* Stats */}
          <Card className="border border-slate-200">
            <CardContent className="p-3">
              <p className="text-[10px] font-semibold text-slate-500 mb-1">Replay Stats</p>
              <div className="space-y-0.5 text-[10px] text-slate-600">
                <p>Telemetry: <strong>{data.stats.telemetry_points}</strong> points</p>
                <p>Anomalies: <strong>{data.stats.anomalies}</strong></p>
                <p>Notifications: <strong>{data.stats.notifications_sent}</strong></p>
                <p>Window: <strong>{data.replay_window.before_minutes}m before → {data.replay_window.after_minutes}m after</strong></p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Playback controls */}
      <div className="flex items-center gap-3 px-4 py-2 bg-slate-900 rounded-lg" data-testid="replay-controls">
        {/* Play/Pause */}
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            if (frameIdx >= data.frames.length - 1) setFrameIdx(0);
            setPlaying(!playing);
          }}
          className="text-white hover:bg-slate-800 h-8 w-8 p-0"
          data-testid="replay-play-btn"
        >
          {playing ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
        </Button>

        {/* Skip back */}
        <Button size="sm" variant="ghost" className="text-white hover:bg-slate-800 h-8 w-8 p-0"
          onClick={() => setFrameIdx(Math.max(0, frameIdx - 12))} data-testid="replay-skip-back">
          <SkipBack className="w-4 h-4" />
        </Button>

        {/* Progress bar */}
        <div className="flex-1 relative h-2 bg-slate-700 rounded-full overflow-hidden cursor-pointer"
          onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const pct = (e.clientX - rect.left) / rect.width;
            setFrameIdx(Math.round(pct * (data.frames.length - 1)));
          }}
          data-testid="replay-progress"
        >
          <div className="absolute inset-y-0 left-0 bg-amber-500 rounded-full transition-all"
            style={{ width: `${progress}%` }} />
          {/* Event markers on progress bar */}
          {data.events.map((evt, i) => {
            const evtFrame = data.frames.findIndex(f => f.timestamp >= evt.time);
            if (evtFrame < 0) return null;
            const pct = (evtFrame / Math.max(data.frames.length - 1, 1)) * 100;
            return (
              <div key={i} className={`absolute top-0 bottom-0 w-0.5 ${
                evt.severity === 'critical' ? 'bg-red-500' :
                evt.severity === 'high' ? 'bg-orange-500' : 'bg-blue-400'
              }`} style={{ left: `${pct}%` }} />
            );
          })}
        </div>

        {/* Skip forward */}
        <Button size="sm" variant="ghost" className="text-white hover:bg-slate-800 h-8 w-8 p-0"
          onClick={() => setFrameIdx(Math.min(data.frames.length - 1, frameIdx + 12))} data-testid="replay-skip-fwd">
          <SkipForward className="w-4 h-4" />
        </Button>

        {/* Time display */}
        <span className="text-[11px] font-mono text-slate-400 w-16 text-center" data-testid="replay-time">
          {frame.timestamp?.substring(11, 19)}
        </span>

        {/* Speed selector */}
        <div className="flex gap-1">
          {SPEED_OPTIONS.map(s => (
            <button key={s}
              onClick={() => setSpeed(s)}
              className={`text-[10px] px-1.5 py-0.5 rounded ${
                speed === s ? 'bg-amber-500 text-white' : 'text-slate-400 hover:bg-slate-800'
              }`}
              data-testid={`replay-speed-${s}x`}
            >{s}x</button>
          ))}
        </div>
      </div>
    </div>
  );
}
