import React, { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polyline, CircleMarker, useMap } from 'react-leaflet';
import L from 'leaflet';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { operatorApi } from '../api';
import { toast } from 'sonner';
import {
  Users, Shield, AlertTriangle, MapPin, Play, Square, Plus,
  RefreshCw, Clock, Eye, Radio, CheckCircle, XCircle, Navigation,
  User, Timer, Phone, Mail, Heart, Trash2, ChevronRight
} from 'lucide-react';

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

const RISK_COLORS = { CRITICAL: '#dc2626', HIGH: '#f97316', LOW: '#eab308', SAFE: '#22c55e' };
const ESC_COLORS = { none: '#22c55e', user: '#eab308', guardian: '#f97316', emergency: '#dc2626' };
const ESC_LABELS = { none: 'Normal', user: 'User Alert', guardian: 'Guardian Alert', emergency: 'Emergency' };

function userIcon() {
  return L.divIcon({
    className: 'gm-user',
    html: '<div style="width:20px;height:20px;background:#3b82f6;border:3px solid white;border-radius:50%;box-shadow:0 0 12px rgba(59,130,246,0.6)"></div>',
    iconSize: [20, 20], iconAnchor: [10, 10],
  });
}

function destIcon() {
  return L.divIcon({
    className: 'gm-dest',
    html: '<div style="width:16px;height:16px;background:#f43f5e;border:2px solid white;border-radius:3px;box-shadow:0 0 8px rgba(244,63,94,0.5)"></div>',
    iconSize: [16, 16], iconAnchor: [8, 8],
  });
}

function FitPoints({ points }) {
  const map = useMap();
  const doneRef = useRef(false);
  useEffect(() => {
    if (doneRef.current || !points?.length) return;
    doneRef.current = true;
    map.fitBounds(points.map(p => [p.lat, p.lng]), { padding: [50, 50], maxZoom: 15 });
  }, [points, map]);
  return null;
}

function AddGuardianForm({ onAdd }) {
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [email, setEmail] = useState('');
  const [rel, setRel] = useState('family');
  const [open, setOpen] = useState(false);

  const handleAdd = async () => {
    if (!name) return toast.error('Name required');
    await onAdd({ name, phone: phone || null, email: email || null, relationship: rel });
    setName(''); setPhone(''); setEmail('');
    setOpen(false);
  };

  if (!open) return (
    <Button data-testid="gm-add-guardian-btn" onClick={() => setOpen(true)}
      size="sm" variant="outline" className="w-full border-slate-700 text-slate-300 text-xs">
      <Plus className="w-3 h-3 mr-1" /> Add Guardian
    </Button>
  );

  return (
    <div data-testid="gm-add-guardian-form" className="bg-slate-800/50 rounded-lg p-2.5 space-y-2 border border-slate-700/50">
      <input data-testid="gm-guardian-name" value={name} onChange={e => setName(e.target.value)} placeholder="Name"
        className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-300" />
      <div className="grid grid-cols-2 gap-2">
        <input data-testid="gm-guardian-phone" value={phone} onChange={e => setPhone(e.target.value)} placeholder="Phone"
          className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-300" />
        <input data-testid="gm-guardian-email" value={email} onChange={e => setEmail(e.target.value)} placeholder="Email"
          className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-300" />
      </div>
      <select data-testid="gm-guardian-rel" value={rel} onChange={e => setRel(e.target.value)}
        className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-300">
        <option value="family">Family</option>
        <option value="friend">Friend</option>
        <option value="spouse">Spouse</option>
        <option value="organization">Organization</option>
      </select>
      <div className="flex gap-2">
        <Button data-testid="gm-save-guardian" onClick={handleAdd} size="sm" className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-xs">Save</Button>
        <Button onClick={() => setOpen(false)} size="sm" variant="outline" className="border-slate-700 text-slate-400 text-xs">Cancel</Button>
      </div>
    </div>
  );
}

