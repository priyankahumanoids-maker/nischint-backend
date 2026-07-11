import React, { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polyline, CircleMarker, useMap } from 'react-leaflet';
import L from 'leaflet';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { operatorApi } from '../api';
import { toast } from 'sonner';
import {
  Moon, Shield, AlertTriangle, MapPin, Navigation, Play, Square,
  RefreshCw, Clock, Activity, Eye, Zap, ChevronRight, Radio,
  CheckCircle, XCircle, User, Route, Timer
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
    className: 'ng-user-icon',
    html: '<div style="width:20px;height:20px;background:#3b82f6;border:3px solid white;border-radius:50%;box-shadow:0 0 12px rgba(59,130,246,0.6)"></div>',
    iconSize: [20, 20], iconAnchor: [10, 10],
  });
}

function destIcon() {
  return L.divIcon({
    className: 'ng-dest-icon',
    html: '<div style="width:16px;height:16px;background:#f43f5e;border:2px solid white;border-radius:3px;box-shadow:0 0 8px rgba(244,63,94,0.5)"></div>',
    iconSize: [16, 16], iconAnchor: [8, 8],
  });
}

function FitToPoints({ points }) {
  const map = useMap();
  const doneRef = useRef(false);
  useEffect(() => {
    if (doneRef.current || !points?.length) return;
    doneRef.current = true;
    map.fitBounds(points.map(p => [p.lat, p.lng]), { padding: [50, 50], maxZoom: 15 });
  }, [points, map]);
  return null;
}

