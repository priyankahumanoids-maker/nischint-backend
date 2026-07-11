"""Twilio safety wrapper — timeout-bounded, retry-once, latency-tracked.

Why this exists:
- The Twilio Python SDK swallows network problems via the underlying
  `requests` lib, but its default HTTP timeout (60s in some paths) is
  far too lenient for an alert-pipeline call that the user is waiting on.
- The previous code path had no retry on transient failures (e.g.
  Twilio's brief 5xx blips during a region failover).
- We need *every* send to record `twilio_latency_ms` so TTFA can prove
  "alert dispatched" includes the round-trip cost.

Strict design:
- One retry, not three. SOS-class voice escalation already has a 3-retry
  loop higher up in `sms_service.escalation_flow`; the wrapper handles
  *single-shot* SMS / voice deliveries.
- Hard timeout via `concurrent.futures` so a hung TLS handshake can't
  freeze a request handler.
- Never raises. Always returns a structured dict with `success`,
  `latency_ms`, `error`, and `attempts` so the alert pipeline stays
  intact even if Twilio is completely down.
- Records into `ttfa_recorder` so `/api/_dev/alert-ttfa/stats` sees the
  Twilio leg as part of TTFA.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────
SEND_TIMEOUT_S = 5.0    # hard wall — Twilio call MUST return in 5s
RETRY_COUNT    = 1       # one extra attempt on failure (so 2 total)
RETRY_BACKOFF_S = 0.4    # short backoff so the retry still fits inside
                         # the *next* 5s budget at the per-call layer.

# A small dedicated executor avoids contention with the asyncio loop.
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="twilio-safe")


# ── Public ──────────────────────────────────────────────────────────
def safe_call(
    fn: Callable[..., Any],
    *,
    kind: str,
    timeout_s: float = SEND_TIMEOUT_S,
    retries: int = RETRY_COUNT,
    args: tuple = (),
    kwargs: dict | None = None,
) -> dict:
    """Run a synchronous Twilio SDK call with timeout + retry + latency.

    Args:
        fn:        the Twilio SDK callable (e.g. `client.messages.create`).
        kind:      free-form label for logs / TTFA. Use the alert kind +
                   leg ("sos-sms", "voice_distress-call", ...).
        timeout_s: hard wall per attempt.
        retries:   extra attempts on failure (RETRY_COUNT default).
        args/kwargs: forwarded to `fn`.

    Returns:
        {
          "success":       bool,
          "result":        Any | None,    # raw Twilio response on success
          "error":         str | None,
          "attempts":      int,
          "latency_ms":    int,            # total elapsed across all attempts
        }
    """
    kwargs = kwargs or {}
    t0 = time.monotonic()
    last_err: str | None = None
    last_result: Any = None
    attempts = 0

    for i in range(retries + 1):
        attempts += 1
        attempt_t0 = time.monotonic()
        try:
            future = _EXECUTOR.submit(fn, *args, **kwargs)
            last_result = future.result(timeout=timeout_s)
            latency_ms = int((time.monotonic() - t0) * 1000)
            attempt_ms = int((time.monotonic() - attempt_t0) * 1000)
            logger.info(
                f"[TWILIO_OK] kind={kind} attempt={attempts}/{retries + 1} "
                f"attempt_ms={attempt_ms} total_ms={latency_ms}"
            )
            _record_ttfa(kind, latency_ms, success=True)
            return {
                "success":    True,
                "result":     last_result,
                "error":      None,
                "attempts":   attempts,
                "latency_ms": latency_ms,
            }
        except FutureTimeout:
            last_err = f"timeout after {timeout_s}s"
            logger.warning(
                f"[TWILIO_TIMEOUT] kind={kind} attempt={attempts}/{retries + 1} "
                f"timeout_s={timeout_s}"
            )
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            logger.warning(
                f"[TWILIO_FAIL] kind={kind} attempt={attempts}/{retries + 1} "
                f"err={last_err}"
            )

        # Backoff before next attempt (only if we have one left).
        if i < retries:
            time.sleep(RETRY_BACKOFF_S)

    latency_ms = int((time.monotonic() - t0) * 1000)
    logger.error(
        f"[TWILIO_GIVE_UP] kind={kind} attempts={attempts} "
        f"total_ms={latency_ms} err={last_err}"
    )
    _record_ttfa(kind, latency_ms, success=False)
    # Fire ops alert — best effort, never raises.
    try:
        from app.services.health_alerter import notify_failure
        notify_failure(
            level="warn",
            kind="twilio_give_up",
            message=f"Twilio {kind} send failed after {attempts} attempts.",
            details={
                "error":      last_err,
                "attempts":   attempts,
                "total_ms":   latency_ms,
                "leg_kind":   kind,
            },
        )
    except Exception:
        pass
    return {
        "success":    False,
        "result":     None,
        "error":      last_err,
        "attempts":   attempts,
        "latency_ms": latency_ms,
    }


# ── TTFA hook ───────────────────────────────────────────────────────
def _record_ttfa(kind: str, latency_ms: int, success: bool) -> None:
    """Best-effort sample emission into the TTFA recorder so the
    `/api/_dev/alert-ttfa/stats` endpoint sees Twilio leg latency
    alongside SSE-leg latency. Tagged with `twilio:<kind>` so it's
    grep-able and segregable from other kinds in the by_kind breakdown.
    """
    try:
        from app.services import ttfa_recorder
        ttfa_recorder.record(
            kind=f"twilio:{kind}",
            ttfa_ms=latency_ms,
            louder=False,
            priority="critical" if success else "warning",
        )
    except Exception:
        pass  # Never let observability break the alert path.


__all__ = ["safe_call", "SEND_TIMEOUT_S", "RETRY_COUNT"]
