/**
 * NISCHINT — Journey Engine v3 (Core)
 * Real-Time Personal Safety Intelligence Engine.
 * Predictive risk scoring, SOS state machine, adaptive geo, sync queue.
 * Zero platform imports — pure JS.
 */

// ── CONSTANTS ──

export const IDLE_THRESHOLD_MS     = 5 * 60 * 1000;
export const CRITICAL_IDLE_MS      = 15 * 60 * 1000;
export const MAX_GEO_HISTORY       = 50;
export const LOW_BATTERY_THRESHOLD = 0.15;
export const MAX_SYNC_ATTEMPTS     = 5;
export const SYNC_BATCH_SIZE       = 10;

export const GEO_MOVING_INTERVAL   = 15000;
export const GEO_IDLE_INTERVAL     = 60000;
export const GEO_LOW_BAT_INTERVAL  = 90000;
export const MOVEMENT_THRESHOLD_M  = 20;

// Risk thresholds
export const RISK_SAFE     = 30;
export const RISK_CAUTION  = 60;
export const RISK_HIGH     = 80;

// SOS States
export const SOS_STATES = {
  IDLE: "idle",
  TRIGGERED: "triggered",
  DELIVERED: "delivered",
  ACKNOWLEDGED: "acknowledged",
  ACTIONED: "actioned",
  RESOLVED: "resolved",
  FAILED: "failed",
};

// ── SESSION FACTORY ──

