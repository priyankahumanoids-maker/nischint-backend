import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../api';
import {
  Shield, MapPin, Users, AlertTriangle, ChevronRight,
  Play, Phone, Navigation, Brain, Loader2, RefreshCw, Eye,
} from 'lucide-react';

const RISK_STYLES = {
  critical: { bg: 'bg-red-500/15', border: 'border-red-500/40', text: 'text-red-400', ring: 'ring-red-500/20' },
  high: { bg: 'bg-orange-500/15', border: 'border-orange-500/40', text: 'text-orange-400', ring: 'ring-orange-500/20' },
  moderate: { bg: 'bg-amber-500/15', border: 'border-amber-500/40', text: 'text-amber-400', ring: 'ring-amber-500/20' },
  low: { bg: 'bg-emerald-500/15', border: 'border-emerald-500/40', text: 'text-emerald-400', ring: 'ring-emerald-500/20' },
};

export default function MobileHome() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const mountedRef = React.useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const fetchDashboard = useCallback(async () => {
    try {
      const res = await api.get('/safety-events/user-dashboard');
      if (mountedRef.current) {
        setData(res.data);
        setError(false);
      }
    } catch {
      if (mountedRef.current) setError(true);
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDashboard();
    const iv = setInterval(fetchDashboard, 15000);
    return () => clearInterval(iv);
  }, [fetchDashboard]);

  // Failsafe: if still loading after 5s, force show content
  useEffect(() => {
    const timer = setTimeout(() => {
      if (mountedRef.current && loading) setLoading(false);
    }, 5000);
    return () => clearTimeout(timer);
  }, [loading]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full min-h-[400px]">
        <Loader2 className="w-8 h-8 text-teal-400 animate-spin" />
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[400px] px-6 text-center">
        <AlertTriangle className="w-8 h-8 text-amber-400 mb-3" />
        <p className="text-sm text-white font-medium mb-1">Could not load dashboard</p>
        <p className="text-xs text-slate-500 mb-4">Check your connection and try again</p>
        <button onClick={fetchDashboard} className="px-4 py-2 rounded-full bg-teal-500 text-white text-xs font-medium active:scale-95 transition-transform" data-testid="retry-dashboard-btn">
          <RefreshCw className="w-3.5 h-3.5 inline mr-1.5" /> Retry
        </button>
      </div>
    );
  }

  const rs = RISK_STYLES[data?.risk_level] || RISK_STYLES.low;
  const threat = data?.threat_assessment;

  return (
    <div className="px-4 pt-4 pb-6 space-y-4" data-testid="mobile-home">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-white">Nischint</h1>
          <p className="text-[11px] text-slate-500">Safety Intelligence</p>
        </div>
        <button onClick={fetchDashboard} className="p-2 rounded-full bg-slate-800/50 active:bg-slate-700/50">
          <RefreshCw className={`w-4 h-4 text-slate-400 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Risk Score Card */}
      <div className={`p-4 rounded-2xl ${rs.bg} border ${rs.border} ring-1 ${rs.ring}`} data-testid="risk-score-card">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Shield className={`w-5 h-5 ${rs.text}`} />
            <span className="text-xs text-slate-400 uppercase font-medium">AI Risk Assessment</span>
          </div>
          <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${rs.bg} ${rs.text} border ${rs.border}`}>
            {data?.risk_level || 'safe'}
          </span>
        </div>
        <div className="flex items-end gap-2">
          <span className={`text-4xl font-bold font-mono ${rs.text}`}>
            {((data?.risk_score || 0) * 10).toFixed(1)}
          </span>
          <span className="text-xs text-slate-500 mb-1">/10</span>
        </div>
        <p className="text-[10px] text-slate-500 mt-1">Powered by Guardian AI Engine</p>
      </div>

      {/* Threat Assessment */}
      {threat && (
        <div className="p-3 rounded-2xl bg-slate-800/40 border border-slate-700/40" data-testid="threat-card">
          <div className="flex items-center gap-2 mb-1.5">
            <Brain className="w-4 h-4 text-purple-400" />
            <span className="text-xs font-semibold text-white">Threat Assessment</span>
            <span className={`text-[9px] font-bold ml-auto px-1.5 py-0.5 rounded ${
              threat.level === 'CRITICAL' ? 'bg-red-500/20 text-red-400' :
              threat.level === 'HIGH' ? 'bg-orange-500/20 text-orange-400' :
              'bg-emerald-500/20 text-emerald-400'
            }`}>{threat.level}</span>
          </div>
          <p className="text-[11px] text-slate-400 leading-relaxed">{threat.summary}</p>
        </div>
      )}

      {/* Session Status */}
      <div
        className={`p-3 rounded-2xl border ${data?.session_active
          ? 'bg-teal-500/10 border-teal-500/30'
          : 'bg-slate-800/40 border-slate-700/40'}`}
        data-testid="session-card"
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${data?.session_active ? 'bg-teal-400 animate-pulse' : 'bg-slate-600'}`} />
            <span className="text-xs font-medium text-white">
              {data?.session_active ? 'Session Active' : 'No Active Session'}
            </span>
          </div>
          {data?.session_active ? (
            <button
              onClick={() => navigate('/m/live')}
              className="text-[10px] text-teal-400 font-medium flex items-center gap-1"
            >
              View <ChevronRight className="w-3 h-3" />
            </button>
          ) : (
            <button
              onClick={() => navigate('/m/session')}
              className="px-3 py-1.5 rounded-full bg-teal-500 text-white text-[11px] font-medium flex items-center gap-1 active:scale-95 transition-transform"
              data-testid="start-session-btn"
            >
              <Play className="w-3 h-3" /> Start
            </button>
          )}
        </div>
        {data?.session && (
          <div className="mt-2 flex items-center gap-3 text-[10px] text-slate-400">
            <span>{Math.floor(data.session.duration_seconds / 60)}m active</span>
            <span>{data.session.total_distance_m}m traveled</span>
            <span>{data.session.alert_count} alerts</span>
          </div>
        )}
      </div>

      {/* Quick Actions Grid */}
      <div className="grid grid-cols-2 gap-3" data-testid="quick-actions">
        <QuickAction icon={<Eye className="w-5 h-5 text-cyan-400" />} label="Live Map" sub="Guardian tracking" onClick={() => navigate('/m/guardian-live-map')} testId="qa-live-map" />
        <QuickAction icon={<Navigation className="w-5 h-5 text-blue-400" />} label="Safe Route" sub="AI-powered routing" onClick={() => navigate('/m/safe-route')} testId="qa-safe-route" />
        <QuickAction icon={<Brain className="w-5 h-5 text-violet-400" />} label="AI Insights" sub="Risk analysis" onClick={() => navigate('/m/ai')} testId="qa-ai-insights" />
        <QuickAction icon={<Phone className="w-5 h-5 text-purple-400" />} label="Fake Call" sub="Escape scenario" onClick={() => navigate('/m/fake-call')} testId="qa-fake-call" />
      </div>

      {/* Last Alert */}
      {data?.last_alert && (
        <div className="p-3 rounded-2xl bg-slate-800/30 border border-slate-700/30" data-testid="last-alert-card">
          <p className="text-[10px] text-slate-500 uppercase mb-1">Last Alert</p>
          <p className="text-[11px] text-slate-300">{data.last_alert.message}</p>
          <p className="text-[9px] text-slate-500 mt-1">
            {new Date(data.last_alert.created_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
          </p>
        </div>
      )}

      {/* Guardian Network Summary */}
      <div className="flex items-center justify-between p-3 rounded-2xl bg-slate-800/30 border border-slate-700/30" data-testid="guardian-summary">
        <div className="flex items-center gap-2">
          <Users className="w-4 h-4 text-teal-400" />
          <div>
            <p className="text-xs font-medium text-white">{data?.guardian_count || 0} Guardians</p>
            <p className="text-[10px] text-slate-500">{data?.emergency_contact_count || 0} emergency contacts</p>
          </div>
        </div>
        <button onClick={() => navigate('/m/profile')} className="text-[10px] text-teal-400 font-medium flex items-center gap-1">
          Manage <ChevronRight className="w-3 h-3" />
        </button>
      </div>
    </div>
  );
}

const QuickAction = ({ icon, label, sub, onClick, testId }) => (
  <button
    onClick={onClick}
    className="p-3 rounded-2xl bg-slate-800/40 border border-slate-700/40 text-left active:scale-[0.97] transition-transform"
    data-testid={testId}
  >
    <div className="mb-2">{icon}</div>
    <p className="text-xs font-medium text-white">{label}</p>
    <p className="text-[10px] text-slate-500">{sub}</p>
  </button>
);
