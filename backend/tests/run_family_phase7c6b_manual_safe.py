from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FILES = [
    "app/api/behavioral.py",
    "app/api/sensors.py",
    "app/api/guardian_dashboard.py",
    "app/services/guardian_dashboard_engine.py",
    "app/api/guardian_network.py",
    "app/api/guardian_ai.py",
    "app/api/voice_trigger.py",
    "app/api/zones.py",
    "app/api/safe_route.py",
    "app/api/guardian.py",
    "app/api/route_monitor.py",
    "app/api/ai_services.py",
    "app/services/protected_behavior_advisory.py",
    "app/services/geofence_alerts.py",
    "app/services/emergency_engine.py",
    "app/api/stream.py",
]

checks: list[tuple[str, bool]] = []

def add(name: str, condition: bool) -> None:
    checks.append((name, bool(condition)))

sources: dict[str, str] = {}
for rel in FILES:
    path = ROOT / rel
    src = path.read_text(encoding="utf-8")
    sources[rel] = src
    ast.parse(src, filename=str(path))
    add(f"syntax:{rel}", True)

b = sources["app/api/behavioral.py"]
add("F01 behavioral subject helper", "_require_behavioral_subject_access" in b)
add("F01 baseline authenticated", "user: User = Depends(get_current_user)" in b[b.index("async def get_baseline"):b.index("@router.get(\"/anomalies")])
add("F01 anomaly authenticated", "user: User = Depends(get_current_user)" in b[b.index("async def list_anomalies"):b.index("@router.get(\"/metrics")])
add("F01 baseline guard before DB read", b.index("await _require_behavioral_subject_access", b.index("async def get_baseline")) < b.index("SELECT zone_affinity", b.index("async def get_baseline")))
add("F01 anomaly guard before DB read", b.index("await _require_behavioral_subject_access", b.index("async def list_anomalies")) < b.index("SELECT id, anomaly_type", b.index("async def list_anomalies")))
add("F01 staff diagnostics", b.count("Depends(_staff_behavioral)") >= 4)

s = sources["app/api/sensors.py"]
add("F22 event owner/staff helper", "_require_event_owner_or_staff" in s)
add("F22 fall guard before auto SOS", s.index("_require_event_owner_or_staff", s.index("async def auto_sos")) < s.index("trigger_auto_sos(session", s.index("async def auto_sos")))
add("F22 voice GET guard", s.index("_require_event_owner_or_staff", s.index("async def get_voice_verification")) < s.index("get_verification_status(session", s.index("async def get_voice_verification")))
add("F22 voice reverify guard", s.index("_require_event_owner_or_staff", s.index("async def re_verify_voice_event")) < s.index("verify_voice_event(session", s.index("async def re_verify_voice_event")))
add("F16 wandering canonical location", "ACTION_PRODUCE_LOCATION" in s[s.index("async def check_wandering"):s.index("async def resolve_wandering")])

gd = sources["app/api/guardian_dashboard.py"]
add("F07 canonical peer journey management", "ACTION_MANAGE_OTHER_SAFETY" in gd and "target_user_id=journey.user_id" in gd)


gde = sources["app/services/guardian_dashboard_engine.py"]
add("F08 dashboard purpose scope helper", "_purpose_scope_sets" in gde and "ACTION_VIEW_AI_PROFILE" in gde and "ACTION_VIEW_ACTIVITY" in gde and "ACTION_VIEW_WEARABLE" in gde)
add("F08 dashboard actual location logging", "record_disclosure=True" in gde and "location_type in {\"recent\", \"historical\"}" in gde)
add("F08 active sessions require location+activity", "ACTION_VIEW_ACTIVITY" in gde[gde.index("async def get_active_sessions"):gde.index("async def get_alerts")])
add("F09 canonical alert audience", "alert_recipient_ids" in gde[gde.index("async def get_alerts"):gde.index("async def get_session_history")])
add("F09 alert purpose redaction", "ACTION_VIEW_LOCATION_HISTORY" in gde[gde.index("async def get_alerts"):gde.index("async def get_session_history")] and "ACTION_VIEW_AI_PROFILE" in gde[gde.index("async def get_alerts"):gde.index("async def get_session_history")])

