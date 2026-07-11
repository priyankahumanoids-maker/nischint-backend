"""Synthetic uptime probes — runs in the scheduler process.

Every `PROBE_INTERVAL_S` seconds, fires three production-equivalent
requests against the API:

  1. `GET /api/health`            — shallow K8s liveness
  2. `GET /api/public/status`     — full status envelope (DB + Redis + signals)
  3. `POST /api/auth/login`       — end-to-end auth path (Redis-backed rate
                                    limit + bcrypt + DB lookup + JWT mint)

Results are logged to Redis (last 30 results per probe, ring buffer) so
the operator dashboard can render a live mini-strip without the prober
itself becoming a single point of failure. After
`FAIL_THRESHOLD_CONSECUTIVE` consecutive failures on a single probe, a
Sentry WARNING is captured with structured tags so on-call gets paged.

Design contract — what this module promises:

  * NEVER blocks the scheduler loop. Each probe has a hard
    `httpx.Timeout(PROBE_TIMEOUT_S)` and the whole batch runs through
    `asyncio.gather(..., return_exceptions=True)` so a single hung
    probe doesn't starve the others.

  * NEVER spams Sentry. We fire the WARNING ONCE per failure streak.
    The next WARNING for the same probe only fires after a recovery
    (consecutive_failures back to 0) followed by another streak.

  * NEVER mutates production state. The login probe goes through the
    normal login route — slowapi rate-limiter still applies. With a 60s
    cadence and `MAX_REQUESTS_PER_MIN ≥ 10`, we're nowhere near the
    budget. The token from a successful login is **discarded**; no
    session is held.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

# ── Tunables ───────────────────────────────────────────────────────

PROBE_INTERVAL_S = 60
PROBE_TIMEOUT_S = 15.0
# httpx.Timeout(connect=, read=, write=, pool=) — explicit per-phase
# caps. Without setting connect explicitly, httpx can wait the system
# socket default (~60–75s) for a fresh TCP handshake when the upstream
# is congested. We hard-cap connect at 5s so a transient network blip
# fails fast instead of blowing the probe budget.
PROBE_CONNECT_TIMEOUT_S = 5.0
FAIL_THRESHOLD_CONSECUTIVE = 3
HISTORY_LIMIT = 30
REDIS_NAMESPACE = "synth_probe"

# Test account for the login probe. We DON'T read this from .env so a
# rotation requires a deliberate code change — the credential is
# already tracked in `/app/memory/test_credentials.md`. If the operator
# account password ever changes, update both.
_PROBE_EMAIL = "operator@nischint.com"
_PROBE_PASSWORD = "OperatorSecure!2026"  # noqa: S105 — synthetic-only test account

# Target API. Synthetic probes MUST hit the public ingress (same path a
# real user takes) — never localhost — so we exercise the full
# Cloudflare → nginx → uvicorn chain. Falls back to localhost only when
# REACT_APP_BACKEND_URL is not set (e.g. test runs).
_BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")

_scheduler: AsyncIOScheduler | None = None
_JOB_ID = "synthetic_probes_60s"

# In-process state for "fire WARN once per streak" logic. Backed up to
# Redis too, but we keep an in-memory copy so a Redis blip doesn't
# cause us to spam Sentry once Redis comes back.
_consecutive_failures: dict[str, int] = {}
_sentry_fired_for_streak: set[str] = set()


# ── Probe definitions ──────────────────────────────────────────────


async def _probe_health(client: httpx.AsyncClient) -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        r = await client.get(f"{_BASE_URL}/api/health")
        ok = (r.status_code == 200 and r.json().get("status") == "ok")
        return {
            "ok": ok,
            "status_code": r.status_code,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "error": None if ok else f"unexpected payload: {r.text[:120]}",
        }
    except Exception as e:
        return {"ok": False, "status_code": None, "latency_ms": int((time.monotonic() - t0) * 1000), "error": f"{type(e).__name__}: {e}"[:200]}


async def _probe_public_status(client: httpx.AsyncClient) -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        r = await client.get(f"{_BASE_URL}/api/public/status")
        body = r.json() if r.status_code == 200 else {}
        # Public status returns "operational" / "degraded" / "outage" — all
        # 3 are valid 200 responses; the probe fails only on transport.
        ok = (
            r.status_code == 200
            and isinstance(body.get("components"), list)
            and len(body["components"]) >= 4
            and body.get("overall") in ("operational", "degraded", "outage")
        )
        return {
            "ok": ok,
            "status_code": r.status_code,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "error": None if ok else f"malformed envelope keys={sorted(body.keys()) if isinstance(body, dict) else type(body).__name__}",
            "overall": body.get("overall") if isinstance(body, dict) else None,
        }
    except Exception as e:
        return {"ok": False, "status_code": None, "latency_ms": int((time.monotonic() - t0) * 1000), "error": f"{type(e).__name__}: {e}"[:200]}


async def _probe_login(client: httpx.AsyncClient) -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        r = await client.post(
            f"{_BASE_URL}/api/auth/login",
            json={"email": _PROBE_EMAIL, "password": _PROBE_PASSWORD},
            headers={"X-Synthetic-Probe": "nischint-synthetic-monitor"},  # for log filtering
        )
        ok = (r.status_code == 200)
        token_present = False
        if ok:
            try:
                token_present = bool(r.json().get("access_token"))
            except Exception:
                token_present = False
        return {
            "ok": ok and token_present,
            "status_code": r.status_code,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "error": None if (ok and token_present) else (
                "no access_token in payload" if ok else f"HTTP {r.status_code}: {r.text[:120]}"
            ),
        }
    except Exception as e:
        return {"ok": False, "status_code": None, "latency_ms": int((time.monotonic() - t0) * 1000), "error": f"{type(e).__name__}: {e}"[:200]}


PROBES = [
    ("health",      _probe_health),
    ("public_status", _probe_public_status),
    ("login",       _probe_login),
]


# ── State persistence ──────────────────────────────────────────────


def _record_result(name: str, result: dict[str, Any]) -> None:
    """Push the result onto Redis history + update state. Silent on Redis errors."""
    try:
        from app.services import redis_service
        # Last-state snapshot (always overwritten, used by dashboards)
        state = {
            **result,
            "name": name,
            "ts": datetime.now(timezone.utc).isoformat(),
            "consecutive_failures": _consecutive_failures.get(name, 0),
        }
        redis_service.set_json(REDIS_NAMESPACE, f"{name}:state", state, ttl=3600)

        # Ring-buffered history (last 30). We keep history as a list
        # stored under a single key for simplicity — the entries are
        # tiny (< 200 B each) so the whole blob stays well under 6 KB.
        history = redis_service.get_json(REDIS_NAMESPACE, f"{name}:history") or []
        history.append(state)
        if len(history) > HISTORY_LIMIT:
            history = history[-HISTORY_LIMIT:]
        redis_service.set_json(REDIS_NAMESPACE, f"{name}:history", history, ttl=3600)
    except Exception as e:
        logger.debug(f"[synthetic_monitor] redis write failed for {name}: {e}")


def _alert_sentry_once(name: str, result: dict[str, Any]) -> None:
    """Fire a Sentry WARNING exactly once per failure streak."""
    if name in _sentry_fired_for_streak:
        return
    try:
        import sentry_sdk
        if sentry_sdk.Hub.current.client is None:
            return  # Sentry not configured — local dev or test run
        sentry_sdk.capture_message(
            f"Synthetic probe `{name}` failed {FAIL_THRESHOLD_CONSECUTIVE} times in a row",
            level="warning",
        )
        with sentry_sdk.configure_scope() as scope:
            scope.set_tag("probe", name)
            scope.set_tag("probe_latency_ms", str(result.get("latency_ms")))
            scope.set_tag("probe_status_code", str(result.get("status_code")))
            scope.set_context("synthetic_probe", {
                "name": name,
                "consecutive_failures": _consecutive_failures.get(name, 0),
                "error": result.get("error"),
                "latency_ms": result.get("latency_ms"),
                "status_code": result.get("status_code"),
            })
        _sentry_fired_for_streak.add(name)
        logger.warning(f"[synthetic_monitor] Sentry alert fired for `{name}` after {FAIL_THRESHOLD_CONSECUTIVE} consecutive failures")
    except Exception as e:
        logger.debug(f"[synthetic_monitor] Sentry alert failed for {name}: {e}")


def _update_streak(name: str, result: dict[str, Any]) -> None:
    """Update consecutive-failure counter; fire Sentry on first crossing."""
    if result.get("ok"):
        # Recovery — reset both counter and the "already-fired" flag so
        # the next streak can re-alert.
        if _consecutive_failures.get(name, 0) > 0:
            logger.info(f"[synthetic_monitor] `{name}` recovered after {_consecutive_failures[name]} failures")
        _consecutive_failures[name] = 0
        _sentry_fired_for_streak.discard(name)
    else:
        _consecutive_failures[name] = _consecutive_failures.get(name, 0) + 1
        if _consecutive_failures[name] >= FAIL_THRESHOLD_CONSECUTIVE:
            _alert_sentry_once(name, result)


# ── Probe-pass orchestration ───────────────────────────────────────


async def _run_probe_with_budget(name: str, fn, client: httpx.AsyncClient) -> dict[str, Any]:
    """Wrap a single probe in a hard `asyncio.wait_for` budget.

    The httpx client has its own timeout, but a misbehaving DNS / TLS
    handshake can occasionally exceed `PROBE_TIMEOUT_S` at the socket
    level. `wait_for` is the belt-and-braces guarantee that one slow
    probe can never starve the whole pass.
    """
    try:
        return await asyncio.wait_for(fn(client), timeout=PROBE_TIMEOUT_S + 2)
    except asyncio.TimeoutError:
        return {
            "ok": False,
            "status_code": None,
            "latency_ms": int(PROBE_TIMEOUT_S * 1000),
            "error": f"probe budget exceeded ({PROBE_TIMEOUT_S + 2}s)",
        }
    except Exception as e:
        return {
            "ok": False,
            "status_code": None,
            "latency_ms": -1,
            "error": f"unhandled: {type(e).__name__}: {e}"[:200],
        }


async def run_probe_pass() -> dict[str, dict[str, Any]]:
    """Single full pass — fire all 3 probes concurrently. Returns the
    full result dict keyed by probe name for caller introspection (tests
    + the manual `python3 -c '...'` path).

    The pass itself is wrapped in `asyncio.shield` at the scheduler
    layer (see `_scheduled_probe_pass`) so an APScheduler tick
    cancellation can't leave the Sentry-streak state half-written.
    """
    timeout = httpx.Timeout(
        PROBE_TIMEOUT_S,
        connect=PROBE_CONNECT_TIMEOUT_S,
    )
    results: dict[str, dict[str, Any]] = {}
    async with httpx.AsyncClient(timeout=timeout) as client:
        # Fire all 3 concurrently with individual budgets — they're
        # independent and the whole batch should complete in
        # ~max(individual probe latency).
        completed = await asyncio.gather(
            *[_run_probe_with_budget(name, fn, client) for (name, fn) in PROBES],
            return_exceptions=True,
        )
        for (name, _), outcome in zip(PROBES, completed):
            if isinstance(outcome, Exception):
                result = {
                    "ok": False,
                    "status_code": None,
                    "latency_ms": -1,
                    "error": f"unhandled: {type(outcome).__name__}: {outcome}"[:200],
                }
            else:
                result = outcome
            results[name] = result
            try:
                _update_streak(name, result)
                _record_result(name, result)
            except Exception as e:
                # Never let bookkeeping break the next tick.
                logger.warning(f"[synthetic_monitor] bookkeeping failed for {name}: {e}")
    return results


async def _scheduled_probe_pass() -> None:
    """APScheduler entrypoint — shields the pass from tick cancellation.

    APScheduler's AsyncIOExecutor schedules the coroutine on the loop
    and, if the loop is congested and the scheduler is being shut down
    or a new tick steals priority, the in-flight coroutine can be
    cancelled mid-flight. `asyncio.shield` lets the probe pass finish
    its current iteration even if the parent task is cancelled, so we
    never leave `_consecutive_failures` / `_sentry_fired_for_streak` in
    a half-updated state.

    The shield doesn't block forever — `run_probe_pass` has its own
    per-probe `asyncio.wait_for` budget (≤ PROBE_TIMEOUT_S + 2s per
    probe, all 3 concurrent), so worst case the shielded coroutine
    completes in <20s.
    """
    try:
        await asyncio.shield(run_probe_pass())
    except asyncio.CancelledError:
        # Surfaced when the outer scheduler tick is cancelled. The
        # shielded `run_probe_pass` continues in the background and
        # records its own result; we just acknowledge the cancel here
        # so APScheduler doesn't log it as a job error.
        logger.info("[synthetic_monitor] tick cancelled — shielded pass continuing in background")
    except Exception as e:
        # Last-resort safety net — log + swallow, never let the
        # scheduler think the job is broken.
        logger.warning(f"[synthetic_monitor] tick failed: {type(e).__name__}: {e}")


# ── Public scheduler hooks ─────────────────────────────────────────


def start_synthetic_monitor() -> None:
    """Idempotent — call once at scheduler-process startup."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    if not _scheduler.running:
        _scheduler.add_job(
            _scheduled_probe_pass,
            IntervalTrigger(seconds=PROBE_INTERVAL_S),
            id=_JOB_ID,
            replace_existing=True,
            # If a single tick takes > PROBE_INTERVAL_S, coalesce the
            # missed runs into one rather than queueing — we only care
            # about current health, not the backlog.
            coalesce=True,
            max_instances=1,
            # When the scheduler loop is congested (e.g. other jobs
            # hanging on DB connect timeouts), the dispatch can be
            # delayed by tens of seconds. Without misfire_grace_time
            # the run is dropped silently; with 120s it's just delayed,
            # which is the behaviour we want for an uptime probe.
            misfire_grace_time=120,
        )
        _scheduler.start()
        logger.info(f"[synthetic_monitor] started — interval={PROBE_INTERVAL_S}s threshold={FAIL_THRESHOLD_CONSECUTIVE} probes={[n for n, _ in PROBES]}")


def stop_synthetic_monitor() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[synthetic_monitor] stopped")
    _scheduler = None
