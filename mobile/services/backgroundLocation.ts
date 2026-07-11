// Background Location Task — must be defined at module top level (expo-task-manager requirement)
// This file is imported early in _layout.tsx to register the task before the app renders.
import * as TaskManager from 'expo-task-manager';
import * as Location from 'expo-location';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Platform } from 'react-native';

export const BACKGROUND_LOCATION_TASK = 'nischint-emergency-location';
const ACTIVE_KEY = 'nischint:active_emergency';
const LOCATION_BATCH_KEY = 'nischint:location_batch';

// ── Task Definition (runs even when app is backgrounded) ──

TaskManager.defineTask(BACKGROUND_LOCATION_TASK, async ({ data, error }) => {
  if (error) return;
  if (!data) return;

  const { locations } = data as { locations: Location.LocationObject[] };
  if (!locations || locations.length === 0) return;

  // Read active emergency from AsyncStorage (background task has no access to React state)
  try {
    const stored = await AsyncStorage.getItem(ACTIVE_KEY);
    if (!stored) return;
    const emergency = JSON.parse(stored);
    if (!emergency.event_id || emergency.event_id === 'pending') return;

    const latest = locations[locations.length - 1];
    const lat = latest.coords.latitude;
    const lng = latest.coords.longitude;

    // Read API base URL from storage (set during app init)
    const apiBase = await AsyncStorage.getItem('nischint:api_base');
    const token = await _getToken();

    if (!apiBase || !token) {
      // Queue location for later send
      await _queueLocation(emergency.event_id, lat, lng);
      return;
    }

    // POST location update directly (no axios in background task — use fetch)
    try {
      const res = await fetch(`${apiBase}/api/emergency/location-update`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          event_id: emergency.event_id,
          lat,
          lng,
        }),
      });

      if (!res.ok) {
        await _queueLocation(emergency.event_id, lat, lng);
      }
    } catch {
      // Network failure — queue for retry
      await _queueLocation(emergency.event_id, lat, lng);
    }
  } catch {
    // Silently fail — task will retry on next location update
  }
});

// ── Start Background Location Tracking ──

const EMERGENCY_INTERVAL = 5000;   // 5s during active SOS
const PASSIVE_INTERVAL = 20000;    // 20s for non-emergency monitoring

export type TrackingMode = 'emergency' | 'passive';

export async function startBackgroundLocationTracking(mode: TrackingMode = 'emergency'): Promise<boolean> {
  try {
    // Stop existing task first to apply new config
    const isRunning = await Location.hasStartedLocationUpdatesAsync(BACKGROUND_LOCATION_TASK).catch(() => false);
    if (isRunning) await Location.stopLocationUpdatesAsync(BACKGROUND_LOCATION_TASK);

    const { status } = await Location.requestBackgroundPermissionsAsync();
    if (status !== 'granted') {
      console.warn('Background location permission denied');
      return false;
    }

    const isEmergency = mode === 'emergency';
    const interval = isEmergency ? EMERGENCY_INTERVAL : PASSIVE_INTERVAL;

    await Location.startLocationUpdatesAsync(BACKGROUND_LOCATION_TASK, {
      accuracy: isEmergency ? Location.Accuracy.High : Location.Accuracy.Balanced,
      timeInterval: interval,
      distanceInterval: isEmergency ? 5 : 20, // 5m emergency, 20m passive
      deferredUpdatesInterval: interval,
      showsBackgroundLocationIndicator: isEmergency, // Blue bar only during SOS
      foregroundService: {
        notificationTitle: isEmergency ? 'NISCHINT Emergency Active' : 'NISCHINT Safety Monitoring',
        notificationBody: isEmergency
          ? 'Live location tracking is active. Your guardians can see your location.'
          : 'Background safety monitoring active.',
        notificationColor: isEmergency ? '#EF4444' : '#0EA5E9',
      },
      activityType: Location.ActivityType.OtherNavigation,
      pausesUpdatesAutomatically: !isEmergency,
    });

    return true;
  } catch (err) {
    console.error('Failed to start background location:', err);
    return false;
  }
}

// ── Stop Background Location Tracking ──

export async function stopBackgroundLocationTracking(): Promise<void> {
  try {
    const isRunning = await Location.hasStartedLocationUpdatesAsync(BACKGROUND_LOCATION_TASK).catch(() => false);
    if (isRunning) {
      await Location.stopLocationUpdatesAsync(BACKGROUND_LOCATION_TASK);
    }
  } catch {
    // Already stopped or never started
  }
}

// ── Flush Queued Locations (call when app returns to foreground) ──

export async function flushQueuedLocations(): Promise<void> {
  try {
    const stored = await AsyncStorage.getItem(LOCATION_BATCH_KEY);
    if (!stored) return;

    const batch: Array<{ event_id: string; lat: number; lng: number }> = JSON.parse(stored);
    if (batch.length === 0) return;

    const apiBase = await AsyncStorage.getItem('nischint:api_base');
    const token = await _getToken();
    if (!apiBase || !token) return;

    // Send queued locations (latest is most important)
    for (const loc of batch) {
      try {
        await fetch(`${apiBase}/api/emergency/location-update`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify(loc),
        });
      } catch {
        break; // Still offline, stop trying
      }
    }

    await AsyncStorage.removeItem(LOCATION_BATCH_KEY);
  } catch {
    // Silently fail
  }
}

// ── Helpers ──

async function _getToken(): Promise<string | null> {
  if (Platform.OS === 'web') {
    return typeof localStorage !== 'undefined' ? localStorage.getItem('nischint_token') : null;
  }
  try {
    const SecureStore = require('expo-secure-store');
    return await SecureStore.getItemAsync('nischint_token');
  } catch {
    return null;
  }
}

async function _queueLocation(eventId: string, lat: number, lng: number): Promise<void> {
  try {
    const stored = await AsyncStorage.getItem(LOCATION_BATCH_KEY);
    const batch = stored ? JSON.parse(stored) : [];
    batch.push({ event_id: eventId, lat, lng });
    // Keep max 100 queued locations (prevent storage bloat)
    const trimmed = batch.slice(-100);
    await AsyncStorage.setItem(LOCATION_BATCH_KEY, JSON.stringify(trimmed));
  } catch {
    // Silently fail
  }
}
