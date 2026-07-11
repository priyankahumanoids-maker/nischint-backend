/**
 * RiskPanelTile — the docked Command Center heartbeat.
 *
 * Single decision question this surface answers: "what needs attention
 * in the next 10 seconds?"
 *
 * Behavior contract:
 *   • Polls /api/command-center/risk-panel every 5s.
 *   • On API failure: keep last good state. Never blank the UI.
 *     Show a subtle "updating…" indicator instead.
 *   • Top strip = decision in 2 seconds (Critical / Pending / Offline / TTFH).
 *   • Incident list = max 5 visible, urgency-ranked, color-coded.
 *   • Tap a row → drill-down (handled by parent via onIncidentClick).
 *
 * Not in scope: charts, graphs, analytics. This is "act now or
 * ignore safely" — nothing else.
 */
import React, { useEffect, useRef, useState } from 'react';
import {
  AlertTriangle, Clock, WifiOff, Zap, Loader2, ChevronRight,
} from 'lucide-react';
import { operatorApi } from '../../api';

const POLL_MS = 5000;

const Counter = ({ icon: Icon, value, label, tone, testId }) => {
  const tones = {
    red:   'bg-red-500/10 text-red-300 border-red-500/30',
    amber: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
    slate: 'bg-slate-700/40 text-slate-300 border-slate-600/40',
    blue:  'bg-blue-500/10 text-blue-300 border-blue-500/30',
  };
  return (
    <div
      data-testid={testId}
      className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border ${tones[tone] || tones.slate}`}
    >
      <Icon className="w-4 h-4" />
      <div className="flex flex-col leading-tight">
        <span className="text-lg font-bold tabular-nums">{value ?? '—'}</span>
        <span className="text-[9px] uppercase tracking-wider opacity-70">{label}</span>
      </div>
    </div>
  );
};

// Live ACK countdown — ticks once per second, no parent re-fetch.
const Countdown = ({ deadlineIso }) => {
  const [remaining, setRemaining] = useState(() => {
    if (!deadlineIso) return null;
    return Math.round((new Date(deadlineIso) - Date.now()) / 1000);
  });
  useEffect(() => {
    if (!deadlineIso) return undefined;
    const id = setInterval(() => {
      setRemaining(Math.round((new Date(deadlineIso) - Date.now()) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [deadlineIso]);
  if (remaining === null) return null;
  if (remaining <= 0) {
    return <span className="text-red-300 font-semibold">overdue</span>;
  }
  return <span className="font-semibold tabular-nums">ACK in {remaining}s</span>;
};

const incidentTone = (inc) => {
  if (inc.rank >= 80) return 'red';
  if (inc.rank >= 60) return 'amber';
  if (inc.kind === 'session') return 'slate';
  return 'amber';
};

const incidentToneClasses = {
  red:   'border-l-2 border-red-500 bg-red-500/5 hover:bg-red-500/10',
  amber: 'border-l-2 border-amber-500 bg-amber-500/5 hover:bg-amber-500/10',
  slate: 'border-l-2 border-slate-500 bg-slate-700/20 hover:bg-slate-700/40',
};

const incidentIcon = (inc) => {
  if (inc.is_offline) return WifiOff;
  if (inc.rank >= 80)  return AlertTriangle;
  return Clock;
};

const formatAge = (s) => {
  if (s == null) return '';
  if (s < 60)   return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
};

const guardiansText = (g) => {
  if (!g || typeof g !== 'object') return null;
  const total = g.total ?? 0;
  const healthy = g.healthy ?? 0;
  if (!total) return null;
  return `${healthy}/${total} guardians reachable`;
};

const IncidentRow = ({ inc, onClick, onAck }) => {
  const tone = incidentTone(inc);
  const Icon = incidentIcon(inc);
  const pulse = inc.rank === 100 ? 'animate-pulse' : '';
  const guardians = guardiansText(inc.guardians);

  // ── Swipe-to-ACK (pointer-based, touch + mouse + pen) ──
  // Swipe right >= SWIPE_THRESHOLD_PX → POST /api/alerts/{id}/ack
  // with ack_type="acting". Only armed for alert-kind rows that
  // haven't already been acknowledged.
  const SWIPE_THRESHOLD_PX = 90;
  const [dragX, setDragX] = React.useState(0);
  const [acking, setAcking] = React.useState(false);
  const [acked,  setAcked]  = React.useState(false);
  const startXRef = React.useRef(null);
  const canSwipe = !!onAck && inc.kind === 'alert' && inc.alert_id && !inc.ack_type && !acked;

  const onPointerDown = (e) => {
    if (!canSwipe) return;
    startXRef.current = e.clientX;
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e) => {
    if (startXRef.current == null) return;
    const dx = Math.max(0, e.clientX - startXRef.current);
    setDragX(Math.min(dx, SWIPE_THRESHOLD_PX + 20));
  };
  const onPointerUp = async (e) => {
    if (startXRef.current == null) return;
    const dx = e.clientX - startXRef.current;
    startXRef.current = null;
    if (dx >= SWIPE_THRESHOLD_PX && !acking) {
      setAcking(true);
      try {
        await onAck(inc);
        setAcked(true);
      } finally {
        setAcking(false);
        setDragX(0);
      }
    } else {
      setDragX(0);
    }
  };

  return (
    <div
      className="relative overflow-hidden rounded-md"
      data-testid={`risk-incident-wrap-${inc.alert_id || inc.session_id}`}
    >
      {/* Swipe reveal track — visible behind the row as user drags. */}
      {canSwipe && (
        <div
          className={`absolute inset-y-0 left-0 flex items-center justify-start pl-3 text-xs font-semibold transition-opacity ${
            dragX > 20 ? 'opacity-100' : 'opacity-0'
          } ${dragX >= SWIPE_THRESHOLD_PX ? 'text-emerald-300' : 'text-slate-300'}`}
          style={{ width: '100%', background: dragX >= SWIPE_THRESHOLD_PX ? 'rgba(16,185,129,0.15)' : 'rgba(100,116,139,0.12)' }}
          data-testid={`risk-swipe-hint-${inc.alert_id}`}
        >
          {acking ? 'acknowledging…' : acked ? 'acknowledged ✓' : dragX >= SWIPE_THRESHOLD_PX ? 'release to ACK' : 'swipe to ACK →'}
        </div>
      )}
      <button
        type="button"
        onClick={() => {
          // Suppress click if we were dragging/acking.
          if (dragX > 8 || acking) return;
          onClick?.(inc);
        }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => { startXRef.current = null; setDragX(0); }}
        data-testid={`risk-incident-${inc.alert_id || inc.session_id}`}
        className={`relative w-full text-left flex items-center gap-2 px-2 py-1.5 rounded-md transition-colors ${incidentToneClasses[tone]} ${pulse} ${acked ? 'opacity-60' : ''} ${canSwipe ? 'touch-pan-y cursor-grab active:cursor-grabbing' : ''}`}
        style={{ transform: `translateX(${dragX}px)`, transition: dragX === 0 ? 'transform 150ms ease-out' : 'none' }}
      >
        <Icon className={`w-4 h-4 shrink-0 ${tone === 'red' ? 'text-red-400' : tone === 'amber' ? 'text-amber-400' : 'text-slate-400'}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-xs truncate text-slate-100">
              {inc.child_name || inc.user_id?.slice(0, 8)}
            </span>
            <span className="text-[10px] text-slate-400 tabular-nums">
              {formatAge(inc.stale_seconds)}
            </span>
          </div>
          <div className="text-[10px] text-slate-400 flex items-center gap-1.5 flex-wrap">
            {inc.kind === 'alert' && (
              <span className="font-medium uppercase">
                {(inc.severity || 'alert')}
                {inc.ack_status === 'escalated' && ' • escalated'}
                {inc.ack_type && ` • ${inc.ack_type}`}
              </span>
            )}
            {inc.kind === 'session' && (
              <span className="uppercase font-medium">{inc.is_offline ? 'offline' : 'silent'}</span>
            )}
            {guardians && <span>• {guardians}</span>}
            {inc.ack_deadline && (
              <span>• <Countdown deadlineIso={inc.ack_deadline} /></span>
            )}
          </div>
        </div>
        <ChevronRight className="w-4 h-4 text-slate-500 shrink-0" />
      </button>
    </div>
  );
};

