"""System-health transition history — unit tests.

Locks the four invariants the user mandated for the SSE replay tail:
  1. Capped list — `LPUSH` + `LTRIM` keeps at most 10 entries.
  2. Chronological order on read (oldest first).
  3. Unknown sources are silently dropped (no unbounded keys).
  4. The same envelope format flows through — no schema mutation.

Plus a behavioural test confirming the live emitters
(`_emit_sachet_health_delta`, `_emit_v2_parity_delta`) hook into the
history layer so an operator-side replay catches them up.
"""
from __future__ import annotations

import json

import pytest

from app.services import system_health_history as shh


class _FakeRedis:
    """In-memory Redis double — minimal LPUSH / LTRIM / LRANGE /
    DELETE so we can drive the contract without spinning a real
    server."""

    def __init__(self):
        self.lists: dict[str, list[str]] = {}

    def lpush(self, key, *values):
        # Redis LPUSH inserts each value individually at the head.
        arr = self.lists.setdefault(key, [])
        for v in values:
            arr.insert(0, v)
        return len(arr)

    def ltrim(self, key, start, end):
        arr = self.lists.get(key)
        if arr is None:
            return True
        # Redis LTRIM is inclusive on both ends.
        self.lists[key] = arr[start:end + 1]
        return True

    def lrange(self, key, start, end):
        arr = self.lists.get(key) or []
        return arr[start:end + 1]

    def delete(self, *keys):
        n = 0
        for k in keys:
            if k in self.lists:
                del self.lists[k]
                n += 1
        return n


@pytest.fixture
def fake_redis(monkeypatch):
    fr = _FakeRedis()
    monkeypatch.setattr(shh.redis_service, "_get_client", lambda: fr)
    yield fr


def _envelope(seq: int, source: str = "sachet_health") -> dict:
    """Build a payload shaped exactly like the live WS broadcast."""
    return {
        "type":     "system_health_delta",
        "ts":       1700000000 + seq,
        "iso":      f"2026-05-01T00:00:{seq:02d}+00:00",
        "source":   source,
        "severity": "warning",
        source: {"state": "stale", "seq": seq},
    }


# ── Capped list invariant ────────────────────────────────────────

def test_record_caps_at_history_cap(fake_redis):
    """Append 25 entries; the underlying list must never exceed 10."""
    for i in range(25):
        ok = shh.record_transition("sachet_health", _envelope(i))
        assert ok is True
    key = shh._key("sachet_health")
    assert len(fake_redis.lists[key]) == shh.HISTORY_CAP == 10


def test_record_unknown_source_silently_dropped(fake_redis):
    """Typo'd source must NOT create an unbounded Redis key."""
    ok = shh.record_transition("typo_source", _envelope(0))
    assert ok is False
    # No key should have been created.
    assert all("typo_source" not in k for k in fake_redis.lists)


# ── Read contract: chronological, untouched envelope ─────────────

def test_get_recent_returns_chronological_order(fake_redis):
    """Oldest first — operator narrative reads naturally on replay."""
    for i in range(5):
        shh.record_transition("v2_parity", _envelope(i, source="v2_parity"))
    out = shh.get_recent_transitions("v2_parity", limit=10)
    assert len(out) == 5
    # Each event's nested seq must be ascending (oldest → newest).
    seqs = [e["v2_parity"]["seq"] for e in out]
    assert seqs == sorted(seqs)
    assert seqs == [0, 1, 2, 3, 4]


def test_get_recent_envelope_is_byte_identical(fake_redis):
    """The replayed payload must match what the live WS would deliver
    — no schema transformation. Operators see the same event whether
    it came over WS live or over the SSE replay tail."""
    original = _envelope(7, source="sachet_health")
    shh.record_transition("sachet_health", original)
    out = shh.get_recent_transitions("sachet_health", limit=10)
    assert len(out) == 1
    # JSON round-trip is exact (default=str on the write side has no
    # effect on plain JSON-safe scalars).
    assert out[0] == original


