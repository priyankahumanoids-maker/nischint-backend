// Twin Trust Tile — operator status surface for the behavioural
// intelligence engine.
//
// Backend contract (LOCKED — see app/services/behavioral/badge.py):
//   GET /api/behavioral/trust/badge → { level, color, reason }
//   WS  trust_level_changed         → { level, reason, trend,
//                                       severity_delta }
//
// Rendering contract:
//   * HIGH_TRUST   → green dot, "TRUST HIGH"
//   * MEDIUM_TRUST → yellow dot, "TRUST MEDIUM"
//   * LOW_TRUST    → red dot + animated ping, "TRUST LOW"
//   * unknown / fetch fail → yellow + "TRUST CHECK" (matches the
//     backend's fail-safe MEDIUM-default).
//
// Polling: 10 s (matches backend Redis cache TTL — anything tighter
// is wasted load because the cache won't change inside the window).
// The polling endpoint is the SOURCE OF TRUTH per the locked spec.
// WebSocket is enhancement only and wired separately if/when needed.
//
// Transition animation: `severity_delta` from the WS payload would
// drive a ⬆ / ⬇ arrow on a future SSE-wired version. For the
// polling-only MVP we infer transitions client-side by comparing
// the previous level — same direction, same arrow semantics.

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Brain, ChevronDown, ArrowUpRight, ArrowDownRight } from 'lucide-react';
import { useDashboardSummary } from '../../hooks/useDashboardSummary';

// Locked level → presentation map. The three states + the
// fail-safe `CHECK` state cover every backend outcome.
const STATE_TONE = {
  HIGH_TRUST: {
    label: 'TRUST HIGH',
    cls:   'text-emerald-300',
    dot:   'bg-emerald-500',
    ring:  null,
  },
  MEDIUM_TRUST: {
    label: 'TRUST MEDIUM',
    cls:   'text-amber-300',
    dot:   'bg-amber-500',
    ring:  null,
  },
  LOW_TRUST: {
    // LOW is the only state that animates the dot — operators
    // should notice the colour change without staring.
    label: 'TRUST LOW',
    cls:   'text-rose-300',
    dot:   'bg-rose-500',
    ring:  'animate-ping bg-rose-400 opacity-75',
  },
  CHECK: {
    label: 'TRUST CHECK',
    cls:   'text-slate-400',
    dot:   'bg-slate-600',
    ring:  null,
  },
};

// Locked reason taxonomy → operator-readable copy. Mirrors the
// backend ladder (services/behavioral/badge.py:REASON_PRIORITY).
const REASON_COPY = {
  all_healthy:                        'Behavioural twin healthy — all signals nominal.',
  insufficient_reconciliation_window: 'Warming up — fewer than 168 reconciled predictions in the ledger.',
  divergence_elevated:                'Forecasters disagree more than usual — environmental volatility.',
  delayed_ledger_convergence:         'Reconciliation queue is lagging — accuracy reports may be stale.',
  prediction_precision_degraded:      'Critical-risk precision below the healthy band.',
  false_escalation_spike:             'False-escalation rate above the healthy band.',
  dlq_fallback_spike:                 'Behavioural anomaly DLQ depth elevated — DB write retries firing.',
  unresolved_backlog:                 'Unresolved prediction backlog — reconciler is behind.',
  telemetry_unavailable:              'Telemetry partial or unavailable — defaulting to safe MEDIUM.',
};

const LEVEL_RANK = { HIGH_TRUST: 0, MEDIUM_TRUST: 1, LOW_TRUST: 2 };

// 10 s polling matches the backend Redis cache TTL — anything
// tighter is wasted load. The WebSocket pathway (when wired) will
// drive instant transitions; polling remains source of truth.
// REL-08: polling now lives in useDashboardSummary (30s shared interval,
// Redis-cached 10s server-side). Previous local poll was 10s.

function deriveDelta(prevLevel, nextLevel) {
  if (!prevLevel || !nextLevel) return 0;
  const a = LEVEL_RANK[prevLevel];
  const b = LEVEL_RANK[nextLevel];
  if (a === undefined || b === undefined) return 0;
  return b - a;
}

