import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { operatorApi } from '../api';
import { useNavigate } from 'react-router-dom';
import { IncidentReplayViewer } from '../components/IncidentReplayViewer';
import {
  Shield, AlertTriangle, Clock, TrendingDown, TrendingUp,
  Activity, Loader2, RefreshCw, Zap, Heart, Eye,
  ChevronRight, Radio, Brain, Minus, Fingerprint,
  Cloud, Thermometer, Wind, Droplets, Navigation, Pause, Play,
  Globe, Flame,
} from 'lucide-react';

// ── Status / Color configs ──

const STATUS_CFG = {
  EXCELLENT: { color: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200', badge: 'bg-emerald-100 text-emerald-700', label: 'Excellent' },
  STABLE: { color: 'text-green-600', bg: 'bg-green-50', border: 'border-green-200', badge: 'bg-green-100 text-green-700', label: 'Stable' },
  MONITOR: { color: 'text-amber-600', bg: 'bg-amber-50', border: 'border-amber-200', badge: 'bg-amber-100 text-amber-700', label: 'Monitor' },
  ATTENTION: { color: 'text-orange-600', bg: 'bg-orange-50', border: 'border-orange-200', badge: 'bg-orange-100 text-orange-700', label: 'Attention' },
  CRITICAL: { color: 'text-red-600', bg: 'bg-red-50', border: 'border-red-200', badge: 'bg-red-100 text-red-700', label: 'Critical' },
};

const SEVERITY_CFG = {
  critical: { bg: 'bg-red-50', border: 'border-red-200', text: 'text-red-700', badge: 'bg-red-100 text-red-700 border-red-200' },
  high: { bg: 'bg-orange-50', border: 'border-orange-200', text: 'text-orange-700', badge: 'bg-orange-100 text-orange-700 border-orange-200' },
  medium: { bg: 'bg-amber-50', border: 'border-amber-200', text: 'text-amber-700', badge: 'bg-amber-100 text-amber-700 border-amber-200' },
  low: { bg: 'bg-slate-50', border: 'border-slate-200', text: 'text-slate-600', badge: 'bg-slate-100 text-slate-600 border-slate-200' },
};

function scoreColor(s) {
  if (s >= 90) return '#10b981';
  if (s >= 75) return '#22c55e';
  if (s >= 60) return '#f59e0b';
  if (s >= 40) return '#f97316';
  return '#ef4444';
}

function ScoreRing({ score, size = 64, stroke = 5 }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const off = c * (1 - Math.max(0, Math.min(100, score)) / 100);
  const col = scoreColor(score);
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size/2} cy={size/2} r={r} stroke="#e2e8f0" strokeWidth={stroke} fill="none" />
        <circle cx={size/2} cy={size/2} r={r} stroke={col} strokeWidth={stroke} fill="none"
          strokeDasharray={c} strokeDashoffset={off} strokeLinecap="round"
          className="transition-all duration-1000 ease-out" />
      </svg>
      <span className="absolute text-lg font-bold" style={{ color: col }}>{Math.round(score)}</span>
    </div>
  );
}

