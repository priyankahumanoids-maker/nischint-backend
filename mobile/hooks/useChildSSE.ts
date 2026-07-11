// Singleton SSE connection for child real-time events
// Multiple hook consumers share ONE EventSource connection via ref-counting.
import { useEffect, useRef, useState } from 'react';
import { AppState, AppStateStatus } from 'react-native';
import EventSource from 'react-native-sse';
import { API_BASE } from '@/services/api';
import { useAuthStore } from '@/stores/authStore';

var MIN_RETRY_MS = 2000;
var MAX_RETRY_MS = 60000;
var STALE_THRESHOLD_MS = 60000; // FIX 1: 60s stale threshold
// Backoff schedule per audit spec: 1s, 2s, 5s, 10s, 30s, 60s + ±25% jitter.
var BACKOFF_LADDER_MS = [1000, 2000, 5000, 10000, 30000, 60000];

var CHILD_EVENT_TYPES = [
  'checkin_pending',
  'checkin_safe',
  'checkin_help',
  'checkin_expired',
  'safety_alert',
  'location_update',
  'emergency_triggered',
  'emergency_cancelled',
  'emergency_resolved',
  'geofence_status',
  // NISCH-008 streaming events — child receives stream_offer for
  // their own SOS/distress incidents; stream_state lets the banner
  // know when the offer is no longer actionable.
  'stream_offer',
  'stream_state',
];

type SSECallback = (eventType: string, payload: any) => void;

// ── Module-level singleton state ──
var _es: any = null;
var _callbacks: Set<SSECallback> = new Set();
var _subscriberCount = 0;
var _connected = false;
var _lastEventTime = 0;       // FIX 1: heartbeat tracker
var _lastConnectTime = 0;     // FIX 3: prevent rapid reconnects
var _retryTimeout: ReturnType<typeof setTimeout> | null = null;
var _retryAttempt = 0;
var _closed = false;
var _currentToken: string | null = null;
var _appStateSub: any = null;
var _statusLogInterval: ReturnType<typeof setInterval> | null = null;
var _bgDisconnectTimer: ReturnType<typeof setTimeout> | null = null;
var BG_DISCONNECT_DELAY_MS = 10000; // delay SSE disconnect on background by 10s

// FIX 1: Stale check
function _isStale(): boolean {
  if (_lastEventTime === 0) return true;
  return Date.now() - _lastEventTime > STALE_THRESHOLD_MS;
}

function _disconnect() {
  if (_retryTimeout) { clearTimeout(_retryTimeout); _retryTimeout = null; }
  if (_es) { try { _es.close(); } catch (e) {} _es = null; }
  _connected = false;
}

function _connect(token: string) {
  if (_closed || !token) return;
  _disconnect();
  _currentToken = token;
  _lastConnectTime = Date.now(); // FIX 3: track connect time

  var url = API_BASE + '/api/stream?token=' + encodeURIComponent(token);
  console.log('[CHILD_SSE] Connecting... (subscribers: ' + _subscriberCount + ')');

  var es = new EventSource(url);
  _es = es;

  (es as any).addEventListener('open', function() {
    var wasReconnect = _retryAttempt > 0;
    console.log(wasReconnect ? '[SSE_RECOVERED] child (after ' + _retryAttempt + ' attempts)' : '[SSE_CONNECTED] child');
    _connected = true;
    _lastEventTime = Date.now(); // FIX 2: connect = not stale
    _retryAttempt = 0;
    _logStatus();
  });

  // Server sends "connected" event with channel info
  (es as any).addEventListener('connected', function() {
    _lastEventTime = Date.now(); // FIX 2
  });

  // Server pings to keep connection alive
  (es as any).addEventListener('ping', function() {
    _lastEventTime = Date.now(); // FIX 1: heartbeat
  });

  CHILD_EVENT_TYPES.forEach(function(type) {
    (es as any).addEventListener(type, function(event: any) {
      try {
        var parsed = JSON.parse(event.data);
        var inner = parsed.data || parsed;
        console.log('[CHILD_SSE_EVENT] type=' + type, JSON.stringify(inner).substring(0, 120));
        _lastEventTime = Date.now(); // FIX 1: heartbeat on every event
        // Fan out to all registered callbacks
        _callbacks.forEach(function(cb) { cb(type, parsed); });
      } catch (e) {
        console.warn('[CHILD_SSE] Parse error for ' + type + ':', e);
      }
    });
  });

  (es as any).addEventListener('error', function(event: any) {
    console.warn('[SSE_DISCONNECTED] child error=' + (event && event.message ? event.message : 'connection lost'));
    _connected = false;
    if (_es) { try { _es.close(); } catch (e) {} _es = null; }
    if (!_closed && _subscriberCount > 0) {
      // Single timer guard — never two backoffs in flight.
      if (_retryTimeout) { clearTimeout(_retryTimeout); _retryTimeout = null; }
      var idx = Math.min(_retryAttempt, BACKOFF_LADDER_MS.length - 1);
      var base = BACKOFF_LADDER_MS[idx];
      var jitter = 0.75 + Math.random() * 0.5;
      var delay = Math.round(base * jitter);
      console.log('[SSE_BACKOFF] child attempt=' + _retryAttempt + ' base=' + base + 'ms jitter=' + jitter.toFixed(2) + ' delay=' + delay + 'ms');
      _retryAttempt += 1;
      _retryTimeout = setTimeout(function() {
        _retryTimeout = null;
        if (_currentToken && !_closed && _subscriberCount > 0) {
          console.log('[SSE_RECONNECTING] child (attempt ' + _retryAttempt + ')');
          _connect(_currentToken);
        }
      }, delay);
    }
  });
}

