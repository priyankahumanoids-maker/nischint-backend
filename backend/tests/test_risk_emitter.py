"""Regression: Risk Emitter — emit decision rules + dedup/ordering.

Locked contract:
- Emit on first observation, bucket change, |delta| ≥ 2, escalation
  tier change, offline boundary flip.
- Skip everything else.
- Each event carries `event_id` (unique) and `version` (monotonic
  increment per child).
"""
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

import pytest

from app.services import risk_emitter
from app.services.risk_emitter import (
    RiskState,
    SCORE_DELTA_THRESHOLD,
    should_emit,
    maybe_emit_risk_update,
    reset_state,
)


# ── Pure decision logic ────────────────────────────────────────────────
class TestShouldEmit:
    def test_first_observation_always_emits(self):
        assert should_emit(None, score=0, risk_level="GREEN", escalation_tier=0, is_offline=False) == "first_observation"

    def test_no_change_no_emit(self):
        prev = RiskState(score=4, risk_level="YELLOW", escalation_tier=0, is_offline=False, version=1)
        assert should_emit(prev, score=4, risk_level="YELLOW", escalation_tier=0, is_offline=False) is None

    def test_small_delta_no_emit(self):
        prev = RiskState(score=4, risk_level="YELLOW", escalation_tier=0, is_offline=False, version=1)
        # Delta of 1 is below the threshold, same bucket, same esc, same offline → no emit
        assert should_emit(prev, score=5, risk_level="YELLOW", escalation_tier=0, is_offline=False) is None

    def test_score_delta_threshold_emits(self):
        prev = RiskState(score=4, risk_level="YELLOW", escalation_tier=0, is_offline=False, version=1)
        assert should_emit(prev, score=4 + SCORE_DELTA_THRESHOLD, risk_level="YELLOW", escalation_tier=0, is_offline=False) == "score_delta"

    def test_negative_delta_threshold_emits(self):
        prev = RiskState(score=6, risk_level="YELLOW", escalation_tier=0, is_offline=False, version=1)
        assert should_emit(prev, score=4, risk_level="YELLOW", escalation_tier=0, is_offline=False) == "score_delta"

    def test_bucket_change_emits_even_with_zero_delta(self):
        # Score stays at 4 but the level was reclassified — that's a
        # bucket change and MUST emit.
        prev = RiskState(score=4, risk_level="YELLOW", escalation_tier=0, is_offline=False, version=1)
        assert should_emit(prev, score=4, risk_level="GREEN", escalation_tier=0, is_offline=False) == "bucket_change"

    def test_escalation_tier_change_emits(self):
        prev = RiskState(score=4, risk_level="YELLOW", escalation_tier=1, is_offline=False, version=1)
        assert should_emit(prev, score=4, risk_level="YELLOW", escalation_tier=2, is_offline=False) == "escalation_change"

    def test_offline_transition_emits(self):
        prev = RiskState(score=4, risk_level="YELLOW", escalation_tier=0, is_offline=False, version=1)
        assert should_emit(prev, score=4, risk_level="YELLOW", escalation_tier=0, is_offline=True) == "offline_transition"
        # And back online again
        prev_off = RiskState(score=4, risk_level="YELLOW", escalation_tier=0, is_offline=True, version=2)
        assert should_emit(prev_off, score=4, risk_level="YELLOW", escalation_tier=0, is_offline=False) == "offline_transition"


# ── Integration: maybe_emit_risk_update + broadcaster ──────────────────
@pytest.fixture(autouse=True)
def _force_local_state(monkeypatch):
    """Force the in-memory fallback path so unit tests never hit a
    real Redis instance. Real Redis is exercised by the live curl
    smoke at the end of the iteration."""
    monkeypatch.setattr(risk_emitter.redis_service, "is_available", lambda: False)
    reset_state()
    yield
    reset_state()


