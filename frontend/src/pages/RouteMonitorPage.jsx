import React, { useEffect, useRef, useState, useCallback } from 'react';
import mapboxgl from 'mapbox-gl';
import 'mapbox-gl/dist/mapbox-gl.css';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  Navigation, Shield, AlertTriangle, Radio, MapPin,
  Play, Square, Clock, Activity, ArrowLeft, Crosshair,
} from 'lucide-react';
import api from '../api';
import { toast } from 'sonner';

mapboxgl.accessToken = process.env.REACT_APP_MAPBOX_TOKEN;

const MUMBAI_CENTER = [72.8777, 19.076];

// Corridor colors by escalation
const CORRIDOR_COLORS = {
  0: 'rgba(34, 197, 94, 0.25)',   // green safe
  1: 'rgba(245, 158, 11, 0.35)',  // yellow warning
  2: 'rgba(249, 115, 22, 0.4)',   // orange alert
  3: 'rgba(239, 68, 68, 0.45)',   // red emergency
};
const CORRIDOR_OUTLINE = {
  0: '#22c55e', 1: '#f59e0b', 2: '#f97316', 3: '#ef4444',
};
const ESCALATION_LABELS = {
  0: 'Safe', 1: 'Warning', 2: 'Alert', 3: 'Emergency',
};
const ESCALATION_STYLES = {
  0: 'bg-green-100 text-green-700 border-green-300',
  1: 'bg-yellow-100 text-yellow-700 border-yellow-300',
  2: 'bg-orange-100 text-orange-700 border-orange-300',
  3: 'bg-red-100 text-red-700 border-red-300',
};

