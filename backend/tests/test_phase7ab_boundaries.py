import ast
import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_migration_graph_unique_and_complete():
    revisions = {}
    for path in (ROOT / "migrations/versions").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        values = {}
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id in {"revision", "down_revision"}:
                values[node.target.id] = ast.literal_eval(node.value)
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                        values[target.id] = ast.literal_eval(node.value)
        if "revision" not in values:
            continue
        assert values["revision"] not in revisions, path.name
        revisions[values["revision"]] = values.get("down_revision")
    for child, parents in revisions.items():
        for parent in parents if isinstance(parents, tuple) else (parents,):
            assert parent is None or parent in revisions, (child, parent)
    assert revisions["fc07_schema_compat"] == "fc06_family_entitlement_lifecycle_audit"
    assert revisions["aa1a2b3c4dp02"] == "aa1a2b3c4dp01"


def test_version_storage_and_audit_conflict_compatibility():
    env = (ROOT / "migrations/env.py").read_text()
    assert "ALTER COLUMN version_num TYPE TEXT" in env
    assert env.index("connection.execute(text(statement))") < env.index("context.configure(connection=")
    assert env.index("connection.execute(text(AMBIGUOUS_ACK_DDL))") < env.index("context.configure(connection=")
    assert "version_num IN ('aa1a2b3c4dp01','aa1a2b3c4dp02')" in env
    assert "ADD COLUMN IF NOT EXISTS ack_type VARCHAR(16)" in env
    ddl = (ROOT / "app/migrations/fc06_family_entitlement_lifecycle_audit.py").read_text()
    assert "uq_family_audit_event_key_all ON family_circle_audit_log(event_key);" in ddl
    audit = (ROOT / "app/services/family_circle_audit_service.py").read_text()
    assert "ON CONFLICT (event_key) WHERE event_key IS NOT NULL DO NOTHING" in audit
    assert "from app.db.session import engine" not in ddl.split("async def ensure_")[0]


@pytest.mark.parametrize("activity,history,ai", [(False, False, False), (True, False, False), (True, True, False), (True, True, True)])
def test_location_disclosure_field_purposes(activity, history, ai):
    from app.services.family_location_disclosure import filter_live_status, has_coordinates
    source = {"session": {"current_location": {"lat": 20, "lng": 70}, "risk_score": 90,
                          "speed_kmh": 10, "route_points": [{"lat": 20, "lng": 70}]},
              "risk": {"score": 90}, "behavior_pattern": "Deviating", "recommendation": "check in",
              "recent_alerts": [{"location": {"lat": 20, "lng": 70}, "message": "inferred risk"}],
              "past_sessions": [{"risk_level": "RED", "distance_m": 20}]}
    result = filter_live_status(source, activity=activity, history=history, ai=ai)
    assert has_coordinates(result["session"]["current_location"])
    if not ai:
        assert result["risk"] is None and result["behavior_pattern"] is None
        assert "risk_score" not in result["session"]
    if not activity:
        assert "speed_kmh" not in result["session"]
    if not history:
        assert "route_points" not in result["session"]
    assert bool(result["recent_alerts"]) == (activity and history and ai)
    assert source["risk"]["score"] == 90  # never mutate a shared response


def test_only_actual_coordinate_disclosures():
    from app.services.family_location_disclosure import has_coordinates
    assert not has_coordinates({"allowed": True, "lat": None, "lng": None})
    assert not has_coordinates({"lat": float("nan"), "lng": 20})
    assert has_coordinates({"location": {"latitude": 0, "longitude": 0}})


class Rows:
    def __init__(self, row=None): self.row = row
    def mappings(self): return self
    def first(self): return self.row
    def scalars(self): return self
    def all(self): return []
    def scalar_one_or_none(self): return None


