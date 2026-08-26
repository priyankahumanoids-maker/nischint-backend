"""Scheduler-health metrics — the truth source for Phase 1 isolation.

Listens to APScheduler EVENT_JOB_* events on every running scheduler in
this process and records per-job:

  • last_run_drift_ms   — scheduled vs actual fire time (positive = late)
  • last_duration_ms    — wall-clock execution time
  • drift_p50 / p95     — over the last N runs (rolling window)
  • missed / error / success counts

Persisted in Redis under `scheduler:metrics:{job_id}` so the
`api` process and the standalone `scheduler` process share the same
truth. Falls back to a process-local dict if Redis is unavailable —
the `/api/monitoring/schedulers` endpoint will still return whatever
the local recorder has seen.

The endpoint that consumes this is intentionally read-only and works
off this snapshot, never live-introspecting the schedulers.
"""

from __future__ import annotations
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MISSED,
    EVENT_JOB_SUBMITTED,
)

logger = logging.getLogger(__name__)

REDIS_NS = "scheduler_metrics"
ROLLING_WINDOW = 50  # last N drift samples per job for p50/p95


# ── Local state (per-process) ─────────────────────────────────────────
@dataclass
class _JobStats:
    job_id: str
    owner: str = ""           # module that owns the scheduler
    drifts_ms: list[float] = field(default_factory=list)  # rolling
    last_run_at: str | None = None
    last_run_drift_ms: float | None = None
    last_duration_ms: float | None = None
    last_status: str | None = None    # success | error | missed
    last_error: str | None = None
    avg_duration_ms: float = 0.0
    success_count: int = 0
    error_count: int = 0
    missed_count: int = 0


_lock = threading.Lock()
_stats: dict[str, _JobStats] = {}
_attached_schedulers: set[int] = set()


# ── Redis helpers ─────────────────────────────────────────────────────
def _redis():
    try:
        from app.services.redis_service import _get_client
        return _get_client()
    except Exception:
        return None


def _persist(stats: _JobStats) -> None:
    c = _redis()
    if not c:
        return
    try:
        payload = {
            "job_id":             stats.job_id,
            "owner":              stats.owner,
            "last_run_at":        stats.last_run_at,
            "last_run_drift_ms":  stats.last_run_drift_ms,
            "last_duration_ms":   stats.last_duration_ms,
            "last_status":        stats.last_status,
            "last_error":         stats.last_error,
            "avg_duration_ms":    round(stats.avg_duration_ms, 2),
            "success_count":      stats.success_count,
            "error_count":        stats.error_count,
            "missed_count":       stats.missed_count,
            "drifts_ms":          stats.drifts_ms[-ROLLING_WINDOW:],
        }
        c.set(f"nischint:{REDIS_NS}:{stats.job_id}", json.dumps(payload), ex=86400)
        c.sadd(f"nischint:{REDIS_NS}:_index", stats.job_id)
    except Exception as e:
        logger.debug(f"scheduler_metrics persist failed for {stats.job_id}: {e}")


def _get_or_create(job_id: str, owner: str = "") -> _JobStats:
    s = _stats.get(job_id)
    if s is None:
        s = _JobStats(job_id=job_id, owner=owner)
        _stats[job_id] = s
    elif owner and not s.owner:
        s.owner = owner
    return s


# ── APScheduler event listeners ───────────────────────────────────────
def _on_submitted(event, owner: str) -> None:
    """Record scheduled -> executor-dispatch delay.

    APScheduler emits EVENT_JOB_SUBMITTED when scheduled run times have
    been handed to the executor. Measuring here keeps actual job runtime
    out of scheduler drift.

    Standard APScheduler submission events expose ``scheduled_run_times``.
    The singular fallback also supports synthetic/custom event objects.
    """
    scheduled_run_times = list(
        getattr(event, "scheduled_run_times", None) or []
    )

    if not scheduled_run_times:
        single = getattr(
            event,
            "scheduled_run_time",
            None,
        )
        if single is not None:
            scheduled_run_times = [single]

    if not scheduled_run_times:
        return

    dispatched_at = datetime.now(timezone.utc)

    with _lock:
        s = _get_or_create(
            event.job_id,
            owner,
        )

        for scheduled_run_time in scheduled_run_times:
            drift_ms = max(
                0.0,
                (
                    dispatched_at
                    - scheduled_run_time
                ).total_seconds() * 1000,
            )

            rounded = round(
                drift_ms,
                2,
            )

            s.last_run_drift_ms = rounded
            s.drifts_ms.append(rounded)

        if len(s.drifts_ms) > ROLLING_WINDOW:
            s.drifts_ms = (
                s.drifts_ms[-ROLLING_WINDOW:]
            )

        _persist(s)

    _maybe_emit_threshold_event(
        event.job_id
    )


