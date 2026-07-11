"""Shadow rollout controller — production-grade behavioural-change
deployment pattern, extracted from `alert_trigger_v2_shadow.py` so
any future behavioural PR can adopt the same self-protecting shape
in <50 lines of glue.

THE PATTERN (locked from operator review)
─────────────────────────────────────────
1. Run new logic in shadow mode alongside production.
2. Diff each event into a typed outcome (`classify_fn`).
3. Bump per-classification counters; track rolling critical rate.
4. Auto-disable the rollout when critical rate breaches threshold.
5. Hysteresis-gate the tier-state machine so recoveries don't
   flap during early rollout.
6. Emit transition deltas on the system_health_delta stream.

INTERFACE CONTRACT
──────────────────
The classification taxonomy LIVES INSIDE this helper — domains do
NOT redefine what "critical" means. Each domain injects only a
`classify_fn` that maps its own diff data to the locked taxonomy:

    Classification.MATCH
    Classification.IMPROVEMENT
    Classification.REGRESSION
    Classification.CRITICAL_REGRESSION

Only CRITICAL_REGRESSION feeds the autodisable safeguard. Domains
can have richer domain-specific labels (V2's `missed_target_critical`
vs `unreachable_target_chosen`) but those collapse into the generic
taxonomy at the helper boundary, preventing per-domain drift.

`record()` is IDEMPOTENT on `event_id` — duplicate events (replay,
SSE reconnection, retry storms) do NOT corrupt streak counters or
counters. Idempotency keys live in Redis with a 1-hour TTL so the
typical retry window is covered.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Awaitable, Callable, Optional

from app.services import redis_service

logger = logging.getLogger(__name__)


# ── Locked taxonomy ────────────────────────────────────────────────
class Classification(str, Enum):
    """Generic, cross-domain diff outcomes. Locked vocabulary so the
    word "critical" means the same thing regardless of which domain
    rollout is running."""
    MATCH                = "match"
    IMPROVEMENT          = "improvement"
    REGRESSION           = "regression"
    CRITICAL_REGRESSION  = "critical_regression"


_CRITICAL = {Classification.CRITICAL_REGRESSION}
_IMPROVEMENT = {Classification.IMPROVEMENT}


# ── Tier state machine ─────────────────────────────────────────────
class Tier(str, Enum):
    AUTO_DISABLED = "auto_disabled"
    CRITICAL      = "critical"
    DRIFT         = "drift"
    IMPROVING     = "improving"
    IN_PARITY     = "in_parity"
    UNKNOWN       = "unknown"


# Lower priority = worse. Regressions snap immediately to a worse
# tier; recoveries are hysteresis-gated.
_TIER_PRIORITY: dict[Tier, int] = {
    Tier.AUTO_DISABLED: 0,
    Tier.CRITICAL:      1,
    Tier.DRIFT:         2,
    Tier.IMPROVING:     3,
    Tier.IN_PARITY:     4,
    Tier.UNKNOWN:       5,
}


# ── Result type ────────────────────────────────────────────────────
@dataclass(frozen=True)
class RecordResult:
    """What `record()` returns. Callers use `transition` (None when
    no transition fired) to drive WS emission."""
    classification: Classification
    tier_transition: Optional[dict] = None
    autodisabled:    bool = False
    deduped:         bool = False
    rolling_total:   int = 0
    rolling_critical: int = 0


# ── Controller ─────────────────────────────────────────────────────
class ShadowRolloutController:
    """One controller instance per rollout `kind` (e.g.
    `help_request`, `sos`, future `trust_weighted_routing`).

    All Redis state is namespaced by `kind` so independent rollouts
    can run in parallel without cross-contamination.
    """

    REDIS_NAMESPACE = "shadow_rollout"

    def __init__(
        self,
        kind: str,
        classify_fn: Callable[..., Classification | Awaitable[Classification]],
        *,
        autodisable_threshold_pct: float = 0.05,
        autodisable_min_samples:   int   = 20,
        autodisable_window_s:      int   = 600,
        hysteresis_recovery:       int   = 20,
        drift_recovery:            int   = 50,
        dedup_ttl_s:               int   = 3600,
        redis_namespace:           Optional[str] = None,
        kind_position:             str = "first",
    ):
        if not kind:
            raise ValueError("ShadowRolloutController: `kind` required")
        if not callable(classify_fn):
            raise ValueError("ShadowRolloutController: `classify_fn` required")
        if kind_position not in ("first", "last"):
            raise ValueError("kind_position must be 'first' or 'last'")
        self.kind = kind
        self._classify_fn = classify_fn
        self.autodisable_threshold_pct = autodisable_threshold_pct
        self.autodisable_min_samples   = autodisable_min_samples
        self.autodisable_window_s      = autodisable_window_s
        self.hysteresis_recovery       = hysteresis_recovery
        self.drift_recovery            = drift_recovery
        self.dedup_ttl_s               = dedup_ttl_s
        # Per-instance overrides so adopters (e.g. the V2 adapter) can
        # preserve their existing Redis namespace + key shape during a
        # delegation refactor without invalidating production state or
        # breaking pre-existing tests that assert on key substrings.
        self._namespace = redis_namespace or self.REDIS_NAMESPACE
        self._kind_position = kind_position

    # ── Public API ────────────────────────────────────────────────
    async def record(
        self,
        event_id: str,
        **diff_inputs,
    ) -> RecordResult:
        """Record a comparison event for this rollout. Idempotent on
        `event_id`: duplicate events are no-ops returning `deduped=True`
        without bumping any counter.

        `diff_inputs` is passed verbatim to `classify_fn`.
        """
        if not event_id:
            raise ValueError("record(): event_id is required for idempotency")

        # Idempotency check — early-return on replay.
        if self._claim_event_id(event_id):
            # First time seen.
            pass
        else:
            return RecordResult(
                classification=Classification.MATCH,
                deduped=True,
            )

        # Domain classification → generic taxonomy.
        raw = self._classify_fn(**diff_inputs)
        if hasattr(raw, "__await__"):
            classification = await raw
        else:
            classification = raw
        if not isinstance(classification, Classification):
            raise ValueError(
                f"classify_fn must return Classification enum; got {type(classification)}"
            )

        # Counters + rolling-window + autodisable + tier transition.
        self._bump_counter(classification.value)
        is_critical_event = classification in _CRITICAL
        self._record_window(is_critical_event)
        total, critical, rate = self._rolling_window_stats()
        autodisabled = False
        if (
            total >= self.autodisable_min_samples
            and rate >= self.autodisable_threshold_pct
            and not self._read_autodisable()
        ):
            self._set_autodisable(
                f"critical_rate={rate:.3f} over last "
                f"{self.autodisable_window_s}s ({critical}/{total} events)"
            )
            autodisabled = True

        transition = self._evaluate_tier_transition(classification)

        return RecordResult(
            classification=classification,
            tier_transition=transition,
            autodisabled=autodisabled,
            rolling_total=total,
            rolling_critical=critical,
        )

    def is_active_for(self, user_id: str, rollout_pct: int) -> bool:
        """Returns True when the rollout should *replace* production
        for this user. Auto-disable wins regardless of rollout_pct."""
        if self._read_autodisable():
            return False
        if rollout_pct <= 0:
            return False
        return self._user_hash_pct(user_id) < rollout_pct

    def get_safety_state(self) -> dict:
        """Operator-facing snapshot."""
        total, critical, rate = self._rolling_window_stats()
        flag = self._read_autodisable()
        return {
            "kind":                 self.kind,
            "rolling_window_s":     self.autodisable_window_s,
            "total_events":         total,
            "critical_events":      critical,
            "critical_rate":        round(rate, 4),
            "threshold":            self.autodisable_threshold_pct,
            "min_samples":          self.autodisable_min_samples,
            "auto_disabled":        bool(flag),
            "auto_disabled_at":     (flag or {}).get("disabled_at"),
            "auto_disable_reason":  (flag or {}).get("reason"),
        }

    def clear_autodisable(self) -> bool:
        """Operator-facing manual reset."""
        try:
            client = redis_service._get_client()
            if not client:
                return False
            return bool(client.delete(self._key("autodisable_state")))
        except Exception:
            return False

    # ── Redis layer ───────────────────────────────────────────────
    def _key(self, *parts: str) -> str:
        if self._kind_position == "last":
            return ":".join((
                redis_service.PREFIX, self._namespace, *parts, self.kind,
            ))
        return ":".join((
            redis_service.PREFIX, self._namespace, self.kind, *parts,
        ))

    def _claim_event_id(self, event_id: str) -> bool:
        """Atomic claim. Returns True iff this is the first time we've
        seen `event_id` within the dedup window."""
        try:
            client = redis_service._get_client()
            if not client:
                # No Redis → can't dedup safely; treat as first-seen so
                # the audit still records. Failure-mode is "double
                # count on replay", never "lost record".
                return True
            return bool(client.set(
                self._key("seen", event_id), "1",
                nx=True, ex=self.dedup_ttl_s,
            ))
        except Exception as e:
            logger.warning("[SHADOW_ROLLOUT] dedup claim failed: %r", e)
            return True

    def _bump_counter(self, classification: str) -> None:
        try:
            client = redis_service._get_client()
            if not client:
                return
            k = self._key("classification", classification)
            client.incr(k)
            client.expire(k, 7 * 24 * 3600)
        except Exception as e:
            logger.warning("[SHADOW_ROLLOUT] counter bump failed: %r", e)

    def _record_window(self, is_critical_event: bool) -> None:
        try:
            client = redis_service._get_client()
            if not client:
                return
            sec = int(datetime.now(timezone.utc).timestamp())
            ttl = self.autodisable_window_s + 60
            tk = self._key("window", "total", str(sec))
            client.incr(tk)
            client.expire(tk, ttl)
            if is_critical_event:
                ck = self._key("window", "crit", str(sec))
                client.incr(ck)
                client.expire(ck, ttl)
        except Exception as e:
            logger.warning("[SHADOW_ROLLOUT] window record failed: %r", e)

    def _rolling_window_stats(self) -> tuple[int, int, float]:
        try:
            client = redis_service._get_client()
            if not client:
                return 0, 0, 0.0
            now_s = int(datetime.now(timezone.utc).timestamp())
            secs = range(now_s - self.autodisable_window_s, now_s + 1)
            tks = [self._key("window", "total", str(s)) for s in secs]
            cks = [self._key("window", "crit", str(s)) for s in secs]
            total = sum(int(v or 0) for v in (client.mget(tks) or []))
            crit  = sum(int(v or 0) for v in (client.mget(cks) or []))
        except Exception as e:
            logger.warning("[SHADOW_ROLLOUT] window stats failed: %r", e)
            return 0, 0, 0.0
        rate = (crit / total) if total else 0.0
        return total, crit, rate

    def _read_autodisable(self) -> Optional[dict]:
        try:
            client = redis_service._get_client()
            if not client:
                return None
            raw = client.get(self._key("autodisable_state"))
            return json.loads(raw) if raw else None
        except Exception:
            return None

    def _set_autodisable(self, reason: str) -> None:
        try:
            client = redis_service._get_client()
            if not client:
                return
            client.set(self._key("autodisable_state"), json.dumps({
                "disabled_at": datetime.now(timezone.utc).isoformat(),
                "reason":      reason,
            }), ex=7 * 24 * 3600)
        except Exception as e:
            logger.warning("[SHADOW_ROLLOUT] autodisable stamp failed: %r", e)

    # ── Tier-state machine ────────────────────────────────────────
    def _read_tier_state(self) -> dict:
        try:
            client = redis_service._get_client()
            if not client:
                return {}
            raw = client.get(self._key("tier_state"))
            return json.loads(raw) if raw else {}
        except Exception:
            return {}

    def _write_tier_state(self, state: dict) -> None:
        try:
            client = redis_service._get_client()
            if not client:
                return
            client.set(self._key("tier_state"),
                       json.dumps(state, default=str),
                       ex=7 * 24 * 3600)
        except Exception as e:
            logger.warning("[SHADOW_ROLLOUT] tier state write failed: %r", e)

    def _ideal_tier(self, classification: Classification) -> Tier:
        if self._read_autodisable():
            return Tier.AUTO_DISABLED
        if classification in _CRITICAL:
            return Tier.CRITICAL
        if classification in _IMPROVEMENT:
            return Tier.IMPROVING
        return Tier.IN_PARITY

    def _required_recovery_streak(self, current: Tier) -> int:
        if current in (Tier.CRITICAL, Tier.AUTO_DISABLED):
            return self.hysteresis_recovery
        if current == Tier.DRIFT:
            return self.drift_recovery
        return 0

    def _evaluate_tier_transition(
        self, classification: Classification,
    ) -> Optional[dict]:
        state = self._read_tier_state()
        current = Tier(state.get("tier") or Tier.UNKNOWN.value)
        streak = int(state.get("clean_streak") or 0)
        ideal = self._ideal_tier(classification)

        # auto_disabled is sticky — only clear_autodisable() leaves it.
        if current == Tier.AUTO_DISABLED and not self._read_autodisable():
            new_state = {
                "tier": Tier.CRITICAL.value, "clean_streak": 0,
                "last_transition_at": datetime.now(timezone.utc).isoformat(),
            }
            self._write_tier_state(new_state)
            return {
                "from": Tier.AUTO_DISABLED.value,
                "to":   Tier.CRITICAL.value,
                "reason": "operator_cleared_autodisable",
            }
        if ideal == Tier.AUTO_DISABLED and current != Tier.AUTO_DISABLED:
            new_state = {
                "tier": Tier.AUTO_DISABLED.value, "clean_streak": 0,
                "last_transition_at": datetime.now(timezone.utc).isoformat(),
            }
            self._write_tier_state(new_state)
            return {
                "from": current.value, "to": Tier.AUTO_DISABLED.value,
                "reason": "autodisable_safeguard_armed",
            }

        # Regression — snap immediately.
        if _TIER_PRIORITY[ideal] < _TIER_PRIORITY[current]:
            new_state = {
                "tier": ideal.value, "clean_streak": 0,
                "last_transition_at": datetime.now(timezone.utc).isoformat(),
            }
            self._write_tier_state(new_state)
            return {"from": current.value, "to": ideal.value,
                    "reason": "regression"}

        # Recovery — gated by clean streak.
        if _TIER_PRIORITY[ideal] > _TIER_PRIORITY[current]:
            if classification in _CRITICAL:
                self._write_tier_state({
                    "tier": current.value, "clean_streak": 0,
                    "last_transition_at": state.get("last_transition_at"),
                })
                return None
            streak += 1
            required = self._required_recovery_streak(current)
            if streak >= required:
                self._write_tier_state({
                    "tier": ideal.value, "clean_streak": 0,
                    "last_transition_at": datetime.now(timezone.utc).isoformat(),
                })
                return {"from": current.value, "to": ideal.value,
                        "reason": "recovery_hysteresis_met",
                        "streak": streak, "required": required}
            self._write_tier_state({
                "tier": current.value, "clean_streak": streak,
                "last_transition_at": state.get("last_transition_at"),
            })
            return None

        # Same tier — streak bookkeeping.
        if classification in _CRITICAL:
            if streak != 0:
                self._write_tier_state({
                    "tier": current.value, "clean_streak": 0,
                    "last_transition_at": state.get("last_transition_at"),
                })
        else:
            self._write_tier_state({
                "tier": current.value, "clean_streak": streak + 1,
                "last_transition_at": state.get("last_transition_at"),
            })
        return None

    # ── User-hash rollout cohort ──────────────────────────────────
    @staticmethod
    def _user_hash_pct(user_id: str) -> int:
        import hashlib
        h = hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()
        return int(h[:8], 16) % 100


__all__ = [
    "Classification",
    "Tier",
    "RecordResult",
    "ShadowRolloutController",
]
