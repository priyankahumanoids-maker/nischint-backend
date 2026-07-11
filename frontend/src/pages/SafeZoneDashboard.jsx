import React, { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { MapContainer, TileLayer, CircleMarker, Marker, Popup, useMap, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet.heat';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { operatorApi } from '../api';
import { toast } from 'sonner';
import {
  Shield, AlertTriangle, MapPin, Navigation, Eye,
  RefreshCw, Crosshair, Clock, TrendingUp, Activity,
  ChevronRight, Zap
} from 'lucide-react';

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

const RISK_COLORS = { CRITICAL: '#dc2626', HIGH: '#f97316', LOW: '#eab308', SAFE: '#22c55e' };
const RISK_BG = {
  CRITICAL: 'bg-red-500/15 border-red-500/40 text-red-300',
  HIGH: 'bg-orange-500/15 border-orange-500/40 text-orange-300',
  LOW: 'bg-yellow-500/15 border-yellow-500/40 text-yellow-300',
  SAFE: 'bg-emerald-500/15 border-emerald-500/40 text-emerald-300',
};
const RISK_ICON_COLOR = { CRITICAL: 'text-red-400', HIGH: 'text-orange-400', LOW: 'text-yellow-400', SAFE: 'text-emerald-400' };

const HEAT_GRADIENT = { 0.1: '#16a34a', 0.25: '#65a30d', 0.4: '#eab308', 0.55: '#ea580c', 0.7: '#dc2626', 0.85: '#991b1b', 1.0: '#7f1d1d' };

function userMarkerIcon() {
  return L.divIcon({
    className: 'user-loc-icon',
    html: '<div style="width:18px;height:18px;background:#3b82f6;border:3px solid white;border-radius:50%;box-shadow:0 0 10px rgba(59,130,246,0.5),0 2px 6px rgba(0,0,0,0.3)"></div>',
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

// ── Heat Layer ──
function HeatLayer({ zones }) {
  const map = useMap();
  const layerRef = useRef(null);
  useEffect(() => {
    if (layerRef.current) { map.removeLayer(layerRef.current); layerRef.current = null; }
    if (!zones?.length) return;
    const pts = zones.filter(z => z.risk_score > 0).map(z => [z.lat, z.lng, Math.max(0.12, z.risk_score / 10)]);
    if (!pts.length) return;
    const heat = L.heatLayer(pts, { radius: 35, blur: 25, maxZoom: 16, max: 1.0, minOpacity: 0.45, gradient: HEAT_GRADIENT });
    heat.addTo(map);
    layerRef.current = heat;
    return () => { if (layerRef.current) map.removeLayer(layerRef.current); };
  }, [map, zones]);
  return null;
}

// ── Map click handler ──
function MapClickHandler({ onMapClick }) {
  useMapEvents({ click: (e) => onMapClick(e.latlng.lat, e.latlng.lng) });
  return null;
}

// ── FitBounds ──
function FitBounds({ zones }) {
  const map = useMap();
  const doneRef = useRef(false);
  useEffect(() => {
    if (doneRef.current || !zones?.length) return;
    doneRef.current = true;
    const pts = zones.map(z => [z.lat, z.lng]);
    map.fitBounds(pts, { padding: [40, 40], maxZoom: 14, animate: false });
  }, [zones, map]);
  return null;
}

// ── Score bar ──
function ScoreItem({ label, value, icon: Icon, color }) {
  const pct = Math.min(100, (value / 10) * 100);
  return (
    <div className="flex items-center gap-2">
      <Icon className={`w-3.5 h-3.5 ${color}`} />
      <span className="w-20 text-xs text-slate-400">{label}</span>
      <div className="flex-1 h-1.5 bg-slate-700/50 rounded-full overflow-hidden">
        <div className={`h-full rounded-full`} style={{ width: `${pct}%`, background: pct > 70 ? '#dc2626' : pct > 40 ? '#f97316' : pct > 20 ? '#eab308' : '#22c55e' }} />
      </div>
      <span className="w-8 text-right text-xs text-slate-300 font-medium">{value.toFixed(1)}</span>
    </div>
  );
}

// ── Alert Card ──
function AlertCard({ data }) {
  if (!data) return null;
  const rl = data.risk_level || 'SAFE';
  const color = RISK_COLORS[rl] || '#22c55e';

  return (
    <div data-testid="safe-zone-alert" className={`border rounded-lg p-4 ${RISK_BG[rl]}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Shield className={`w-5 h-5 ${RISK_ICON_COLOR[rl]}`} />
          <span className="text-lg font-bold">{data.zone_status}</span>
        </div>
        <div className="text-right">
          <div className="text-2xl font-bold" style={{ color }}>{data.risk_score}</div>
          <div className="text-[10px] text-slate-500">RISK SCORE</div>
        </div>
      </div>

      <p className="text-sm mb-2">{data.recommendation_message}</p>

      <div className="grid grid-cols-3 gap-2 text-[10px] mb-3">
        <div>
          <span className="text-slate-500">Zone</span>
          <p className="text-slate-300 font-medium truncate">{data.zone_name}</p>
        </div>
        <div>
          <span className="text-slate-500">Time</span>
          <p className="text-slate-300 font-medium capitalize">{data.time_period} (x{data.time_multiplier})</p>
        </div>
        <div>
          <span className="text-slate-500">Incidents</span>
          <p className="text-slate-300 font-medium">{data.incident_density} nearby</p>
        </div>
      </div>

      {/* Score breakdown */}
      {data.score_breakdown && (
        <div className="space-y-1.5 pt-2 border-t border-white/10">
          <ScoreItem label="Crime Density" value={data.score_breakdown.crime_density || 0} icon={AlertTriangle} color="text-red-400" />
          <ScoreItem label="Incidents" value={data.score_breakdown.recent_incidents || 0} icon={Zap} color="text-orange-400" />
          <ScoreItem label="Time of Day" value={data.score_breakdown.time_of_day || 0} icon={Clock} color="text-yellow-400" />
          <ScoreItem label="Environment" value={data.score_breakdown.environment || 0} icon={Eye} color="text-cyan-400" />
        </div>
      )}

      {/* Transition alert */}
      {data.alert_triggered && data.transition?.type === 'escalation' && (
        <div className="mt-3 pt-2 border-t border-white/10 flex items-center gap-2 text-xs">
          <AlertTriangle className="w-4 h-4 text-red-400 animate-pulse" />
          <span className="font-medium">Risk Escalation: {data.transition.previous_risk} → {data.risk_level}</span>
        </div>
      )}

      {data.safe_route_available && (
        <div className="mt-2 flex items-center gap-1 text-xs text-indigo-400">
          <Navigation className="w-3 h-3" /> Safe route available
        </div>
      )}

      <div className="mt-2 text-[9px] text-slate-600 flex items-center justify-between">
        <span>ID: {data.zone_id}</span>
        <span>{data.cached ? 'Cached' : 'Live'}</span>
      </div>
    </div>
  );
}

// ── Legend ──
function MapLegend() {
  return (
    <div data-testid="safe-zone-legend" className="absolute bottom-4 left-4 z-[1000] bg-slate-900/90 backdrop-blur-sm border border-slate-700/60 rounded-lg p-3 text-xs">
      <div className="text-slate-400 font-medium mb-1.5">Risk Levels</div>
      {Object.entries(RISK_COLORS).map(([k, c]) => (
        <div key={k} className="flex items-center gap-2 mb-1">
          <div className="w-3 h-3 rounded-full" style={{ background: c }} />
          <span className="text-slate-300">{k}</span>
        </div>
      ))}
      <div className="mt-2 pt-1.5 border-t border-slate-700/40 text-[10px] text-slate-500">
        Click map to check any location
      </div>
    </div>
  );
}

// ── Zone Stats ──
function ZoneStats({ mapData }) {
  if (!mapData) return null;
  const s = mapData.stats || {};
  return (
    <div data-testid="safe-zone-stats" className="grid grid-cols-4 gap-2">
      {[
        { label: 'Critical', value: s.CRITICAL || 0, color: 'text-red-400', bg: 'bg-red-500/10' },
        { label: 'High', value: s.HIGH || 0, color: 'text-orange-400', bg: 'bg-orange-500/10' },
        { label: 'Low', value: s.LOW || 0, color: 'text-yellow-400', bg: 'bg-yellow-500/10' },
        { label: 'Safe', value: s.SAFE || 0, color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
      ].map((it) => (
        <div key={it.label} className={`${it.bg} border border-slate-700/40 rounded-lg p-2 text-center`}>
          <div className={`text-lg font-bold ${it.color}`}>{it.value}</div>
          <div className="text-[9px] text-slate-500">{it.label}</div>
        </div>
      ))}
    </div>
  );
}

// ── Main Dashboard ──
export default function SafeZoneDashboard() {
  const [mapData, setMapData] = useState(null);
  const [checkResult, setCheckResult] = useState(null);
  const [selectedPos, setSelectedPos] = useState(null);
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(false);

  // Load zone map on mount
  useEffect(() => {
    setLoading(true);
    operatorApi.getZoneMap()
      .then(({ data }) => setMapData(data))
      .catch(() => toast.error('Failed to load zone map'))
      .finally(() => setLoading(false));
  }, []);

  const checkLocation = useCallback(async (lat, lng) => {
    setSelectedPos({ lat, lng });
    setChecking(true);
    try {
      const { data } = await operatorApi.checkZone({
        location: { lat, lng },
      });
      setCheckResult(data);
      const rl = data.risk_level;
      if (rl === 'CRITICAL') toast.error(`CRITICAL zone: ${data.zone_name}`);
      else if (rl === 'HIGH') toast.warning(`HIGH risk: ${data.zone_name}`);
      else if (rl === 'LOW') toast.info(`Low risk: ${data.zone_name}`);
      else toast.success(`Safe zone: ${data.zone_name}`);
    } catch {
      toast.error('Zone check failed');
    } finally {
      setChecking(false);
    }
  }, []);

  const zones = mapData?.zones || [];

  const mapCenter = useMemo(() => {
    if (zones.length) {
      const lats = zones.map(z => z.lat);
      const lngs = zones.map(z => z.lng);
      return [(Math.min(...lats) + Math.max(...lats)) / 2, (Math.min(...lngs) + Math.max(...lngs)) / 2];
    }
    return [12.97, 77.59];
  }, [zones]);

  return (
    <div data-testid="safe-zone-dashboard" className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Shield className="w-6 h-6 text-emerald-400" />
          <div>
            <h1 className="text-xl font-bold text-slate-100">Safe Zone Detection</h1>
            <p className="text-xs text-slate-500">Real-time zone safety with composite risk scoring</p>
          </div>
        </div>
        <Button
          data-testid="safe-zone-refresh"
          onClick={() => {
            setLoading(true);
            operatorApi.getZoneMap()
              .then(({ data }) => { setMapData(data); toast.success('Zone map refreshed'); })
              .catch(() => toast.error('Refresh failed'))
              .finally(() => setLoading(false));
          }}
          variant="outline"
          size="sm"
          className="border-slate-700 text-slate-300 text-xs"
        >
          <RefreshCw className={`w-3 h-3 mr-1.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      {/* Zone stats */}
      <ZoneStats mapData={mapData} />

      {/* Main: Map + Alert panel */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4" style={{ minHeight: '520px' }}>
        {/* Left: Alert + info */}
        <div className="lg:col-span-2 space-y-3">
          {checkResult ? (
            <AlertCard data={checkResult} />
          ) : (
            <Card className="bg-slate-900/50 border-slate-700/60">
              <CardContent className="py-8 text-center">
                <Crosshair className="w-8 h-8 mx-auto mb-2 text-indigo-500/40" />
                <p className="text-sm text-slate-400">Click anywhere on the map</p>
                <p className="text-xs text-slate-600">to check zone safety</p>
              </CardContent>
            </Card>
          )}

          {/* Time info */}
          {mapData && (
            <Card className="bg-slate-900/50 border-slate-700/60">
              <CardContent className="p-3 space-y-1.5">
                <div className="text-[10px] text-slate-500 font-medium uppercase">Current Conditions</div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-slate-400">Time Period</span>
                  <Badge className="bg-indigo-500/20 text-indigo-300 border-indigo-500/30 text-[10px] capitalize">{mapData.time_period}</Badge>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-slate-400">Time Multiplier</span>
                  <span className="text-slate-300 font-medium">x{mapData.time_multiplier}</span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-slate-400">Active Zones</span>
                  <span className="text-slate-300 font-medium">{mapData.total_zones}</span>
                </div>
                <div className="pt-1.5 border-t border-slate-700/40 text-[9px] text-slate-600">
                  Scores: Crime Density 50% + Incidents 30% + Time 10% + Environment 10%
                </div>
              </CardContent>
            </Card>
          )}

          {/* Selected position */}
          {selectedPos && (
            <div className="flex items-center gap-2 text-[10px] text-slate-500 px-1">
              <MapPin className="w-3 h-3" />
              <span>{selectedPos.lat.toFixed(5)}, {selectedPos.lng.toFixed(5)}</span>
              {checking && <span className="animate-pulse text-indigo-400">Checking...</span>}
            </div>
          )}
        </div>

        {/* Right: Map */}
        <div className="lg:col-span-3 relative rounded-lg overflow-hidden border border-slate-700/50" data-testid="safe-zone-map">
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

            <FitBounds zones={zones} />
            <MapClickHandler onMapClick={checkLocation} />

            {/* Heatmap overlay */}
            <HeatLayer zones={zones} />

            {/* Zone markers */}
            {zones.map((zone) => (
              <CircleMarker
                key={zone.zone_id}
                center={[zone.lat, zone.lng]}
                radius={6}
                pathOptions={{
                  color: RISK_COLORS[zone.risk_level] || '#6366f1',
                  fillColor: RISK_COLORS[zone.risk_level] || '#6366f1',
                  fillOpacity: 0.5,
                  weight: 1.5,
                  opacity: 0.8,
                }}
                eventHandlers={{ click: () => checkLocation(zone.lat, zone.lng) }}
              >
                <Popup maxWidth={200}>
                  <div className="text-xs">
                    <p className="font-bold">{zone.zone_name}</p>
                    <p>Risk: <strong style={{ color: RISK_COLORS[zone.risk_level] }}>{zone.risk_level}</strong> ({zone.risk_score})</p>
                    <p>Incidents: {zone.incident_count}</p>
                    <p className="text-[10px] text-slate-500">ID: {zone.zone_id}</p>
                  </div>
                </Popup>
              </CircleMarker>
            ))}

            {/* User check marker */}
            {selectedPos && (
              <Marker position={[selectedPos.lat, selectedPos.lng]} icon={userMarkerIcon()}>
                <Popup>
                  <div className="text-xs">
                    <p className="font-bold">Checked Location</p>
                    {checkResult && (
                      <>
                        <p style={{ color: RISK_COLORS[checkResult.risk_level] }}>
                          {checkResult.risk_level} — Score: {checkResult.risk_score}
                        </p>
                        <p>{checkResult.recommendation_message}</p>
                      </>
                    )}
                  </div>
                </Popup>
              </Marker>
            )}
          </MapContainer>

          <MapLegend />

          {/* Map overlay */}
          {mapData && (
            <div className="absolute top-3 right-3 z-[1000] bg-slate-900/85 backdrop-blur-sm border border-slate-700/60 rounded-lg px-3 py-1.5 text-xs flex items-center gap-2">
              <Shield className="w-3.5 h-3.5 text-emerald-400" />
              <span className="text-slate-300">{mapData.total_zones} zones</span>
              <span className="text-slate-600">|</span>
              <span className="text-red-400">{mapData.stats?.CRITICAL || 0} critical</span>
              <span className="text-slate-600">|</span>
              <span className="text-slate-400 capitalize">{mapData.time_period}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
