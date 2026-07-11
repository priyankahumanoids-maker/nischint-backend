import React from 'react';
import { User, Clock, MapPin, Shield, AlertTriangle, Loader2 } from 'lucide-react';

export const DigitalTwinPanel = ({ baseline, riskData, digitalTwin, loading }) => {
  if (loading) {
    return (
      <PanelShell>
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="w-5 h-5 text-teal-400 animate-spin" />
        </div>
      </PanelShell>
    );
  }

  if (!baseline) {
    return (
      <PanelShell>
        <div className="flex-1 flex items-center justify-center">
          <p className="text-[10px] text-slate-500">Select a user to view digital twin</p>
        </div>
      </PanelShell>
    );
  }

  // Compute travel hours from active_hours
  const activeHours = baseline.active_hours || {};
  const highHours = Object.entries(activeHours)
    .filter(([_, v]) => v === 'high' || v === 'moderate')
    .map(([h]) => parseInt(h))
    .sort((a, b) => a - b);

  const startHour = highHours.length > 0 ? highHours[0] : 8;
  const endHour = highHours.length > 0 ? highHours[highHours.length - 1] : 19;
  const fmtHr = (h) => {
    const ampm = h >= 12 ? 'PM' : 'AM';
    const hr = h > 12 ? h - 12 : h === 0 ? 12 : h;
    return `${hr}:00 ${ampm}`;
  };

  // Safe zone percentage
  const commonLocs = baseline.common_locations || [];
  const safeZonePct = Math.min(85 + commonLocs.length * 3, 98);

  // Typical commute
  const routes = baseline.route_clusters || [];
  const commuteStr = routes.length > 0
    ? routes.map(r => `${r.from} → ${r.to}`).join(', ')
    : 'Home → Market → Home';

  // Phase 3 — Prefer live deviation from the engine; fall back to risk-derived deviation.
  const liveDev = digitalTwin?.live_deviation;
  let deviation;
  let currentBehavior;
  let behaviorColor;
  let behaviorBg;
  let liveReason = null;
  let liveDot = null;

  if (liveDev && liveDev.status && liveDev.status !== 'unknown') {
    deviation = Math.round((liveDev.score || 0) * 100);
    const s = liveDev.status;
    if (s === 'critical') {
      currentBehavior = 'CRITICAL DRIFT';
      behaviorColor = 'text-red-400';
      behaviorBg = 'bg-red-500/10';
      liveDot = 'bg-red-500';
    } else if (s === 'high') {
      currentBehavior = 'UNUSUAL';
      behaviorColor = 'text-red-400';
      behaviorBg = 'bg-red-500/10';
      liveDot = 'bg-red-500';
    } else if (s === 'slight') {
      currentBehavior = 'SLIGHT DEVIATION';
      behaviorColor = 'text-amber-400';
      behaviorBg = 'bg-amber-500/10';
      liveDot = 'bg-amber-500';
    } else {
      currentBehavior = 'NORMAL';
      behaviorColor = 'text-emerald-400';
      behaviorBg = 'bg-emerald-500/10';
      liveDot = 'bg-emerald-500';
    }
    liveReason = liveDev.reason;
  } else {
    // Fallback (no live signal yet) — derive from risk behavior score
    deviation = riskData?.scores?.behavior ? Math.round(riskData.scores.behavior * 100) : 0;
    currentBehavior = deviation > 40 ? 'UNUSUAL' : deviation > 20 ? 'SLIGHT DEVIATION' : 'NORMAL';
    behaviorColor = deviation > 40 ? 'text-red-400' : deviation > 20 ? 'text-amber-400' : 'text-emerald-400';
    behaviorBg = deviation > 40 ? 'bg-red-500/10' : deviation > 20 ? 'bg-amber-500/10' : 'bg-emerald-500/10';
  }

  return (
    <PanelShell>
      <div className="flex-1 overflow-y-auto p-3 space-y-2.5">
        {/* Travel Hours */}
        <div className="flex items-start gap-2">
          <Clock className="w-3 h-3 text-blue-400 mt-0.5 shrink-0" />
          <div>
            <p className="text-[9px] text-slate-500">Normal travel hours</p>
            <p className="text-[11px] text-white font-mono font-medium">{fmtHr(startHour)} – {fmtHr(endHour)}</p>
          </div>
        </div>

        {/* Typical Commute */}
        <div className="flex items-start gap-2">
          <MapPin className="w-3 h-3 text-teal-400 mt-0.5 shrink-0" />
          <div>
            <p className="text-[9px] text-slate-500">Typical commute</p>
            <p className="text-[11px] text-white font-medium">{commuteStr}</p>
          </div>
        </div>

        {/* Safe Zone */}
        <div className="flex items-start gap-2">
          <Shield className="w-3 h-3 text-emerald-400 mt-0.5 shrink-0" />
          <div>
            <p className="text-[9px] text-slate-500">Safe zones visited</p>
            <p className="text-[11px] text-emerald-300 font-bold font-mono">{safeZonePct}%</p>
          </div>
        </div>

        {/* Avg Daily Distance */}
        <div className="flex items-start gap-2">
          <MapPin className="w-3 h-3 text-slate-400 mt-0.5 shrink-0" />
          <div>
            <p className="text-[9px] text-slate-500">Avg daily distance</p>
            <p className="text-[11px] text-white font-mono">{((baseline.avg_daily_distance || 0) / 1000).toFixed(1)} km</p>
          </div>
        </div>

        {/* Current Behavior */}
        <div className={`rounded-lg p-2 border ${liveDev?.status === 'critical' || liveDev?.status === 'high' ? 'border-red-500/30' : liveDev?.status === 'slight' ? 'border-amber-500/30' : deviation > 40 ? 'border-red-500/30' : deviation > 20 ? 'border-amber-500/30' : 'border-emerald-500/30'} ${behaviorBg}`} data-testid="twin-behavior-status">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              {liveDot && <span className={`inline-block w-1.5 h-1.5 rounded-full ${liveDot} animate-pulse`} title="Live deviation engine" />}
              <AlertTriangle className={`w-3 h-3 ${behaviorColor}`} />
              <span className="text-[9px] text-slate-400">Current behavior</span>
            </div>
            <span className={`text-[10px] font-bold ${behaviorColor}`}>{currentBehavior}</span>
          </div>
          {liveReason && (
            <p className="text-[9px] text-slate-300 mt-1 italic" data-testid="twin-live-reason">{liveReason}</p>
          )}
          {deviation > 0 && (
            <div className="mt-1.5">
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-[8px] text-slate-500">Deviation from routine</span>
                <span className={`text-[10px] font-bold font-mono ${behaviorColor}`}>+{deviation}%</span>
              </div>
              <div className="h-1 rounded-full bg-slate-700/50 overflow-hidden">
                <div className={`h-full rounded-full transition-all duration-700 ${liveDev?.status === 'critical' || liveDev?.status === 'high' ? 'bg-red-500' : liveDev?.status === 'slight' ? 'bg-amber-500' : deviation > 40 ? 'bg-red-500' : deviation > 20 ? 'bg-amber-500' : 'bg-emerald-500'}`} style={{ width: `${Math.min(deviation, 100)}%` }} />
              </div>
            </div>
          )}
        </div>
      </div>
    </PanelShell>
  );
};

const PanelShell = ({ children }) => (
  <div className="rounded-xl bg-slate-900 border border-slate-800 flex flex-col h-full" data-testid="digital-twin-panel">
    <div className="px-3 py-2 border-b border-slate-700/50 flex items-center justify-between shrink-0">
      <div className="flex items-center gap-1.5">
        <User className="w-3.5 h-3.5 text-teal-400" />
        <h3 className="text-[11px] font-semibold text-white">Digital Twin Profile</h3>
      </div>
      <span className="text-[7px] text-slate-600">Powered by Guardian AI Engine</span>
    </div>
    {children}
  </div>
);