function timeAgo(d) {
  if (!d) return '';
  const diff = (Date.now() - new Date(d).getTime()) / 1000;
  if (diff < 5) return 'just now';
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// ── Panels ──

function FleetSafetyPanel({ data, navigate }) {
  if (!data) return null;
  const cfg = STATUS_CFG[data.fleet_status] || STATUS_CFG.MONITOR;
  const bd = data.status_breakdown || {};

  return (
    <Card className={`border-2 ${cfg.border}`} data-testid="cc-fleet-safety">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <Shield className={`w-5 h-5 ${cfg.color}`} />
          <CardTitle className="text-sm">Fleet Safety Score</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <div className="flex items-center gap-5">
          <ScoreRing score={data.fleet_score} size={80} stroke={6} />
          <div className="flex-1">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-2xl font-bold" style={{ color: scoreColor(data.fleet_score) }}>{data.fleet_score}</span>
              <Badge className={`${cfg.badge} border ${cfg.border} text-xs`}>{cfg.label}</Badge>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {bd.critical > 0 && <Badge className="bg-red-100 text-red-700 border border-red-200 text-[10px]">{bd.critical} Critical</Badge>}
              {bd.attention > 0 && <Badge className="bg-orange-100 text-orange-700 border border-orange-200 text-[10px]">{bd.attention} Attention</Badge>}
              {bd.monitor > 0 && <Badge className="bg-amber-100 text-amber-700 border border-amber-200 text-[10px]">{bd.monitor} Monitor</Badge>}
              {bd.stable > 0 && <Badge className="bg-green-100 text-green-700 border border-green-200 text-[10px]">{bd.stable} Stable</Badge>}
              {bd.excellent > 0 && <Badge className="bg-emerald-100 text-emerald-700 border border-emerald-200 text-[10px]">{bd.excellent} Excellent</Badge>}
            </div>
          </div>
        </div>
        {/* Device list (worst first) */}
        <div className="mt-3 space-y-1 max-h-48 overflow-y-auto" data-testid="cc-fleet-devices">
          {data.devices?.map((d) => {
            const s = STATUS_CFG[d.status] || STATUS_CFG.MONITOR;
            return (
              <div key={d.device_id}
                className={`flex items-center gap-2 px-2 py-1.5 rounded border ${s.border} ${s.bg} cursor-pointer hover:shadow-sm transition-shadow`}
                onClick={() => navigate('/operator/device-health')}
                data-testid={`cc-device-${d.device_identifier}`}
              >
                <span className="text-sm font-bold w-8" style={{ color: scoreColor(d.safety_score) }}>{Math.round(d.safety_score)}</span>
                <span className="text-xs font-medium text-slate-700 flex-1">{d.device_identifier}</span>
                <Badge className={`${s.badge} border ${s.border} text-[10px]`}>{s.label}</Badge>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

function PredictiveAlertsPanel({ alerts }) {
  if (!alerts?.length) return (
    <Card className="border border-slate-200" data-testid="cc-predictive-alerts">
      <CardContent className="p-4 text-center text-sm text-slate-400">
        <Zap className="w-5 h-5 mx-auto mb-1 text-slate-300" />No active predictive alerts
      </CardContent>
    </Card>
  );

  return (
    <Card className="border border-amber-200" data-testid="cc-predictive-alerts">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <Zap className="w-5 h-5 text-amber-500" />
          <CardTitle className="text-sm">Predictive Alerts</CardTitle>
          <Badge className="bg-amber-100 text-amber-700 border border-amber-200 text-[10px]">{alerts.length}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-1.5 max-h-64 overflow-y-auto">
        {alerts.map((a, i) => (
          <div key={i} className="flex items-center gap-2 px-3 py-2 rounded-md border border-amber-100 bg-amber-50/50 text-xs"
            data-testid={`cc-alert-${a.device_identifier}`}>
            <AlertTriangle className="w-3.5 h-3.5 text-amber-500 shrink-0" />
            <div className="flex-1 min-w-0">
              <span className="font-semibold text-slate-700">{a.device_identifier}</span>
              <span className="text-slate-500 ml-1.5">{a.prediction_type.replace(/_/g, ' ')}</span>
              <p className="text-[10px] text-slate-400 truncate">{a.explanation}</p>
            </div>
            <Badge className="bg-amber-100 text-amber-700 text-[10px] border border-amber-200 shrink-0">
              {(a.score * 100).toFixed(0)}%
            </Badge>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function ForecastHighlightsPanel({ highlights }) {
  if (!highlights?.length) return (
    <Card className="border border-slate-200" data-testid="cc-forecast-highlights">
      <CardContent className="p-4 text-center text-sm text-slate-400">
        <Clock className="w-5 h-5 mx-auto mb-1 text-slate-300" />No high-risk forecast windows
      </CardContent>
    </Card>
  );

  const highCount = highlights.filter(h => h.risk_level === 'HIGH').length;

  return (
    <Card className={`border ${highCount > 0 ? 'border-red-200' : 'border-amber-200'}`} data-testid="cc-forecast-highlights">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <Clock className="w-5 h-5 text-sky-500" />
          <CardTitle className="text-sm">Risk Forecast (24h)</CardTitle>
          {highCount > 0 && <Badge className="bg-red-100 text-red-700 border border-red-200 text-[10px]">{highCount} HIGH</Badge>}
        </div>
      </CardHeader>
      <CardContent className="space-y-1.5 max-h-64 overflow-y-auto">
        {highlights.map((f, i) => {
          const isHigh = f.risk_level === 'HIGH';
          return (
            <div key={i} className={`flex items-center gap-2 px-3 py-2 rounded-md border text-xs ${isHigh ? 'border-red-200 bg-red-50/50' : 'border-amber-100 bg-amber-50/30'}`}
              data-testid={`cc-forecast-${f.device_identifier}-${f.bucket.toLowerCase().replace(/\s/g,'-')}`}>
              <div className={`w-2 h-2 rounded-full shrink-0 ${isHigh ? 'bg-red-500' : 'bg-amber-400'}`} />
              <span className="font-semibold text-slate-700">{f.device_identifier}</span>
              <span className="text-slate-500">{f.bucket}</span>
              <span className="text-[10px] text-slate-400 font-mono">{String(f.start_hour).padStart(2,'0')}–{String(f.end_hour).padStart(2,'0')}h</span>
              <span className="ml-auto text-slate-400 text-[10px] truncate max-w-[120px]">{f.reason}</span>
              <Badge className={`text-[10px] border shrink-0 ${isHigh ? 'bg-red-100 text-red-700 border-red-200' : 'bg-amber-100 text-amber-700 border-amber-200'}`}>
                {(f.risk_score * 100).toFixed(0)}%
              </Badge>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function EvolutionShiftsPanel({ shifts }) {
  if (!shifts?.length) return (
    <Card className="border border-slate-200" data-testid="cc-evolution-shifts">
      <CardContent className="p-4 text-center text-sm text-slate-400">
        <Heart className="w-5 h-5 mx-auto mb-1 text-slate-300" />No behavioral shifts detected
      </CardContent>
    </Card>
  );

  const highCount = shifts.filter(s => s.severity === 'high').length;

  return (
    <Card className={`border ${highCount > 0 ? 'border-red-200' : 'border-amber-200'}`} data-testid="cc-evolution-shifts">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <Heart className="w-5 h-5 text-rose-500" />
          <CardTitle className="text-sm">Twin Evolution Trends</CardTitle>
          <Badge className="bg-rose-100 text-rose-700 border border-rose-200 text-[10px]">{shifts.length} shift{shifts.length > 1 ? 's' : ''}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-1.5 max-h-64 overflow-y-auto">
        {shifts.map((s, i) => {
          const isHigh = s.severity === 'high';
          return (
            <div key={i} className={`flex items-center gap-2 px-3 py-2 rounded-md border text-xs ${isHigh ? 'border-red-200 bg-red-50/50' : 'border-amber-100 bg-amber-50/30'}`}
              data-testid={`cc-shift-${s.device_identifier}-${s.metric}`}>
              <TrendingDown className={`w-3.5 h-3.5 shrink-0 ${isHigh ? 'text-red-500' : 'text-amber-500'}`} />
              <span className="font-semibold text-slate-700">{s.device_identifier}</span>
              <span className="text-slate-500">{s.label}</span>
              <span className="text-slate-400 font-mono text-[10px]">{s.from_value} → {s.to_value}</span>
              <span className={`ml-auto font-mono text-[10px] font-semibold ${isHigh ? 'text-red-600' : 'text-amber-600'}`}>
                {s.change_percent > 0 ? '+' : ''}{s.change_percent}%
              </span>
              <Badge className={`text-[10px] border shrink-0 ${isHigh ? 'bg-red-100 text-red-700 border-red-200' : 'bg-amber-100 text-amber-700 border-amber-200'}`}>
                {s.weeks_span}w
              </Badge>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function ActiveIncidentsPanel({ incidents, navigate, onReplay }) {
  if (!incidents?.length) return (
    <Card className="border border-slate-200" data-testid="cc-active-incidents">
      <CardContent className="p-4 text-center text-sm text-slate-400">
        <Eye className="w-5 h-5 mx-auto mb-1 text-slate-300" />No active incidents
      </CardContent>
    </Card>
  );

  return (
    <Card className="border border-red-200" data-testid="cc-active-incidents">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-5 h-5 text-red-500" />
            <CardTitle className="text-sm">Active Incidents</CardTitle>
            <Badge className="bg-red-100 text-red-700 border border-red-200 text-[10px]">{incidents.length}</Badge>
          </div>
          <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px] text-slate-500"
            onClick={() => navigate('/operator/incidents')}
            data-testid="cc-view-all-incidents"
          >
            View All <ChevronRight className="w-3 h-3 ml-0.5" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-1.5 max-h-64 overflow-y-auto">
        {incidents.map((inc) => {
          const sev = SEVERITY_CFG[inc.severity] || SEVERITY_CFG.low;
          return (
            <div key={inc.id}
              className={`flex items-center gap-2 px-3 py-2 rounded-md border text-xs ${sev.bg} ${sev.border}`}
              data-testid={`cc-incident-${inc.id}`}
            >
              <div className={`w-2 h-2 rounded-full shrink-0 ${inc.severity === 'critical' ? 'bg-red-500 animate-pulse' : inc.severity === 'high' ? 'bg-orange-500' : 'bg-amber-400'}`} />
              <span className="font-semibold text-slate-700">{inc.device_identifier}</span>
              <span className="text-slate-500">{inc.incident_type.replace(/_/g, ' ')}</span>
              {inc.is_test && <Badge className="bg-slate-100 text-slate-500 text-[9px]">TEST</Badge>}
              <span className="ml-auto text-slate-400 text-[10px]">{timeAgo(inc.created_at)}</span>
              <Badge className={`${sev.badge} text-[10px] border shrink-0`}>{inc.severity}</Badge>
              {inc.escalation_level > 1 && (
                <Badge className="bg-purple-100 text-purple-700 border border-purple-200 text-[10px]">L{inc.escalation_level}</Badge>
              )}
              <button
                onClick={(e) => { e.stopPropagation(); onReplay(inc.id); }}
                className="ml-1 text-[9px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 hover:bg-amber-200 transition-colors border border-amber-200 shrink-0"
                data-testid={`replay-btn-${inc.id}`}
              >
                Replay
              </button>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

// ── Life Pattern Alerts Panel ──

function LifePatternAlertsPanel({ alerts, navigate }) {
  if (!alerts?.length) return (
    <Card className="border border-slate-200" data-testid="cc-life-pattern-alerts">
      <CardContent className="p-4 text-center text-sm text-slate-400">
        <Fingerprint className="w-5 h-5 mx-auto mb-1 text-slate-300" />No routine deviations detected
      </CardContent>
    </Card>
  );

  const highCount = alerts.filter(a => a.severity === 'high').length;

  return (
    <Card className={`border ${highCount > 0 ? 'border-red-200' : 'border-blue-200'}`} data-testid="cc-life-pattern-alerts">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <Fingerprint className="w-5 h-5 text-blue-600" />
          <CardTitle className="text-sm">Life Pattern Alerts</CardTitle>
          <Badge className="bg-blue-100 text-blue-700 border border-blue-200 text-[10px]">{alerts.length}</Badge>
          {highCount > 0 && <Badge className="bg-red-100 text-red-700 border border-red-200 text-[10px]">{highCount} HIGH</Badge>}
        </div>
      </CardHeader>
      <CardContent className="space-y-1.5 max-h-48 overflow-y-auto">
        {alerts.map((a, i) => {
          const isHigh = a.severity === 'high';
          return (
            <div key={i}
              className={`flex items-center gap-2 px-3 py-2 rounded-md border text-xs cursor-pointer hover:shadow-sm transition-shadow ${
                isHigh ? 'border-red-200 bg-red-50/50' : 'border-blue-100 bg-blue-50/30'
              }`}
              onClick={() => navigate('/operator/device-health')}
              data-testid={`cc-lp-alert-${a.device_identifier}-${a.hour}`}
            >
              <div className={`w-2 h-2 rounded-full shrink-0 ${isHigh ? 'bg-red-500' : 'bg-blue-400'}`} />
              <span className="font-semibold text-slate-700">{a.device_identifier}</span>
              <span className="text-slate-500">{a.type.replace(/_/g, ' ')}</span>
              <span className="text-[10px] text-slate-400 font-mono ml-auto">{String(a.hour).padStart(2,'0')}:00</span>
              <Badge className={`text-[10px] border shrink-0 ${isHigh ? 'bg-red-100 text-red-700 border-red-200' : 'bg-blue-100 text-blue-700 border-blue-200'}`}>
                {a.severity}
              </Badge>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

// ── Environmental Status Panel ──

function EnvironmentStatusPanel({ envStatus, navigate }) {
  if (!envStatus?.length) return (
    <Card className="border border-slate-200" data-testid="cc-environment-status">
      <CardContent className="p-4 text-center text-sm text-slate-400">
        <Cloud className="w-5 h-5 mx-auto mb-1 text-slate-300" />No environmental data
      </CardContent>
    </Card>
  );

  const atRisk = envStatus.filter(d => d.environment_score >= 5);
  const moderate = envStatus.filter(d => d.environment_score >= 3 && d.environment_score < 5);

  return (
    <Card className={`border ${atRisk.length > 0 ? 'border-orange-200' : 'border-blue-200'}`}
      data-testid="cc-environment-status">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <Cloud className="w-5 h-5 text-blue-600" />
          <CardTitle className="text-sm">Environmental Risk</CardTitle>
          {atRisk.length > 0 && (
            <Badge className="bg-orange-100 text-orange-700 border border-orange-200 text-[10px]">
              {atRisk.length} At Risk
            </Badge>
          )}
          {moderate.length > 0 && (
            <Badge className="bg-yellow-100 text-yellow-700 border border-yellow-200 text-[10px]">
              {moderate.length} Moderate
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-1.5 max-h-48 overflow-y-auto">
        {envStatus.slice(0, 8).map((d, i) => {
          const color = d.environment_score >= 7 ? 'text-red-600' :
            d.environment_score >= 5 ? 'text-orange-600' :
            d.environment_score >= 3 ? 'text-yellow-600' : 'text-green-600';
          const bg = d.environment_score >= 7 ? 'border-red-200 bg-red-50/30' :
            d.environment_score >= 5 ? 'border-orange-200 bg-orange-50/30' :
            d.environment_score >= 3 ? 'border-yellow-100 bg-yellow-50/30' :
            'border-green-100 bg-green-50/30';
          return (
            <div key={i}
              className={`flex items-center gap-2 px-3 py-2 rounded-md border text-xs cursor-pointer hover:shadow-sm transition-shadow ${bg}`}
              onClick={() => navigate('/operator/device-health')}
              data-testid={`cc-env-${d.device_identifier}`}
            >
              <span className={`text-sm font-bold ${color}`}>{d.environment_score}</span>
              <span className="font-semibold text-slate-700">{d.device_identifier}</span>
              <div className="flex items-center gap-1 text-[10px] text-slate-500 ml-auto">
                <Thermometer className="w-3 h-3" />{d.weather?.temperature}°C
                <Droplets className="w-3 h-3 ml-1" />{d.weather?.humidity}%
                <Wind className="w-3 h-3 ml-1" />{d.weather?.wind_speed}m/s
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

// ── Route Monitor Alerts Panel ──

function RouteMonitorAlertsPanel({ monitors, navigate }) {
  if (!monitors?.length) return (
    <Card className="border border-slate-200" data-testid="cc-route-monitors">
      <CardContent className="p-4 text-center text-sm text-slate-400">
        <Navigation className="w-5 h-5 mx-auto mb-1 text-slate-300" />No active route monitors
      </CardContent>
    </Card>
  );

  const dangerCount = monitors.filter(m => m.alert_level === 'danger' || m.alert_level === 'warning').length;

  return (
    <Card className={`border ${dangerCount > 0 ? 'border-red-200' : 'border-green-200'}`}
      data-testid="cc-route-monitors">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Navigation className="w-5 h-5 text-green-600" />
            <CardTitle className="text-sm">Route Monitors</CardTitle>
            <Badge className="bg-green-100 text-green-700 border border-green-200 text-[10px]">
              {monitors.length} Active
            </Badge>
            {dangerCount > 0 && (
              <Badge className="bg-red-100 text-red-700 border border-red-200 text-[10px] animate-pulse">
                {dangerCount} Alert{dangerCount > 1 ? 's' : ''}
              </Badge>
            )}
          </div>
          <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px] text-slate-500"
            onClick={() => navigate('/operator/route-safety')}
            data-testid="cc-view-route-safety"
          >
            Route Safety <ChevronRight className="w-3 h-3 ml-0.5" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-1.5 max-h-48 overflow-y-auto">
        {monitors.map((m, i) => {
          const isDanger = m.alert_level === 'danger';
          const isWarning = m.alert_level === 'warning';
          const isAlert = isDanger || isWarning;
          const bg = isDanger ? 'border-red-200 bg-red-50/50' :
            isWarning ? 'border-amber-200 bg-amber-50/50' :
            'border-green-100 bg-green-50/30';
          return (
            <div key={i} className={`px-3 py-2 rounded-md border text-xs ${bg}`}
              data-testid={`cc-route-${m.device_identifier}`}>
              <div className="flex items-center gap-2">
                <div className={`w-2 h-2 rounded-full shrink-0 ${
                  isDanger ? 'bg-red-500 animate-pulse' :
                  isWarning ? 'bg-amber-500 animate-pulse' :
                  'bg-green-500'
                }`} />
                <span className="font-semibold text-slate-700">{m.device_identifier}</span>
                <span className="text-slate-400 text-[10px] ml-auto">{m.route_progress}% complete</span>
              </div>
              {m.alert_message && (
                <p className={`mt-1 text-[10px] ${isDanger ? 'text-red-600' : isWarning ? 'text-amber-600' : 'text-slate-500'}`}>
                  {isAlert && <AlertTriangle className="w-3 h-3 inline mr-0.5" />}
                  {m.alert_message}
                </p>
              )}
              {/* Notification status */}
              {m.notification_summary?.has_alerts && (
                <div className="mt-1 flex items-center gap-1 text-[9px]" data-testid={`notif-status-${m.device_identifier}`}>
                  <Radio className="w-2.5 h-2.5 text-blue-500" />
                  <span className="text-blue-600">
                    {m.notification_summary.acknowledged ? 'Acknowledged by guardian' :
                      `Sent to guardian (${m.notification_summary.unacknowledged} pending)`}
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

// ── Refresh tiers (ms) ──
const TIER_CRITICAL = 20_000;  // incidents + risk + monitors
const TIER_FLEET    = 35_000;  // fleet safety
const TIER_ENV      = 60_000;  // environment

// ── Main Command Center ──

export default function CommandCenter() {
  const [fleet, setFleet] = useState(null);
  const [risk, setRisk] = useState(null);
  const [incidents, setIncidents] = useState(null);
  const [env, setEnv] = useState(null);
  const [routeMonitors, setRouteMonitors] = useState(null);
  const [risingHotspots, setRisingHotspots] = useState(null);
  const [forecastStats, setForecastStats] = useState(null);
  const [heatmapStats, setHeatmapStats] = useState(null);
  const [loading, setLoading] = useState({ fleet: true, risk: true, incidents: true, env: true, monitors: true });
  const [refreshing, setRefreshing] = useState(false);
  const [isLive, setIsLive] = useState(true);
  const [isVisible, setIsVisible] = useState(true);
  const [replayIncidentId, setReplayIncidentId] = useState(null);
  const [timestamps, setTimestamps] = useState({ risk: null, incidents: null, fleet: null, env: null, monitors: null });
  const [tick, setTick] = useState(0); // forces re-render for "Xs ago"
  const navigate = useNavigate();

  // Refs for change detection
  const prevData = useRef({});

  // Change-aware setter: skip update if data is identical
  const smartSet = useCallback((key, setter, newData) => {
    const serialized = JSON.stringify(newData);
    if (prevData.current[key] === serialized) return;
    prevData.current[key] = serialized;
    setter(newData);
    setTimestamps(p => ({ ...p, [key]: Date.now() }));
  }, []);

  // Individual tier fetchers (silent — no loading spinners)
  const fetchCritical = useCallback(async () => {
    const calls = [
      operatorApi.getCommandCenterRisk().then(r => { smartSet('risk', setRisk, r.data); setTimestamps(p => ({ ...p, risk: Date.now() })); }).catch(() => {}),
      operatorApi.getCommandCenterIncidents().then(r => { smartSet('incidents', setIncidents, r.data); setTimestamps(p => ({ ...p, incidents: Date.now() })); }).catch(() => {}),
      operatorApi.getActiveRouteMonitors().then(r => { smartSet('monitors', setRouteMonitors, r.data?.monitors || []); setTimestamps(p => ({ ...p, monitors: Date.now() })); }).catch(() => {}),
      operatorApi.getHotspotTrendStats().then(r => { smartSet('hotspots', setRisingHotspots, r.data); }).catch(() => {}),
      operatorApi.getRiskForecastStats().then(r => { smartSet('forecast', setForecastStats, r.data); }).catch(() => {}),
      operatorApi.getCityHeatmapStats().then(r => { smartSet('heatmap', setHeatmapStats, r.data); }).catch(() => {}),
    ];
    await Promise.allSettled(calls);
  }, [smartSet]);

  const fetchFleet = useCallback(async () => {
    operatorApi.getCommandCenterFleet().then(r => { smartSet('fleet', setFleet, r.data); setTimestamps(p => ({ ...p, fleet: Date.now() })); }).catch(() => {});
  }, [smartSet]);

  const fetchEnv = useCallback(async () => {
    operatorApi.getCommandCenterEnvironment().then(r => { smartSet('env', setEnv, r.data); setTimestamps(p => ({ ...p, env: Date.now() })); }).catch(() => {});
  }, [smartSet]);

  // Initial full load (with loading spinners)
  const fetchAll = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading({ fleet: true, risk: true, incidents: true, env: true, monitors: true });

    const now = Date.now();
    const calls = [
      operatorApi.getCommandCenterFleet().then(r => { setFleet(r.data); setLoading(p => ({ ...p, fleet: false })); setTimestamps(p => ({ ...p, fleet: now })); prevData.current.fleet = JSON.stringify(r.data); }),
      operatorApi.getCommandCenterRisk().then(r => { setRisk(r.data); setLoading(p => ({ ...p, risk: false })); setTimestamps(p => ({ ...p, risk: now })); prevData.current.risk = JSON.stringify(r.data); }),
      operatorApi.getCommandCenterIncidents().then(r => { setIncidents(r.data); setLoading(p => ({ ...p, incidents: false })); setTimestamps(p => ({ ...p, incidents: now })); prevData.current.incidents = JSON.stringify(r.data); }),
      operatorApi.getCommandCenterEnvironment().then(r => { setEnv(r.data); setLoading(p => ({ ...p, env: false })); setTimestamps(p => ({ ...p, env: now })); prevData.current.env = JSON.stringify(r.data); }),
      operatorApi.getActiveRouteMonitors().then(r => { setRouteMonitors(r.data?.monitors || []); setLoading(p => ({ ...p, monitors: false })); setTimestamps(p => ({ ...p, monitors: now })); prevData.current.monitors = JSON.stringify(r.data?.monitors || []); }),
      operatorApi.getHotspotTrendStats().then(r => { setRisingHotspots(r.data); prevData.current.hotspots = JSON.stringify(r.data); }).catch(() => {}),
      operatorApi.getRiskForecastStats().then(r => { setForecastStats(r.data); prevData.current.forecast = JSON.stringify(r.data); }).catch(() => {}),
      operatorApi.getCityHeatmapStats().then(r => { setHeatmapStats(r.data); prevData.current.heatmap = JSON.stringify(r.data); }).catch(() => {}),
    ];
    await Promise.allSettled(calls);
    setRefreshing(false);
  }, []);

  // Initial load
  useEffect(() => { fetchAll(); }, [fetchAll]);

  // Tab visibility tracking
  useEffect(() => {
    const handler = () => setIsVisible(document.visibilityState === 'visible');
    document.addEventListener('visibilitychange', handler);
    return () => document.removeEventListener('visibilitychange', handler);
  }, []);

  // Tiered auto-refresh intervals
  useEffect(() => {
    if (!isLive || !isVisible) return;

    const t1 = setInterval(fetchCritical, TIER_CRITICAL);
    const t2 = setInterval(fetchFleet, TIER_FLEET);
    const t3 = setInterval(fetchEnv, TIER_ENV);

    return () => { clearInterval(t1); clearInterval(t2); clearInterval(t3); };
  }, [isLive, isVisible, fetchCritical, fetchFleet, fetchEnv]);

  // Tick every 5s to update "Xs ago" labels
  useEffect(() => {
    const t = setInterval(() => setTick(k => k + 1), 5000);
    return () => clearInterval(t);
  }, []);

  const anyLoading = loading.fleet || loading.risk || loading.incidents || loading.env || loading.monitors;
  const liveStatus = !isLive ? 'paused' : !isVisible ? 'hidden' : 'live';

  // Derive counts
  const counts = {
    active_incidents: incidents?.active_incidents?.length || 0,
    high_risk_windows: risk?.forecast_highlights?.filter(f => f.risk_level === 'HIGH').length || 0,
    evolution_shifts: fleet?.evolution_shifts?.length || 0,
    predictive_alerts: risk?.predictive_alerts?.length || 0,
    critical_devices: (fleet?.fleet_safety?.status_breakdown?.critical || 0) + (fleet?.fleet_safety?.status_breakdown?.attention || 0),
  };

  const PanelLoader = () => (
    <Card className="border border-slate-200">
      <CardContent className="p-6 flex items-center justify-center h-32">
        <Loader2 className="w-5 h-5 animate-spin text-slate-400" />
      </CardContent>
    </Card>
  );

  const RisingHotspotsPanel = ({ data }) => {
    if (!data) return null;
    const { status_counts = {}, priority_counts = {}, zones_needing_attention = 0, total_zones = 0 } = data;
    const TREND_COLORS = { growing: 'text-red-600', emerging: 'text-orange-600', stable: 'text-amber-600', declining: 'text-green-600', dormant: 'text-slate-400' };
    return (
      <Card className="border border-slate-200" data-testid="cc-rising-hotspots">
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-sm font-semibold text-slate-700 flex items-center gap-2">
            <Brain className="w-4 h-4 text-purple-500" /> Risk Hotspot Trends
            {zones_needing_attention > 0 && <Badge className="bg-red-100 text-red-700 text-[10px]">{zones_needing_attention} need attention</Badge>}
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-3">
          <div className="grid grid-cols-5 gap-1 mb-2">
            {['growing', 'emerging', 'stable', 'declining', 'dormant'].map(s => (
              <div key={s} className="text-center">
                <p className={`text-sm font-bold ${TREND_COLORS[s]}`}>{status_counts[s] || 0}</p>
                <p className="text-[9px] text-slate-400 capitalize">{s}</p>
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between text-[10px] text-slate-400 border-t border-slate-100 pt-1.5">
            <span>{total_zones} zones tracked</span>
            <span>P1: {priority_counts['1'] || 0} | P2: {priority_counts['2'] || 0}</span>
            <button onClick={() => navigate('/operator/risk-learning')} className="text-purple-600 hover:underline flex items-center gap-0.5">
              View Trends <ChevronRight className="w-3 h-3" />
            </button>
          </div>
        </CardContent>
      </Card>
    );
  };

  const ForecastPanel = ({ data }) => {
    if (!data) return null;
    const { forecast_counts = {}, priority_counts = {}, p1_predicted_48h = 0, zones_escalating = 0, total_zones = 0, avg_predicted_48h = 0 } = data;
    const FC_COLORS = { escalating: 'text-red-600', emerging: 'text-orange-600', stable: 'text-amber-600', cooling: 'text-green-600' };
    return (
      <Card className={`border ${p1_predicted_48h > 0 ? 'border-red-200' : 'border-slate-200'}`} data-testid="cc-risk-forecast">
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-sm font-semibold text-slate-700 flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-red-500" /> Risk Forecast (72h)
            {p1_predicted_48h > 0 && <Badge className="bg-red-100 text-red-700 text-[10px]">{p1_predicted_48h} will be P1</Badge>}
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-3">
          <div className="grid grid-cols-4 gap-1 mb-2">
            {['escalating', 'emerging', 'stable', 'cooling'].map(s => (
              <div key={s} className="text-center">
                <p className={`text-sm font-bold ${FC_COLORS[s]}`}>{forecast_counts[s] || 0}</p>
                <p className="text-[9px] text-slate-400 capitalize">{s}</p>
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between text-[10px] text-slate-400 border-t border-slate-100 pt-1.5">
            <span>Avg 48h: {avg_predicted_48h}</span>
            <span>P1: {priority_counts['1'] || 0} | P2: {priority_counts['2'] || 0}</span>
            <button onClick={() => navigate('/operator/risk-learning')} className="text-purple-600 hover:underline flex items-center gap-0.5">
              View Forecast <ChevronRight className="w-3 h-3" />
            </button>
          </div>
        </CardContent>
      </Card>
    );
  };

  const CityRiskPanel = ({ data }) => {
    if (!data) return null;
    const { total_zones = 0, critical_zones = 0, high_risk_zones = 0, recent_incidents_7d = 0 } = data;
    const safe_zones = Math.max(0, total_zones - critical_zones - high_risk_zones);
    const total = Math.max(1, total_zones);
    const critPct = Math.round((critical_zones / total) * 100);
    const highPct = Math.round((high_risk_zones / total) * 100);
    const safePct = Math.max(0, 100 - critPct - highPct);

    return (
      <Card className={`border ${critical_zones > 0 ? 'border-red-200' : 'border-slate-200'}`} data-testid="cc-city-risk">
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-sm font-semibold text-slate-700 flex items-center gap-2">
            <Globe className="w-4 h-4 text-indigo-500" /> City Risk Snapshot
            {critical_zones > 0 && <Badge className="bg-red-100 text-red-700 text-[10px]">{critical_zones} Critical</Badge>}
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-3">
          <div className="grid grid-cols-4 gap-1 mb-2">
            <div className="text-center">
              <p className="text-sm font-bold text-red-600">{critical_zones}</p>
              <p className="text-[9px] text-slate-400">Critical</p>
            </div>
            <div className="text-center">
              <p className="text-sm font-bold text-orange-600">{high_risk_zones}</p>
              <p className="text-[9px] text-slate-400">High Risk</p>
            </div>
            <div className="text-center">
              <p className="text-sm font-bold text-green-600">{safe_zones}</p>
              <p className="text-[9px] text-slate-400">Safe</p>
            </div>
            <div className="text-center">
              <p className="text-sm font-bold text-slate-600">{recent_incidents_7d}</p>
              <p className="text-[9px] text-slate-400">Inc (7d)</p>
            </div>
          </div>
          {/* Risk distribution bar */}
          <div className="flex h-2 rounded-full overflow-hidden mb-2">
            {critPct > 0 && <div className="bg-red-500" style={{ width: `${critPct}%` }} title={`Critical: ${critPct}%`} />}
            {highPct > 0 && <div className="bg-orange-400" style={{ width: `${highPct}%` }} title={`High: ${highPct}%`} />}
            {safePct > 0 && <div className="bg-green-400" style={{ width: `${safePct}%` }} title={`Safe: ${safePct}%`} />}
          </div>
          <div className="flex items-center justify-between text-[10px] text-slate-400 border-t border-slate-100 pt-1.5">
            <span>{total_zones} zones monitored</span>
            <button onClick={() => navigate('/operator/city-heatmap')} className="text-indigo-600 hover:underline flex items-center gap-0.5">
              Open Heatmap <ChevronRight className="w-3 h-3" />
            </button>
          </div>
        </CardContent>
      </Card>
    );
  };

  return (
    <div className="space-y-6" data-testid="command-center">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-800 flex items-center gap-2">
            <Brain className="w-6 h-6 text-amber-500" />
            NISCHINT Command Center
          </h2>
          <p className="text-sm text-slate-500 mt-0.5">
            Unified intelligence — what happened, what will happen, what is deteriorating
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Quick stats */}
          <div className="flex gap-2">
            {counts.active_incidents > 0 && (
              <Badge className="bg-red-100 text-red-700 border border-red-200 text-xs px-2 py-1">
                <AlertTriangle className="w-3 h-3 mr-1" />{counts.active_incidents} Active
              </Badge>
            )}
            {counts.high_risk_windows > 0 && (
              <Badge className="bg-amber-100 text-amber-700 border border-amber-200 text-xs px-2 py-1">
                <Clock className="w-3 h-3 mr-1" />{counts.high_risk_windows} HIGH Risk
              </Badge>
            )}
            {counts.evolution_shifts > 0 && (
              <Badge className="bg-rose-100 text-rose-700 border border-rose-200 text-xs px-2 py-1">
                <TrendingDown className="w-3 h-3 mr-1" />{counts.evolution_shifts} Shifts
              </Badge>
            )}
          </div>

          {/* Live/Paused indicator + toggle */}
          <button
            onClick={() => setIsLive(p => !p)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium border transition-colors ${
              liveStatus === 'live'
                ? 'bg-green-50 text-green-700 border-green-200'
                : liveStatus === 'hidden'
                ? 'bg-slate-100 text-slate-500 border-slate-200'
                : 'bg-slate-100 text-slate-500 border-slate-200'
            }`}
            data-testid="cc-live-toggle"
          >
            {liveStatus === 'live' ? (
              <><span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" /> Live</>
            ) : liveStatus === 'hidden' ? (
              <><Pause className="w-3 h-3" /> Tab Hidden</>
            ) : (
              <><Play className="w-3 h-3" /> Paused</>
            )}
          </button>

          <Button variant="outline" size="sm" onClick={() => fetchAll(true)} disabled={refreshing}
            data-testid="cc-refresh">
            <RefreshCw className={`w-4 h-4 mr-1 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Grid layout — panels load independently */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="space-y-4">
          {loading.fleet ? <PanelLoader /> : <FleetSafetyPanel data={fleet?.fleet_safety} navigate={navigate} />}
          {loading.risk ? <PanelLoader /> : <ForecastHighlightsPanel highlights={risk?.forecast_highlights} />}
        </div>
        <div className="space-y-4">
          {loading.incidents ? <PanelLoader /> : <ActiveIncidentsPanel incidents={incidents?.active_incidents} navigate={navigate} onReplay={(id) => setReplayIncidentId(id)} />}
          {loading.risk ? <PanelLoader /> : <PredictiveAlertsPanel alerts={risk?.predictive_alerts} />}
        </div>
      </div>

      {/* Full-width bottom row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
        {loading.fleet ? <PanelLoader /> : <EvolutionShiftsPanel shifts={fleet?.evolution_shifts} />}
        {loading.env ? <PanelLoader /> : <LifePatternAlertsPanel alerts={env?.life_pattern_alerts} navigate={navigate} />}
        {loading.monitors ? <PanelLoader /> : <RouteMonitorAlertsPanel monitors={routeMonitors} navigate={navigate} />}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {loading.env ? <PanelLoader /> : <EnvironmentStatusPanel envStatus={env?.environment_status} navigate={navigate} />}
        <RisingHotspotsPanel data={risingHotspots} />
        <ForecastPanel data={forecastStats} />
        <CityRiskPanel data={heatmapStats} />
      </div>

      {/* Incident Replay Overlay */}
      {replayIncidentId && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-6" data-testid="replay-overlay"
          onClick={(e) => { if (e.target === e.currentTarget) setReplayIncidentId(null); }}>
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-6xl max-h-[90vh] overflow-y-auto p-5">
            <IncidentReplayViewer incidentId={replayIncidentId} onClose={() => setReplayIncidentId(null)} />
          </div>
        </div>
      )}

      {/* Footer — per-panel timestamps */}
      <div className="flex items-center justify-center gap-4 text-[10px] text-slate-400" data-testid="cc-refresh-status">
        <span>Risk {timeAgo(timestamps.risk)}</span>
        <span className="text-slate-300">|</span>
        <span>Fleet {timeAgo(timestamps.fleet)}</span>
        <span className="text-slate-300">|</span>
        <span>Environment {timeAgo(timestamps.env)}</span>
        <span className="text-slate-300">|</span>
        <span>Monitors {timeAgo(timestamps.monitors)}</span>
        <span className="text-slate-300">|</span>
        <span>{fleet?.fleet_safety?.device_count || 0} devices across 13 AI layers</span>
      </div>
    </div>
  );
}
