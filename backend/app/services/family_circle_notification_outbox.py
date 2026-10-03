"""Durable Family Circle notification outbox.

Lifecycle state commits first. Push transport is attempted afterwards and a
failed/no-token delivery remains pending for a later retry instead of rolling
back privacy/membership state or being silently lost.
"""
from __future__ import annotations

import json
import uuid
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MAX_ATTEMPTS = 8
BATCH_SIZE = 25


async def _retry(session, outbox_id, attempts: int, reason: str):
    await session.execute(
        text("""UPDATE family_notification_outbox
                SET attempts=attempts+1, last_error=:error,
                    next_attempt_at=NOW() + (:delay * INTERVAL '1 second')
                WHERE id=:id AND delivered_at IS NULL"""),
        {"id": outbox_id, "error": reason[:300],
         "delay": min(3600, 30 * (2 ** min(attempts, 7)))},
    )


async def enqueue_family_notifications(
    session: AsyncSession,
    *,
    circle_id,
    recipient_user_ids: Iterable,
    event_type: str,
    title: str,
    body: str,
    payload: dict | None = None,
    event_key_prefix: str | None = None,
) -> list[str]:
    ids: list[str] = []
    for recipient in recipient_user_ids:
        recipient_id = str(recipient)
        event_key = f"{event_key_prefix}:{recipient_id}" if event_key_prefix else None
        outbox_id = uuid.uuid4()
        result = await session.execute(
            text(
                """
                INSERT INTO family_notification_outbox
                    (id, circle_id, recipient_user_id, event_key, event_type,
                     title, body, payload_json, created_at)
                VALUES
                    (:id, :circle_id, :recipient_user_id, :event_key, :event_type,
                     :title, :body, CAST(:payload AS JSONB), NOW())
                ON CONFLICT (event_key) DO NOTHING
                RETURNING id
                """
            ),
            {
                "id": outbox_id,
                "circle_id": circle_id,
                "recipient_user_id": recipient_id,
                "event_key": event_key,
                "event_type": str(event_type),
                "title": str(title)[:160],
                "body": str(body)[:500],
                "payload": json.dumps(payload or {}, separators=(",", ":"), sort_keys=True),
            },
        )
        inserted = result.scalar_one_or_none()
        if inserted is not None:
            ids.append(str(inserted))
        elif event_key:
            existing = (
                await session.execute(
                    text("SELECT id FROM family_notification_outbox WHERE event_key=:event_key"),
                    {"event_key": event_key},
                )
            ).scalar_one_or_none()
            if existing is not None:
                ids.append(str(existing))
    return ids


async def deliver_outbox_notifications(session: AsyncSession, *, outbox_ids: Iterable[str]) -> dict:
    ids = list(dict.fromkeys(str(x) for x in outbox_ids if x))[:BATCH_SIZE]
    if not ids:
        return {"delivered": 0, "pending": 0}
    delivered = 0
    pending = 0
    from app.services.push_service import get_users_push_tokens, send_push_to_tokens

    for outbox_id in ids:
        row = (
            await session.execute(
                text(
                    """
                    SELECT id, recipient_user_id, event_type, title, body, payload_json,
                           delivered_at, attempts
                      FROM family_notification_outbox
                     WHERE id=:id AND attempts < 8
                       AND next_attempt_at <= NOW()
                     FOR UPDATE SKIP LOCKED
                    """
                ),
                {"id": outbox_id},
            )
        ).mappings().first()
        if not row or row["delivered_at"] is not None:
            continue
        recipient = row["recipient_user_id"]
        if recipient is None:
            await _retry(session, outbox_id, row["attempts"], "recipient_deleted")
            pending += 1
            continue
        try:
            recipient_uuid = uuid.UUID(str(recipient))
            tokens = await get_users_push_tokens(session, [recipient_uuid])
            if not tokens:
                await _retry(session, outbox_id, row["attempts"], "no_push_token")
                pending += 1
                continue
            payload = row["payload_json"] if isinstance(row["payload_json"], dict) else {}
            data = {"type": str(row["event_type"]), **payload}
            successful = await send_push_to_tokens(tokens, str(row["title"]), str(row["body"]), data=data)
            if not successful or successful <= 0:
                await _retry(session, outbox_id, row["attempts"], "zero_successful_sends")
                pending += 1
                continue
            # Recipient-level delivery: one accepted device means notified.
            # Do not resend to successful devices just because a second token
            # failed. Record partial acceptance explicitly (FCM acceptance is
            # not a claim that the user read the notification).
            await session.execute(
                text("UPDATE family_notification_outbox SET delivered_at=NOW(), attempts=attempts+1, last_error=:partial WHERE id=:id"),
                {"id": outbox_id, "partial": "partial_device_delivery" if successful < len(tokens) else None},
            )
            delivered += 1
        except Exception as exc:
            await _retry(session, outbox_id, row["attempts"], type(exc).__name__)
            pending += 1
    return {"delivered": delivered, "pending": pending}


async def drain_family_notifications(session: AsyncSession) -> dict:
    """Bounded worker-owned retry. Exhausted rows remain for explicit review."""
    rows = await session.execute(text("""
        SELECT id FROM family_notification_outbox
        WHERE delivered_at IS NULL AND attempts < 8 AND next_attempt_at <= NOW()
        ORDER BY next_attempt_at, created_at LIMIT 25 FOR UPDATE SKIP LOCKED
    """))
    return await deliver_outbox_notifications(session, outbox_ids=rows.scalars().all())


async def pending_notifications_for_user(session: AsyncSession, *, user_id, limit: int = 50) -> list[str]:
    rows = (
        await session.execute(
            text(
                """
                SELECT id FROM family_notification_outbox
                 WHERE recipient_user_id=:uid AND delivered_at IS NULL
                 ORDER BY created_at ASC LIMIT :limit
                """
            ),
            {"uid": str(user_id), "limit": max(1, min(int(limit), 100))},
        )
    ).scalars().all()
    return [str(x) for x in rows]


__all__ = [
    "enqueue_family_notifications", "deliver_outbox_notifications",
    "pending_notifications_for_user",
]
