import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import api from '../api';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  Play, Pause, SkipForward, SkipBack, Rewind, FastForward,
  ArrowLeft, Shield, Clock, MapPin, AlertTriangle, CheckCircle,
  Bell, UserCheck, Loader2, Radio, Eye, Brain, Zap, Timer, Target, ChevronRight,
} from 'lucide-react';
import { MapContainer, TileLayer, Marker, Popup, Polyline, CircleMarker, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

/* Inject styles */
if (typeof document !== 'undefined' && !document.getElementById('replay-styles')) {
  const s = document.createElement('style');
  s.id = 'replay-styles';
  s.textContent = `
    @keyframes replayPulse { 0%,100%{transform:scale(1);opacity:1} 50%{transform:scale(1.4);opacity:.7} }
    .replay-marker-pulse { animation: replayPulse 1s ease-in-out infinite; }
    .journey-glow { filter: drop-shadow(0 0 6px #00e5ff); }
    .journey-trail-fade { opacity: 0.3; filter: drop-shadow(0 0 3px #00e5ff); }
    @keyframes trailDotFade { 0%{opacity:0.8;transform:scale(1)} 100%{opacity:0;transform:scale(0.3)} }
    .trail-dot { animation: trailDotFade 3s ease-out forwards; }
    @keyframes trailFade { 0%{opacity:.8} 100%{opacity:.2} }
    .replay-timeline-active { background: rgba(6,182,212,.12); border-left: 3px solid #06b6d4; }
    .replay-progress::-webkit-slider-thumb { -webkit-appearance:none; width:14px; height:14px; border-radius:50%; background:#06b6d4; cursor:pointer; border:2px solid #0f172a; }
    .replay-progress::-moz-range-thumb { width:14px; height:14px; border-radius:50%; background:#06b6d4; cursor:pointer; border:2px solid #0f172a; }
  `;
  document.head.appendChild(s);
}

const currentMarkerIcon = new L.DivIcon({
  className: '',
  html: `<div class="replay-marker-pulse" style="width:22px;height:22px;border-radius:50%;background:#06b6d4;border:3px solid #fff;box-shadow:0 0 10px #00e5ff,0 0 20px #00e5ff,0 0 30px rgba(0,229,255,0.3)"></div>`,
  iconSize: [22, 22],
  iconAnchor: [11, 11],
});

const SPEED_OPTIONS = [0.5, 1, 2, 4];

const RISK_PANEL_COLORS = {
  critical: { bg: 'bg-red-500/10', border: 'border-red-500/30', text: 'text-red-400', accent: 'text-red-300' },
  high: { bg: 'bg-orange-500/10', border: 'border-orange-500/30', text: 'text-orange-400', accent: 'text-orange-300' },
  moderate: { bg: 'bg-amber-500/10', border: 'border-amber-500/30', text: 'text-amber-400', accent: 'text-amber-300' },
  low: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', text: 'text-emerald-400', accent: 'text-emerald-300' },
  CRITICAL: { bg: 'bg-red-500/10', border: 'border-red-500/30', text: 'text-red-400', accent: 'text-red-300' },
  HIGH: { bg: 'bg-orange-500/10', border: 'border-orange-500/30', text: 'text-orange-400', accent: 'text-orange-300' },
  SAFE: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', text: 'text-emerald-400', accent: 'text-emerald-300' },
};

const fmtTime = (s) => {
  if (!s && s !== 0) return '—';
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return sec > 0 ? `${m}m ${sec}s` : `${m}m`;
};

/* AI Incident Analysis Panel — appears after replay ends */
const AIAnalysisPanel = ({ sessionId, visible, onClose }) => {
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!visible || !sessionId) return;
    setLoading(true);
    api.get(`/replay/${sessionId}/analysis`)
      .then(r => setAnalysis(r.data))
      .catch(() => setAnalysis(null))
      .finally(() => setLoading(false));
  }, [visible, sessionId]);

  if (!visible) return null;

  const risk = analysis?.risk_analysis || {};
  const resp = analysis?.response_times || {};
  const preventable = analysis?.preventable_moments || [];
  const recs = analysis?.recommendations || [];
  const rColors = RISK_PANEL_COLORS[risk.peak_level] || RISK_PANEL_COLORS.low;

  return (
    <div className="absolute inset-0 z-[1100] bg-slate-900/95 backdrop-blur-md flex items-center justify-center p-6" data-testid="ai-analysis-panel">
      {loading ? (
        <div className="text-center">
          <Brain className="w-10 h-10 text-purple-400 animate-pulse mx-auto mb-3" />
          <p className="text-sm text-slate-400">Analyzing session...</p>
        </div>
      ) : !analysis ? (
        <div className="text-center">
          <p className="text-sm text-slate-500">Analysis unavailable</p>
          <Button size="sm" variant="ghost" className="mt-2 text-slate-400" onClick={onClose}>Close</Button>
        </div>
      ) : (
        <div className="w-full max-w-3xl max-h-[80vh] overflow-y-auto" data-testid="ai-analysis-content">
          {/* Header */}
          <div className="flex items-center justify-between mb-5">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-purple-500/20 flex items-center justify-center border border-purple-500/30">
                <Brain className="w-5 h-5 text-purple-400" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-white">AI Incident Analysis</h2>
                <p className="text-[10px] text-slate-500">Guardian AI post-session intelligence</p>
              </div>
            </div>
            <Button size="sm" variant="ghost" className="text-slate-400 hover:text-white" onClick={onClose} data-testid="close-analysis">
              Close
            </Button>
          </div>

          <div className="grid grid-cols-3 gap-3 mb-4">
            {/* Risk Peak */}
            <div className={`p-4 rounded-xl border ${rColors.border} ${rColors.bg}`} data-testid="risk-peak-card">
              <div className="flex items-center gap-2 mb-2">
                <Zap className={`w-4 h-4 ${rColors.text}`} />
                <span className="text-[10px] uppercase text-slate-500 font-medium">Risk Peak</span>
              </div>
              <p className={`text-3xl font-bold font-mono ${rColors.accent}`}>{(risk.peak_score * 10).toFixed(1)}</p>
              <Badge className={`text-[9px] mt-1 ${rColors.bg} ${rColors.text} border ${rColors.border}`}>
                {risk.peak_level}
              </Badge>
              {risk.peak_time && (
                <p className="text-[9px] text-slate-500 mt-1">
                  at {new Date(risk.peak_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </p>
              )}
            </div>

            {/* Response Time */}
            <div className="p-4 rounded-xl border border-blue-500/30 bg-blue-500/5" data-testid="response-time-card">
              <div className="flex items-center gap-2 mb-2">
                <Timer className="w-4 h-4 text-blue-400" />
                <span className="text-[10px] uppercase text-slate-500 font-medium">Response Time</span>
              </div>
              <p className="text-3xl font-bold font-mono text-blue-300">{fmtTime(resp.avg_dispatch_s)}</p>
              <p className="text-[9px] text-slate-500 mt-1">Avg dispatch delay</p>
              {resp.avg_resolution_s && (
                <p className="text-[9px] text-slate-400 mt-0.5">Resolution: {fmtTime(resp.avg_resolution_s)}</p>
              )}
            </div>

            {/* Incidents */}
            <div className="p-4 rounded-xl border border-slate-700/50 bg-slate-800/30" data-testid="incidents-count-card">
              <div className="flex items-center gap-2 mb-2">
                <Target className="w-4 h-4 text-slate-400" />
                <span className="text-[10px] uppercase text-slate-500 font-medium">Incidents</span>
              </div>
              <p className="text-3xl font-bold font-mono text-white">{resp.incidents_count || 0}</p>
              <p className="text-[9px] text-slate-500 mt-1">During session</p>
              <p className="text-[9px] text-slate-400 mt-0.5">Duration: {fmtTime(analysis.duration_seconds)}</p>
            </div>
          </div>

          {/* Top Risk Factors */}
          {risk.peak_factors?.length > 0 && (
            <div className="mb-4 p-3 rounded-xl border border-slate-700/50 bg-slate-800/20" data-testid="risk-factors">
              <h3 className="text-xs font-semibold text-slate-300 mb-2 flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />Top Risk Factors
              </h3>
              <div className="space-y-1.5">
                {risk.peak_factors.map((f, i) => (
                  <div key={i} className="flex items-center gap-2 text-[11px]">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
                    <span className="text-slate-300">{f.description}</span>
                    {f.impact > 0 && <span className="text-[9px] text-slate-500 ml-auto">{(f.impact * 100).toFixed(0)}% impact</span>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Preventable Moments */}
          {preventable.length > 0 && (
            <div className="mb-4 p-3 rounded-xl border border-orange-500/20 bg-orange-500/5" data-testid="preventable-moments">
              <h3 className="text-xs font-semibold text-orange-300 mb-2 flex items-center gap-1.5">
                <Shield className="w-3.5 h-3.5 text-orange-400" />Preventable Moments
              </h3>
              <div className="space-y-2">
                {preventable.map((p, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <ChevronRight className={`w-3 h-3 mt-0.5 shrink-0 ${p.impact === 'critical' ? 'text-red-400' : p.impact === 'high' ? 'text-orange-400' : 'text-amber-400'}`} />
                    <div>
                      <p className="text-[11px] text-slate-200 font-medium">{p.moment}</p>
                      <p className="text-[10px] text-slate-400">{p.detail}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Recommendations */}
          <div className="p-3 rounded-xl border border-purple-500/20 bg-purple-500/5" data-testid="recommendations">
            <h3 className="text-xs font-semibold text-purple-300 mb-2 flex items-center gap-1.5">
              <Brain className="w-3.5 h-3.5 text-purple-400" />Recommendations
            </h3>
            <div className="space-y-1.5">
              {recs.map((r, i) => (
                <div key={i} className="flex items-start gap-2 text-[11px]">
                  <span className="w-1.5 h-1.5 rounded-full bg-purple-400 mt-1.5 shrink-0" />
                  <span className="text-slate-300">{r}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const TYPE_CONFIG = {
  session_start: { icon: Play, label: 'Session Start', bg: 'bg-blue-500/15', text: 'text-blue-400' },
  session_end: { icon: CheckCircle, label: 'Session End', bg: 'bg-slate-500/15', text: 'text-slate-400' },
  movement: { icon: MapPin, label: 'Movement', bg: 'bg-cyan-500/10', text: 'text-cyan-400' },
  idle_start: { icon: Clock, label: 'Idle', bg: 'bg-amber-500/15', text: 'text-amber-400' },
  route_deviation: { icon: AlertTriangle, label: 'Route Deviation', bg: 'bg-orange-500/15', text: 'text-orange-400' },
  risk_change: { icon: Shield, label: 'Risk Change', bg: 'bg-purple-500/15', text: 'text-purple-400' },
  guardian_alert: { icon: Bell, label: 'Alert', bg: 'bg-red-500/15', text: 'text-red-400' },
  incident_created: { icon: Radio, label: 'Incident', bg: 'bg-red-500/15', text: 'text-red-400' },
  incident_acknowledged: { icon: Eye, label: 'Acknowledged', bg: 'bg-blue-500/15', text: 'text-blue-400' },
  caregiver_assigned: { icon: UserCheck, label: 'Caregiver Dispatched', bg: 'bg-amber-500/15', text: 'text-amber-400' },
  caregiver_visit: { icon: CheckCircle, label: 'Visit', bg: 'bg-emerald-500/15', text: 'text-emerald-400' },
  incident_resolved: { icon: CheckCircle, label: 'Resolved', bg: 'bg-emerald-500/15', text: 'text-emerald-400' },
};

const fallback = { icon: MapPin, label: 'Event', bg: 'bg-slate-500/15', text: 'text-slate-400' };

/* Map auto-pan to current event */
const MapPan = ({ lat, lng, fitAll }) => {
  const map = useMap();
  const prevRef = useRef(null);
  const fittedRef = useRef(false);

  // Fit entire journey on first render
  useEffect(() => {
    if (fitAll && fitAll.length > 1 && !fittedRef.current) {
      fittedRef.current = true;
      const bounds = L.latLngBounds(fitAll.map(e => [e.lat, e.lng]));
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
    }
  }, [fitAll, map]);

  useEffect(() => {
    if (lat && lng) {
      const prev = prevRef.current;
      if (!prev || Math.abs(lat - prev.lat) > 0.02 || Math.abs(lng - prev.lng) > 0.02) {
        map.flyTo([lat, lng], 15, { animate: true, duration: 0.8, easeLinearity: 0.25 });
      } else {
        map.panTo([lat, lng], { animate: true, duration: 0.4 });
      }
      prevRef.current = { lat, lng };
    }
  }, [lat, lng, map]);

  return null;
};

/* ════════════════════════════════════════
   SESSION LIST PAGE
   ════════════════════════════════════════ */
const SessionList = () => {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/replay/sessions?limit=30')
      .then(r => setSessions(r.data?.sessions || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return (
    <div className="h-screen bg-slate-900 flex items-center justify-center">
      <Loader2 className="w-8 h-8 animate-spin text-cyan-500" />
    </div>
  );

  return (
    <div className="min-h-screen bg-slate-900 text-white" data-testid="replay-sessions">
      <div className="max-w-4xl mx-auto px-6 py-8">
        <div className="flex items-center gap-3 mb-8">
          <Link to="/operator-dashboard" className="text-slate-400 hover:text-white transition-colors">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div className="w-10 h-10 rounded-lg bg-cyan-500/20 flex items-center justify-center border border-cyan-500/30">
            <Play className="w-5 h-5 text-cyan-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold">Journey Replay</h1>
            <p className="text-xs text-slate-400">Select a guardian session to replay</p>
          </div>
        </div>

        {sessions.length === 0 ? (
          <div className="text-center py-16">
            <p className="text-slate-500">No sessions available for replay</p>
          </div>
        ) : (
          <div className="space-y-2">
            {sessions.map(s => (
              <Link
                key={s.id}
                to={`/replay/${s.id}`}
                className="block p-4 rounded-lg bg-slate-800/50 border border-slate-700/50 hover:border-cyan-500/30 hover:bg-slate-800/80 transition-all group"
                data-testid={`replay-session-${s.id}`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={`w-8 h-8 rounded-full flex items-center justify-center ${s.risk_level === 'CRITICAL' ? 'bg-red-500/20' : s.risk_level === 'HIGH' ? 'bg-orange-500/20' : 'bg-emerald-500/20'}`}>
                      <Shield className={`w-4 h-4 ${s.risk_level === 'CRITICAL' ? 'text-red-400' : s.risk_level === 'HIGH' ? 'text-orange-400' : 'text-emerald-400'}`} />
                    </div>
                    <div>
                      <p className="text-sm font-medium text-white group-hover:text-cyan-300 transition-colors">{s.user_name}</p>
                      <p className="text-[10px] text-slate-500">
                        {s.started_at ? new Date(s.started_at).toLocaleString() : 'Unknown'} — {s.status}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <div className="text-right">
                      <Badge className={`text-[9px] ${s.risk_level === 'CRITICAL' ? 'bg-red-500/20 text-red-400' : s.risk_level === 'HIGH' ? 'bg-orange-500/20 text-orange-400' : 'bg-emerald-500/20 text-emerald-400'}`}>
                        {s.risk_level}
                      </Badge>
                    </div>
                    <div className="text-right text-[10px] text-slate-500">
                      <p>{s.alert_count} alerts</p>
                      <p>{Math.round(s.total_distance_m)}m traveled</p>
                    </div>
                    <Play className="w-4 h-4 text-slate-600 group-hover:text-cyan-400 transition-colors" />
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

/* ════════════════════════════════════════
   REPLAY PLAYER PAGE
   ════════════════════════════════════════ */
const ReplayPlayer = () => {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [currentIdx, setCurrentIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [showAnalysis, setShowAnalysis] = useState(false);
  const intervalRef = useRef(null);
  const timelineRef = useRef(null);

  useEffect(() => {
    api.get(`/replay/${sessionId}`)
      .then(r => setData(r.data))
      .catch(() => navigate('/replay'))
      .finally(() => setLoading(false));
  }, [sessionId, navigate]);

  const events = data?.events || [];
  const currentEvent = events[currentIdx] || null;

  // Playback
  useEffect(() => {
    if (playing && events.length > 0) {
      intervalRef.current = setInterval(() => {
        setCurrentIdx(prev => {
          if (prev >= events.length - 1) {
            setPlaying(false);
            setShowAnalysis(true);
            return prev;
          }
          return prev + 1;
        });
      }, 1500 / speed);
    }
    return () => clearInterval(intervalRef.current);
  }, [playing, speed, events.length]);

  // Auto-scroll timeline
  useEffect(() => {
    if (timelineRef.current) {
      const active = timelineRef.current.querySelector('.replay-timeline-active');
      if (active) active.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [currentIdx]);

  const togglePlay = () => setPlaying(p => !p);
  const stepForward = () => { setPlaying(false); setCurrentIdx(i => Math.min(i + 1, events.length - 1)); };
  const stepBack = () => { setPlaying(false); setCurrentIdx(i => Math.max(i - 1, 0)); };
  const restart = () => { setCurrentIdx(0); setPlaying(false); };
  const cycleSpeed = () => {
    const idx = SPEED_OPTIONS.indexOf(speed);
    setSpeed(SPEED_OPTIONS[(idx + 1) % SPEED_OPTIONS.length]);
  };

  // Build path from movement events up to current index
  const pathCoords = events
    .slice(0, currentIdx + 1)
    .filter(e => e.lat && e.lng)
    .map(e => [e.lat, e.lng]);

  // Significant events (non-movement) for map markers
  const significantEvents = events
    .slice(0, currentIdx + 1)
    .filter(e => e.type !== 'movement')
    .map(e => ({ ...e }));

  if (loading) return (
    <div className="h-screen bg-slate-900 flex items-center justify-center">
      <Loader2 className="w-8 h-8 animate-spin text-cyan-500" />
    </div>
  );

  if (!data) return null;

  const progress = events.length > 1 ? (currentIdx / (events.length - 1)) * 100 : 0;

  return (
    <div className="h-screen bg-slate-900 text-white grid grid-rows-[56px_1fr_64px] overflow-hidden relative" data-testid="replay-player">
      {/* AI Analysis Overlay */}
      <AIAnalysisPanel sessionId={sessionId} visible={showAnalysis} onClose={() => setShowAnalysis(false)} />

      {/* Header */}
      <div className="bg-slate-900 border-b border-slate-700/50 px-5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/replay')} className="text-slate-400 hover:text-white transition-colors" data-testid="replay-back">
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div className="w-8 h-8 rounded-lg bg-cyan-500/20 flex items-center justify-center border border-cyan-500/30">
            <Play className="w-4 h-4 text-cyan-400" />
          </div>
          <div>
            <h1 className="text-sm font-bold">Journey Replay</h1>
            <p className="text-[10px] text-slate-400">
              {data.started_at ? new Date(data.started_at).toLocaleString() : ''} — {data.risk_level}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-4 text-[10px] text-slate-400">
          <span>{data.event_count} events</span>
          <span>{data.alert_count} alerts</span>
          <span>{Math.round(data.total_distance_m)}m traveled</span>
          <span>{Math.floor((data.duration_seconds || 0) / 60)}min</span>
          <button
            onClick={() => setShowAnalysis(true)}
            className="flex items-center gap-1 px-2.5 py-1 rounded-md bg-purple-500/15 border border-purple-500/30 text-purple-300 hover:bg-purple-500/25 transition-colors"
            data-testid="open-analysis-btn"
          >
            <Brain className="w-3 h-3" />
            <span className="text-[10px] font-medium">AI Analysis</span>
          </button>
        </div>
      </div>

      {/* Main: Map + Timeline */}
      <div className="grid grid-cols-[1fr_360px] gap-0 min-h-0">
        {/* Map */}
        <div className="relative" data-testid="replay-map">
          <MapContainer center={[19.076, 72.877]} zoom={13} className="h-full w-full" style={{ background: '#0f172a' }} zoomControl={false} attributionControl={false}>
            <TileLayer url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" />
            {currentEvent && <MapPan lat={currentEvent.lat} lng={currentEvent.lng} fitAll={events.filter(e => e.lat && e.lng)} />}

            {/* Journey path trail */}
            {/* Faded older trail */}
            {pathCoords.length > 6 && (
              <Polyline positions={pathCoords.slice(0, -5)} pathOptions={{ color: '#00E5FF', weight: 3, opacity: 0.2, dashArray: '4 8', className: 'journey-trail-fade' }} />
            )}
            {/* Active recent trail (glowing) */}
            {pathCoords.length > 1 && (
              <Polyline positions={pathCoords.slice(Math.max(0, pathCoords.length - 6))} pathOptions={{ color: '#00E5FF', weight: 5, opacity: 0.9, dashArray: '6 10', className: 'journey-glow' }} />
            )}
            {/* Fading trail dots at recent positions */}
            {pathCoords.slice(Math.max(0, pathCoords.length - 8), -1).map((pos, i, arr) => (
              <CircleMarker key={`trail-${currentIdx}-${i}`} center={pos} radius={3 - (arr.length - 1 - i) * 0.3} pathOptions={{ fillColor: '#00E5FF', fillOpacity: 0.15 + (i / arr.length) * 0.5, color: 'transparent', className: 'trail-dot' }} />
            ))}

            {/* Significant event markers */}
            {significantEvents.map((ev, i) => (
              <CircleMarker
                key={`sig-${i}`}
                center={[ev.lat, ev.lng]}
                radius={6}
                pathOptions={{ fillColor: ev.color || '#64748b', fillOpacity: 0.8, color: '#fff', weight: 1, opacity: 0.6 }}
              >
                <Popup><div className="text-xs"><p className="font-bold">{(TYPE_CONFIG[ev.type] || fallback).label}</p><p>{ev.description}</p></div></Popup>
              </CircleMarker>
            ))}

            {/* Current position marker */}
            {currentEvent && currentEvent.lat && (
              <Marker position={[currentEvent.lat, currentEvent.lng]} icon={currentMarkerIcon}>
                <Popup>
                  <div className="text-xs">
                    <p className="font-bold text-cyan-600">{(TYPE_CONFIG[currentEvent.type] || fallback).label}</p>
                    <p>{currentEvent.description}</p>
                    <p className="text-slate-500">{currentEvent.timestamp ? new Date(currentEvent.timestamp).toLocaleTimeString() : ''}</p>
                  </div>
                </Popup>
              </Marker>
            )}
          </MapContainer>

          {/* Current event overlay */}
          {currentEvent && currentEvent.type !== 'movement' && (
            <div className="absolute top-3 left-3 right-3 z-[1000] pointer-events-none">
              <div className={`inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-700/50 backdrop-blur-md ${(TYPE_CONFIG[currentEvent.type] || fallback).bg}`}>
                {React.createElement((TYPE_CONFIG[currentEvent.type] || fallback).icon, { className: `w-4 h-4 ${(TYPE_CONFIG[currentEvent.type] || fallback).text}` })}
                <span className={`text-xs font-medium ${(TYPE_CONFIG[currentEvent.type] || fallback).text}`}>{currentEvent.description}</span>
              </div>
            </div>
          )}
        </div>

        {/* Timeline Panel */}
        <div className="bg-slate-800/40 border-l border-slate-700/50 flex flex-col" data-testid="replay-timeline">
          <div className="px-4 py-3 border-b border-slate-700/50 flex items-center gap-2 shrink-0">
            <Clock className="w-4 h-4 text-cyan-400" />
            <h2 className="text-sm font-semibold">Event Timeline</h2>
            <span className="text-[10px] text-slate-500 ml-auto">{currentIdx + 1}/{events.length}</span>
          </div>
          <div className="flex-1 overflow-y-auto" ref={timelineRef}>
            {events.map((ev, i) => {
              const cfg = TYPE_CONFIG[ev.type] || fallback;
              const Icon = cfg.icon;
              const isActive = i === currentIdx;
              const isPast = i < currentIdx;
              return (
                <button
                  key={i}
                  onClick={() => { setPlaying(false); setCurrentIdx(i); }}
                  className={`w-full text-left px-4 py-2.5 flex items-start gap-3 border-l-[3px] transition-all hover:bg-slate-700/20 ${
                    isActive ? 'replay-timeline-active border-l-cyan-500' : isPast ? 'border-l-slate-700/50 opacity-60' : 'border-l-transparent'
                  }`}
                  data-testid={`replay-event-${i}`}
                >
                  <div className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 mt-0.5 ${isActive ? 'bg-cyan-500/20' : cfg.bg}`}>
                    <Icon className={`w-3 h-3 ${isActive ? 'text-cyan-400' : cfg.text}`} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between">
                      <span className={`text-[10px] font-medium ${isActive ? 'text-cyan-300' : cfg.text}`}>{cfg.label}</span>
                      <span className="text-[9px] text-slate-500">{ev.timestamp ? new Date(ev.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : ''}</span>
                    </div>
                    {ev.type !== 'movement' && (
                      <p className="text-[10px] text-slate-400 truncate">{ev.description}</p>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Controls Bar */}
      <div className="bg-slate-900 border-t border-slate-700/50 px-5 flex items-center gap-4" data-testid="replay-controls">
        <div className="flex items-center gap-1">
          <Button size="sm" variant="ghost" className="h-8 w-8 p-0 text-slate-400 hover:text-white" onClick={restart} data-testid="replay-restart">
            <Rewind className="w-4 h-4" />
          </Button>
          <Button size="sm" variant="ghost" className="h-8 w-8 p-0 text-slate-400 hover:text-white" onClick={stepBack} data-testid="replay-prev">
            <SkipBack className="w-4 h-4" />
          </Button>
          <Button size="sm" className={`h-9 w-9 p-0 rounded-full ${playing ? 'bg-cyan-600 hover:bg-cyan-700' : 'bg-cyan-600 hover:bg-cyan-700'}`} onClick={togglePlay} data-testid="replay-play">
            {playing ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
          </Button>
          <Button size="sm" variant="ghost" className="h-8 w-8 p-0 text-slate-400 hover:text-white" onClick={stepForward} data-testid="replay-next">
            <SkipForward className="w-4 h-4" />
          </Button>
          <button onClick={cycleSpeed} className="ml-1 px-2 py-1 rounded bg-slate-800 border border-slate-700/50 text-[10px] font-mono text-cyan-400 hover:bg-slate-700 transition-colors" data-testid="replay-speed">
            {speed}x
          </button>
        </div>

        {/* Progress bar */}
        <div className="flex-1 flex items-center gap-3">
          <span className="text-[10px] text-slate-500 w-16">
            {currentEvent?.timestamp ? new Date(currentEvent.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '--:--'}
          </span>
          <input
            type="range"
            min={0}
            max={events.length - 1}
            value={currentIdx}
            onChange={e => { setPlaying(false); setCurrentIdx(Number(e.target.value)); }}
            className="flex-1 h-1 appearance-none bg-slate-700 rounded-full replay-progress cursor-pointer"
            data-testid="replay-scrubber"
          />
          <span className="text-[10px] text-slate-500 w-16 text-right">
            {events.length > 0 && events[events.length - 1]?.timestamp
              ? new Date(events[events.length - 1].timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
              : '--:--'}
          </span>
        </div>
      </div>
    </div>
  );
};

/* ════════════════════════════════════════
   MAIN EXPORT — routes between list and player
   ════════════════════════════════════════ */
export default function JourneyReplayPage() {
  const { sessionId } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const isAuthorized = user?.role === 'admin' || user?.role === 'operator' || user?.roles?.includes('admin') || user?.roles?.includes('operator');

  useEffect(() => {
    if (!isAuthorized) navigate('/family');
  }, [isAuthorized, navigate]);

  if (!isAuthorized) return null;
  return sessionId ? <ReplayPlayer /> : <SessionList />;
}