gn = sources["app/api/guardian_network.py"]
add("F20 legacy network mutation isolation", "_require_legacy_network_management" in gn and gn.count("await _require_legacy_network_management(session, user)") >= 6)
add("F20 stale legacy inviter isolation", "_require_legacy_inviter" in gn and "await _require_legacy_inviter(session, invite.inviter_user_id)" in gn)

ga = sources["app/api/guardian_ai.py"]
add("F13 AI canonical helper", "_require_ai_authority" in ga and "ACTION_PRODUCE_AI_PROFILE" in ga)
add("F13 AI routes gated", ga.count("await _require_ai_authority(session, user)") >= 6)

vt = sources["app/api/voice_trigger.py"]
add("F14 voice canonical helper", "_require_voice_authority" in vt and "ACTION_PRODUCE_VOICE_DISTRESS" in vt)
add("F14 voice routes gated", vt.count("await _require_voice_authority(session, user)") >= 6)

z = sources["app/api/zones.py"]
add("F16 zones own-safety helper", "_require_own_safety_authority" in z and "ACTION_MANAGE_OWN_SAFETY" in z)
add("F16 zone routes gated", z.count("await _require_own_safety_authority(session, user)") >= 3)

sr = sources["app/api/safe_route.py"]
add("F17 safe-route entitlement boundary", "ACTION_MANAGE_OWN_SAFETY" in sr and "Family Circle Safe Route authority denied" in sr)

g = sources["app/api/guardian.py"]
add("F18 journey requires location+activity", g.count("ACTION_PRODUCE_ACTIVITY, ACTION_PRODUCE_LOCATION") >= 2 and g.count("for action in (ACTION_PRODUCE_ACTIVITY, ACTION_PRODUCE_LOCATION)") >= 2)
add("F20 legacy Guardian contact isolation", "_require_legacy_guardian_contact_management" in g and g.count("await _require_legacy_guardian_contact_management(session, user)") >= 2)

rm = sources["app/api/route_monitor.py"]
add("F18 route-monitor requires location+activity", rm.count("for action in (ACTION_PRODUCE_ACTIVITY, ACTION_PRODUCE_LOCATION)") >= 2)

ai = sources["app/api/ai_services.py"]
summary = ai[ai.index("async def get_protected_behavior_summary_api"):]
add("F11 behavioral summary uses AI purpose", "ACTION_VIEW_AI_PROFILE" in summary and "runtime_decision" in summary)

pba = sources["app/services/protected_behavior_advisory.py"]
add("F12 worker producer recheck", "ACTION_PRODUCE_AI_PROFILE" in pba and "eligibility = await runtime_decision" in pba)
add("F12 advisory recipient AI recheck", "ACTION_VIEW_AI_PROFILE" in pba and "allowed_guardians" in pba)

geo = sources["app/services/geofence_alerts.py"]
resolver = geo[geo.index("async def _resolve_guardian_ids"):geo.index("def invalidate_guardian_cache")]
add("F19 canonical recipients before legacy cache", resolver.index("location_recipient_ids") < resolver.index('get_json("geofence:guardians"'))

em = sources["app/services/emergency_engine.py"]
fast = em[em.index("async def _resolve_fast_guardians_v64"):em.index("async def _guardian_realtime_after_response_v64")]
add("F21 first SOS fanout canonical-first", "app.services.alert_trigger import _resolve_guardian_ids_fast" in fast)

st = sources["app/api/stream.py"]
family = st[st.index("async def _family_event_allowed"):st.index("async def get_user_from_token")]
add("F21 emergency SSE recipient reauth", "alert_recipient_ids" in family and 'event_type in {"emergency_triggered", "emergency_location_update"}' in family)

failed = [name for name, ok in checks if not ok]
for name, ok in checks:
    print(f"{'PASS' if ok else 'FAIL'} | {name}")

print("-" * 72)
print(f"PHASE 7C-6B MANUAL SOURCE CONTRACTS: {len(checks)-len(failed)}/{len(checks)} PASS")
if failed:
    raise SystemExit("FAILED: " + ", ".join(failed))
