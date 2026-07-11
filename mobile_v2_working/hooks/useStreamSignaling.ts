// NISCH-008 — WebSocket signalling hook for live emergency streams.
//
// Connects to `WS /api/stream/{id}/signal?token=…`, exposes a
// `send(msg)` method, and invokes `onMessage` for every inbound
// payload. Server is an opaque relay — it forwards offer / answer /
// ice_candidate / end_stream between peers without inspecting them.
//
// Hook lifecycle:
//   * connect on mount
//   * close on unmount or on `streamId === null`
//   * exponential backoff up to STREAM_WS_MAX_RETRIES; fail-quiet
//     after that (caller decides whether to render a "lost" UI)
//
// We use the global `WebSocket` (RN provides it) — no extra dep.
import { useEffect, useRef, useState, useCallback } from 'react';
import { useAuthStore } from '@/stores/authStore';
import { API_BASE } from '@/services/api';

const STREAM_WS_MAX_RETRIES = 4;

export interface SignalMessage {
  type:
    | 'connected'
    | 'offer'
    | 'answer'
    | 'ice_candidate'
    | 'end_stream'
    | 'error'
    | string;
  [k: string]: any;
}

interface Options {
  streamId: string | null;
  onMessage: (msg: SignalMessage) => void;
  enabled?: boolean;
}

export function useStreamSignaling({ streamId, onMessage, enabled = true }: Options) {
  const token = useAuthStore((s: any) => s.token);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const closedRef = useRef(false);
  const msgRef = useRef(onMessage);
  msgRef.current = onMessage;

  const [connected, setConnected] = useState(false);

  const send = useCallback((msg: SignalMessage) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === 1 /* OPEN */) {
      try {
        ws.send(JSON.stringify(msg));
      } catch (e) {
        if (__DEV__) console.warn('[STREAM_WS] send failed:', e);
      }
    }
  }, []);

  const close = useCallback(() => {
    closedRef.current = true;
    setConnected(false);
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws) {
      try { ws.close(); } catch {}
    }
  }, []);

  useEffect(() => {
    if (!enabled || !streamId || !token || !API_BASE) return;
    closedRef.current = false;
    retryRef.current = 0;

    let cancelled = false;
    const open = () => {
      if (cancelled || closedRef.current) return;
      // Convert https:// → wss:// (and http:// → ws://) so we hit the
      // signalling relay through the same TLS-terminated host.
      const wsBase = API_BASE.replace(/^http/, 'ws');
      const url = `${wsBase}/api/stream/${streamId}/signal?token=${encodeURIComponent(token)}`;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (cancelled) return;
        retryRef.current = 0;
        setConnected(true);
        if (__DEV__) console.log('[STREAM_WS] connected', streamId);
      };
      ws.onmessage = (evt: any) => {
        if (cancelled) return;
        try {
          const parsed = JSON.parse(evt.data);
          msgRef.current(parsed);
        } catch (e) {
          if (__DEV__) console.warn('[STREAM_WS] bad json:', evt.data);
        }
      };
      ws.onerror = () => {
        if (__DEV__) console.warn('[STREAM_WS] error', streamId);
      };
      ws.onclose = (evt: any) => {
        setConnected(false);
        if (cancelled || closedRef.current) return;
        // Server uses 4003 (not authorized) / 4004 (not found) /
        // 4009 (already ended/declined) — terminal, never retry.
        if (evt?.code >= 4001 && evt?.code <= 4099) return;
        if (retryRef.current >= STREAM_WS_MAX_RETRIES) return;
        const backoff = Math.min(15_000, 500 * 2 ** retryRef.current);
        retryRef.current += 1;
        setTimeout(open, backoff);
      };
    };

    open();
    return () => {
      cancelled = true;
      close();
    };
  }, [streamId, token, enabled, close]);

  return { connected, send, close };
}
