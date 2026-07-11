// Phase 5 + Hardening — Command Center Delta Patch Utility
//
// Standard envelope shape (matches backend `cc_delta_emitter.py`):
//   {
//     type: 'COMMAND_CENTER_DELTA',
//     user_id, timestamp, version: 'v1',
//     changes: { 'risk.final_score': 7.5, 'live_deviation.status': 'high' }
//   }
//
// Hardening: per-namespace timestamp tracking so updates to different
// namespaces (risk / live_deviation / live_location / environment /
// active_event) cannot reject each other.
//
// Returns { state, applied, reason } so callers can log telemetry.

export const DELTA_VERSION = 'v1';
const TS_FIELD = '__deltaTs';   // hidden per-namespace timestamps under root

function setDotted(obj, path, value) {
  const parts = path.split('.');
  if (parts.length === 0) return obj;
  const next = { ...(obj || {}) };
  let cursor = next;
  for (let i = 0; i < parts.length - 1; i++) {
    const key = parts[i];
    cursor[key] = { ...(cursor[key] || {}) };
    cursor = cursor[key];
  }
  cursor[parts[parts.length - 1]] = value;
  return next;
}

/**
 * Apply a COMMAND_CENTER_DELTA envelope to `state` for a given namespace.
 *
 * Per-namespace stale-timestamp rejection: if `state.__deltaTs[namespace]`
 * is newer than the incoming envelope timestamp, reject. Otherwise apply
 * and update the namespace timestamp.
 *
 * @param {Object} state         — previous slice (e.g. userRiskData)
 * @param {Object} envelope      — { version, timestamp, user_id, changes }
 * @param {string} namespace     — e.g. 'risk' | 'live_deviation'
 * @returns {{state, applied, reason}}
 */
export function applyDelta(state, envelope, namespace = '__root') {
  if (!envelope || typeof envelope !== 'object') {
    return { state, applied: false, reason: 'no_envelope' };
  }
  const { version, timestamp, changes, user_id: deltaUserId } = envelope;
  if (version !== DELTA_VERSION) {
    return { state, applied: false, reason: `version_mismatch:${version}` };
  }
  if (!changes || typeof changes !== 'object' || Object.keys(changes).length === 0) {
    return { state, applied: false, reason: 'no_changes' };
  }

  const tsMap = (state && state[TS_FIELD]) || {};
  const lastTs = tsMap[namespace];
  if (lastTs && timestamp && new Date(timestamp).getTime() <= new Date(lastTs).getTime()) {
    return { state, applied: false, reason: 'stale_timestamp' };
  }

  let next = { ...(state || {}) };
  for (const path of Object.keys(changes)) {
    next = setDotted(next, path, changes[path]);
  }
  next[TS_FIELD] = { ...tsMap, [namespace]: timestamp };
  next.lastDeltaUserId = deltaUserId;

  return { state: next, applied: true, reason: 'applied' };
}

// Lightweight in-memory metrics (visible to the WS Frame Inspector)
export const deltaMetrics = {
  applied: 0,
  rejected: 0,
  staleRejected: 0,
  versionMismatch: 0,
  reconnects: 0,
  framesReceived: 0,
  recordReceived() { this.framesReceived += 1; },
  recordApply(reason) {
    if (reason === 'applied') this.applied += 1;
    else this.rejected += 1;
    if (reason === 'stale_timestamp') this.staleRejected += 1;
    else if (typeof reason === 'string' && reason.startsWith('version_mismatch')) this.versionMismatch += 1;
  },
  recordReconnect() { this.reconnects += 1; },
  snapshot() {
    const total = this.applied + this.rejected;
    return {
      applied: this.applied,
      rejected: this.rejected,
      staleRejected: this.staleRejected,
      versionMismatch: this.versionMismatch,
      reconnects: this.reconnects,
      framesReceived: this.framesReceived,
      successRate: total > 0
        ? Math.round((this.applied / total) * 100) : null,
    };
  },
};

// Frame ring buffer for the Frame Inspector (dev mode)
const FRAME_BUFFER_LIMIT = 20;
const _frameSubscribers = new Set();
const _frameRing = [];

export function recordFrame(envelope) {
  deltaMetrics.recordReceived();
  const entry = {
    id: Math.random().toString(36).slice(2, 9),
    ts: envelope?.timestamp || new Date().toISOString(),
    user_id: envelope?.user_id || null,
    paths: Object.keys(envelope?.changes || {}),
    version: envelope?.version || null,
    received_at: Date.now(),
  };
  _frameRing.unshift(entry);
  if (_frameRing.length > FRAME_BUFFER_LIMIT) _frameRing.length = FRAME_BUFFER_LIMIT;
  _frameSubscribers.forEach((cb) => {
    try { cb(_frameRing.slice()); } catch (_) { /* ignore subscriber errors */ }
  });
}

export function subscribeFrames(cb) {
  _frameSubscribers.add(cb);
  cb(_frameRing.slice());
  return () => _frameSubscribers.delete(cb);
}
