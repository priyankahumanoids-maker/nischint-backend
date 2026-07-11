# Telemetry Schemas
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TelemetryCreate(BaseModel):
    """Schema for creating telemetry data. Accepts device_identifier (string) for IoT devices."""
    device_identifier: str
    metric_type: str
    metric_value: dict[str, Any] = {}
    # Heartbeat-specific optional fields
    battery_level: int | None = None
    signal_strength: int | None = None


class TelemetryResponse(BaseModel):
    """Schema for telemetry response."""
    id: UUID
    device_id: UUID
    metric_type: str
    metric_value: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
