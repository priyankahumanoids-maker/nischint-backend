# Simulation Run Model — immutable audit log of every simulation execution
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SimulationRun(Base):
    __tablename__ = "simulation_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    simulation_run_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    run_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'single' | 'fleet'
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    summary_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    total_devices_affected: Mapped[int] = mapped_column(Integer, nullable=False)
    anomalies_triggered: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduler_execution_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    db_write_volume: Mapped[int] = mapped_column(Integer, nullable=False)
    executed_by_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True,
    )
