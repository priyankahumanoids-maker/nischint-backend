// SSE Service — Journey Engine real-time event stream.
//
// Backend exposes per-SOS streams at:
//   GET /api/journey/sos/{sos_id}/stream  (emits state changes + 30s keepalive)
//
// There is no global "/api/journey/stream" — each active SOS gets its own
// stream. This service manages one active subscription at a time (the
// currently active SOS). It handles:
//   • auto-reconnect with exponential backoff
//   • event dedup via lastEventId
//   • payload parsing → journeyEngineStore updates
//
// NOTE: This service does NOT handle guardian-side alerts — those flow
// through the existing useGuardianSSE.ts.
import EventSource from 'react-native-sse';
import { useJourneyEngineStore, ActiveAlert } from '../stores/journeyEngineStore';

const BASE = process.env.EXPO_PUBLIC_API_URL || 'https://nischint.care';
const MAX_BACKOFF_MS = 60_000;

let _es: EventSource | null = null;
let _activeSosId: string | null = null;
let _authToken: string | null = null;
let _reconnectAttempts = 0;
let _reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let _lastEventId: string | null = null;
const _seenEventIds = new Set<string>();

export function setSseAuthToken(token: string | null): void {
  _authToken = token;
}

export function connectSOSStream(sosId: string, token?: string | null): void {
  if (_activeSosId === sosId && _es) return; // already connected
  disconnectSOSStream();

  _activeSosId = sosId;
  _authToken = token ?? _authToken;
  _reconnectAttempts = 0;
  _openStream();
}

export function disconnectSOSStream(): void {
  if (_reconnectTimer) clearTimeout(_reconnectTimer);
  _reconnectTimer = null;
  if (_es) {
    try { _es.close(); } catch (e) { /* ignore */ }
    _es = null;
  }
  _activeSosId = null;
  _lastEventId = null;
  _seenEventIds.clear();
  useJourneyEngineStore.getState().setConnection('offline');
}

function _openStream(): void {
  if (!_activeSosId) return;
  const url = `${BASE}/api/journey/sos/${_activeSosId}/stream`;

  const headers: Record<string, string> = { Accept: 'text/event-stream' };
  if (_authToken) headers['Authorization'] = `Bearer ${_authToken}`;
  if (_lastEventId) headers['Last-Event-ID'] = _lastEventId;

  console.log('[SSE] opening', url, _lastEventId ? `(resume from ${_lastEventId})` : '');
  useJourneyEngineStore.getState().setConnection('reconnecting');

  try {
    _es = new EventSource(url, { headers, pollingInterval: 0 } as any);
  } catch (e) {
    console.warn('[SSE] construct failed', e);
    _scheduleReconnect();
    return;
  }

  _es.addEventListener('open', () => {
    console.log('[SSE] connected');
    _reconnectAttempts = 0;
    useJourneyEngineStore.getState().setConnection('online');
  });

  _es.addEventListener('message', (e: any) => {
    _handleMessage(e);
  });

  _es.addEventListener('error', (e: any) => {
    console.warn('[SSE] error', e?.message || e?.type);
    _scheduleReconnect();
  });
}

function _handleMessage(e: any): void {
  const data = e?.data;
  const evId = e?.lastEventId || e?.id;
  if (evId && _seenEventIds.has(evId)) {
    return; // dedup
  }
  if (evId) {
    _seenEventIds.add(evId);
    _lastEventId = evId;
    if (_seenEventIds.size > 200) {
      // trim to avoid memory growth
      const iter = _seenEventIds.values();
      for (let i = 0; i < 50; i++) {
        const next = iter.next();
        if (next.done || !next.value) break;
        _seenEventIds.delete(next.value);
      }
    }
  }

  useJourneyEngineStore.getState().bumpSseReceived();

  let parsed: any;
  try {
    parsed = typeof data === 'string' ? JSON.parse(data) : data;
  } catch {
    console.log('[SSE] non-JSON event', data);
    return;
  }

  // Backend journey SSE emits state updates with shape:
  //   { sos_id, sos_state, ts, ...meta }
  const store = useJourneyEngineStore.getState();
  if (parsed.sos_state) {
    const alert: ActiveAlert = {
      id: parsed.sos_id || _activeSosId || 'sos',
      type: 'sos',
      state: parsed.sos_state,
      message: _messageFor(parsed.sos_state, parsed),
      ts: Date.now(),
      meta: parsed,
    };
    store.setAlert(alert);

    // Escalation state sync
    if (parsed.sos_state === 'authority_dispatched') {
      store.setEscalation({
        sos_id: parsed.sos_id,
        active_layer: 'authority',
        authority_verified: true,
      });
    } else if (parsed.sos_state === 'acknowledged') {
      store.setEscalation({
        sos_id: parsed.sos_id,
        any_guardian_acked: true,
      });
    } else if (parsed.sos_state === 'resolved' || parsed.sos_state === 'failed') {
      // Auto-disconnect when SOS is terminal
      setTimeout(() => disconnectSOSStream(), 500);
    }
  }

  // Risk update from backend (if broadcast on this stream)
  if (parsed.risk_score != null && parsed.level) {
    store.setRisk(parsed.risk_score, parsed.level);
  }
}

function _messageFor(state: string, payload: any): string {
  switch (state) {
    case 'delivered':            return 'SOS delivered — guardians notified';
    case 'acknowledged':         return `Acknowledged by ${payload.by || 'guardian'}`;
    case 'authority_dispatched': return 'Authority dispatched';
    case 'actioned':             return 'Response in progress';
    case 'resolved':             return 'SOS resolved';
    case 'failed':               return 'SOS dispatch failed';
    default:                      return `SOS state: ${state}`;
  }
}

function _scheduleReconnect(): void {
  if (!_activeSosId) return;
  if (_reconnectTimer) return;
  _reconnectAttempts += 1;
  // 2s, 4s, 8s, 16s, 32s, 60s cap
  const delay = Math.min(MAX_BACKOFF_MS, 2_000 * Math.pow(2, _reconnectAttempts - 1));
  useJourneyEngineStore.getState().setConnection('reconnecting');
  console.log(`[SSE] reconnecting in ${delay}ms (attempt ${_reconnectAttempts})`);

  try { _es?.close(); } catch (e) { /* ignore */ }
  _es = null;

  _reconnectTimer = setTimeout(() => {
    _reconnectTimer = null;
    _openStream();
  }, delay);
}
