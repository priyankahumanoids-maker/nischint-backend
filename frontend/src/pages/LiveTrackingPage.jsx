import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import { MapContainer, TileLayer, Marker, Popup, Circle, Polyline, useMap } from 'react-leaflet';
import L from 'leaflet';
import {
  MapPin, Shield, Clock, Navigation, Loader2, AlertTriangle,
  RefreshCw, Activity, Footprints, Eye, Brain, Compass, Play, Square,
} from 'lucide-react';
import 'leaflet/dist/leaflet.css';

const API_BASE = '';  // same-origin — no CORS, no stale baked-URL risk
const POLL_INTERVAL = 8000;
const TRAIL_POLL_INTERVAL = 15000;
const CONTEXT_POLL_INTERVAL = 20000;

const RISK_COLORS = {
  SAFE:     { bg: '#10b981', glow: '#10b98140', text: '#34d399', label: 'Safe' },
  LOW:      { bg: '#10b981', glow: '#10b98140', text: '#34d399', label: 'Low Risk' },
  MODERATE: { bg: '#f59e0b', glow: '#f59e0b40', text: '#fbbf24', label: 'Moderate' },
  HIGH:     { bg: '#f97316', glow: '#f9731640', text: '#fb923c', label: 'High Risk' },
  CRITICAL: { bg: '#ef4444', glow: '#ef444440', text: '#f87171', label: 'Critical' },
};

const INSIGHT_STYLES = {
  clear:  { border: 'border-emerald-500/40', bg: 'bg-emerald-500/8', icon: 'text-emerald-400', title: 'text-emerald-400', line: 'text-emerald-300/70' },
  notice: { border: 'border-amber-500/40', bg: 'bg-amber-500/8', icon: 'text-amber-400', title: 'text-amber-400', line: 'text-amber-300/70' },
  alert:  { border: 'border-red-500/40', bg: 'bg-red-500/8', icon: 'text-red-400', title: 'text-red-400', line: 'text-red-300/70' },
};

const ZONE_STYLES = {
  home:     { color: '#1D9E75', fillOpacity: 0.15, weight: 2, dashArray: null },
  school:   { color: '#185FA5', fillOpacity: 0.15, weight: 2, dashArray: null },
  frequent: { color: '#888780', fillOpacity: 0.10, weight: 1, dashArray: null },
  danger:   { color: '#A32D2D', fillOpacity: 0.20, weight: 2, dashArray: '6 4' },
};

const ZONE_BADGE = {
  home:     { bg: 'bg-emerald-500/20', text: 'text-emerald-400', border: 'border-emerald-500/40' },
  school:   { bg: 'bg-blue-500/20', text: 'text-blue-400', border: 'border-blue-500/40' },
  frequent: { bg: 'bg-slate-500/20', text: 'text-slate-400', border: 'border-slate-500/40' },
  danger:   { bg: 'bg-red-500/20', text: 'text-red-400', border: 'border-red-500/40' },
  transit:  { bg: 'bg-slate-600/20', text: 'text-slate-400', border: 'border-slate-600/40' },
};

const TIMELINE_COLORS = {
  safe:     { dot: 'bg-emerald-400', text: 'text-emerald-300/80' },
  info:     { dot: 'bg-slate-500', text: 'text-slate-400' },
  notice:   { dot: 'bg-amber-400', text: 'text-amber-300/80' },
  warning:  { dot: 'bg-amber-500', text: 'text-amber-300/80' },
  critical: { dot: 'bg-red-500', text: 'text-red-300/80' },
};

// ── Icon factories ──

function createPulsingIcon(color) {
  return L.divIcon({
    className: '',
    html: `<div style="position:relative;width:40px;height:40px;"><div style="position:absolute;inset:0;border-radius:50%;background:${color}30;animation:pulse-ring 1.5s ease-out infinite;"></div><div style="position:absolute;top:8px;left:8px;width:24px;height:24px;border-radius:50%;background:${color};border:3px solid white;box-shadow:0 2px 8px ${color}80;"></div></div><style>@keyframes pulse-ring{0%{transform:scale(0.8);opacity:1}100%{transform:scale(2);opacity:0}}</style>`,
    iconSize: [40, 40], iconAnchor: [20, 20],
  });
}