export function createSession() {
  return {
    sessionId: `session_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    startedAt: Date.now(),
    lastActiveAt: Date.now(),
    visibility: "active",
    network: "online",
    batteryLevel: null,
    geoHistory: [],
    pendingSyncEvents: [],
    riskLevel: "safe",
    riskScore: 0,
    idleSinceMs: null,
    isMoving: false,
    lastSpeed: 0,
    geoAnomalies: [],
    // SOS state machine
    sosState: SOS_STATES.IDLE,
    sosId: null,
    sosTriggeredAt: null,
    sosHistory: [],
  };
}

// ── VISIBILITY ──

export function handleForeground(session) {
  return { ...session, visibility: "active", lastActiveAt: Date.now(), idleSinceMs: null };
}

export function handleBackground(session) {
  return { ...session, visibility: "background", idleSinceMs: session.idleSinceMs ?? Date.now() };
}

// ── NETWORK ──

export function handleOnline(session) { return { ...session, network: "online" }; }
export function handleOffline(session) { return { ...session, network: "offline" }; }

// ── GEO (adaptive + anomaly detection) ──

function _haversineMeters(a, b) {
  const R = 6371000;
  const dLat = (b.lat - a.lat) * Math.PI / 180;
  const dLng = (b.lng - a.lng) * Math.PI / 180;
  const sa = Math.sin(dLat / 2) ** 2 +
    Math.cos(a.lat * Math.PI / 180) * Math.cos(b.lat * Math.PI / 180) *
    Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(sa), Math.sqrt(1 - sa));
}

export function appendGeoPoint(session, point) {
  const history = [...session.geoHistory, point].slice(-MAX_GEO_HISTORY);
  const prev = session.geoHistory.at?.(-1);

  let isMoving = session.isMoving;
  let lastSpeed = session.lastSpeed;
  const anomalies = [...session.geoAnomalies];

  if (prev) {
    const dist = _haversineMeters(prev, point);
    const dt = (point.timestamp - prev.timestamp) / 1000;
    lastSpeed = dt > 0 ? dist / dt : 0;
    isMoving = dist > MOVEMENT_THRESHOLD_M;

    if (session.isMoving && !isMoving && session.lastSpeed > 2) {
      anomalies.push({ type: "sudden_stop", ts: point.timestamp, lat: point.lat, lng: point.lng, prevSpeed: session.lastSpeed });
    }
    if (dist > 500 && dt < 60) {
      anomalies.push({ type: "route_deviation", ts: point.timestamp, distance: Math.round(dist), dt: Math.round(dt) });
    }
    // Keep last 20 anomalies
    while (anomalies.length > 20) anomalies.shift();
  }

  return { ...session, geoHistory: history, isMoving, lastSpeed, geoAnomalies: anomalies };
}

export function getAdaptiveGeoInterval(session) {
  if (isLowBattery(session)) return GEO_LOW_BAT_INTERVAL;
  if (session.isMoving) return GEO_MOVING_INTERVAL;
  return GEO_IDLE_INTERVAL;
}

// ── BATTERY ──

export function updateBattery(session, level) { return { ...session, batteryLevel: level }; }
export function isLowBattery(session) { return session.batteryLevel !== null && session.batteryLevel <= LOW_BATTERY_THRESHOLD; }

// ═══════════════════════════════════════════════
// PREDICTIVE RISK SCORING ENGINE (v1 — deterministic + weighted)
// ═══════════════════════════════════════════════

function _isLateNight() {
  const h = new Date().getHours();
  return h >= 22 || h <= 5;
}

function _recentAnomalyCount(session, windowMs = 10 * 60 * 1000) {
  const cutoff = Date.now() - windowMs;
  return session.geoAnomalies.filter(a => a.ts > cutoff).length;
}

export function computeRiskScore(session) {
  let score = 0;

  // 1. Idle time
  if (session.visibility === "background" && session.idleSinceMs) {
    const idle = Date.now() - session.idleSinceMs;
    if (idle > CRITICAL_IDLE_MS) score += 40;
    else if (idle > IDLE_THRESHOLD_MS) score += 20;
    else if (idle > IDLE_THRESHOLD_MS * 0.5) score += 10;
  }

  // 2. Movement anomalies (last 10 minutes)
  const anomalyCount = _recentAnomalyCount(session);
  score += Math.min(anomalyCount * 15, 30);

  // 3. Speed drop (was moving fast, now stopped)
  if (!session.isMoving && session.lastSpeed > 5) {
    score += 25;
  }

  // 4. Time of day
  if (_isLateNight()) score += 15;

  // 5. Battery
  if (session.batteryLevel !== null) {
    if (session.batteryLevel <= 0.05) score += 15;
    else if (session.batteryLevel <= 0.10) score += 10;
    else if (session.batteryLevel <= 0.15) score += 5;
  }

  // 6. Network
  if (session.network === "offline") score += 15;

  // 7. Active SOS amplifier
  if (session.sosState !== SOS_STATES.IDLE && session.sosState !== SOS_STATES.RESOLVED) {
    score += 20;
  }

  // Cap at 100
  score = Math.min(score, 100);

  // Determine level
  let riskLevel;
  if (score >= RISK_HIGH) riskLevel = "critical";
  else if (score >= RISK_CAUTION) riskLevel = "high";
  else if (score >= RISK_SAFE) riskLevel = "caution";
  else riskLevel = "safe";

  return { ...session, riskScore: score, riskLevel };
}

// Risk action recommendations (consumed by the adapter/UI)
export function getRiskActions(session) {
  const actions = [];
  if (session.riskLevel === "caution") {
    actions.push({ type: "ui_alert", message: "NISCHINT is monitoring your safety" });
  }
  if (session.riskLevel === "high") {
    actions.push({ type: "push_notification", message: "Are you safe? Tap to confirm." });
    actions.push({ type: "guardian_ping", message: "Pre-alert: User may need help" });
  }
  if (session.riskLevel === "critical") {
    actions.push({ type: "auto_pre_sos", message: "Initiating safety check..." });
    actions.push({ type: "guardian_alert", message: "URGENT: User safety at risk" });
    actions.push({ type: "sms_fallback", message: "SMS SOS queued" });
  }
  return actions;
}

// ═══════════════════════════════════════════════
// SOS STATE MACHINE
// ═══════════════════════════════════════════════

export function triggerSOS(session) {
  const sosId = `sos_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
  return {
    ...session,
    sosState: SOS_STATES.TRIGGERED,
    sosId,
    sosTriggeredAt: Date.now(),
  };
}

export function updateSOSState(session, newState, meta = {}) {
  const entry = {
    sosId: session.sosId,
    from: session.sosState,
    to: newState,
    ts: Date.now(),
    ...meta,
  };
  const history = [...session.sosHistory, entry].slice(-20);
  return { ...session, sosState: newState, sosHistory: history };
}

export function createSOSPayload(session) {
  return {
    sosId: session.sosId,
    sosState: session.sosState,
    location: session.geoHistory.at?.(-1) || null,
    geoTrail: session.geoHistory.slice(-5),
    ts: Date.now(),
    riskScore: session.riskScore,
    riskLevel: session.riskLevel,
    battery: session.batteryLevel,
    isMoving: session.isMoving,
    network: session.network,
    sessionId: session.sessionId,
    anomalies: session.geoAnomalies.slice(-3),
    idleSinceMs: session.idleSinceMs,
  };
}

// ── SYNC EVENT QUEUE ──

export function enqueueEvent(session, event) {
  const newEvent = {
    ...event,
    id: event.id || `evt_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
    createdAt: Date.now(),
    attempts: 0,
    priority: event.priority || "normal",
    requiresAck: event.requiresAck || false,
    lastAttemptAt: null,
  };
  return { ...session, pendingSyncEvents: [...session.pendingSyncEvents, newEvent] };
}

export function flushEvents(session) {
  if (session.network === "offline") return { toSend: [], session };

  const eligible = session.pendingSyncEvents
    .filter(e => e.attempts < MAX_SYNC_ATTEMPTS)
    .sort((a, b) => {
      if (a.priority === "high" && b.priority !== "high") return -1;
      if (b.priority === "high" && a.priority !== "high") return 1;
      return a.createdAt - b.createdAt;
    });

  const toSend = eligible.slice(0, SYNC_BATCH_SIZE);
  const remaining = session.pendingSyncEvents.filter(e => !toSend.some(s => s.id === e.id));
  const bumped = toSend.map(e => ({ ...e, attempts: e.attempts + 1, lastAttemptAt: Date.now() }));

  return { toSend: bumped, session: { ...session, pendingSyncEvents: remaining } };
}

// ── SERIALISE ──

export function serialiseSession(s) { return JSON.stringify(s); }
export function deserialiseSession(r) { try { return JSON.parse(r); } catch { return null; } }
