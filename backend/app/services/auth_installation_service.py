"""Auth installation metadata, separate from wearable devices and FCM tokens.

All functions use a caller-owned transaction. No dispatch, session creation,
provider access or changes to the legacy push-token upsert are introduced.
"""
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import text

from app.core.auth_foundation_policy import aware, installation_key


async def associate_installation(session, *, user_id: UUID, session_id: UUID,
                                 installation_id: UUID, key: bytes, now: datetime) -> UUID:
    aware(now)
    digest = installation_key(user_id, installation_id, key)
    # Serialize first-device classification across simultaneous logins.
    subject = (await session.execute(text("SELECT id FROM users WHERE id=:uid FOR UPDATE"),
                                    {"uid": user_id})).scalar_one_or_none()
    if subject is None:
        raise ValueError("Unknown subject")
    sid = (await session.execute(text("""
        SELECT id FROM auth_sessions WHERE id=:sid AND user_id=:uid
            AND revoked_at IS NULL AND expires_at>:now FOR UPDATE
    """), {"sid": session_id, "uid": user_id, "now": now})).scalar_one_or_none()
    if sid is None:
        raise ValueError("Active subject session required")
    row = (await session.execute(text("""
        SELECT id,revoked_at FROM auth_installations
        WHERE user_id=:uid AND identity_digest=:digest FOR UPDATE
    """), {"uid": user_id, "digest": digest})).mappings().first()
    if row:
        if row["revoked_at"] is not None:
            raise ValueError("Installation revoked; explicit recovery required")
        identifier = row["id"]
        await session.execute(text("UPDATE auth_installations SET last_seen_at=:now WHERE id=:id"),
                              {"id": identifier, "now": now})
    else:
        other = (await session.execute(text("""
            SELECT id FROM auth_installations WHERE user_id=:uid LIMIT 1
        """), {"uid": user_id})).scalar_one_or_none()
        identifier = uuid4()
        await session.execute(text("""
            INSERT INTO auth_installations (id,user_id,identity_digest,created_at,last_seen_at,notice_state)
            VALUES (:id,:uid,:digest,:now,:now,:notice)
        """), {"id": identifier, "uid": user_id, "digest": digest, "now": now,
                "notice": "pending" if other is not None else "not_required"})
    await session.execute(text("""
        UPDATE auth_sessions SET auth_installation_id=:id WHERE id=:sid AND user_id=:uid
    """), {"id": identifier, "sid": session_id, "uid": user_id})
    return identifier


async def associate_push_token(session, *, user_id: UUID, installation_id: UUID, token: str) -> bool:
    result = await session.execute(text("""
        UPDATE push_tokens p SET auth_installation_id=:iid
        WHERE p.token=:token AND p.user_id=:uid AND EXISTS (
            SELECT 1 FROM auth_installations i WHERE i.id=:iid AND i.user_id=:uid AND i.revoked_at IS NULL)
        RETURNING p.token
    """), {"uid": user_id, "iid": installation_id, "token": token})
    return result.scalar_one_or_none() is not None


async def other_signed_in_push_tokens(session, *, user_id: UUID, installation_id: UUID, now: datetime) -> list[str]:
    aware(now)
    result = await session.execute(text("""
        SELECT DISTINCT p.token FROM push_tokens p JOIN auth_installations i
            ON i.id=p.auth_installation_id AND i.user_id=p.user_id
        WHERE p.user_id=:uid AND i.id<>:iid AND i.revoked_at IS NULL
            AND EXISTS (SELECT 1 FROM auth_sessions s WHERE s.auth_installation_id=i.id
                AND s.user_id=i.user_id AND s.revoked_at IS NULL AND s.expires_at>:now)
    """), {"uid": user_id, "iid": installation_id, "now": now})
    # A legacy account-transfer upsert may leave a stale installation pointer;
    # the owner join excludes it until a verified association is refreshed.
    return list(result.scalars().all())


async def dispatch_pending_new_device_notice(session, *, user_id: UUID, installation_id: UUID, now: datetime) -> str:
    """Deliver a single new-device notice to the user's other active installations.

    ``notice_state`` is the durable dedup key. A provider failure keeps the row
    pending so a later token-registration retry can deliver it. If there is no
    other active signed-in destination, no notification is required.
    """
    aware(now)
    row = (await session.execute(text("""
        SELECT notice_state FROM auth_installations
        WHERE id=:iid AND user_id=:uid AND revoked_at IS NULL FOR UPDATE
    """), {"iid": installation_id, "uid": user_id})).mappings().first()
    if not row:
        raise ValueError("Active subject installation required")
    state = str(row["notice_state"] or "not_required")
    if state != "pending":
        return state

    tokens = await other_signed_in_push_tokens(
        session, user_id=user_id, installation_id=installation_id, now=now,
    )
    if not tokens:
        await session.execute(text("""
            UPDATE auth_installations SET notice_state='not_required'
            WHERE id=:iid AND user_id=:uid AND notice_state='pending'
        """), {"iid": installation_id, "uid": user_id})
        return "not_required"

    from app.services.push_service import send_push_to_tokens
    sent = await send_push_to_tokens(
        tokens,
        title="New sign-in to your NISCHINT account",
        body="A new device signed in to your account. Review Signed-in devices if this was not you.",
        data={"event_type": "new_device_login", "screen": "settings", "section": "sessions"},
    )
    if int(sent or 0) > 0:
        await session.execute(text("""
            UPDATE auth_installations SET notice_state='delivered'
            WHERE id=:iid AND user_id=:uid AND notice_state='pending'
        """), {"iid": installation_id, "uid": user_id})
        return "delivered"
    return "pending"
