import React from 'react';
import { AlertTriangle, TrendingUp, Cpu, Zap } from 'lucide-react';

const AlertItem = ({ alert }) => {
  const colors = {
    critical: 'text-red-400 bg-red-500/10 border-red-500/20',
    high: 'text-orange-400 bg-orange-500/10 border-orange-500/20',
    medium: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
    low: 'text-slate-400 bg-slate-500/10 border-slate-500/20',
  };
  const c = colors[alert.severity] || colors.low;

  return (
    <div className={`p-2.5 rounded-md border ${c}`} data-testid="cc-ai-alert-item">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] uppercase tracking-wider font-semibold">{alert.prediction_type || alert.type || 'risk'}</span>
        <span className="text-[10px] opacity-60">{alert.score ? `${(alert.score * 100).toFixed(0)}%` : ''}</span>
      </div>
      <p className="text-xs opacity-80 truncate">{alert.device_identifier || alert.explanation || alert.message || 'Signal detected'}</p>
    </div>
  );
};

export const AISafetyAlerts = ({ predictiveAlerts = [], riskSpikes = 0, heatmapAlerts = 0, anomalies = 0 }) => (
  <div className="bg-slate-800/40 rounded-lg border border-slate-700/50 flex flex-col h-full" data-testid="cc-ai-alerts">
    <div className="px-4 py-3 border-b border-slate-700/50 flex items-center gap-2 shrink-0">
      <Cpu className="w-4 h-4 text-violet-400" />
      <h3 className="text-sm font-semibold text-white">AI Safety Alerts</h3>
    </div>
    <div className="flex gap-2 px-3 pt-3">
      <div className="flex-1 text-center p-2 rounded bg-red-500/10 border border-red-500/20">
        <TrendingUp className="w-3.5 h-3.5 text-red-400 mx-auto mb-0.5" />
        <p className="text-lg font-bold text-red-400">{riskSpikes}</p>
        <p className="text-[9px] text-slate-500">Risk Spikes</p>
      </div>
      <div className="flex-1 text-center p-2 rounded bg-amber-500/10 border border-amber-500/20">
        <Zap className="w-3.5 h-3.5 text-amber-400 mx-auto mb-0.5" />
        <p className="text-lg font-bold text-amber-400">{heatmapAlerts}</p>
        <p className="text-[9px] text-slate-500">Heatmap</p>
      </div>
      <div className="flex-1 text-center p-2 rounded bg-violet-500/10 border border-violet-500/20">
        <AlertTriangle className="w-3.5 h-3.5 text-violet-400 mx-auto mb-0.5" />
        <p className="text-lg font-bold text-violet-400">{anomalies}</p>
        <p className="text-[9px] text-slate-500">Anomalies</p>
      </div>
    </div>
    <div className="flex-1 overflow-y-auto p-3 space-y-1.5">
      {predictiveAlerts.length === 0 ? (
        <p className="text-xs text-slate-500 text-center py-3">No active predictions</p>
      ) : (
        predictiveAlerts.slice(0, 8).map((a, i) => <AlertItem key={i} alert={a} />)
      )}
    </div>
  </div>
);
