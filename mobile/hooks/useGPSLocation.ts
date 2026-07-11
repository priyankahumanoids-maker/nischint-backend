// GPS Location Hook — SINGLETON core location system for NISCHINT.
//
// One Location.watchPositionAsync subscription shared across all
// consumers via ref-counting. Two screens that both `useGPSLocation()`
// → ONE GPS stream + one AppState listener; previously two of each.
//
// GPS is the primary system. Map is just a visual layer on top.
// Location MUST always be available even if map fails.
//
// Logs:
//   [LOCATION_WATCHER] — singleton start/stop
//   [APPSTATE_LISTENER] — AppState registration
//   [GPS] — fix events
import { useState, useEffect, useRef, useCallback } from 'react';
import * as Location from 'expo-location';
import { AppState } from 'react-native';

export interface GPSState {
  latitude: number | null;
  longitude: number | null;
  accuracy: number | null;
  altitude: number | null;
  speed: number | null;
  heading: number | null;
  timestamp: number | null;
  permissionStatus: 'undetermined' | 'granted' | 'denied';
  isLoading: boolean;
  error: string | null;
}

const INITIAL_STATE: GPSState = {
  latitude: null,
  longitude: null,
  accuracy: null,
  altitude: null,
  speed: null,
  heading: null,
  timestamp: null,
  permissionStatus: 'undetermined',
  isLoading: true,
  error: null,
};

interface UseGPSOptions {
  watchPosition?: boolean;
  intervalMs?: number;
}

// ── Module-level singleton state ───────────────────────────────────
let _state: GPSState = { ...INITIAL_STATE };
const _listeners: Set<(s: GPSState) => void> = new Set();
let _watchSub: Location.LocationSubscription | null = null;
let _pollInterval: ReturnType<typeof setInterval> | null = null;
let _appStateSub: any = null;
let _refCount = 0;
let _initInFlight = false;
let _activeWatchOptions: UseGPSOptions = {};

function _emit() {
  _listeners.forEach((l) => {
    try { l(_state); } catch {}
  });
}

function _setState(patch: Partial<GPSState>) {
  _state = { ..._state, ...patch };
  _emit();
}

function _updateLocation(loc: Location.LocationObject) {
  const { latitude, longitude, accuracy, altitude, speed, heading } = loc.coords;
  console.log(
    `[GPS] lat=${latitude.toFixed(6)} lng=${longitude.toFixed(6)} ` +
    `accuracy=${accuracy?.toFixed(1)}m`
  );
  _setState({
    latitude, longitude, accuracy, altitude, speed, heading,
    timestamp: loc.timestamp,
    isLoading: false,
    error: null,
  });
}

async function _ensureWatcher(options: UseGPSOptions) {
  if (_watchSub || _pollInterval) {
    console.log('[LOCATION_WATCHER] singleton already active — reusing');
    return;
  }
  if (!options.watchPosition) return;

  const intervalMs = options.intervalMs ?? 5000;
  console.log(`[LOCATION_WATCHER] starting singleton watch (interval ~${intervalMs}ms)`);
  try {
    _watchSub = await Location.watchPositionAsync(
      {
        accuracy: Location.Accuracy.High,
        timeInterval: intervalMs,
        distanceInterval: 5,
      },
      _updateLocation
    );
  } catch (err: any) {
    console.warn('[LOCATION_WATCHER] watch failed, falling back to poll:', err?.message);
    _pollInterval = setInterval(async () => {
      try {
        const loc = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.Balanced,
        });
        _updateLocation(loc);
      } catch {}
    }, intervalMs);
  }
}

async function _initialize(options: UseGPSOptions) {
  if (_initInFlight) return;
  _initInFlight = true;
  try {
    console.log('[GPS] requesting permission...');
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== 'granted') {
      _setState({
        permissionStatus: 'denied',
        isLoading: false,
        error: 'Location permission denied. Please enable in Settings.',
      });
      return;
    }
    _setState({ permissionStatus: 'granted' });

    const enabled = await Location.hasServicesEnabledAsync();
    if (!enabled) {
      _setState({
        isLoading: false,
        error: 'GPS is disabled. Please enable Location Services.',
      });
      return;
    }

    try {
      const loc = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.High,
      });
      _updateLocation(loc);
    } catch {
      try {
        const loc = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.Balanced,
        });
        _updateLocation(loc);
      } catch (fallbackErr: any) {
        _setState({
          isLoading: false,
          error: 'Could not get GPS fix. Try moving to an open area.',
        });
      }
    }

    await _ensureWatcher(options);
  } finally {
    _initInFlight = false;
  }
}

function _setupAppState() {
  if (_appStateSub) return;
  console.log('[APPSTATE_LISTENER] gps registered');
  _appStateSub = AppState.addEventListener('change', (state) => {
    if (state === 'active' && _refCount > 0) {
      // Refresh on foreground — single fetch, no extra watcher.
      Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High })
        .then(_updateLocation)
        .catch(() => {});
    }
  });
}

function _teardown() {
  console.log('[LOCATION_WATCHER] singleton tearing down (refCount=0)');
  if (_watchSub) {
    try { _watchSub.remove(); } catch {}
    _watchSub = null;
  }
  if (_pollInterval) {
    clearInterval(_pollInterval);
    _pollInterval = null;
  }
  if (_appStateSub) {
    _appStateSub.remove();
    _appStateSub = null;
  }
}

function _attach(options: UseGPSOptions) {
  _refCount += 1;
  if (_refCount === 1) {
    console.log('[LOCATION_WATCHER] first consumer — initializing singleton');
    _activeWatchOptions = options;
    _setupAppState();
    _initialize(options);
  } else {
    console.log(`[LOCATION_WATCHER] consumer #${_refCount} (reusing singleton)`);
  }
}

function _detach() {
  _refCount = Math.max(0, _refCount - 1);
  if (_refCount === 0) {
    _teardown();
    _state = { ...INITIAL_STATE };
  }
}

// ── Public hook ────────────────────────────────────────────────────
export function useGPSLocation(options: UseGPSOptions = {}) {
  const watchPosition = options.watchPosition ?? true;
  const intervalMs    = options.intervalMs    ?? 5000;
  const [gps, setGps] = useState<GPSState>(_state);
  const optsRef = useRef({ watchPosition, intervalMs });
  optsRef.current = { watchPosition, intervalMs };

  // Stable listener registered exactly once per consumer.
  const listenerRef = useRef((s: GPSState) => setGps(s));

  useEffect(() => {
    _listeners.add(listenerRef.current);
    _attach({ watchPosition: optsRef.current.watchPosition,
              intervalMs:    optsRef.current.intervalMs });
    // Immediate sync for late subscribers.
    setGps(_state);
    return () => {
      _listeners.delete(listenerRef.current);
      _detach();
    };
    // Intentionally no deps — singleton lifecycle is reference-counted,
    // not config-controlled. Changing options would not retroactively
    // restart the watcher; if you need to change intervals at runtime
    // expose a dedicated `reconfigureGPSLocation()` function.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refresh = useCallback(async () => {
    try {
      const loc = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.High,
      });
      _updateLocation(loc);
    } catch {}
  }, []);

  const secondsAgo = gps.timestamp
    ? Math.round((Date.now() - gps.timestamp) / 1000)
    : null;

  return { ...gps, secondsAgo, refresh };
}
