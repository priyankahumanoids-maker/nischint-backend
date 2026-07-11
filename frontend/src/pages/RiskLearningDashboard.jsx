import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { operatorApi } from '../api';
import { toast } from 'sonner';
import {
  Brain, RefreshCw, Loader2, MapPin, AlertTriangle,
  BarChart3, Clock, Shield, Zap, Target, TrendingUp,
  TrendingDown, ArrowUpRight, ArrowDownRight, Minus,
  Moon, Activity, Eye, Radio, Crosshair, ChevronRight,
} from 'lucide-react';

const TREND_CONFIG = {
  growing:  { color: 'text-red-600',    bg: 'bg-red-100 text-red-700',      icon: <TrendingUp className="w-3.5 h-3.5" /> },
  emerging: { color: 'text-orange-600',  bg: 'bg-orange-100 text-orange-700', icon: <ArrowUpRight className="w-3.5 h-3.5" /> },
  stable:   { color: 'text-amber-600',   bg: 'bg-amber-100 text-amber-700',   icon: <Minus className="w-3.5 h-3.5" /> },
  declining:{ color: 'text-green-600',   bg: 'bg-green-100 text-green-700',   icon: <TrendingDown className="w-3.5 h-3.5" /> },
  dormant:  { color: 'text-slate-400',   bg: 'bg-slate-100 text-slate-500',   icon: <Moon className="w-3.5 h-3.5" /> },
};

const FORECAST_CONFIG = {
  escalating: { color: 'text-red-600',    bg: 'bg-red-100 text-red-700',      icon: <Radio className="w-3.5 h-3.5" />,     label: 'Escalating' },
  emerging:   { color: 'text-orange-600',  bg: 'bg-orange-100 text-orange-700', icon: <ArrowUpRight className="w-3.5 h-3.5" />, label: 'Emerging' },
  stable:     { color: 'text-amber-600',   bg: 'bg-amber-100 text-amber-700',   icon: <Minus className="w-3.5 h-3.5" />,     label: 'Stable' },
  cooling:    { color: 'text-green-600',   bg: 'bg-green-100 text-green-700',   icon: <TrendingDown className="w-3.5 h-3.5" />, label: 'Cooling' },
};

const PRIORITY_CONFIG = {
  1: { label: 'P1 — Urgent', bg: 'bg-red-600 text-white' },
  2: { label: 'P2 — Watch',  bg: 'bg-amber-500 text-white' },
  3: { label: 'P3 — Monitor', bg: 'bg-slate-200 text-slate-600' },
};

