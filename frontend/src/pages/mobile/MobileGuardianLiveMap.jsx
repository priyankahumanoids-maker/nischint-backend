import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { MapContainer, TileLayer, Marker, Popup, Polyline, Circle, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import JourneyPolyline from '../../components/JourneyPolyline';
import {
  ArrowLeft, Phone, MessageCircle, Bell, ShieldAlert,
  Activity, Navigation, Clock, AlertTriangle, MapPin,
  Loader2, ChevronUp, ChevronDown, Users, Zap, Eye,
} from 'lucide-react';
import api from '../../api';

// ── Risk color mapping ──
const RISK_COLORS = {
  CRITICAL: { bg: 'bg-red-500/15', border: 'border-red-500/50', text: 'text-red-400', hex: '#ef4444', pulse: true },
  HIGH: { bg: 'bg-orange-500/15', border: 'border-orange-500/50', text: 'text-orange-400', hex: '#f97316', pulse: true },
  MODERATE: { bg: 'bg-amber-500/15', border: 'border-amber-500/50', text: 'text-amber-400', hex: '#f59e0b', pulse: false },
  LOW: { bg: 'bg-emerald-500/15', border: 'border-emerald-500/50', text: 'text-emerald-400', hex: '#10b981', pulse: false },
  SAFE: { bg: 'bg-emerald-500/15', border: 'border-emerald-500/50', text: 'text-emerald-400', hex: '#10b981', pulse: false },
};

function getRisk(level) {
  return RISK_COLORS[level?.toUpperCase()] || RISK_COLORS.SAFE;
}

// ── Custom marker icons ──
function userIcon(riskLevel) {
  const color = getRisk(riskLevel).hex;
  return L.divIcon({
    className: '',
    iconSize: [36, 36],
    iconAnchor: [18, 18],
    html: `<div style="width:36px;height:36px;border-radius:50%;background:${color};border:3px solid white;box-shadow:0 0 12px ${color}80;display:flex;align-items:center;justify-content:center;">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="white"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/></svg>
    </div>`,
  });
}

// ── Map auto-pan component ──
function MapUpdater({ center }) {
  const map = useMap();
  useEffect(() => {
    if (center) map.flyTo(center, map.getZoom(), { duration: 1 });
  }, [center, map]);
  return null;
}

// ── Time formatter ──
function formatDuration(seconds) {
  if (!seconds) return '0m';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function lastUpdateText(seconds) {
  if (!seconds && seconds !== 0) return 'N/A';
  if (seconds < 10) return 'Just now';
  if (seconds < 60) return `${seconds}s ago`;
  return `${Math.floor(seconds / 60)}m ago`;
}

export default function MobileGuardianLiveMap() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const initialUserId = searchParams.get('user');

  const [protectedUsers, setProtectedUsers] = useState([]);
  const [selectedUserId, setSelectedUserId] = useState(initialUserId);
  const [liveData, setLiveData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [panelOpen, setPanelOpen] = useState(true);
  const [mapCenter, setMapCenter] = useState([19.076, 72.877]);
  const refreshRef = useRef(null);

  // Fetch protected users list
  useEffect(() => {
    api.get('/guardian/live/protected-users').then(res => {
      const users = res.data?.protected_users || [];
      setProtectedUsers(users);
      if (!selectedUserId && users.length > 0) {
        setSelectedUserId(users[0].user_id);
      }
    }).catch(() => {}).finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch live status for selected user
  const fetchLiveStatus = useCallback(async () => {
    if (!selectedUserId) return;
    try {
      const res = await api.get(`/guardian/live/status/${selectedUserId}`);
      setLiveData(res.data);
      const loc = res.data?.session?.current_location;
      if (loc?.lat && loc?.lng) {
        setMapCenter([loc.lat, loc.lng]);
      }
    } catch (err) {
      console.warn('Live status fetch error:', err.message);
    }
  }, [selectedUserId]);

  useEffect(() => {
    fetchLiveStatus();
    refreshRef.current = setInterval(fetchLiveStatus, 10000);
    return () => clearInterval(refreshRef.current);
  }, [fetchLiveStatus]);

  const risk = getRisk(liveData?.risk?.level);
  const session = liveData?.session;
  const loc = session?.current_location;

  // Build route polyline from route_points
  const routePositions = (session?.route_points || [])
    .filter(p => p?.lat && p?.lng)
    .map(p => [p.lat, p.lng]);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center" data-testid="guardian-live-map-loading">
        <Loader2 className="w-8 h-8 text-teal-400 animate-spin" />
      </div>
    );
  }

  if (protectedUsers.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center px-6" data-testid="no-protected-users">
        <Users className="w-12 h-12 text-slate-600 mb-4" />
        <p className="text-slate-400 text-sm text-center">You are not a guardian of anyone yet.</p>
        <p className="text-slate-600 text-xs mt-1 text-center">Ask someone to add you as their guardian.</p>
        <button onClick={() => navigate('/m/home')} className="mt-4 px-4 py-2 bg-teal-500/20 text-teal-400 rounded-xl text-sm">
          Go Home
        </button>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col relative" data-testid="guardian-live-map">
      {/* ── Header ── */}
      <div className="absolute top-0 left-0 right-0 z-[1000] px-3 pt-2 pb-1">
        <div className="flex items-center gap-2 mb-2">
          <button onClick={() => navigate(-1)} className="p-1.5 rounded-xl bg-slate-900/90 backdrop-blur-lg border border-slate-700/50" data-testid="live-map-back-btn">
            <ArrowLeft className="w-4 h-4 text-slate-300" />
          </button>
          <div className="flex-1 text-center">
            <span className="text-xs font-medium text-slate-400 tracking-wider uppercase">Guardian Live Map</span>
          </div>
          <div className="w-8" />
        </div>

        {/* ── User Info Card ── */}
        {liveData && (
          <div className={`bg-slate-900/90 backdrop-blur-lg rounded-2xl border ${risk.border} p-3`} data-testid="live-user-card">
            <div className="flex items-center justify-between">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-white truncate" data-testid="live-user-name">{liveData.user_name}</p>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${risk.bg} ${risk.text}`} data-testid="live-risk-badge">
                    {liveData.risk?.level || 'SAFE'}
                  </span>
                  <span className={`text-[10px] font-medium ${session ? 'text-teal-400' : 'text-slate-500'}`}>
                    {session ? 'SESSION ACTIVE' : 'NO SESSION'}
                  </span>
                </div>
              </div>
              <div className="text-right">
                <p className={`text-2xl font-bold ${risk.text}`} data-testid="live-risk-score">{liveData.risk?.score || 0}</p>
                <p className="text-[9px] text-slate-500">RISK /10</p>
              </div>
            </div>
            {session && (
              <div className="flex items-center gap-3 mt-2 pt-2 border-t border-slate-800/50">
                <div className="flex items-center gap-1">
                  <Clock className="w-3 h-3 text-slate-500" />
                  <span className="text-[10px] text-slate-400">{formatDuration(session.duration_seconds)}</span>
                </div>
                <div className="flex items-center gap-1">
                  <Navigation className="w-3 h-3 text-slate-500" />
                  <span className="text-[10px] text-slate-400">{(session.total_distance_m / 1000).toFixed(1)} km</span>
                </div>
                <div className="flex items-center gap-1">
                  <Zap className="w-3 h-3 text-slate-500" />
                  <span className="text-[10px] text-slate-400">{session.speed_kmh} km/h</span>
                </div>
                <div className="flex items-center gap-1 ml-auto">
                  <Eye className="w-3 h-3 text-slate-500" />
                  <span className="text-[10px] text-slate-400">{lastUpdateText(session.last_update_seconds)}</span>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── User Selector (if multiple) ── */}
        {protectedUsers.length > 1 && (
          <div className="flex gap-1.5 mt-2 overflow-x-auto pb-1 scrollbar-hide">
            {protectedUsers.map(u => (
              <button
                key={u.user_id}
                onClick={() => setSelectedUserId(u.user_id)}
                className={`shrink-0 px-3 py-1.5 rounded-xl text-xs font-medium transition-all ${
                  u.user_id === selectedUserId
                    ? 'bg-teal-500/20 text-teal-400 border border-teal-500/40'
                    : 'bg-slate-800/60 text-slate-500 border border-slate-700/30'
                }`}
                data-testid={`user-selector-${u.user_id}`}
              >
                {u.name?.split(' ')[0] || 'User'}
                {u.has_active_session && <span className="ml-1 w-1.5 h-1.5 rounded-full bg-teal-400 inline-block" />}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ── Map ── */}
      <div className="flex-1" data-testid="live-map-container">
        <MapContainer
          center={mapCenter}
          zoom={15}
          className="h-full w-full"
          style={{ background: '#0f172a' }}
          zoomControl={false}
          attributionControl={false}
        >
          <TileLayer
            url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
            attribution="NISCHINT"
          />
          <MapUpdater center={loc ? [loc.lat, loc.lng] : null} />

          {/* User location marker */}
          {loc?.lat && loc?.lng && (
            <Marker position={[loc.lat, loc.lng]} icon={userIcon(liveData?.risk?.level)}>
              <Popup className="nischint-popup">
                <div className="text-xs">
                  <strong>{liveData?.user_name}</strong><br />
                  Risk: {liveData?.risk?.level} ({liveData?.risk?.score}/10)
                </div>
              </Popup>
            </Marker>
          )}

          {/* Route polyline (PLANNED route — dashed cyan) */}
          {routePositions.length > 1 && (
            <Polyline
              positions={routePositions}
              pathOptions={{ color: '#06b6d4', weight: 3, dashArray: '8,6', opacity: 0.7 }}
            />
          )}

          {/* Tri-color ACTUAL historical polyline — solid blue / dashed
              amber / dashed grey depending on edge quality. Only
              rendered when a session is live. */}
          {session?.session_id && (
            <JourneyPolyline sessionId={session.session_id} />
          )}

          {/* Risk zone around user */}
          {loc?.lat && loc?.lng && liveData?.risk?.score > 3 && (
            <Circle
              center={[loc.lat, loc.lng]}
              radius={200}
              pathOptions={{
                color: risk.hex,
                fillColor: risk.hex,
                fillOpacity: 0.08,
                weight: 1,
                dashArray: '4,4',
              }}
            />
          )}

          {/* Alert markers */}
          {(liveData?.recent_alerts || []).filter(a => a.location?.lat).map((a, i) => (
            <Circle
              key={i}
              center={[a.location.lat, a.location.lng]}
              radius={50}
              pathOptions={{
                color: a.severity === 'critical' ? '#ef4444' : a.severity === 'high' ? '#f97316' : '#f59e0b',
                fillOpacity: 0.15,
                weight: 2,
              }}
            />
          ))}
        </MapContainer>

        {/* Polyline legend — only visible when an active session paints
            the tri-color historical trail. Explains what dashed-amber /
            dashed-grey actually mean so guardians don't panic. */}
        {session?.session_id && (
          <div
            className="absolute top-3 right-3 z-[1000] bg-slate-900/85 backdrop-blur-sm border border-slate-700/60 rounded-lg px-3 py-2 text-[10px] text-slate-300 space-y-1 shadow-lg"
            data-testid="polyline-legend"
          >
            <div className="flex items-center gap-2">
              <span className="inline-block w-5 h-0.5 bg-cyan-500 rounded-full" />
              <span>Live GPS</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="inline-block w-5 border-t-2 border-dashed border-amber-500" />
              <span>Weak signal</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="inline-block w-5 border-t-2 border-dashed border-slate-500" />
              <span>Offline gap</span>
            </div>
          </div>
        )}
      </div>

      {/* ── Bottom Intelligence Panel ── */}
      <div className={`absolute bottom-0 left-0 right-0 z-[1000] transition-transform duration-300 ${panelOpen ? 'translate-y-0' : 'translate-y-[calc(100%-44px)]'}`}>
        {/* Toggle handle */}
        <button
          onClick={() => setPanelOpen(!panelOpen)}
          className="w-full flex items-center justify-center py-1 bg-slate-900/95 backdrop-blur-lg rounded-t-2xl border-t border-x border-slate-700/50"
          data-testid="panel-toggle"
        >
          <div className="w-8 h-1 rounded-full bg-slate-600 mb-1" />
          {panelOpen ? <ChevronDown className="w-4 h-4 text-slate-500" /> : <ChevronUp className="w-4 h-4 text-slate-500" />}
        </button>

        <div className="bg-slate-900/95 backdrop-blur-lg border-x border-slate-700/50 px-4 pb-4" data-testid="intelligence-panel">
          {/* AI Intelligence Row */}
          <div className="grid grid-cols-3 gap-3 mb-3">
            <div className="text-center" data-testid="ai-risk-score-panel">
              <p className={`text-xl font-bold ${risk.text}`}>{liveData?.risk?.score || 0}</p>
              <p className="text-[9px] text-slate-500 uppercase">AI Risk</p>
            </div>
            <div className="text-center" data-testid="behavior-pattern-panel">
              <p className="text-xs font-semibold text-slate-300">{liveData?.behavior_pattern || 'Normal'}</p>
              <p className="text-[9px] text-slate-500 uppercase">Pattern</p>
            </div>
            <div className="text-center" data-testid="recommendation-panel">
              <p className="text-xs font-semibold text-slate-300 line-clamp-1">{liveData?.recommendation || 'N/A'}</p>
              <p className="text-[9px] text-slate-500 uppercase">Action</p>
            </div>
          </div>

          {/* Risk Factors */}
          {liveData?.risk?.factors?.length > 0 && (
            <div className="mb-3">
              <p className="text-[10px] text-slate-500 uppercase mb-1.5">Risk Factors</p>
              <div className="flex flex-wrap gap-1">
                {liveData.risk.factors.slice(0, 4).map((f, i) => (
                  <span key={i} className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800/80 text-slate-400 border border-slate-700/40">
                    {typeof f === 'string' ? f : f.name || f.factor || 'Unknown'}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Session status indicators */}
          {session && (
            <div className="flex gap-2 mb-3">
              {session.route_deviated && (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-red-500/10 text-red-400 border border-red-500/30 flex items-center gap-1">
                  <AlertTriangle className="w-3 h-3" /> Route Deviated
                </span>
              )}
              {session.is_idle && (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/30">
                  Idle
                </span>
              )}
              {session.is_night && (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/30">
                  Night Mode
                </span>
              )}
              {session.destination && (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-700/50 text-slate-400 flex items-center gap-1">
                  <MapPin className="w-3 h-3" /> {session.destination}
                </span>
              )}
            </div>
          )}

          {/* Recent Alerts Preview */}
          {liveData?.recent_alerts?.length > 0 && (
            <div className="mb-3">
              <p className="text-[10px] text-slate-500 uppercase mb-1.5">Recent Alerts</p>
              <div className="space-y-1">
                {liveData.recent_alerts.slice(0, 3).map(a => (
                  <div key={a.id} className="flex items-center gap-2 text-[10px]">
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                      a.severity === 'critical' ? 'bg-red-400' : a.severity === 'high' ? 'bg-orange-400' : 'bg-amber-400'
                    }`} />
                    <span className="text-slate-400 truncate flex-1">{a.message || a.type}</span>
                    <span className="text-slate-600 shrink-0">{a.created_at ? new Date(a.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ── Action Buttons ── */}
          <div className="grid grid-cols-4 gap-2" data-testid="action-buttons">
            <ActionButton
              icon={<Phone className="w-4 h-4" />}
              label="Call"
              color="bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
              testId="action-call"
              onClick={() => {
                if (liveData?.email) window.location.href = `tel:${liveData.email}`;
              }}
            />
            <ActionButton
              icon={<MessageCircle className="w-4 h-4" />}
              label="Message"
              color="bg-blue-500/15 text-blue-400 border-blue-500/30"
              testId="action-message"
              onClick={() => {}}
            />
            <ActionButton
              icon={<Bell className="w-4 h-4" />}
              label="Safety Ping"
              color="bg-amber-500/15 text-amber-400 border-amber-500/30"
              testId="action-ping"
              onClick={async () => {
                if (!session) return;
                try {
                  await api.post('/guardian/dashboard/request-check', { session_id: session.session_id });
                } catch {}
              }}
            />
            <ActionButton
              icon={<ShieldAlert className="w-4 h-4" />}
              label="Alert"
              color="bg-red-500/15 text-red-400 border-red-500/30"
              testId="action-alert"
              onClick={() => navigate('/m/sos')}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function ActionButton({ icon, label, color, testId, onClick }) {
  return (
    <button
      onClick={onClick}
      className={`flex flex-col items-center gap-1 py-2.5 rounded-xl border ${color} active:scale-95 transition-transform`}
      data-testid={testId}
    >
      {icon}
      <span className="text-[10px] font-medium">{label}</span>
    </button>
  );
}
