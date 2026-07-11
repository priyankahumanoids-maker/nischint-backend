import React, { useEffect, useRef, useState, useCallback } from 'react';
import mapboxgl from 'mapbox-gl';
import 'mapbox-gl/dist/mapbox-gl.css';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  AlertTriangle, MapPin, Navigation, Layers, Radio,
  Shield, Clock, ChevronRight, X,
} from 'lucide-react';
import api from '../api';

mapboxgl.accessToken = process.env.REACT_APP_MAPBOX_TOKEN;

// Mumbai center
const DEFAULT_CENTER = [72.8777, 19.076];
const DEFAULT_ZOOM = 12;

// Marker colors
const MARKER_COLORS = { safe: '#22c55e', warning: '#f59e0b', emergency: '#ef4444', responder: '#3b82f6' };

const EmergencyMap = ({ activeEmergency, onEmergencySelect, fallEvent, wanderingEvent, pickupEvent, voiceDistressEvent, safetyBrainEvent, rerouteSuggestion, onRerouteAction }) => {
  const mapContainer = useRef(null);
  const map = useRef(null);
  const markersRef = useRef({});
  const trailSourceAdded = useRef(false);

  const [mapLoaded, setMapLoaded] = useState(false);
  const [incidents, setIncidents] = useState([]);
  const [heatmapData, setHeatmapData] = useState(null);
  const [selectedIncident, setSelectedIncident] = useState(null);
  const [layers, setLayers] = useState({
    emergencies: true,
    heatmap: true,
    dangerZones: true,
    trail: true,
  });

  // Fetch incidents + heatmap
  const fetchData = useCallback(async () => {
    try {
      // Get incidents from safety/zone-map (public safety zones for heatmap)
      // Note: /incidents requires guardian_id which we don't have here
      // Instead fetch zone map data for heatmap visualization
      const [zoneRes] = await Promise.all([
        api.get('/safety/zone-map').catch(() => ({ data: { zones: [] } })),
      ]);
      
      // Convert zones to incidents format for map markers
      const zones = zoneRes.data?.zones || [];
      const zoneIncidents = zones.map((z, idx) => ({
        id: z.zone_id || `zone-${idx}`,
        latitude: z.center_lat,
        longitude: z.center_lng,
        severity: z.risk_level?.toLowerCase() === 'critical' ? 'critical' 
                : z.risk_level?.toLowerCase() === 'high' ? 'high' 
                : 'medium',
        incident_type: z.zone_type || 'risk_zone',
        description: z.description || `Risk zone: ${z.risk_score?.toFixed(1) || 'N/A'}`
      }));
      setIncidents(zoneIncidents);
      
      // Generate heatmap points from zones
      const heatmapPoints = zones.map(z => ({
        lat: z.center_lat,
        lng: z.center_lng,
        weight: z.risk_score || 5
      }));
      setHeatmapData({ points: heatmapPoints });
    } catch {}
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Init map
  useEffect(() => {
    if (map.current || !mapContainer.current) return;

    map.current = new mapboxgl.Map({
      container: mapContainer.current,
      style: 'mapbox://styles/mapbox/dark-v11',
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
      pitch: 30,
    });

    map.current.addControl(new mapboxgl.NavigationControl(), 'top-right');
    map.current.addControl(new mapboxgl.GeolocateControl({ trackUserLocation: true }), 'top-right');

    map.current.on('load', () => setMapLoaded(true));

    return () => {
      Object.values(markersRef.current).forEach(m => m.remove());
      markersRef.current = {};
      if (map.current) { map.current.remove(); map.current = null; }
    };
  }, []);

  // Add heatmap layer
  useEffect(() => {
    if (!mapLoaded || !map.current || !heatmapData) return;
    const points = heatmapData.points || heatmapData.heatmap_points || [];
    if (points.length === 0) return;

    const features = points.map(p => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [p.lng || p.longitude, p.lat || p.latitude] },
      properties: { intensity: p.weight || p.intensity || 1 },
    }));

    const sourceId = 'heatmap-source';
    if (map.current.getSource(sourceId)) {
      map.current.getSource(sourceId).setData({ type: 'FeatureCollection', features });
    } else {
      map.current.addSource(sourceId, { type: 'geojson', data: { type: 'FeatureCollection', features } });
      map.current.addLayer({
        id: 'heatmap-layer',
        type: 'heatmap',
        source: sourceId,
        paint: {
          'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 0, 1, 15, 3],
          'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 0, 4, 15, 30],
          'heatmap-opacity': 0.7,
          'heatmap-color': [
            'interpolate', ['linear'], ['heatmap-density'],
            0, 'rgba(0,0,0,0)', 0.2, '#22d3ee', 0.4, '#22c55e',
            0.6, '#f59e0b', 0.8, '#f97316', 1, '#ef4444',
          ],
        },
      });
    }
  }, [mapLoaded, heatmapData]);

  // Add incident markers
  useEffect(() => {
    if (!mapLoaded || !map.current) return;

    // Remove old incident markers
    Object.entries(markersRef.current).forEach(([id, m]) => {
      if (id.startsWith('inc-')) { m.remove(); delete markersRef.current[id]; }
    });

    incidents.forEach(inc => {
      const lat = inc.latitude || inc.lat;
      const lng = inc.longitude || inc.lng;
      if (!lat || !lng) return;

      const sev = inc.severity || 'medium';
      const color = sev === 'critical' ? MARKER_COLORS.emergency
        : sev === 'high' ? '#f97316' : sev === 'medium' ? MARKER_COLORS.warning : MARKER_COLORS.safe;

      const el = document.createElement('div');
      el.className = 'incident-marker';
      el.style.cssText = `width:14px;height:14px;border-radius:50%;background:${color};border:2px solid white;cursor:pointer;box-shadow:0 0 8px ${color}80;`;

      const marker = new mapboxgl.Marker({ element: el })
        .setLngLat([lng, lat])
        .addTo(map.current);

      el.addEventListener('click', () => {
        setSelectedIncident(inc);
        map.current.flyTo({ center: [lng, lat], zoom: 15, duration: 1000 });
      });

      markersRef.current[`inc-${inc.id || inc.incident_id}`] = marker;
    });
  }, [mapLoaded, incidents]);

  // Emergency marker + trail (real-time from SSE)
  useEffect(() => {
    if (!mapLoaded || !map.current) return;

    const emKey = 'emergency-active';
    if (markersRef.current[emKey]) {
      markersRef.current[emKey].remove();
      delete markersRef.current[emKey];
    }

    if (!activeEmergency) {
      // Clear trail
      if (trailSourceAdded.current && map.current.getSource('emergency-trail')) {
        map.current.getSource('emergency-trail').setData({ type: 'FeatureCollection', features: [] });
      }
      return;
    }

    const { lat, lng, event_id, trigger_source } = activeEmergency;
    if (!lat || !lng) return;

    // Pulsing emergency marker
    const el = document.createElement('div');
    el.innerHTML = `
      <div style="position:relative;width:40px;height:40px;cursor:pointer;">
        <div style="position:absolute;inset:0;border-radius:50%;background:${MARKER_COLORS.emergency};opacity:0.3;animation:pulse-ring 1.5s ease-out infinite;"></div>
        <div style="position:absolute;inset:6px;border-radius:50%;background:${MARKER_COLORS.emergency};border:3px solid white;box-shadow:0 0 20px ${MARKER_COLORS.emergency};"></div>
      </div>
    `;
    const style = document.createElement('style');
    style.textContent = '@keyframes pulse-ring{0%{transform:scale(1);opacity:0.3}100%{transform:scale(2.5);opacity:0}}';
    if (!document.querySelector('#pulse-style')) { style.id = 'pulse-style'; document.head.appendChild(style); }

    const popup = new mapboxgl.Popup({ offset: 25, closeButton: false }).setHTML(`
      <div style="padding:8px;font-family:system-ui;">
        <div style="font-weight:700;color:#ef4444;font-size:13px;letter-spacing:1px;">EMERGENCY SOS</div>
        <div style="font-size:11px;color:#666;margin-top:4px;">Trigger: ${trigger_source || 'unknown'}</div>
        <div style="font-size:11px;color:#666;">Event: ${(event_id || '').slice(0, 8)}...</div>
        <div style="font-size:11px;color:#666;">Location: ${lat.toFixed(4)}, ${lng.toFixed(4)}</div>
      </div>
    `);

    const marker = new mapboxgl.Marker({ element: el })
      .setLngLat([lng, lat])
      .setPopup(popup)
      .addTo(map.current);

    markersRef.current[emKey] = marker;
    map.current.flyTo({ center: [lng, lat], zoom: 15, duration: 1500 });

    // Trail line
    if (!trailSourceAdded.current) {
      map.current.addSource('emergency-trail', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });
      map.current.addLayer({
        id: 'emergency-trail-line',
        type: 'line',
        source: 'emergency-trail',
        paint: {
          'line-color': MARKER_COLORS.emergency,
          'line-width': 3,
          'line-opacity': 0.8,
          'line-dasharray': [2, 1],
        },
      });
      trailSourceAdded.current = true;
    }
  }, [mapLoaded, activeEmergency]);

  // Fall event marker (confidence-based colors: orange / red / flashing red)
  useEffect(() => {
    if (!mapLoaded || !map.current) return;

    const fallKey = 'fall-active';
    if (markersRef.current[fallKey]) {
      markersRef.current[fallKey].remove();
      delete markersRef.current[fallKey];
    }

    if (!fallEvent || !fallEvent.lat || !fallEvent.lng) return;

    const { lat, lng, confidence, marker_level, user_id, event_id, status } = fallEvent;
    const isAutoSos = status === 'auto_sos';

    // Color by confidence
    let color, glowColor, labelText;
    if (isAutoSos || confidence >= 0.95) {
      color = '#ef4444'; glowColor = '#ef444480'; labelText = 'FALL - AUTO SOS';
    } else if (confidence >= 0.85) {
      color = '#ef4444'; glowColor = '#ef444460'; labelText = 'FALL - HIGH';
    } else {
      color = '#f97316'; glowColor = '#f9731660'; labelText = 'POSSIBLE FALL';
    }

    const el = document.createElement('div');
    el.setAttribute('data-testid', 'fall-marker');
    const anim = (isAutoSos || confidence >= 0.95) ? 'animation:fall-pulse 0.8s ease-in-out infinite;' : 'animation:fall-pulse 1.5s ease-out infinite;';
    el.innerHTML = `
      <div style="position:relative;width:36px;height:36px;cursor:pointer;">
        <div style="position:absolute;inset:0;border-radius:50%;background:${color};opacity:0.3;${anim}"></div>
        <div style="position:absolute;inset:5px;border-radius:50%;background:${color};border:3px solid white;box-shadow:0 0 16px ${glowColor};display:flex;align-items:center;justify-content:center;">
          <span style="color:white;font-size:14px;font-weight:900;">!</span>
        </div>
      </div>
    `;
    if (!document.querySelector('#fall-pulse-style')) {
      const s = document.createElement('style');
      s.id = 'fall-pulse-style';
      s.textContent = '@keyframes fall-pulse{0%{transform:scale(1);opacity:0.3}50%{transform:scale(1.8);opacity:0.15}100%{transform:scale(2.5);opacity:0}}';
      document.head.appendChild(s);
    }

    const popup = new mapboxgl.Popup({ offset: 25, closeButton: false }).setHTML(`
      <div style="padding:8px;font-family:system-ui;">
        <div style="font-weight:700;color:${color};font-size:13px;letter-spacing:0.5px;">${labelText}</div>
        <div style="font-size:11px;color:#666;margin-top:4px;">Confidence: ${(confidence * 100).toFixed(0)}%</div>
        <div style="font-size:11px;color:#666;">User: ${(user_id || '').slice(0, 8)}...</div>
        <div style="font-size:11px;color:#666;">Location: ${lat.toFixed(4)}, ${lng.toFixed(4)}</div>
        ${isAutoSos ? '<div style="font-size:11px;color:#ef4444;font-weight:700;margin-top:4px;">User unresponsive — SOS triggered</div>' : ''}
      </div>
    `);

    const marker = new mapboxgl.Marker({ element: el })
      .setLngLat([lng, lat])
      .setPopup(popup)
      .addTo(map.current);

    markersRef.current[fallKey] = marker;
    map.current.flyTo({ center: [lng, lat], zoom: 15, duration: 1500 });
  }, [mapLoaded, fallEvent]);

  // Wandering event marker (purple)
  useEffect(() => {
    if (!mapLoaded || !map.current) return;

    const wKey = 'wandering-active';
    if (markersRef.current[wKey]) {
      markersRef.current[wKey].remove();
      delete markersRef.current[wKey];
    }

    if (!wanderingEvent || !wanderingEvent.lat || !wanderingEvent.lng) return;

    const { lat, lng, wander_score, safe_zone_name, distance_m, escalated } = wanderingEvent;
    const isEscalated = escalated || (wander_score >= 0.85);
    const color = '#8b5cf6';
    const anim = isEscalated ? 'animation:wander-pulse 0.8s ease-in-out infinite;' : 'animation:wander-pulse 1.5s ease-out infinite;';

    const el = document.createElement('div');
    el.setAttribute('data-testid', 'wandering-marker');
    el.innerHTML = `
      <div style="position:relative;width:36px;height:36px;cursor:pointer;">
        <div style="position:absolute;inset:0;border-radius:50%;background:${color};opacity:0.3;${anim}"></div>
        <div style="position:absolute;inset:5px;border-radius:50%;background:${color};border:3px solid white;box-shadow:0 0 16px ${color}60;display:flex;align-items:center;justify-content:center;">
          <span style="color:white;font-size:12px;font-weight:900;">W</span>
        </div>
      </div>
    `;
    if (!document.querySelector('#wander-pulse-style')) {
      const s = document.createElement('style');
      s.id = 'wander-pulse-style';
      s.textContent = '@keyframes wander-pulse{0%{transform:scale(1);opacity:0.3}50%{transform:scale(1.8);opacity:0.15}100%{transform:scale(2.5);opacity:0}}';
      document.head.appendChild(s);
    }

    const popup = new mapboxgl.Popup({ offset: 25, closeButton: false }).setHTML(`
      <div style="padding:8px;font-family:system-ui;">
        <div style="font-weight:700;color:${color};font-size:13px;">WANDERING ${isEscalated ? '— ESCALATED' : 'DETECTED'}</div>
        <div style="font-size:11px;color:#666;margin-top:4px;">Zone: ${safe_zone_name || 'Unknown'}</div>
        <div style="font-size:11px;color:#666;">Distance: ${distance_m?.toFixed(0) || '?'}m</div>
        <div style="font-size:11px;color:#666;">Score: ${wander_score?.toFixed(2) || '?'}</div>
      </div>
    `);

    const marker = new mapboxgl.Marker({ element: el })
      .setLngLat([lng, lat])
      .setPopup(popup)
      .addTo(map.current);

    markersRef.current[wKey] = marker;
    map.current.flyTo({ center: [lng, lat], zoom: 15, duration: 1500 });
  }, [mapLoaded, wanderingEvent]);

  // Pickup event marker (blue)
  useEffect(() => {
    if (!mapLoaded || !map.current) return;

    const pKey = 'pickup-active';
    if (markersRef.current[pKey]) {
      markersRef.current[pKey].remove();
      delete markersRef.current[pKey];
    }

    if (!pickupEvent) return;

    // Use location from SSE data or lat/lng fields
    const lat = pickupEvent.lat || pickupEvent.pickup_location_lat;
    const lng = pickupEvent.lng || pickupEvent.pickup_location_lng;
    if (!lat || !lng) return;

    const type = pickupEvent.type || 'scheduled';
    const isVerified = type === 'verified';
    const isFailed = type === 'failed';
    const color = isFailed ? '#ef4444' : isVerified ? '#22c55e' : '#3b82f6';

    const el = document.createElement('div');
    el.setAttribute('data-testid', 'pickup-marker');
    el.innerHTML = `
      <div style="position:relative;width:32px;height:32px;cursor:pointer;">
        <div style="position:absolute;inset:0;border-radius:50%;background:${color};opacity:0.25;animation:pickup-pulse 2s ease-out infinite;"></div>
        <div style="position:absolute;inset:4px;border-radius:50%;background:${color};border:3px solid white;box-shadow:0 0 12px ${color}60;display:flex;align-items:center;justify-content:center;">
          <span style="color:white;font-size:12px;font-weight:900;">P</span>
        </div>
      </div>
    `;
    if (!document.querySelector('#pickup-pulse-style')) {
      const s = document.createElement('style');
      s.id = 'pickup-pulse-style';
      s.textContent = '@keyframes pickup-pulse{0%{transform:scale(1);opacity:0.25}100%{transform:scale(2);opacity:0}}';
      document.head.appendChild(s);
    }

    const statusLabel = isVerified ? 'VERIFIED' : isFailed ? 'FAILED' : 'SCHEDULED';
    const popup = new mapboxgl.Popup({ offset: 25, closeButton: false }).setHTML(`
      <div style="padding:8px;font-family:system-ui;">
        <div style="font-weight:700;color:${color};font-size:13px;">PICKUP ${statusLabel}</div>
        <div style="font-size:11px;color:#666;margin-top:4px;">Person: ${pickupEvent.authorized_person || 'Unknown'}</div>
        <div style="font-size:11px;color:#666;">Location: ${pickupEvent.location || ''}</div>
        ${isFailed ? `<div style="font-size:11px;color:#ef4444;font-weight:700;margin-top:4px;">Reason: ${pickupEvent.reason || 'unknown'}</div>` : ''}
      </div>
    `);

    const marker = new mapboxgl.Marker({ element: el })
      .setLngLat([lng, lat])
      .setPopup(popup)
      .addTo(map.current);

    markersRef.current[pKey] = marker;
  }, [mapLoaded, pickupEvent]);

  // Voice distress marker (red pulsing)
  useEffect(() => {
    if (!mapLoaded || !map.current) return;

    const vKey = 'voice-active';
    if (markersRef.current[vKey]) {
      markersRef.current[vKey].remove();
      delete markersRef.current[vKey];
    }

    if (!voiceDistressEvent || !voiceDistressEvent.lat || !voiceDistressEvent.lng) return;

    const { lat, lng, distress_score, keywords, scream_detected, auto_sos } = voiceDistressEvent;
    const color = '#dc2626';
    const anim = auto_sos ? 'animation:voice-pulse 0.6s ease-in-out infinite;' : 'animation:voice-pulse 1.2s ease-out infinite;';

    const el = document.createElement('div');
    el.setAttribute('data-testid', 'voice-distress-marker');
    el.innerHTML = `
      <div style="position:relative;width:38px;height:38px;cursor:pointer;">
        <div style="position:absolute;inset:0;border-radius:50%;background:${color};opacity:0.35;${anim}"></div>
        <div style="position:absolute;inset:5px;border-radius:50%;background:${color};border:3px solid white;box-shadow:0 0 20px ${color}80;display:flex;align-items:center;justify-content:center;">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" stroke-linecap="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/></svg>
        </div>
      </div>
    `;
    if (!document.querySelector('#voice-pulse-style')) {
      const s = document.createElement('style');
      s.id = 'voice-pulse-style';
      s.textContent = '@keyframes voice-pulse{0%{transform:scale(1);opacity:0.35}50%{transform:scale(2);opacity:0.15}100%{transform:scale(2.8);opacity:0}}';
      document.head.appendChild(s);
    }

    const kws = (keywords || []).join(', ') || 'none';
    const popup = new mapboxgl.Popup({ offset: 25, closeButton: false }).setHTML(`
      <div style="padding:8px;font-family:system-ui;">
        <div style="font-weight:700;color:${color};font-size:13px;">VOICE DISTRESS${auto_sos ? ' — AUTO SOS' : ''}</div>
        <div style="font-size:11px;color:#666;margin-top:4px;">Keywords: ${kws}</div>
        <div style="font-size:11px;color:#666;">Score: ${(distress_score * 100).toFixed(0)}%</div>
        <div style="font-size:11px;color:#666;">Scream: ${scream_detected ? 'Yes' : 'No'}</div>
        ${auto_sos ? '<div style="font-size:11px;color:#dc2626;font-weight:700;margin-top:4px;">Emergency SOS auto-triggered</div>' : ''}
      </div>
    `);

    const marker = new mapboxgl.Marker({ element: el })
      .setLngLat([lng, lat])
      .setPopup(popup)
      .addTo(map.current);

    markersRef.current[vKey] = marker;
    map.current.flyTo({ center: [lng, lat], zoom: 16, duration: 1500 });
  }, [mapLoaded, voiceDistressEvent]);

  // ── Safety Brain unified risk marker ──
  useEffect(() => {
    const sbKey = 'safety-brain-active';
    if (markersRef.current[sbKey]) {
      markersRef.current[sbKey].remove();
      delete markersRef.current[sbKey];
    }
    if (!mapLoaded || !map.current) return;
    if (!safetyBrainEvent || !safetyBrainEvent.lat || !safetyBrainEvent.lng) return;

    const { lat, lng, risk_score, risk_level } = safetyBrainEvent;
    const pct = Math.round((risk_score || 0) * 100);
    const isCritical = risk_level === 'critical';
    const isDangerous = risk_level === 'dangerous';
    const borderColor = isCritical ? '#ef4444' : isDangerous ? '#f97316' : '#f59e0b';
    const bgColor = isCritical ? '#fef2f2' : isDangerous ? '#fff7ed' : '#fffbeb';

    const el = document.createElement('div');
    el.setAttribute('data-testid', 'safety-brain-marker');
    el.style.cssText = `width:48px;height:48px;position:relative;cursor:pointer;`;
    el.innerHTML = `
      <div style="position:absolute;inset:0;border-radius:50%;border:3px solid ${borderColor};background:${bgColor};display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:900;color:${borderColor};${isCritical ? 'animation:sb-pulse 1.5s ease-out infinite;' : ''}">
        ${pct}
      </div>
      <div style="position:absolute;inset:-4px;border-radius:50%;border:2px dashed ${borderColor};opacity:0.4;"></div>
    `;
    if (!document.querySelector('#sb-pulse-style')) {
      const s = document.createElement('style');
      s.id = 'sb-pulse-style';
      s.textContent = '@keyframes sb-pulse{0%{box-shadow:0 0 0 0 rgba(239,68,68,0.5)}70%{box-shadow:0 0 0 14px rgba(239,68,68,0)}100%{box-shadow:0 0 0 0 rgba(239,68,68,0)}}';
      document.head.appendChild(s);
    }

    const signalNames = Object.entries(safetyBrainEvent.signals || {})
      .filter(([, v]) => v > 0)
      .map(([k, v]) => `${k}: ${Math.round(v * 100)}%`)
      .join('<br/>');

    const popup = new mapboxgl.Popup({ offset: 25, closeButton: true }).setHTML(`
      <div style="min-width:180px;padding:4px;">
        <div style="font-size:13px;font-weight:900;color:${borderColor};margin-bottom:4px;">SAFETY BRAIN: ${risk_level?.toUpperCase()}</div>
        <div style="font-size:12px;font-weight:700;">Risk: ${pct}%</div>
        <div style="font-size:11px;color:#64748b;margin-top:4px;">${signalNames || 'No active signals'}</div>
        <div style="font-size:10px;color:#94a3b8;margin-top:4px;">${lat.toFixed(4)}, ${lng.toFixed(4)}</div>
      </div>
    `);

    const marker = new mapboxgl.Marker({ element: el })
      .setLngLat([lng, lat])
      .setPopup(popup)
      .addTo(map.current);

    markersRef.current[sbKey] = marker;
    if (isCritical || isDangerous) {
      map.current.flyTo({ center: [lng, lat], zoom: 16, duration: 1500 });
    }
  }, [mapLoaded, safetyBrainEvent]);

  // ── Reroute Suggestion — dashed green line on map ──
  useEffect(() => {
    if (!mapLoaded || !map.current) return;
    const sourceId = 'reroute-line-source';
    const layerId = 'reroute-line-layer';

    // Remove previous layer/source
    if (map.current.getLayer(layerId)) map.current.removeLayer(layerId);
    if (map.current.getSource(sourceId)) map.current.removeSource(sourceId);

    if (!rerouteSuggestion || !rerouteSuggestion.suggested_route) return;

    const coords = rerouteSuggestion.suggested_route;
    if (!coords || coords.length < 2) return;

    map.current.addSource(sourceId, {
      type: 'geojson',
      data: {
        type: 'Feature',
        geometry: { type: 'LineString', coordinates: coords },
      },
    });

    map.current.addLayer({
      id: layerId,
      type: 'line',
      source: sourceId,
      paint: {
        'line-color': '#22c55e',
        'line-width': 4,
        'line-dasharray': [3, 2],
        'line-opacity': 0.85,
      },
    });

    // Fit bounds to show both current position and destination
    if (rerouteSuggestion.destination && rerouteSuggestion.current_location) {
      const bounds = coords.reduce((b, c) => b.extend(c), new mapboxgl.LngLatBounds(coords[0], coords[0]));
      map.current.fitBounds(bounds, { padding: 60, duration: 1200 });
    }
  }, [mapLoaded, rerouteSuggestion]);

  // Update emergency marker position on location update
  useEffect(() => {
    if (!activeEmergency || !markersRef.current['emergency-active']) return;
    const { lat, lng } = activeEmergency;
    if (!lat || !lng) return;
    markersRef.current['emergency-active'].setLngLat([lng, lat]);
  }, [activeEmergency?.lat, activeEmergency?.lng]);

  // Layer toggles
  const toggleLayer = (layerName) => {
    setLayers(prev => {
      const next = { ...prev, [layerName]: !prev[layerName] };
      if (map.current) {
        if (layerName === 'heatmap' && map.current.getLayer('heatmap-layer')) {
          map.current.setLayoutProperty('heatmap-layer', 'visibility', next.heatmap ? 'visible' : 'none');
        }
        if (layerName === 'trail' && map.current.getLayer('emergency-trail-line')) {
          map.current.setLayoutProperty('emergency-trail-line', 'visibility', next.trail ? 'visible' : 'none');
        }
      }
      return next;
    });
  };

  return (
    <div className="flex h-[calc(100vh-8rem)] gap-4" data-testid="emergency-map-page">
      {/* Map */}
      <div className="flex-1 relative rounded-xl overflow-hidden border border-slate-200 shadow-sm">
        <div ref={mapContainer} className="w-full h-full" data-testid="mapbox-container" />

        {/* Layer Controls */}
        <div className="absolute top-4 left-4 z-10 flex flex-col gap-2">
          <Card className="bg-slate-900/90 backdrop-blur border-slate-700 shadow-xl">
            <CardContent className="p-3 flex flex-col gap-1.5">
              <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1 flex items-center gap-1.5">
                <Layers className="w-3 h-3" /> Layers
              </div>
              {[
                { key: 'emergencies', label: 'Emergencies', color: '#ef4444' },
                { key: 'heatmap', label: 'Heatmap', color: '#f59e0b' },
                { key: 'dangerZones', label: 'Danger Zones', color: '#f97316' },
                { key: 'trail', label: 'SOS Trail', color: '#ef4444' },
              ].map(l => (
                <button
                  key={l.key}
                  onClick={() => toggleLayer(l.key)}
                  className={`flex items-center gap-2 px-2.5 py-1.5 rounded text-xs font-medium transition-all ${
                    layers[l.key] ? 'bg-slate-700 text-white' : 'text-slate-500 hover:bg-slate-800'
                  }`}
                  data-testid={`layer-toggle-${l.key}`}
                >
                  <div className="w-2.5 h-2.5 rounded-full" style={{ background: layers[l.key] ? l.color : '#475569' }} />
                  {l.label}
                </button>
              ))}
            </CardContent>
          </Card>
        </div>

        {/* Active Emergency Badge */}
        {activeEmergency && (
          <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10" data-testid="map-emergency-badge">
            <div className="bg-red-600 text-white px-4 py-2 rounded-full shadow-lg flex items-center gap-2 animate-pulse">
              <Radio className="w-4 h-4" />
              <span className="text-xs font-bold tracking-wider">LIVE EMERGENCY TRACKING</span>
            </div>
          </div>
        )}
      </div>

      {/* Side Panel */}
      <div className="w-80 flex flex-col gap-3 overflow-y-auto" data-testid="map-side-panel">
        {/* Active Emergency Card */}
        {activeEmergency && (
          <Card className="border-red-300 bg-red-50 shadow-md" data-testid="emergency-detail-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-black text-red-700 flex items-center gap-2">
                <AlertTriangle className="w-4 h-4" />
                ACTIVE EMERGENCY
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-red-600">Event ID</span>
                <span className="font-mono font-bold">{(activeEmergency.event_id || '').slice(0, 12)}...</span>
              </div>
              <div className="flex justify-between">
                <span className="text-red-600">Trigger</span>
                <Badge variant="destructive" className="text-[10px]">{activeEmergency.trigger_source}</Badge>
              </div>
              <div className="flex justify-between">
                <span className="text-red-600">Location</span>
                <span className="font-mono">{activeEmergency.lat?.toFixed(4)}, {activeEmergency.lng?.toFixed(4)}</span>
              </div>
              <Button
                size="sm"
                variant="destructive"
                className="w-full mt-2 text-xs"
                onClick={() => {
                  if (map.current && activeEmergency.lat) {
                    map.current.flyTo({ center: [activeEmergency.lng, activeEmergency.lat], zoom: 16, duration: 1000 });
                  }
                }}
                data-testid="fly-to-emergency-btn"
              >
                <Navigation className="w-3 h-3 mr-1" /> Focus on Emergency
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Fall Detection Card */}
        {fallEvent && (
          <Card className={`shadow-md ${fallEvent.status === 'auto_sos' ? 'border-red-400 bg-red-50' : fallEvent.confidence >= 0.85 ? 'border-orange-400 bg-orange-50' : 'border-amber-300 bg-amber-50'}`}
                data-testid="fall-event-card">
            <CardHeader className="pb-2">
              <CardTitle className={`text-sm font-black flex items-center gap-2 ${fallEvent.status === 'auto_sos' ? 'text-red-700' : 'text-orange-700'}`}>
                <AlertTriangle className="w-4 h-4" />
                {fallEvent.status === 'auto_sos' ? 'FALL - AUTO SOS' : 'POSSIBLE FALL'}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-orange-600">Confidence</span>
                <Badge className={
                  fallEvent.confidence >= 0.95 ? 'bg-red-100 text-red-700'
                  : fallEvent.confidence >= 0.85 ? 'bg-orange-100 text-orange-700'
                  : 'bg-amber-100 text-amber-700'
                }>{(fallEvent.confidence * 100).toFixed(0)}%</Badge>
              </div>
              <div className="flex justify-between">
                <span className="text-orange-600">Location</span>
                <span className="font-mono">{fallEvent.lat?.toFixed(4)}, {fallEvent.lng?.toFixed(4)}</span>
              </div>
              <div className="grid grid-cols-5 gap-1 pt-1">
                {[
                  { key: 'impact_detected', label: 'IMP', title: 'Impact' },
                  { key: 'freefall_detected', label: 'FF', title: 'Free-fall' },
                  { key: 'orientation_change', label: 'ORI', title: 'Orientation' },
                  { key: 'post_impact_motion', label: 'PIM', title: 'Post-impact' },
                  { key: 'immobility_detected', label: 'IMM', title: 'Immobility' },
                ].map(s => (
                  <div key={s.key}
                       title={s.title}
                       className={`text-center py-1 rounded text-[9px] font-bold ${
                         fallEvent[s.key] ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-400'
                       }`}>
                    {s.label}
                  </div>
                ))}
              </div>
              {fallEvent.status === 'auto_sos' && (
                <div className="bg-red-100 border border-red-200 rounded px-2 py-1 text-red-700 text-[10px] font-bold">
                  User unresponsive — SOS auto-triggered
                </div>
              )}
              <Button
                size="sm"
                variant="outline"
                className="w-full mt-1 text-xs border-orange-300 text-orange-700 hover:bg-orange-100"
                onClick={() => {
                  if (map.current && fallEvent.lat) {
                    map.current.flyTo({ center: [fallEvent.lng, fallEvent.lat], zoom: 16, duration: 1000 });
                  }
                }}
                data-testid="fly-to-fall-btn"
              >
                <Navigation className="w-3 h-3 mr-1" /> Focus on Fall
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Wandering Event Card */}
        {wanderingEvent && (
          <Card className={`shadow-md ${wanderingEvent.escalated ? 'border-purple-500 bg-purple-50' : 'border-purple-300 bg-purple-50/70'}`}
                data-testid="wandering-event-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-black text-purple-700 flex items-center gap-2">
                <MapPin className="w-4 h-4" />
                {wanderingEvent.escalated ? 'WANDERING — ESCALATED' : 'WANDERING DETECTED'}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-purple-600">Zone</span>
                <span className="font-semibold">{wanderingEvent.safe_zone_name || 'Unknown'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-purple-600">Distance</span>
                <span className="font-bold">{wanderingEvent.distance_m?.toFixed(0) || '?'}m</span>
              </div>
              <div className="flex justify-between">
                <span className="text-purple-600">Wander Score</span>
                <Badge className={wanderingEvent.wander_score >= 0.85 ? 'bg-purple-600 text-white' : 'bg-purple-100 text-purple-700'}>
                  {wanderingEvent.wander_score?.toFixed(2) || '0'}
                </Badge>
              </div>
              <div className="grid grid-cols-3 gap-1 pt-1">
                {[
                  { key: 'distance', label: 'Distance', active: wanderingEvent.distance_m > 0 },
                  { key: 'time', label: 'Time', active: wanderingEvent.time_outside_s > 60 },
                  { key: 'direction', label: 'Away', active: wanderingEvent.direction === 'away' },
                ].map(s => (
                  <div key={s.key}
                       className={`text-center py-1 rounded text-[9px] font-bold ${
                         s.active ? 'bg-purple-200 text-purple-700' : 'bg-slate-100 text-slate-400'
                       }`}>
                    {s.label}
                  </div>
                ))}
              </div>
              <Button
                size="sm"
                variant="outline"
                className="w-full mt-1 text-xs border-purple-300 text-purple-700 hover:bg-purple-100"
                onClick={() => {
                  if (map.current && wanderingEvent.lat) {
                    map.current.flyTo({ center: [wanderingEvent.lng, wanderingEvent.lat], zoom: 16, duration: 1000 });
                  }
                }}
                data-testid="fly-to-wandering-btn"
              >
                <Navigation className="w-3 h-3 mr-1" /> Focus on Wandering
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Pickup Event Card */}
        {pickupEvent && (
          <Card className={`shadow-md ${pickupEvent.type === 'verified' ? 'border-green-300 bg-green-50' : pickupEvent.type === 'failed' ? 'border-red-300 bg-red-50' : 'border-blue-300 bg-blue-50'}`}
                data-testid="pickup-event-card">
            <CardHeader className="pb-2">
              <CardTitle className={`text-sm font-black flex items-center gap-2 ${pickupEvent.type === 'verified' ? 'text-green-700' : pickupEvent.type === 'failed' ? 'text-red-700' : 'text-blue-700'}`}>
                <Shield className="w-4 h-4" />
                Pickup {pickupEvent.type === 'verified' ? 'Verified' : pickupEvent.type === 'failed' ? 'Failed' : 'Scheduled'}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-slate-600">Person</span>
                <span className="font-semibold">{pickupEvent.authorized_person || 'Unknown'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-600">Location</span>
                <span className="font-semibold">{pickupEvent.location || 'N/A'}</span>
              </div>
              {pickupEvent.scheduled_time && (
                <div className="flex justify-between">
                  <span className="text-slate-600">Scheduled</span>
                  <span className="font-mono text-[10px]">{new Date(pickupEvent.scheduled_time).toLocaleTimeString()}</span>
                </div>
              )}
              {pickupEvent.type === 'verified' && (
                <div className="bg-green-100 border border-green-200 rounded px-2 py-1 text-green-700 text-[10px] font-bold text-center">
                  Pickup confirmed successfully
                </div>
              )}
              {pickupEvent.type === 'failed' && (
                <div className="bg-red-100 border border-red-200 rounded px-2 py-1 text-red-700 text-[10px] font-bold">
                  Failed: {pickupEvent.reason === 'invalid_code' ? 'Invalid Code' : pickupEvent.reason === 'proximity_failed' ? 'Too Far' : pickupEvent.reason}
                  {pickupEvent.distance_m ? ` (${pickupEvent.distance_m.toFixed(0)}m away)` : ''}
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Voice Distress Card */}
        {voiceDistressEvent && (
          <Card className={`shadow-md border-red-400 ${voiceDistressEvent.auto_sos ? 'bg-red-50 animate-pulse' : 'bg-red-50/70'}`}
                data-testid="voice-distress-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-black text-red-700 flex items-center gap-2">
                <Radio className="w-4 h-4" />
                VOICE DISTRESS{voiceDistressEvent.auto_sos ? ' — AUTO SOS' : ''}
                {voiceDistressEvent.whisper_verified && (
                  <Badge className="bg-blue-600 text-white text-[8px] ml-auto">WHISPER VERIFIED</Badge>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-red-600">Distress Score</span>
                <Badge className="bg-red-600 text-white">{((voiceDistressEvent.distress_score || 0) * 100).toFixed(0)}%</Badge>
              </div>
              {voiceDistressEvent.whisper_confidence != null && (
                <div className="flex justify-between">
                  <span className="text-blue-600">Whisper Confidence</span>
                  <Badge className={
                    voiceDistressEvent.whisper_confidence >= 0.8 ? 'bg-red-600 text-white'
                    : voiceDistressEvent.whisper_confidence >= 0.6 ? 'bg-orange-500 text-white'
                    : voiceDistressEvent.whisper_confidence >= 0.3 ? 'bg-amber-500 text-white'
                    : 'bg-slate-300 text-slate-700'
                  }>{Math.round(voiceDistressEvent.whisper_confidence * 100)}%</Badge>
                </div>
              )}
              {voiceDistressEvent.transcript && (
                <div className="bg-slate-50 border border-slate-200 rounded p-2" data-testid="whisper-transcript">
                  <div className="text-[9px] font-bold text-slate-500 uppercase tracking-wider mb-1">Transcript</div>
                  <p className="text-[11px] text-slate-700 italic leading-snug">"{voiceDistressEvent.transcript}"</p>
                </div>
              )}
              {voiceDistressEvent.phrases_found?.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {voiceDistressEvent.phrases_found.map((p, i) => (
                    <span key={i} className="text-[9px] px-1.5 py-0.5 rounded bg-red-100 text-red-700 font-semibold">{p}</span>
                  ))}
                </div>
              )}
              {voiceDistressEvent.keywords?.length > 0 && (
                <div className="flex justify-between">
                  <span className="text-red-600">Keywords</span>
                  <span className="font-semibold">{voiceDistressEvent.keywords.join(', ')}</span>
                </div>
              )}
              <div className="grid grid-cols-4 gap-1 pt-1">
                {[
                  { key: 'keywords', label: 'Keywords', active: voiceDistressEvent.keywords?.length > 0 },
                  { key: 'scream', label: 'Scream', active: voiceDistressEvent.scream_detected },
                  { key: 'repeated', label: 'Repeated', active: voiceDistressEvent.repeated },
                  { key: 'whisper', label: 'Whisper', active: voiceDistressEvent.whisper_verified },
                ].map(s => (
                  <div key={s.key}
                       className={`text-center py-1 rounded text-[9px] font-bold ${
                         s.active ? 'bg-red-200 text-red-700' : 'bg-slate-100 text-slate-400'
                       }`}>
                    {s.label}
                  </div>
                ))}
              </div>
              {voiceDistressEvent.distress_level && voiceDistressEvent.distress_level !== 'ignore' && (
                <div className={`rounded px-2 py-1 text-[10px] font-bold text-center ${
                  voiceDistressEvent.distress_level === 'emergency' ? 'bg-red-100 border border-red-300 text-red-700'
                  : voiceDistressEvent.distress_level === 'high_alert' ? 'bg-orange-100 border border-orange-300 text-orange-700'
                  : 'bg-amber-100 border border-amber-300 text-amber-700'
                }`} data-testid="distress-level-badge">
                  {voiceDistressEvent.distress_level === 'emergency' ? 'EMERGENCY — Immediate escalation'
                   : voiceDistressEvent.distress_level === 'high_alert' ? 'HIGH ALERT — Guardian notified'
                   : 'CAUTION — Monitoring'}
                </div>
              )}
              {voiceDistressEvent.auto_sos && (
                <div className="bg-red-100 border border-red-300 rounded px-2 py-1 text-red-700 text-[10px] font-bold text-center">
                  Emergency SOS auto-triggered
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-red-600">Location</span>
                <span className="font-mono text-[10px]">{voiceDistressEvent.lat?.toFixed(4)}, {voiceDistressEvent.lng?.toFixed(4)}</span>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Safety Brain — Unified Risk Card */}
        {safetyBrainEvent && safetyBrainEvent.risk_level !== 'normal' && (
          <Card className={`shadow-md ${
            safetyBrainEvent.risk_level === 'critical' ? 'border-red-500 bg-gradient-to-br from-red-50 to-red-100 animate-pulse'
            : safetyBrainEvent.risk_level === 'dangerous' ? 'border-orange-400 bg-gradient-to-br from-orange-50 to-amber-50'
            : 'border-amber-300 bg-amber-50'
          }`} data-testid="safety-brain-card">
            <CardHeader className="pb-2">
              <CardTitle className={`text-sm font-black flex items-center gap-2 ${
                safetyBrainEvent.risk_level === 'critical' ? 'text-red-700'
                : safetyBrainEvent.risk_level === 'dangerous' ? 'text-orange-700'
                : 'text-amber-700'
              }`}>
                <AlertTriangle className="w-4 h-4" />
                {safetyBrainEvent.risk_level === 'critical' ? 'CRITICAL SAFETY EVENT' : safetyBrainEvent.risk_level === 'dangerous' ? 'DANGEROUS SAFETY EVENT' : 'SUSPICIOUS ACTIVITY'}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-slate-600">Risk Score</span>
                <Badge className={
                  safetyBrainEvent.risk_level === 'critical' ? 'bg-red-600 text-white'
                  : safetyBrainEvent.risk_level === 'dangerous' ? 'bg-orange-600 text-white'
                  : 'bg-amber-600 text-white'
                }>{Math.round(safetyBrainEvent.risk_score * 100)}%</Badge>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-600">Primary Signal</span>
                <span className="font-bold capitalize">{safetyBrainEvent.primary_event}</span>
              </div>
              <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mt-1">Active Signals</div>
              <div className="space-y-1">
                {Object.entries(safetyBrainEvent.signals || {}).filter(([, v]) => v > 0).map(([k, v]) => (
                  <div key={k} className="flex items-center gap-2">
                    <div className="w-14 text-[10px] font-semibold text-slate-600 capitalize">{k}</div>
                    <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
                      <div className="h-full rounded-full" style={{
                        width: `${Math.round(v * 100)}%`,
                        background: k === 'fall' ? '#f97316' : k === 'voice' ? '#dc2626' : k === 'route' ? '#3b82f6' : k === 'wander' ? '#8b5cf6' : '#06b6d4',
                      }} />
                    </div>
                    <span className="text-[10px] font-bold w-8 text-right">{Math.round(v * 100)}%</span>
                  </div>
                ))}
              </div>
              <div className="flex justify-between">
                <span className="text-slate-600">Location</span>
                <span className="font-mono text-[10px]">{safetyBrainEvent.lat?.toFixed(4)}, {safetyBrainEvent.lng?.toFixed(4)}</span>
              </div>
              {safetyBrainEvent.auto_sos && (
                <div className="bg-red-100 border border-red-300 rounded px-2 py-1 text-red-700 text-[10px] font-bold text-center">
                  Auto-SOS triggered — Emergency services alerted
                </div>
              )}
              <Button
                size="sm"
                variant="outline"
                className={`w-full mt-1 text-xs ${
                  safetyBrainEvent.risk_level === 'critical' ? 'border-red-300 text-red-700 hover:bg-red-100'
                  : 'border-orange-300 text-orange-700 hover:bg-orange-100'
                }`}
                onClick={() => {
                  if (map.current && safetyBrainEvent.lat) {
                    map.current.flyTo({ center: [safetyBrainEvent.lng, safetyBrainEvent.lat], zoom: 16, duration: 1000 });
                  }
                }}
                data-testid="fly-to-safety-brain-btn"
              >
                <Navigation className="w-3 h-3 mr-1" /> Focus on Event
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Reroute Suggestion Card */}
        {rerouteSuggestion && (
          <Card className="shadow-md border-green-400 bg-gradient-to-br from-green-50 to-emerald-50" data-testid="reroute-suggestion-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-black text-green-700 flex items-center gap-2">
                <Navigation className="w-4 h-4" />
                Safer Route Available
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs">
              <div className="bg-green-100/60 border border-green-200 rounded p-2 text-green-800 text-[11px]">
                {rerouteSuggestion.reason || 'Safety concern detected along current route'}
              </div>
              <div className="flex justify-between">
                <span className="text-slate-600">Current Route Risk</span>
                <Badge className="bg-orange-100 text-orange-700">{Math.round((rerouteSuggestion.current_route_risk || 0) * 100)}%</Badge>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-600">Suggested Route Risk</span>
                <Badge className="bg-green-100 text-green-700">{Math.round((rerouteSuggestion.suggested_route_risk || 0) * 100)}%</Badge>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-600">Distance</span>
                <span className="font-semibold">{((rerouteSuggestion.distance_m || 0) / 1000).toFixed(1)} km</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-600">ETA Change</span>
                <span className={`font-semibold ${(rerouteSuggestion.eta_change_seconds || 0) > 0 ? 'text-amber-600' : 'text-green-600'}`}>
                  {(rerouteSuggestion.eta_change_seconds || 0) > 0 ? '+' : ''}{Math.round((rerouteSuggestion.eta_change_seconds || 0) / 60)} min
                </span>
              </div>
              {rerouteSuggestion.safety_details && (
                <div className="space-y-1 pt-1 border-t border-green-200">
                  <div className="text-[10px] font-bold text-slate-500 uppercase">Safety Factors</div>
                  {Object.entries(rerouteSuggestion.safety_details).filter(([k]) => !k.includes('near')).map(([k, v]) => (
                    <div key={k} className="flex items-center gap-2">
                      <div className="w-24 text-[10px] text-slate-500 capitalize">{k.replace(/_/g, ' ')}</div>
                      <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                        <div className="h-full rounded-full bg-green-500" style={{ width: `${Math.round((1 - v) * 100)}%` }} />
                      </div>
                      <span className="text-[10px] w-7 text-right">{Math.round((1 - v) * 100)}%</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="flex gap-2 pt-1">
                <Button
                  size="sm"
                  className="flex-1 bg-green-600 hover:bg-green-700 text-white text-xs"
                  onClick={async () => {
                    try {
                      const { default: api } = await import('../api');
                      await api.post(`/reroute/${rerouteSuggestion.suggestion_id}/approve`);
                      onRerouteAction?.('approve', rerouteSuggestion.suggestion_id);
                    } catch {}
                  }}
                  data-testid="approve-reroute-btn"
                >
                  Approve Route
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="flex-1 border-slate-300 text-slate-600 text-xs"
                  onClick={async () => {
                    try {
                      const { default: api } = await import('../api');
                      await api.post(`/reroute/${rerouteSuggestion.suggestion_id}/dismiss`);
                      onRerouteAction?.('dismiss', rerouteSuggestion.suggestion_id);
                    } catch {}
                  }}
                  data-testid="dismiss-reroute-btn"
                >
                  Dismiss
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Stats */}
        <Card className="bg-slate-50">
          <CardContent className="p-4 grid grid-cols-2 gap-3">
            <div className="text-center">
              <div className="text-2xl font-black text-red-600" data-testid="stat-emergencies">
                {activeEmergency ? 1 : 0}
              </div>
              <div className="text-[10px] text-slate-500 font-semibold">Active SOS</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-black text-amber-600" data-testid="stat-incidents">
                {incidents.length}
              </div>
              <div className="text-[10px] text-slate-500 font-semibold">Incidents</div>
            </div>
          </CardContent>
        </Card>

        {/* Selected Incident */}
        {selectedIncident && (
          <Card className="border-amber-300 bg-amber-50" data-testid="selected-incident-card">
            <CardHeader className="pb-2 flex flex-row items-center justify-between">
              <CardTitle className="text-sm font-bold text-amber-800">Incident Detail</CardTitle>
              <button onClick={() => setSelectedIncident(null)} className="text-slate-400 hover:text-slate-600">
                <X className="w-4 h-4" />
              </button>
            </CardHeader>
            <CardContent className="space-y-1.5 text-xs">
              <div className="flex justify-between">
                <span className="text-amber-700">Type</span>
                <span className="font-semibold">{selectedIncident.incident_type || selectedIncident.type || 'Unknown'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-amber-700">Severity</span>
                <Badge className={`text-[10px] ${
                  selectedIncident.severity === 'critical' ? 'bg-red-100 text-red-700'
                  : selectedIncident.severity === 'high' ? 'bg-orange-100 text-orange-700'
                  : 'bg-amber-100 text-amber-700'
                }`}>{selectedIncident.severity}</Badge>
              </div>
              {selectedIncident.description && (
                <p className="text-slate-600 mt-1">{selectedIncident.description}</p>
              )}
            </CardContent>
          </Card>
        )}

        {/* Recent Incidents List */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-bold text-slate-700 flex items-center gap-2">
              <Clock className="w-4 h-4" />
              Recent Incidents
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-1.5 max-h-60 overflow-y-auto">
            {incidents.length === 0 ? (
              <p className="text-xs text-slate-400 text-center py-4">No incidents reported</p>
            ) : (
              incidents.slice(0, 15).map((inc, i) => {
                const lat = inc.latitude || inc.lat;
                const lng = inc.longitude || inc.lng;
                return (
                  <button
                    key={inc.id || inc.incident_id || i}
                    className="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg hover:bg-slate-50 transition-colors text-left"
                    onClick={() => {
                      setSelectedIncident(inc);
                      if (map.current && lat && lng) {
                        map.current.flyTo({ center: [lng, lat], zoom: 15, duration: 1000 });
                      }
                    }}
                    data-testid={`incident-item-${i}`}
                  >
                    <div className={`w-2 h-2 rounded-full shrink-0 ${
                      inc.severity === 'critical' ? 'bg-red-500' : inc.severity === 'high' ? 'bg-orange-500' : 'bg-amber-400'
                    }`} />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-slate-700 truncate">
                        {inc.incident_type || inc.type || 'Incident'}
                      </p>
                      <p className="text-[10px] text-slate-400">{inc.severity}</p>
                    </div>
                    <ChevronRight className="w-3 h-3 text-slate-300 shrink-0" />
                  </button>
                );
              })
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default EmergencyMap;
