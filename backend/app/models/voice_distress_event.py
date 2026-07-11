# Voice Distress Event Model
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Float, Boolean, ForeignKey, JSON, ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class VoiceDistressEvent(Base):
    __tablename__ = "voice_distress_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)

    # Detection signals
    keywords: Mapped[dict | None] = mapped_column(type_=JSON, nullable=True)  # ["help","stop"]
    scream_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    repeated_detection: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Audio features for ML training
    audio_features: Mapped[dict | None] = mapped_column(type_=JSON, nullable=True)
    # {amplitude, pitch_variance, spectral_spread, duration_ms}

    # Scoring
    distress_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)

    # Status
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    # active | auto_sos | resolved | false_positive
    resolved_by: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Linked emergency (if auto-SOS triggered)
    emergency_event_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    # Whisper verification (Phase 2)
    whisper_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    whisper_transcript: Mapped[str | None] = mapped_column(String(500), nullable=True)
    whisper_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    verification_status: Mapped[str] = mapped_column(String(20), default="none", nullable=False)
    # none | queued | processing | verified | failed
    distress_phrases_found: Mapped[dict | None] = mapped_column(type_=JSON, nullable=True)
    trigger_type: Mapped[str] = mapped_column(String(20), default="on_device", nullable=False)
    # on_device | manual | re_verify

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