function createStartIcon() {
  return L.divIcon({
    className: '',
    html: `<div style="width:18px;height:18px;border-radius:50%;background:#10b981;border:3px solid white;box-shadow:0 2px 6px rgba(16,185,129,.6);"></div>`,
    iconSize: [18, 18], iconAnchor: [9, 9],
  });
}

function createStopIcon(durationMin) {
  return L.divIcon({
    className: '',
    html: `<div style="position:relative;"><div style="width:16px;height:16px;border-radius:50%;background:#f59e0b;border:2px solid white;box-shadow:0 2px 6px rgba(245,158,11,.5);"></div><div style="position:absolute;top:-18px;left:50%;transform:translateX(-50%);white-space:nowrap;background:rgba(245,158,11,.9);color:white;font-size:9px;font-weight:700;padding:1px 5px;border-radius:4px;pointer-events:none;">Stopped ${durationMin}m</div></div>`,
    iconSize: [16, 16], iconAnchor: [8, 8],
  });
}

function createZoneLabelIcon(name) {
  return L.divIcon({
    className: '',
    html: `<div style="white-space:nowrap;font-size:11px;font-weight:600;color:rgba(255,255,255,.7);text-shadow:0 1px 3px rgba(0,0,0,.8);pointer-events:none;">${name}</div>`,
    iconSize: [0, 0], iconAnchor: [0, 0],
  });
}

// ── Map helpers ──

function MapRecenter({ lat, lng }) {
  const map = useMap();
  const first = useRef(true);
  useEffect(() => {
    if (lat && lng) {
      if (first.current) { map.setView([lat, lng], 15, { animate: false }); first.current = false; }
      else map.panTo([lat, lng], { animate: true, duration: 0.5 });
    }
  }, [lat, lng, map]);
  return null;
}

