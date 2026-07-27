# Centralized Configuration via Pydantic Settings
from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Application ──
    app_name: str = "nischint"
    app_env: str = "dev"

    # ── JWT ──
    jwt_secret: str = "nischint_jwt_secret_key_prod_2026"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60
    family_invite_ttl_minutes: int = Field(default=15, ge=1, le=1440)

    # ── Database (Neon PostgreSQL) ──
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/nischint"

    # ── MongoDB (legacy status checks) ──
    mongo_url: str = "mongodb://localhost:27017"
    db_name: str = "nischint"

    # ── CORS ──
    cors_origins: str = "*"

    # ── SSE ──
    sse_ping_interval: int = 15

    # ── AWS SES ──
    aws_region: str = "ap-south-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    ses_from_email: str = ""
    email_provider: str = "stub"

    # ── Twilio SMS ──
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    sms_provider: str = "stub"

    # ── Firebase (FCM Push) ──
    firebase_sa_key_path: str = ""
    firebase_sa_key_json: str = ""
    firebase_project_id: str = "nischint-5f248"
    firebase_private_key: str = ""
    firebase_client_email: str = ""
    push_provider: str = "stub"

    # ── Escalation Thresholds (minutes) ──
    escalation_l1_minutes: int = 2
    escalation_l2_minutes: int = 5
    escalation_l3_minutes: int = 10
    escalation_check_interval: int = 60

    # ── NISCH-006: Safety Incident Lifecycle (minutes) ──
    # Auto-resolve an ESCALATED incident with no ACK after N min
    # (operator/guardian unreachable — incident still gets a terminal
    # close, surfaced to ops dashboards via the timeline).
    safety_incident_escalated_resolve_minutes: int = 30
    # Auto-resolve an ACKNOWLEDGED incident idle for N min — guardian
    # ACK'd, but no explicit resolve. Defaults to 30 per Sprint 2 spec.
    safety_incident_acknowledged_resolve_minutes: int = 30
    # ARCHIVE a RESOLVED incident after M min — keeps the recent
    # operational tail hot, ages historical incidents into archive.
    safety_incident_resolved_archive_minutes: int = 30
    # How often the lifecycle sweeper runs (seconds).
    safety_incident_lifecycle_interval_seconds: int = 60

    # ── Device Offline Detection ──
    device_offline_threshold_minutes: int = 10
    device_offline_cooldown_minutes: int = 15

    # ── Health Rule: Low Battery ──
    rule_low_battery_enabled: bool = True
    low_battery_threshold_percent: int = 20
    low_battery_sustain_minutes: int = 10
    low_battery_cooldown_minutes: int = 60
    low_battery_recovery_buffer_percent: int = 5

    # ── Health Rule: Signal Degradation ──
    rule_signal_degradation_enabled: bool = True
    signal_degradation_threshold_dbm: int = -80
    signal_degradation_sustain_minutes: int = 10
    signal_degradation_cooldown_minutes: int = 60
    signal_degradation_recovery_buffer_dbm: int = 5

    # ── Health Rule: Reboot Anomaly ──
    rule_reboot_anomaly_enabled: bool = True
    reboot_anomaly_max_reboots: int = 3
    reboot_anomaly_window_minutes: int = 60
    reboot_anomaly_cooldown_minutes: int = 120

    # ── Notification Worker ──
    worker_max_attempts: int = 5
    worker_batch_size: int = 20
    worker_poll_interval: int = 15
    worker_backoff_base: int = 30

    # ── AI Narrative Engine ──
    emergent_llm_key: str = ""

    # ── AWS Cognito ──
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    cognito_client_secret: str = ""

    # ── Google OAuth ──
    google_client_id: str = ""
    google_client_secret: str = ""

    # ── Redis Cache ──
    redis_url: str = ""

    # ── OSRM Routing ──
    osrm_url: str = ""

    # ── Blog ──
    blog_api_key: str = ""

    # ── OpenAI Embeddings (RAG) ──
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"

    # ── OpenWeather (Phase 4 environment risk) ──
    openweather_api_key: str = ""

    # ── Journey Engine Delivery Guard ──
    journey_live_delivery: bool = False          # False = simulator (logs only); True = real SMS/Push dispatch
    journey_max_sos_per_hour: int = 5            # Rate limit per session_id
    journey_require_verified_user: bool = False  # If True, only verified users trigger real delivery
    journey_mongo_enabled: bool = True           # Persist to Mongo (falls back to in-memory if false or client fails)

    model_config = {
        "env_file": str(Path(__file__).resolve().parent.parent.parent / ".env"),
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
