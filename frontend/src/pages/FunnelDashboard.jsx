import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Shield, TrendingUp, Users, MessageCircle, Eye, MousePointer, ArrowRight, ChevronDown, RefreshCw, Loader2 } from 'lucide-react';

const API_BASE = '';  // same-origin — no CORS, no stale baked-URL risk

const STAGES = [
  { key: 'page_views', label: 'Page Views', color: '#6366f1' },
  { key: 'cta_clicks', label: 'CTA Clicks', color: '#8b5cf6' },
  { key: 'modal_opens', label: 'Modal Opens', color: '#a78bfa' },
  { key: 'leads', label: 'Leads', color: '#10b981' },
  { key: 'whatsapp_redirects', label: 'WhatsApp', color: '#22c55e' },
];

const DROP_KEYS = ['view_to_click', 'click_to_modal', 'modal_to_lead', 'lead_to_whatsapp'];

const PAGE_COLORS = { women: '#f43f5e', kids: '#3b82f6', family: '#10b981' };
const PAGE_LABELS = { women: 'Women Safety', kids: 'Kids Safety', family: 'Family Safety' };

function StatCard({ label, value, icon: Icon, accent }) {
  return (
    <div className="p-5 rounded-2xl bg-white/[0.03] border border-slate-800/50" data-testid={`stat-${label.toLowerCase().replace(/\s/g, '-')}`}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs text-slate-500 uppercase tracking-wider font-medium">{label}</span>
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center`} style={{ backgroundColor: `${accent}18` }}>
          <Icon className="w-4 h-4" style={{ color: accent }} />
        </div>
      </div>
      <p className="text-2xl font-bold text-white">{typeof value === 'number' && value % 1 !== 0 ? `${value}%` : value}</p>
    </div>
  );
}

function FunnelBar({ stage, count, maxCount, prevCount, index }) {
  const pct = maxCount > 0 ? (count / maxCount) * 100 : 0;
  const dropPct = prevCount > 0 ? Math.round((1 - count / prevCount) * 100) : null;

  return (
    <div className="flex items-center gap-4" data-testid={`funnel-bar-${stage.key}`}>
      <div className="w-28 sm:w-36 text-right">
        <p className="text-sm text-slate-400">{stage.label}</p>
        <p className="text-lg font-bold text-white">{count}</p>
      </div>
      <div className="flex-1 h-10 bg-white/[0.03] rounded-lg overflow-hidden relative">
        <div
          className="h-full rounded-lg transition-all duration-700 ease-out"
          style={{ width: `${Math.max(pct, 2)}%`, backgroundColor: stage.color }}
        />
      </div>
      <div className="w-16 text-right">
        {dropPct !== null && dropPct > 0 ? (
          <span className="text-xs text-red-400 font-medium">-{dropPct}%</span>
        ) : index === 0 ? (
          <span className="text-xs text-slate-600">—</span>
        ) : (
          <span className="text-xs text-emerald-400 font-medium">0%</span>
        )}
      </div>
    </div>
  );
}

function PageCard({ name, data }) {
  const views = data?.page_view || 0;
  const leads = data?.lead_submit || 0;
  const wa = data?.whatsapp_redirect || 0;
  const cvr = views > 0 ? ((leads / views) * 100).toFixed(1) : '0.0';
  const accent = PAGE_COLORS[name] || '#6366f1';

  return (
    <div className="p-5 rounded-2xl bg-white/[0.03] border border-slate-800/50" data-testid={`page-card-${name}`}>
      <div className="flex items-center gap-2 mb-4">
        <div className="w-3 h-3 rounded-full" style={{ backgroundColor: accent }} />
        <h3 className="text-sm font-semibold text-white">{PAGE_LABELS[name] || name}</h3>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <div>
          <p className="text-xs text-slate-500 mb-1">CVR</p>
          <p className="text-lg font-bold text-white">{cvr}%</p>
        </div>
        <div>
          <p className="text-xs text-slate-500 mb-1">Leads</p>
          <p className="text-lg font-bold text-white">{leads}</p>
        </div>
        <div>
          <p className="text-xs text-slate-500 mb-1">WhatsApp</p>
          <p className="text-lg font-bold text-white">{wa}</p>
        </div>
      </div>
    </div>
  );
}

function MiniLineChart({ data, days }) {
  if (!data || Object.keys(data).length === 0) {
    return <p className="text-sm text-slate-500 text-center py-8">No daily data yet</p>;
  }

  // Fill missing days
  const today = new Date();
  const allDays = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    allDays.push(d.toISOString().split('T')[0]);
  }

  const leadsArr = allDays.map(d => data[d]?.lead_submit || 0);
  const waArr = allDays.map(d => data[d]?.whatsapp_redirect || 0);
  const maxVal = Math.max(...leadsArr, ...waArr, 1);
  const h = 120;
  const w = allDays.length > 1 ? allDays.length - 1 : 1;

  const toPath = (arr) => {
    return arr.map((v, i) => {
      const x = (i / w) * 100;
      const y = h - (v / maxVal) * (h - 20);
      return `${i === 0 ? 'M' : 'L'}${x},${y}`;
    }).join(' ');
  };

  return (
    <div className="relative" data-testid="daily-trend-chart">
      <svg viewBox={`0 0 100 ${h}`} className="w-full" preserveAspectRatio="none" style={{ height: 140 }}>
        <path d={toPath(leadsArr)} fill="none" stroke="#10b981" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
        <path d={toPath(waArr)} fill="none" stroke="#22c55e" strokeWidth="1.5" strokeDasharray="4 2" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="flex justify-between mt-1 px-1">
        <span className="text-[10px] text-slate-600">{allDays[0]?.slice(5)}</span>
        <span className="text-[10px] text-slate-600">{allDays[allDays.length - 1]?.slice(5)}</span>
      </div>
      <div className="flex items-center gap-4 mt-2 justify-center">
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-0.5 bg-emerald-500 rounded" />
          <span className="text-[11px] text-slate-500">Leads</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-0.5 bg-green-500 rounded border-dashed" style={{ borderTop: '1px dashed #22c55e', height: 0, width: 12 }} />
          <span className="text-[11px] text-slate-500">WhatsApp</span>
        </div>
      </div>
    </div>
  );
}

export default function FunnelDashboard() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(7);
  const [pageFilter, setPageFilter] = useState('');

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ days: String(days) });
      if (pageFilter) params.set('page', pageFilter);
      const res = await fetch(`${API_BASE}/api/funnel-metrics?${params}`);
      const json = await res.json();
      setData(json);
    } catch (_) {}
    setLoading(false);
  }, [days, pageFilter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const f = data?.funnel || {};
  const cr = data?.conversion_rates || {};
  const byPage = data?.by_page || {};

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-slate-200" data-testid="funnel-dashboard">
      {/* Nav */}
      <nav className="sticky top-0 z-50 bg-[#0a0e1a]/80 backdrop-blur-xl border-b border-slate-800/40">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
          <button onClick={() => navigate('/')} className="flex items-center gap-2" data-testid="funnel-nav-logo">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-teal-500 to-emerald-600 flex items-center justify-center">
              <Shield className="w-3.5 h-3.5 text-white" />
            </div>
            <span className="text-sm font-bold tracking-tight">NISCHINT</span>
            <span className="text-xs text-slate-500 ml-1">/ Funnel</span>
          </button>
          <button onClick={fetchData} disabled={loading} className="p-2 rounded-lg hover:bg-white/5 text-slate-400 hover:text-white transition-colors" data-testid="funnel-refresh">
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
          </button>
        </div>
      </nav>

      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6 space-y-6">
        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3" data-testid="funnel-filters">
          {[1, 7, 30].map(d => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${days === d ? 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/30' : 'bg-white/[0.03] text-slate-500 border border-slate-800/40 hover:text-slate-300'}`}
              data-testid={`filter-${d}d`}
            >
              {d === 1 ? 'Today' : `${d}D`}
            </button>
          ))}
          <select
            value={pageFilter}
            onChange={e => setPageFilter(e.target.value)}
            className="px-3 py-1.5 rounded-lg text-xs bg-white/[0.03] border border-slate-800/40 text-slate-400 outline-none"
            data-testid="filter-page"
          >
            <option value="">All Pages</option>
            <option value="women">Women</option>
            <option value="kids">Kids</option>
            <option value="family">Family</option>
          </select>
        </div>

        {loading && !data ? (
          <div className="flex items-center justify-center py-24">
            <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
          </div>
        ) : (
          <>
            {/* Overview Cards */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3" data-testid="overview-cards">
              <StatCard label="Page Views" value={f.page_views || 0} icon={Eye} accent="#6366f1" />
              <StatCard label="Leads" value={f.leads || 0} icon={Users} accent="#10b981" />
              <StatCard label="WhatsApp" value={f.whatsapp_redirects || 0} icon={MessageCircle} accent="#22c55e" />
              <StatCard label="Conversion" value={cr.overall || 0} icon={TrendingUp} accent="#f59e0b" />
            </div>

            {/* Funnel Visual */}
            <div className="p-5 sm:p-6 rounded-2xl bg-white/[0.02] border border-slate-800/40" data-testid="funnel-visual">
              <h2 className="text-sm font-semibold text-white mb-5">Conversion Funnel</h2>
              <div className="space-y-3">
                {STAGES.map((stage, i) => {
                  const count = f[stage.key] || 0;
                  const prevCount = i > 0 ? (f[STAGES[i - 1].key] || 0) : 0;
                  const maxCount = f[STAGES[0].key] || 1;
                  return (
                    <FunnelBar key={stage.key} stage={stage} count={count} maxCount={maxCount} prevCount={prevCount} index={i} />
                  );
                })}
              </div>
            </div>

            {/* Page Breakdown + Daily Trend */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {/* Page Breakdown */}
              <div className="p-5 sm:p-6 rounded-2xl bg-white/[0.02] border border-slate-800/40" data-testid="page-breakdown">
                <h2 className="text-sm font-semibold text-white mb-4">Page Breakdown</h2>
                <div className="space-y-3">
                  {['women', 'kids', 'family'].map(p => (
                    <PageCard key={p} name={p} data={byPage[p]} />
                  ))}
                </div>
              </div>

              {/* Daily Trend */}
              <div className="p-5 sm:p-6 rounded-2xl bg-white/[0.02] border border-slate-800/40" data-testid="daily-trend">
                <h2 className="text-sm font-semibold text-white mb-4">Daily Trend</h2>
                <MiniLineChart data={data?.daily_trend} days={days} />
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
