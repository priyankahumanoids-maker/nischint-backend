// Phase 7 — Fleet Change Indicator
//
// Glanceable floating badge that pulses for ~9s when the city's weather
// picture shifts. Driven by the `FLEET_CHANGE_SUMMARY` WS event (separate
// from COMMAND_CENTER_DELTA for clarity).

import React, { useEffect, useRef, useState } from 'react';
import { Activity, ArrowUp, ArrowDown } from 'lucide-react';

const PULSE_DURATION_MS = 9000;

/**
 * @param {Object} change — last received summary
 *   { timestamp, summary: { cells_updated, cells_escalated, cells_deescalated },
 *     breakdown: [ { cell_id, from, to, direction } ] }
 */
export const FleetChangeIndicator = ({ change }) => {
  const [visible, setVisible] = useState(false);
  const [tooltipOpen, setTooltipOpen] = useState(false);
  const timerRef = useRef(null);
  const lastTsRef = useRef(null);

  useEffect(() => {
    if (!change || !change.timestamp) return;
    if (change.timestamp === lastTsRef.current) return;
    lastTsRef.current = change.timestamp;
    setVisible(true);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setVisible(false), PULSE_DURATION_MS);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [change]);

  if (!visible || !change) return null;

  const summary = change.summary || {};
  const updated = summary.cells_updated || 0;
  const escalated = summary.cells_escalated || 0;
  const deescalated = summary.cells_deescalated || 0;

  // Color band: rose if anything escalated, amber if only de-escalations,
  // emerald-tinted if neutral updates only.
  let tone = 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200';
  if (escalated > 0) {
    tone = 'border-rose-500/50 bg-rose-500/15 text-rose-100';
  } else if (deescalated > 0) {
    tone = 'border-amber-500/40 bg-amber-500/10 text-amber-200';
  }

  return (
    <div
      data-testid="fleet-change-indicator"
      className={`absolute top-3 right-3 z-30 px-3 py-1.5 rounded-full border backdrop-blur shadow-lg ${tone} flex items-center gap-2 cursor-default animate-fade-in`}
      style={{ animation: 'fleetPulse 1.6s ease-in-out infinite' }}
      onMouseEnter={() => setTooltipOpen(true)}
      onMouseLeave={() => setTooltipOpen(false)}
    >
      <Activity className="h-3.5 w-3.5 animate-pulse" />
      <span className="text-[11px] font-semibold tracking-wide">
        {updated} zone{updated === 1 ? '' : 's'} updated
        {escalated > 0 && (
          <>
            {' · '}
            <span className="inline-flex items-center gap-0.5">
              {escalated} <ArrowUp className="h-3 w-3 inline" /> HIGH risk
            </span>
          </>
        )}
        {escalated === 0 && deescalated > 0 && (
          <>
            {' · '}
            <span className="inline-flex items-center gap-0.5">
              {deescalated} <ArrowDown className="h-3 w-3 inline" /> calmer
            </span>
          </>
        )}
      </span>

      {tooltipOpen && Array.isArray(change.breakdown) && change.breakdown.length > 0 && (
        <div
          data-testid="fleet-change-tooltip"
          className="absolute right-0 top-full mt-2 w-[260px] rounded-md border border-slate-700 bg-slate-900/95 p-2 backdrop-blur shadow-xl"
        >
          {change.breakdown.map((b, i) => (
            <div
              key={`${b.cell_id}-${i}`}
              className="flex items-center justify-between text-[10px] py-0.5 font-mono"
            >
              <span className="text-slate-400">{b.cell_id}</span>
              <span
                className={
                  b.direction === 'up'
                    ? 'text-rose-300'
                    : b.direction === 'down'
                    ? 'text-amber-200'
                    : 'text-emerald-300'
                }
              >
                {(b.from || 'low').toUpperCase()} → {(b.to || 'low').toUpperCase()}
              </span>
            </div>
          ))}
        </div>
      )}

      <style>{`
        @keyframes fleetPulse {
          0%, 100% { box-shadow: 0 0 0 0 currentColor; opacity: 1; }
          50%      { box-shadow: 0 0 0 6px transparent; opacity: 0.85; }
        }
        .animate-fade-in { animation: ccFadeIn 0.4s ease-out; }
        @keyframes ccFadeIn { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }
      `}</style>
    </div>
  );
};
