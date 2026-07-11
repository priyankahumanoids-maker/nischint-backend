# Device Schemas
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DeviceCreate(BaseModel):
    """Schema for creating a new device."""
    device_identifier: str
    device_type: Optional[str] = None


class DeviceResponse(BaseModel):
    """Schema for device response."""
    id: UUID
    device_identifier: str
    device_type: Optional[str] = None
    status: str
    last_seen: Optional[datetime] = None
    senior_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
