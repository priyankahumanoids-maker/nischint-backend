"""NISCH-009 — Feedback aggregator: turns guardian verdicts into AI
loop signals + auto-resolution decisions.

Threshold rule (locked by tests):
  * ≥2 `confirm_risk` AND zero `mark_safe`
        → bump `confidence` by +CONFIDENCE_DELTA_UP (cap 0.99)
  * ≥2 `mark_safe`    AND zero `confirm_risk`
        → drop `confidence` by CONFIDENCE_DELTA_DOWN (floor 0.0)
        → AND auto-transition to RESOLVED (state machine), with
          actor_type='community_feedback' for forensic clarity.
  * `report_anomaly` votes are *flags* — they never move confidence
    (it's a "needs human review" signal, not a binary classifier).

Why this rule and not "majority vote":
  * Asymmetric cost: a false MARK_SAFE on a real distress event is
    catastrophic. A false CONFIRM_RISK is recoverable (extra alert).
  * "AND zero of the other side" gates noisy crowds — if even one
    guardian disagreed, we hold and let the human review path run.
  * Threshold of 2 (not 3) because in practice a child's network is
    small (mom + dad). Requiring 3 would never trigger.

This service is invoked from the API after every accepted verdict.
It is **idempotent** — re-running it on the same feedback set will
NOT double-bump confidence (we re-derive the *target* confidence
relative to the original confidence stored in incident.extra, then
clamp).
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident_feedback import (
    IncidentFeedback, VERDICT_CONFIRM_RISK, VERDICT_MARK_SAFE,
    VERDICT_REPORT_ANOMALY,
)
from app.models.safety_incident import SafetyIncident
from app.services.incident_state_machine import (
    IncidentState, is_valid_transition, transition,
)

logger = logging.getLogger(__name__)


# Tunables — keep small enough that a single false vote can be
# absorbed without cascading state damage. These are read once at
# import time and locked by the unit tests.
CONFIDENCE_THRESHOLD_VOTES = 2
CONFIDENCE_DELTA_UP   = 0.10
CONFIDENCE_DELTA_DOWN = 0.15
CONFIDENCE_FLOOR      = 0.0
CONFIDENCE_CEIL       = 0.99


def _classify(counts: dict[str, int]) -> Optional[str]:
    """Return 'risk' | 'safe' | None based on the threshold rule.

    `counts` keys are verdict names; missing keys default to 0.
    """
    risk = counts.get(VERDICT_CONFIRM_RISK, 0)
    safe = counts.get(VERDICT_MARK_SAFE, 0)
    if risk >= CONFIDENCE_THRESHOLD_VOTES and safe == 0:
        return "risk"
    if safe >= CONFIDENCE_THRESHOLD_VOTES and risk == 0:
        return "safe"
    return None


async def get_feedback_counts(
    session: AsyncSession, incident_id: uuid.UUID,
) -> dict[str, int]:
    """Per-verdict counts for one incident. Always returns all three
    keys — callers don't need to handle missing keys."""
    rows = (await session.execute(
        select(IncidentFeedback.verdict, IncidentFeedback.id)
        .where(IncidentFeedback.incident_id == incident_id)
    )).all()
    out = {
        VERDICT_MARK_SAFE: 0,
        VERDICT_CONFIRM_RISK: 0,
        VERDICT_REPORT_ANOMALY: 0,
    }
    for verdict, _ in rows:
        if verdict in out:
            out[verdict] += 1
    return out


async def apply_feedback_decision(
    session: AsyncSession,
    incident: SafetyIncident,
    *,
    actor_id: Optional[uuid.UUID] = None,
) -> dict:
    """Re-evaluate feedback for `incident`, mutate confidence + state
    if the threshold rule fires.

    Returns a decision summary:
        {
            "counts": {...},
            "classification": "risk"|"safe"|None,
            "confidence_before": float,
            "confidence_after":  float,
            "auto_resolved":     bool,
        }

    Idempotency: stores the original confidence under
    `incident.extra['confidence_before_feedback']` on the first hit
    and re-derives subsequent adjustments from that anchor — repeated
    calls converge instead of drifting.
    """
    counts = await get_feedback_counts(session, incident.id)
    cls = _classify(counts)

    before = float(incident.confidence or 0.0)
    after  = before
    auto_resolved = False

    extra = dict(incident.extra or {})
    # Anchor: the confidence at the moment feedback first touched
    # this incident. Used as the reference point so a flip-flopping
    # crowd can't drift the score arbitrarily.
    anchor = extra.get("confidence_before_feedback")
    if anchor is None:
        anchor = before
        extra["confidence_before_feedback"] = anchor

    if cls == "risk":
        after = min(CONFIDENCE_CEIL, float(anchor) + CONFIDENCE_DELTA_UP)
    elif cls == "safe":
        after = max(CONFIDENCE_FLOOR, float(anchor) - CONFIDENCE_DELTA_DOWN)
    # cls is None → leave confidence at `before`. (We do NOT reset to
    # the anchor — once feedback has moved the needle, partial vote
    # withdrawal shouldn't snap it back; the next firing threshold
    # will recompute from the anchor anyway.)

    if after != before:
        incident.confidence = after
        logger.info(
            f"[FEEDBACK] incident={incident.id} confidence "
            f"{before:.2f} → {after:.2f} cls={cls} counts={counts}"
        )

    # Auto-resolve when classification is 'safe' AND state is in a
    # transition-eligible band. We use the same state machine as
    # any other resolver — no direct DB writes.
    if cls == "safe":
        current = IncidentState(incident.state)
        if is_valid_transition(current, IncidentState.RESOLVED):
            await transition(
                session, incident, IncidentState.RESOLVED,
                actor_id=actor_id,
                actor_type="community_feedback",
                note=f"Auto-resolved by community feedback "
                     f"(safe={counts[VERDICT_MARK_SAFE]}, "
                     f"risk={counts[VERDICT_CONFIRM_RISK]})",
            )
            auto_resolved = True
            # NISCH-009.1 — invalidate impact-badge caches for the
            # contributing guardians so they see fresh counts within
            # seconds. Best-effort; never blocks the resolve path.
            try:
                from app.services.guardian_impact_service import (
                    get_mark_safe_voters, invalidate_guardians,
                )
                voters = await get_mark_safe_voters(session, incident.id)
                await invalidate_guardians(voters)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[FEEDBACK] impact invalidate failed: {e}")

    incident.extra = extra
    await session.flush()

    return {
        "counts":            counts,
        "classification":    cls,
        "confidence_before": before,
        "confidence_after":  after,
        "auto_resolved":     auto_resolved,
    }


__all__ = [
    "CONFIDENCE_THRESHOLD_VOTES",
    "CONFIDENCE_DELTA_UP",
    "CONFIDENCE_DELTA_DOWN",
    "CONFIDENCE_FLOOR",
    "CONFIDENCE_CEIL",
    "_classify",
    "get_feedback_counts",
    "apply_feedback_decision",
]