@pytest.mark.parametrize("successful,tokens,expected", [(0, ["a"], 0), (1, ["a"], 1), (1, ["a", "b"], 1), (0, [], 0)])
@pytest.mark.parametrize("event_type", ["family_sharing_paused", "family_sharing_resumed", "family_member_left", "family_member_removed", "family_plan_downgrade"])
def test_outbox_zero_and_partial_delivery(monkeypatch, successful, tokens, expected, event_type):
    from app.services.family_circle_notification_outbox import deliver_outbox_notifications
    writes = []
    class DB:
        async def execute(self, stmt, params=None):
            sql = str(stmt)
            if "SELECT id, recipient" in sql:
                return Rows(dict(id="entry", recipient_user_id="00000000-0000-0000-0000-000000000001",
                                 delivered_at=None, attempts=0, event_type=event_type,
                                 title="Sharing update", body="Name paused", payload_json={}))
            writes.append((sql, params))
            return Rows()
    push = types.ModuleType("app.services.push_service")
    async def get_tokens(*a, **kw): return tokens
    async def send(*a, **kw): return successful
    push.get_users_push_tokens = get_tokens
    push.send_push_to_tokens = send
    monkeypatch.setitem(sys.modules, "app.services.push_service", push)
    result = asyncio.run(deliver_outbox_notifications(DB(), outbox_ids=["entry"]))
    assert result == {"delivered": expected, "pending": 1 - expected}
    assert any("delivered_at=NOW()" in sql for sql, _ in writes) == bool(expected)
    if not expected:
        assert any("next_attempt_at" in sql for sql, _ in writes)
    elif successful < len(tokens):
        assert writes[-1][1]["partial"] == "partial_device_delivery"


def test_outbox_retry_is_bounded_and_postcommit():
    source = (ROOT / "app/services/family_circle_notification_outbox.py").read_text()
    assert "attempts < 8" in source and "LIMIT 25 FOR UPDATE SKIP LOCKED" in source
    assert "next_attempt_at <= NOW()" in source
    worker = (ROOT / "app/services/notification_worker.py").read_text()
    assert "async with async_session() as family_session" in worker
    assert "await family_session.commit()" in worker


@pytest.mark.parametrize("state,allow", [("active", True), ("active", False), ("former", False), ("invalid", False)])
def test_canonical_wearable_never_reads_legacy(monkeypatch, state, allow):
    from app.services import subscription_service as service
    from app.services import family_circle_runtime_authority as authority
    async def membership(*a, **kw): return state
    async def snapshot(*a, **kw):
        return {"canonical": True, "entitlement": "active" if state == "active" else "lifeline",
                "plan": "individual", "can_produce_wearable": allow}
    monkeypatch.setattr(authority, "canonical_membership_state", membership)
    monkeypatch.setattr(authority, "runtime_snapshot", snapshot)
    class NoLegacy:
        async def execute(self, *a, **kw): raise AssertionError("Legacy SQL used by canonical member")
    result = asyncio.run(service.member_subscription(NoLegacy(), "member"))
    assert result["canonical"] is True
    assert result["entitlements"]["wearable"] is allow
    assert result["price_monthly"] == 299


def test_test_activation_is_disabled_before_database_access():
    from app.services import subscription_service as service
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        asyncio.run(service.activate_test_subscription(None, None, "premium"))
    assert error.value.status_code == 410


def test_emergency_logging_does_not_block_delivery():
    source = (ROOT / "app/api/stream.py").read_text()
    assert '"emergency_location_update"' in source
    assert "asyncio.create_task(bounded_audit())" in source
    assert "timeout=3" in source and "len(_disclosure_tasks) < 128" in source
    assert "str(target) != str(viewer.id)" in source
    assert "yield _encode_event(viewer, event)" in source


def _stream_functions():
    # Execute the real functions without importing API configuration, secrets,
    # broadcaster startup, or a database engine.
    source = ast.parse((ROOT / "app/api/stream.py").read_text())
    names = {"_family_event_allowed", "_encode_event"}
    nodes = [n for n in source.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    tree = ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[]))
    import json
    namespace = {"asyncio": asyncio, "json": json, "_disclosure_tasks": set(),
                 "logger": SimpleNamespace(warning=lambda *a: None, error=lambda *a: None)}
    exec(compile(tree, "<real stream functions>", "exec"), namespace)
    return namespace


