import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Shield, Activity, Brain, Radio, AlertTriangle, CheckCircle, Clock, MapPin, Users, Zap, Eye, ChevronRight, Bell, Navigation, ShieldAlert, RotateCcw, Play } from 'lucide-react';

// Use relative paths for public pages — works on any domain without CORS
const API = '';

// Client-side fallback data shown when API calls fail
const FALLBACK_PLATFORM = {
  status: 'operational',
  metrics: { active_sessions: 148, signals_today: 12904, ai_predictions: 3400, alerts_today: 31, cities_monitored: 6, avg_response_time: 2.8 },
  cities: [
    { name: 'Mumbai', lat: 19.076, lng: 72.877, active_sessions: 42, signals_today: 2800, risk_level: 'low' },
    { name: 'Delhi', lat: 28.613, lng: 77.209, active_sessions: 35, signals_today: 2400, risk_level: 'low' },
    { name: 'Bangalore', lat: 12.971, lng: 77.594, active_sessions: 28, signals_today: 2100, risk_level: 'low' },
    { name: 'Pune', lat: 18.520, lng: 73.856, active_sessions: 22, signals_today: 1800, risk_level: 'medium' },
    { name: 'Dubai', lat: 25.204, lng: 55.270, active_sessions: 15, signals_today: 1200, risk_level: 'low' },
    { name: 'London', lat: 51.507, lng: -0.127, active_sessions: 12, signals_today: 900, risk_level: 'low' },
  ],
  systems: [
    { name: 'AI Safety Brain', status: 'operational', uptime: 99.98 },
    { name: 'Command Center', status: 'operational', uptime: 99.99 },
    { name: 'Guardian Network', status: 'operational', uptime: 99.95 },
    { name: 'Notification System', status: 'operational', uptime: 99.97 },
  ],
};
const FALLBACK_EVENTS = {
  events: [
    { timestamp: '14:42:18', message: 'Session completed safely — Zone Alpha', type: 'resolved' },
    { timestamp: '14:41:03', message: 'AI risk prediction generated — Campus North', type: 'system' },
    { timestamp: '14:39:47', message: 'Guardian notification sent — Zone Bravo', type: 'system' },
    { timestamp: '14:38:22', message: 'Risk score normalized — Zone Delta', type: 'resolved' },
    { timestamp: '14:37:15', message: 'Geofence deviation detected — Zone Echo', type: 'anomaly' },
    { timestamp: '14:36:01', message: 'Safety session started — Zone Charlie', type: 'system' },
    { timestamp: '14:34:48', message: 'Fall event detected — Industrial Corridor', type: 'alert' },
    { timestamp: '14:33:33', message: 'Behavioral anomaly cleared — Residential Block', type: 'resolved' },
  ],
};
const FALLBACK_INCIDENTS = {
  incidents: [
    { type: 'fall', severity: 'high', status: 'active', risk_score: 0.78, zone: 'Zone Alpha', created_at: '12:41:03', response_time: 12 },
    { type: 'wandering', severity: 'medium', status: 'resolved', risk_score: 0.55, zone: 'Zone Bravo', created_at: '12:38:17', response_time: 22 },
    { type: 'sos_alert', severity: 'critical', status: 'resolved', risk_score: 0.92, zone: 'Campus North', created_at: '12:35:41', response_time: 8 },
    { type: 'voice_distress', severity: 'high', status: 'acknowledged', risk_score: 0.81, zone: 'Zone Delta', created_at: '12:32:09', response_time: 15 },
    { type: 'extended_inactivity', severity: 'medium', status: 'resolved', risk_score: 0.48, zone: 'Residential Block', created_at: '12:28:55', response_time: 35 },
    { type: 'geofence_exit', severity: 'medium', status: 'resolved', risk_score: 0.62, zone: 'Zone Echo', created_at: '12:25:33', response_time: 18 },
  ],
};
const FALLBACK_RISK = {
  high_risk_incidents: 5, anomaly_clusters: 12, ai_predictions_active: 34, unresolved_incidents: 3,
  risk_zones: [
    { zone: 'Zone Alpha', risk_level: 'elevated', signal_count: 8, recommendation: 'Increase patrol frequency' },
    { zone: 'Campus North', risk_level: 'high', signal_count: 14, recommendation: 'Deploy mobile safety unit' },
    { zone: 'Industrial Corridor', risk_level: 'moderate', signal_count: 6, recommendation: 'Monitor behavioral patterns' },
    { zone: 'Zone Bravo', risk_level: 'low', signal_count: 3, recommendation: 'Standard monitoring' },
  ],
  ai_recommendations: [
    { priority: 'high', message: 'Elevated anomaly activity detected in Zone Alpha. Recommend increased monitoring.' },
    { priority: 'medium', message: 'Pattern analysis suggests peak risk window 18:00-22:00 in transit corridors.' },
    { priority: 'low', message: 'Historical data indicates reduced risk on weekends. Consider schedule optimization.' },
  ],
};

