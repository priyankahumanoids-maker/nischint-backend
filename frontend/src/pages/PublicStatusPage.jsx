import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { CheckCircle2, AlertTriangle, XCircle, Clock, ChevronRight, ExternalLink, RefreshCw } from 'lucide-react';

// Public endpoint — no auth, served at /api/public/status
const STATUS_ENDPOINT = '/api/public/status';
// Auto-refresh cadence — endpoint is Redis-cached for 30s upstream.
const REFRESH_INTERVAL_MS = 30_000;

// Visual tokens for each status. Kept inline (not Tailwind classes
// referencing dynamic values) so the JIT doesn't tree-shake them.
const STATUS_VISUAL = {
  operational: {
    label: 'Operational',
    Icon: CheckCircle2,
    pillBg: 'bg-emerald-500/10',
    pillBorder: 'border-emerald-500/30',
    pillText: 'text-emerald-300',
    dot: 'bg-emerald-400',
    headerBg: 'bg-emerald-500',
    headerText: 'text-emerald-50',
    rowAccent: 'bg-emerald-500/5',
  },
  degraded: {
    label: 'Degraded performance',
    Icon: AlertTriangle,
    pillBg: 'bg-amber-500/10',
    pillBorder: 'border-amber-500/30',
    pillText: 'text-amber-300',
    dot: 'bg-amber-400',
    headerBg: 'bg-amber-500',
    headerText: 'text-amber-50',
    rowAccent: 'bg-amber-500/5',
  },
  outage: {
    label: 'Service disruption',
    Icon: XCircle,
    pillBg: 'bg-rose-500/10',
    pillBorder: 'border-rose-500/30',
    pillText: 'text-rose-300',
    dot: 'bg-rose-400',
    headerBg: 'bg-rose-600',
    headerText: 'text-rose-50',
    rowAccent: 'bg-rose-500/5',
  },
};

const SEVERITY_TONE = {
  minor:    { bg: 'bg-amber-500/10',  border: 'border-amber-500/30',  text: 'text-amber-300',  label: 'Minor'    },
  major:    { bg: 'bg-orange-500/10', border: 'border-orange-500/30', text: 'text-orange-300', label: 'Major'    },
  critical: { bg: 'bg-rose-500/10',   border: 'border-rose-500/30',   text: 'text-rose-300',   label: 'Critical' },
};

function formatRelativeTime(iso) {
  if (!iso) return '—';
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return '—';
  const diffMin = Math.floor((Date.now() - t) / 60_000);
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}h ago`;
  const diffD = Math.floor(diffH / 24);
  if (diffD < 30) return `${diffD}d ago`;
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}

function formatLocalDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-IN', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatDuration(minutes) {
  if (minutes == null) return null;
  if (minutes < 1) return '< 1 min';
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

// Group incidents by ISO date (YYYY-MM-DD) for the timeline view.
function groupIncidentsByDate(incidents) {
  const groups = new Map();
  for (const inc of incidents) {
    const day = inc.started_at ? inc.started_at.slice(0, 10) : 'unknown';
    if (!groups.has(day)) groups.set(day, []);
    groups.get(day).push(inc);
  }
  return Array.from(groups.entries()).sort((a, b) => b[0].localeCompare(a[0]));
}

function StatusPill({ status }) {
  const visual = STATUS_VISUAL[status] || STATUS_VISUAL.operational;
  const { Icon } = visual;
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border ${visual.pillBg} ${visual.pillBorder} ${visual.pillText} text-xs font-semibold`}
      data-testid={`status-pill-${status}`}
    >
      <Icon className="w-3.5 h-3.5" aria-hidden="true" />
      {visual.label}
    </span>
  );
}