const RouteMonitorPage = ({ routeDeviation, onDeviationHandled }) => {
  const mapContainer = useRef(null);
  const map = useRef(null);
  const markersRef = useRef({});
  const [mapLoaded, setMapLoaded] = useState(false);

  const [monitoring, setMonitoring] = useState(false);
  const [session, setSession] = useState(null);
  const [escalation, setEscalation] = useState(0);
  const [trail, setTrail] = useState([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);

  // Demo route coords
  const demoRoute = useRef([
    [72.8300, 19.0760], [72.8340, 19.0770], [72.8380, 19.0780],
    [72.8420, 19.0790], [72.8460, 19.0795], [72.8500, 19.0800],
    [72.8540, 19.0810], [72.8580, 19.0825], [72.8620, 19.0840],
    [72.8660, 19.0855], [72.8700, 19.0870], [72.8740, 19.0885],
    [72.8777, 19.0900],
  ]);

  // Check existing session
  const checkSession = useCallback(async () => {
    try {
      const res = await api.get('/route-monitor/session');
      if (res.data?.status === 'active') {
        setMonitoring(true);
        setSession(res.data);
        setEscalation(res.data.escalation_level || 0);
      }
    } catch {}
  }, []);

  useEffect(() => { checkSession(); }, [checkSession]);

  // Handle SSE deviation events from parent
  useEffect(() => {
    if (!routeDeviation) return;
    const data = routeDeviation.data || routeDeviation;
    const level = data.escalation_level || 0;
    setEscalation(level);

    if (data.lat && data.lng) {
      setLastUpdate({ lat: data.lat, lng: data.lng, distance_m: data.distance_from_route_m || data.distance_from_corridor_m });
      // Add deviation marker
      if (map.current && mapLoaded) {
        addDeviationMarker(data.lat, data.lng, level);
      }
    }
    onDeviationHandled?.();
  }, [routeDeviation, mapLoaded, onDeviationHandled]);

  // Init map
  useEffect(() => {
    if (map.current || !mapContainer.current) return;
    map.current = new mapboxgl.Map({
      container: mapContainer.current,
      style: 'mapbox://styles/mapbox/dark-v11',
      center: MUMBAI_CENTER,
      zoom: 13,
      pitch: 20,
    });
    map.current.addControl(new mapboxgl.NavigationControl(), 'top-right');
    map.current.on('load', () => setMapLoaded(true));
    return () => {
      Object.values(markersRef.current).forEach(m => m.remove());
      markersRef.current = {};
      if (map.current) { map.current.remove(); map.current = null; }
    };
  }, []);

  // Draw corridor + route on map
  const drawCorridorAndRoute = useCallback((corridor, routeCoords) => {
    if (!map.current || !mapLoaded) return;

    // Route line
    if (map.current.getSource('route-line')) {
      map.current.getSource('route-line').setData({
        type: 'Feature',
        geometry: { type: 'LineString', coordinates: routeCoords },
      });
    } else {
      map.current.addSource('route-line', {
        type: 'geojson',
        data: {
          type: 'Feature',
          geometry: { type: 'LineString', coordinates: routeCoords },
        },
      });
      map.current.addLayer({
        id: 'route-line-layer',
        type: 'line',
        source: 'route-line',
        paint: {
          'line-color': '#60a5fa',
          'line-width': 3,
          'line-opacity': 0.9,
          'line-dasharray': [2, 1],
        },
      });
    }

    // Corridor polygon
    if (corridor) {
      const corridorData = {
        type: 'Feature',
        geometry: { type: corridor.type, coordinates: corridor.coordinates },
      };
      if (map.current.getSource('corridor-fill')) {
        map.current.getSource('corridor-fill').setData(corridorData);
      } else {
        map.current.addSource('corridor-fill', { type: 'geojson', data: corridorData });
        map.current.addLayer({
          id: 'corridor-fill-layer',
          type: 'fill',
          source: 'corridor-fill',
          paint: {
            'fill-color': CORRIDOR_COLORS[0],
            'fill-opacity': 0.6,
          },
        });
        map.current.addLayer({
          id: 'corridor-outline-layer',
          type: 'line',
          source: 'corridor-fill',
          paint: {
            'line-color': CORRIDOR_OUTLINE[0],
            'line-width': 2,
            'line-opacity': 0.8,
          },
        });
      }
    }

    // Start/end markers
    if (routeCoords.length >= 2) {
      addEndpointMarker(routeCoords[0], 'S', '#22c55e', 'start-marker');
      addEndpointMarker(routeCoords[routeCoords.length - 1], 'D', '#3b82f6', 'end-marker');
      // Fit bounds
      const lngs = routeCoords.map(c => c[0]);
      const lats = routeCoords.map(c => c[1]);
      map.current.fitBounds(
        [[Math.min(...lngs) - 0.005, Math.min(...lats) - 0.005],
         [Math.max(...lngs) + 0.005, Math.max(...lats) + 0.005]],
        { padding: 60, duration: 1000 }
      );
    }
  }, [mapLoaded]);

  // Update corridor color by escalation
  useEffect(() => {
    if (!map.current || !mapLoaded) return;
    if (map.current.getLayer('corridor-fill-layer')) {
      map.current.setPaintProperty('corridor-fill-layer', 'fill-color', CORRIDOR_COLORS[escalation] || CORRIDOR_COLORS[0]);
    }
    if (map.current.getLayer('corridor-outline-layer')) {
      map.current.setPaintProperty('corridor-outline-layer', 'line-color', CORRIDOR_OUTLINE[escalation] || CORRIDOR_OUTLINE[0]);
    }
  }, [escalation, mapLoaded]);

  // Draw user trail
  const updateTrail = useCallback((trailPoints) => {
    if (!map.current || !mapLoaded || !trailPoints.length) return;
    const coords = trailPoints.map(p => [p.lng, p.lat]);
    const data = {
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: coords },
    };
    if (map.current.getSource('user-trail')) {
      map.current.getSource('user-trail').setData(data);
    } else {
      map.current.addSource('user-trail', { type: 'geojson', data });
      map.current.addLayer({
        id: 'user-trail-layer',
        type: 'line',
        source: 'user-trail',
        paint: {
          'line-color': '#a78bfa',
          'line-width': 4,
          'line-opacity': 0.9,
        },
      });
    }
    // Update user position marker
    const last = trailPoints[trailPoints.length - 1];
    addUserMarker(last.lat, last.lng, last.inside);
  }, [mapLoaded]);

  const addEndpointMarker = (coord, label, color, key) => {
    if (markersRef.current[key]) markersRef.current[key].remove();
    const el = document.createElement('div');
    el.style.cssText = `width:28px;height:28px;border-radius:50%;background:${color};border:3px solid white;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:12px;color:white;box-shadow:0 0 10px ${color}80;`;
    el.textContent = label;
    markersRef.current[key] = new mapboxgl.Marker({ element: el }).setLngLat(coord).addTo(map.current);
  };

  const addUserMarker = (lat, lng, inside) => {
    const key = 'user-pos';
    if (markersRef.current[key]) markersRef.current[key].remove();
    const color = inside ? '#22c55e' : '#ef4444';
    const el = document.createElement('div');
    el.innerHTML = `<div style="position:relative;width:24px;height:24px;">
      <div style="position:absolute;inset:0;border-radius:50%;background:${color};opacity:0.3;animation:pulse-user 1.5s ease-out infinite;"></div>
      <div style="position:absolute;inset:4px;border-radius:50%;background:${color};border:2px solid white;box-shadow:0 0 12px ${color};"></div>
    </div>`;
    if (!document.querySelector('#pulse-user-style')) {
      const s = document.createElement('style');
      s.id = 'pulse-user-style';
      s.textContent = '@keyframes pulse-user{0%{transform:scale(1);opacity:0.3}100%{transform:scale(2.2);opacity:0}}';
      document.head.appendChild(s);
    }
    markersRef.current[key] = new mapboxgl.Marker({ element: el }).setLngLat([lng, lat]).addTo(map.current);
  };

  const addDeviationMarker = (lat, lng, level) => {
    const key = `dev-${Date.now()}`;
    const color = CORRIDOR_OUTLINE[level] || '#ef4444';
    const el = document.createElement('div');
    el.style.cssText = `width:12px;height:12px;border-radius:50%;background:${color};border:2px solid white;box-shadow:0 0 8px ${color};`;
    markersRef.current[key] = new mapboxgl.Marker({ element: el }).setLngLat([lng, lat]).addTo(map.current);
  };

  // Start monitoring
  const handleStart = async () => {
    setLoading(true);
    try {
      const res = await api.post('/route-monitor/start', {
        route_coords: demoRoute.current,
        mode: 'balanced',
        destination: { lat: 19.09, lng: 72.8777, name: 'Destination' },
        route_risk_score: 4.5,
      });
      setMonitoring(true);
      setSession(res.data);
      setEscalation(0);
      setTrail([]);
      drawCorridorAndRoute(res.data.corridor, demoRoute.current);
      toast.success('Route monitoring started');
    } catch (err) {
      toast.error('Failed to start monitoring: ' + (err.response?.data?.detail || err.message));
    }
    setLoading(false);
  };

  // Stop monitoring
  const handleStop = async () => {
    setLoading(true);
    try {
      const res = await api.post('/route-monitor/stop');
      setMonitoring(false);
      setSession(null);
      setEscalation(0);
      toast.success(`Monitoring stopped. Deviations: ${res.data.total_deviations || 0}`);
    } catch (err) {
      toast.error('Failed to stop: ' + (err.response?.data?.detail || err.message));
    }
    setLoading(false);
  };

  // Simulate location update
  const simulateOnRoute = async () => {
    const idx = Math.min(trail.length, demoRoute.current.length - 1);
    const coord = demoRoute.current[idx];
    await sendLocation(coord[1], coord[0]);
  };

  const simulateOffRoute = async () => {
    const idx = Math.min(trail.length, demoRoute.current.length - 1);
    const coord = demoRoute.current[idx];
    await sendLocation(coord[1] + 0.002, coord[0] + 0.003); // ~300m off
  };

  const sendLocation = async (lat, lng) => {
    try {
      const res = await api.post('/route-monitor/location', { lat, lng });
      const pt = { lat, lng, inside: res.data.inside_corridor, ts: new Date().toISOString() };
      setTrail(prev => {
        const next = [...prev, pt];
        updateTrail(next);
        return next;
      });
      setLastUpdate(res.data);
      if (res.data.escalation_level !== undefined) setEscalation(res.data.escalation_level);
    } catch (err) {
      toast.error('Location update failed');
    }
  };

  const escLevel = escalation || 0;

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)] gap-3" data-testid="route-monitor-page">
      {/* Developer / Testing banner — THIS PAGE IS A SIMULATOR, NOT LIVE TRACKING */}
      <div className="rounded-xl bg-gradient-to-r from-amber-50 to-orange-50 border border-amber-300 p-3 flex items-start gap-3">
        <div className="w-8 h-8 rounded-full bg-amber-100 flex items-center justify-center flex-shrink-0 mt-0.5">
          <AlertTriangle className="w-4 h-4 text-amber-600" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-amber-900">Route Deviation Simulator (Developer Tool)</p>
          <p className="text-xs text-amber-700 leading-snug mt-0.5">
            This page uses a pre-set Mumbai demo route (Khar Danda → BOM Airport) to test the deviation
            detection engine. It is <span className="font-semibold">not</span> showing your child&apos;s live journey.
            For live child tracking, open the <a href="/family/safety" className="underline font-semibold">Safety Tracking</a> or
            <a href="/family/emergency-map" className="underline font-semibold"> Live Safety Map</a> pages.
          </p>
        </div>
      </div>

      <div className="flex flex-1 gap-4 min-h-0">
      {/* Map */}
      <div className="flex-1 relative rounded-xl overflow-hidden border border-slate-200 shadow-sm">
        <div ref={mapContainer} className="w-full h-full" data-testid="route-monitor-map" />

        {/* Escalation Banner */}
        {monitoring && escLevel > 0 && (
          <div className={`absolute top-4 left-1/2 -translate-x-1/2 z-10 ${escLevel >= 3 ? 'animate-pulse' : ''}`}
               data-testid="escalation-banner">
            <div className={`px-5 py-2.5 rounded-full shadow-lg flex items-center gap-2 border-2 ${ESCALATION_STYLES[escLevel]}`}>
              {escLevel >= 3 ? <AlertTriangle className="w-4 h-4" /> : escLevel >= 2 ? <Radio className="w-4 h-4" /> : <Shield className="w-4 h-4" />}
              <span className="text-xs font-black tracking-wider uppercase">
                {ESCALATION_LABELS[escLevel]} — Level {escLevel}
              </span>
              {lastUpdate?.distance_from_route_m && (
                <span className="text-[10px] font-medium opacity-75">
                  {lastUpdate.distance_from_route_m.toFixed(0)}m off
                </span>
              )}
            </div>
          </div>
        )}

        {/* Map Legend */}
        <div className="absolute bottom-4 left-4 z-10">
          <Card className="bg-slate-900/90 backdrop-blur border-slate-700 shadow-xl">
            <CardContent className="p-3 space-y-1.5">
              <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Legend</div>
              {[
                { color: '#60a5fa', label: 'Planned Route', dash: true },
                { color: '#22c55e', label: 'Safe Corridor' },
                { color: '#a78bfa', label: 'User Trail' },
                { color: '#ef4444', label: 'Deviation Point' },
              ].map(i => (
                <div key={i.label} className="flex items-center gap-2 text-[10px] text-slate-300">
                  <div style={{
                    width: 16, height: 3, borderRadius: 2, background: i.color,
                    borderTop: i.dash ? `2px dashed ${i.color}` : 'none',
                  }} />
                  {i.label}
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Side Panel */}
      <div className="w-80 flex flex-col gap-3 overflow-y-auto" data-testid="route-monitor-panel">
        {/* Status Card */}
        <Card className={`border-2 ${ESCALATION_STYLES[escLevel]}`} data-testid="monitoring-status-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-black flex items-center gap-2">
              <Navigation className="w-4 h-4" />
              Route Monitor
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-600">Status</span>
              <Badge className={monitoring ? 'bg-green-500 text-white' : 'bg-slate-300 text-slate-600'}
                     data-testid="monitor-status-badge">
                {monitoring ? 'Active' : 'Inactive'}
              </Badge>
            </div>
            {monitoring && (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-600">Escalation</span>
                  <Badge className={ESCALATION_STYLES[escLevel]} data-testid="escalation-level-badge">
                    L{escLevel} — {ESCALATION_LABELS[escLevel]}
                  </Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-600">Trail Points</span>
                  <span className="text-xs font-bold">{trail.length}</span>
                </div>
                {session?.mode && (
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-slate-600">Mode</span>
                    <span className="text-xs font-bold capitalize">{session.mode}</span>
                  </div>
                )}
              </>
            )}

            {/* Controls */}
            <div className="flex gap-2 pt-2">
              {!monitoring ? (
                <Button size="sm" className="flex-1 bg-teal-600 hover:bg-teal-700"
                        onClick={handleStart} disabled={loading} data-testid="start-monitor-btn">
                  <Play className="w-3 h-3 mr-1" /> Start
                </Button>
              ) : (
                <Button size="sm" variant="destructive" className="flex-1"
                        onClick={handleStop} disabled={loading} data-testid="stop-monitor-btn">
                  <Square className="w-3 h-3 mr-1" /> Stop
                </Button>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Simulation Controls */}
        {monitoring && (
          <Card data-testid="simulation-controls">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-bold text-slate-700 flex items-center gap-2">
                <Crosshair className="w-4 h-4" />
                Simulate Movement
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <p className="text-[10px] text-slate-500">Simulate GPS updates for testing</p>
              <div className="flex gap-2">
                <Button size="sm" variant="outline" className="flex-1 text-xs"
                        onClick={simulateOnRoute} data-testid="sim-on-route-btn">
                  <MapPin className="w-3 h-3 mr-1 text-green-500" /> On Route
                </Button>
                <Button size="sm" variant="outline" className="flex-1 text-xs border-red-300 text-red-600 hover:bg-red-50"
                        onClick={simulateOffRoute} data-testid="sim-off-route-btn">
                  <AlertTriangle className="w-3 h-3 mr-1" /> Deviate
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Last Update */}
        {lastUpdate && (
          <Card data-testid="last-update-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-bold text-slate-700 flex items-center gap-2">
                <Activity className="w-4 h-4" />
                Last Update
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1.5 text-xs">
              <div className="flex justify-between">
                <span className="text-slate-500">In Corridor</span>
                <Badge className={lastUpdate.inside_corridor ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}>
                  {lastUpdate.inside_corridor ? 'Yes' : 'No'}
                </Badge>
              </div>
              {lastUpdate.distance_from_route_m !== undefined && (
                <div className="flex justify-between">
                  <span className="text-slate-500">Route Distance</span>
                  <span className="font-bold">{lastUpdate.distance_from_route_m?.toFixed(1) || 0}m</span>
                </div>
              )}
              {lastUpdate.off_route_duration_s !== undefined && (
                <div className="flex justify-between">
                  <span className="text-slate-500">Off Duration</span>
                  <span className="font-bold">{lastUpdate.off_route_duration_s?.toFixed(0) || 0}s</span>
                </div>
              )}
              {lastUpdate.area_risk !== undefined && (
                <div className="flex justify-between">
                  <span className="text-slate-500">Area Risk</span>
                  <span className="font-bold">{lastUpdate.area_risk?.toFixed(1)}</span>
                </div>
              )}
              {lastUpdate.risk_elevated && (
                <div className="bg-red-50 border border-red-200 rounded px-2 py-1 text-red-700 text-[10px] font-semibold">
                  Risk elevated beyond route baseline
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Escalation Guide */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-bold text-slate-700">Escalation Levels</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-[10px]">
            {[
              { level: 1, label: 'Warning', desc: '>30m off, >10s', color: 'border-l-yellow-400' },
              { level: 2, label: 'Alert', desc: '>60m off, >30s, high risk', color: 'border-l-orange-400' },
              { level: 3, label: 'Emergency', desc: '>120m off, >60s', color: 'border-l-red-400' },
            ].map(e => (
              <div key={e.level}
                   className={`border-l-4 ${e.color} pl-2 py-1 ${escLevel === e.level ? 'bg-slate-50 font-bold' : 'text-slate-500'}`}>
                <span className="font-semibold">L{e.level}: {e.label}</span> — {e.desc}
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
      </div>
    </div>
  );
};

export default RouteMonitorPage;
