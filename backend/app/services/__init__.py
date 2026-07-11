# Services package
from app.services.user_service import (
    create_user,
    get_user_by_email,
    get_user_by_id,
    hash_password,
    verify_password,
    verify_password_async,
    hash_password_async,
)
from app.services.senior_service import (
    create_senior,
    get_seniors_by_guardian,
    get_senior_by_id,
)
from app.services.device_service import (
    register_device,
    get_devices_by_senior,
)
from app.services.telemetry_service import (
    ingest_telemetry,
    get_telemetry_by_device,
)
from app.services.incident_service import (
    get_incidents_by_guardian,
    get_incident_by_id,
    acknowledge_incident,
    resolve_incident,
    mark_false_alarm,
)
from app.services.dashboard_service import (
    get_guardian_summary,
)
from app.services import notification_service

__all__ = [
    # User
    "create_user",
    "get_user_by_email",
    "get_user_by_id",
    "hash_password",
    "verify_password",
    "verify_password_async",
    "hash_password_async",
    # Senior
    "create_senior",
    "get_seniors_by_guardian",
    "get_senior_by_id",
    # Device
    "register_device",
    "get_devices_by_senior",
    # Telemetry
    "ingest_telemetry",
    "get_telemetry_by_device",
    # Incident
    "get_incidents_by_guardian",
    "get_incident_by_id",
    "acknowledge_incident",
    "resolve_incident",
    "mark_false_alarm",
    # Dashboard
    "get_guardian_summary",
    # Notification
    "notification_service",
]
