import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../api';
import {
  Brain, ArrowLeft, Shield, Activity, MapPin, Smartphone,
  Cloud, Users, Loader2, RefreshCw, AlertTriangle, TrendingUp,
  Zap, ChevronDown, ChevronUp, Lightbulb,
} from 'lucide-react';

const RISK_COLORS = {
  critical: { bg: 'bg-red-500', ring: 'ring-red-500/30', text: 'text-red-400', bar: 'bg-red-500' },
  high: { bg: 'bg-orange-500', ring: 'ring-orange-500/30', text: 'text-orange-400', bar: 'bg-orange-500' },
  moderate: { bg: 'bg-amber-500', ring: 'ring-amber-500/30', text: 'text-amber-400', bar: 'bg-amber-500' },
  low: { bg: 'bg-emerald-500', ring: 'ring-emerald-500/30', text: 'text-emerald-400', bar: 'bg-emerald-500' },
};

const CATEGORY_ICONS = {
  behavior: Activity,
  location: MapPin,
  device: Smartphone,
  environment: Cloud,
  response: Users,
};

const CATEGORY_COLORS = {
  behavior: 'text-violet-400',
  location: 'text-blue-400',
  device: 'text-cyan-400',
  environment: 'text-amber-400',
  response: 'text-teal-400',
};

