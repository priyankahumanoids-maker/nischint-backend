"""F03-F06 local behavior tests. Production function bodies, fake persistence only."""
import ast
import asyncio
import importlib
import sys
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as S

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_service(name):
    """No package initializer, model registry, configuration or engine imports."""
    full = "app.services." + name
    path = ROOT / "app/services" / (name + ".py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = []
    for n in tree.body:
        if isinstance(n, ast.ImportFrom):
            if n.module and (n.module.startswith(("app.core.", "sqlalchemy", "fastapi"))
                             or n.module in {"__future__", "datetime", "dataclasses", "typing"}):
                nodes.append(n)
        elif isinstance(n, ast.Import):
            if all(a.name in {"uuid", "asyncio", "logging", "json", "hashlib", "secrets", "string"} for a in n.names):
                nodes.append(n)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign)):
            nodes.append(n)
    module = types.ModuleType(full)
    module.__file__ = str(path)
    sys.modules[full] = module
    setattr(sys.modules["app.services"], name, module)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(path), "exec"), module.__dict__)
    return module


def bootstrap():
    sys.path.insert(0, str(ROOT))
    services = types.ModuleType("app.services")
    services.__path__ = [str(ROOT / "app/services")]
    sys.modules["app.services"] = services
    # Pure policies use their real imports. Heavy service startup imports are omitted.
    modules = {name: load_service(name) for name in (
        "family_circle_runtime_authority", "member_monitoring_policy",
        "family_circle_invite_service", "subscription_service",
        "family_circle_notification_outbox",
    )}
    return modules


def run(coro):
    return asyncio.run(coro)


def authority(monkeypatch, *, states=None, role="adult_member", paused=False, entitlement="active"):
    from app.services import family_circle_runtime_authority as r
    from app.core import family_circle_permissions as p
    states = states or {"a": "active", "b": "active"}
    circle = S(id="circle", plan="family", status="active")
    async def snapshot(db, uid):
        return S(circle=circle, membership=S(user_id=uid, role=role if uid == "a" else "minor",
                                             seat="member")) if states.get(uid) == "active" else None
    async def state(db, uid): return states.get(uid, "legacy")
    async def consent(*args, **kwargs):
        return p.ConsentState({p.CONSENT_LOCATION: True, p.CONSENT_BACKGROUND_LOCATION: True,
                               p.CONSENT_AI_BEHAVIORAL: True})
    async def ent(*args): return S(permission_entitlement=entitlement)
    async def pause(*args): return paused
    monkeypatch.setattr(r, "membership_snapshot", snapshot)
    monkeypatch.setattr(r, "canonical_membership_state", state)
    monkeypatch.setattr(r, "_consent_state", consent)
    monkeypatch.setattr(r, "resolve_entitlement", ent, raising=False)
    monkeypatch.setattr(r, "sharing_paused", pause)
    return r


@pytest.mark.parametrize("actor,target,canonical", [
    ("legacy", "active", True), ("legacy", "former", True), ("legacy", "invalid", True),
    ("former", "legacy", True), ("former", "active", True), ("active", "legacy", True),
    ("active", "former", True), ("legacy", "legacy", False),
])
def test_two_sided_authority(monkeypatch, actor, target, canonical):
    r = authority(monkeypatch, states={"a": actor, "b": target})
    decision = run(r.runtime_decision(None, actor_user_id="a", target_user_id="b", action=r.ACTION_VIEW_LOCATION))
    assert decision.canonical is canonical
    assert not decision.allowed  # noncanonical means caller may apply its existing legacy policy
    allowed = run(r.filter_targets_for_action(None, "a", ["b"], r.ACTION_VIEW_LOCATION))
    assert allowed == ([] if canonical else ["b"])


def test_mixed_legacy_bulk_candidates(monkeypatch):
    r = authority(monkeypatch, states={"a": "legacy", "b": "active", "c": "former", "d": "legacy"})
    assert run(r.filter_targets_for_action(None, "a", ["b", "c", "d"], r.ACTION_VIEW_LOCATION)) == ["d"]


@pytest.mark.parametrize("paused,expected", [(True, False), (False, True)])
def test_ordinary_collection_pause(monkeypatch, paused, expected):
    r = authority(monkeypatch, paused=paused)
    assert run(r.runtime_decision(None, actor_user_id="a", action=r.ACTION_PRODUCE_LOCATION)).allowed is expected
    assert run(r.runtime_decision(None, actor_user_id="a", target_user_id="b", action=r.ACTION_VIEW_LOCATION)).allowed is expected


