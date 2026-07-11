# User Cache — short-window cache for `get_current_user` to slash the
# ~2.2s Mumbai pooler round-trip every authenticated endpoint pays.
#
# Strategy
# --------
# • Cache key:    `auth_user:{sub}`  (sub == local-UUID OR Cognito sub string).
# • TTL:          30 seconds.  Role / disable changes propagate within one
#                 TTL window. Login flow invalidates explicitly.
# • Storage:      Redis when available, in-process LRU fallback otherwise.
# • Payload:      Plain dict of scalar User fields. Reconstituted to an
#                 *unattached* SQLAlchemy User instance on read so callers
#                 see the exact same object shape they had before.
#
# Safety
# ------
# Callers in `app/api/*` only read scalar attributes (id, email, role,
# full_name, phone, facility_id, last_known_*). None refresh / mutate
# / add the current_user back into a session. An unattached ORM instance
# is therefore a drop-in.

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.models.user import User
from app.services import redis_service

logger = logging.getLogger(__name__)

USER_CACHE_NAMESPACE = "auth_user"
USER_CACHE_TTL_S = 30

# In-process fallback for when Redis is unavailable. Kept intentionally
# small + short-lived so a Redis outage doesn't accidentally pin stale
# auth state for long.
_MEM_CACHE_TTL_S = 10
_MEM_CACHE_MAX = 1024
_mem_cache: dict[str, tuple[float, dict]] = {}


def _user_to_dict(user: User) -> dict[str, Any]:
    return {
        "id":                 str(user.id),
        "email":              user.email,
        "password_hash":      user.password_hash,
        "cognito_sub":        user.cognito_sub,
        "role":               user.role,
        "facility_id":        user.facility_id,
        "phone":              user.phone,
        "full_name":          user.full_name,
        "is_active":          bool(user.is_active),
        "preferred_channels": list(user.preferred_channels) if user.preferred_channels else ["email"],
        "created_at":         user.created_at.isoformat() if user.created_at else None,
        "last_known_lat":     user.last_known_lat,
        "last_known_lng":     user.last_known_lng,
        "last_known_at":      user.last_known_at.isoformat() if user.last_known_at else None,
    }


def _dict_to_user(data: dict[str, Any]) -> User:
    """Reconstruct an unattached User ORM instance from a cached dict."""
    def _parse_dt(v):
        if not v:
            return None
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            return None

    user = User()
    user.id                 = UUID(data["id"])
    user.email              = data["email"]
    user.password_hash      = data["password_hash"]
    user.cognito_sub        = data.get("cognito_sub")
    user.role               = data.get("role") or "guardian"
    user.facility_id        = data.get("facility_id")
    user.phone              = data.get("phone")
    user.full_name          = data.get("full_name")
    user.is_active          = bool(data.get("is_active", True))
    user.preferred_channels = data.get("preferred_channels") or ["email"]
    user.created_at         = _parse_dt(data.get("created_at")) or datetime.now(timezone.utc)
    user.last_known_lat     = data.get("last_known_lat")
    user.last_known_lng     = data.get("last_known_lng")
    user.last_known_at      = _parse_dt(data.get("last_known_at"))
    return user


def _mem_get(key: str) -> dict | None:
    entry = _mem_cache.get(key)
    if not entry:
        return None
    ts, data = entry
    if (time.time() - ts) > _MEM_CACHE_TTL_S:
        _mem_cache.pop(key, None)
        return None
    return data


def _mem_set(key: str, data: dict) -> None:
    # Cheap LRU-ish eviction — drop the oldest if we exceed budget.
    if len(_mem_cache) >= _MEM_CACHE_MAX:
        oldest_key = min(_mem_cache, key=lambda k: _mem_cache[k][0])
        _mem_cache.pop(oldest_key, None)
    _mem_cache[key] = (time.time(), data)


def get_cached_user(sub: str) -> User | None:
    """Return a fresh unattached User instance for the given token sub,
    or None if no fresh cache entry exists.

    Lookup order is in-process mem first (sub-ms), then Redis (10–100ms
    on a remote Redis like Upstash). The mem path covers the hot per-
    request case; Redis covers cross-process consistency between API
    workers and the scheduler runner.
    """
    if not sub:
        return None

    # 1) In-process fast path (sub-ms)
    data = _mem_get(sub)

    # 2) Redis (cross-process)
    if data is None:
        try:
            data = redis_service.get_json(USER_CACHE_NAMESPACE, sub)
            if data is not None:
                # Replicate into mem so the next call in this process
                # is also a sub-ms hit.
                _mem_set(sub, data)
        except Exception as e:
            logger.debug(f"user_cache redis read failed [{sub}]: {e}")

    if not data:
        return None

    try:
        return _dict_to_user(data)
    except Exception as e:
        logger.warning(f"user_cache reconstruction failed [{sub}]: {e}")
        return None


def cache_user(sub: str, user: User) -> None:
    """Cache a fresh User payload under the token sub key (best-effort)."""
    if not sub or user is None:
        return
    try:
        data = _user_to_dict(user)
    except Exception as e:
        logger.warning(f"user_cache serialize failed [{sub}]: {e}")
        return

    # In-process first (always).
    _mem_set(sub, data)

    # Then Redis (may no-op on outage).
    try:
        redis_service.set_json(USER_CACHE_NAMESPACE, sub, data, ttl=USER_CACHE_TTL_S)
    except Exception as e:
        logger.debug(f"user_cache redis write failed [{sub}]: {e}")


def invalidate_user(sub: str) -> None:
    """Drop the cache entry for a sub (called on role mutation / logout)."""
    if not sub:
        return
    _mem_cache.pop(sub, None)
    try:
        redis_service.delete_key(USER_CACHE_NAMESPACE, sub)
    except Exception:
        pass


def invalidate_user_keys(*subs: str) -> None:
    """Invalidate multiple sub keys (e.g. local UUID + cognito_sub)."""
    for s in subs:
        if s:
            invalidate_user(s)
