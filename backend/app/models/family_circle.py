"""Family Circle v1.0 canonical membership authority.

This model is additive. It does not replace ``users.guardian_id``,
``relationships``, ``guardian_relationships``, GuardianInvite, emergency
contacts, or subscription assignment tables. Those remain compatibility inputs
until later phases migrate their callers to this authority deliberately.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FamilyCircle(Base):
    __tablename__ = "family_circles"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'closed')",
            name="ck_family_circles_status",
        ),
        CheckConstraint(
            "plan IS NULL OR plan IN ('trial', 'individual', 'family')",
            name="ck_family_circles_plan",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    # Phase 2: plan is deliberately nullable for legacy/uninitialized circles.
    # New onboarding must select it before any seat-based visibility is exposed.
    plan: Mapped[str | None] = mapped_column(String(20), nullable=True)
    trial_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class CircleMembership(Base):
    __tablename__ = "circle_memberships"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'co_admin', 'adult_member', 'minor')",
            name="ck_circle_memberships_role",
        ),
        CheckConstraint(
            "status IN ('active', 'left', 'removed')",
            name="ck_circle_memberships_status",
        ),
        CheckConstraint(
            "seat IS NULL OR seat IN ('protected', 'guardian', 'member')",
            name="ck_circle_memberships_seat",
        ),
        # D6: a person may belong to only one active Family Circle.
        Index(
            "uq_circle_membership_one_active_circle_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        # D10 default / T19: at most one active Co-Admin.
        Index(
            "uq_circle_membership_one_active_co_admin",
            "circle_id",
            unique=True,
            postgresql_where=text("status = 'active' AND role = 'co_admin'"),
        ),
        # D8/D3: exactly one Owner is created by the service; this DB index
        # prevents a second active owner from being added later.
        Index(
            "uq_circle_membership_one_active_owner",
            "circle_id",
            unique=True,
            postgresql_where=text("status = 'active' AND role = 'owner'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    circle_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("family_circles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    # Phase 2: seat is independent from role and determines tracking/visibility.
    # Nullable only for legacy/uninitialized Phase 1B rows.
    seat: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FamilyTrialClaim(Base):
    """One-trial-per-phone AND one-trial-per-device server authority.

    Only SHA-256 fingerprints are persisted; raw phone/device values are never
    stored in this table.
    """

    __tablename__ = "family_trial_claims"
    __table_args__ = (
        Index("uq_family_trial_claim_phone", "phone_fingerprint", unique=True),
        Index("uq_family_trial_claim_device", "device_fingerprint", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    circle_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("family_circles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phone_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    device_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
