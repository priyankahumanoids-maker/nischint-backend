"""ALERT_TRIGGER_V2 — V2-specific adapter on top of ShadowRolloutController.

The reusable rollout pattern (rolling window, autodisable, tier
state machine, hysteresis, per-kind isolation, dedup) lives in
`app.services.shadow_rollout.ShadowRolloutController`. This module
is the **V2-specific adapter** for the
ALERT_TRIGGER_V2_HELP_REQUEST + ALERT_TRIGGER_V2_SOS rollouts.

The adapter owns:
  1. The V2-specific diff classification (the 7-label taxonomy
     mapping to V2 incidents) and its mapper to the generic
     4-label `Classification` enum exposed by the controller.
  2. The V1↔V2 comparison logic (`diff_decisions`, `classify_diff`).
  3. The shadow orchestrator (`run_shadow_compare`) that V1 calls
     fire-and-forget from `alert_trigger.trigger_alert`.
  4. The legacy 3-bucket counter system (`_bump_counter`) retained
     for the operator chip's `legacy_counters` field.
  5. WebSocket emission of tier transitions
     (`_emit_v2_parity_delta` → `system_health_delta`).

Everything else — the autodisable safeguard, the hysteresis state
machine, the rolling-window math, the dedup-by-event_id idempotency
— delegates to the controller. The adapter passes
`redis_namespace="alert_v2_shadow"` and `kind_position="last"` to
preserve V2's existing Redis key shape so this refactor is
state-continuous in production AND bit-for-bit identical for the
42 V2 unit tests.

Hot-path contract (unchanged):
  * Fire-and-forget `asyncio.create_task` wrapper in V1's hot path
    means V1's TTFA is unaffected.
  * Every Redis op is best-effort — log + swallow, never raise.
  * `should_v2_actually_fire` honours the controller's autodisable
    safeguard BEFORE consulting the env-var rollout %.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import redis_service
from app.services.alert_trigger_v2 import V2Decision, compute_v2_decision
from app.services.shadow_rollout import (
    Classification, ShadowRolloutController, Tier,
)

logger = logging.getLogger(__name__)


# ── Tunables ─────────────────────────────────────────────────────────
SHADOW_LOG_NAMESPACE = "alert_v2_shadow"
SHADOW_LOG_LIST_KEY  = "events"
COUNTERS_KEY         = "counters"
CLASSIFICATIONS_KEY  = "classifications"   # per-classification counters
CRITICAL_KEY         = "critical_regressions"
SHADOW_LOG_MAX_LEN   = 1000        # ring buffer cap
SHADOW_LOG_TTL_S     = 24 * 3600   # 24 h on the list itself

# Per-kind rollout %, env-driven. Defaults to 0 = pure shadow mode.
_ROLLOUT_ENV_HELP = "ALERT_TRIGGER_V2_HELP_REQUEST_ROLLOUT_PCT"
_ROLLOUT_ENV_SOS  = "ALERT_TRIGGER_V2_SOS_ROLLOUT_PCT"

# Auto-disable safeguard. If the rolling critical-regression rate over
# the last AUTODISABLE_WINDOW_S seconds breaches AUTODISABLE_THRESHOLD,
# `should_v2_actually_fire()` clamps to False regardless of the env-var
# rollout %. Operators must investigate + manually re-enable.
AUTODISABLE_WINDOW_S       = 600    # rolling 10-min window
AUTODISABLE_MIN_SAMPLES    = 20     # need at least N events to judge
AUTODISABLE_THRESHOLD      = 0.05   # 5% critical regressions = halt
AUTODISABLE_REDIS_KEY      = "autodisable_state"

# Tier-state hysteresis. Regressions are immediate; recoveries require
# N consecutive clean (non-critical) events to prevent flapping during
# early rollout. Operator review feedback locked these numbers.
TIER_STATE_REDIS_KEY       = "tier_state"
HYSTERESIS_CRITICAL_RECOVERY = 20   # critical → anything better
HYSTERESIS_DRIFT_RECOVERY    = 50   # drift → anything better
TIER_PRIORITY = {                   # lower index = worse (snap-immediate on regression)
    "auto_disabled": 0,
    "critical":      1,
    "drift":         2,
    "improving":     3,
    "in_parity":     4,
    "unknown":       5,
}


# ── Controller factory ─────────────────────────────────────────────
# One controller per `kind`, cached at module level. The controller
# preserves V2's existing Redis key shape via `kind_position='last'`
# + `redis_namespace='alert_v2_shadow'` so this refactor is
# state-continuous (production keys unchanged) AND bit-for-bit
# identical for the 42 V2 unit tests that assert on key substrings.
_controllers: dict[str, ShadowRolloutController] = {}


def _classify_via_diff(**kwargs) -> Classification:
    """Bridge classify_fn used when callers go through the
    controller's `record()` path. Maps the V2-specific classification
    label to the controller's generic `Classification` enum."""
    label = kwargs.get("classification") or "match"
    return _v2_label_to_generic(label)