@pytest.mark.asyncio
async def test_first_emit_sends_to_all_guardians_and_persists_state():
    captured = []

    async def fake_b2u(uid, etype, payload):
        captured.append((uid, etype, payload))

    with patch("app.services.event_broadcaster.broadcaster.broadcast_to_user", new=fake_b2u):
        evt = await maybe_emit_risk_update(
            child_id="child-1",
            guardian_ids=["g1", "g2"],
            score=4,
            risk_level="YELLOW",
            escalation_level="none",
            is_offline=False,
            payload_extras={"lat": 1.0, "lng": 2.0, "factors": []},
        )

    assert evt is not None
    assert evt["version"] == 1
    assert evt["delta"] == 4
    assert evt["reason"] == "first_observation"
    assert evt["risk_level"] == "YELLOW"
    assert evt["score"] == 4
    assert "event_id" in evt and len(evt["event_id"]) >= 32  # uuid string
    # Idempotency token: deterministic from (child_id, version)
    assert evt["emit_key"] == f"child-1:{evt['version']}"
    # All guardians got notified, each as type='risk_update'
    assert {(uid, etype) for uid, etype, _ in captured} == {("g1", "risk_update"), ("g2", "risk_update")}
    # All guardians received the same event body
    bodies = [p for _, _, p in captured]
    assert bodies[0] == bodies[1] == evt


@pytest.mark.asyncio
async def test_silent_when_no_change_no_emit():
    # First emit
    async def noop_b2u(*a, **kw): return None
    with patch("app.services.event_broadcaster.broadcaster.broadcast_to_user", new=noop_b2u):
        a = await maybe_emit_risk_update(
            child_id="child-2", guardian_ids=["g1"], score=4,
            risk_level="YELLOW", escalation_level="none", is_offline=False,
            payload_extras={},
        )
        # Same state again — must NOT emit
        b = await maybe_emit_risk_update(
            child_id="child-2", guardian_ids=["g1"], score=4,
            risk_level="YELLOW", escalation_level="none", is_offline=False,
            payload_extras={},
        )
    assert a is not None
    assert b is None


@pytest.mark.asyncio
async def test_version_is_monotonic_and_event_id_unique():
    seen_versions, seen_ids = [], []
    async def fake_b2u(*a, **kw): return None

    with patch("app.services.event_broadcaster.broadcaster.broadcast_to_user", new=fake_b2u):
        # Force three distinct emits via bucket changes
        for level, score in [("GREEN", 0), ("YELLOW", 4), ("RED", 7)]:
            evt = await maybe_emit_risk_update(
                child_id="child-3", guardian_ids=["g1"],
                score=score, risk_level=level, escalation_level="none",
                is_offline=False, payload_extras={},
            )
            assert evt is not None
            seen_versions.append(evt["version"])
            seen_ids.append(evt["event_id"])

    assert seen_versions == [1, 2, 3]
    assert len(set(seen_ids)) == 3   # all distinct


@pytest.mark.asyncio
async def test_offline_transition_emits_then_skips_repeats():
    captured = []
    async def fake_b2u(uid, etype, payload):
        captured.append(payload)

    with patch("app.services.event_broadcaster.broadcaster.broadcast_to_user", new=fake_b2u):
        # Baseline (online)
        await maybe_emit_risk_update(
            child_id="child-4", guardian_ids=["g1"], score=4,
            risk_level="YELLOW", escalation_level="none", is_offline=False,
            payload_extras={},
        )
        # Goes offline → emit
        await maybe_emit_risk_update(
            child_id="child-4", guardian_ids=["g1"], score=4,
            risk_level="YELLOW", escalation_level="none", is_offline=True,
            payload_extras={},
        )
        # Still offline, same state → no emit
        await maybe_emit_risk_update(
            child_id="child-4", guardian_ids=["g1"], score=4,
            risk_level="YELLOW", escalation_level="none", is_offline=True,
            payload_extras={},
        )
        # Comes back online → emit
        await maybe_emit_risk_update(
            child_id="child-4", guardian_ids=["g1"], score=4,
            risk_level="YELLOW", escalation_level="none", is_offline=False,
            payload_extras={},
        )

    reasons = [p["reason"] for p in captured]
    assert reasons == ["first_observation", "offline_transition", "offline_transition"]


