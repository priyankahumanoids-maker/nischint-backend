// SF-01 v2 Day 4 — Investor demo button row.
//
// Operator-gated, env-flag-gated. Renders a horizontal row of one
// button per scenario returned by `GET /api/operator/dev/scenarios`.
// Clicking fires `POST /api/operator/dev/scenario` and surfaces the
// returned composite + action inline — no page reload, no terminal
// on stage.
//
// Strict additive contract:
//   * Renders nothing in production (the backend endpoint 403s when
//     `DEV_SCENARIOS_ENABLED` is unset, so the `/scenarios` GET
//     returns 403 too — we hide the panel on that signal).
//   * Never affects real telemetry / dispatch / trust flow.
//   * The injected hazard expires via Redis TTL — no cleanup
//     button needed.

import React, { useEffect, useMemo, useState } from 'react';
import { Flame, Loader2, Zap } from 'lucide-react';
import api from '../../api';

// Tone token — matches the broader Command Center "alert vs ambient"
// language: amber for "demo / dev", rose flash for "fired result".
const TONE = {
  shell: 'border border-amber-700/50 bg-amber-950/30',
  title: 'text-amber-200',
  btn:   'border-amber-700/60 bg-amber-900/40 hover:bg-amber-900/70 text-amber-100',
};

const ACTION_COLOR = {
  emergency: 'text-rose-300',
  alert:     'text-rose-200',
  watch:     'text-amber-200',
  normal:    'text-emerald-200',
};

export const DevScenarioPanel = ({ targetUserId }) => {
  const [available, setAvailable]   = useState(null);  // null=unknown, []=disabled
  const [pending, setPending]       = useState(null);  // scenario id while firing
  const [lastResult, setLastResult] = useState(null);  // last fire envelope
  const [error, setError]           = useState(null);

  // Probe on mount. 403 → hide the panel entirely. 200 → render.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await api.get('/operator/dev/scenarios');
        if (cancelled) return;
        setAvailable(r.data?.scenarios || []);
      } catch (e) {
        if (cancelled) return;
        // 403 (env flag off or non-operator role) is the expected
        // "production" state — silently render nothing.
        setAvailable([]);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const fire = async (scenarioId) => {
    if (!targetUserId) {
      setError('Select a user first.');
      return;
    }
    setError(null);
    setPending(scenarioId);
    try {
      const r = await api.post('/operator/dev/scenario', {
        scenario:       scenarioId,
        target_user_id: targetUserId,
        ttl_minutes:    5,
      });
      setLastResult(r.data);
      // SF-01 v2 Day 5 — row flash. Dispatch a window-level
      // CustomEvent so CommandCenterPage can amber-glow the target
      // row for 3s. Decoupled (no prop drilling) — the page listens
      // for `nischint:scenario-fired` and times out the flash itself.
      try {
        window.dispatchEvent(new CustomEvent('nischint:scenario-fired', {
          detail: {
            target_user_id: targetUserId,
            scenario:       scenarioId,
            composite:      r.data?.composite,
            action:         r.data?.action,
          },
        }));
      } catch {
        // CustomEvent unsupported (very old browser) — silently
        // drop. The result chip in-panel still renders.
      }
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || 'fire failed');
    } finally {
      setPending(null);
    }
  };

  const result = useMemo(() => {
    if (!lastResult) return null;
    const action = (lastResult.action || 'normal').toLowerCase();
    return {
      scenario:  lastResult.label || lastResult.scenario,
      composite: Number(lastResult.composite ?? 0).toFixed(3),
      preMult:   Number(lastResult.pre_mult_score ?? 0).toFixed(3),
      mult:      Number(lastResult.env_multiplier ?? 1.0).toFixed(2),
      action,
      cooldown:  Boolean(lastResult.cooldown_suppressed),
      envType:   lastResult.env_hazard_type,
    };
  }, [lastResult]);

  // Hidden by default — only renders when the backend says scenarios
  // are enabled AND at least one is registered.
  if (available === null) return null;
  if (!Array.isArray(available) || available.length === 0) return null;

  return (
    <div
      data-testid="dev-scenario-panel"
      className={`rounded-lg ${TONE.shell} p-3 space-y-2`}
    >
      <div className="flex items-center gap-2">
        <Flame size={14} className="text-amber-300" />
        <span
          data-testid="dev-scenario-title"
          className={`text-xs font-semibold uppercase tracking-wider ${TONE.title}`}
        >
          Demo · Fire Scenario
        </span>
        <span className="text-[10px] text-amber-400/70 ml-auto">
          DEV ENV · operator only
        </span>
      </div>

      <div className="flex flex-wrap gap-2">
        {available.map((s) => (
          <button
            key={s.id}
            data-testid={`dev-scenario-fire-${s.id}`}
            type="button"
            onClick={() => fire(s.id)}
            disabled={!!pending}
            className={`inline-flex items-center gap-1.5 rounded-full border ${TONE.btn} px-3 py-1.5 text-xs font-medium tracking-wide transition-colors disabled:opacity-50 disabled:cursor-not-allowed`}
          >
            {pending === s.id ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <Zap size={12} />
            )}
            <span>Fire: {s.label}</span>
            <span className="text-[10px] opacity-60">· {s.state}</span>
          </button>
        ))}
      </div>

      {error && (
        <div
          data-testid="dev-scenario-error"
          className="text-xs text-rose-300"
        >
          {error}
        </div>
      )}

      {result && (
        <div
          data-testid="dev-scenario-result"
          className="rounded-md border border-amber-800/40 bg-amber-950/40 px-3 py-2 text-xs space-y-1"
        >
          <div className="flex items-center gap-2 text-amber-100">
            <span className="font-semibold">{result.scenario}</span>
            <span
              data-testid="dev-scenario-result-action"
              className={`font-bold uppercase tracking-wider ${ACTION_COLOR[result.action] || 'text-slate-200'}`}
            >
              {result.action}
            </span>
            {result.cooldown && (
              <span className="text-[10px] text-amber-300/70">
                (cooldown · re-fire suppressed)
              </span>
            )}
          </div>
          <div className="text-amber-200/80 font-mono">
            base {result.preMult} · ×{result.mult} env →{' '}
            <span
              data-testid="dev-scenario-result-composite"
              className="text-amber-50 font-bold"
            >
              {result.composite}
            </span>
            <span className="opacity-60"> · {result.envType}</span>
          </div>
        </div>
      )}
    </div>
  );
};

export default DevScenarioPanel;
