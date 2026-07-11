/**
 * NISCHINT — Journey Lifecycle Hook (React Native)
 * Platform adapter for the future React Native app.
 *
 * ⚠️  BLUEPRINT — not wired up yet.
 *     Same function signatures as the web adapter.
 *     Same JourneyEngine core.
 *     Only the platform APIs differ.
 *
 * React Native APIs used:
 *   AppState                           (RN core)
 *   @react-native-community/netinfo
 *   react-native-battery-optimization-check  (or expo-battery)
 *   react-native-geolocation-service
 *   @react-native-async-storage/async-storage
 */

import { useEffect, useRef, useCallback } from "react";
import { AppState, AppStateStatus } from "react-native";

// Future installs:
// import NetInfo from "@react-native-community/netinfo";
// import Geolocation from "react-native-geolocation-service";
// import AsyncStorage from "@react-native-async-storage/async-storage";
// import * as Battery from "expo-battery";  // or react-native-device-info

import {
  JourneySession,
  GeoPoint,
  createSession,
  handleForeground,
  handleBackground,
  handleOnline,
  handleOffline,
  appendGeoPoint,
  updateBattery,
  evaluateIdleRisk,
  enqueueEvent,
  flushEvents,
  serialiseSession,
  deserialiseSession,
  isLowBattery,
  IDLE_THRESHOLD_MS,
} from "./JourneyEngine";

// ─────────────────────────────────────────────
// CONSTANTS  (mirrors web adapter)
// ─────────────────────────────────────────────

const SESSION_STORAGE_KEY   = "nischint_journey_session";
const GEO_INTERVAL_MS       = 30_000;
const LOW_BATTERY_INTERVAL  = 90_000;
const IDLE_CHECK_INTERVAL   = 30_000;
const SYNC_FLUSH_INTERVAL   = 15_000;

// ─────────────────────────────────────────────
// CALLBACKS INTERFACE  (identical to web adapter)
// ─────────────────────────────────────────────

export interface JourneyCallbacks {
  onForeground?:  (session: JourneySession) => void;
  onBackground?:  (session: JourneySession) => void;
  onOnline?:      (session: JourneySession) => void;
  onOffline?:     (session: JourneySession) => void;
  onSafetyRisk?:  (session: JourneySession) => void;
  onSyncFlush?:   (events: ReturnType<typeof flushEvents>["toSend"]) => void;
  onLowBattery?:  (level: number) => void;
  onGeoUpdate?:   (point: GeoPoint) => void;
}

// ─────────────────────────────────────────────
// HOOK
// ─────────────────────────────────────────────

