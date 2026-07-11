"""Consent ORM model (DPDP Act §6).

One row per user-category combination — `(user_id, category)` is
unique. When the user revokes, `revoked_at` becomes non-NULL but the
row is kept (audit trail). Re-granting clears `revoked_at` and updates
`granted_at` + `consent_text_version`.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Consent(Base):
    __tablename__ = "consents"
    __table_args__ = (
        UniqueConstraint("user_id", "category", name="uq_consents_user_category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    consent_text_version: Mapped[str] = mapped_column(String(20), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Consent user_id={self.user_id} category={self.category} "
            f"granted_at={self.granted_at} revoked_at={self.revoked_at}>"
        )
