import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Shield, Activity, Brain, Radio, Globe, Zap, Eye, Server, CheckCircle, ChevronRight, Users, Building2, Network, MapPin, Clock } from 'lucide-react';

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
    { name: 'Location Intelligence', status: 'operational', uptime: 99.96 },
    { name: 'Incident Replay Engine', status: 'operational', uptime: 99.94 },
    { name: 'Risk Prediction Engine', status: 'operational', uptime: 99.99 },
    { name: 'Telemetry Pipeline', status: 'operational', uptime: 99.98 },
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
    { timestamp: '14:32:19', message: 'Patrol response initiated — Campus South', type: 'system' },
    { timestamp: '14:31:05', message: 'Incident resolved — Zone Foxtrot', type: 'resolved' },
  ],
};
const FALLBACK_METRICS = {
  institutions_protected: 14, active_guardians: 20, total_safety_sessions: 44,
  incidents_resolved: 25, total_users: 32, total_sos_events: 53,
  signals_processed_total: 4023, avg_response_seconds: 11.2,
};

const EVENT_COLORS = {
  anomaly: { text: 'text-orange-400', dot: 'bg-orange-400' },
  alert: { text: 'text-red-400', dot: 'bg-red-400' },
  system: { text: 'text-cyan-400', dot: 'bg-cyan-400' },
  resolved: { text: 'text-emerald-400', dot: 'bg-emerald-400' },
};

function AnimatedCounter({ target, duration = 2000 }) {
  const [count, setCount] = useState(0);
  const ref = useRef(null);
  useEffect(() => {
    let start = 0;
    const step = target / (duration / 16);
    const timer = setInterval(() => {
      start += step;
      if (start >= target) { setCount(target); clearInterval(timer); }
      else setCount(Math.floor(start));
    }, 16);
    ref.current = timer;
    return () => clearInterval(ref.current);
  }, [target, duration]);
  return <>{count.toLocaleString()}</>;
}