export function useJourneyLifecycle(callbacks: JourneyCallbacks = {}) {
  const sessionRef    = useRef<JourneySession>(createSession());
  const appStateRef   = useRef<AppStateStatus>(AppState.currentState);
  const callbacksRef  = useRef(callbacks);
  callbacksRef.current = callbacks;

  const getSession  = () => sessionRef.current;
  const setSession  = useCallback((next: JourneySession) => {
    sessionRef.current = next;
    persistSession(next);   // AsyncStorage equivalent
  }, []);

  // ── VISIBILITY ───────────────────────────────

  const handleAppStateChange = useCallback((nextState: AppStateStatus) => {
    const prev = appStateRef.current;
    appStateRef.current = nextState;

    if (prev.match(/inactive|background/) && nextState === "active") {
      const next = handleForeground(getSession());
      setSession(next);
      callbacksRef.current.onForeground?.(next);
      flushQueue();
    }

    if (nextState.match(/inactive|background/)) {
      const next = handleBackground(getSession());
      setSession(next);
      callbacksRef.current.onBackground?.(next);
    }
  }, [setSession]);

  // ── NETWORK ──────────────────────────────────
  // TODO: replace stub with real NetInfo.addEventListener

  const handleNetworkOnline = useCallback(() => {
    const next = handleOnline(getSession());
    setSession(next);
    callbacksRef.current.onOnline?.(next);
    flushQueue();
  }, [setSession]);

  const handleNetworkOffline = useCallback(() => {
    const next = handleOffline(getSession());
    setSession(next);
    callbacksRef.current.onOffline?.(next);
  }, [setSession]);

  // ── GEO ──────────────────────────────────────
  // TODO: replace with Geolocation.watchPosition for continuous background tracking

  const startGeoTracking = useCallback(() => {
    const capturePosition = () => {
      /*
      Geolocation.getCurrentPosition(
        (pos) => {
          const point: GeoPoint = {
            lat: pos.coords.latitude,
            lng: pos.coords.longitude,
            accuracy: pos.coords.accuracy,
            timestamp: Date.now(),
          };
          const withGeo   = appendGeoPoint(getSession(), point);
          const withEvent = enqueueEvent(withGeo, { type: "geo", payload: point });
          setSession(withEvent);
          callbacksRef.current.onGeoUpdate?.(point);
        },
        (err) => console.warn("[Journey/RN] Geo error:", err.message),
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
      );
      */
      console.log("[Journey/RN] 📍 Geo stub — wire up Geolocation");
    };

    capturePosition();
    const ms = isLowBattery(getSession()) ? LOW_BATTERY_INTERVAL : GEO_INTERVAL_MS;
    return setInterval(capturePosition, ms);
  }, [setSession]);

  // ── BATTERY ───────────────────────────────────
  // TODO: wire up expo-battery or react-native-device-info

  const initBattery = useCallback(async () => {
    /*
    const level = await Battery.getBatteryLevelAsync();
    setSession(updateBattery(getSession(), level));

    Battery.addBatteryLevelListener(({ batteryLevel }) => {
      setSession(updateBattery(getSession(), batteryLevel));
      if (batteryLevel <= 0.15) callbacksRef.current.onLowBattery?.(batteryLevel);
    });
    */
    console.log("[Journey/RN] 🔋 Battery stub — wire up expo-battery");
  }, [setSession]);

  // ── IDLE / SAFETY ─────────────────────────────

  const startIdleMonitor = useCallback(() => {
    return setInterval(() => {
      const evaluated = evaluateIdleRisk(getSession());
      setSession(evaluated);
      if (evaluated.riskLevel === "high" || evaluated.riskLevel === "critical") {
        callbacksRef.current.onSafetyRisk?.(evaluated);
      }
    }, IDLE_CHECK_INTERVAL);
  }, [setSession]);

  // ── SYNC QUEUE ────────────────────────────────

  const flushQueue = useCallback(() => {
    const { toSend, session: flushed } = flushEvents(getSession());
    if (toSend.length > 0) {
      setSession(flushed);
      callbacksRef.current.onSyncFlush?.(toSend);
    }
  }, [setSession]);

  const startSyncFlushInterval = useCallback(() => {
    return setInterval(flushQueue, SYNC_FLUSH_INTERVAL);
  }, [flushQueue]);

  // ── HEARTBEAT ─────────────────────────────────

  const startHeartbeat = useCallback(() => {
    return setInterval(() => {
      setSession(enqueueEvent(getSession(), {
        type: "heartbeat",
        payload: { ts: Date.now(), risk: getSession().riskLevel },
      }));
    }, IDLE_THRESHOLD_MS);
  }, [setSession]);

  // ── MOUNT / UNMOUNT ───────────────────────────

  useEffect(() => {
    const appStateSub = AppState.addEventListener("change", handleAppStateChange);

    // TODO: replace with real NetInfo subscription
    // const netSub = NetInfo.addEventListener((state) => {
    //   state.isConnected ? handleNetworkOnline() : handleNetworkOffline();
    // });

    initBattery();
    const geoInterval   = startGeoTracking();
    const idleInterval  = startIdleMonitor();
    const syncInterval  = startSyncFlushInterval();
    const hbInterval    = startHeartbeat();

    return () => {
      appStateSub.remove();
      // netSub();
      clearInterval(geoInterval);
      clearInterval(idleInterval);
      clearInterval(syncInterval);
      clearInterval(hbInterval);
      persistSession(getSession());
    };
  }, [
    handleAppStateChange,
    initBattery,
    startGeoTracking,
    startIdleMonitor,
    startSyncFlushInterval,
    startHeartbeat,
  ]);

  // ── PUBLIC API  (identical to web adapter) ────

  return {
    session: sessionRef.current,

    triggerSOS: () => {
      const withSOS = enqueueEvent(getSession(), {
        type: "sos",
        payload: {
          location: getSession().geoHistory.at(-1) ?? null,
          ts: Date.now(),
          risk: getSession().riskLevel,
        },
      });
      setSession(withSOS);
      flushQueue();
    },

    forceSync: flushQueue,
  };
}

// ─────────────────────────────────────────────
// STORAGE HELPERS (AsyncStorage — stub)
// ─────────────────────────────────────────────

function persistSession(session: JourneySession): void {
  // AsyncStorage.setItem(SESSION_STORAGE_KEY, serialiseSession(session));
  console.log("[Journey/RN] 💾 Persist stub — wire up AsyncStorage");
}

// async function loadOrCreateSession(): Promise<JourneySession> {
//   const raw = await AsyncStorage.getItem(SESSION_STORAGE_KEY);
//   if (raw) {
//     const prev = deserialiseSession(raw);
//     if (prev) return handleForeground(prev);
//   }
//   return createSession();
// }
