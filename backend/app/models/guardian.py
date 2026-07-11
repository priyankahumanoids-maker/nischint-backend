# Guardian Mode Models
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, JSON, ForeignKey, Text, Integer, Float, Boolean, BigInteger, Identity, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Guardian(Base):
    __tablename__ = "guardians"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    relationship: Mapped[str] = mapped_column(String(100), default="family", nullable=False)
    notification_pref: Mapped[dict] = mapped_column(type_=JSON, default=lambda: {"push": True, "sms": True, "email": True}, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class GuardianSession(Base):
    __tablename__ = "guardian_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    destination: Mapped[dict | None] = mapped_column(type_=JSON, nullable=True)
    route_points: Mapped[dict | None] = mapped_column(type_=JSON, nullable=True)
    current_location: Mapped[dict | None] = mapped_column(type_=JSON, nullable=True)
    previous_location: Mapped[dict | None] = mapped_column(type_=JSON, nullable=True)
    previous_update_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    zone_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    risk_level: Mapped[str] = mapped_column(String(20), default="SAFE", nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    zone_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    eta_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed_mps: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_distance_m: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    location_updates: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    escalation_level: Mapped[str] = mapped_column(String(20), default="none", nullable=False)
    is_night: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    route_deviated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    route_deviation_m: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_idle: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    idle_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idle_duration_s: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    alert_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_alert_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    safety_check_pending: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    safety_check_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Journey Intelligence (layered, Apr 28, 2026) ─────────────────
    # `guardian_sessions` is the SOLE lifecycle state owner — these
    # five columns live here, NOT in a parallel `journeys` table.
    # See /app/memory/SYSTEM_INVARIANTS.md.
    is_offline:           Mapped[bool] = mapped_column(default=False, nullable=False)
    last_seen_online_at:  Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_points:         Mapped[int]  = mapped_column(default=0, nullable=False)
    offline_gaps:         Mapped[int]  = mapped_column(default=0, nullable=False)
    max_gap_seconds:      Mapped[int]  = mapped_column(default=0, nullable=False)


class GuardianAlert(Base):
    __tablename__ = "guardian_alerts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # NULLABLE: session-less alerts (e.g. help-request when no active
    # journey) MUST still land here so the ACK engine can escalate and
    # the audit trail is complete. See migration ae1a2b3c4dt01.
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("guardian_sessions.id", ondelete="CASCADE"), nullable=True, index=True)
    # The child this alert is about. Always populated — never derived
    # from session at read time (sessions can be deleted, alerts can
    # outlive them).
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[dict | None] = mapped_column(type_=JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # ── ACK + escalation primitive (Control Layer phase 1) ───────────
    ack_required:    Mapped[bool] = mapped_column(default=False, nullable=False)
    ack_timeout_sec: Mapped[int | None] = mapped_column(nullable=True)
    # none | pending | acknowledged | escalated
    ack_status:      Mapped[str] = mapped_column(String(16), default="none", nullable=False)
    ack_deadline:    Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_by:        Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    acked_at:        Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalation_step:    Mapped[int]  = mapped_column(default=0, nullable=False)
    escalation_history: Mapped[list] = mapped_column(type_=JSON, default=list, nullable=False)

    # Immutable snapshot at mark_for_ack — context for every escalation.
    context_json:    Mapped[dict] = mapped_column(type_=JSON, default=dict, nullable=False)
    # Tri-state response depth: null | seen | acting | resolved | seen_lapsed.
    ack_type:        Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 60s window from `seen` to `acting` before a soft re-escalation.
    seen_deadline:   Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Liveness heartbeat once the guardian has committed to `acting`.
    # If this stays older than 30s, the engine fires `alert_acting_lapsed`.
    acting_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Anti-spam guard for the louder_push escalation step. The tick
    # runs every 5s; without this guard a single alert parked at
    # `escalated` could re-broadcast a critical-channel push every
    # tick. Only one louder_push within any 15s window.
    last_louder_push_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Same kind of guard for the automated_call (Twilio voice)
    # escalation step. Without this a parked `escalated` alert would
    # place a phone call every tick — burning real money and turning
    # the guardian's phone into an automation weapon. Only one call
    # within any 60s window per alert.
    last_automated_call_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class JourneyPoint(Base):
    """Append-only event log for a journey's GPS trail.
    Pure derivation source — not a state authority."""
    __tablename__ = "journey_points"

    id:        Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("guardian_sessions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id:   Mapped[uuid.UUID] = mapped_column(nullable=False)
    seq:       Mapped[int] = mapped_column(nullable=False)
    lat:       Mapped[float] = mapped_column(nullable=False)
    lng:       Mapped[float] = mapped_column(nullable=False)
    accuracy:  Mapped[float | None] = mapped_column(nullable=True)
    speed_mps: Mapped[float | None] = mapped_column(nullable=True)
    # good | unstable | offline
    quality:        Mapped[str] = mapped_column(String(16), default="good", nullable=False)
    gap_before_s:   Mapped[int | None] = mapped_column(nullable=True)
    gps_recorded_at:    Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    server_received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("session_id", "seq", name="uq_journey_points_session_seq"),
    )
