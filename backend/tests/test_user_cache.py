"""Unit tests for app.services.user_cache.

Locks the contract for the short-window auth cache that wraps
`get_current_user` to slash the ~2 s Mumbai pooler round-trip every
authenticated endpoint pays.
"""
import uuid
from datetime import datetime, timezone

import pytest

from app.models.user import User
from app.services import user_cache


def _make_user(**overrides) -> User:
    base = {
        "id": uuid.uuid4(),
        "email": "cache-test@example.com",
        "password_hash": "$bcrypt$dummy",
        "cognito_sub": None,
        "role": "guardian",
        "facility_id": None,
        "phone": "+15551234567",
        "full_name": "Cache Tester",
        "is_active": True,
        "preferred_channels": ["email", "push"],
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "last_known_lat": 19.076,
        "last_known_lng": 72.8777,
        "last_known_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
    }
    base.update(overrides)
    u = User()
    for k, v in base.items():
        setattr(u, k, v)
    return u


@pytest.fixture(autouse=True)
def _clear_mem_cache_between_tests():
    user_cache._mem_cache.clear()
    yield
    user_cache._mem_cache.clear()


def test_cache_round_trip_preserves_fields(monkeypatch):
    """A cached user reconstructs to the same scalar attributes."""
    # Force in-memory path so this test does not depend on Redis.
    monkeypatch.setattr(user_cache.redis_service, "set_json", lambda *a, **kw: False)
    monkeypatch.setattr(user_cache.redis_service, "get_json", lambda *a, **kw: None)

    original = _make_user(role="operator")
    sub = str(original.id)

    user_cache.cache_user(sub, original)
    restored = user_cache.get_cached_user(sub)

    assert restored is not None
    assert restored.id == original.id
    assert restored.email == original.email
    assert restored.role == "operator"
    assert restored.full_name == original.full_name
    assert restored.is_active is True
    assert restored.last_known_lat == pytest.approx(19.076)
    assert restored.last_known_lng == pytest.approx(72.8777)
    assert restored.preferred_channels == ["email", "push"]


def test_cache_miss_for_unknown_sub(monkeypatch):
    monkeypatch.setattr(user_cache.redis_service, "get_json", lambda *a, **kw: None)
    assert user_cache.get_cached_user("does-not-exist") is None


def test_invalidate_clears_entry(monkeypatch):
    monkeypatch.setattr(user_cache.redis_service, "set_json", lambda *a, **kw: False)
    monkeypatch.setattr(user_cache.redis_service, "get_json", lambda *a, **kw: None)
    monkeypatch.setattr(user_cache.redis_service, "delete_key", lambda *a, **kw: True)

    u = _make_user()
    sub = str(u.id)
    user_cache.cache_user(sub, u)
    assert user_cache.get_cached_user(sub) is not None

    user_cache.invalidate_user(sub)
    assert user_cache.get_cached_user(sub) is None


def test_redis_failure_falls_back_to_mem(monkeypatch):
    """Redis I/O failures must NEVER raise — fall back to mem cache."""
    def boom_set(*a, **kw): raise RuntimeError("redis down")
    def boom_get(*a, **kw): raise RuntimeError("redis down")
    monkeypatch.setattr(user_cache.redis_service, "set_json", boom_set)
    monkeypatch.setattr(user_cache.redis_service, "get_json", boom_get)

    u = _make_user()
    sub = str(u.id)
    user_cache.cache_user(sub, u)  # must not raise

    restored = user_cache.get_cached_user(sub)
    assert restored is not None
    assert restored.id == u.id


def test_mem_cache_ttl_eviction(monkeypatch):
    """Entries older than the in-process TTL are evicted on read."""
    monkeypatch.setattr(user_cache.redis_service, "get_json", lambda *a, **kw: None)
    monkeypatch.setattr(user_cache.redis_service, "set_json", lambda *a, **kw: False)

    u = _make_user()
    sub = str(u.id)
    user_cache.cache_user(sub, u)
    assert user_cache.get_cached_user(sub) is not None

    # Backdate the cached entry past the in-process TTL.
    ts, data = user_cache._mem_cache[sub]
    user_cache._mem_cache[sub] = (ts - (user_cache._MEM_CACHE_TTL_S + 1), data)

    assert user_cache.get_cached_user(sub) is None
    assert sub not in user_cache._mem_cache  # evicted on read


def test_unattached_user_has_no_sa_session():
    """Reconstructed user must not be attached to any SQLAlchemy session."""
    from sqlalchemy import inspect as sa_inspect
    u = _make_user()
    sub = str(u.id)
    user_cache.cache_user(sub, u)
    restored = user_cache.get_cached_user(sub)
    state = sa_inspect(restored)
    # Detached / transient — no session, no identity_key.
    assert state.session is None


def test_invalidate_user_keys_handles_blanks(monkeypatch):
    """Passing falsy / missing subs should be a no-op, not a crash."""
    monkeypatch.setattr(user_cache.redis_service, "delete_key", lambda *a, **kw: True)
    user_cache.invalidate_user_keys("", None, "x")  # must not raise
