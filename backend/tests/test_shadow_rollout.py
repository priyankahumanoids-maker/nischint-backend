"""ShadowRolloutController unit tests.

Coverage:
  * Constructor input validation.
  * Classification taxonomy enforcement (classify_fn must return enum).
  * Idempotency on event_id (replay-safe).
  * Hysteresis: regression snaps, recovery requires streak.
  * Autodisable safeguard fires at threshold + survives env-var.
  * Tier state machine + transition emission.
  * Per-domain classify_fn isolation (no cross-domain drift).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.shadow_rollout import (
    Classification, RecordResult, ShadowRolloutController, Tier,
)


def _classify_match(**_):
    return Classification.MATCH


def _classify_critical(**_):
    return Classification.CRITICAL_REGRESSION


def _classify_improvement(**_):
    return Classification.IMPROVEMENT


def _stateful_redis():
    """A MagicMock Redis client that persists keys between calls so
    the state machine can be exercised."""
    store: dict[str, str] = {}
    fake = MagicMock()

    def fake_get(key):
        return store.get(key)

    def fake_set(key, value, ex=None, nx=False):
        if nx and key in store:
            return False
        store[key] = value
        return True

    def fake_incr(key):
        store[key] = str(int(store.get(key, 0)) + 1)
        return int(store[key])

    def fake_expire(key, ttl):
        return key in store

    def fake_delete(key):
        return 1 if store.pop(key, None) is not None else 0

    def fake_mget(keys):
        return [store.get(k) for k in keys]

    fake.get = MagicMock(side_effect=fake_get)
    fake.set = MagicMock(side_effect=fake_set)
    fake.incr = MagicMock(side_effect=fake_incr)
    fake.expire = MagicMock(side_effect=fake_expire)
    fake.delete = MagicMock(side_effect=fake_delete)
    fake.mget = MagicMock(side_effect=fake_mget)
    return fake, store


# ── Constructor ────────────────────────────────────────────────────

def test_constructor_rejects_empty_kind():
    with pytest.raises(ValueError):
        ShadowRolloutController(kind="", classify_fn=_classify_match)


def test_constructor_rejects_non_callable_classify_fn():
    with pytest.raises(ValueError):
        ShadowRolloutController(kind="test", classify_fn="not_callable")


def test_default_thresholds_locked():
    """The locked operational tunables must not silently drift."""
    c = ShadowRolloutController("test", _classify_match)
    assert c.autodisable_threshold_pct == 0.05
    assert c.autodisable_min_samples   == 20
    assert c.autodisable_window_s      == 600
    assert c.hysteresis_recovery       == 20
    assert c.drift_recovery            == 50
    assert c.dedup_ttl_s               == 3600


# ── Classification taxonomy ────────────────────────────────────────

@pytest.mark.asyncio
async def test_record_requires_event_id():
    c = ShadowRolloutController("test", _classify_match)
    with pytest.raises(ValueError, match="event_id"):
        await c.record(event_id="")


@pytest.mark.asyncio
async def test_classify_fn_must_return_enum():
    """Domain code must return Classification enum — returning a
    plain string is rejected so the taxonomy contract is enforced."""
    fake, _ = _stateful_redis()
    bad_fn = lambda **_: "match"   # string, not enum  # noqa: E731
    c = ShadowRolloutController("test", bad_fn)
    with patch(
        "app.services.shadow_rollout.redis_service._get_client",
        return_value=fake,
    ):
        with pytest.raises(ValueError, match="Classification"):
            await c.record(event_id="evt-1")


@pytest.mark.asyncio
async def test_record_returns_classification():
    fake, _ = _stateful_redis()
    c = ShadowRolloutController("test", _classify_match)
    with patch(
        "app.services.shadow_rollout.redis_service._get_client",
        return_value=fake,
    ):
        r = await c.record(event_id="evt-1")
    assert isinstance(r, RecordResult)
    assert r.classification == Classification.MATCH
    assert r.deduped is False


# ── Idempotency ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_record_is_idempotent_on_event_id():
    """Duplicate event_id → no-op, no counter bump, no streak change.
    This is critical for replay safety (SSE reconnection, retries)."""
    fake, store = _stateful_redis()
    c = ShadowRolloutController("test", _classify_critical)
    with patch(
        "app.services.shadow_rollout.redis_service._get_client",
        return_value=fake,
    ):
        r1 = await c.record(event_id="duplicate")
        # Snapshot the store after the first call.
        snapshot_keys = set(store.keys())
        snapshot_total = sum(int(v) for k, v in store.items() if k.endswith(":1"))

        r2 = await c.record(event_id="duplicate")
        r3 = await c.record(event_id="duplicate")

    assert r1.deduped is False
    assert r2.deduped is True
    assert r3.deduped is True
    # No new keys were created by the dedup'd calls.
    assert set(store.keys()) == snapshot_keys
    # And counter values didn't double-bump.
    after_total = sum(int(v) for k, v in store.items() if k.endswith(":1"))
    assert after_total == snapshot_total


# ── Hysteresis state machine ───────────────────────────────────────

@pytest.mark.asyncio
async def test_regression_snaps_immediately():
    """First critical event → immediate transition to `critical`."""
    fake, _ = _stateful_redis()
    c = ShadowRolloutController("test", _classify_match)
    with patch(
        "app.services.shadow_rollout.redis_service._get_client",
        return_value=fake,
    ):
        # Prime as in_parity by recording a match (transition from unknown → in_parity).
        await c.record(event_id="ev-1")
        # Now drop a critical — manually swap classify_fn.
        c._classify_fn = _classify_critical  # noqa: SLF001
        r = await c.record(event_id="ev-2")

    assert r.tier_transition is not None
    assert r.tier_transition["to"] == Tier.CRITICAL.value
    assert r.tier_transition["reason"] == "regression"


@pytest.mark.asyncio
async def test_recovery_requires_clean_streak():
    """critical → improving requires `hysteresis_recovery` consecutive
    clean events. Recovery on the streak-completing event."""
    fake, _ = _stateful_redis()
    c = ShadowRolloutController(
        "test", _classify_critical, hysteresis_recovery=3,
    )
    with patch(
        "app.services.shadow_rollout.redis_service._get_client",
        return_value=fake,
    ):
        # Force into critical.
        await c.record(event_id="crit-1")
        # Now switch to match — recovery streak begins.
        c._classify_fn = _classify_match  # noqa: SLF001
        r1 = await c.record(event_id="m-1")
        r2 = await c.record(event_id="m-2")
        r3 = await c.record(event_id="m-3")

    # First two should NOT transition (streak not met yet).
    assert r1.tier_transition is None
    assert r2.tier_transition is None
    # The third recovery event fires the transition.
    assert r3.tier_transition is not None
    assert r3.tier_transition["reason"] == "recovery_hysteresis_met"
    assert r3.tier_transition["to"] == Tier.IN_PARITY.value


@pytest.mark.asyncio
async def test_streak_resets_on_critical_mid_recovery():
    fake, _ = _stateful_redis()
    c = ShadowRolloutController(
        "test", _classify_critical, hysteresis_recovery=3,
    )
    with patch(
        "app.services.shadow_rollout.redis_service._get_client",
        return_value=fake,
    ):
        await c.record(event_id="crit-1")
        c._classify_fn = _classify_match  # noqa: SLF001
        await c.record(event_id="m-1")
        await c.record(event_id="m-2")
        # Insert a critical mid-streak — should reset.
        c._classify_fn = _classify_critical  # noqa: SLF001
        await c.record(event_id="crit-2")
        c._classify_fn = _classify_match  # noqa: SLF001
        # Next match must NOT trigger recovery (streak was reset to 0).
        r = await c.record(event_id="m-3")
    assert r.tier_transition is None


# ── Autodisable ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_autodisable_fires_at_threshold():
    """Once rolling critical-rate breaches threshold AND samples ≥ min,
    autodisable stamps and the safety state reflects it."""
    fake, _ = _stateful_redis()
    c = ShadowRolloutController(
        "test", _classify_critical,
        autodisable_threshold_pct=0.05,
        autodisable_min_samples=3,
    )
    with patch(
        "app.services.shadow_rollout.redis_service._get_client",
        return_value=fake,
    ):
        # 3 critical events → 100% critical rate, ≥ min_samples.
        await c.record(event_id="c-1")
        await c.record(event_id="c-2")
        r = await c.record(event_id="c-3")
        safety = c.get_safety_state()

    assert r.autodisabled is True
    assert safety["auto_disabled"] is True


def test_is_active_for_blocked_by_autodisable():
    """Even at 100% rollout, an autodisabled kind cannot fire."""
    fake, store = _stateful_redis()
    c = ShadowRolloutController("test", _classify_match)
    # Pre-stamp the autodisable flag.
    store[c._key("autodisable_state")] = '{"disabled_at":"x","reason":"y"}'  # noqa: SLF001
    with patch(
        "app.services.shadow_rollout.redis_service._get_client",
        return_value=fake,
    ):
        assert c.is_active_for("user-x", 100) is False


def test_is_active_for_zero_rollout_returns_false():
    fake, _ = _stateful_redis()
    c = ShadowRolloutController("test", _classify_match)
    with patch(
        "app.services.shadow_rollout.redis_service._get_client",
        return_value=fake,
    ):
        assert c.is_active_for("user-x", 0) is False


def test_is_active_for_user_hash_is_deterministic():
    fake, _ = _stateful_redis()
    c = ShadowRolloutController("test", _classify_match)
    with patch(
        "app.services.shadow_rollout.redis_service._get_client",
        return_value=fake,
    ):
        decisions = {c.is_active_for("stable-uid", 50) for _ in range(20)}
    assert len(decisions) == 1


# ── Per-domain isolation ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_separate_kinds_do_not_share_state():
    """Two independent rollouts with the same Redis must not pollute
    each other's counters or tier state."""
    fake, _ = _stateful_redis()
    a = ShadowRolloutController("kind_a", _classify_critical)
    b = ShadowRolloutController("kind_b", _classify_match)
    with patch(
        "app.services.shadow_rollout.redis_service._get_client",
        return_value=fake,
    ):
        await a.record(event_id="a-1")
        await b.record(event_id="b-1")
        a_state = a.get_safety_state()
        b_state = b.get_safety_state()

    assert a_state["critical_events"] >= 1
    assert b_state["critical_events"] == 0
