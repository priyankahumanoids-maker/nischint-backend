"""Poison-list drain endpoint — contract tests.

Locks the invariants for the operator-triggered drain:

  * Discard mode echoes the popped payloads (CSV-exportable).
  * Replay mode resets `_attempts=0` and re-routes via the
    per-DLQ replay function. Successes are dropped; failures are
    LPUSHed back onto the poison list with LTRIM.
  * Unknown DLQ key → ValueError at the service layer.
  * max_drain bounds enforced (1..POISON_MAX).
  * Corrupt JSON entries always discard, regardless of mode —
    operators can never replay malformed blobs.
  * The live DLQ is NEVER touched by a poison drain.
"""
from __future__ import annotations

import json

import pytest

from app.services import dlq_reconciler as dlq


class _RedisDouble:
    def __init__(self):
        self.lists: dict[str, list[str]] = {}

    def rpop(self, key):
        lst = self.lists.get(key)
        return lst.pop() if lst else None

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    def ltrim(self, key, start, stop):
        lst = self.lists.get(key)
        if not lst:
            return True
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
# Bounds + validation
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_unknown_dlq_raises_value_error(redis_double):
    with pytest.raises(ValueError, match="unknown dlq"):
        await dlq.drain_poison_list("dlq:made_up_key")


@pytest.mark.asyncio
async def test_max_drain_zero_rejected(redis_double):
    with pytest.raises(ValueError, match="max_drain"):
        await dlq.drain_poison_list(
            "dlq:notification_history", max_drain=0,
        )


@pytest.mark.asyncio
async def test_max_drain_over_cap_rejected(redis_double):
    with pytest.raises(ValueError, match="max_drain"):
        await dlq.drain_poison_list(
            "dlq:notification_history", max_drain=dlq.POISON_MAX + 1,
        )


@pytest.mark.asyncio
async def test_is_known_dlq_locks_registered_keys():
    """The endpoint uses this for the 404 — a typo'd DLQ key MUST
    reject before any RPOP is attempted."""
    assert dlq.is_known_dlq("dlq:notification_history") is True
    assert dlq.is_known_dlq("dlq:failsafe_audit") is True
    assert dlq.is_known_dlq("dlq:voice_distress_audit") is True
    assert dlq.is_known_dlq("dlq:checkin_audit") is True
    assert dlq.is_known_dlq("dlq:totally_made_up") is False
    assert dlq.is_known_dlq("") is False


# ════════════════════════════════════════════════════════════════════
# Discard mode — hard delete with payload echo
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_discard_mode_drains_and_echoes_items(redis_double):
    """Operator can CSV-export the popped payloads. Items array
    MUST mirror what was in poison so the operator has a complete
    audit trail."""
    pkey = dlq._poison_key("dlq:failsafe_audit")
    redis_double.lists[pkey] = [
        json.dumps({"event_id": "e1", "_attempts": 3}),
        json.dumps({"event_id": "e2", "_attempts": 3}),
        json.dumps({"event_id": "e3", "_attempts": 3}),
    ]
    out = await dlq.drain_poison_list(
        "dlq:failsafe_audit", replay=False, max_drain=100,
    )
    assert out["mode"] == "discard"
    assert out["attempted"] == 3
    assert out["discarded"] == 3
    assert len(out["items"]) == 3
    # Poison list emptied.
    assert redis_double.lists.get(pkey, []) == []


@pytest.mark.asyncio
async def test_discard_respects_max_drain_cap(redis_double):
    pkey = dlq._poison_key("dlq:failsafe_audit")
    redis_double.lists[pkey] = [
        json.dumps({"i": i}) for i in range(20)
    ]
    out = await dlq.drain_poison_list(
        "dlq:failsafe_audit", replay=False, max_drain=5,
    )
    assert out["attempted"] == 5
    assert out["discarded"] == 5
    assert redis_double.llen(pkey) == 15


@pytest.mark.asyncio
async def test_discard_mode_handles_corrupt_json(redis_double):
    """Malformed entries land in `items` with a `_corrupt` marker
    so operators can still see what was in poison."""
    pkey = dlq._poison_key("dlq:failsafe_audit")
    redis_double.lists[pkey] = ["{not json"]
    out = await dlq.drain_poison_list(
        "dlq:failsafe_audit", replay=False,
    )
    assert out["attempted"] == 1
    assert out["discarded"] == 1
    assert out["items"][0]["_corrupt"] is True