function Sparkline({ data, className = '' }) {
  if (!data || data.length === 0) return null;
  const max = Math.max(...data, 1);
  const w = 70, h = 24;
  const points = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - (v / max) * h}`).join(' ');
  const hasActivity = data.some(v => v > 0);
  return (
    <svg width={w} height={h} className={className} viewBox={`0 0 ${w} ${h}`}>
      <polyline points={points} fill="none" stroke={hasActivity ? 'currentColor' : '#cbd5e1'}
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ForecastProjection({ past, future, current, className = '' }) {
  if (!past || past.length === 0) return null;
  const maxPast = Math.max(...past, 1);
  const allScores = [current, ...(future || [])];
  const maxScore = Math.max(...allScores, maxPast, 1);
  const w = 120, h = 32;
  const totalPoints = past.length + allScores.length;
  // Past sparkline (incident counts normalized)
  const pastPoints = past.map((v, i) => {
    const x = (i / (totalPoints - 1)) * w;
    const y = h - (v / maxScore) * h * 0.8;
    return `${x},${y}`;
  });
  // Future projection (risk scores)
  const futurePoints = allScores.map((v, i) => {
    const x = ((past.length + i) / (totalPoints - 1)) * w;
    const y = h - (v / 10.0) * h * 0.9;
    return `${x},${y}`;
  });
  const dividerX = ((past.length) / (totalPoints - 1)) * w;

  return (
    <svg width={w} height={h} className={className} viewBox={`0 0 ${w} ${h}`}>
      {/* Past line */}
      <polyline points={pastPoints.join(' ')} fill="none" stroke="#94a3b8"
        strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      {/* Now divider */}
      <line x1={dividerX} y1="0" x2={dividerX} y2={h} stroke="#cbd5e1" strokeWidth="0.5" strokeDasharray="2,2" />
      {/* Future projection */}
      <polyline points={futurePoints.join(' ')} fill="none" stroke="#ef4444"
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" strokeDasharray="4,2" />
      <text x={w - 2} y={h - 2} fontSize="7" fill="#ef4444" textAnchor="end">{future?.[2]}</text>
    </svg>
  );
}

function TrendBadge({ status }) {
  const cfg = TREND_CONFIG[status] || TREND_CONFIG.stable;
  return <Badge className={`${cfg.bg} gap-1 text-[10px] font-semibold`} data-testid={`trend-badge-${status}`}>{cfg.icon} {status}</Badge>;
}

function ForecastBadge({ category }) {
  const cfg = FORECAST_CONFIG[category] || FORECAST_CONFIG.stable;
  return <Badge className={`${cfg.bg} gap-1 text-[10px] font-semibold`} data-testid={`forecast-badge-${category}`}>{cfg.icon} {cfg.label}</Badge>;
}

function PriorityBadge({ priority }) {
  const cfg = PRIORITY_CONFIG[priority] || PRIORITY_CONFIG[3];
  return <Badge className={`${cfg.bg} text-[10px] font-bold`} data-testid={`priority-badge-${priority}`}>{cfg.label}</Badge>;
}

function DeltaIndicator({ value, suffix = '' }) {
  if (value === 0) return <span className="text-slate-400 text-xs">—</span>;
  const positive = value > 0;
  return (
    <span className={`text-xs font-medium flex items-center gap-0.5 ${positive ? 'text-red-600' : 'text-green-600'}`}>
      {positive ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
      {positive ? '+' : ''}{value}{suffix}
    </span>
  );
}

function TrendZoneRow({ zone, index, onViewDetail }) {
  const w7d = zone.windows?.['7d'] || {};
  return (
    <div className={`flex items-center gap-3 p-3 rounded-lg border transition-colors hover:shadow-sm ${
      zone.recommended_priority === 1 ? 'border-red-200 bg-red-50/50' :
      zone.recommended_priority === 2 ? 'border-amber-200 bg-amber-50/50' : 'border-slate-100 bg-white'
    }`} data-testid={`trend-zone-${index}`}>
      <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${
        zone.risk_score >= 7 ? 'bg-red-100' : zone.risk_score >= 5 ? 'bg-orange-100' : 'bg-amber-100'
      }`}>
        <span className={`text-sm font-bold ${zone.risk_score >= 7 ? 'text-red-600' : zone.risk_score >= 5 ? 'text-orange-600' : 'text-amber-600'}`}>{zone.risk_score}</span>
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium text-slate-800 text-sm truncate">{zone.zone_name}</span>
          <TrendBadge status={zone.trend_status} />
          <PriorityBadge priority={zone.recommended_priority} />
        </div>
        <div className="flex gap-3 text-[10px] text-slate-400 mt-0.5">
          <span className="flex items-center gap-0.5"><MapPin className="w-3 h-3" />{zone.lat?.toFixed(4)}, {zone.lng?.toFixed(4)}</span>
          <DeltaIndicator value={w7d.incident_delta || 0} suffix=" inc" />
          <DeltaIndicator value={w7d.score_delta || 0} suffix=" sev" />
        </div>
      </div>
      <div className={`shrink-0 ${(TREND_CONFIG[zone.trend_status] || TREND_CONFIG.stable).color}`}>
        <Sparkline data={zone.sparkline_7d} />
      </div>
      <Button variant="ghost" size="sm" className="shrink-0 h-7 px-2" onClick={() => onViewDetail(zone)}
        data-testid={`view-trend-detail-${index}`}><Eye className="w-3.5 h-3.5" /></Button>
    </div>
  );
}

