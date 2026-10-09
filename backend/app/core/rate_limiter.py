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
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from slowapi import Limiter
from slowapi.util import get_remote_address
from redis.backoff import NoBackoff
from redis.retry import Retry

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
            # redis-py URL query options override kwargs. These three options
            # must not override the HTTP limiter's explicit short bounds.
            parsed = urlsplit(_redis_url)
            query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                     if k not in {"socket_connect_timeout", "socket_timeout", "retry_on_timeout"}]
            storage_uri = urlunsplit(parsed._replace(query=urlencode(query)))
            limiter = Limiter(
                storage_uri=storage_uri,
                storage_options={
                    "socket_connect_timeout": 1.0,
                    "socket_timeout": 1.0,
                    "retry_on_timeout": False,
                    "retry": Retry(NoBackoff(), 0),
                },
                **common,
            )
            logger.info(
                "Rate limiter: Redis-backed with bounded I/O and in-memory fallback armed",
            )
            return limiter
        except Exception as e:
            # Limiter() itself rarely throws (the underlying connection is
            # lazy), but if it does — e.g. malformed URI — fall through to a
            # pure in-memory limiter so the API still boots.
            logger.warning("Rate limiter: Redis init failed (%s), using in-memory only", type(e).__name__)
    else:
        logger.info("Rate limiter: in-memory only (REDIS_URL not set)")
    return Limiter(**common)


limiter = _build_limiter()


async def enforce_otp_limit(request, *, identity, purpose, operation, key, include_peer=True):
    """OTP-only distributed quota boundary; never changes SOS/general fallback."""
    import asyncio
    from fastapi import HTTPException
    from app.core.otp_rate_limit import check_quota, QuotaUnavailable
    from app.services.redis_service import _get_client

    # Trust only the ASGI peer established by the server. Raw forwarded headers
    # are not identity evidence; deployment proxy policy is a separate review.
    peer = getattr(getattr(request, "client", None), "host", None)
    if not peer:
        raise HTTPException(503, "OTP request origin unavailable", headers={"Retry-After": "30"})

    def check():
        try:
            return check_quota(_get_client(), identity=identity, ip=peer,
                               purpose=purpose, operation=operation, key=key, include_peer=include_peer)
        except Exception:
            raise QuotaUnavailable("Shared OTP quota unavailable") from None

    try:
        retry = await asyncio.to_thread(check)
    except QuotaUnavailable:
        raise HTTPException(503, "Verification temporarily unavailable", headers={"Retry-After": "30"}) from None
    if retry:
        raise HTTPException(429, "Too many verification requests", headers={"Retry-After": str(retry)})
