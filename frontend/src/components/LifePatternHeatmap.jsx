import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { operatorApi } from '../api';
import { LifePatternLegend } from './LifePatternLegend';
import { LifePatternInsight } from './LifePatternInsight';
import { Loader2, Fingerprint, RefreshCw } from 'lucide-react';

// ── Color system per spec ──
const METRIC_COLORS = {
  sleep:       { base: '#1E88E5', light: '#BBDEFB', dark: '#0D47A1' },
  movement:    { base: '#2ECC71', light: '#C8E6C9', dark: '#1B5E20' },
  interaction: { base: '#F1C40F', light: '#FFF9C4', dark: '#F57F17' },
  location:    { base: '#FF7043', light: '#FFE0B2', dark: '#BF360C' },
  anomaly:     { base: '#E53935', light: '#FFCDD2', dark: '#B71C1C' },
};

const METRIC_ORDER = ['sleep', 'movement', 'interaction', 'location'];
const ALL_METRICS = [...METRIC_ORDER, 'anomaly'];

const DAYS_OPTIONS = [7, 30, 90];

function lerpColor(a, b, t) {
  const ah = parseInt(a.replace('#', ''), 16);
  const bh = parseInt(b.replace('#', ''), 16);
  const ar = (ah >> 16) & 0xff, ag = (ah >> 8) & 0xff, ab = ah & 0xff;
  const br = (bh >> 16) & 0xff, bg = (bh >> 8) & 0xff, bb = bh & 0xff;
  return `rgb(${Math.round(ar + (br - ar) * t)},${Math.round(ag + (bg - ag) * t)},${Math.round(ab + (bb - ab) * t)})`;
}

function probToColor(prob, metric) {
  const c = METRIC_COLORS[metric];
  if (!c) return '#e2e8f0';
  const p = Math.max(0, Math.min(1, prob));
  if (p < 0.5) return lerpColor(c.light, c.base, p / 0.5);
  return lerpColor(c.base, c.dark, (p - 0.5) / 0.5);
}

function hourLabel(h) {
  if (h === 0) return '00';
  return String(h).padStart(2, '0');
}