// FIX 5: Status log
function _logStatus() {
  var ago = _lastEventTime > 0 ? Date.now() - _lastEventTime : -1;
  console.log('[SSE_STATUS] connected=' + _connected + ' lastEventAgo=' + ago + 'ms stale=' + _isStale() + ' subscribers=' + _subscriberCount);
}

function _setupAppState(token: string) {
  if (_appStateSub) return;
  console.log('[APPSTATE_LISTENER] child registered');
  _appStateSub = AppState.addEventListener('change', function(next: AppStateStatus) {
    if (next === 'active' && !_closed && _subscriberCount > 0) {
      // Cancel any pending background disconnect
      if (_bgDisconnectTimer) {
        clearTimeout(_bgDisconnectTimer);
        _bgDisconnectTimer = null;
        console.log('[CHILD_SSE] App foregrounded — cancelled pending disconnect');
        // If connection exists (active or in progress), do NOT reconnect
        if (_es) return;
      }
      // Skip reconnect if already connected and not stale
      if (_connected && !_isStale()) {
        return;
      }
      // Skip if connection is in progress
      if (_es) {
        return;
      }
      var sinceLast = Date.now() - _lastConnectTime;
      console.log('[CHILD_SSE] App foregrounded -> reconnecting (last connect ' + sinceLast + 'ms ago)');
      _retryAttempt = 0;
      if (_retryTimeout) { clearTimeout(_retryTimeout); _retryTimeout = null; }
      _connect(token);
    } else if (next === 'background' || next === 'inactive') {
      // Delay disconnect by 10s — keeps SSE alive during distress events
      if (_bgDisconnectTimer) clearTimeout(_bgDisconnectTimer);
      _bgDisconnectTimer = setTimeout(function() {
        _bgDisconnectTimer = null;
        console.log('[CHILD_SSE] Background disconnect timer fired -> disconnecting');
        _disconnect();
      }, BG_DISCONNECT_DELAY_MS);
    }
  });
}

function _subscribe(cb: SSECallback, token: string) {
  _callbacks.add(cb);
  _subscriberCount++;
  _closed = false;

  if (_subscriberCount === 1 && !_es) {
    console.log('[SSE_SINGLETON] child first subscriber — opening connection');
    _connect(token);
    _setupAppState(token);
    // FIX 5: Periodic status log every 30s
    if (!_statusLogInterval) {
      _statusLogInterval = setInterval(_logStatus, 30000);
    }
  } else {
    console.log('[SSE_SINGLETON] child subscriber count=' + _subscriberCount + ' (reusing)');
  }
}

function _unsubscribe(cb: SSECallback) {
  _callbacks.delete(cb);
  _subscriberCount = Math.max(0, _subscriberCount - 1);

  if (_subscriberCount === 0) {
    _closed = true;
    _disconnect();
    if (_bgDisconnectTimer) { clearTimeout(_bgDisconnectTimer); _bgDisconnectTimer = null; }
    if (_appStateSub) { _appStateSub.remove(); _appStateSub = null; }
    if (_statusLogInterval) { clearInterval(_statusLogInterval); _statusLogInterval = null; }
  }
}

// ── Public getters for polling logic ──
export function isSSEAlive(): boolean {
  // FIX 4: SSE is alive only if connected AND not stale
  return _connected && !_isStale();
}

// Aliased for the dev-only RealtimeStatusBadge — keeps a stable public
// name parallel to the guardian hook's export.
export function isChildSSEAlive(): boolean {
  return _connected && !_isStale();
}

export function getChildSSELastEvent(): number {
  return _lastEventTime;
}

export function getChildSSESubscriberCount(): number {
  return _subscriberCount;
}

export function getLastEventTime(): number {
  return _lastEventTime;
}

// ── Public hook ──
export function useChildSSE(onEvent: SSECallback): { connected: boolean; lastEventTs: number } {
  var tokenVal = useAuthStore(function(s) { return s.token; });
  var cbRef = useRef(onEvent);
  cbRef.current = onEvent;

  var stableCb = useRef(function(type: string, payload: any) {
    cbRef.current(type, payload);
  }).current;

  var [connected, setConnected] = useState(_connected);
  var [lastEventTs, setLastEventTs] = useState(_lastEventTime);

  useEffect(function() {
    if (!tokenVal) return;

    _subscribe(stableCb, tokenVal);

    // Sync module state to React state every 5s
    var poll = setInterval(function() {
      setConnected(_connected);
      setLastEventTs(_lastEventTime);
    }, 5000);

    return function() {
      clearInterval(poll);
      _unsubscribe(stableCb);
    };
  }, [tokenVal, stableCb]);

  return { connected, lastEventTs };
}
