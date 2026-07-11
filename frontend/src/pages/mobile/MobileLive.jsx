import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../api';
import {
  MapPin, Square, Shield, Clock, Navigation, Activity,
  Loader2, AlertTriangle, ArrowLeft, Zap, Share2,
} from 'lucide-react';

const RISK_COLORS = {
  SAFE: { bg: 'bg-emerald-500', ring: 'ring-emerald-500/30', text: 'text-emerald-400' },
  LOW: { bg: 'bg-emerald-500', ring: 'ring-emerald-500/30', text: 'text-emerald-400' },
  MODERATE: { bg: 'bg-amber-500', ring: 'ring-amber-500/30', text: 'text-amber-400' },
  HIGH: { bg: 'bg-orange-500', ring: 'ring-orange-500/30', text: 'text-orange-400' },
  CRITICAL: { bg: 'bg-red-500', ring: 'ring-red-500/30', text: 'text-red-400' },
};

function formatDuration(s) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}:${String(sec).padStart(2, '0')}`;
}

export default function MobileLive() {
  const navigate = useNavigate();
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);
  const [ending, setEnding] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const watchRef = useRef(null);
  const locationRef = useRef(null);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await api.get('/safety-events/session-status');
      if (!res.data.tracking_active) {
        navigate('/m/session', { replace: true });
        return;
      }
      setSession(res.data);
      if (res.data.session_duration_s) {
        setElapsed(res.data.session_duration_s);
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, [navigate]);

  // Poll session status
  useEffect(() => {
    fetchStatus();
    const iv = setInterval(fetchStatus, 5000);
    return () => clearInterval(iv);
  }, [fetchStatus]);

  // Tick elapsed time locally
  useEffect(() => {
    const iv = setInterval(() => setElapsed(e => e + 1), 1000);
    return () => clearInterval(iv);
  }, []);

  // Share location via geolocation API
  useEffect(() => {
    if (!session?.tracking_active) return;

    const sendLocation = (pos) => {
      api.post('/safety-events/share-location', {
        lat: pos.coords.latitude,
        lng: pos.coords.longitude,
        accuracy_m: pos.coords.accuracy,
        speed_mps: pos.coords.speed,
        heading: pos.coords.heading,
      }).catch(() => {});
    };

    if ('geolocation' in navigator) {
      watchRef.current = navigator.geolocation.watchPosition(
        sendLocation,
        () => {},
        { enableHighAccuracy: true, maximumAge: 5000, timeout: 10000 }
      );
    }

    return () => {
      if (watchRef.current !== null) {
        navigator.geolocation.clearWatch(watchRef.current);
      }
    };
  }, [session?.tracking_active]);

  const endSession = async () => {
    setEnding(true);
    try {
      await api.post('/safety-events/end-session', { reason: 'arrived' });
      navigate('/m/home', { replace: true });
    } catch {
      setEnding(false);
    }
  };

  const shareLiveTracking = async () => {
    setSharing(true);
    try {
      const res = await api.post('/location/share', { duration_hours: 4 });
      const origin = window.location.origin;
      const trackingUrl = `${origin}${res.data.tracking_url}`;
      const text = `Track ${res.data.share_name}'s live location on Nischint:\n${trackingUrl}`;

      if (navigator.share) {
        await navigator.share({ title: 'Nischint Live Tracking', text });
      } else {
        const whatsappUrl = `https://wa.me/?text=${encodeURIComponent(text)}`;
        window.open(whatsappUrl, '_blank');
      }
    } catch (err) {
      console.error('Share failed:', err);
    }
    setSharing(false);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-8 h-8 text-teal-400 animate-spin" />
      </div>
    );
  }

  if (!session) return null;

  const level = session.risk_level || 'SAFE';
  const rs = RISK_COLORS[level] || RISK_COLORS.SAFE;
  const loc = session.current_location;

  return (
    <div className="flex flex-col h-full" data-testid="mobile-live">
      {/* Header */}
      <div className="px-4 pt-3 pb-2 flex items-center justify-between">
        <button onClick={() => navigate('/m/home')} className="p-1.5 rounded-full active:bg-slate-800">
          <ArrowLeft className="w-5 h-5 text-slate-400" />
        </button>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-teal-400 animate-pulse" />
          <span className="text-xs font-medium text-teal-400">LIVE TRACKING</span>
        </div>
        <button
          onClick={shareLiveTracking}
          disabled={sharing}
          className="p-1.5 rounded-full active:bg-slate-800 disabled:opacity-50"
          data-testid="share-location-btn"
          title="Share Live Tracking"
        >
          {sharing ? <Loader2 className="w-5 h-5 text-teal-400 animate-spin" /> : <Share2 className="w-5 h-5 text-teal-400" />}
        </button>
      </div>

      {/* Risk Gauge - main hero */}
      <div className="flex-1 flex flex-col items-center justify-center px-6 pb-4">
        <div className={`relative w-40 h-40 rounded-full ${rs.ring} ring-4 flex items-center justify-center mb-4`}>
          <div className={`w-32 h-32 rounded-full ${rs.bg}/15 flex flex-col items-center justify-center`}>
            <span className={`text-3xl font-bold font-mono ${rs.text}`}>
              {((session.current_risk_score || 0) * 10).toFixed(1)}
            </span>
            <span className="text-[10px] text-slate-500">/10 RISK</span>
          </div>
          <div className={`absolute -bottom-1 px-3 py-0.5 rounded-full ${rs.bg} text-white text-[10px] font-bold`}>
            {level}
          </div>
        </div>

        {/* Timer */}
        <div className="flex items-center gap-2 mb-6">
          <Clock className="w-4 h-4 text-slate-500" />
          <span className="text-2xl font-mono text-white font-light tracking-wider">
            {formatDuration(elapsed)}
          </span>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-3 gap-3 w-full max-w-xs">
          <StatCard icon={<Navigation className="w-4 h-4 text-blue-400" />} label="Distance" value={`${((session.total_distance_m || 0) / 1000).toFixed(2)} km`} testId="stat-distance" />
          <StatCard icon={<Activity className="w-4 h-4 text-teal-400" />} label="Updates" value={session.location_updates || 0} testId="stat-updates" />
          <StatCard icon={<AlertTriangle className="w-4 h-4 text-amber-400" />} label="Alerts" value={session.alert_count || 0} testId="stat-alerts" />
        </div>

        {/* Location */}
        {loc && (
          <div className="mt-4 flex items-center gap-1.5 text-[10px] text-slate-500">
            <MapPin className="w-3 h-3" />
            <span>{loc.lat?.toFixed(4)}, {loc.lng?.toFixed(4)}</span>
            {loc.accuracy_m && <span>({Math.round(loc.accuracy_m)}m accuracy)</span>}
          </div>
        )}

        {/* Destination */}
        {session.destination?.name && (
          <div className="mt-2 px-3 py-1.5 rounded-full bg-slate-800/50 border border-slate-700/50">
            <span className="text-[10px] text-slate-400">
              <MapPin className="w-3 h-3 inline mr-1" />
              Heading to {session.destination.name}
            </span>
          </div>
        )}

        {/* Route deviation warning */}
        {session.route_deviated && (
          <div className="mt-3 px-4 py-2 rounded-xl bg-orange-500/10 border border-orange-500/30 flex items-center gap-2" data-testid="route-deviation-warning">
            <Zap className="w-4 h-4 text-orange-400" />
            <span className="text-xs text-orange-400 font-medium">Route Deviation Detected</span>
          </div>
        )}
      </div>

      {/* End Session Button */}
      <div className="px-4 pb-6">
        <button
          onClick={endSession}
          disabled={ending}
          className="w-full py-4 rounded-2xl bg-slate-800 border border-slate-700 text-white font-bold text-sm flex items-center justify-center gap-2 active:scale-[0.98] transition-transform disabled:opacity-50"
          data-testid="end-session-btn"
        >
          {ending ? (
            <><Loader2 className="w-5 h-5 animate-spin" /> Ending...</>
          ) : (
            <><Square className="w-4 h-4 text-red-400" /> End Session</>
          )}
        </button>
      </div>
    </div>
  );
}

const StatCard = ({ icon, label, value, testId }) => (
  <div className="p-3 rounded-xl bg-slate-800/50 border border-slate-700/40 text-center" data-testid={testId}>
    <div className="flex justify-center mb-1">{icon}</div>
    <p className="text-sm font-bold text-white font-mono">{value}</p>
    <p className="text-[9px] text-slate-500 uppercase">{label}</p>
  </div>
);