def _v2_label_to_generic(label: str) -> Classification:
    """Generic-taxonomy mapper for the 7 V2-specific labels.

    Locked contract: ONLY these mappings exist. The 4-label
    taxonomy lives inside `ShadowRolloutController`; this is the
    V2 adapter's contract for collapsing its domain-specific
    labels into the shared vocabulary."""
    if label in _CRITICAL_CLASSIFICATIONS:
        return Classification.CRITICAL_REGRESSION
    if label in _IMPROVEMENT_CLASSIFICATIONS:
        return Classification.IMPROVEMENT
    if label in ("fanout_diff", "decision_diff"):
        return Classification.REGRESSION
    return Classification.MATCH


def _get_controller(kind: str) -> ShadowRolloutController:
    """Lazy per-kind controller. The controller owns the rolling
    window, autodisable, tier state machine, and hysteresis math —
    this module just feeds it events and reads its state."""
    if kind not in _controllers:
        _controllers[kind] = ShadowRolloutController(
            kind=kind,
            classify_fn=_classify_via_diff,
            autodisable_threshold_pct=AUTODISABLE_THRESHOLD,
            autodisable_min_samples=AUTODISABLE_MIN_SAMPLES,
            autodisable_window_s=AUTODISABLE_WINDOW_S,
            hysteresis_recovery=HYSTERESIS_CRITICAL_RECOVERY,
            drift_recovery=HYSTERESIS_DRIFT_RECOVERY,
            redis_namespace=SHADOW_LOG_NAMESPACE,
            kind_position="last",
        )
    return _controllers[kind]


def _reset_controllers_for_test() -> None:
    """Clear the per-kind cache. Used only by tests that want a
    fresh state machine across runs."""
    _controllers.clear()


# ── Diff classification taxonomy (locked) ─────────────────────────
# critical → V2 would silently lose a real alert; rollout MUST stop.
# regression → measurable degradation (worse routing, slower escalation).
# improvement → measurable upgrade (healthier target, smaller fan-out).
# match → no observable difference.
_CRITICAL_CLASSIFICATIONS = frozenset({
    "missed_target_critical",        # SOS: V2 dropped a guardian V1 included
    "v2_would_not_dispatch",         # V1 fired, V2 wouldn't
    "unreachable_target_chosen",     # V2's first target is `dead`/`risk`
})
_REGRESSION_CLASSIFICATIONS = frozenset({
    "v1_only_extra_fanout",          # V1 included guardians V2 did not (HELP)
    # NOTE: for HELP this is *expected* (V2 narrows to best guardian),
    # so it's only flagged here if it's not the design intent — see
    # `classify_diff` below.
})
_IMPROVEMENT_CLASSIFICATIONS = frozenset({
    "ranking_improvement",           # same set, V2 ordered healthier first
    "fanout_reduction_help",         # HELP: V2 narrowed to best-of guardians
    "unreachable_dropped",           # V2 left out dead/risk, kept healthy
})


