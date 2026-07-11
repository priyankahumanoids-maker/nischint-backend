"""ALERT_TRIGGER_V2 — severity-tier dispatch decision engine (shadow mode).

Status: SHADOW-ONLY. V2 computes what it *would* dispatch; it does NOT
actually fire alerts. The result is compared against V1's actual
dispatch in `alert_trigger_v2_shadow.py` for offline analysis.

Policy split (locked):

| Kind family              | Policy             | Routing                                     |
|--------------------------|--------------------|---------------------------------------------|
| help_request, help_requested | passive_help_request | Best-reachable guardian first; rest queued  |
|                          |                    | for 120 s escalation if no ack.             |
| sos, sos_triggered, panic| active_sos         | Full broadcast immediately (parity with V1).|
| anything else            | not_in_scope_v2    | V2 declines — V1 owns the kind.             |

"Best-reachable" is computed from the existing `push_tokens` table
(`last_success_at`, `consecutive_failures`) reusing the
`reachability_classifier` thresholds from `app/api/push.py`. No new
schema. No new HTTP. The DB hop is bounded (one SELECT) so the
shadow path stays cheap.

Pure decision contract:
  * `compute_v2_decision()` is async (one DB read for reachability).
  * It NEVER mutates the session, NEVER writes anywhere, NEVER raises.
  * It returns a `V2Decision` even on error paths (with `dispatched=False`
    and `reason='v2_error'`) so the shadow logger can attribute the
    failure correctly.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ── Tunables (locked by tests) ────────────────────────────────────────
HELP_REQUEST_KINDS: frozenset[str] = frozenset({
    "help_request", "help_requested", "help",
})
SOS_KINDS: frozenset[str] = frozenset({
    "sos", "sos_triggered", "panic", "emergency_triggered",
})
HELP_REQUEST_ESCALATION_DELAY_S: int = 120

# Reachability ranks — lower is better (sort ascending).
_REACH_RANK: dict[str, int] = {
    "healthy": 0,
    "unknown": 1,
    "risk":    2,
    "dead":    3,
}


# ── Result type ───────────────────────────────────────────────────────
@dataclass
class V2Decision:
    """What V2 would do given the same inputs as V1.

    `routing_plan` is an ordered list of guardian_ids: index 0 is the
    first to notify, subsequent indices are escalation steps spaced
    by `escalation_delay_s` seconds. For SOS the whole list fires at
    once (escalation_delay_s = 0).
    """
    policy:               str               # passive_help_request | active_sos | not_in_scope_v2
    dispatched:           bool              # would V2 actually fire?
    routing_plan:         list[str]         # ordered guardian_ids
    escalation_delay_s:   int               # 0 for full-broadcast SOS
    reason:               Optional[str]     # human-readable summary
    reachability:         dict[str, str] = field(default_factory=dict)  # gid -> status

    def to_dict(self) -> dict:
        return asdict(self)


def classify_kind(kind: str) -> str:
    """Map raw kind → V2 policy. Pure function."""
    k = (kind or "").strip().lower()
    if k in HELP_REQUEST_KINDS:
        return "passive_help_request"
    if k in SOS_KINDS:
        return "active_sos"
    return "not_in_scope_v2"


# ── Reachability lookup ───────────────────────────────────────────────
async def _fetch_guardian_reachability(
    session: AsyncSession, guardian_ids: list[str],
) -> dict[str, str]:
    """One SELECT over push_tokens, return {guardian_id: status}.

    Reuses the same _classify() thresholds as `app/api/push.py` so the
    V2 ranking and the operator reachability badge agree. Failure to
    classify a guardian → status 'unknown' (defensive default)."""
    if not guardian_ids:
        return {}
    try:
        from app.api.push import _classify as classify_token

        uids = [uuid.UUID(g) for g in guardian_ids]
        rows = (await session.execute(
            text("""
                SELECT user_id, last_success_at, last_failure_at,
                       consecutive_failures
                FROM push_tokens
                WHERE user_id = ANY(:uids)
            """),
            {"uids": uids},
        )).all()
    except Exception as e:  # noqa: BLE001
        logger.warning("[V2] reachability lookup failed: %r", e)
        return {gid: "unknown" for gid in guardian_ids}

    now = datetime.now(timezone.utc)
    # Track per-guardian best-of status: a user with multiple devices
    # routes to the *best* device's status (any healthy beats any dead).
    # Guardians with NO push_tokens row default to "unknown" at the end.
    seen: dict[str, str] = {}
    for r in rows:
        gid = str(r.user_id)
        token_status = classify_token(
            r.last_success_at, r.last_failure_at,
            int(r.consecutive_failures or 0), now,
        )
        prev = seen.get(gid)
        if prev is None:
            seen[gid] = token_status
        elif _REACH_RANK.get(token_status, 99) < _REACH_RANK.get(prev, 99):
            seen[gid] = token_status
    return {gid: seen.get(gid, "unknown") for gid in guardian_ids}


def _rank_guardians(
    guardian_ids: list[str], reachability: dict[str, str],
) -> list[str]:
    """Sort guardians by reachability rank, then by stable lex order
    so ties are deterministic and reproducible across runs."""
    return sorted(
        guardian_ids,
        key=lambda g: (_REACH_RANK.get(reachability.get(g, "unknown"), 99), g),
    )


# ── Public entry point ────────────────────────────────────────────────
async def compute_v2_decision(
    session: AsyncSession,
    *,
    kind: str,
    user_id: str,
    guardian_ids: list[str],
) -> V2Decision:
    """Compute the V2 dispatch plan. Side-effect-free. Never raises."""
    policy = classify_kind(kind)

    if policy == "not_in_scope_v2":
        return V2Decision(
            policy=policy, dispatched=False,
            routing_plan=[], escalation_delay_s=0,
            reason="kind_not_owned_by_v2",
        )

    if not guardian_ids:
        return V2Decision(
            policy=policy, dispatched=False,
            routing_plan=[], escalation_delay_s=0,
            reason="no_guardians_resolved",
        )

    try:
        reachability = await _fetch_guardian_reachability(
            session, guardian_ids,
        )
    except Exception as e:  # noqa: BLE001
        # The lookup itself already swallows DB errors; this is a final
        # last-resort guard.
        logger.warning("[V2] reachability outer guard fired: %r", e)
        reachability = {gid: "unknown" for gid in guardian_ids}

    if policy == "active_sos":
        # Full broadcast — order is still ranked so the most-reachable
        # guardian sits at index 0 for any downstream UI sorting, but
        # all are notified in a single fan-out (delay = 0).
        plan = _rank_guardians(guardian_ids, reachability)
        return V2Decision(
            policy=policy, dispatched=True,
            routing_plan=plan, escalation_delay_s=0,
            reason="sos_full_broadcast",
            reachability=reachability,
        )

    # passive_help_request
    plan = _rank_guardians(guardian_ids, reachability)
    return V2Decision(
        policy=policy, dispatched=True,
        routing_plan=plan,
        escalation_delay_s=HELP_REQUEST_ESCALATION_DELAY_S,
        reason="best_guardian_first_with_escalation",
        reachability=reachability,
    )


__all__ = [
    "HELP_REQUEST_KINDS",
    "SOS_KINDS",
    "HELP_REQUEST_ESCALATION_DELAY_S",
    "V2Decision",
    "classify_kind",
    "compute_v2_decision",
]
