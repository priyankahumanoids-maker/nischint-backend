# Incident Schemas
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class IncidentCreate(BaseModel):
    """Schema for creating an incident."""
    senior_id: UUID
    device_id: UUID
    incident_type: str
    severity: str


class IncidentResponse(BaseModel):
    """Schema for incident response."""
    id: UUID
    senior_id: UUID
    device_id: UUID
    incident_type: str
    severity: str
    status: str
    escalation_minutes: int
    escalated: bool
    escalated_at: Optional[datetime] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
    acknowledged_by_user_id: Optional[UUID] = None
    acknowledged_at: Optional[datetime] = None
    acknowledged_via: Optional[str] = None
    escalation_level: int = 1
    level2_escalated_at: Optional[datetime] = None
    level3_escalated_at: Optional[datetime] = None
    assigned_to_user_id: Optional[UUID] = None
    assigned_at: Optional[datetime] = None
    assigned_by_user_id: Optional[UUID] = None
    is_test: bool = False

    model_config = ConfigDict(from_attributes=True)
