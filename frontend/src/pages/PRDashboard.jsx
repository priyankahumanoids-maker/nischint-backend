import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Shield, TrendingUp, Users, Newspaper, Send, Mail, BarChart3, Target, Award, ChevronDown, RefreshCw, Loader2, Zap, DollarSign, ArrowUpRight, ArrowDownRight, Brain, ExternalLink } from 'lucide-react';

const API_BASE = '';  // same-origin — no CORS, no stale baked-URL risk

function StatCard({ label, value, subtitle, icon: Icon, accent }) {
  return (
    <div className="p-5 rounded-2xl bg-white/[0.03] border border-slate-800/50 hover:border-slate-700/60 transition-colors" data-testid={`pr-stat-${label.toLowerCase().replace(/\s/g, '-')}`}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs text-slate-500 uppercase tracking-wider font-medium">{label}</span>
        <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ backgroundColor: `${accent}18` }}>
          <Icon className="w-4 h-4" style={{ color: accent }} />
        </div>
      </div>
      <p className="text-2xl font-bold text-white">{typeof value === 'number' ? value.toLocaleString() : value}</p>
      {subtitle && <p className="text-xs text-slate-500 mt-1">{subtitle}</p>}
    </div>
  );
}

function FunnelRow({ label, count, maxCount, rate, color, icon: Icon }) {
  const pct = maxCount > 0 ? (count / maxCount) * 100 : 0;
  return (
    <div className="flex items-center gap-3" data-testid={`pr-funnel-${label.toLowerCase().replace(/\s/g, '-')}`}>
      <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" style={{ backgroundColor: `${color}15` }}>
        <Icon className="w-3.5 h-3.5" style={{ color }} />
      </div>
      <div className="w-28 shrink-0">
        <p className="text-sm text-slate-300 font-medium">{label}</p>
      </div>
      <div className="flex-1 h-8 bg-white/[0.03] rounded-lg overflow-hidden">
        <div className="h-full rounded-lg transition-all duration-700" style={{ width: `${Math.max(pct, 3)}%`, backgroundColor: color, opacity: 0.8 }} />
      </div>
      <div className="w-16 text-right shrink-0">
        <p className="text-sm font-bold text-white">{count}</p>
      </div>
      <div className="w-14 text-right shrink-0">
        <span className="text-xs text-slate-500">{rate}%</span>
      </div>
    </div>
  );
}

function JournalistRow({ j, rank }) {
  const priorityColors = { high: '#10b981', medium: '#f59e0b', low: '#6b7280' };
  const pc = priorityColors[j.priority] || '#6b7280';
  return (
    <div className="flex items-center gap-3 py-3 border-b border-slate-800/30 last:border-0" data-testid={`journalist-row-${rank}`}>
      <div className="w-7 h-7 rounded-full bg-white/[0.06] flex items-center justify-center text-xs font-bold text-slate-400 shrink-0">
        {rank}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-white truncate">{j.name}</p>
        <p className="text-xs text-slate-500 truncate">{j.publication || '—'}</p>
      </div>
      <div className="hidden sm:block w-12 text-center">
        <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold" style={{ backgroundColor: `${pc}20`, color: pc }}>
          {j.priority}
        </div>
      </div>
      <div className="w-12 text-center">
        <p className="text-sm font-bold text-white">{j.score}</p>
        <p className="text-[10px] text-slate-600">score</p>
      </div>
      <div className="w-16 text-right">
        <p className="text-sm font-semibold text-emerald-400">{j.metrics?.revenue > 0 ? `$${j.metrics.revenue.toLocaleString()}` : '—'}</p>
        <p className="text-[10px] text-slate-600">{j.metrics?.articles || 0} articles</p>
      </div>
    </div>
  );
}

