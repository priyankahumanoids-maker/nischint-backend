"""Canonical Family Circle runtime authorization bridge.

Family Circle authority wins whenever a user has *ever* entered the canonical
model. Legacy relationship fallbacks are permitted only for users with no
canonical membership history at all. This prevents a removed/left member from
regaining access through old relationship rows.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.age_policy import is_minor
from app.core.family_consent_policy import CURRENT_FAMILY_NOTICE_VERSION
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
    PermissionContext,
    ConsentState,
    permission_decision,
)
from app.models.family_circle import CircleMembership, FamilyCircle
from app.models.user import User
from app.services.family_circle_age_transition import reconcile_age18_for_user
from app.services.family_circle_entitlement_service import resolve_entitlement
from app.services.family_circle_audit_service import append_family_audit, record_location_view


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


async def _uuid(value) -> uuid.UUID | None:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


async def canonical_membership_state(session: AsyncSession, user_id: str | uuid.UUID) -> str:
    """Return legacy|active|former|invalid for canonical membership history."""
    uid = await _uuid(user_id)
    if uid is None:
        return "invalid"
    rows = (
        await session.execute(
            select(CircleMembership, FamilyCircle)
            .join(FamilyCircle, FamilyCircle.id == CircleMembership.circle_id)
            .where(CircleMembership.user_id == uid)
            .order_by(CircleMembership.joined_at.desc())
        )
    ).all()
    if not rows:
        return "legacy"
    for membership, circle in rows:
        if membership.status == "active" and circle.status == "active":
            if circle.plan and membership.seat:
                return "active"
            return "invalid"
    return "former"


async def membership_snapshot(
    session: AsyncSession,
    user_id: str | uuid.UUID,
) -> MembershipSnapshot | None:
    uid = await _uuid(user_id)
    if uid is None:
        return None

    # Automatic birthday reconciliation is idempotent and occurs before role
    # dependent permission checks.
    await reconcile_age18_for_user(session, uid)

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


async def _consent_state(session: AsyncSession, subject_user_id: uuid.UUID, *, now: datetime | None = None) -> ConsentState:
    """Derive current canonical consent, enforcing notice and ownership.

    Adults use only their own current-notice decisions. A person who has just
    turned 18 may continue to rely on parental location/background consent only
    until the birthday-anchored bridge deadline. Minors may use verified
    parental location/background records only and never AI/voice/wearable.
    """
    point = now or datetime.now(timezone.utc)
    subject = await session.get(User, subject_user_id)
    if subject is None or subject.date_of_birth is None:
        return ConsentState()
    minor = is_minor(subject.date_of_birth, on_date=point.date())

    bridge = (
        await session.execute(
            text(
                """
                SELECT consent_due_at, consent_completed_at, bridge_expired_at
                  FROM family_age18_transitions
                 WHERE user_id=:uid
                """
            ),
            {"uid": str(subject_user_id)},
        )
    ).mappings().first()
    bridge_active = False
    if not minor and bridge and bridge["consent_completed_at"] is None and bridge["bridge_expired_at"] is None:
        due = bridge["consent_due_at"]
        if due is not None and getattr(due, "tzinfo", None) is None:
            due = due.replace(tzinfo=timezone.utc)
        bridge_active = bool(due is not None and point < due)

    rows = (
        await session.execute(
            text(
                """
                SELECT purpose, state, actor_user_id, parental_basis, notice_version, created_at, id
                  FROM family_consent_events
                 WHERE subject_user_id=:subject_user_id
                   AND notice_version=:notice_version
                 ORDER BY purpose, created_at DESC, id DESC
                """
            ),
            {"subject_user_id": str(subject_user_id), "notice_version": CURRENT_FAMILY_NOTICE_VERSION},
        )
    ).mappings().all()

    decided: set[str] = set()
    values: dict[str, bool] = {}
    for row in rows:
        persisted = str(row["purpose"] or "")
        canonical = _PERSISTED_TO_PERMISSION_PURPOSE.get(persisted)
        if not canonical or canonical in decided:
            continue
        actor_is_self = str(row["actor_user_id"]) == str(subject_user_id)
        parental = bool(str(row["parental_basis"] or "").strip()) and not actor_is_self

        valid = False
        if minor:
            valid = parental and persisted in {"location", "background_location"}
        elif actor_is_self:
            valid = True
        elif bridge_active:
            valid = parental and persisted in {"location", "background_location"}
        if not valid:
            continue

        decided.add(canonical)
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
    if paused_until.astimezone(timezone.utc) > point.astimezone(timezone.utc):
        return True

    # Timed pause has expired. Reconcile it exactly once when a canonical
    # runtime/status request next touches the member. The caller owns commit.
    resumed = await session.execute(
        text(
            """
            UPDATE family_sharing_states
               SET paused=FALSE, pause_mode=NULL, paused_until=NULL, updated_at=:at
             WHERE user_id=:uid AND paused=TRUE AND pause_mode IN ('1h','8h')
               AND paused_until=:until
            """
        ),
        {"uid": str(user_id), "at": point, "until": paused_until},
    )
    if getattr(resumed, "rowcount", 1) == 0:
        # Another request extended/replaced the pause after our read. Do not
        # publish a resume event or allow collection from this stale decision.
        return True
    circle_row = (
        await session.execute(
            text(
                """
                SELECT circle_id FROM circle_memberships
                 WHERE user_id=:uid AND status='active' LIMIT 1
                """
            ),
            {"uid": str(user_id)},
        )
    ).mappings().first()
    if circle_row:
        inserted = await append_family_audit(
            session,
            circle_id=circle_row["circle_id"],
            actor_user_id=None,
            subject_user_id=user_id,
            event_type="sharing_resumed",
            details={"automatic": True, "paused_until": paused_until.isoformat()},
            event_key=f"auto-resume:{user_id}:{paused_until.isoformat()}",
        )
        if inserted:
            from app.services.family_circle_notification_outbox import enqueue_family_notifications
            subject = await session.get(User, await _uuid(user_id))
            _, recipients = await alert_recipient_ids(session, user_id)
            await enqueue_family_notifications(
                session, circle_id=circle_row["circle_id"], recipient_user_ids=recipients,
                event_type="family_sharing_resumed", title="NISCHINT sharing update",
                body=f'{subject.full_name if subject and subject.full_name else "A family member"} resumed location sharing.',
                payload={"user_id": str(user_id)},
                event_key_prefix=f"auto-resume:{user_id}:{paused_until.isoformat()}",
            )
    return False


async def runtime_decision(
    session: AsyncSession,
    *,
    actor_user_id: str | uuid.UUID,
    action: str,
    target_user_id: str | uuid.UUID | None = None,
    record_disclosure: bool = False,
) -> RuntimeDecision:
    actor = await membership_snapshot(session, actor_user_id)
    if actor is None:
        state = await canonical_membership_state(session, actor_user_id)
        if state == "legacy":
            return RuntimeDecision(False, False, "legacy_fallback")
        return RuntimeDecision(True, False, "former_family_circle_member" if state == "former" else "canonical_authority_unavailable")

    target = None
    if target_user_id is not None:
        target = await membership_snapshot(session, target_user_id)
        if target is None:
            target_state = await canonical_membership_state(session, target_user_id)
            code = "former_family_circle_member" if target_state == "former" else "target_not_in_family_circle"
            return RuntimeDecision(True, False, code)
        if target.circle.id != actor.circle.id:
            return RuntimeDecision(True, False, "different_circle")

    actor_consent = await _consent_state(session, actor.membership.user_id)
    target_consent = await _consent_state(session, target.membership.user_id) if target is not None else ConsentState()
    # Phase 6 replaces this former temporary ACTIVE entitlement with the canonical resolver.
    entitlement = await resolve_entitlement(session, actor.circle)
    ctx = PermissionContext(
        actor_user_id=str(actor.membership.user_id),
        actor_role=actor.membership.role,
        actor_seat=str(actor.membership.seat),
        plan=str(actor.circle.plan),
        entitlement=entitlement.permission_entitlement,
        same_circle=True,
        actor_consent=actor_consent,
        target_user_id=str(target.membership.user_id) if target is not None else None,
        target_role=target.membership.role if target is not None else None,
        target_seat=str(target.membership.seat) if target is not None else None,
        target_consent=target_consent,
    )
    decision = permission_decision(ctx, action)

    if (
        decision.allowed
        and target is not None
        and str(target.membership.user_id) != str(actor.membership.user_id)
        and action in _VIEW_ACTIONS
        and await sharing_paused(session, target.membership.user_id)
    ):
        return RuntimeDecision(True, False, "sharing_paused")

    if (
        record_disclosure
        and decision.allowed
        and target is not None
        and str(target.membership.user_id) != str(actor.membership.user_id)
        and action in {ACTION_VIEW_LOCATION, ACTION_VIEW_LOCATION_HISTORY}
    ):
        await record_location_view(
            session,
            circle_id=actor.circle.id,
            viewer_user_id=actor.membership.user_id,
            subject_user_id=target.membership.user_id,
            view_kind="history" if action == ACTION_VIEW_LOCATION_HISTORY else "live",
        )

    return RuntimeDecision(True, decision.allowed, decision.code)


async def plan_visible_target_ids(
    session: AsyncSession,
    actor_user_id: str | uuid.UUID,
) -> tuple[bool, list[uuid.UUID]]:
    actor = await membership_snapshot(session, actor_user_id)
    if actor is None:
        state = await canonical_membership_state(session, actor_user_id)
        return (state != "legacy"), []

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
    if actor.circle.plan in {"trial", "individual"}:
        if actor.membership.seat != "guardian":
            return True, []
        return True, [m.user_id for m in rows if m.seat == "protected" and m.user_id != actor.membership.user_id]
    if actor.circle.plan == "family":
        return True, [m.user_id for m in rows if m.user_id != actor.membership.user_id and m.seat == "member"]
    return True, []


async def filter_targets_for_action(
    session: AsyncSession,
    actor_user_id: str | uuid.UUID,
    candidate_ids: list[uuid.UUID],
    action: str,
    *,
    record_disclosures: bool = False,
) -> list[uuid.UUID]:
    actor = await membership_snapshot(session, actor_user_id)
    if actor is None:
        state = await canonical_membership_state(session, actor_user_id)
        return list(candidate_ids) if state == "legacy" else []
    allowed: list[uuid.UUID] = []
    for target_id in candidate_ids:
        decision = await runtime_decision(
            session,
            actor_user_id=actor_user_id,
            target_user_id=target_id,
            action=action,
            record_disclosure=record_disclosures,
        )
        if decision.allowed:
            allowed.append(target_id)
    return allowed


async def alert_recipient_ids(
    session: AsyncSession,
    subject_user_id: str | uuid.UUID,
) -> tuple[bool, list[str]]:
    subject = await membership_snapshot(session, subject_user_id)
    if subject is None:
        state = await canonical_membership_state(session, subject_user_id)
        return (state != "legacy"), []

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
    if subject.circle.plan in {"trial", "individual"} and subject.membership.seat == "protected":
        return True, [str(m.user_id) for m in rows if m.seat == "guardian" and m.user_id != subject.membership.user_id]
    if subject.circle.plan == "family":
        return True, [str(m.user_id) for m in rows if m.user_id != subject.membership.user_id and m.seat == "member"]
    return True, []


async def location_recipient_ids(
    session: AsyncSession,
    subject_user_id: str | uuid.UUID,
) -> tuple[bool, list[str]]:
    """Resolve current canonical recipients for an ordinary location disclosure.

    The result is recalculated on each publish; no stale journey recipient cache
    may override pause, leave, removal, consent or entitlement changes.
    """
    subject = await membership_snapshot(session, subject_user_id)
    if subject is None:
        state = await canonical_membership_state(session, subject_user_id)
        return (state != "legacy"), []
    members = list((await session.execute(
        select(CircleMembership).where(
            CircleMembership.circle_id == subject.circle.id,
            CircleMembership.status == "active",
            CircleMembership.user_id != subject.membership.user_id,
        )
    )).scalars().all())
    recipients: list[str] = []
    for member in members:
        decision = await runtime_decision(
            session,
            actor_user_id=member.user_id,
            target_user_id=subject.membership.user_id,
            action=ACTION_VIEW_LOCATION,
            record_disclosure=False,
        )
        if decision.allowed:
            recipients.append(str(member.user_id))
    return True, recipients


async def runtime_snapshot(session: AsyncSession, user_id: str | uuid.UUID) -> dict:
    actor = await membership_snapshot(session, user_id)
    if actor is None:
        state = await canonical_membership_state(session, user_id)
        if state == "legacy":
            return {"canonical": False}
        return {
            "canonical": True,
            "authority_state": state,
            "can_trigger_sos": True,
            "can_produce_location": False,
            "can_produce_background_location": False,
            "can_produce_activity": False,
            "can_produce_ai": False,
            "can_produce_voice": False,
            "can_produce_wearable": False,
            "sharing_paused": True,
            "lifeline": True,
            "entitlement": "lifeline",
            "entitlement_state": "lifeline",
            "entitlement_reason": "canonical_membership_inactive",
            "payment_required": False,
        }

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
    entitlement = await resolve_entitlement(session, actor.circle)

    return {
        "canonical": True,
        "authority_state": "active",
        "circle_id": str(actor.circle.id),
        "plan": actor.circle.plan,
        "role": actor.membership.role,
        "seat": actor.membership.seat,
        "entitlement_state": entitlement.state,
        "entitlement": entitlement.permission_entitlement,
        "lifeline": entitlement.lifeline,
        "entitlement_reason": entitlement.reason,
        "access_until": entitlement.access_until,
        "grace_until": entitlement.grace_until,
        "payment_required": entitlement.payment_required,
        "sharing_paused": await sharing_paused(session, actor.membership.user_id),
        "can_trigger_sos": await allowed(ACTION_TRIGGER_SOS),
        "can_produce_location": location_allowed,
        # Background-location consent is its own purpose. It is not ACTION_PRODUCE_ACTIVITY.
        "can_produce_background_location": location_allowed and actor_consent.granted(CONSENT_BACKGROUND_LOCATION),
        "can_produce_activity": await allowed(ACTION_PRODUCE_ACTIVITY),
        "can_produce_ai": await allowed(ACTION_PRODUCE_AI_PROFILE),
        "can_produce_voice": await allowed(ACTION_PRODUCE_VOICE_DISTRESS),
        "can_produce_wearable": await allowed(ACTION_PRODUCE_WEARABLE),
    }


__all__ = [
    "RuntimeDecision", "MembershipSnapshot", "canonical_membership_state",
    "membership_snapshot", "runtime_decision", "sharing_paused",
    "plan_visible_target_ids", "filter_targets_for_action", "alert_recipient_ids",
    "location_recipient_ids", "runtime_snapshot",
]
