# Pydantic schemas for Device Health Rule management
from typing import Optional
from pydantic import BaseModel, field_validator, model_validator

VALID_SEVERITIES = {"low", "medium", "high"}

# Required keys per rule — anything else is rejected
RULE_THRESHOLD_KEYS: dict[str, set[str]] = {
    "low_battery": {"battery_percent", "sustain_minutes", "recovery_buffer"},
    "signal_degradation": {"signal_threshold", "sustain_minutes", "recovery_buffer_dbm"},
    "reboot_anomaly": {"gap_minutes", "gap_count", "window_minutes"},
    "combined_anomaly": {"weight_battery", "weight_signal", "weight_behavior", "trigger_threshold", "correlation_bonus", "persistence_minutes", "escalation_tiers", "instability_cooldown_minutes", "recovery_minutes", "recovery_buffer", "min_clear_cycles"},
}

KNOWN_RULE_NAMES = set(RULE_THRESHOLD_KEYS.keys())


class RuleUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    threshold_json: Optional[dict] = None
    cooldown_minutes: Optional[int] = None
    severity: Optional[str] = None

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v):
        if v is not None and v not in VALID_SEVERITIES:
            raise ValueError(f"severity must be one of: {', '.join(sorted(VALID_SEVERITIES))}")
        return v

    @field_validator("cooldown_minutes")
    @classmethod
    def validate_cooldown(cls, v):
        if v is not None and v < 1:
            raise ValueError("cooldown_minutes must be >= 1")
        return v


def validate_threshold_json(rule_name: str, threshold: dict):
    """Validate threshold_json keys against the rule's required schema."""
    required = RULE_THRESHOLD_KEYS.get(rule_name)
    if required is None:
        return  # unknown rule — caller handles this

    provided = set(threshold.keys())
    unknown = provided - required
    if unknown:
        raise ValueError(f"Unknown keys for '{rule_name}': {', '.join(sorted(unknown))}. Allowed: {', '.join(sorted(required))}")

    missing = required - provided
    if missing:
        raise ValueError(f"Missing required keys for '{rule_name}': {', '.join(sorted(missing))}. Required: {', '.join(sorted(required))}")

    # Validate weight ranges for combined_anomaly
    if rule_name == "combined_anomaly":
        for w_key in ("weight_battery", "weight_signal", "weight_behavior"):
            val = threshold.get(w_key, 0)
            if not isinstance(val, (int, float)) or val < 0 or val > 1:
                raise ValueError(f"{w_key} must be a number between 0 and 1")
        w_sum = round(threshold.get("weight_battery", 0) + threshold.get("weight_signal", 0) + threshold.get("weight_behavior", 0), 2)
        if abs(w_sum - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0 (currently {w_sum})")


class RuleToggleRequest(BaseModel):
    enabled: bool


class RuleSimulationRequest(BaseModel):
    enabled: bool
    threshold_json: dict
    cooldown_minutes: int
    severity: str

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v):
        if v not in VALID_SEVERITIES:
            raise ValueError(f"severity must be one of: {', '.join(sorted(VALID_SEVERITIES))}")
        return v

    @field_validator("cooldown_minutes")
    @classmethod
    def validate_cooldown(cls, v):
        if v < 1:
            raise ValueError("cooldown_minutes must be >= 1")
        return v


class MatchedDevice(BaseModel):
    device_identifier: str
    senior_name: str
    guardian_name: str | None = None


class RuleSimulationResponse(BaseModel):
    rule_name: str
    simulated_severity: str
    matched_devices_count: int
    total_devices_count: int
    evaluation_window_minutes: int
    would_escalate: bool
    matched_devices: list[MatchedDevice]


class RuleResponse(BaseModel):
    rule_name: str
    enabled: bool
    threshold_json: dict
    cooldown_minutes: int
    severity: str
    updated_at: Optional[str] = None
