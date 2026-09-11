"""NISCHINT member-specific Protection Center monitoring policy.

Control plane only: no SOS, FCM, Guardian notification, escalation, sensor
inference, zone, route or wearable side effects. Guardian / authorized co-parent
updates exactly one linked protected member. Protected devices may only READ
their own desired policy.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.product_roles import (
    is_co_guardian,
    is_primary_guardian,
    is_protected_member,
    normalize_role,
)
from app.models.user import User

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS member_monitoring_policies (
    member_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    ai_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    location_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    microphone_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    version BIGINT NOT NULL DEFAULT 1,
    updated_by UUID NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""
_table_ready = False
_table_lock = asyncio.Lock()


async def ensure_member_monitoring_policy_table() -> None:
    global _table_ready
    if _table_ready:
        return
    async with _table_lock:
        if _table_ready:
            return
        from app.db.session import async_session
        async with async_session() as session:
            await session.execute(text(_DDL))
            await session.commit()
        _table_ready = True


def _default_policy(member_id: str) -> dict[str, Any]:
    return {
        "member_id": str(member_id),
        "ai_enabled": False,
        "location_enabled": False,
        "microphone_enabled": False,
        "version": 0,
        "updated_by": None,
        "updated_at": None,
        "source": "default_off",
    }


async def _load_policy(session: AsyncSession, member_id: str) -> dict[str, Any]:
    result = await session.execute(
        text(
            "SELECT member_id, ai_enabled, location_enabled, microphone_enabled, "
            "version, updated_by, updated_at FROM member_monitoring_policies "
            "WHERE member_id = :member_id"
        ),
        {"member_id": str(member_id)},
    )
    row = result.mappings().first()
    if not row:
        return _default_policy(member_id)
    return {
        "member_id": str(row["member_id"]),
        "ai_enabled": bool(row["ai_enabled"]),
        "location_enabled": bool(row["location_enabled"]),
        "microphone_enabled": bool(row["microphone_enabled"]),
        "version": int(row["version"] or 0),
        "updated_by": str(row["updated_by"]) if row["updated_by"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        "source": "server",
    }


async def _canonical_protected_member(session: AsyncSession, member_id: str) -> str:
    try:
        member_uuid = uuid.UUID(str(member_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(status_code=404, detail="Protected member not found") from exc

    result = await session.execute(
        text("SELECT id, role, is_active FROM users WHERE id = :member_id"),
        {"member_id": str(member_uuid)},
    )
    row = result.mappings().first()
    if not row or not row["is_active"] or not is_protected_member(row["role"]):
        raise HTTPException(status_code=404, detail="Protected member not found")
    return str(row["id"])


async def require_policy_read_access(
    session: AsyncSession,
    actor: User,
    member_id: str,
) -> str:
    target_id = await _canonical_protected_member(session, member_id)
    if str(actor.id) == target_id and is_protected_member(actor.role):
        return target_id
    return await require_policy_write_access(session, actor, target_id)


async def require_policy_write_access(
    session: AsyncSession,
    actor: User,
    member_id: str,
) -> str:
    """Only primary Guardian / authorized co-parent writes."""
    target_id = await _canonical_protected_member(session, member_id)
    role = normalize_role(actor.role)

    if is_primary_guardian(role) or is_co_guardian(role):
        from app.services.guardian_dashboard_engine import _get_linked_user_ids
        linked = await _get_linked_user_ids(
            session,
            actor.email,
            str(actor.id),
            actor.role,
            include_checkin_recovery=False,
        )
        if any(str(item) == target_id for item in linked):
            return target_id

    raise HTTPException(
        status_code=403,
        detail="You are not authorized to configure this protected member.",
    )


async def get_policy_for_actor(
    session: AsyncSession,
    actor: User,
    member_id: str,
) -> dict[str, Any]:
    await ensure_member_monitoring_policy_table()
    target_id = await require_policy_read_access(session, actor, member_id)
    return await _load_policy(session, target_id)


async def update_policy_for_actor(
    session: AsyncSession,
    actor: User,
    member_id: str,
    *,
    ai_enabled: bool | None = None,
    location_enabled: bool | None = None,
    microphone_enabled: bool | None = None,
) -> dict[str, Any]:
    await ensure_member_monitoring_policy_table()
    target_id = await require_policy_write_access(session, actor, member_id)

    # IMPORTANT: update only fields supplied by this request. Parent and
    # co-parent phones may toggle different controls at nearly the same time;
    # COALESCE preserves the other two booleans atomically instead of doing a
    # stale read -> full-row write that could lose an independent toggle.
    await session.execute(
        text(
            """
            INSERT INTO member_monitoring_policies
                (member_id, ai_enabled, location_enabled, microphone_enabled,
                 version, updated_by, updated_at)
            VALUES
                (:member_id,
                 COALESCE(:ai_enabled, FALSE),
                 COALESCE(:location_enabled, FALSE),
                 COALESCE(:microphone_enabled, FALSE),
                 1, :updated_by, NOW())
            ON CONFLICT (member_id) DO UPDATE SET
                ai_enabled = COALESCE(:ai_enabled, member_monitoring_policies.ai_enabled),
                location_enabled = COALESCE(:location_enabled, member_monitoring_policies.location_enabled),
                microphone_enabled = COALESCE(:microphone_enabled, member_monitoring_policies.microphone_enabled),
                version = member_monitoring_policies.version + 1,
                updated_by = :updated_by,
                updated_at = NOW()
            """
        ),
        {
            "member_id": target_id,
            "ai_enabled": ai_enabled,
            "location_enabled": location_enabled,
            "microphone_enabled": microphone_enabled,
            "updated_by": str(actor.id),
        },
    )
    await session.commit()
    updated = await _load_policy(session, target_id)

    # Existing SSE transport is only a best-effort wake-up hint. The protected
    # mobile bridge also polls, so Redis/SSE failure cannot corrupt policy state.
    try:
        from app.services.event_broadcaster import broadcaster
        await broadcaster.broadcast_to_user(
            target_id,
            "monitoring_policy_changed",
            updated,
        )
    except Exception as exc:
        logger.warning("[MONITORING_POLICY] SSE wake-up deferred: %s", exc)

    # PHASE 2B — DATA-ONLY high-priority FCM wake for the protected member.
    # This is not an emergency/Guardian notification. It wakes the protected
    # member's headless monitoring-policy task so AI/Mic/Location desired state
    # can be reconciled while the app UI is backgrounded/removed from Recents.
    try:
        from app.services.monitoring_policy_push import send_monitoring_policy_wake
        await send_monitoring_policy_wake(session, target_id, updated)
    except Exception as exc:
        logger.warning("[MONITORING_POLICY] FCM wake-up deferred: %s", exc)

    return updated
