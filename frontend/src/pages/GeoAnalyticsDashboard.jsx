import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Shield, Eye, MousePointer, TrendingUp, MapPin, Tag, Layers, RefreshCw, Loader2, Clock, Globe, Zap, AlertTriangle, ArrowUpRight, Lightbulb, Trophy, Target } from 'lucide-react';

const API_BASE = '';  // same-origin — no CORS, no stale baked-URL risk

const TYPE_COLORS = { women: '#f43f5e', kids: '#3b82f6', family: '#10b981' };
const TYPE_LABELS = { women: 'Women Safety', kids: 'Kids Safety', family: 'Family Safety' };
const VARIANT_COLORS = { default: '#6366f1', best: '#f59e0b', personal: '#ec4899' };

function StatCard({ label, value, sub, icon: Icon, accent }) {
  return (
    <div className="p-5 rounded-2xl bg-white/[0.03] border border-slate-800/50" data-testid={`stat-${label.toLowerCase().replace(/\s/g, '-')}`}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs text-slate-500 uppercase tracking-wider font-medium">{label}</span>
        <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ backgroundColor: `${accent}18` }}>
          <Icon className="w-4 h-4" style={{ color: accent }} />
        </div>
      </div>
      <p className="text-2xl font-bold text-white">{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-1">{sub}</p>}
    </div>
  );
}

function BarRow({ label, value, maxValue, accent, suffix }) {
  const pct = maxValue > 0 ? (value / maxValue) * 100 : 0;
  return (
    <div className="flex items-center gap-3">
      <span className="w-28 text-sm text-slate-400 truncate text-right">{label}</span>
      <div className="flex-1 h-7 bg-white/[0.03] rounded-lg overflow-hidden relative">
        <div className="h-full rounded-lg transition-all duration-500 ease-out" style={{ width: `${Math.max(pct, 3)}%`, backgroundColor: accent }} />
        <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-slate-300 font-medium">{value}{suffix || ''}</span>
      </div>
    </div>
  );
}

