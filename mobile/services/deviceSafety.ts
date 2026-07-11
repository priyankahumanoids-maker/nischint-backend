// Device Safety Service — Shake detection, SOS trigger, location tracking, offline queue
import { Platform, Vibration } from 'react-native';
import * as Location from 'expo-location';
import { Accelerometer } from 'expo-sensors';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { emergencyService } from './emergency';
import {
  startBackgroundLocationTracking,
  stopBackgroundLocationTracking,
  flushQueuedLocations,
  type TrackingMode,
} from './backgroundLocation';

const SHAKE_THRESHOLD = 2.5; // g-force
const SHAKE_COUNT_TRIGGER = 3; // shakes needed
const SHAKE_WINDOW_MS = 2000; // within 2 seconds
const LOCATION_UPDATE_INTERVAL = 5000; // 5 seconds

// Exponential backoff retry schedule
const RETRY_DELAYS_MS = [0, 3000, 6000, 12000]; // 0s, 3s, 6s, 12s

const ACTIVE_KEY = 'nischint:active_emergency';
const QUEUE_KEY = 'nischint:sos_queue';

type ServiceState = {
  eventId: string | null;
  isActive: boolean;
  cancelPin: string;
  backgroundTrackingActive: boolean;
};

const state: ServiceState = {
  eventId: null,
  isActive: false,
  cancelPin: '',
  backgroundTrackingActive: false,
};

let shakeTimestamps: number[] = [];
let shakeSubscription: any = null;

// ── Shake Detection ──

export function startShakeDetection(onShake: () => void) {
  try {
    Accelerometer.setUpdateInterval(100); // 10 Hz

    shakeSubscription = Accelerometer.addListener(({ x, y, z }) => {
      const magnitude = Math.sqrt(x * x + y * y + z * z);

      if (magnitude > SHAKE_THRESHOLD) {
        const now = Date.now();
        shakeTimestamps.push(now);

        // Remove old timestamps outside window
        shakeTimestamps = shakeTimestamps.filter((t) => now - t < SHAKE_WINDOW_MS);

        if (shakeTimestamps.length >= SHAKE_COUNT_TRIGGER) {
          shakeTimestamps = [];
          try { onShake(); } catch (e) { console.warn('[SHAKE] onShake callback error:', (e as any)?.message || e); }
        }
      }
    });
  } catch (e) {
    console.warn('[SHAKE] Accelerometer unavailable — shake detection disabled:', (e as any)?.message || e);
    return () => {};
  }

  return () => {
    try {
      if (shakeSubscription) {
        shakeSubscription.remove();
        shakeSubscription = null;
      }
    } catch {}
  };
}

export function stopShakeDetection() {
  if (shakeSubscription) {
    shakeSubscription.remove();
    shakeSubscription = null;
  }
}

// ── SOS Trigger (immediate — no delay) ──

// Debounce guard: prevent duplicate SOS events within 8 seconds.
// Covers shake + fall + manual + hold-button from a single centralized guard.
// Reset when the active emergency is cancelled (see cancelSOS below).
const SOS_COOLDOWN_MS = 8000;
let _lastSosAttemptAt = 0;
function _canTriggerSOS(): boolean {
  return Date.now() - _lastSosAttemptAt > SOS_COOLDOWN_MS;
}

