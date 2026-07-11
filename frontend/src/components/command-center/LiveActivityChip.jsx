// Live Activity Class Chip — NISCH-012 operator presentation surface.
//
// Backend contract (additive, observational only — see
// app/api/command_center_unified.py:_build_motion_telemetry_view):
//
//   payload.motion_telemetry = {
//     status:                    'live' | 'fresh' | 'recent' | 'stale' | 'unavailable',
//     activity_class:            'stationary' | 'walking' | 'running' | 'vehicle' | 'anomalous' | null,
//     last_motion_at:            ISO8601 | null,
//     freshness_s:               number | null,
//     window_count_24h:          number,
//     activity_distribution_24h: { stationary, walking, running, vehicle, anomalous } | null,
//     telemetry_pipeline_version: string | null,
//   }
//
// Strict additive contract:
//   * Pure UI augmentation — never affects dispatch, risk score,
//     trust calibration, or telemetry ingestion.
//   * Fail-silent on missing / malformed data → renders `STALE`
//     placeholder, never throws.
//   * No new backend endpoint, no new WS subscription — the chip
//     reads from the already-hydrated unified payload.
//   * Local freshness ticker (30 s) so the relative-time label
//     decays even when no new payload arrives.
//
// UX rules (per spec):
//   * Ambient, not alarming. No pulsing on healthy states.
//   * Only `anomalous` activity gets attention styling (rose) —
//     never a flashing/pinging dot. The chip is calm by design.
//   * If telemetry is stale → degrade gracefully to a slate "stale"
//     chip with no activity icon, mirroring the truth-layer dashed
//     marker semantics used on the LiveSafetyMap.

import React, { useEffect, useMemo, useState } from 'react';
import {
  Activity, Pause, Footprints, Zap, Car, AlertTriangle, CircleHelp,
} from 'lucide-react';

// ── Locked activity → presentation map ────────────────────────────
//
// Tone intent:
//   stationary → neutral / calm   (slate)
//   walking    → safe / active    (emerald)
//   running    → elevated awareness (amber)
//   vehicle    → transit state    (sky)
//   anomalous  → high attention   (rose)
//
// Icons are intentionally calm (lucide line-icons, not filled), and
// the dot color matches the tone token. No animation on any tone —
// this is ambient situational intelligence, not an alarm surface.
const ACTIVITY_TONE = {
  stationary: {
    label: 'Stationary',
    icon: Pause,
    dot: 'bg-slate-400',
    text: 'text-slate-200',
    border: 'border-slate-700/70',
  },
  walking: {
    label: 'Walking',
    icon: Footprints,
    dot: 'bg-emerald-400',
    text: 'text-emerald-200',
    border: 'border-emerald-800/60',
  },
  running: {
    label: 'Running',
    icon: Zap,
    dot: 'bg-amber-400',
    text: 'text-amber-200',
    border: 'border-amber-800/60',
  },
  vehicle: {
    label: 'In transit',
    icon: Car,
    dot: 'bg-sky-400',
    text: 'text-sky-200',
    border: 'border-sky-800/60',
  },
  anomalous: {
    label: 'Anomalous',
    icon: AlertTriangle,
    dot: 'bg-rose-400',
    text: 'text-rose-200',
    border: 'border-rose-800/60',
  },
};

// Unknown-enum fallback. Reuses the slate/CircleHelp pair so the
// chip stays visually consistent and never reads as "active".
const UNKNOWN_TONE = {
  label: 'Unknown',
  icon: CircleHelp,
  dot: 'bg-slate-600',
  text: 'text-slate-400',
  border: 'border-slate-700/70',
};

// Stale / unavailable share the same calm slate render — the only
// difference is the secondary label.
const STALE_TONE = {
  label: 'No recent activity',
  icon: CircleHelp,
  dot: 'bg-slate-600',
  text: 'text-slate-500',
  border: 'border-slate-800/80',
};

// ── Helpers ───────────────────────────────────────────────────────

function pickTone(activityClass, status) {
  if (status === 'stale' || status === 'unavailable') return STALE_TONE;
  if (!activityClass) return UNKNOWN_TONE;
  return ACTIVITY_TONE[activityClass] || UNKNOWN_TONE;
}

