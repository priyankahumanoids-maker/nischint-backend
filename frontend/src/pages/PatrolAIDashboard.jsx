import React, { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { MapContainer, TileLayer, Polyline, Marker, Popup, CircleMarker, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet.heat';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Slider } from '../components/ui/slider';
import { Switch } from '../components/ui/switch';
import { operatorApi } from '../api';
import { toast } from 'sonner';
import {
  Play, MapPin, Clock, Route, AlertTriangle, TrendingUp,
  Activity, Brain, Timer, ChevronDown, ChevronUp, Navigation,
  Crosshair, Eye, Globe, Flame
} from 'lucide-react';

// Fix Leaflet default icon
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

const PRIORITY_HEX = {
  critical: '#ef4444',
  high: '#f97316',
  medium: '#eab308',
  low: '#22c55e',
};

const PRIORITY_BADGE = {
  critical: 'bg-red-500/20 text-red-300 border-red-500/40',
  high: 'bg-orange-500/20 text-orange-300 border-orange-500/40',
  medium: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/40',
  low: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
};

const FORECAST_COLORS = {
  escalating: 'text-red-400',
  emerging: 'text-orange-400',
  stable: 'text-slate-400',
  cooling: 'text-cyan-400',
};

function stopIcon(number, priority, isSelected) {
  const color = PRIORITY_HEX[priority] || '#6366f1';
  const size = isSelected ? 36 : 28;
  const border = isSelected ? '3px solid white' : '2px solid rgba(255,255,255,0.7)';
  const shadow = isSelected ? '0 0 12px rgba(99,102,241,0.6), 0 2px 8px rgba(0,0,0,0.4)' : '0 2px 6px rgba(0,0,0,0.35)';
  return L.divIcon({
    className: 'patrol-stop-icon',
    html: `<div style="background:${color};color:white;width:${size}px;height:${size}px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:${isSelected ? 14 : 11}px;font-weight:700;border:${border};box-shadow:${shadow};transition:all 0.2s">${number}</div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function startIcon() {
  return L.divIcon({
    className: 'patrol-start-icon',
    html: `<div style="background:#22c55e;color:white;width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:700;border:2px solid white;box-shadow:0 2px 8px rgba(0,0,0,0.35)">S</div>`,
    iconSize: [32, 32],
    iconAnchor: [16, 16],
  });
}

// ── Map auto-fit ──
function FitBounds({ bounds }) {
  const map = useMap();
  useEffect(() => {
    if (bounds && bounds.length >= 2) {
      map.fitBounds(bounds, { padding: [50, 50], maxZoom: 14 });
    }
  }, [bounds, map]);
  return null;
}

// ── Fly to selected stop ──
function FlyToStop({ position }) {
  const map = useMap();
  useEffect(() => {
    if (position) {
      map.flyTo(position, 15, { duration: 0.8 });
    }
  }, [position, map]);
  return null;
}

// ── Heatmap overlay layer for patrol map ──
const HEAT_GRADIENT = { 0.1: '#16a34a', 0.25: '#65a30d', 0.4: '#eab308', 0.55: '#ea580c', 0.7: '#dc2626', 0.85: '#991b1b', 1.0: '#7f1d1d' };
function PatrolHeatLayer({ cells }) {
  const map = useMap();
  const layerRef = useRef(null);
  useEffect(() => {
    if (layerRef.current) { map.removeLayer(layerRef.current); layerRef.current = null; }
    if (!cells?.length) return;
    const pts = cells.filter(c => c.composite_score > 0).map(c => [c.lat, c.lng, Math.max(0.12, c.composite_score / 10.0)]);
    if (!pts.length) return;
    const heat = L.heatLayer(pts, { radius: 30, blur: 22, maxZoom: 16, max: 1.0, minOpacity: 0.35, gradient: HEAT_GRADIENT });
    heat.addTo(map);
    layerRef.current = heat;
    return () => { if (layerRef.current) map.removeLayer(layerRef.current); };
  }, [map, cells]);
  return null;
}



// ── Score breakdown bar ──
function ScoreBar({ label, score, weighted, icon: Icon, color }) {
  const pct = Math.min(100, (score / 10) * 100);
  return (
    <div className="flex items-center gap-2 text-xs">
      <Icon className={`w-3.5 h-3.5 ${color}`} />
      <span className="w-16 text-slate-400 truncate">{label}</span>
      <div className="flex-1 h-1.5 bg-slate-700/50 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color.replace('text-', 'bg-')}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-8 text-right text-slate-300">{score.toFixed(1)}</span>
      <span className="w-10 text-right text-slate-500">({weighted.toFixed(2)})</span>
    </div>
  );
}

// ── Zone list card ──
function ZoneCard({ zone, expanded, onToggle, selected, onSelect }) {
  const bd = zone.score_breakdown || {};
  return (
    <div
      data-testid={`patrol-zone-${zone.stop_number}`}
      className={`border rounded-lg overflow-hidden transition-all ${
        selected
          ? 'bg-indigo-900/40 border-indigo-500/60 ring-1 ring-indigo-500/30'
          : 'bg-slate-800/60 border-slate-700/50 hover:border-slate-600/60'
      }`}
    >
      <div className="flex items-center gap-2 p-2.5 cursor-pointer" onClick={onSelect}>
        <div
          className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold text-white flex-shrink-0"
          style={{ background: PRIORITY_HEX[zone.patrol_priority] || '#6366f1' }}
        >
          {zone.stop_number}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-medium text-slate-200 truncate">{zone.zone_name}</span>
            <Badge className={`text-[9px] px-1 py-0 leading-tight ${PRIORITY_BADGE[zone.patrol_priority]}`}>
              {zone.patrol_priority}
            </Badge>
            {zone.heatmap_enhanced && bd.heatmap_risk !== 'none' && (
              <Badge className="text-[9px] px-1 py-0 leading-tight bg-amber-500/20 text-amber-300 border-amber-500/40" data-testid={`heatmap-badge-${zone.stop_number}`}>
                <Flame className="w-2.5 h-2.5 mr-0.5 inline" />{bd.heatmap_boost > 1 ? `+${Math.round((bd.heatmap_boost - 1) * 100)}%` : 'HM'}
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-2 text-[10px] text-slate-500 mt-0.5">
            <span>{zone.incident_count} inc</span>
            <span className={FORECAST_COLORS[zone.forecast_category] || ''}>
              {zone.forecast_category}
            </span>
          </div>
        </div>
        <div className="text-right flex-shrink-0">
          <div className="text-sm font-bold text-amber-400">{zone.composite_score.toFixed(1)}</div>
        </div>
        <button onClick={(e) => { e.stopPropagation(); onToggle(); }} className="p-0.5 text-slate-500 hover:text-slate-300">
          {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </button>
      </div>

      {expanded && (
        <div className="border-t border-slate-700/50 p-2.5 space-y-1.5">
          <ScoreBar label="Forecast" score={bd.forecast || 0} weighted={bd.forecast_weighted || 0} icon={TrendingUp} color="text-red-400" />
          <ScoreBar label="Trend" score={bd.trend || 0} weighted={bd.trend_weighted || 0} icon={AlertTriangle} color="text-orange-400" />
          <ScoreBar label="Activity" score={bd.activity || 0} weighted={bd.activity_weighted || 0} icon={Activity} color="text-yellow-400" />
          <ScoreBar label="Learning" score={bd.learning || 0} weighted={bd.learning_weighted || 0} icon={Brain} color="text-purple-400" />
          <ScoreBar label="Temporal" score={bd.temporal || 0} weighted={bd.temporal_weighted || 0} icon={Timer} color="text-cyan-400" />
          {zone.heatmap_enhanced && bd.heatmap_score > 0 && (
            <div className="pt-1.5 mt-1 border-t border-slate-700/40">
              <div className="flex items-center gap-2 text-xs">
                <Globe className="w-3.5 h-3.5 text-amber-400" />
                <span className="w-16 text-slate-400 truncate">Heatmap</span>
                <div className="flex-1 h-1.5 bg-slate-700/50 rounded-full overflow-hidden">
                  <div className="h-full rounded-full bg-amber-400" style={{ width: `${Math.min(100, (bd.heatmap_score / 10) * 100)}%` }} />
                </div>
                <span className="w-8 text-right text-amber-300">{bd.heatmap_score.toFixed(1)}</span>
                <Badge className="text-[8px] px-1 py-0 bg-amber-500/15 text-amber-400 border-amber-500/30 capitalize">{bd.heatmap_risk}</Badge>
              </div>
              {bd.heatmap_cell_id && (
                <div className="text-[9px] text-slate-600 mt-0.5 ml-5">Cell: {bd.heatmap_cell_id} | Boost: x{bd.heatmap_boost}</div>
              )}
            </div>
          )}
          {zone.recommendation?.action && (
            <div className="mt-1.5 text-[10px] bg-slate-900/50 rounded p-1.5">
              <span className="text-amber-400 font-medium">{zone.recommendation.action}:</span>
              <span className="text-slate-400 ml-1">{zone.recommendation.details?.[0]}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Map Legend ──
function MapLegend() {
  return (
    <div
      data-testid="patrol-map-legend"
      className="absolute bottom-4 left-4 z-[1000] bg-slate-900/90 backdrop-blur-sm border border-slate-700/60 rounded-lg p-3 text-xs"
    >
      <div className="text-slate-400 font-medium mb-2">Patrol Priority</div>
      {Object.entries(PRIORITY_HEX).map(([k, c]) => (
        <div key={k} className="flex items-center gap-2 mb-1">
          <div className="w-3 h-3 rounded-full" style={{ background: c }} />
          <span className="text-slate-300 capitalize">{k}</span>
        </div>
      ))}
      <div className="flex items-center gap-2 mt-2 pt-2 border-t border-slate-700/40">
        <div className="w-3 h-3 rounded-full bg-green-500" />
        <span className="text-slate-300">Start</span>
      </div>
      <div className="flex items-center gap-2 mt-1">
        <div className="w-6 h-0.5 bg-indigo-400" />
        <span className="text-slate-300">Route path</span>
      </div>
    </div>
  );
}

// ── Summary stat cards ──
function SummaryStrip({ data }) {
  if (!data) return null;
  const s = data.summary || {};
  const pb = data.priority_breakdown || {};
  const items = [
    { icon: Route, value: s.total_distance_km || 0, unit: 'km', color: 'text-indigo-400' },
    { icon: Clock, value: s.total_estimated_minutes || 0, unit: 'min', color: 'text-amber-400' },
    { icon: MapPin, value: s.total_zones || 0, unit: 'zones', color: 'text-emerald-400' },
    { icon: AlertTriangle, value: pb.critical || 0, unit: 'critical', color: 'text-red-400' },
  ];
  return (
    <div data-testid="patrol-summary-panel" className="grid grid-cols-4 gap-2">
      {items.map((it, i) => (
        <div key={i} className="bg-slate-800/60 border border-slate-700/50 rounded-lg p-2 text-center">
          <it.icon className={`w-4 h-4 ${it.color} mx-auto mb-0.5`} />
          <div className="text-base font-bold text-slate-200">{it.value}</div>
          <div className="text-[9px] text-slate-500 uppercase">{it.unit}</div>
        </div>
      ))}
    </div>
  );
}

// ── Weights bar ──
function WeightsBar() {
  const items = [
    { label: 'Forecast 30%', color: 'bg-red-400', w: 30 },
    { label: 'Trend 25%', color: 'bg-orange-400', w: 25 },
    { label: 'Activity 20%', color: 'bg-yellow-400', w: 20 },
    { label: 'Learning 15%', color: 'bg-purple-400', w: 15 },
    { label: 'Temporal 10%', color: 'bg-cyan-400', w: 10 },
  ];
  return (
    <div>
      <div className="flex gap-0.5 h-2 rounded-full overflow-hidden">
        {items.map((it) => (
          <div key={it.label} className={`${it.color} h-full`} style={{ width: `${it.w}%` }} title={it.label} />
        ))}
      </div>
      <div className="flex justify-between text-[8px] text-slate-600 mt-0.5">
        {items.map((it) => <span key={it.label}>{it.label}</span>)}
      </div>
    </div>
  );
}

// ── Main Dashboard ──
export default function PatrolAIDashboard() {
  const [shift, setShift] = useState('morning');
  const [maxZones, setMaxZones] = useState(10);
  const [dwellMinutes, setDwellMinutes] = useState(10);
  const [loading, setLoading] = useState(false);
  const [routeData, setRouteData] = useState(null);
  const [expandedZone, setExpandedZone] = useState(null);
  const [selectedZone, setSelectedZone] = useState(null);
  const [useHeatmap, setUseHeatmap] = useState(false);
  const [heatmapCells, setHeatmapCells] = useState([]);

  const generateRoute = useCallback(async () => {
    setLoading(true);
    setSelectedZone(null);
    setExpandedZone(null);
    try {
      // If heatmap-enhanced, also fetch heatmap cells for overlay
      let heatCells = [];
      if (useHeatmap) {
        try {
          const { data: hm } = await operatorApi.getCityHeatmap();
          heatCells = hm.cells || [];
        } catch {}
      }
      setHeatmapCells(heatCells);

      const { data } = await operatorApi.generatePatrolRoute({
        shift,
        max_zones: maxZones,
        dwell_minutes: dwellMinutes,
        use_heatmap: useHeatmap,
      });
      setRouteData(data);
      if (data.route?.length > 0) {
        const hmLabel = data.heatmap_enhanced ? ' [Heatmap Enhanced]' : '';
        toast.success(`Route: ${data.route.length} stops, ${data.summary?.total_distance_km || 0} km, ~${data.summary?.total_estimated_minutes || 0} min${hmLabel}`);
      } else {
        toast.info('No hotspot zones available.');
      }
    } catch (err) {
      toast.error('Failed to generate patrol route');
    } finally {
      setLoading(false);
    }
  }, [shift, maxZones, dwellMinutes, useHeatmap]);

  // Map bounds
  const mapBounds = useMemo(() => {
    if (!routeData?.route?.length) return null;
    const points = routeData.route.map((z) => [z.lat, z.lng]);
    if (routeData.start_position) {
      points.push([routeData.start_position.lat, routeData.start_position.lng]);
    }
    return points;
  }, [routeData]);

  // Route polyline
  const polylinePath = useMemo(() => {
    if (!routeData?.route_geometry?.polyline) return [];
    return routeData.route_geometry.polyline;
  }, [routeData]);

  // Selected zone position for flyTo
  const selectedPosition = useMemo(() => {
    if (!selectedZone || !routeData?.route) return null;
    const z = routeData.route.find((r) => r.zone_id === selectedZone);
    return z ? [z.lat, z.lng] : null;
  }, [selectedZone, routeData]);

  const hasRoute = routeData?.route?.length > 0;

  return (
    <div data-testid="patrol-ai-dashboard" className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Navigation className="w-6 h-6 text-indigo-400" />
        <div>
          <h1 className="text-xl font-bold text-slate-100">Patrol Routing AI</h1>
          <p className="text-xs text-slate-500">Composite AI scoring + TSP route optimization</p>
        </div>
      </div>

      {/* Controls row */}
      <Card data-testid="patrol-controls" className="bg-slate-900/50 border-slate-700/60">
        <CardContent className="p-3">
          <div className="flex items-end gap-3 flex-wrap">
            <div className="w-44">
              <label className="text-[10px] text-slate-500 mb-1 block">SHIFT</label>
              <Select value={shift} onValueChange={setShift}>
                <SelectTrigger data-testid="patrol-shift-trigger" className="bg-slate-800 border-slate-700 text-slate-200 h-9 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="morning">Morning (06-14)</SelectItem>
                  <SelectItem value="afternoon">Afternoon (14-22)</SelectItem>
                  <SelectItem value="night">Night (22-06)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="w-36">
              <label className="text-[10px] text-slate-500 mb-1 block">MAX ZONES: {maxZones}</label>
              <Slider data-testid="patrol-max-zones-slider" value={[maxZones]} onValueChange={([v]) => setMaxZones(v)} min={3} max={20} step={1} />
            </div>
            <div className="w-36">
              <label className="text-[10px] text-slate-500 mb-1 block">DWELL: {dwellMinutes} min</label>
              <Slider data-testid="patrol-dwell-slider" value={[dwellMinutes]} onValueChange={([v]) => setDwellMinutes(v)} min={5} max={30} step={5} />
            </div>
            <div className="flex-1 min-w-[120px]">
              <WeightsBar />
            </div>
            <div className="flex items-center gap-2 border-l border-slate-700/40 pl-3">
              <Switch
                data-testid="patrol-heatmap-toggle"
                checked={useHeatmap}
                onCheckedChange={setUseHeatmap}
              />
              <label className="text-[10px] text-slate-400 flex items-center gap-1 cursor-pointer" onClick={() => setUseHeatmap(!useHeatmap)}>
                <Flame className={`w-3 h-3 ${useHeatmap ? 'text-amber-400' : 'text-slate-600'}`} />
                Heatmap
              </label>
            </div>
            <Button
              data-testid="patrol-generate-btn"
              onClick={generateRoute}
              disabled={loading}
              className="bg-indigo-600 hover:bg-indigo-500 text-white h-9 px-5 text-xs"
            >
              {loading ? (
                <span className="flex items-center gap-1.5">
                  <span className="animate-spin h-3.5 w-3.5 border-2 border-white/30 border-t-white rounded-full" />
                  Generating...
                </span>
              ) : (
                <span className="flex items-center gap-1.5">
                  <Play className="w-3.5 h-3.5" />
                  Generate
                </span>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Results: Summary + Split Layout */}
      {hasRoute && (
        <>
          <SummaryStrip data={routeData} />

          {/* Score stats */}
          <div className="flex items-center gap-3 text-[10px] text-slate-500 px-1">
            <span>Avg: <span className="text-amber-400 font-medium">{routeData.summary.avg_composite_score}</span></span>
            <span>Max: <span className="text-red-400 font-medium">{routeData.summary.max_composite_score}</span></span>
            <span>Min: <span className="text-emerald-400 font-medium">{routeData.summary.min_composite_score}</span></span>
            <span className="text-slate-700">|</span>
            <span>{routeData.total_zones_analyzed} analyzed, {routeData.zones_selected} selected</span>
            <span className="text-slate-700">|</span>
            <span>{routeData.shift_label}</span>
          </div>

          {/* Split: Zone List + Map */}
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-4" style={{ minHeight: '500px' }}>
            {/* Left: Zone list */}
            <div className="lg:col-span-2 space-y-2 overflow-y-auto" style={{ maxHeight: '580px' }} data-testid="patrol-route-list">
              <div className="text-xs text-slate-400 font-medium flex items-center gap-1.5 mb-1">
                <Route className="w-3.5 h-3.5 text-indigo-400" />
                Patrol Route ({routeData.route.length} stops)
              </div>
              {routeData.route.map((zone) => (
                <ZoneCard
                  key={zone.zone_id}
                  zone={zone}
                  expanded={expandedZone === zone.zone_id}
                  onToggle={() => setExpandedZone(expandedZone === zone.zone_id ? null : zone.zone_id)}
                  selected={selectedZone === zone.zone_id}
                  onSelect={() => setSelectedZone(selectedZone === zone.zone_id ? null : zone.zone_id)}
                />
              ))}
            </div>

            {/* Right: Map */}
            <div className="lg:col-span-3 relative rounded-lg overflow-hidden border border-slate-700/50" data-testid="patrol-route-map">
              <MapContainer
                center={[routeData.start_position?.lat || 0, routeData.start_position?.lng || 0]}
                zoom={13}
                style={{ height: '580px', width: '100%', background: '#0f172a' }}
                zoomControl={false}
              >
                <TileLayer
                  url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
                  attribution='&copy; CartoDB'
                />

                {/* Auto fit bounds */}
                <FitBounds bounds={mapBounds} />

                {/* Fly to selected */}
                {selectedPosition && <FlyToStop position={selectedPosition} />}

                {/* Heatmap overlay (when enhanced mode is active) */}
                {useHeatmap && heatmapCells.length > 0 && (
                  <PatrolHeatLayer cells={heatmapCells} />
                )}

                {/* Route polyline */}
                {polylinePath.length > 1 && (
                  <>
                    {/* Glow line */}
                    <Polyline
                      positions={polylinePath}
                      pathOptions={{ color: '#6366f1', weight: 6, opacity: 0.25 }}
                    />
                    {/* Main line */}
                    <Polyline
                      positions={polylinePath}
                      pathOptions={{ color: '#818cf8', weight: 3, opacity: 0.8, dashArray: '8, 6' }}
                    />
                  </>
                )}

                {/* Zone radius circles */}
                {routeData.route.map((zone) => (
                  <CircleMarker
                    key={`radius-${zone.zone_id}`}
                    center={[zone.lat, zone.lng]}
                    radius={12}
                    pathOptions={{
                      color: PRIORITY_HEX[zone.patrol_priority],
                      fillColor: PRIORITY_HEX[zone.patrol_priority],
                      fillOpacity: 0.08,
                      weight: 1,
                      opacity: 0.3,
                    }}
                  />
                ))}

                {/* Start marker */}
                {routeData.start_position && (
                  <Marker
                    position={[routeData.start_position.lat, routeData.start_position.lng]}
                    icon={startIcon()}
                  >
                    <Popup className="patrol-popup">
                      <div className="text-xs font-medium">Patrol Start</div>
                    </Popup>
                  </Marker>
                )}

                {/* Stop markers */}
                {routeData.route.map((zone) => {
                  const bd = zone.score_breakdown || {};
                  return (
                    <Marker
                      key={zone.zone_id}
                      position={[zone.lat, zone.lng]}
                      icon={stopIcon(zone.stop_number, zone.patrol_priority, selectedZone === zone.zone_id)}
                      eventHandlers={{
                        click: () => setSelectedZone(selectedZone === zone.zone_id ? null : zone.zone_id),
                      }}
                    >
                      <Popup className="patrol-popup" maxWidth={280}>
                        <div className="text-xs space-y-1.5" style={{ minWidth: '200px' }}>
                          <div className="flex items-center justify-between">
                            <span className="font-bold text-sm">Stop #{zone.stop_number}</span>
                            <span className="font-bold text-amber-600">{zone.composite_score.toFixed(1)}</span>
                          </div>
                          <div className="font-medium text-slate-700">{zone.zone_name}</div>
                          <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px] mt-1 pt-1 border-t border-slate-200">
                            <span className="text-slate-500">Forecast:</span>
                            <span className="font-medium text-red-600">{bd.forecast?.toFixed(1) || '—'}</span>
                            <span className="text-slate-500">Activity:</span>
                            <span className="font-medium text-yellow-600">{bd.activity?.toFixed(1) || '—'}</span>
                            <span className="text-slate-500">Trend:</span>
                            <span className="font-medium text-orange-600">{bd.trend_status || '—'}</span>
                            <span className="text-slate-500">Dwell:</span>
                            <span className="font-medium">{dwellMinutes} min</span>
                            <span className="text-slate-500">Priority:</span>
                            <span className="font-medium capitalize" style={{ color: PRIORITY_HEX[zone.patrol_priority] }}>{zone.patrol_priority}</span>
                            <span className="text-slate-500">Incidents:</span>
                            <span className="font-medium">{zone.incident_count}</span>
                          </div>
                          {zone.recommendation?.action && (
                            <div className="text-[10px] bg-amber-50 rounded p-1.5 mt-1">
                              <span className="font-medium text-amber-700">{zone.recommendation.action}</span>
                            </div>
                          )}
                        </div>
                      </Popup>
                    </Marker>
                  );
                })}
              </MapContainer>

              {/* Map Legend */}
              <MapLegend />

              {/* Map overlay summary */}
              <div className="absolute top-3 right-3 z-[1000] bg-slate-900/85 backdrop-blur-sm border border-slate-700/60 rounded-lg p-2.5 text-xs">
                <div className="flex items-center gap-2 text-slate-300">
                  <Route className="w-3.5 h-3.5 text-indigo-400" />
                  <span className="font-medium">{routeData.summary.total_distance_km} km</span>
                  <span className="text-slate-600">|</span>
                  <Clock className="w-3.5 h-3.5 text-amber-400" />
                  <span className="font-medium">~{routeData.summary.total_estimated_minutes} min</span>
                  <span className="text-slate-600">|</span>
                  <span className="font-medium">{routeData.route.length} stops</span>
                  {routeData.heatmap_enhanced && (
                    <>
                      <span className="text-slate-600">|</span>
                      <Flame className="w-3.5 h-3.5 text-amber-400" />
                      <span className="text-amber-400 font-medium">Heatmap</span>
                    </>
                  )}
                </div>
              </div>

              {/* Focus route button */}
              {selectedZone && (
                <button
                  data-testid="patrol-focus-route-btn"
                  onClick={() => setSelectedZone(null)}
                  className="absolute top-3 left-4 z-[1000] bg-indigo-600/90 hover:bg-indigo-500 text-white text-xs px-3 py-1.5 rounded-md flex items-center gap-1.5 transition-colors"
                >
                  <Eye className="w-3 h-3" />
                  Show full route
                </button>
              )}
            </div>
          </div>
        </>
      )}

      {/* Empty state */}
      {!hasRoute && !loading && (
        <Card className="bg-slate-900/50 border-slate-700/60">
          <CardContent className="py-16 text-center">
            <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-indigo-600/10 border border-indigo-500/20 flex items-center justify-center">
              <Navigation className="w-8 h-8 text-indigo-500/50" />
            </div>
            <h3 className="text-base font-medium text-slate-300 mb-1">Generate a Patrol Route</h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto">
              Configure shift and parameters above, then click Generate.
              The AI analyzes all hotspot zones using forecast, trend, activity, and learning signals
              to create an optimized patrol path.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Loading state on map area */}
      {loading && (
        <Card className="bg-slate-900/50 border-slate-700/60">
          <CardContent className="py-16 text-center">
            <div className="animate-spin h-8 w-8 border-3 border-indigo-500/30 border-t-indigo-400 rounded-full mx-auto mb-3" />
            <p className="text-sm text-slate-400">Scoring zones across 5 AI engines...</p>
            <p className="text-xs text-slate-600 mt-1">Forecast + Trend + Activity + Learning + Temporal</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
