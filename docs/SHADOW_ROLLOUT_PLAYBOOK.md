# Shadow Rollout Playbook

How to ship a behavioural change to NISCHINT's safety pipeline
without taking down production. Five-line constructor, one
classification function, automatic self-protection.

This document is the **onboarding contract for every future
behavioural-change PR**. You do *not* need to read
`alert_trigger_v2_shadow.py` to use the pattern — that file is just
one adopter. The reusable machinery lives in
`app/services/shadow_rollout.py`.

---

## When to use this pattern

Use the shadow rollout pattern any time you want to change how the
safety pipeline *behaves* — different dispatch routing, different
escalation policy, different trust weighting, different incident
opening rules. Use it when "rolling back is hard" because the side
effects (push, SMS, voice calls) have already fired by the time
you know something was wrong.

Do **not** use it for:
- pure read-path additions (no side effects to guard)
- internal data-shape migrations (use a schema migration instead)
- one-time data corrections (use a backfill script)

---

## The 5-line constructor pattern

```python
from app.services.shadow_rollout import (
    Classification, ShadowRolloutController,
)

controller = ShadowRolloutController(
    kind="my_new_dispatch_policy",
    classify_fn=my_classify_fn,
)
```

That's it. The controller now owns:

- A rolling 10-minute critical-event window.
- A self-protecting auto-disable safeguard (`critical_rate ≥ 5%`
  over the window with `≥ 20` samples → freezes the rollout
  regardless of env-var rollout %).
- A hysteresis-gated tier state machine
  (`in_parity → improving → drift → critical → auto_disabled`).
  Regressions snap immediately; recoveries require `20` consecutive
  clean events (50 for `drift`).
- Replay-safe idempotency on `event_id` (Redis SET NX, 1h TTL).
- Per-`kind` Redis namespace isolation — independent rollouts
  cannot pollute each other's state.

You can override any tunable at construction time:

```python
ShadowRolloutController(
    kind="my_new_dispatch_policy",
    classify_fn=my_classify_fn,
    autodisable_threshold_pct=0.05,
    autodisable_min_samples=20,
    autodisable_window_s=600,
    hysteresis_recovery=20,
    drift_recovery=50,
    dedup_ttl_s=3600,
)
```

Do not lower `autodisable_min_samples` below 20 — the rolling-rate
math is noisy under small samples, and the safeguard exists to
protect against silent regressions, not to fire on small-sample
flukes.

---

## How to write a `classify_fn`

The locked taxonomy lives **inside** `ShadowRolloutController`:

```python
class Classification(str, Enum):
    MATCH                = "match"
    IMPROVEMENT          = "improvement"
    REGRESSION           = "regression"
    CRITICAL_REGRESSION  = "critical_regression"
```

Your `classify_fn` receives whatever keyword arguments you pass to
`record()` and **MUST return a `Classification` enum value**. The
controller rejects plain strings — this prevents per-domain drift
of what "critical" means.

```python
def my_classify_fn(*, v1_decision, v2_decision, **_) -> Classification:
    if v1_decision == v2_decision:
        return Classification.MATCH
    if _v2_drops_critical_target(v1_decision, v2_decision):
        return Classification.CRITICAL_REGRESSION  # auto-disable fires
    if _v2_picks_healthier_target(v1_decision, v2_decision):
        return Classification.IMPROVEMENT
    return Classification.REGRESSION
```

**Only `CRITICAL_REGRESSION` feeds the auto-disable safeguard.**
That's deliberate. The taxonomy is intentionally coarse so the
safety contract is clear: "if the new logic could silently lose a
real alert, return `CRITICAL_REGRESSION` and the system protects
itself."

Domains can have richer internal labels (the V2 adapter has 7),
but those collapse to the generic 4-label vocabulary at the
controller boundary. The pattern is in
`alert_trigger_v2_shadow.py::_v2_label_to_generic` — feel free to
copy it for your own adapter.

---

## The `record()` idempotency contract

```python
result = await controller.record(
    event_id="dispatch-2026-05-10T08:00:00-incident-abc",
    v1_decision=...,
    v2_decision=...,
)
```

`event_id` is required. Duplicate events on replay (SSE reconnect,
retry storms, kafka redelivery) **must not corrupt streak
counters or trip the auto-disable safeguard**. The controller uses
Redis SET NX with a 1-hour TTL so the typical retry window is
covered.

Pick an `event_id` that:

- Is stable across retries of the same logical event (deterministic
  hash of the inputs is ideal).
