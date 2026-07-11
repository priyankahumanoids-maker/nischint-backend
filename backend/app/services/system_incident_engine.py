"""Incident State Engine.

Strict scope: persist + snapshot + correlate. Nothing more.

Trigger contract (locked by tests in `test_system_incident_engine.py`):
  • START on transition healthy → warning OR healthy → degraded OR
    warning → degraded.
  • RESOLVE on transition X → healthy.
  • Repeated degraded ticks while incident is active → silent.
  • Optional 30 s debounce on the START path: if the engine sees a
    transition that recovers within the debounce window, no DB row is
    written. (Cheap insurance against transient spikes.)

What this does NOT do:
  • No alerting. No paging. No workflow routing.
  • No coupling to the WS layer. The capsule already gets its
    real-time push from `health_thresholds._emit`. This module is the
    *historical* layer; it speaks Postgres only.
"""

from __future__ import annotations
import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_incident import SystemIncident

logger = logging.getLogger(__name__)

# Severity ranking
_SEV_RANK = {"healthy": 0, "warning": 1, "degraded": 2}

# Window during which a transient transition is suppressed before being
# committed to the DB. Keeps cold-start bias and 1-tick spikes out of
# the historical record.
START_DEBOUNCE_S = 30.0


# ── Pending-start tracker (in-process; harmless if duplicated across
# processes because `ix_system_incidents_active_singleton` rejects the
# 2nd INSERT of an active row).
_lock = threading.Lock()
_pending: dict[str, dict[str, Any]] = {}


def _is_escalation(prev: str | None, new: str) -> bool:
    """True if the new severity is strictly worse than the previous."""
    return _SEV_RANK.get(new, 0) > _SEV_RANK.get(prev or "healthy", 0)


async def _capture_snapshot() -> dict:
    """Best-effort full-system snapshot. Must never raise."""
    out: dict = {"taken_at": datetime.now(timezone.utc).isoformat()}
    try:
        from app.services.scheduler_metrics import get_snapshot as sched_snap
        out["scheduler"] = sched_snap()
    except Exception:
        out["scheduler"] = {"error": "unavailable"}
    try:
        from app.services.ai_metrics import get_snapshot as ai_snap
        out["ai"] = ai_snap()
    except Exception:
        out["ai"] = {"error": "unavailable"}
    try:
        from app.services.auth_metrics import get_snapshot as auth_snap
        out["auth"] = auth_snap()
    except Exception:
        out["auth"] = {"error": "unavailable"}
    try:
        from app.services.queue_service import get_queue_stats
        out["queue"] = get_queue_stats() or {}
    except Exception:
        out["queue"] = {"error": "unavailable"}
    try:
        from app.api.ws_command_center import _cc_connections
        out["ws"] = {"command_center_active": len(_cc_connections)}
    except Exception:
        out["ws"] = {"error": "unavailable"}
    try:
        from app.services import redis_service
        t0 = time.perf_counter()
        available = redis_service.is_available()
        ping_ms = (time.perf_counter() - t0) * 1000
        out["redis"] = {
            "available": bool(available),
            "ping_ms":   round(ping_ms, 2),
        }
    except Exception as e:
        out["redis"] = {"available": False, "error": str(e)[:120]}
    # REL-04 — DB pool stats embedded in the incident snapshot so a
    # post-mortem on a `database_pool` incident has the full pool
    # state at the moment of trigger (and again at resolve time).
    pool_state: dict[str, Any] = {"available": False}
    try:
        from app.db.pool_stats import get_pool_stats
        pool_state = get_pool_stats()
        out["db_pool"] = pool_state
    except Exception as e:
        out["db_pool"] = {"available": False, "error": str(e)[:120]}

    # REL-04 — pg_stat_activity post-mortem. Captured ONLY when the
    # pool is over the alerting threshold (or has waiters), to keep
    # routine snapshots from hammering pg_stat_activity for every
    # transition. The query runs on the dedicated asyncpg pool, which
    # is independent of the saturated SQLAlchemy pool — that's how we
    # can introspect the DB even when the ORM is out of slots.
    try:
        util = pool_state.get("pg_pool_utilization_pct") if pool_state else None
        waiters = pool_state.get("pg_pool_wait_count") if pool_state else None
        # Both conditions are written so a process queuing up acquire()
        # calls (waiters > 0) is captured even if utilization briefly
        # dropped below 85 % between the spike and the snapshot.
        if (util is not None and util >= 85.0) or (waiters and waiters > 0):
            from app.db.pg_diagnostics import capture_top_queries
            out["pg_stat_activity_top"] = await capture_top_queries()
        else:
            out["pg_stat_activity_top"] = []
    except Exception as e:
        out["pg_stat_activity_top"] = []
        logger.debug(f"[incident] pg_stat_activity capture failed: {e}")

    return out