@pytest.mark.parametrize("entitlement", ["active", "lifeline"])
def test_sos_ignores_ordinary_pause(monkeypatch, entitlement):
    from app.core.family_circle_permissions import ACTION_TRIGGER_SOS
    r = authority(monkeypatch, paused=True, entitlement=entitlement)
    async def forbidden(*args): raise AssertionError("SOS consulted ordinary pause")
    monkeypatch.setattr(r, "sharing_paused", forbidden)
    assert run(r.runtime_decision(None, actor_user_id="a", action=ACTION_TRIGGER_SOS)).allowed


def test_pause_does_not_lock_unrelated_ai_action(monkeypatch):
    r = authority(monkeypatch, paused=True)
    assert run(r.runtime_decision(None, actor_user_id="a", action=r.ACTION_VIEW_AI_PROFILE,
                                 target_user_id="b")).allowed is False  # peer view still paused
    from app.core.family_circle_permissions import ACTION_PRODUCE_AI_PROFILE
    assert run(r.runtime_decision(None, actor_user_id="a", action=ACTION_PRODUCE_AI_PROFILE)).allowed


class Rows:
    def __init__(self, row=None): self.row = row
    def mappings(self): return self
    def first(self): return self.row
    def scalar_one_or_none(self): return self.row
    def scalars(self): return self
    def all(self): return [] if self.row is None else [self.row]


@pytest.mark.parametrize("state", ["former", "invalid"])
def test_former_monitoring_target_rejected_before_legacy(monkeypatch, state):
    from app.services import member_monitoring_policy as m
    from fastapi import HTTPException
    uid = "11111111-1111-1111-1111-111111111111"
    authority(monkeypatch, states={uid: state})
    class DB:
        async def execute(self, *args): return Rows({"id": uid, "role": "child", "is_active": True})
    with pytest.raises(HTTPException) as error:
        run(m.require_policy_write_access(DB(), S(id=uid, role="child"), uid))
    assert error.value.status_code == 403


@pytest.mark.parametrize("actor_state,target_state,role,allow", [
    ("legacy", "active", "guardian", False),
    ("former", "legacy", "guardian", False),
    ("active", "legacy", "owner", False),
    ("active", "active", "owner", True),
    ("active", "active", "adult_member", False),
])
def test_monitoring_write_uses_canonical_boundary(monkeypatch, actor_state, target_state, role, allow):
    from app.services import member_monitoring_policy as m
    from fastapi import HTTPException
    authority(monkeypatch, states={"a": actor_state, "b": target_state}, role=role)
    async def target(*args): return "b"
    monkeypatch.setattr(m, "_canonical_protected_member", target)
    if allow:
        assert run(m.require_policy_write_access(None, S(id="a", role="guardian"), "b")) == "b"
    else:
        with pytest.raises(HTTPException):
            run(m.require_policy_write_access(None, S(id="a", role="guardian"), "b"))


@pytest.mark.parametrize("state", ["legacy", "active"])
def test_adult_self_management_preserved(monkeypatch, state):
    from app.services import member_monitoring_policy as m
    authority(monkeypatch, states={"a": state})
    async def target(*args): return "a"
    monkeypatch.setattr(m, "_canonical_protected_member", target)
    assert run(m.require_policy_write_access(None, S(id="a", role="woman"), "a")) == "a"


def test_no_owner_override_of_adult(monkeypatch):
    from app.services import member_monitoring_policy as m
    from fastapi import HTTPException
    r = authority(monkeypatch, role="owner")
    original = r.membership_snapshot
    async def snapshot(db, uid):
        result = await original(db, uid)
        if uid == "b": result.membership.role = "adult_member"
        return result
    monkeypatch.setattr(r, "membership_snapshot", snapshot)
    async def target(*args): return "b"
    monkeypatch.setattr(m, "_canonical_protected_member", target)
    with pytest.raises(HTTPException, match="Another adult"):
        run(m.require_policy_write_access(None, S(id="a", role="guardian"), "b"))


class Query:
    def where(self, *args): return self
    def with_for_update(self): return self
    def execution_options(self, **kwargs): return self


