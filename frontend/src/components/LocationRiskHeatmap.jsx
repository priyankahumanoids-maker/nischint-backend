import React, { useState, useEffect, useCallback, useRef } from 'react';
import { MapContainer, TileLayer, CircleMarker, Circle, Popup, Marker, useMap } from 'react-leaflet';
import MarkerClusterGroup from 'react-leaflet-cluster';
import L from 'leaflet';
import 'leaflet.heat';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { operatorApi } from '../api';
import {
  Loader2, MapPin, Shield, AlertTriangle, RefreshCw,
  Eye, EyeOff, Navigation, Radio, Flame,
} from 'lucide-react';

// Fix Leaflet default marker icon
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

const RISK_COLORS = {
  critical: '#dc2626',
  high: '#f97316',
  moderate: '#eab308',
  low: '#22c55e',
};

const LAYER_OPTIONS = [
  { key: 'zones', label: 'Risk Zones', icon: Shield },
  { key: 'devices', label: 'Devices', icon: Navigation },
  { key: 'incidents', label: 'Incidents', icon: AlertTriangle },
  { key: 'geofences', label: 'Geofences', icon: Radio },
  { key: 'heatmap', label: 'Heatmap', icon: Flame },
];

function riskColor(score) {
  if (score >= 7) return RISK_COLORS.critical;
  if (score >= 5) return RISK_COLORS.high;
  if (score >= 3) return RISK_COLORS.moderate;
  return RISK_COLORS.low;
}

function riskLabel(score) {
  if (score >= 7) return 'Critical';
  if (score >= 5) return 'High';
  if (score >= 3) return 'Moderate';
  return 'Low';
}

function severityColor(severity) {
  if (severity === 'critical') return '#dc2626';
  if (severity === 'high') return '#f97316';
  return '#eab308';
}

// ── Device marker with risk-based color + pulse animation ──
function deviceIcon(identifier, riskScore) {
  const color = riskColor(riskScore ?? 0);
  const isHigh = (riskScore ?? 0) >= 5;
  const pulse = isHigh
    ? `<div style="position:absolute;inset:-6px;border-radius:50%;border:2px solid ${color};animation:devpulse 1.5s ease-out infinite;opacity:0.6"></div>`
    : '';
  return L.divIcon({
    className: 'custom-device-marker',
    html: `<div style="position:relative;width:32px;height:32px">${pulse}<div style="position:absolute;inset:2px;background:${color};color:white;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:700;border:2px solid white;box-shadow:0 2px 8px rgba(0,0,0,0.35)">${identifier.slice(-3)}</div></div>`,
    iconSize: [32, 32],
    iconAnchor: [16, 16],
  });
}

// ── Pulse animation CSS (injected once) ──
const PULSE_CSS = `@keyframes devpulse{0%{transform:scale(1);opacity:0.7}100%{transform:scale(2);opacity:0}}`;

// ── Heat Layer component ──
function HeatLayer({ points }) {
  const map = useMap();
  const layerRef = useRef(null);

  useEffect(() => {
    if (!points?.length) return;
    const heat = L.heatLayer(
      points.map(p => [p[0], p[1], p[2] || 0.5]),
      { radius: 30, blur: 20, maxZoom: 17, gradient: { 0.2: '#22c55e', 0.4: '#eab308', 0.6: '#f97316', 0.8: '#dc2626', 1.0: '#7f1d1d' } }
    );
    heat.addTo(map);
    layerRef.current = heat;
    return () => { map.removeLayer(heat); };
  }, [map, points]);

  return null;
}

function FitBounds({ center, zoom }) {
  const map = useMap();
  useEffect(() => {
    if (center) map.setView([center.lat, center.lng], zoom || 14);
  }, [center, zoom, map]);
  return null;
}

function LocationProbe({ onProbe }) {
  const map = useMap();
  useEffect(() => {
    const handler = (e) => onProbe({ lat: e.latlng.lat, lng: e.latlng.lng });
    map.on('contextmenu', handler);
    return () => map.off('contextmenu', handler);
  }, [map, onProbe]);
  return null;
}

// ── Risk Breakdown Bars ──
const BREAKDOWN_LABELS = {
  incident_density: { label: 'Incident Density', color: '#dc2626' },
  time_of_day: { label: 'Night Risk', color: '#8b5cf6' },
  zone_proximity: { label: 'Zone Proximity', color: '#f97316' },
  isolation: { label: 'Isolation Risk', color: '#0ea5e9' },
  history: { label: 'History', color: '#6b7280' },
};