// ── Tooltip ──
function HeatmapTooltip({ data, x, y }) {
  if (!data) return null;
  return (
    <div
      className="fixed z-50 pointer-events-none"
      style={{ left: x + 12, top: y - 8 }}
    >
      <div className="bg-slate-900 text-white text-[10px] rounded-lg shadow-xl px-3 py-2 space-y-0.5 min-w-[140px]"
        data-testid="heatmap-tooltip">
        <p className="font-semibold border-b border-slate-700 pb-1 mb-1">
          Hour: {hourLabel(data.hour)}:00
        </p>
        {ALL_METRICS.map((m) => (
          <div key={m} className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-sm" style={{ backgroundColor: METRIC_COLORS[m]?.base }} />
              <span className="capitalize">{m}</span>
            </div>
            <span className="font-mono font-semibold">{((data[m] || 0) * 100).toFixed(0)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Heatmap Grid ──
function HeatmapGrid({ heatmap, enabledMetrics }) {
  const [tooltip, setTooltip] = useState(null);

  const visibleMetrics = ALL_METRICS.filter(m => enabledMetrics.includes(m));

  return (
    <div
      className="relative"
      data-testid="life-pattern-heatmap"
      onMouseLeave={() => setTooltip(null)}
    >
      {/* Row labels + Grid */}
      <div className="space-y-1">
        {visibleMetrics.map((metric) => (
          <div key={metric} className="flex items-center gap-1.5" data-testid={`heatmap-row-${metric}`}>
            <span className="text-[10px] font-medium text-slate-500 w-[72px] shrink-0 text-right pr-1 capitalize">
              {metric === 'interaction' ? 'Interact' : metric}
            </span>
            <div className="grid grid-cols-24 gap-[2px] flex-1" style={{ gridTemplateColumns: 'repeat(24, 1fr)' }}>
              {heatmap.map((entry) => {
                const val = entry[metric] || 0;
                const bg = probToColor(val, metric);
                return (
                  <div
                    key={entry.hour}
                    className="h-[36px] rounded-sm cursor-crosshair transition-all hover:ring-2 hover:ring-slate-400 hover:ring-offset-1 hover:z-10"
                    style={{ backgroundColor: bg }}
                    onMouseEnter={(e) => setTooltip({ data: entry, x: e.clientX, y: e.clientY })}
                    onMouseMove={(e) => setTooltip((t) => t ? { ...t, x: e.clientX, y: e.clientY } : null)}
                  />
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Hour axis */}
      <div className="flex items-center gap-1.5 mt-1">
        <span className="w-[72px] shrink-0" />
        <div className="grid flex-1" style={{ gridTemplateColumns: 'repeat(24, 1fr)', gap: '2px' }}>
          {Array.from({ length: 24 }, (_, i) => (
            <span key={i} className="text-center text-[8px] text-slate-400 font-mono">
              {hourLabel(i)}
            </span>
          ))}
        </div>
      </div>

      {/* Color scale hint */}
      <div className="flex items-center gap-2 mt-1 ml-[76px]">
        <span className="text-[9px] text-slate-400">0%</span>
        <div className="flex h-2 flex-1 max-w-[120px] rounded-sm overflow-hidden">
          {[0, 0.25, 0.5, 0.75, 1].map((p, i) => (
            <div key={i} className="flex-1" style={{ backgroundColor: lerpColor('#e2e8f0', '#1e293b', p) }} />
          ))}
        </div>
        <span className="text-[9px] text-slate-400">100%</span>
      </div>

      {tooltip && <HeatmapTooltip {...tooltip} />}
    </div>
  );
}

// ── Main Component ──
export function LifePatternHeatmap({ deviceId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [days, setDays] = useState(30);
  const [enabledMetrics, setEnabledMetrics] = useState([...ALL_METRICS]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await operatorApi.getDeviceLifePattern(deviceId, days);
      setData(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load life pattern');
    } finally {
      setLoading(false);
    }
  }, [deviceId, days]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const toggleMetric = (key) => {
    setEnabledMetrics((prev) =>
      prev.includes(key)
        ? prev.filter((m) => m !== key)
        : [...prev, key]
    );
  };

  return (
    <Card className="border-slate-200" data-testid="life-pattern-graph">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Fingerprint className="w-5 h-5 text-blue-600" />
            <div>
              <CardTitle className="text-sm font-semibold text-slate-800">
                AI Life Pattern Graph
              </CardTitle>
              <p className="text-[10px] text-slate-400 mt-0.5">
                Behavioral fingerprint ({days} days)
              </p>
            </div>
            {data && (
              <Badge variant="outline" className="text-[10px] bg-blue-50 text-blue-700 border-blue-200 ml-2">
                {data.days_observed}d observed
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            {/* Days selector */}
            <div className="flex border border-slate-200 rounded-md overflow-hidden" data-testid="days-selector">
              {DAYS_OPTIONS.map((d) => (
                <button
                  key={d}
                  onClick={() => setDays(d)}
                  className={`px-2.5 py-1 text-[10px] font-medium transition-colors ${
                    days === d
                      ? 'bg-slate-800 text-white'
                      : 'bg-white text-slate-500 hover:bg-slate-50'
                  }`}
                  data-testid={`days-${d}`}
                >
                  {d}d
                </button>
              ))}
            </div>
            <Button
              variant="ghost" size="sm" onClick={fetchData} disabled={loading}
              className="h-7 w-7 p-0" data-testid="life-pattern-refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="pt-1">
        {loading && (
          <div className="flex items-center justify-center py-10 gap-2 text-slate-400" data-testid="life-pattern-loading">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span className="text-xs">Building behavioral fingerprint...</span>
          </div>
        )}

        {error && (
          <div className="text-xs text-red-500 py-6 text-center" data-testid="life-pattern-error">
            {error}
          </div>
        )}

        {!loading && !error && data && (
          <div>
            <LifePatternLegend enabledMetrics={enabledMetrics} onToggle={toggleMetric} />
            <HeatmapGrid heatmap={data.heatmap} enabledMetrics={enabledMetrics} />
            <LifePatternInsight
              fingerprint={data.fingerprint}
              deviations={data.deviations}
              insights={data.insights}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
