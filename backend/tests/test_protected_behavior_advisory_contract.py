"""Source-level launch contracts for Protected Behavioral Advisory V1.

These tests intentionally avoid importing the application or touching a DB.
They lock the no-regression architecture: background-only observation,
protected-user identity, authorized parent read, and advisory-only delivery.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GEOFENCE = (ROOT / "backend/app/api/geofence.py").read_text(encoding="utf-8")
AI = (ROOT / "backend/app/api/ai_services.py").read_text(encoding="utf-8")
SERVICE = (ROOT / "backend/app/services/protected_behavior_advisory.py").read_text(encoding="utf-8")


def require(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def test_geofence_hook_is_post_core_and_background_only() -> None:
    core_commit = GEOFENCE.index("await session.commit()", GEOFENCE.index("telemetry = await record_protected_telemetry"))
    hook = GEOFENCE.index("background_tasks.add_task(", core_commit)
    availability = GEOFENCE.index("from app.services.location_availability", hook)
    require(core_commit < hook < availability, "behavior learner must be scheduled only after durable core commit")
    require("record_protected_behavior_observation" in GEOFENCE, "missing protected behavior hook")


def test_existing_location_owner_remains_authoritative() -> None:
    require("telemetry = await record_protected_telemetry(" in GEOFENCE, "canonical protected telemetry call changed/missing")
    require("evaluate_user_location(" in GEOFENCE, "geofence evaluation changed/missing")
    require("_run_environmental_hazard_background" in GEOFENCE, "environmental background path changed/missing")


def test_summary_is_authenticated_and_family_authorized() -> None:
    require('@router.get("/protected-behavior-summary")' in AI, "summary route missing")
    require("user: User = Depends(get_current_user)" in AI, "summary route must authenticate")
    require("await _can_view_safety(session, user, user_id)" in AI, "summary route must reuse Guardian/Co-Guardian authorization")


def test_service_is_protected_user_based_and_isolated() -> None:
    for role in ("child", "women", "senior", "familymember", "family"):
        require(f'"{role}"' in SERVICE, f"protected role missing: {role}")
    require("REFERENCES users(id) ON DELETE CASCADE" in SERVICE, "behavioral data must be user-owned and cascade on erasure")
    require("protected_behavior_observations" in SERVICE, "isolated observations table missing")
    require("protected_behavior_profiles" in SERVICE, "isolated profiles table missing")
    require("protected_behavior_advisories" in SERVICE, "isolated advisory ledger missing")




def test_launch_feature_gates_default_off() -> None:
    require('FEATURE_ENV = "PROTECTED_BEHAVIOR_ADVISORY_ENABLED"' in SERVICE, "engine feature gate missing")
    require('NOTIFICATIONS_ENV = "PROTECTED_BEHAVIOR_NOTIFICATIONS_ENABLED"' in SERVICE, "notification feature gate missing")
    require('os.environ.get(FEATURE_ENV, "false")' in SERVICE, "engine must default disabled")
    require('os.environ.get(NOTIFICATIONS_ENV, "false")' in SERVICE, "notifications must default disabled")

def test_no_emergency_authority_is_added() -> None:
    require("trigger_alert(" not in SERVICE, "behavioral advisory must not call trigger_alert")
    require("dispatch_guardian_alert(" not in SERVICE, "behavioral advisory must not enter GuardianAlert escalation")
    require("from app.models.guardian import GuardianAlert" not in SERVICE, "behavioral advisory must not import GuardianAlert")
    require('"advisory_only": True' in SERVICE, "SSE payload must identify advisory-only behavior")
    require('"advisory_only": "true"' in SERVICE, "FCM payload must identify advisory-only behavior")
    require('"safety_alert"' in SERVICE, "must reuse existing non-emergency SSE event family")
    require("louder=False" in SERVICE, "behavioral push must never use louder/siren mode")


def test_guardian_and_coguardian_fanout_reuses_existing_resolver() -> None:
    require("from app.services.geofence_alerts import _resolve_guardian_ids" in SERVICE, "must reuse established family recipient resolution")
    require("get_users_push_tokens" in SERVICE, "ordinary closed-app push path missing")


def test_truthful_cold_start() -> None:
    require('state="learning"' in SERVICE, "learning state missing")
    require("MIN_DISTINCT_DAYS = 3" in SERVICE, "multi-day maturity gate missing")
    require("MIN_OBSERVATIONS = 36" in SERVICE, "observation maturity gate missing")
    require("No anomaly" not in SERVICE, "absence of anomaly must not be presented as normal")


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS: {test.__name__}")
    print(f"PASS: {len(tests)} protected behavioral advisory contracts")


if __name__ == "__main__":
    main()