const Heartbeat = ({ generatedAt, isUpdating, hasError }) => {
  const ageS = generatedAt
    ? Math.max(0, Math.round((Date.now() - new Date(generatedAt)) / 1000))
    : null;
  const stale = ageS != null && ageS > 15;
  const tone =
    hasError ? 'text-red-300' :
    stale    ? 'text-amber-300' :
               'text-emerald-300';
  return (
    <div
      data-testid="risk-panel-heartbeat"
      className={`flex items-center gap-1.5 text-[10px] ${tone}`}
    >
      <span className={`inline-block w-1.5 h-1.5 rounded-full ${
        hasError ? 'bg-red-500' : stale ? 'bg-amber-500' : 'bg-emerald-500 animate-pulse'
      }`} />
      {hasError ? 'updating…' : (ageS != null ? `live • ${ageS}s ago` : 'connecting…')}
      {isUpdating && <Loader2 className="w-3 h-3 animate-spin opacity-60" />}
    </div>
  );
};

export default function RiskPanelTile({ onIncidentClick, limit = 10 }) {
  const [data, setData] = useState(null);
  const [isUpdating, setUpdating] = useState(false);
  const [hasError, setError] = useState(false);
  const lastGoodRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      setUpdating(true);
      try {
        const res = await operatorApi.getRiskPanel(limit);
        if (cancelled) return;
        setData(res.data);
        lastGoodRef.current = res.data;
        setError(false);
      } catch {
        // Keep last good state — never blank the UI.
        if (!cancelled) setError(true);
      } finally {
        if (!cancelled) setUpdating(false);
      }
    };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, [limit]);

  // Swipe-to-ACK handler. Commits the operator to `acting` — this
  // is stronger than `seen` (human is on it + accountable) but
  // weaker than `resolved` (which requires an explicit confirm
  // gesture and is NOT available via swipe by design).
  const handleAck = async (inc) => {
    if (!inc?.alert_id) return;
    try {
      await operatorApi.ackAlert(inc.alert_id, 'acting', false);
      // Optimistically mark this incident acked in local view so
      // the strip feels instant (the next 5s poll will refresh
      // with server truth).
      setData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          incidents: prev.incidents.map((i) =>
            i.alert_id === inc.alert_id
              ? { ...i, ack_type: 'acting' }
              : i
          ),
        };
      });
    } catch (e) {
      // Keep UX silent on failure — the next poll will reflect the
      // real state. (A toast layer could go here.)
      // eslint-disable-next-line no-console
      console.warn('[RiskPanelTile] ACK failed', e);
      throw e;  // surfaces "acknowledged ✓" only on success
    }
  };

  // Render with last good data even mid-error.
  const view = data || lastGoodRef.current;
  const summary = view?.summary || {};
  const ttfh = summary.ttfh || {};
  const incidents = (view?.incidents || []).slice(0, 5);

  return (
    <div
      data-testid="risk-panel-tile"
      className="bg-slate-800/60 border border-slate-700 rounded-lg p-2.5"
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold tracking-tight text-slate-100">
            LIVE RISK PANEL
          </span>
          <span className="text-[10px] text-slate-400">act now or ignore safely</span>
        </div>
        <Heartbeat
          generatedAt={view?.generated_at}
          isUpdating={isUpdating}
          hasError={hasError && !view}
        />
      </div>

      {/* ── Top strip: decision in 2 seconds ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-2.5">
        <Counter
          icon={AlertTriangle}
          value={summary.active_critical_alerts}
          label="Critical"
          tone="red"
          testId="risk-counter-critical"
        />
        <Counter
          icon={Clock}
          value={summary.pending_acks}
          label="Pending ACK"
          tone="amber"
          testId="risk-counter-pending"
        />
        <Counter
          icon={WifiOff}
          value={summary.shadow_sessions}
          label="Offline"
          tone="slate"
          testId="risk-counter-offline"
        />
        <Counter
          icon={Zap}
          value={
            ttfh.p50_seconds != null ? `${Math.round(ttfh.p50_seconds)}s` : '—'
          }
          label="TTFH p50"
          tone="blue"
          testId="risk-counter-ttfh"
        />
      </div>

      {/* ── Incident list ── */}
      {incidents.length === 0 ? (
        <div
          data-testid="risk-incidents-empty"
          className="text-center py-3 text-xs text-slate-500"
        >
          All clear. Nothing requires attention.
        </div>
      ) : (
        <div className="flex flex-col gap-1">
          {incidents.map((inc) => (
            <IncidentRow
              key={inc.alert_id || inc.session_id}
              inc={inc}
              onClick={onIncidentClick}
              onAck={handleAck}
            />
          ))}
          {(view?.incidents?.length || 0) > 5 && (
            <div
              data-testid="risk-more-count"
              className="text-[10px] text-slate-400 text-center pt-1"
            >
              + {view.incidents.length - 5} more pending
            </div>
          )}
        </div>
      )}
    </div>
  );
}