function ForecastZoneRow({ zone, index, onViewDetail }) {
  const cfg = FORECAST_CONFIG[zone.forecast_category] || FORECAST_CONFIG.stable;
  const delta48 = round1(zone.predicted_48h - zone.risk_score);
  return (
    <div className={`flex items-center gap-3 p-3 rounded-lg border transition-colors hover:shadow-sm ${
      zone.forecast_priority === 1 ? 'border-red-200 bg-red-50/50' :
      zone.forecast_priority === 2 ? 'border-amber-200 bg-amber-50/50' : 'border-slate-100 bg-white'
    }`} data-testid={`forecast-zone-${index}`}>
      {/* Current → Predicted */}
      <div className="flex items-center gap-1 shrink-0">
        <div className={`w-9 h-9 rounded-full flex items-center justify-center ${
          zone.risk_score >= 7 ? 'bg-red-100' : zone.risk_score >= 5 ? 'bg-orange-100' : 'bg-amber-100'
        }`}>
          <span className={`text-xs font-bold ${zone.risk_score >= 7 ? 'text-red-600' : zone.risk_score >= 5 ? 'text-orange-600' : 'text-amber-600'}`}>{zone.risk_score}</span>
        </div>
        <ChevronRight className="w-3 h-3 text-slate-300" />
        <div className={`w-9 h-9 rounded-full flex items-center justify-center border-2 ${
          zone.predicted_48h >= 7 ? 'bg-red-50 border-red-400' : zone.predicted_48h >= 5 ? 'bg-orange-50 border-orange-400' : 'bg-amber-50 border-amber-300'
        }`}>
          <span className={`text-xs font-bold ${zone.predicted_48h >= 7 ? 'text-red-600' : zone.predicted_48h >= 5 ? 'text-orange-600' : 'text-amber-600'}`}>{zone.predicted_48h}</span>
        </div>
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium text-slate-800 text-sm truncate">{zone.zone_name}</span>
          <ForecastBadge category={zone.forecast_category} />
          <PriorityBadge priority={zone.forecast_priority} />
        </div>
        <div className="flex gap-3 text-[10px] text-slate-400 mt-0.5">
          <span>24h: {zone.predicted_24h}</span>
          <span>48h: {zone.predicted_48h}</span>
          <span>72h: {zone.predicted_72h}</span>
          <span className={delta48 > 0 ? 'text-red-500' : 'text-green-500'}>
            {delta48 > 0 ? '+' : ''}{delta48} in 48h
          </span>
          <span>conf: {Math.round(zone.confidence * 100)}%</span>
        </div>
      </div>
      <div className={`shrink-0 ${cfg.color}`}>
        <ForecastProjection past={zone.sparkline_past} future={zone.sparkline_future} current={zone.risk_score} />
      </div>
      <Button variant="ghost" size="sm" className="shrink-0 h-7 px-2" onClick={() => onViewDetail(zone)}
        data-testid={`view-forecast-detail-${index}`}><Eye className="w-3.5 h-3.5" /></Button>
    </div>
  );
}

function round1(v) { return Math.round(v * 10) / 10; }

