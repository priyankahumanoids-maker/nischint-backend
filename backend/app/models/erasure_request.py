"""ErasureRequest ORM model — DPDP §17 right-to-erasure audit log.

Each row is one user-initiated or admin-triggered request to erase a
user's personal data. The row survives the user's hard-delete (FK is
`ondelete=SET NULL`) so the audit trail outlives the data it tracks.

Status state machine:

    pending  ──[user cancel]──> cancelled
       │
       ├──[day 30 scheduler]──> completed (completion_source='scheduled')
       └──[admin approve]────> completed (completion_source='admin_approve')

`completed` is terminal. `cancelled` is also terminal but a NEW request
can be submitted (the previous request_id is preserved for the audit
trail, the new one starts a fresh 30-day clock).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# Status enum — kept as plain strings in DB for migration ease.
STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"

# Completion sources.
COMPLETION_SCHEDULED = "scheduled"
COMPLETION_ADMIN_APPROVE = "admin_approve"

# Cancellation sources.
CANCELLATION_USER = "user"
CANCELLATION_ADMIN = "admin"


class ErasureRequest(Base):
    __tablename__ = "erasure_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Nullable on purpose — survives user hard-delete (ondelete=SET NULL).
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Denormalised so the audit row remains meaningful after user deletion.
    user_email: Mapped[str] = mapped_column(String(255), nullable=False)

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=STATUS_PENDING,
    )

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    grace_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    cancellation_source: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
    )
    completion_source: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
    )
    completion_actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    request_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    cascade_summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ErasureRequest id={self.id} user_email={self.user_email} "
            f"status={self.status} grace_expires_at={self.grace_expires_at}>"
        )