def invitation(monkeypatch, *, role="owner", entitlement="active", sponsor_state="active"):
    from app.services import family_circle_invite_service as i
    authority(monkeypatch, states={"a": sponsor_state}, role=role, entitlement=entitlement)
    class Circle: id = "circle"
    class Member: user_id = "user"; circle_id = "circle"; status = "status"
    class User: pass
    monkeypatch.setattr(i, "FamilyCircle", Circle, raising=False)
    monkeypatch.setattr(i, "CircleMembership", Member, raising=False)
    monkeypatch.setattr(i, "User", User, raising=False)
    monkeypatch.setattr(i, "select", lambda *args: Query())
    class PlanError(ValueError): pass
    monkeypatch.setattr(i, "CirclePlanError", PlanError, raising=False)
    circle = S(id="circle", plan="family", status="active")
    membership = S(role=role, user_id="a", circle_id="circle", status="active")
    events = []
    class DB:
        async def execute(self, stmt, params=None):
            events.append(str(stmt))
            sql = str(stmt)
            if isinstance(stmt, Query):
                return Rows(membership if sponsor_state == "active" else None)
            if "FROM family_plan_catalog" in sql:
                plan = str((params or {}).get("plan") or "family").strip().lower()
                capacities = {
                    "trial": {"protected": 1, "guardian": 2},
                    "individual": {"protected": 1, "guardian": 2},
                    "family": {"member": 4},
                }.get(plan)
                if capacities is None:
                    return Rows(None)
                return Rows({
                    "plan_key": plan,
                    "display_name": plan.title(),
                    "price_inr": 0 if plan == "trial" else (299 if plan == "individual" else 999),
                    "billing_period": "trial" if plan == "trial" else "month",
                    "trial_days": 7 if plan == "trial" else None,
                    "seat_capacities": capacities,
                    "feature_flags": {},
                    "sort_order": 0,
                })
            if sql.lstrip().startswith("SELECT 1"): return Rows()
            if sql.lstrip().startswith("SELECT user_id FROM circle_memberships"): return Rows("a")
            return Rows("accepted")
        async def get(self, model, uid, **kwargs):
            if model is Circle: return circle
            if model is User: return S(id="a", is_active=True)
            return S(id="joined", user_id="new")
        async def flush(self): events.append("flush")
    async def load(*args): return circle, membership
    async def zero(*args): return 0
    async def no_op(*args, **kwargs): pass
    async def add(*args, **kwargs): events.append("add_member"); return S(membership_id="joined")
    monkeypatch.setattr(i, "_load_circle_and_actor", load)
    monkeypatch.setattr(i, "_active_seat_count", zero)
    monkeypatch.setattr(i, "_pending_invite_count", zero)
    monkeypatch.setattr(i, "seat_capacity", lambda *args: 4, raising=False)
    monkeypatch.setattr(i, "append_family_audit", no_op, raising=False)
    monkeypatch.setattr(i, "validate_seat_for_membership", lambda *args: None, raising=False)
    monkeypatch.setattr(i, "add_membership_with_seat", add, raising=False)
    point = datetime(2026, 10, 6, tzinfo=timezone.utc)
    row = dict(id="invite", circle_id="circle", created_by_user_id="a", seat="member",
               status="pending", expires_at=point + timedelta(hours=48), invitee_kind="adult",
               parental_basis=None, parental_verification_ref=None)
    async def invite_row(*args, **kwargs): return row
    monkeypatch.setattr(i, "_invite_row", invite_row)
    return i, DB(), S(id="a"), S(id="new", full_name="New Member", date_of_birth=date(1990, 1, 1)), point, row, events


@pytest.mark.parametrize("role,entitlement,allow", [
    ("owner", "active", True), ("co_admin", "active", True),
    ("adult_member", "active", False), ("minor", "active", False),
    ("owner", "lifeline", False), ("co_admin", "lifeline", False),
])
def test_invite_creation_current_policy(monkeypatch, role, entitlement, allow):
    i, db, actor, _, point, _, events = invitation(monkeypatch, role=role, entitlement=entitlement)
    call = i.create_invite(db, actor=actor, requested_seat="member", now=point)
    if allow:
        result = run(call)
        assert result[1] == point + timedelta(hours=48)
        assert any("INSERT INTO family_circle_invites" in e for e in events)
    else:
        with pytest.raises(i.FamilyInviteError): run(call)
        assert not any("INSERT INTO family_circle_invites" in e for e in events)


@pytest.mark.parametrize("role,entitlement,state", [
    ("adult_member", "active", "active"), ("minor", "active", "active"),
    ("owner", "lifeline", "active"), ("owner", "active", "former"),
    ("owner", "active", "legacy"),
])
def test_acceptance_rechecks_sponsor(monkeypatch, role, entitlement, state):
    i, db, _, user, point, _, events = invitation(monkeypatch, role=role, entitlement=entitlement, sponsor_state=state)
    with pytest.raises(i.FamilyInviteError):
        run(i.accept_invite_for_user(db, code="ABCDEF", new_user=user, now=point))
    assert "add_member" not in events


