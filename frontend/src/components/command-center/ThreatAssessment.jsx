import React, { useState, useEffect, useRef } from 'react';
import api from '../../api';
import { Shield, MapPin, Users, AlertTriangle, RefreshCw } from 'lucide-react';

const THREAT_COLORS = {
  CRITICAL: { bg: 'bg-red-500/15', border: 'border-red-500/40', text: 'text-red-400', badge: 'bg-red-500', dot: 'bg-red-400' },
  HIGH: { bg: 'bg-orange-500/15', border: 'border-orange-500/40', text: 'text-orange-400', badge: 'bg-orange-500', dot: 'bg-orange-400' },
  MODERATE: { bg: 'bg-amber-500/15', border: 'border-amber-500/40', text: 'text-amber-400', badge: 'bg-amber-500', dot: 'bg-amber-400' },
  SAFE: { bg: 'bg-emerald-500/15', border: 'border-emerald-500/40', text: 'text-emerald-400', badge: 'bg-emerald-500', dot: 'bg-emerald-400' },
};

export const ThreatAssessment = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [displayedText, setDisplayedText] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const prevSummaryRef = useRef('');
  const typingRef = useRef(null);

  const fetchAssessment = async () => {
    try {
      const res = await api.get('/guardian-ai/insights/threat-assessment');
      if (res?.data) {
        setData(res.data);
        // Trigger typing animation only if summary changed
        if (res.data.summary !== prevSummaryRef.current) {
          prevSummaryRef.current = res.data.summary;
          animateTyping(res.data.summary);
        }
      }
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  };

  const animateTyping = (text) => {
    if (typingRef.current) clearInterval(typingRef.current);
    setIsTyping(true);
    setDisplayedText('');
    let i = 0;
    typingRef.current = setInterval(() => {
      if (i < text.length) {
        setDisplayedText(text.slice(0, i + 1));
        i++;
      } else {
        clearInterval(typingRef.current);
        setIsTyping(false);
      }
    }, 12);
  };

  useEffect(() => {
    fetchAssessment();
    const iv = setInterval(fetchAssessment, 90000);
    return () => {
      clearInterval(iv);
      if (typingRef.current) clearInterval(typingRef.current);
    };
  }, []);

  if (loading && !data) return null;

  const tc = THREAT_COLORS[data?.threat_level] || THREAT_COLORS.SAFE;

  return (
    <div
      className="rounded-xl bg-slate-900 border border-slate-800 overflow-hidden h-full flex flex-col"
      data-testid="threat-assessment-panel"
    >
      {/* Header */}
      <div className="px-3 py-2 border-b border-slate-700/50 flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Shield className="w-3.5 h-3.5 text-cyan-400" />
          <span className="text-[10px] font-bold uppercase tracking-wider text-cyan-300">Threat Assessment</span>
        </div>
        <span className="text-[7px] text-slate-600">Powered by Guardian AI Engine</span>
      </div>

      {/* Threat Level Badge */}
      <div className={`mx-3 mt-2.5 px-3 py-1.5 rounded-lg ${tc.bg} border ${tc.border} flex items-center justify-between`} data-testid="threat-level-badge">
        <span className="text-[9px] text-slate-400 uppercase">Threat Level</span>
        <div className="flex items-center gap-1.5">
          <span className={`w-2 h-2 rounded-full ${tc.dot} animate-pulse`} />
          <span className={`text-xs font-bold font-mono ${tc.text}`}>{data?.threat_level || 'SAFE'}</span>
        </div>
      </div>

      {/* Narrative */}
      <div className="px-3 py-2.5">
        <p className="text-[10px] text-slate-300 leading-relaxed min-h-[36px]" data-testid="threat-narrative">
          {displayedText || data?.summary || ''}
          {isTyping && <span className="inline-block w-[2px] h-3 bg-cyan-400 ml-0.5 animate-pulse" />}
        </p>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-3 gap-px mx-3 mb-2.5 bg-slate-700/30 rounded-lg overflow-hidden">
        <StatCell icon={<MapPin className="w-3 h-3 text-orange-400" />} label="Zones" value={data?.zones_escalating ?? 0} />
        <StatCell icon={<Users className="w-3 h-3 text-purple-400" />} label="Users" value={data?.users_anomaly ?? 0} />
        <StatCell icon={<AlertTriangle className="w-3 h-3 text-amber-400" />} label="Incidents" value={data?.recent_incidents ?? 0} />
      </div>

      {/* Recommended Action */}
      {data?.recommended_action && (
        <div className="mx-3 mb-2.5 px-2.5 py-1.5 rounded-lg bg-slate-800/50 border border-slate-700/40">
          <p className="text-[8px] text-slate-500 uppercase mb-0.5">Recommended</p>
          <p className="text-[9px] text-slate-300" data-testid="threat-recommendation">{data.recommended_action}</p>
        </div>
      )}

      {/* Refresh indicator */}
      <div className="px-3 pb-2 flex items-center justify-between">
        <span className="text-[7px] text-slate-600">
          {data?.generated_at ? `Updated ${new Date(data.generated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : ''}
        </span>
        <RefreshCw className={`w-2.5 h-2.5 text-slate-600 ${loading ? 'animate-spin' : ''}`} />
      </div>
    </div>
  );
};

const StatCell = ({ icon, label, value }) => (
  <div className="bg-slate-800/40 px-2.5 py-1.5 text-center">
    <div className="flex items-center justify-center gap-1 mb-0.5">
      {icon}
      <span className="text-sm font-bold font-mono text-white">{value}</span>
    </div>
    <p className="text-[7px] text-slate-500 uppercase">{label}</p>
  </div>
);