# ── Rollout gate ────────────────────────────────────────────────────
def _read_rollout_pct(env_name: str) -> int:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return 0
    try:
        v = int(raw)
    except ValueError:
        return 0
    return max(0, min(100, v))


def _user_hash_pct(user_id: str) -> int:
    """Stable hash → 0..99 cohort. Same user always lands in the same
    bucket so the rollout is deterministic across processes."""
    h = hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()
    return int(h[:8], 16) % 100


def should_v2_actually_fire(kind: str, user_id: str) -> bool:
    """Returns True when V2 should *replace* V1 for this event.

    Delegates the gate decision to the controller's `is_active_for`,
    which already encodes the locked priority:
      1. Out-of-scope kind → False (we check this here at the boundary).
      2. Auto-disabled by safeguard → False (controller).
      3. Env-var rollout = 0 → False (controller).
      4. User-id hash cohort below env-var % → True (controller).
    """
    from app.services.alert_trigger_v2 import classify_kind
    policy = classify_kind(kind)
    if policy == "passive_help_request":
        rollout = _read_rollout_pct(_ROLLOUT_ENV_HELP)
    elif policy == "active_sos":
        rollout = _read_rollout_pct(_ROLLOUT_ENV_SOS)
    else:
        return False
    return _get_controller(kind).is_active_for(user_id, rollout)


# ── Diff computation ────────────────────────────────────────────────
def diff_decisions(
    *,
    v1_dispatched: bool,
    v1_guardian_ids_notified: list[str],
    v2: V2Decision,
) -> dict:
    """Compute the comparison envelope. Pure function."""
    v1_set = set(v1_guardian_ids_notified or [])
    v2_set = set(v2.routing_plan or [])
    decision_match = (v1_dispatched == v2.dispatched)
    fanout_diff = sorted(v1_set.symmetric_difference(v2_set))
    return {
        "decision_match":  decision_match,
        "v1_dispatched":   v1_dispatched,
        "v2_dispatched":   v2.dispatched,
        "v1_count":        len(v1_set),
        "v2_count":        len(v2_set),
        "v1_only":         sorted(v1_set - v2_set),
        "v2_only":         sorted(v2_set - v1_set),
        "fanout_diff":     fanout_diff,
        "v2_first_target": v2.routing_plan[0] if v2.routing_plan else None,
    }


def classify_outcome(diff: dict) -> str:
    """LEGACY — coarse 3-state bucketing. Kept for backwards compat.
    Prefer `classify_diff()` for diagnostic-grade output."""
    if not diff["decision_match"]:
        return "decision_diff"
    if diff["fanout_diff"]:
        return "fanout_diff"
    return "match"


