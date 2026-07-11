"""Per-account login backoff (defense-in-depth on top of slowapi IP limiter).

Why this exists
---------------
slowapi gives us per-IP rate limiting. A real attacker rotates IPs.
A real *defender* needs to protect THE ACCOUNT under attack — not the
infra. This module tracks failed login attempts per email in Redis
and enforces progressive lockouts:

    5 fails  → 30 second lock
    10 fails → 2 minute lock
    15 fails → 15 minute lock

Reset on successful login. Best-effort: if Redis is down or any call
fails, we fail OPEN (warn + allow login). Locking out legitimate users
because Redis is sick is a worse outcome than briefly relaxing the
defense layer — we still have slowapi's IP limiter underneath.
"""
from __future__ import annotations

import logging
from typing import NamedTuple

from app.services.redis_service import _get_client

logger = logging.getLogger(__name__)

# Progressive thresholds — (failure_count, lockout_seconds).
# Sorted descending by count so we pick the most severe matching tier.
_TIERS: list[tuple[int, int]] = [
    (15, 15 * 60),   # 15 fails → 15 minutes
    (10, 2 * 60),    # 10 fails → 2 minutes
    (5,  30),        # 5 fails  → 30 seconds
]

# Counter window — failures older than this naturally fall off.
# 24h is long enough to catch slow-burn distributed attacks but short
# enough that a forgetful user isn't locked out forever after a
# password change.
_COUNTER_TTL_SEC = 24 * 3600

_COUNTER_PREFIX = "login_fail"
_LOCK_PREFIX    = "login_lock"


class LockState(NamedTuple):
    locked: bool
    retry_after: int       # seconds until unlock; 0 if not locked
    fail_count: int        # current cumulative failures
    tier_seconds: int      # the lockout duration that would apply NOW


def _norm(email: str) -> str:
    return (email or "").strip().lower()


def _ckey(email: str) -> str:
    return f"{_COUNTER_PREFIX}:{_norm(email)}"


def _lkey(email: str) -> str:
    return f"{_LOCK_PREFIX}:{_norm(email)}"


def _tier_for(fails: int) -> int:
    """Return the lockout duration (seconds) the current failure
    count earns. 0 if below the lowest tier."""
    for threshold, seconds in _TIERS:
        if fails >= threshold:
            return seconds
    return 0


def check_lock(email: str) -> LockState:
    """Read-only: is this account currently locked? Best-effort —
    on Redis failure returns "not locked" (fail-open)."""
    if not email:
        return LockState(False, 0, 0, 0)
    c = _get_client()
    if c is None:
        return LockState(False, 0, 0, 0)
    try:
        ttl = c.ttl(_lkey(email))
        # Redis TTL semantics:
        #   -2 → key doesn't exist (no lock)
        #   -1 → key has no TTL    (treat as not locked, defensive)
        #   >0 → seconds remaining
        if isinstance(ttl, int) and ttl > 0:
            count_raw = c.get(_ckey(email))
            count = int(count_raw) if count_raw else 0
            return LockState(True, ttl, count, _tier_for(count))
        count_raw = c.get(_ckey(email))
        count = int(count_raw) if count_raw else 0
        return LockState(False, 0, count, _tier_for(count))
    except Exception as e:
        logger.warning(f"[login_backoff] check_lock failed (fail-open): {e}")
        return LockState(False, 0, 0, 0)


def record_failure(email: str) -> LockState:
    """Increment the failure counter and arm a lock if a tier is hit.
    Returns the new state. Best-effort."""
    if not email:
        return LockState(False, 0, 0, 0)
    c = _get_client()
    if c is None:
        return LockState(False, 0, 0, 0)
    try:
        ckey = _ckey(email)
        # INCR + EXPIRE in a pipeline — close enough to atomic for
        # our purposes (we don't care about a 1-tick race).
        pipe = c.pipeline()
        pipe.incr(ckey)
        pipe.expire(ckey, _COUNTER_TTL_SEC)
        results = pipe.execute()
        new_count = int(results[0]) if results else 0
        tier_sec = _tier_for(new_count)
        if tier_sec > 0:
            # Arm/refresh the lock with the tier's TTL. Using SET
            # with EX so an existing shorter lock gets escalated.
            c.set(_lkey(email), "1", ex=tier_sec)
            logger.warning(
                f"[login_backoff] LOCK email={_norm(email)} "
                f"fails={new_count} for {tier_sec}s"
            )
            return LockState(True, tier_sec, new_count, tier_sec)
        return LockState(False, 0, new_count, 0)
    except Exception as e:
        logger.warning(f"[login_backoff] record_failure failed (fail-open): {e}")
        return LockState(False, 0, 0, 0)


def reset(email: str) -> None:
    """Clear counter + lock on successful login. Best-effort."""
    if not email:
        return
    c = _get_client()
    if c is None:
        return
    try:
        c.delete(_ckey(email), _lkey(email))
    except Exception as e:
        logger.warning(f"[login_backoff] reset failed: {e}")