function formatRelative(lastIso, freshnessS, status) {
  if (status === 'unavailable' || !lastIso) return 'no data';
  if (status === 'live') return 'LIVE';
  if (freshnessS === null || freshnessS === undefined) return '—';
  const s = Math.max(0, Math.floor(freshnessS));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

// Returns freshness in seconds derived from the original payload
// timestamp + the local clock. Lets the chip decay between
// payload refreshes (the unified endpoint refreshes on selection /
// WS-driven invalidation, not on a fixed cadence).
function liveFreshness(lastIso, nowMs) {
  if (!lastIso) return null;
  const t = Date.parse(lastIso);
  if (Number.isNaN(t)) return null;
  return Math.max(0, (nowMs - t) / 1000);
}

function statusFromFreshness(freshnessS) {
  if (freshnessS === null || freshnessS === undefined) return 'unavailable';
  if (freshnessS <= 60)   return 'live';
  if (freshnessS <= 300)  return 'fresh';
  if (freshnessS <= 1800) return 'recent';
  return 'stale';
}

// ── Component ─────────────────────────────────────────────────────

export const LiveActivityChip = ({ motion, loading }) => {
  // Local clock tick so the relative-time label and freshness band
  // decay even when no new payload lands. 15 s tick is more than
  // accurate enough for an ambient operator chip — anything faster
  // is wasted re-renders.
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNowMs(Date.now()), 15_000);
    return () => clearInterval(t);
  }, []);

  // Defensive: shape is documented but never trusted blindly.
  const rawClass  = motion?.activity_class || null;
  const lastIso   = motion?.last_motion_at || null;
  const baseStatus = motion?.status || 'unavailable';

  // Re-derive freshness client-side so the chip ages between
  // payload refreshes. Backend's `freshness_s` is the snapshot
  // value at request time; this is the live one.
  const freshnessS = useMemo(
    () => liveFreshness(lastIso, nowMs),
    [lastIso, nowMs],
  );
  // If we have a `last_motion_at` and a live freshness, prefer the
  // client-derived status — it stays honest as time passes. If the
  // backend says `unavailable`, respect that (no data ≠ stale data).
  const status = baseStatus === 'unavailable'
    ? 'unavailable'
    : statusFromFreshness(freshnessS);

  const tone = pickTone(rawClass, status);
  const Icon = tone.icon;
  const rel  = formatRelative(lastIso, freshnessS, status);

  // For accessibility we build a clean spoken label up-front. The
  // visible chip is compact; screen readers get the full sentence.
  const aria = useMemo(() => {
    if (status === 'unavailable') {
      return 'Activity telemetry unavailable for this user.';
    }
    if (status === 'stale') {
      return 'No recent activity telemetry. Last activity unknown.';
    }
    const cls = rawClass || 'unknown';
    return `Current activity: ${cls}. Last update ${rel}.`;
  }, [status, rawClass, rel]);

  // Tooltip carries the 24h distribution for operators who want a
  // quick "what's been going on" without opening another panel.
  const tooltip = useMemo(() => {
    const dist = motion?.activity_distribution_24h;
    const n = motion?.window_count_24h || 0;
    if (!dist || n === 0) {
      if (status === 'unavailable') {
        return 'No motion telemetry uploaded for this user yet.';
      }
      return `Last motion: ${rel}`;
    }
    const parts = Object.entries(dist)
      .filter(([, v]) => v > 0)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `${k} ${Math.round((v / n) * 100)}%`)
      .slice(0, 4);
    const head = status === 'unavailable' ? 'No data' : `${rel}`;
    return `${head} · 24h: ${parts.join(' · ')}`;
  }, [motion, status, rel]);

  // Loading skeleton — only shown on the very first per-user fetch.
  // Subsequent fetches keep the last good chip visible to avoid
  // flicker. Returned AFTER all hooks so the hook order stays
  // stable across renders.
  if (loading && !motion) {
    return (
      <div
        data-testid="live-activity-chip-loading"
        className="inline-flex items-center gap-2 rounded-full border border-slate-800/80 bg-slate-900/70 px-3 py-1.5 text-xs text-slate-500"
      >
        <span className="h-2 w-2 animate-pulse rounded-full bg-slate-700" />
        <span className="font-medium tracking-wide">Activity…</span>
      </div>
    );
  }

  return (
    <div
      data-testid="live-activity-chip"
      data-activity-class={rawClass || 'unknown'}
      data-activity-status={status}
      title={tooltip}
      aria-label={aria}
      role="status"
      className={`inline-flex items-center gap-2 rounded-full border ${tone.border} bg-slate-900/70 px-3 py-1.5 text-xs font-medium tracking-wide ${tone.text}`}
    >
      <span className="relative inline-flex h-2 w-2">
        <span
          data-testid="live-activity-chip-dot"
          className={`relative inline-flex h-2 w-2 rounded-full ${tone.dot}`}
        />
      </span>
      <Icon size={12} className="opacity-80" aria-hidden="true" />
      <span data-testid="live-activity-chip-label">{tone.label}</span>
      <span
        data-testid="live-activity-chip-relative"
        className="text-[10px] uppercase tracking-wider opacity-70"
      >
        · {rel}
      </span>
    </div>
  );
};

export default LiveActivityChip;
