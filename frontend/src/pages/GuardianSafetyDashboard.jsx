import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import {
  Shield, AlertTriangle, CheckCircle, Loader2, MapPin, Clock,
  Navigation, Phone, MessageSquare, RefreshCw, Eye, Heart,
  ArrowRight, Zap, Activity, ChevronDown, ChevronUp,
} from 'lucide-react';
import { operatorApi } from '../api';
import { toast } from 'sonner';
import L from 'leaflet';
import { MapContainer, TileLayer, Marker, Popup, Circle, Polyline, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';

// Fix default marker icon
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

const RISK_COLORS = { SAFE: '#10b981', LOW: '#f59e0b', HIGH: '#ef4444', CRITICAL: '#991b1b' };
const RISK_BG = { SAFE: 'bg-emerald-100 text-emerald-700', LOW: 'bg-amber-100 text-amber-700', HIGH: 'bg-red-100 text-red-700', CRITICAL: 'bg-red-200 text-red-800' };
const SEVERITY_BG = { low: 'bg-slate-100 text-slate-600', medium: 'bg-amber-100 text-amber-700', high: 'bg-red-100 text-red-700', critical: 'bg-red-200 text-red-800' };
const ALERT_ICONS = {
  zone_risk: <AlertTriangle className="w-4 h-4 text-red-500" />,
  idle: <Clock className="w-4 h-4 text-amber-500" />,
  emergency: <Zap className="w-4 h-4 text-red-600" />,
  arrived: <CheckCircle className="w-4 h-4 text-emerald-500" />,
  route_deviation: <Navigation className="w-4 h-4 text-orange-500" />,
  safety_confirmed: <CheckCircle className="w-4 h-4 text-emerald-500" />,
  check_in_request: <MessageSquare className="w-4 h-4 text-blue-500" />,
};

const createUserIcon = (riskLevel) => L.divIcon({
  className: 'custom-marker',
  html: `<div style="width:32px;height:32px;border-radius:50%;background:${RISK_COLORS[riskLevel] || '#6366f1'};border:3px solid white;box-shadow:0 2px 8px rgba(0,0,0,0.3);display:flex;align-items:center;justify-content:center">
    <div style="width:10px;height:10px;border-radius:50%;background:white"></div>
  </div>`,
  iconSize: [32, 32], iconAnchor: [16, 16],
});

const createDestIcon = () => L.divIcon({
  className: 'custom-marker',
  html: `<div style="width:28px;height:28px;border-radius:50%;background:#6366f1;border:3px solid white;box-shadow:0 2px 8px rgba(0,0,0,0.3);display:flex;align-items:center;justify-content:center">
    <div style="width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;border-bottom:8px solid white;transform:rotate(180deg)"></div>
  </div>`,
  iconSize: [28, 28], iconAnchor: [14, 14],
});

const MapRecenter = ({ center }) => {
  const map = useMap();
  useEffect(() => {
    if (center) map.flyTo(center, 14, { duration: 1 });
  }, [center, map]);
  return null;
};

const LiveMap = ({ sessions, zones }) => {
  const [mapCenter, setMapCenter] = useState([19.076, 72.877]);

  useEffect(() => {
    if (sessions.length > 0 && sessions[0].current_location) {
      const loc = sessions[0].current_location;
      setMapCenter([loc.lat, loc.lng]);
    }
  }, [sessions]);

  return (
    <div className="h-full w-full rounded-xl overflow-hidden" data-testid="safety-live-map">
      <MapContainer center={mapCenter} zoom={14} style={{ height: '100%', width: '100%' }}
        zoomControl={false} attributionControl={false}>
        <TileLayer url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" />
        <MapRecenter center={mapCenter} />

        {sessions.map((s) => {
          if (!s.current_location) return null;
          const pos = [s.current_location.lat, s.current_location.lng];
          return (
            <React.Fragment key={s.session_id}>
              <Marker position={pos} icon={createUserIcon(s.risk_level)}>
                <Popup>
                  <div className="text-sm">
                    <p className="font-bold">{s.user_name}</p>
                    <p>Risk: {s.risk_level} ({s.risk_score})</p>
                    <p>Speed: {s.speed_kmh} km/h</p>
                    {s.eta_minutes && <p>ETA: {s.eta_minutes} min</p>}
                  </div>
                </Popup>
              </Marker>
              <Circle center={pos} radius={250} pathOptions={{
                color: RISK_COLORS[s.risk_level] || '#6366f1', fillOpacity: 0.1, weight: 1, dashArray: '4 4',
              }} />
              {s.destination && (
                <>
                  <Marker position={[s.destination.lat, s.destination.lng]} icon={createDestIcon()}>
                    <Popup><span className="text-sm font-medium">Destination</span></Popup>
                  </Marker>
                  <Polyline positions={[pos, [s.destination.lat, s.destination.lng]]}
                    pathOptions={{ color: '#818cf8', weight: 2, dashArray: '8 8', opacity: 0.7 }} />
                </>
              )}
            </React.Fragment>
          );
        })}

        {zones.map((z, i) => (
          <Circle key={i} center={[z.lat, z.lng]} radius={z.radius || 300}
            pathOptions={{ color: RISK_COLORS[z.risk_level] || '#ef4444', fillOpacity: 0.15, weight: 1 }} />
        ))}
      </MapContainer>
    </div>
  );
};

const StatusCard = ({ person, onRequestCheck, requestingCheck }) => {
  const s = person.active_session;
  if (!s) {
    return (
      <Card className="border-l-4 border-l-slate-300" data-testid={`status-card-${person.user_id}`}>
        <CardContent className="p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-slate-200 flex items-center justify-center text-slate-500 font-bold text-lg">
                {person.name[0]}
              </div>
              <div>
                <p className="font-semibold text-slate-800">{person.name}</p>
                <p className="text-xs text-slate-400">{person.relationship}</p>
              </div>
            </div>
            <Badge className="bg-slate-100 text-slate-500">No Active Journey</Badge>
          </div>
        </CardContent>
      </Card>
    );
  }

  const borderColor = s.risk_level === 'CRITICAL' ? 'border-l-red-600' :
    s.risk_level === 'HIGH' ? 'border-l-red-400' :
    s.risk_level === 'LOW' ? 'border-l-amber-400' : 'border-l-emerald-400';

  return (
    <Card className={`border-l-4 ${borderColor}`} data-testid={`status-card-${person.user_id}`}>
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <div className={`w-10 h-10 rounded-full flex items-center justify-center text-white font-bold text-lg ${
              s.risk_level === 'SAFE' ? 'bg-emerald-500' : s.risk_level === 'HIGH' ? 'bg-red-500' : s.risk_level === 'CRITICAL' ? 'bg-red-700' : 'bg-amber-500'
            }`}>
              {person.name[0]}
            </div>
            <div>
              <p className="font-semibold text-slate-800">{person.name}</p>
              <p className="text-xs text-slate-400">{person.relationship} &middot; Journey Active</p>
            </div>
          </div>
          <Badge className={RISK_BG[s.risk_level] || 'bg-slate-100'} data-testid={`risk-badge-${person.user_id}`}>
            {s.risk_level}
          </Badge>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
          <div className="bg-slate-50 rounded-lg p-2.5">
            <p className="text-xs text-slate-400">Location</p>
            <p className="font-medium text-slate-700 truncate">{s.zone_name || 'Unknown'}</p>
          </div>
          <div className="bg-slate-50 rounded-lg p-2.5">
            <p className="text-xs text-slate-400">Speed</p>
            <p className="font-medium text-slate-700">{s.speed_kmh} km/h</p>
          </div>
          <div className="bg-slate-50 rounded-lg p-2.5">
            <p className="text-xs text-slate-400">ETA Home</p>
            <p className="font-medium text-slate-700">{s.eta_minutes ? `${s.eta_minutes} min` : '--'}</p>
          </div>
          <div className="bg-slate-50 rounded-lg p-2.5">
            <p className="text-xs text-slate-400">Duration</p>
            <p className="font-medium text-slate-700">{s.duration_minutes} min</p>
          </div>
        </div>

        {/* Status flags */}
        <div className="flex gap-2 mt-3 flex-wrap">
          {s.is_idle && <Badge className="bg-amber-50 text-amber-600 text-xs">Idle</Badge>}
          {s.route_deviated && <Badge className="bg-orange-50 text-orange-600 text-xs">Route Deviated</Badge>}
          {s.is_night && <Badge className="bg-indigo-50 text-indigo-600 text-xs">Night Journey</Badge>}
          {s.escalation_level !== 'none' && (
            <Badge className="bg-red-50 text-red-600 text-xs">Escalation: {s.escalation_level}</Badge>
          )}
        </div>

        {/* Guardian Controls */}
        <div className="flex gap-2 mt-3">
          {person.phone && (
            <Button size="sm" variant="outline" className="text-xs" asChild data-testid={`call-btn-${person.user_id}`}>
              <a href={`tel:${person.phone}`}><Phone className="w-3.5 h-3.5 mr-1" />Call</a>
            </Button>
          )}
          <Button size="sm" variant="outline" className="text-xs"
            onClick={() => onRequestCheck(s.session_id)}
            disabled={requestingCheck}
            data-testid={`checkin-btn-${person.user_id}`}>
            <MessageSquare className="w-3.5 h-3.5 mr-1" />
            {requestingCheck ? 'Sending...' : 'Request Check-in'}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
};

const AlertsFeed = ({ alerts }) => {
  const [expanded, setExpanded] = useState(true);
  const shown = expanded ? alerts : alerts.slice(0, 5);

  return (
    <Card data-testid="alerts-feed">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold flex items-center gap-2 text-slate-700">
          <Activity className="w-4 h-4 text-amber-500" /> Alerts Feed
          <Badge variant="outline" className="ml-auto text-xs">{alerts.length}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="p-3 pt-0 max-h-[400px] overflow-y-auto">
        {alerts.length === 0 ? (
          <p className="text-xs text-slate-400 text-center py-4">No alerts yet</p>
        ) : (
          <div className="space-y-2">
            {shown.map((a) => (
              <div key={a.id} className="flex items-start gap-2 p-2 rounded-lg bg-slate-50 hover:bg-slate-100 transition-colors"
                data-testid={`alert-item-${a.id}`}>
                <div className="mt-0.5">{ALERT_ICONS[a.alert_type] || <AlertTriangle className="w-4 h-4 text-slate-400" />}</div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-medium text-slate-700">{a.user_name}</span>
                    <Badge className={`text-[10px] px-1 py-0 ${SEVERITY_BG[a.severity] || ''}`}>{a.severity}</Badge>
                  </div>
                  <p className="text-xs text-slate-600 mt-0.5">{a.message}</p>
                  <p className="text-[10px] text-slate-400 mt-0.5">
                    {a.created_at ? new Date(a.created_at).toLocaleTimeString() : ''}
                  </p>
                </div>
              </div>
            ))}
            {alerts.length > 5 && (
              <Button variant="ghost" size="sm" className="w-full text-xs text-slate-500"
                onClick={() => setExpanded(!expanded)}>
                {expanded ? <><ChevronUp className="w-3 h-3 mr-1" />Show less</> : <><ChevronDown className="w-3 h-3 mr-1" />Show all ({alerts.length})</>}
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
};

const SessionHistory = ({ history }) => (
  <Card data-testid="session-history">
    <CardHeader className="pb-2">
      <CardTitle className="text-sm font-semibold flex items-center gap-2 text-slate-700">
        <Clock className="w-4 h-4 text-indigo-500" /> Journey History
      </CardTitle>
    </CardHeader>
    <CardContent className="p-3 pt-0 max-h-[400px] overflow-y-auto">
      {history.length === 0 ? (
        <p className="text-xs text-slate-400 text-center py-4">No journey history</p>
      ) : (
        <div className="space-y-2">
          {history.map((h) => (
            <div key={h.session_id} className="p-2.5 rounded-lg bg-slate-50" data-testid={`history-item-${h.session_id}`}>
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-slate-700">{h.user_name}</span>
                <Badge className={RISK_BG[h.max_risk_level] || 'bg-slate-100'} style={{ fontSize: '10px', padding: '1px 6px' }}>
                  {h.max_risk_level}
                </Badge>
              </div>
              <div className="grid grid-cols-3 gap-2 mt-1.5 text-[11px] text-slate-500">
                <div>
                  <p className="text-slate-400">Duration</p>
                  <p className="font-medium">{h.duration_minutes} min</p>
                </div>
                <div>
                  <p className="text-slate-400">Alerts</p>
                  <p className="font-medium">{h.alert_count}</p>
                </div>
                <div>
                  <p className="text-slate-400">Distance</p>
                  <p className="font-medium">{(h.total_distance_m / 1000).toFixed(1)} km</p>
                </div>
              </div>
              <p className="text-[10px] text-slate-400 mt-1">
                {h.started_at ? new Date(h.started_at).toLocaleDateString() + ' ' + new Date(h.started_at).toLocaleTimeString() : ''}
              </p>
            </div>
          ))}
        </div>
      )}
    </CardContent>
  </Card>
);

const EmptyState = () => (
  <div className="flex flex-col items-center justify-center py-16 text-center" data-testid="safety-empty-state">
    <div className="w-20 h-20 rounded-full bg-teal-50 flex items-center justify-center mb-4">
      <Heart className="w-10 h-10 text-teal-400" />
    </div>
    <h3 className="text-lg font-semibold text-slate-700 mb-2">No Loved Ones Connected</h3>
    <p className="text-sm text-slate-500 max-w-md mb-4">
      When someone adds you as their guardian contact, they will appear here.
      You'll be able to monitor their journeys in real-time.
    </p>
    <div className="bg-slate-50 rounded-xl p-4 max-w-sm text-left">
      <p className="text-xs font-semibold text-slate-600 mb-2">How it works:</p>
      <ol className="text-xs text-slate-500 space-y-1.5 list-decimal list-inside">
        <li>Your loved one opens the app and adds you as a guardian</li>
        <li>They start a journey with Guardian Mode enabled</li>
        <li>You see their live location, risk status, and alerts here</li>
      </ol>
    </div>
  </div>
);

const GuardianSafetyDashboard = () => {
  const [lovedOnes, setLovedOnes] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [history, setHistory] = useState([]);
  const [zones, setZones] = useState([]);
  const [loading, setLoading] = useState(true);
  const [requestingCheck, setRequestingCheck] = useState(false);
  const refreshRef = useRef(null);

  const fetchData = useCallback(async () => {
    try {
      const [lovedRes, sessRes, alertRes, histRes] = await Promise.all([
        operatorApi.getGuardianLovedOnes(),
        operatorApi.getGuardianDashboardSessions(),
        operatorApi.getGuardianDashboardAlerts(30),
        operatorApi.getGuardianDashboardHistory(10),
      ]);
      setLovedOnes(lovedRes.data);
      setSessions(sessRes.data.sessions || []);
      setAlerts(alertRes.data.alerts || []);
      setHistory(histRes.data.history || []);
    } catch (err) {
      console.error('Dashboard fetch error:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchZones = useCallback(async () => {
    try {
      const res = await operatorApi.getZoneMap();
      setZones(res.data.zones || []);
    } catch {
      // Zone map optional
    }
  }, []);

  useEffect(() => {
    fetchData();
    fetchZones();
    refreshRef.current = setInterval(fetchData, 15000);
    return () => clearInterval(refreshRef.current);
  }, [fetchData, fetchZones]);

  const handleRequestCheck = async (sessionId) => {
    setRequestingCheck(true);
    try {
      await operatorApi.requestGuardianSafetyCheck(sessionId);
      toast.success('Safety check request sent');
      fetchData();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to send request');
    } finally {
      setRequestingCheck(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-teal-600" />
      </div>
    );
  }

  const monitored = lovedOnes?.monitored_users || [];
  const hasLovedOnes = monitored.length > 0;
  const activeJourneys = lovedOnes?.active_journeys || 0;

  if (!hasLovedOnes) return <EmptyState />;

  return (
    <div className="space-y-6" data-testid="guardian-safety-dashboard">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-800">Safety Monitor</h2>
          <p className="text-sm text-slate-500">
            {monitored.length} loved one{monitored.length !== 1 ? 's' : ''} &middot; {activeJourneys} active journey{activeJourneys !== 1 ? 's' : ''}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchData} data-testid="safety-refresh-btn">
          <RefreshCw className="w-4 h-4 mr-1" /> Refresh
        </Button>
      </div>

      {/* Status Cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4" data-testid="status-cards-grid">
        {monitored.map((p) => (
          <StatusCard key={p.user_id} person={p} onRequestCheck={handleRequestCheck} requestingCheck={requestingCheck} />
        ))}
      </div>

      {/* Main Content: Map + Panels */}
      {activeJourneys > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Map (takes 2 columns) */}
          <div className="lg:col-span-2 h-[420px] rounded-xl overflow-hidden border border-slate-200">
            <LiveMap sessions={sessions} zones={zones} />
          </div>

          {/* Right panel */}
          <div className="space-y-4">
            <AlertsFeed alerts={alerts} />
          </div>
        </div>
      )}

      {/* Bottom: Alerts + History when no active journey */}
      {activeJourneys === 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <AlertsFeed alerts={alerts} />
          <SessionHistory history={history} />
        </div>
      )}

      {/* Always show history when active journeys exist */}
      {activeJourneys > 0 && (
        <SessionHistory history={history} />
      )}
    </div>
  );
};

export default GuardianSafetyDashboard;
