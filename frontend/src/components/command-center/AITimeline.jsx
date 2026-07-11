import React from 'react';
import { Clock, MapPin, AlertTriangle, Shield, Radio, TrendingUp, CheckCircle, Loader2 } from 'lucide-react';

const EVENT_STYLES = {
  zone_entry: { icon: <MapPin className="w-3 h-3" />, color: 'text-blue-400', line: 'bg-blue-500' },
  behavior_anomaly: { icon: <AlertTriangle className="w-3 h-3" />, color: 'text-amber-400', line: 'bg-amber-500' },
  risk_rising: { icon: <TrendingUp className="w-3 h-3" />, color: 'text-orange-400', line: 'bg-orange-500' },
  heatmap_warning: { icon: <Radio className="w-3 h-3" />, color: 'text-red-400', line: 'bg-red-500' },
  ai_alert: { icon: <Shield className="w-3 h-3" />, color: 'text-red-400', line: 'bg-red-500' },
  resolved: { icon: <CheckCircle className="w-3 h-3" />, color: 'text-emerald-400', line: 'bg-emerald-500' },
  default: { icon: <Clock className="w-3 h-3" />, color: 'text-slate-400', line: 'bg-slate-600' },
};

export const AITimeline = ({ riskHistory = [], incidents = [], loading }) => {
  // Build timeline events from risk history + incidents
  const events = [];

  // Add risk events
  riskHistory.slice(0, 8).forEach(e => {
    const score = e.final_risk_score || e.final_score || 0;
    let type = 'default';
    if (score >= 0.7) type = 'ai_alert';
    else if (score >= 0.5) type = 'risk_rising';
    else if (score >= 0.3) type = 'behavior_anomaly';

    events.push({
      type,
      time: e.timestamp,
      label: score >= 0.7
        ? 'AI predictive alert issued'
        : score >= 0.5
          ? 'Risk rising'
          : 'Behavioral anomaly detected',
      score: score,
      factors: e.top_factors || [],
    });
  });

  // Add recent incidents
  incidents.slice(0, 5).forEach(inc => {
    events.push({
      type: inc.status === 'resolved' ? 'resolved' : inc.severity === 'critical' ? 'heatmap_warning' : 'zone_entry',
      time: inc.created_at,
      label: `${(inc.incident_type || '').replace(/_/g, ' ')} — ${inc.senior_name || 'Unknown'}`,
      severity: inc.severity,
    });
  });

  // Sort by time descending
  events.sort((a, b) => new Date(b.time || 0) - new Date(a.time || 0));
  const displayEvents = events.slice(0, 10);

  const fmtTime = (iso) => {
    if (!iso) return '--:--';
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 flex flex-col h-full" data-testid="ai-timeline">
      <div className="px-3 py-2 border-b border-slate-700/50 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-1.5">
          <Clock className="w-3.5 h-3.5 text-cyan-400" />
          <h3 className="text-[11px] font-semibold text-white">AI Timeline</h3>
        </div>
        <span className="text-[7px] text-slate-600">Powered by Guardian AI Engine</span>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-2">
        {loading ? (
          <div className="flex items-center justify-center h-full">
            <Loader2 className="w-4 h-4 text-cyan-400 animate-spin" />
          </div>
        ) : displayEvents.length === 0 ? (
          <p className="text-[10px] text-slate-500 text-center py-4">No recent events</p>
        ) : (
          <div className="relative">
            {/* Vertical line */}
            <div className="absolute left-[5px] top-2 bottom-2 w-[1px] bg-slate-700/60" />

            <div className="space-y-2.5">
              {displayEvents.map((ev, i) => {
                const style = EVENT_STYLES[ev.type] || EVENT_STYLES.default;
                return (
                  <div key={i} className="flex items-start gap-2.5 relative" data-testid={`timeline-event-${i}`}>
                    {/* Dot */}
                    <div className={`w-[11px] h-[11px] rounded-full border-2 border-slate-900 ${style.line} shrink-0 z-10 mt-0.5`} />
                    {/* Content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className={`${style.color}`}>{style.icon}</span>
                        <span className="text-[10px] text-white truncate">{ev.label}</span>
                      </div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-[9px] text-slate-500 font-mono">{fmtTime(ev.time)}</span>
                        {ev.score !== undefined && (
                          <span className={`text-[8px] font-mono ${ev.score >= 0.7 ? 'text-red-400' : ev.score >= 0.5 ? 'text-orange-400' : 'text-amber-400'}`}>
                            risk: {(ev.score * 10).toFixed(1)}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
