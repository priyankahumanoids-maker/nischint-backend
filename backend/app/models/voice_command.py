# Voice Command Models — Config and trigger logs
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, Float
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class VoiceCommandConfig(Base):
    __tablename__ = "voice_command_configs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    phrase: Mapped[str] = mapped_column(String(200), nullable=False)
    linked_action: Mapped[str] = mapped_column(String(50), nullable=False)
    action_config: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_threshold: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False,
    )


class VoiceTriggerLog(Base):
    __tablename__ = "voice_trigger_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    command_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("voice_command_configs.id", ondelete="SET NULL"), nullable=True,
    )
    transcribed_text: Mapped[str] = mapped_column(Text, nullable=False)
    matched_phrase: Mapped[str | None] = mapped_column(String(200), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    linked_action: Mapped[str | None] = mapped_column(String(50), nullable=True)
    triggered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="processed", nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False,
    )
