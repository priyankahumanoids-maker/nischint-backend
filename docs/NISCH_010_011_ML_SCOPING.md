# NISCH-010 / NISCH-011 — ML Layer Scoping

**Status:** scoping phase only. No code written. Locks the
design constraints from the 2026-02 session so the
implementation PR has a defended target before the first line
of code.

**Locked constraints (recorded in `ROADMAP.md`):**

  1. Both detectors are **`ProviderPrewarmer` subclasses.**
  2. **`dlq:ml_predictions`** is an **append-only prediction
     ledger**, not a retry queue. Bounded ring-buffer.

Everything below is design — choices are flagged with `[OPEN]`
when the implementation PR will need to pick one.

---

## NISCH-010 — Predictive risk surface (LSTM + Prophet)

### Surface contract

```python
class PredictiveRiskPrewarmer(ProviderPrewarmer):
    name = "predictive_risk"
    fetch_timeout_s = 0.2          # inference SLA — hot-path budget
    refresh_interval_s = 60        # one prediction per minute per zone
    history_window = 60            # rolling sample window for latency

    async def fetch(self) -> list[dict]:
        # Returns a list of modifiers, one per zone:
        #   {"zone": "mumbai", "predicted_risk_15min": 0.42,
        #    "model": "lstm-v1", "confidence": 0.71,
        #    "inputs_hash": "..."}
        ...
```

Same operator chip + asymmetric hysteresis + latency exporter
+ `budget_warning` amber/red as Sachet/TomTom/News. Free.

### Data inventory — `[OPEN]` confirm before training

Existing time-series sources in PostgreSQL:

| Table                | Field                                | Notes                            |
|----------------------|--------------------------------------|----------------------------------|
| `safety_incidents`   | `created_at`, `confidence`, `external_signals` JSONB | Sparse — incident-rate too low for an LSTM alone |
| `behavior_anomalies` | `score`, `created_at`, `user_id`     | Denser — per-user time series    |
| `geo_history`        | JSONB blob in `users` table          | Lat/lng/timestamp — rich         |
| `external_signals`   | Cached per provider in Redis         | Weather, traffic, NDMA, news     |

**Minimum window:** 14 days rolling for LSTM convergence, 30
days preferred. `behavior_anomalies` + `geo_history` are the
primary signal — `safety_incidents` is the label, too sparse
to be the input.

### Train offline vs online — `[OPEN]`

**Option A (recommended):** offline-trained model + online
inference.

  * Nightly batch job re-trains the LSTM on the last 30 days
    of data, persists weights to S3 (already wired for stream
    recording bucket — same pattern).
  * Prewarmer's `fetch()` loads weights once at process start,
    runs inference per cycle.
  * Pro: SLA target (≤ 200 ms) is achievable with cached
    weights. Training pressure is decoupled from inference
    pressure.
  * Con: Up to 24 h staleness on the model itself (data is
    realtime; weights are not).

**Option B:** online learning via sliding-window Prophet on a
short horizon.

  * Prophet is much lighter-weight than LSTM — could be
    re-fit per cycle.
  * Pro: zero training infra, near-zero staleness.
  * Con: Prophet is weaker at multi-variate inputs; we'd be
    fitting per-zone univariate series only.

**Recommendation: Option A with Prophet as a fallback model**
that's swapped in when the LSTM weights are missing / corrupt /
producing NaN. Hysteresis state machine already handles the
"primary down → fallback active → recover" choreography.

### SLA — locked at ≤ 200 ms

The prewarmer's `fetch_timeout_s` enforces this. If a cycle
breaches the budget, the existing `budget_warning` chip turns
amber at 80 % — operators see the regression before it starts
biting alert latency.

### Shadow rollout — `[OPEN]` mode at first deploy

The same `alert_trigger_v2_shadow` pattern: log what the
predictive layer **would have** said for 1-2 incident cycles
*before* any hot-path wiring. Modifier output flows into
`dlq:ml_predictions` (the ledger, see below) but does NOT
influence `fetch_all_signals()` until a separate
`PREDICTIVE_RISK_HOT_PATH_ENABLED` flag flips. Same news-
provider gate philosophy.

---

## NISCH-011 — Z-score behavioural anomaly detector

### Surface contract

```python
class BehavioralAnomalyPrewarmer(ProviderPrewarmer):
    name = "behavioral_anomaly"
    fetch_timeout_s = 0.1          # pure math — even tighter SLA
    refresh_interval_s = 30
    z_threshold = 2.5              # |z| ≥ 2.5 → evidence, not fire

    async def fetch(self) -> list[dict]:
        # Per-user signal:
        #   {"user_id": uuid, "feature": "stride_cadence",
        #    "z_score": 3.1, "rolling_mean": 1.2,
        #    "rolling_std": 0.3, "sample_n": 480}
        ...
```

