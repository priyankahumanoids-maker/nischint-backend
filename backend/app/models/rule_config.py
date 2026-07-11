# Device Health Rule Config Model
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base


class DeviceHealthRuleConfig(Base):
    __tablename__ = "device_health_rule_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    rule_name = Column(String(100), unique=True, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    threshold_json = Column(JSONB, nullable=False)
    cooldown_minutes = Column(Integer, nullable=False, default=60)
    severity = Column(String(20), nullable=False, default="low")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<RuleConfig {self.rule_name} enabled={self.enabled}>"
