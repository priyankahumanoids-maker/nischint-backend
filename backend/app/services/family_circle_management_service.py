"""Canonical R1 operations. Caller owns commit; outbox delivery is asynchronous.

Requires fc08_r1_lifecycle. No startup DDL, payment calls or legal-verification
shortcuts. Existing membership, permission, audit and outbox remain authoritative.
"""
from __future__ import annotations

import json
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from app.core.age_policy import is_minor
from app.core.family_circle_roles import role_for_date_of_birth
from app.core.family_circle_permissions import (
    ACTION_ADD_MINOR, ACTION_MANAGE_BILLING, ACTION_MANAGE_CO_ADMIN,
    ACTION_REMOVE_MEMBER, ACTION_TRANSFER_OWNERSHIP,
)
from app.models.family_circle import CircleMembership, FamilyCircle
from app.models.user import User
from app.services.family_circle_audit_service import append_family_audit
from app.services.family_circle_notification_outbox import enqueue_family_notifications
from app.services.family_circle_runtime_authority import membership_snapshot, runtime_decision
from app.services.family_circle_plan_service import _lock_circle, runtime_seat_capacity
from app.services import family_circle_lifecycle_service as lifecycle


async def locked_membership(session, user_id, circle_id):
    # Use the same lock as canonical invite/seat allocation. Refresh identity-map
    # objects after waiting, so a competing role/membership change is not stale.
    await _lock_circle(session, circle_id)
    await session.execute(select(FamilyCircle).where(FamilyCircle.id == circle_id).execution_options(populate_existing=True))
    await session.execute(select(CircleMembership).where(CircleMembership.circle_id == circle_id).execution_options(populate_existing=True))
    snap = await membership_snapshot(session, user_id)
    if snap is None or snap.circle.id != circle_id:
        raise PermissionError("current_circle_required")
    return snap


async def authorize(session, user_id, action, target_id=None):
    decision = await runtime_decision(session, actor_user_id=user_id, action=action, target_user_id=target_id)
    if not decision.canonical or not decision.allowed:
        raise PermissionError(decision.code)


async def notify(session, circle_id, recipients, event, body, operation_id):
    return await enqueue_family_notifications(
        session, circle_id=circle_id, recipient_user_ids=recipients,
        event_type=event, title="NISCHINT Family Circle", body=body,
        payload={}, event_key_prefix=f"r1:{operation_id}:{event}",
    )


async def operation(session, *, circle_id, actor_id, kind, state, target_id=None,
                    membership_id=None, details=None, expires_at=None, operation_id=None):
    oid = operation_id or uuid.uuid4()
    await session.execute(text("""
        INSERT INTO family_lifecycle_operations
          (id,circle_id,actor_user_id,target_user_id,membership_id,kind,state,details,expires_at)
        VALUES (:id,:circle,:actor,:target,:membership,:kind,:state,CAST(:details AS JSONB),:expires)
    """), dict(id=oid, circle=circle_id, actor=actor_id, target=target_id,
                membership=membership_id, kind=kind, state=state,
                details=json.dumps(details or {}), expires=expires_at))
    return oid


async def co_admin(session, *, actor, circle_id, target_id, appoint):
    snap = await locked_membership(session, actor.id, circle_id)
    await authorize(session, actor.id, ACTION_MANAGE_CO_ADMIN)
    if appoint:
        # Keep a removed Co-Admin's slot reserved during the server Undo window.
        reserved = (await session.execute(text("""
            SELECT 1 FROM family_lifecycle_operations WHERE circle_id=:circle
              AND kind='member_remove' AND state='pending' AND expires_at > NOW()
              AND details->>'role'='co_admin' LIMIT 1
        """), {"circle": circle_id})).first()
        if reserved:
            raise PermissionError("co_admin_removal_undo_window_active")
        result = await lifecycle.appoint_co_admin(session, owner=actor, target_user_id=target_id)
    else:
        result = await lifecycle.remove_co_admin(session, owner=actor, target_user_id=target_id)
    await notify(session, snap.circle.id, [target_id], "family_role_changed",
                 "Your Family Circle administrative role changed.", uuid.uuid4())
    return result


