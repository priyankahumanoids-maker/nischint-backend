// ALERT_TRIGGER_V2 Parity Chip — diagnostic, not decorative.
//
// Polls /api/admin/monitoring/alert-v2/shadow-stats every 30s. For
// each kind family in scope (HELP_REQUEST, SOS) it surfaces the
// signals operators actually need before flipping the rollout gate:
//
//   * total events observed
//   * match%        — agreement between V1 and V2
//   * critical mismatch count (zero is the precondition for rollout)
//   * ΔFanout       — average (v2_count − v1_count); negative means
//                     V2 narrows, positive means V2 expands
//   * worst-recent classification + auto-disable verdict
//
// Critical insight (locked from operator review):
//   Diffs aren't binary. Some are improvements (ranking_improvement,
//   unreachable_dropped, fanout_reduction_help). Some are regressions
//   (missed_target_critical, unreachable_target_chosen). The chip
//   reports both — it does NOT collapse them into a single parity
//   percentage that obscures the regression rate.
//
// The chip hides itself for non-admin users (403). It NEVER shows
// "V2 Healthy ✅" — that's vanity status. Worst case is always
// surfaced visibly.

import React, { useEffect, useRef, useState } from 'react';
import { ChevronDown, ShieldAlert } from 'lucide-react';
import api from '../../api';

const KINDS_OF_INTEREST = ['help_request', 'help_requested', 'help', 'sos', 'sos_triggered', 'panic'];

const CRITICAL_CLASSES = new Set([
  'v2_would_not_dispatch',
  'missed_target_critical',
  'unreachable_target_chosen',
]);

const IMPROVEMENT_CLASSES = new Set([
  'ranking_improvement',
  'unreachable_dropped',
  'fanout_reduction_help',
]);

const fmtPct = (v) => (v === null || v === undefined || Number.isNaN(v) ? '—' : `${v.toFixed(0)}%`);
const fmtDelta = (v) => {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  if (v === 0) return '±0';
  return v > 0 ? `+${v.toFixed(1)}` : v.toFixed(1);
};

function tierFor(kindData) {
  // Honour the WS-pushed override first so the chip flips within
  // 1s of a server-side tier transition. The 30s poll still
  // reconciles to authoritative on the next tick.
  if (kindData && kindData._ws_tier_override) {
    return kindData._ws_tier_override;
  }
  // Worst-of: any auto-disabled OR any critical events → CRITICAL.
  // Otherwise improvements > 0 with no critical → IMPROVING.
  // Match-rate < 80 % → DRIFT. Else IN_PARITY.
  if (!kindData) return 'unknown';
  if (kindData.safety?.auto_disabled) return 'auto_disabled';
  if ((kindData.critical_count || 0) > 0) return 'critical';
  if ((kindData.match_pct || 0) < 80 && (kindData.total || 0) >= 5) return 'drift';
  if ((kindData.improvement_count || 0) > 0) return 'improving';
  return 'in_parity';
}

const TIER_TONE = {
  auto_disabled: { label: 'AUTO-DISABLED', class: 'text-rose-300', dot: 'bg-rose-500', ring: 'animate-ping bg-rose-400 opacity-75' },
  critical:      { label: 'CRITICAL',      class: 'text-rose-300', dot: 'bg-rose-500', ring: 'animate-ping bg-rose-400 opacity-75' },
  drift:         { label: 'DRIFT',         class: 'text-amber-300', dot: 'bg-amber-500', ring: null },
  improving:     { label: 'IMPROVING',     class: 'text-emerald-300', dot: 'bg-emerald-500', ring: null },
  in_parity:     { label: 'IN PARITY',     class: 'text-slate-300', dot: 'bg-slate-500', ring: null },
  unknown:       { label: 'NO DATA',       class: 'text-slate-500', dot: 'bg-slate-700', ring: null },
};