def classify_diff(diff: dict, v2: V2Decision) -> str:
    """Diagnostic classification — not all diffs are bad.

    Per the locked taxonomy, returns ONE of (in priority order so the
    most-actionable label always wins):

      * `v2_would_not_dispatch`        — CRITICAL: V1 fired, V2 wouldn't.
      * `missed_target_critical`       — CRITICAL (SOS only): V2 dropped
                                         a guardian V1 included.
      * `unreachable_target_chosen`    — CRITICAL (HELP only): V2's
                                         first target is `dead` or `risk`
                                         AND a healthier guardian was
                                         present in the resolved set.
      * `unreachable_dropped`          — IMPROVEMENT: V2 dropped only
                                         dead/risk targets V1 included.
      * `fanout_reduction_help`        — IMPROVEMENT (HELP only): V2
                                         narrowed to a smaller subset
                                         (best-guardian-first design).
      * `ranking_improvement`          — IMPROVEMENT: same set, V2 put
                                         a healthier guardian first.
      * `match`                        — no observable difference.
    """
    # 1. Decision-level mismatches (critical regressions).
    if diff["v1_dispatched"] and not diff["v2_dispatched"]:
        return "v2_would_not_dispatch"
    if (not diff["v1_dispatched"]) and diff["v2_dispatched"]:
        # V1 didn't fire (e.g. dedup) — V2 would. Not a regression
        # against V1 since V1 *chose* not to fire; treat as match-ish.
        return "match"

    v1_only = set(diff.get("v1_only", []))
    v2_only = set(diff.get("v2_only", []))
    reachability = (v2.reachability or {}) if v2 else {}

    # 2. SOS missed-target — V2 dropped someone V1 included.
    #    SOS contract = full broadcast, so any drop is critical.
    if v2.policy == "active_sos" and v1_only:
        return "missed_target_critical"

    # 3. HELP unreachable-target-chosen — V2 chose a degraded primary
    #    while a healthier guardian was available. This is the
    #    failure mode operators must catch BEFORE flipping rollout.
    if v2.policy == "passive_help_request" and diff.get("v2_first_target"):
        first = diff["v2_first_target"]
        first_status = reachability.get(first, "unknown")
        # "Bad" = first target is dead/risk AND someone in the resolved
        # set is healthy/unknown. If everyone is degraded it's not a
        # ranking failure — it's just a degraded fleet.
        from app.services.alert_trigger_v2 import _REACH_RANK
        first_rank = _REACH_RANK.get(first_status, 99)
        any_better = any(
            _REACH_RANK.get(s, 99) < first_rank
            for gid, s in reachability.items()
            if gid != first
        )
        if first_status in ("dead", "risk") and any_better:
            return "unreachable_target_chosen"

    # 4. Improvements — V2 dropped dead/risk targets while keeping the
    #    healthier ones (V2 only narrowed for HELP_REQUEST design).
    if v1_only and not v2_only:
        # All dropped targets are dead/risk?
        if v1_only and all(
            reachability.get(g, "unknown") in ("dead", "risk")
            for g in v1_only
        ):
            return "unreachable_dropped"
        if v2.policy == "passive_help_request":
            return "fanout_reduction_help"

    # 5. Same set, possibly different ordering — check via fanout_diff.
    if not diff.get("fanout_diff"):
        # If V2's first target has a *strictly better* reachability
        # rank than the average of V1's set, call it a ranking win.
        first = diff.get("v2_first_target")
        if first and reachability:
            from app.services.alert_trigger_v2 import _REACH_RANK
            first_rank = _REACH_RANK.get(
                reachability.get(first, "unknown"), 99
            )
            if any(
                _REACH_RANK.get(s, 99) > first_rank
                for gid, s in reachability.items() if gid != first
            ):
                return "ranking_improvement"
        return "match"

    # 6. Anything else is an unclassified fan-out difference.
    return "fanout_diff"


def is_critical(classification: str) -> bool:
    return classification in _CRITICAL_CLASSIFICATIONS


def is_improvement(classification: str) -> bool:
    return classification in _IMPROVEMENT_CLASSIFICATIONS


def _bump_classification(kind: str, classification: str) -> None:
    """Per-classification counter, used by the operator chip + the
    rollback safeguard's rolling-window critical-rate calculator."""
    try:
        client = redis_service._get_client()
        if not client:
            return
        full_key = (
            f"{redis_service.PREFIX}:{SHADOW_LOG_NAMESPACE}:"
            f"{CLASSIFICATIONS_KEY}:{kind}:{classification}"
        )
        client.incr(full_key)
        client.expire(full_key, 7 * 24 * 3600)
    except Exception as e:  # noqa: BLE001
        logger.warning("[V2_SHADOW] classification bump failed: %r", e)


def _record_event_in_window(kind: str, is_critical_event: bool) -> None:
    """Delegate: per-second rolling-window bucket — owned by the
    controller. See `ShadowRolloutController._record_window`."""
    _get_controller(kind)._record_window(is_critical_event)


