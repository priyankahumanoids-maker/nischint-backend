// REL-08 — Shared Command Center dashboard summary hook.
//
// Single fetcher for `/api/admin/monitoring/dashboard-summary` —
// every capsule (`DLQCapsule`, `DBIncidentsCapsule`,
// `SachetStatusCapsule`, `ConsentHealthCapsule`, `TwinTrustTile`)
// subscribes here so the whole strip pays exactly one network
// round-trip per 30 s poll instead of five.
//
// Architecture:
//   * Module-level singleton state (`_state` + `_listeners`) — we
//     intentionally DON'T use React Context here. A Context would
//     re-render every consumer on every poll; with this listener
//     pattern each capsule re-renders only when it actually
//     subscribes via `useDashboardSummary()`.
//   * Reference counting (`_subscriberCount`) controls when the
//     interval starts/stops — when the last capsule unmounts the
//     polling stops entirely.
//   * Multiple in-flight calls are deduped with `_inflight`.

import { useEffect, useState } from 'react';
import api from '../api';

const POLL_MS = 30_000;

let _state = { data: null, error: null, loading: false };
const _listeners = new Set();
let _intervalId = null;
let _subscriberCount = 0;
let _inflight = null;

function _emit() {
  for (const fn of _listeners) {
    try { fn(_state); } catch { /* listener errors must not break siblings */ }
  }
}

async function _fetchOnce() {
  // Dedupe — concurrent calls share the same promise.
  if (_inflight) return _inflight;
  _state = { ..._state, loading: true };
  _emit();
  _inflight = (async () => {
    try {
      const res = await api.get('/admin/monitoring/dashboard-summary');
      _state = { data: res.data, error: null, loading: false };
    } catch (e) {
      // 403 = not operator/admin → capsules detect this and hide.
      const errCode = e?.response?.status === 403 ? 'forbidden' : (e?.message || 'fetch_failed');
      _state = { ..._state, error: errCode, loading: false };
    }
    _emit();
    _inflight = null;
  })();
  return _inflight;
}

function _startPolling() {
  if (_intervalId != null) return;
  _intervalId = setInterval(_fetchOnce, POLL_MS);
  // Kick the first fetch immediately so the chip doesn't sit blank
  // for 30 s after mount.
  _fetchOnce();
}

function _stopPolling() {
  if (_intervalId != null) {
    clearInterval(_intervalId);
    _intervalId = null;
  }
}

/**
 * Subscribe to the dashboard-summary stream.
 *
 * @param {(s: {data: object|null, error: string|null, loading: boolean}) => any} [selector]
 *        Optional projector. If provided, the hook returns
 *        `selector(state)`. Re-renders only when the selector's
 *        return value changes by reference equality (a `useMemo`-
 *        style optimisation — selectors should be cheap and pure).
 * @returns the full state, or the projected slice when `selector`
 *          is supplied.
 */
export function useDashboardSummary(selector) {
  // Initial snapshot — same shape across re-mounts.
  const initial = selector ? selector(_state) : _state;
  const [slice, setSlice] = useState(initial);

  useEffect(() => {
    const onUpdate = (next) => {
      const projected = selector ? selector(next) : next;
      // Skip pointless re-renders when the selector projects to the
      // same reference (common when only an unrelated slice updated).
      setSlice((prev) => (Object.is(prev, projected) ? prev : projected));
    };
    _listeners.add(onUpdate);
    _subscriberCount += 1;
    if (_subscriberCount === 1) _startPolling();
    return () => {
      _listeners.delete(onUpdate);
      _subscriberCount -= 1;
      if (_subscriberCount === 0) _stopPolling();
    };
    // We deliberately want the SAME selector reference between renders
    // when the caller defines it inline — they should wrap with
    // useCallback if they want stricter equality. For the capsules,
    // a fresh selector each render is fine; the listener fires only
    // on poll events, not on render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return slice;
}

/** Test seam — force an immediate refetch. */
export function refetchDashboardSummary() {
  return _fetchOnce();
}
