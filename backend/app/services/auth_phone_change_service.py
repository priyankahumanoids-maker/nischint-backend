"""AUTH-05 durable phone-change workflow helpers.

No public routing lives here.  The operation stores only keyed phone identities;
callers must re-present raw numbers for each OTP send/verify and at completion.
All terminal mutation/step-up consumption stays in the caller transaction.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import text

from app.core.auth_foundation_policy import (
    PHONE_RECOVERY_SECONDS,
    aware,
    phone_change_ready,
    phone_security_key,
)


async def create_phone_change(
    session,
    *,
    user_id: UUID,
    old_phone: str,
    new_phone: str,
    key: bytes,
    recovery: bool,
    now: datetime,
) -> UUID:
    aware(now)
    old_digest = phone_security_key(old_phone, key)
    new_digest = phone_security_key(new_phone, key)
    if old_digest == new_digest:
        raise ValueError("New phone identity must differ")

    identifier = uuid4()
    await session.execute(text("""
        INSERT INTO auth_phone_change_operations
            (id,user_id,old_phone_digest,new_phone_digest,recovery,requested_at,
             eligible_after,owner_notice_state)
        VALUES (:id,:uid,:old,:new,:recovery,:now,:eligible,:notice)
    """), {
        "id": identifier,
        "uid": user_id,
        "old": old_digest,
        "new": new_digest,
        "recovery": recovery,
        "now": now,
        "eligible": now + timedelta(seconds=PHONE_RECOVERY_SECONDS if recovery else 0),
        "notice": "pending" if recovery else "not_required",
    })
    return identifier


async def pending_phone_change_exists(session, *, user_id: UUID) -> bool:
    """Return whether the account already has an unfinished phone change.

    Kept separate from ``create_phone_change`` so the original 7C-1 persistence
    contract remains stable: creating an operation still begins with the keyed
    INSERT and never persists raw phone values.
    """
    result = await session.execute(text("""
        SELECT id FROM auth_phone_change_operations
        WHERE user_id=:uid AND status='pending'
        LIMIT 1
    """), {"uid": user_id})
    return result.scalar_one_or_none() is not None


async def get_phone_change(session, *, operation_id: UUID, user_id: UUID, for_update: bool = False):
    suffix = " FOR UPDATE" if for_update else ""
    result = await session.execute(text(f"""
        SELECT id,user_id,old_phone_digest,new_phone_digest,recovery,
               old_verified_at,new_verified_at,requested_at,eligible_after,
               status,completed_at,cancelled_at,owner_notice_state,owner_notified_at
        FROM auth_phone_change_operations
        WHERE id=:id AND user_id=:uid
        {suffix}
    """), {"id": operation_id, "uid": user_id})
    return result.mappings().first()


def phone_matches_operation(*, operation, phone: str, key: bytes, which: str) -> bool:
    if which not in {"old", "new"}:
        raise ValueError("Invalid phone side")
    expected = operation[f"{which}_phone_digest"]
    return phone_security_key(phone, key) == expected


async def mark_phone_verified(
    session,
    *,
    operation_id: UUID,
    user_id: UUID,
    which: str,
    verified_at: datetime,
) -> bool:
    aware(verified_at)
    if which not in {"old", "new"}:
        raise ValueError("Invalid phone side")
    column = "old_verified_at" if which == "old" else "new_verified_at"
    result = await session.execute(text(f"""
        UPDATE auth_phone_change_operations
        SET {column}=:verified
        WHERE id=:id AND user_id=:uid AND status='pending'
        RETURNING id
    """), {"verified": verified_at, "id": operation_id, "uid": user_id})
    return result.scalar_one_or_none() is not None


async def recovery_is_eligible(session, *, operation_id: UUID, user_id: UUID, now: datetime) -> bool:
    aware(now)
    row = await get_phone_change(session, operation_id=operation_id, user_id=user_id)
    if not row or row["status"] != "pending" or not row["recovery"]:
        return False
    return now >= row["eligible_after"] and row["owner_notice_state"] in {"delivered", "not_required"}


async def queue_recovery_owner_notice(
    session,
    *,
    operation_id: UUID,
    user_id: UUID,
    now: datetime,
) -> str:
    """Durably hand a recovery notice to the canonical Family outbox.

    `delivered` on the phone operation means accepted by the durable Family
    notification outbox, not that a human has opened/read a push notification.
    Accounts outside an active Family Circle have no Circle Owner audience and
    are marked `not_required`.
    """
    aware(now)
    circle = (await session.execute(text("""
        SELECT c.id AS circle_id, c.owner_user_id AS owner_user_id
        FROM circle_memberships m
        JOIN family_circles c ON c.id=m.circle_id
        WHERE m.user_id=:uid AND m.status='active' AND c.status='active'
        LIMIT 1
    """), {"uid": user_id})).mappings().first()

    if not circle or not circle["owner_user_id"]:
        await session.execute(text("""
            UPDATE auth_phone_change_operations
            SET owner_notice_state='not_required'
            WHERE id=:id AND user_id=:uid AND status='pending' AND recovery=TRUE
        """), {"id": operation_id, "uid": user_id})
        return "not_required"

    payload = json.dumps({
        "type": "phone_change_recovery_requested",
        "operation_id": str(operation_id),
        "subject_user_id": str(user_id),
    })
    event_key = f"auth-phone-recovery:{operation_id}"
    await session.execute(text("""
        INSERT INTO family_notification_outbox
            (id,circle_id,recipient_user_id,event_key,event_type,title,body,
             payload_json,attempts,created_at,next_attempt_at)
        VALUES
            (:id,:circle,:owner,:event_key,'phone_change_recovery_requested',
             'Phone number recovery requested',
             'A protected NISCHINT account requested phone-number recovery. Review account activity if this was unexpected.',
             CAST(:payload AS JSONB),0,:now,:now)
        ON CONFLICT (event_key) DO NOTHING
    """), {
        "id": uuid4(),
        "circle": circle["circle_id"],
        "owner": circle["owner_user_id"],
        "event_key": event_key,
        "payload": payload,
        "now": now,
    })
    await session.execute(text("""
        UPDATE auth_phone_change_operations
        SET owner_notice_state='delivered', owner_notified_at=COALESCE(owner_notified_at,:now)
        WHERE id=:id AND user_id=:uid AND status='pending' AND recovery=TRUE
    """), {"id": operation_id, "uid": user_id, "now": now})
    return "delivered"


async def cancel_phone_change(session, *, operation_id: UUID, user_id: UUID, now: datetime) -> bool:
    """Cancel only the caller's still-pending operation; no identity state changes."""
    aware(now)
    result = await session.execute(text("""
        UPDATE auth_phone_change_operations
        SET status='cancelled', cancelled_at=:now
        WHERE id=:id AND user_id=:uid AND status='pending'
        RETURNING id
    """), {"id": operation_id, "uid": user_id, "now": now})
    return result.scalar_one_or_none() is not None


async def mark_completed(session, *, operation_id: UUID, user_id: UUID, now: datetime) -> bool:
    aware(now)
    result = await session.execute(text("""
        UPDATE auth_phone_change_operations
        SET status='completed', completed_at=:now
        WHERE id=:id AND user_id=:uid AND status='pending'
        RETURNING id
    """), {"id": operation_id, "uid": user_id, "now": now})
    return result.scalar_one_or_none() is not None


def operation_ready(operation, *, now: datetime) -> bool:
    if not operation or operation["status"] != "pending":
        return False
    if operation["recovery"] and operation["owner_notice_state"] not in {"delivered", "not_required"}:
        return False
    return phone_change_ready(
        recovery=bool(operation["recovery"]),
        requested_at=operation["requested_at"],
        eligible_after=operation["eligible_after"],
        old_verified_at=operation["old_verified_at"],
        new_verified_at=operation["new_verified_at"],
        now=now,
    )