function TrendDetailModal({ zone, onClose }) {
  if (!zone) return null;
  const windows = zone.windows || {};
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose} data-testid="trend-detail-modal">
      <div className="bg-white rounded-xl shadow-2xl max-w-lg w-full max-h-[80vh] overflow-y-auto p-5" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-bold text-slate-800">{zone.zone_name}</h3>
            <div className="flex items-center gap-2 mt-1">
              <TrendBadge status={zone.trend_status} />
              <PriorityBadge priority={zone.recommended_priority} />
              <span className="text-xs text-slate-400">Score: {zone.risk_score}</span>
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>x</Button>
        </div>
        <div className="space-y-3">
          {Object.entries(windows).map(([key, w]) => (
            <Card key={key} className="border-slate-100">
              <CardContent className="p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-semibold text-slate-700">{key} Window</span>
                  <TrendBadge status={w.trend_status} />
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="p-2 rounded bg-slate-50">
                    <p className="text-[10px] text-slate-400">Recent</p>
                    <p className="font-bold text-slate-700">{w.recent?.count || 0} incidents</p>
                    <p className="text-slate-500">Sev: {w.recent?.severity_weighted || 0}</p>
                  </div>
                  <div className="p-2 rounded bg-slate-50">
                    <p className="text-[10px] text-slate-400">Previous</p>
                    <p className="font-bold text-slate-700">{w.previous?.count || 0} incidents</p>
                    <p className="text-slate-500">Sev: {w.previous?.severity_weighted || 0}</p>
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-2 mt-2 text-[10px]">
                  {[['Incidents', w.incident_delta], ['Severity', w.score_delta], ['High-Sev', w.confidence_delta], ['Night', w.night_delta]].map(([label, val]) => (
                    <div key={label} className="text-center">
                      <p className="text-slate-400">{label}</p>
                      <DeltaIndicator value={val || 0} />
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}

function ForecastDetailModal({ zone, onClose }) {
  if (!zone) return null;
  const sig = zone.signals || {};
  const rec = zone.recommendation || {};
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose} data-testid="forecast-detail-modal">
      <div className="bg-white rounded-xl shadow-2xl max-w-lg w-full max-h-[80vh] overflow-y-auto p-5" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-bold text-slate-800">{zone.zone_name}</h3>
            <div className="flex items-center gap-2 mt-1">
              <ForecastBadge category={zone.forecast_category} />
              <PriorityBadge priority={zone.forecast_priority} />
              <span className="text-xs text-slate-400">Confidence: {Math.round(zone.confidence * 100)}%</span>
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>x</Button>
        </div>

        {/* Prediction Timeline */}
        <Card className="border-slate-100 mb-3">
          <CardContent className="p-3">
            <p className="text-sm font-semibold text-slate-700 mb-2">Risk Forecast Timeline</p>
            <div className="flex items-end gap-2">
              {[
                { label: 'Now', value: zone.risk_score, isCurrent: true },
                { label: '24h', value: zone.predicted_24h },
                { label: '48h', value: zone.predicted_48h },
                { label: '72h', value: zone.predicted_72h },
              ].map(p => (
                <div key={p.label} className="flex-1 text-center">
                  <div className={`mx-auto w-12 rounded-lg p-2 ${
                    p.value >= 7 ? 'bg-red-100' : p.value >= 5 ? 'bg-orange-100' : 'bg-amber-100'
                  } ${p.isCurrent ? 'border-2 border-slate-400' : 'border border-dashed border-slate-200'}`}>
                    <p className={`text-lg font-bold ${p.value >= 7 ? 'text-red-600' : p.value >= 5 ? 'text-orange-600' : 'text-amber-600'}`}>{p.value}</p>
                  </div>
                  <p className="text-[10px] text-slate-400 mt-1">{p.label}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Signals */}
        <Card className="border-slate-100 mb-3">
          <CardContent className="p-3">
            <p className="text-sm font-semibold text-slate-700 mb-2">Prediction Signals</p>
            <div className="grid grid-cols-2 gap-2 text-xs">
              {[
                { label: 'Trend Score', value: sig.trend_score, desc: 'Direction of change' },
                { label: 'Incident Velocity', value: `${sig.incident_velocity}x`, desc: 'Rate of new incidents' },
                { label: 'Severity Momentum', value: sig.severity_momentum, desc: 'Shift toward critical' },
                { label: 'Temporal Pattern', value: sig.temporal_pattern, desc: 'Time-of-day clustering' },
              ].map(s => (
                <div key={s.label} className="p-2 rounded bg-slate-50 border border-slate-100">
                  <p className="text-[10px] text-slate-400">{s.label}</p>
                  <p className="font-bold text-slate-700">{s.value}</p>
                  <p className="text-[9px] text-slate-400">{s.desc}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Recommendation */}
        <Card className={`border ${rec.urgency === 'high' ? 'border-red-200 bg-red-50/30' : rec.urgency === 'medium' ? 'border-amber-200 bg-amber-50/30' : 'border-slate-100'}`}>
          <CardContent className="p-3">
            <div className="text-sm font-semibold text-slate-700 mb-1 flex items-center gap-2">
              <Crosshair className="w-4 h-4" /> {rec.action}
              <Badge className={rec.urgency === 'high' ? 'bg-red-100 text-red-700' : rec.urgency === 'medium' ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-600'}>{rec.urgency}</Badge>
            </div>
            <ul className="space-y-1">
              {(rec.details || []).map((d, i) => (
                <li key={i} className="text-xs text-slate-500 flex items-start gap-1">
                  <span className="text-slate-300 mt-0.5">-</span> {d}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        {zone.factors?.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1">
            {zone.factors.filter(f => typeof f === 'string').map((f, i) => (
              <span key={i} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 border border-slate-200">{f}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function RiskLearningDashboard() {
  const [stats, setStats] = useState(null);
  const [trends, setTrends] = useState(null);
  const [forecasts, setForecasts] = useState(null);
  const [loading, setLoading] = useState(true);
  const [trendsLoading, setTrendsLoading] = useState(true);
  const [forecastLoading, setForecastLoading] = useState(true);
  const [recalculating, setRecalculating] = useState(false);
  const [activeTab, setActiveTab] = useState('forecast');
  const [detailZone, setDetailZone] = useState(null);
  const [forecastDetailZone, setForecastDetailZone] = useState(null);

  const fetchStats = useCallback(async () => {
    setLoading(true);
    try { setStats((await operatorApi.getRiskLearningStats()).data); }
    catch { toast.error('Failed to load risk learning data'); }
    finally { setLoading(false); }
  }, []);

  const fetchTrends = useCallback(async () => {
    setTrendsLoading(true);
    try { setTrends((await operatorApi.getHotspotTrends()).data); }
    catch { toast.error('Failed to load trend data'); }
    finally { setTrendsLoading(false); }
  }, []);

  const fetchForecasts = useCallback(async () => {
    setForecastLoading(true);
    try { setForecasts((await operatorApi.getRiskForecasts()).data); }
    catch { toast.error('Failed to load forecast data'); }
    finally { setForecastLoading(false); }
  }, []);

  useEffect(() => { fetchStats(); fetchTrends(); fetchForecasts(); }, [fetchStats, fetchTrends, fetchForecasts]);

  const handleRecalculate = async () => {
    setRecalculating(true);
    try {
      const res = await operatorApi.triggerRiskRecalculation();
      toast.success(`Risk learning complete: ${res.data.hotspots_created} hotspots from ${res.data.incidents_analyzed} incidents`);
      fetchStats(); fetchTrends(); fetchForecasts();
    } catch { toast.error('Risk recalculation failed'); }
    finally { setRecalculating(false); }
  };

  const refreshAll = () => { fetchStats(); fetchTrends(); fetchForecasts(); };

  const riskColor = (score) => score >= 7 ? 'text-red-600' : score >= 5 ? 'text-orange-600' : score >= 3 ? 'text-amber-600' : 'text-green-600';
  const riskBg = (level) => ({ critical: 'bg-red-100 text-red-700', high: 'bg-orange-100 text-orange-700', medium: 'bg-amber-100 text-amber-700', low: 'bg-green-100 text-green-700' }[level] || 'bg-slate-100 text-slate-600');

  if (loading && trendsLoading && forecastLoading) return (
    <div className="flex items-center justify-center py-12"><Loader2 className="w-6 h-6 animate-spin text-slate-400" /></div>
  );

  const statusCounts = trends?.status_counts || {};
  const priorityCounts = trends?.priority_counts || {};
  const forecastCounts = forecasts?.forecast_counts || {};

  return (
    <div className="space-y-6" data-testid="risk-learning-dashboard">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-slate-800">AI Risk Intelligence</h2>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={refreshAll} data-testid="refresh-risk-learning">
            <RefreshCw className="w-4 h-4 mr-2" /> Refresh
          </Button>
          <Button size="sm" onClick={handleRecalculate} disabled={recalculating}
            className="bg-purple-600 hover:bg-purple-700" data-testid="recalculate-btn">
            {recalculating ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Brain className="w-4 h-4 mr-2" />}
            {recalculating ? 'Learning...' : 'Recalculate Now'}
          </Button>
        </div>
      </div>

      {/* Stats Overview */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3" data-testid="learning-stats">
          {[
            { label: 'Learned Zones', value: stats.learned_zones_count, icon: <Target className="w-5 h-5 text-purple-500" />, color: 'border-purple-200 bg-purple-50/50' },
            { label: 'Manual Zones', value: stats.manual_zones_count, icon: <MapPin className="w-5 h-5 text-blue-500" />, color: 'border-blue-200 bg-blue-50/50' },
            { label: 'Incidents Analyzed', value: stats.geolocated_incidents, icon: <BarChart3 className="w-5 h-5 text-amber-500" />, color: 'border-amber-200 bg-amber-50/50' },
            { label: 'P1 Predicted 48h', value: forecasts?.p1_predicted_48h ?? '—', icon: <Radio className="w-5 h-5 text-red-500" />, color: 'border-red-200 bg-red-50/50' },
          ].map(s => (
            <Card key={s.label} className={`border ${s.color}`}>
              <CardContent className="p-4 flex items-center gap-3">
                {s.icon}
                <div>
                  <p className="text-2xl font-bold text-slate-800">{s.value}</p>
                  <p className="text-xs text-slate-500">{s.label}</p>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Forecast Status Overview */}
      {forecasts && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2" data-testid="forecast-status-overview">
          {['escalating', 'emerging', 'stable', 'cooling'].map(cat => {
            const cfg = FORECAST_CONFIG[cat];
            const count = forecastCounts[cat] || 0;
            return (
              <Card key={cat} className={`border cursor-pointer transition-all ${count > 0 ? 'hover:shadow-sm' : 'opacity-60'}`}>
                <CardContent className="p-3 flex items-center gap-2">
                  <div className={cfg.color}>{cfg.icon}</div>
                  <div>
                    <p className="text-lg font-bold text-slate-800">{count}</p>
                    <p className="text-[10px] text-slate-500 capitalize">{cfg.label}</p>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 bg-slate-100 rounded-lg p-1" data-testid="tab-switcher">
        {[
          { id: 'forecast', label: 'Forecast', icon: <Radio className="w-4 h-4" /> },
          { id: 'trends', label: 'Trends', icon: <Activity className="w-4 h-4" /> },
          { id: 'zones', label: 'All Zones', icon: <Target className="w-4 h-4" /> },
          { id: 'config', label: 'Config', icon: <Zap className="w-4 h-4" /> },
        ].map(tab => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
              activeTab === tab.id ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'
            }`} data-testid={`tab-${tab.id}`}>
            {tab.icon} {tab.label}
          </button>
        ))}
      </div>

      {/* Forecast Tab */}
      {activeTab === 'forecast' && (
        <div className="space-y-4">
          {forecastLoading ? (
            <div className="text-center py-8"><Loader2 className="w-6 h-6 animate-spin text-slate-400 mx-auto" /><p className="text-xs text-slate-400 mt-2">Computing forecasts...</p></div>
          ) : forecasts ? (
            <>
              {/* Escalating Zones */}
              {forecasts.escalating_zones?.length > 0 && (
                <Card data-testid="escalating-zones-card">
                  <CardContent className="p-5">
                    <h3 className="text-base font-semibold text-slate-800 mb-3 flex items-center gap-2">
                      <Radio className="w-5 h-5 text-red-500" />
                      Escalating — Will Become P1
                      <Badge className="bg-red-100 text-red-700 ml-1">{forecasts.escalating_zones.length}</Badge>
                    </h3>
                    <div className="space-y-2">
                      {forecasts.escalating_zones.map((z, i) => (
                        <ForecastZoneRow key={z.zone_id || i} zone={z} index={`esc-${i}`} onViewDetail={setForecastDetailZone} />
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Emerging Zones */}
              {forecasts.emerging_zones?.length > 0 && (
                <Card data-testid="emerging-forecast-card">
                  <CardContent className="p-5">
                    <h3 className="text-base font-semibold text-slate-800 mb-3 flex items-center gap-2">
                      <ArrowUpRight className="w-5 h-5 text-orange-500" />
                      Emerging Risk
                      <Badge className="bg-orange-100 text-orange-700 ml-1">{forecasts.emerging_zones.length}</Badge>
                    </h3>
                    <div className="space-y-2">
                      {forecasts.emerging_zones.map((z, i) => (
                        <ForecastZoneRow key={z.zone_id || i} zone={z} index={`em-${i}`} onViewDetail={setForecastDetailZone} />
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Cooling Zones */}
              {forecasts.cooling_zones?.length > 0 && (
                <Card data-testid="cooling-forecast-card">
                  <CardContent className="p-5">
                    <h3 className="text-base font-semibold text-slate-800 mb-3 flex items-center gap-2">
                      <TrendingDown className="w-5 h-5 text-green-500" />
                      Cooling Down
                      <Badge className="bg-green-100 text-green-700 ml-1">{forecasts.cooling_zones.length}</Badge>
                    </h3>
                    <div className="space-y-2">
                      {forecasts.cooling_zones.map((z, i) => (
                        <ForecastZoneRow key={z.zone_id || i} zone={z} index={`cool-${i}`} onViewDetail={setForecastDetailZone} />
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* All Forecasts */}
              {forecasts.forecasts?.length > 0 && (
                <Card data-testid="all-forecasts-card">
                  <CardContent className="p-5">
                    <h3 className="text-base font-semibold text-slate-800 mb-3 flex items-center gap-2">
                      <Shield className="w-5 h-5 text-purple-500" />
                      All Zone Forecasts
                      <Badge className="bg-purple-100 text-purple-700 ml-1">{forecasts.forecasts.length}</Badge>
                    </h3>
                    <div className="space-y-2 max-h-[400px] overflow-y-auto">
                      {forecasts.forecasts.map((z, i) => (
                        <ForecastZoneRow key={z.zone_id || i} zone={z} index={`all-fc-${i}`} onViewDetail={setForecastDetailZone} />
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}

              {!forecasts.forecasts?.length && (
                <div className="text-center py-8" data-testid="no-forecasts">
                  <Radio className="w-10 h-10 mx-auto text-slate-300 mb-2" />
                  <p className="text-sm text-slate-500">No forecast data available</p>
                </div>
              )}
            </>
          ) : null}
        </div>
      )}

      {/* Trends Tab */}
      {activeTab === 'trends' && trends && (
        <div className="space-y-4">
          {/* Trend Status */}
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2" data-testid="trend-status-overview">
            {['growing', 'emerging', 'stable', 'declining', 'dormant'].map(status => {
              const cfg = TREND_CONFIG[status];
              return (
                <Card key={status} className={`border ${(statusCounts[status] || 0) > 0 ? '' : 'opacity-60'}`}>
                  <CardContent className="p-3 flex items-center gap-2">
                    <div className={cfg.color}>{cfg.icon}</div>
                    <div><p className="text-lg font-bold text-slate-800">{statusCounts[status] || 0}</p><p className="text-[10px] text-slate-500 capitalize">{status}</p></div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
          {trends.top_growing?.length > 0 && (
            <Card data-testid="top-growing-card">
              <CardContent className="p-5">
                <h3 className="text-base font-semibold text-slate-800 mb-3 flex items-center gap-2">
                  <TrendingUp className="w-5 h-5 text-red-500" /> Rising Hotspots <Badge className="bg-red-100 text-red-700 ml-1">{trends.top_growing.length}</Badge>
                </h3>
                <div className="space-y-2">{trends.top_growing.map((z, i) => <TrendZoneRow key={z.zone_id || i} zone={z} index={i} onViewDetail={setDetailZone} />)}</div>
              </CardContent>
            </Card>
          )}
          {trends.top_declining?.length > 0 && (
            <Card data-testid="top-declining-card">
              <CardContent className="p-5">
                <h3 className="text-base font-semibold text-slate-800 mb-3 flex items-center gap-2">
                  <TrendingDown className="w-5 h-5 text-green-500" /> Declining <Badge className="bg-green-100 text-green-700 ml-1">{trends.top_declining.length}</Badge>
                </h3>
                <div className="space-y-2">{trends.top_declining.map((z, i) => <TrendZoneRow key={z.zone_id || i} zone={z} index={`dec-${i}`} onViewDetail={setDetailZone} />)}</div>
              </CardContent>
            </Card>
          )}
          {trends.trends?.length > 0 && (
            <Card data-testid="all-trends-card">
              <CardContent className="p-5">
                <h3 className="text-base font-semibold text-slate-800 mb-3 flex items-center gap-2"><Shield className="w-5 h-5 text-purple-500" /> All Zone Trends <Badge className="bg-purple-100 text-purple-700 ml-1">{trends.trends.length}</Badge></h3>
                <div className="space-y-2 max-h-[400px] overflow-y-auto">{trends.trends.map((z, i) => <TrendZoneRow key={z.zone_id || i} zone={z} index={`all-${i}`} onViewDetail={setDetailZone} />)}</div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* Zones Tab */}
      {activeTab === 'zones' && stats && (
        <Card data-testid="hotspot-zones-card">
          <CardContent className="p-5">
            <h3 className="text-lg font-semibold text-slate-800 mb-3 flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-red-500" /> Learned Hotspot Zones
              {stats.learned_zones_count > 0 && <Badge className="bg-purple-100 text-purple-700 ml-2">{stats.learned_zones_count}</Badge>}
            </h3>
            {stats.learned_zones.length === 0 ? (
              <div className="text-center py-8" data-testid="no-hotspots"><Brain className="w-10 h-10 mx-auto text-slate-300 mb-2" /><p className="text-sm text-slate-500">No hotspots detected yet</p></div>
            ) : (
              <div className="space-y-2" data-testid="hotspot-list">
                {stats.learned_zones.map((zone, i) => (
                  <div key={i} className={`flex items-center gap-3 p-3 rounded-lg border ${zone.risk_level === 'critical' ? 'border-red-200 bg-red-50/50' : zone.risk_level === 'high' ? 'border-orange-200 bg-orange-50/50' : 'border-slate-100 bg-slate-50/50'}`} data-testid={`hotspot-zone-${i}`}>
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${zone.risk_level === 'critical' ? 'bg-red-100' : zone.risk_level === 'high' ? 'bg-orange-100' : 'bg-amber-100'}`}>
                      <span className={`text-sm font-bold ${riskColor(zone.risk_score)}`}>{zone.risk_score}</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-slate-800 text-sm">{zone.zone_name}</span>
                        <Badge className={riskBg(zone.risk_level)}>{zone.risk_level}</Badge>
                      </div>
                      <div className="flex gap-2 text-[10px] text-slate-400 mt-0.5 flex-wrap">
                        <span className="flex items-center gap-0.5"><MapPin className="w-3 h-3" />{zone.lat.toFixed(4)}, {zone.lng.toFixed(4)}</span>
                        <span>r={zone.radius_meters}m</span>
                        {(zone.factors || []).filter(f => typeof f === 'string').map((f, j) => (
                          <span key={j} className="px-1 py-0 rounded bg-white border border-slate-200">{f}</span>
                        ))}
                      </div>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-xs text-slate-500 font-medium">{zone.incident_count} incidents</p>
                      <p className="text-[10px] text-slate-400">{zone.last_updated ? new Date(zone.last_updated).toLocaleDateString() : '—'}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Config Tab */}
      {activeTab === 'config' && (
        <>
          {stats && (
            <Card data-testid="learning-config-card">
              <CardContent className="p-5">
                <h3 className="text-lg font-semibold text-slate-800 mb-3 flex items-center gap-2"><Zap className="w-5 h-5 text-purple-500" /> Learning Parameters</h3>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                  {[
                    { label: 'Cluster Radius', value: `${stats.cluster_radius_m}m` },
                    { label: 'Min Incidents', value: stats.min_incidents_for_hotspot },
                    { label: 'Decay Half-Life', value: `${stats.decay_half_life_days}d` },
                    { label: 'Last Analysis', value: stats.last_analysis ? new Date(stats.last_analysis).toLocaleString([], {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'}) : 'Never' },
                  ].map(s => (
                    <div key={s.label} className="p-2 rounded bg-slate-50 border border-slate-100">
                      <p className="text-[10px] text-slate-400 uppercase">{s.label}</p>
                      <p className="font-bold text-slate-700 text-xs">{s.value}</p>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
          <Card data-testid="how-it-works-card">
            <CardContent className="p-5">
              <h3 className="text-lg font-semibold text-slate-800 mb-3 flex items-center gap-2"><TrendingUp className="w-5 h-5 text-green-500" /> How It Works</h3>
              <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
                {[
                  { step: '1', title: 'Learn', desc: 'Cluster incidents spatially to detect hotspot zones.' },
                  { step: '2', title: 'Trend', desc: 'Compare rolling windows (24h/7d/30d) to classify zone direction.' },
                  { step: '3', title: 'Forecast', desc: 'Project risk scores at 24h/48h/72h using velocity and severity signals.' },
                  { step: '4', title: 'Act', desc: 'Prioritize zones and provide preventive operator recommendations.' },
                ].map(s => (
                  <div key={s.step} className="p-3 rounded-lg border border-slate-100 bg-slate-50/50">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="w-6 h-6 rounded-full bg-purple-100 text-purple-700 text-xs font-bold flex items-center justify-center">{s.step}</span>
                      <span className="font-semibold text-sm text-slate-700">{s.title}</span>
                    </div>
                    <p className="text-xs text-slate-500">{s.desc}</p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {/* Modals */}
      <TrendDetailModal zone={detailZone} onClose={() => setDetailZone(null)} />
      <ForecastDetailModal zone={forecastDetailZone} onClose={() => setForecastDetailZone(null)} />
    </div>
  );
}