function formatDuration(s) {
  if (!s || s <= 0) return '0:00';
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}:${String(sec).padStart(2, '0')}`;
}

function timeAgo(isoStr) {
  if (!isoStr) return 'Unknown';
  const d = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000);
  if (d < 10) return 'Just now';
  if (d < 60) return `${d}s ago`;
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  return `${Math.floor(d / 3600)}h ago`;
}

function subsampleTrail(trail, max) {
  if (trail.length <= max) return trail;
  const step = (trail.length - 2) / (max - 2), r = [trail[0]];
  for (let i = 1; i < max - 1; i++) r.push(trail[Math.round(i * step)]);
  r.push(trail[trail.length - 1]);
  return r;
}

// ── Main Component ──

export default function LiveTrackingPage() {
  const { token } = useParams();
  const [data, setData] = useState(null);
  const [trail, setTrail] = useState(null);
  const [context, setContext] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastPoll, setLastPoll] = useState(null);
  const [replaying, setReplaying] = useState(false);
  const [replayIdx, setReplayIdx] = useState(0);
  const [replayTime, setReplayTime] = useState('');
  const replayTimer = useRef(null);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/location/track/${token}`);
      if (!res.ok) { setError(res.status === 404 ? 'not_found' : 'fetch_error'); setLoading(false); return; }
      setData(await res.json()); setError(null); setLastPoll(new Date());
    } catch { setError('fetch_error'); }
    setLoading(false);
  }, [token]);

  const fetchTrail = useCallback(async () => {
    try { const r = await fetch(`${API_BASE}/api/location/track/${token}/trail`); if (r.ok) setTrail(await r.json()); } catch {}
  }, [token]);

  const fetchContext = useCallback(async () => {
    try { const r = await fetch(`${API_BASE}/api/location/track/${token}/context`); if (r.ok) setContext(await r.json()); } catch {}
  }, [token]);

  const startReplay = useCallback(() => {
    if (!trail?.trail?.length || trail.trail.length < 2) return;
    setReplaying(true); setReplayIdx(0); setReplayTime(trail.trail[0].recorded_at_ist);
    let idx = 0;
    replayTimer.current = setInterval(() => {
      idx++;
      if (idx >= trail.trail.length) { clearInterval(replayTimer.current); replayTimer.current = null; setReplaying(false); return; }
      setReplayIdx(idx); setReplayTime(trail.trail[idx].recorded_at_ist);
    }, 300);
  }, [trail]);

  const stopReplay = useCallback(() => {
    if (replayTimer.current) { clearInterval(replayTimer.current); replayTimer.current = null; }
    setReplaying(false); setReplayIdx(0); setReplayTime('');
  }, []);

  useEffect(() => {
    fetchData(); fetchTrail(); fetchContext();
    const i1 = setInterval(fetchData, POLL_INTERVAL);
    const i2 = setInterval(fetchTrail, TRAIL_POLL_INTERVAL);
    const i3 = setInterval(fetchContext, CONTEXT_POLL_INTERVAL);
    return () => { clearInterval(i1); clearInterval(i2); clearInterval(i3); };
  }, [fetchData, fetchTrail, fetchContext]);

  // Error / status screens
  if (loading) return <LoadingScreen />;
  if (error === 'not_found') return <ErrorState icon={<AlertTriangle className="w-8 h-8 text-red-400" />} title="Link Not Found" msg="This tracking link is invalid or has been removed." testId="tracking-not-found" />;
  if (error === 'fetch_error') return <ErrorState icon={<AlertTriangle className="w-8 h-8 text-amber-400" />} title="Connection Error" msg="Could not load tracking data." testId="tracking-error" action={<button onClick={fetchData} className="px-5 py-2 rounded-full bg-teal-500 text-white text-sm font-medium" data-testid="retry-btn"><RefreshCw className="w-4 h-4 inline mr-1.5" />Retry</button>} />;
  if (data?.status === 'expired') return <ErrorState icon={<Clock className="w-8 h-8 text-amber-400" />} title="Link Expired" msg={<>Tracking link for <span className="text-white font-medium">{data.share_name}</span> has expired.</>} testId="tracking-expired" bgClass="bg-amber-500/15" />;
  if (data?.status === 'inactive') return <ErrorState icon={<Eye className="w-8 h-8 text-slate-500" />} title="Tracking Stopped" msg={<><span className="text-white font-medium">{data.share_name}</span> has stopped sharing.</>} testId="tracking-inactive" bgClass="bg-slate-700/50" />;

  const risk = RISK_COLORS[data?.risk_level] || RISK_COLORS.SAFE;
  const hasLocation = data?.lat != null && data?.lng != null;
  const expiresIn = data?.expires_at ? Math.max(0, Math.floor((new Date(data.expires_at).getTime() - Date.now()) / 60000)) : 0;
  const insight = data?.ai_insight;
  const insightStyle = insight ? (INSIGHT_STYLES[insight.state] || INSIGHT_STYLES.clear) : null;
  const summary = trail?.movement_summary;
  const hasTrail = trail?.has_data && trail?.trail?.length >= 2;
  const currentZone = context?.current_zone;
  const zones = context?.zones || [];
  const timeline = context?.timeline || [];
  const aiContext = context?.ai_context;

  // Zone badge
  const zoneBadgeType = currentZone?.type || 'transit';
  const zoneBadgeStyle = ZONE_BADGE[zoneBadgeType] || ZONE_BADGE.transit;
  const zoneBadgeText = currentZone
    ? `In ${currentZone.name.split(' - ')[0]} Zone`
    : 'In Transit';

  // Check for recent exit for "Left X · Y min ago" badge
  const recentExit = !currentZone && zones.find(z => z.child_exited_at_ist);
  const leftBadge = recentExit ? `Left ${recentExit.name.split(' - ')[0]}` : null;

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col" data-testid="live-tracking-page">
      {/* Header */}
      <div className="px-4 py-3 bg-slate-900/90 border-b border-slate-800 backdrop-blur-sm z-20 relative">
        <div className="flex items-center justify-between max-w-xl mx-auto">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-teal-500/15 flex items-center justify-center">
              <Shield className="w-5 h-5 text-teal-400" />
            </div>
            <div>
              <h1 className="text-sm font-bold text-white leading-tight" data-testid="share-name">{data?.share_name}</h1>
              <div className="flex items-center gap-1.5">
                {data?.session_active && <span className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse" />}
                <span className="text-[10px] text-slate-500">{data?.session_active ? 'Live Tracking' : 'Last Known Location'}</span>
              </div>
            </div>
          </div>
          <div className="flex flex-col items-end gap-1">
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full" style={{ background: `${risk.bg}20`, color: risk.text, border: `1px solid ${risk.bg}40` }} data-testid="risk-badge">{risk.label}</span>
            {/* Zone status badge */}
            <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full border ${zoneBadgeStyle.bg} ${zoneBadgeStyle.text} ${zoneBadgeStyle.border} ${currentZone?.type === 'danger' ? 'animate-pulse' : ''}`} data-testid="zone-badge">
              {leftBadge || zoneBadgeText}
            </span>
          </div>
        </div>
      </div>

      {/* Map */}
      <div className="flex-1 relative z-10" data-testid="tracking-map">
        {hasLocation ? (
          <MapContainer center={[data.lat, data.lng]} zoom={15} className="w-full h-full" style={{ minHeight: '38vh' }} zoomControl={false} attributionControl={false}>
            <TileLayer url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" />
            <MapRecenter lat={data.lat} lng={data.lng} />
            {data.accuracy_m > 0 && <Circle center={[data.lat, data.lng]} radius={data.accuracy_m} pathOptions={{ color: risk.bg, fillColor: risk.glow, fillOpacity: 0.15, weight: 1 }} />}

            {/* Geofence zone circles */}
            <ZoneCircles zones={zones} currentZone={currentZone} />

            {/* Trail polyline */}
            {hasTrail && <TrailPolyline trail={trail.trail} />}

            {/* Start marker */}
            {hasTrail && (
              <Marker position={[trail.trail[0].lat, trail.trail[0].lng]} icon={createStartIcon()}>
                <Popup><span className="text-xs font-bold">Started {trail.trail[0].recorded_at_ist}</span></Popup>
              </Marker>
            )}

            {/* Stop markers */}
            {hasTrail && <StopMarkers trail={trail.trail} />}

            {/* Current location */}
            <Marker position={[data.lat, data.lng]} icon={createPulsingIcon(risk.bg)}>
              <Popup><div className="text-xs"><p className="font-bold">{data.share_name}</p><p>{data.lat.toFixed(5)}, {data.lng.toFixed(5)}</p></div></Popup>
            </Marker>

            {/* Replay dot */}
            {replaying && hasTrail && trail.trail[replayIdx] && <ReplayDot lat={trail.trail[replayIdx].lat} lng={trail.trail[replayIdx].lng} time={replayTime} />}
          </MapContainer>
        ) : (
          <div className="flex items-center justify-center h-full min-h-[38vh] bg-slate-900">
            <div className="text-center"><MapPin className="w-10 h-10 text-slate-600 mx-auto mb-3" /><p className="text-slate-500 text-sm">Waiting for location data...</p></div>
          </div>
        )}
      </div>

      {/* Info Panel */}
      <div className="bg-slate-900 border-t border-slate-800 px-4 pt-4 pb-6 z-20 relative overflow-y-auto" style={{ maxHeight: '55vh' }} data-testid="tracking-info-panel">
        <div className="max-w-xl mx-auto space-y-3">

          {/* AI Insight */}
          {insight && (
            <div className={`p-3 rounded-xl border ${insightStyle.border} ${insightStyle.bg}`} data-testid="ai-insight-panel">
              <div className="flex items-center gap-2 mb-2">
                <Brain className={`w-4 h-4 ${insightStyle.icon}`} />
                <span className={`text-xs font-bold uppercase tracking-wider ${insightStyle.title}`}>{insight.title}</span>
              </div>
              <div className="space-y-0.5">{insight.lines.map((l, i) => <p key={i} className={`text-xs ${insightStyle.line}`}>{l}</p>)}</div>
            </div>
          )}

          {/* AI Context (Geofence) */}
          {aiContext && <AIContextPanel aiContext={aiContext} currentZone={currentZone} />}

          {/* Movement Summary */}
          <MovementSummaryPanel summary={summary} hasTrail={hasTrail} />

          {/* Replay */}
          {hasTrail && trail.trail.length >= 3 && (
            <div className="flex items-center gap-2">
              <button onClick={replaying ? stopReplay : startReplay} className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl text-xs font-bold transition-all ${replaying ? 'bg-red-500/15 border border-red-500/40 text-red-400' : 'bg-teal-500/15 border border-teal-500/40 text-teal-400 hover:bg-teal-500/25'}`} data-testid="replay-journey-btn">
                {replaying ? <><Square className="w-3.5 h-3.5" /> Stop Replay</> : <><Play className="w-3.5 h-3.5" /> Replay Journey</>}
              </button>
              {replaying && <span className="text-xs font-mono text-teal-400 bg-teal-500/10 border border-teal-500/30 px-2.5 py-2 rounded-xl" data-testid="replay-time">{replayTime}</span>}
            </div>
          )}

          {/* Movement Timeline */}
          {timeline.length > 0 && <TimelinePanel events={timeline} />}

          {/* Stats */}
          <div className="grid grid-cols-3 gap-2">
            <InfoCard icon={<Clock className="w-4 h-4 text-blue-400" />} label="Duration" value={data?.session_active ? formatDuration(data.session_duration_s) : '--'} testId="stat-duration" />
            <InfoCard icon={<Navigation className="w-4 h-4 text-teal-400" />} label="Distance" value={data?.session_active ? `${(data.total_distance_m / 1000).toFixed(2)} km` : '--'} testId="stat-distance" />
            <InfoCard icon={<Activity className="w-4 h-4 text-purple-400" />} label="Speed" value={data?.speed_mps ? `${(data.speed_mps * 3.6).toFixed(1)} km/h` : '--'} testId="stat-speed" />
          </div>

          {data?.destination_name && (
            <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-800/60 border border-slate-700/40">
              <Footprints className="w-4 h-4 text-teal-400 shrink-0" />
              <span className="text-xs text-slate-300">Heading to <span className="text-white font-medium">{data.destination_name}</span></span>
            </div>
          )}

          {/* Footer */}
          <div className="flex items-center justify-between pt-1">
            <div className="flex items-center gap-1.5">
              <RefreshCw className="w-3 h-3 text-slate-600" />
              <span className="text-[10px] text-slate-600" data-testid="last-updated">Updated {timeAgo(data?.last_updated)} {lastPoll && `| Polled ${timeAgo(lastPoll.toISOString())}`}</span>
            </div>
            <span className="text-[10px] text-slate-600" data-testid="expires-in">Expires in {expiresIn > 60 ? `${Math.floor(expiresIn / 60)}h ${expiresIn % 60}m` : `${expiresIn}m`}</span>
          </div>
          <div className="text-center pt-1">
            <span className="text-[10px] text-slate-400">Powered by <span className="text-teal-600 font-semibold">Nischint</span> Safety Intelligence</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Sub-components ──