export default function MobileAIInsights() {
  const navigate = useNavigate();
  const [riskData, setRiskData] = useState(null);
  const [threat, setThreat] = useState(null);
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(false); // Start with content visible
  const [refreshing, setRefreshing] = useState(false);
  const [expandedThreat, setExpandedThreat] = useState(false);
  const [aiLoading, setAiLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setAiLoading(true);
    try {
      const dashRes = await api.get('/safety-events/user-dashboard');
      setDashboard(dashRes.data);

      const userId = dashRes.data.user_id;
      const [riskRes, threatRes] = await Promise.allSettled([
        api.get(`/guardian-ai/${userId}/risk-score`),
        api.get('/guardian-ai/insights/threat-assessment'),
      ]);

      if (riskRes.status === 'fulfilled') setRiskData(riskRes.value.data);
      if (threatRes.status === 'fulfilled') setThreat(threatRes.value.data);
    } catch { /* silent */ }
    setAiLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const refresh = () => { setRefreshing(true); fetchData(); };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[400px] gap-3">
        <Brain className="w-8 h-8 text-violet-400 animate-pulse" />
        <span className="text-xs text-slate-500">Analyzing safety intelligence...</span>
      </div>
    );
  }

  const level = riskData?.risk_level || dashboard?.risk_level || 'low';
  const rs = RISK_COLORS[level] || RISK_COLORS.low;
  const score = riskData?.final_score || dashboard?.risk_score || 0;
  const scores = riskData?.scores || {};
  const factors = riskData?.top_factors || [];
  const action = riskData?.recommended_action || '';

  return (
    <div className="px-4 pt-4 pb-6" data-testid="mobile-ai-insights">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/m/home')} className="p-2 -ml-2 rounded-full active:bg-slate-800">
            <ArrowLeft className="w-5 h-5 text-slate-400" />
          </button>
          <div>
            <h1 className="text-base font-bold text-white">AI Insights</h1>
            <p className="text-[10px] text-slate-500">Guardian AI Analysis</p>
          </div>
        </div>
        <button onClick={refresh} className="p-2 rounded-full bg-slate-800/50 active:bg-slate-700/50" data-testid="refresh-insights">
          <RefreshCw className={`w-4 h-4 text-slate-400 ${refreshing ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Risk Score Gauge */}
      <div className="p-5 rounded-2xl bg-slate-800/30 border border-slate-700/30 mb-4" data-testid="risk-gauge-card">
        <div className="flex items-center justify-between mb-4">
          <span className="text-[11px] text-slate-500 uppercase font-medium">Current Risk Level</span>
          <span className={`px-2.5 py-0.5 rounded-full ${rs.bg} text-white text-[10px] font-bold uppercase`}>
            {level}
          </span>
        </div>

        {/* Score Arc */}
        <div className="flex items-center justify-center mb-4">
          <div className={`relative w-36 h-36 rounded-full ${rs.ring} ring-[3px] flex items-center justify-center`}>
            <div className={`w-28 h-28 rounded-full ${rs.bg}/10 flex flex-col items-center justify-center`}>
              {aiLoading && !dashboard ? (
                <Loader2 className="w-6 h-6 text-slate-500 animate-spin" />
              ) : (
                <>
                  <span className={`text-4xl font-bold font-mono ${rs.text}`}>
                    {(score * 10).toFixed(1)}
                  </span>
                  <span className="text-[10px] text-slate-500 mt-0.5">/10 risk</span>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Category Bars */}
        <div className="space-y-2.5">
          {Object.entries(scores).map(([cat, val]) => {
            const Icon = CATEGORY_ICONS[cat] || Shield;
            const color = CATEGORY_COLORS[cat] || 'text-slate-400';
            const pct = Math.max(2, (val || 0) * 100);

            return (
              <div key={cat} className="flex items-center gap-3" data-testid={`factor-${cat}`}>
                <Icon className={`w-3.5 h-3.5 ${color} shrink-0`} />
                <span className="text-[10px] text-slate-400 w-20 capitalize shrink-0">{cat}</span>
                <div className="flex-1 h-2 rounded-full bg-slate-800 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-700 ${rs.bar}/60`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="text-[10px] text-slate-500 font-mono w-8 text-right">
                  {(val || 0).toFixed(2)}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Top Risk Factors */}
      {factors.length > 0 && (
        <div className="p-4 rounded-2xl bg-slate-800/30 border border-slate-700/30 mb-4" data-testid="risk-factors-card">
          <div className="flex items-center gap-2 mb-3">
            <Zap className="w-4 h-4 text-amber-400" />
            <span className="text-[11px] text-slate-500 uppercase font-medium">Top Risk Factors</span>
          </div>

          <div className="space-y-2">
            {factors.map((f, i) => {
              const catColor = CATEGORY_COLORS[f.category] || 'text-slate-400';
              return (
                <div key={i} className="p-2.5 rounded-xl bg-slate-900/50 border border-slate-800/50" data-testid={`risk-factor-${i}`}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-white font-medium">{f.description}</span>
                    <span className={`text-[10px] font-mono font-bold ${catColor}`}>
                      +{f.impact?.toFixed(2)}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`text-[9px] ${catColor} capitalize`}>{f.category}</span>
                    <span className="text-[9px] text-slate-600">{f.factor?.replace(/_/g, ' ')}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Threat Assessment */}
      {threat && (
        <div
          className="p-4 rounded-2xl bg-slate-800/30 border border-slate-700/30 mb-4 cursor-pointer"
          onClick={() => setExpandedThreat(!expandedThreat)}
          data-testid="threat-assessment-card"
        >
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <Brain className="w-4 h-4 text-violet-400" />
              <span className="text-[11px] text-slate-500 uppercase font-medium">Threat Assessment</span>
            </div>
            <div className="flex items-center gap-2">
              <span className={`px-2 py-0.5 rounded-full text-[9px] font-bold ${
                threat.threat_level === 'HIGH' ? 'bg-red-500/20 text-red-400' :
                threat.threat_level === 'MODERATE' ? 'bg-amber-500/20 text-amber-400' :
                'bg-emerald-500/20 text-emerald-400'
              }`}>
                {threat.threat_level}
              </span>
              {expandedThreat ? <ChevronUp className="w-3.5 h-3.5 text-slate-600" /> : <ChevronDown className="w-3.5 h-3.5 text-slate-600" />}
            </div>
          </div>

          <p className="text-xs text-slate-300 leading-relaxed">{threat.summary}</p>

          {expandedThreat && (
            <div className="mt-3 pt-3 border-t border-slate-700/30 space-y-2">
              <div className="grid grid-cols-3 gap-2">
                <StatMini label="Zones at Risk" value={threat.zones_escalating || 0} color="text-red-400" />
                <StatMini label="Anomalies" value={threat.users_anomaly || 0} color="text-amber-400" />
                <StatMini label="Incidents" value={threat.recent_incidents || 0} color="text-blue-400" />
              </div>
              {threat.top_zone && (
                <div className="flex items-center gap-2 text-[10px] text-slate-500">
                  <MapPin className="w-3 h-3" />
                  <span>Hotspot: {threat.top_zone}</span>
                </div>
              )}
              {threat.recommended_action && (
                <div className="p-2 rounded-lg bg-violet-500/8 border border-violet-500/15">
                  <p className="text-[10px] text-violet-300 leading-relaxed">{threat.recommended_action}</p>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* AI Recommendation */}
      {action && (
        <div className="p-4 rounded-2xl bg-teal-500/8 border border-teal-500/20 mb-4" data-testid="ai-recommendation">
          <div className="flex items-start gap-2.5">
            <Lightbulb className="w-4 h-4 text-teal-400 mt-0.5 shrink-0" />
            <div>
              <p className="text-[11px] text-teal-400 font-medium mb-1">AI Recommendation</p>
              <p className="text-xs text-teal-300/80 leading-relaxed">{action}</p>
            </div>
          </div>
        </div>
      )}

      {/* Trend Indicator */}
      <div className="p-4 rounded-2xl bg-slate-800/30 border border-slate-700/30" data-testid="trend-card">
        <div className="flex items-center gap-2 mb-3">
          <TrendingUp className="w-4 h-4 text-blue-400" />
          <span className="text-[11px] text-slate-500 uppercase font-medium">Safety Trend</span>
        </div>
        <div className="flex items-center gap-4">
          {/* Mini trend visualization */}
          <div className="flex items-end gap-0.5 h-10">
            {[0.3, 0.4, 0.35, 0.5, 0.45, 0.38, score].map((v, i) => (
              <div
                key={i}
                className={`w-5 rounded-t transition-all ${
                  i === 6 ? rs.bar : 'bg-slate-700'
                }`}
                style={{ height: `${Math.max(10, v * 100)}%` }}
              />
            ))}
          </div>
          <div className="flex-1">
            <p className="text-xs text-white font-medium">
              {score > 0.6 ? 'Elevated risk trend' : score > 0.3 ? 'Moderate fluctuation' : 'Stable and safe'}
            </p>
            <p className="text-[10px] text-slate-500 mt-0.5">
              Last 7 analysis cycles
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

const StatMini = ({ label, value, color }) => (
  <div className="text-center">
    <p className={`text-sm font-bold font-mono ${color}`}>{value}</p>
    <p className="text-[8px] text-slate-600 uppercase">{label}</p>
  </div>
);
