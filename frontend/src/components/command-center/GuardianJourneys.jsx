import React from 'react';
import { MapPin, Clock, Shield } from 'lucide-react';

const RISK_COLORS = {
  SAFE: { text: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/20' },
  LOW: { text: 'text-green-400', bg: 'bg-green-500/10', border: 'border-green-500/20' },
  HIGH: { text: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/20' },
  CRITICAL: { text: 'text-red-400', bg: 'bg-red-500/10', border: 'border-red-500/20' },
};

const JourneyItem = ({ journey }) => {
  const risk = RISK_COLORS[journey.risk_level] || RISK_COLORS.SAFE;
  const duration = journey.duration_minutes ? `${Math.round(journey.duration_minutes)}m` : '--';
  const eta = journey.eta_minutes ? `${Math.round(journey.eta_minutes)}m` : '--';

  return (
    <div className={`p-2.5 rounded-md border ${risk.bg} ${risk.border}`} data-testid="cc-journey-item">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-medium text-slate-300 truncate">{journey.user_id?.slice(0, 8) || 'User'}</span>
        <span className={`text-[10px] px-1.5 py-0.5 rounded ${risk.bg} ${risk.text} font-semibold`}>{journey.risk_level || 'SAFE'}</span>
      </div>
      <div className="flex items-center gap-3 text-[10px] text-slate-500">
        <span className="flex items-center gap-0.5"><Clock className="w-2.5 h-2.5" />{duration}</span>
        <span className="flex items-center gap-0.5"><MapPin className="w-2.5 h-2.5" />ETA: {eta}</span>
        {journey.is_idle && <span className="text-amber-400">Idle</span>}
        {journey.route_deviated && <span className="text-red-400">Deviated</span>}
      </div>
    </div>
  );
};

export const GuardianJourneys = ({ journeys = [] }) => (
  <div className="bg-slate-800/40 rounded-lg border border-slate-700/50 flex flex-col h-full" data-testid="cc-guardian-journeys">
    <div className="px-4 py-3 border-b border-slate-700/50 flex items-center justify-between shrink-0">
      <div className="flex items-center gap-2">
        <Shield className="w-4 h-4 text-blue-400" />
        <h3 className="text-sm font-semibold text-white">Guardian Journeys</h3>
      </div>
      <span className="text-[10px] bg-blue-500/20 text-blue-400 px-2 py-0.5 rounded-full font-medium">{journeys.length} active</span>
    </div>
    <div className="flex-1 overflow-y-auto p-3 space-y-1.5">
      {journeys.length === 0 ? (
        <p className="text-xs text-slate-500 text-center py-3">No active journeys</p>
      ) : (
        journeys.map((j, i) => <JourneyItem key={i} journey={j} />)
      )}
    </div>
  </div>
);
