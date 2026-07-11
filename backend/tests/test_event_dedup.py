"""Tests for NISCH-005 generic event dedup gate."""
from __future__ import annotations

import time

import pytest

from app.services import event_dedup


@pytest.fixture(autouse=True)
def _force_local_path(monkeypatch):
    # Exercise the local-LRU branch deterministically.
    monkeypatch.setattr(
        "app.services.event_dedup.redis_service.is_available", lambda: False
    )
    event_dedup.reset_local()
    yield
    event_dedup.reset_local()


# ── Happy path ──────────────────────────────────────────────────────
def test_first_emit_passes():
    assert event_dedup.should_emit("voice_distress", "user-1", cooldown_s=10) is True


def test_second_emit_in_cooldown_blocked():
    assert event_dedup.should_emit("voice_distress", "user-1", cooldown_s=10) is True
    assert event_dedup.should_emit("voice_distress", "user-1", cooldown_s=10) is False


def test_emit_after_cooldown_passes(monkeypatch):
    base = [time.time()]
    monkeypatch.setattr(event_dedup.time, "time", lambda: base[0])
    assert event_dedup.should_emit("sos", "user-1", cooldown_s=5) is True
    base[0] += 6
    assert event_dedup.should_emit("sos", "user-1", cooldown_s=5) is True


def test_different_kinds_dont_collide():
    assert event_dedup.should_emit("voice_distress", "user-1", cooldown_s=30) is True
    assert event_dedup.should_emit("sos",            "user-1", cooldown_s=30) is True


def test_different_keys_dont_collide():
    assert event_dedup.should_emit("voice_distress", "user-1", cooldown_s=30) is True
    assert event_dedup.should_emit("voice_distress", "user-2", cooldown_s=30) is True


# ── Bypass conditions ───────────────────────────────────────────────
@pytest.mark.parametrize("bad_key", [None, "", "  "])
def test_empty_key_bypasses_dedup(bad_key):
    # Both calls should pass — no dedup applies.
    assert event_dedup.should_emit("sos", bad_key, cooldown_s=30) is True
    assert event_dedup.should_emit("sos", bad_key, cooldown_s=30) is True


def test_zero_cooldown_bypasses_dedup():
    assert event_dedup.should_emit("sos", "user-1", cooldown_s=0) is True
    assert event_dedup.should_emit("sos", "user-1", cooldown_s=0) is True


def test_negative_cooldown_bypasses_dedup():
    assert event_dedup.should_emit("sos", "user-1", cooldown_s=-1) is True
    assert event_dedup.should_emit("sos", "user-1", cooldown_s=-1) is True


# ── Reset semantics ─────────────────────────────────────────────────
def test_reset_local_clears_all():
    event_dedup.should_emit("sos", "user-1", cooldown_s=30)
    event_dedup.reset_local()
    assert event_dedup.should_emit("sos", "user-1", cooldown_s=30) is True


def test_reset_local_targeted_clears_subset():
    event_dedup.should_emit("sos", "user-1", cooldown_s=30)
    event_dedup.should_emit("sos", "user-2", cooldown_s=30)
    event_dedup.reset_local(kind="sos", key="user-1")
    # user-1 cleared — re-emit allowed; user-2 still blocked.
    assert event_dedup.should_emit("sos", "user-1", cooldown_s=30) is True
    assert event_dedup.should_emit("sos", "user-2", cooldown_s=30) is False


# ── Robustness ──────────────────────────────────────────────────────
def test_redis_failure_falls_back_to_local(monkeypatch):
    # Force redis_service.is_available True but pretend the client throws.
    class _BoomClient:
        def set(self, *a, **kw):
            raise RuntimeError("simulated upstream blip")

    monkeypatch.setattr(
        "app.services.event_dedup.redis_service.is_available", lambda: True
    )
    monkeypatch.setattr(
        "app.services.event_dedup.redis_service._get_client", lambda: _BoomClient()
    )
    # Local fallback still gives correct dedup behavior.
    assert event_dedup.should_emit("sos", "user-1", cooldown_s=30) is True
    assert event_dedup.should_emit("sos", "user-1", cooldown_s=30) is False