const SEVERITY_STYLES = {
  critical: { bg: 'bg-red-500/10', border: 'border-red-500/25', text: 'text-red-400', dot: 'bg-red-400', badge: 'bg-red-500/20 text-red-400' },
  high: { bg: 'bg-orange-500/10', border: 'border-orange-500/25', text: 'text-orange-400', dot: 'bg-orange-400', badge: 'bg-orange-500/20 text-orange-400' },
  medium: { bg: 'bg-amber-500/10', border: 'border-amber-500/25', text: 'text-amber-400', dot: 'bg-amber-400', badge: 'bg-amber-500/20 text-amber-400' },
  low: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/25', text: 'text-emerald-400', dot: 'bg-emerald-400', badge: 'bg-emerald-500/20 text-emerald-400' },
};

const STATUS_STYLES = {
  active: { text: 'text-red-400', label: 'ACTIVE' },
  acknowledged: { text: 'text-amber-400', label: 'ACK' },
  resolved: { text: 'text-emerald-400', label: 'RESOLVED' },
  investigating: { text: 'text-cyan-400', label: 'INVESTIGATING' },
};

const INCIDENT_LABELS = {
  fall: 'Fall Detected',
  wandering: 'Geofence Deviation',
  voice_distress: 'Voice Distress',
  sos_alert: 'SOS Emergency',
  device_offline: 'Device Offline',
  low_battery: 'Low Battery',
  extended_inactivity: 'Extended Inactivity',
  route_deviation: 'Route Deviation',
  geofence_exit: 'Geofence Exit',
  risk_spike: 'Risk Spike',
};

const RISK_LEVEL_COLORS = {
  high: 'text-red-400',
  elevated: 'text-orange-400',
  moderate: 'text-amber-400',
  low: 'text-emerald-400',
};