function LoadingScreen() {
  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center" data-testid="tracking-loading">
      <div className="text-center"><Loader2 className="w-10 h-10 text-teal-400 animate-spin mx-auto mb-4" /><p className="text-slate-400 text-sm">Loading live tracking...</p></div>
    </div>
  );
}

function ErrorState({ icon, title, msg, testId, bgClass = 'bg-red-500/15', action }) {
  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center px-6" data-testid={testId}>
      <div className="text-center max-w-sm">
        <div className={`w-16 h-16 rounded-full ${bgClass} flex items-center justify-center mx-auto mb-4`}>{icon}</div>
        <h1 className="text-xl font-bold text-white mb-2">{title}</h1>
        <p className="text-slate-400 text-sm mb-4">{msg}</p>
        {action}
      </div>
    </div>
  );
}

function ZoneCircles({ zones, currentZone }) {
  return zones.map(z => {
    const style = ZONE_STYLES[z.type] || ZONE_STYLES.frequent;
    const showLabel = z.child_currently_inside || (currentZone === null && z.child_exited_at_ist);
    return (
      <React.Fragment key={z.id}>
        <Circle
          center={[z.lat, z.lng]}
          radius={z.radius_metres}
          pathOptions={{ color: style.color, fillColor: style.color, fillOpacity: style.fillOpacity, weight: style.weight, dashArray: style.dashArray }}
        />
        {showLabel && (
          <Marker position={[z.lat, z.lng]} icon={createZoneLabelIcon(z.name.split(' - ')[0])} interactive={false} />
        )}
      </React.Fragment>
    );
  });
}