function CampaignRow({ c }) {
  return (
    <div className="p-4 rounded-xl bg-white/[0.02] border border-slate-800/30 hover:border-slate-700/50 transition-colors" data-testid={`campaign-${c.name}`}>
      <div className="flex items-start justify-between mb-3">
        <div>
          <h4 className="text-sm font-semibold text-white">{c.name}</h4>
          {c.narrative_angle && <p className="text-xs text-slate-500 mt-0.5 italic">"{c.narrative_angle}"</p>}
        </div>
        <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${c.revenue > 0 ? 'bg-emerald-500/15 text-emerald-400' : 'bg-slate-800 text-slate-500'}`}>
          {c.revenue > 0 ? `$${c.revenue.toLocaleString()}` : 'No revenue'}
        </span>
      </div>
      <div className="grid grid-cols-4 gap-2">
        {[
          { label: 'Outreach', val: c.total_outreach || 0 },
          { label: 'Responses', val: c.total_responses || 0 },
          { label: 'Articles', val: c.total_articles || 0 },
          { label: 'Leads', val: c.total_leads || 0 },
        ].map(item => (
          <div key={item.label}>
            <p className="text-[10px] text-slate-600">{item.label}</p>
            <p className="text-sm font-bold text-slate-300">{item.val}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function DailyChart({ data, days }) {
  if (!data || Object.keys(data).length === 0) {
    return <p className="text-sm text-slate-500 text-center py-8">No event data yet</p>;
  }
  const today = new Date();
  const allDays = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    allDays.push(d.toISOString().split('T')[0]);
  }
  const outreachArr = allDays.map(d => data[d]?.pr_outreach_sent || 0);
  const articlesArr = allDays.map(d => data[d]?.article_published || 0);
  const leadsArr = allDays.map(d => data[d]?.lead_generated || 0);
  const maxVal = Math.max(...outreachArr, ...articlesArr, ...leadsArr, 1);
  const h = 120;
  const w = allDays.length > 1 ? allDays.length - 1 : 1;

  const toPath = (arr) =>
    arr.map((v, i) => {
      const x = (i / w) * 100;
      const y = h - (v / maxVal) * (h - 20);
      return `${i === 0 ? 'M' : 'L'}${x},${y}`;
    }).join(' ');

  return (
    <div data-testid="pr-daily-chart">
      <svg viewBox={`0 0 100 ${h}`} className="w-full" preserveAspectRatio="none" style={{ height: 140 }}>
        <path d={toPath(outreachArr)} fill="none" stroke="#6366f1" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
        <path d={toPath(articlesArr)} fill="none" stroke="#f59e0b" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
        <path d={toPath(leadsArr)} fill="none" stroke="#10b981" strokeWidth="1.5" strokeDasharray="4 2" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="flex justify-between mt-1 px-1">
        <span className="text-[10px] text-slate-600">{allDays[0]?.slice(5)}</span>
        <span className="text-[10px] text-slate-600">{allDays[allDays.length - 1]?.slice(5)}</span>
      </div>
      <div className="flex items-center gap-4 mt-2 justify-center">
        {[{ color: '#6366f1', label: 'Outreach' }, { color: '#f59e0b', label: 'Articles' }, { color: '#10b981', label: 'Leads' }].map(l => (
          <div key={l.label} className="flex items-center gap-1.5">
            <div className="w-3 h-0.5 rounded" style={{ backgroundColor: l.color }} />
            <span className="text-[11px] text-slate-500">{l.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function AIInsightsPanel({ insights, loading, onAnalyze }) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-5 h-5 animate-spin text-violet-400 mr-2" />
        <span className="text-sm text-slate-400">Analyzing PR data...</span>
      </div>
    );
  }

  if (!insights || Object.keys(insights).length === 0) {
    return (
      <div className="text-center py-8">
        <Brain className="w-8 h-8 text-slate-600 mx-auto mb-3" />
        <p className="text-sm text-slate-500 mb-4">No AI analysis available yet</p>
        <button onClick={onAnalyze} className="px-4 py-2 rounded-lg bg-violet-500/20 text-violet-300 text-xs font-medium hover:bg-violet-500/30 transition-colors" data-testid="trigger-ai-analysis">
          Run AI Analysis
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="ai-insights">
      {insights.narrative_analysis && (
        <div>
          <h4 className="text-xs text-violet-400 font-semibold uppercase tracking-wider mb-2">Narrative Intelligence</h4>
          <p className="text-sm text-slate-300 leading-relaxed">{typeof insights.narrative_analysis === 'string' ? insights.narrative_analysis : JSON.stringify(insights.narrative_analysis)}</p>
        </div>
      )}
      {insights.recommendations && (
        <div>
          <h4 className="text-xs text-amber-400 font-semibold uppercase tracking-wider mb-2">Recommendations</h4>
          <p className="text-sm text-slate-300 leading-relaxed">{typeof insights.recommendations === 'string' ? insights.recommendations : JSON.stringify(insights.recommendations)}</p>
        </div>
      )}
      {insights.journalist_priorities && (
        <div>
          <h4 className="text-xs text-emerald-400 font-semibold uppercase tracking-wider mb-2">Journalist Priorities</h4>
          <p className="text-sm text-slate-300 leading-relaxed">{typeof insights.journalist_priorities === 'string' ? insights.journalist_priorities : JSON.stringify(insights.journalist_priorities)}</p>
        </div>
      )}
      <button onClick={onAnalyze} className="mt-2 px-3 py-1.5 rounded-lg bg-white/[0.04] text-slate-400 text-xs hover:bg-white/[0.08] transition-colors" data-testid="re-analyze-btn">
        Re-analyze
      </button>
    </div>
  );
}

export default function PRDashboard() {
  const navigate = useNavigate();
  const [dashData, setDashData] = useState(null);
  const [journalists, setJournalists] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  const [aiInsights, setAiInsights] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(30);
  const [attrGroup, setAttrGroup] = useState('journalist');
  const [attributions, setAttributions] = useState([]);
  const [tab, setTab] = useState('overview');

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [dashRes, jourRes, campRes, aiRes] = await Promise.all([
        fetch(`${API_BASE}/api/pr/dashboard?days=${days}`),
        fetch(`${API_BASE}/api/pr/journalists?sort_by=score&limit=10`),
        fetch(`${API_BASE}/api/pr/campaigns`),
        fetch(`${API_BASE}/api/pr/analysis/latest`),
      ]);
      const [dash, jour, camp, ai] = await Promise.all([dashRes.json(), jourRes.json(), campRes.json(), aiRes.json()]);
      setDashData(dash);
      setJournalists(jour.journalists || []);
      setCampaigns(camp.campaigns || []);
      setAiInsights(ai.insights || null);
    } catch (e) { console.error('PR fetch error', e); }
    setLoading(false);
  }, [days]);

  const fetchAttribution = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/pr/attribution?days=${days}&group_by=${attrGroup}`);
      const data = await res.json();
      setAttributions(data.attributions || []);
    } catch (_) {}
  }, [days, attrGroup]);

  useEffect(() => { fetchAll(); }, [fetchAll]);
  useEffect(() => { if (tab === 'attribution') fetchAttribution(); }, [tab, fetchAttribution]);

  const triggerAI = async () => {
    setAiLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/pr/analyze`, { method: 'POST' });
      const data = await res.json();
      setAiInsights(data.insights || null);
    } catch (e) { console.error('AI analysis error', e); }
    setAiLoading(false);
  };

  const ov = dashData?.overview || {};
  const cr = dashData?.conversion_rates || {};

  const TABS = [
    { key: 'overview', label: 'Overview', icon: BarChart3 },
    { key: 'journalists', label: 'Journalists', icon: Users },
    { key: 'campaigns', label: 'Campaigns', icon: Target },
    { key: 'attribution', label: 'Attribution', icon: DollarSign },
    { key: 'ai', label: 'AI Insights', icon: Brain },
  ];

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-slate-200" data-testid="pr-dashboard">
      {/* Nav */}
      <nav className="sticky top-0 z-50 bg-[#0a0e1a]/80 backdrop-blur-xl border-b border-slate-800/40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
          <button onClick={() => navigate('/')} className="flex items-center gap-2" data-testid="pr-nav-logo">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center">
              <Shield className="w-3.5 h-3.5 text-white" />
            </div>
            <span className="text-sm font-bold tracking-tight">NISCHINT</span>
            <span className="text-xs text-slate-500 ml-1">/ PR Intelligence</span>
          </button>
          <div className="flex items-center gap-2">
            {[7, 30, 90].map(d => (
              <button key={d} onClick={() => setDays(d)}
                className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${days === d ? 'bg-violet-500/20 text-violet-300 border border-violet-500/30' : 'bg-white/[0.03] text-slate-500 border border-slate-800/40 hover:text-slate-300'}`}
                data-testid={`pr-filter-${d}d`}>
                {d}D
              </button>
            ))}
            <button onClick={fetchAll} disabled={loading} className="p-2 rounded-lg hover:bg-white/5 text-slate-400 hover:text-white transition-colors ml-1" data-testid="pr-refresh">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            </button>
          </div>
        </div>
      </nav>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-6">
        {/* Tab Nav */}
        <div className="flex gap-1 mb-6 overflow-x-auto pb-1 scrollbar-none" data-testid="pr-tabs">
          {TABS.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-medium whitespace-nowrap transition-colors ${tab === t.key ? 'bg-violet-500/15 text-violet-300 border border-violet-500/25' : 'text-slate-500 hover:text-slate-300 hover:bg-white/[0.03]'}`}
              data-testid={`pr-tab-${t.key}`}>
              <t.icon className="w-3.5 h-3.5" />
              {t.label}
            </button>
          ))}
        </div>

        {loading && !dashData ? (
          <div className="flex items-center justify-center py-24">
            <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
          </div>
        ) : (
          <>
            {/* OVERVIEW TAB */}
            {tab === 'overview' && (
              <div className="space-y-6">
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3" data-testid="pr-overview-cards">
                  <StatCard label="Campaigns" value={ov.total_campaigns || 0} icon={Target} accent="#8b5cf6" />
                  <StatCard label="Outreach" value={ov.total_outreach || 0} icon={Send} accent="#6366f1" />
                  <StatCard label="Responses" value={ov.total_responses || 0} subtitle={`${cr.outreach_to_response || 0}% rate`} icon={Mail} accent="#3b82f6" />
                  <StatCard label="Articles" value={ov.articles_published || 0} subtitle={`${cr.response_to_article || 0}% rate`} icon={Newspaper} accent="#f59e0b" />
                  <StatCard label="Leads" value={ov.leads_generated || 0} subtitle={`${cr.article_to_lead || 0}% rate`} icon={Users} accent="#10b981" />
                  <StatCard label="Revenue" value={ov.revenue_influenced > 0 ? `$${ov.revenue_influenced.toLocaleString()}` : '$0'} subtitle={`${cr.overall_pr_roi || 0}% ROI`} icon={DollarSign} accent="#22c55e" />
                </div>

                {/* PR Funnel */}
                <div className="p-5 sm:p-6 rounded-2xl bg-white/[0.02] border border-slate-800/40" data-testid="pr-funnel">
                  <h2 className="text-sm font-semibold text-white mb-5">PR Conversion Funnel</h2>
                  <div className="space-y-3">
                    <FunnelRow label="Outreach" count={ov.total_outreach || 0} maxCount={ov.total_outreach || 1} rate={100} color="#6366f1" icon={Send} />
                    <FunnelRow label="Responses" count={ov.total_responses || 0} maxCount={ov.total_outreach || 1} rate={cr.outreach_to_response || 0} color="#3b82f6" icon={Mail} />
                    <FunnelRow label="Articles" count={ov.articles_published || 0} maxCount={ov.total_outreach || 1} rate={cr.response_to_article || 0} color="#f59e0b" icon={Newspaper} />
                    <FunnelRow label="Leads" count={ov.leads_generated || 0} maxCount={ov.total_outreach || 1} rate={cr.article_to_lead || 0} color="#10b981" icon={Users} />
                    <FunnelRow label="Revenue" count={ov.revenue_influenced || 0} maxCount={ov.total_outreach || 1} rate={cr.overall_pr_roi || 0} color="#22c55e" icon={DollarSign} />
                  </div>
                </div>

                {/* Daily Trend + Top lists */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <div className="p-5 rounded-2xl bg-white/[0.02] border border-slate-800/40" data-testid="pr-daily-trend">
                    <h2 className="text-sm font-semibold text-white mb-4">Activity Trend</h2>
                    <DailyChart data={dashData?.daily_trend} days={days} />
                  </div>
                  <div className="p-5 rounded-2xl bg-white/[0.02] border border-slate-800/40" data-testid="pr-top-journalists-mini">
                    <h2 className="text-sm font-semibold text-white mb-4">Top Journalists by Revenue</h2>
                    {(dashData?.top_journalists || []).length === 0 ? (
                      <p className="text-sm text-slate-500 text-center py-6">No journalist data yet</p>
                    ) : (
                      <div className="space-y-2">
                        {(dashData?.top_journalists || []).map((j, i) => (
                          <div key={i} className="flex items-center justify-between py-1.5">
                            <div className="flex items-center gap-2">
                              <span className="text-xs text-slate-600 w-4">{i + 1}</span>
                              <span className="text-sm text-slate-300">{j.name}</span>
                              <span className="text-xs text-slate-600">{j.publication}</span>
                            </div>
                            <span className="text-sm font-semibold text-emerald-400">{j.revenue > 0 ? `$${j.revenue.toLocaleString()}` : '—'}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* JOURNALISTS TAB */}
            {tab === 'journalists' && (
              <div className="p-5 sm:p-6 rounded-2xl bg-white/[0.02] border border-slate-800/40" data-testid="pr-journalists-table">
                <div className="flex items-center justify-between mb-5">
                  <h2 className="text-sm font-semibold text-white">Journalist Performance Rankings</h2>
                  <span className="text-xs text-slate-500">{journalists.length} journalists</span>
                </div>
                {journalists.length === 0 ? (
                  <p className="text-sm text-slate-500 text-center py-12">No journalists tracked yet. Ingest PR outreach events to populate this table.</p>
                ) : (
                  <div>
                    {journalists.map((j, i) => <JournalistRow key={j.journalist_id} j={j} rank={i + 1} />)}
                  </div>
                )}
              </div>
            )}

            {/* CAMPAIGNS TAB */}
            {tab === 'campaigns' && (
              <div className="space-y-4" data-testid="pr-campaigns-list">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-white">{campaigns.length} Campaigns</h2>
                </div>
                {campaigns.length === 0 ? (
                  <div className="p-8 rounded-2xl bg-white/[0.02] border border-slate-800/40 text-center">
                    <Target className="w-8 h-8 text-slate-600 mx-auto mb-3" />
                    <p className="text-sm text-slate-500">No campaigns created yet.</p>
                    <p className="text-xs text-slate-600 mt-1">Use POST /api/pr/campaigns or the n8n webhook to create campaigns.</p>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {campaigns.map(c => <CampaignRow key={c.campaign_id} c={c} />)}
                  </div>
                )}
              </div>
            )}

            {/* ATTRIBUTION TAB */}
            {tab === 'attribution' && (
              <div className="space-y-4" data-testid="pr-attribution">
                <div className="flex items-center gap-3 mb-2">
                  <span className="text-xs text-slate-500">Group by:</span>
                  {['journalist', 'campaign', 'publication'].map(g => (
                    <button key={g} onClick={() => setAttrGroup(g)}
                      className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${attrGroup === g ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' : 'bg-white/[0.03] text-slate-500 border border-slate-800/40 hover:text-slate-300'}`}
                      data-testid={`attr-group-${g}`}>
                      {g.charAt(0).toUpperCase() + g.slice(1)}
                    </button>
                  ))}
                </div>
                <div className="p-5 rounded-2xl bg-white/[0.02] border border-slate-800/40">
                  <h2 className="text-sm font-semibold text-white mb-4">Revenue Attribution — by {attrGroup}</h2>
                  {attributions.length === 0 ? (
                    <p className="text-sm text-slate-500 text-center py-8">No attribution data yet. Ingest lead_generated and conversion events to populate.</p>
                  ) : (
                    <div className="space-y-2">
                      {attributions.map((a, i) => (
                        <div key={i} className="flex items-center justify-between py-2 border-b border-slate-800/30 last:border-0">
                          <div>
                            <p className="text-sm text-slate-300 font-medium">{a.name || a.publication || 'Unknown'}</p>
                            {a.narrative_angle && <p className="text-xs text-slate-500 italic">"{a.narrative_angle}"</p>}
                            {a.email && <p className="text-xs text-slate-600">{a.email}</p>}
                          </div>
                          <div className="text-right">
                            <p className="text-sm font-bold text-emerald-400">{a.revenue > 0 ? `$${a.revenue.toLocaleString()}` : '—'}</p>
                            <p className="text-xs text-slate-500">{a.leads || 0} leads</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* AI INSIGHTS TAB */}
            {tab === 'ai' && (
              <div className="p-5 sm:p-6 rounded-2xl bg-white/[0.02] border border-violet-500/20" data-testid="pr-ai-panel">
                <div className="flex items-center gap-2 mb-5">
                  <Brain className="w-4 h-4 text-violet-400" />
                  <h2 className="text-sm font-semibold text-white">AI Narrative Intelligence</h2>
                </div>
                <AIInsightsPanel insights={aiInsights} loading={aiLoading} onAnalyze={triggerAI} />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
