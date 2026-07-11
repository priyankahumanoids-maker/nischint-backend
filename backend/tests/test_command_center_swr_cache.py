"""Tests for the per-user Command Center SWR cache.

Locks in the contracts:
  1. Cold (no cache) → compute + write + return state="cold".
  2. Fresh (<10s old) → cache hit, state="fresh", NO background refresh.
  3. Stale (10–60s old) → cache hit, state="stale" or "stale-refreshing",
     background refresh task spawned (when no other is already running).
  4. ?fresh=1 → bypass cache + compute + write.
  5. Refresh lock prevents thundering herd — only one background task at a time.
"""
from __future__ import annotations

import asyncio
import uuid as uuid_mod
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api import command_center_unified as cc


UID = uuid_mod.uuid4()
UID_STR = str(UID)


def _mock_payload(ts: datetime, user_name: str = "Test Child") -> dict:
    return {
        "version": "v1",
        "timestamp": ts.isoformat(),
        "user_id": UID_STR,
        "user": {"id": UID_STR, "full_name": user_name, "email": "t@e", "role": "user", "phone": None},
        "risk": None,
        "baseline": None,
        "digital_twin": {},
        "predictions": [],
        "risk_history": [],
        "live_location": None,
        "active_event": None,
        "environment": {},
        "motion_telemetry": {},
        "_degraded_sections": [],
    }


@pytest.fixture
def _mock_operator():
    u = MagicMock()
    u.role = "operator"
    u.id = uuid_mod.uuid4()
    return u


# ────────────────────────────────────────────────────────────
# 1. Cold path — no cache, compute synchronously, write cache
# ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cold_path_computes_and_writes_cache(_mock_operator):
    fresh_payload = _mock_payload(datetime.now(timezone.utc))

    with patch.object(cc, "_compute_command_center_user_payload", new=AsyncMock(return_value=fresh_payload)), \
         patch("app.services.redis_service.get_json", return_value=None), \
         patch("app.services.redis_service.set_json") as mock_set:
        result = await cc.get_command_center_user(
            user_id=UID_STR, fresh=False, _operator=_mock_operator,
        )

    assert result["_cache"]["hit"] is False
    assert result["_cache"]["state"] == "cold"
    assert mock_set.called, "cold path must persist payload to Redis"
    args, kwargs = mock_set.call_args
    assert kwargs.get("ttl") == 60, "STALE_TTL_S must be 60s, got {}".format(kwargs.get("ttl"))


# ────────────────────────────────────────────────────────────
# 2. Fresh path — cache <10s old, return immediately, no refresh
# ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fresh_cache_returns_without_compute(_mock_operator):
    cached = _mock_payload(datetime.now(timezone.utc) - timedelta(seconds=3))

    compute_mock = AsyncMock(side_effect=AssertionError("should NOT be called on fresh"))
    with patch.object(cc, "_compute_command_center_user_payload", new=compute_mock), \
         patch("app.services.redis_service.get_json", return_value=cached), \
         patch("app.services.redis_service.set_json"):
        result = await cc.get_command_center_user(
            user_id=UID_STR, fresh=False, _operator=_mock_operator,
        )

    assert result["_cache"]["hit"] is True
    assert result["_cache"]["state"] == "fresh"
    assert result["_cache"]["age_s"] < 10
    compute_mock.assert_not_called()


# ────────────────────────────────────────────────────────────
# 3. Stale path — cache 10-60s old, serve + spawn background refresh
# ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stale_cache_serves_immediately_and_spawns_refresh(_mock_operator):
    """Returns the stale payload synchronously. A background refresh
    task is created — we don't await it (it would defeat the purpose)
    but we verify the create_task happened."""
    cached = _mock_payload(datetime.now(timezone.utc) - timedelta(seconds=25))

    # Redis lock acquisition succeeds (this is the first stale hit).
    mock_redis = MagicMock()
    mock_redis.set.return_value = True

    refresh_mock = AsyncMock()
    with patch.object(cc, "_refresh_command_center_user_cache", new=refresh_mock), \
         patch.object(cc, "_compute_command_center_user_payload", new=AsyncMock()), \
         patch("app.services.redis_service.get_json", return_value=cached), \
         patch("app.services.redis_service._get_client", return_value=mock_redis), \
         patch("app.services.redis_service.set_json"):
        result = await cc.get_command_center_user(
            user_id=UID_STR, fresh=False, _operator=_mock_operator,
        )

    assert result["_cache"]["hit"] is True
    assert result["_cache"]["state"] == "stale-refreshing"
    assert 10 <= result["_cache"]["age_s"] < 60
    # The lock was acquired with the SET ... NX EX 30 pattern.
    set_call = mock_redis.set.call_args
    assert set_call.kwargs.get("nx") is True
    assert set_call.kwargs.get("ex") == 30

    # Allow the just-created task to run.
    await asyncio.sleep(0)
    refresh_mock.assert_called_once()


