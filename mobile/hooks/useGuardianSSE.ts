// useGuardianSSE — module-level SINGLETON SSE connection for guardian dashboard.
//
// All consumers share ONE EventSource via ref-counting. Mirrors the
// useChildSSE singleton (which solved the same problem on the child app).
//
// Production-grade reconnect:
//   * Exponential backoff: 1s, 2s, 5s, 10s, 30s, 60s (capped)
//   * ±25% jitter to avoid synchronized reconnect storms
//   * Reset to MIN on successful 'open'
//   * Single timer ref — never multiple in flight
//   * Cancel timer on unsubscribe / app close
//   * Foreground triggers immediate reconnect (resets backoff)
//
// Polling coordination:
//   `isGuardianSSEAlive()` is the single source of truth for
//   "should polling be running?" — exported for `useGuardianLocationPolling`.
//
// Logs follow the keys the audit requested:
//   [SSE_SINGLETON] [APPSTATE_LISTENER] [SSE_RETRY] [SSE_BACKOFF]
//   [SSE_RECONNECTING] [SSE_RECOVERED] [SSE_CONNECTED] [SSE_STALE]
//   [SSE_DISCONNECTED]
import { useEffect, useRef, useState } from 'react';
import { AppState, AppStateStatus } from 'react-native';
import EventSource from 'react-native-sse';
import { API_BASE } from '@/services/api';
import { useAuthStore } from '@/stores/authStore';

// Backoff schedule per spec: 1s → 2s → 5s → 10s → 30s → 60s (capped).
// Index past the last entry stays at 60s. ±25% jitter applied per attempt.
const BACKOFF_LADDER_MS = [1_000, 2_000, 5_000, 10_000, 30_000, 60_000];
const BG_DISCONNECT_DELAY_MS = 10_000;
const STALE_THRESHOLD_MS = 60_000;

const EVENT_TYPES = [
  'checkin_help',
  'checkin_safe',
  'checkin_pending',
  'checkin_expired',
  'location_update',
  'emergency_triggered',
  'emergency_cancelled',
  'emergency_resolved',
  'incident_created',
  'incident_updated',
  'child_linked',
  'safety_alert',
  'risk_update',
  'escalation_update',
  'geofence_breach',
  'geofence_recovery',
  'geofence_status',
  // NISCH-008 streaming events
  'stream_offer',
  'stream_available',
  'stream_state',
];

type SSECallback = (eventType: string, payload: any) => void;

// ── Module-level singleton state ───────────────────────────────────
let _es: any = null;
const _callbacks: Set<SSECallback> = new Set();
let _subscriberCount = 0;
let _connected = false;
let _lastEventTime = 0;
let _retryTimer: ReturnType<typeof setTimeout> | null = null;
let _retryAttempt = 0;
let _closed = false;
let _currentToken: string | null = null;
let _appStateSub: any = null;
let _bgDisconnectTimer: ReturnType<typeof setTimeout> | null = null;
const _seenIds: Set<string> = new Set();

function _isStale(): boolean {
  if (_lastEventTime === 0) return true;
  return Date.now() - _lastEventTime > STALE_THRESHOLD_MS;
}

/**
 * Public health check for polling fallback. Polling MUST run only when
 * this returns false.
 */
export function isGuardianSSEAlive(): boolean {
  return _connected && !_isStale();
}

export function getGuardianSSELastEvent(): number {
  return _lastEventTime;
}

export function getGuardianSSESubscriberCount(): number {
  return _subscriberCount;
}

export function getGuardianSSERetryAttempt(): number {
  return _retryAttempt;
}

function _scheduleNextBackoff() {
  // Single source of truth: clear any in-flight timer first so we never
  // leak a second one (the bug being fixed).
  if (_retryTimer) {
    clearTimeout(_retryTimer);
    _retryTimer = null;
  }
  if (_closed || _subscriberCount === 0) return;

  const idx = Math.min(_retryAttempt, BACKOFF_LADDER_MS.length - 1);
  const base = BACKOFF_LADDER_MS[idx];
  // ±25% jitter — uniform random in [0.75, 1.25].
  const jitter = 0.75 + Math.random() * 0.5;
  const delay = Math.round(base * jitter);

  console.log(
    `[SSE_BACKOFF] guardian attempt=${_retryAttempt} base=${base}ms ` +
    `jitter=${jitter.toFixed(2)} delay=${delay}ms`
  );
  _retryAttempt += 1;

  _retryTimer = setTimeout(() => {
    _retryTimer = null;
    if (_closed || _subscriberCount === 0 || !_currentToken) return;
    console.log(`[SSE_RECONNECTING] guardian (attempt ${_retryAttempt})`);
    _connect(_currentToken);
  }, delay);
}

function _disconnect(reason: string) {
  if (_retryTimer) { clearTimeout(_retryTimer); _retryTimer = null; }
  if (_es) {
    try { _es.close(); } catch {}
    _es = null;
  }
  if (_connected) {
    console.log(`[SSE_DISCONNECTED] guardian reason=${reason}`);
  }
  _connected = false;
}

