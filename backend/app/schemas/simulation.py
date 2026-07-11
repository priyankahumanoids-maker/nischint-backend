# Simulation Comparison Schemas
from typing import Optional
from pydantic import BaseModel, field_validator


class BatteryRuleThreshold(BaseModel):
    battery_percent: int
    sustain_minutes: int

    @field_validator("battery_percent")
    @classmethod
    def validate_percent(cls, v):
        if v < 1 or v > 100:
            raise ValueError("battery_percent must be between 1 and 100")
        return v

    @field_validator("sustain_minutes")
    @classmethod
    def validate_sustain(cls, v):
        if v < 1 or v > 1440:
            raise ValueError("sustain_minutes must be between 1 and 1440")
        return v


class BatteryCompareRequest(BaseModel):
    config_a: BatteryRuleThreshold
    config_b: BatteryRuleThreshold
    min_heartbeats: int = 2

    @field_validator("min_heartbeats")
    @classmethod
    def validate_min_hb(cls, v):
        if v < 1 or v > 100:
            raise ValueError("min_heartbeats must be between 1 and 100")
        return v


class CompareMatchedDevice(BaseModel):
    device_identifier: str
    senior_name: str
    guardian_name: Optional[str] = None


class ConfigResult(BaseModel):
    threshold: BatteryRuleThreshold
    matched_devices_count: int


class CompareDelta(BaseModel):
    newly_flagged_count: int
    no_longer_flagged_count: int
    intersection_count: int


class BatteryCompareResponse(BaseModel):
    metric: str
    evaluation_window_minutes: int
    min_heartbeats: int
    a: ConfigResult
    b: ConfigResult
    delta: CompareDelta
    newly_flagged_devices: list[CompareMatchedDevice]
    no_longer_flagged_devices: list[CompareMatchedDevice]
    matched_in_both: list[CompareMatchedDevice]
