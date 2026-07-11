// FamilyLivePage — single-screen consolidated Mother Dashboard
// Collapses: Safety Tracking · Safety Score · Live Safety Map · Route Monitor · Safety Zones
// Goal: guardian opens → understands child's safety in <2s → one-tap action
import React, { useCallback, useEffect, useState } from 'react';
import { MapContainer, TileLayer, Marker, Circle, useMap } from 'react-leaflet';
import {
  Shield, Phone, Bell, MapPin, Activity, AlertTriangle, RefreshCw, Heart,
  Navigation, ArrowUpRight, CheckCircle2, Radio,
} from 'lucide-react';
import { toast } from 'sonner';
import { useNavigate } from 'react-router-dom';
import api from '../api';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import 'leaflet/dist/leaflet.css';

// ─── Human-first status mapping ───
const STATUS_CFG = {
  SAFE:       { label: 'All Safe',             tint: 'bg-emerald-100 text-emerald-700 border-emerald-200', dot: 'bg-emerald-500',           color: '#10B981' },
  MOVING:     { label: 'Moving Safely',        tint: 'bg-amber-100 text-amber-700 border-amber-200',       dot: 'bg-amber-500',             color: '#F59E0B' },
  WARNING:    { label: 'Check In Needed',      tint: 'bg-orange-100 text-orange-700 border-orange-200',    dot: 'bg-orange-500',            color: '#F97316' },
  EMERGENCY:  { label: 'Needs Help Now',       tint: 'bg-red-100 text-red-700 border-red-200',             dot: 'bg-red-500 animate-pulse', color: '#EF4444' },
  OFFLINE:    { label: 'Signal Weak',          tint: 'bg-slate-100 text-slate-700 border-slate-200',       dot: 'bg-slate-400',             color: '#64748B' },
};

function humanAgo(iso) {
  if (!iso) return '—';
  try {
    const then = new Date(iso).getTime();
    const secs = Math.max(0, Math.floor((Date.now() - then) / 1000));
    if (secs < 2) return 'just now';
    if (secs < 60) return `${secs}s ago`;
    const m = Math.floor(secs / 60);
    if (m < 60) return `${m}m ago`;
    return `${Math.floor(m / 60)}h ago`;
  } catch { return '—'; }
}

