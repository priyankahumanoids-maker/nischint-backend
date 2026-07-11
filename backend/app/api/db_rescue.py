"""REL-04 — Operator-initiated pg_terminate_backend endpoint.

`POST /api/admin/db/terminate-backend/{pid}`
  • RBAC: admin or operator only
  • Always writes a `DBBackendTerminateAuditLog` row BEFORE issuing
    `SELECT pg_terminate_backend(pid)` (and updates the row with the
    outcome after)
  • Runs via the dedicated diagnostic asyncpg pool so a saturated ORM
    pool doesn't block the rescue action

Why a separate router file:
  • `admin.py` is already 580+ lines of user/facility CRUD — keeping
    DB-rescue surface area separate makes RBAC and audit policy easier
    to audit.
  • This file is mounted under `/api/admin/db/...` so the URL still
    reads as an admin action.
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.rbac import require_role
from app.models.db_backend_terminate_audit import DBBackendTerminateAuditLog
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/db", tags=["admin-db"])

_rescue_role = require_role(["admin", "operator"])


# ── Schema bootstrap ────────────────────────────────────────────────


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS db_backend_terminate_audits (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    user_email VARCHAR(200),
    target_pid INTEGER NOT NULL,
    query_text TEXT,
    duration_ms INTEGER,
    wait_event VARCHAR(60),
    state VARCHAR(40),
    reason VARCHAR(500),
    success BOOLEAN DEFAULT FALSE,
    pg_terminate_backend_returned BOOLEAN,
    error_message VARCHAR(500),
    ip_address VARCHAR(45),
    user_agent VARCHAR(300),
    incident_id UUID,
    extras JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_db_backend_terminate_audits_user_id
    ON db_backend_terminate_audits (user_id);
CREATE INDEX IF NOT EXISTS ix_db_backend_terminate_audits_target_pid
    ON db_backend_terminate_audits (target_pid);
CREATE INDEX IF NOT EXISTS ix_db_backend_terminate_audits_incident_id
    ON db_backend_terminate_audits (incident_id);
CREATE INDEX IF NOT EXISTS ix_db_backend_terminate_audits_created_at
    ON db_backend_terminate_audits (created_at);
"""

_table_ready = False


async def _ensure_audit_table(session: AsyncSession) -> None:
    """Idempotent table create — mirrors the pattern used by
    `dpdp_digest_service` and other code-only-managed tables in this
    codebase. Runs on the request session so it gets committed under
    the same connection that's about to write the audit row.
    """
    global _table_ready
    if _table_ready:
        return
    from sqlalchemy import text
    # Execute each statement separately — Supabase pgbouncer in
    # transaction-pooling mode doesn't allow multi-statement strings.
    for stmt in [s.strip() for s in _CREATE_TABLE_SQL.strip().split(";") if s.strip()]:
        await session.execute(text(stmt))
    await session.commit()
    _table_ready = True


# ── Request / response schemas ──────────────────────────────────────


class TerminateRequest(BaseModel):
    """Body for the terminate call. Everything is optional so the
    frontend can also issue a bare-bones `POST /pid` with an empty body
    when an operator just smashes the kill button.
    """
    # Forensic context the operator copy-pasted from the
    # pg_stat_activity_top row they were looking at. We don't trust the
    # client values for *deciding* anything — they just go into the
    # audit log to make the post-mortem readable.
    query_text:    Optional[str] = Field(None, max_length=4000)
    duration_ms:   Optional[int] = Field(None, ge=0)
    wait_event:    Optional[str] = Field(None, max_length=60)
    state:         Optional[str] = Field(None, max_length=40)
    reason:        Optional[str] = Field(None, max_length=500)
    incident_id:   Optional[UUID] = None


class TerminateResponse(BaseModel):
    success: bool
    pid: int
    pg_terminate_backend_returned: Optional[bool]
    audit_log_id: str
    error: Optional[str] = None


# ── The endpoint ─────────────────────────────────────────────────────