@pytest.mark.asyncio
async def test_stale_lock_already_held_skips_refresh_spawn(_mock_operator):
    """If another worker is already refreshing, we just serve stale
    without spawning a duplicate refresh task."""
    cached = _mock_payload(datetime.now(timezone.utc) - timedelta(seconds=25))
    mock_redis = MagicMock()
    mock_redis.set.return_value = False  # lock NOT acquired

    refresh_mock = AsyncMock()
    with patch.object(cc, "_refresh_command_center_user_cache", new=refresh_mock), \
         patch("app.services.redis_service.get_json", return_value=cached), \
         patch("app.services.redis_service._get_client", return_value=mock_redis), \
         patch("app.services.redis_service.set_json"):
        result = await cc.get_command_center_user(
            user_id=UID_STR, fresh=False, _operator=_mock_operator,
        )

    assert result["_cache"]["state"] == "stale"
    # No background task was created.
    await asyncio.sleep(0)
    refresh_mock.assert_not_called()


# ────────────────────────────────────────────────────────────
# 4. ?fresh=1 bypasses cache
# ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fresh_query_param_bypasses_cache(_mock_operator):
    """Even if a fresh cache exists, ?fresh=1 forces a recompute."""
    cached = _mock_payload(datetime.now(timezone.utc) - timedelta(seconds=1))
    computed = _mock_payload(datetime.now(timezone.utc), user_name="Recomputed Child")

    get_mock = MagicMock(return_value=cached)
    compute_mock = AsyncMock(return_value=computed)

    with patch.object(cc, "_compute_command_center_user_payload", new=compute_mock), \
         patch("app.services.redis_service.get_json", new=get_mock), \
         patch("app.services.redis_service.set_json"):
        result = await cc.get_command_center_user(
            user_id=UID_STR, fresh=True, _operator=_mock_operator,
        )

    assert result["_cache"]["state"] == "cold"
    assert result["user"]["full_name"] == "Recomputed Child"
    get_mock.assert_not_called()  # ?fresh=1 means we don't even peek at the cache
    compute_mock.assert_called_once()


# ────────────────────────────────────────────────────────────
# 5. Background refresh worker
# ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_background_refresh_writes_cache_and_releases_lock():
    """Refresh task computes, writes Redis, and clears the refresh lock."""
    fresh = _mock_payload(datetime.now(timezone.utc))
    mock_redis = MagicMock()

    with patch.object(cc, "_compute_command_center_user_payload", new=AsyncMock(return_value=fresh)), \
         patch("app.services.redis_service.set_json") as mock_set, \
         patch("app.services.redis_service._get_client", return_value=mock_redis):
        await cc._refresh_command_center_user_cache(
            UID, "command_center_user", f"{UID_STR}:v1", 10, 60,
        )

    assert mock_set.called
    # The lock-release happened.
    mock_redis.delete.assert_called_once()
    lock_key = mock_redis.delete.call_args.args[0]
    assert lock_key.endswith(":refreshing")


@pytest.mark.asyncio
async def test_background_refresh_releases_lock_even_on_failure():
    """If the recompute crashes, the lock must STILL be released
    so the next stale hit can trigger a fresh attempt."""
    mock_redis = MagicMock()
    with patch.object(cc, "_compute_command_center_user_payload",
                      new=AsyncMock(side_effect=RuntimeError("boom"))), \
         patch("app.services.redis_service._get_client", return_value=mock_redis), \
         patch("app.services.redis_service.set_json"):
        await cc._refresh_command_center_user_cache(
            UID, "command_center_user", f"{UID_STR}:v1", 10, 60,
        )

    mock_redis.delete.assert_called_once()
