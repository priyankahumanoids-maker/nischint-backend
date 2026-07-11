import React, { useEffect, useState, useRef } from 'react';
import { AlertTriangle, MapPin, Phone, Eye, CheckCircle, Brain, X, Loader2, Shield } from 'lucide-react';

/* Inject alert card animations once */
if (typeof document !== 'undefined' && !document.getElementById('sos-alert-styles')) {
  const s = document.createElement('style');
  s.id = 'sos-alert-styles';
  s.textContent = `
    @keyframes slideInRight{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}
    @keyframes sosGlow{0%,100%{box-shadow:0 0 20px rgba(239,68,68,0.3),inset 0 0 20px rgba(239,68,68,0.05)}50%{box-shadow:0 0 40px rgba(239,68,68,0.5),inset 0 0 30px rgba(239,68,68,0.1)}}
    @keyframes sosPulse{0%,100%{opacity:1}50%{opacity:0.6}}
    .sos-alert-card{animation:slideInRight 0.4s cubic-bezier(0.16,1,0.3,1),sosGlow 2s ease-in-out infinite}
    .sos-pulse-dot{animation:sosPulse 1s ease-in-out infinite}
  `;
  document.head.appendChild(s);
}

const PRIORITY_COLORS = {
  1: 'text-red-400',
  2: 'text-amber-400',
  3: 'text-blue-400',
};

