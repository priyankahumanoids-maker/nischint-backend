"""
Rate Limiter — IP-based request throttling using slowapi.

Uses Redis (Upstash) as the primary distributed hit-counter store.

**Memory fallback (P0 — 2026-05-30 DR drill)**

slowapi's `in_memory_fallback_enabled=True` activates a built-in fallback path:
when the Redis backend raises any exception during a rate-check, the limiter
sets `_storage_dead = True`, logs once, and retries the check against a
per-process `MemoryStorage`. It periodically probes Redis (exponential backoff
inside `__should_check_backend`) and flips back to Redis the moment a
`check()` succeeds.

Why this matters: without the fallback, an Upstash blip turned every
rate-limited endpoint into HTTP 500 — including `/api/auth/login`,
`/api/auth/forgot-password`, and `/api/sos/trigger`. The 2026-05-30 DR drill
reproduced this with `REDIS_URL=redis://invalid-host` and observed login 500s
within milliseconds. After this fix the same drill returns 200, with a single
`WARN slowapi ... falling back to in-memory storage` log line and rate-limit
budgets enforced per-process (slightly weaker than Redis-shared budgets, but
that's the correct trade-off when Redis is unreachable).
"""
import os
import logging
from slowapi import Limiter
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)

_redis_url = os.environ.get("REDIS_URL", "")


def _build_limiter() -> Limiter:
    # Common kwargs across all branches — `in_memory_fallback_enabled=True`
    # is the P0 fix. Keep `swallow_errors=False` so we still log loudly on
    # the *first* storage failure (the fallback path also writes a WARN), and
    # so rate-limit exceeded responses still raise correctly.
    common = dict(
        key_func=get_remote_address,
        in_memory_fallback_enabled=True,
    )
    if _redis_url:
        try:
            limiter = Limiter(storage_uri=_redis_url, **common)
            logger.info(
                "Rate limiter: Redis-backed (%s) with in-memory fallback armed",
                _redis_url.split("@")[-1] if "@" in _redis_url else "connected",
            )
            return limiter
        except Exception as e:
            # Limiter() itself rarely throws (the underlying connection is
            # lazy), but if it does — e.g. malformed URI — fall through to a
            # pure in-memory limiter so the API still boots.
            logger.warning("Rate limiter: Redis init failed (%s), using in-memory only", e)
    else:
        logger.info("Rate limiter: in-memory only (REDIS_URL not set)")
    return Limiter(**common)


limiter = _build_limiter()