function TrailPolyline({ trail }) {
  const segments = useMemo(() => {
    const sampled = subsampleTrail(trail, 120);
    const coords = sampled.map(p => [p.lat, p.lng]);
    const brightCount = Math.min(40, coords.length);
    const fadeCount = coords.length - brightCount;
    return { faded: coords.slice(0, fadeCount + 1), bright: coords.slice(fadeCount) };
  }, [trail]);
  return (
    <>
      {segments.faded.length > 1 && <Polyline positions={segments.faded} pathOptions={{ color: '#1D9E75', weight: 3, opacity: 0.2, smoothFactor: 2 }} />}
      {segments.bright.length > 1 && <Polyline positions={segments.bright} pathOptions={{ color: '#1D9E75', weight: 3, opacity: 1.0, smoothFactor: 2 }} />}
    </>
  );
}

function StopMarkers({ trail }) {
  const stops = useMemo(() => {
    const r = []; let i = 0;
    while (i < trail.length) {
      if (trail[i].is_stop) {
        const s = i;
        while (i < trail.length && trail[i].is_stop) i++;
        const dm = Math.round(((i - s) * 30) / 60);
        if (dm >= 2) { const mid = trail[Math.floor((s + i - 1) / 2)]; r.push({ lat: mid.lat, lng: mid.lng, durationMin: dm, time: trail[s].recorded_at_ist }); }
      } else i++;
    }
    return r;
  }, [trail]);
  return stops.map((s, i) => (
    <Marker key={`stop-${i}`} position={[s.lat, s.lng]} icon={createStopIcon(s.durationMin)}>
      <Popup><span className="text-xs">Stopped {s.durationMin} min at {s.time}</span></Popup>
    </Marker>
  ));
}