- Is unique per logical event (do not reuse an `incident_id` if
  the same incident can fire multiple dispatch comparisons).
- Survives a process restart (in-memory IDs do not qualify).

Good event_ids:
- `f"v2-{alert_id}"`
- `f"trust-route-{incident_id}-{leg_no}"`

Bad event_ids:
- `str(uuid4())` — non-deterministic; replays count twice
- `incident_id` — collides if the same incident emits two events

If you cannot pass a stable `event_id`, the duplicate-event-counting
risk is yours to accept — the controller will surface the issue
through suspicious-looking streak resets in the diagnostic chip.

---

## The result object

```python
result.classification     # Classification enum
result.tier_transition    # {from, to, reason, ...} | None
result.autodisabled       # True iff this event tripped the safeguard
result.deduped            # True iff event_id was a replay
result.rolling_total      # samples in the autodisable window
result.rolling_critical   # critical samples in the autodisable window
```

If `result.tier_transition is not None`, emit a real-time delta
event so operators see the transition in <1s. The V2 adapter rides
the existing `system_health_delta` WebSocket envelope — copy that
pattern for new domains so all transitions share one operator UI
state machine.

---

## The gate sequence

Shipping a behavioural change with this pattern is a five-stage
ratchet:

### 1. Ship in pure shadow mode

```python
# .env (production)
# (no rollout env vars set)
```

`controller.is_active_for(user_id, rollout_pct)` returns `False`
for everyone. New logic runs alongside production, classifies
every event, fills counters and the recent-events ring. No
production traffic is rerouted.

### 2. Observe ≥ 100 events per kind

Wait. Real traffic accumulates per-kind classification counters.
Do not stare at synthetic test data — you need real-world entropy
(network asymmetry, mobile sleep states, guardian-availability
variance) that synthetic tests cannot reproduce.

The V2 Parity Chip surfaces this in the operator Command Center:
match%, critical count, ΔFanout, worst-recent classification per
kind family. **Wait until total ≥ 100 per kind family** before
judging parity.

### 3. Parity confidence

Read the diagnostic. You want:

- `critical_count = 0` over the last incident cycle.
- `match_pct ≥ 80%` (drift threshold).
- No `auto_disabled` transitions in the operator review window.
- Stable `fanout_delta_avg` (no oscillation between +N and −N).

If any of these are violated, **fix the classifier or the new
logic before flipping the gate**. Do not raise the
`autodisable_threshold_pct` to silence the warning.

### 4. Auto-disable arms automatically

You don't have to "turn on" the safeguard. The moment any
`CRITICAL_REGRESSION` events accumulate beyond threshold, the
flag stamps automatically and `is_active_for` returns False for
new events regardless of the env-var rollout %.

`should_v2_actually_fire() returns False even at env-var 100%` is
the locked contract. Operator manual reset is available via
`POST /api/admin/monitoring/alert-v2/clear-autodisable?kind=...`
but **only after the underlying regression is understood**.

### 5. Flip rollout %

```bash
# .env (production)
ALERT_TRIGGER_V2_HELP_REQUEST_ROLLOUT_PCT=5    # 5% cohort
```

`controller.is_active_for(user_id, 5)` now returns True for ~5%
of users by sha256 hash. Ramp: 5 → 25 → 50 → 100. Stay at each
step for at least one full incident cycle. Watch the diagnostic
chip. The auto-disable stays armed throughout — it will yank the
rollout back to 0% if the rate breaches.

---

## `critical_count = 0` for ≥ 1 incident cycle

The most-asked question is "when can I let V2 *actually* dispatch?"

The answer is: when `critical_count = 0` for the kind family
over **at least one full incident cycle** in production.

An "incident cycle" is operationally defined as:

- ≥ 100 real-world events of this kind
- Across multiple guardian-availability states (online, offline,
  push-failed, recently-active)
- Spanning at least one weekday + one weekend (mobile activity
  patterns differ)
- With no `auto_disabled` transitions

Synthetic test traffic does not qualify. Heatmap-style soak tests
do not qualify. The cycle must contain real incidents with real
guardian responses.

Once that bar is met, the actual dispatch path can be wired
behind `is_active_for(user_id, rollout_pct)` — and even then,
flip in 5% → 25% → 50% → 100% steps with the auto-disable still
armed.

---

## Worked example: the V2 adapter

`app/services/alert_trigger_v2_shadow.py` is the canonical
production adopter of this playbook. It shows:

