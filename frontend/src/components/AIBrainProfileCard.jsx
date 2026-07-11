import React, { useEffect, useState } from 'react';
import { Brain, Sparkles, ChevronDown, ChevronUp } from 'lucide-react';
import api from '../api';

/**
 * AIBrainProfileCard — "Who Am I to the Brain?"
 *
 * Surfaces the persisted per-user adaptation profile in plain English, so
 * users can see (and trust) what the AI has actually learned about them.
 *
 * Data source: GET /api/ai-brain/user-adjustment/{user_id}
 *
 * Graceful fallbacks:
 *   - no user id → renders nothing
 *   - 0 feedback → "Still learning your patterns…" (warm, not sad)
 *   - API error → silently skip (not critical to page function)
 */
export default function AIBrainProfileCard({ userId }) {
  const [data, setData] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!userId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get(`/ai-brain/user-adjustment/${encodeURIComponent(userId)}`);
        if (!cancelled) setData(res.data);
      } catch {
        /* silent — card just won't render */
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  }, [userId]);

  if (!userId || !loaded || !data) return null;

  const n = data.feedback_count || 0;
  const adj = Number(data.adjustment ?? 0);
  const avgConf = data.confidence_profile?.avg_confidence ?? null;

  // Headline in plain English
  let headline, subline, tone;
  if (n === 0) {
    headline = 'Still learning your patterns…';
    subline = 'Give feedback on any alert to personalise your brain.';
    tone = 'neutral';
  } else if (adj > 3) {
    headline = 'You prefer fewer false alarms';
    subline = `Brain is being less sensitive for you (+${adj}) based on ${n} feedback${n === 1 ? '' : 's'}.`;
    tone = 'calm';
  } else if (adj < -3) {
    headline = 'You want alerts earlier';
    subline = `Brain is being more sensitive for you (${adj}) based on ${n} feedback${n === 1 ? '' : 's'}.`;
    tone = 'alert';
  } else {
    headline = 'Your sensitivity feels balanced';
    subline = `Brain is running default thresholds for you (adj ${adj >= 0 ? '+' : ''}${adj}) across ${n} feedback${n === 1 ? '' : 's'}.`;
    tone = 'balanced';
  }

  const toneClass = {
    calm:     'bg-emerald-500/10 border-emerald-500/25 text-emerald-300',
    alert:    'bg-amber-500/10 border-amber-500/25 text-amber-300',
    balanced: 'bg-indigo-500/10 border-indigo-500/25 text-indigo-300',
    neutral:  'bg-slate-500/10 border-slate-500/25 text-slate-300',
  }[tone];

  return (
    <div
      className="rounded-2xl bg-slate-800/40 border border-slate-700/40 p-4 mb-4"
      data-testid="ai-brain-profile-card"
    >
      <div className="flex items-start gap-3">
        <div className={`w-9 h-9 rounded-full flex items-center justify-center border ${toneClass}`}>
          <Brain className="w-4.5 h-4.5" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-0.5">
            <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium">
              Who you are to the brain
            </p>
            <Sparkles className="w-3 h-3 text-indigo-400" />
          </div>
          <p className="text-sm font-semibold text-white" data-testid="ai-brain-headline">
            {headline}
          </p>
          <p className="text-[11px] text-slate-400 mt-0.5 leading-snug" data-testid="ai-brain-subline">
            {subline}
          </p>

          {n > 0 && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="mt-2 text-[10px] text-indigo-400 flex items-center gap-0.5 hover:text-indigo-300"
              data-testid="ai-brain-toggle-details"
            >
              {expanded ? 'Hide details' : 'Show details'}
              {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            </button>
          )}

          {expanded && n > 0 && (
            <div className="mt-2 grid grid-cols-3 gap-1.5" data-testid="ai-brain-details">
              <Metric label="👍 Correct" value={data.true_positive_count ?? 0} />
              <Metric label="👎 False alarm" value={data.false_alarm_count ?? 0} />
              <Metric label="⚠️ Missed" value={data.missed_count ?? 0} />
              {avgConf != null && (
                <Metric label="Avg confidence" value={`${Math.round(avgConf * 100)}%`} />
              )}
              {data.false_positive_rate_weighted != null && (
                <Metric label="FP rate (w)" value={`${Math.round(data.false_positive_rate_weighted * 100)}%`} />
              )}
              {data.confidence_profile?.high_conf_error_rate != null && (
                <Metric
                  label="High-conf errors"
                  value={`${Math.round(data.confidence_profile.high_conf_error_rate * 100)}%`}
                />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const Metric = ({ label, value }) => (
  <div className="rounded-lg bg-slate-900/40 border border-slate-700/30 px-2 py-1.5">
    <p className="text-[9px] text-slate-500 uppercase tracking-wider">{label}</p>
    <p className="text-xs text-white font-semibold tabular-nums mt-0.5">{value}</p>
  </div>
);