function aggregateByPolicy(diagnostic) {
  // Combine help_request + help_requested + help into one HELP roll-up,
  // and sos + sos_triggered + panic into one SOS roll-up. Keeps the
  // chip readable even when callers use different kind strings.
  const helpKinds = ['help_request', 'help_requested', 'help'];
  const sosKinds  = ['sos', 'sos_triggered', 'panic', 'emergency_triggered'];
  const merge = (kinds) => {
    let total = 0, match = 0, critical = 0, improvement = 0;
    let deltas = [];
    let worst = null, worstAt = null;
    let autoDisabled = false, autoDisabledKind = null;
    for (const k of kinds) {
      const d = diagnostic?.[k];
      if (!d) continue;
      total += d.total || 0;
      match += d.match_count || 0;
      critical += d.critical_count || 0;
      improvement += d.improvement_count || 0;
      if (typeof d.fanout_delta_avg === 'number') deltas.push(d.fanout_delta_avg);
      if (d.worst_recent && (!worstAt || (d.worst_recent_at || '') > worstAt)) {
        worst = d.worst_recent; worstAt = d.worst_recent_at;
      }
      if (d.safety?.auto_disabled) {
        autoDisabled = true;
        autoDisabledKind = k;
      }
    }
    const matchPct = total > 0 ? (match / total) * 100 : null;
    const delta = deltas.length ? deltas.reduce((a, b) => a + b, 0) / deltas.length : null;
    return {
      total,
      match_count: match,
      match_pct: matchPct,
      critical_count: critical,
      improvement_count: improvement,
      fanout_delta_avg: delta,
      worst_recent: worst,
      worst_recent_at: worstAt,
      safety: { auto_disabled: autoDisabled, kind: autoDisabledKind },
    };
  };
  return { HELP: merge(helpKinds), SOS: merge(sosKinds) };
}

function classBreakdown(diagnostic, kindGroup) {
  const helpKinds = ['help_request', 'help_requested', 'help'];
  const sosKinds  = ['sos', 'sos_triggered', 'panic', 'emergency_triggered'];
  const kinds = kindGroup === 'HELP' ? helpKinds : sosKinds;
  const acc = {};
  for (const k of kinds) {
    const d = diagnostic?.[k];
    if (!d?.by_classification) continue;
    for (const [c, n] of Object.entries(d.by_classification)) {
      acc[c] = (acc[c] || 0) + n;
    }
  }
  // Sort: critical first, then improvement, then others.
  return Object.entries(acc).sort((a, b) => {
    const aCrit = CRITICAL_CLASSES.has(a[0]) ? 0 : 1;
    const bCrit = CRITICAL_CLASSES.has(b[0]) ? 0 : 1;
    if (aCrit !== bCrit) return aCrit - bCrit;
    return b[1] - a[1];
  });
}

