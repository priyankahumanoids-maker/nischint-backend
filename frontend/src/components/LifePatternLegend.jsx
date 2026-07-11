import React from 'react';

const METRICS = [
  { key: 'sleep', label: 'Sleep', color: '#1E88E5' },
  { key: 'movement', label: 'Movement', color: '#2ECC71' },
  { key: 'interaction', label: 'Interaction', color: '#F1C40F' },
  { key: 'location', label: 'Location', color: '#FF7043' },
  { key: 'anomaly', label: 'Anomaly', color: '#E53935' },
];

export function LifePatternLegend({ enabledMetrics, onToggle }) {
  return (
    <div className="flex flex-wrap items-center gap-3 mb-3" data-testid="life-pattern-legend">
      {METRICS.map(({ key, label, color }) => {
        const active = enabledMetrics.includes(key);
        return (
          <button
            key={key}
            onClick={() => onToggle(key)}
            className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium border transition-all cursor-pointer select-none ${
              active
                ? 'border-slate-300 bg-white shadow-sm'
                : 'border-transparent bg-slate-100 opacity-50'
            }`}
            data-testid={`legend-toggle-${key}`}
          >
            <span
              className="w-3 h-3 rounded-sm shrink-0"
              style={{ backgroundColor: active ? color : '#94a3b8' }}
            />
            {label}
          </button>
        );
      })}
    </div>
  );
}