@router.post(
    "/terminate-backend/{pid}",
    response_model=TerminateResponse,
    status_code=status.HTTP_200_OK,
)
async def terminate_backend(
    pid: int,
    body: TerminateRequest,
    request: Request,
    user: User = Depends(_rescue_role),
    session: AsyncSession = Depends(get_db_session),
) -> TerminateResponse:
    """Fire `SELECT pg_terminate_backend({pid})` after writing an
    audit row. Every call is logged regardless of outcome.

    PID validation:
      • Must be > 0 (Postgres backend pids are always positive).
      • Cannot be the current backend's own pid — guardrail against
        an operator nuking the connection that's auditing the call.
    """
    if pid <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid pid (must be > 0)",
        )

    await _ensure_audit_table(session)

    # Pre-write the audit row so we have a record even if the SQL
    # blows up before we get to the outcome update.
    audit = DBBackendTerminateAuditLog(
        user_id=user.id,
        user_email=getattr(user, "email", None),
        target_pid=pid,
        query_text=body.query_text,
        duration_ms=body.duration_ms,
        wait_event=body.wait_event,
        state=body.state,
        reason=body.reason,
        incident_id=body.incident_id,
        success=False,
        pg_terminate_backend_returned=None,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", "")[:300],
    )
    session.add(audit)
    await session.commit()
    await session.refresh(audit)

    # Execute via the dedicated diagnostic pool — independent of the
    # SQLAlchemy pool that we're probably trying to rescue.
    pg_result: Optional[bool] = None
    error_text: Optional[str] = None
    try:
        from app.db.session import get_db_pool
        pool = await get_db_pool()
        # Guardrail: never let an operator terminate the diagnostic
        # backend that's serving this very request.
        async with pool.acquire() as conn:
            own_pid = await conn.fetchval("SELECT pg_backend_pid()")
            if int(own_pid) == int(pid):
                error_text = "refusing to terminate own diagnostic backend"
                logger.warning(f"[db_rescue] {error_text} (pid={pid})")
            else:
                # `pg_terminate_backend` returns BOOLEAN — true on
                # signal delivered, false if the pid was already gone.
                pg_result = await conn.fetchval(
                    "SELECT pg_terminate_backend($1)", pid
                )
    except Exception as e:
        error_text = str(e)[:480]
        logger.error(f"[db_rescue] pg_terminate_backend({pid}) raised: {e}")

    audit.success = bool(pg_result)
    audit.pg_terminate_backend_returned = pg_result
    audit.error_message = error_text
    await session.commit()

    logger.info(
        f"[db_rescue] user={user.email} pid={pid} pg_return={pg_result} "
        f"success={audit.success} error={error_text!r} "
        f"audit_id={audit.id}"
    )

    return TerminateResponse(
        success=bool(pg_result),
        pid=pid,
        pg_terminate_backend_returned=pg_result,
        audit_log_id=str(audit.id),
        error=error_text,
    )


# ── Read-only: list recent terminate audits ─────────────────────────


class AuditEntry(BaseModel):
    id: str
    created_at: str
    user_id: str
    user_email: Optional[str]
    target_pid: int
    duration_ms: Optional[int]
    wait_event: Optional[str]
    state: Optional[str]
    query_text: Optional[str]
    reason: Optional[str]
    success: bool
    error_message: Optional[str]
    incident_id: Optional[str]


@router.get("/terminate-backend/audits", response_model=list[AuditEntry])
async def list_terminate_audits(
    limit: int = 50,
    user: User = Depends(_rescue_role),
    session: AsyncSession = Depends(get_db_session),
) -> list[AuditEntry]:
    """Most-recent first. Capped at 200 rows per page — auditors who
    need more should pull from the DB directly."""
    limit = max(1, min(limit, 200))
    await _ensure_audit_table(session)
    from sqlalchemy import select
    q = (
        select(DBBackendTerminateAuditLog)
        .order_by(DBBackendTerminateAuditLog.created_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(q)).scalars().all()
    return [
        AuditEntry(
            id=str(r.id),
            created_at=r.created_at.isoformat() if r.created_at else "",
            user_id=str(r.user_id),
            user_email=r.user_email,
            target_pid=r.target_pid,
            duration_ms=r.duration_ms,
            wait_event=r.wait_event,
            state=r.state,
            query_text=r.query_text,
            reason=r.reason,
            success=bool(r.success),
            error_message=r.error_message,
            incident_id=str(r.incident_id) if r.incident_id else None,
        )
        for r in rows
    ]