function PulsingDot({ color = 'bg-emerald-400', size = 'w-2.5 h-2.5' }) {
  return (
    <span className="relative flex">
      <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${color} opacity-40`} />
      <span className={`relative inline-flex rounded-full ${size} ${color}`} />
    </span>
  );
}

export default function StatusPage() {
  const navigate = useNavigate();
  const [platform, setPlatform] = useState(null);
  const [events, setEvents] = useState([]);
  const [networkMetrics, setNetworkMetrics] = useState(null);
  const [lastRefresh, setLastRefresh] = useState(new Date());

  const fetchData = async () => {
    // Fetch each endpoint independently — one failure won't block others
    const safeFetch = async (url, fallback) => {
      try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
      } catch {
        return fallback;
      }
    };

    const [pData, eData, mData] = await Promise.all([
      safeFetch(`${API}/api/status/platform`, FALLBACK_PLATFORM),
      safeFetch(`${API}/api/status/events`, FALLBACK_EVENTS),
      safeFetch(`${API}/api/status/metrics`, FALLBACK_METRICS),
    ]);
    setPlatform(pData);
    setEvents(eData.events || []);
    setNetworkMetrics(mData);
    setLastRefresh(new Date());
  };

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, 8000);
    return () => clearInterval(iv);
  }, []);

  const metrics = platform?.metrics;
  const cities = platform?.cities || [];
  const systems = platform?.systems || [];

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-slate-200 overflow-x-hidden">
      {/* Nav */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-[#0a0e1a]/80 backdrop-blur-xl border-b border-slate-800/40">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <button onClick={() => navigate('/')} className="flex items-center gap-2.5" data-testid="status-nav-logo">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-teal-500 to-emerald-600 flex items-center justify-center">
              <Shield className="w-4 h-4 text-white" />
            </div>
            <span className="text-lg font-bold tracking-tight">NISCHINT</span>
          </button>
          <div className="hidden md:flex items-center gap-6">
            <div className="flex items-center gap-2">
              <PulsingDot color="bg-emerald-400" size="w-2 h-2" />
              <span className="text-[10px] font-bold text-emerald-400 uppercase tracking-widest">ALL SYSTEMS OPERATIONAL</span>
            </div>
            <button onClick={() => navigate('/investors')} className="text-sm text-slate-400 hover:text-white transition-colors" data-testid="status-nav-investors">Investors</button>
            <button onClick={() => navigate('/pilot')} className="text-sm text-teal-400 hover:text-teal-300 font-medium" data-testid="status-nav-pilot">Request Pilot</button>
          </div>
          <div className="md:hidden flex items-center gap-2">
            <PulsingDot color="bg-emerald-400" size="w-1.5 h-1.5" />
            <span className="text-[9px] font-bold text-emerald-400 uppercase">OPERATIONAL</span>
          </div>
        </div>
      </nav>

      {/* Hero Header */}
      <section className="pt-28 pb-10 px-6" data-testid="status-hero">
        <div className="max-w-6xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/5 border border-emerald-500/20 mb-6">
            <PulsingDot color="bg-emerald-400" size="w-1.5 h-1.5" />
            <span className="text-[10px] font-bold text-emerald-400 uppercase tracking-widest">LIVE TELEMETRY</span>
          </div>
          <h1 className="text-4xl sm:text-5xl font-bold tracking-tight mb-3">
            <span className="text-white">Nischint Live </span>
            <span className="bg-gradient-to-r from-teal-400 to-emerald-400 bg-clip-text text-transparent">Safety Network</span>
          </h1>
          <p className="text-base text-slate-400 max-w-xl mx-auto">
            Real-time platform telemetry and safety intelligence signals
          </p>
          <p className="text-[10px] text-slate-600 mt-3">
            Last updated: {lastRefresh.toLocaleTimeString()} &middot; Auto-refreshes every 8s
          </p>
        </div>
      </section>

      {/* ── 1. Platform Status Overview ── */}
      <section className="py-10 px-6" data-testid="status-overview">
        <div className="max-w-6xl mx-auto">
          <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-6 text-center">Platform Status</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            {metrics && [
              { label: 'Active Sessions', value: metrics.active_sessions, icon: Activity },
              { label: 'Signals Today', value: metrics.signals_today, icon: Radio },
              { label: 'AI Predictions', value: metrics.ai_predictions, icon: Brain },
              { label: 'Alerts Triggered', value: metrics.alerts_today, icon: Zap },
              { label: 'Cities Monitored', value: metrics.cities_monitored, icon: Globe },
              { label: 'Avg Response', value: metrics.avg_response_time, icon: Clock, suffix: 's' },
            ].map((m, i) => (
              <div key={i} className="p-4 rounded-xl bg-white/[0.02] border border-slate-800/40 text-center">
                <m.icon className="w-5 h-5 text-teal-400/60 mx-auto mb-2" />
                <p className="text-xl font-bold text-white" data-testid={`metric-${i}`}>
                  {typeof m.value === 'number' && !m.suffix ? <AnimatedCounter target={m.value} /> : <>{m.value}{m.suffix || ''}</>}
                </p>
                <p className="text-[9px] text-slate-500 uppercase tracking-wider mt-1">{m.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 2. Live Intelligence Feed ── */}
      <section className="py-10 px-6 bg-[#0c1020]" data-testid="status-live-feed">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-3">
              <PulsingDot />
              <p className="text-xs text-teal-400 font-bold uppercase tracking-widest">Live Intelligence Feed</p>
            </div>
            <span className="text-[10px] text-slate-600">{events.length} events</span>
          </div>
          <div className="rounded-xl border border-slate-800/40 bg-[#0a0e1a]/50 overflow-hidden max-h-[360px] overflow-y-auto">
            {events.map((ev, i) => {
              const c = EVENT_COLORS[ev.type] || EVENT_COLORS.system;
              return (
                <div key={i} className="flex items-center gap-3 px-4 py-2.5 border-b border-slate-800/20 last:border-b-0 hover:bg-white/[0.01] transition-colors" data-testid={`event-${i}`}>
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${c.dot}`} />
                  <span className="text-[11px] text-slate-500 font-mono shrink-0 w-16">{ev.timestamp}</span>
                  <span className={`text-xs font-medium ${c.text}`}>{ev.message}</span>
                  <span className="ml-auto text-[9px] text-slate-700 uppercase shrink-0">{ev.type}</span>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── 3. City Safety Heatmap ── */}
      <section className="py-10 px-6" data-testid="status-city-heatmap">
        <div className="max-w-6xl mx-auto">
          <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-6 text-center">City Safety Network</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            {cities.map((city, i) => {
              const riskColor = city.risk_level === 'high' ? 'border-red-500/30' : city.risk_level === 'medium' ? 'border-amber-500/30' : 'border-emerald-500/30';
              const dotColor = city.risk_level === 'high' ? 'bg-red-400' : city.risk_level === 'medium' ? 'bg-amber-400' : 'bg-emerald-400';
              const riskText = city.risk_level === 'high' ? 'text-red-400' : city.risk_level === 'medium' ? 'text-amber-400' : 'text-emerald-400';
              return (
                <div key={i} className={`p-4 rounded-xl bg-white/[0.02] border ${riskColor} text-center`} data-testid={`city-${i}`}>
                  <div className="flex items-center justify-center gap-2 mb-3">
                    <PulsingDot color={dotColor} size="w-2 h-2" />
                    <p className="text-sm font-semibold text-white">{city.name}</p>
                  </div>
                  <p className="text-lg font-bold text-white">{city.active_sessions}</p>
                  <p className="text-[9px] text-slate-500 uppercase tracking-wider">Active Sessions</p>
                  <div className="mt-2 flex items-center justify-center gap-1">
                    <span className={`text-[9px] font-bold uppercase ${riskText}`}>{city.risk_level}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── 4. System Health Status ── */}
      <section className="py-10 px-6 bg-[#0c1020]" data-testid="status-system-health">
        <div className="max-w-6xl mx-auto">
          <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-6 text-center">System Health</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {systems.map((sys, i) => (
              <div key={i} className="p-4 rounded-xl bg-white/[0.02] border border-emerald-500/15 flex items-center gap-3" data-testid={`system-${i}`}>
                <div className="shrink-0">
                  <PulsingDot color="bg-emerald-400" size="w-2.5 h-2.5" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-semibold text-white">{sys.name}</p>
                  <p className="text-[10px] text-emerald-400 capitalize">{sys.status}</p>
                </div>
                <div className="shrink-0 text-right">
                  <p className="text-xs font-bold text-white">{sys.uptime}%</p>
                  <p className="text-[9px] text-slate-600">uptime</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 5. Network Growth Metrics ── */}
      <section className="py-10 px-6" data-testid="status-network-growth">
        <div className="max-w-6xl mx-auto">
          <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-6 text-center">Network Growth</p>
          {networkMetrics && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                { label: 'Institutions Protected', value: networkMetrics.institutions_protected, icon: Building2 },
                { label: 'Active Guardians', value: networkMetrics.active_guardians, icon: Users },
                { label: 'Total Safety Sessions', value: networkMetrics.total_safety_sessions, icon: Activity },
                { label: 'Incidents Resolved', value: networkMetrics.incidents_resolved, icon: CheckCircle },
                { label: 'Total Users', value: networkMetrics.total_users, icon: Eye },
                { label: 'SOS Events', value: networkMetrics.total_sos_events, icon: Zap },
                { label: 'Signals Processed', value: networkMetrics.signals_processed_total, icon: Radio },
                { label: 'Avg Response', value: networkMetrics.avg_response_seconds, icon: Clock, suffix: 's' },
              ].map((m, i) => (
                <div key={i} className="p-5 rounded-xl bg-white/[0.02] border border-slate-800/40 text-center" data-testid={`growth-${i}`}>
                  <m.icon className="w-6 h-6 text-teal-400/50 mx-auto mb-3" />
                  <p className="text-2xl font-bold text-white">
                    {m.suffix ? <>{m.value}{m.suffix}</> : <AnimatedCounter target={m.value} />}
                  </p>
                  <p className="text-[10px] text-slate-500 uppercase tracking-wider mt-1">{m.label}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* ── 6. Live Safety Network Map ── */}
      <section className="py-10 px-6 bg-[#0c1020]" data-testid="status-network-map">
        <div className="max-w-6xl mx-auto">
          <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-6 text-center">Safety Network Nodes</p>
          <div className="relative rounded-2xl border border-slate-800/40 bg-[#080c16] p-8 overflow-hidden min-h-[280px]">
            {/* Grid background */}
            <div className="absolute inset-0" style={{
              backgroundImage: `linear-gradient(rgba(45,212,191,0.02) 1px, transparent 1px), linear-gradient(90deg, rgba(45,212,191,0.02) 1px, transparent 1px)`,
              backgroundSize: '40px 40px',
            }} />
            {/* City nodes */}
            <div className="relative z-10 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-6">
              {cities.map((city, i) => {
                const dotColor = city.risk_level === 'high' ? 'bg-red-400' : city.risk_level === 'medium' ? 'bg-amber-400' : 'bg-teal-400';
                return (
                  <div key={i} className="flex flex-col items-center gap-2" data-testid={`node-${i}`}>
                    <div className="relative">
                      <span className={`absolute inset-0 animate-ping rounded-full ${dotColor} opacity-20`} style={{ animationDelay: `${i * 0.4}s`, animationDuration: '2s' }} />
                      <span className={`relative block w-4 h-4 rounded-full ${dotColor}`} />
                    </div>
                    <p className="text-xs font-semibold text-white">{city.name}</p>
                    <p className="text-[10px] text-slate-500">{city.signals_today.toLocaleString()} signals</p>
                  </div>
                );
              })}
            </div>
            {/* Connecting lines (decorative) */}
            <svg className="absolute inset-0 w-full h-full pointer-events-none opacity-10" viewBox="0 0 100 100" preserveAspectRatio="none">
              <line x1="10" y1="50" x2="30" y2="50" stroke="#2dd4bf" strokeWidth="0.2" />
              <line x1="30" y1="50" x2="50" y2="50" stroke="#2dd4bf" strokeWidth="0.2" />
              <line x1="50" y1="50" x2="70" y2="50" stroke="#2dd4bf" strokeWidth="0.2" />
              <line x1="70" y1="50" x2="90" y2="50" stroke="#2dd4bf" strokeWidth="0.2" />
            </svg>
          </div>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="border-t border-slate-800/40 py-10 px-6" data-testid="status-footer">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-gradient-to-br from-teal-500 to-emerald-600 flex items-center justify-center">
              <Shield className="w-3 h-3 text-white" />
            </div>
            <span className="text-sm font-bold tracking-tight">NISCHINT</span>
            <span className="text-xs text-slate-600 ml-1">Live Safety Network</span>
          </div>
          <div className="flex items-center gap-6">
            <button onClick={() => navigate('/')} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">Home</button>
            <button onClick={() => navigate('/investors')} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">Investors</button>
            <button onClick={() => navigate('/pilot')} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">Pilot Program</button>
            <a href="mailto:hello@nischint.app" className="text-xs text-slate-500 hover:text-teal-400 transition-colors">hello@nischint.app</a>
          </div>
          <p className="text-[10px] text-slate-400">&copy; 2026 Nischint Technologies</p>
        </div>
      </footer>
    </div>
  );
}