function ConversionTable({ data, labelKey, labelTitle }) {
  if (!data || data.length === 0) return <p className="text-sm text-slate-500 text-center py-6">No conversion data yet</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-800/40">
            <th className="text-left text-xs text-slate-500 font-medium pb-2 uppercase tracking-wider">{labelTitle}</th>
            <th className="text-right text-xs text-slate-500 font-medium pb-2 uppercase tracking-wider">Views</th>
            <th className="text-right text-xs text-slate-500 font-medium pb-2 uppercase tracking-wider">Clicks</th>
            <th className="text-right text-xs text-slate-500 font-medium pb-2 uppercase tracking-wider">CVR</th>
          </tr>
        </thead>
        <tbody>
          {data.map((r, i) => (
            <tr key={i} className="border-b border-slate-800/20">
              <td className="py-2.5 text-slate-300 font-medium">{r[labelKey]}</td>
              <td className="py-2.5 text-right text-slate-400">{r.views}</td>
              <td className="py-2.5 text-right text-slate-400">{r.clicks}</td>
              <td className="py-2.5 text-right">
                <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${r.rate > 10 ? 'bg-emerald-500/15 text-emerald-400' : r.rate > 0 ? 'bg-amber-500/15 text-amber-400' : 'bg-slate-700/30 text-slate-500'}`}>
                  {r.rate}%
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TrendChart({ data, days }) {
  if (!data || Object.keys(data).length === 0) return <p className="text-sm text-slate-500 text-center py-8">No trend data yet</p>;
  const today = new Date();
  const allDays = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    allDays.push(d.toISOString().split('T')[0]);
  }
  const viewsArr = allDays.map(d => data[d]?.geo_page_view || 0);
  const clicksArr = allDays.map(d => data[d]?.geo_cta_click || 0);
  const maxVal = Math.max(...viewsArr, ...clicksArr, 1);
  const h = 120;
  const w = allDays.length > 1 ? allDays.length - 1 : 1;
  const toPath = (arr) => arr.map((v, i) => `${i === 0 ? 'M' : 'L'}${(i / w) * 100},${h - (v / maxVal) * (h - 20)}`).join(' ');

  return (
    <div data-testid="geo-trend-chart">
      <svg viewBox={`0 0 100 ${h}`} className="w-full" preserveAspectRatio="none" style={{ height: 140 }}>
        <path d={toPath(viewsArr)} fill="none" stroke="#6366f1" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
        <path d={toPath(clicksArr)} fill="none" stroke="#10b981" strokeWidth="1.5" strokeDasharray="4 2" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="flex justify-between mt-1 px-1">
        <span className="text-[10px] text-slate-600">{allDays[0]?.slice(5)}</span>
        <span className="text-[10px] text-slate-600">{allDays[allDays.length - 1]?.slice(5)}</span>
      </div>
      <div className="flex items-center gap-4 mt-2 justify-center">
        <div className="flex items-center gap-1.5"><div className="w-3 h-0.5 bg-indigo-500 rounded" /><span className="text-[11px] text-slate-500">Views</span></div>
        <div className="flex items-center gap-1.5"><div className="w-3 h-0.5 bg-emerald-500 rounded" /><span className="text-[11px] text-slate-500">CTA Clicks</span></div>
      </div>
    </div>
  );
}

function RecentEvents({ events }) {
  if (!events || events.length === 0) return <p className="text-sm text-slate-500 text-center py-6">No events recorded yet</p>;
  return (
    <div className="space-y-1.5 max-h-72 overflow-y-auto">
      {events.map((ev, i) => (
        <div key={i} className="flex items-center gap-3 py-2 px-3 rounded-lg bg-white/[0.02] hover:bg-white/[0.04] transition-colors">
          <div className={`w-2 h-2 rounded-full shrink-0 ${ev.event === 'geo_cta_click' ? 'bg-emerald-400' : 'bg-indigo-400'}`} />
          <div className="flex-1 min-w-0">
            <span className="text-xs text-slate-300 font-medium">{ev.event === 'geo_cta_click' ? 'CTA Click' : 'Page View'}</span>
            {ev.city && <span className="text-xs text-slate-500 ml-2">{ev.city}</span>}
            {ev.variant && ev.variant !== 'default' && <span className="text-xs text-amber-400/70 ml-1.5">({ev.variant})</span>}
          </div>
          <span className="text-[10px] text-slate-600 shrink-0">{ev.created_at ? new Date(ev.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}</span>
        </div>
      ))}
    </div>
  );
}

const ACTION_STYLES = {
  scale: { bg: 'bg-emerald-500/15', text: 'text-emerald-400', label: 'Scale', icon: ArrowUpRight },
  test_more: { bg: 'bg-amber-500/15', text: 'text-amber-400', label: 'Test More', icon: Zap },
  optimize: { bg: 'bg-red-500/15', text: 'text-red-400', label: 'Optimize', icon: AlertTriangle },
};

function VariantPerformanceTable({ vpData }) {
  if (!vpData || Object.keys(vpData).length === 0) return <p className="text-sm text-slate-500 text-center py-6">No variant performance data yet</p>;
  const allVariants = new Set();
  Object.values(vpData).forEach(entry => {
    Object.keys(entry).forEach(k => { if (k !== 'winner' && k !== 'action') allVariants.add(k); });
  });
  const variants = [...allVariants].sort();

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" data-testid="variant-performance-table">
        <thead>
          <tr className="border-b border-slate-800/40">
            <th className="text-left text-xs text-slate-500 font-medium pb-2 uppercase tracking-wider">City</th>
            {variants.map(v => (
              <th key={v} className="text-center text-xs font-medium pb-2 uppercase tracking-wider" style={{ color: VARIANT_COLORS[v] || '#94a3b8' }}>{v}</th>
            ))}
            <th className="text-center text-xs text-slate-500 font-medium pb-2 uppercase tracking-wider">Winner</th>
            <th className="text-center text-xs text-slate-500 font-medium pb-2 uppercase tracking-wider">Action</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(vpData).map(([city, entry]) => {
            const winner = entry.winner;
            const action = entry.action;
            const isWeak = winner === 'weak_city';
            const isInsufficient = winner === 'insufficient_data';
            const actionStyle = ACTION_STYLES[action] || ACTION_STYLES.optimize;
            const ActionIcon = actionStyle.icon;
            return (
              <tr key={city} className={`border-b border-slate-800/20 ${isWeak ? 'bg-red-500/[0.03]' : ''}`}>
                <td className={`py-2.5 font-medium ${isWeak ? 'text-red-400' : 'text-slate-300'}`}>{city}</td>
                {variants.map(v => {
                  const d = entry[v];
                  if (!d) return <td key={v} className="text-center py-2.5 text-slate-600">—</td>;
                  const isWinner = v === winner;
                  return (
                    <td key={v} className="text-center py-2.5">
                      <div className={`inline-flex flex-col items-center px-2 py-1 rounded-lg ${isWinner ? 'bg-emerald-500/10 ring-1 ring-emerald-500/20' : ''}`}>
                        <span className={`text-xs font-bold ${isWinner ? 'text-emerald-400' : 'text-slate-300'}`}>{d.cvr}%</span>
                        <span className="text-[10px] text-slate-600">{d.views}v / {d.clicks}c</span>
                      </div>
                    </td>
                  );
                })}
                <td className="text-center py-2.5">
                  <span className={`text-xs font-semibold ${isWeak ? 'text-red-400' : isInsufficient ? 'text-slate-500' : 'text-emerald-400'}`}>
                    {isWeak ? 'Weak' : isInsufficient ? 'Need Data' : winner}
                  </span>
                </td>
                <td className="text-center py-2.5">
                  <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${actionStyle.bg} ${actionStyle.text}`}>
                    <ActionIcon className="w-3 h-3" />{actionStyle.label}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Recommendations({ items }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="space-y-2" data-testid="geo-recommendations-list">
      {items.map((r, i) => (
        <div key={i} className="flex items-start gap-3 py-2.5 px-4 rounded-xl bg-indigo-500/[0.06] border border-indigo-500/10">
          <Lightbulb className="w-4 h-4 text-indigo-400 mt-0.5 shrink-0" />
          <p className="text-sm text-slate-300">{r}</p>
        </div>
      ))}
    </div>
  );
}

const CATEGORY_STYLES = {
  high_performer: { bg: 'bg-emerald-500/15', text: 'text-emerald-400', ring: 'ring-emerald-500/20', label: 'High Performer' },
  above_average:  { bg: 'bg-teal-500/15',    text: 'text-teal-400',    ring: 'ring-teal-500/20',    label: 'Above Avg' },
  below_average:  { bg: 'bg-amber-500/15',    text: 'text-amber-400',   ring: 'ring-amber-500/20',   label: 'Below Avg' },
  weak:           { bg: 'bg-red-500/15',       text: 'text-red-400',     ring: 'ring-red-500/20',     label: 'Weak' },
};

function CityPriorityRanking({ benchmarking, globalAvg }) {
  if (!benchmarking || benchmarking.length === 0) {
    return <p className="text-sm text-slate-500 text-center py-6">Not enough data for benchmarking (need cities with 30+ views)</p>;
  }
  return (
    <div>
      {globalAvg > 0 && (
        <div className="flex items-center gap-2 mb-4 px-1">
          <Target className="w-3.5 h-3.5 text-slate-500" />
          <span className="text-xs text-slate-500">Network avg CVR: <span className="text-slate-300 font-semibold">{globalAvg}%</span></span>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm" data-testid="city-priority-table">
          <thead>
            <tr className="border-b border-slate-800/40">
              <th className="text-left text-xs text-slate-500 font-medium pb-2 uppercase tracking-wider w-8">#</th>
              <th className="text-left text-xs text-slate-500 font-medium pb-2 uppercase tracking-wider">City</th>
              <th className="text-center text-xs text-slate-500 font-medium pb-2 uppercase tracking-wider">Best Variant</th>
              <th className="text-center text-xs text-slate-500 font-medium pb-2 uppercase tracking-wider">CVR</th>
              <th className="text-center text-xs text-slate-500 font-medium pb-2 uppercase tracking-wider">vs Avg</th>
              <th className="text-center text-xs text-slate-500 font-medium pb-2 uppercase tracking-wider">Category</th>
              <th className="text-center text-xs text-slate-500 font-medium pb-2 uppercase tracking-wider">Priority</th>
              <th className="text-center text-xs text-slate-500 font-medium pb-2 uppercase tracking-wider">Action</th>
            </tr>
          </thead>
          <tbody>
            {benchmarking.map((row, i) => {
              const cat = CATEGORY_STYLES[row.category] || CATEGORY_STYLES.weak;
              const isTop = row.category === 'high_performer';
              const isWeak = row.category === 'weak';
              return (
                <tr key={row.city} className={`border-b border-slate-800/20 ${isWeak ? 'bg-red-500/[0.03]' : isTop ? 'bg-emerald-500/[0.03]' : ''}`} data-testid={`benchmark-row-${row.city}`}>
                  <td className="py-2.5 text-slate-600 font-mono text-xs">{i + 1}</td>
                  <td className={`py-2.5 font-medium ${isTop ? 'text-emerald-400' : isWeak ? 'text-red-400' : 'text-slate-300'}`}>
                    {isTop && <Trophy className="w-3.5 h-3.5 inline mr-1.5 -mt-0.5" />}{row.city}
                  </td>
                  <td className="py-2.5 text-center">
                    <span className="text-xs font-medium px-2 py-0.5 rounded-full" style={{ color: VARIANT_COLORS[row.best_variant] || '#94a3b8', backgroundColor: `${VARIANT_COLORS[row.best_variant] || '#94a3b8'}18` }}>
                      {row.best_variant}
                    </span>
                  </td>
                  <td className={`py-2.5 text-center font-bold ${isTop ? 'text-emerald-400' : isWeak ? 'text-red-400' : 'text-slate-300'}`}>{row.cvr}%</td>
                  <td className="py-2.5 text-center">
                    <span className={`text-xs font-medium ${row.performance_ratio >= 1.0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {row.performance_ratio}x
                    </span>
                  </td>
                  <td className="py-2.5 text-center">
                    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ring-1 ${cat.bg} ${cat.text} ${cat.ring}`}>{cat.label}</span>
                  </td>
                  <td className="py-2.5 text-center font-mono text-xs text-slate-400">{row.priority_score}</td>
                  <td className="py-2.5 text-center">
                    <span className={`text-xs ${cat.text}`}>{row.action}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function GeoAnalyticsDashboard() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(7);
  const [cityFilter, setCityFilter] = useState('');
  const [variantFilter, setVariantFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ days: String(days) });
      if (cityFilter) params.set('city', cityFilter);
      if (variantFilter) params.set('variant', variantFilter);
      if (typeFilter) params.set('type', typeFilter);
      const res = await fetch(`${API_BASE}/api/geo-analytics?${params}`);
      const json = await res.json();
      setData(json);
    } catch (_) {}
    setLoading(false);
  }, [days, cityFilter, variantFilter, typeFilter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const totalViews = data?.total_views || 0;
  const totalClicks = data?.total_clicks || 0;
  const avgCvr = totalViews > 0 ? ((totalClicks / totalViews) * 100).toFixed(1) : '0.0';
  const totalCities = (data?.top_cities || []).length;
  const maxCityViews = Math.max(...(data?.top_cities || []).map(c => c.views), 1);
  const maxVariantViews = Math.max(...(data?.top_variants || []).map(v => v.views), 1);
  const maxTypeViews = Math.max(...(data?.top_types || []).map(t => t.views), 1);
  const filterOpts = data?.filter_options || {};

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-slate-200" data-testid="geo-analytics-dashboard">
      {/* Nav */}
      <nav className="sticky top-0 z-50 bg-[#0a0e1a]/80 backdrop-blur-xl border-b border-slate-800/40">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
          <button onClick={() => navigate('/')} className="flex items-center gap-2" data-testid="geo-nav-logo">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-teal-500 to-emerald-600 flex items-center justify-center">
              <Shield className="w-3.5 h-3.5 text-white" />
            </div>
            <span className="text-sm font-bold tracking-tight">NISCHINT</span>
            <span className="text-xs text-slate-500 ml-1">/ GEO Analytics</span>
          </button>
          <div className="flex items-center gap-2">
            <button onClick={() => navigate('/admin/funnel')} className="px-3 py-1.5 rounded-lg text-xs text-slate-500 hover:text-slate-300 bg-white/[0.03] border border-slate-800/40 transition-colors" data-testid="go-funnel">Funnel</button>
            <button onClick={fetchData} disabled={loading} className="p-2 rounded-lg hover:bg-white/5 text-slate-400 hover:text-white transition-colors" data-testid="geo-refresh">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            </button>
          </div>
        </div>
      </nav>

      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6 space-y-6">
        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3" data-testid="geo-filters">
          {[1, 7, 30].map(d => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${days === d ? 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/30' : 'bg-white/[0.03] text-slate-500 border border-slate-800/40 hover:text-slate-300'}`}
              data-testid={`geo-filter-${d}d`}
            >
              {d === 1 ? 'Today' : `${d}D`}
            </button>
          ))}
          <select value={cityFilter} onChange={e => setCityFilter(e.target.value)} className="px-3 py-1.5 rounded-lg text-xs bg-white/[0.03] border border-slate-800/40 text-slate-400 outline-none" data-testid="geo-filter-city">
            <option value="">All Cities</option>
            {(filterOpts.cities || []).map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          <select value={variantFilter} onChange={e => setVariantFilter(e.target.value)} className="px-3 py-1.5 rounded-lg text-xs bg-white/[0.03] border border-slate-800/40 text-slate-400 outline-none" data-testid="geo-filter-variant">
            <option value="">All Variants</option>
            {(filterOpts.variants || []).map(v => <option key={v} value={v}>{v}</option>)}
          </select>
          <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)} className="px-3 py-1.5 rounded-lg text-xs bg-white/[0.03] border border-slate-800/40 text-slate-400 outline-none" data-testid="geo-filter-type">
            <option value="">All Types</option>
            {(filterOpts.types || []).map(t => <option key={t} value={t}>{TYPE_LABELS[t] || t}</option>)}
          </select>
        </div>

        {loading && !data ? (
          <div className="flex items-center justify-center py-24"><Loader2 className="w-6 h-6 animate-spin text-slate-500" /></div>
        ) : (
          <>
            {/* Overview Cards */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3" data-testid="geo-overview-cards">
              <StatCard label="GEO Views" value={totalViews} icon={Eye} accent="#6366f1" />
              <StatCard label="CTA Clicks" value={totalClicks} icon={MousePointer} accent="#10b981" />
              <StatCard label="Avg CVR" value={`${avgCvr}%`} icon={TrendingUp} accent="#f59e0b" />
              <StatCard label="Cities" value={totalCities} icon={MapPin} accent="#ec4899" />
            </div>

            {/* Top Cities + Top Variants */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <div className="p-5 sm:p-6 rounded-2xl bg-white/[0.02] border border-slate-800/40" data-testid="geo-top-cities">
                <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2"><MapPin className="w-4 h-4 text-indigo-400" /> Top Cities</h2>
                {(data?.top_cities || []).length === 0
                  ? <p className="text-sm text-slate-500 text-center py-6">No city data yet</p>
                  : <div className="space-y-2.5">{(data?.top_cities || []).map(c => <BarRow key={c.city} label={c.city} value={c.views} maxValue={maxCityViews} accent="#6366f1" suffix=" views" />)}</div>}
              </div>
              <div className="p-5 sm:p-6 rounded-2xl bg-white/[0.02] border border-slate-800/40" data-testid="geo-top-variants">
                <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2"><Tag className="w-4 h-4 text-amber-400" /> Top Variants</h2>
                {(data?.top_variants || []).length === 0
                  ? <p className="text-sm text-slate-500 text-center py-6">No variant data yet</p>
                  : <div className="space-y-2.5">{(data?.top_variants || []).map(v => <BarRow key={v.variant} label={v.variant} value={v.views} maxValue={maxVariantViews} accent={VARIANT_COLORS[v.variant] || '#6366f1'} suffix=" views" />)}</div>}
              </div>
            </div>

            {/* Top Types + Trend Chart */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <div className="p-5 sm:p-6 rounded-2xl bg-white/[0.02] border border-slate-800/40" data-testid="geo-top-types">
                <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2"><Layers className="w-4 h-4 text-emerald-400" /> Top Types</h2>
                {(data?.top_types || []).length === 0
                  ? <p className="text-sm text-slate-500 text-center py-6">No type data yet</p>
                  : <div className="space-y-2.5">{(data?.top_types || []).map(t => <BarRow key={t.type} label={TYPE_LABELS[t.type] || t.type} value={t.views} maxValue={maxTypeViews} accent={TYPE_COLORS[t.type] || '#6366f1'} suffix=" views" />)}</div>}
              </div>
              <div className="p-5 sm:p-6 rounded-2xl bg-white/[0.02] border border-slate-800/40" data-testid="geo-daily-trend">
                <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2"><TrendingUp className="w-4 h-4 text-indigo-400" /> {days}D Trend</h2>
                <TrendChart data={data?.daily_trend} days={days} />
              </div>
            </div>

            {/* Conversion by City + Conversion by Variant */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <div className="p-5 sm:p-6 rounded-2xl bg-white/[0.02] border border-slate-800/40" data-testid="geo-conv-city">
                <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2"><Globe className="w-4 h-4 text-rose-400" /> Conversion by City</h2>
                <ConversionTable data={data?.conversion_rates} labelKey="city" labelTitle="City" />
              </div>
              <div className="p-5 sm:p-6 rounded-2xl bg-white/[0.02] border border-slate-800/40" data-testid="geo-conv-variant">
                <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2"><Tag className="w-4 h-4 text-amber-400" /> Conversion by Variant</h2>
                <ConversionTable data={data?.conversion_by_variant} labelKey="variant" labelTitle="Variant" />
              </div>
            </div>

            {/* Decision Engine: Variant Performance by City */}
            <div className="p-5 sm:p-6 rounded-2xl bg-white/[0.02] border border-indigo-500/20" data-testid="geo-variant-performance">
              <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2"><Zap className="w-4 h-4 text-indigo-400" /> Variant Performance by City</h2>
              <VariantPerformanceTable vpData={data?.variant_performance_by_city} />
            </div>

            {/* City-to-City Benchmarking */}
            <div className="p-5 sm:p-6 rounded-2xl bg-white/[0.02] border border-emerald-500/20" data-testid="geo-city-benchmarking">
              <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2"><Trophy className="w-4 h-4 text-emerald-400" /> City Priority Ranking</h2>
              <CityPriorityRanking benchmarking={data?.city_benchmarking} globalAvg={data?.global_avg_cvr} />
            </div>

            {/* Recommendations */}
            {(data?.recommendations || []).length > 0 && (
              <div className="p-5 sm:p-6 rounded-2xl bg-white/[0.02] border border-indigo-500/20" data-testid="geo-recommendations">
                <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2"><Lightbulb className="w-4 h-4 text-indigo-400" /> Recommendations</h2>
                <Recommendations items={data?.recommendations} />
              </div>
            )}

            {/* Recent Events */}
            <div className="p-5 sm:p-6 rounded-2xl bg-white/[0.02] border border-slate-800/40" data-testid="geo-recent-events">
              <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2"><Clock className="w-4 h-4 text-slate-400" /> Recent Events</h2>
              <RecentEvents events={data?.recent_events} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
