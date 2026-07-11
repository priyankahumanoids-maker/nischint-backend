import React from 'react';
import { Activity, Radio, AlertTriangle, Users, MapPin, Shield, Volume2, VolumeX, BellRing, Wifi, WifiOff } from 'lucide-react';

/* Inject flash CSS once */
if (typeof document !== 'undefined' && !document.getElementById('cc-header-flash')) {
  const s = document.createElement('style');
  s.id = 'cc-header-flash';
  s.textContent = `
    @keyframes ccHeaderFlash{
      0%{background-color:#0f172a;box-shadow:none}
      8%{background-color:#991b1b;box-shadow:inset 0 0 40px rgba(239,68,68,.5),0 0 30px rgba(239,68,68,.3)}
      20%{background-color:#7f1d1d;box-shadow:inset 0 0 30px rgba(239,68,68,.35)}
      50%{background-color:#450a0a;box-shadow:inset 0 0 20px rgba(239,68,68,.2)}
      100%{background-color:#0f172a;box-shadow:none}
    }
    .cc-flash{animation:ccHeaderFlash 1s ease-out}
    @keyframes ccBadgePulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.6;transform:scale(1.15)}}
    .cc-badge-pulse{animation:ccBadgePulse 1.2s ease-in-out infinite}
  `;
  document.head.appendChild(s);
}

const HeaderStat = ({ icon: Icon, label, value, color = 'teal', pulse }) => (
  <div className="flex items-center gap-2.5 px-4 py-2 rounded-lg bg-slate-800/60 border border-slate-700/50" data-testid={`cc-stat-${label.toLowerCase().replace(/\s+/g, '-')}`}>
    <div className={`relative w-8 h-8 rounded-md bg-${color}-500/20 flex items-center justify-center`}>
      <Icon className={`w-4 h-4 text-${color}-400`} />
      {pulse && <span className={`absolute -top-0.5 -right-0.5 w-2.5 h-2.5 bg-${color}-400 rounded-full animate-ping`} />}
    </div>
    <div>
      <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`text-lg font-bold text-${color}-400 leading-tight`}>{value}</p>
    </div>
  </div>
);

export const CommandCenterHeader = ({ metrics, incidents, guardianSessions, flashing, newCriticalCount, alertsMuted, onToggleMute, demoMode, onToggleDemo, wsConnected }) => {
  const sosCount = metrics?.emergency_activity?.last_1h?.sos_triggers || 0;
  const aiAlerts = metrics?.ai_safety?.risk_spikes || 0;
  const activeGuardians = guardianSessions || 0;
  const activeIncidents = incidents?.length || 0;

  return (
    <div className={`bg-slate-900 border-b border-slate-700/50 px-6 flex items-center justify-between ${flashing ? 'cc-flash' : ''}`} data-testid="cc-header">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2.5">
          <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-red-500/30 to-orange-500/30 flex items-center justify-center border border-red-500/30">
            <Shield className="w-5 h-5 text-red-400" />
          </div>
          <div>
            <h1 className="text-base font-bold text-white tracking-tight">NISCHINT Command Center</h1>
            <div className="flex items-center gap-2.5">
              <div className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                <span className="text-[10px] text-emerald-400 font-medium">LIVE</span>
              </div>
              <div className="flex items-center gap-1" data-testid="cc-ws-status">
                {wsConnected ? (
                  <>
                    <Wifi className="w-3 h-3 text-cyan-400" />
                    <span className="text-[9px] text-cyan-400 font-medium">WS</span>
                  </>
                ) : (
                  <>
                    <WifiOff className="w-3 h-3 text-slate-500" />
                    <span className="text-[9px] text-slate-500">WS</span>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
        {newCriticalCount > 0 && (
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-red-600/30 border border-red-500/50 cc-badge-pulse" data-testid="cc-new-critical-badge">
            <BellRing className="w-3.5 h-3.5 text-red-400" />
            <span className="text-[10px] font-bold text-red-300">{newCriticalCount} NEW CRITICAL</span>
          </div>
        )}
      </div>

      <div className="flex items-center gap-3">
        <HeaderStat icon={Radio} label="Active SOS" value={sosCount} color={sosCount > 0 ? 'red' : 'slate'} pulse={sosCount > 0} />
        <HeaderStat icon={AlertTriangle} label="AI Alerts" value={aiAlerts} color={aiAlerts > 0 ? 'amber' : 'slate'} />
        <HeaderStat icon={Users} label="Guardians" value={activeGuardians} color="teal" />
        <HeaderStat icon={MapPin} label="Incidents" value={activeIncidents} color={activeIncidents > 0 ? 'orange' : 'slate'} />
        <HeaderStat icon={Activity} label="Uptime" value={`${Math.floor((metrics?.uptime_seconds || 0) / 60)}m`} color="blue" />
        <button onClick={onToggleMute} className="w-8 h-8 rounded-lg bg-slate-800/60 border border-slate-700/50 flex items-center justify-center hover:bg-slate-700/60 transition-colors" data-testid="cc-toggle-mute" title={alertsMuted ? 'Unmute alerts' : 'Mute alerts'}>
          {alertsMuted ? <VolumeX className="w-4 h-4 text-red-400" /> : <Volume2 className="w-4 h-4 text-slate-400" />}
        </button>
        <button
          onClick={onToggleDemo}
          className={`px-3 py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-all border flex items-center gap-1.5 ${
            demoMode
              ? 'bg-amber-500/20 text-amber-400 border-amber-500/50 animate-pulse'
              : 'bg-slate-800/60 text-slate-400 border-slate-700/50 hover:bg-slate-700/60 hover:text-amber-400'
          }`}
          data-testid="cc-demo-toggle"
          title={demoMode ? 'Stop Demo Mode' : 'Start Demo Mode'}
        >
          <Activity className="w-3.5 h-3.5" />
          {demoMode ? 'DEMO LIVE' : 'DEMO'}
        </button>
      </div>
    </div>
  );
};
