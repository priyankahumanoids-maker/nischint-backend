import React, { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import { MapContainer, TileLayer, Polyline, Marker, Popup, CircleMarker, useMap } from 'react-leaflet';
import L from 'leaflet';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { operatorApi } from '../api';
import { toast } from 'sonner';
import {
  AlertTriangle, Shield, Eye, MapPin, Navigation, RefreshCw,
  Zap, ChevronRight, Clock, Activity, Radio, Target
} from 'lucide-react';

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

const RISK_COLORS = { CRITICAL: '#dc2626', HIGH: '#f97316', LOW: '#eab308', SAFE: '#22c55e' };
const SEV_COLORS = { CRITICAL: '#dc2626', HIGH: '#f97316', LOW: '#eab308' };

function userIcon() {
  return L.divIcon({
    className: 'pa-user',
    html: '<div style="width:18px;height:18px;background:#3b82f6;border:3px solid white;border-radius:50%;box-shadow:0 0 12px rgba(59,130,246,0.6)"></div>',
    iconSize: [18, 18], iconAnchor: [9, 9],
  });
}

function dangerIcon() {
  return L.divIcon({
    className: 'pa-danger',
    html: '<div style="width:24px;height:24px;background:#dc262680;border:2px solid #dc2626;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:14px;color:#dc2626;font-weight:bold">!</div>',
    iconSize: [24, 24], iconAnchor: [12, 12],
  });
}

function FitBounds({ points }) {
  const map = useMap();
  const done = useRef(false);
  useEffect(() => {
    if (done.current || !points?.length) return;
    done.current = true;
    map.fitBounds(points, { padding: [50, 50], maxZoom: 15 });
  }, [points, map]);
  return null;
}

function AlertBanner({ prediction }) {
  if (!prediction?.alert) return null;
  const sev = prediction.severity;
  const color = SEV_COLORS[sev] || '#f97316';

  return (
    <div
      data-testid="pa-alert-banner"
      className="rounded-lg p-3 border-2 animate-pulse"
      style={{ borderColor: color, background: `${color}15` }}
    >
      <div className="flex items-center gap-2 mb-1.5">
        <AlertTriangle className="w-5 h-5" style={{ color }} />
        <span className="text-sm font-bold" style={{ color }}>{prediction.message}</span>
      </div>
      <p className="text-xs text-slate-400 mb-2">{prediction.recommendation}</p>
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <div className="text-lg font-bold" style={{ color }}>{prediction.distance_to_risk}m</div>
          <div className="text-[9px] text-slate-500">DISTANCE</div>
        </div>
        <div>
          <div className="text-lg font-bold" style={{ color }}>{prediction.risk_score}</div>
          <div className="text-[9px] text-slate-500">RISK SCORE</div>
        </div>
        <div>
          <div className="text-lg font-bold text-slate-200">{prediction.danger_zones_ahead}</div>
          <div className="text-[9px] text-slate-500">DANGER ZONES</div>
        </div>
      </div>
      {prediction.danger_segments?.length > 0 && (
        <div className="mt-2 space-y-1">
          {prediction.danger_segments.map((s, i) => (
            <div key={i} className="flex items-center gap-2 text-[10px]">
              <div className="w-2.5 h-2.5 rounded-full" style={{ background: RISK_COLORS[s.risk_level] }} />
              <span className="text-slate-400">{s.risk_level} zone at {s.distance}m</span>
              <span className="text-slate-500">(score {s.risk})</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SafeAheadBanner({ prediction }) {
  if (!prediction || prediction.alert) return null;
  return (
    <div data-testid="pa-safe-banner" className="rounded-lg p-3 border border-emerald-500/30 bg-emerald-500/10">
      <div className="flex items-center gap-2">
        <Shield className="w-4 h-4 text-emerald-400" />
        <span className="text-sm text-emerald-300 font-medium">{prediction.message || 'Route ahead appears safe'}</span>
      </div>
      <div className="flex items-center gap-3 mt-1 text-[10px] text-slate-500">
        <span>Mode: {prediction.mode}</span>
        <span>Lookahead: {prediction.lookahead_m}m</span>
        <span>Period: {prediction.time_period}</span>
      </div>
    </div>
  );
}

export default function PredictiveAlertDashboard() {
  const [prediction, setPrediction] = useState(null);
  const [loading, setLoading] = useState(false);
  const [userLat, setUserLat] = useState('12.968');
  const [userLng, setUserLng] = useState('77.590');
  const [destLat, setDestLat] = useState('12.975');
  const [destLng, setDestLng] = useState('77.585');
  const [speed, setSpeed] = useState('1.5');
  const [timeMode, setTimeMode] = useState('');
  const [routeCoords, setRouteCoords] = useState(null);

  const handleEvaluate = useCallback(async () => {
    setLoading(true);
    try {
      // First generate route coords if we have origin+dest
      let coords = routeCoords;
      if (!coords) {
        // Generate a simple interpolated route
        const steps = 20;
        coords = [];
        for (let i = 0; i <= steps; i++) {
          const t = i / steps;
          coords.push([
            +userLng + (+destLng - +userLng) * t,
            +userLat + (+destLat - +userLat) * t,
          ]);
        }
        setRouteCoords(coords);
      }

      const payload = {
        location: { lat: +userLat, lng: +userLng },
        route_coords: coords,
        speed: +speed,
      };
      if (timeMode) payload.timestamp = `2026-03-07T${timeMode}:00+00:00`;

      const { data } = await operatorApi.evaluatePredictiveAlert(payload);
      setPrediction(data);

      if (data.alert) {
        if (data.severity === 'CRITICAL') toast.error(data.message);
        else if (data.severity === 'HIGH') toast.warning(data.message);
        else toast.info(data.message);
      } else {
        toast.success(data.message || 'Route ahead is safe');
      }
    } catch {
      toast.error('Prediction failed');
    } finally {
      setLoading(false);
    }
  }, [userLat, userLng, destLat, destLng, speed, timeMode, routeCoords]);

  const handleNewRoute = useCallback(() => {
    setRouteCoords(null);
    setPrediction(null);
  }, []);

  const mapCenter = useMemo(() => [+userLat, +userLng], [userLat, userLng]);
  const fitPoints = useMemo(() => {
    const pts = [[+userLat, +userLng], [+destLat, +destLng]];
    if (prediction?.danger_segments) {
      prediction.danger_segments.forEach(s => pts.push([s.lat, s.lng]));
    }
    return pts;
  }, [userLat, userLng, destLat, destLng, prediction]);

  return (
    <div data-testid="predictive-alert-dashboard" className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Zap className="w-6 h-6 text-amber-400" />
          <div>
            <h1 className="text-xl font-bold text-slate-100">Predictive Danger Alerts</h1>
            <p className="text-xs text-slate-500">AI-powered risk prediction for upcoming route segments</p>
          </div>
        </div>
        {prediction?.alert && (
          <Badge data-testid="pa-severity-badge"
            style={{ borderColor: `${SEV_COLORS[prediction.severity]}60`, color: SEV_COLORS[prediction.severity], background: `${SEV_COLORS[prediction.severity]}15` }}
            className="text-xs animate-pulse">
            <AlertTriangle className="w-3 h-3 mr-1" /> {prediction.severity} RISK AHEAD
          </Badge>
        )}
      </div>

      {/* Controls */}
      <Card className="bg-slate-900/50 border-slate-700/60">
        <CardContent className="p-3">
          <div className="grid grid-cols-2 lg:grid-cols-7 gap-2 items-end">
            <div>
              <label className="text-[9px] text-slate-500 uppercase">Your Lat</label>
              <input data-testid="pa-user-lat" value={userLat} onChange={e => { setUserLat(e.target.value); handleNewRoute(); }}
                className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-300" />
            </div>
            <div>
              <label className="text-[9px] text-slate-500 uppercase">Your Lng</label>
              <input data-testid="pa-user-lng" value={userLng} onChange={e => { setUserLng(e.target.value); handleNewRoute(); }}
                className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-300" />
            </div>
            <div>
              <label className="text-[9px] text-slate-500 uppercase">Dest Lat</label>
              <input data-testid="pa-dest-lat" value={destLat} onChange={e => { setDestLat(e.target.value); handleNewRoute(); }}
                className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-300" />
            </div>
            <div>
              <label className="text-[9px] text-slate-500 uppercase">Dest Lng</label>
              <input data-testid="pa-dest-lng" value={destLng} onChange={e => { setDestLng(e.target.value); handleNewRoute(); }}
                className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-300" />
            </div>
            <div>
              <label className="text-[9px] text-slate-500 uppercase">Speed (m/s)</label>
              <input data-testid="pa-speed" value={speed} onChange={e => setSpeed(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-300" />
            </div>
            <div>
              <label className="text-[9px] text-slate-500 uppercase">Time</label>
              <select data-testid="pa-time-mode" value={timeMode} onChange={e => setTimeMode(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-300">
                <option value="">Now</option>
                <option value="10:00">Day (10:00)</option>
                <option value="22:00">Night (22:00)</option>
                <option value="02:00">Late Night (02:00)</option>
              </select>
            </div>
            <Button data-testid="pa-evaluate" onClick={handleEvaluate} disabled={loading}
              size="sm" className="bg-amber-600 hover:bg-amber-700 text-xs">
              {loading ? <RefreshCw className="w-3 h-3 mr-1 animate-spin" /> : <Eye className="w-3 h-3 mr-1" />}
              Predict
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Main Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4" style={{ minHeight: '480px' }}>
        {/* Left: Results */}
        <div className="lg:col-span-2 space-y-3">
          {prediction?.alert ? (
            <AlertBanner prediction={prediction} />
          ) : prediction ? (
            <SafeAheadBanner prediction={prediction} />
          ) : (
            <Card className="bg-slate-900/50 border-slate-700/60">
              <CardContent className="py-8 text-center">
                <Zap className="w-8 h-8 mx-auto mb-2 text-amber-500/30" />
                <p className="text-sm text-slate-400">Enter route and click Predict</p>
                <p className="text-xs text-slate-600">AI evaluates risk ahead on your route</p>
              </CardContent>
            </Card>
          )}

          {/* Info Panel */}
          {prediction && (
            <Card data-testid="pa-info-panel" className="bg-slate-900/50 border-slate-700/60">
              <CardContent className="p-3 space-y-1.5">
                <div className="text-[10px] text-slate-500 font-medium uppercase">Prediction Details</div>
                <div className="space-y-1 text-xs">
                  <div className="flex justify-between text-slate-400"><span>Travel Mode</span><span className="text-slate-300 capitalize">{prediction.mode}</span></div>
                  <div className="flex justify-between text-slate-400"><span>Lookahead</span><span className="text-slate-300">{prediction.lookahead_m}m</span></div>
                  <div className="flex justify-between text-slate-400"><span>Time Period</span><span className="text-slate-300 capitalize">{prediction.time_period}</span></div>
                  {prediction.alert && (
                    <>
                      <div className="flex justify-between text-slate-400"><span>Nearest Danger</span><span style={{ color: RISK_COLORS[prediction.risk_level] }}>{prediction.distance_to_risk}m ({prediction.risk_level})</span></div>
                      <div className="flex justify-between text-slate-400"><span>Zone ID</span><span className="text-slate-300 text-[10px]">{prediction.zone_id}</span></div>
                    </>
                  )}
                  {prediction.cooldown_remaining_s && (
                    <div className="flex justify-between text-yellow-400"><span>Cooldown</span><span>{prediction.cooldown_remaining_s}s remaining</span></div>
                  )}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Mode Legend */}
          <Card className="bg-slate-900/50 border-slate-700/60">
            <CardContent className="p-3">
              <div className="text-[10px] text-slate-500 font-medium uppercase mb-1.5">Speed-Adaptive Lookahead</div>
              <div className="space-y-1">
                {[['Walking', '<2 m/s', '250m'], ['Bike', '2-6 m/s', '350m'], ['Vehicle', '>6 m/s', '550m']].map(([mode, range, dist]) => (
                  <div key={mode} className="flex items-center justify-between text-xs">
                    <span className="text-slate-400">{mode} ({range})</span>
                    <span className="text-slate-300">{dist}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Right: Map */}
        <div className="lg:col-span-3 relative rounded-lg overflow-hidden border border-slate-700/50" data-testid="pa-map">
          <MapContainer center={mapCenter} zoom={15} style={{ height: '480px', width: '100%', background: '#0f172a' }} zoomControl={false}>
            <TileLayer url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" attribution='&copy; CartoDB' />
            <FitBounds points={fitPoints} />

            {/* Route line */}
            {routeCoords && (
              <Polyline
                positions={routeCoords.map(c => [c[1], c[0]])}
                pathOptions={{ color: '#6366f1', weight: 3, opacity: 0.6, dashArray: '6 4' }}
              />
            )}

            {/* User marker */}
            <Marker position={[+userLat, +userLng]} icon={userIcon()}>
              <Popup><div className="text-xs font-bold">Your Location</div></Popup>
            </Marker>

            {/* Danger segments */}
            {prediction?.danger_segments?.map((seg, i) => (
              <CircleMarker key={i} center={[seg.lat, seg.lng]} radius={12}
                pathOptions={{ color: RISK_COLORS[seg.risk_level], fillOpacity: 0.25, weight: 2.5, fillColor: RISK_COLORS[seg.risk_level] }}>
                <Popup>
                  <div className="text-xs">
                    <p className="font-bold" style={{ color: RISK_COLORS[seg.risk_level] }}>{seg.risk_level} Risk</p>
                    <p>Score: {seg.risk} | Distance: {seg.distance}m</p>
                    <p className="text-[10px] text-gray-500">{seg.zone_id}</p>
                  </div>
                </Popup>
              </CircleMarker>
            ))}

            {/* Danger zone highlight */}
            {prediction?.alert && prediction?.danger_segments?.[0] && (
              <Marker position={[prediction.danger_segments[0].lat, prediction.danger_segments[0].lng]} icon={dangerIcon()}>
                <Popup><div className="text-xs font-bold text-red-500">Danger Zone Ahead</div></Popup>
              </Marker>
            )}
          </MapContainer>

          {/* Map overlay */}
          <div className="absolute top-3 right-3 z-[1000] bg-slate-900/85 backdrop-blur-sm border border-slate-700/60 rounded-lg px-3 py-1.5 text-xs flex items-center gap-2">
            <Zap className="w-3.5 h-3.5 text-amber-400" />
            <span className="text-slate-300">Predictive Alert</span>
            {prediction && (
              <>
                <span className="text-slate-600">|</span>
                {prediction.alert ? (
                  <span style={{ color: SEV_COLORS[prediction.severity] }}>{prediction.severity} — {prediction.distance_to_risk}m</span>
                ) : (
                  <span className="text-emerald-400">Safe Ahead</span>
                )}
              </>
            )}
          </div>

          {/* Legend */}
          <div className="absolute bottom-4 left-4 z-[1000] bg-slate-900/90 backdrop-blur-sm border border-slate-700/60 rounded-lg p-3 text-xs">
            <div className="text-slate-400 font-medium mb-1.5">Risk Levels</div>
            {Object.entries(RISK_COLORS).map(([k, c]) => (
              <div key={k} className="flex items-center gap-2 mb-1">
                <div className="w-3 h-3 rounded-full" style={{ background: c }} />
                <span className="text-slate-300">{k}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
