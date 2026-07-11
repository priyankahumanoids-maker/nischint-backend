"""DLQ Reconciler contract tests.

Locks the invariants for every replay function inherited from the
2026-02 reliability ratchet pass:

  1. Three strikes → poison (compensating action becomes audit
     trail of an unreconciled gap, not a silent forever-retry).
  2. Poison list is bounded at `POISON_MAX` via LTRIM.
  3. Drain succeeds quietly when the underlying DB path heals.
  4. Corrupt JSON entries go straight to poison so a single bad
     payload can't block the drain.
  5. The reconciler swallows replay-function raises as
     defence-in-depth — same as the prewarmer base class.
  6. `get_dlq_stats()` returns a stable shape backward-compatible
     with the operator capsule chip; amber and red thresholds at
     10 % / 50 % pressure.

Pure-unit: Redis double, no real DB, no scheduler spin.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.services import dlq_reconciler as dlq


class _RedisDouble:
    """Minimal list + LTRIM-aware double."""

    def __init__(self):
        self.lists: dict[str, list[str]] = {}

    def rpop(self, key):
        lst = self.lists.get(key)
        if not lst:
            return None
        return lst.pop()

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    def ltrim(self, key, start, stop):
        lst = self.lists.get(key)
        if not lst:
            return True
        # Redis LTRIM keeps [start, stop] inclusive. stop = MAX-1
        # means keep the first MAX entries.
        self.lists[key] = lst[start:stop + 1]
        return True

    def llen(self, key):
        return len(self.lists.get(key, []))


@pytest.fixture
def redis_double(monkeypatch):
    d = _RedisDouble()
    monkeypatch.setattr(
        "app.services.redis_service._get_client", lambda: d,
    )
    return d


# ════════════════════════════════════════════════════════════════════
# Drain semantics
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_drain_succeeds_when_replay_returns_true(redis_double):
    """Happy path: replay returns True → entry is removed and never
    re-queued."""
    redis_double.lists["dlq:t"] = [
        json.dumps({"user_id": "u1", "_attempts": 0}),
    ]

    async def _ok(_payload):
        return True

    verb = await dlq._drain_one("dlq:t", _ok)
    assert verb == "drained"
    assert redis_double.lists.get("dlq:t", []) == []
    assert redis_double.lists.get("dlq:t:poison", []) == []


@pytest.mark.asyncio
async def test_transient_failure_requeues_with_attempts_incremented(
        redis_double):
    """Transient: replay returns False with attempts < MAX → entry
    rotates back to the live DLQ with `_attempts` bumped."""
    redis_double.lists["dlq:t"] = [
        json.dumps({"user_id": "u1", "_attempts": 0}),
    ]

    async def _flaky(_payload):
        return False

    verb = await dlq._drain_one("dlq:t", _flaky)
    assert verb == "requeued"
    assert len(redis_double.lists["dlq:t"]) == 1
    payload = json.loads(redis_double.lists["dlq:t"][0])
    assert payload["_attempts"] == 1
    assert redis_double.lists.get("dlq:t:poison", []) == []


@pytest.mark.asyncio
async def test_three_strikes_poison(redis_double):
    """After MAX_ATTEMPTS failures the entry MUST be poisoned so the
    live DLQ stays drainable. Locks the compensating-action promise
    against a silent forever-retry regression."""
    redis_double.lists["dlq:t"] = [
        json.dumps({"user_id": "u1", "_attempts": dlq.MAX_ATTEMPTS - 1}),
    ]

    async def _broken(_payload):
        return False

    verb = await dlq._drain_one("dlq:t", _broken)
    assert verb == "poisoned"
    assert redis_double.lists.get("dlq:t", []) == []
    poison = redis_double.lists["dlq:t:poison"]
    assert len(poison) == 1
    assert json.loads(poison[0])["_attempts"] == dlq.MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_poison_list_bounded_at_max(redis_double):
    """Memory-safety: even a sustained DB outage with hundreds of
    payloads landing must not grow poison unboundedly. Locked at
    `POISON_MAX` via LTRIM."""
    # Pre-fill the poison list AT capacity so LTRIM has to bite.
    redis_double.lists["dlq:t:poison"] = [
        json.dumps({"old": True, "i": i}) for i in range(dlq.POISON_MAX)
    ]
    redis_double.lists["dlq:t"] = [
        json.dumps({"new": True, "_attempts": dlq.MAX_ATTEMPTS - 1}),
    ]

    async def _broken(_payload):
        return False

    verb = await dlq._drain_one("dlq:t", _broken)
    assert verb == "poisoned"
    assert len(redis_double.lists["dlq:t:poison"]) == dlq.POISON_MAX


@pytest.mark.asyncio
async def test_corrupt_json_goes_straight_to_poison(redis_double):
    """A single malformed entry must NOT block the drain. The
    reconciler routes it to poison and continues."""
    redis_double.lists["dlq:t"] = ["{not json{"]

    async def _never_called(_payload):  # pragma: no cover
        raise AssertionError("replay must not be invoked on corrupt entry")

    verb = await dlq._drain_one("dlq:t", _never_called)
    assert verb == "poisoned"
    assert redis_double.lists.get("dlq:t", []) == []
    assert len(redis_double.lists["dlq:t:poison"]) == 1


@pytest.mark.asyncio
async def test_replay_function_raise_treated_as_failure(redis_double):
    """Defence-in-depth: a replay fn that raises (contract
    violation) is logged + treated as a transient failure. The
    entry is requeued, never silently dropped."""
    redis_double.lists["dlq:t"] = [
        json.dumps({"_attempts": 0}),
    ]

    async def _crashes(_payload):
        raise RuntimeError("oops")

    verb = await dlq._drain_one("dlq:t", _crashes)
    assert verb == "requeued"
    assert len(redis_double.lists["dlq:t"]) == 1


@pytest.mark.asyncio
async def test_empty_dlq_short_circuits(redis_double):
    async def _never(_p):  # pragma: no cover
        raise AssertionError("must not be called")
    verb = await dlq._drain_one("dlq:t", _never)
    assert verb == "empty"


@pytest.mark.asyncio
async def test_redis_unavailable_returns_verb(monkeypatch):
    """Redis-down must not raise — degrades to a verb the rollup
    can surface to the operator chip."""
    monkeypatch.setattr(
        "app.services.redis_service._get_client", lambda: None,
    )
    async def _never(_p):  # pragma: no cover
        raise AssertionError("must not be called")
    verb = await dlq._drain_one("dlq:t", _never)
    assert verb == "redis_unavailable"


@pytest.mark.asyncio
async def test_run_cycle_returns_per_dlq_verbs(redis_double):
    """Each registered DLQ contributes one verb. Empty-DLQ verbs
    mean the rollup can surface 'idle' rather than 'broken' on
    cold start."""
    out = await dlq.run_cycle()
    keys = {entry[0] for entry in dlq._DLQS}
    assert set(out.keys()) == keys
    # All empty in a fresh double.
    assert all(v == "empty" for v in out.values())


# ════════════════════════════════════════════════════════════════════
# Stats — capsule chip contract
# ════════════════════════════════════════════════════════════════════

def test_stats_amber_at_ten_percent(redis_double):
    """Threshold lock: amber fires at exactly 10 % depth. A drift
    here breaks the capsule chip."""
    # notification_history MAX=1000. Seed 100 entries → 10 %.
    redis_double.lists["dlq:notification_history"] = [
        json.dumps({"i": i}) for i in range(100)
    ]
    out = dlq.get_dlq_stats()
    nh = next(d for d in out["dlqs"] if d["key"] == "dlq:notification_history")
    assert nh["depth"] == 100
    assert nh["pressure_pct"] == 10.0
    assert nh["amber"] is True
    assert nh["red"] is False
    assert out["any_amber"] is True
    assert out["any_red"] is False


def test_stats_red_at_fifty_percent(redis_double):
    """Threshold lock: red fires at exactly 50 % depth."""
    redis_double.lists["dlq:notification_history"] = [
        json.dumps({"i": i}) for i in range(500)
    ]
    out = dlq.get_dlq_stats()
    nh = next(d for d in out["dlqs"] if d["key"] == "dlq:notification_history")
    assert nh["pressure_pct"] == 50.0
    assert nh["amber"] is True
    assert nh["red"] is True
    assert out["any_red"] is True


def test_stats_shape_backward_compatible(redis_double):
    """Lock the per-DLQ field set so the capsule UI never silently
    loses a key. Updating this test requires updating the chip."""
    out = dlq.get_dlq_stats()
    expected_top = {"dlqs", "any_amber", "any_red", "redis_available",
                    "max_attempts"}
    assert set(out.keys()) == expected_top
    expected_each = {"key", "depth", "max_size", "poison_depth",
                     "poison_max", "pressure_pct", "amber", "red"}
    for d in out["dlqs"]:
        assert set(d.keys()) == expected_each


def test_stats_redis_unavailable_returns_safe_defaults(monkeypatch):
    """When Redis is down the chip must still get a stable shape
    with depth=0 — otherwise the UI shows 'unknown' garbage."""
    monkeypatch.setattr(
        "app.services.redis_service._get_client", lambda: None,
    )
    out = dlq.get_dlq_stats()
    assert out["redis_available"] is False
    assert all(d["depth"] == 0 for d in out["dlqs"])
    assert all(d["poison_depth"] == 0 for d in out["dlqs"])
    assert out["any_amber"] is False
    assert out["any_red"] is False


# ════════════════════════════════════════════════════════════════════
# Registry — all three DLQs MUST be registered
# ════════════════════════════════════════════════════════════════════

def test_all_dlqs_registered():
    """Locks the surface contract — adding a new DLQ-producing site
    in the codebase MUST also add it here, or the audit row will
    silently accumulate forever."""
    keys = {entry[0] for entry in dlq._DLQS}
    assert keys == {
        "dlq:notification_history",
        "dlq:failsafe_audit",
        "dlq:voice_distress_audit",
        "dlq:checkin_audit",
        "dlq:rag_reindex",
    }


def test_max_sizes_match_producer_declarations():
    """The reconciler's `max_size` for each DLQ MUST match the
    producer's `_*_DLQ_MAX` constant. A drift here misreports
    pressure % to operators."""
    from app.services.auto_escalation_engine import _FAILSAFE_DLQ_MAX
    from app.services.checkin_service import _CHECKIN_DLQ_MAX
    from app.services.notification_service import _HISTORY_DLQ_MAX
    from app.services.voice_distress_service import _VOICE_DISTRESS_DLQ_MAX
    from app.api.rag import _RAG_REINDEX_DLQ_MAX
    by_key = {entry[0]: entry[1] for entry in dlq._DLQS}
    assert by_key["dlq:notification_history"] == _HISTORY_DLQ_MAX
    assert by_key["dlq:failsafe_audit"] == _FAILSAFE_DLQ_MAX
    assert by_key["dlq:voice_distress_audit"] == _VOICE_DISTRESS_DLQ_MAX
    assert by_key["dlq:checkin_audit"] == _CHECKIN_DLQ_MAX
    assert by_key["dlq:rag_reindex"] == _RAG_REINDEX_DLQ_MAX


# ════════════════════════════════════════════════════════════════════
# Scheduler lifecycle — idempotent, can stop, accepts no-op stop
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_start_is_idempotent():
    dlq.stop()  # reset
    dlq.start()
    try:
        dlq.start()  # should not raise / spin a second scheduler
        assert dlq._scheduler is not None
    finally:
        dlq.stop()


def test_stop_is_noop_when_not_started():
    dlq.stop()
    dlq.stop()  # idempotent — must not raise


def test_module_level_lifecycle_names_match_prewarmer_convention():
    """`scheduler_runner.py` imports `start_X_scheduler` /
    `stop_X_scheduler` from every prewarmer. The reconciler must
    expose the same shape for consistency."""
    assert callable(dlq.start_dlq_reconciler)
    assert callable(dlq.stop_dlq_reconciler)


def test_jitter_within_declared_range():
    """± DRAIN_JITTER_S around DRAIN_INTERVAL_S."""
    import random as _r
    rng = _r.Random(42)
    for _ in range(100):
        v = dlq.compute_next_interval_seconds(rng)
        assert (dlq.DRAIN_INTERVAL_S - dlq.DRAIN_JITTER_S
                <= v
                <= dlq.DRAIN_INTERVAL_S + dlq.DRAIN_JITTER_S)