export const V2ParityChip = () => {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);

  useEffect(() => {
    let alive = true;
    const fetchStats = async () => {
      try {
        const res = await api.get('/admin/monitoring/alert-v2/shadow-stats');
        if (alive) { setData(res.data); setError(null); }
      } catch (e) {
        if (alive) setError(e.response?.status === 403 ? 'no-access' : 'unreachable');
      }
    };
    fetchStats();
    const iv = setInterval(fetchStats, 30000);

    // Real-time tier delta — embedded in the existing system_health_delta
    // envelope so we share one WS subscription with NetworkHealth +
    // SystemHealthCapsule. The 30s poll above is the reconciliation
    // layer that fills any missed-frame gaps.
    const onDelta = (e) => {
      const d = e.detail || {};
      if (d.source !== 'alert_v2' || !d.v2_parity) return;
      const v2p = d.v2_parity;
      setData((prev) => {
        const base = prev || {};
        const nextDiag = { ...(base.diagnostic || {}) };
        const kindKey = v2p.kind;
        const existing = nextDiag[kindKey] || {};
        nextDiag[kindKey] = {
          ...existing,
          total:             v2p.total ?? existing.total ?? 0,
          critical_count:    v2p.critical_count ?? existing.critical_count ?? 0,
          improvement_count: v2p.improvement_count ?? existing.improvement_count ?? 0,
          match_pct:         v2p.match_pct ?? existing.match_pct ?? null,
          fanout_delta_avg:  v2p.fanout_delta_avg ?? existing.fanout_delta_avg ?? null,
          by_classification: existing.by_classification || {},
          worst_recent:      existing.worst_recent || null,
          safety: {
            ...(existing.safety || {}),
            auto_disabled: !!v2p.auto_disabled,
          },
          // Mark the optimistic tier override so the chip header
          // reflects the WS event in <1s; the next 30s poll will
          // reconcile if the chip's locally computed tier disagrees
          // with the server-side tier.
          _ws_tier_override: v2p.tier,
        };
        return { ...base, diagnostic: nextDiag };
      });
    };
    window.addEventListener('cc:system_health_delta', onDelta);
    return () => {
      alive = false;
      clearInterval(iv);
      window.removeEventListener('cc:system_health_delta', onDelta);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    const onClick = (e) => { if (!containerRef.current?.contains(e.target)) setOpen(false); };
    const onEsc = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onEsc);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onEsc);
    };
  }, [open]);

  if (error === 'no-access') return null;
  if (!data) {
    return (
      <div
        className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-slate-800/60 border border-slate-700/40"
        data-testid="v2-parity-chip-loading"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-slate-600 animate-pulse" />
        <span className="text-[10px] font-mono text-slate-500 tracking-wider">V2 —</span>
      </div>
    );
  }

  const groups = aggregateByPolicy(data?.diagnostic || {});
  // Worst-of tier across both groups drives the headline.
  const helpTier = tierFor(groups.HELP);
  const sosTier  = tierFor(groups.SOS);
  const tierPriority = ['auto_disabled', 'critical', 'drift', 'improving', 'in_parity', 'unknown'];
  const headlineTier = [helpTier, sosTier].sort(
    (a, b) => tierPriority.indexOf(a) - tierPriority.indexOf(b),
  )[0];
  const tone = TIER_TONE[headlineTier] || TIER_TONE.unknown;
  const totalCritical = (groups.HELP.critical_count || 0) + (groups.SOS.critical_count || 0);

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-slate-800/70 border border-slate-700/50 hover:bg-slate-700/60 transition-colors"
        data-testid="v2-parity-chip"
        title="ALERT_TRIGGER_V2 — shadow dispatch parity vs V1"
      >
        <span className="relative inline-flex w-1.5 h-1.5">
          {tone.ring && <span className={`absolute inline-flex w-full h-full rounded-full ${tone.ring}`} />}
          <span className={`relative inline-flex w-1.5 h-1.5 rounded-full ${tone.dot}`} />
        </span>
        <ShieldAlert className="w-3 h-3 text-slate-400" />
        <span
          className={`text-[10px] font-mono font-bold tracking-wider ${tone.class}`}
          data-testid="v2-parity-tier"
        >
          V2 {tone.label}
        </span>
        {totalCritical > 0 && (
          <span
            className="text-[9px] font-mono font-bold text-rose-300"
            data-testid="v2-parity-critical-count"
            title="Critical regressions in last 200 events"
          >· {totalCritical} CRITICAL</span>
        )}
        <ChevronDown className={`w-3 h-3 text-slate-500 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-1.5 z-[1500] w-[360px] max-w-[calc(100vw-1.5rem)] rounded-md border border-slate-700 bg-slate-900/95 backdrop-blur shadow-xl"
          data-testid="v2-parity-flyout"
        >
          <div className="px-3 py-2 border-b border-slate-700/60 flex items-center justify-between">
            <span className="text-[10px] font-mono font-bold tracking-wider text-slate-200">
              ALERT_TRIGGER_V2 SHADOW
            </span>
            <span className="text-[9px] font-mono text-slate-500">
              mode={data.mode || 'shadow'} · help={data.rollout?.help_request_pct ?? 0}% · sos={data.rollout?.sos_pct ?? 0}%
            </span>
          </div>

          <div className="p-2 space-y-2">
            <KindRow group="HELP" data={groups.HELP} breakdown={classBreakdown(data?.diagnostic, 'HELP')} />
            <KindRow group="SOS"  data={groups.SOS}  breakdown={classBreakdown(data?.diagnostic, 'SOS')} />
          </div>

          <div className="px-3 py-1.5 border-t border-slate-700/60 text-[9px] font-mono text-slate-500 flex justify-between">
            <span>Auto-disable: ≥{`5%`} critical / 10-min window</span>
            <span data-testid="v2-parity-rollout-mode">
              {data.mode === 'shadow' ? 'V1 OWNS DISPATCH' : 'V2 ACTIVE COHORT'}
            </span>
          </div>
        </div>
      )}
    </div>
  );
};

const KindRow = ({ group, data, breakdown }) => {
  const tier = tierFor(data);
  const tone = TIER_TONE[tier] || TIER_TONE.unknown;
  const matchLabel = data.total ? fmtPct(data.match_pct) : '—';

  return (
    <div className="bg-slate-800/40 border border-slate-700/30 rounded p-2" data-testid={`v2-parity-row-${group.toLowerCase()}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full ${tone.dot}`} />
          <span className="text-[10px] font-mono font-bold tracking-wider text-slate-200">
            {group}
          </span>
          <span className={`text-[9px] font-mono font-bold tracking-wider ${tone.class}`}>
            · {tone.label}
          </span>
        </div>
        <span className="text-[9px] font-mono text-slate-500">
          {data.total || 0} events
        </span>
      </div>
      <div className="grid grid-cols-3 gap-x-2 mt-1 text-[10px] font-mono">
        <Stat label="match" value={matchLabel} />
        <Stat
          label="critical"
          value={`${data.critical_count || 0}`}
          tone={(data.critical_count || 0) > 0 ? 'rose' : 'slate'}
        />
        <Stat label="ΔFanout" value={fmtDelta(data.fanout_delta_avg)} />
      </div>
      {data.safety?.auto_disabled && (
        <div className="mt-1 text-[9px] font-mono text-rose-300" data-testid={`v2-parity-auto-disabled-${group.toLowerCase()}`}>
          ⚠ auto-disabled — investigate critical events before clearing.
        </div>
      )}
      {breakdown.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {breakdown.map(([c, n]) => (
            <span
              key={c}
              className={
                CRITICAL_CLASSES.has(c)
                  ? 'inline-block px-1 py-0 rounded bg-rose-500/15 border border-rose-500/30 text-[9px] font-mono text-rose-200'
                  : IMPROVEMENT_CLASSES.has(c)
                    ? 'inline-block px-1 py-0 rounded bg-emerald-500/15 border border-emerald-500/30 text-[9px] font-mono text-emerald-200'
                    : 'inline-block px-1 py-0 rounded bg-slate-700/40 border border-slate-600/30 text-[9px] font-mono text-slate-300'
              }
            >
              {c} · {n}
            </span>
          ))}
        </div>
      )}
      {data.worst_recent && (
        <div className="mt-1 text-[9px] font-mono text-slate-400" data-testid={`v2-parity-worst-${group.toLowerCase()}`}>
          worst recent · {data.worst_recent}
        </div>
      )}
    </div>
  );
};

const Stat = ({ label, value, tone = 'slate' }) => {
  const cls = tone === 'rose' ? 'text-rose-300' : 'text-slate-200';
  return (
    <div className="flex flex-col">
      <span className="text-[8px] tracking-wider text-slate-500 uppercase">{label}</span>
      <span className={`font-bold ${cls}`}>{value}</span>
    </div>
  );
};

export default V2ParityChip;
