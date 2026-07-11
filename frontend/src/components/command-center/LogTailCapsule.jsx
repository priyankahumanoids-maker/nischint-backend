// REL-02 — Operator-facing log tail capsule.
//
// Auto-polls `/api/admin/monitoring/logs/tail?since_minutes=5&lines=500`
// every 10 s. Surfaces backend supervisor log lines into the
// Command Center so an operator hitting a "degraded" capsule
// can see what the log is saying RIGHT NOW without leaving the
// console.
//
// Locked decisions:
//   * Polling interval: 10 s (matches the cadence of other capsules,
//     gives the operator a real-time feel without DOSing the API).
//   * Hard ceiling 500 lines — matches the backend's MAX_LINES so
//     we never get into "the API truncated, the UI doesn't know".
//   * DIY virtualisation (`react-window` not in package.json). We
//     compute the visible window from scrollTop + rowHeight and
//     render ~max 60 rows at a time. 500 plain DOM nodes is too
//     many for smooth scrolling on lower-end ops machines.
//   * Level-based colouring keys off the `level` field of the
//     JSON log envelope. Unparseable lines stay rendered (operators
//     need to see tracebacks) — they get the default grey.
//   * Regex filter is permissive: invalid regex falls back to
//     plain-substring match so an operator doesn't lose their
//     view to a syntax error mid-typing.
//   * Same z-[1500] flyout pattern as SystemHealthCapsule for
//     overlay consistency.

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ScrollText, Pause, Play, Copy, X, Search } from 'lucide-react';
import api from '../../api';
import { parseLine, filterLines, fmtClock, LEVEL_TONE } from './logTailHelpers';

// ── Locked constants ─────────────────────────────────────────────
const POLL_INTERVAL_MS = 10_000;
const SINCE_MINUTES    = 5;
const MAX_LINES        = 500;
const ROW_HEIGHT_PX    = 18;       // single fixed row height — required for virtualisation math
const FLYOUT_HEIGHT_PX = 420;      // outer fly-out content area
const VIEWPORT_HEIGHT  = 320;      // virtualised viewport (header + chrome subtracted)
const OVERSCAN_ROWS    = 8;        // render this many extra rows above + below the visible window

// ── Capsule ──────────────────────────────────────────────────────

