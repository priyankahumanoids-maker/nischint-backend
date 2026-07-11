"""ALERT_TRIGGER_V2 — shadow + decision engine + rollout gate tests.

Pure unit. Mocks the DB read for guardian reachability so each test
is fast and deterministic.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.alert_trigger_v2 import (
    HELP_REQUEST_ESCALATION_DELAY_S, V2Decision,
    classify_kind, compute_v2_decision,
)
from app.services.alert_trigger_v2_shadow import (
    AUTODISABLE_MIN_SAMPLES, AUTODISABLE_THRESHOLD,
    HYSTERESIS_CRITICAL_RECOVERY, HYSTERESIS_DRIFT_RECOVERY,
    _evaluate_tier_transition,
    classify_diff, classify_outcome, diff_decisions,
    is_critical, is_improvement,
    run_shadow_compare, should_v2_actually_fire,
)


# ════════════════════════════════════════════════════════════════════
# classify_kind — policy router
# ════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("k,expected", [
    ("help_request",        "passive_help_request"),
    ("help_requested",      "passive_help_request"),
    ("help",                "passive_help_request"),
    ("HELP_REQUEST",        "passive_help_request"),
    ("sos",                 "active_sos"),
    ("sos_triggered",       "active_sos"),
    ("panic",               "active_sos"),
    ("emergency_triggered", "active_sos"),
    ("voice_distress",      "not_in_scope_v2"),
    ("fall",                "not_in_scope_v2"),
    ("",                    "not_in_scope_v2"),
])
def test_classify_kind_table(k, expected):
    assert classify_kind(k) == expected


# ════════════════════════════════════════════════════════════════════
# compute_v2_decision — policy + ranking
# ════════════════════════════════════════════════════════════════════

def _mock_session_with_tokens(token_rows: list[tuple]):
    """token_rows is a list of (user_id_str, last_success_at,
    last_failure_at, consecutive_failures)."""
    rows = []
    for uid, last_succ, last_fail, fails in token_rows:
        r = MagicMock()
        r.user_id = uid
        r.last_success_at = last_succ
        r.last_failure_at = last_fail
        r.consecutive_failures = fails
        rows.append(r)
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    sess = MagicMock()
    sess.execute = AsyncMock(return_value=result)
    return sess


@pytest.mark.asyncio
async def test_decision_not_in_scope_returns_undispatched():
    sess = MagicMock()
    sess.execute = AsyncMock(return_value=MagicMock(all=lambda: []))
    d = await compute_v2_decision(
        sess, kind="voice_distress", user_id="u1",
        guardian_ids=["g1", "g2"],
    )
    assert d.policy == "not_in_scope_v2"
    assert d.dispatched is False
    assert d.routing_plan == []


@pytest.mark.asyncio
async def test_decision_help_request_no_guardians_undispatched():
    sess = MagicMock()
    sess.execute = AsyncMock(return_value=MagicMock(all=lambda: []))
    d = await compute_v2_decision(
        sess, kind="help_request", user_id="u1", guardian_ids=[],
    )
    assert d.policy == "passive_help_request"
    assert d.dispatched is False
    assert d.reason == "no_guardians_resolved"


@pytest.mark.asyncio
async def test_decision_help_request_ranks_healthy_first():
    """Best reachability guardian must sit at index 0 of the routing
    plan; escalation_delay = 120s."""
    import uuid
    g_dead    = str(uuid.uuid4())
    g_healthy = str(uuid.uuid4())
    g_risk    = str(uuid.uuid4())
    g_unknown = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    sess = _mock_session_with_tokens([
        # healthy: success 2 min ago, no failures
        (uuid.UUID(g_healthy), now - timedelta(minutes=2), None, 0),
        # dead: 4 consecutive failures
        (uuid.UUID(g_dead), None, now - timedelta(minutes=10), 4),
        # risk: success 30 min ago + 1 recent failure
        (uuid.UUID(g_risk), now - timedelta(minutes=30),
         now - timedelta(minutes=2), 1),
        # unknown not present in push_tokens → defaults to "unknown"
    ])
    d = await compute_v2_decision(
        sess, kind="help_request", user_id="u1",
        guardian_ids=[g_dead, g_healthy, g_risk, g_unknown],
    )
    assert d.policy == "passive_help_request"
    assert d.dispatched is True
    assert d.escalation_delay_s == HELP_REQUEST_ESCALATION_DELAY_S
    assert d.routing_plan[0] == g_healthy
    assert d.routing_plan[-1] == g_dead          # dead last
    assert d.reachability[g_healthy] == "healthy"
    assert d.reachability[g_dead]    == "dead"
    assert d.reachability[g_unknown] == "unknown"


@pytest.mark.asyncio
async def test_decision_sos_full_broadcast_zero_delay():
    """SOS = full broadcast, escalation_delay 0, all guardians in plan."""
    import uuid
    g1, g2 = str(uuid.uuid4()), str(uuid.uuid4())
    sess = _mock_session_with_tokens([])
    d = await compute_v2_decision(
        sess, kind="sos", user_id="u1", guardian_ids=[g1, g2],
    )
    assert d.policy == "active_sos"
    assert d.dispatched is True
    assert d.escalation_delay_s == 0
    assert sorted(d.routing_plan) == sorted([g1, g2])


@pytest.mark.asyncio
async def test_decision_swallows_db_errors():
    """A DB read failure must NOT raise — V2 returns a defensive
    decision with reachability all defaulted to 'unknown'."""
    import uuid
    g1 = str(uuid.uuid4())
    sess = MagicMock()
    sess.execute = AsyncMock(side_effect=RuntimeError("db down"))
    d = await compute_v2_decision(
        sess, kind="help_request", user_id="u1", guardian_ids=[g1],
    )
    assert d.dispatched is True
    assert d.policy == "passive_help_request"
    assert d.reachability[g1] == "unknown"


# ════════════════════════════════════════════════════════════════════
# diff_decisions + classify_outcome
# ════════════════════════════════════════════════════════════════════

def _v2(plan, dispatched=True, policy="passive_help_request"):
    return V2Decision(
        policy=policy, dispatched=dispatched,
        routing_plan=plan, escalation_delay_s=120,
        reason="t",
    )


def test_diff_match_when_v1_v2_identical():
    diff = diff_decisions(
        v1_dispatched=True,
        v1_guardian_ids_notified=["a", "b"],
        v2=_v2(["a", "b"]),
    )
    assert diff["decision_match"] is True
    assert diff["fanout_diff"] == []
    assert classify_outcome(diff) == "match"


def test_diff_decision_mismatch():
    diff = diff_decisions(
        v1_dispatched=True,
        v1_guardian_ids_notified=["a"],
        v2=_v2([], dispatched=False),
    )
    assert diff["decision_match"] is False
    assert classify_outcome(diff) == "decision_diff"


def test_diff_fanout_mismatch():
    diff = diff_decisions(
        v1_dispatched=True,
        v1_guardian_ids_notified=["a", "b", "c"],
        v2=_v2(["a", "b"]),
    )
    assert diff["decision_match"] is True
    assert diff["fanout_diff"] == ["c"]
    assert diff["v1_only"] == ["c"]
    assert classify_outcome(diff) == "fanout_diff"


def test_diff_first_target_field():
    diff = diff_decisions(
        v1_dispatched=True,
        v1_guardian_ids_notified=["a", "b"],
        v2=_v2(["b", "a"]),
    )
    # set-equal but order-different — counts as match (ordering is
    # behavioural detail, not a dispatch decision).
    assert diff["fanout_diff"] == []
    assert diff["v2_first_target"] == "b"
    assert classify_outcome(diff) == "match"


# ════════════════════════════════════════════════════════════════════
# Rollout gate
# ════════════════════════════════════════════════════════════════════

def test_rollout_zero_means_shadow_only(monkeypatch):
    monkeypatch.delenv("ALERT_TRIGGER_V2_HELP_REQUEST_ROLLOUT_PCT", raising=False)
    monkeypatch.delenv("ALERT_TRIGGER_V2_SOS_ROLLOUT_PCT", raising=False)
    assert should_v2_actually_fire("help_request", "user-x") is False
    assert should_v2_actually_fire("sos", "user-x") is False


def test_rollout_full_pct_fires_for_all_users(monkeypatch):
    monkeypatch.setenv("ALERT_TRIGGER_V2_HELP_REQUEST_ROLLOUT_PCT", "100")
    for uid in ("u1", "u2", "u3", "abc-def-ghi"):
        assert should_v2_actually_fire("help_request", uid) is True


def test_rollout_per_kind_independent(monkeypatch):
    monkeypatch.setenv("ALERT_TRIGGER_V2_HELP_REQUEST_ROLLOUT_PCT", "100")
    monkeypatch.delenv("ALERT_TRIGGER_V2_SOS_ROLLOUT_PCT", raising=False)
    assert should_v2_actually_fire("help_request", "u1") is True
    assert should_v2_actually_fire("sos",          "u1") is False


def test_rollout_user_hash_is_deterministic(monkeypatch):
    """A user must always land in the same cohort so rollout
    membership is stable across processes."""
    monkeypatch.setenv("ALERT_TRIGGER_V2_HELP_REQUEST_ROLLOUT_PCT", "50")
    decisions = {should_v2_actually_fire("help_request", "stable-uid")
                 for _ in range(20)}
    assert len(decisions) == 1


def test_rollout_out_of_scope_kind_never_fires(monkeypatch):
    monkeypatch.setenv("ALERT_TRIGGER_V2_HELP_REQUEST_ROLLOUT_PCT", "100")
    monkeypatch.setenv("ALERT_TRIGGER_V2_SOS_ROLLOUT_PCT", "100")
    assert should_v2_actually_fire("voice_distress", "u1") is False
    assert should_v2_actually_fire("fall",           "u1") is False


# ════════════════════════════════════════════════════════════════════
# run_shadow_compare — end-to-end with mocked Redis
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_shadow_skips_out_of_scope_kinds():
    """A non-V2 kind should short-circuit before computing anything."""
    sess = MagicMock()
    sess.execute = AsyncMock(side_effect=AssertionError("must not query"))
    out = await run_shadow_compare(
        sess, kind="voice_distress", user_id="u1",
        guardian_ids_resolved=["g1"],
        v1_dispatched=True,
        v1_guardian_ids_notified=["g1"],
    )
    assert out is None


@pytest.mark.asyncio
async def test_shadow_returns_diff_for_help_request():
    import uuid
    g1 = str(uuid.uuid4())
    sess = _mock_session_with_tokens([
        (uuid.UUID(g1), datetime.now(timezone.utc), None, 0),
    ])
    fake_client = MagicMock()
    fake_client.incr = MagicMock(return_value=1)
    fake_client.expire = MagicMock(return_value=True)
    fake_client.lpush = MagicMock(return_value=1)
    fake_client.ltrim = MagicMock(return_value=True)
    fake_client.mget = MagicMock(return_value=[None])  # rolling-window scan
    fake_client.get = MagicMock(return_value=None)     # autodisable read
    fake_client.set = MagicMock(return_value=True)
    with patch(
        "app.services.alert_trigger_v2_shadow.redis_service._get_client",
        return_value=fake_client,
    ):
        diff = await run_shadow_compare(
            sess, kind="help_request", user_id="u1",
            guardian_ids_resolved=[g1],
            v1_dispatched=True,
            v1_guardian_ids_notified=[g1],
            alert_id="alert-123",
        )
    assert diff is not None
    assert diff["decision_match"] is True
    assert diff["fanout_diff"] == []
    fake_client.incr.assert_called()      # counter bumped
    fake_client.lpush.assert_called()     # event persisted


@pytest.mark.asyncio
async def test_shadow_never_raises_on_redis_failure():
    """Redis being down must NOT crash the hot-path hook."""
    import uuid
    g1 = str(uuid.uuid4())
    sess = _mock_session_with_tokens([])
    with patch(
        "app.services.alert_trigger_v2_shadow.redis_service._get_client",
        side_effect=RuntimeError("redis down"),
    ):
        diff = await run_shadow_compare(
            sess, kind="sos", user_id="u1",
            guardian_ids_resolved=[g1],
            v1_dispatched=True,
            v1_guardian_ids_notified=[g1],
        )
    # Diff is still computed even when persistence fails.


# ════════════════════════════════════════════════════════════════════
# classify_diff — diagnostic taxonomy
# ════════════════════════════════════════════════════════════════════

def _v2_with_reach(plan, reachability, policy="passive_help_request"):
    return V2Decision(
        policy=policy, dispatched=True,
        routing_plan=list(plan), escalation_delay_s=120,
        reason="t", reachability=dict(reachability),
    )


def test_classify_match_when_identical_and_no_ranking_signal():
    diff = diff_decisions(
        v1_dispatched=True,
        v1_guardian_ids_notified=["a", "b"],
        v2=_v2_with_reach(["a", "b"], {"a": "unknown", "b": "unknown"}),
    )
    assert classify_diff(diff, _v2_with_reach(
        ["a", "b"], {"a": "unknown", "b": "unknown"})) == "match"


def test_classify_v2_would_not_dispatch_is_critical():
    diff = diff_decisions(
        v1_dispatched=True,
        v1_guardian_ids_notified=["a"],
        v2=V2Decision(
            policy="passive_help_request", dispatched=False,
            routing_plan=[], escalation_delay_s=120, reason="x",
        ),
    )
    cls = classify_diff(diff, V2Decision(
        policy="passive_help_request", dispatched=False,
        routing_plan=[], escalation_delay_s=120, reason="x",
    ))
    assert cls == "v2_would_not_dispatch"
    assert is_critical(cls)


def test_classify_sos_missed_target_is_critical():
    """SOS = full broadcast; V2 dropping anyone V1 included is critical."""
    v2 = _v2_with_reach(
        ["a"], {"a": "healthy"}, policy="active_sos",
    )
    diff = diff_decisions(
        v1_dispatched=True,
        v1_guardian_ids_notified=["a", "b"],
        v2=v2,
    )
    cls = classify_diff(diff, v2)
    assert cls == "missed_target_critical"
    assert is_critical(cls)


def test_classify_unreachable_target_chosen_is_critical():
    """V2 chose a `dead` primary while a `healthy` was available."""
    v2 = _v2_with_reach(
        ["a", "b"], {"a": "dead", "b": "healthy"},
    )
    diff = diff_decisions(
        v1_dispatched=True,
        v1_guardian_ids_notified=["a", "b"],
        v2=v2,
    )
    cls = classify_diff(diff, v2)
    assert cls == "unreachable_target_chosen"
    assert is_critical(cls)


def test_classify_unreachable_dropped_is_improvement():
    """V2 dropped only the dead/risk targets V1 was including."""
    v2 = _v2_with_reach(
        ["a"], {"a": "healthy", "b": "dead"},
    )
    diff = diff_decisions(
        v1_dispatched=True,
        v1_guardian_ids_notified=["a", "b"],
        v2=v2,
    )
    cls = classify_diff(diff, v2)
    assert cls == "unreachable_dropped"
    assert is_improvement(cls)


def test_classify_ranking_improvement_is_improvement():
    """Same set, V2 puts the healthier guardian first."""
    v2 = _v2_with_reach(
        ["healthy_g", "risk_g"],
        {"healthy_g": "healthy", "risk_g": "risk"},
    )
    diff = diff_decisions(
        v1_dispatched=True,
        v1_guardian_ids_notified=["risk_g", "healthy_g"],
        v2=v2,
    )
    cls = classify_diff(diff, v2)
    assert cls == "ranking_improvement"
    assert is_improvement(cls)


# ════════════════════════════════════════════════════════════════════
# Auto-disable safeguard
# ════════════════════════════════════════════════════════════════════

def _disabled_redis():
    """A Redis mock with the autodisable flag set for `help_request`."""
    fake = MagicMock()
    state_blob = '{"disabled_at":"2026-05-10T00:00:00+00:00","reason":"test"}'

    def _get(key):
        return state_blob if "autodisable_state:help_request" in key else None

    fake.get = MagicMock(side_effect=_get)
    return fake


def test_should_v2_actually_fire_blocked_by_autodisable(monkeypatch):
    """Even at 100 % rollout, an autodisabled kind cannot fire."""
    monkeypatch.setenv("ALERT_TRIGGER_V2_HELP_REQUEST_ROLLOUT_PCT", "100")
    fake = _disabled_redis()
    with patch(
        "app.services.alert_trigger_v2_shadow.redis_service._get_client",
        return_value=fake,
    ):
        assert should_v2_actually_fire("help_request", "u-1") is False


@pytest.mark.asyncio
async def test_autodisable_fires_after_threshold_breach(monkeypatch):
    """Mock the rolling window to report critical_rate above threshold,
    then verify an autodisable stamp is written on the next event."""
    import uuid
    g_dead = str(uuid.uuid4())
    g_healthy = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    sess = _mock_session_with_tokens([
        (uuid.UUID(g_dead), None, now, 5),                 # dead
        (uuid.UUID(g_healthy), now - timedelta(minutes=2), None, 0),  # healthy
    ])

    fake = MagicMock()
    fake.incr = MagicMock(return_value=1)
    fake.expire = MagicMock(return_value=True)
    fake.lpush = MagicMock(return_value=1)
    fake.ltrim = MagicMock(return_value=True)

    # Rolling window: synthesise a 100 % critical rate from N samples.
    n_samples = AUTODISABLE_MIN_SAMPLES
    total_returns = [str(n_samples)] + [None] * 700
    crit_returns  = [str(n_samples)] + [None] * 700

    def fake_mget(keys):
        sample = keys[0] if keys else ""
        return crit_returns if ":crit:" in sample else total_returns

    fake.mget = MagicMock(side_effect=fake_mget)
    fake.get = MagicMock(return_value=None)   # no pre-existing autodisable
    set_calls: list = []
    fake.set = MagicMock(side_effect=lambda *a, **kw: set_calls.append((a, kw)) or True)
    fake.delete = MagicMock(return_value=1)

    with patch(
        "app.services.alert_trigger_v2_shadow.redis_service._get_client",
        return_value=fake,
    ):
        # NB: we deliberately notify only the dead guardian via V1 so
        # V2's plan (dead first since healthy ranks lower than dead's
        # rank-3 only when sorted ASC — actually unknown < dead, but
        # here healthy=0 still ranks first, so V2's first_target is
        # healthy. To force `unreachable_target_chosen` we'd need a
        # different setup; simpler: rely on the synthetic critical
        # rate alone — the autodisable check uses the rolling stats,
        # not THIS event's own classification).
        await run_shadow_compare(
            sess, kind="help_request", user_id="u1",
            guardian_ids_resolved=[g_dead, g_healthy],
            v1_dispatched=True,
            v1_guardian_ids_notified=[g_dead, g_healthy],
        )

    # An autodisable_state stamp must have been written for help_request.
    set_keys = [c[0][0] for c in set_calls if c[0]]
    assert any("autodisable_state:help_request" in k for k in set_keys), (
        f"expected autodisable stamp; got set_keys={set_keys}"
    )
    # Threshold constants are locked.
    assert AUTODISABLE_THRESHOLD == 0.05
    assert AUTODISABLE_MIN_SAMPLES == 20


# ════════════════════════════════════════════════════════════════════
# Tier-state machine — hysteresis on recovery, snap on regression
# ════════════════════════════════════════════════════════════════════

def _stateful_redis():
    """A MagicMock Redis client that actually persists tier state
    between calls so the hysteresis state machine can be exercised."""
    store: dict[str, str] = {}
    fake = MagicMock()

    def fake_get(key):
        return store.get(key)

    def fake_set(key, value, ex=None):
        store[key] = value
        return True

    fake.get = MagicMock(side_effect=fake_get)
    fake.set = MagicMock(side_effect=fake_set)
    fake.delete = MagicMock(side_effect=lambda key: (store.pop(key, None), 1)[1])
    return fake, store


def test_hysteresis_regression_snaps_immediately():
    """in_parity → critical fires on the FIRST critical classification."""
    fake, _ = _stateful_redis()
    with patch(
        "app.services.alert_trigger_v2_shadow.redis_service._get_client",
        return_value=fake,
    ):
        # Cold start: prime as in_parity by recording a match.
        first = _evaluate_tier_transition("help_request", "match")
        # Cold start (no prior tier) becomes in_parity on first match —
        # which is a "regression" from `unknown` to `in_parity`? Actually
        # unknown rank > in_parity rank (lower is worse), so this is a
        # *recovery* path. Let's verify by getting state.
        assert first is None or first["to"] == "in_parity"

        # Now drop a critical → must snap immediately.
        t = _evaluate_tier_transition("help_request", "missed_target_critical")
        assert t is not None
        assert t["to"] == "critical"
        assert t["reason"] == "regression"


def test_hysteresis_recovery_blocked_until_streak_met():
    """critical → improving must require HYSTERESIS_CRITICAL_RECOVERY
    consecutive non-critical events. A single match in between must
    NOT trigger recovery early."""
    fake, _ = _stateful_redis()
    with patch(
        "app.services.alert_trigger_v2_shadow.redis_service._get_client",
        return_value=fake,
    ):
        # Force into critical.
        _evaluate_tier_transition("help_request", "missed_target_critical")

        # Recovery streak below threshold → no transition.
        for _ in range(HYSTERESIS_CRITICAL_RECOVERY - 1):
            t = _evaluate_tier_transition("help_request", "match")
            assert t is None, "recovery fired before streak met"

        # One more clean event → recovery fires.
        t = _evaluate_tier_transition("help_request", "match")
        assert t is not None
        assert t["from"] == "critical"
        assert t["to"] == "in_parity"
        assert t["reason"] == "recovery_hysteresis_met"


def test_hysteresis_streak_resets_on_critical_event():
    """A critical event mid-recovery resets the streak — operator
    sees zero progress instead of false confidence."""
    fake, _ = _stateful_redis()
    with patch(
        "app.services.alert_trigger_v2_shadow.redis_service._get_client",
        return_value=fake,
    ):
        _evaluate_tier_transition("help_request", "missed_target_critical")

        # Build a partial streak.
        for _ in range(HYSTERESIS_CRITICAL_RECOVERY - 1):
            _evaluate_tier_transition("help_request", "match")

        # One critical event resets the counter; recovery must NOT
        # fire on the next match.
        _evaluate_tier_transition("help_request", "missed_target_critical")
        t = _evaluate_tier_transition("help_request", "match")
        assert t is None, "streak did not reset after critical event"


def test_hysteresis_drift_recovery_requires_longer_streak():
    """drift → in_parity must take HYSTERESIS_DRIFT_RECOVERY events,
    even after the rolling stats look clean."""
    fake, _ = _stateful_redis()
    with patch(
        "app.services.alert_trigger_v2_shadow.redis_service._get_client",
        return_value=fake,
    ):
        # Manually plant `drift` tier state — drift can't be reached
        # via the per-event ideal computation (drift is a periodic
        # determination), so we seed Redis directly.
        from app.services.alert_trigger_v2_shadow import _write_tier_state
        _write_tier_state("help_request", {"tier": "drift", "clean_streak": 0})

        for _ in range(HYSTERESIS_DRIFT_RECOVERY - 1):
            t = _evaluate_tier_transition("help_request", "match")
            assert t is None
        t = _evaluate_tier_transition("help_request", "match")
        assert t is not None
        assert t["from"] == "drift"
        assert t["reason"] == "recovery_hysteresis_met"


def test_hysteresis_constants_locked():
    """Operator-locked tunables — fail CI if anyone tweaks them
    without updating the review note."""
    assert HYSTERESIS_CRITICAL_RECOVERY == 20
    assert HYSTERESIS_DRIFT_RECOVERY    == 50


# ════════════════════════════════════════════════════════════════════
# WebSocket embedding — v2_parity rides system_health_delta
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_run_shadow_compare_emits_v2_parity_on_transition():
    """When a critical classification fires the tier state machine,
    the broadcaster must receive a `system_health_delta` event with
    an embedded `v2_parity` payload."""
    import uuid
    g_dead = str(uuid.uuid4())
    g_healthy = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    sess = _mock_session_with_tokens([
        (uuid.UUID(g_dead), None, now, 5),
        (uuid.UUID(g_healthy), now - timedelta(minutes=2), None, 0),
    ])

    # Stateful Redis so tier state persists across the call.
    fake, _store = _stateful_redis()
    fake.incr = MagicMock(return_value=1)
    fake.expire = MagicMock(return_value=True)
    fake.lpush = MagicMock(return_value=1)
    fake.ltrim = MagicMock(return_value=True)
    fake.mget = MagicMock(return_value=[None] * 700)  # window stats: no autodisable
    fake.scan_iter = MagicMock(return_value=iter([]))

    broadcaster_mock = MagicMock()
    broadcaster_mock.broadcast_to_operators = AsyncMock()

    with patch(
        "app.services.alert_trigger_v2_shadow.redis_service._get_client",
        return_value=fake,
    ), patch(
        "app.services.event_broadcaster.broadcaster",
        broadcaster_mock,
    ):
        # First call: classification will be `unreachable_target_chosen`
        # because V2's first target candidate (g_healthy) is healthy,
        # but we forced V1 to fan out only to g_dead — wait, classify_diff
        # logic chooses based on V2's plan. Simpler: send a kind that
        # forces missed_target_critical via SOS where V1 includes
        # someone V2 drops.
        await run_shadow_compare(
            sess, kind="sos", user_id="u1",
            guardian_ids_resolved=[g_dead],         # V2 only sees dead
            v1_dispatched=True,
            v1_guardian_ids_notified=[g_dead, g_healthy],   # V1 sent to both
            alert_id="alert-1",
        )
        # Give the create_task'd _send() coroutine a chance to run.
        import asyncio as _asyncio
        await _asyncio.sleep(0.05)

    # The broadcaster must have been called with system_health_delta
    # carrying a `v2_parity` payload describing the new tier.
    calls = broadcaster_mock.broadcast_to_operators.call_args_list
    relevant = [
        c for c in calls
        if c.args and c.args[0] == "system_health_delta"
        and isinstance(c.args[1], dict)
        and c.args[1].get("source") == "alert_v2"
        and "v2_parity" in c.args[1]
    ]
    assert relevant, (
        "expected broadcast_to_operators call with system_health_delta "
        f"+ v2_parity payload; got calls={calls}"
    )
    v2p = relevant[-1].args[1]["v2_parity"]
    assert v2p["kind"] == "sos"
    assert v2p["tier"] == "critical"
    assert v2p["reason"] == "regression"

