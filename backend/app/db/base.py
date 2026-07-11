# Database Base Configuration
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy declarative base class."""
    pass


# Import all models here so Alembic can detect them
from app.models import user, senior, device, incident, notification, notification_job, rule_config, rule_audit, device_baseline, device_anomaly, guardian, city_risk_snapshot, fall_event, safe_zone, wandering_event, pickup_authorization, pickup_event, voice_distress_event, fake_call, fake_notification, sos, guardian_ai, guardian_network, relationship, system_incident, stream_recording_chunk, stream_session, stream_playback_audit, erasure_request, consent, safety_incident  # noqa: F401, E402