function RiskBreakdownBars({ breakdown }) {
  if (!breakdown) return null;
  return (
    <div className="space-y-1 mt-2 pt-2 border-t border-slate-100" data-testid="risk-breakdown">
      <p className="text-[9px] font-semibold text-slate-500 mb-1">Risk Components</p>
      {Object.entries(BREAKDOWN_LABELS).map(([key, { label, color }]) => {
        const val = breakdown[key] ?? 0;
        return (
          <div key={key} className="flex items-center gap-1.5">
            <span className="text-[9px] text-slate-500 w-[78px] shrink-0 text-right">{label}</span>
            <div className="flex-1 h-[6px] bg-slate-100 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{ width: `${Math.min(100, val * 10)}%`, backgroundColor: color }}
              />
            </div>
            <span className="text-[9px] font-mono font-semibold text-slate-600 w-6 text-right">{val}</span>
          </div>
        );
      })}
    </div>
  );
}

// ── Probe Panel ──
function RiskProbePanel({ probe, onClose }) {
  if (!probe) return null;
  return (
    <div className="absolute bottom-3 left-3 z-[1000] bg-white rounded-lg shadow-xl border border-slate-200 p-3 w-[270px]"
      data-testid="risk-probe-panel">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-slate-700">Location Risk Probe</span>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-xs cursor-pointer">Close</button>
      </div>
      {probe.loading ? (
        <div className="flex items-center gap-2 text-xs text-slate-400 py-2">
          <Loader2 className="w-3 h-3 animate-spin" /> Evaluating...
        </div>
      ) : probe.data ? (
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-slate-800">{probe.data.location_name}</p>
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold" style={{ color: riskColor(probe.data.safety_score) }}>
              {probe.data.safety_score}
            </span>
            <span className="text-[10px] text-slate-400">/ 10</span>
            <Badge className={`text-[10px] ${
              probe.data.risk_level === 'Critical' ? 'bg-red-100 text-red-700' :
              probe.data.risk_level === 'High' ? 'bg-orange-100 text-orange-700' :
              probe.data.risk_level === 'Moderate' ? 'bg-yellow-100 text-yellow-700' :
              'bg-green-100 text-green-700'
            }`}>{probe.data.risk_level}</Badge>
          </div>
          <div className="space-y-0.5">
            {probe.data.factors?.map((f, i) => (
              <p key={i} className="text-[10px] text-slate-500 flex items-start gap-1">
                <span className="w-1 h-1 rounded-full bg-slate-400 mt-1.5 shrink-0" />{f}
              </p>
            ))}
          </div>
          <RiskBreakdownBars breakdown={probe.data.breakdown} />
        </div>
      ) : (
        <p className="text-[10px] text-red-400">Failed to evaluate</p>
      )}
    </div>
  );
}

// ── Stats Bar ──
function StatsBar({ data }) {
  if (!data) return null;
  const highZones = data.risk_zones?.filter(z => z.risk_score >= 7).length || 0;
  const moderateZones = data.risk_zones?.filter(z => z.risk_score >= 3 && z.risk_score < 7).length || 0;
  const alertCount = data.active_alerts?.length || 0;
  const highRiskDevices = data.devices?.filter(d => (d.risk_score ?? 0) >= 5).length || 0;

  return (
    <div className="flex items-center gap-3 flex-wrap" data-testid="location-stats-bar">
      <div className="flex items-center gap-1.5 text-xs">
        <Navigation className="w-3.5 h-3.5 text-blue-500" />
        <span className="text-slate-500">Devices:</span>
        <span className="font-semibold text-slate-700">{data.devices?.length || 0}</span>
      </div>
      {highRiskDevices > 0 && (
        <Badge className="bg-red-100 text-red-700 border border-red-200 text-[10px]">
          {highRiskDevices} At Risk
        </Badge>
      )}
      <div className="flex items-center gap-1.5 text-xs">
        <Shield className="w-3.5 h-3.5 text-red-500" />
        <span className="text-slate-500">High Risk Zones:</span>
        <span className="font-semibold text-red-600">{highZones}</span>
      </div>
      <div className="flex items-center gap-1.5 text-xs">
        <Shield className="w-3.5 h-3.5 text-yellow-500" />
        <span className="text-slate-500">Moderate:</span>
        <span className="font-semibold text-yellow-600">{moderateZones}</span>
      </div>
      <div className="flex items-center gap-1.5 text-xs">
        <AlertTriangle className="w-3.5 h-3.5 text-orange-500" />
        <span className="text-slate-500">Incidents (30d):</span>
        <span className="font-semibold text-slate-700">{data.incidents?.length || 0}</span>
      </div>
      {alertCount > 0 && (
        <Badge className="bg-red-100 text-red-700 border border-red-200 text-[10px]">
          {alertCount} Active Alert{alertCount > 1 ? 's' : ''}
        </Badge>
      )}
    </div>
  );
}

