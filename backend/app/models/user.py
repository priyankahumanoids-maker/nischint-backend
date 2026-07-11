# User Model
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Float, JSON
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, List

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.senior import Senior


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    cognito_sub: Mapped[str | None] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
    )
    role: Mapped[str] = mapped_column(
        String(50),
        default="guardian",
        nullable=False,
    )
    facility_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )
    phone: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )
    full_name: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
    )
    preferred_channels: Mapped[dict] = mapped_column(
        type_=JSON,
        default=lambda: ["email"],
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    # New nullable columns for guardian linking and invite codes
    guardian_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    invite_code: Mapped[str | None] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
    )
    invite_code_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # NISCH-002B: last-known location (populated by mobile heartbeat).
    # Used by `trigger_alert` for co-location suppression. NULL → fail-safe
    # ("no recent fix" → never suppress → always notify).
    last_known_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_known_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_known_at:  Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── DPDP-01: erasure tombstone columns ────────────────────────────
    # When non-NULL, the account is "frozen": auth still works (so the
    # user can cancel their erasure), but write methods are refused by
    # `get_current_user_active` in `app/api/deps.py`.
    # `erasure_status` mirrors the linked `erasure_requests.status`
    # row so the auth hot path can answer "is this user mid-erasure?"
    # in one column read instead of a JOIN.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    erasure_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
    )
    erasure_scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )

    # Relationships
    seniors: Mapped[List["Senior"]] = relationship(
        "Senior",
        back_populates="guardian",
        cascade="all, delete",
    )

    def __repr__(self) -> str:
        return f"<User {self.email}>"