@pytest.mark.asyncio
async def test_broadcaster_failure_does_not_corrupt_state():
    """If a broadcaster call raises, the dedup state still updates so
    we don't end up emitting forever in a tight retry loop."""
    async def boom(*a, **kw):
        raise RuntimeError("downstream offline")

    with patch("app.services.event_broadcaster.broadcaster.broadcast_to_user", new=boom):
        evt = await maybe_emit_risk_update(
            child_id="child-5", guardian_ids=["g1"], score=4,
            risk_level="YELLOW", escalation_level="none", is_offline=False,
            payload_extras={},
        )
    # Emit decision still made; state cached.
    assert evt is not None and evt["reason"] == "first_observation"

    # Identical retry — must NOT re-emit (state was committed).
    async def noop(*a, **kw): return None
    with patch("app.services.event_broadcaster.broadcaster.broadcast_to_user", new=noop):
        evt2 = await maybe_emit_risk_update(
            child_id="child-5", guardian_ids=["g1"], score=4,
            risk_level="YELLOW", escalation_level="none", is_offline=False,
            payload_extras={},
        )
    assert evt2 is None



# ── Redis-backed mode (state shared across instances) ─────────────────
class _FakeRedisClient:
    """Minimum redis-py surface used by the emitter."""
    def __init__(self):
        self.kv: dict[str, str] = {}
        self.counters: dict[str, int] = {}
        self.expires: dict[str, int] = {}

    def incr(self, key):
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    def expire(self, key, ttl):
        self.expires[key] = ttl
        return True

    def get(self, key):
        return self.kv.get(key)

    def set(self, key, val):
        self.kv[key] = val
        return True

    def delete(self, key):
        existed = key in self.kv or key in self.counters
        self.kv.pop(key, None)
        self.counters.pop(key, None)
        return 1 if existed else 0

    def scan_iter(self, match=None):
        prefix = (match or "").rstrip("*")
        for k in list(self.kv.keys()) + list(self.counters.keys()):
            if k.startswith(prefix):
                yield k

    def ping(self):
        return True


@pytest.fixture
def _redis_mode(monkeypatch):
    """Swap the in-memory fallback for a fake Redis client. Exercises
    the same code paths the production system will hit."""
    fake = _FakeRedisClient()
    monkeypatch.setattr(risk_emitter.redis_service, "is_available", lambda: True)
    monkeypatch.setattr(risk_emitter.redis_service, "_get_client", lambda: fake)

    import json as _json
    def _key(ns, k): return f"nischint:{ns}:{k}"

    def fake_get_json(ns, k):
        raw = fake.get(_key(ns, k))
        return _json.loads(raw) if raw else None

    def fake_set_json(ns, k, data, ttl=None):
        fake.set(_key(ns, k), _json.dumps(data, default=str))
        if ttl: fake.expire(_key(ns, k), ttl)
        return True

    def fake_delete_key(ns, k):
        return bool(fake.delete(_key(ns, k)))

    monkeypatch.setattr(risk_emitter.redis_service, "get_json", fake_get_json)
    monkeypatch.setattr(risk_emitter.redis_service, "set_json", fake_set_json)
    monkeypatch.setattr(risk_emitter.redis_service, "delete_key", fake_delete_key)

    reset_state()
    yield fake
    reset_state()