function ReplayDot({ lat, lng, time }) {
  const icon = useMemo(() => L.divIcon({
    className: '',
    html: `<div style="position:relative;"><div style="width:14px;height:14px;border-radius:50%;background:#3b82f6;border:2px solid white;box-shadow:0 0 12px rgba(59,130,246,.7);"></div><div style="position:absolute;top:-20px;left:50%;transform:translateX(-50%);white-space:nowrap;background:rgba(59,130,246,.9);color:white;font-size:9px;font-weight:700;padding:1px 6px;border-radius:4px;pointer-events:none;">${time}</div></div>`,
    iconSize: [14, 14], iconAnchor: [7, 7],
  }), [time]);
  return <Marker position={[lat, lng]} icon={icon} />;
}

function AIContextPanel({ aiContext, currentZone }) {
  const isWarning = aiContext.includes('attention') || aiContext.includes('deviation') || aiContext.includes('unfamiliar');
  const isDanger = aiContext.includes('flagged') || aiContext.includes('HIGH');
  const isSafe = aiContext.includes('safely') || aiContext.includes('No concern') || aiContext.includes('normally');
  const style = isDanger ? 'border-red-500/40 bg-red-500/8' : isWarning ? 'border-amber-500/40 bg-amber-500/8' : 'border-emerald-500/40 bg-emerald-500/8';
  const titleColor = isDanger ? 'text-red-400' : isWarning ? 'text-amber-400' : 'text-emerald-400';

  return (
    <div className={`p-3 rounded-xl border ${style}`} data-testid="ai-context-panel">
      <div className="flex items-center gap-2 mb-2">
        <Brain className={`w-4 h-4 ${titleColor}`} />
        <span className={`text-xs font-bold uppercase tracking-wider ${titleColor}`}>AI Context</span>
      </div>
      <p className={`text-xs ${titleColor.replace('400', '300/80')}`}>{aiContext}</p>
    </div>
  );
}