function _connect(token: string) {
  if (_closed || !token) return;
  // Singleton guard — refuse to open a second EventSource. Prevents the
  // duplicate-listener storm we set out to fix.
  if (_es) {
    console.log('[SSE_SINGLETON] guardian connect() skipped — already open');
    return;
  }

  _currentToken = token;
  const url = `${API_BASE}/api/stream?token=${encodeURIComponent(token)}`;
  console.log(`[SSE_RETRY] guardian connecting subscribers=${_subscriberCount}`);

  const es = new EventSource(url);
  _es = es;

  (es as any).addEventListener('open', () => {
    const wasReconnect = _retryAttempt > 0;
    console.log(
      wasReconnect
        ? `[SSE_RECOVERED] guardian (after ${_retryAttempt} attempts)`
        : '[SSE_CONNECTED] guardian'
    );
    _connected = true;
    _lastEventTime = Date.now();
    _retryAttempt = 0;
  });

  (es as any).addEventListener('connected', () => {
    _lastEventTime = Date.now();
  });

  (es as any).addEventListener('ping', () => {
    _lastEventTime = Date.now();
  });

  EVENT_TYPES.forEach((type) => {
    (es as any).addEventListener(type, (event: any) => {
      try {
        const parsed = JSON.parse(event.data);
        const inner = parsed.data || parsed;
        const eventId = parsed.id || inner.event_id || inner.safety_event_id || '';

        if (eventId && _seenIds.has(eventId)) {
          return; // dedup replay
        }
        if (eventId) {
          _seenIds.add(eventId);
          if (_seenIds.size > 200) {
            // Trim — keep most recent ~100.
            const arr = Array.from(_seenIds);
            _seenIds.clear();
            arr.slice(-100).forEach((id) => _seenIds.add(id));
          }
        }

        _lastEventTime = Date.now();
        _callbacks.forEach((cb) => {
          try { cb(type, inner); } catch (e) {
            console.warn('[GUARDIAN_SSE] callback threw:', e);
          }
        });
      } catch (e) {
        console.warn(`[GUARDIAN_SSE] parse error for ${type}:`, e);
      }
    });
  });

  (es as any).addEventListener('error', (event: any) => {
    console.warn(
      `[SSE_DISCONNECTED] guardian error=${event && event.message ? event.message : 'connection lost'}`
    );
    _connected = false;
    if (_es) { try { _es.close(); } catch {} _es = null; }
    _scheduleNextBackoff();
  });
}

function _setupAppState() {
  if (_appStateSub) return; // singleton AppState listener
  console.log('[APPSTATE_LISTENER] guardian registered');
  _appStateSub = AppState.addEventListener('change', (next: AppStateStatus) => {
    if (next === 'active' && !_closed && _subscriberCount > 0) {
      // Cancel any pending background disconnect.
      if (_bgDisconnectTimer) {
        clearTimeout(_bgDisconnectTimer);
        _bgDisconnectTimer = null;
        if (_es) {
          // Connection still alive — nothing to do.
          return;
        }
      }
      // Skip if connection is in progress / alive AND not stale.
      if (_es && _connected && !_isStale()) return;

      // Foreground = immediate reconnect at the bottom of the ladder.
      console.log('[GUARDIAN_SSE] foregrounded — immediate reconnect');
      _retryAttempt = 0;
      if (_retryTimer) { clearTimeout(_retryTimer); _retryTimer = null; }
      if (_currentToken) _connect(_currentToken);
    } else if (next === 'background' || next === 'inactive') {
      if (_bgDisconnectTimer) clearTimeout(_bgDisconnectTimer);
      _bgDisconnectTimer = setTimeout(() => {
        _bgDisconnectTimer = null;
        _disconnect('background_timeout');
      }, BG_DISCONNECT_DELAY_MS);
    }
  });
}

function _subscribe(cb: SSECallback, token: string) {
  _callbacks.add(cb);
  _subscriberCount += 1;
  _closed = false;

  if (_subscriberCount === 1) {
    console.log('[SSE_SINGLETON] guardian first subscriber — opening connection');
    _setupAppState();
    if (!_es) _connect(token);
  } else {
    console.log(`[SSE_SINGLETON] guardian subscriber count=${_subscriberCount} (reusing)`);
  }
}

function _unsubscribe(cb: SSECallback) {
  if (!_callbacks.has(cb)) return;
  _callbacks.delete(cb);
  _subscriberCount = Math.max(0, _subscriberCount - 1);

  if (_subscriberCount === 0) {
    console.log('[SSE_SINGLETON] guardian last subscriber gone — closing');
    _closed = true;
    _disconnect('no_subscribers');
    if (_bgDisconnectTimer) {
      clearTimeout(_bgDisconnectTimer);
      _bgDisconnectTimer = null;
    }
    if (_appStateSub) {
      _appStateSub.remove();
      _appStateSub = null;
    }
    _retryAttempt = 0;
  }
}

// ── Public hook ────────────────────────────────────────────────────
export function useGuardianSSE(onEvent: SSECallback): boolean {
  const tokenVal = useAuthStore((s) => s.token);
  const cbRef = useRef(onEvent);
  cbRef.current = onEvent;

  // Stable wrapper — registering the same function reference every
  // render means Set.delete() works on cleanup.
  const stableCb = useRef((type: string, payload: any) => {
    cbRef.current(type, payload);
  }).current;

  const [connected, setConnected] = useState(_connected);

  useEffect(() => {
    if (!tokenVal) return;
    _subscribe(stableCb, tokenVal);

    // Sync local state with module state. Light interval — 5s.
    // (One per consumer is fine; the heavy work is one-shot in the singleton.)
    const poll = setInterval(() => {
      setConnected(_connected && !_isStale());
    }, 5000);

    return () => {
      clearInterval(poll);
      _unsubscribe(stableCb);
    };
  }, [tokenVal, stableCb]);

  return connected;
}