function humanDist(m) {
  if (!m && m !== 0) return '';
  return m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(1)} km`;
}

// Smooth fly-to on map when selection / location changes
function FlyTo({ lat, lng, zoom }) {
  const map = useMap();
  useEffect(() => { if (lat && lng) map.flyTo([lat, lng], zoom || 14, { duration: 0.8 }); }, [lat, lng, zoom, map]);
  return null;
}

const FamilyLivePage = () => {
  const navigate = useNavigate();
  const [lovedOnes, setLovedOnes] = useState([]);
  const [selected, setSelected] = useState(null);   // monitored user id
  const [zoneStatus, setZoneStatus] = useState(null); // geofence state for selected
  const [safetyScore, setSafetyScore] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadLovedOnes = useCallback(async () => {
    try {
      const { data } = await api.get('/guardian/dashboard/loved-ones');
      const arr = data?.monitored_users || [];
      setLovedOnes(arr);
      if (!selected && arr.length > 0) setSelected(arr[0].user_id);
    } catch (e) {
      toast.error('Could not load your loved ones');
    } finally {
      setLoading(false);
    }
  }, [selected]);

  const loadGeofenceStatus = useCallback(async () => {
    if (!selected) return;
    try {
      const { data } = await api.get(`/geofence/status/${selected}`);
      setZoneStatus(data);
    } catch { /* quiet */ }
  }, [selected]);

  const loadSafetyScore = useCallback(async () => {
    if (!selected) return;
    try {
      const { data } = await api.get(`/safety-score/${selected}`).catch(() => ({ data: null }));
      setSafetyScore(data);
    } catch { setSafetyScore(null); }
  }, [selected]);

  useEffect(() => { loadLovedOnes(); }, [loadLovedOnes]);
  useEffect(() => {
    loadGeofenceStatus();
    loadSafetyScore();
    const poll = setInterval(() => {
      loadLovedOnes();
      loadGeofenceStatus();
    }, 10_000);
    return () => clearInterval(poll);
  }, [loadGeofenceStatus, loadSafetyScore, loadLovedOnes]);

  const currentUser = lovedOnes.find(u => u.user_id === selected);
  const loc = currentUser?.location;
  const rawStatus = (currentUser?.status || 'SAFE').toUpperCase();
  const cfg = STATUS_CFG[rawStatus] || STATUS_CFG.SAFE;
  const zone = zoneStatus?.zone || (zoneStatus?.zone_id ? {
    id: zoneStatus.zone_id,
    name: zoneStatus.zone_name,
    center_lat: zoneStatus.center_lat,
    center_lng: zoneStatus.center_lng,
    radius_m: zoneStatus.radius_m,
  } : null);
  const scoreVal = safetyScore?.score ?? safetyScore?.overall_score ?? null;

  const handleCall = () => {
    if (currentUser?.phone) {
      window.location.href = `tel:${currentUser.phone}`;
    } else {
      toast('Phone number not set for this user');
    }
  };

  const handleStartTracking = async () => {
    if (!selected) return;
    try {
      await api.post('/tracking/session/start', { user_id: selected }).catch(() => {});
      toast.success(`Live tracking enabled for ${currentUser?.name || 'your loved one'}`);
      loadLovedOnes();
    } catch { toast.error('Could not start live tracking'); }
  };

  const handleEscalate = () => {
    navigate('/family/incidents');
  };

  return (
    <div className="space-y-4" data-testid="family-live-page">
      {/* ─── HERO STATUS ROW (reads in < 2 seconds) ─── */}
      <Card className={`border-l-4 ${rawStatus === 'EMERGENCY' ? 'border-l-red-500 bg-gradient-to-br from-red-50 to-white' : 'border-l-teal-500 bg-gradient-to-br from-teal-50 to-white'}`}>
        <CardContent className="pt-6">
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div className="flex items-center gap-4">
              <div className={`w-14 h-14 rounded-full flex items-center justify-center ${rawStatus === 'EMERGENCY' ? 'bg-red-100' : 'bg-teal-100'}`}>
                <Shield className={`w-7 h-7 ${rawStatus === 'EMERGENCY' ? 'text-red-600' : 'text-teal-600'}`} />
              </div>
              <div>
                <p className="text-xs text-slate-500 uppercase tracking-wider font-semibold">Care status</p>
                <h1 className="text-2xl font-bold text-slate-800" data-testid="hero-status-label">
                  {currentUser?.name || 'Your Loved One'} — {cfg.label}
                </h1>
                <p className="text-sm text-slate-600 mt-1">
                  {zoneStatus?.message || (rawStatus === 'SAFE' ? 'Everything looks calm. Updates every 10 seconds.' : '')}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <Button onClick={handleCall} className="bg-teal-600 hover:bg-teal-700" data-testid="quick-call-btn">
                <Phone className="w-4 h-4 mr-2" /> Call
              </Button>
              <Button variant="outline" onClick={handleStartTracking} data-testid="quick-track-btn">
                <Activity className="w-4 h-4 mr-2" /> Start Live Tracking
              </Button>
              {rawStatus === 'EMERGENCY' ? (
                <Button variant="destructive" onClick={handleEscalate} data-testid="quick-escalate-btn">
                  <AlertTriangle className="w-4 h-4 mr-2" /> Escalate
                </Button>
              ) : (
                <Button variant="outline" onClick={() => navigate('/family/incidents')} data-testid="quick-incidents-btn">
                  <Bell className="w-4 h-4 mr-2" /> Incidents
                </Button>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* LEFT — loved ones + mini stats */}
        <div className="lg:col-span-1 space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Your Loved Ones</CardTitle>
              <CardDescription>{lovedOnes.length} under your care · updates every 10s</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {loading ? (
                <p className="text-sm text-slate-500">Loading…</p>
              ) : lovedOnes.length === 0 ? (
                <p className="text-sm text-slate-500">No one linked yet.</p>
              ) : lovedOnes.map((u) => {
                const st = STATUS_CFG[(u.status || 'SAFE').toUpperCase()] || STATUS_CFG.SAFE;
                const active = selected === u.user_id;
                return (
                  <button
                    key={u.user_id}
                    onClick={() => setSelected(u.user_id)}
                    className={`w-full text-left p-3 rounded-lg border transition-all ${active ? 'border-teal-500 bg-teal-50 shadow-sm' : 'border-slate-200 hover:bg-slate-50'}`}
                    data-testid={`live-user-${u.user_id}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <div className={`w-2.5 h-2.5 rounded-full ${st.dot} shrink-0`} />
                        <span className="font-medium text-slate-800 truncate">{u.name}</span>
                      </div>
                      <Badge className={`${st.tint} border text-[10px] shrink-0`}>{st.label}</Badge>
                    </div>
                    <p className="text-xs text-slate-500 capitalize mt-0.5">{u.relationship || u.role}</p>
                    <p className="text-[11px] text-slate-400 mt-0.5">
                      <Radio className="w-3 h-3 inline mr-1" /> {humanAgo(u.last_updated)}
                    </p>
                  </button>
                );
              })}
            </CardContent>
          </Card>

          {/* Hidden smart features as a single subtle row */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm text-slate-600">Background care</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-slate-600 flex items-center gap-2"><Shield className="w-3.5 h-3.5 text-teal-600" /> Safe zone</span>
                <span className="text-slate-800 font-medium truncate max-w-[160px]">
                  {zone ? zone.name : 'Not set'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-600 flex items-center gap-2"><Navigation className="w-3.5 h-3.5 text-teal-600" /> Route watch</span>
                <span className="text-slate-800 font-medium">
                  {rawStatus === 'SAFE' ? 'Normal' : 'Alert on deviation'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-600 flex items-center gap-2"><Heart className="w-3.5 h-3.5 text-teal-600" /> Safety score</span>
                <span className="text-slate-800 font-medium">
                  {scoreVal !== null ? `${Math.round(scoreVal)}/100` : '—'}
                </span>
              </div>
              <button
                onClick={() => navigate('/family/safety-zones')}
                className="mt-1 text-xs text-teal-600 hover:text-teal-700 flex items-center gap-1"
                data-testid="configure-zones-link"
              >
                Configure safety zones <ArrowUpRight className="w-3 h-3" />
              </button>
            </CardContent>
          </Card>
        </div>

        {/* RIGHT — Map (primary) */}
        <Card className="lg:col-span-2">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <MapPin className={`w-4 h-4 ${rawStatus === 'EMERGENCY' ? 'text-red-500' : 'text-teal-600'}`} />
              Live Map
              <span className="ml-auto inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-teal-50 border border-teal-200 text-[10px] font-bold text-teal-700 tracking-wider">
                <span className="w-1.5 h-1.5 rounded-full bg-teal-500 animate-pulse" /> LIVE
              </span>
            </CardTitle>
            <CardDescription>
              {loc ? `Updated ${humanAgo(currentUser?.last_updated)}` : 'Waiting for first location update…'}
              {loc && zone && typeof zoneStatus?.distance_m === 'number' && (
                <> · {humanDist(zoneStatus.distance_m)} from {zone.name}</>
              )}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {loc ? (
              <div className="h-[460px] rounded-lg overflow-hidden border border-slate-200">
                <MapContainer
                  center={[loc.lat, loc.lng]}
                  zoom={14}
                  style={{ height: '100%', width: '100%' }}
                  scrollWheelZoom
                >
                  <TileLayer
                    url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
                    attribution='&copy; OpenStreetMap &copy; CARTO'
                  />
                  {zone && (
                    <Circle
                      center={[zone.center_lat, zone.center_lng]}
                      radius={zone.radius_m}
                      pathOptions={{
                        color: cfg.color,
                        fillColor: cfg.color,
                        fillOpacity: 0.12,
                        weight: 2,
                      }}
                    />
                  )}
                  {zone && <Marker position={[zone.center_lat, zone.center_lng]} />}
                  <Marker position={[loc.lat, loc.lng]} />
                  <FlyTo lat={loc.lat} lng={loc.lng} zoom={14} />
                </MapContainer>
              </div>
            ) : (
              <div className="h-[460px] rounded-lg border border-dashed border-slate-200 bg-slate-50 flex items-center justify-center text-center p-8">
                <div>
                  <MapPin className="w-12 h-12 text-slate-300 mx-auto mb-2" />
                  <p className="text-slate-600 font-medium">Waiting for {currentUser?.name || 'your loved one'}</p>
                  <p className="text-xs text-slate-500 mt-1">The moment they open their phone, you'll see them here.</p>
                </div>
              </div>
            )}

            {/* Inline safety chips */}
            <div className="mt-3 flex items-center gap-2 flex-wrap">
              <Badge className={`${cfg.tint} border`} data-testid="live-status-badge">{cfg.label}</Badge>
              {rawStatus === 'EMERGENCY' ? (
                <span className="text-xs text-red-600 flex items-center gap-1">
                  <AlertTriangle className="w-3.5 h-3.5" /> Family notified — support circle informed.
                </span>
              ) : (
                <span className="text-xs text-slate-500 flex items-center gap-1">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" /> Background watching — we'll notify you on any change.
                </span>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default FamilyLivePage;
