/**
 * NISCHINT — Journey Lifecycle Hook v3 (Web)
 * Real-Time Personal Safety Intelligence Engine.
 * SOS state machine, predictive risk scoring, multi-channel fallback, adaptive geo.
 */

import { useEffect, useRef, useCallback } from "react";
import {
  createSession, handleForeground, handleBackground,
  handleOnline, handleOffline,
  appendGeoPoint, updateBattery, getAdaptiveGeoInterval,
  computeRiskScore, getRiskActions,
  triggerSOS as engineTriggerSOS, updateSOSState, createSOSPayload,
  enqueueEvent, flushEvents,
  serialiseSession, deserialiseSession,
  isLowBattery, IDLE_THRESHOLD_MS, SYNC_BATCH_SIZE,
  SOS_STATES,
} from "./JourneyEngine";
import {
  saveEvent, getPendingEvents, markEventsSynced, markEventFailed,
  pruneOldEvents, saveSession as idbSaveSession,
} from "./EventStore";

// ── CONSTANTS ──

const SESSION_LS_KEY       = "nischint_journey_session";
const RISK_EVAL_INTERVAL   = 15000;   // evaluate risk every 15s
const SYNC_FLUSH_INTERVAL  = 15000;
const BASE_BACKOFF_MS      = 2000;
const MAX_BACKOFF_MS       = 60000;
const SOS_POLL_INTERVAL    = 5000;    // poll SOS state every 5s during active SOS

// ── STORAGE ──

function persistSession(session) {
  try { localStorage.setItem(SESSION_LS_KEY, serialiseSession(session)); } catch {}
  idbSaveSession(session).catch(() => {});
}

function loadOrCreateSession() {
  try {
    const raw = localStorage.getItem(SESSION_LS_KEY);
    if (raw) {
      const prev = deserialiseSession(raw);
      if (prev) return handleForeground({ ...prev });
    }
  } catch {}
  return createSession();
}

// ── HOOK ──