function MovementSummaryPanel({ summary, hasTrail }) {
  if (!hasTrail || !summary) {
    return (
      <div className="p-3 rounded-xl border border-slate-700/40 bg-slate-800/40" data-testid="movement-summary-panel">
        <div className="flex items-center gap-2 mb-1"><Compass className="w-4 h-4 text-slate-500" /><span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Movement Summary</span></div>
        <p className="text-xs text-slate-500">Tracking started · Waiting for movement data...</p>
      </div>
    );
  }
  const bc = summary.deviation_detected ? (summary.stop_count > 0 ? 'border-red-500/40' : 'border-amber-500/40') : (summary.stops_total_min > 5 ? 'border-amber-500/40' : 'border-emerald-500/40');
  const bg = summary.deviation_detected ? (summary.stop_count > 0 ? 'bg-red-500/8' : 'bg-amber-500/8') : (summary.stops_total_min > 5 ? 'bg-amber-500/8' : 'bg-emerald-500/8');
  const ic = summary.deviation_detected ? (summary.stop_count > 0 ? 'text-red-400' : 'text-amber-400') : (summary.stops_total_min > 5 ? 'text-amber-400' : 'text-emerald-400');
  return (
    <div className={`p-3 rounded-xl border ${bc} ${bg}`} data-testid="movement-summary-panel">
      <div className="flex items-center gap-2 mb-2"><Compass className={`w-4 h-4 ${ic}`} /><span className={`text-xs font-bold uppercase tracking-wider ${ic}`}>Movement Summary</span></div>
      <div className="space-y-1 text-xs text-slate-300">
        <p>Started at {summary.started_at_ist}</p>
        <p>Distance: {summary.total_distance_km} km · {summary.total_duration_min} min</p>
        {summary.stop_count > 0 && <p>Stops: {summary.stop_count} ({summary.stops_total_min} min total)</p>}
      </div>
      <p className={`text-xs mt-2 italic ${ic}`} data-testid="ai-interpretation">"{summary.ai_interpretation}"</p>
    </div>
  );
}

function TimelinePanel({ events }) {
  const reversed = [...events].reverse().slice(0, 10);
  return (
    <div className="p-3 rounded-xl border border-slate-700/40 bg-slate-800/40" data-testid="movement-timeline">
      <div className="flex items-center gap-2 mb-3">
        <Compass className="w-4 h-4 text-slate-400" />
        <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">Movement Timeline</span>
      </div>
      <div className="space-y-0">
        {reversed.map((ev, i) => {
          const c = TIMELINE_COLORS[ev.severity] || TIMELINE_COLORS.info;
          const isLast = i === reversed.length - 1;
          return (
            <div key={i} className="flex items-start gap-2.5 relative" data-testid="timeline-event">
              <div className="flex flex-col items-center shrink-0 mt-0.5">
                <div className={`w-2 h-2 rounded-full ${c.dot}`} />
                {!isLast && <div className="w-px flex-1 bg-slate-700/60 min-h-[16px]" />}
              </div>
              <div className="flex-1 pb-2">
                <div className="flex items-baseline gap-2">
                  <span className="text-[10px] font-mono text-slate-500 shrink-0">{ev.time_ist}</span>
                  <span className={`text-xs ${c.text}`}>{ev.label}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function InfoCard({ icon, label, value, testId }) {
  return (
    <div className="p-2.5 rounded-xl bg-slate-800/60 border border-slate-700/30 text-center" data-testid={testId}>
      <div className="flex justify-center mb-1">{icon}</div>
      <p className="text-sm font-bold text-white font-mono">{value}</p>
      <p className="text-[9px] text-slate-500 uppercase">{label}</p>
    </div>
  );
}