export async function triggerSilentSOS(
  cancelPin: string = '1234',
  triggerSource: string = 'shake',
): Promise<{ success: boolean; eventId?: string; error?: string }> {
  // Debounce: reject if another trigger happened within cooldown window.
  // Returns success=true + event_id of the active emergency if one exists so
  // the caller can show the "already active" UI without firing duplicate alerts.
  if (!_canTriggerSOS()) {
    const existing = state.eventId && state.isActive ? state.eventId : undefined;
    console.log(`[SOS_DEBOUNCE] Ignored ${triggerSource} — within ${SOS_COOLDOWN_MS}ms cooldown`);
    return {
      success: !!existing,
      eventId: existing,
      error: existing ? undefined : 'cooldown_active',
    };
  }
  _lastSosAttemptAt = Date.now();

  try {
    // Vibrate to confirm (subtle)
    Vibration.vibrate([0, 100, 50, 100]);

    // Request location permission, then get position — fallback to 0,0 if denied
    let lat = 0;
    let lng = 0;
    let deviceMetadata: Record<string, any> = {
      platform: Platform.OS,
      timestamp: new Date().toISOString(),
    };

    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status === 'granted') {
        const loc = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.High,
        });
        lat = loc.coords.latitude;
        lng = loc.coords.longitude;
        deviceMetadata.accuracy = loc.coords.accuracy;
        deviceMetadata.altitude = loc.coords.altitude;
        deviceMetadata.speed = loc.coords.speed;
      }
    } catch {
      // Location unavailable — continue with 0,0
    }

    state.cancelPin = cancelPin;

    // POST immediately — never delay the backend call
    try {
      const res = await emergencyService.triggerSOS(
        lat,
        lng,
        triggerSource,
        cancelPin,
        deviceMetadata,
      );

      state.eventId = res.data.event_id;
      state.isActive = true;

      // Start live location tracking (background-capable, survives app minimize)
      await startLocationTracking(res.data.event_id);

      // Persist to AsyncStorage for crash recovery
      await AsyncStorage.setItem(
        ACTIVE_KEY,
        JSON.stringify({
          event_id: res.data.event_id,
          started_at: new Date().toISOString(),
          trigger: triggerSource,
          cancel_pin: cancelPin,
        }),
      );

      return { success: true, eventId: res.data.event_id };
    } catch {
      // Offline — queue with exponential backoff retry
      await queueOfflineSOS(lat, lng, triggerSource, cancelPin, deviceMetadata);
      return { success: true, error: 'offline_queued' };
    }
  } catch (err: any) {
    return { success: false, error: err.message || 'Failed to trigger SOS' };
  }
}

// ── Cancel SOS ──

export async function cancelSOS(
  pin: string,
  fallbackEventId?: string | null,
): Promise<{ success: boolean; error?: string }> {
  const eventId = state.eventId || fallbackEventId;
  if (!eventId) return { success: false, error: 'No active emergency' };

  try {
    const res = await emergencyService.cancel(eventId, pin);
    if (res.data.status === 'cancelled') {
      stopLocationTracking();
      state.isActive = false;
      state.eventId = null;
      _lastSosAttemptAt = 0; // reset cooldown — user can immediately re-trigger if needed
      await AsyncStorage.removeItem(ACTIVE_KEY);
      return { success: true };
    }
    return { success: false, error: 'Cancel failed' };
  } catch (err: any) {
    const detail = err.response?.data?.detail || '';
    // Already resolved/cancelled from web — clear local state too
    if (detail.includes('already') || detail.includes('not active')) {
      stopLocationTracking();
      state.isActive = false;
      state.eventId = null;
      _lastSosAttemptAt = 0; // reset cooldown
      await AsyncStorage.removeItem(ACTIVE_KEY);
      return { success: true };
    }
    if (detail === 'Invalid cancellation PIN') {
      return { success: false, error: 'Wrong PIN. Please try again.' };
    }
    return { success: false, error: detail || 'Cancel failed' };
  }
}

// ── Location Tracking (background-capable, survives app minimize) ──

async function startLocationTracking(eventId: string, mode: TrackingMode = 'emergency') {
  await stopLocationTracking();

  // Store API base URL for background task access
  const { API_BASE } = require('./api');
  await AsyncStorage.setItem('nischint:api_base', API_BASE);

  // Try background tracking first (works when app is minimized)
  const bgStarted = await startBackgroundLocationTracking(mode);
  state.backgroundTrackingActive = bgStarted;

  if (!bgStarted) {
    // Fallback: foreground-only interval (web or permission denied)
    state.backgroundTrackingActive = false;
    const interval = mode === 'emergency' ? LOCATION_UPDATE_INTERVAL : 20000;
    _startForegroundFallback(eventId, interval);
  }
}