function GuardianList({ guardians, onRemove }) {
  if (!guardians.length) return <p className="text-xs text-slate-500 text-center py-2">No guardians added yet</p>;
  return (
    <div data-testid="gm-guardian-list" className="space-y-1.5">
      {guardians.map(g => (
        <div key={g.id} className="flex items-center gap-2 bg-slate-800/40 rounded-lg px-2.5 py-1.5 border border-slate-700/30">
          <Heart className="w-3.5 h-3.5 text-pink-400 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-xs text-slate-300 font-medium truncate">{g.name}</p>
            <p className="text-[10px] text-slate-500">{g.relationship}{g.phone ? ` | ${g.phone}` : ''}</p>
          </div>
          <Button onClick={() => onRemove(g.id)} size="sm" variant="ghost" className="h-6 w-6 p-0 text-slate-500 hover:text-red-400">
            <Trash2 className="w-3 h-3" />
          </Button>
        </div>
      ))}
    </div>
  );
}

export default function GuardianModeDashboard() {
  const [guardians, setGuardians] = useState([]);
  const [activeSession, setActiveSession] = useState(null);
  const [activeSessions, setActiveSessions] = useState([]);
  const [history, setHistory] = useState([]);
  const [locationHistory, setLocationHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [simStep, setSimStep] = useState(0);
  const [tab, setTab] = useState('monitor');

  const [startLat, setStartLat] = useState('12.971');
  const [startLng, setStartLng] = useState('77.594');
  const [destLat, setDestLat] = useState('12.935');
  const [destLng, setDestLng] = useState('77.624');

  const fetchGuardians = useCallback(async () => {
    try { const { data } = await operatorApi.listGuardianContacts(); setGuardians(data.guardians || []); } catch {}
  }, []);

  const fetchActiveSessions = useCallback(async () => {
    try { const { data } = await operatorApi.getGuardianActiveSessions(); setActiveSessions(data.sessions || []); } catch {}
  }, []);

  const fetchHistory = useCallback(async () => {
    try { const { data } = await operatorApi.getGuardianHistory(); setHistory(data.sessions || []); } catch {}
  }, []);

  const fetchSession = useCallback(async (sid) => {
    try { const { data } = await operatorApi.getGuardianSession(sid); setActiveSession(data); } catch {}
  }, []);

  useEffect(() => { fetchGuardians(); fetchActiveSessions(); fetchHistory(); }, [fetchGuardians, fetchActiveSessions, fetchHistory]);

  // Poll active session
  useEffect(() => {
    if (!activeSession?.session_id || activeSession.status !== 'active') return;
    const iv = setInterval(() => { fetchSession(activeSession.session_id); fetchActiveSessions(); }, 5000);
    return () => clearInterval(iv);
  }, [activeSession, fetchSession, fetchActiveSessions]);

  const handleAddGuardian = useCallback(async (data) => {
    try {
      await operatorApi.addGuardianContact(data);
      toast.success(`Guardian ${data.name} added`);
      fetchGuardians();
    } catch { toast.error('Failed to add guardian'); }
  }, [fetchGuardians]);

  const handleRemoveGuardian = useCallback(async (id) => {
    try {
      await operatorApi.removeGuardianContact(id);
      toast.info('Guardian removed');
      fetchGuardians();
    } catch { toast.error('Failed to remove'); }
  }, [fetchGuardians]);

  const handleStart = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await operatorApi.startGuardianSession({
        location: { lat: +startLat, lng: +startLng },
        destination: { lat: +destLat, lng: +destLng },
      });
      toast.success(`Guardian Mode active. ${data.guardians_notified} guardians notified.`);
      setLocationHistory([{ lat: +startLat, lng: +startLng }]);
      setSimStep(0);
      fetchSession(data.session_id);
      fetchActiveSessions();
    } catch { toast.error('Failed to start'); }
    setLoading(false);
  }, [startLat, startLng, destLat, destLng, fetchSession, fetchActiveSessions]);

  const handleStop = useCallback(async () => {
    if (!activeSession) return;
    try {
      const { data } = await operatorApi.stopGuardianSession(activeSession.session_id);
      toast.info(`Session ended. Duration: ${data.duration_minutes}min, Alerts: ${data.alerts_triggered}`);
      setActiveSession(null);
      setLocationHistory([]);
      fetchActiveSessions();
      fetchHistory();
    } catch { toast.error('Failed to stop'); }
  }, [activeSession, fetchActiveSessions, fetchHistory]);

  const handleStep = useCallback(async () => {
    if (!activeSession) return;
    const step = simStep + 1;
    const totalSteps = 12;
    const progress = Math.min(step / totalSteps, 1);
    const sLat = +startLat, sLng = +startLng, dLat = +destLat, dLng = +destLng;
    const jitter = (Math.random() - 0.5) * 0.002;
    const lat = sLat + (dLat - sLat) * progress + jitter;
    const lng = sLng + (dLng - sLng) * progress + jitter;

    try {
      const { data } = await operatorApi.updateGuardianLocation({
        session_id: activeSession.session_id, location: { lat, lng },
      });
      setSimStep(step);
      setLocationHistory(prev => [...prev, { lat, lng }]);
      if (data.alerts?.length) {
        data.alerts.forEach(a => {
          if (a.severity === 'critical') toast.error(a.message);
          else if (a.severity === 'high' || a.severity === 'medium') toast.warning(a.message);
          else toast.info(a.message);
        });
      }
      fetchSession(activeSession.session_id);
    } catch { toast.error('Location update failed'); }
  }, [activeSession, simStep, startLat, startLng, destLat, destLng, fetchSession]);

  const mapCenter = useMemo(() => {
    if (activeSession?.current_location) return [activeSession.current_location.lat, activeSession.current_location.lng];
    return [12.95, 77.61];
  }, [activeSession]);

  const fitPoints = useMemo(() => {
    const pts = [];
    if (activeSession?.current_location) pts.push(activeSession.current_location);
    if (activeSession?.destination) pts.push(activeSession.destination);
    return pts.length >= 2 ? pts : null;
  }, [activeSession]);

  return (
    <div data-testid="guardian-mode-dashboard" className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Users className="w-6 h-6 text-pink-400" />
          <div>
            <h1 className="text-xl font-bold text-slate-100">Guardian Mode</h1>
            <p className="text-xs text-slate-500">Live safety sharing with trusted contacts</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {activeSession?.status === 'active' && (
            <Badge data-testid="gm-active-badge" className="bg-pink-500/20 text-pink-300 border-pink-500/40 animate-pulse">
              <Radio className="w-3 h-3 mr-1" /> SHARING
            </Badge>
          )}
          <Button data-testid="gm-refresh" onClick={() => { fetchGuardians(); fetchActiveSessions(); fetchHistory(); }}
            variant="outline" size="sm" className="border-slate-700 text-slate-300 text-xs">
            <RefreshCw className="w-3 h-3 mr-1" /> Refresh
          </Button>
        </div>
      </div>

      {/* Stats */}
      <div data-testid="gm-stats" className="grid grid-cols-4 gap-2">
        <div className="bg-pink-500/10 border border-slate-700/40 rounded-lg p-2 text-center">
          <div className="text-lg font-bold text-pink-400">{guardians.length}</div>
          <div className="text-[9px] text-slate-500">Guardians</div>
        </div>
        <div className="bg-indigo-500/10 border border-slate-700/40 rounded-lg p-2 text-center">
          <div className="text-lg font-bold text-indigo-400">{activeSessions.length}</div>
          <div className="text-[9px] text-slate-500">Active Sessions</div>
        </div>
        <div className="bg-red-500/10 border border-slate-700/40 rounded-lg p-2 text-center">
          <div className="text-lg font-bold text-red-400">{activeSessions.filter(s => s.risk_level === 'CRITICAL').length}</div>
          <div className="text-[9px] text-slate-500">Critical</div>
        </div>
        <div className="bg-emerald-500/10 border border-slate-700/40 rounded-lg p-2 text-center">
          <div className="text-lg font-bold text-emerald-400">{history.length}</div>
          <div className="text-[9px] text-slate-500">Total Sessions</div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-slate-800/40 rounded-lg p-0.5">
        {['monitor', 'guardians', 'history'].map(t => (
          <button key={t} data-testid={`gm-tab-${t}`} onClick={() => setTab(t)}
            className={`flex-1 py-1.5 text-xs rounded-md transition-colors ${tab === t ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-300'}`}>
            {t === 'monitor' ? 'Live Monitor' : t === 'guardians' ? 'My Guardians' : 'History'}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {tab === 'monitor' && (
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-4" style={{ minHeight: '520px' }}>
          {/* Left */}
          <div className="lg:col-span-2 space-y-3">
            {/* Start Controls */}
            <Card className="bg-slate-900/50 border-slate-700/60">
              <CardContent className="p-3 space-y-2">
                <div className="text-[10px] text-slate-500 font-medium uppercase">Session Controls</div>
                <div className="grid grid-cols-2 gap-2">
                  <div><label className="text-[9px] text-slate-500">Start Lat</label>
                    <input data-testid="gm-start-lat" value={startLat} onChange={e => setStartLat(e.target.value)}
                      className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-slate-300" /></div>
                  <div><label className="text-[9px] text-slate-500">Start Lng</label>
                    <input data-testid="gm-start-lng" value={startLng} onChange={e => setStartLng(e.target.value)}
                      className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-slate-300" /></div>
                  <div><label className="text-[9px] text-slate-500">Dest Lat</label>
                    <input data-testid="gm-dest-lat" value={destLat} onChange={e => setDestLat(e.target.value)}
                      className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-slate-300" /></div>
                  <div><label className="text-[9px] text-slate-500">Dest Lng</label>
                    <input data-testid="gm-dest-lng" value={destLng} onChange={e => setDestLng(e.target.value)}
                      className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-slate-300" /></div>
                </div>
                <div className="flex gap-2">
                  <Button data-testid="gm-start" onClick={handleStart} disabled={loading || activeSession?.status === 'active'}
                    size="sm" className="flex-1 bg-pink-600 hover:bg-pink-700 text-xs">
                    <Play className="w-3 h-3 mr-1" /> Share My Safety
                  </Button>
                  <Button data-testid="gm-stop" onClick={handleStop} disabled={!activeSession || activeSession.status !== 'active'}
                    size="sm" variant="outline" className="border-red-500/50 text-red-400 text-xs hover:bg-red-500/10">
                    <Square className="w-3 h-3 mr-1" /> Stop
                  </Button>
                </div>
                {activeSession?.status === 'active' && (
                  <Button data-testid="gm-step" onClick={handleStep} size="sm" variant="outline"
                    className="w-full border-slate-600 text-slate-300 text-xs">
                    <Navigation className="w-3 h-3 mr-1" /> Simulate Movement (Step {simStep})
                  </Button>
                )}
              </CardContent>
            </Card>

            {/* Status */}
            {activeSession?.status === 'active' ? (
              <Card data-testid="gm-status-panel" className="bg-slate-900/50 border-slate-700/60">
                <CardContent className="p-3 space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="text-[10px] text-slate-500 font-medium uppercase">Live Status</div>
                    <Badge style={{ borderColor: `${ESC_COLORS[activeSession.escalation_level]}60`, color: ESC_COLORS[activeSession.escalation_level], background: `${ESC_COLORS[activeSession.escalation_level]}15` }}
                      className="text-[10px]">{ESC_LABELS[activeSession.escalation_level]}</Badge>
                  </div>
                  <div className="grid grid-cols-3 gap-3 text-center">
                    <div>
                      <div className={`text-lg font-bold ${activeSession.risk_level === 'CRITICAL' ? 'text-red-400' : activeSession.risk_level === 'HIGH' ? 'text-orange-400' : 'text-emerald-400'}`}>{activeSession.risk_level}</div>
                      <div className="text-[9px] text-slate-500">RISK</div>
                    </div>
                    <div>
                      <div className="text-lg font-bold text-slate-200">{activeSession.risk_score?.toFixed(1)}</div>
                      <div className="text-[9px] text-slate-500">SCORE</div>
                    </div>
                    <div>
                      <div className="text-lg font-bold text-cyan-400">{activeSession.eta_minutes ? `${activeSession.eta_minutes}m` : '--'}</div>
                      <div className="text-[9px] text-slate-500">ETA</div>
                    </div>
                  </div>
                  <div className="space-y-1 text-xs">
                    <div className="flex justify-between text-slate-400"><span>Zone</span><span className="text-slate-300 truncate ml-2 max-w-[180px]">{activeSession.zone_name}</span></div>
                    <div className="flex justify-between text-slate-400"><span>Speed</span><span className="text-slate-300">{activeSession.speed_mps?.toFixed(1)} m/s</span></div>
                    <div className="flex justify-between text-slate-400"><span>Duration</span><span className="text-slate-300">{activeSession.duration_minutes?.toFixed(1)} min</span></div>
                    <div className="flex justify-between text-slate-400"><span>Distance</span><span className="text-slate-300">{(activeSession.total_distance_m / 1000).toFixed(2)} km</span></div>
                  </div>
                  {activeSession.safety_check_pending && (
                    <div data-testid="gm-safety-check" className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-2 text-center">
                      <p className="text-xs text-yellow-300 font-medium mb-1">Are you safe?</p>
                      <Button data-testid="gm-ack-safety" size="sm" className="bg-emerald-600 hover:bg-emerald-700 text-xs"
                        onClick={async () => { await operatorApi.acknowledgeGuardianSafety(activeSession.session_id); toast.success('Safety confirmed'); fetchSession(activeSession.session_id); }}>
                        <CheckCircle className="w-3 h-3 mr-1" /> I'm Safe
                      </Button>
                    </div>
                  )}
                </CardContent>
              </Card>
            ) : (
              <Card className="bg-slate-900/50 border-slate-700/60">
                <CardContent className="py-6 text-center">
                  <Users className="w-8 h-8 mx-auto mb-2 text-pink-500/30" />
                  <p className="text-sm text-slate-400">No active session</p>
                  <p className="text-xs text-slate-600">Start sharing to activate Guardian Mode</p>
                </CardContent>
              </Card>
            )}

            {/* Alerts */}
            {activeSession?.alerts?.length > 0 && (
              <Card data-testid="gm-alerts" className="bg-slate-900/50 border-slate-700/60">
                <CardContent className="p-3 space-y-1.5">
                  <div className="text-[10px] text-slate-500 font-medium uppercase">Alerts ({activeSession.alert_count})</div>
                  <div className="space-y-1 max-h-[180px] overflow-y-auto">
                    {[...activeSession.alerts].reverse().map((a, i) => (
                      <div key={i} className={`border rounded-lg p-2 text-xs ${a.severity === 'critical' ? 'bg-red-500/10 border-red-500/30' : a.severity === 'high' ? 'bg-orange-500/10 border-orange-500/30' : 'bg-slate-800/50 border-slate-700/30'}`}>
                        <div className="flex items-center gap-1.5">
                          <AlertTriangle className={`w-3 h-3 ${a.severity === 'critical' ? 'text-red-400' : a.severity === 'high' ? 'text-orange-400' : 'text-yellow-400'}`} />
                          <span className="text-slate-300 font-medium">{a.message}</span>
                        </div>
                        {a.details && <p className="text-[10px] text-slate-500 mt-0.5">{a.details}</p>}
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>

          {/* Right: Map */}
          <div className="lg:col-span-3 relative rounded-lg overflow-hidden border border-slate-700/50" data-testid="gm-map">
            <MapContainer center={mapCenter} zoom={14} style={{ height: '520px', width: '100%', background: '#0f172a' }} zoomControl={false}>
              <TileLayer url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" attribution='&copy; CartoDB' />
              {fitPoints && <FitPoints points={fitPoints} />}
              {activeSession?.current_location && (
                <Marker position={[activeSession.current_location.lat, activeSession.current_location.lng]} icon={userIcon()}>
                  <Popup><div className="text-xs"><p className="font-bold">Current Location</p><p style={{ color: RISK_COLORS[activeSession.risk_level] }}>{activeSession.risk_level} — Score: {activeSession.risk_score}</p></div></Popup>
                </Marker>
              )}
              {activeSession?.destination && (
                <Marker position={[activeSession.destination.lat, activeSession.destination.lng]} icon={destIcon()}>
                  <Popup><div className="text-xs font-bold">Destination</div></Popup>
                </Marker>
              )}
              {locationHistory.length > 1 && (
                <Polyline positions={locationHistory.map(p => [p.lat, p.lng])} pathOptions={{ color: '#ec4899', weight: 3, opacity: 0.7, dashArray: '8 6' }} />
              )}
              {activeSession?.alerts?.filter(a => a.location).map((a, i) => (
                <CircleMarker key={i} center={[a.location.lat, a.location.lng]} radius={7}
                  pathOptions={{ color: a.severity === 'critical' ? '#dc2626' : '#f97316', fillOpacity: 0.3, weight: 2, dashArray: '4 4' }}>
                  <Popup><div className="text-xs"><p className="font-bold">{a.message}</p></div></Popup>
                </CircleMarker>
              ))}
            </MapContainer>
            {activeSession?.status === 'active' && (
              <div className="absolute top-3 right-3 z-[1000] bg-slate-900/85 backdrop-blur-sm border border-slate-700/60 rounded-lg px-3 py-1.5 text-xs flex items-center gap-2">
                <Users className="w-3.5 h-3.5 text-pink-400" />
                <span className="text-slate-300">Guardian Mode</span>
                <span className="text-slate-600">|</span>
                <span style={{ color: RISK_COLORS[activeSession.risk_level] }}>{activeSession.risk_level}</span>
                <span className="text-slate-600">|</span>
                <span className="text-slate-400">{activeSession.eta_minutes ? `ETA ${activeSession.eta_minutes}m` : 'Active'}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {tab === 'guardians' && (
        <Card className="bg-slate-900/50 border-slate-700/60">
          <CardContent className="p-4 space-y-3">
            <div className="text-sm text-slate-300 font-medium">My Guardian Network</div>
            <GuardianList guardians={guardians} onRemove={handleRemoveGuardian} />
            <AddGuardianForm onAdd={handleAddGuardian} />
          </CardContent>
        </Card>
      )}

      {tab === 'history' && (
        <Card data-testid="gm-history" className="bg-slate-900/50 border-slate-700/60">
          <CardContent className="p-3">
            <div className="text-[10px] text-slate-500 font-medium uppercase mb-2">Session History</div>
            {history.length === 0 ? (
              <p className="text-xs text-slate-500 text-center py-4">No sessions yet</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-slate-500 border-b border-slate-700/40">
                      <th className="text-left py-1.5 px-2">Started</th>
                      <th className="text-left py-1.5 px-2">Status</th>
                      <th className="text-center py-1.5 px-2">Duration</th>
                      <th className="text-center py-1.5 px-2">Risk</th>
                      <th className="text-center py-1.5 px-2">Distance</th>
                      <th className="text-center py-1.5 px-2">Escalation</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map(s => (
                      <tr key={s.session_id} className="border-b border-slate-800/40">
                        <td className="py-1.5 px-2 text-slate-300">{new Date(s.started_at).toLocaleString()}</td>
                        <td className="py-1.5 px-2">
                          <Badge className={`text-[9px] ${s.status === 'active' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-slate-700/50 text-slate-400'}`}>{s.status}</Badge>
                        </td>
                        <td className="py-1.5 px-2 text-center text-slate-400">{s.duration_minutes?.toFixed(0)}m</td>
                        <td className="py-1.5 px-2 text-center"><span style={{ color: RISK_COLORS[s.risk_level] }}>{s.risk_level}</span></td>
                        <td className="py-1.5 px-2 text-center text-slate-400">{(s.total_distance_m / 1000).toFixed(2)}km</td>
                        <td className="py-1.5 px-2 text-center"><span style={{ color: ESC_COLORS[s.escalation_level] }}>{ESC_LABELS[s.escalation_level]}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Active Sessions Table (Operator View) */}
      {activeSessions.length > 0 && tab === 'monitor' && (
        <Card data-testid="gm-active-sessions" className="bg-slate-900/50 border-slate-700/60">
          <CardContent className="p-3">
            <div className="text-[10px] text-slate-500 font-medium uppercase mb-2">All Active Sessions (Operator View)</div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-slate-500 border-b border-slate-700/40">
                    <th className="text-left py-1.5 px-2">User</th>
                    <th className="text-left py-1.5 px-2">Risk</th>
                    <th className="text-left py-1.5 px-2">Zone</th>
                    <th className="text-center py-1.5 px-2">Duration</th>
                    <th className="text-center py-1.5 px-2">Escalation</th>
                  </tr>
                </thead>
                <tbody>
                  {activeSessions.map(s => (
                    <tr key={s.session_id} className="border-b border-slate-800/40 hover:bg-slate-800/20 cursor-pointer"
                      onClick={() => fetchSession(s.session_id)}>
                      <td className="py-1.5 px-2 text-slate-300">{s.user_id.slice(0, 8)}...</td>
                      <td className="py-1.5 px-2"><span style={{ color: RISK_COLORS[s.risk_level] }} className="font-medium">{s.risk_level}</span></td>
                      <td className="py-1.5 px-2 text-slate-400 truncate max-w-[120px]">{s.zone_name}</td>
                      <td className="py-1.5 px-2 text-center text-slate-400">{s.duration_minutes?.toFixed(0)}m</td>
                      <td className="py-1.5 px-2 text-center"><span style={{ color: ESC_COLORS[s.escalation_level] }}>{ESC_LABELS[s.escalation_level]}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