1. **Constructor wiring** — `_get_controller(kind)` lazy-caches
   one controller per kind family, with V2-specific tunables
   (matching the constants exported for the test suite).
2. **`classify_fn` implementation** —
   `_classify_via_diff` maps the V2-specific 7-label taxonomy
   (`missed_target_critical`, `unreachable_dropped`, etc.) to the
   generic 4-label `Classification` enum via
   `_v2_label_to_generic`.
3. **Endpoint glue** — `should_v2_actually_fire` delegates the
   gate decision to `controller.is_active_for`; `get_safety_state`,
   `clear_autodisable`, and the diagnostic summary all delegate
   to the controller.
4. **Tier transition emission** — when `record()` (or the
   equivalent legacy `_evaluate_tier_transition` path) returns a
   transition, `_emit_v2_parity_delta` rides the existing
   `system_health_delta` WebSocket envelope.

Read that file for the production shape. Read
`tests/test_alert_trigger_v2.py` for the test patterns you can
copy.

---

## Anti-patterns

**Lowering `autodisable_threshold_pct` to silence the warning.**
The threshold is the safety contract. If real-world traffic
breaches it, the new logic has a regression — fix the regression,
not the threshold.

**Reusing an `event_id` across logically distinct events.**
Streak counters silently undercount. Pick a stable, unique
identifier.

**Returning a plain string from `classify_fn`.** The controller
rejects this on purpose — the taxonomy is enforced at the
boundary so domain code cannot redefine "critical".

**Sharing a controller instance across kinds.** Each rollout
needs its own `kind` so the per-kind Redis namespace isolation
works. Two controllers with the same `kind` will fight over
state; two controllers with different `kind` values are
independent.

**Skipping the observation phase.** "Synthetic tests cover it"
is not a substitute for ≥ 100 real-world events. The pattern
exists *because* synthetic tests cannot reproduce production
entropy.

**Flipping the rollout % without watching the auto-disable.**
The whole point of the auto-disable is to be the brake. If you
raise rollout % and the safeguard fires, leave it disabled
and investigate. Do not bypass the safeguard manually.

---

## Three-layer protection model

This playbook is layer 1 (runtime safeguards). The other two
layers run pre-merge and catch the bugs that would otherwise
silently undermine the safeguards:

| Layer | What it catches | Where it lives |
|-------|-----------------|----------------|
| Runtime safeguards | Critical-regression rate + tier-state hysteresis + auto-disable + dedup | `app/services/shadow_rollout.py` |
| Contract enforcement | Missing required kwargs (`user_id` on `GuardianAlert(...)`) | `tests/test_guardian_alert_user_id_contract.py` |
| Structural audits | INSERT-in-broad-except / Tier A broadcast-before-flush | `tests/test_swallow_audit.py` + `tests/test_broadcast_before_persist.py` |

All three are enforced in CI. All three fail loud with actionable
remediation guidance. Combined, they prevent the failure modes
that motivated NISCH-AUDIT-001 (silent missing rows) and its
inverse (broadcast firing for a row that never persists).

If you are adding a new behavioural change, you only need to
think about layer 1 — the other two protect themselves.

---

## Reading order for new engineers

1. This playbook (you are here).
2. `app/services/shadow_rollout.py` — the controller. ~400 lines.
3. `tests/test_shadow_rollout.py` — usage patterns.
4. `app/services/alert_trigger_v2_shadow.py` — production adopter.
5. `app/api/monitoring.py::get_alert_v2_shadow_stats` — operator
   surface.
6. `frontend/src/components/command-center/V2ParityChip.jsx` —
   diagnostic UI pattern.

Do not read in any other order. Reading the V2 adapter before
the controller is the most common reason engineers come away
confused about what is "the pattern" vs "the V2 specifics".

---

## Appendix — Provider Debugging Reflex

When an external-signal provider chip shows `degraded` or
`100% failure rate` for sustained periods, the diagnostic
discipline below has caught more bugs than network-policy
theories ever have:

### Step 1 — Probe the provider's actual latency BEFORE anything else

```bash
for i in 1 2 3 4 5; do
  curl -sS -o /dev/null \
    -w "  attempt $i: code=%{http_code} time=%{time_total}s size=%{size_download}\n" \
    "https://<provider-url>"
done
```

You want to see:
1. Does the provider respond at all? (rules out egress block)
2. What is its actual response latency? (this is the bug 80% of
   the time)

### Step 2 — Compare against our HTTP_TIMEOUT_S