function OverallBanner({ status, lastUpdatedIso, refreshing, onRefresh }) {
  const visual = STATUS_VISUAL[status] || STATUS_VISUAL.operational;
  const { Icon } = visual;
  return (
    <section
      className={`rounded-2xl border ${visual.pillBorder} ${visual.pillBg} p-6 sm:p-8 mb-10`}
      role="status"
      aria-live="polite"
      data-testid="overall-status-banner"
    >
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-start gap-4">
          <div className={`p-3 rounded-xl ${visual.headerBg}/15 ring-1 ${visual.pillBorder}`}>
            <Icon className={`w-7 h-7 ${visual.pillText}`} aria-hidden="true" />
          </div>
          <div>
            <h1
              className={`text-2xl sm:text-3xl font-bold ${visual.pillText}`}
              data-testid="overall-status-headline"
            >
              {status === 'operational' && 'All systems operational'}
              {status === 'degraded' && 'Some systems are experiencing issues'}
              {status === 'outage' && 'Service disruption in progress'}
            </h1>
            <p className="text-sm text-slate-400 mt-1">
              Live status of the Nischint Safety Operating System.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-400" data-testid="last-updated-label">
            <Clock className="inline-block w-3.5 h-3.5 mr-1 -mt-0.5" aria-hidden="true" />
            Updated {formatRelativeTime(lastUpdatedIso)}
          </span>
          <button
            type="button"
            onClick={onRefresh}
            aria-label="Refresh status now"
            data-testid="status-refresh-button"
            className="p-2 rounded-lg border border-slate-700/70 hover:border-slate-500 hover:bg-slate-800/40 transition-colors text-slate-300"
          >
            <RefreshCw
              className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`}
              aria-hidden="true"
            />
          </button>
        </div>
      </div>
    </section>
  );
}

function ComponentRow({ component }) {
  const visual = STATUS_VISUAL[component.status] || STATUS_VISUAL.operational;
  return (
    <div
      className={`flex items-center justify-between gap-4 px-4 sm:px-6 py-4 border-b border-slate-800/60 last:border-b-0 ${visual.rowAccent}`}
      data-testid={`component-row-${component.name.replace(/\W+/g, '-').toLowerCase()}`}
    >
      <div className="flex items-center gap-3 min-w-0">
        <span className={`w-2.5 h-2.5 rounded-full ${visual.dot} shrink-0`} aria-hidden="true" />
        <div className="min-w-0">
          <p className="text-sm sm:text-base font-semibold text-slate-100 truncate">
            {component.name}
          </p>
          <p className="text-xs text-slate-400 truncate">{component.description}</p>
        </div>
      </div>
      <StatusPill status={component.status} />
    </div>
  );
}

function UptimeBlock({ pct, windowDays }) {
  const tone =
    pct >= 99.9 ? 'text-emerald-300' :
    pct >= 99   ? 'text-amber-300'   :
    pct >= 95   ? 'text-orange-300'  :
                  'text-rose-300';
  return (
    <section
      className="rounded-2xl border border-slate-800/60 bg-slate-900/40 p-6 mb-10"
      data-testid="uptime-block"
    >
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <p className="text-xs text-slate-400 uppercase tracking-widest font-semibold mb-2">
            Rolling uptime ({windowDays}-day)
          </p>
          <p
            className={`text-5xl sm:text-6xl font-bold tabular-nums ${tone}`}
            data-testid="uptime-pct"
          >
            {pct?.toFixed?.(2) ?? '—'}
            <span className="text-2xl sm:text-3xl ml-1 text-slate-500">%</span>
          </p>
        </div>
        <p className="text-sm text-slate-400 max-w-md">
          Computed from resolved incidents of major or critical severity over the
          last {windowDays} days. Active incidents are excluded until they resolve
          so we never overstate availability.
        </p>
      </div>
    </section>
  );
}

function IncidentItem({ incident }) {
  const tone = SEVERITY_TONE[incident.severity] || SEVERITY_TONE.minor;
  const isResolved = incident.status === 'resolved';
  return (
    <li
      className="flex items-start gap-4 pl-4 py-4 border-l-2 border-slate-800/60 relative"
      data-testid={`incident-${incident.id}`}
    >
      <span
        className={`absolute -left-[5px] top-5 w-2 h-2 rounded-full ${isResolved ? 'bg-emerald-400' : 'bg-rose-400'}`}
        aria-hidden="true"
      />
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2 mb-1">
          <span
            className={`inline-flex items-center px-2 py-0.5 rounded-full border ${tone.bg} ${tone.border} ${tone.text} text-[10px] font-bold uppercase tracking-wider`}
          >
            {tone.label}
          </span>
          <span
            className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
              isResolved
                ? 'bg-emerald-500/10 border border-emerald-500/30 text-emerald-300'
                : 'bg-rose-500/10 border border-rose-500/30 text-rose-300'
            }`}
          >
            {isResolved ? 'Resolved' : 'Investigating'}
          </span>
        </div>
        <p className="text-sm font-semibold text-slate-100">{incident.title}</p>
        <p className="text-xs text-slate-400 mt-1">
          {formatLocalDate(incident.started_at)}
          {incident.duration_minutes != null && (
            <>
              {' · '}
              <span className="text-slate-300">{formatDuration(incident.duration_minutes)}</span>
            </>
          )}
        </p>
      </div>
    </li>
  );
}

