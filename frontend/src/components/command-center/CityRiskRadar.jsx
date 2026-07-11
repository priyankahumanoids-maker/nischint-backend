import React from 'react';
import { Radio, TrendingUp, AlertTriangle, ShieldAlert } from 'lucide-react';

export const CityRiskRadar = ({ heatmapData = [] }) => {
  const critical = heatmapData.filter(c => c.risk_level === 'CRITICAL').length;
  const high = heatmapData.filter(c => c.risk_level === 'HIGH').length;
  const moderate = heatmapData.filter(c => c.risk_level === 'MODERATE').length;
  const rising = heatmapData.filter(c => c.risk_score > 5.5).length;

  // Find top area (highest composite score)
  const sorted = [...heatmapData].sort((a, b) => (b.risk_score || 0) - (a.risk_score || 0));
  const topZone = sorted[0];

  return (
    <div
      className="rounded-xl bg-slate-900 border border-slate-800 p-3 h-full flex flex-col"
      data-testid="city-risk-radar"
    >
      <div className="flex items-center gap-1.5 mb-2.5">
        <div className="w-2 h-2 rounded-full bg-teal-400 animate-pulse" />
        <span className="text-[10px] font-bold uppercase tracking-wider text-teal-300">City Risk Radar</span>
      </div>

      <div className="space-y-1.5 mb-2.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <ShieldAlert className="w-3 h-3 text-red-400" />
            <span className="text-[10px] text-slate-400">Critical zones</span>
          </div>
          <span className="text-xs font-bold font-mono text-red-400">{critical}</span>
        </div>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <AlertTriangle className="w-3 h-3 text-orange-400" />
            <span className="text-[10px] text-slate-400">High-risk zones</span>
          </div>
          <span className="text-xs font-bold font-mono text-orange-400">{high}</span>
        </div>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <TrendingUp className="w-3 h-3 text-amber-400" />
            <span className="text-[10px] text-slate-400">Rising zones</span>
          </div>
          <span className="text-xs font-bold font-mono text-amber-400">{rising}</span>
        </div>
      </div>

      {topZone && (
        <div className="border-t border-slate-700/50 pt-2">
          <p className="text-[9px] text-slate-500 uppercase mb-1">Top Area</p>
          <p className="text-[11px] text-white font-semibold">
            Zone {topZone.grid_id || 'A1'}
          </p>
          <div className="flex items-center gap-1 mt-0.5">
            <TrendingUp className="w-2.5 h-2.5 text-red-400" />
            <span className="text-[10px] text-red-400 font-mono">
              Risk: {(topZone.risk_score || 0).toFixed(1)}/10
            </span>
          </div>
        </div>
      )}

      <p className="text-[7px] text-slate-600 mt-2 text-right">Powered by Guardian AI Engine</p>
    </div>
  );
};