async def request_transfer(session, *, actor, circle_id, target_id):
    snap = await locked_membership(session, actor.id, circle_id)
    await authorize(session, actor.id, ACTION_TRANSFER_OWNERSHIP)
    target = await membership_snapshot(session, target_id)
    if target is None or target.circle.id != circle_id or target_id == actor.id:
        raise PermissionError("eligible_circle_recipient_required")
    person = await session.get(User, target_id)
    role_for_date_of_birth(person.date_of_birth if person else None, "owner")
    # Expiry never changes ownership. An expired request may be replaced.
    await session.execute(text("""UPDATE family_lifecycle_operations SET state='cancelled'
        WHERE circle_id=:circle AND kind='ownership_transfer' AND state='pending'
          AND expires_at <= NOW()"""), {"circle": circle_id})
    existing = (await session.execute(text("""SELECT 1 FROM family_lifecycle_operations
        WHERE circle_id=:circle AND kind='ownership_transfer' AND state IN ('pending','provider_pending')"""), {"circle": circle_id})).first()
    if existing:
        raise PermissionError("ownership_transfer_already_pending")
    expires = datetime.now(timezone.utc) + timedelta(hours=48)
    oid = await operation(session, circle_id=circle_id, actor_id=actor.id, target_id=target_id,
                          membership_id=target.membership.id, kind="ownership_transfer", state="pending", expires_at=expires)
    await append_family_audit(session, circle_id=circle_id, actor_user_id=actor.id,
        subject_user_id=target_id, event_type="ownership_transfer_requested", details={"operation_id": str(oid)})
    await notify(session, circle_id, [target_id], "family_ownership_transfer_requested",
                 "Please review a request to become Family Circle Owner.", oid)
    return {"operation_id": str(oid), "state": "pending_recipient_acceptance", "expires_at": expires.isoformat()}


async def load_operation(session, oid, circle_id, kind):
    row = (await session.execute(text("""SELECT * FROM family_lifecycle_operations
        WHERE id=:id AND circle_id=:circle AND kind=:kind FOR UPDATE"""),
        {"id": oid, "circle": circle_id, "kind": kind})).mappings().first()
    if not row:
        raise PermissionError("operation_not_found")
    return row


async def accept_transfer(session, *, actor, circle_id, operation_id):
    await locked_membership(session, actor.id, circle_id)
    row = await load_operation(session, operation_id, circle_id, "ownership_transfer")
    if row["target_user_id"] != actor.id or row["state"] != "pending" or row["expires_at"] <= datetime.now(timezone.utc):
        raise PermissionError("transfer_not_acceptible")
    sender = await session.get(User, row["actor_user_id"])
    current = await membership_snapshot(session, sender.id)
    if current is None or current.circle.id != circle_id or current.membership.role != "owner":
        raise PermissionError("sponsor_no_longer_owner")
    role_for_date_of_birth(actor.date_of_birth, "owner")
    recipient = await membership_snapshot(session, actor.id)
    if recipient is None or recipient.membership.id != row['membership_id']:
        raise PermissionError('recipient_membership_changed')
    # R1 separates canonical Owner authority from existing paid-period payer.
    # The operation's immutable actor ID retains the previous payer identity;
    # provider subscription references and billing events are never changed.
    from app.services.family_circle_entitlement_service import resolve_entitlement
    entitlement = await resolve_entitlement(session, current.circle)
    payment_pending = current.circle.plan != 'trial'
    result = await lifecycle.transfer_ownership(session, owner=sender, target_user_id=actor.id,
                                                 defer_mandate_transition=True)
    await session.execute(text("""UPDATE family_lifecycle_operations
        SET state=:state,completed_at=NOW(),expires_at=NULL,
            details=CAST(:details AS JSONB) WHERE id=:id"""),
        {"id": operation_id, "state": "provider_pending" if payment_pending else "completed",
         "details": json.dumps({"ownership_accepted": True, "previous_payer_user_id": str(sender.id),
                                "mandate_verified": False, "payment_transition_pending": payment_pending,
                                "existing_paid_period_end": entitlement.access_until.isoformat() if entitlement.access_until else None})})
    await append_family_audit(session, circle_id=circle_id, actor_user_id=actor.id,
        subject_user_id=sender.id, event_type="ownership_transfer_accepted", details={"operation_id": str(operation_id)})
    await notify(session, circle_id, [sender.id, actor.id], "family_ownership_transferred",
                 "Family Circle ownership transfer was accepted.", operation_id)
    return {**result, "payment_transition_pending": payment_pending}


