import React from 'react';
import { Brain, Activity, MapPin, Cpu, Cloud, UserCheck, Loader2 } from 'lucide-react';

const RISK_COLORS = {
  critical: { bar: 'bg-red-500', text: 'text-red-400', glow: 'shadow-red-500/20' },
  high: { bar: 'bg-orange-500', text: 'text-orange-400', glow: 'shadow-orange-500/20' },
  moderate: { bar: 'bg-amber-500', text: 'text-amber-400', glow: 'shadow-amber-500/20' },
  low: { bar: 'bg-emerald-500', text: 'text-emerald-400', glow: 'shadow-emerald-500/20' },
};

const CATEGORY_ICONS = {
  behavior: <Activity className="w-3 h-3" />,
  location: <MapPin className="w-3 h-3" />,
  device: <Cpu className="w-3 h-3" />,
  environment: <Cloud className="w-3 h-3" />,
  response: <UserCheck className="w-3 h-3" />,
};

const CATEGORY_LABELS = {
  behavior: 'Behavioral Pattern',
  location: 'Location Intelligence',
  device: 'Device Reliability',
  environment: 'Environmental Risk',
  response: 'Response Readiness',
};

export const AIReasoningPanel = ({ riskData, loading }) => {
  if (loading) {
    return (
      <PanelShell>
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="w-5 h-5 text-purple-400 animate-spin" />
        </div>
      </PanelShell>
    );
  }

  if (!riskData) {
    return (
      <PanelShell>
        <div className="flex-1 flex items-center justify-center">
          <p className="text-[10px] text-slate-500">Select a user to view AI reasoning</p>
        </div>
      </PanelShell>
    );
  }

  const scores = riskData.scores || {};
  const riskLevel = riskData.risk_level || 'low';
  const rc = RISK_COLORS[riskLevel] || RISK_COLORS.low;
  const confidence = Math.round(
    (1 - Math.abs(0.5 - riskData.final_score) * 0.4) * 100
  );

  return (
    <PanelShell>
      {/* Score Header */}
      <div className="flex items-center justify-between mb-2 px-3 pt-0.5">
        <div>
          <span className={`text-2xl font-bold font-mono ${rc.text}`}>
            {(riskData.final_score * 10).toFixed(1)}
          </span>
          <span className={`text-[9px] uppercase font-bold ml-1.5 ${rc.text}`}>{riskLevel}</span>
        </div>
        <div className="text-right">
          <p className="text-[9px] text-slate-500">Confidence</p>
          <p className="text-xs font-bold font-mono text-slate-300">{confidence}%</p>
        </div>
      </div>

      {/* Factor Breakdown */}
      <div className="flex-1 overflow-y-auto px-3 space-y-1.5">
        <p className="text-[9px] text-slate-500 uppercase font-medium mb-1">Factors detected</p>
        {Object.entries(scores).map(([category, score]) => {
          const s = Math.round(score * 100);
          const factorColor = s >= 60 ? 'bg-red-500' : s >= 40 ? 'bg-amber-500' : 'bg-emerald-500';
          const factorText = s >= 60 ? 'text-red-400' : s >= 40 ? 'text-amber-400' : 'text-emerald-400';
          const matchedFactor = riskData.top_factors?.find(f => f.category === category);

          return (
            <div key={category} className="group" data-testid={`reasoning-factor-${category}`}>
              <div className="flex items-center gap-1.5 mb-0.5">
                <span className={factorText}>{CATEGORY_ICONS[category] || <Brain className="w-3 h-3" />}</span>
                <span className="text-[10px] text-slate-300 flex-1">{CATEGORY_LABELS[category] || category}</span>
                <span className={`text-[10px] font-bold font-mono ${factorText}`}>+{(score).toFixed(2)}</span>
              </div>
              <div className="h-1 rounded-full bg-slate-700/50 overflow-hidden ml-[18px]">
                <div
                  className={`h-full rounded-full ${factorColor} transition-all duration-700`}
                  style={{ width: `${Math.min(s, 100)}%` }}
                />
              </div>
              {matchedFactor && (
                <p className="text-[8px] text-slate-500 ml-[18px] mt-0.5 italic">{matchedFactor.description}</p>
              )}
            </div>
          );
        })}
      </div>
    </PanelShell>
  );
};

const PanelShell = ({ children }) => (
  <div className="rounded-xl bg-slate-900 border border-slate-800 flex flex-col h-full" data-testid="ai-reasoning-panel">
    <div className="px-3 py-2 border-b border-slate-700/50 flex items-center justify-between shrink-0">
      <div className="flex items-center gap-1.5">
        <Brain className="w-3.5 h-3.5 text-purple-400" />
        <h3 className="text-[11px] font-semibold text-white">AI Reasoning</h3>
      </div>
      <span className="text-[7px] text-slate-600">Powered by Guardian AI Engine</span>
    </div>
    {children}
  </div>
);
