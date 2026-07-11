// Phase 6 — Weather Chip
//
// Compact chip that surfaces the selected user's current weather + impact
// band. Source: unified endpoint `environment.weather` + `environment.impact`.
// Renders nothing when source !== 'openweather' so the UI never blocks on
// missing data.

import React from 'react';
import {
  Sun, Cloud, CloudRain, CloudSnow, CloudLightning, CloudFog, Wind,
} from 'lucide-react';

const ICON_MAP = {
  clear: Sun,
  clouds: Cloud,
  rain: CloudRain,
  drizzle: CloudRain,
  snow: CloudSnow,
  thunderstorm: CloudLightning,
  mist: CloudFog,
  fog: CloudFog,
  haze: CloudFog,
  smoke: CloudFog,
};

const IMPACT_STYLES = {
  low:    { bg: 'bg-emerald-500/15', border: 'border-emerald-500/30', text: 'text-emerald-300' },
  medium: { bg: 'bg-amber-500/15',   border: 'border-amber-500/30',   text: 'text-amber-300'   },
  high:   { bg: 'bg-rose-500/15',    border: 'border-rose-500/40',    text: 'text-rose-300'    },
};

/**
 * @param {Object} environment - the `environment` slice of the unified payload
 */
export const WeatherChip = ({ environment }) => {
  const w = environment?.weather;
  if (!w || w.source !== 'openweather') return null;

  const impact = environment?.impact || 'low';
  const styles = IMPACT_STYLES[impact] || IMPACT_STYLES.low;
  const Icon = ICON_MAP[(w.condition || '').toLowerCase()] || Wind;
  const label = w.description || w.condition || 'Weather';
  const tempLabel = typeof w.temp_c === 'number' ? `${Math.round(w.temp_c)}°C` : '';

  return (
    <div
      data-testid="weather-chip"
      className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md border ${styles.bg} ${styles.border}`}
      title={[
        label,
        tempLabel,
        typeof w.wind_kmh === 'number' ? `${w.wind_kmh} km/h wind` : null,
        typeof w.visibility_m === 'number' ? `${(w.visibility_m / 1000).toFixed(1)} km vis` : null,
      ].filter(Boolean).join(' · ')}
    >
      <Icon className={`w-3 h-3 ${styles.text}`} />
      <span className={`text-[10px] font-semibold capitalize ${styles.text}`}>
        {label}
      </span>
      {tempLabel && (
        <span className="text-[10px] text-slate-400 font-mono">{tempLabel}</span>
      )}
      <span
        data-testid="weather-chip-impact"
        className={`text-[9px] font-bold tracking-wider px-1 py-0.5 rounded ${styles.bg} ${styles.text} border ${styles.border}`}
      >
        {impact.toUpperCase()}
      </span>
    </div>
  );
};
