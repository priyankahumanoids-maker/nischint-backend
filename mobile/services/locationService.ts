// Location Service — adaptive GPS tracking for Journey Engine.
//
// Strategy:
//   • Uses expo-location foreground tracking (starts/stops with lifecycle).
//   • Background tracking is handled by the existing backgroundLocation.ts
//     TaskManager task; this service focuses on the foreground stream
//     and publishing `location_update` events into journeyService.
//   • Adaptive interval:
//        moving  → 15 s
//        idle    → 60 s
//        low bat → 90 s
//   • Debounce: only send if moved ≥ 25 m OR interval elapsed.

import * as Location from 'expo-location';
import { sendEvent } from './journeyService';
import { useJourneyEngineStore } from '../stores/journeyEngineStore';
import { requireConsent } from './consentService';

const MOVING_INTERVAL_MS = 15_000;
const IDLE_INTERVAL_MS = 60_000;
const LOWBAT_INTERVAL_MS = 90_000;
const DISTANCE_THRESHOLD_M = 25;
const IDLE_SPEED_THRESHOLD = 0.5; // m/s — slower than walking
const IDLE_TIME_MS = 5 * 60_000;  // 5 min below threshold = idle

let _watchSub: Location.LocationSubscription | null = null;
let _lastSentAt = 0;
let _lastSentLat: number | null = null;
let _lastSentLng: number | null = null;
let _lastMovingAt = Date.now();
let _lowBattery = false;
let _sessionId: string = 'default';

function haversineMeters(a: { lat: number; lng: number }, b: { lat: number; lng: number }): number {
  const R = 6371000;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

function currentInterval(): number {
  if (_lowBattery) return LOWBAT_INTERVAL_MS;
  const idle = Date.now() - _lastMovingAt > IDLE_TIME_MS;
  return idle ? IDLE_INTERVAL_MS : MOVING_INTERVAL_MS;
}

export function setLowBatteryMode(on: boolean): void {
  _lowBattery = on;
}

export function setSessionId(sid: string): void {
  _sessionId = sid;
}

export async function ensureLocationPermissions(): Promise<boolean> {
  try {
    // DPDP-04-MOB — show pre-permission consent half-modal before the
    // native OS prompt. If the user declines here we never invoke
    // the OS prompt, keeping the system permission state "undetermined"
    // and respecting the data principal's choice.
    const consent = await requireConsent('location_tracking');
    if (!consent) {
      console.warn('[LOC_SVC] DPDP consent declined — skipping native prompt');
      return false;
    }
    const fg = await Location.requestForegroundPermissionsAsync();
    if (fg.status !== 'granted') {
      console.warn('[LOC_SVC] foreground permission denied');
      return false;
    }
    // Background permission is optional — request but don't block journey on it.
    try {
      await Location.requestBackgroundPermissionsAsync();
    } catch (e) {
      console.warn('[LOC_SVC] background permission unavailable', e);
    }
    return true;
  } catch (e) {
    console.error('[LOC_SVC] permission error', e);
    return false;
  }
}

export async function startLocationTracking(sessionId: string): Promise<boolean> {
  _sessionId = sessionId;
  if (_watchSub) return true;
  const ok = await ensureLocationPermissions();
  if (!ok) return false;

  try {
    _watchSub = await Location.watchPositionAsync(
      {
        accuracy: Location.Accuracy.Balanced,
        timeInterval: 10_000,
        distanceInterval: 10,
      },
      (pos) => {
        void onLocationUpdate(pos);
      }
    );
    console.log('[LOC_SVC] tracking started');
    return true;
  } catch (e) {
    console.error('[LOC_SVC] watch start failed', e);
    return false;
  }
}

export function stopLocationTracking(): void {
  if (_watchSub) {
    _watchSub.remove();
    _watchSub = null;
    console.log('[LOC_SVC] tracking stopped');
  }
}

async function onLocationUpdate(pos: Location.LocationObject): Promise<void> {
  const { latitude, longitude, accuracy, speed } = pos.coords;
  const now = Date.now();

  // SF-01 v2 Day 1 — feed GPS speed into the fall detector for its
  // vehicle-suppression guard. expo-location reports speed in m/s
  // (or null when unavailable); the fall detector contract is km/h.
  if (typeof speed === 'number' && speed >= 0) {
    try {
      // Lazy import keeps the existing locationService start-up
      // contract unchanged when fallDetection isn't loaded.
      const { updateGpsSpeed } = await import('./fallDetection');
      updateGpsSpeed(speed * 3.6);
    } catch {
      // fall detector not loaded — non-fatal, GPS guard simply
      // stays off until it imports.
    }
  }

  // SF-01 v2 Day 2 — push the same fix to motionTelemetryService so
  // its 30s /signals/motion heartbeat doesn't have to take its own
  // GPS read. Lazy import for the same reason as updateGpsSpeed.
  try {
    const { setLatestLocation } = await import('./motionTelemetryService');
    setLatestLocation(latitude, longitude);
  } catch {
    // motionTelemetry not loaded — heartbeat will emit with lat=0,lng=0.
  }

  // Movement/idle bookkeeping
  if (typeof speed === 'number' && speed > IDLE_SPEED_THRESHOLD) {
    _lastMovingAt = now;
  }

  // Debounce: enforce adaptive interval AND distance threshold
  const interval = currentInterval();
  const intervalElapsed = now - _lastSentAt >= interval;
  let distanceOk = true;
  if (_lastSentLat != null && _lastSentLng != null) {
    const d = haversineMeters(
      { lat: _lastSentLat, lng: _lastSentLng },
      { lat: latitude, lng: longitude }
    );
    distanceOk = d >= DISTANCE_THRESHOLD_M;
  }

  if (!intervalElapsed && !distanceOk) return;

  _lastSentAt = now;
  _lastSentLat = latitude;
  _lastSentLng = longitude;

  // Update store
  useJourneyEngineStore.getState().setLastLocation({
    lat: latitude,
    lng: longitude,
    accuracy: accuracy ?? undefined,
    speed: speed ?? null,
    ts: now,
  });

  // Queue via journeyService (offline-safe)
  await sendEvent('location_update', {
    sessionId: _sessionId,
    lat: latitude,
    lng: longitude,
    accuracy: accuracy ?? null,
    speed: speed ?? null,
    timestamp: now,
  });
  useJourneyEngineStore.getState().bumpLocationSent();
}