export const SOSAlertCard = ({
  alert,
  aiSuggestions,
  aiLoading,
  onTrackLive,
  onCallGuardian,
  onAcknowledge,
  onDismiss,
}) => {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const timerRef = useRef(null);

  useEffect(() => {
    timerRef.current = setInterval(() => setElapsedSeconds(s => s + 1), 1000);
    return () => clearInterval(timerRef.current);
  }, []);

  if (!alert) return null;

  const riskScore = alert.risk_score || alert.data?.risk_score || 7.6;
  const userName = alert.user_name || alert.data?.user_name || 'Unknown';
  const lat = alert.lat || alert.data?.lat;
  const lng = alert.lng || alert.data?.lng;
  const riskLevel = riskScore >= 7 ? 'HIGH' : riskScore >= 4 ? 'MODERATE' : 'LOW';
  const riskColor = riskScore >= 7 ? 'text-red-400' : riskScore >= 4 ? 'text-amber-400' : 'text-emerald-400';

  const formatElapsed = (s) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
  };

  return (
    <div
      className="sos-alert-card fixed top-20 right-4 w-[380px] z-[2000] bg-slate-900/95 backdrop-blur-xl rounded-xl border border-red-500/40 overflow-hidden"
      data-testid="sos-alert-card"
    >
      {/* Red pulse bar at top */}
      <div className="h-1 bg-gradient-to-r from-red-600 via-red-400 to-red-600 sos-pulse-dot" />

      {/* Header */}
      <div className="px-4 py-3 bg-red-500/10 border-b border-red-500/20 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-red-500/20 flex items-center justify-center">
            <AlertTriangle className="w-4.5 h-4.5 text-red-400 sos-pulse-dot" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-red-400 tracking-wide" data-testid="sos-alert-title">SOS ALERT</h3>
            <p className="text-[10px] text-slate-400">{formatElapsed(elapsedSeconds)} ago</p>
          </div>
        </div>
        <button
          onClick={onDismiss}
          className="w-7 h-7 rounded-lg bg-slate-800 border border-slate-700/50 flex items-center justify-center text-slate-500 hover:text-white hover:bg-slate-700 transition-colors"
          data-testid="sos-alert-dismiss"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* User Details */}
      <div className="px-4 py-3 border-b border-slate-700/30">
        <div className="flex items-center justify-between mb-2">
          <div>
            <p className="text-base font-bold text-white" data-testid="sos-alert-user">{userName}</p>
            {lat && lng && (
              <div className="flex items-center gap-1 mt-0.5">
                <MapPin className="w-3 h-3 text-slate-500" />
                <span className="text-[10px] text-slate-400">
                  {Number(lat).toFixed(4)}, {Number(lng).toFixed(4)}
                </span>
              </div>
            )}
          </div>
          <div className="text-right">
            <p className="text-[9px] text-slate-500 uppercase">Risk Score</p>
            <div className="flex items-center gap-1.5">
              <span className={`text-2xl font-bold font-mono ${riskColor}`}>
                {riskScore.toFixed(1)}
              </span>
              <span className={`text-[9px] font-bold uppercase ${riskColor}`}>{riskLevel}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="px-4 py-3 border-b border-slate-700/30 flex gap-2">
        <button
          onClick={onTrackLive}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-blue-500/15 border border-blue-500/30 text-blue-400 text-xs font-semibold hover:bg-blue-500/25 transition-colors"
          data-testid="sos-track-live-btn"
        >
          <Eye className="w-3.5 h-3.5" />
          Track Live
        </button>
        <button
          onClick={onCallGuardian}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-amber-500/15 border border-amber-500/30 text-amber-400 text-xs font-semibold hover:bg-amber-500/25 transition-colors"
          data-testid="sos-call-guardian-btn"
        >
          <Phone className="w-3.5 h-3.5" />
          Call Guardian
        </button>
        <button
          onClick={onAcknowledge}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 text-xs font-semibold hover:bg-emerald-500/25 transition-colors"
          data-testid="sos-acknowledge-btn"
        >
          <CheckCircle className="w-3.5 h-3.5" />
          Acknowledge
        </button>
      </div>

      {/* AI Reasoning Panel */}
      <div className="px-4 py-3">
        <div className="flex items-center gap-1.5 mb-2">
          <Brain className="w-3.5 h-3.5 text-purple-400" />
          <span className="text-[10px] font-semibold text-slate-300 uppercase tracking-wider">AI Reasoning</span>
          {aiSuggestions?.source === 'ai' && (
            <span className="text-[8px] px-1.5 py-0.5 rounded bg-purple-500/15 text-purple-400 border border-purple-500/30">GPT-5.2</span>
          )}
        </div>
        {aiLoading ? (
          <div className="flex items-center gap-2 py-3">
            <Loader2 className="w-4 h-4 text-purple-400 animate-spin" />
            <span className="text-[10px] text-slate-500">Generating response...</span>
          </div>
        ) : aiSuggestions?.actions ? (
          <div className="space-y-1.5">
            {aiSuggestions.actions.map((action, i) => (
              <div
                key={i}
                className="flex items-start gap-2 px-2.5 py-2 rounded-lg bg-slate-800/60 border border-slate-700/30"
                data-testid={`ai-action-${i}`}
              >
                <Shield className={`w-3 h-3 mt-0.5 shrink-0 ${PRIORITY_COLORS[action.priority] || 'text-slate-400'}`} />
                <span className="text-[11px] text-slate-300">{action.action}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="space-y-1.5">
            <div className="flex items-start gap-2 px-2.5 py-2 rounded-lg bg-slate-800/60 border border-slate-700/30">
              <Shield className="w-3 h-3 mt-0.5 text-red-400" />
              <span className="text-[11px] text-slate-300">Contact guardians immediately</span>
            </div>
            <div className="flex items-start gap-2 px-2.5 py-2 rounded-lg bg-slate-800/60 border border-slate-700/30">
              <Shield className="w-3 h-3 mt-0.5 text-amber-400" />
              <span className="text-[11px] text-slate-300">Start live location monitoring</span>
            </div>
            <div className="flex items-start gap-2 px-2.5 py-2 rounded-lg bg-slate-800/60 border border-slate-700/30">
              <Shield className="w-3 h-3 mt-0.5 text-blue-400" />
              <span className="text-[11px] text-slate-300">Notify nearby trusted contacts</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