@pytest.mark.parametrize("role", ["owner", "co_admin"])
def test_valid_invite_acceptance(monkeypatch, role):
    i, db, _, user, point, _, events = invitation(monkeypatch, role=role)
    assert run(i.accept_invite_for_user(db, code="ABCDEF", new_user=user, now=point)).user_id == "new"
    assert "add_member" in events
    assert any("AND status='pending'" in e for e in events)
    assert any("INSERT INTO family_notification_outbox" in e for e in events)


@pytest.mark.parametrize("invalid", ["expired", "accepted", "revoked"])
def test_invite_expiry_and_single_use(monkeypatch, invalid):
    i, db, _, user, point, row, events = invitation(monkeypatch)
    if invalid == "expired": row["expires_at"] = point
    else: row["status"] = invalid
    with pytest.raises(i.FamilyInviteError):
        run(i.accept_invite_for_user(db, code="ABCDEF", new_user=user, now=point))
    assert "add_member" not in events


def test_creation_capacity_reserves_pending(monkeypatch):
    i, db, actor, _, point, _, events = invitation(monkeypatch)
    async def two(*args): return 2
    monkeypatch.setattr(i, "_active_seat_count", two)
    monkeypatch.setattr(i, "_pending_invite_count", two)
    with pytest.raises(i.FamilyInviteError, match="full"):
        run(i.create_invite(db, actor=actor, requested_seat="member", now=point))
    assert not any("INSERT INTO family_circle_invites" in e for e in events)


def test_acceptance_propagates_capacity_denial(monkeypatch):
    i, db, _, user, point, _, events = invitation(monkeypatch)
    async def full(*args, **kwargs): raise i.CirclePlanError("capacity full")
    monkeypatch.setattr(i, "add_membership_with_seat", full)
    with pytest.raises(i.FamilyInviteError, match="capacity full"):
        run(i.accept_invite_for_user(db, code="ABCDEF", new_user=user, now=point))
    assert not any("SET status='accepted'" in e for e in events)


def test_minor_creation_stays_disabled(monkeypatch):
    i, db, actor, _, point, _, events = invitation(monkeypatch)
    with pytest.raises(i.FamilyInviteError, match="not enabled"):
        run(i.create_invite(db, actor=actor, requested_seat="member", invitee_kind="minor",
                            parental_basis="untrusted", parental_verification_ref="untrusted", now=point))
    assert not any("INSERT INTO family_circle_invites" in e for e in events)


def test_legacy_guardian_minor_compatibility(monkeypatch):
    from app.services import member_monitoring_policy as m
    authority(monkeypatch, states={"a": "legacy", "b": "legacy"})
    async def target(*args): return "b"
    async def dob(*args): return date(2015, 1, 1)
    async def linked(*args, **kwargs): return ["b"]
    module = types.ModuleType("app.services.guardian_dashboard_engine")
    module._get_linked_user_ids = linked
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(m, "_canonical_protected_member", target)
    monkeypatch.setattr(m, "_target_date_of_birth", dob)
    assert run(m.require_policy_write_access(None, S(id="a", role="guardian", email="local@example.invalid"), "b")) == "b"


def test_canonical_minor_cannot_manage_own_policy(monkeypatch):
    from app.services import member_monitoring_policy as m
    from fastapi import HTTPException
    authority(monkeypatch, states={"a": "active"}, role="minor")
    async def target(*args): return "a"
    monkeypatch.setattr(m, "_canonical_protected_member", target)
    with pytest.raises(HTTPException):
        run(m.require_policy_write_access(None, S(id="a", role="child"), "a"))


def test_paused_runtime_snapshot_denies_background_collection(monkeypatch):
    r = authority(monkeypatch, paused=True)
    async def entitlement(*args):
        return S(permission_entitlement="active", state="paid_active", lifeline=False,
                 reason="test", access_until=None, grace_until=None, payment_required=False)
    monkeypatch.setattr(r, "resolve_entitlement", entitlement)
    snapshot = run(r.runtime_snapshot(None, "a"))
    assert snapshot["sharing_paused"]
    assert not snapshot["can_produce_location"]
    assert not snapshot["can_produce_background_location"]
    assert snapshot["can_trigger_sos"]


def test_inactive_sponsor_cannot_accept(monkeypatch):
    i, db, _, user, point, _, events = invitation(monkeypatch)
    original = db.get
    async def get(model, uid, **kwargs):
        if model is i.User: return S(id="a", is_active=False)
        return await original(model, uid, **kwargs)
    monkeypatch.setattr(db, "get", get)
    with pytest.raises(i.FamilyInviteError):
        run(i.accept_invite_for_user(db, code="ABCDEF", new_user=user, now=point))
    assert "add_member" not in events