function PulsingDot({ color = 'bg-emerald-400', size = 'w-2 h-2' }) {
  return (
    <span className="relative flex">
      <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${color} opacity-40`} />
      <span className={`relative inline-flex rounded-full ${size} ${color}`} />
    </span>
  );
}

function AnimatedNum({ target }) {
  const [val, setVal] = useState(0);
  useEffect(() => {
    let s = 0;
    const step = target / 40;
    const t = setInterval(() => {
      s += step;
      if (s >= target) { setVal(target); clearInterval(t); }
      else setVal(Math.floor(s));
    }, 25);
    return () => clearInterval(t);
  }, [target]);
  return <>{val.toLocaleString()}</>;
}

export default function SafetyDashboard() {
  const navigate = useNavigate();
  const [platform, setPlatform] = useState(null);
  const [events, setEvents] = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [riskIntel, setRiskIntel] = useState(null);
  const [actionLog, setActionLog] = useState([]);
  const [lastRefresh, setLastRefresh] = useState(new Date());

  const fetchAll = async () => {
    const safeFetch = async (url, fallback) => {
      try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
      } catch {
        return fallback;
      }
    };

    const [pD, eD, iD, rD] = await Promise.all([
      safeFetch(`${API}/api/status/platform`, FALLBACK_PLATFORM),
      safeFetch(`${API}/api/status/events`, FALLBACK_EVENTS),
      safeFetch(`${API}/api/status/incidents`, FALLBACK_INCIDENTS),
      safeFetch(`${API}/api/status/risk-intelligence`, FALLBACK_RISK),
    ]);
    setPlatform(pD);
    setEvents(eD.events || []);
    setIncidents(iD.incidents || []);
    setRiskIntel(rD);
    setLastRefresh(new Date());
  };

  useEffect(() => {
    fetchAll();
    const iv = setInterval(fetchAll, 10000);
    return () => clearInterval(iv);
  }, []);

  const handleAction = (action, zone) => {
    setActionLog(prev => [{
      action,
      zone: zone || 'All Zones',
      time: new Date().toLocaleTimeString(),
    }, ...prev].slice(0, 8));
  };

  const metrics = platform?.metrics;
  const cities = platform?.cities || [];

  return (
    <div className="min-h-screen bg-[#080c16] text-slate-200">
      {/* Nav */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-[#080c16]/90 backdrop-blur-xl border-b border-slate-800/30">
        <div className="max-w-[1600px] mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <button onClick={() => navigate('/')} className="flex items-center gap-2" data-testid="dash-nav-logo">
              <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-teal-500 to-emerald-600 flex items-center justify-center">
                <Shield className="w-3.5 h-3.5 text-white" />
              </div>
              <span className="text-sm font-bold tracking-tight">NISCHINT</span>
            </button>
            <div className="h-5 w-px bg-slate-800" />
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Public Safety Dashboard</span>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <PulsingDot color="bg-emerald-400" size="w-1.5 h-1.5" />
              <span className="text-[9px] font-bold text-emerald-400 uppercase tracking-widest">LIVE</span>
            </div>
            <span className="text-[10px] text-slate-600">{lastRefresh.toLocaleTimeString()}</span>
            <button onClick={() => navigate('/telemetry')} className="text-xs text-slate-500 hover:text-white transition-colors" data-testid="dash-nav-telemetry">Telemetry</button>
            <button onClick={() => navigate('/pilot')} className="text-xs text-teal-400 hover:text-teal-300 font-medium" data-testid="dash-nav-pilot">Request Pilot</button>
          </div>
        </div>
      </nav>

      <div className="pt-16 px-4 pb-8 max-w-[1600px] mx-auto">
        {/* ── Top Metrics Bar ── */}
        {metrics && (
          <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 mb-4" data-testid="dash-metrics">
            {[
              { icon: Activity, label: 'Active Sessions', value: metrics.active_sessions, color: 'text-emerald-400' },
              { icon: Radio, label: 'Signals', value: metrics.signals_today, color: 'text-teal-400' },
              { icon: Brain, label: 'AI Predictions', value: metrics.ai_predictions, color: 'text-violet-400' },
              { icon: AlertTriangle, label: 'Alerts', value: metrics.alerts_today, color: 'text-amber-400' },
              { icon: MapPin, label: 'Cities', value: metrics.cities_monitored, color: 'text-blue-400' },
              { icon: Clock, label: 'Avg Response', value: metrics.avg_response_time, color: 'text-cyan-400', suffix: 's' },
            ].map((m, i) => (
              <div key={i} className="px-3 py-2.5 rounded-xl bg-white/[0.02] border border-slate-800/30 flex items-center gap-2.5">
                <m.icon className={`w-4 h-4 ${m.color} shrink-0`} />
                <div>
                  <p className="text-sm font-bold text-white leading-none">
                    {m.suffix ? `${m.value}${m.suffix}` : <AnimatedNum target={m.value} />}
                  </p>
                  <p className="text-[8px] text-slate-600 uppercase tracking-wider">{m.label}</p>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ── Main Grid ── */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-3">

          {/* ── LEFT: Live Incident Map + City Nodes ── */}
          <div className="lg:col-span-5 space-y-3">
            {/* Incident Map */}
            <div className="rounded-xl border border-slate-800/30 bg-[#0a0e1a] overflow-hidden" data-testid="dash-incident-map">
              <div className="px-4 py-2.5 border-b border-slate-800/20 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <PulsingDot color="bg-teal-400" size="w-1.5 h-1.5" />
                  <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Live Incident Map</span>
                </div>
                <span className="text-[9px] text-slate-600">{cities.length} zones active</span>
              </div>
              <div className="relative p-4" style={{ minHeight: 240 }}>
                <div className="absolute inset-0" style={{
                  backgroundImage: `linear-gradient(rgba(45,212,191,0.015) 1px, transparent 1px), linear-gradient(90deg, rgba(45,212,191,0.015) 1px, transparent 1px)`,
                  backgroundSize: '24px 24px',
                }} />
                <svg className="relative w-full h-full" viewBox="0 0 100 70" preserveAspectRatio="xMidYMid meet">
                  {/* Connection lines */}
                  {cities.slice(0, -1).map((c, i) => {
                    const next = cities[i + 1];
                    if (!next) return null;
                    const positions = [[15, 18], [38, 12], [62, 22], [85, 15], [25, 52], [75, 55]];
                    const p1 = positions[i] || [50, 50];
                    const p2 = positions[i + 1] || [50, 50];
                    return <line key={i} x1={p1[0]} y1={p1[1]} x2={p2[0]} y2={p2[1]} stroke="rgba(45,212,191,0.06)" strokeWidth="0.3" />;
                  })}
                  {/* City nodes */}
                  {cities.map((city, i) => {
                    const positions = [[15, 18], [38, 12], [62, 22], [85, 15], [25, 52], [75, 55]];
                    const [cx, cy] = positions[i] || [50, 50];
                    const color = city.risk_level === 'high' ? '#ef4444' : city.risk_level === 'medium' ? '#f59e0b' : '#10b981';
                    return (
                      <g key={i}>
                        <circle cx={cx} cy={cy} r={3} fill={color} opacity={0.15}>
                          <animate attributeName="r" from="3" to="6" dur="2s" repeatCount="indefinite" />
                          <animate attributeName="opacity" from="0.15" to="0" dur="2s" repeatCount="indefinite" />
                        </circle>
                        <circle cx={cx} cy={cy} r={2} fill={color} opacity={0.3} />
                        <circle cx={cx} cy={cy} r={1} fill={color} />
                        <text x={cx} y={cy + 5} textAnchor="middle" fill="rgba(255,255,255,0.4)" fontSize="2.5">{city.name}</text>
                      </g>
                    );
                  })}
                </svg>
              </div>
            </div>

            {/* City Zone Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2" data-testid="dash-city-zones">
              {cities.map((city, i) => {
                const riskStyle = city.risk_level === 'high' ? 'border-red-500/25' : city.risk_level === 'medium' ? 'border-amber-500/25' : 'border-emerald-500/25';
                const riskColor = RISK_LEVEL_COLORS[city.risk_level] || 'text-emerald-400';
                return (
                  <div key={i} className={`px-3 py-2.5 rounded-lg bg-white/[0.02] border ${riskStyle}`}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-semibold text-white">{city.name}</span>
                      <span className={`text-[8px] font-bold uppercase ${riskColor}`}>{city.risk_level}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-[9px] text-slate-500">{city.active_sessions} sessions</span>
                      <span className="text-[9px] text-slate-600">{city.signals_today.toLocaleString()} sig</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* ── CENTER: Active Incidents + Live Events ── */}
          <div className="lg:col-span-4 space-y-3">
            {/* Active Incidents Panel */}
            <div className="rounded-xl border border-slate-800/30 bg-[#0a0e1a]" data-testid="dash-active-incidents">
              <div className="px-4 py-2.5 border-b border-slate-800/20 flex items-center justify-between">
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Active Incidents</span>
                <span className="text-[9px] text-slate-600">{incidents.length} total</span>
              </div>
              <div className="max-h-[280px] overflow-y-auto">
                {incidents.map((inc, i) => {
                  const sev = SEVERITY_STYLES[inc.severity] || SEVERITY_STYLES.medium;
                  const st = STATUS_STYLES[inc.status] || STATUS_STYLES.active;
                  const label = INCIDENT_LABELS[inc.type] || inc.type;
                  return (
                    <div key={i} className={`px-4 py-2.5 border-b border-slate-800/15 flex items-center gap-3 ${i === 0 && inc.status === 'active' ? sev.bg : ''}`} data-testid={`incident-${i}`}>
                      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${sev.dot}`} />
                      <div className="flex-1 min-w-0">
                        <p className="text-[11px] font-semibold text-white truncate">{label}</p>
                        <p className="text-[9px] text-slate-500">{inc.zone} &middot; {inc.created_at}</p>
                      </div>
                      <div className="shrink-0 text-right">
                        <span className={`text-[8px] font-bold uppercase ${st.text}`}>{st.label}</span>
                        {inc.response_time && <p className="text-[8px] text-slate-600">{inc.response_time}s</p>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Live Intelligence Feed */}
            <div className="rounded-xl border border-slate-800/30 bg-[#0a0e1a]" data-testid="dash-live-feed">
              <div className="px-4 py-2.5 border-b border-slate-800/20 flex items-center gap-2">
                <PulsingDot color="bg-teal-400" size="w-1.5 h-1.5" />
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Intelligence Feed</span>
              </div>
              <div className="max-h-[200px] overflow-y-auto">
                {events.slice(0, 10).map((ev, i) => {
                  const typeColor = ev.type === 'alert' ? 'text-red-400' : ev.type === 'anomaly' ? 'text-orange-400' : ev.type === 'resolved' ? 'text-emerald-400' : 'text-cyan-400';
                  const dotColor = ev.type === 'alert' ? 'bg-red-400' : ev.type === 'anomaly' ? 'bg-orange-400' : ev.type === 'resolved' ? 'bg-emerald-400' : 'bg-cyan-400';
                  return (
                    <div key={i} className="px-4 py-1.5 border-b border-slate-800/10 flex items-center gap-2">
                      <span className={`w-1 h-1 rounded-full shrink-0 ${dotColor}`} />
                      <span className="text-[9px] text-slate-600 font-mono w-14 shrink-0">{ev.timestamp}</span>
                      <span className={`text-[10px] ${typeColor} truncate`}>{ev.message}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* ── RIGHT: AI Risk Intelligence + Response Actions ── */}
          <div className="lg:col-span-3 space-y-3">
            {/* AI Risk Intelligence */}
            {riskIntel && (
              <div className="rounded-xl border border-slate-800/30 bg-[#0a0e1a]" data-testid="dash-risk-intel">
                <div className="px-4 py-2.5 border-b border-slate-800/20">
                  <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">AI Risk Intelligence</span>
                </div>
                <div className="p-3 space-y-2">
                  <div className="grid grid-cols-2 gap-2">
                    <div className="px-2.5 py-2 rounded-lg bg-red-500/5 border border-red-500/15 text-center">
                      <p className="text-lg font-bold text-red-400">{riskIntel.high_risk_incidents}</p>
                      <p className="text-[7px] text-slate-500 uppercase">High Risk</p>
                    </div>
                    <div className="px-2.5 py-2 rounded-lg bg-amber-500/5 border border-amber-500/15 text-center">
                      <p className="text-lg font-bold text-amber-400">{riskIntel.anomaly_clusters}</p>
                      <p className="text-[7px] text-slate-500 uppercase">Anomalies</p>
                    </div>
                    <div className="px-2.5 py-2 rounded-lg bg-violet-500/5 border border-violet-500/15 text-center">
                      <p className="text-lg font-bold text-violet-400">{riskIntel.ai_predictions_active}</p>
                      <p className="text-[7px] text-slate-500 uppercase">Predictions</p>
                    </div>
                    <div className="px-2.5 py-2 rounded-lg bg-orange-500/5 border border-orange-500/15 text-center">
                      <p className="text-lg font-bold text-orange-400">{riskIntel.unresolved_incidents}</p>
                      <p className="text-[7px] text-slate-500 uppercase">Unresolved</p>
                    </div>
                  </div>

                  {/* Risk Zones */}
                  <div className="space-y-1.5 mt-2">
                    <p className="text-[9px] font-bold text-slate-500 uppercase">Risk Zones</p>
                    {riskIntel.risk_zones?.map((z, i) => {
                      const color = RISK_LEVEL_COLORS[z.risk_level] || 'text-slate-400';
                      return (
                        <div key={i} className="flex items-center justify-between px-2 py-1.5 rounded-lg bg-white/[0.02]">
                          <div className="flex items-center gap-2">
                            <span className="text-[10px] font-medium text-white">{z.zone}</span>
                          </div>
                          <span className={`text-[8px] font-bold uppercase ${color}`}>{z.risk_level}</span>
                        </div>
                      );
                    })}
                  </div>

                  {/* AI Recommendations */}
                  <div className="space-y-1.5 mt-2">
                    <p className="text-[9px] font-bold text-slate-500 uppercase">AI Recommendations</p>
                    {riskIntel.ai_recommendations?.map((rec, i) => {
                      const prioColor = rec.priority === 'high' ? 'border-l-red-400' : rec.priority === 'medium' ? 'border-l-amber-400' : 'border-l-emerald-400';
                      return (
                        <div key={i} className={`border-l-2 ${prioColor} pl-2.5 py-1.5`}>
                          <p className="text-[10px] text-slate-400 leading-relaxed">{rec.message}</p>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            {/* Response Actions */}
            <div className="rounded-xl border border-slate-800/30 bg-[#0a0e1a]" data-testid="dash-response-actions">
              <div className="px-4 py-2.5 border-b border-slate-800/20">
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Response Actions</span>
              </div>
              <div className="p-3 space-y-2">
                <button
                  onClick={() => handleAction('Dispatch Security', riskIntel?.risk_zones?.[0]?.zone)}
                  className="w-full py-2 px-3 rounded-lg bg-red-500/10 border border-red-500/20 text-xs text-red-400 font-semibold hover:bg-red-500/20 transition-colors flex items-center gap-2"
                  data-testid="action-dispatch"
                >
                  <ShieldAlert className="w-3.5 h-3.5" />
                  Dispatch Security
                </button>
                <button
                  onClick={() => handleAction('Notify Guardian')}
                  className="w-full py-2 px-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-xs text-amber-400 font-semibold hover:bg-amber-500/20 transition-colors flex items-center gap-2"
                  data-testid="action-notify"
                >
                  <Bell className="w-3.5 h-3.5" />
                  Notify Guardian
                </button>
                <button
                  onClick={() => handleAction('Activate Safety Protocol')}
                  className="w-full py-2 px-3 rounded-lg bg-teal-500/10 border border-teal-500/20 text-xs text-teal-400 font-semibold hover:bg-teal-500/20 transition-colors flex items-center gap-2"
                  data-testid="action-protocol"
                >
                  <Shield className="w-3.5 h-3.5" />
                  Activate Safety Protocol
                </button>

                {/* Action Log */}
                {actionLog.length > 0 && (
                  <div className="mt-2 space-y-1" data-testid="action-log">
                    <p className="text-[8px] font-bold text-slate-600 uppercase">Action Log</p>
                    {actionLog.map((log, i) => (
                      <div key={i} className="flex items-center gap-2 text-[9px]">
                        <span className="text-slate-600 font-mono">{log.time}</span>
                        <span className="text-emerald-400">{log.action}</span>
                        <span className="text-slate-600">→ {log.zone}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Incident Replay Link */}
            <div className="rounded-xl border border-slate-800/30 bg-[#0a0e1a] p-3" data-testid="dash-replay-link">
              <button
                onClick={() => navigate('/telemetry')}
                className="w-full flex items-center justify-between group"
              >
                <div className="flex items-center gap-2">
                  <RotateCcw className="w-4 h-4 text-violet-400" />
                  <div>
                    <p className="text-xs font-semibold text-white">Incident Replay</p>
                    <p className="text-[9px] text-slate-500">View past incident analysis</p>
                  </div>
                </div>
                <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-white transition-colors" />
              </button>
            </div>
          </div>
        </div>

        {/* ── Footer ── */}
        <div className="mt-6 pt-4 border-t border-slate-800/20 flex flex-col sm:flex-row items-center justify-between gap-3" data-testid="dash-footer">
          <div className="flex items-center gap-4">
            <button onClick={() => navigate('/')} className="text-[10px] text-slate-600 hover:text-slate-400 transition-colors">Home</button>
            <button onClick={() => navigate('/investors')} className="text-[10px] text-slate-600 hover:text-slate-400 transition-colors">Investors</button>
            <button onClick={() => navigate('/pilot')} className="text-[10px] text-slate-600 hover:text-slate-400 transition-colors">Pilot Program</button>
            <a href="mailto:hello@nischint.app" className="text-[10px] text-slate-600 hover:text-teal-400 transition-colors">hello@nischint.app</a>
          </div>
          <p className="text-[9px] text-slate-700">Public Safety Dashboard &middot; Anonymized Data &middot; No Personal Information Displayed</p>
        </div>
      </div>
    </div>
  );
}
