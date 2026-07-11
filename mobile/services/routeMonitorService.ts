// Route / Wandering Detection Service
//
// During an active journey:
//  1. Subscribe to GPS updates every 10s
//  2. Compare current location to planned route polyline
//  3. If deviation > 200m sustained for > 3 minutes → wandering detected
//  4. POST /api/sensors/wandering/check
//  5. Show alert banner with "I'm OK - Taking a detour" / "Need help"

import * as Location from 'expo-location';
import api from './api';
import type { SafetyAlert, SensorCallbacks } from './sensorService';

// ── Config ──

const GPS_INTERVAL_MS = 10_000;          // 10 seconds
const DEVIATION_THRESHOLD_M = 200;       // metres off-route
const SUSTAINED_DURATION_MS = 3 * 60_000; // 3 minutes
const COOLDOWN_MS = 5 * 60_000;          // 5 min between detections

// ── State ──

interface RouteMonitorState {
  isMonitoring: boolean;
  routePoints: { lat: number; lng: number }[];
  plannedRouteId?: string;
  deviationStart: number | null;
  lastAlertTime: number;
}

const state: RouteMonitorState = {
  isMonitoring: false,
  routePoints: [],
  plannedRouteId: undefined,
  deviationStart: null,
  lastAlertTime: 0,
};

let _locationSub: Location.LocationSubscription | null = null;
let _onAlert: SensorCallbacks['onAlert'] | null = null;
let _onCountdown: SensorCallbacks['onCountdown'] | null = null;
let _onAutoSOS: SensorCallbacks['onAutoSOS'] | null = null;
let _activeAlert: SafetyAlert | null = null;
let _countdownTimer: ReturnType<typeof setInterval> | null = null;

// ── Geo Helpers ──