def test_get_recent_unknown_source_returns_empty(fake_redis):
    assert shh.get_recent_transitions("typo_source") == []


def test_get_recent_caps_to_history_cap_on_read(fake_redis):
    """Even if a misbehaving emitter bypassed LTRIM, the read API
    must never deliver more than HISTORY_CAP entries to operators."""
    # Manually overflow the underlying list (bypassing LTRIM).
    key = shh._key("sachet_health")
    fake_redis.lists[key] = [json.dumps(_envelope(i)) for i in range(20)]
    out = shh.get_recent_transitions("sachet_health")
    assert len(out) == shh.HISTORY_CAP


# ── get_all_recent_transitions shape contract ────────────────────

def test_get_all_recent_returns_stable_shape(fake_redis):
    """SSE endpoint relies on every known source appearing in the
    dict — empty lists for cold sources, not missing keys."""
    out = shh.get_all_recent_transitions()
    for src in shh.KNOWN_SOURCES:
        assert src in out
        assert out[src] == []


def test_get_all_recent_after_writes(fake_redis):
    shh.record_transition("v2_parity", _envelope(0, source="v2_parity"))
    shh.record_transition("sachet_health", _envelope(0))
    out = shh.get_all_recent_transitions()
    assert len(out["v2_parity"]) == 1
    assert len(out["sachet_health"]) == 1


# ── Hook integration — live emitters write history ───────────────

def test_sachet_emitter_records_history(fake_redis, monkeypatch):
    """The sachet pre-warmer's transition broadcaster must call
    `record_transition` so the SSE replay catches every transition.
    Without this hook the replay tail is silently empty."""
    from app.services.external_signals import sachet_prewarmer as sp

    # Patch broadcaster import to a no-op (we only care about history).
    class _NoBroadcaster:
        async def broadcast_to_operators(self, *a, **kw):
            return None

    import app.services.event_broadcaster as eb
    monkeypatch.setattr(eb, "broadcaster", _NoBroadcaster())

    sp._emit_sachet_health_delta(
        prior_state="healthy",
        new_state="degraded",
        telemetry={
            "cache_age_seconds":  900,
            "parse_failure_rate": 0.30,
            "active_alert_count": 0,
            "last_success_ts":    "2026-05-01T00:00:00+00:00",
        },
    )
    out = shh.get_recent_transitions("sachet_health")
    assert len(out) == 1
    assert out[0]["source"] == "sachet_health"
    assert out[0]["sachet_health"]["state"] == "degraded"
    assert out[0]["sachet_health"]["previous_state"] == "healthy"


def test_v2_emitter_records_history(fake_redis, monkeypatch):
    """The V2 shadow's transition broadcaster must also feed the
    history list — operators reloading mid-incident should see V2
    parity transitions in the replay."""
    from app.services import alert_trigger_v2_shadow as v2s

    class _NoBroadcaster:
        async def broadcast_to_operators(self, *a, **kw):
            return None

    import app.services.event_broadcaster as eb
    monkeypatch.setattr(eb, "broadcaster", _NoBroadcaster())

    v2s._emit_v2_parity_delta(
        kind="help_request",
        transition={
            "from": "in_parity", "to": "critical",
            "reason": "test critical regression",
        },
        diagnostic_for_kind={
            "total": 12, "critical_count": 3, "improvement_count": 0,
            "match_pct": 75.0, "fanout_delta_avg": 0.2,
            "safety": {"auto_disabled": False},
        },
    )
    out = shh.get_recent_transitions("v2_parity")
    assert len(out) == 1
    # The storage bucket is `v2_parity` (operator-facing taxonomy);
    # the envelope's own `source` field is `alert_v2` (the WS routing
    # key the frontend chip already dispatches on). Both are
    # preserved on replay.
    assert out[0]["source"] == "alert_v2"
    assert out[0]["v2_parity"]["tier"] == "critical"
