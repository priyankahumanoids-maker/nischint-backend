import React, { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import { MapContainer, TileLayer, Polyline, Marker, Popup, CircleMarker, useMap } from 'react-leaflet';
import L from 'leaflet';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { operatorApi } from '../api';
import { toast } from 'sonner';
import {
  Navigation, Shield, AlertTriangle, MapPin, Clock, Route,
  RefreshCw, Zap, Eye, TrendingUp, ChevronRight, Moon, Sun
} from 'lucide-react';

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

const RISK_COLORS = { CRITICAL: '#dc2626', HIGH: '#f97316', LOW: '#eab308', SAFE: '#22c55e' };
const TYPE_COLORS = { fastest: '#ef4444', safest: '#22c55e', balanced: '#f59e0b' };
const TYPE_ICONS = { fastest: Clock, safest: Shield, balanced: TrendingUp };
const TYPE_LABELS = { fastest: 'Fastest Route', safest: 'Safest Route', balanced: 'Balanced Route' };

function originIcon() {
  return L.divIcon({
    className: 'sr-origin',
    html: '<div style="width:16px;height:16px;background:#3b82f6;border:3px solid white;border-radius:50%;box-shadow:0 0 10px rgba(59,130,246,0.6)"></div>',
    iconSize: [16, 16], iconAnchor: [8, 8],
  });
}

function destIcon() {
  return L.divIcon({
    className: 'sr-dest',
    html: '<div style="width:16px;height:16px;background:#f43f5e;border:3px solid white;border-radius:4px;box-shadow:0 0 8px rgba(244,63,94,0.5)"></div>',
    iconSize: [16, 16], iconAnchor: [8, 8],
  });
}

function FitRoutes({ routes, origin, destination }) {
  const map = useMap();
  const doneRef = useRef(false);
  useEffect(() => {
    if (doneRef.current || !routes?.length) return;
    doneRef.current = true;
    const pts = [];
    if (origin) pts.push([origin.lat, origin.lng]);
    if (destination) pts.push([destination.lat, destination.lng]);
    routes.forEach(r => {
      if (r.geometry?.length) {
        r.geometry.forEach(c => pts.push([c[1], c[0]]));
      }
    });
    if (pts.length > 1) map.fitBounds(pts, { padding: [50, 50], maxZoom: 15 });
  }, [routes, origin, destination, map]);
  return null;
}

function RouteCard({ route, selected, onClick }) {
  const Icon = TYPE_ICONS[route.type] || Route;
  const color = TYPE_COLORS[route.type] || '#6366f1';
  const isSelected = selected === route.type;

  return (
    <div
      data-testid={`sr-route-${route.type}`}
      onClick={() => onClick(route.type)}
      className={`border rounded-lg p-3 cursor-pointer transition-all ${
        isSelected
          ? 'border-indigo-500/60 bg-indigo-500/10 ring-1 ring-indigo-500/30'
          : 'border-slate-700/50 bg-slate-900/50 hover:border-slate-600/60'
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full" style={{ background: color }} />
          <span className="text-sm font-medium text-slate-200">{TYPE_LABELS[route.type]}</span>
        </div>
        <Badge
          style={{ borderColor: `${RISK_COLORS[route.risk_level]}50`, color: RISK_COLORS[route.risk_level], background: `${RISK_COLORS[route.risk_level]}15` }}
          className="text-[10px]"
        >
          {route.risk_level}
        </Badge>
      </div>

      <div className="grid grid-cols-3 gap-2 text-center mb-2">
        <div>
          <div className="text-lg font-bold text-slate-200">{route.time_min}</div>
          <div className="text-[9px] text-slate-500">MIN</div>
        </div>
        <div>
          <div className="text-lg font-bold text-slate-200">{route.distance_km}</div>
          <div className="text-[9px] text-slate-500">KM</div>
        </div>
        <div>
          <div className="text-lg font-bold" style={{ color: RISK_COLORS[route.risk_level] }}>{route.risk_score}</div>
          <div className="text-[9px] text-slate-500">RISK</div>
        </div>
      </div>

      <div className="flex items-center justify-between text-[10px] text-slate-500">
        <span>{route.zones_crossed} zones</span>
        {route.high_risk_zones > 0 && <span className="text-orange-400">{route.high_risk_zones} high risk</span>}
        {route.critical_zones > 0 && <span className="text-red-400">{route.critical_zones} critical</span>}
      </div>

      {route.warnings?.length > 0 && (
        <div className="mt-2 space-y-0.5">
          {route.warnings.map((w, i) => (
            <div key={i} className="flex items-center gap-1 text-[10px] text-orange-400">
              <AlertTriangle className="w-2.5 h-2.5" />
              <span>{w}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SmartSuggestion({ routes }) {
  if (!routes || routes.length < 2) return null;
  const fastest = routes.find(r => r.type === 'fastest');
  const safest = routes.find(r => r.type === 'safest');
  if (!fastest || !safest) return null;

  const timeDiff = safest.time_min - fastest.time_min;
  const riskDiff = fastest.risk_score - safest.risk_score;

  if (fastest.high_risk_zones > 0 || fastest.critical_zones > 0) {
    return (
      <div data-testid="sr-suggestion" className="bg-orange-500/10 border border-orange-500/30 rounded-lg p-2.5 text-xs">
        <div className="flex items-center gap-2 mb-1">
          <AlertTriangle className="w-3.5 h-3.5 text-orange-400" />
          <span className="font-medium text-orange-300">Safety Advisory</span>
        </div>
        <p className="text-slate-400">
          Fastest route passes through {fastest.high_risk_zones + fastest.critical_zones} high-risk zone{(fastest.high_risk_zones + fastest.critical_zones) > 1 ? 's' : ''}.
          {timeDiff > 0 ? ` Safer route available (+${timeDiff.toFixed(0)} min, ${riskDiff.toFixed(1)} lower risk).` : ''}
        </p>
      </div>
    );
  }
  return null;
}

export default function SafeRouteDashboard() {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState('balanced');
  const [originLat, setOriginLat] = useState('12.971');
  const [originLng, setOriginLng] = useState('77.594');
  const [destLat, setDestLat] = useState('12.935');
  const [destLng, setDestLng] = useState('77.624');
  const [timeMode, setTimeMode] = useState('');

  const handleGenerate = useCallback(async () => {
    setLoading(true);
    try {
      const payload = {
        origin: { lat: +originLat, lng: +originLng },
        destination: { lat: +destLat, lng: +destLng },
      };
      if (timeMode) payload.time = timeMode;
      const { data } = await operatorApi.generateSafeRoute(payload);
      setResult(data);
      setSelected('balanced');
      toast.success(`Generated ${data.routes?.length || 0} routes (${data.time_period})`);
    } catch {
      toast.error('Route generation failed');
    } finally {
      setLoading(false);
    }
  }, [originLat, originLng, destLat, destLng, timeMode]);

  const routes = result?.routes || [];
  const selectedRoute = routes.find(r => r.type === selected);

  const mapCenter = useMemo(() => {
    if (result?.origin && result?.destination) {
      return [(result.origin.lat + result.destination.lat) / 2, (result.origin.lng + result.destination.lng) / 2];
    }
    return [12.95, 77.61];
  }, [result]);

  return (
    <div data-testid="safe-route-dashboard" className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Navigation className="w-6 h-6 text-cyan-400" />
          <div>
            <h1 className="text-xl font-bold text-slate-100">Safe Route AI</h1>
            <p className="text-xs text-slate-500">AI-powered route optimization — fastest, safest, balanced</p>
          </div>
        </div>
        {result && (
          <div className="flex items-center gap-2 text-xs text-slate-400">
            {result.time_period === 'day' ? <Sun className="w-3.5 h-3.5 text-yellow-400" /> : <Moon className="w-3.5 h-3.5 text-indigo-400" />}
            <span className="capitalize">{result.time_period}</span>
            <span className="text-slate-600">|</span>
            <span>Night factor: x{result.night_multiplier}</span>
          </div>
        )}
      </div>

      {/* Input Controls */}
      <Card className="bg-slate-900/50 border-slate-700/60">
        <CardContent className="p-3">
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-2 items-end">
            <div>
              <label className="text-[9px] text-slate-500 uppercase">Origin Lat</label>
              <input data-testid="sr-origin-lat" value={originLat} onChange={e => setOriginLat(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-300" />
            </div>
            <div>
              <label className="text-[9px] text-slate-500 uppercase">Origin Lng</label>
              <input data-testid="sr-origin-lng" value={originLng} onChange={e => setOriginLng(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-300" />
            </div>
            <div>
              <label className="text-[9px] text-slate-500 uppercase">Dest Lat</label>
              <input data-testid="sr-dest-lat" value={destLat} onChange={e => setDestLat(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-300" />
            </div>
            <div>
              <label className="text-[9px] text-slate-500 uppercase">Dest Lng</label>
              <input data-testid="sr-dest-lng" value={destLng} onChange={e => setDestLng(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-300" />
            </div>
            <div className="flex gap-2">
              <select
                data-testid="sr-time-mode"
                value={timeMode}
                onChange={e => setTimeMode(e.target.value)}
                className="bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-300 flex-1"
              >
                <option value="">Current Time</option>
                <option value="10:00">Day (10:00)</option>
                <option value="22:00">Night (22:00)</option>
                <option value="02:00">Late Night (02:00)</option>
              </select>
              <Button
                data-testid="sr-generate"
                onClick={handleGenerate}
                disabled={loading}
                size="sm" className="bg-cyan-600 hover:bg-cyan-700 text-xs whitespace-nowrap"
              >
                {loading ? <RefreshCw className="w-3 h-3 mr-1 animate-spin" /> : <Route className="w-3 h-3 mr-1" />}
                Generate
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Main Layout */}
      {routes.length > 0 ? (
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-4" style={{ minHeight: '520px' }}>
          {/* Left: Route Cards */}
          <div className="lg:col-span-2 space-y-3">
            {routes.map(r => (
              <RouteCard key={r.type} route={r} selected={selected} onClick={setSelected} />
            ))}
            <SmartSuggestion routes={routes} />
          </div>

          {/* Right: Map */}
          <div className="lg:col-span-3 relative rounded-lg overflow-hidden border border-slate-700/50" data-testid="sr-map">
            <MapContainer
              center={mapCenter}
              zoom={13}
              style={{ height: '520px', width: '100%', background: '#0f172a' }}
              zoomControl={false}
            >
              <TileLayer
                url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
                attribution='&copy; CartoDB'
              />

              <FitRoutes routes={routes} origin={result?.origin} destination={result?.destination} />

              {/* All route polylines (dimmed non-selected) */}
              {routes.map(r => (
                <Polyline
                  key={r.type}
                  positions={r.geometry?.map(c => [c[1], c[0]]) || []}
                  pathOptions={{
                    color: TYPE_COLORS[r.type],
                    weight: r.type === selected ? 5 : 2,
                    opacity: r.type === selected ? 0.9 : 0.3,
                    dashArray: r.type === selected ? undefined : '6 6',
                  }}
                  eventHandlers={{ click: () => setSelected(r.type) }}
                />
              ))}

              {/* Risk segment markers for selected route */}
              {selectedRoute?.segments?.filter(s => s.risk >= 5).map((seg, i) => (
                <CircleMarker
                  key={i}
                  center={[seg.lat, seg.lng]}
                  radius={5}
                  pathOptions={{
                    color: RISK_COLORS[seg.risk_level] || '#f97316',
                    fillOpacity: 0.4, weight: 1.5, opacity: 0.7,
                  }}
                >
                  <Popup>
                    <div className="text-xs">
                      <p className="font-bold" style={{ color: RISK_COLORS[seg.risk_level] }}>{seg.risk_level} Risk</p>
                      <p>Score: {seg.risk}</p>
                      <p className="text-[10px] text-slate-500">Zone: {seg.zone_id}</p>
                    </div>
                  </Popup>
                </CircleMarker>
              ))}

              {/* Origin marker */}
              {result?.origin && (
                <Marker position={[result.origin.lat, result.origin.lng]} icon={originIcon()}>
                  <Popup><div className="text-xs font-bold">Origin</div></Popup>
                </Marker>
              )}

              {/* Destination marker */}
              {result?.destination && (
                <Marker position={[result.destination.lat, result.destination.lng]} icon={destIcon()}>
                  <Popup><div className="text-xs font-bold">Destination</div></Popup>
                </Marker>
              )}
            </MapContainer>

            {/* Map overlay */}
            <div className="absolute top-3 right-3 z-[1000] bg-slate-900/85 backdrop-blur-sm border border-slate-700/60 rounded-lg px-3 py-1.5 text-xs flex items-center gap-2">
              <Navigation className="w-3.5 h-3.5 text-cyan-400" />
              <span className="text-slate-300">Safe Route AI</span>
              <span className="text-slate-600">|</span>
              {selectedRoute && (
                <>
                  <span style={{ color: TYPE_COLORS[selected] }}>{TYPE_LABELS[selected]}</span>
                  <span className="text-slate-600">|</span>
                  <span style={{ color: RISK_COLORS[selectedRoute.risk_level] }}>{selectedRoute.risk_level}</span>
                </>
              )}
            </div>

            {/* Legend */}
            <div className="absolute bottom-4 left-4 z-[1000] bg-slate-900/90 backdrop-blur-sm border border-slate-700/60 rounded-lg p-3 text-xs">
              <div className="text-slate-400 font-medium mb-1.5">Route Types</div>
              {Object.entries(TYPE_LABELS).map(([k, label]) => (
                <div key={k} className="flex items-center gap-2 mb-1 cursor-pointer" onClick={() => setSelected(k)}>
                  <div className="w-3 h-3 rounded-full" style={{ background: TYPE_COLORS[k], opacity: k === selected ? 1 : 0.4 }} />
                  <span className={`text-slate-300 ${k === selected ? 'font-medium' : 'opacity-60'}`}>{label}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <Card className="bg-slate-900/50 border-slate-700/60">
          <CardContent className="py-12 text-center">
            <Navigation className="w-10 h-10 mx-auto mb-3 text-cyan-500/30" />
            <p className="text-sm text-slate-400">Enter origin and destination</p>
            <p className="text-xs text-slate-600">AI will generate fastest, safest, and balanced routes</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
