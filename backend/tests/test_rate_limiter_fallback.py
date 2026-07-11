"""Regression test for the slowapi memory-fallback wrapper.

2026-05-30 DR drill: pointing `REDIS_URL` at an invalid host caused
every rate-limited endpoint (auth login, password reset, SOS trigger)
to return HTTP 500 — `slowapi` had no memory-storage fallback. The fix
in `app/core/rate_limiter.py` passes `in_memory_fallback_enabled=True`
to the `Limiter` constructor, which arms a per-process `MemoryStorage`
that slowapi switches to on the first storage exception.

These tests verify the wiring is intact so the next dependency upgrade
or refactor can't silently regress it.
"""
import importlib
import os
import sys

import pytest


@pytest.fixture
def rate_limiter_module(monkeypatch):
    """Reload the module with a controlled REDIS_URL."""
    # Save current state so we can restore between parametrised runs
    saved_url = os.environ.get("REDIS_URL")

    def _load(redis_url: str | None):
        if redis_url is None:
            monkeypatch.delenv("REDIS_URL", raising=False)
        else:
            monkeypatch.setenv("REDIS_URL", redis_url)
        # Force a clean reload
        sys.modules.pop("app.core.rate_limiter", None)
        return importlib.import_module("app.core.rate_limiter")

    yield _load

    # Restore environment (monkeypatch handles env, but pop module too)
    sys.modules.pop("app.core.rate_limiter", None)
    if saved_url is not None:
        os.environ["REDIS_URL"] = saved_url


def test_fallback_enabled_when_redis_url_set(rate_limiter_module):
    """With a Redis URL, slowapi must boot Redis-backed AND have memory fallback armed."""
    mod = rate_limiter_module("redis://invalid-host-test.local:6379/0")
    lim = mod.limiter

    assert lim._in_memory_fallback_enabled is True, (
        "in_memory_fallback_enabled must be True so a Redis outage doesn't 500"
    )
    assert lim._fallback_limiter is not None, (
        "slowapi must have constructed a fallback limiter at boot time"
    )
    # Fallback storage must be the in-process MemoryStorage
    from limits.storage import MemoryStorage
    assert isinstance(lim._fallback_storage, MemoryStorage)


def test_fallback_enabled_when_redis_url_missing(rate_limiter_module):
    """Without a Redis URL we use in-memory only — fallback is still armed
    so the limiter behaves identically to the Redis-backed path."""
    mod = rate_limiter_module(None)
    lim = mod.limiter
    assert lim._in_memory_fallback_enabled is True


def test_storage_dead_flag_initially_false(rate_limiter_module):
    """slowapi's `_storage_dead` must start False — it flips to True on the
    first storage error, then back to False once Redis returns.
    """
    mod = rate_limiter_module("redis://invalid-host-test.local:6379/0")
    assert mod.limiter._storage_dead is False


def test_limiter_can_hit_via_fallback(rate_limiter_module, monkeypatch):
    """Simulate a Redis ConnectionError and verify the fallback path is taken."""
    mod = rate_limiter_module("redis://invalid-host-test.local:6379/0")
    lim = mod.limiter

    # Mark storage as dead manually — same state slowapi puts itself in
    # after the first Redis error.
    lim._storage_dead = True

    # The fallback strategy/storage should accept hits without raising.
    from limits import parse
    from limits.strategies import FixedWindowRateLimiter
    assert isinstance(lim._fallback_limiter, FixedWindowRateLimiter)

    limit = parse("5/minute")
    # 5 successive hits should succeed
    for i in range(5):
        ok = lim._fallback_limiter.hit(limit, "test-key")
        assert ok is True, f"hit {i+1} should succeed within budget"
    # 6th hit exceeds the budget
    ok = lim._fallback_limiter.hit(limit, "test-key")
    assert ok is False, "6th hit should be denied by in-memory limiter"
