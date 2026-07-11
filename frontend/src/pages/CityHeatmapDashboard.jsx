import React, { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet.heat';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Switch } from '../components/ui/switch';
import { operatorApi } from '../api';
import { toast } from 'sonner';
import {
  Globe, TrendingUp, Activity, Brain, Navigation, Shield,
  AlertTriangle, Eye, RefreshCw, Layers, MapPin, BarChart3,
  Zap, Users, Moon, ArrowUpRight, ArrowDownRight, Clock, Radio,
} from 'lucide-react';

// Fix Leaflet icons
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

const RISK_COLORS = {
  critical: '#dc2626', high: '#f97316', moderate: '#eab308', safe: '#22c55e',
};

const SIGNAL_CONFIG = {
  composite: { label: 'Composite', icon: Globe, color: '#818cf8', field: 'composite_score' },
  forecast: { label: 'Forecast', icon: TrendingUp, color: '#ef4444', field: 'forecast' },
  hotspot: { label: 'Hotspot', icon: MapPin, color: '#f97316', field: 'hotspot' },
  trend: { label: 'Trend', icon: BarChart3, color: '#eab308', field: 'trend' },
  activity: { label: 'Activity', icon: Activity, color: '#a855f7', field: 'activity' },
  patrol: { label: 'Patrol', icon: Navigation, color: '#06b6d4', field: 'patrol' },
  environment: { label: 'Environment', icon: Moon, color: '#64748b', field: 'environment' },
  session_density: { label: 'Sessions', icon: Users, color: '#14b8a6', field: 'session_density' },
  mobility_anomaly: { label: 'Anomaly', icon: Zap, color: '#f43f5e', field: 'mobility_anomaly' },
};

const HEAT_GRADIENT = { 0.1: '#16a34a', 0.25: '#65a30d', 0.4: '#eab308', 0.55: '#ea580c', 0.7: '#dc2626', 0.85: '#991b1b', 1.0: '#7f1d1d' };

// ── Heat Layer ──
function HeatLayer({ points, signal }) {
  const map = useMap();
  const layerRef = useRef(null);

  useEffect(() => {
    if (layerRef.current) {
      map.removeLayer(layerRef.current);
      layerRef.current = null;
    }
    if (!points?.length) return;

    const field = SIGNAL_CONFIG[signal]?.field || 'composite_score';
    const heatPoints = points
      .filter(p => p[field] > 0)
      .map(p => [p.lat, p.lng, Math.max(0.15, p[field] / 10.0)]);

    if (!heatPoints.length) return;

    const heat = L.heatLayer(heatPoints, {
      radius: 35, blur: 25, maxZoom: 16, max: 1.0, minOpacity: 0.5, gradient: HEAT_GRADIENT,
    });
    heat.addTo(map);
    layerRef.current = heat;
    return () => { if (layerRef.current) map.removeLayer(layerRef.current); };
  }, [map, points, signal]);

  return null;
}

// ── Auto-fit bounds ──
function FitBounds({ bounds }) {
  const map = useMap();
  const appliedRef = useRef(false);
  useEffect(() => {
    if (!bounds || appliedRef.current) return;
    appliedRef.current = true;
    map.invalidateSize();
    map.fitBounds(
      [[bounds.min_lat, bounds.min_lng], [bounds.max_lat, bounds.max_lng]],
      { padding: [30, 30], maxZoom: 15, animate: false }
    );
  }, [bounds, map]);
  return null;
}

// ── Map click handler ──
function MapClickHandler({ cells, onCellClick }) {
  const map = useMap();
  useEffect(() => {
    const handler = (e) => {
      const { lat, lng } = e.latlng;
      let nearest = null, minDist = Infinity;
      for (const cell of cells) {
        const d = Math.sqrt((cell.lat - lat) ** 2 + (cell.lng - lng) ** 2);
        if (d < minDist && d < 0.003) { minDist = d; nearest = cell; }
      }
      if (nearest) onCellClick(nearest);
    };
    map.on('click', handler);
    return () => map.off('click', handler);
  }, [map, cells, onCellClick]);
  return null;
}

// ── Signal Toggle ──
function SignalToggle({ signalKey, active, onChange }) {
  const cfg = SIGNAL_CONFIG[signalKey];
  const Icon = cfg.icon;
  return (
    <button
      data-testid={`heatmap-toggle-${signalKey}`}
      onClick={() => onChange(signalKey)}
      className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-xs transition-all ${
        active
          ? 'bg-slate-700/80 text-white border border-slate-600/60'
          : 'bg-slate-800/40 text-slate-500 border border-slate-700/30 hover:text-slate-400'
      }`}
    >
      <div className="w-2 h-2 rounded-full" style={{ background: active ? cfg.color : '#475569' }} />
      <Icon className="w-3 h-3" />
      <span>{cfg.label}</span>
    </button>
  );
}

// ── Stats Panel ──
function StatsPanel({ stats, totalCells, data }) {
  if (!stats) return null;
  const items = [
    { label: 'Critical', value: stats.critical, color: RISK_COLORS.critical, icon: AlertTriangle },
    { label: 'High Risk', value: stats.high, color: RISK_COLORS.high, icon: Shield },
    { label: 'Moderate', value: stats.moderate, color: RISK_COLORS.moderate, icon: Eye },
    { label: 'Safe', value: stats.safe, color: RISK_COLORS.safe, icon: Globe },
  ];
  return (
    <div data-testid="heatmap-stats-panel" className="space-y-2">
      <div className="text-[10px] text-slate-500 font-medium uppercase tracking-wider">City Risk Overview</div>
      {items.map(({ label, value, color, icon: Icon }) => (
        <div key={label} className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Icon className="w-3 h-3" style={{ color }} />
            <span className="text-[10px] text-slate-400">{label}</span>
          </div>
          <span className="text-xs font-semibold" style={{ color }}>{value}</span>
        </div>
      ))}
      <div className="pt-2 border-t border-slate-700/40 space-y-1">
        <div className="flex items-center justify-between text-[10px]">
          <span className="text-slate-500">Active Cells</span>
          <span className="text-slate-400">{totalCells}</span>
        </div>
        {data?.active_sessions !== undefined && (
          <div className="flex items-center justify-between text-[10px]">
            <span className="text-slate-500">Live Sessions</span>
            <span className="text-teal-400">{data.active_sessions}</span>
          </div>
        )}
        {data?.incident_velocity !== undefined && (
          <div className="flex items-center justify-between text-[10px]">
            <span className="text-slate-500">Incident Velocity</span>
            <span className={data.incident_velocity > 1.3 ? 'text-red-400' : 'text-slate-400'}>
              {data.incident_velocity}x
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Delta Panel ──
function DeltaPanel({ delta }) {
  if (!delta || (delta.escalated_count === 0 && delta.de_escalated_count === 0 && delta.new_hotspot_count === 0)) {
    return null;
  }
  return (
    <Card className="bg-slate-900/50 border-slate-700/60" data-testid="heatmap-delta-panel">
      <CardContent className="p-3 space-y-2">
        <div className="text-[10px] text-slate-500 font-medium uppercase tracking-wider">Risk Changes</div>
        {delta.escalated_count > 0 && (
          <div className="flex items-center gap-2 text-xs">
            <ArrowUpRight className="w-3.5 h-3.5 text-red-400" />
            <span className="text-red-400 font-medium">{delta.escalated_count} escalated</span>
          </div>
        )}
        {delta.de_escalated_count > 0 && (
          <div className="flex items-center gap-2 text-xs">
            <ArrowDownRight className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-emerald-400 font-medium">{delta.de_escalated_count} de-escalated</span>
          </div>
        )}
        {delta.new_hotspot_count > 0 && (
          <div className="flex items-center gap-2 text-xs">
            <Zap className="w-3.5 h-3.5 text-amber-400" />
            <span className="text-amber-400 font-medium">{delta.new_hotspot_count} new hotspots</span>
          </div>
        )}
        {delta.cooling_count > 0 && (
          <div className="flex items-center gap-2 text-xs">
            <Shield className="w-3.5 h-3.5 text-blue-400" />
            <span className="text-blue-400 font-medium">{delta.cooling_count} cooling</span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Timeline Scrubber ──
function TimelineScrubber({ timeline }) {
  if (!timeline || timeline.length < 2) return null;
  return (
    <Card className="bg-slate-900/50 border-slate-700/60" data-testid="heatmap-timeline">
      <CardContent className="p-3 space-y-2">
        <div className="text-[10px] text-slate-500 font-medium uppercase tracking-wider flex items-center gap-1.5">
          <Clock className="w-3 h-3" /> Risk Timeline
        </div>
        <div className="space-y-1 max-h-[200px] overflow-y-auto">
          {timeline.map((t, i) => (
            <div key={i} className="flex items-center gap-2 text-[10px] py-1 border-b border-slate-800/40 last:border-0">
              <span className="text-slate-500 w-14 flex-shrink-0">
                {t.analyzed_at ? new Date(t.analyzed_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '--'}
              </span>
              <span className="text-slate-400">{t.total_cells} cells</span>
              {t.delta_summary?.escalated > 0 && (
                <span className="text-red-400 flex items-center gap-0.5">
                  <ArrowUpRight className="w-2.5 h-2.5" />{t.delta_summary.escalated}
                </span>
              )}
              {t.delta_summary?.de_escalated > 0 && (
                <span className="text-emerald-400 flex items-center gap-0.5">
                  <ArrowDownRight className="w-2.5 h-2.5" />{t.delta_summary.de_escalated}
                </span>
              )}
              <span className="text-slate-600 ml-auto">{t.computation_time_ms}ms</span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

// ── Cell Detail Panel ──
function CellDetail({ cell, onClose }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!cell) return;
    setLoading(true);
    operatorApi.getCityHeatmapCell(cell.grid_id)
      .then(({ data }) => setDetail(data))
      .catch(() => {
        setDetail({
          grid_id: cell.grid_id, lat: cell.lat, lng: cell.lng,
          composite_score: cell.composite_score, risk_level: cell.risk_level,
          signals: Object.entries(SIGNAL_CONFIG).filter(([k]) => k !== 'composite').map(([k, v]) => ({
            name: v.label, score: cell[v.field] || 0,
          })),
          dominant_signal: 'N/A', recommendations: ['Unable to load detailed analysis'],
        });
      })
      .finally(() => setLoading(false));
  }, [cell]);

  if (!cell) return null;

  return (
    <div data-testid="heatmap-cell-detail"
      className="absolute bottom-4 right-4 z-[1000] w-80 bg-slate-900/95 backdrop-blur-sm border border-slate-700/60 rounded-lg shadow-2xl overflow-hidden">
      <div className="flex items-center justify-between p-3 border-b border-slate-700/40">
        <div>
          <div className="text-xs font-medium text-slate-300">Grid Cell {cell.grid_id}</div>
          <div className="text-[10px] text-slate-500">{cell.lat.toFixed(5)}, {cell.lng.toFixed(5)}</div>
        </div>
        <div className="flex items-center gap-2">
          <div className="text-lg font-bold" style={{ color: RISK_COLORS[cell.risk_level] || '#818cf8' }}>
            {cell.composite_score}
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300 text-lg">&times;</button>
        </div>
      </div>

      {loading ? (
        <div className="p-4 text-center text-xs text-slate-500">Loading...</div>
      ) : detail ? (
        <div className="p-3 space-y-2">
          <div className="flex items-center justify-between text-[10px]">
            <span className="text-slate-500 font-medium uppercase">Signal Breakdown</span>
            {detail.weight_profile && (
              <Badge className="bg-indigo-500/20 text-indigo-300 text-[9px]">{detail.weight_profile}</Badge>
            )}
          </div>
          {detail.signals?.map((sig) => {
            const pct = Math.min(100, (sig.score / 10) * 100);
            return (
              <div key={sig.name || sig.key} className="space-y-0.5">
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-slate-400">{sig.name}</span>
                  <span className="text-slate-300 font-medium">{sig.score?.toFixed(1)}</span>
                </div>
                <div className="h-1 bg-slate-700/50 rounded-full overflow-hidden">
                  <div className="h-full rounded-full transition-all" style={{
                    width: `${pct}%`,
                    background: pct > 70 ? '#ef4444' : pct > 50 ? '#f97316' : pct > 30 ? '#eab308' : '#22c55e',
                  }} />
                </div>
              </div>
            );
          })}
          {detail.dominant_signal && (
            <div className="pt-2 border-t border-slate-700/40 text-[10px]">
              <span className="text-slate-500">Dominant: </span>
              <span className="text-indigo-400 font-medium">{detail.dominant_signal}</span>
            </div>
          )}
          {detail.recommendations?.length > 0 && (
            <div className="pt-1 space-y-1">
              {detail.recommendations.map((r, i) => (
                <div key={i} className="text-[10px] text-amber-400/80 flex gap-1.5">
                  <AlertTriangle className="w-3 h-3 flex-shrink-0 mt-0.5" />
                  <span>{r}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

// ── Intensity Legend ──
function IntensityLegend() {
  return (
    <div data-testid="heatmap-legend"
      className="absolute bottom-4 left-4 z-[1000] bg-slate-900/90 backdrop-blur-sm border border-slate-700/60 rounded-lg p-3">
      <div className="text-[10px] text-slate-400 font-medium mb-2">Risk Intensity</div>
      <div className="flex items-center gap-1">
        <span className="text-[9px] text-slate-500">Safe</span>
        <div className="w-32 h-2.5 rounded-full" style={{
          background: 'linear-gradient(to right, #22c55e, #84cc16, #eab308, #f97316, #dc2626, #7f1d1d)',
        }} />
        <span className="text-[9px] text-slate-500">Critical</span>
      </div>
    </div>
  );
}

// ── LIVE Indicator ──
function LiveIndicator({ data, autoRefresh }) {
  if (!data) return null;
  const analyzedAt = data.analyzed_at ? new Date(data.analyzed_at) : null;
  const timeStr = analyzedAt?.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) || '--';

  return (
    <div data-testid="heatmap-live-indicator"
      className="absolute top-3 right-3 z-[1000] bg-slate-900/90 backdrop-blur-sm border border-slate-700/60 rounded-lg px-3 py-2 space-y-1">
      <div className="flex items-center gap-2 text-xs">
        {autoRefresh && (
          <span className="flex items-center gap-1.5">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
            </span>
            <span className="text-emerald-400 font-bold text-[10px] uppercase">Live</span>
          </span>
        )}
        <span className="text-slate-400">{data.total_cells} cells</span>
        <span className="text-slate-600">|</span>
        <span className="text-red-400">{data.stats?.critical || 0} critical</span>
      </div>
      <div className="flex items-center gap-2 text-[10px] text-slate-500">
        <Clock className="w-3 h-3" />
        <span>Updated: {timeStr}</span>
        <span className="text-slate-600">|</span>
        <span>{data.weight_profile}</span>
        <span className="text-slate-600">|</span>
        <span>{data.computation_time_ms}ms</span>
      </div>
    </div>
  );
}

// ── Main Dashboard ──
export default function CityHeatmapDashboard() {
  const [loading, setLoading] = useState(false);
  const [heatmapData, setHeatmapData] = useState(null);
  const [activeSignal, setActiveSignal] = useState('composite');
  const [selectedCell, setSelectedCell] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [delta, setDelta] = useState(null);
  const [timeline, setTimeline] = useState([]);
  const refreshRef = useRef(null);

  const loadLive = useCallback(async (showToast = false) => {
    try {
      const [heatRes, deltaRes, timelineRes] = await Promise.all([
        operatorApi.getCityHeatmapLive(),
        operatorApi.getCityHeatmapDelta(),
        operatorApi.getCityHeatmapTimeline(),
      ]);
      setHeatmapData(heatRes.data);
      setDelta(deltaRes.data);
      setTimeline(timelineRes.data.timeline || []);
      if (showToast && heatRes.data.total_cells > 0) {
        toast.success(`Live heatmap: ${heatRes.data.total_cells} cells, ${heatRes.data.stats?.critical || 0} critical`);
      }
    } catch (err) {
      // Fall back to compute on demand
      try {
        const { data } = await operatorApi.getCityHeatmap();
        setHeatmapData(data);
        setDelta(data.delta || null);
      } catch {
        toast.error('Failed to load heatmap');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const loadFull = useCallback(async () => {
    setLoading(true);
    setSelectedCell(null);
    await loadLive(true);
  }, [loadLive]);

  // Initial load
  useEffect(() => { loadFull(); }, [loadFull]);

  // Auto-refresh every 30s
  useEffect(() => {
    if (autoRefresh) {
      refreshRef.current = setInterval(() => loadLive(false), 30000);
    }
    return () => { if (refreshRef.current) clearInterval(refreshRef.current); };
  }, [autoRefresh, loadLive]);

  const cells = heatmapData?.cells || [];
  const stats = heatmapData?.stats;
  const bounds = heatmapData?.bounds;
  const hasCells = cells.length > 0;

  const mapCenter = useMemo(() => {
    if (bounds) return [(bounds.min_lat + bounds.max_lat) / 2, (bounds.min_lng + bounds.max_lng) / 2];
    return [12.97, 77.59];
  }, [bounds]);

  const markerCells = useMemo(() => {
    return cells.filter(c => c.risk_level === 'critical' || c.risk_level === 'high');
  }, [cells]);

  return (
    <div data-testid="city-heatmap-dashboard" className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <Globe className="w-6 h-6 text-indigo-400" />
          <div>
            <h1 className="text-xl font-bold text-slate-100">Dynamic City Risk Engine</h1>
            <p className="text-xs text-slate-500">
              8 AI signals &middot; auto-refresh every 5 min &middot; adaptive weights
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {/* Auto-refresh toggle */}
          <div className="flex items-center gap-2" data-testid="heatmap-auto-refresh-toggle">
            <Radio className={`w-3.5 h-3.5 ${autoRefresh ? 'text-emerald-400' : 'text-slate-600'}`} />
            <span className="text-[10px] text-slate-400">Auto-refresh</span>
            <Switch checked={autoRefresh} onCheckedChange={setAutoRefresh} />
          </div>
          <Button
            data-testid="heatmap-refresh-btn"
            onClick={loadFull} disabled={loading}
            variant="outline" size="sm"
            className="border-slate-700 text-slate-300 hover:bg-slate-800 text-xs"
          >
            {loading ? (
              <span className="flex items-center gap-1.5">
                <span className="animate-spin h-3 w-3 border-2 border-slate-400/30 border-t-slate-400 rounded-full" />
                Loading...
              </span>
            ) : (
              <span className="flex items-center gap-1.5"><RefreshCw className="w-3 h-3" />Refresh</span>
            )}
          </Button>
        </div>
      </div>

      {/* Signal Toggles */}
      <div className="flex items-center gap-2 flex-wrap">
        <Layers className="w-4 h-4 text-slate-500" />
        {Object.keys(SIGNAL_CONFIG).map((key) => (
          <SignalToggle key={key} signalKey={key} active={activeSignal === key} onChange={setActiveSignal} />
        ))}
      </div>

      {/* Main content: Map + Stats sidebar */}
      {hasCells && (
        <div className="grid grid-cols-1 lg:grid-cols-6 gap-4" style={{ minHeight: '560px' }}>
          {/* Left: Stats + Delta + Timeline */}
          <div className="lg:col-span-1 space-y-3">
            <Card className="bg-slate-900/50 border-slate-700/60">
              <CardContent className="p-3">
                <StatsPanel stats={stats} totalCells={heatmapData.total_cells} data={heatmapData} />
              </CardContent>
            </Card>

            <DeltaPanel delta={delta} />
            <TimelineScrubber timeline={timeline} />

            {/* Info card */}
            <Card className="bg-slate-900/50 border-slate-700/60">
              <CardContent className="p-3 space-y-1.5">
                <div className="text-[10px] text-slate-500 font-medium uppercase tracking-wider">Engine Info</div>
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-slate-500">Cell Size</span>
                  <span className="text-slate-300">{heatmapData.grid_size_m}m</span>
                </div>
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-slate-500">Zones</span>
                  <span className="text-slate-300">{heatmapData.total_zones}</span>
                </div>
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-slate-500">Incidents (30d)</span>
                  <span className="text-slate-300">{heatmapData.total_incidents_analyzed}</span>
                </div>
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-slate-500">Weight Profile</span>
                  <Badge className="bg-indigo-500/20 text-indigo-300 border-indigo-500/30 text-[9px] capitalize">
                    {heatmapData.weight_profile}
                  </Badge>
                </div>
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-slate-500">Signal</span>
                  <Badge className="bg-indigo-500/20 text-indigo-300 border-indigo-500/30 text-[9px] capitalize">{activeSignal}</Badge>
                </div>
                <div className="pt-2 border-t border-slate-700/40 text-[9px] text-slate-600">
                  Click any hot area on the map to inspect its 8-signal breakdown.
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Right: Map */}
          <div className="lg:col-span-5 relative rounded-lg overflow-hidden border border-slate-700/50" data-testid="heatmap-map">
            <MapContainer
              center={mapCenter} zoom={14}
              style={{ height: '560px', width: '100%', background: '#0f172a' }}
              zoomControl={false}
            >
              <TileLayer url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" attribution='&copy; CartoDB' />
              <FitBounds bounds={bounds} />
              <HeatLayer points={cells} signal={activeSignal} />
              <MapClickHandler cells={cells} onCellClick={setSelectedCell} />

              {markerCells.map((cell) => (
                <CircleMarker key={cell.grid_id} center={[cell.lat, cell.lng]} radius={4}
                  pathOptions={{
                    color: RISK_COLORS[cell.risk_level], fillColor: RISK_COLORS[cell.risk_level],
                    fillOpacity: 0.6, weight: 1, opacity: 0.8,
                  }}
                  eventHandlers={{ click: () => setSelectedCell(cell) }}
                >
                  <Popup maxWidth={200}>
                    <div className="text-xs">
                      <div className="font-bold">{cell.grid_id}</div>
                      <div>Score: {cell.composite_score}</div>
                      <div className="capitalize">Risk: {cell.risk_level}</div>
                    </div>
                  </Popup>
                </CircleMarker>
              ))}
            </MapContainer>

            <IntensityLegend />
            <LiveIndicator data={heatmapData} autoRefresh={autoRefresh} />
            <CellDetail cell={selectedCell} onClose={() => setSelectedCell(null)} />
          </div>
        </div>
      )}

      {/* Loading state */}
      {loading && !hasCells && (
        <Card className="bg-slate-900/50 border-slate-700/60">
          <CardContent className="py-16 text-center">
            <div className="animate-spin h-8 w-8 border-3 border-indigo-500/30 border-t-indigo-400 rounded-full mx-auto mb-3" />
            <p className="text-sm text-slate-400">Computing city-scale risk intelligence...</p>
            <p className="text-xs text-slate-600 mt-1">Scoring grid cells across 8 AI signal layers</p>
          </CardContent>
        </Card>
      )}

      {/* Empty state */}
      {!hasCells && !loading && (
        <Card className="bg-slate-900/50 border-slate-700/60">
          <CardContent className="py-16 text-center">
            <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-indigo-600/10 border border-indigo-500/20 flex items-center justify-center">
              <Globe className="w-8 h-8 text-indigo-500/50" />
            </div>
            <h3 className="text-base font-medium text-slate-300 mb-1">No Heatmap Data</h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto">
              The Dynamic Risk Engine will auto-compute the heatmap every 5 minutes. Run Risk Learning first to generate hotspot zones.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
