import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { operatorApi } from '../api';
import { useNavigate } from 'react-router-dom';
import {
  Shield, Loader2, AlertTriangle, ChevronRight,
  Heart, Activity, TrendingDown,
} from 'lucide-react';

const STATUS_CONFIG = {
  EXCELLENT: { color: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200', badge: 'bg-emerald-100 text-emerald-700', ring: 'ring-emerald-400', label: 'Excellent' },
  STABLE: { color: 'text-green-600', bg: 'bg-green-50', border: 'border-green-200', badge: 'bg-green-100 text-green-700', ring: 'ring-green-400', label: 'Stable' },
  MONITOR: { color: 'text-amber-600', bg: 'bg-amber-50', border: 'border-amber-200', badge: 'bg-amber-100 text-amber-700', ring: 'ring-amber-400', label: 'Monitor' },
  ATTENTION: { color: 'text-orange-600', bg: 'bg-orange-50', border: 'border-orange-200', badge: 'bg-orange-100 text-orange-700', ring: 'ring-orange-400', label: 'Attention' },
  CRITICAL: { color: 'text-red-600', bg: 'bg-red-50', border: 'border-red-200', badge: 'bg-red-100 text-red-700', ring: 'ring-red-400', label: 'Critical' },
};

function scoreColor(score) {
  if (score >= 90) return 'text-emerald-600';
  if (score >= 75) return 'text-green-600';
  if (score >= 60) return 'text-amber-600';
  if (score >= 40) return 'text-orange-600';
  return 'text-red-600';
}

function ScoreRing({ score, size = 56, stroke = 5 }) {
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const pct = Math.max(0, Math.min(100, score)) / 100;
  const offset = circumference * (1 - pct);
  const color = score >= 90 ? '#10b981' : score >= 75 ? '#22c55e' : score >= 60 ? '#f59e0b' : score >= 40 ? '#f97316' : '#ef4444';

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} stroke="#e2e8f0" strokeWidth={stroke} fill="none" />
        <circle cx={size / 2} cy={size / 2} r={radius} stroke={color} strokeWidth={stroke} fill="none"
          strokeDasharray={circumference} strokeDashoffset={offset}
          strokeLinecap="round" className="transition-all duration-1000 ease-out" />
      </svg>
      <span className={`absolute text-sm font-bold ${scoreColor(score)}`}>{Math.round(score)}</span>
    </div>
  );
}

function DeviceRow({ device }) {
  const navigate = useNavigate();
  const cfg = STATUS_CONFIG[device.status] || STATUS_CONFIG.MONITOR;

  return (
    <div
      className={`flex items-center gap-3 px-3 py-2 rounded-lg border ${cfg.border} ${cfg.bg} cursor-pointer hover:shadow-sm transition-shadow`}
      onClick={() => navigate('/operator/device-health')}
      data-testid={`fleet-safety-device-${device.device_identifier}`}
    >
      <ScoreRing score={device.safety_score} size={40} stroke={4} />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-slate-800 truncate">{device.device_identifier}</p>
      </div>
      <Badge className={`${cfg.badge} text-[10px] border ${cfg.border}`}>{cfg.label}</Badge>
      <ChevronRight className="w-3.5 h-3.5 text-slate-400" />
    </div>
  );
}

export function FleetSafetyScore() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchFleet = useCallback(async () => {
    setLoading(true);
    try {
      const res = await operatorApi.getFleetSafety();
      setData(res.data);
    } catch {
      // supplementary — silent fail
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchFleet(); }, [fetchFleet]);

  if (loading) {
    return (
      <Card className="border border-slate-200">
        <CardContent className="p-6 flex items-center justify-center gap-2 text-slate-400">
          <Loader2 className="w-4 h-4 animate-spin" /> Computing fleet safety...
        </CardContent>
      </Card>
    );
  }

  if (!data) return null;

  const { fleet_score, fleet_status, devices, status_breakdown } = data;
  const cfg = STATUS_CONFIG[fleet_status] || STATUS_CONFIG.MONITOR;
  const hasIssues = (status_breakdown?.critical || 0) + (status_breakdown?.attention || 0) > 0;

  return (
    <Card
      className={`border ${hasIssues ? 'border-orange-200 bg-gradient-to-br from-white to-orange-50/20' : 'border-slate-200'}`}
      data-testid="fleet-safety-card"
    >
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Shield className="w-5 h-5 text-sky-600" />
            <CardTitle className="text-base">Fleet Safety Index</CardTitle>
          </div>
          <span className="text-[10px] text-slate-400">{data.device_count} devices</span>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Fleet Average Score */}
        <div className="flex items-center gap-5" data-testid="fleet-safety-score">
          <ScoreRing score={fleet_score} size={72} stroke={6} />
          <div>
            <p className="text-sm font-semibold text-slate-700">Fleet Average</p>
            <Badge className={`${cfg.badge} border ${cfg.border} text-xs mt-1`}>{cfg.label}</Badge>
          </div>
          {/* Status breakdown pills */}
          <div className="ml-auto flex gap-1.5 flex-wrap justify-end">
            {status_breakdown?.critical > 0 && (
              <Badge className="bg-red-100 text-red-700 border border-red-200 text-[10px]">
                <AlertTriangle className="w-2.5 h-2.5 mr-0.5" /> {status_breakdown.critical} Critical
              </Badge>
            )}
            {status_breakdown?.attention > 0 && (
              <Badge className="bg-orange-100 text-orange-700 border border-orange-200 text-[10px]">
                {status_breakdown.attention} Attention
              </Badge>
            )}
            {status_breakdown?.monitor > 0 && (
              <Badge className="bg-amber-100 text-amber-700 border border-amber-200 text-[10px]">
                {status_breakdown.monitor} Monitor
              </Badge>
            )}
            {status_breakdown?.stable > 0 && (
              <Badge className="bg-green-100 text-green-700 border border-green-200 text-[10px]">
                {status_breakdown.stable} Stable
              </Badge>
            )}
            {status_breakdown?.excellent > 0 && (
              <Badge className="bg-emerald-100 text-emerald-700 border border-emerald-200 text-[10px]">
                {status_breakdown.excellent} Excellent
              </Badge>
            )}
          </div>
        </div>

        {/* Device List */}
        <div className="space-y-1.5" data-testid="fleet-safety-devices">
          {devices?.map((d) => (
            <DeviceRow key={d.device_id} device={d} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export default FleetSafetyScore;
