# Synthetic Telemetry Seeder Schemas
# Multi-metric pattern abstraction for future-proof simulation
from typing import Optional, Literal
from pydantic import BaseModel, field_validator


class AnomalyPhase(BaseModel):
    """Defines when anomalous behavior begins within the simulation window."""
    start_at_minute: int
    rate_per_minute: float  # Aggressive rate during anomaly (e.g., -2.0 for fast drain)

    @field_validator("start_at_minute")
    @classmethod
    def validate_start(cls, v):
        if v < 0:
            raise ValueError("start_at_minute must be >= 0")
        return v


class MetricPattern(BaseModel):
    """
    Pattern for simulating a single metric over time.
    Supports: battery_level, signal_strength (extensible).
    """
    metric: Literal["battery_level", "signal_strength"]
    start_value: float
    normal_rate_per_minute: float  # Change per minute in normal phase (e.g., -0.1)
    anomaly: Optional[AnomalyPhase] = None

    @field_validator("start_value")
    @classmethod
    def validate_start_value(cls, v):
        if v < -200 or v > 200:
            raise ValueError("start_value must be between -200 and 200")
        return v


class GapPattern(BaseModel):
    """
    Simulate heartbeat gaps to trigger reboot anomaly detection.
    No heartbeats are emitted during the gap window.
    """
    start_at_minute: int
    duration_minutes: int

    @field_validator("start_at_minute")
    @classmethod
    def validate_gap_start(cls, v):
        if v < 0:
            raise ValueError("start_at_minute must be >= 0")
        return v

    @field_validator("duration_minutes")
    @classmethod
    def validate_gap_duration(cls, v):
        if v < 1:
            raise ValueError("duration_minutes must be >= 1")
        return v


class HeartbeatSeedRequest(BaseModel):
    device_identifier: str
    duration_minutes: int = 60
    interval_seconds: int = 60
    metric_patterns: list[MetricPattern] = []
    gap_patterns: list[GapPattern] = []
    random_seed: Optional[int] = None
    noise_percent: float = 2.0  # Random noise as % of current value
    trigger_evaluation: bool = True  # Run baseline + anomaly detection after seeding

    @field_validator("duration_minutes")
    @classmethod
    def validate_duration(cls, v):
        if v < 1 or v > 1440:
            raise ValueError("duration_minutes must be between 1 and 1440 (24h)")
        return v

    @field_validator("interval_seconds")
    @classmethod
    def validate_interval(cls, v):
        if v < 10 or v > 600:
            raise ValueError("interval_seconds must be between 10 and 600")
        return v

    @field_validator("noise_percent")
    @classmethod
    def validate_noise(cls, v):
        if v < 0 or v > 50:
            raise ValueError("noise_percent must be between 0 and 50")
        return v


class HeartbeatSeedResponse(BaseModel):
    simulation_run_id: str
    device_identifier: str
    records_created: int
    records_skipped_by_gaps: int
    duration_minutes: int
    time_range_start: str
    time_range_end: str
    metrics_seeded: list[str]
    anomaly_evaluation_triggered: bool
    baselines_updated: Optional[dict] = None
    anomalies_detected: Optional[int] = None


# ── Fleet Simulation Schemas ──

class DevicePattern(BaseModel):
    """Per-device configuration for fleet simulation."""
    device_identifier: str
    metric_patterns: list[MetricPattern] = []
    gap_patterns: list[GapPattern] = []


class FleetSimulationRequest(BaseModel):
    device_patterns: list[DevicePattern]
    duration_minutes: int = 60
    interval_seconds: int = 60
    random_seed: Optional[int] = None
    noise_percent: float = 2.0
    trigger_evaluation: bool = True

    @field_validator("duration_minutes")
    @classmethod
    def validate_duration(cls, v):
        if v < 1 or v > 1440:
            raise ValueError("duration_minutes must be between 1 and 1440 (24h)")
        return v

    @field_validator("interval_seconds")
    @classmethod
    def validate_interval(cls, v):
        if v < 10 or v > 600:
            raise ValueError("interval_seconds must be between 10 and 600")
        return v

    @field_validator("noise_percent")
    @classmethod
    def validate_noise(cls, v):
        if v < 0 or v > 50:
            raise ValueError("noise_percent must be between 0 and 50")
        return v

    @field_validator("device_patterns")
    @classmethod
    def validate_at_least_one(cls, v):
        if len(v) < 1:
            raise ValueError("At least one device_pattern is required")
        if len(v) > 50:
            raise ValueError("Maximum 50 devices per fleet simulation")
        return v


class DeviceSeedResult(BaseModel):
    device_identifier: str
    records_created: int
    records_skipped_by_gaps: int
    metrics_seeded: list[str]


class AnomalyHistogramBucket(BaseModel):
    range_label: str  # e.g. "0-25", "25-50", "50-75", "75-100"
    count: int


class FleetSimulationResponse(BaseModel):
    simulation_run_id: str
    total_devices_affected: int
    total_records_created: int
    total_records_skipped: int
    duration_minutes: int
    time_range_start: str
    time_range_end: str
    db_write_volume: int  # total rows written (telemetry + anomalies)
    scheduler_execution_ms: Optional[int] = None
    anomalies_triggered: int
    baselines_updated: Optional[dict] = None
    anomaly_distribution: list[AnomalyHistogramBucket]
    per_device_results: list[DeviceSeedResult]
    anomaly_details: list[dict]