/** Haversine distance in metres between two lat/lng points */
function haversineM(
  lat1: number, lng1: number,
  lat2: number, lng2: number,
): number {
  const R = 6_371_000; // Earth radius in metres
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function toRad(deg: number): number {
  return deg * (Math.PI / 180);
}

/**
 * Minimum distance from a point to a polyline (series of segments).
 * Returns metres.
 */
function distanceToRoute(
  lat: number, lng: number,
  route: { lat: number; lng: number }[],
): number {
  if (route.length === 0) return Infinity;
  if (route.length === 1) return haversineM(lat, lng, route[0].lat, route[0].lng);

  let minDist = Infinity;
  for (let i = 0; i < route.length - 1; i++) {
    const d = pointToSegmentDistance(lat, lng, route[i], route[i + 1]);
    if (d < minDist) minDist = d;
  }
  return minDist;
}

/** Approximate closest distance from point to a line segment */
function pointToSegmentDistance(
  lat: number, lng: number,
  a: { lat: number; lng: number },
  b: { lat: number; lng: number },
): number {
  const segLen = haversineM(a.lat, a.lng, b.lat, b.lng);
  if (segLen < 1) return haversineM(lat, lng, a.lat, a.lng);

  // Project point onto segment via parameter t (clamped 0-1)
  const dx = b.lng - a.lng;
  const dy = b.lat - a.lat;
  const t = Math.max(0, Math.min(1,
    ((lng - a.lng) * dx + (lat - a.lat) * dy) / (dx * dx + dy * dy),
  ));

  const projLat = a.lat + t * dy;
  const projLng = a.lng + t * dx;
  return haversineM(lat, lng, projLat, projLng);
}

// ── Countdown ──

function clearCountdown() {
  if (_countdownTimer) {
    clearInterval(_countdownTimer);
    _countdownTimer = null;
  }
}

async function triggerSOS(alert: SafetyAlert) {
  clearCountdown();
  try {
    await api.post('/sos/trigger', {
      trigger_type: 'auto',
      lat: alert.location?.lat ?? 0,
      lng: alert.location?.lng ?? 0,
    });
  } catch (e) {
    console.error('[RouteService] SOS failed:', e);
  }
  _onAutoSOS?.(alert.id);
  _activeAlert = null;
}

// ── Core Logic ──

function processLocation(coords: Location.LocationObjectCoords) {
  const now = Date.now();
  const { latitude: lat, longitude: lng, speed, heading } = coords;

  if (now - state.lastAlertTime < COOLDOWN_MS) return;
  if (state.routePoints.length === 0) return;

  const deviation = distanceToRoute(lat, lng, state.routePoints);

  if (deviation > DEVIATION_THRESHOLD_M) {
    // Start or continue deviation timer
    if (!state.deviationStart) {
      state.deviationStart = now;
    }

    const duration = now - state.deviationStart;
    if (duration >= SUSTAINED_DURATION_MS) {
      // Wandering confirmed
      state.lastAlertTime = now;
      state.deviationStart = null;
      reportWandering(lat, lng, deviation, speed ?? 0, heading ?? 0);
    }
  } else {
    // Back on route — reset
    state.deviationStart = null;
  }
}

async function reportWandering(
  lat: number, lng: number,
  deviation: number, speed: number, heading: number,
) {
  let eventId: string | undefined;
  try {
    const res = await api.post('/sensors/wandering/check', { lat, lng, speed, heading });
    eventId = res.data?.event_id;
  } catch (e) {
    console.error('[RouteService] Report failed:', e);
  }

  const alert: SafetyAlert = {
    id: `wander-${Date.now()}`,
    type: 'wandering',
    message: "You seem to be off your route — are you OK?",
    timestamp: Date.now(),
    countdownSeconds: 30,
    secondsRemaining: 30,
    eventId,
    location: { lat, lng },
    data: { deviation_metres: Math.round(deviation), planned_route_id: state.plannedRouteId },
    actions: [
      { label: "I'm OK - Taking a detour", key: 'detour' },
      { label: 'Need help', key: 'help' },
    ],
  };

  _activeAlert = alert;
  _onAlert?.(alert);

  // No auto-SOS for wandering — but if user taps "Need help" it triggers SOS
}

// ── Public API ──

/**
 * Start route monitoring during an active journey.
 * @param routePoints Planned route polyline [{lat,lng}, ...]
 * @param routeId Optional route identifier
 */
export async function startRouteMonitoring(
  callbacks: SensorCallbacks,
  routePoints: { lat: number; lng: number }[],
  routeId?: string,
): Promise<() => void> {
  _onAlert = callbacks.onAlert;
  _onCountdown = callbacks.onCountdown;
  _onAutoSOS = callbacks.onAutoSOS;

  state.isMonitoring = true;
  state.routePoints = routePoints;
  state.plannedRouteId = routeId;
  state.deviationStart = null;

  const { status } = await Location.requestForegroundPermissionsAsync();
  if (status !== 'granted') {
    console.warn('[RouteService] Location permission denied');
    return () => {};
  }

  _locationSub = await Location.watchPositionAsync(
    {
      accuracy: Location.Accuracy.High,
      timeInterval: GPS_INTERVAL_MS,
      distanceInterval: 10, // also trigger on 10m movement
    },
    (location) => {
      if (state.isMonitoring) {
        processLocation(location.coords);
      }
    },
  );

  return () => stopRouteMonitoring();
}

/**
 * Handle user response to wandering alert.
 * @param key 'detour' = dismiss, 'help' = trigger SOS
 */
export async function handleWanderingResponse(alertId: string, key: string): Promise<void> {
  clearCountdown();
  const alert = _activeAlert;

  if (key === 'help') {
    if (alert) await triggerSOS(alert);
    return;
  }

  // "detour" — resolve
  if (alert?.eventId) {
    try {
      await api.post('/sensors/wandering/resolve', { event_id: alert.eventId });
    } catch {}
  }
  _activeAlert = null;
}

export function stopRouteMonitoring(): void {
  clearCountdown();
  state.isMonitoring = false;
  state.routePoints = [];
  state.deviationStart = null;
  if (_locationSub) {
    _locationSub.remove();
    _locationSub = null;
  }
  _onAlert = null;
  _onCountdown = null;
  _onAutoSOS = null;
  _activeAlert = null;
}

export function isRouteMonitoringActive(): boolean {
  return state.isMonitoring;
}