async def _open_incident(session: AsyncSession, *,
                         severity: str, source: str, metric: str | None) -> SystemIncident | None:
    """Insert a new active incident. Idempotent — relies on the partial
    unique index `ix_system_incidents_active_singleton` to prevent a
    duplicate active row when two processes race."""
    snap = await _capture_snapshot()
    try:
        from app.services.incident_classifier import classify_root_cause
        root_cause = classify_root_cause(snap, trigger_source=source)
        inc = SystemIncident(
            severity_peak=severity,
            trigger_source=source,
            trigger_metric=metric,
            snapshot_json=snap,
            status="active",
            started_at=datetime.now(timezone.utc),
            root_cause_domain=root_cause,
        )
        session.add(inc)
        await session.commit()
        await session.refresh(inc)
        logger.info(
            f"[incident] OPENED id={inc.id} severity={severity} source={source} "
            f"metric={metric} root_cause={root_cause}"
        )
        return inc
    except Exception as e:
        await session.rollback()
        # Likely the partial-unique index blocked us — another process
        # already opened this incident. That's the desired no-op.
        logger.info(f"[incident] open suppressed (probably dup-active): {e}")
        return None


async def _escalate_active(session: AsyncSession, *, severity: str) -> None:
    """If an active incident exists at lower severity, bump severity_peak."""
    rows = (await session.execute(
        select(SystemIncident).where(SystemIncident.status == "active").limit(1)
    )).scalars().all()
    if not rows:
        return
    inc = rows[0]
    if _SEV_RANK.get(severity, 0) > _SEV_RANK.get(inc.severity_peak, 0):
        inc.severity_peak = severity
        await session.commit()
        logger.info(f"[incident] ESCALATED id={inc.id} new_peak={severity}")


async def _resolve_active(session: AsyncSession) -> None:
    """Close the currently-active incident (there's at most one)."""
    rows = (await session.execute(
        select(SystemIncident).where(SystemIncident.status == "active")
    )).scalars().all()
    if not rows:
        return
    inc = rows[0]
    end = datetime.now(timezone.utc)
    duration_ms = int((end - inc.started_at).total_seconds() * 1000)
    closing = await _capture_snapshot()
    await session.execute(
        update(SystemIncident)
        .where(SystemIncident.id == inc.id)
        .values(
            status="resolved",
            resolved_at=end,
            duration_ms=duration_ms,
            resolution_json=closing,
        )
    )
    await session.commit()
    logger.info(f"[incident] RESOLVED id={inc.id} duration_ms={duration_ms}")


async def handle_transition(*,
                             prev_severity: str | None,
                             new_severity: str,
                             source: str,
                             metric: str | None) -> None:
    """Single entry point — called by `health_thresholds._evaluate`
    after it has already decided the transition is real (i.e. the
    threshold engine's emit-on-transition contract has fired)."""
    from app.db.session import async_session
    if async_session is None:
        return  # DB not initialised yet (during very early startup)

    if new_severity == "healthy":
        # Cancel any pending START in the debounce queue first — a
        # transient spike that recovers within the window must NOT
        # ever appear in the historical record.
        cancel_pending(source)
        async with async_session() as session:
            await _resolve_active(session)
        return

    # Defensive: same severity → no-op. The threshold engine should
    # not call us in this case, but if a future caller does we must
    # never double-open or mis-escalate.
    if prev_severity == new_severity:
        return

    # Escalation within an existing active incident → bump peak only.
    if prev_severity and prev_severity != "healthy" and _is_escalation(prev_severity, new_severity):
        async with async_session() as session:
            await _escalate_active(session, severity=new_severity)
        return

    # First entry into non-healthy. Apply the debounce: queue a deferred
    # open, but if a recovery transition arrives within the window we
    # just cancel without ever writing to the DB.
    pending_key = f"start:{source}"
    deadline = time.time() + START_DEBOUNCE_S
    with _lock:
        _pending[pending_key] = {
            "severity": new_severity, "source": source, "metric": metric,
            "deadline": deadline,
        }

    async def _deferred_open():
        await asyncio.sleep(START_DEBOUNCE_S)
        with _lock:
            entry = _pending.get(pending_key)
            if not entry or entry.get("deadline") != deadline:
                return  # canceled or replaced
            _pending.pop(pending_key, None)
        async with async_session() as session:
            await _open_incident(
                session,
                severity=entry["severity"],
                source=entry["source"],
                metric=entry["metric"],
            )

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_deferred_open())
    except RuntimeError:
        pass


def cancel_pending(source: str) -> None:
    """Called by the resolve path: if a START is sitting in the
    debounce queue and we just recovered, drop it on the floor."""
    with _lock:
        _pending.pop(f"start:{source}", None)
