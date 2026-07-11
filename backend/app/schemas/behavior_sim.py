# Behavior Simulation Schemas
from typing import Optional
from pydantic import BaseModel, Field


SCENARIO_TYPES = [
    "prolonged_inactivity",
    "movement_drop",
    "routine_disruption",
    "location_wandering",
    "route_deviation",
]

SCENARIO_DESCRIPTIONS = {
    "prolonged_inactivity": "Senior stops responding — fall or unconsciousness scenario",
    "movement_drop": "Gradual decrease in movement — health deterioration",
    "routine_disruption": "Deviation from normal daily routine patterns",
    "location_wandering": "Unusually high erratic movement — elder wandering",
    "route_deviation": "Sudden change in location patterns — child safety concern",
}


class BehaviorScenario(BaseModel):
    scenario_type: str = Field(..., description="One of: prolonged_inactivity, movement_drop, routine_disruption, location_wandering, route_deviation")
    device_identifier: str
    duration_minutes: int = Field(120, ge=10, le=720, description="Simulation window in minutes")
    intensity: float = Field(0.7, ge=0.1, le=1.0, description="Peak behavior_risk_score severity")
    ramp_minutes: int = Field(30, ge=0, le=360, description="Time to ramp from baseline to peak intensity")


class BehaviorSimRequest(BaseModel):
    scenarios: list[BehaviorScenario] = Field(..., min_length=1, max_length=10)
    trigger_escalation: bool = Field(True, description="Run combined risk + escalation evaluation")
    step_interval_minutes: int = Field(5, ge=1, le=30, description="Timeline granularity")


class TimelineStep(BaseModel):
    minute: int
    behavior_score: float
    anomaly_type: str
    combined_risk_score: Optional[float] = None
    escalation_tier: Optional[str] = None
    escalation_reason: Optional[str] = None


class ScenarioResult(BaseModel):
    device_identifier: str
    scenario_type: str
    scenario_description: str
    duration_minutes: int
    intensity: float
    behavior_anomalies_created: int
    timeline: list[TimelineStep]
    peak_behavior_score: float
    peak_combined_score: Optional[float] = None
    final_escalation_tier: Optional[str] = None
    time_to_first_escalation_minutes: Optional[int] = None


class BehaviorSimResponse(BaseModel):
    simulation_run_id: str
    total_scenarios: int
    total_behavior_anomalies: int
    total_escalations: int
    scenario_results: list[ScenarioResult]
    is_simulated: bool = True
