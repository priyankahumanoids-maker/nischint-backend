# Device Health Rule Audit Log Model
from uuid import uuid4

from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base


class DeviceHealthRuleAuditLog(Base):
    __tablename__ = "device_health_rule_audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    rule_name = Column(String(100), nullable=False)
    changed_by = Column(UUID(as_uuid=True), nullable=False)
    changed_by_name = Column(String(150))
    change_type = Column(String(20), nullable=False)
    old_config = Column(JSONB, nullable=False)
    new_config = Column(JSONB, nullable=False)
    ip_address = Column(String(45))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