export function useJourneyLifecycle(callbacks = {}) {
  const {
    isActive = false,  // Gate live tracking — caller MUST opt in. Marketing
                       // and public landing pages pass `false` (or omit),
                       // ensuring `navigator.geolocation.getCurrentPosition`
                       // is NEVER called before the user authenticates and
                       // explicitly starts a journey. App Store-rejection
                       // risk: requesting geolocation without a user action.
    ...rest
  } = callbacks;
  callbacks = rest;
  const sessionRef = useRef(loadOrCreateSession());
  const callbacksRef = useRef(callbacks);
  callbacksRef.current = callbacks;
  const geoIntervalRef = useRef(null);
  const geoIntervalMsRef = useRef(0);
  const sosPollRef = useRef(null);
  const syncFailCount = useRef(0);

  const getSession = () => sessionRef.current;
  const setSession = useCallback((next) => {
    sessionRef.current = next;
    persistSession(next);
  }, []);

  // ── VISIBILITY ──

  const handleVisibilityChange = useCallback(() => {
    if (document.visibilityState === "hidden") {
      setSession(handleBackground(getSession()));
      callbacksRef.current.onBackground?.(getSession());
    } else {
      setSession(handleForeground(getSession()));
      callbacksRef.current.onForeground?.(getSession());
      syncNow();
    }
  }, [setSession]);

  // ── NETWORK ──

  const handleNetworkOnline = useCallback(() => {
    setSession(handleOnline(getSession()));
    callbacksRef.current.onOnline?.(getSession());
    syncFailCount.current = 0;
    syncNow();
  }, [setSession]);

  const handleNetworkOffline = useCallback(() => {
    setSession(handleOffline(getSession()));
    callbacksRef.current.onOffline?.(getSession());
  }, [setSession]);

  // ── ADAPTIVE GEO ──

  const captureGeo = useCallback(() => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const point = { lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: pos.coords.accuracy, speed: pos.coords.speed, timestamp: Date.now() };
        const updated = appendGeoPoint(getSession(), point);
        const withEvt = enqueueEvent(updated, { type: "geo", payload: point });
        setSession(withEvt);
        saveEvent({ id: `geo_${Date.now()}`, type: "geo", payload: point, createdAt: Date.now(), attempts: 0, priority: "normal" }).catch(() => {});
        callbacksRef.current.onGeoUpdate?.(point);

        // Check anomalies
        const latest = withEvt.geoAnomalies.at?.(-1);
        if (latest && latest.ts === point.timestamp) {
          callbacksRef.current.onGeoAnomaly?.(latest);
        }

        // Adjust geo interval
        const newMs = getAdaptiveGeoInterval(withEvt);
        if (geoIntervalRef.current && geoIntervalMsRef.current !== newMs) {
          clearInterval(geoIntervalRef.current);
          const id = setInterval(captureGeo, newMs);
          geoIntervalMsRef.current = newMs;
          geoIntervalRef.current = id;
        }
      },
      () => {},
      { enableHighAccuracy: true, timeout: 10000 }
    );
  }, [setSession]);

  const startGeoTracking = useCallback(() => {
    if (!navigator.geolocation) return undefined;
    captureGeo();
    const ms = getAdaptiveGeoInterval(getSession());
    const id = setInterval(captureGeo, ms);
    geoIntervalMsRef.current = ms;
    geoIntervalRef.current = id;
    return id;
  }, [captureGeo]);

  // ── BATTERY ──

  const initBattery = useCallback(async () => {
    if (!("getBattery" in navigator)) return;
    try {
      const bat = await navigator.getBattery();
      const onChange = () => {
        setSession(updateBattery(getSession(), bat.level));
        if (bat.level <= 0.15) callbacksRef.current.onLowBattery?.(bat.level);
      };
      bat.addEventListener("levelchange", onChange);
      onChange();
    } catch {}
  }, [setSession]);

  // ── PREDICTIVE RISK ENGINE ──

  const startRiskEngine = useCallback(() => {
    return setInterval(() => {
      const evaluated = computeRiskScore(getSession());
      setSession(evaluated);

      const actions = getRiskActions(evaluated);
      if (actions.length > 0) {
        callbacksRef.current.onRiskActions?.(actions, evaluated);
      }

      // Auto pre-SOS for critical risk if SOS not already active
      if (evaluated.riskLevel === "critical" && evaluated.sosState === SOS_STATES.IDLE) {
        callbacksRef.current.onAutoPreSOS?.(evaluated);
      }
    }, RISK_EVAL_INTERVAL);
  }, [setSession]);

  // ── SYNC ENGINE v2 ──

  const syncNow = useCallback(async () => {
    const session = getSession();
    if (session.network === "offline") return;

    const { toSend: memEvents, session: flushed } = flushEvents(session);
    if (memEvents.length > 0) {
      setSession(flushed);
      for (const evt of memEvents) await saveEvent(evt).catch(() => {});
    }

    const pending = await getPendingEvents(SYNC_BATCH_SIZE);
    if (pending.length === 0) return;

    const backoff = Math.min(BASE_BACKOFF_MS * Math.pow(2, syncFailCount.current), MAX_BACKOFF_MS);
    if (syncFailCount.current > 0) await new Promise(r => setTimeout(r, backoff));

    // Same-origin relative path — no CORS, no stale baked-URL risk.
    const url = "";
    try {
      const resp = await fetch(`${url}/api/journey/sync`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ events: pending }),
        keepalive: true,
      });
      if (resp.ok) {
        await markEventsSynced(pending.map(e => e.id));
        syncFailCount.current = 0;
        const data = await resp.json();
        callbacksRef.current.onSyncFlush?.(pending, data);
      } else {
        syncFailCount.current++;
        for (const evt of pending) await markEventFailed(evt.id);
      }
    } catch {
      syncFailCount.current++;
      for (const evt of pending) await markEventFailed(evt.id);
    }

    if (Math.random() < 0.1) pruneOldEvents();
  }, [setSession]);

  // ── SOS STATE MACHINE + MULTI-CHANNEL FALLBACK ──

  const executeSOS = useCallback(async () => {
    // Step 1: Capture fresh geo
    await new Promise((resolve) => {
      if (!navigator.geolocation) { resolve(); return; }
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const pt = { lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: pos.coords.accuracy, timestamp: Date.now() };
          setSession(appendGeoPoint(getSession(), pt));
          resolve();
        },
        () => resolve(),
        { enableHighAccuracy: true, timeout: 5000 }
      );
    });

    // Step 2: Trigger in engine
    let s = engineTriggerSOS(getSession());
    s = computeRiskScore(s);
    setSession(s);
    callbacksRef.current.onSOSStateChange?.(SOS_STATES.TRIGGERED, s);

    const payload = createSOSPayload(s);

    // Step 3: Persist to IDB
    await saveEvent({ id: s.sosId, type: "sos", priority: "high", requiresAck: true, payload, createdAt: Date.now(), attempts: 0, status: "pending" }).catch(() => {});

    // Step 4: Multi-channel delivery (parallel)
    // Same-origin relative path — no CORS, no stale baked-URL risk.
    const url = "";

    // Channel 1: Direct API
    const apiPromise = fetch(`${url}/api/journey/sos`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      keepalive: true,
    }).then(async (resp) => {
      if (resp.ok) {
        const data = await resp.json();
        const delivered = updateSOSState(getSession(), SOS_STATES.DELIVERED, { channel: "api", sosId: data.sos_id });
        setSession(delivered);
        callbacksRef.current.onSOSStateChange?.(SOS_STATES.DELIVERED, delivered);
        return { channel: "api", success: true, data };
      }
      return { channel: "api", success: false };
    }).catch(() => ({ channel: "api", success: false }));

    // Channel 2: SMS fallback via backend
    const smsPromise = fetch(`${url}/api/journey/sos-sms`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sosId: s.sosId, location: payload.location, sessionId: s.sessionId }),
      keepalive: true,
    }).then(async (resp) => {
      if (resp.ok) return { channel: "sms", success: true, data: await resp.json() };
      return { channel: "sms", success: false };
    }).catch(() => ({ channel: "sms", success: false }));

    // Channel 3: Guardian webhook
    const webhookPromise = fetch(`${url}/api/journey/sos-webhook`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      keepalive: true,
    }).then(async (resp) => {
      if (resp.ok) return { channel: "webhook", success: true, data: await resp.json() };
      return { channel: "webhook", success: false };
    }).catch(() => ({ channel: "webhook", success: false }));

    const results = await Promise.allSettled([apiPromise, smsPromise, webhookPromise]);
    const channelResults = results.map(r => r.status === "fulfilled" ? r.value : { channel: "unknown", success: false });
    const anySuccess = channelResults.some(r => r.success);

    if (!anySuccess) {
      const failed = updateSOSState(getSession(), SOS_STATES.FAILED, { channels: channelResults });
      setSession(failed);
      callbacksRef.current.onSOSStateChange?.(SOS_STATES.FAILED, failed);
    }

    callbacksRef.current.onSOSChannelResults?.(channelResults);

    // Step 5: Start polling for SOS state updates
    if (sosPollRef.current) clearInterval(sosPollRef.current);
    sosPollRef.current = setInterval(async () => {
      try {
        const resp = await fetch(`${url}/api/journey/sos/${s.sosId}`);
        if (resp.ok) {
          const data = await resp.json();
          if (data.sos_state && data.sos_state !== getSession().sosState) {
            const updated = updateSOSState(getSession(), data.sos_state, { source: "server_poll" });
            setSession(updated);
            callbacksRef.current.onSOSStateChange?.(data.sos_state, updated);
            if (data.sos_state === SOS_STATES.RESOLVED) {
              clearInterval(sosPollRef.current);
              sosPollRef.current = null;
            }
          }
        }
      } catch {}
    }, SOS_POLL_INTERVAL);

    return channelResults;
  }, [setSession]);

  // ── HEARTBEAT ──

  const startHeartbeat = useCallback(() => {
    return setInterval(() => {
      const s = getSession();
      setSession(enqueueEvent(s, {
        type: "heartbeat",
        payload: { ts: Date.now(), riskScore: s.riskScore, riskLevel: s.riskLevel, moving: s.isMoving, battery: s.batteryLevel, sosState: s.sosState },
      }));
    }, IDLE_THRESHOLD_MS);
  }, [setSession]);

  // ── MOUNT / UNMOUNT ──

  useEffect(() => {
    // Visibility & network listeners are cheap and consent-free — safe
    // to wire even on marketing pages so we capture re-engagement events.
    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("online", handleNetworkOnline);
    window.addEventListener("offline", handleNetworkOffline);

    // Privileged side effects — only when caller has opted in via `isActive`.
    // Marketing landing pages never trip these, so the geolocation prompt
    // does NOT appear before user authentication + explicit journey start.
    let geoId = null;
    let riskId = null;
    let syncId = null;
    let hbId = null;
    if (isActive) {
      initBattery();
      geoId  = startGeoTracking();
      riskId = startRiskEngine();
      syncId = setInterval(syncNow, SYNC_FLUSH_INTERVAL);
      hbId   = startHeartbeat();
      syncNow(); // flush leftover events from previous session
    }

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("online", handleNetworkOnline);
      window.removeEventListener("offline", handleNetworkOffline);
      if (geoId)  clearInterval(geoId);
      if (riskId) clearInterval(riskId);
      if (syncId) clearInterval(syncId);
      if (hbId)   clearInterval(hbId);
      if (sosPollRef.current) clearInterval(sosPollRef.current);
      persistSession(getSession());
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── PUBLIC API ──

  return {
    session: sessionRef.current,
    triggerSOS: executeSOS,
    forceSync: syncNow,
    resolveCurrentSOS: () => {
      if (getSession().sosState !== SOS_STATES.IDLE) {
        const resolved = updateSOSState(getSession(), SOS_STATES.RESOLVED, { source: "user" });
        setSession(resolved);
        if (sosPollRef.current) { clearInterval(sosPollRef.current); sosPollRef.current = null; }
        callbacksRef.current.onSOSStateChange?.(SOS_STATES.RESOLVED, resolved);
      }
    },
  };
}