Every provider declares an `HTTP_TIMEOUT_S` in its module. Open
that file and check:

```
provider.HTTP_TIMEOUT_S    vs    observed p95 of curl runs above
```

If `HTTP_TIMEOUT_S < observed_p95`, every fetch races the timer
and loses. **Fix: split the timeout into hot-path vs prewarmer
budgets.** Hot path keeps its tight crash budget (typically
≤ 1.5 s under the registry's `PROVIDER_TIMEOUT_S` cap); the
pre-warmer can wait 5–10 s because it has no incident-time
budget to honour.

The pattern:

```python
async def _fetch_feed_uncached(timeout_s: float | None = None):
    effective_timeout = timeout_s if timeout_s is not None else HTTP_TIMEOUT_S
    async with httpx.AsyncClient(timeout=effective_timeout) as client:
        ...

# Hot path (caller in the alert pipeline):
result = await _fetch_feed_uncached()   # default 1.0 s

# Pre-warmer (caller in the background job):
result = await _fetch_feed_uncached(timeout_s=PREWARMER_TIMEOUT_S)
```

### Step 3 — Only AFTER 1 & 2 fail, suspect infra

Network policy, egress allowlists, regional routing, DNS — all
of these are real failure modes, but they are the *minority*
failure mode for provider regressions. The Sachet NDMA-NO-DATA
bug (Feb 2026) looked exactly like an egress block and turned
out to be a 1.0 s timeout against a 1.8 s response — fixed in
one line.

### Pre-emptive: the latency exporter

The `ProviderPrewarmer` base class records per-fetch wall-clock
latency in a rolling window. The operator chip surfaces
`budget_warning: true` when p95 exceeds 80% of the
`fetch_timeout_s` declared by the subclass — i.e., the chip
warns you BEFORE failures start. If you see a chip suddenly
amber, run Step 1 against that provider's URL and check the
declared `fetch_timeout_s` against the p95 the chip is showing.

## Compensating DLQs (audit-row recovery)

When a safety-critical event has already fanned out via SSE +
push + SMS but the persistence INSERT failed, the planned audit
row is pushed to a bounded Redis list (LPUSH + LTRIM). The
**DLQ Reconciler** (`app/services/dlq_reconciler.py`) drains
these every 60 s ± 10 s, retrying each payload up to
`MAX_ATTEMPTS = 3` before routing it to a sibling
`dlq:<key>:poison` list (capped at `POISON_MAX = 200`). All
four DLQs are bounded — neither the live queue nor the poison
list can grow Redis memory unboundedly during a sustained
outage.

| DLQ key                            | Source                                | Max | Poison Max |
|------------------------------------|---------------------------------------|-----|------------|
| `dlq:notification_history`         | `notification_service._store_notification` | 1000 | 200 |
| `dlq:failsafe_audit`               | `auto_escalation_engine._trigger_guardian_failsafe` | 500 | 200 |
| `dlq:voice_distress_audit`         | `voice_distress_service.report_voice_distress` | 500 | 200 |
| `dlq:checkin_audit`                | `checkin_service` (help_requested + safety_event) | 500 | 200 |

### Capsule chip

The Command Center header carries a `DLQCapsule` chip that polls
`/api/admin/monitoring/dlqs` every 30 s.
  * Green ("DLQ IDLE") — all DLQs below 10 % pressure
  * Amber ("DLQ PRESSURE") — any DLQ at ≥ 10 % of MAX
  * Red ("DLQ CRITICAL") — any DLQ at ≥ 50 % of MAX
  * Grey ("DLQ NO DATA") — Redis unavailable

Click the chip for a per-DLQ depth + poison-depth flyout.

### Operator reflex when a DLQ accumulates

  1. Click the capsule and confirm which DLQ is amber/red.
  2. `LLEN dlq:<key>` to sanity-check the chip; > 10 % of MAX is
     the amber threshold.
  3. Grep backend logs for the corresponding structured event
     name (`failsafe_audit_row_dlq`,
     `voice_distress_audit_row_dlq`,
     `notification_history_dlq`,
     `checkin_help_audit_row_dlq`,
     `checkin_safety_event_audit_row_dlq`) to confirm the
     underlying failure class.
  4. Watch for `dlq_drained` logs once the DB path heals — they
     prove the reconciler is making progress.
  5. If the **poison list** is non-empty, the reconciler has
     given up after 3 attempts. Operators drain
     `dlq:<key>:poison` out-of-band — the live DLQ stays clear
     so new failures keep flowing through the normal retry path.