@pytest.mark.parametrize("payload,expected_log", [({"allowed": True}, False), ({"lat": 20, "lng": 70}, True)])
def test_sse_logs_coordinates_not_permission_probes(monkeypatch, payload, expected_log):
    from app.services import family_circle_runtime_authority as authority
    calls = []
    async def decision(*a, **kw):
        calls.append(kw)
        return SimpleNamespace(canonical=True, allowed=True)
    monkeypatch.setattr(authority, "runtime_decision", decision)
    class DB:
        async def commit(self): pass
        async def rollback(self): raise AssertionError("unexpected rollback")
    ns = _stream_functions()
    event = {"type": "location_update", "data": {"user_id": "target", **payload}}
    assert asyncio.run(ns["_family_event_allowed"](DB(), SimpleNamespace(id="viewer"), event))
    assert calls[0]["record_disclosure"] is False
    assert any(call.get("record_disclosure") for call in calls) is expected_log


@pytest.mark.parametrize("history_allowed", [False, True])
def test_sse_redacted_history_is_not_logged_as_live(monkeypatch, history_allowed):
    from app.services import family_circle_runtime_authority as authority
    from app.core.family_circle_permissions import ACTION_VIEW_LOCATION_HISTORY
    calls = []
    async def decision(*a, **kw):
        calls.append(kw)
        return SimpleNamespace(canonical=True,
            allowed=history_allowed if kw["action"] == ACTION_VIEW_LOCATION_HISTORY else True)
    monkeypatch.setattr(authority, "runtime_decision", decision)
    class DB:
        async def commit(self): pass
        async def rollback(self): raise AssertionError("unexpected rollback")
    event = {"type": "location_update", "data": {"user_id": "target", "route_points": [{"lat": 20, "lng": 70}]}}
    assert asyncio.run(_stream_functions()["_family_event_allowed"](DB(), SimpleNamespace(id="viewer"), event))
    logged = [call["action"] for call in calls if call.get("record_disclosure")]
    assert logged == ([ACTION_VIEW_LOCATION_HISTORY] if history_allowed else [])
    assert ("route_points" in event["data"]) is history_allowed


def test_emergency_sse_delivery_survives_audit_failure_and_excludes_self():
    ns = _stream_functions()
    calls = []
    async def broken_audit(viewer, subject):
        calls.append((viewer, subject))
        raise RuntimeError("simulated audit outage")
    ns["_write_emergency_view"] = broken_audit
    async def run():
        viewer = SimpleNamespace(id="viewer")
        event = {"type": "emergency_location_update", "data": {"user_id": "target", "lat": 20, "lng": 70}}
        assert await ns["_family_event_allowed"](None, viewer, event)
        encoded = ns["_encode_event"](viewer, event)
        assert "emergency_location_update" in encoded
        assert len(ns["_disclosure_tasks"]) == 1
        await asyncio.gather(*list(ns["_disclosure_tasks"]))
        ns["_encode_event"](SimpleNamespace(id="target"), event)
        assert calls == [("viewer", "target")]
    asyncio.run(run())


def test_newer_pause_cannot_be_cleared_by_stale_automatic_resume():
    from datetime import datetime, timezone, timedelta
    from app.services.family_circle_runtime_authority import sharing_paused
    now = datetime.now(timezone.utc)
    calls = []
    class DB:
        async def execute(self, stmt, params):
            calls.append(str(stmt))
            if len(calls) == 1:
                return Rows({"paused": True, "pause_mode": "1h", "paused_until": now - timedelta(seconds=1)})
            assert "AND paused_until=:until" in str(stmt)
            return SimpleNamespace(rowcount=0)
    assert asyncio.run(sharing_paused(DB(), "user", now=now)) is True
    assert len(calls) == 2  # no false resume audit/notification