async def remove_member(session, *, actor, circle_id, target_id):
    await locked_membership(session, actor.id, circle_id)
    if actor.id == target_id:
        raise PermissionError("use_leave_circle_for_self")
    await authorize(session, actor.id, ACTION_REMOVE_MEMBER, target_id)
    target = await membership_snapshot(session, target_id)
    if target is None or target.circle.id != circle_id or target.membership.role == "owner":
        raise PermissionError("removable_member_required")
    role, seat, mid = target.membership.role, target.membership.seat, target.membership.id
    result = await lifecycle.remove_member(session, actor=actor, target_user_id=target_id)
    # Membership becomes removed in the same transaction. No local-only delay.
    # Do not restore sharing/consent on Undo: the subject must resume explicitly.
    expires = datetime.now(timezone.utc) + timedelta(seconds=10)
    oid = await operation(session, circle_id=circle_id, actor_id=actor.id, target_id=target_id,
        membership_id=mid, kind="member_remove", state="pending", expires_at=expires,
        details={"role": role, "seat": seat})
    await append_family_audit(session, circle_id=circle_id, actor_user_id=actor.id,
        subject_user_id=target_id, event_type="member_removal_undo_opened",
        details={"operation_id": str(oid), "undo_until": expires.isoformat()})
    return {**result, "operation_id": str(oid), "undo_until": expires.isoformat()}


async def undo_removal(session, *, actor, circle_id, operation_id):
    snap = await locked_membership(session, actor.id, circle_id)
    row = await load_operation(session, operation_id, circle_id, "member_remove")
    if row["actor_user_id"] != actor.id or row["state"] != "pending" or row["expires_at"] <= datetime.now(timezone.utc):
        raise PermissionError("undo_window_closed")
    # Target is deliberately no longer a member; authorize administration against
    # the still-current actor and separately prohibit restoring an Owner.
    if snap.membership.role not in {"owner", "co_admin"}:
        raise PermissionError("current_administrator_required")
    from app.core.family_circle_permissions import ACTION_INVITE_MEMBER
    await authorize(session, actor.id, ACTION_INVITE_MEMBER)
    membership = await session.get(CircleMembership, row["membership_id"])
    if membership is None or membership.status != "removed" or membership.role == "owner":
        raise PermissionError("removal_no_longer_reversible")
    active = (await session.execute(select(CircleMembership.id).where(
        CircleMembership.user_id == row["target_user_id"], CircleMembership.status == "active"))).first()
    if active:
        raise PermissionError("member_already_joined_a_circle")
    if snap.circle.plan not in {"trial", "individual", "family"}:
        raise PermissionError("current_plan_required")
    from app.services.family_circle_plan_service import _active_seat_count
    from app.services.family_circle_invite_service import _pending_invite_count
    capacity = await runtime_seat_capacity(session, snap.circle.plan, membership.seat)
    # Reclaim only this operation's still-valid, subject/seat-bound reservation.
    if (membership.circle_id != circle_id or membership.user_id != row["target_user_id"]
            or (row.get("details") or {}).get("seat") != membership.seat):
        raise PermissionError("removal_reservation_mismatch")
    occupied = await _active_seat_count(
        session, circle_id, membership.seat, exclude_removal_id=operation_id)
    invites = await _pending_invite_count(session, circle_id, membership.seat, datetime.now(timezone.utc))
    if occupied + invites >= capacity:
        raise PermissionError("seat_capacity_changed")
    # Recheck the database clock after capacity work; an expired reservation
    # cannot be claimed. The caller rolls back the whole mutation on denial.
    claimed = (await session.execute(text("""
        UPDATE family_lifecycle_operations SET state='undone',completed_at=NOW()
        WHERE id=:id AND state='pending' AND expires_at > clock_timestamp()
        RETURNING id
    """), {"id": operation_id})).scalar_one_or_none()
    if claimed is None:
        raise PermissionError("undo_window_closed")
    # DB active-user / active-Co-Admin indexes remain the final concurrency guard.
    membership.status = "active"
    membership.ended_at = None
    await session.flush()
    await append_family_audit(session, circle_id=circle_id, actor_user_id=actor.id,
        subject_user_id=row["target_user_id"], event_type="member_removal_undone", details={"operation_id": str(operation_id)})
    await notify(session, circle_id, [row["target_user_id"]], "family_member_removal_undone",
                 "Your membership was restored. Sharing remains paused; review your sharing choices.", operation_id)
    return {"restored": True, "sharing_paused": True}