Per-user behavioural drift, NOT incident classification.
Important framing: **this is evidence**, not a fire signal —
it modulates `confidence` in `fetch_all_signals()`, never
triggers an alert on its own.

### Rolling window — `[OPEN]`

**Option A:** Redis sorted set keyed by user, score=ts,
member=feature value. O(log N) writes + O(N) reads for the
window.

**Option B:** Postgres time-bucketed aggregates (TimescaleDB-
style, even without the extension — just a hand-rolled bucket
key on the row).

**Recommendation: Option A.** The detector reads the window on
every cycle; Postgres round-trips would dominate the 100 ms
budget. Redis sorted-set is the right shape and we already use
Redis heavily.

### Threshold tuning — locked

Start at `|z| ≥ 2.5`. Surface the value in the prewarmer
config so operators can tune via env var
`BEHAVIORAL_ANOMALY_Z_THRESHOLD`. Don't ship a hot-path effect
until the **distribution of `z_score` values has been observed
in shadow mode** for ≥ 1 week — otherwise we don't know what
2.5 means in practice for our user base.

### Integration — `[OPEN]`

**Option A:** New provider entry in `_PROVIDERS`. Same shape
as the weather / traffic / news modifiers.

**Option B:** Separate `BehavioralSignalProvider` registry
(parallel to `_PROVIDERS`) because the signal is per-user not
per-zone.

**Recommendation: Option A with a `scope: "user"` discriminator
on the modifier shape.** Avoids a parallel registry; aligns the
operator chip / shadow-rollout machinery; lets the External
Signal Layer compose user-scoped + zone-scoped modifiers in
one pass.

---

## `dlq:ml_predictions` — append-only ledger

**Locked design constraint from the session:** this is NOT a
retry queue. It's a forensic record of **every inference
attempt** — successes AND failures — so the post-mortem of
any incident can answer "what would the model have said at
T?"

### Shape

```python
LEDGER_KEY     = "dlq:ml_predictions"
LEDGER_MAX     = 10_000   # ~24h at 60s cycles × 7 detectors

def append(entry: dict) -> None:
    # entry MUST contain:
    #   {"ts":         "2026-05-12T...",
    #    "detector":   "predictive_risk" | "behavioral_anomaly",
    #    "inputs_hash": "...",
    #    "inputs":     {...},   # full inputs for replay
    #    "output":     {...} | None,  # None on inference failure
    #    "error":      "..."   | None,
    #    "latency_ms":  17.4,
    #    "shadow_mode": True | False}
    #    "would_have_dispatched": bool   # what the modifier WOULD do
```

LPUSH + LTRIM at `LEDGER_MAX = 10_000`. Same memory-safety
principle as the audit DLQs. **No reconciler** — the ledger is
read-only from the platform's perspective; operators query it
via a new endpoint.

### Endpoints — `[OPEN]` for implementation PR

```
GET  /api/admin/monitoring/ml-ledger?detector=&since=&limit=
GET  /api/admin/monitoring/ml-ledger/incident/{incident_id}
       — returns the ledger window ±5 min around the
         incident timestamp. The post-mortem view.
```

### Why this matters

A silent prediction drop during an incident is **unrecoverable**
from a post-mortem perspective. You cannot prove what the model
would have said because the inference path failed. The ledger
guarantees that even on inference failure, the **inputs** are
preserved — so the model can be re-run offline against the
exact state of the world at incident time. This is the
difference between "we think the model would have helped" and
"we know what the model said."

---

## Implementation order (when V2 ramp clears)

1. `dlq:ml_predictions` ledger + endpoints — **build this
   first**, before any detector. Both detectors will write to
   it from day one of shadow mode.
2. `BehavioralAnomalyPrewarmer` — cheaper, pure-math, smaller
   surface. Validates the ledger + prewarmer subclassing
   patterns.
3. `PredictiveRiskPrewarmer` — depends on offline training
   infrastructure (S3 weights, batch nightly job).
4. Shadow → flag-gated hot-path activation, one detector at a
   time. Same playbook as V2 ramp / News provider.

## Open questions (implementation PR will need to answer)

  * `[OPEN]` Offline training infra: re-use the existing
    nightly geo_digest cron, or stand up a separate
    `nightly_ml_training` supervisor?
  * `[OPEN]` Where do LSTM weights live in S3 — re-use the
    existing `STREAM_RECORDING_BUCKET` pattern or stand up
    `ML_MODEL_WEIGHTS_BUCKET`?
  * `[OPEN]` Z-score: per-feature rolling stats stored
    per-user, or per-feature only with user-id as a
    grouping key? (Affects Redis memory bound.)
  * `[OPEN]` Ledger query shape — JSONB-style filters or just
    a dumb LRANGE + client-side filter? At 10 k entries the
    dumb approach is fine for a v1.
