import React from 'react';
import { Sun, Activity, Coffee, Moon, Zap, AlertTriangle } from 'lucide-react';

function StabilityGauge({ value }) {
  const size = 56;
  const stroke = 5;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, value));
  const offset = c * (1 - pct / 100);
  const color = pct >= 75 ? '#10b981' : pct >= 50 ? '#f59e0b' : '#ef4444';

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}
      data-testid="stability-gauge">
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size/2} cy={size/2} r={r} stroke="#e2e8f0" strokeWidth={stroke} fill="none" />
        <circle cx={size/2} cy={size/2} r={r} stroke={color} strokeWidth={stroke} fill="none"
          strokeDasharray={c} strokeDashoffset={offset} strokeLinecap="round"
          className="transition-all duration-1000 ease-out" />
      </svg>
      <span className="absolute text-sm font-bold" style={{ color }}>{pct}%</span>
    </div>
  );
}

export function LifePatternInsight({ fingerprint, deviations, insights }) {
  if (!fingerprint) return null;

  const landmarks = [
    { icon: Sun, label: 'Wake-up pattern', value: `~${fingerprint.wake_time}`, color: 'text-amber-600' },
    { icon: Activity, label: 'Peak activity', value: fingerprint.peak_activity_time, color: 'text-green-600' },
    { icon: Coffee, label: 'Rest window', value: `~${fingerprint.rest_window_time}`, color: 'text-orange-500' },
    { icon: Moon, label: 'Sleep start', value: `~${fingerprint.sleep_time}`, color: 'text-blue-600' },
  ];

  return (
    <div className="mt-4 space-y-4" data-testid="life-pattern-insight-panel">
      {/* Fingerprint + Gauge */}
      <div className="flex items-start gap-4">
        <StabilityGauge value={fingerprint.routine_stability} />
        <div className="flex-1">
          <p className="text-xs font-semibold text-slate-700 mb-1.5">AI Behavioral Summary</p>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1">
            {landmarks.map(({ icon: Icon, label, value, color }) => (
              <div key={label} className="flex items-center gap-1.5 text-xs">
                <Icon className={`w-3.5 h-3.5 ${color} shrink-0`} />
                <span className="text-slate-500">{label}:</span>
                <span className="font-semibold text-slate-700">{value}</span>
              </div>
            ))}
          </div>
          <div className="mt-1.5 flex items-center gap-2">
            <span className="text-[10px] text-slate-400">Routine stability:</span>
            <span className={`text-xs font-semibold ${
              fingerprint.routine_stability >= 75 ? 'text-emerald-600' :
              fingerprint.routine_stability >= 50 ? 'text-amber-600' : 'text-red-600'
            }`}>
              {fingerprint.routine_stability}% — {fingerprint.routine_stability_label}
            </span>
          </div>
        </div>
      </div>

      {/* Deviations */}
      {deviations?.length > 0 && (
        <div data-testid="life-pattern-deviations">
          <p className="text-xs font-semibold text-slate-600 flex items-center gap-1 mb-1">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
            Today's Deviations ({deviations.length})
          </p>
          {deviations.slice(0, 4).map((d, i) => (
            <div key={i} className="flex items-start gap-2 pl-5 text-[11px] py-0.5">
              <span className={`mt-0.5 w-1.5 h-1.5 rounded-full shrink-0 ${
                d.type === 'missing_activity' ? 'bg-red-400' : 'bg-amber-400'
              }`} />
              <span className="text-slate-600">{d.description}</span>
            </div>
          ))}
        </div>
      )}

      {/* Insights */}
      {insights?.length > 0 && (
        <div data-testid="life-pattern-insights">
          <p className="text-xs font-semibold text-slate-600 flex items-center gap-1 mb-1">
            <Zap className="w-3.5 h-3.5 text-blue-500" />
            AI Insights
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-0.5 pl-5">
            {insights.map((insight, i) => (
              <span key={i} className="text-[11px] text-slate-500 flex items-start gap-1.5">
                <span className="w-1 h-1 rounded-full bg-blue-400 mt-1.5 shrink-0" />
                {insight}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