def _rolling_window_stats(kind: str) -> tuple[int, int, float]:
    """Delegate: rolling-window aggregation — owned by the
    controller. See `ShadowRolloutController._rolling_window_stats`."""
    return _get_controller(kind)._rolling_window_stats()


def _set_autodisable(kind: str, reason: str) -> None:
    """Delegate: autodisable stamp — owned by the controller."""
    _get_controller(kind)._set_autodisable(reason)


def _read_autodisable(kind: str) -> Optional[dict]:
    """Delegate: autodisable read — owned by the controller."""
    return _get_controller(kind)._read_autodisable()


def clear_autodisable(kind: str) -> bool:
    """Operator-facing reset — delegates to controller."""
    return _get_controller(kind).clear_autodisable()


def get_safety_state(kind: str) -> dict:
    """Delegate to controller. Identical shape."""
    return _get_controller(kind).get_safety_state()


# ── Tier-state machine (hysteresis-gated) ──────────────────────────
def _read_tier_state(kind: str) -> dict:
    """Delegate: tier state read — owned by the controller."""
    return _get_controller(kind)._read_tier_state()


def _write_tier_state(kind: str, state: dict) -> None:
    """Delegate: tier state write — owned by the controller."""
    _get_controller(kind)._write_tier_state(state)


def _compute_ideal_tier(kind: str, classification: str) -> str:
    """Delegate to controller's ideal-tier computation. The V2-specific
    classification label is mapped to the generic enum before the
    controller's logic runs; controller returns a `Tier` enum whose
    `.value` is the legacy string ('in_parity', 'critical', etc.)."""
    return _get_controller(kind)._ideal_tier(
        _v2_label_to_generic(classification),
    ).value


def _required_recovery_streak(current_tier: str) -> int:
    """Pure function — kept locally so that test fixtures can call
    it without spinning a controller. Numbers match the controller's
    defaults exactly."""
    if current_tier in ("critical", "auto_disabled"):
        return HYSTERESIS_CRITICAL_RECOVERY
    if current_tier == "drift":
        return HYSTERESIS_DRIFT_RECOVERY
    return 0


def _evaluate_tier_transition(kind: str, classification: str) -> Optional[dict]:
    """Delegate to controller's tier evaluator. The V2-specific
    classification label is collapsed to the generic enum at the
    boundary; the controller's hysteresis state machine handles
    regression-snap + recovery-gated transitions identically."""
    generic = _v2_label_to_generic(classification)
    return _get_controller(kind)._evaluate_tier_transition(generic)


def _emit_v2_parity_delta(kind: str, transition: dict,
                          diagnostic_for_kind: Optional[dict] = None) -> None:
    """Embed v2_parity in the existing system_health_delta envelope —
    single WS stream, single reconnect path, single operator UI state
    machine (per operator-review feedback)."""
    try:
        from app.services.event_broadcaster import broadcaster
    except Exception:
        return
    diag = diagnostic_for_kind or {}
    payload = {
        "type":              "system_health_delta",
        "ts":                int(datetime.now(timezone.utc).timestamp()),
        "iso":               datetime.now(timezone.utc).isoformat(),
        "source":            "alert_v2",
        "severity":          "warning" if transition["to"] in ("critical", "auto_disabled") else "healthy",
        "previous_severity": "warning" if transition["from"] in ("critical", "auto_disabled") else "healthy",
        "v2_parity": {
            "kind":              kind,
            "tier":              transition["to"],
            "previous_tier":     transition["from"],
            "reason":            transition.get("reason"),
            "critical_count":    diag.get("critical_count", 0),
            "improvement_count": diag.get("improvement_count", 0),
            "match_pct":         diag.get("match_pct"),
            "total":             diag.get("total", 0),
            "fanout_delta_avg":  diag.get("fanout_delta_avg"),
            "auto_disabled":     bool((diag.get("safety") or {}).get("auto_disabled")),
        },
    }

    async def _send():
        try:
            await broadcaster.broadcast_to_operators(
                "system_health_delta", payload,
            )
        except Exception:
            logger.exception("v2_parity delta broadcast failed")

    # Mirror to the replay-tail history (best-effort, never blocks
    # the live broadcast). Operator reload gap is closed by the SSE
    # replay endpoint reading this same Redis list.
    try:
        from app.services.system_health_history import record_transition
        record_transition("v2_parity", payload)
    except Exception:
        logger.debug("v2_parity history write skipped")

    try:
        import asyncio as _asyncio
        loop = _asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_send())
        else:
            _asyncio.run(_send())
    except RuntimeError:
        try:
            import asyncio as _asyncio
            _asyncio.new_event_loop().run_until_complete(_send())
        except Exception:
            logger.debug("v2_parity delta emit could not schedule send")


