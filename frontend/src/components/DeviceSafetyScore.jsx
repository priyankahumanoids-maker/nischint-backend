import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { operatorApi } from '../api';
import {
  Shield, Loader2, TrendingDown, Activity, Clock, Eye,
  AlertTriangle, Cpu, Radio,
} from 'lucide-react';

const STATUS_CONFIG = {
  EXCELLENT: { color: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200', badge: 'bg-emerald-100 text-emerald-700', label: 'Excellent' },
  STABLE: { color: 'text-green-600', bg: 'bg-green-50', border: 'border-green-200', badge: 'bg-green-100 text-green-700', label: 'Stable' },
  MONITOR: { color: 'text-amber-600', bg: 'bg-amber-50', border: 'border-amber-200', badge: 'bg-amber-100 text-amber-700', label: 'Monitor' },
  ATTENTION: { color: 'text-orange-600', bg: 'bg-orange-50', border: 'border-orange-200', badge: 'bg-orange-100 text-orange-700', label: 'Attention' },
  CRITICAL: { color: 'text-red-600', bg: 'bg-red-50', border: 'border-red-200', badge: 'bg-red-100 text-red-700', label: 'Critical' },
};

const CONTRIBUTOR_META = {
  predictive_risk: { label: 'Predictive Risk', icon: TrendingDown, weight: 25 },
  anomaly_factor: { label: 'Active Anomalies', icon: AlertTriangle, weight: 20 },
  forecast_peak_risk: { label: 'Forecast Peak', icon: Clock, weight: 20 },
  twin_deviation: { label: 'Twin Deviation', icon: Cpu, weight: 15 },
  device_instability: { label: 'Device Stability', icon: Radio, weight: 20 },
};

function scoreColor(score) {
  if (score >= 90) return 'text-emerald-600';
  if (score >= 75) return 'text-green-600';
  if (score >= 60) return 'text-amber-600';
  if (score >= 40) return 'text-orange-600';
  return 'text-red-600';
}

function ScoreGauge({ score, size = 80 }) {
  const radius = (size - 8) / 2;
  const circumference = Math.PI * radius; // Half circle
  const pct = Math.max(0, Math.min(100, score)) / 100;
  const offset = circumference * (1 - pct);
  const color = score >= 90 ? '#10b981' : score >= 75 ? '#22c55e' : score >= 60 ? '#f59e0b' : score >= 40 ? '#f97316' : '#ef4444';

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} stroke="#e2e8f0" strokeWidth={6} fill="none" />
        <circle cx={size / 2} cy={size / 2} r={radius} stroke={color} strokeWidth={6} fill="none"
          strokeDasharray={circumference * 2} strokeDashoffset={offset * 2}
          strokeLinecap="round" className="transition-all duration-1000 ease-out" />
      </svg>
      <div className="absolute flex flex-col items-center">
        <span className={`text-xl font-bold ${scoreColor(score)}`}>{Math.round(score)}</span>
        <span className="text-[9px] text-slate-400 -mt-0.5">/ 100</span>
      </div>
    </div>
  );
}

function ContributorBar({ name, value, meta }) {
  const penalty = value * meta.weight;
  const severity = value >= 0.7 ? 'bg-red-400' : value >= 0.4 ? 'bg-amber-400' : value >= 0.1 ? 'bg-sky-400' : 'bg-emerald-400';
  const Icon = meta.icon;

  return (
    <div className="flex items-center gap-2 text-xs" data-testid={`contributor-${name}`}>
      <Icon className="w-3 h-3 text-slate-400 shrink-0" />
      <span className="w-[100px] text-slate-600 shrink-0">{meta.label}</span>
      <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${severity} transition-all duration-500`}
          style={{ width: `${Math.max(value * 100, 2)}%` }} />
      </div>
      <span className="w-8 text-right text-slate-500 font-mono">{penalty > 0 ? `-${penalty.toFixed(0)}` : '0'}</span>
    </div>
  );
}

export function DeviceSafetyScore({ deviceId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchScore = useCallback(async () => {
    if (!deviceId) return;
    setLoading(true);
    try {
      const res = await operatorApi.getDeviceSafetyScore(deviceId);
      setData(res.data);
    } catch {
      // supplementary
    } finally {
      setLoading(false);
    }
  }, [deviceId]);

  useEffect(() => { fetchScore(); }, [fetchScore]);

  if (loading) {
    return (
      <Card className="border border-slate-200">
        <CardContent className="p-4 flex items-center justify-center gap-2 text-slate-400">
          <Loader2 className="w-4 h-4 animate-spin" /> Calculating safety score...
        </CardContent>
      </Card>
    );
  }

  if (!data) return null;

  const cfg = STATUS_CONFIG[data.status] || STATUS_CONFIG.MONITOR;
  const contrib = data.contributors || {};

  return (
    <Card className={`border ${cfg.border}`} data-testid="device-safety-score-card">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Shield className={`w-4 h-4 ${cfg.color}`} />
            <CardTitle className="text-sm">Safety Score</CardTitle>
          </div>
          <Badge className={`${cfg.badge} border ${cfg.border} text-[10px]`}>{cfg.label}</Badge>
        </div>
      </CardHeader>

      <CardContent>
        <div className="flex items-start gap-5">
          {/* Score gauge */}
          <ScoreGauge score={data.safety_score} />

          {/* Contributors */}
          <div className="flex-1 space-y-1.5" data-testid="safety-contributors">
            <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Top Contributors</p>
            {Object.entries(CONTRIBUTOR_META).map(([key, meta]) => {
              const val = key === 'anomaly_factor' ? (contrib.anomaly_factor ?? 0) : (contrib[key] ?? 0);
              return <ContributorBar key={key} name={key} value={val} meta={meta} />;
            })}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between mt-3 pt-2 border-t border-slate-100">
          <span className="text-[10px] text-slate-400">
            {data.cached ? 'cached' : 'fresh'} - {data.device_identifier}
          </span>
          <span className="text-[10px] text-slate-400">
            {data.generated_at ? new Date(data.generated_at).toLocaleTimeString() : ''}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

export default DeviceSafetyScore;
