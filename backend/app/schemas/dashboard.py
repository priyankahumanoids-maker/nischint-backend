# Dashboard Schemas
from pydantic import BaseModel


class GuardianSummary(BaseModel):
    """Guardian dashboard summary."""
    total_seniors: int
    total_devices: int
    active_incidents: int
    critical_incidents: int
    devices_online: int
    devices_offline: int