export const LogTailCapsule = () => {
  const [open, setOpen]       = useState(false);
  const [paused, setPaused]   = useState(false);
  const [lines, setLines]     = useState([]);
  const [error, setError]     = useState(null);
  const [query, setQuery]     = useState('');
  const [lastFetchAt, setLastFetchAt] = useState(null);
  const containerRef = useRef(null);
  const scrollRef    = useRef(null);
  const [scrollTop, setScrollTop] = useState(0);

  // Poll loop — only when open AND not paused. Skips fetch when
  // closed so we don't burn the API budget for a chip nobody is
  // looking at.
  useEffect(() => {
    if (!open || paused) return;
    let alive = true;
    const tick = async () => {
      try {
        const res = await api.get(
          `/admin/monitoring/logs/tail?lines=${MAX_LINES}&since_minutes=${SINCE_MINUTES}`
        );
        if (!alive) return;
        const parsed = (res.data?.lines || []).map(parseLine);
        setLines(parsed);
        setLastFetchAt(Date.now());
        setError(null);
      } catch (e) {
        if (!alive) return;
        setError(e.response?.status === 403 ? 'forbidden' : 'failed');
      }
    };
    tick();
    const iv = setInterval(tick, POLL_INTERVAL_MS);
    return () => { alive = false; clearInterval(iv); };
  }, [open, paused]);

  // Outside-click / Esc to dismiss — same pattern as
  // SystemHealthCapsule.
  useEffect(() => {
    if (!open) return;
    const onClick = (e) => { if (!containerRef.current?.contains(e.target)) setOpen(false); };
    const onEsc   = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown',   onEsc);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown',   onEsc);
    };
  }, [open]);

  // ── Filtering + virtualisation maths ──────────────────────────
  const filtered = useMemo(() => filterLines(lines, query), [lines, query]);

  // Visible window indices — compute once per scroll/filter change.
  // `endIndex` is bounded by the filtered length so we never
  // overshoot when the user types a narrow regex.
  const startIndex = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT_PX) - OVERSCAN_ROWS);
  const visibleCount = Math.ceil(VIEWPORT_HEIGHT / ROW_HEIGHT_PX) + OVERSCAN_ROWS * 2;
  const endIndex = Math.min(filtered.length, startIndex + visibleCount);
  const visible  = filtered.slice(startIndex, endIndex);

  const onScroll = (e) => setScrollTop(e.currentTarget.scrollTop);

  // Auto-scroll to bottom when new lines arrive AND user isn't
  // mid-scroll (i.e. they're parked at the bottom). We detect
  // "parked at bottom" as scrollTop being within 1 row of the max.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || paused) return;
    const max = el.scrollHeight - el.clientHeight;
    if (max - el.scrollTop <= ROW_HEIGHT_PX * 2) {
      el.scrollTop = max;
    }
  }, [lines.length, paused]);

  // ── Action handlers ───────────────────────────────────────────
  const onCopyAsJson = () => {
    const payload = JSON.stringify({
      exported_at:   new Date().toISOString(),
      since_minutes: SINCE_MINUTES,
      count:         filtered.length,
      query:         query || null,
      lines:         filtered.map(l => l.raw),
    }, null, 2);
    navigator.clipboard?.writeText(payload).catch(() => {});
  };

  // ── Capsule chip counts (hooks MUST be above the early return) ─
  const errorCount = useMemo(
    () => lines.filter(l => l.level === 'ERROR' || l.level === 'CRITICAL').length,
    [lines]
  );
  const warnCount = useMemo(
    () => lines.filter(l => l.level === 'WARNING' || l.level === 'WARN').length,
    [lines]
  );

  // Forbidden = operator hasn't been granted log access (rare —
  // _read_role allows admin + operator). Render nothing so the
  // capsule strip doesn't show a broken affordance.
  if (error === 'forbidden') return null;

  const tone = errorCount > 0
    ? 'border-red-700/60 hover:bg-red-900/30'
    : warnCount > 0
      ? 'border-amber-700/60 hover:bg-amber-900/30'
      : 'border-slate-700/50 hover:bg-slate-700/60';

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className={`flex items-center gap-1.5 px-2 py-1 rounded-md bg-slate-800/70 border ${tone} transition-colors`}
        data-testid="log-tail-capsule"
        title={`Backend logs · last ${SINCE_MINUTES}min`}
      >
        <ScrollText className="w-3 h-3 text-slate-400" />
        <span className="text-[10px] font-mono font-bold tracking-wider text-slate-300">LOGS</span>
        {errorCount > 0 && (
          <span className="text-[9px] font-mono font-bold text-red-300 px-1 rounded bg-red-900/40" data-testid="log-tail-error-count">
            {errorCount}E
          </span>
        )}
        {warnCount > 0 && errorCount === 0 && (
          <span className="text-[9px] font-mono font-bold text-amber-200 px-1 rounded bg-amber-900/30">
            {warnCount}W
          </span>
        )}
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-1.5 z-[1500] w-[640px] max-w-[calc(100vw-1.5rem)] rounded-md border border-slate-700 bg-slate-900/95 backdrop-blur shadow-xl"
          data-testid="log-tail-capsule-flyout"
          style={{ height: FLYOUT_HEIGHT_PX }}
        >
          {/* Header */}
          <div className="px-3 py-2 border-b border-slate-700/60 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <ScrollText className="w-3 h-3 text-slate-400 shrink-0" />
              <span className="text-[10px] font-mono font-bold tracking-wider text-slate-200">
                BACKEND LOGS · last {SINCE_MINUTES}m
              </span>
              <span className="text-[9px] font-mono text-slate-500">
                {filtered.length}/{lines.length} lines
                {lastFetchAt && ` · ${Math.max(0, Math.round((Date.now() - lastFetchAt) / 1000))}s ago`}
              </span>
              {paused && (
                <span className="text-[9px] font-mono text-amber-300 px-1 rounded bg-amber-900/30" data-testid="log-tail-paused-indicator">
                  PAUSED
                </span>
              )}
              {error === 'failed' && (
                <span className="text-[9px] font-mono text-red-300">fetch failed</span>
              )}
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setPaused(p => !p)}
                className="inline-flex items-center justify-center w-6 h-6 rounded hover:bg-slate-700/70 text-slate-400 hover:text-slate-200"
                data-testid="log-tail-pause-btn"
                title={paused ? 'Resume polling' : 'Pause polling'}
              >
                {paused ? <Play className="w-3 h-3" /> : <Pause className="w-3 h-3" />}
              </button>
              <button
                type="button"
                onClick={onCopyAsJson}
                className="inline-flex items-center justify-center w-6 h-6 rounded hover:bg-slate-700/70 text-slate-400 hover:text-slate-200"
                data-testid="log-tail-copy-btn"
                title="Copy filtered lines as JSON"
              >
                <Copy className="w-3 h-3" />
              </button>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="inline-flex items-center justify-center w-6 h-6 rounded hover:bg-slate-700/70 text-slate-400 hover:text-slate-200"
                data-testid="log-tail-close-btn"
                title="Close"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          </div>

          {/* Search bar */}
          <div className="px-3 py-2 border-b border-slate-700/40 flex items-center gap-2">
            <Search className="w-3 h-3 text-slate-500 shrink-0" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Regex or substring filter…"
              className="flex-1 text-[11px] font-mono bg-slate-800/60 border border-slate-700/50 rounded px-2 py-1 text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-slate-500"
              data-testid="log-tail-search-input"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery('')}
                className="text-[10px] text-slate-500 hover:text-slate-300 font-mono"
                data-testid="log-tail-clear-search-btn"
              >
                clear
              </button>
            )}
          </div>

          {/* Virtualised viewport */}
          <div
            ref={scrollRef}
            onScroll={onScroll}
            className="overflow-y-auto"
            style={{ height: VIEWPORT_HEIGHT }}
            data-testid="log-tail-viewport"
          >
            {filtered.length === 0 ? (
              <div className="flex items-center justify-center h-full text-[10px] font-mono text-slate-600">
                {lines.length === 0 ? 'no log lines yet' : 'no lines match filter'}
              </div>
            ) : (
              <div style={{ height: filtered.length * ROW_HEIGHT_PX, position: 'relative' }}>
                <div style={{ position: 'absolute', top: startIndex * ROW_HEIGHT_PX, left: 0, right: 0 }}>
                  {visible.map((l, i) => {
                    const t = LEVEL_TONE[l.level] || LEVEL_TONE.unknown;
                    return (
                      <div
                        key={startIndex + i}
                        className={`flex items-center gap-2 px-3 ${t.bg} hover:bg-slate-700/30`}
                        style={{ height: ROW_HEIGHT_PX, lineHeight: `${ROW_HEIGHT_PX}px` }}
                        data-testid={`log-tail-row-${l.level.toLowerCase()}`}
                      >
                        <span className={`shrink-0 text-[8px] font-mono font-bold uppercase ${t.badge} text-white rounded px-1`}
                          style={{ minWidth: 32, textAlign: 'center' }}
                        >
                          {l.level === 'unknown' ? '—' : l.level.slice(0, 4)}
                        </span>
                        <span className="shrink-0 text-[9px] font-mono text-slate-500 tabular-nums">
                          {fmtClock(l.ts)}
                        </span>
                        <span className={`truncate text-[10px] font-mono ${t.text}`}>
                          {l.msg || l.raw}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

// Exported helpers re-exported here for direct test access without
// going through the React component's lifecycle.
export { parseLine, filterLines, fmtClock } from './logTailHelpers';
