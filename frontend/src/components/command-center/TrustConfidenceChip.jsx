/**
 * TrustConfidenceChip — Operator-facing "do I trust the AI right now?" chip.
 *
 * Reads `GET /api/ai/confidence/{userId}` (OCE-01) and renders a compact
 * card with:
 *   • Score ring (0..1, color-coded — red < 0.4, amber < 0.7, green ≥ 0.7)
 *   • Trend pill (improving / stable / degrading)
 *   • 7-day sparkline (inline SVG, no extra deps)
 *   • Collapsible explanation list (3–5 plain English strings from the API)
 *
 * Lifecycle:
 *   • Self-fetches on mount and whenever `userId` changes.
 *   • Auto-refreshes every 30 s (matches the Redis cache TTL on the
 *     backend — refreshing faster gives no fresh data).
 *   • Renders nothing if `userId` is null/empty (Command Center hasn't
 *     selected a user yet) so the surrounding panel doesn't reserve
 *     empty space.
 *   • On API failure: shows a compact error pill with a retry button —
 *     never blanks the surrounding context.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Brain, ChevronDown, ChevronUp, TrendingUp, TrendingDown, Minus,
  RefreshCw, AlertCircle,
} from 'lucide-react';
import api from '../../api';

const REFRESH_MS = 30_000;

const TONE_BY_SCORE = (s) => {
  if (s == null) return { ring: '#475569', text: 'text-slate-300', bg: 'bg-slate-700/40', label: '—' };
  if (s >= 0.7) return { ring: '#34d399', text: 'text-emerald-300', bg: 'bg-emerald-500/10', label: 'high' };
  if (s >= 0.4) return { ring: '#fbbf24', text: 'text-amber-300', bg: 'bg-amber-500/10', label: 'medium' };
  return { ring: '#fb7185', text: 'text-rose-300', bg: 'bg-rose-500/10', label: 'low' };
};

const TREND_VISUAL = {
  improving: { Icon: TrendingUp,   color: 'text-emerald-300', bg: 'bg-emerald-500/10', label: 'Improving' },
  stable:    { Icon: Minus,        color: 'text-slate-300',   bg: 'bg-slate-700/40',   label: 'Stable' },
  degrading: { Icon: TrendingDown, color: 'text-rose-300',    bg: 'bg-rose-500/10',    label: 'Degrading' },
};

function ScoreRing({ score }) {
  const tone = TONE_BY_SCORE(score);
  const pct = Math.max(0, Math.min(1, score ?? 0));
  // Conic gradient: filled portion in tone color, rest dark slate
  const angle = pct * 360;
  return (
    <div
      data-testid="trust-chip-score-ring"
      className="relative w-16 h-16 rounded-full flex items-center justify-center shrink-0"
      style={{
        background: `conic-gradient(${tone.ring} ${angle}deg, rgba(51,65,85,0.4) ${angle}deg)`,
      }}
    >
      <div className="w-12 h-12 rounded-full bg-slate-900 flex flex-col items-center justify-center">
        <span className={`text-base font-bold tabular-nums ${tone.text}`}>
          {score == null ? '—' : (score * 100).toFixed(0)}
        </span>
        <span className="text-[8px] uppercase tracking-wider text-slate-400 leading-none">
          /100
        </span>
      </div>
    </div>
  );
}

function Sparkline({ history }) {
  // SVG sparkline — no chart lib, ~30 lines of geometry.
  // Empty / 1-pt history collapses to a flat hint line so the layout
  // is stable across users.
  const W = 96;
  const H = 28;
  const PAD = 2;
  const points = useMemo(() => {
    if (!history || history.length === 0) return [];
    if (history.length === 1) {
      return [{ x: PAD, y: H / 2 }, { x: W - PAD, y: H / 2 }];
    }
    const xs = history.map((_, i) => PAD + (i * (W - 2 * PAD)) / (history.length - 1));
    const ys = history.map((p) => {
      const s = Math.max(0, Math.min(1, p.score ?? 0));
      return H - PAD - s * (H - 2 * PAD);
    });
    return xs.map((x, i) => ({ x, y: ys[i] }));
  }, [history]);

  if (points.length === 0) {
    return (
      <span className="text-[10px] text-slate-500 italic">
        No history yet
      </span>
    );
  }

  const lastScore = history[history.length - 1]?.score ?? 0;
  const stroke = TONE_BY_SCORE(lastScore).ring;
  const d = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  const fillPath = `${d} L${(W - PAD).toFixed(1)},${(H - PAD).toFixed(1)} L${PAD.toFixed(1)},${(H - PAD).toFixed(1)} Z`;

  return (
    <svg
      width={W}
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      data-testid="trust-chip-sparkline"
      aria-label="7-day overall AI confidence trend"
    >
      <path d={fillPath} fill={stroke} fillOpacity="0.12" />
      <path d={d} stroke={stroke} strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      {points.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={i === points.length - 1 ? 2 : 1.2} fill={stroke} />
      ))}
    </svg>
  );
}

function TrendPill({ trend }) {
  const v = TREND_VISUAL[trend] || TREND_VISUAL.stable;
  const { Icon } = v;
  return (
    <span
      data-testid={`trust-chip-trend-${trend}`}
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full ${v.bg} ${v.color} text-[10px] font-bold uppercase tracking-wider`}
    >
      <Icon className="w-3 h-3" aria-hidden="true" />
      {v.label}
    </span>
  );
}

export default function TrustConfidenceChip({ userId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const fetchOnce = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    try {
      // The shared `api` axios instance automatically injects the
      // `Authorization: Bearer <token>` header via its request
      // interceptor, so we don't need to read localStorage here.
      const res = await api.get(`/ai/confidence/${userId}`);
      setData(res.data);
      setError(false);
    } catch (_e) {
      setError(!data);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  // Clear payload immediately when userId changes so an old user's
  // numbers don't flash on screen during the new fetch.
  useEffect(() => {
    setData(null);
    setExpanded(false);
  }, [userId]);

  useEffect(() => {
    if (!userId) return undefined;
    fetchOnce();
    const id = setInterval(fetchOnce, REFRESH_MS);
    return () => clearInterval(id);
  }, [userId, fetchOnce]);

  if (!userId) return null;

  if (error && !data) {
    return (
      <div
        data-testid="trust-chip-error"
        className="flex items-center justify-between gap-2 px-3 py-2 rounded-lg border border-rose-500/30 bg-rose-500/[0.04]"
      >
        <div className="flex items-center gap-2 text-rose-300 text-xs">
          <AlertCircle className="w-3.5 h-3.5" aria-hidden="true" />
          AI confidence unavailable
        </div>
        <button
          type="button"
          onClick={fetchOnce}
          data-testid="trust-chip-retry"
          aria-label="Retry AI confidence fetch"
          className="p-1 rounded hover:bg-rose-500/10 text-rose-300"
        >
          <RefreshCw className="w-3.5 h-3.5" aria-hidden="true" />
        </button>
      </div>
    );
  }

  const score = data?.overall_confidence;
  const trend = data?.trend || 'stable';
  const history = data?.history || [];
  const explanation = data?.explanation || [];
  const tone = TONE_BY_SCORE(score);

  return (
    <div
      data-testid="trust-confidence-chip"
      className={`rounded-xl border border-slate-800/60 ${tone.bg} backdrop-blur-sm`}
    >
      <div className="flex items-center justify-between gap-3 px-3 py-2.5">
        <div className="flex items-center gap-3 min-w-0">
          <ScoreRing score={score} />
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <Brain className="w-3.5 h-3.5 text-slate-400" aria-hidden="true" />
              <span className="text-[10px] uppercase tracking-widest font-semibold text-slate-400">
                AI Confidence
              </span>
              <TrendPill trend={trend} />
            </div>
            <p className={`text-sm font-semibold mt-0.5 ${tone.text}`} data-testid="trust-chip-label">
              {tone.label.charAt(0).toUpperCase() + tone.label.slice(1)} trust
              <span className="text-slate-400 font-normal text-xs ml-2">
                ({history.length || 0}-day series)
              </span>
            </p>
            <div className="mt-1.5">
              <Sparkline history={history} />
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {loading && (
            <RefreshCw
              className="w-3 h-3 text-slate-500 animate-spin"
              aria-label="Refreshing"
            />
          )}
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            aria-label={expanded ? 'Collapse explanation' : 'Expand explanation'}
            data-testid="trust-chip-expand-toggle"
            className="p-1 rounded hover:bg-slate-800/50 text-slate-300"
          >
            {expanded ? (
              <ChevronUp className="w-4 h-4" aria-hidden="true" />
            ) : (
              <ChevronDown className="w-4 h-4" aria-hidden="true" />
            )}
          </button>
        </div>
      </div>

      {expanded && (
        <ul
          data-testid="trust-chip-explanation"
          className="px-3 pb-3 pt-1 border-t border-slate-800/60 space-y-1.5"
        >
          {explanation.length === 0 ? (
            <li className="text-xs text-slate-400 italic">No explanation available.</li>
          ) : (
            explanation.map((line, i) => (
              <li
                key={i}
                data-testid={`trust-chip-explanation-line-${i}`}
                className="text-xs text-slate-300 leading-relaxed flex items-start gap-1.5"
              >
                <span className="text-slate-500 mt-0.5">•</span>
                <span>{line}</span>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