def _on_executed(event, owner: str) -> None:
    """Record completion without adding runtime to dispatch drift."""
    duration_ms: float | None = None

    rt = getattr(
        event,
        "retval",
        None,
    )

    if (
        isinstance(rt, dict)
        and "_duration_ms" in rt
    ):
        duration_ms = float(
            rt["_duration_ms"]
        )

    with _lock:
        s = _get_or_create(
            event.job_id,
            owner,
        )

        s.last_run_at = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )
        s.last_status = "success"
        s.last_error = None
        s.success_count += 1

        if duration_ms is not None:
            s.last_duration_ms = round(
                duration_ms,
                2,
            )

            n = s.success_count

            s.avg_duration_ms = (
                s.avg_duration_ms * (n - 1)
                + duration_ms
            ) / n

        _persist(s)

    _maybe_emit_threshold_event(
        event.job_id
    )


def _on_missed(event, owner: str) -> None:
    with _lock:
        s = _get_or_create(event.job_id, owner)
        s.missed_count += 1
        s.last_status = "missed"
        s.last_run_at = datetime.now(timezone.utc).isoformat()
        _persist(s)
    logger.warning(f"[scheduler_metrics] missed job {event.job_id} (owner={owner})")
    _maybe_emit_threshold_event(event.job_id)


def _on_error(event, owner: str) -> None:
    with _lock:
        s = _get_or_create(event.job_id, owner)
        s.error_count += 1
        s.last_status = "error"
        s.last_error = str(getattr(event, "exception", ""))[:300]
        s.last_run_at = datetime.now(timezone.utc).isoformat()
        _persist(s)
    _maybe_emit_threshold_event(event.job_id)


def _maybe_emit_threshold_event(job_id: str | None) -> None:
    """Compute global drift_p95 + missed/error totals and ask the
    threshold engine to emit a `system_health_delta` IFF the severity
    changed since the last evaluation. Cheap — just a list sort and
    one Redis SET in the no-op case.
    """
    try:
        snap = get_snapshot()
        from app.services.health_thresholds import evaluate_scheduler_state
        evaluate_scheduler_state(
            snap.get("drift_p95_ms"),
            int(snap.get("missed_total") or 0),
            int(snap.get("error_total") or 0),
            job_id=job_id,
        )
    except Exception:
        logger.debug("threshold evaluation failed", exc_info=True)


# ── Attach to a running scheduler (idempotent) ────────────────────────
def attach(scheduler, owner: str) -> bool:
    """Hook EVENT_JOB_* listeners onto the given scheduler.

    Idempotent — returns False if already attached.
    """
    if scheduler is None:
        return False
    sid = id(scheduler)
    if sid in _attached_schedulers:
        return False
    _attached_schedulers.add(sid)
    scheduler.add_listener(lambda e: _on_submitted(e, owner), EVENT_JOB_SUBMITTED)
    scheduler.add_listener(lambda e: _on_executed(e, owner), EVENT_JOB_EXECUTED)
    scheduler.add_listener(lambda e: _on_missed(e, owner), EVENT_JOB_MISSED)
    scheduler.add_listener(lambda e: _on_error(e, owner), EVENT_JOB_ERROR)
    return True


def attach_to_all_running() -> dict[str, int]:
    """Walk loaded `app.*` modules, find any APScheduler instance that's
    running, and attach metrics listeners. Returns counts."""
    import sys
    from apscheduler.schedulers.base import BaseScheduler

    attached, skipped = 0, 0
    for mod_name in list(sys.modules.keys()):
        if not (mod_name == "app" or mod_name.startswith("app.")):
            continue
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        for attr_name in dir(mod):
            try:
                obj = getattr(mod, attr_name)
            except Exception:
                continue
            if isinstance(obj, BaseScheduler) and getattr(obj, "running", False):
                if attach(obj, owner=mod_name):
                    attached += 1
                else:
                    skipped += 1
    logger.info(f"[scheduler_metrics] attached={attached} skipped={skipped}")
    return {"attached": attached, "skipped": skipped}


# ── Snapshot for the read-only API endpoint ───────────────────────────
def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((pct / 100) * (len(s) - 1)))))
    return round(s[k], 2)


