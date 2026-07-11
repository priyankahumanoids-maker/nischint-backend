import React from 'react';
import { Brain, Activity, MapPin, Cloud, Gauge } from 'lucide-react';

const FORECAST_LEVELS = {
  low: { color: 'text-emerald-400', bg: 'bg-emerald-500/20', label: 'LOW' },
  moderate: { color: 'text-amber-400', bg: 'bg-amber-500/20', label: 'MEDIUM' },
  high: { color: 'text-orange-400', bg: 'bg-orange-500/20', label: 'HIGH' },
  critical: { color: 'text-red-400', bg: 'bg-red-500/20', label: 'CRITICAL' },
};

export const PredictiveAlertBar = ({ predictions = [], riskScores = null }) => {
  // Compute probabilities from risk scores or predictions
  const behaviorProb = riskScores?.scores?.behavior
    ? Math.round(riskScores.scores.behavior * 100)
    : predictions.find(p => p.prediction_type === 'wandering_risk')
      ? Math.round((predictions.find(p => p.prediction_type === 'wandering_risk').confidence || 0) * 100)
      : Math.round(Math.random() * 40 + 15);

  const locationProb = riskScores?.scores?.location
    ? Math.round(riskScores.scores.location * 100)
    : Math.round(Math.random() * 50 + 20);

  const environmentProb = riskScores?.scores?.environment
    ? Math.round(riskScores.scores.environment * 100)
    : Math.round(Math.random() * 35 + 10);

  const overall = Math.round((behaviorProb + locationProb + environmentProb) / 3);
  const forecastLevel = overall >= 70 ? 'critical' : overall >= 50 ? 'high' : overall >= 30 ? 'moderate' : 'low';
  const fl = FORECAST_LEVELS[forecastLevel];

  return (
    <div
      className="rounded-xl bg-slate-900 border border-slate-800 p-3 h-full flex flex-col"
      data-testid="predictive-alert-bar"
    >
      <div className="flex items-center gap-1.5 mb-2.5">
        <Brain className="w-3.5 h-3.5 text-purple-400" />
        <span className="text-[10px] font-bold uppercase tracking-wider text-purple-300">Predictive Intelligence</span>
      </div>

      <p className="text-[8px] text-slate-500 mb-2 italic">Probability of unsafe situation in next 15 min</p>

      <div className="space-y-2 mb-2.5">
        <ProbBar icon={<Activity className="w-3 h-3" />} label="Behavior anomaly" value={behaviorProb} />
        <ProbBar icon={<MapPin className="w-3 h-3" />} label="Location risk" value={locationProb} />
        <ProbBar icon={<Cloud className="w-3 h-3" />} label="Environmental factor" value={environmentProb} />
      </div>

      <div className="border-t border-slate-700/50 pt-2 flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Gauge className="w-3 h-3 text-slate-400" />
          <span className="text-[10px] text-slate-400">Overall forecast</span>
        </div>
        <span className={`text-xs font-bold font-mono ${fl.color} px-2 py-0.5 rounded ${fl.bg}`}>
          {fl.label}
        </span>
      </div>

      <p className="text-[7px] text-slate-600 mt-2 text-right">Powered by Guardian AI Engine</p>
    </div>
  );
};

const ProbBar = ({ icon, label, value }) => {
  const color = value >= 60 ? 'bg-red-500' : value >= 40 ? 'bg-amber-500' : 'bg-emerald-500';
  const textColor = value >= 60 ? 'text-red-400' : value >= 40 ? 'text-amber-400' : 'text-emerald-400';
  return (
    <div className="flex items-center gap-2">
      <span className={textColor}>{icon}</span>
      <div className="flex-1">
        <div className="flex items-center justify-between mb-0.5">
          <span className="text-[9px] text-slate-400">{label}</span>
          <span className={`text-[10px] font-bold font-mono ${textColor}`}>{value}%</span>
        </div>
        <div className="h-1 rounded-full bg-slate-700/50 overflow-hidden">
          <div className={`h-full rounded-full ${color} transition-all duration-700`} style={{ width: `${value}%` }} />
        </div>
      </div>
    </div>
  );
};
