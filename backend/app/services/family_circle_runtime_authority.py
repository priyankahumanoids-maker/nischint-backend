"""Phase 5 Family Circle runtime authorization bridge.

This module connects the frozen Phase 1C policy engine to existing production
safety APIs without rewriting their engines.  Family Circle membership is
canonical when present; legacy relationship logic remains a compatibility
fallback only for users who are not yet in a Family Circle.

Phase 6 will replace the temporary ACTIVE entitlement used here with the
subscription/Lifeline authority.  Emergency alert visibility is deliberately
plan-based and remains available while ordinary sharing is paused.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.family_circle_permissions import (
    ACTION_VIEW_LOCATION,
    ACTION_VIEW_LOCATION_HISTORY,
    ACTION_VIEW_AI_PROFILE,
    ACTION_VIEW_ACTIVITY,
    ACTION_VIEW_WEARABLE,
    CONSENT_AI_BEHAVIORAL,
    CONSENT_BACKGROUND_LOCATION,
    CONSENT_LOCATION,
    CONSENT_MICROPHONE,
    CONSENT_WEARABLE,
    ENTITLEMENT_ACTIVE,
    PermissionContext,
    ConsentState,
    permission_decision,
)
from app.models.family_circle import CircleMembership, FamilyCircle


_PERSISTED_TO_PERMISSION_PURPOSE = {
    "location": CONSENT_LOCATION,
    "background_location": CONSENT_BACKGROUND_LOCATION,
    "behavioral_ai": CONSENT_AI_BEHAVIORAL,
    "microphone": CONSENT_MICROPHONE,
    "wearable": CONSENT_WEARABLE,
}

_VIEW_ACTIONS = frozenset({
    ACTION_VIEW_LOCATION,
    ACTION_VIEW_LOCATION_HISTORY,
    ACTION_VIEW_AI_PROFILE,
    ACTION_VIEW_ACTIVITY,
    ACTION_VIEW_WEARABLE,
})


@dataclass(frozen=True)
class RuntimeDecision:
    canonical: bool
    allowed: bool
    code: str


@dataclass(frozen=True)
class MembershipSnapshot:
    membership: CircleMembership
    circle: FamilyCircle


async def membership_snapshot(
    session: AsyncSession,
    user_id: str | uuid.UUID,
) -> MembershipSnapshot | None:
    try:
        uid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
    except (TypeError, ValueError, AttributeError):
        return None

    row = (
        await session.execute(
            select(CircleMembership, FamilyCircle)
            .join(FamilyCircle, FamilyCircle.id == CircleMembership.circle_id)
            .where(
                CircleMembership.user_id == uid,
                CircleMembership.status == "active",
                FamilyCircle.status == "active",
            )
        )
    ).first()
    if not row:
        return None
    membership, circle = row
    if not circle.plan or not membership.seat:
        return None
    return MembershipSnapshot(membership=membership, circle=circle)


async def _consent_state(session: AsyncSession, subject_user_id: uuid.UUID) -> ConsentState:
    """Load the latest Family Circle decision for every persisted purpose."""
    result = await session.execute(
        text(
            """
            SELECT DISTINCT ON (purpose) purpose, state
              FROM family_consent_events
             WHERE subject_user_id = :subject_user_id
             ORDER BY purpose, created_at DESC, id DESC
            """
        ),
        {"subject_user_id": str(subject_user_id)},
    )
    values: dict[str, bool] = {}
    for row in result.mappings().all():
        canonical = _PERSISTED_TO_PERMISSION_PURPOSE.get(str(row["purpose"] or ""))
        if canonical:
            values[canonical] = str(row["state"] or "").lower() == "granted"
    return ConsentState(values)


async def sharing_paused(
    session: AsyncSession,
    user_id: str | uuid.UUID,
    *,
    now: datetime | None = None,
) -> bool:
    point = now or datetime.now(timezone.utc)
    row = (
        await session.execute(
            text(
                """
                SELECT paused, pause_mode, paused_until
                  FROM family_sharing_states
                 WHERE user_id = :user_id
                """
            ),
            {"user_id": str(user_id)},
        )
    ).mappings().first()
    if not row or not bool(row["paused"]):
        return False
    if str(row["pause_mode"] or "") == "manual":
        return True
    paused_until = row["paused_until"]
    if paused_until is None:
        return True
    if getattr(paused_until, "tzinfo", None) is None:
        paused_until = paused_until.replace(tzinfo=timezone.utc)
    return paused_until.astimezone(timezone.utc) > point.astimezone(timezone.utc)


async def runtime_decision(
    session: AsyncSession,
    *,
    actor_user_id: str | uuid.UUID,
    action: str,
    target_user_id: str | uuid.UUID | None = None,
) -> RuntimeDecision:
    actor = await membership_snapshot(session, actor_user_id)
    if actor is None:
        return RuntimeDecision(False, False, "legacy_fallback")

    target = None
    if target_user_id is not None:
        target = await membership_snapshot(session, target_user_id)
        if target is None:
            return RuntimeDecision(True, False, "target_not_in_family_circle")
        if target.circle.id != actor.circle.id:
            return RuntimeDecision(True, False, "different_circle")

    actor_consent = await _consent_state(session, actor.membership.user_id)
    target_consent = (
        await _consent_state(session, target.membership.user_id)
        if target is not None
        else ConsentState()
    )

    ctx = PermissionContext(
        actor_user_id=str(actor.membership.user_id),
        actor_role=actor.membership.role,
        actor_seat=str(actor.membership.seat),
        plan=str(actor.circle.plan),
        # Phase 6 replaces this with paid/trial/grace/Lifeline state.
        entitlement=ENTITLEMENT_ACTIVE,
        same_circle=True,
        actor_consent=actor_consent,
        target_user_id=str(target.membership.user_id) if target is not None else None,
        target_role=target.membership.role if target is not None else None,
        target_seat=str(target.membership.seat) if target is not None else None,
        target_consent=target_consent,
    )
    decision = permission_decision(ctx, action)

    # A pause stops ordinary sharing to other members, but it does not revoke
    # consent/collection and never blocks SOS/emergency visibility.
    if (
        decision.allowed
        and target is not None
        and str(target.membership.user_id) != str(actor.membership.user_id)
        and action in _VIEW_ACTIONS
        and await sharing_paused(session, target.membership.user_id)
    ):
        return RuntimeDecision(True, False, "sharing_paused")

    return RuntimeDecision(True, decision.allowed, decision.code)


async def plan_visible_target_ids(
    session: AsyncSession,
    actor_user_id: str | uuid.UUID,
) -> tuple[bool, list[uuid.UUID]]:
    """Return canonical plan-visible targets, without consent filtering.

    This is the correct scope for alerts/SOS. Feature-specific readers must use
    ``filter_targets_for_action`` before returning location/AI/wearable data.
    """
    actor = await membership_snapshot(session, actor_user_id)
    if actor is None:
        return False, []

    rows = list(
        (
            await session.execute(
                select(CircleMembership).where(
                    CircleMembership.circle_id == actor.circle.id,
                    CircleMembership.status == "active",
                )
            )
        ).scalars().all()
    )
    out: list[uuid.UUID] = []
    if actor.circle.plan in {"trial", "individual"}:
        if actor.membership.seat != "guardian":
            return True, []
        out = [m.user_id for m in rows if m.seat == "protected" and m.user_id != actor.membership.user_id]
    elif actor.circle.plan == "family":
        out = [m.user_id for m in rows if m.user_id != actor.membership.user_id and m.seat == "member"]
    return True, out


async def filter_targets_for_action(
    session: AsyncSession,
    actor_user_id: str | uuid.UUID,
    candidate_ids: list[uuid.UUID],
    action: str,
) -> list[uuid.UUID]:
    actor = await membership_snapshot(session, actor_user_id)
    if actor is None:
        return list(candidate_ids)
    allowed: list[uuid.UUID] = []
    for target_id in candidate_ids:
        decision = await runtime_decision(
            session,
            actor_user_id=actor_user_id,
            target_user_id=target_id,
            action=action,
        )
        if decision.allowed:
            allowed.append(target_id)
    return allowed


async def alert_recipient_ids(
    session: AsyncSession,
    subject_user_id: str | uuid.UUID,
) -> tuple[bool, list[str]]:
    """Return Family Circle recipients for one emergency/safety alert."""
    subject = await membership_snapshot(session, subject_user_id)
    if subject is None:
        return False, []

    rows = list(
        (
            await session.execute(
                select(CircleMembership).where(
                    CircleMembership.circle_id == subject.circle.id,
                    CircleMembership.status == "active",
                )
            )
        ).scalars().all()
    )
    recipients: list[str] = []
    if subject.circle.plan in {"trial", "individual"}:
        if subject.membership.seat == "protected":
            recipients = [str(m.user_id) for m in rows if m.seat == "guardian" and m.user_id != subject.membership.user_id]
    elif subject.circle.plan == "family":
        recipients = [str(m.user_id) for m in rows if m.user_id != subject.membership.user_id and m.seat == "member"]
    return True, recipients


async def runtime_snapshot(session: AsyncSession, user_id: str | uuid.UUID) -> dict:
    actor = await membership_snapshot(session, user_id)
    if actor is None:
        return {"canonical": False}

    from app.core.family_circle_permissions import (
        ACTION_PRODUCE_LOCATION,
        ACTION_PRODUCE_ACTIVITY,
        ACTION_PRODUCE_AI_PROFILE,
        ACTION_PRODUCE_VOICE_DISTRESS,
        ACTION_PRODUCE_WEARABLE,
        ACTION_TRIGGER_SOS,
    )

    async def allowed(action: str) -> bool:
        return (await runtime_decision(session, actor_user_id=user_id, action=action)).allowed

    location_allowed = await allowed(ACTION_PRODUCE_LOCATION)
    actor_consent = await _consent_state(session, actor.membership.user_id)

    return {
        "canonical": True,
        "circle_id": str(actor.circle.id),
        "plan": actor.circle.plan,
        "role": actor.membership.role,
        "seat": actor.membership.seat,
        "sharing_paused": await sharing_paused(session, actor.membership.user_id),
        "can_trigger_sos": await allowed(ACTION_TRIGGER_SOS),
        "can_produce_location": location_allowed,
        # Background GPS is distinct consent from foreground/live location.
        # It is not ACTION_PRODUCE_ACTIVITY because a Minor may have parental
        # background-location consent while still being forbidden activity AI.
        "can_produce_background_location": (
            location_allowed and actor_consent.granted(CONSENT_BACKGROUND_LOCATION)
        ),
        "can_produce_activity": await allowed(ACTION_PRODUCE_ACTIVITY),
        "can_produce_ai": await allowed(ACTION_PRODUCE_AI_PROFILE),
        "can_produce_voice": await allowed(ACTION_PRODUCE_VOICE_DISTRESS),
        "can_produce_wearable": await allowed(ACTION_PRODUCE_WEARABLE),
    }