async def request_minor(session, *, actor, circle_id, evidence_id, child_name, birth_date, relationship):
    await locked_membership(session, actor.id, circle_id)
    await authorize(session, actor.id, ACTION_ADD_MINOR)
    if relationship not in {"parent", "lawful_guardian"} or not is_minor(birth_date):
        raise ValueError("minor_and_parental_relationship_required")
    # Declaration is NOT verification or consent. No invite/consent/membership is
    # activated from caller-supplied references, names or relationship claims.
    oid = await operation(session, operation_id=evidence_id, circle_id=circle_id,
        actor_id=actor.id, kind="minor_add", state="awaiting_verification",
        details={"subject_binding": hashlib.sha256(f"{evidence_id}:{child_name.strip()}:{birth_date.isoformat()}".encode()).hexdigest(),
                 "declared_relationship": relationship, "verified": False})
    await append_family_audit(session, circle_id=circle_id, actor_user_id=actor.id,
        event_type="parental_verification_requested", details={"operation_id": str(oid)})
    return {"operation_id": str(oid), "state": "awaiting_verification", "activated": False,
            "message": "Parental verification is not yet available. No child account or membership has been activated."}


async def cancel_or_delete(session, *, actor, circle_id, delete):
    snap = await locked_membership(session, actor.id, circle_id)
    await authorize(session, actor.id, ACTION_MANAGE_BILLING)
    from app.services.family_circle_entitlement_service import resolve_entitlement
    entitlement = await resolve_entitlement(session, snap.circle)
    kind = "circle_delete" if delete else "plan_cancel"
    # No provider adapter is implemented. Persist the request honestly and keep
    # billing/lifecycle unchanged for a paid subscription until verified action.
    if snap.circle.plan != "trial":
        oid = await operation(session, circle_id=circle_id, actor_id=actor.id,
                              kind=kind, state="provider_pending")
        await append_family_audit(session, circle_id=circle_id, actor_user_id=actor.id,
            event_type=kind + "_requested", details={"operation_id": str(oid), "provider_pending": True})
        return {"state": "provider_pending", "completed": False,
                "message": "Request recorded. Provider cancellation is not completed; billing and membership remain unchanged."}
    if not delete:
        await session.execute(text("UPDATE family_circle_entitlements SET cancel_at_period_end=TRUE,updated_at=NOW() WHERE circle_id=:circle"), {"circle": circle_id})
        state = "completed"
    else:
        recipients = (await session.execute(select(CircleMembership.user_id).where(
            CircleMembership.circle_id == circle_id, CircleMembership.status == "active"))).scalars().all()
        snap.circle.status = "closed"
        await session.execute(text("UPDATE circle_memberships SET status='left',ended_at=NOW() WHERE circle_id=:circle AND status='active'"), {"circle": circle_id})
        await session.execute(text("UPDATE family_circle_invites SET status='revoked',revoked_at=NOW() WHERE circle_id=:circle AND status='pending'"), {"circle": circle_id})
        await session.execute(text("UPDATE family_circle_entitlements SET state='lifeline',updated_at=NOW() WHERE circle_id=:circle"), {"circle": circle_id})
        await notify(session, circle_id, recipients, "family_circle_closed", "The Family Circle was closed.", uuid.uuid4())
        state = "completed"
    oid = await operation(session, circle_id=circle_id, actor_id=actor.id, kind=kind, state=state)
    await append_family_audit(session, circle_id=circle_id, actor_user_id=actor.id,
        event_type=kind + "_completed", details={"operation_id": str(oid), "payment_provider_called": False})
    return {"state": state, "completed": True, "message": "Circle closed." if delete else "Trial will end on its existing expiry date; no paid subscription was cancelled."}


async def depart_for_erasure(session, user):
    """Privacy-request reconciliation, not permission to self-manage a circle.

    Existing authenticated erasure verification remains required by its route.
    A Minor's privacy request never grants pause/leave/administrative authority.
    Cancelling erasure will not restore membership or another person's consent.
    """
    from app.services.family_circle_service import get_active_membership
    membership = await get_active_membership(session, user.id)
    if membership is None:
        return
    snap = await locked_membership(session, user.id, membership.circle_id)
    if snap.membership.role == 'owner':
        raise PermissionError('Transfer ownership or complete Circle cancellation before requesting account deletion.')
    recipients = (await session.execute(select(CircleMembership.user_id).where(
        CircleMembership.circle_id == snap.circle.id, CircleMembership.status == 'active',
        CircleMembership.user_id != user.id))).scalars().all()
    snap.membership.status = 'left'
    snap.membership.ended_at = datetime.now(timezone.utc)
    await append_family_audit(session, circle_id=snap.circle.id, actor_user_id=user.id,
        subject_user_id=user.id, event_type='member_left', details={'public_message': 'A member left the circle'})
    await notify(session, snap.circle.id, recipients, 'family_member_left', 'A member left the circle', uuid.uuid4())
    await session.flush()