// Alert type icons and colors
const ALERT_CONFIG = {
  zone_escalation: { icon: AlertTriangle, color: 'text-red-400', bg: 'bg-red-500/10 border-red-500/30' },
  route_deviation: { icon: Route, color: 'text-orange-400', bg: 'bg-orange-500/10 border-orange-500/30' },
  idle_detected: { icon: Timer, color: 'text-yellow-400', bg: 'bg-yellow-500/10 border-yellow-500/30' },
  no_response_escalation: { icon: XCircle, color: 'text-red-400', bg: 'bg-red-500/10 border-red-500/30' },
  arrived: { icon: CheckCircle, color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/30' },
  safety_confirmed: { icon: Shield, color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/30' },
};

function AlertItem({ alert }) {
  const cfg = ALERT_CONFIG[alert.type] || ALERT_CONFIG.zone_escalation;
  const Icon = cfg.icon;
  const time = alert.timestamp ? new Date(alert.timestamp).toLocaleTimeString() : '';
  return (
    <div data-testid={`ng-alert-${alert.type}`} className={`border rounded-lg p-2.5 ${cfg.bg} text-xs`}>
      <div className="flex items-center gap-2 mb-1">
        <Icon className={`w-3.5 h-3.5 ${cfg.color}`} />
        <span className="font-medium text-slate-200">{alert.message}</span>
        <span className="ml-auto text-[9px] text-slate-500">{time}</span>
      </div>
      <p className="text-slate-400 text-[10px]">{alert.details}</p>
      {alert.recommendation && <p className="text-indigo-400 text-[10px] mt-0.5">{alert.recommendation}</p>}
    </div>
  );
}

function StatusBadge({ label, value, color }) {
  return (
    <div className="text-center">
      <div className={`text-lg font-bold ${color}`}>{value}</div>
      <div className="text-[9px] text-slate-500 uppercase">{label}</div>
    </div>
  );
}

// Simulation panel for operator testing
function SimulationPanel({ onSimulate, simulating, simStep }) {
  const [startLat, setStartLat] = useState('12.971');
  const [startLng, setStartLng] = useState('77.594');
  const [destLat, setDestLat] = useState('12.935');
  const [destLng, setDestLng] = useState('77.624');

  return (
    <Card className="bg-slate-900/50 border-slate-700/60">
      <CardContent className="p-3 space-y-2">
        <div className="text-[10px] text-slate-500 font-medium uppercase">Simulation Controls</div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[9px] text-slate-500">Start Lat</label>
            <input data-testid="ng-sim-start-lat" value={startLat} onChange={e => setStartLat(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-slate-300" />
          </div>
          <div>
            <label className="text-[9px] text-slate-500">Start Lng</label>
            <input data-testid="ng-sim-start-lng" value={startLng} onChange={e => setStartLng(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-slate-300" />
          </div>
          <div>
            <label className="text-[9px] text-slate-500">Dest Lat</label>
            <input data-testid="ng-sim-dest-lat" value={destLat} onChange={e => setDestLat(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-slate-300" />
          </div>
          <div>
            <label className="text-[9px] text-slate-500">Dest Lng</label>
            <input data-testid="ng-sim-dest-lng" value={destLng} onChange={e => setDestLng(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-slate-300" />
          </div>
        </div>
        <div className="flex gap-2">
          <Button
            data-testid="ng-sim-start"
            onClick={() => onSimulate('start', { startLat: +startLat, startLng: +startLng, destLat: +destLat, destLng: +destLng })}
            disabled={simulating}
            size="sm" className="flex-1 bg-indigo-600 hover:bg-indigo-700 text-xs"
          >
            <Play className="w-3 h-3 mr-1" /> Start Guardian
          </Button>
          <Button
            data-testid="ng-sim-stop"
            onClick={() => onSimulate('stop', {})}
            disabled={!simulating}
            size="sm" variant="outline" className="border-red-500/50 text-red-400 text-xs hover:bg-red-500/10"
          >
            <Square className="w-3 h-3 mr-1" /> Stop
          </Button>
        </div>
        {simulating && (
          <div className="flex items-center gap-2">
            <Button
              data-testid="ng-sim-step"
              onClick={() => onSimulate('step', {})}
              size="sm" variant="outline" className="flex-1 border-slate-600 text-slate-300 text-xs"
            >
              <Navigation className="w-3 h-3 mr-1" /> Simulate Movement (Step {simStep})
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function NightGuardianDashboard() {
  const [status, setStatus] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [simulating, setSimulating] = useState(false);
  const [simStep, setSimStep] = useState(0);
  const [simUserId] = useState('sim-night-user');
  const [simCoords, setSimCoords] = useState(null);
  const [locationHistory, setLocationHistory] = useState([]);
  const [lastUpdate, setLastUpdate] = useState(null);

  const fetchSessions = useCallback(async () => {
    try {
      const { data } = await operatorApi.getNightGuardianSessions();
      setSessions(data.sessions || []);
    } catch { /* ignore */ }
  }, []);

  const fetchStatus = useCallback(async (uid) => {
    try {
      const { data } = await operatorApi.getNightGuardianStatus(uid || simUserId);
      setStatus(data);
    } catch { /* ignore */ }
  }, [simUserId]);

  useEffect(() => { fetchSessions(); }, [fetchSessions]);

  // Polling when simulating
  useEffect(() => {
    if (!simulating) return;
    const iv = setInterval(() => {
      fetchStatus(simUserId);
      fetchSessions();
    }, 5000);
    return () => clearInterval(iv);
  }, [simulating, fetchStatus, fetchSessions, simUserId]);

  const handleSimulate = useCallback(async (action, params) => {
    try {
      if (action === 'start') {
        setLoading(true);
        const { data } = await operatorApi.startNightGuardian({
          user_id: simUserId,
          location: { lat: params.startLat, lng: params.startLng },
          destination: { lat: params.destLat, lng: params.destLng },
        });
        setSimulating(true);
        setSimStep(0);
        setSimCoords({ start: { lat: params.startLat, lng: params.startLng }, dest: { lat: params.destLat, lng: params.destLng } });
        setLocationHistory([{ lat: params.startLat, lng: params.startLng }]);
        toast.success('Night Guardian activated');
        await fetchStatus(simUserId);
        await fetchSessions();
        setLoading(false);
      } else if (action === 'stop') {
        const { data } = await operatorApi.stopNightGuardian({ user_id: simUserId });
        setSimulating(false);
        setStatus(null);
        setSimStep(0);
        setLocationHistory([]);
        toast.info(`Guardian stopped. Duration: ${data.duration_minutes}min, Alerts: ${data.alerts_triggered}`);
        await fetchSessions();
      } else if (action === 'step') {
        if (!simCoords) return;
        const step = simStep + 1;
        const totalSteps = 12;
        const progress = Math.min(step / totalSteps, 1);
        // Interpolate between start and dest with some jitter
        const jitter = (Math.random() - 0.5) * 0.002;
        const lat = simCoords.start.lat + (simCoords.dest.lat - simCoords.start.lat) * progress + jitter;
        const lng = simCoords.start.lng + (simCoords.dest.lng - simCoords.start.lng) * progress + jitter;

        const { data } = await operatorApi.updateNightGuardianLocation({
          user_id: simUserId,
          location: { lat, lng },
        });
        setSimStep(step);
        setLastUpdate(data);
        setLocationHistory(prev => [...prev, { lat, lng }]);

        if (data.alerts?.length) {
          data.alerts.forEach(a => {
            if (a.severity === 'critical') toast.error(a.message);
            else if (a.severity === 'high' || a.severity === 'medium') toast.warning(a.message);
            else toast.info(a.message);
          });
        }
        await fetchStatus(simUserId);
      }
    } catch (e) {
      toast.error('Operation failed');
      setLoading(false);
    }
  }, [simUserId, simStep, simCoords, fetchStatus, fetchSessions]);

  const mapCenter = useMemo(() => {
    if (status?.current_location) return [status.current_location.lat, status.current_location.lng];
    return [12.97, 77.59];
  }, [status]);

  const fitPoints = useMemo(() => {
    const pts = [];
    if (status?.current_location) pts.push(status.current_location);
    if (status?.destination) pts.push(status.destination);
    return pts.length >= 2 ? pts : null;
  }, [status]);

  const escColor = ESC_COLORS[status?.escalation_level] || ESC_COLORS.none;
  const escLabel = ESC_LABELS[status?.escalation_level] || 'Normal';

  return (
    <div data-testid="night-guardian-dashboard" className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Moon className="w-6 h-6 text-indigo-400" />
          <div>
            <h1 className="text-xl font-bold text-slate-100">Night Safety Guardian</h1>
            <p className="text-xs text-slate-500">Active safety monitoring during night journeys</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {simulating && (
            <Badge data-testid="ng-active-badge" className="bg-indigo-500/20 text-indigo-300 border-indigo-500/40 animate-pulse">
              <Radio className="w-3 h-3 mr-1" /> MONITORING
            </Badge>
          )}
          <Button
            data-testid="ng-refresh"
            onClick={() => { fetchSessions(); if (simulating) fetchStatus(simUserId); }}
            variant="outline" size="sm" className="border-slate-700 text-slate-300 text-xs"
          >
            <RefreshCw className="w-3 h-3 mr-1" /> Refresh
          </Button>
        </div>
      </div>

      {/* Active Sessions Summary */}
      <div data-testid="ng-sessions-summary" className="grid grid-cols-4 gap-2">
        <div className="bg-indigo-500/10 border border-slate-700/40 rounded-lg p-2 text-center">
          <div className="text-lg font-bold text-indigo-400">{sessions.length}</div>
          <div className="text-[9px] text-slate-500">Active Sessions</div>
        </div>
        <div className="bg-red-500/10 border border-slate-700/40 rounded-lg p-2 text-center">
          <div className="text-lg font-bold text-red-400">{sessions.filter(s => s.risk_level === 'CRITICAL').length}</div>
          <div className="text-[9px] text-slate-500">Critical</div>
        </div>
        <div className="bg-orange-500/10 border border-slate-700/40 rounded-lg p-2 text-center">
          <div className="text-lg font-bold text-orange-400">{sessions.filter(s => s.route_deviated).length}</div>
          <div className="text-[9px] text-slate-500">Route Deviated</div>
        </div>
        <div className="bg-yellow-500/10 border border-slate-700/40 rounded-lg p-2 text-center">
          <div className="text-lg font-bold text-yellow-400">{sessions.filter(s => s.is_idle).length}</div>
          <div className="text-[9px] text-slate-500">Idle</div>
        </div>
      </div>

      {/* Main Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4" style={{ minHeight: '520px' }}>
        {/* Left Panel */}
        <div className="lg:col-span-2 space-y-3">
          {/* Simulation Controls */}
          <SimulationPanel onSimulate={handleSimulate} simulating={simulating} simStep={simStep} />

          {/* Status Panel */}
          {status?.active ? (
            <Card data-testid="ng-status-panel" className="bg-slate-900/50 border-slate-700/60">
              <CardContent className="p-3 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="text-[10px] text-slate-500 font-medium uppercase">Guardian Status</div>
                  <Badge
                    data-testid="ng-escalation-badge"
                    style={{ borderColor: `${escColor}60`, background: `${escColor}15`, color: escColor }}
                    className="text-[10px]"
                  >
                    {escLabel}
                  </Badge>
                </div>

                <div className="grid grid-cols-3 gap-3">
                  <StatusBadge
                    label="Risk"
                    value={status.current_zone?.risk_level || 'N/A'}
                    color={`${status.current_zone?.risk_level === 'CRITICAL' ? 'text-red-400' : status.current_zone?.risk_level === 'HIGH' ? 'text-orange-400' : status.current_zone?.risk_level === 'LOW' ? 'text-yellow-400' : 'text-emerald-400'}`}
                  />
                  <StatusBadge label="Score" value={status.current_zone?.risk_score?.toFixed(1) || '0'} color="text-slate-200" />
                  <StatusBadge label="ETA" value={status.eta_minutes ? `${status.eta_minutes}m` : '--'} color="text-cyan-400" />
                </div>

                <div className="space-y-1 text-xs">
                  <div className="flex justify-between text-slate-400">
                    <span>Zone</span>
                    <span className="text-slate-300 truncate ml-2 max-w-[180px]">{status.current_zone?.zone_name}</span>
                  </div>
                  <div className="flex justify-between text-slate-400">
                    <span>Speed</span>
                    <span className="text-slate-300">{status.speed_mps?.toFixed(1)} m/s</span>
                  </div>
                  <div className="flex justify-between text-slate-400">
                    <span>Duration</span>
                    <span className="text-slate-300">{status.duration_minutes?.toFixed(1)} min</span>
                  </div>
                  <div className="flex justify-between text-slate-400">
                    <span>Distance</span>
                    <span className="text-slate-300">{(status.total_distance_m / 1000).toFixed(2)} km</span>
                  </div>
                  <div className="flex justify-between text-slate-400">
                    <span>Updates</span>
                    <span className="text-slate-300">{status.location_updates}</span>
                  </div>
                  {status.is_idle && (
                    <div className="flex justify-between text-yellow-400">
                      <span>Idle</span>
                      <span>{status.idle_duration_s}s</span>
                    </div>
                  )}
                  {status.route_deviated && (
                    <div className="flex justify-between text-orange-400">
                      <span>Route Deviation</span>
                      <span>{status.route_deviation_m?.toFixed(0)}m</span>
                    </div>
                  )}
                </div>

                {status.safety_check_pending && (
                  <div data-testid="ng-safety-check" className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-2 text-center">
                    <p className="text-xs text-yellow-300 font-medium mb-1">Are you safe?</p>
                    <Button
                      data-testid="ng-acknowledge-safety"
                      onClick={async () => {
                        await operatorApi.acknowledgeNightGuardianSafety();
                        toast.success('Safety confirmed');
                        fetchStatus(simUserId);
                      }}
                      size="sm" className="bg-emerald-600 hover:bg-emerald-700 text-xs"
                    >
                      <CheckCircle className="w-3 h-3 mr-1" /> I'm Safe
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          ) : (
            <Card className="bg-slate-900/50 border-slate-700/60">
              <CardContent className="py-8 text-center">
                <Moon className="w-8 h-8 mx-auto mb-2 text-indigo-500/30" />
                <p className="text-sm text-slate-400">No active guardian session</p>
                <p className="text-xs text-slate-600">Start a simulation to test Night Guardian</p>
              </CardContent>
            </Card>
          )}

          {/* Alerts Log */}
          {status?.alerts?.length > 0 && (
            <Card data-testid="ng-alerts-panel" className="bg-slate-900/50 border-slate-700/60">
              <CardContent className="p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <div className="text-[10px] text-slate-500 font-medium uppercase">Alert Log ({status.alert_count})</div>
                </div>
                <div className="space-y-1.5 max-h-[200px] overflow-y-auto">
                  {[...status.alerts].reverse().map((alert, i) => (
                    <AlertItem key={i} alert={alert} />
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>

        {/* Right: Map */}
        <div className="lg:col-span-3 relative rounded-lg overflow-hidden border border-slate-700/50" data-testid="ng-map">
          <MapContainer
            center={mapCenter}
            zoom={14}
            style={{ height: '520px', width: '100%', background: '#0f172a' }}
            zoomControl={false}
          >
            <TileLayer
              url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
              attribution='&copy; CartoDB'
            />

            {fitPoints && <FitToPoints points={fitPoints} />}

            {/* User marker */}
            {status?.current_location && (
              <Marker position={[status.current_location.lat, status.current_location.lng]} icon={userIcon()}>
                <Popup>
                  <div className="text-xs">
                    <p className="font-bold">Current Location</p>
                    <p style={{ color: RISK_COLORS[status.current_zone?.risk_level] }}>
                      {status.current_zone?.risk_level} — Score: {status.current_zone?.risk_score}
                    </p>
                    <p>Speed: {status.speed_mps?.toFixed(1)} m/s</p>
                  </div>
                </Popup>
              </Marker>
            )}

            {/* Destination marker */}
            {status?.destination && (
              <Marker position={[status.destination.lat, status.destination.lng]} icon={destIcon()}>
                <Popup>
                  <div className="text-xs">
                    <p className="font-bold">Destination</p>
                    {status.eta_minutes && <p>ETA: {status.eta_minutes} min</p>}
                  </div>
                </Popup>
              </Marker>
            )}

            {/* Location history trail */}
            {locationHistory.length > 1 && (
              <Polyline
                positions={locationHistory.map(p => [p.lat, p.lng])}
                pathOptions={{ color: '#6366f1', weight: 3, opacity: 0.7, dashArray: '8 6' }}
              />
            )}

            {/* Alert markers */}
            {status?.alerts?.filter(a => a.location && (a.type === 'zone_escalation' || a.type === 'idle_detected')).map((a, i) => (
              <CircleMarker
                key={i}
                center={[a.location.lat, a.location.lng]}
                radius={8}
                pathOptions={{
                  color: a.severity === 'critical' ? '#dc2626' : a.severity === 'high' ? '#f97316' : '#eab308',
                  fillOpacity: 0.3, weight: 2, dashArray: '4 4',
                }}
              >
                <Popup><div className="text-xs"><p className="font-bold">{a.message}</p><p>{a.details}</p></div></Popup>
              </CircleMarker>
            ))}
          </MapContainer>

          {/* Map overlay */}
          {status?.active && (
            <div className="absolute top-3 right-3 z-[1000] bg-slate-900/85 backdrop-blur-sm border border-slate-700/60 rounded-lg px-3 py-1.5 text-xs flex items-center gap-2">
              <Moon className="w-3.5 h-3.5 text-indigo-400" />
              <span className="text-slate-300">Night Guardian</span>
              <span className="text-slate-600">|</span>
              <span style={{ color: RISK_COLORS[status.current_zone?.risk_level] }}>{status.current_zone?.risk_level}</span>
              <span className="text-slate-600">|</span>
              <span className="text-slate-400">{status.eta_minutes ? `ETA ${status.eta_minutes}m` : 'No ETA'}</span>
            </div>
          )}

          {/* Legend */}
          <div className="absolute bottom-4 left-4 z-[1000] bg-slate-900/90 backdrop-blur-sm border border-slate-700/60 rounded-lg p-3 text-xs">
            <div className="text-slate-400 font-medium mb-1.5">Escalation Levels</div>
            {Object.entries(ESC_LABELS).map(([k, label]) => (
              <div key={k} className="flex items-center gap-2 mb-1">
                <div className="w-3 h-3 rounded-full" style={{ background: ESC_COLORS[k] }} />
                <span className="text-slate-300">{label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Active Sessions Table */}
      {sessions.length > 0 && (
        <Card data-testid="ng-sessions-table" className="bg-slate-900/50 border-slate-700/60">
          <CardContent className="p-3">
            <div className="text-[10px] text-slate-500 font-medium uppercase mb-2">Active Guardian Sessions</div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-slate-500 border-b border-slate-700/40">
                    <th className="text-left py-1.5 px-2">User</th>
                    <th className="text-left py-1.5 px-2">Risk</th>
                    <th className="text-left py-1.5 px-2">Zone</th>
                    <th className="text-center py-1.5 px-2">Duration</th>
                    <th className="text-center py-1.5 px-2">Escalation</th>
                    <th className="text-center py-1.5 px-2">Alerts</th>
                    <th className="text-center py-1.5 px-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.map((s) => (
                    <tr key={s.user_id} className="border-b border-slate-800/40 hover:bg-slate-800/20">
                      <td className="py-1.5 px-2 text-slate-300">{s.user_id}</td>
                      <td className="py-1.5 px-2">
                        <span style={{ color: RISK_COLORS[s.risk_level] }} className="font-medium">{s.risk_level}</span>
                      </td>
                      <td className="py-1.5 px-2 text-slate-400 truncate max-w-[120px]">{s.zone_name}</td>
                      <td className="py-1.5 px-2 text-center text-slate-400">{s.duration_minutes?.toFixed(0)}m</td>
                      <td className="py-1.5 px-2 text-center">
                        <span style={{ color: ESC_COLORS[s.escalation_level] }}>{ESC_LABELS[s.escalation_level]}</span>
                      </td>
                      <td className="py-1.5 px-2 text-center text-slate-300">{s.alert_count}</td>
                      <td className="py-1.5 px-2 text-center">
                        {s.is_idle ? <Badge className="bg-yellow-500/20 text-yellow-300 text-[9px]">Idle</Badge>
                          : s.route_deviated ? <Badge className="bg-orange-500/20 text-orange-300 text-[9px]">Deviated</Badge>
                          : <Badge className="bg-emerald-500/20 text-emerald-300 text-[9px]">Moving</Badge>}
                      </td>
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
