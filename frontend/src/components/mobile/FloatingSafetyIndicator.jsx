import React, { useState, useEffect, useCallback } from 'react';
import { Shield, Brain, ChevronUp, ChevronDown } from 'lucide-react';
import api from '../../api';

const RISK_COLORS = {
  critical: { bg: 'bg-red-500/90', text: 'text-white', pulse: 'animate-pulse' },
  high: { bg: 'bg-orange-500/90', text: 'text-white', pulse: 'animate-pulse' },
  moderate: { bg: 'bg-amber-500/90', text: 'text-white', pulse: '' },
  low: { bg: 'bg-emerald-500/90', text: 'text-white', pulse: '' },
};

export default function FloatingSafetyIndicator() {
  const [data, setData] = useState(null);
  const [expanded, setExpanded] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await api.get('/safety-events/user-dashboard');
      setData(res.data);
    } catch { /* silent */ }
  }, []);

  useEffect(() => {
    fetchStatus();
    const iv = setInterval(fetchStatus, 20000);
    return () => clearInterval(iv);
  }, [fetchStatus]);

  if (!data) return null;

  const level = data.risk_level || 'low';
  const style = RISK_COLORS[level] || RISK_COLORS.low;
  const score = ((data.risk_score || 0) * 10).toFixed(1);
  const threat = data.threat_assessment;

  return (
    <div className="fixed top-0 left-0 right-0 z-[100] max-w-[430px] mx-auto" data-testid="floating-safety-indicator">
      <div
        className={`mx-3 mt-1 rounded-2xl ${style.bg} ${style.pulse} backdrop-blur-xl shadow-lg transition-all duration-300 cursor-pointer`}
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center justify-between px-3 py-2">
          <div className="flex items-center gap-2">
            <Shield className={`w-4 h-4 ${style.text}`} />
            <span className={`text-[11px] font-bold uppercase tracking-wide ${style.text}`}>
              {level}
            </span>
            <span className={`text-[10px] font-mono ${style.text} opacity-80`}>
              {score}/10
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            {threat && (
              <span className={`text-[9px] ${style.text} opacity-75 max-w-[120px] truncate`}>
                {threat.summary?.slice(0, 40)}...
              </span>
            )}
            {expanded ? (
              <ChevronUp className={`w-3.5 h-3.5 ${style.text} opacity-70`} />
            ) : (
              <ChevronDown className={`w-3.5 h-3.5 ${style.text} opacity-70`} />
            )}
          </div>
        </div>

        {expanded && (
          <div className="px-3 pb-2.5 border-t border-white/15">
            <div className="flex items-center gap-2 mt-2">
              <Brain className="w-3.5 h-3.5 text-white/80" />
              <span className="text-[10px] text-white/90 leading-snug">
                {threat?.summary || 'No active threat assessment'}
              </span>
            </div>
            {data.session_active && (
              <div className="flex items-center gap-2 mt-1.5">
                <div className="w-1.5 h-1.5 rounded-full bg-teal-300 animate-pulse" />
                <span className="text-[10px] text-white/80">
                  Session active — {data.session?.alert_count || 0} alerts
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