// ── Cluster icon ──
function createClusterIcon(cluster) {
  const count = cluster.getChildCount();
  const size = count < 10 ? 32 : count < 30 ? 38 : 44;
  const bg = count < 10 ? '#eab308' : count < 30 ? '#f97316' : '#dc2626';
  return L.divIcon({
    html: `<div style="width:${size}px;height:${size}px;background:${bg};color:white;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;border:3px solid white;box-shadow:0 2px 8px rgba(0,0,0,0.3)">${count}</div>`,
    className: 'incident-cluster-icon',
    iconSize: [size, size],
  });
}

// ── Main Component ──
export function LocationRiskHeatmap() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [layers, setLayers] = useState(['zones', 'devices', 'incidents', 'geofences', 'heatmap']);
  const [probe, setProbe] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await operatorApi.getLocationHeatmap();
      setData(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load heatmap');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const toggleLayer = (key) => {
    setLayers(prev => prev.includes(key) ? prev.filter(l => l !== key) : [...prev, key]);
  };

  const handleProbe = useCallback(async ({ lat, lng }) => {
    setProbe({ lat, lng, loading: true, data: null });
    try {
      const res = await operatorApi.evaluateLocationRisk(lat, lng);
      setProbe({ lat, lng, loading: false, data: res.data });
    } catch {
      setProbe({ lat, lng, loading: false, data: null });
    }
  }, []);

  // Build heatmap points from incidents
  const heatPoints = data?.incidents?.map(inc => {
    const intensity = inc.severity === 'critical' ? 1.0 : inc.severity === 'high' ? 0.7 : 0.4;
    return [inc.lat, inc.lng, intensity];
  }) || [];

  return (
    <Card className="border-slate-200" data-testid="location-risk-heatmap">
      <style>{PULSE_CSS}</style>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MapPin className="w-5 h-5 text-red-500" />
            <div>
              <CardTitle className="text-sm font-semibold text-slate-800">
                Location Risk Intelligence
              </CardTitle>
              <p className="text-[10px] text-slate-400 mt-0.5">
                Right-click map to probe risk at any point
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            {LAYER_OPTIONS.map(({ key, label, icon: Icon }) => {
              const active = layers.includes(key);
              return (
                <button
                  key={key}
                  onClick={() => toggleLayer(key)}
                  className={`flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium border transition-all ${
                    active ? 'border-slate-300 bg-white shadow-sm' : 'border-transparent bg-slate-100 opacity-50'
                  }`}
                  data-testid={`layer-toggle-${key}`}
                >
                  {active ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
                  {label}
                </button>
              );
            })}
            <Button variant="ghost" size="sm" onClick={fetchData} disabled={loading}
              className="h-7 w-7 p-0" data-testid="heatmap-refresh">
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </div>
        {data && <div className="mt-2"><StatsBar data={data} /></div>}
      </CardHeader>

      <CardContent className="pt-0">
        {loading && !data && (
          <div className="flex items-center justify-center py-16 gap-2 text-slate-400" data-testid="heatmap-loading">
            <Loader2 className="w-5 h-5 animate-spin" />
            <span className="text-sm">Loading location intelligence...</span>
          </div>
        )}

        {error && (
          <div className="text-sm text-red-500 py-8 text-center" data-testid="heatmap-error">{error}</div>
        )}

        {data && (
          <div className="relative rounded-lg overflow-hidden border border-slate-200" style={{ height: 480 }}
            data-testid="heatmap-map-container">
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css" />
            <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" />
            <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css" />
            <MapContainer
              center={[data.center.lat, data.center.lng]}
              zoom={data.zoom}
              style={{ height: '100%', width: '100%' }}
              scrollWheelZoom={true}
            >
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org">OSM</a>'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <FitBounds center={data.center} zoom={data.zoom} />
              <LocationProbe onProbe={handleProbe} />

              {/* True Heatmap Layer */}
              {layers.includes('heatmap') && heatPoints.length > 0 && (
                <HeatLayer points={heatPoints} />
              )}

              {/* Risk Zones */}
              {layers.includes('zones') && data.risk_zones?.map((z) => (
                <Circle
                  key={`zone-${z.id}`}
                  center={[z.lat, z.lng]}
                  radius={z.radius}
                  pathOptions={{
                    color: riskColor(z.risk_score),
                    fillColor: riskColor(z.risk_score),
                    fillOpacity: 0.18,
                    weight: 2,
                  }}
                >
                  <Popup>
                    <div className="text-xs space-y-1 min-w-[160px]">
                      <p className="font-bold">{z.name}</p>
                      <p>Score: <strong style={{ color: riskColor(z.risk_score) }}>{z.risk_score}/10</strong> ({z.risk_level})</p>
                      <p className="text-slate-500">Type: {z.risk_type}</p>
                      {z.factors?.map((f, i) => <p key={i} className="text-slate-400">&bull; {f}</p>)}
                    </div>
                  </Popup>
                </Circle>
              ))}

              {/* Device markers with risk-based color + pulse */}
              {layers.includes('devices') && data.devices?.map((d) => (
                <Marker
                  key={`dev-${d.device_id}`}
                  position={[d.lat, d.lng]}
                  icon={deviceIcon(d.device_identifier, d.risk_score)}
                >
                  <Popup>
                    <div className="text-xs space-y-1 min-w-[140px]">
                      <p className="font-bold">{d.device_identifier}</p>
                      <p>Risk: <strong style={{ color: riskColor(d.risk_score ?? 0) }}>{d.risk_score ?? '—'}/10</strong> ({riskLabel(d.risk_score ?? 0)})</p>
                      <p className="text-slate-400">Last seen: {d.updated_at ? new Date(d.updated_at).toLocaleString() : '—'}</p>
                    </div>
                  </Popup>
                </Marker>
              ))}

              {/* Clustered incident markers */}
              {layers.includes('incidents') && (
                <MarkerClusterGroup
                  chunkedLoading
                  iconCreateFunction={createClusterIcon}
                  maxClusterRadius={50}
                  spiderfyOnMaxZoom={true}
                  showCoverageOnHover={false}
                >
                  {data.incidents?.map((inc, i) => (
                    <CircleMarker
                      key={`inc-${i}`}
                      center={[inc.lat, inc.lng]}
                      radius={5}
                      pathOptions={{
                        color: severityColor(inc.severity),
                        fillColor: severityColor(inc.severity),
                        fillOpacity: 0.8,
                        weight: 1,
                      }}
                    >
                      <Popup>
                        <div className="text-xs">
                          <p className="font-bold">{inc.type}</p>
                          <p>{inc.device} — {inc.severity}</p>
                          <p className="text-slate-400">{new Date(inc.created_at).toLocaleString()}</p>
                        </div>
                      </Popup>
                    </CircleMarker>
                  ))}
                </MarkerClusterGroup>
              )}

              {/* Geofences */}
              {layers.includes('geofences') && data.geofences?.map((gf) => (
                <Circle
                  key={`gf-${gf.id}`}
                  center={[gf.lat, gf.lng]}
                  radius={gf.radius}
                  pathOptions={{
                    color: gf.type === 'safe' ? '#3b82f6' : '#ef4444',
                    fillColor: gf.type === 'safe' ? '#3b82f6' : '#ef4444',
                    fillOpacity: 0.08,
                    weight: 2,
                    dashArray: '8 4',
                  }}
                >
                  <Popup>
                    <div className="text-xs">
                      <p className="font-bold">{gf.name}</p>
                      <p>{gf.device_identifier} — {gf.type} zone ({gf.radius}m)</p>
                    </div>
                  </Popup>
                </Circle>
              ))}

              {/* Probe marker */}
              {probe && (
                <CircleMarker
                  center={[probe.lat, probe.lng]}
                  radius={8}
                  pathOptions={{ color: '#8b5cf6', fillColor: '#8b5cf6', fillOpacity: 0.5, weight: 2 }}
                />
              )}
            </MapContainer>

            {/* Probe panel overlay */}
            <RiskProbePanel probe={probe} onClose={() => setProbe(null)} />

            {/* Map legend */}
            <div className="absolute top-3 right-3 z-[1000] bg-white/95 rounded-lg shadow-md border border-slate-200 p-2 space-y-1"
              data-testid="map-legend">
              <p className="text-[9px] font-semibold text-slate-600 mb-1">Risk Level</p>
              {[
                { label: 'Critical (7-10)', color: RISK_COLORS.critical },
                { label: 'High (5-7)', color: RISK_COLORS.high },
                { label: 'Moderate (3-5)', color: RISK_COLORS.moderate },
                { label: 'Low (0-3)', color: RISK_COLORS.low },
              ].map(({ label, color }) => (
                <div key={label} className="flex items-center gap-1.5">
                  <span className="w-3 h-3 rounded-full" style={{ backgroundColor: color, opacity: 0.7 }} />
                  <span className="text-[9px] text-slate-500">{label}</span>
                </div>
              ))}
              <div className="border-t border-slate-100 pt-1 mt-1">
                <p className="text-[9px] font-semibold text-slate-600 mb-0.5">Device Status</p>
                <div className="flex items-center gap-1.5">
                  <span className="w-3 h-3 rounded-full bg-green-500" />
                  <span className="text-[9px] text-slate-500">Safe</span>
                  <span className="w-3 h-3 rounded-full bg-yellow-500 ml-1" />
                  <span className="text-[9px] text-slate-500">Moderate</span>
                  <span className="w-3 h-3 rounded-full bg-red-500 ml-1" />
                  <span className="text-[9px] text-slate-500">High</span>
                </div>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
