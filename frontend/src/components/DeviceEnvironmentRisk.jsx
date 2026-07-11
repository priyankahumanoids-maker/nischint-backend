import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { operatorApi } from '../api';
import {
  Loader2, Cloud, Thermometer, Wind, Droplets, Sun,
  RefreshCw, ShieldAlert, Heart, AlertTriangle,
} from 'lucide-react';

const RISK_BG = {
  Critical: 'bg-red-50 border-red-200',
  High: 'bg-orange-50 border-orange-200',
  Moderate: 'bg-yellow-50 border-yellow-200',
  Safe: 'bg-green-50 border-green-200',
};
const RISK_TEXT = {
  Critical: 'text-red-700',
  High: 'text-orange-700',
  Moderate: 'text-yellow-700',
  Safe: 'text-green-700',
};
const RISK_BADGE = {
  Critical: 'bg-red-100 text-red-700 border-red-200',
  High: 'bg-orange-100 text-orange-700 border-orange-200',
  Moderate: 'bg-yellow-100 text-yellow-700 border-yellow-200',
  Safe: 'bg-green-100 text-green-700 border-green-200',
};

const BREAKDOWN_ITEMS = [
  { key: 'heat_index', label: 'Heat', color: '#dc2626', icon: Thermometer },
  { key: 'air_pollution', label: 'Air Quality', color: '#8b5cf6', icon: Cloud },
  { key: 'rain_risk', label: 'Rain', color: '#3b82f6', icon: Droplets },
  { key: 'wind_risk', label: 'Wind', color: '#0ea5e9', icon: Wind },
  { key: 'uv_risk', label: 'UV', color: '#f59e0b', icon: Sun },
];

function WeatherCard({ weather, airQuality }) {
  if (!weather) return null;
  return (
    <div className="grid grid-cols-4 gap-2 mt-3" data-testid="env-weather-card">
      <div className="flex flex-col items-center p-2 bg-slate-50 rounded-lg">
        <Thermometer className="w-4 h-4 text-red-500 mb-0.5" />
        <span className="text-sm font-bold text-slate-800">{weather.temperature}°C</span>
        <span className="text-[9px] text-slate-400">Feels {weather.feels_like}°C</span>
      </div>
      <div className="flex flex-col items-center p-2 bg-slate-50 rounded-lg">
        <Wind className="w-4 h-4 text-blue-500 mb-0.5" />
        <span className="text-sm font-bold text-slate-800">{weather.wind_speed} m/s</span>
        <span className="text-[9px] text-slate-400">{weather.condition}</span>
      </div>
      <div className="flex flex-col items-center p-2 bg-slate-50 rounded-lg">
        <Droplets className="w-4 h-4 text-blue-400 mb-0.5" />
        <span className="text-sm font-bold text-slate-800">{weather.humidity}%</span>
        <span className="text-[9px] text-slate-400">Humidity</span>
      </div>
      <div className="flex flex-col items-center p-2 bg-slate-50 rounded-lg">
        <Cloud className="w-4 h-4 text-purple-500 mb-0.5" />
        <span className="text-sm font-bold text-slate-800">AQI {airQuality?.aqi}</span>
        <span className="text-[9px] text-slate-400">{airQuality?.aqi_label}</span>
      </div>
    </div>
  );
}

function BreakdownBars({ breakdown }) {
  if (!breakdown) return null;
  return (
    <div className="space-y-1 mt-3" data-testid="env-breakdown">
      {BREAKDOWN_ITEMS.map(({ key, label, color, icon: Icon }) => {
        const val = breakdown[key] ?? 0;
        return (
          <div key={key} className="flex items-center gap-1.5">
            <Icon className="w-3 h-3 shrink-0" style={{ color }} />
            <span className="text-[10px] text-slate-500 w-14 shrink-0">{label}</span>
            <div className="flex-1 h-[5px] bg-slate-100 rounded-full overflow-hidden">
              <div className="h-full rounded-full transition-all duration-700"
                style={{ width: `${Math.min(100, val * 10)}%`, backgroundColor: color }} />
            </div>
            <span className="text-[9px] font-mono font-semibold text-slate-600 w-5 text-right">{val}</span>
          </div>
        );
      })}
    </div>
  );
}

export function DeviceEnvironmentRisk({ deviceId, lat, lng }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetch = useCallback(async () => {
    if (!lat || !lng) return;
    setLoading(true);
    try {
      const res = await operatorApi.evaluateEnvironmentRisk(lat, lng);
      setData(res.data);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [lat, lng]);

  useEffect(() => { fetch(); }, [fetch]);

  return (
    <Card className={`border ${data ? RISK_BG[data.risk_level] || 'border-slate-200' : 'border-slate-200'}`}
      data-testid="device-environment-risk">
      <CardHeader className="pb-2 flex-row items-center justify-between space-y-0">
        <div className="flex items-center gap-2">
          <Cloud className="w-4 h-4 text-blue-600" />
          <CardTitle className="text-sm font-semibold text-slate-800">Environmental Risk</CardTitle>
          {data && (
            <Badge variant="outline" className={`text-[10px] ${RISK_BADGE[data.risk_level] || ''}`}>
              {data.risk_level}
            </Badge>
          )}
        </div>
        <Button variant="ghost" size="sm" onClick={fetch} disabled={loading}
          className="h-7 w-7 p-0" data-testid="env-risk-refresh">
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </CardHeader>

      <CardContent className="pt-0">
        {loading && (
          <div className="flex items-center justify-center py-6 gap-2 text-slate-400" data-testid="env-loading">
            <Loader2 className="w-4 h-4 animate-spin" /><span className="text-xs">Fetching live weather...</span>
          </div>
        )}

        {!loading && data && (
          <div>
            {/* Score */}
            <div className="flex items-center gap-3">
              <div className="flex items-baseline gap-1">
                <span className={`text-2xl font-bold ${RISK_TEXT[data.risk_level] || 'text-slate-800'}`}>
                  {data.environment_score}
                </span>
                <span className="text-xs text-slate-400">/ 10</span>
              </div>
              <span className="text-xs text-slate-500">{data.location}</span>
            </div>

            {/* Weather details */}
            <WeatherCard weather={data.weather} airQuality={data.air_quality} />

            {/* Risk breakdown */}
            <BreakdownBars breakdown={data.breakdown} />

            {/* Factors */}
            {data.factors?.length > 0 && data.factors[0] !== "No significant environmental risks" && (
              <div className="mt-2.5 space-y-0.5" data-testid="env-factors">
                <p className="text-[10px] font-semibold text-slate-600 flex items-center gap-1">
                  <AlertTriangle className="w-3 h-3 text-amber-500" />Risk Factors
                </p>
                {data.factors.map((f, i) => (
                  <p key={i} className="text-[10px] text-slate-500 pl-4 flex items-start gap-1">
                    <span className="w-1 h-1 rounded-full bg-amber-400 mt-1.5 shrink-0" />{f}
                  </p>
                ))}
              </div>
            )}

            {/* Recommendations */}
            {data.recommendations?.length > 0 && (
              <div className="mt-2.5 space-y-0.5" data-testid="env-recommendations">
                <p className="text-[10px] font-semibold text-slate-600 flex items-center gap-1">
                  <Heart className="w-3 h-3 text-green-500" />Recommendations
                </p>
                {data.recommendations.map((r, i) => (
                  <p key={i} className="text-[10px] text-slate-500 pl-4 flex items-start gap-1">
                    <ShieldAlert className="w-3 h-3 text-green-400 mt-0.5 shrink-0" />{r}
                  </p>
                ))}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
