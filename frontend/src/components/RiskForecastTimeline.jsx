import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { operatorApi } from '../api';
import {
  Clock, Loader2, AlertTriangle, Shield, Activity,
  Sun, Sunset, Moon, Coffee, CloudMoon,
} from 'lucide-react';

const RISK_STYLES = {
  LOW: { bg: 'bg-emerald-500', bar: 'bg-emerald-400', text: 'text-emerald-700', badge: 'bg-emerald-50 text-emerald-700 border-emerald-200', label: 'LOW' },
  MEDIUM: { bg: 'bg-amber-500', bar: 'bg-amber-400', text: 'text-amber-700', badge: 'bg-amber-50 text-amber-700 border-amber-200', label: 'MEDIUM' },
  HIGH: { bg: 'bg-red-500', bar: 'bg-red-400', text: 'text-red-700', badge: 'bg-red-50 text-red-700 border-red-200', label: 'HIGH' },
};

const BUCKET_ICONS = {
  early_morning: Coffee,
  morning: Sun,
  afternoon: Activity,
  evening: Sunset,
  night: Moon,
  late_night: CloudMoon,
};

const SUGGESTED_ACTIONS = {
  HIGH: [
    { action: 'Check activity level & device connectivity', icon: Activity },
    { action: 'Contact caregiver if no check-in', icon: Shield },
    { action: 'Verify device telemetry is reporting', icon: AlertTriangle },
  ],
};

function ForecastBar({ bucket }) {
  const style = RISK_STYLES[bucket.risk_level] || RISK_STYLES.LOW;
  const Icon = BUCKET_ICONS[bucket.bucket] || Clock;
  const pct = Math.max(bucket.risk_score * 100, 4);

  return (
    <div className="group" data-testid={`forecast-bucket-${bucket.bucket}`}>
      <div className="flex items-center gap-3 py-1.5">
        {/* Label */}
        <div className="flex items-center gap-1.5 w-[110px] shrink-0">
          <Icon className={`w-3.5 h-3.5 ${style.text}`} />
          <span className="text-xs font-medium text-slate-700">{bucket.label}</span>
        </div>

        {/* Time range */}
        <span className="text-[10px] text-slate-400 w-[52px] shrink-0 font-mono">
          {String(bucket.start_hour).padStart(2, '0')}:00–{String(bucket.end_hour).padStart(2, '0')}:00
        </span>

        {/* Bar */}
        <div className="flex-1 h-5 bg-slate-100 rounded-full overflow-hidden relative">
          <div
            className={`h-full rounded-full transition-all duration-700 ease-out ${style.bar}`}
            style={{ width: `${pct}%` }}
          />
          {/* Score overlay */}
          <span className="absolute inset-0 flex items-center justify-end pr-2 text-[10px] font-semibold text-slate-500">
            {(bucket.risk_score * 100).toFixed(0)}%
          </span>
        </div>

        {/* Risk badge */}
        <Badge className={`${style.badge} border text-[10px] w-[62px] justify-center shrink-0`}>
          {style.label}
        </Badge>
      </div>

      {/* Reason (hover/expand) */}
      {bucket.reason && bucket.reason !== 'normal activity expected' && (
        <p className="text-[10px] text-slate-500 ml-[110px] pl-[55px] -mt-0.5 mb-0.5 italic">
          {bucket.reason}
        </p>
      )}
    </div>
  );
}

export function RiskForecastTimeline({ deviceId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchForecast = useCallback(async () => {
    if (!deviceId) return;
    setLoading(true);
    try {
      const res = await operatorApi.getDeviceRiskForecast(deviceId);
      setData(res.data);
    } catch {
      // Forecast is supplementary — silent fail
    } finally {
      setLoading(false);
    }
  }, [deviceId]);

  useEffect(() => { fetchForecast(); }, [fetchForecast]);

  if (loading) {
    return (
      <Card className="border border-sky-100">
        <CardContent className="p-4 flex items-center justify-center gap-2 text-slate-400">
          <Loader2 className="w-4 h-4 animate-spin" /> Generating risk forecast...
        </CardContent>
      </Card>
    );
  }

  if (!data || !data.buckets) return null;

  const { buckets, summary } = data;
  const hasHighRisk = summary?.high_risk_count > 0;
  const hasMediumRisk = summary?.medium_risk_count > 0;

  return (
    <Card
      className={`border ${hasHighRisk ? 'border-red-200 bg-gradient-to-br from-white to-red-50/20' : hasMediumRisk ? 'border-amber-200 bg-gradient-to-br from-white to-amber-50/20' : 'border-slate-200'}`}
      data-testid="risk-forecast-card"
    >
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-sky-600" />
            <CardTitle className="text-sm">Next 24h Safety Forecast</CardTitle>
            {hasHighRisk && (
              <Badge variant="outline" className="text-[10px] bg-red-100 text-red-700 border-red-300">
                <AlertTriangle className="w-2.5 h-2.5 mr-0.5" />
                {summary.high_risk_count} HIGH risk window{summary.high_risk_count > 1 ? 's' : ''}
              </Badge>
            )}
            {!hasHighRisk && hasMediumRisk && (
              <Badge variant="outline" className="text-[10px] bg-amber-100 text-amber-700 border-amber-300">
                {summary.medium_risk_count} elevated
              </Badge>
            )}
          </div>
          <span className="text-[10px] text-slate-400">
            {data.cached ? 'cached' : 'fresh'} - {data.device_identifier}
          </span>
        </div>
      </CardHeader>

      <CardContent className="space-y-0 pb-3">
        {/* Timeline bars */}
        <div className="space-y-0" data-testid="forecast-timeline">
          {buckets.map((b) => (
            <ForecastBar key={b.bucket} bucket={b} />
          ))}
        </div>

        {/* Suggested actions for HIGH risk */}
        {hasHighRisk && (
          <div className="mt-3 pt-3 border-t border-red-100" data-testid="forecast-actions">
            <p className="text-xs font-semibold text-red-700 mb-1.5 flex items-center gap-1">
              <AlertTriangle className="w-3 h-3" /> Suggested Actions
            </p>
            <div className="space-y-1">
              {SUGGESTED_ACTIONS.HIGH.map((a, i) => {
                const AIcon = a.icon;
                return (
                  <div key={i} className="flex items-center gap-2 text-xs text-slate-600 px-2 py-1 bg-red-50/50 rounded border border-red-100">
                    <AIcon className="w-3 h-3 text-red-400 shrink-0" />
                    {a.action}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Peak risk summary */}
        {summary && (
          <div className="mt-2 pt-2 border-t border-slate-100 flex items-center justify-between">
            <span className="text-[10px] text-slate-400">
              Peak: {summary.peak_risk_bucket} ({(summary.peak_risk_score * 100).toFixed(0)}%)
            </span>
            <span className="text-[10px] text-slate-400">
              {new Date(data.generated_at).toLocaleTimeString()}
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default RiskForecastTimeline;