# ════════════════════════════════════════════════════════════════════
# Replay mode — routes through per-DLQ replay function
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_replay_mode_drops_on_success(redis_double, monkeypatch):
    """Successful replays leave the entry drained — the poison
    list shrinks."""
    pkey = dlq._poison_key("dlq:failsafe_audit")
    redis_double.lists[pkey] = [
        json.dumps({"event_id": "e1", "_attempts": 3}),
    ]

    async def _ok(_p):
        return True
    monkeypatch.setattr(dlq, "_replay_fn_for", lambda k: _ok)

    out = await dlq.drain_poison_list("dlq:failsafe_audit", replay=True)
    assert out["mode"] == "replay"
    assert out["attempted"] == 1
    assert out["drained"] == 1
    assert out["requeued"] == 0
    assert redis_double.lists.get(pkey, []) == []


@pytest.mark.asyncio
async def test_replay_mode_requeues_on_failure(redis_double, monkeypatch):
    """Replay failure → entry back on poison so it stays auditable
    (defensive: never silently drop a poisoned payload)."""
    pkey = dlq._poison_key("dlq:failsafe_audit")
    redis_double.lists[pkey] = [
        json.dumps({"event_id": "e1", "_attempts": 3}),
    ]

    async def _broken(_p):
        return False
    monkeypatch.setattr(dlq, "_replay_fn_for", lambda k: _broken)

    out = await dlq.drain_poison_list("dlq:failsafe_audit", replay=True)
    assert out["attempted"] == 1
    assert out["drained"] == 0
    assert out["requeued"] == 1
    # Entry is back on poison.
    assert redis_double.llen(pkey) == 1


@pytest.mark.asyncio
async def test_replay_mode_resets_attempts(redis_double, monkeypatch):
    """`_attempts` MUST reset to 0 so the replay doesn't
    immediately re-poison on the first transient failure during
    the operator drain. This is the operator saying 'try again
    from scratch.'"""
    seen_attempts: list[int] = []
    pkey = dlq._poison_key("dlq:failsafe_audit")
    redis_double.lists[pkey] = [
        json.dumps({"event_id": "e1", "_attempts": 3}),
    ]

    async def _capture(p):
        seen_attempts.append(p["_attempts"])
        return True

    monkeypatch.setattr(dlq, "_replay_fn_for", lambda k: _capture)
    await dlq.drain_poison_list("dlq:failsafe_audit", replay=True)
    assert seen_attempts == [0]


@pytest.mark.asyncio
async def test_replay_swallows_replay_function_raises(
        redis_double, monkeypatch):
    """A replay-fn raise = transient failure = requeue. NEVER raise
    out of the drain endpoint."""
    pkey = dlq._poison_key("dlq:failsafe_audit")
    redis_double.lists[pkey] = [
        json.dumps({"event_id": "e1", "_attempts": 3}),
    ]

    async def _crashes(_p):
        raise RuntimeError("boom")
    monkeypatch.setattr(dlq, "_replay_fn_for", lambda k: _crashes)

    out = await dlq.drain_poison_list("dlq:failsafe_audit", replay=True)
    assert out["requeued"] == 1
    assert redis_double.llen(pkey) == 1


# ════════════════════════════════════════════════════════════════════
# Safety — live DLQ untouched
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_poison_drain_never_touches_live_dlq(redis_double):
    """The poison drain MUST only ever read/write the
    `dlq:<key>:poison` list. The live `dlq:<key>` list is the
    reconciler's responsibility — touching it from the operator
    surface would create a race."""
    live_key = "dlq:failsafe_audit"
    pkey = dlq._poison_key(live_key)
    redis_double.lists[live_key] = [
        json.dumps({"live": True, "i": i}) for i in range(5)
    ]
    redis_double.lists[pkey] = [
        json.dumps({"poison": True, "_attempts": 3}),
    ]
    await dlq.drain_poison_list(live_key, replay=False)
    # Live DLQ unchanged.
    assert redis_double.llen(live_key) == 5
    # Poison drained.
    assert redis_double.llen(pkey) == 0


@pytest.mark.asyncio
async def test_drain_empty_poison_returns_zero(redis_double):
    """Empty poison → attempted=0. No errors, no side effects."""
    out = await dlq.drain_poison_list("dlq:failsafe_audit", replay=False)
    assert out["attempted"] == 0
    assert out["discarded"] == 0
    assert out["items"] == []


@pytest.mark.asyncio
async def test_drain_redis_unavailable_returns_safe_shape(monkeypatch):
    """Redis-down must not raise — degrades to a shape with an
    explicit `error` field. The UI can surface this without
    crashing the chip."""
    monkeypatch.setattr(
        "app.services.redis_service._get_client", lambda: None,
    )
    out = await dlq.drain_poison_list(
        "dlq:failsafe_audit", replay=False,
    )
    assert out["attempted"] == 0
    assert out["error"] == "redis_unavailable"