function IncidentTimeline({ incidents }) {
  const grouped = useMemo(() => groupIncidentsByDate(incidents), [incidents]);

  if (incidents.length === 0) {
    return (
      <section
        className="rounded-2xl border border-emerald-500/20 bg-emerald-500/[0.03] p-8 text-center"
        data-testid="no-incidents-empty-state"
      >
        <CheckCircle2 className="w-10 h-10 text-emerald-400 mx-auto mb-3" aria-hidden="true" />
        <p className="text-emerald-200 font-semibold">No incidents reported in the last 30 days.</p>
        <p className="text-xs text-slate-400 mt-2">
          That's the quiet you want from a safety system.
        </p>
      </section>
    );
  }

  return (
    <div className="space-y-8" data-testid="incident-timeline">
      {grouped.map(([day, items]) => (
        <section key={day} data-testid={`incident-day-${day}`}>
          <h3 className="text-xs text-slate-400 uppercase tracking-widest font-semibold mb-3">
            {new Date(day).toLocaleDateString('en-IN', {
              day: 'numeric',
              month: 'long',
              year: 'numeric',
            })}
          </h3>
          <ul className="space-y-0">
            {items.map((inc) => (
              <IncidentItem key={inc.id} incident={inc} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function ErrorState({ onRetry }) {
  return (
    <div
      className="rounded-2xl border border-rose-500/30 bg-rose-500/[0.04] p-8 text-center"
      data-testid="status-error-state"
    >
      <XCircle className="w-10 h-10 text-rose-400 mx-auto mb-3" aria-hidden="true" />
      <p className="text-rose-200 font-semibold">Status feed unavailable</p>
      <p className="text-xs text-slate-400 mt-2 mb-4">
        We couldn't reach the public status API. This page does not block any
        safety operation — the platform itself may still be healthy.
      </p>
      <button
        type="button"
        onClick={onRetry}
        data-testid="status-error-retry"
        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-100 text-sm font-semibold transition-colors"
      >
        <RefreshCw className="w-4 h-4" aria-hidden="true" />
        Try again
      </button>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="animate-pulse" data-testid="status-loading-skeleton">
      <div className="h-28 rounded-2xl bg-slate-800/40 mb-10" />
      <div className="space-y-3 mb-10">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-16 rounded-xl bg-slate-800/40" />
        ))}
      </div>
      <div className="h-32 rounded-2xl bg-slate-800/40 mb-10" />
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-20 rounded-xl bg-slate-800/40" />
        ))}
      </div>
    </div>
  );
}

export default function PublicStatusPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchStatus = useCallback(async () => {
    setRefreshing(true);
    try {
      const res = await fetch(STATUS_ENDPOINT, {
        // Don't send credentials — this is a fully public endpoint.
        credentials: 'omit',
        cache: 'no-store',
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
      setError(false);
    } catch (e) {
      // Keep last-known-good data visible so a transient network blip
      // doesn't blank the page.
      setError(!data);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [data]);

  useEffect(() => {
    fetchStatus();
    const id = setInterval(fetchStatus, REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
    // We intentionally re-create the interval only on mount — fetchStatus's
    // dependency on `data` lets it close over the latest value for the
    // error fallback, but the interval itself stays stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const overallStatus = data?.overall || 'operational';
  const components = data?.components || [];
  const incidents = data?.incidents || [];
  const uptimePct = data?.uptime_30d_pct;
  const uptimeDays = data?.uptime_window_days || 30;

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-slate-100" data-testid="public-status-page">
      {/* Header */}
      <header className="border-b border-slate-800/60 bg-slate-900/40 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2.5" data-testid="status-page-home-link">
            <div className="w-8 h-8 rounded-lg bg-teal-500/15 border border-teal-500/40 flex items-center justify-center">
              <span className="text-teal-300 font-black text-sm">N</span>
            </div>
            <span className="font-bold text-slate-100 text-sm tracking-wide">NISCHINT STATUS</span>
          </Link>
          <a
            href="https://nischint.care/"
            className="text-xs text-slate-400 hover:text-slate-200 transition-colors inline-flex items-center gap-1"
            data-testid="status-page-main-site-link"
          >
            nischint.care
            <ExternalLink className="w-3 h-3" aria-hidden="true" />
          </a>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-10 sm:py-14">
        {loading && !data ? (
          <LoadingSkeleton />
        ) : error ? (
          <ErrorState onRetry={fetchStatus} />
        ) : (
          <>
            <OverallBanner
              status={overallStatus}
              lastUpdatedIso={data?.generated_at}
              refreshing={refreshing}
              onRefresh={fetchStatus}
            />

            <section className="mb-10" data-testid="components-section">
              <h2 className="text-sm font-bold text-slate-300 uppercase tracking-widest mb-4">
                Components
              </h2>
              <div className="rounded-2xl border border-slate-800/60 bg-slate-900/30 overflow-hidden">
                {components.map((c) => (
                  <ComponentRow key={c.name} component={c} />
                ))}
              </div>
            </section>

            <UptimeBlock pct={uptimePct} windowDays={uptimeDays} />

            <section data-testid="incidents-section">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-sm font-bold text-slate-300 uppercase tracking-widest">
                  Past incidents ({uptimeDays} days)
                </h2>
                <span className="text-xs text-slate-500" data-testid="incident-count-label">
                  {incidents.length} {incidents.length === 1 ? 'event' : 'events'}
                </span>
              </div>
              <IncidentTimeline incidents={incidents} />
            </section>
          </>
        )}
      </main>

      <footer className="border-t border-slate-800/60 mt-10">
        <div className="max-w-5xl mx-auto px-6 py-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <p className="text-[11px] text-slate-400">
            Public status feed.{' '}
            <a
              href="/api/public/status"
              className="text-teal-400 hover:text-teal-300 transition-colors inline-flex items-center gap-1"
              data-testid="status-page-api-link"
            >
              JSON endpoint
              <ChevronRight className="w-3 h-3" aria-hidden="true" />
            </a>
          </p>
          <p className="text-[11px] text-slate-400">
            &copy; {new Date().getFullYear()} Nischint Technologies. All rights reserved.
          </p>
        </div>
      </footer>
    </div>
  );
}