async function stopLocationTracking() {
  if (state.backgroundTrackingActive) {
    await stopBackgroundLocationTracking();
    state.backgroundTrackingActive = false;
  }
  _stopForegroundFallback();
}

// Foreground fallback for web or when background permission is denied
let _foregroundIntervalId: NodeJS.Timeout | null = null;

function _startForegroundFallback(eventId: string, interval: number = LOCATION_UPDATE_INTERVAL) {
  _stopForegroundFallback();
  _foregroundIntervalId = setInterval(async () => {
    try {
      const loc = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.High,
      });
      await emergencyService.updateLocation(
        eventId,
        loc.coords.latitude,
        loc.coords.longitude,
      );
    } catch {
      // Silently fail — will retry next interval
    }
  }, interval);
}

function _stopForegroundFallback() {
  if (_foregroundIntervalId) {
    clearInterval(_foregroundIntervalId);
    _foregroundIntervalId = null;
  }
}

// ── Offline Queue with Exponential Backoff ──

async function queueOfflineSOS(
  lat: number,
  lng: number,
  triggerSource: string,
  cancelPin: string,
  deviceMetadata: object,
) {
  const queued = {
    lat,
    lng,
    triggerSource,
    cancelPin,
    deviceMetadata,
    queuedAt: new Date().toISOString(),
  };
  await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(queued));

  let attempt = 0;

  const tryRetry = async () => {
    const stored = await AsyncStorage.getItem(QUEUE_KEY);
    if (!stored) return; // Already sent successfully

    try {
      const data = JSON.parse(stored);
      const res = await emergencyService.triggerSOS(
        data.lat,
        data.lng,
        data.triggerSource,
        data.cancelPin,
        data.deviceMetadata,
      );

      // Success — clear queue, activate tracking
      await AsyncStorage.removeItem(QUEUE_KEY);
      state.eventId = res.data.event_id;
      state.isActive = true;
      state.cancelPin = data.cancelPin;
      await startLocationTracking(res.data.event_id);

      // Persist active state
      await AsyncStorage.setItem(
        ACTIVE_KEY,
        JSON.stringify({
          event_id: res.data.event_id,
          started_at: new Date().toISOString(),
          trigger: data.triggerSource,
          cancel_pin: data.cancelPin,
        }),
      );
    } catch {
      // Still offline — schedule next retry if attempts remain
      attempt++;
      if (attempt < RETRY_DELAYS_MS.length) {
        setTimeout(tryRetry, RETRY_DELAYS_MS[attempt]);
      }
      // After all retries exhausted, queued SOS remains in storage
      // Will be retried on next app launch
    }
  };

  // First retry is immediate (0ms delay)
  setTimeout(tryRetry, RETRY_DELAYS_MS[0]);
}

// ── Restore State on App Launch ──

export async function restoreEmergencyState(): Promise<boolean> {
  try {
    // First check for queued SOS that never sent
    const queued = await AsyncStorage.getItem(QUEUE_KEY);
    if (queued) {
      const data = JSON.parse(queued);
      // Re-attempt the queued SOS
      try {
        const res = await emergencyService.triggerSOS(
          data.lat,
          data.lng,
          data.triggerSource,
          data.cancelPin,
          data.deviceMetadata,
        );
        await AsyncStorage.removeItem(QUEUE_KEY);
        state.eventId = res.data.event_id;
        state.isActive = true;
        await startLocationTracking(res.data.event_id);
        return true;
      } catch {
        // Still offline — keep queued
      }
    }

    // Restore active emergency
    const stored = await AsyncStorage.getItem(ACTIVE_KEY);
    if (!stored) return false;

    const data = JSON.parse(stored);
    state.eventId = data.event_id;
    state.cancelPin = data.cancel_pin || '1234';
    state.isActive = true;

    // Resume location tracking
    if (data.event_id && data.event_id !== 'pending') {
      await startLocationTracking(data.event_id);
      // Flush any locations queued while app was in background
      await flushQueuedLocations();
    }

    return true;
  } catch {
    return false;
  }
}

export function getEmergencyState() {
  return { ...state };
}