# ── Diff persistence (best-effort) ─────────────────────────────────
def _bump_counter(kind: str, outcome: str) -> None:
    try:
        client = redis_service._get_client()
        if not client:
            return
        full_key = f"{redis_service.PREFIX}:{SHADOW_LOG_NAMESPACE}:{COUNTERS_KEY}:{kind}:{outcome}"
        client.incr(full_key)
        # 7-day TTL on counters so dormant events naturally roll off.
        client.expire(full_key, 7 * 24 * 3600)
    except Exception as e:  # noqa: BLE001
        logger.warning("[V2_SHADOW] counter bump failed: %r", e)


def _push_event(event: dict) -> None:
    try:
        client = redis_service._get_client()
        if not client:
            return
        full_key = f"{redis_service.PREFIX}:{SHADOW_LOG_NAMESPACE}:{SHADOW_LOG_LIST_KEY}"
        client.lpush(full_key, json.dumps(event, default=str))
        client.ltrim(full_key, 0, SHADOW_LOG_MAX_LEN - 1)
        client.expire(full_key, SHADOW_LOG_TTL_S)
    except Exception as e:  # noqa: BLE001
        logger.warning("[V2_SHADOW] event push failed: %r", e)


# ── Public hook (wrapped fire-and-forget by callers) ────────────────
async def run_shadow_compare(
    session: AsyncSession,
    *,
    kind: str,
    user_id: str,
    guardian_ids_resolved: list[str],
    v1_dispatched: bool,
    v1_guardian_ids_notified: list[str],
    alert_id: Optional[str] = None,
) -> Optional[dict]:
    """Compute V2 decision + diff vs V1 + persist log. Returns the
    diff envelope (for tests). Returns None on hook-disable / failure.

    SAFE: never raises. Caller is expected to wrap in
    `asyncio.create_task` for fire-and-forget semantics."""
    try:
        from app.services.alert_trigger_v2 import classify_kind
        policy = classify_kind(kind)
        if policy == "not_in_scope_v2":
            return None

        v2 = await compute_v2_decision(
            session,
            kind=kind, user_id=user_id,
            guardian_ids=guardian_ids_resolved,
        )
        diff = diff_decisions(
            v1_dispatched=v1_dispatched,
            v1_guardian_ids_notified=v1_guardian_ids_notified,
            v2=v2,
        )
        outcome = classify_outcome(diff)                    # legacy 3-bucket
        classification = classify_diff(diff, v2)             # diagnostic
        critical = is_critical(classification)

        event = {
            "ts":              datetime.now(timezone.utc).isoformat(),
            "kind":            kind,
            "user_id":         str(user_id),
            "alert_id":        alert_id,
            "policy":          v2.policy,
            "outcome":         outcome,
            "classification":  classification,
            "critical":        critical,
            "diff":            diff,
            "v2_decision":     asdict(v2),
        }
        _bump_counter(kind, outcome)
        _bump_classification(kind, classification)
        _record_event_in_window(kind, critical)
        _push_event(event)

        # Tier-state machine — emits a `system_health_delta` envelope
        # with embedded `v2_parity` ONLY on transition. Regressions
        # snap immediately; recoveries are hysteresis-gated to prevent
        # flapping during early rollout.
        try:
            transition = _evaluate_tier_transition(kind, classification)
            if transition:
                # Cheap per-kind diagnostic from the just-bumped counters.
                k_diag = (get_diagnostic_summary() or {}).get(kind, {})
                _emit_v2_parity_delta(kind, transition, k_diag)
                logger.info(
                    "[V2_SHADOW] tier transition kind=%s %s→%s reason=%s",
                    kind, transition["from"], transition["to"],
                    transition.get("reason"),
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("[V2_SHADOW] tier evaluator failed: %r", e)

        # Auto-disable check — runs after recording so this event
        # contributes to the rate that gates the next one.
        try:
            total, crit, rate = _rolling_window_stats(kind)
            if (
                total >= AUTODISABLE_MIN_SAMPLES
                and rate >= AUTODISABLE_THRESHOLD
                and not _read_autodisable(kind)
            ):
                _set_autodisable(
                    kind,
                    f"critical_rate={rate:.3f} over last "
                    f"{AUTODISABLE_WINDOW_S}s ({crit}/{total} events)",
                )
                logger.error(
                    "[V2_SHADOW] AUTODISABLE FIRED kind=%s "
                    "rate=%.3f crit=%d total=%d",
                    kind, rate, crit, total,
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("[V2_SHADOW] autodisable check failed: %r", e)

        logger.info(
            "[V2_SHADOW] kind=%s user=%s class=%s critical=%s "
            "v1=%d v2=%d match=%s policy=%s",
            kind, user_id, classification, critical,
            diff["v1_count"], diff["v2_count"],
            diff["decision_match"], v2.policy,
        )
        return diff
    except Exception as e:  # noqa: BLE001
        logger.warning("[V2_SHADOW] run failed: %r", e)
        return None


# ── Read helpers (used by monitoring API + tests) ───────────────────
def get_recent_events(limit: int = 50) -> list[dict]:
    try:
        client = redis_service._get_client()
        if not client:
            return []
        full_key = f"{redis_service.PREFIX}:{SHADOW_LOG_NAMESPACE}:{SHADOW_LOG_LIST_KEY}"
        raw = client.lrange(full_key, 0, max(0, limit - 1))
    except Exception as e:  # noqa: BLE001
        logger.warning("[V2_SHADOW] read failed: %r", e)
        return []
    out: list[dict] = []
    for s in raw or []:
        try:
            out.append(json.loads(s))
        except Exception:
            continue
    return out


def get_counter_snapshot() -> dict:
    """Return {kind: {outcome: count}} aggregated from Redis."""
    snap: dict[str, dict[str, int]] = {}
    try:
        client = redis_service._get_client()
        if not client:
            return {}
        pattern = f"{redis_service.PREFIX}:{SHADOW_LOG_NAMESPACE}:{COUNTERS_KEY}:*"
        for k in client.scan_iter(match=pattern, count=200):
            # key shape: PREFIX:alert_v2_shadow:counters:{kind}:{outcome}
            parts = k.split(":")
            if len(parts) < 5:
                continue
            kind_str = parts[-2]
            outcome = parts[-1]
            try:
                val = int(client.get(k) or 0)
            except Exception:
                val = 0
            snap.setdefault(kind_str, {})[outcome] = val
    except Exception as e:  # noqa: BLE001
        logger.warning("[V2_SHADOW] counter snapshot failed: %r", e)
        return snap
    return snap


def get_classification_snapshot() -> dict:
    """Return {kind: {classification: count}} for the diagnostic chip."""
    snap: dict[str, dict[str, int]] = {}
    try:
        client = redis_service._get_client()
        if not client:
            return {}
        pattern = (
            f"{redis_service.PREFIX}:{SHADOW_LOG_NAMESPACE}:"
            f"{CLASSIFICATIONS_KEY}:*"
        )
        for k in client.scan_iter(match=pattern, count=200):
            parts = k.split(":")
            if len(parts) < 5:
                continue
            kind_str = parts[-2]
            cls = parts[-1]
            try:
                val = int(client.get(k) or 0)
            except Exception:
                val = 0
            snap.setdefault(kind_str, {})[cls] = val
    except Exception as e:  # noqa: BLE001
        logger.warning("[V2_SHADOW] classification snapshot failed: %r", e)
        return snap
    return snap


def get_diagnostic_summary() -> dict:
    """One-call digest used by the operator V2 Parity Chip.

    For each kind family in scope, returns:
      * total events, match %, critical-event count
      * fan-out delta (sum(v2_count - v1_count) / total) — a rough
        proxy for whether V2 narrows or expands the fan-out vs V1
      * worst recent classification + worst-recent timestamp
      * the safety state (autodisable + critical rate)
    """
    classifications = get_classification_snapshot()
    out: dict[str, dict] = {}
    recent = get_recent_events(limit=200)
    for kind, by_class in classifications.items():
        total = sum(by_class.values())
        critical = sum(
            v for c, v in by_class.items() if is_critical(c)
        )
        improvements = sum(
            v for c, v in by_class.items() if is_improvement(c)
        )
        matches = by_class.get("match", 0)
        match_pct = (matches / total * 100.0) if total else 0.0
        # Fanout delta — average over the latest events for this kind.
        deltas = []
        worst_class = None
        worst_at = None
        for e in recent:
            if e.get("kind") != kind:
                continue
            d = e.get("diff") or {}
            deltas.append(int(d.get("v2_count", 0)) - int(d.get("v1_count", 0)))
            cls = e.get("classification") or ""
            if is_critical(cls):
                worst_class = cls
                worst_at = e.get("ts")
        avg_delta = round(sum(deltas) / len(deltas), 2) if deltas else 0.0
        out[kind] = {
            "total":              total,
            "match_count":        matches,
            "match_pct":          round(match_pct, 1),
            "critical_count":     critical,
            "improvement_count":  improvements,
            "by_classification":  by_class,
            "fanout_delta_avg":   avg_delta,
            "worst_recent":       worst_class,
            "worst_recent_at":    worst_at,
            "safety":             get_safety_state(kind),
        }
    return out


def get_rollout_state() -> dict:
    """Surface the current rollout config so operators / dashboards can
    see at a glance whether V2 is actually firing for any cohort."""
    return {
        "help_request_pct": _read_rollout_pct(_ROLLOUT_ENV_HELP),
        "sos_pct":          _read_rollout_pct(_ROLLOUT_ENV_SOS),
        "mode":             "shadow",  # see should_v2_actually_fire docstring
    }


__all__ = [
    "SHADOW_LOG_NAMESPACE", "SHADOW_LOG_MAX_LEN", "SHADOW_LOG_TTL_S",
    "AUTODISABLE_WINDOW_S", "AUTODISABLE_THRESHOLD",
    "AUTODISABLE_MIN_SAMPLES",
    "HYSTERESIS_CRITICAL_RECOVERY", "HYSTERESIS_DRIFT_RECOVERY",
    "TIER_PRIORITY",
    "diff_decisions",
    "classify_outcome",
    "classify_diff",
    "is_critical",
    "is_improvement",
    "run_shadow_compare",
    "should_v2_actually_fire",
    "get_recent_events",
    "get_counter_snapshot",
    "get_classification_snapshot",
    "get_diagnostic_summary",
    "get_safety_state",
    "get_rollout_state",
    "clear_autodisable",
    "_evaluate_tier_transition",
    "_read_tier_state",
]
