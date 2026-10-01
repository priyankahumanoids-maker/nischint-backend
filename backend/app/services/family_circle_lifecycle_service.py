"""Family Circle privacy/lifecycle operations for Phase 6.

State mutations are transaction-owned by the API caller. Push delivery helpers
are intentionally separate so notifications happen only after a successful
commit and cannot make privacy/lifecycle state roll back.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.family_circle_permissions import ACTION_LEAVE_CIRCLE, ACTION_PAUSE_OWN_SHARING
from app.models.family_circle import CircleMembership
from app.models.user import User
from app.services.family_circle_age_transition import age18_status
from app.services.family_circle_audit_service import append_family_audit

PAUSE_MODES = {"1h": timedelta(hours=1), "8h": timedelta(hours=8), "manual": None}


async def deliver_pause_notification(session: AsyncSession, *, outbox_ids: list[str]) -> dict:
    from app.services.family_circle_notification_outbox import deliver_outbox_notifications
    return await deliver_outbox_notifications(session, outbox_ids=outbox_ids)


async def deliver_circle_message(session: AsyncSession, *, outbox_ids: list[str]) -> dict:
    from app.services.family_circle_notification_outbox import deliver_outbox_notifications
    return await deliver_outbox_notifications(session, outbox_ids=outbox_ids)


async def _remaining_member_ids(session: AsyncSession, circle_id, *, exclude_user_id=None) -> list[str]:
    rows = list((await session.execute(
        select(CircleMembership).where(
            CircleMembership.circle_id == circle_id,
            CircleMembership.status == "active",
        )
    )).scalars().all())
    return [str(m.user_id) for m in rows if exclude_user_id is None or str(m.user_id) != str(exclude_user_id)]


async def pause_own_sharing(session: AsyncSession, *, user: User, mode: str, now: datetime | None = None) -> dict:
    from app.services.family_circle_runtime_authority import alert_recipient_ids, membership_snapshot, runtime_decision
    point = now or datetime.now(timezone.utc)
    canonical = str(mode or "").strip().lower()
    if canonical not in PAUSE_MODES:
        raise ValueError("Pause mode must be 1h, 8h or manual.")
    decision = await runtime_decision(session, actor_user_id=user.id, action=ACTION_PAUSE_OWN_SHARING)
    if not decision.canonical or not decision.allowed:
        raise PermissionError(decision.code)
    snapshot = await membership_snapshot(session, user.id)
    if snapshot is None:
        raise PermissionError("family_circle_required")
    until = None if PAUSE_MODES[canonical] is None else point + PAUSE_MODES[canonical]
    await session.execute(
        text(
            """
            INSERT INTO family_sharing_states (user_id, paused, pause_mode, paused_until, updated_at)
            VALUES (:uid, TRUE, :mode, :until, :at)
            ON CONFLICT (user_id) DO UPDATE SET
                paused=TRUE, pause_mode=EXCLUDED.pause_mode,
                paused_until=EXCLUDED.paused_until, updated_at=EXCLUDED.updated_at
            """
        ),
        {"uid": str(user.id), "mode": canonical, "until": until, "at": point},
    )
    _, recipients = await alert_recipient_ids(session, user.id)
    await append_family_audit(
        session,
        circle_id=snapshot.circle.id,
        actor_user_id=user.id,
        subject_user_id=user.id,
        event_type="sharing_paused",
        details={"mode": canonical, "paused_until": until.isoformat() if until else None},
    )
    from app.services.family_circle_notification_outbox import enqueue_family_notifications
    outbox_ids = await enqueue_family_notifications(
        session,
        circle_id=snapshot.circle.id,
        recipient_user_ids=recipients,
        event_type="family_sharing_paused",
        title="NISCHINT sharing update",
        body=f'{user.full_name or "A family member"} paused location sharing.',
        payload={"user_id": str(user.id)},
        event_key_prefix=f"sharing-paused:{user.id}:{point.isoformat()}",
    )
    return {"paused": True, "mode": canonical, "paused_until": until, "notification_outbox_ids": outbox_ids}


async def resume_own_sharing(session: AsyncSession, *, user: User, now: datetime | None = None) -> dict:
    from app.services.family_circle_runtime_authority import membership_snapshot, runtime_decision
    point = now or datetime.now(timezone.utc)
    decision = await runtime_decision(session, actor_user_id=user.id, action=ACTION_PAUSE_OWN_SHARING)
    if not decision.canonical or not decision.allowed:
        raise PermissionError(decision.code)
    age = await age18_status(session, user.id)
    if age.get("transitioned") and age.get("requires_own_consent") and age.get("bridge_expired_at"):
        raise PermissionError("age18_self_consent_required")
    snapshot = await membership_snapshot(session, user.id)
    if snapshot is None:
        raise PermissionError("family_circle_required")
    await session.execute(
        text(
            """
            INSERT INTO family_sharing_states (user_id, paused, pause_mode, paused_until, updated_at)
            VALUES (:uid, FALSE, NULL, NULL, :at)
            ON CONFLICT (user_id) DO UPDATE SET
                paused=FALSE, pause_mode=NULL, paused_until=NULL, updated_at=EXCLUDED.updated_at
            """
        ),
        {"uid": str(user.id), "at": point},
    )
    await append_family_audit(
        session,
        circle_id=snapshot.circle.id,
        actor_user_id=user.id,
        subject_user_id=user.id,
        event_type="sharing_resumed",
        details={"automatic": False},
    )
    return {"paused": False}


async def leave_circle(session: AsyncSession, *, user: User, now: datetime | None = None) -> dict:
    from app.services.family_circle_runtime_authority import membership_snapshot, runtime_decision
    point = now or datetime.now(timezone.utc)
    decision = await runtime_decision(session, actor_user_id=user.id, action=ACTION_LEAVE_CIRCLE)
    if not decision.canonical or not decision.allowed:
        raise PermissionError(decision.code)
    snapshot = await membership_snapshot(session, user.id)
    if snapshot is None:
        raise PermissionError("family_circle_required")
    if snapshot.membership.role == "owner":
        raise PermissionError("owner_must_transfer_or_cancel")
    recipients = await _remaining_member_ids(session, snapshot.circle.id, exclude_user_id=user.id)
    snapshot.membership.status = "left"
    snapshot.membership.ended_at = point
    await session.execute(
        text(
            """
            INSERT INTO family_sharing_states (user_id, paused, pause_mode, paused_until, updated_at)
            VALUES (:uid, TRUE, 'manual', NULL, :at)
            ON CONFLICT (user_id) DO UPDATE SET
                paused=TRUE, pause_mode='manual', paused_until=NULL, updated_at=EXCLUDED.updated_at
            """
        ),
        {"uid": str(user.id), "at": point},
    )
    await append_family_audit(
        session,
        circle_id=snapshot.circle.id,
        actor_user_id=user.id,
        subject_user_id=user.id,
        event_type="member_left",
        details={"public_message": "A member left the circle"},
    )
    from app.services.family_circle_notification_outbox import enqueue_family_notifications
    outbox_ids = await enqueue_family_notifications(
        session,
        circle_id=snapshot.circle.id,
        recipient_user_ids=recipients,
        event_type="family_member_left",
        title="NISCHINT Family Circle",
        body="A member left the circle",
        payload={},
        event_key_prefix=f"member-left:{user.id}:{point.isoformat()}",
    )
    return {"left": True, "message": "A member left the circle", "notification_outbox_ids": outbox_ids}


async def remove_member(session: AsyncSession, *, actor: User, target_user_id, now: datetime | None = None) -> dict:
    """Internal canonical removal primitive; public exposure requires step-up OTP."""
    from app.core.family_circle_permissions import ACTION_REMOVE_MEMBER
    from app.services.family_circle_runtime_authority import membership_snapshot, runtime_decision
    point = now or datetime.now(timezone.utc)
    decision = await runtime_decision(session, actor_user_id=actor.id, target_user_id=target_user_id, action=ACTION_REMOVE_MEMBER)
    if not decision.canonical or not decision.allowed:
        raise PermissionError(decision.code)
    actor_snap = await membership_snapshot(session, actor.id)
    target_snap = await membership_snapshot(session, target_user_id)
    if actor_snap is None or target_snap is None or actor_snap.circle.id != target_snap.circle.id:
        raise PermissionError("different_circle")
    if target_snap.membership.role == "owner" or str(target_snap.membership.user_id) == str(actor_snap.circle.owner_user_id):
        raise PermissionError("owner_cannot_be_removed")
    recipients = await _remaining_member_ids(session, actor_snap.circle.id, exclude_user_id=target_user_id)
    target_snap.membership.status = "removed"
    target_snap.membership.ended_at = point
    await session.execute(
        text(
            """
            INSERT INTO family_sharing_states (user_id, paused, pause_mode, paused_until, updated_at)
            VALUES (:uid, TRUE, 'manual', NULL, :at)
            ON CONFLICT (user_id) DO UPDATE SET
                paused=TRUE, pause_mode='manual', paused_until=NULL, updated_at=EXCLUDED.updated_at
            """
        ),
        {"uid": str(target_user_id), "at": point},
    )
    await append_family_audit(
        session,
        circle_id=actor_snap.circle.id,
        actor_user_id=actor.id,
        subject_user_id=target_user_id,
        event_type="member_removed",
        details={},
    )
    from app.services.family_circle_notification_outbox import enqueue_family_notifications
    outbox_ids = await enqueue_family_notifications(
        session,
        circle_id=actor_snap.circle.id,
        recipient_user_ids=[target_user_id],
        event_type="family_member_removed",
        title="NISCHINT Family Circle",
        body="You were removed from the Family Circle.",
        payload={},
        event_key_prefix=f"member-removed:{target_user_id}:{point.isoformat()}",
    )
    return {"removed": True, "notification_outbox_ids": outbox_ids, "remaining_member_ids": recipients}


async def appoint_co_admin(session: AsyncSession, *, owner: User, target_user_id) -> dict:
    """Internal Owner-only role primitive; public route requires step-up OTP."""
    from app.core.family_circle_permissions import ACTION_MANAGE_CO_ADMIN
    from app.services.family_circle_runtime_authority import membership_snapshot, runtime_decision
    decision = await runtime_decision(session, actor_user_id=owner.id, action=ACTION_MANAGE_CO_ADMIN)
    if not decision.canonical or not decision.allowed:
        raise PermissionError(decision.code)
    owner_snap = await membership_snapshot(session, owner.id)
    target_snap = await membership_snapshot(session, target_user_id)
    if owner_snap is None or target_snap is None or owner_snap.circle.id != target_snap.circle.id:
        raise PermissionError("different_circle")
    if str(target_user_id) == str(owner.id) or target_snap.membership.role == "owner":
        raise PermissionError("owner_cannot_be_co_admin")
    if target_snap.membership.role == "minor":
        raise PermissionError("co_admin_must_be_adult")
    current = (
        await session.execute(
            text("SELECT user_id FROM circle_memberships WHERE circle_id=:circle_id AND status='active' AND role='co_admin'"),
            {"circle_id": str(owner_snap.circle.id)},
        )
    ).scalar_one_or_none()
    if current is not None and str(current) != str(target_user_id):
        raise PermissionError("co_admin_already_exists")
    previous_role = target_snap.membership.role
    target_snap.membership.role = "co_admin"
    await append_family_audit(
        session,
        circle_id=owner_snap.circle.id,
        actor_user_id=owner.id,
        subject_user_id=target_user_id,
        event_type="role_changed",
        details={"from": previous_role, "to": "co_admin"},
    )
    return {"co_admin_user_id": str(target_user_id)}


async def remove_co_admin(session: AsyncSession, *, owner: User, target_user_id) -> dict:
    from app.core.family_circle_permissions import ACTION_MANAGE_CO_ADMIN
    from app.services.family_circle_runtime_authority import membership_snapshot, runtime_decision
    decision = await runtime_decision(session, actor_user_id=owner.id, action=ACTION_MANAGE_CO_ADMIN)
    if not decision.canonical or not decision.allowed:
        raise PermissionError(decision.code)
    owner_snap = await membership_snapshot(session, owner.id)
    target_snap = await membership_snapshot(session, target_user_id)
    if owner_snap is None or target_snap is None or owner_snap.circle.id != target_snap.circle.id:
        raise PermissionError("different_circle")
    if target_snap.membership.role != "co_admin":
        raise PermissionError("target_is_not_co_admin")
    target_snap.membership.role = "adult_member"
    await append_family_audit(
        session,
        circle_id=owner_snap.circle.id,
        actor_user_id=owner.id,
        subject_user_id=target_user_id,
        event_type="role_changed",
        details={"from": "co_admin", "to": "adult_member"},
    )
    return {"removed_co_admin_user_id": str(target_user_id)}


async def transfer_ownership(
    session: AsyncSession,
    *,
    owner: User,
    target_user_id,
    billing_mandate_ready: bool = False,
) -> dict:
    """Internal ownership primitive. Public exposure requires fresh step-up OTP."""
    from app.core.family_circle_permissions import ACTION_TRANSFER_OWNERSHIP
    from app.services.family_circle_entitlement_service import resolve_entitlement
    from app.services.family_circle_runtime_authority import membership_snapshot, runtime_decision
    decision = await runtime_decision(session, actor_user_id=owner.id, action=ACTION_TRANSFER_OWNERSHIP)
    if not decision.canonical or not decision.allowed:
        raise PermissionError(decision.code)
    owner_snap = await membership_snapshot(session, owner.id)
    target_snap = await membership_snapshot(session, target_user_id)
    if owner_snap is None or target_snap is None or owner_snap.circle.id != target_snap.circle.id:
        raise PermissionError("different_circle")
    if str(target_user_id) == str(owner.id):
        raise PermissionError("owner_transfer_target_must_differ")
    if target_snap.membership.role == "minor":
        raise PermissionError("owner_must_be_adult")
    ent = await resolve_entitlement(session, owner_snap.circle)
    if ent.state in {"paid_active", "grace"} and not billing_mandate_ready:
        raise PermissionError("new_owner_payment_mandate_required")

    previous_target_role = target_snap.membership.role
    # Flush the old Owner demotion first so the partial unique owner index cannot
    # be violated by SQLAlchemy update ordering during the transfer.
    owner_snap.membership.role = "adult_member"
    await session.flush()
    target_snap.membership.role = "owner"
    owner_snap.circle.owner_user_id = target_snap.membership.user_id
    await session.flush()
    await append_family_audit(
        session,
        circle_id=owner_snap.circle.id,
        actor_user_id=owner.id,
        subject_user_id=target_user_id,
        event_type="ownership_transferred",
        details={"previous_target_role": previous_target_role},
    )
    return {"owner_user_id": str(target_user_id)}


__all__ = [
    "PAUSE_MODES", "pause_own_sharing", "resume_own_sharing", "leave_circle",
    "remove_member", "appoint_co_admin", "remove_co_admin", "transfer_ownership",
    "deliver_pause_notification", "deliver_circle_message",
]