export const TwinTrustTile = () => {
  const [open, setOpen] = useState(false);
  // Sticky `severity_delta` for visual animation. Cleared after
  // the highlight animation finishes (~3 s).
  const [lastDelta, setLastDelta] = useState(0);
  const prevLevelRef = useRef(null);
  const containerRef = useRef(null);
  const highlightTimerRef = useRef(null);

  // REL-08 — Subscribe to the batched dashboard-summary. We keep the
  // same shape contract { level, color, reason }; defensive fall-back
  // to `null` (→ CHECK state) if the slice is mid-load or malformed.
  const trust = useDashboardSummary((s) => s.data?.trust || null);
  const badge = useMemo(() => {
    if (!trust || !trust.level || !trust.color || !trust.reason) return null;
    return trust;
  }, [trust]);

  // Transition-detection effect — fires whenever the level changes.
  useEffect(() => {
    if (!badge) return undefined;
    const delta = deriveDelta(prevLevelRef.current, badge.level);
    if (delta !== 0) {
      setLastDelta(delta);
      if (highlightTimerRef.current) clearTimeout(highlightTimerRef.current);
      // 3 s highlight window — long enough for an operator
      // glancing at the chip to notice the direction.
      highlightTimerRef.current = setTimeout(() => setLastDelta(0), 3000);
    }
    prevLevelRef.current = badge.level;
    return undefined;
  }, [badge?.level]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Clean up any pending highlight timer on unmount.
  useEffect(() => {
    return () => {
      if (highlightTimerRef.current) {
        clearTimeout(highlightTimerRef.current);
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Close flyout on outside click — same idiom as DLQCapsule.
  useEffect(() => {
    if (!open) return undefined;
    const handler = (ev) => {
      if (containerRef.current && !containerRef.current.contains(ev.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const tone = STATE_TONE[badge?.level] || STATE_TONE.CHECK;
  const reasonCopy = useMemo(() => {
    if (!badge?.reason) return REASON_COPY.telemetry_unavailable;
    return REASON_COPY[badge.reason] || badge.reason;
  }, [badge?.reason]);

  return (
    <div ref={containerRef} className="relative" data-testid="twin-trust-tile">
      <button
        type="button"
        data-testid="twin-trust-tile-chip"
        onClick={() => setOpen((v) => !v)}
        className={`group flex items-center gap-2 rounded-full border border-slate-700/70 bg-slate-900/70 px-3 py-1.5 text-xs font-medium tracking-wide ${tone.cls} hover:border-slate-500/70 transition-colors`}
      >
        <span className="relative inline-flex h-2 w-2">
          {tone.ring && (
            <span
              data-testid="twin-trust-tile-ring"
              className={`absolute inline-flex h-full w-full rounded-full ${tone.ring}`}
            />
          )}
          <span className={`relative inline-flex h-2 w-2 rounded-full ${tone.dot}`} />
        </span>
        <Brain size={12} className="opacity-70" />
        <span data-testid="twin-trust-tile-label">{tone.label}</span>
        {lastDelta > 0 && (
          <ArrowUpRight
            data-testid="twin-trust-tile-delta-up"
            size={12}
            className="text-rose-300 animate-pulse"
          />
        )}
        {lastDelta < 0 && (
          <ArrowDownRight
            data-testid="twin-trust-tile-delta-down"
            size={12}
            className="text-emerald-300 animate-pulse"
          />
        )}
        <ChevronDown
          size={12}
          className={`opacity-70 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div
          data-testid="twin-trust-tile-flyout"
          // zIndex 1000 lifts the panel above Leaflet's pane range (max
          // popup-pane=700). Matches DLQCapsule's flyout fix.
          style={{ zIndex: 1000 }}
          className="absolute right-0 mt-2 w-72 rounded-md border border-slate-700/70 bg-slate-950/95 p-3 text-xs text-slate-200 shadow-xl backdrop-blur"
        >
          <div className="mb-2 flex items-baseline justify-between border-b border-slate-800 pb-2">
            <span className="font-semibold tracking-wide text-slate-300">
              Behavioural twin trust
            </span>
            <span
              data-testid="twin-trust-tile-level-badge"
              className={`rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider ${tone.cls}`}
            >
              {badge?.level || 'UNKNOWN'}
            </span>
          </div>

          <div
            data-testid="twin-trust-tile-reason-copy"
            className="text-[11px] leading-relaxed text-slate-300"
          >
            {reasonCopy}
          </div>

          <div className="mt-3 flex items-baseline justify-between text-[10px] text-slate-500">
            <span
              data-testid="twin-trust-tile-reason-code"
              className="font-mono"
            >
              {badge?.reason || 'telemetry_unavailable'}
            </span>
            <span data-testid="twin-trust-tile-color" className="opacity-60">
              {badge?.color || 'yellow'}
            </span>
          </div>

          <div className="mt-3 border-t border-slate-800 pt-2 text-[10px] text-slate-500">
            Source: batched /admin/monitoring/dashboard-summary every 30 s (Redis-cached 10 s).
            Observability only — never affects dispatch.
          </div>
        </div>
      )}
    </div>
  );
};

export default TwinTrustTile;
