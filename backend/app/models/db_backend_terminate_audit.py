"""REL-04 — Audit trail for operator-initiated pg backend terminations.

Every `POST /api/admin/db/terminate-backend/{pid}` writes one row
here before the SQL fires. The row carries enough context that, if
someone questions the action three months later, we can answer:

  • WHO  pressed the button (`user_id`, `user_email`),
  • WHEN (`created_at`),
  • WHICH  backend (pg `pid`),
  • WHAT  the backend was running at the moment (`query_text` from the
    `pg_stat_activity_top` snapshot the operator was looking at),
  • WHY   if they typed a free-form reason,
  • OUTCOME (`success`, `pg_terminate_backend_returned`,
    `error_message`),
  • from WHERE (`ip_address`, `user_agent`).
"""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base


class DBBackendTerminateAuditLog(Base):
    __tablename__ = "db_backend_terminate_audits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    # Who
    user_id    = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_email = Column(String(200))

    # What
    target_pid    = Column(Integer, nullable=False, index=True)
    query_text    = Column(String, nullable=True)
    duration_ms   = Column(Integer, nullable=True)
    wait_event    = Column(String(60), nullable=True)
    state         = Column(String(40), nullable=True)
    reason        = Column(String(500), nullable=True)

    # Outcome
    success                          = Column(Boolean, default=False)
    pg_terminate_backend_returned    = Column(Boolean, nullable=True)
    error_message                    = Column(String(500), nullable=True)

    # Provenance
    ip_address = Column(String(45))
    user_agent = Column(String(300))
    incident_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    extras     = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
