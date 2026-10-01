"""Append-only Family Circle audit + location-disclosure logging."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def append_family_audit(
    session: AsyncSession,
    *,
    circle_id,
    event_type: str,
    actor_user_id=None,
    subject_user_id=None,
    details: dict | None = None,
    event_key: str | None = None,
) -> bool:
    """Append one immutable application-audit event.

    ``event_key`` is optional idempotency for automatic/reconciliation events.
    Multiple NULL keys are allowed. No update/delete API exists for this table.
    """
    result = await session.execute(
        text(
            """
            INSERT INTO family_circle_audit_log
                (id, circle_id, actor_user_id, subject_user_id, event_type,
                 event_key, event_json, created_at)
            VALUES
                (:id, :circle_id, :actor_user_id, :subject_user_id, :event_type,
                 :event_key, CAST(:event_json AS JSONB), NOW())
            ON CONFLICT (event_key) DO NOTHING
            RETURNING id
            """
        ),
        {
            "id": uuid.uuid4(),
            "circle_id": circle_id,
            "actor_user_id": actor_user_id,
            "subject_user_id": subject_user_id,
            "event_type": str(event_type),
            "event_key": str(event_key)[:160] if event_key else None,
            "event_json": json.dumps(details or {}, separators=(",", ":"), sort_keys=True),
        },
    )
    return result.scalar_one_or_none() is not None


async def record_location_view(
    session: AsyncSession,
    *,
    circle_id,
    subject_user_id,
    view_kind: str,
    viewer_user_id=None,
    viewer_kind: str = "member",
    viewer_label: str | None = None,
) -> None:
    """Record an actual disclosure of another person's live/history location."""
    if viewer_user_id is not None and str(viewer_user_id) == str(subject_user_id):
        return
    kind = str(view_kind or "").strip().lower()
    if kind not in {"live", "history"}:
        raise ValueError("Unsupported location-view kind.")
    vkind = str(viewer_kind or "member").strip().lower()
    if vkind not in {"member", "public_link", "staff", "emergency"}:
        raise ValueError("Unsupported location-view viewer kind.")
    await session.execute(
        text(
            """
            INSERT INTO family_location_view_log
                (id, circle_id, viewer_user_id, viewer_kind, viewer_label,
                 subject_user_id, view_kind, created_at)
            VALUES
                (:id, :circle_id, :viewer_user_id, :viewer_kind, :viewer_label,
                 :subject_user_id, :view_kind, NOW())
            """
        ),
        {
            "id": uuid.uuid4(),
            "circle_id": circle_id,
            "viewer_user_id": viewer_user_id,
            "viewer_kind": vkind,
            "viewer_label": (str(viewer_label)[:120] if viewer_label else None),
            "subject_user_id": subject_user_id,
            "view_kind": kind,
        },
    )


async def record_location_disclosure(
    session: AsyncSession,
    *,
    subject_user_id,
    view_kind: str,
    viewer_user_id=None,
    viewer_kind: str = "member",
    viewer_label: str | None = None,
) -> bool:
    """Resolve the subject's active canonical circle and record a disclosure.

    Legacy-only subjects are left to legacy audit policy. Former canonical
    subjects have no active circle and therefore cannot create a new Family
    Circle view record.
    """
    row = (
        await session.execute(
            text(
                """
                SELECT cm.circle_id
                  FROM circle_memberships cm
                  JOIN family_circles fc ON fc.id=cm.circle_id
                 WHERE cm.user_id=:uid AND cm.status='active' AND fc.status='active'
                 LIMIT 1
                """
            ),
            {"uid": str(subject_user_id)},
        )
    ).mappings().first()
    if not row:
        return False
    await record_location_view(
        session,
        circle_id=row["circle_id"],
        subject_user_id=subject_user_id,
        view_kind=view_kind,
        viewer_user_id=viewer_user_id,
        viewer_kind=viewer_kind,
        viewer_label=viewer_label,
    )
    return True


async def who_viewed_my_location(
    session: AsyncSession,
    *,
    user_id,
    days: int = 30,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(int(days), 30)))
    page_size = max(1, min(int(limit), 500))
    page_offset = max(0, int(offset))
    result = await session.execute(
        text(
            """
            SELECT v.viewer_user_id,
                   COALESCE(u.full_name, v.viewer_label, 'Authorized viewer') AS viewer_name,
                   v.viewer_kind, v.view_kind, v.created_at
              FROM family_location_view_log v
              LEFT JOIN users u ON u.id = v.viewer_user_id
             WHERE v.subject_user_id = :user_id
               AND v.created_at >= :since
             ORDER BY v.created_at DESC, v.id DESC
             LIMIT :limit OFFSET :offset
            """
        ),
        {"user_id": str(user_id), "since": since, "limit": page_size, "offset": page_offset},
    )
    return [
        {
            "viewer_user_id": str(row["viewer_user_id"]) if row["viewer_user_id"] else None,
            "viewer_name": str(row["viewer_name"] or "Authorized viewer"),
            "viewer_kind": str(row["viewer_kind"] or "member"),
            "view_kind": str(row["view_kind"]),
            "viewed_at": row["created_at"],
        }
        for row in result.mappings().all()
    ]


async def count_location_views(session: AsyncSession, *, user_id, days: int = 30) -> int:
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(int(days), 30)))
    value = (
        await session.execute(
            text(
                """
                SELECT COUNT(*)
                  FROM family_location_view_log
                 WHERE subject_user_id=:user_id AND created_at>=:since
                """
            ),
            {"user_id": str(user_id), "since": since},
        )
    ).scalar_one()
    return int(value or 0)


__all__ = [
    "append_family_audit", "record_location_view", "record_location_disclosure",
    "who_viewed_my_location", "count_location_views",
]
