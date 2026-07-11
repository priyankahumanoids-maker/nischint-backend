"""DPDP-01: Erasure service.

Single source of truth for the data-erasure right-of-deletion business
logic. Endpoints in `app/api/erasure.py` and the daily scheduler both
delegate to functions here.

Design choices (locked in this sprint):

1. **Soft-delete cascade is implemented via user tombstone** (set
   `users.deleted_at`) rather than per-table `deleted_at` columns. This
   is sufficient because:
     - Read paths can filter `WHERE users.deleted_at IS NULL` (or simply
       refuse via auth dep).
     - Write paths are gated by `get_current_user_active` which rejects
       frozen accounts on day 1.
     - At hard-delete on day 30, we `DELETE FROM users WHERE id = …` and
       all six tables in the spec cascade automatically via existing
       `ondelete="CASCADE"` foreign keys.

2. **Redis health signals are hard-deleted immediately** (DELETE-1c).
   Health-sensor data has 8-day TTL but DPDP §17 favours immediate
   purge where possible — and Redis has no soft-delete primitive.

3. **30-day grace window** is per DPDP convention. Users can cancel
   via `POST /api/privacy/erasure-requests/{id}/cancel` during the
   window. Admins can short-circuit via
   `POST /api/admin/erasure-requests/{id}/approve`.

4. **Audit row outlives the user**. `erasure_requests.user_id` is
   `ON DELETE SET NULL`. The denormalised `user_email`, `request_ip`,
   `user_agent` survive forever. We can still answer "did user X get
   erased on date Y?" five years later.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.erasure_request import (
    ErasureRequest,
    STATUS_PENDING,
    STATUS_COMPLETED,
    STATUS_CANCELLED,
    COMPLETION_SCHEDULED,
    COMPLETION_ADMIN_APPROVE,
    CANCELLATION_USER,
    CANCELLATION_ADMIN,
)
from app.models.user import User
from app.services import user_cache

logger = logging.getLogger(__name__)

# 30 days per DPDP convention. Exposed as a constant so the scheduler
# and admin-approve endpoint can both reference it (and tests can
# monkey-patch it down to seconds for fast verification).
GRACE_PERIOD_DAYS = 30


# ── Custom exceptions (mapped to HTTP statuses in the API layer) ─────


class ErasureError(Exception):
    """Base exception for erasure-flow errors."""


class ErasureAlreadyPending(ErasureError):
    """User already has a pending erasure request."""


class ErasureNotFound(ErasureError):
    """No erasure request with that id (or not visible to this user)."""


class ErasureNotCancellable(ErasureError):
    """Request is no longer in a state that can be cancelled."""


# ─────────────────────────────────────────────────────────────────────


async def submit_request(
    session: AsyncSession,
    user: User,
    *,
    request_ip: str | None,
    user_agent: str | None,
    reason: str | None,
) -> ErasureRequest:
    """Create a new erasure request for `user`.

    Side effects:
      - Inserts an `erasure_requests` row with status='pending'.
      - Sets `users.deleted_at`, `users.erasure_status='pending'`,
        `users.erasure_scheduled_for=<now + 30d>`.
      - Invalidates the user cache so the freeze is enforced
        immediately on the next request.

    Raises:
      - `ErasureAlreadyPending` if the user already has an in-flight
        request. Multiple pending requests is meaningless and would
        require deciding which deadline to honour.
    """
    # Reject if there's already a pending request.
    existing_q = await session.execute(
        select(ErasureRequest)
        .where(ErasureRequest.user_id == user.id)
        .where(ErasureRequest.status == STATUS_PENDING)
    )
    if existing_q.scalar_one_or_none() is not None:
        raise ErasureAlreadyPending(
            "An erasure request is already pending for this account."
        )

    now = datetime.now(timezone.utc)
    grace_expires = now + timedelta(days=GRACE_PERIOD_DAYS)

    req = ErasureRequest(
        user_id=user.id,
        user_email=user.email,
        status=STATUS_PENDING,
        requested_at=now,
        grace_expires_at=grace_expires,
        request_ip=request_ip,
        user_agent=user_agent,
        request_reason=reason,
    )
    session.add(req)

    # Mark the user account as frozen.
    await session.execute(
        update(User)
        .where(User.id == user.id)
        .values(
            deleted_at=now,
            erasure_status=STATUS_PENDING,
            erasure_scheduled_for=grace_expires,
        )
    )

    await session.flush()  # populate req.id

    # Invalidate the auth cache so the freeze is enforced on the next
    # request — otherwise the user could keep writing for up to the
    # cache TTL (30s).
    try:
        user_cache.invalidate_user(str(user.id))
        if user.cognito_sub:
            user_cache.invalidate_user(user.cognito_sub)
    except Exception:  # noqa: BLE001 — cache miss is non-fatal
        logger.debug("user_cache invalidation failed (non-fatal)", exc_info=True)

    logger.info(
        "[erasure] submitted request id=%s user_id=%s email=%s grace_expires_at=%s",
        req.id, user.id, user.email, grace_expires.isoformat(),
    )
    return req


async def cancel_request(
    session: AsyncSession,
    *,
    request_id: uuid.UUID,
    actor_user: User,
    actor_source: str = CANCELLATION_USER,
) -> ErasureRequest:
    """Cancel a pending erasure request.

    If `actor_source == 'user'`, the request must belong to `actor_user`.
    If `actor_source == 'admin'`, the actor can cancel any user's request
    (caller is expected to have already RBAC-checked admin role).
    """
    q = await session.execute(
        select(ErasureRequest).where(ErasureRequest.id == request_id)
    )
    req = q.scalar_one_or_none()
    if req is None:
        raise ErasureNotFound(f"erasure request {request_id} not found")

    if actor_source == CANCELLATION_USER and req.user_id != actor_user.id:
        # Don't leak existence to non-owners.
        raise ErasureNotFound(f"erasure request {request_id} not found")

    if req.status != STATUS_PENDING:
        raise ErasureNotCancellable(
            f"erasure request {request_id} is in status '{req.status}', "
            f"cannot cancel"
        )

    now = datetime.now(timezone.utc)
    req.status = STATUS_CANCELLED
    req.cancelled_at = now
    req.cancellation_source = actor_source

    # Un-freeze the user account.
    if req.user_id is not None:
        await session.execute(
            update(User)
            .where(User.id == req.user_id)
            .values(
                deleted_at=None,
                erasure_status=None,
                erasure_scheduled_for=None,
            )
        )
        try:
            user_cache.invalidate_user(str(req.user_id))
        except Exception:  # noqa: BLE001
            logger.debug("user_cache invalidation failed (non-fatal)", exc_info=True)

    await session.flush()
    logger.info(
        "[erasure] cancelled request id=%s user_id=%s by=%s",
        req.id, req.user_id, actor_source,
    )
    return req


async def execute_hard_delete(
    session: AsyncSession,
    *,
    request_id: uuid.UUID,
    completion_source: str,
    actor_id: uuid.UUID | None = None,
) -> ErasureRequest:
    """Run the actual erasure cascade.

    Idempotent: if the request is already 'completed' or 'cancelled',
    returns the existing row unchanged. This lets the daily scheduler
    safely retry on transient failures.

    Cascade:
      1. Hard-delete Redis health signals (DELETE pattern keys).
      2. DELETE FROM users WHERE id = request.user_id
         — Postgres FKs with ondelete=CASCADE clean up all dependent
           rows (safety_events, incidents, location_trail_points,
           emergency_contacts, safety_event_feedback, etc.). The 6
           tables named in the DPDP-01 spec are all covered.
      3. The `erasure_requests` row's user_id is set to NULL by
         ON DELETE SET NULL — audit trail preserved.

    Returns the updated ErasureRequest with `cascade_summary` populated.
    """
    q = await session.execute(
        select(ErasureRequest).where(ErasureRequest.id == request_id)
    )
    req = q.scalar_one_or_none()
    if req is None:
        raise ErasureNotFound(f"erasure request {request_id} not found")

    if req.status != STATUS_PENDING:
        # Idempotent — return existing row.
        return req

    summary: dict[str, Any] = {
        "tables_cascaded": [],
        "redis_keys_deleted": 0,
        "mongo_docs_deleted": 0,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    user_id = req.user_id

    # ── 1. Redis: wipe wearable health-signal keys ──────────────────
    summary["redis_keys_deleted"] = _purge_redis_for_user(user_id)

    # ── 2. MongoDB: wipe known per-user collections (opt-in) ────────
    summary["mongo_docs_deleted"] = await _purge_mongo_for_user(user_id)

    # ── 3. SQL: cascade-delete the user row ─────────────────────────
    # We use raw SQL to avoid SQLAlchemy's relationship-loading
    # overhead. ondelete=CASCADE on the FKs handles the rest.
    cascade_tables = [
        "safety_events",
        "incidents",
        "safety_event_feedback",
        "location_trail_points",
        "emergency_contacts",
        "guardian_alerts",
        "wandering_events",
        "fall_events",
        "voice_distress_events",
        "incident_feedback",
        "fake_call_logs",
        "relationships",
        "guardian_relationships",
        "guardian_invites",
        "guardian_baselines",
        "guardian_risk_scores",
        "pickup_authorizations",
        "device_baselines",
    ]

    if user_id is not None:
        # Best-effort per-table row count BEFORE delete, for the audit
        # summary. We don't fail the delete on count errors — a missing
        # table or missing user_id column just means it doesn't apply
        # here. CRITICAL: each COUNT runs in its own SAVEPOINT so a
        # ProgrammingError on one table does not abort the outer
        # transaction and break the subsequent DELETE FROM users.
        counts: dict[str, int] = {}
        for t in cascade_tables:
            try:
                async with session.begin_nested():
                    row = await session.execute(
                        text(f"SELECT COUNT(*) FROM {t} WHERE user_id = :uid"),
                        {"uid": str(user_id)},
                    )
                    counts[t] = int(row.scalar() or 0)
            except Exception:  # noqa: BLE001
                # Table missing OR no user_id column. The cascade
                # DELETE on users handles anything with a proper FK
                # chain. The savepoint rollback keeps the outer
                # transaction clean.
                continue
        summary["tables_cascaded"] = [t for t, c in counts.items() if c > 0]
        summary["row_counts"] = counts

        # The actual cascade. FK ondelete=CASCADE propagates.
        await session.execute(
            text("DELETE FROM users WHERE id = :uid"),
            {"uid": str(user_id)},
        )

    # ── 4. Mark request completed ───────────────────────────────────
    now = datetime.now(timezone.utc)
    req.status = STATUS_COMPLETED
    req.completed_at = now
    req.completion_source = completion_source
    req.completion_actor_id = actor_id
    summary["completed_at"] = now.isoformat()
    req.cascade_summary = summary

    await session.flush()

    if user_id is not None:
        try:
            user_cache.invalidate_user(str(user_id))
        except Exception:  # noqa: BLE001
            logger.debug("user_cache invalidation failed (non-fatal)", exc_info=True)

    logger.info(
        "[erasure] completed request id=%s user_id=%s source=%s tables=%d",
        req.id, user_id, completion_source, len(summary["tables_cascaded"]),
    )
    return req


def _purge_redis_for_user(user_id: uuid.UUID | None) -> int:
    """Best-effort wipe of all Redis keys owned by `user_id`.

    Currently covers wearable health signals (`nischint:wearable:<uid>:*`)
    and the auth user cache. Returns the count of keys actually deleted
    (0 on Redis unavailability — the SQL hard-delete is still authoritative).
    """
    if user_id is None:
        return 0
    try:
        from app.services import redis_service

        client = redis_service._get_client()
        if client is None:
            return 0
        deleted = 0
        for pattern in (
            redis_service._key("wearable", f"{user_id}:*"),
            redis_service._key("user_cache", str(user_id)),
            redis_service._key("auth", f"user:{user_id}:*"),
        ):
            for key in client.scan_iter(match=pattern, count=200):
                deleted += int(client.delete(key) or 0)
        return deleted
    except Exception:  # noqa: BLE001
        logger.warning("[erasure] redis purge failed (non-fatal)", exc_info=True)
        return 0


async def _purge_mongo_for_user(user_id: uuid.UUID | None) -> int:
    """Best-effort wipe of Mongo docs that reference `user_id`.

    Returns the total doc count deleted across all collections.
    Failures are logged but non-fatal — the SQL hard-delete remains
    authoritative for compliance.
    """
    if user_id is None:
        return 0
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        from app.core.config import settings

        if not getattr(settings, "mongo_url", None):
            return 0
        client = AsyncIOMotorClient(
            settings.mongo_url, serverSelectionTimeoutMS=3000,
        )
        db = client[getattr(settings, "mongo_db", "nischint")]
        deleted = 0
        # Collections known to carry per-user PII. Extend as new ones
        # appear (see KNOWN_LIMITATIONS register for the full list).
        for coll in (
            "status_checks",
            "notification_preferences",
            "consent_records",
            "device_tokens",
        ):
            try:
                res = await db[coll].delete_many({"user_id": str(user_id)})
                deleted += res.deleted_count
            except Exception:  # noqa: BLE001
                logger.debug(
                    "[erasure] mongo delete on %s failed (non-fatal)",
                    coll, exc_info=True,
                )
        client.close()
        return deleted
    except Exception:  # noqa: BLE001
        logger.warning("[erasure] mongo purge failed (non-fatal)", exc_info=True)
        return 0


async def run_due_erasures(session: AsyncSession) -> int:
    """Daily scheduler entrypoint — execute all pending requests past
    their grace deadline.

    Returns the number of requests completed in this run. Errors on
    individual rows are logged but do not abort the batch — the next
    scheduler tick will retry.
    """
    now = datetime.now(timezone.utc)
    q = await session.execute(
        select(ErasureRequest.id)
        .where(ErasureRequest.status == STATUS_PENDING)
        .where(ErasureRequest.grace_expires_at <= now)
    )
    due_ids = [row[0] for row in q.all()]

    completed = 0
    for req_id in due_ids:
        try:
            await execute_hard_delete(
                session, request_id=req_id, completion_source=COMPLETION_SCHEDULED,
            )
            completed += 1
        except Exception:  # noqa: BLE001
            logger.exception("[erasure] scheduler: row %s failed", req_id)
            # Continue to next row — DON'T let one bad request block the batch.

    if due_ids:
        logger.info(
            "[erasure] scheduler tick: %d/%d completed",
            completed, len(due_ids),
        )
    return completed


__all__ = [
    "GRACE_PERIOD_DAYS",
    "ErasureError",
    "ErasureAlreadyPending",
    "ErasureNotFound",
    "ErasureNotCancellable",
    "CANCELLATION_USER",
    "CANCELLATION_ADMIN",
    "COMPLETION_SCHEDULED",
    "COMPLETION_ADMIN_APPROVE",
    "submit_request",
    "cancel_request",
    "execute_hard_delete",
    "run_due_erasures",
]
