# City Risk Snapshot Model
# Persistent storage for heatmap snapshots — enables timeline, delta, and ML training.

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Float, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class CityRiskSnapshot(Base):
    __tablename__ = "city_risk_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    city_id = Column(String, nullable=False, default="default", index=True)
    snapshot_timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    total_cells = Column(Integer, nullable=False, default=0)
    total_zones = Column(Integer, nullable=False, default=0)
    total_incidents = Column(Integer, nullable=False, default=0)
    stats = Column(JSON, nullable=True)
    cells = Column(JSON, nullable=True)
    delta = Column(JSON, nullable=True)
    weights = Column(JSON, nullable=True)
    weight_profile = Column(String, nullable=True)
    bounds = Column(JSON, nullable=True)
    computation_time_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    def __repr__(self):
        return f"<CityRiskSnapshot {self.city_id} @ {self.snapshot_timestamp}>"