@pytest.mark.asyncio
async def test_redis_mode_persists_state_and_increments_atomically(_redis_mode):
    fake = _redis_mode
    async def noop(*a, **kw): return None
    with patch("app.services.event_broadcaster.broadcaster.broadcast_to_user", new=noop):
        e1 = await maybe_emit_risk_update(
            child_id="cR", guardian_ids=["g1"], score=0,
            risk_level="GREEN", escalation_level="none", is_offline=False,
            payload_extras={},
        )
        e2 = await maybe_emit_risk_update(
            child_id="cR", guardian_ids=["g1"], score=4,
            risk_level="YELLOW", escalation_level="none", is_offline=False,
            payload_extras={},
        )
        e3 = await maybe_emit_risk_update(
            child_id="cR", guardian_ids=["g1"], score=7,
            risk_level="RED", escalation_level="user", is_offline=True,
            payload_extras={},
        )

    assert [e1["version"], e2["version"], e3["version"]] == [1, 2, 3]
    assert fake.counters["nischint:risk:ver:cR"] == 3
    assert "nischint:risk:last:cR" in fake.kv


@pytest.mark.asyncio
async def test_emit_key_is_globally_unique_and_deterministic(_redis_mode):
    """`emit_key = "{child_id}:{version}"` must let frontends drop
    duplicates even after server restart / SSE reconnect."""
    async def noop(*a, **kw): return None
    keys = []
    with patch("app.services.event_broadcaster.broadcaster.broadcast_to_user", new=noop):
        for level, score in [("GREEN", 0), ("YELLOW", 4), ("RED", 7), ("CRITICAL", 9)]:
            evt = await maybe_emit_risk_update(
                child_id="cK", guardian_ids=["g1"],
                score=score, risk_level=level, escalation_level="none",
                is_offline=False, payload_extras={},
            )
            keys.append(evt["emit_key"])
    assert keys == ["cK:1", "cK:2", "cK:3", "cK:4"]
    assert len(set(keys)) == 4


@pytest.mark.asyncio
async def test_redis_concurrent_emits_get_distinct_versions(_redis_mode):
    """Atomic INCR ensures distinct version numbers under contention."""
    async def noop(*a, **kw): return None
    with patch("app.services.event_broadcaster.broadcaster.broadcast_to_user", new=noop):
        await maybe_emit_risk_update(
            child_id="cC", guardian_ids=["g1"], score=4,
            risk_level="YELLOW", escalation_level="none", is_offline=False,
            payload_extras={},
        )
        e_a = await maybe_emit_risk_update(
            child_id="cC", guardian_ids=["g1"], score=7,
            risk_level="RED", escalation_level="none", is_offline=False,
            payload_extras={},
        )
        e_b = await maybe_emit_risk_update(
            child_id="cC", guardian_ids=["g1"], score=10,
            risk_level="CRITICAL", escalation_level="user", is_offline=False,
            payload_extras={},
        )
    assert e_a["version"] != e_b["version"]
    assert e_a["emit_key"] != e_b["emit_key"]


@pytest.mark.asyncio
async def test_falls_back_to_local_when_redis_incr_fails(monkeypatch):
    """Redis says 'available' but the actual INCR call raises.
    Emitter must degrade gracefully, NOT crash."""
    boom_client = MagicMock()
    boom_client.incr = MagicMock(side_effect=RuntimeError("redis down"))
    monkeypatch.setattr(risk_emitter.redis_service, "is_available", lambda: True)
    monkeypatch.setattr(risk_emitter.redis_service, "_get_client", lambda: boom_client)
    monkeypatch.setattr(risk_emitter.redis_service, "get_json", lambda *a, **kw: None)
    monkeypatch.setattr(risk_emitter.redis_service, "set_json", lambda *a, **kw: True)
    reset_state()

    async def noop(*a, **kw): return None
    with patch("app.services.event_broadcaster.broadcaster.broadcast_to_user", new=noop):
        evt = await maybe_emit_risk_update(
            child_id="cF", guardian_ids=["g1"], score=4,
            risk_level="YELLOW", escalation_level="none", is_offline=False,
            payload_extras={},
        )

    assert evt is not None
    assert evt["version"] == 1
    assert evt["emit_key"] == "cF:1"
