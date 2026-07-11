import React, { useState, useCallback, useEffect, useRef } from 'react';
import { MapContainer, TileLayer, Polyline, CircleMarker, Marker, Popup, useMap, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { operatorApi } from '../api';
import { toast } from 'sonner';
import {
  Loader2, Route, Shield, AlertTriangle, Clock, MapPin,
  Navigation, Zap, ChevronRight, RotateCcw, ArrowRight, Radio, Eye,
  RefreshCw, ArrowRightLeft, TrendingDown, TrendingUp, Minus, Flame,
} from 'lucide-react';

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

const ROUTE_COLORS = {
  safest: '#22c55e',
  balanced: '#3b82f6',
  shortest: '#f97316',
  alternate: '#94a3b8',
};

const ROUTE_LABELS = {
  safest: { label: 'Safest Route', icon: Shield, bg: 'bg-green-50 border-green-200', text: 'text-green-700' },
  balanced: { label: 'Balanced Route', icon: Zap, bg: 'bg-blue-50 border-blue-200', text: 'text-blue-700' },
  shortest: { label: 'Shortest Route', icon: Clock, bg: 'bg-orange-50 border-orange-200', text: 'text-orange-700' },
  alternate: { label: 'Alternate Route', icon: Route, bg: 'bg-slate-50 border-slate-200', text: 'text-slate-700' },
};

function riskColor(score) {
  if (score >= 7) return '#dc2626';
  if (score >= 5) return '#f97316';
  if (score >= 3) return '#eab308';
  return '#22c55e';
}

function pinIcon(color, label) {
  return L.divIcon({
    className: 'route-pin',
    html: `<div style="background:${color};color:white;width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;border:2px solid white;box-shadow:0 2px 8px rgba(0,0,0,0.35)">${label}</div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 28],
  });
}

// ── Map click handler ──
function MapClickHandler({ onMapClick, mode }) {
  useMapEvents({
    click(e) {
      if (mode) onMapClick(e.latlng);
    },
  });
  return null;
}

function FitBounds({ bounds }) {
  const map = useMap();
  useEffect(() => {
    if (bounds) map.fitBounds(bounds, { padding: [40, 40] });
  }, [bounds, map]);
  return null;
}

// ── Route comparison card ──
function RouteCard({ route, selected, onSelect, recommended }) {
  const primary = route.label[0] || 'alternate';
  const cfg = ROUTE_LABELS[primary] || ROUTE_LABELS.alternate;
  const Icon = cfg.icon;
  const color = ROUTE_COLORS[primary] || ROUTE_COLORS.alternate;

  return (
    <div
      className={`border rounded-lg p-3 cursor-pointer transition-all ${
        selected ? `ring-2 ring-offset-1 ${cfg.bg}` : 'border-slate-200 hover:border-slate-300 bg-white'
      }`}
      style={selected ? { ringColor: color } : {}}
      onClick={() => onSelect(route.index)}
      data-testid={`route-card-${primary}`}
    >
      <div className="flex items-center gap-2 mb-2">
        <Icon className="w-4 h-4" style={{ color }} />
        <span className={`text-xs font-semibold ${cfg.text}`}>{cfg.label}</span>
        {recommended && (
          <Badge className="bg-green-100 text-green-700 border-green-200 text-[9px] ml-auto">Recommended</Badge>
        )}
      </div>

      <div className="grid grid-cols-4 gap-2 text-center">
        <div>
          <p className="text-lg font-bold text-slate-800">{route.distance_km}</p>
          <p className="text-[9px] text-slate-400">km</p>
        </div>
        <div>
          <p className="text-lg font-bold text-slate-800">{route.duration_min}</p>
          <p className="text-[9px] text-slate-400">min</p>
        </div>
        <div>
          <p className="text-lg font-bold" style={{ color: riskColor(route.route_risk_score) }}>
            {route.route_risk_score}
          </p>
          <p className="text-[9px] text-slate-400">risk</p>
        </div>
        <div>
          <p className="text-lg font-bold text-red-600">{route.dangerous_segments}</p>
          <p className="text-[9px] text-slate-400">danger</p>
        </div>
      </div>

      {selected && route.risk_reasons?.length > 0 && (
        <div className="mt-2 pt-2 border-t border-slate-100 space-y-0.5">
          {route.risk_reasons.slice(0, 4).map((r, i) => (
            <p key={i} className="text-[10px] text-slate-500 flex items-start gap-1">
              <AlertTriangle className="w-3 h-3 text-amber-400 shrink-0 mt-0.5" />{r}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main component ──
export function RouteSafetyIntelligence() {
  const [startPoint, setStartPoint] = useState(null);
  const [endPoint, setEndPoint] = useState(null);
  const [clickMode, setClickMode] = useState(null); // 'start' | 'end' | null
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedRoute, setSelectedRoute] = useState(null);
  const [devices, setDevices] = useState([]);
  const [selectedDevice, setSelectedDevice] = useState('');
  const [monitoring, setMonitoring] = useState(false);
  const [activeMonitors, setActiveMonitors] = useState([]);
  const [rerouteData, setRerouteData] = useState({}); // { deviceId: { loading, data } }
  const [riskUpdateData, setRiskUpdateData] = useState({}); // { deviceId: { loading, data } }

  // Default center (Bangalore)
  const center = [12.9716, 77.5946];

  // Fetch devices + active monitors on mount
  useEffect(() => {
    operatorApi.getDeviceHealth().then(r => {
      const devs = Array.isArray(r.data) ? r.data : [];
      setDevices(devs);
    }).catch(() => {});
    _refreshMonitors();
  }, []);

  const _refreshMonitors = () => {
    operatorApi.getActiveRouteMonitors().then(r => {
      setActiveMonitors(r.data?.monitors || []);
    }).catch(() => {});
  };

  const handleMapClick = useCallback((latlng) => {
    if (clickMode === 'start') {
      setStartPoint({ lat: latlng.lat, lng: latlng.lng });
      setClickMode('end');
    } else if (clickMode === 'end') {
      setEndPoint({ lat: latlng.lat, lng: latlng.lng });
      setClickMode(null);
    }
  }, [clickMode]);

  const evaluateRoutes = useCallback(async () => {
    if (!startPoint || !endPoint) return;
    setLoading(true);
    setError(null);
    setData(null);
    setSelectedRoute(null);
    try {
      const res = await operatorApi.evaluateRouteSafety(
        startPoint.lat, startPoint.lng, endPoint.lat, endPoint.lng
      );
      setData(res.data);
      setSelectedRoute(res.data.recommendation);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to evaluate routes');
    } finally {
      setLoading(false);
    }
  }, [startPoint, endPoint]);

  // Auto-evaluate when both points are set
  useEffect(() => {
    if (startPoint && endPoint) evaluateRoutes();
  }, [startPoint, endPoint, evaluateRoutes]);

  const reset = () => {
    setStartPoint(null);
    setEndPoint(null);
    setData(null);
    setError(null);
    setSelectedRoute(null);
    setClickMode('start');
    setSelectedDevice('');
  };

  const handleMonitorRoute = async () => {
    if (!selectedDevice || selectedRoute === null || !data || !startPoint || !endPoint) return;
    const route = data.routes.find(r => r.index === selectedRoute);
    if (!route) return;
    setMonitoring(true);
    try {
      await operatorApi.assignRouteMonitor(
        selectedDevice, selectedRoute,
        startPoint.lat, startPoint.lng, endPoint.lat, endPoint.lng,
        route
      );
      toast.success(`Route monitoring activated for ${devices.find(d => d.device_id === selectedDevice)?.device_identifier || selectedDevice}`);
      _refreshMonitors();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to assign route monitor');
    } finally {
      setMonitoring(false);
    }
  };

  const handleCancelMonitor = async (deviceId) => {
    try {
      await operatorApi.cancelRouteMonitor(deviceId);
      toast.success('Route monitor cancelled');
      setRerouteData(prev => { const n = {...prev}; delete n[deviceId]; return n; });
      setRiskUpdateData(prev => { const n = {...prev}; delete n[deviceId]; return n; });
      _refreshMonitors();
    } catch {
      toast.error('Failed to cancel monitor');
    }
  };

  const handleSuggestReroute = async (deviceId) => {
    setRerouteData(prev => ({ ...prev, [deviceId]: { loading: true, data: null } }));
    try {
      const res = await operatorApi.suggestReroute(deviceId);
      setRerouteData(prev => ({ ...prev, [deviceId]: { loading: false, data: res.data } }));
      if (res.data.status === 'reroute_available') {
        toast.success(`Safer route found! Risk improvement: -${res.data.risk_improvement}`);
      } else if (res.data.status === 'current_optimal') {
        toast.info('Current route is already optimal');
      } else {
        toast.info(res.data.message || 'No reroute needed');
      }
    } catch {
      setRerouteData(prev => ({ ...prev, [deviceId]: { loading: false, data: null } }));
      toast.error('Failed to evaluate reroute');
    }
  };

  const handleAcceptReroute = async (deviceId, routeData) => {
    try {
      await operatorApi.acceptReroute(deviceId, routeData);
      toast.success('Reroute accepted! Route monitor updated.');
      setRerouteData(prev => { const n = {...prev}; delete n[deviceId]; return n; });
      _refreshMonitors();
    } catch {
      toast.error('Failed to accept reroute');
    }
  };

  const handleRecalculateRisk = async (deviceId) => {
    setRiskUpdateData(prev => ({ ...prev, [deviceId]: { loading: true, data: null } }));
    try {
      const res = await operatorApi.recalculateRouteRisk(deviceId);
      setRiskUpdateData(prev => ({ ...prev, [deviceId]: { loading: false, data: res.data } }));
      _refreshMonitors();
      const trend = res.data.risk_trend;
      if (trend === 'increased') toast.warning(`Risk increased: ${res.data.old_risk} → ${res.data.new_risk}`);
      else if (trend === 'decreased') toast.success(`Risk decreased: ${res.data.old_risk} → ${res.data.new_risk}`);
      else toast.info(`Risk stable at ${res.data.new_risk}`);
    } catch {
      setRiskUpdateData(prev => ({ ...prev, [deviceId]: { loading: false, data: null } }));
      toast.error('Failed to recalculate risk');
    }
  };

  const selected = data?.routes?.find(r => r.index === selectedRoute);
  const bounds = data?.routes?.[0]
    ? data.routes[0].geometry.map(([lng, lat]) => [lat, lng])
    : null;

  return (
    <Card className="border-slate-200" data-testid="route-safety-intelligence">
      <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css" />
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Route className="w-5 h-5 text-blue-600" />
            <div>
              <CardTitle className="text-sm font-semibold text-slate-800">
                Route Safety Intelligence
              </CardTitle>
              <p className="text-[10px] text-slate-400 mt-0.5">
                {clickMode === 'start' ? 'Click map to set start point' :
                 clickMode === 'end' ? 'Click map to set destination' :
                 !startPoint ? 'Click "Set Route" to begin' :
                 'Evaluating safest routes'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            {!clickMode && !data && (
              <Button size="sm" onClick={() => setClickMode('start')}
                className="h-7 text-xs bg-blue-600 hover:bg-blue-700"
                data-testid="set-route-btn">
                <MapPin className="w-3 h-3 mr-1" /> Set Route
              </Button>
            )}
            {(startPoint || data) && (
              <Button variant="outline" size="sm" onClick={reset}
                className="h-7 text-xs" data-testid="reset-route-btn">
                <RotateCcw className="w-3 h-3 mr-1" /> Reset
              </Button>
            )}
          </div>
        </div>

        {/* Start/End labels */}
        {startPoint && (
          <div className="flex items-center gap-2 mt-2 text-xs">
            <Badge className="bg-green-100 text-green-700 border-green-200 text-[10px]">
              Start: {startPoint.lat.toFixed(4)}, {startPoint.lng.toFixed(4)}
            </Badge>
            {endPoint && (
              <>
                <ArrowRight className="w-3 h-3 text-slate-400" />
                <Badge className="bg-red-100 text-red-700 border-red-200 text-[10px]">
                  End: {endPoint.lat.toFixed(4)}, {endPoint.lng.toFixed(4)}
                </Badge>
              </>
            )}
          </div>
        )}
      </CardHeader>

      <CardContent className="pt-0">
        <div className="flex gap-4" style={{ minHeight: 480 }}>
          {/* Map */}
          <div className="flex-1 relative rounded-lg overflow-hidden border border-slate-200"
            data-testid="route-map-container">
            <MapContainer
              center={center}
              zoom={13}
              style={{ height: 480, width: '100%' }}
              scrollWheelZoom={true}
            >
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org">OSM</a>'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <MapClickHandler onMapClick={handleMapClick} mode={clickMode} />
              {bounds && <FitBounds bounds={bounds} />}

              {/* Start marker */}
              {startPoint && (
                <Marker position={[startPoint.lat, startPoint.lng]} icon={pinIcon('#22c55e', 'A')}>
                  <Popup><span className="text-xs font-bold">Start</span></Popup>
                </Marker>
              )}

              {/* End marker */}
              {endPoint && (
                <Marker position={[endPoint.lat, endPoint.lng]} icon={pinIcon('#dc2626', 'B')}>
                  <Popup><span className="text-xs font-bold">Destination</span></Popup>
                </Marker>
              )}

              {/* Route polylines */}
              {data?.routes?.map((r) => {
                const primary = r.label[0] || 'alternate';
                const color = ROUTE_COLORS[primary] || ROUTE_COLORS.alternate;
                const isSelected = r.index === selectedRoute;
                const positions = r.geometry.map(([lng, lat]) => [lat, lng]);

                return (
                  <React.Fragment key={r.index}>
                    <Polyline
                      positions={positions}
                      pathOptions={{
                        color: isSelected ? color : '#94a3b8',
                        weight: isSelected ? 5 : 3,
                        opacity: isSelected ? 0.9 : 0.4,
                        dashArray: isSelected ? null : '8 6',
                      }}
                      eventHandlers={{ click: () => setSelectedRoute(r.index) }}
                    />
                    {/* Dangerous segment markers for selected route */}
                    {isSelected && r.segments?.filter(s => s.risk >= 5).map((s, si) => (
                      <CircleMarker
                        key={`danger-${si}`}
                        center={[s.lat, s.lng]}
                        radius={6}
                        pathOptions={{
                          color: riskColor(s.risk),
                          fillColor: riskColor(s.risk),
                          fillOpacity: 0.7,
                          weight: 2,
                        }}
                      >
                        <Popup>
                          <div className="text-xs">
                            <p className="font-bold" style={{ color: riskColor(s.risk) }}>
                              Risk: {s.risk}/10 ({s.level})
                            </p>
                            {s.factors?.map((f, fi) => <p key={fi} className="text-slate-500">&bull; {f}</p>)}
                          </div>
                        </Popup>
                      </CircleMarker>
                    ))}
                  </React.Fragment>
                );
              })}

              {/* Heatmap risk zones along route */}
              {selected?.heatmap_risk_zones?.map((zone) => (
                <CircleMarker
                  key={`hm-${zone.grid_id}`}
                  center={[zone.lat, zone.lng]}
                  radius={10}
                  pathOptions={{
                    color: zone.risk_level === 'critical' ? '#dc2626' : '#f97316',
                    fillColor: zone.risk_level === 'critical' ? '#dc2626' : '#f97316',
                    fillOpacity: 0.15,
                    weight: 2,
                    dashArray: '4, 4',
                    opacity: 0.7,
                  }}
                >
                  <Popup>
                    <div className="text-[10px]">
                      <p className="font-bold text-red-600 capitalize">{zone.risk_level} Heatmap Zone</p>
                      <p>Cell: {zone.grid_id}</p>
                      <p>Score: {zone.composite_score}</p>
                      {zone.forecast_category === 'escalating' && (
                        <p className="text-red-500 font-medium">Forecast: Escalating</p>
                      )}
                    </div>
                  </Popup>
                </CircleMarker>
              ))}
            </MapContainer>

            {loading && (
              <div className="absolute inset-0 bg-white/70 flex items-center justify-center z-[1000]"
                data-testid="route-loading">
                <div className="flex items-center gap-2 bg-white rounded-lg shadow-lg px-4 py-3">
                  <Loader2 className="w-4 h-4 animate-spin text-blue-600" />
                  <span className="text-sm text-slate-600">Evaluating routes...</span>
                </div>
              </div>
            )}

            {/* Click mode indicator */}
            {clickMode && (
              <div className="absolute top-3 left-1/2 -translate-x-1/2 z-[1000] bg-slate-900 text-white text-xs px-4 py-2 rounded-full shadow-lg"
                data-testid="click-mode-indicator">
                <MapPin className="w-3 h-3 inline mr-1" />
                Click map to set {clickMode === 'start' ? 'start point' : 'destination'}
              </div>
            )}

            {/* Legend */}
            {data && (
              <div className="absolute bottom-3 right-3 z-[1000] bg-white/95 rounded-lg shadow-md border border-slate-200 p-2 space-y-1"
                data-testid="route-legend">
                {Object.entries(ROUTE_COLORS).filter(([k]) => k !== 'alternate').map(([key, color]) => (
                  <div key={key} className="flex items-center gap-1.5">
                    <div className="w-4 h-[3px] rounded" style={{ backgroundColor: color }} />
                    <span className="text-[9px] text-slate-500 capitalize">{key}</span>
                  </div>
                ))}
                <div className="flex items-center gap-1.5 border-t border-slate-100 pt-1 mt-1">
                  <div className="w-2.5 h-2.5 rounded-full bg-red-500" />
                  <span className="text-[9px] text-slate-500">Danger point</span>
                </div>
              </div>
            )}
          </div>

          {/* Route comparison cards + Active Monitors */}
          {data && (
            <div className="w-[280px] shrink-0 space-y-2 overflow-y-auto" data-testid="route-cards-panel">
              <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                {data.routes.length} Route Options
              </p>
              {data.routes.map((r) => (
                <RouteCard
                  key={r.index}
                  route={r}
                  selected={r.index === selectedRoute}
                  onSelect={setSelectedRoute}
                  recommended={r.index === data.recommendation}
                />
              ))}

              {/* Summary */}
              {selected && (
                <div className="border border-slate-200 rounded-lg p-3 bg-slate-50 mt-2" data-testid="route-summary">
                  <p className="text-[10px] font-semibold text-slate-600 mb-1">Selected Route Summary</p>
                  <div className="space-y-0.5 text-[10px] text-slate-500">
                    <p>Distance: <strong>{selected.distance_km} km</strong></p>
                    <p>Duration: <strong>{selected.duration_min} min</strong></p>
                    <p>Risk Score: <strong style={{ color: riskColor(selected.route_risk_score) }}>
                      {selected.route_risk_score}/10
                    </strong> ({selected.risk_level})</p>
                    <p>Dangerous segments: <strong className="text-red-600">{selected.dangerous_segments}</strong></p>
                    <p>Moderate segments: <strong className="text-yellow-600">{selected.moderate_segments}</strong></p>
                    <p>Sampled points: {selected.sampled_points}</p>
                    {selected.base_risk_score !== undefined && selected.heatmap_penalty > 0 && (
                      <p>Heatmap penalty: <strong className="text-orange-600">+{selected.heatmap_penalty}</strong> (base: {selected.base_risk_score})</p>
                    )}
                  </div>

                  {/* Heatmap warnings */}
                  {selected.heatmap_warnings?.length > 0 && (
                    <div className="mt-2 pt-2 border-t border-red-200" data-testid="route-heatmap-warnings">
                      <p className="text-[10px] font-semibold text-red-600 mb-1 flex items-center gap-1">
                        <Flame className="w-3 h-3" /> Heatmap Alerts
                      </p>
                      <div className="space-y-0.5">
                        {selected.heatmap_warnings.map((w, i) => (
                          <p key={i} className="text-[10px] text-red-500 flex items-center gap-1">
                            <span className="w-1 h-1 rounded-full bg-red-400 flex-shrink-0" />
                            {w}
                          </p>
                        ))}
                      </div>
                      {selected.heatmap_risk_zones?.length > 0 && (
                        <p className="text-[9px] text-slate-400 mt-1">
                          {selected.heatmap_summary?.critical_crossings || 0} critical + {selected.heatmap_summary?.high_crossings || 0} high risk crossings
                        </p>
                      )}
                    </div>
                  )}

                  {/* Monitor Route */}
                  <div className="mt-3 pt-2 border-t border-slate-200" data-testid="monitor-route-section">
                    <p className="text-[10px] font-semibold text-slate-600 mb-1.5 flex items-center gap-1">
                      <Radio className="w-3 h-3 text-green-600" /> Assign Live Monitor
                    </p>
                    <select
                      className="w-full text-[11px] border border-slate-200 rounded px-2 py-1.5 bg-white text-slate-700 mb-1.5"
                      value={selectedDevice}
                      onChange={(e) => setSelectedDevice(e.target.value)}
                      data-testid="monitor-device-select"
                    >
                      <option value="">Select device...</option>
                      {devices.map(d => (
                        <option key={d.device_id} value={d.device_id}>
                          {d.device_identifier}
                        </option>
                      ))}
                    </select>
                    <Button
                      size="sm"
                      disabled={!selectedDevice || monitoring}
                      onClick={handleMonitorRoute}
                      className="w-full h-7 text-[11px] bg-green-600 hover:bg-green-700"
                      data-testid="monitor-route-btn"
                    >
                      {monitoring ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> :
                        <Eye className="w-3 h-3 mr-1" />}
                      {monitoring ? 'Activating...' : 'Monitor This Route'}
                    </Button>
                  </div>
                </div>
              )}

              {/* Active Monitors */}
              {activeMonitors.length > 0 && (
                <div className="border border-green-200 rounded-lg p-3 bg-green-50/50 mt-2" data-testid="active-monitors-panel">
                  <p className="text-[10px] font-semibold text-green-700 mb-1.5 flex items-center gap-1">
                    <Radio className="w-3 h-3 animate-pulse" /> {activeMonitors.length} Active Monitor{activeMonitors.length > 1 ? 's' : ''}
                  </p>
                  <div className="space-y-2">
                    {activeMonitors.map(m => {
                      const reroute = rerouteData[m.device_id];
                      const riskUpdate = riskUpdateData[m.device_id];
                      return (
                        <div key={m.monitor_id} className={`px-2 py-2 rounded border text-[10px] ${
                          m.alert_level === 'danger' ? 'border-red-200 bg-red-50' :
                          m.alert_level === 'warning' ? 'border-amber-200 bg-amber-50' :
                          'border-green-200 bg-white'
                        }`} data-testid={`monitor-${m.device_identifier}`}>
                          {/* Header row */}
                          <div className="flex items-center gap-1.5">
                            <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                              m.alert_level === 'danger' ? 'bg-red-500 animate-pulse' :
                              m.alert_level === 'warning' ? 'bg-amber-500 animate-pulse' :
                              'bg-green-500'
                            }`} />
                            <span className="font-semibold text-slate-700">{m.device_identifier}</span>
                            <span className="text-slate-400 ml-auto">{m.route_progress}%</span>
                            <button
                              onClick={() => handleCancelMonitor(m.device_id)}
                              className="text-slate-400 hover:text-red-500 ml-1"
                              data-testid={`cancel-monitor-${m.device_identifier}`}
                            >×</button>
                          </div>

                          {/* Risk + Alert */}
                          {m.alert_message && (
                            <p className="text-[9px] text-amber-700 mt-1">{m.alert_message}</p>
                          )}

                          {/* Action buttons */}
                          <div className="flex gap-1 mt-1.5">
                            <button
                              onClick={() => handleSuggestReroute(m.device_id)}
                              disabled={reroute?.loading}
                              className="flex-1 flex items-center justify-center gap-0.5 px-1.5 py-1 rounded bg-blue-50 border border-blue-200 text-blue-700 hover:bg-blue-100 transition-colors disabled:opacity-50"
                              data-testid={`reroute-btn-${m.device_identifier}`}
                            >
                              {reroute?.loading ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <ArrowRightLeft className="w-2.5 h-2.5" />}
                              <span>Reroute</span>
                            </button>
                            <button
                              onClick={() => handleRecalculateRisk(m.device_id)}
                              disabled={riskUpdate?.loading}
                              className="flex-1 flex items-center justify-center gap-0.5 px-1.5 py-1 rounded bg-slate-50 border border-slate-200 text-slate-600 hover:bg-slate-100 transition-colors disabled:opacity-50"
                              data-testid={`risk-update-btn-${m.device_identifier}`}
                            >
                              {riskUpdate?.loading ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <RefreshCw className="w-2.5 h-2.5" />}
                              <span>Risk</span>
                            </button>
                          </div>

                          {/* Risk Update Result */}
                          {riskUpdate?.data && (
                            <div className="mt-1.5 px-1.5 py-1 rounded bg-white border border-slate-100" data-testid={`risk-result-${m.device_identifier}`}>
                              <div className="flex items-center gap-1">
                                {riskUpdate.data.risk_trend === 'increased' ? <TrendingUp className="w-3 h-3 text-red-500" /> :
                                 riskUpdate.data.risk_trend === 'decreased' ? <TrendingDown className="w-3 h-3 text-green-500" /> :
                                 <Minus className="w-3 h-3 text-slate-400" />}
                                <span className="font-medium">{riskUpdate.data.old_risk} → {riskUpdate.data.new_risk}</span>
                                <span className={`ml-auto font-semibold ${
                                  riskUpdate.data.risk_trend === 'increased' ? 'text-red-600' :
                                  riskUpdate.data.risk_trend === 'decreased' ? 'text-green-600' : 'text-slate-400'
                                }`}>
                                  {riskUpdate.data.risk_delta > 0 ? '+' : ''}{riskUpdate.data.risk_delta}
                                </span>
                              </div>
                            </div>
                          )}

                          {/* Reroute Suggestion */}
                          {reroute?.data?.status === 'reroute_available' && (
                            <div className="mt-1.5 rounded border border-blue-200 bg-blue-50 p-1.5" data-testid={`reroute-result-${m.device_identifier}`}>
                              <p className="text-[9px] font-semibold text-blue-700 flex items-center gap-1 mb-1">
                                <Shield className="w-3 h-3" /> Safer Route Found
                                <span className="ml-auto text-green-600">-{reroute.data.risk_improvement} risk</span>
                              </p>
                              <div className="space-y-1">
                                {reroute.data.alternatives?.slice(0, 2).map((alt, i) => (
                                  <div key={i} className="flex items-center gap-1.5 px-1.5 py-1 rounded bg-white border border-slate-100">
                                    <span className={`text-[9px] font-bold ${alt.risk_improvement > 0 ? 'text-green-600' : 'text-slate-500'}`}>
                                      {alt.route_risk_score}/10
                                    </span>
                                    <span className="text-slate-400">{alt.distance_km}km · {alt.duration_min}min</span>
                                    {i === 0 && (
                                      <button
                                        onClick={() => handleAcceptReroute(m.device_id, alt)}
                                        className="ml-auto px-2 py-0.5 rounded bg-green-600 text-white text-[9px] font-semibold hover:bg-green-700 transition-colors"
                                        data-testid={`accept-reroute-${m.device_identifier}`}
                                      >
                                        Accept
                                      </button>
                                    )}
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                          {reroute?.data?.status === 'current_optimal' && (
                            <p className="mt-1 text-[9px] text-green-600 flex items-center gap-1">
                              <Shield className="w-3 h-3" /> Current route is optimal
                            </p>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Empty state with active monitors */}
          {!data && !loading && (
            <div className="w-[280px] shrink-0 space-y-3 overflow-y-auto" data-testid="route-empty-state">
              <div className="text-center text-slate-400 space-y-2 py-6">
                <Navigation className="w-8 h-8 mx-auto text-slate-300" />
                <p className="text-sm font-medium">Set a route to begin</p>
                <p className="text-[10px]">Click "Set Route" then click two points on the map</p>
              </div>

              {/* Active Monitors (visible even without route data) */}
              {activeMonitors.length > 0 && (
                <div className="border border-green-200 rounded-lg p-3 bg-green-50/50" data-testid="active-monitors-panel">
                  <p className="text-[10px] font-semibold text-green-700 mb-1.5 flex items-center gap-1">
                    <Radio className="w-3 h-3 animate-pulse" /> {activeMonitors.length} Active Monitor{activeMonitors.length > 1 ? 's' : ''}
                  </p>
                  <div className="space-y-2">
                    {activeMonitors.map(m => {
                      const reroute = rerouteData[m.device_id];
                      const riskUpdate = riskUpdateData[m.device_id];
                      return (
                        <div key={m.monitor_id} className={`px-2 py-2 rounded border text-[10px] ${
                          m.alert_level === 'danger' ? 'border-red-200 bg-red-50' :
                          m.alert_level === 'warning' ? 'border-amber-200 bg-amber-50' :
                          'border-green-200 bg-white'
                        }`} data-testid={`monitor-${m.device_identifier}`}>
                          <div className="flex items-center gap-1.5">
                            <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                              m.alert_level === 'danger' ? 'bg-red-500 animate-pulse' :
                              m.alert_level === 'warning' ? 'bg-amber-500 animate-pulse' :
                              'bg-green-500'
                            }`} />
                            <span className="font-semibold text-slate-700">{m.device_identifier}</span>
                            <span className="text-slate-400 ml-auto">{m.route_progress}%</span>
                            <button onClick={() => handleCancelMonitor(m.device_id)} className="text-slate-400 hover:text-red-500 ml-1" data-testid={`cancel-monitor-${m.device_identifier}`}>×</button>
                          </div>
                          {m.alert_message && <p className="text-[9px] text-amber-700 mt-1">{m.alert_message}</p>}
                          <div className="flex gap-1 mt-1.5">
                            <button onClick={() => handleSuggestReroute(m.device_id)} disabled={reroute?.loading}
                              className="flex-1 flex items-center justify-center gap-0.5 px-1.5 py-1 rounded bg-blue-50 border border-blue-200 text-blue-700 hover:bg-blue-100 transition-colors disabled:opacity-50"
                              data-testid={`reroute-btn-${m.device_identifier}`}>
                              {reroute?.loading ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <ArrowRightLeft className="w-2.5 h-2.5" />}
                              <span>Reroute</span>
                            </button>
                            <button onClick={() => handleRecalculateRisk(m.device_id)} disabled={riskUpdate?.loading}
                              className="flex-1 flex items-center justify-center gap-0.5 px-1.5 py-1 rounded bg-slate-50 border border-slate-200 text-slate-600 hover:bg-slate-100 transition-colors disabled:opacity-50"
                              data-testid={`risk-update-btn-${m.device_identifier}`}>
                              {riskUpdate?.loading ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <RefreshCw className="w-2.5 h-2.5" />}
                              <span>Risk</span>
                            </button>
                          </div>
                          {riskUpdate?.data && (
                            <div className="mt-1.5 px-1.5 py-1 rounded bg-white border border-slate-100" data-testid={`risk-result-${m.device_identifier}`}>
                              <div className="flex items-center gap-1">
                                {riskUpdate.data.risk_trend === 'increased' ? <TrendingUp className="w-3 h-3 text-red-500" /> :
                                 riskUpdate.data.risk_trend === 'decreased' ? <TrendingDown className="w-3 h-3 text-green-500" /> :
                                 <Minus className="w-3 h-3 text-slate-400" />}
                                <span className="font-medium">{riskUpdate.data.old_risk} → {riskUpdate.data.new_risk}</span>
                                <span className={`ml-auto font-semibold ${
                                  riskUpdate.data.risk_trend === 'increased' ? 'text-red-600' :
                                  riskUpdate.data.risk_trend === 'decreased' ? 'text-green-600' : 'text-slate-400'
                                }`}>{riskUpdate.data.risk_delta > 0 ? '+' : ''}{riskUpdate.data.risk_delta}</span>
                              </div>
                            </div>
                          )}
                          {reroute?.data?.status === 'reroute_available' && (
                            <div className="mt-1.5 rounded border border-blue-200 bg-blue-50 p-1.5" data-testid={`reroute-result-${m.device_identifier}`}>
                              <p className="text-[9px] font-semibold text-blue-700 flex items-center gap-1 mb-1">
                                <Shield className="w-3 h-3" /> Safer Route Found
                                <span className="ml-auto text-green-600">-{reroute.data.risk_improvement} risk</span>
                              </p>
                              {reroute.data.alternatives?.slice(0, 2).map((alt, i) => (
                                <div key={i} className="flex items-center gap-1.5 px-1.5 py-1 rounded bg-white border border-slate-100 mb-0.5">
                                  <span className={`text-[9px] font-bold ${alt.risk_improvement > 0 ? 'text-green-600' : 'text-slate-500'}`}>{alt.route_risk_score}/10</span>
                                  <span className="text-slate-400">{alt.distance_km}km · {alt.duration_min}min</span>
                                  {i === 0 && (
                                    <button onClick={() => handleAcceptReroute(m.device_id, alt)}
                                      className="ml-auto px-2 py-0.5 rounded bg-green-600 text-white text-[9px] font-semibold hover:bg-green-700 transition-colors"
                                      data-testid={`accept-reroute-${m.device_identifier}`}>Accept</button>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                          {reroute?.data?.status === 'current_optimal' && (
                            <p className="mt-1 text-[9px] text-green-600 flex items-center gap-1">
                              <Shield className="w-3 h-3" /> Current route is optimal
                            </p>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {error && (
          <div className="mt-2 text-xs text-red-500 text-center" data-testid="route-error">{error}</div>
        )}
      </CardContent>
    </Card>
  );
}