def _next_run_times() -> dict[str, str]:
    """Best-effort — query every running scheduler in this process."""
    import sys
    from apscheduler.schedulers.base import BaseScheduler

    out: dict[str, str] = {}
    for mod_name in list(sys.modules.keys()):
        if not mod_name.startswith("app."):
            continue
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        for attr_name in dir(mod):
            try:
                obj = getattr(mod, attr_name)
            except Exception:
                continue
            if not isinstance(obj, BaseScheduler) or not getattr(obj, "running", False):
                continue
            try:
                for j in obj.get_jobs():
                    if j.next_run_time and j.id not in out:
                        out[j.id] = j.next_run_time.isoformat()
            except Exception:
                pass
    return out


def get_snapshot() -> dict:
    """Return the truth-snapshot for `/api/monitoring/schedulers`."""
    from app.core.role import get_role

    next_runs = _next_run_times()

    # Pull cross-process state from Redis if available, otherwise local.
    jobs: dict[str, dict] = {}
    c = _redis()
    if c:
        try:
            ids = c.smembers(f"nischint:{REDIS_NS}:_index") or set()
            ids = {x.decode() if isinstance(x, bytes) else x for x in ids}
            for job_id in ids:
                raw = c.get(f"nischint:{REDIS_NS}:{job_id}")
                if not raw:
                    continue
                try:
                    jobs[job_id] = json.loads(raw)
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"snapshot redis read failed: {e}")

    # Merge local state on top (local has freshest data inside this process)
    with _lock:
        for job_id, s in _stats.items():
            jobs[job_id] = {
                "job_id":            s.job_id,
                "owner":             s.owner,
                "last_run_at":       s.last_run_at,
                "last_run_drift_ms": s.last_run_drift_ms,
                "last_duration_ms":  s.last_duration_ms,
                "last_status":       s.last_status,
                "last_error":        s.last_error,
                "avg_duration_ms":   round(s.avg_duration_ms, 2),
                "success_count":     s.success_count,
                "error_count":       s.error_count,
                "missed_count":      s.missed_count,
                "drifts_ms":         list(s.drifts_ms),
            }

    rows = []
    drifts_all: list[float] = []
    for job_id, j in jobs.items():
        drifts = j.get("drifts_ms") or []
        drifts_all.extend(drifts)
        rows.append({
            "id":                job_id,
            "owner":             j.get("owner") or "",
            "next_run_time":     next_runs.get(job_id),
            "last_run_at":       j.get("last_run_at"),
            "last_run_drift_ms": j.get("last_run_drift_ms"),
            "last_duration_ms":  j.get("last_duration_ms"),
            "avg_duration_ms":   j.get("avg_duration_ms", 0),
            "last_status":       j.get("last_status"),
            "last_error":        j.get("last_error"),
            "success_count":     j.get("success_count", 0),
            "error_count":       j.get("error_count", 0),
            "missed_count":      j.get("missed_count", 0),
            "drift_p50_ms":      _percentile(drifts, 50),
            "drift_p95_ms":      _percentile(drifts, 95),
        })
    rows.sort(key=lambda r: r["id"])

    total_missed = sum(r["missed_count"] for r in rows)
    total_errors = sum(r["error_count"] for r in rows)
    p95_global = _percentile(drifts_all, 95)
    p50_global = _percentile(drifts_all, 50)

    if total_missed > 0 or (p95_global is not None and p95_global > 1000):
        status = "degraded"
    elif total_errors > 0:
        status = "warning"
    else:
        status = "healthy"

    return {
        "role":            get_role().value,
        "status":          status,
        "scheduler_count": len(rows),
        "drift_p50_ms":    p50_global,
        "drift_p95_ms":    p95_global,
        "missed_total":    total_missed,
        "error_total":     total_errors,
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "jobs":            rows,
    }


def reset_drift_baseline() -> dict:
    """Drop rolling drift windows on every job. Use after Phase 1
    activation so previous-baseline drift samples don't pollute the
    post-isolation p95."""
    cleared = 0
    with _lock:
        for s in _stats.values():
            s.drifts_ms.clear()
            _persist(s)
            cleared += 1
    c = _redis()
    if c:
        try:
            ids = c.smembers(f"nischint:{REDIS_NS}:_index") or set()
            ids = {x.decode() if isinstance(x, bytes) else x for x in ids}
            for job_id in ids:
                raw = c.get(f"nischint:{REDIS_NS}:{job_id}")
                if not raw:
                    continue
                try:
                    j = json.loads(raw)
                    j["drifts_ms"] = []
                    c.set(f"nischint:{REDIS_NS}:{job_id}", json.dumps(j), ex=86400)
                    cleared += 1
                except Exception:
                    pass
        except Exception:
            pass
    return {"cleared": cleared, "at": datetime.now(timezone.utc).isoformat()}
