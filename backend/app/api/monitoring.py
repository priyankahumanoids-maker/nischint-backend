# Monitoring API — Real-time platform metrics and alerts for admin dashboard
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.rbac import require_role
from app.models.guardian import GuardianSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/monitoring", tags=["monitoring"])
# Monitoring is READ-ONLY platform insight — both admins and operators
# (the control-room role) need this for day-to-day operations.
_read_role = require_role(["admin", "operator"])


@router.get("/synthetic-probes", dependencies=[Depends(_read_role)])
async def get_synthetic_probe_state():
    """Read-only snapshot of the synthetic monitor running in the
    scheduler process. Returns per-probe last-state + 30-entry history
    ring buffer. Silent on Redis failure — the dashboard renders an
    "unavailable" stub rather than 500.
    """
    from app.services import redis_service
    from app.services.synthetic_monitor import PROBES, REDIS_NAMESPACE, FAIL_THRESHOLD_CONSECUTIVE
    out = {
        "probes": {},
        "fail_threshold_consecutive": FAIL_THRESHOLD_CONSECUTIVE,
    }
    for name, _ in PROBES:
        try:
            state = redis_service.get_json(REDIS_NAMESPACE, f"{name}:state")
            history = redis_service.get_json(REDIS_NAMESPACE, f"{name}:history") or []
        except Exception:
            state = None
            history = []
        out["probes"][name] = {"state": state, "history": history}
    return out


@router.get("/latency", dependencies=[Depends(_read_role)])
async def get_latency_histograms(
    top_n: int = Query(50, ge=1, le=500, description="Truncate after sort. Default 50."),
    sort_by: str = Query("p95_ms", description="One of: p50_ms, p95_ms, p99_ms, total_requests, error_rate"),
):
    """Per-endpoint p50/p95/p99 latency over the last-N samples
    (N = MAX_SAMPLES, default 500). Bucketed by FastAPI route template
    so `/api/users/abc` and `/api/users/xyz` aggregate as
    `/api/users/{user_id}`. Cross-process via Redis. Read-only.
    """
    from app.services.latency_histograms import get_snapshot
    return get_snapshot(top_n=top_n, sort_by=sort_by)


@router.post("/latency/reset", dependencies=[Depends(require_role(["admin"]))])
async def reset_latency_histograms():
    """Wipe the rolling-window samples + Redis index. Admin-only.

    Run this after a deploy that changes route patterns, or after a
    perf-regression hot-fix lands, to drop the pre-fix samples that
    would otherwise drag the p95 down for the next hour.
    """
    from app.services.latency_histograms import reset_all
    return {"reset": True, **reset_all()}






@router.get("/metrics", dependencies=[Depends(_read_role)])
async def get_monitoring_metrics(session: AsyncSession = Depends(get_db_session)):
    """Get comprehensive platform monitoring metrics."""
    from app.services.monitoring_service import get_metrics

    metrics = get_metrics()

    # Add live DB query: active guardian sessions
    result = await session.execute(
        select(func.count()).select_from(GuardianSession).where(
            GuardianSession.status == "active"
        )
    )
    active_sessions = result.scalar() or 0
    metrics["guardian_sessions"] = {"active": active_sessions}

    return metrics


@router.get("/alerts", dependencies=[Depends(_read_role)])
async def get_monitoring_alerts(limit: int = Query(50, ge=1, le=200)):
    """Get recent monitoring alerts."""
    from app.services.monitoring_service import get_alerts
    return {"alerts": get_alerts(limit)}


@router.get("/runtime-info", dependencies=[Depends(_read_role)])
async def runtime_info():
    """Read-only introspection of the running uvicorn process.

    Specifically returns whether `--reload` is enabled, since uvicorn's
    WatchFiles reloader creates a 1-3 s window per file-change where the
    socket on :8001 is closed — surfacing as nginx upstream-connect
    failures (HTTP 520 at Cloudflare). Useful for diagnosing
    intermittent production outages: `curl /api/admin/monitoring/runtime-info`
    from a logged-in admin/operator session will reveal whether the
    production pod was launched with the dev `--reload` flag.

    Also returns memory pressure, open-fd count, thread count, asyncio
    task count, and event-loop responsiveness — useful for distinguishing
    OOM-kill cycles from event-loop stalls from connection-pool exhaustion
    during incident triage.
    """
    import asyncio as _asyncio
    import os
    import sys
    import time

    import psutil

    try:
        proc = psutil.Process(os.getpid())
        cmdline = proc.cmdline()
        create_time = proc.create_time()
        # Also inspect the parent (reloader spawns child workers) — if we
        # are the child, our cmdline won't include --reload but the parent's
        # will. Walk up at most 3 parents.
        parent_cmdlines: list[list[str]] = []
        p = proc
        for _ in range(3):
            try:
                p = p.parent()
                if p is None:
                    break
                parent_cmdlines.append(p.cmdline())
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
    except Exception as e:
        return {"error": f"psutil introspection failed: {e!r}"}

    full_chain = [cmdline] + parent_cmdlines
    flat = " ".join(arg for argv in full_chain for arg in argv)
    reload_detected = "--reload" in flat or "reloader" in flat
    workers_arg: Optional[int] = None
    for argv in full_chain:
        for i, a in enumerate(argv):
            if a == "--workers" and i + 1 < len(argv):
                try:
                    workers_arg = int(argv[i + 1])
                except ValueError:
                    pass
            elif a.startswith("--workers="):
                try:
                    workers_arg = int(a.split("=", 1)[1])
                except ValueError:
                    pass

    # Memory & resource pressure
    try:
        mem = proc.memory_info()
        rss_mb = round(mem.rss / 1024 / 1024, 1)
        vms_mb = round(mem.vms / 1024 / 1024, 1)
    except Exception:
        rss_mb = vms_mb = None
    try:
        num_fds = proc.num_fds()
    except Exception:
        num_fds = None
    try:
        num_threads = proc.num_threads()
    except Exception:
        num_threads = None
    try:
        num_connections = len(proc.connections(kind="inet"))
    except Exception:
        num_connections = None

    # cgroup memory limit (K8s sets this) — lets us compute "% of cap"
    cgroup_mem_limit_mb: Optional[float] = None
    cgroup_mem_used_mb: Optional[float] = None
    for path in (
        "/sys/fs/cgroup/memory.max",
        "/sys/fs/cgroup/memory/memory.limit_in_bytes",
    ):
        try:
            with open(path) as fh:
                val = fh.read().strip()
                if val and val != "max":
                    cgroup_mem_limit_mb = round(int(val) / 1024 / 1024, 1)
                    break
        except Exception:
            continue
    for path in (
        "/sys/fs/cgroup/memory.current",
        "/sys/fs/cgroup/memory/memory.usage_in_bytes",
    ):
        try:
            with open(path) as fh:
                cgroup_mem_used_mb = round(int(fh.read().strip()) / 1024 / 1024, 1)
                break
        except Exception:
            continue

    # asyncio event-loop introspection
    try:
        loop = _asyncio.get_running_loop()
        all_tasks = _asyncio.all_tasks(loop)
        task_count = len(all_tasks)
        # Event-loop lag: schedule a no-op and measure delay vs wall clock.
        # >50ms = event loop is overloaded / blocked.
        t0 = time.monotonic()
        await _asyncio.sleep(0)
        loop_lag_ms = round((time.monotonic() - t0) * 1000, 2)
    except Exception:
        task_count = loop_lag_ms = None

    # REL-04 — Postgres pool introspection. Cheap (in-memory counters);
    # safe to call on every endpoint hit.
    try:
        from app.db.pool_stats import get_pool_stats
        pool_stats = get_pool_stats()
    except Exception as e:
        pool_stats = {"available": False, "error": str(e)[:120]}

    # REL-05 — WebSocket population counts. These are in-memory ints,
    # zero cost to read. `cc_connections_active` is the strict size of
    # the Command Center set; `num_ws_connections` is the *total*
    # unique-socket count across every registered WS connection
    # tracker we know about. If a future module adds another tracker
    # it should expose a `total_connections()` accessor here.
    cc_connections_active = 0
    num_ws_connections = 0
    try:
        from app.api.ws_command_center import cc_connections_count
        cc_connections_active = cc_connections_count()
        num_ws_connections += cc_connections_active
    except Exception:
        pass
    try:
        from app.api.realtime_events import ws_manager
        num_ws_connections += ws_manager.total_connections()
    except Exception:
        pass

    return {
        "pid": os.getpid(),
        "python_version": sys.version.split()[0],
        "uptime_seconds": round(time.time() - create_time, 1),
        "cmdline": cmdline,
        "parent_cmdlines": parent_cmdlines,
        "reload_detected": reload_detected,
        "workers": workers_arg,
        "host": os.environ.get("HOSTNAME") or os.uname().nodename,
        "app_env": os.environ.get("APP_ENV") or os.environ.get("NISCHINT_ROLE"),
        "memory_rss_mb": rss_mb,
        "memory_vms_mb": vms_mb,
        "cgroup_mem_limit_mb": cgroup_mem_limit_mb,
        "cgroup_mem_used_mb": cgroup_mem_used_mb,
        "cgroup_mem_pct": (
            round(100 * cgroup_mem_used_mb / cgroup_mem_limit_mb, 1)
            if cgroup_mem_limit_mb and cgroup_mem_used_mb else None
        ),
        "num_fds": num_fds,
        "num_threads": num_threads,
        "num_inet_connections": num_connections,
        "asyncio_task_count": task_count,
        "asyncio_loop_lag_ms": loop_lag_ms,
        # REL-05 — WebSocket population
        "cc_connections_active": cc_connections_active,
        "num_ws_connections":    num_ws_connections,
        # REL-04 — Postgres connection-pool fields. Flat in the response
        # so the dashboard can read them without an extra hop.
        **pool_stats,
    }




@router.get("/queue-health", dependencies=[Depends(_read_role)])
async def get_queue_health():
    """Get Redis queue health metrics."""
    try:
        from app.services.queue_service import get_queue_stats
        return get_queue_stats()
    except ImportError:
        return {"status": "queue_service_not_loaded", "queues": {}}


@router.get("/schedulers", dependencies=[Depends(_read_role)])
async def get_scheduler_health():
    """Truth source for Phase 1 scheduler-isolation health.

    Read-only deterministic snapshot. Reads cross-process state from Redis
    when available so an `api`-only process can still see drift recorded
    by a `scheduler`-only process. Falls back to in-process state if
    Redis is down — the endpoint never live-introspects a remote
    scheduler, so it can't itself become a timing hazard.

    Reported per job:
      • next_run_time         from APScheduler (where reachable in proc)
      • last_run_drift_ms     scheduled vs actual fire (positive = late)
      • last_duration_ms      wall-clock execution time
      • drift_p50_ms / p95_ms over the rolling last-50-runs window
      • missed_count          EVENT_JOB_MISSED firings
      • error_count           EVENT_JOB_ERROR firings

    Global status:
      • healthy   no missed jobs, p95 drift ≤ 1 s
      • warning   any error fired
      • degraded  any missed job OR p95 drift > 1 s
    """
    from app.services.scheduler_metrics import get_snapshot
    return get_snapshot()


@router.post("/schedulers/reset-baseline", dependencies=[Depends(require_role(["admin"]))])
async def reset_scheduler_baseline():
    """Drop every job's rolling drift window. Run this immediately after
    flipping `NISCHINT_ROLE=api` in production so pre-isolation drift
    samples don't poison the post-isolation p95.

    Admin-only — destructive to the metric, not to the schedulers.
    """
    from app.services.scheduler_metrics import reset_drift_baseline
    return reset_drift_baseline()


# ── SB-02 — user_signal_baselines matview maintenance ────────────


@router.get(
    "/baselines/status",
    dependencies=[Depends(_read_role)],
)
async def user_signal_baselines_status(
    session: AsyncSession = Depends(get_db_session),
):
    """SB-02 — last refresh metadata + freshness verdict for the
    `user_signal_baselines` matview. Read-only, safe for the
    operator chip's poll loop."""
    from app.services.user_signal_baseline_service import get_refresh_status
    return await get_refresh_status(session)


@router.post(
    "/baselines/refresh",
    dependencies=[Depends(require_role(["admin"]))],
)
async def user_signal_baselines_refresh(
    session: AsyncSession = Depends(get_db_session),
):
    """SB-02 — manual `REFRESH MATERIALIZED VIEW CONCURRENTLY`.
    Admin-only because the refresh writes the meta row + runs a
    DB-wide statement; not a thing operators should pull on a
    schedule. Returns the same envelope as the scheduler logs."""
    from app.services.user_signal_baseline_service import (
        refresh_user_signal_baselines,
    )
    return await refresh_user_signal_baselines(session)


# ── SF-03 — Survey of India boundary precision audit ──────────────


@router.get(
    "/soi-boundaries/status",
    dependencies=[Depends(_read_role)],
)
async def soi_boundaries_status(
    session: AsyncSession = Depends(get_db_session),
):
    """SF-03 — list every `env_hazard_zones` row tagged as
    SOI-approximate. The operator console renders each row as a
    'REPLACE WITH OFFICIAL MoEFCC SHAPEFILE' tile with the locked
    boundary_notes verbatim. Read-only; safe for chip-style polling."""
    from app.services.soi_boundary_audit import list_soi_approx_rows
    return {"rows": await list_soi_approx_rows(session)}


# ── REL-02 — backend log tail ────────────────────────────────────


@router.get(
    "/logs/tail",
    dependencies=[Depends(_read_role)],
)
async def logs_tail(
    lines: int = 100,
    since_minutes: int | None = None,
):
    """REL-02 — return the last N lines of `backend.*.log`.

    Both operator and admin roles can read this (debug aid). The
    service layer clamps `lines` to [1, 500] and `since_minutes` to
    [1, 1440] — the operator UI doesn't have to defend against
    user-typed extremes. NEVER raises; missing log files return
    an empty `lines` list."""
    from app.services.log_tail_service import tail_backend_logs
    return tail_backend_logs(lines=lines, since_minutes=since_minutes)


@router.get("/incidents", dependencies=[Depends(_read_role)])
async def list_system_incidents(
    limit: int = Query(50, ge=1, le=500),
    status: Optional[str] = Query(None, regex="^(active|resolved)$"),
    session: AsyncSession = Depends(get_db_session),
):
    """List historical system_incidents — write-only-on-transition.

    Most recent first. Filters: `?status=active` or `?status=resolved`.
    Snapshot JSON is returned in full for the incident replay view.
    """
    from app.models.system_incident import SystemIncident
    q = select(SystemIncident).order_by(SystemIncident.started_at.desc()).limit(limit)
    if status:
        q = q.where(SystemIncident.status == status)
    rows = (await session.execute(q)).scalars().all()
    return {
        "count": len(rows),
        "incidents": [
            {
                "id":             str(r.id),
                "status":         r.status,
                "severity_peak":  r.severity_peak,
                "trigger_source": r.trigger_source,
                "trigger_metric": r.trigger_metric,
                "root_cause_domain": r.root_cause_domain,
                "started_at":     r.started_at.isoformat() if r.started_at else None,
                "resolved_at":    r.resolved_at.isoformat() if r.resolved_at else None,
                "duration_ms":    r.duration_ms,
                "snapshot":       r.snapshot_json,
                "resolution":     r.resolution_json,
            } for r in rows
        ],
    }


@router.get("/system-health", dependencies=[Depends(_read_role)])
async def get_system_health(session: AsyncSession = Depends(get_db_session)):
    """Multi-signal real-time operational state — the system truth layer.

    Aggregates every domain that affects operator situational awareness
    in one polled snapshot:

      • schedulers     drift p95, missed jobs, status
      • ai             inference p95, success/error counters
      • queue          Redis stream depth (incident / ai_signal / notification)
      • websocket      active Command Center connections
      • risk_engine    last cycle status of dynamic_risk_cycle

    Designed to be polled every 20–30 s by the operator dashboard
    capsule. Read-only. Cross-process safe (reads from Redis where
    available, in-process otherwise).
    """
    from app.services.scheduler_metrics import get_snapshot as scheduler_snap
    from app.services.ai_metrics import get_snapshot as ai_snap
    from app.services.auth_metrics import get_snapshot as auth_snap

    sched = scheduler_snap()
    ai = ai_snap()
    auth = auth_snap()

    # Queue depth — reuse existing helper
    try:
        from app.services.queue_service import get_queue_stats
        qstats = get_queue_stats() or {}
    except Exception:
        qstats = {}
    q_depth = sum(
        int((v or {}).get("pending", 0))
        for v in (qstats.get("queues") or {}).values()
    )

    # WS — Command Center connections (operator console)
    try:
        from app.api.ws_command_center import _cc_connections
        ws_active = len(_cc_connections)
    except Exception:
        ws_active = None

    # Risk Engine — derive from the dynamic_risk_cycle scheduler row
    risk_engine = "unknown"
    risk_last_at = None
    for j in sched.get("jobs", []):
        if j.get("id") == "dynamic_risk_cycle":
            ls = (j.get("last_status") or "").lower()
            if ls == "success":
                risk_engine = "stable"
            elif ls == "error":
                risk_engine = "degraded"
            elif ls == "missed":
                risk_engine = "stalled"
            risk_last_at = j.get("last_run_at")
            break

    # Roll up domain statuses into a single SYSTEM verdict.
    # Worst-of: degraded > warning > healthy.
    # NOTE: auth rollup mirrors `_classify_auth` in `health_thresholds.py`
    # — same 10-sample floor + 60 s startup grace. Keep them in sync.
    from app.services.health_thresholds import (
        AUTH_MIN_SAMPLES_DEGRADED, AUTH_STARTUP_GRACE_S, _PROCESS_START_TS,
    )
    import time as _t
    auth_samples = int(auth.get("samples") or 0)
    auth_p95 = auth.get("p95_ms")
    auth_domain = "healthy"
    if (
        (_t.time() - _PROCESS_START_TS) >= AUTH_STARTUP_GRACE_S
        and auth_samples >= AUTH_MIN_SAMPLES_DEGRADED
        and auth_p95 is not None
        and auth_p95 > 500
    ):
        auth_domain = "degraded"

    # SB-02 — baselines matview health. Read the meta row; classify
    # via the same threshold engine that fires the system_health_delta
    # transition events, so the snapshot endpoint and the WS push
    # never disagree about the verdict.
    baselines_status: dict = {}
    baselines_domain = "healthy"
    try:
        from datetime import datetime as _dt
        from app.services.health_thresholds import _classify_baselines
        from app.services.user_signal_baseline_service import (
            classify_freshness, get_refresh_status,
        )
        baselines_status = await get_refresh_status(session)
        last_iso = baselines_status.get("last_refreshed_at")
        last_dt = _dt.fromisoformat(last_iso) if last_iso else None
        sev, _metric, _value = _classify_baselines(
            baselines_status.get("last_status"), last_dt,
        )
        baselines_domain = sev
    except Exception:
        # DB unreachable / matview missing → don't crash the capsule.
        # Mark warning so the operator notices the missing signal.
        baselines_domain = "warning"

    domains = {
        "schedulers": sched.get("status", "unknown"),
        "ai":         "healthy" if (ai.get("p95_ms") is None or ai.get("p95_ms") < 3000) else "degraded",
        "auth":       auth_domain,
        "queue":      "healthy" if q_depth < 100 else ("warning" if q_depth < 500 else "degraded"),
        "ws":         "healthy",
        "risk_engine": "healthy" if risk_engine == "stable" else (
            "warning" if risk_engine == "unknown" else "degraded"
        ),
        "baselines":  baselines_domain,
    }
    if "degraded" in domains.values():
        system_status = "degraded"
    elif "warning" in domains.values():
        system_status = "warning"
    else:
        system_status = "healthy"

    return {
        "status":      system_status,
        "domains":     domains,
        "schedulers": {
            "status":       sched.get("status"),
            "drift_p50_ms": sched.get("drift_p50_ms"),
            "drift_p95_ms": sched.get("drift_p95_ms"),
            "missed_total": sched.get("missed_total"),
            "error_total":  sched.get("error_total"),
            "count":        sched.get("scheduler_count"),
            "role":         sched.get("role"),
        },
        "ai": {
            "p50_ms":         ai.get("p50_ms"),
            "p95_ms":         ai.get("p95_ms"),
            "calls_total":    ai.get("calls_total"),
            "success_count":  ai.get("success_count"),
            "error_count":    ai.get("error_count"),
            "samples":        ai.get("samples"),
        },
        "auth": {
            "p50_ms":        auth.get("p50_ms"),
            "p95_ms":        auth.get("p95_ms"),
            "samples":       auth.get("samples"),
            "window_s":      auth.get("window_s"),
            "hits_window":   auth.get("hits_window"),
            "misses_window": auth.get("misses_window"),
            "hit_rate":      auth.get("hit_rate"),
            "hits_total":    auth.get("hits_total"),
            "misses_total":  auth.get("misses_total"),
        },
        "queue": {
            "pending_total": q_depth,
            "by_stream":     qstats.get("queues", {}),
        },
        "websocket": {
            "command_center_active": ws_active,
        },
        "risk_engine": {
            "state":       risk_engine,
            "last_run_at": risk_last_at,
        },
        "baselines": {
            # SB-02 — operator capsule reads `last_refreshed_at`,
            # `freshness`, and `last_status` to render the chip.
            # `last_error` surfaces in the flyout for the failure case.
            "last_refreshed_at":        baselines_status.get("last_refreshed_at"),
            "last_refresh_duration_ms": baselines_status.get("last_refresh_duration_ms"),
            "last_refresh_rows":        baselines_status.get("last_refresh_rows"),
            "last_status":              baselines_status.get("last_status"),
            "last_error":               baselines_status.get("last_error"),
            "freshness":                baselines_status.get("freshness"),
            "threshold_s":              baselines_status.get("threshold_s"),
        },
    }



@router.get("/prewarmers", dependencies=[Depends(_read_role)])
async def get_all_prewarmers_rollup():
    """NISCH-012.4+ — single-call roll-up of every provider health
    state. Replaces the 4-call fan-out the operator capsule used to
    do every 30 s (75% reduction in dashboard chatter).

    Shape (stable; clients should treat unknown keys as additive):

        {
          "v2_parity":  {"tier", "critical_count", "match_pct", ...},
          "sachet":     {"health_state", "cache_age_seconds", ...},
          "tomtom":     {"health_state", "cache_age_seconds", ...},
          "news":       {"health_state", "cache_age_seconds",
                         "channels": {newsapi, rss}, ...}
        }

    REST reconciliation layer only — real-time transitions still
    fire over the WS `system_health_delta` channel per source."""
    from app.services import alert_trigger_v2_shadow as _v2s
    from app.services.external_signals.sachet_prewarmer import (
        get_health_state as sachet_state,
        get_prewarmer_telemetry as sachet_tele,
    )
    from app.services.external_signals.tomtom_prewarmer import (
        get_health_state as tomtom_state,
        get_prewarmer_telemetry as tomtom_tele,
    )
    from app.services.external_signals.news_prewarmer import (
        get_health_state as news_state,
        get_prewarmer_telemetry as news_tele,
    )

    # ── v2_parity — slim subset of the shadow-stats digest ───
    diag = _v2s.get_diagnostic_summary() or {}
    # Worst tier wins for the roll-up — the capsule already shows
    # per-kind detail via the dedicated V2ParityChip flyout.
    tier_rank = {"in_parity": 0, "drift": 1, "critical": 2}
    worst_tier = "in_parity"
    worst_kind = None
    crit_total = 0
    match_pcts: list[float] = []
    by_kind: dict = {}
    for kind, d in diag.items():
        tier = d.get("tier", "in_parity")
        if tier_rank.get(tier, 0) > tier_rank.get(worst_tier, 0):
            worst_tier = tier
            worst_kind = kind
        crit_total += int(d.get("critical_count", 0) or 0)
        if d.get("match_pct") is not None:
            match_pcts.append(float(d["match_pct"]))
        by_kind[kind] = {
            "tier":           tier,
            "match_pct":      d.get("match_pct"),
            "critical_count": d.get("critical_count", 0),
            "auto_disabled":  (d.get("safety") or {}).get(
                "auto_disabled", False,
            ),
        }
    v2_block = {
        "tier":           worst_tier,
        "worst_kind":     worst_kind,
        "critical_count": crit_total,
        "match_pct": (
            round(sum(match_pcts) / len(match_pcts), 2)
            if match_pcts else None
        ),
        "by_kind":        by_kind,
    }

    # ── External provider blocks ─────────────────────────────
    def _slim(state_fn, tele_fn) -> dict:
        st = state_fn()
        tele = tele_fn()
        return {
            "health_state":      st.get("state"),
            "cache_age_seconds": tele.get("cache_age_seconds"),
            "last_success_ts":   tele.get("last_success_ts"),
            "parse_failure_rate": tele.get("parse_failure_rate"),
            "recovery_progress": tele.get("recovery_progress", 0),
            "recovery_required": tele.get("recovery_required", 3),
        }

    news_block = _slim(news_state, news_tele)
    news_block["channels"] = news_tele().get("channels", {})

    return {
        "v2_parity": v2_block,
        "sachet":    _slim(sachet_state, sachet_tele),
        "tomtom":    _slim(tomtom_state, tomtom_tele),
        "news":      news_block,
    }


@router.get("/alert-v2/shadow-stats", dependencies=[Depends(_read_role)])
async def get_alert_v2_shadow_stats(limit: int = Query(50, ge=1, le=500)):
    """ALERT_TRIGGER_V2 shadow-mode telemetry — diagnostic, not decorative.

    Returns:
      * `mode`: `"shadow"` (V2 is observation-only).
      * `rollout`: per-kind env-var rollout %.
      * `diagnostic`: per-kind digest used by the operator V2 Parity
        Chip — match%, critical count, ΔFanout, worst recent
        classification, full per-classification breakdown, and the
        rolling safety state (auto-disable verdict).
      * `legacy_counters`: the old 3-bucket roll-up
        (`match`/`fanout_diff`/`decision_diff`), kept for older
        consumers — prefer `diagnostic` above.
      * `recent_events`: last N comparison rows for forensic replay.
    """
    from app.services import alert_trigger_v2_shadow as _v2s

    return {
        "version":          "v2",
        "mode":             "shadow",
        "rollout":          _v2s.get_rollout_state(),
        "diagnostic":       _v2s.get_diagnostic_summary(),
        "legacy_counters":  _v2s.get_counter_snapshot(),
        "recent_events":    _v2s.get_recent_events(limit=limit),
    }


@router.post("/alert-v2/clear-autodisable",
             dependencies=[Depends(require_role(["admin"]))])
async def clear_alert_v2_autodisable(kind: str = Query(...)):
    """Operator-facing manual reset of the V2 autodisable safeguard
    for a given kind family. Admin-only — bypasses the safeguard so
    use only after investigating the critical-regression evidence.

    The autodisable flag is set automatically by the shadow runner
    when the rolling 10-minute critical-regression rate breaches 5%.
    Once cleared, V2 can fire again per the env-var rollout %, but
    the safeguard immediately re-arms and will fire again if the
    issue recurs."""
    from app.services import alert_trigger_v2_shadow as _v2s
    cleared = _v2s.clear_autodisable(kind)
    return {"kind": kind, "cleared": cleared}


@router.get("/sachet-prewarmer", dependencies=[Depends(_read_role)])
async def get_sachet_prewarmer_status():
    """NISCH-012.3 — Sachet (NDMA) pre-warmer freshness telemetry.

    Returns the rolling health snapshot that proves the background
    job is keeping the NDMA cache fresh:

      * `last_fetch_ts`        — when the job last *attempted* a fetch
      * `last_success_ts`      — when the job last got a non-empty
                                 feed back (this is the operationally
                                 important one — the cache only
                                 advances on success)
      * `cache_age_seconds`    — derived from `last_success_ts` at
                                 read time so a stalled scheduler
                                 can't fake freshness
      * `parse_failure_rate`   — rolling fraction of the last
                                 `history_window` attempts that
                                 failed (transient outage detector)
      * `active_alert_count`   — alerts in the last successful parse
      * `cache_ttl_s`          — for client-side staleness compare
      * `health_state`         — `healthy` | `stale` | `degraded` |
                                 `unknown` — same machine that drives
                                 the operator UI capsule
      * `recovery_progress`    — counter for the asymmetric hysteresis
                                 (regression snaps; recovery needs N
                                 consecutive clean reads)

    Read-only. Safe to poll every 30 s from the operator dashboard."""
    from app.services.external_signals.sachet_prewarmer import (
        get_prewarmer_telemetry,
    )
    return get_prewarmer_telemetry()


@router.get("/tomtom-prewarmer", dependencies=[Depends(_read_role)])
async def get_tomtom_prewarmer_status():
    """NISCH-012.1 — TomTom Flow pre-warmer freshness telemetry.

    Mirrors `/sachet-prewarmer` exactly so the operator UI can poll
    a single shape across providers. When `TOMTOM_API_KEY` is
    absent, returns `{"health_state": "disabled", "reason":
    "no_api_key"}` and the scheduler refuses to register — no
    log spam, no Redis churn.

    Read-only. Safe to poll every 30 s."""
    from app.services.external_signals.tomtom_prewarmer import (
        get_prewarmer_telemetry,
    )
    return get_prewarmer_telemetry()


@router.get("/news-prewarmer", dependencies=[Depends(_read_role)])
async def get_news_prewarmer_status():
    """NISCH-012.2 — News/Social pre-warmer telemetry.

    Returns the standard shape plus a `channels` block with
    independent NewsAPI vs RSS health. RSS is always on; NewsAPI
    surfaces as `enabled: false` when `NEWSAPI_KEY` is absent."""
    from app.services.external_signals.news_prewarmer import (
        get_prewarmer_telemetry,
    )
    return get_prewarmer_telemetry()


@router.get("/dlqs", dependencies=[Depends(_read_role)])
async def get_dlq_status():
    """DLQ reconciler rollup — depth + poison-list status across the
    four audit-row DLQs. The capsule chip uses `any_amber`/`any_red`
    for colour and per-DLQ `pressure_pct` for the tooltip. Polling
    at 30 s is fine — the reconciler ticks at 60 s so anything
    tighter is wasted load."""
    from app.services.dlq_reconciler import get_dlq_stats
    return get_dlq_stats()


# ── REL-08 — Command Center capsule batch endpoint ───────────────────


_DASHBOARD_SUMMARY_CACHE_NS = "monitoring"
_DASHBOARD_SUMMARY_CACHE_KEY = "dashboard_summary"
_DASHBOARD_SUMMARY_TTL_S = 10


async def _gather_dashboard_summary() -> dict:
    """Fan out to the five capsule data sources concurrently.

    Each source is wrapped in its own try/except returning a stable
    error shape — a single source failing must NEVER prevent the
    remaining four capsules from rendering. The frontend treats a
    `{"error": "..."}` block as "show capsule in error tone, keep
    last-good state where possible".
    """
    import asyncio
    from sqlalchemy import select
    from app.api.deps import get_db_session as _gds

    # ── individual fetchers ────────────────────────────────────────
    async def _dlqs() -> dict:
        try:
            from app.services.dlq_reconciler import get_dlq_stats
            return get_dlq_stats()
        except Exception as e:
            return {"error": str(e)[:200]}

    async def _sachet() -> dict:
        try:
            from app.services.external_signals.sachet_prewarmer import (
                get_prewarmer_telemetry,
            )
            return get_prewarmer_telemetry()
        except Exception as e:
            return {"error": str(e)[:200]}

    async def _db_pool_and_incidents() -> dict:
        out: dict = {}
        try:
            from app.db.pool_stats import get_pool_stats
            out["pool"] = get_pool_stats()
        except Exception as e:
            out["pool"] = {"available": False, "error": str(e)[:200]}
        try:
            from app.models.system_incidents import SystemIncident
            async for sess in _gds():
                q = (
                    select(SystemIncident)
                    .where(SystemIncident.trigger_source == "database_pool")
                    .where(SystemIncident.status == "active")
                    .order_by(SystemIncident.started_at.desc())
                    .limit(5)
                )
                rows = (await sess.execute(q)).scalars().all()
                out["active_incidents"] = [
                    {
                        "id":              str(r.id),
                        "trigger_source":  r.trigger_source,
                        "severity_peak":   r.severity_peak,
                        "status":          r.status,
                        "started_at":      r.started_at.isoformat() if r.started_at else None,
                    }
                    for r in rows
                ]
                break
        except Exception as e:
            out["active_incidents"] = []
            out["incidents_error"]  = str(e)[:200]
        return out

    async def _consent_health() -> dict:
        try:
            from app.api.consents import compute_consent_health
            async for sess in _gds():
                bundle = await compute_consent_health(sess)
                # `generated_at` is a datetime → ISO-string for JSON.
                d = bundle.model_dump()
                if hasattr(d.get("generated_at"), "isoformat"):
                    d["generated_at"] = d["generated_at"].isoformat()
                return d
        except Exception as e:
            return {"error": str(e)[:200]}
        return {"error": "unreachable"}

    async def _trust_badge() -> dict:
        try:
            # Reuse the locked endpoint's cache directly. Calling
            # the handler would require constructing a request — the
            # cache read is the cheaper path and matches the locked
            # 10s TTL semantics.
            from app.api.behavioral import _cache_read
            cached = _cache_read()
            if cached is not None:
                return cached
            # Fall-through fallback per the locked spec — never block
            # the batch endpoint on a trust-recompute, and never
            # surface LOW_TRUST from a missing cache. The dedicated
            # endpoint will populate the cache on its next caller.
            return {
                "level":  "MEDIUM_TRUST",
                "color":  "yellow",
                "reason": "telemetry_unavailable",
            }
        except Exception:
            return {
                "level":  "MEDIUM_TRUST",
                "color":  "yellow",
                "reason": "telemetry_unavailable",
            }

    # Fan-out
    dlqs, sachet, db, consent, trust = await asyncio.gather(
        _dlqs(), _sachet(), _db_pool_and_incidents(), _consent_health(), _trust_badge(),
        return_exceptions=False,
    )
    return {
        "dlqs":     dlqs,
        "sachet":   sachet,
        "db":       db,
        "consent":  consent,
        "trust":    trust,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/dashboard-summary", dependencies=[Depends(_read_role)])
async def get_dashboard_summary():
    """REL-08 — Batched telemetry for the Command Center capsule strip.

    Returns a single JSON envelope containing the data each of the
    five status capsules needs (DLQ / DB / SACHET / Consent / TwinTrust)
    so the dashboard pays one network round-trip per poll instead of
    five.

    Cached in Redis for 10 s under
    `monitoring:dashboard_summary`. The cache is process-shared, so
    a six-operator team produces the same cache pressure as one
    operator. Cache invalidation strategy: pure TTL — every metric
    here is already a rolled-up health state with its own
    backing-cache TTL (DLQ 30 s reconciler, SACHET 5 min prewarmer,
    consent table aggregation, trust 10 s), so a stale 10 s shared
    cache layered on top never produces a worse view than the
    capsules' previous per-source polling.

    Shape:
      {
        "dlqs":    { ... get_dlq_stats() ... },
        "sachet":  { ... sachet prewarmer telemetry ... },
        "db":      {
          "pool":             { ... get_pool_stats() ... },
          "active_incidents": [ { id, severity_peak, status, started_at, ... } ]
        },
        "consent": { ... ConsentHealthBundle ... },
        "trust":   { "level": ..., "color": ..., "reason": ... },
        "generated_at": "<ISO-UTC>"
      }
    """
    from app.services import redis_service

    # Fast path — Redis cache hit. We `get_json` directly so missing
    # / expired entries return None and we slide into the recompute.
    try:
        cached = redis_service.get_json(
            _DASHBOARD_SUMMARY_CACHE_NS,
            _DASHBOARD_SUMMARY_CACHE_KEY,
        )
        if cached is not None:
            cached["_cache_hit"] = True
            return cached
    except Exception:
        # Redis down → never block. Fall through to recompute.
        pass

    summary = await _gather_dashboard_summary()
    summary["_cache_hit"] = False
    try:
        redis_service.set_json(
            _DASHBOARD_SUMMARY_CACHE_NS,
            _DASHBOARD_SUMMARY_CACHE_KEY,
            summary,
            ttl=_DASHBOARD_SUMMARY_TTL_S,
        )
    except Exception:
        # Redis write failure is non-fatal; we just lose the cache.
        pass
    return summary



@router.post(
    "/dlqs/{dlq_key:path}/poison/drain",
    dependencies=[Depends(require_role(["admin"]))],
)
async def drain_dlq_poison(
    dlq_key: str,
    replay: bool = False,
    max_drain: int = 100,
):
    """Operator-triggered drain of a `dlq:<key>:poison` list.

    `replay=false` (default) → hard-discard, returns the popped
    payloads in `items` so the caller can CSV-export them for
    offline reconciliation. The live DLQ is unaffected.

    `replay=true` → re-routes each poisoned entry through the
    per-DLQ replay function with `_attempts` reset. Successes drop
    the entry; failures LPUSH back onto the poison list.

    Admin-only — this is a destructive operation. `dlq_key` MUST
    be one of the four registered DLQ keys, e.g.
    `dlq:failsafe_audit`."""
    from fastapi import HTTPException
    from app.services.dlq_reconciler import (
        drain_poison_list, is_known_dlq, POISON_MAX,
    )
    if not is_known_dlq(dlq_key):
        raise HTTPException(
            status_code=404,
            detail=f"unknown dlq key: {dlq_key}",
        )
    if max_drain < 1 or max_drain > POISON_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"max_drain must be 1..{POISON_MAX}, got {max_drain}",
        )
    return await drain_poison_list(
        dlq_key, replay=replay, max_drain=max_drain,
    )
@router.get("/external-signals/active", dependencies=[Depends(_read_role)])
async def get_active_external_signals():
    """NISCH-012.4 + NISCH-012.1 — operator surface for
    *currently-active* external signal modifiers.

    Unified across providers. The shape is `{ <source>:
    {health_state, modifiers: [...]} }` so the Command Center
    capsule lists modifiers with consistent columns regardless of
    source.

    Implemented for Sachet (NDMA) and TomTom (Flow). Weather is
    fetched per-incident on the alert hot-path and is not
    pre-cached, so it appears with `note: per_request`.
    """
    from app.services.external_signals.sachet_provider import (
        CACHE_KEY as SACHET_CACHE_KEY,
        CACHE_NAMESPACE as SACHET_CACHE_NS,
        SEVERITY_RISK as SACHET_SEVERITY_RISK,
        SIGNAL_TTL_S as SACHET_SIGNAL_TTL_S,
        STATE_BBOX,
    )
    from app.services.external_signals.sachet_prewarmer import (
        get_health_state as sachet_health_state,
        get_prewarmer_telemetry as sachet_telemetry,
    )
    from app.services.external_signals.tomtom_provider import (
        CACHE_KEY as TOMTOM_CACHE_KEY,
        CACHE_NAMESPACE as TOMTOM_CACHE_NS,
        SEVERITY_RISK as TOMTOM_SEVERITY_RISK,
        SIGNAL_TTL_S as TOMTOM_SIGNAL_TTL_S,
    )
    from app.services.external_signals.tomtom_prewarmer import (
        get_health_state as tomtom_health_state,
        get_prewarmer_telemetry as tomtom_telemetry,
        is_provider_enabled as tomtom_enabled,
    )
    from app.services import redis_service

    # ── Sachet ────────────────────────────────────────────
    sachet_cached = redis_service.get_json(SACHET_CACHE_NS, SACHET_CACHE_KEY) or []
    state_names = list(STATE_BBOX.keys())

    def _zones_for(title: str) -> list[str]:
        if not title:
            return []
        lower = title.lower()
        return [s for s in state_names if s.lower() in lower]

    sachet_modifiers: list[dict] = []
    for alert in sachet_cached:
        severity = (alert.get("severity") or "minor").lower()
        zones = _zones_for(alert.get("title", "")) or ["india"]
        for zone in zones:
            sachet_modifiers.append({
                "zone":     zone,
                "severity": severity,
                "strength": float(SACHET_SEVERITY_RISK.get(severity, 0.30)),
                "title":    alert.get("title"),
                "category": alert.get("category"),
                "expiry_window_s": SACHET_SIGNAL_TTL_S,
                "fetched_at": alert.get("pub_date_iso"),
                "raw_url":  alert.get("link"),
            })

    sachet_tele = sachet_telemetry()

    # ── TomTom ────────────────────────────────────────────
    tomtom_block: dict
    if not tomtom_enabled():
        tomtom_block = {
            "source": "tomtom",
            "state":  "disabled",
            "reason": "no_api_key",
        }
    else:
        tomtom_cached = redis_service.get_json(TOMTOM_CACHE_NS, TOMTOM_CACHE_KEY) or []
        tomtom_modifiers: list[dict] = []
        for reading in tomtom_cached:
            severity = (reading.get("severity") or "minor").lower()
            zone = (reading.get("zone") or "unknown").lower().replace(" ", "_")
            tomtom_modifiers.append({
                "zone":            zone,
                "severity":        severity,
                "strength":        float(TOMTOM_SEVERITY_RISK.get(severity, 0.20)),
                "ratio":           reading.get("ratio"),
                "current_speed":   reading.get("current_speed"),
                "free_flow_speed": reading.get("free_flow_speed"),
                "road_closure":    reading.get("road_closure", False),
                "expiry_window_s": TOMTOM_SIGNAL_TTL_S,
                "fetched_at":      None,
                "raw_url":         None,
            })
        tomtom_tele = tomtom_telemetry()
        tomtom_block = {
            "health_state":     tomtom_health_state().get("state"),
            "cache_age_seconds": tomtom_tele.get("cache_age_seconds"),
            "last_success_ts":  tomtom_tele.get("last_success_ts"),
            "active_count":     len(tomtom_modifiers),
            "modifiers":        tomtom_modifiers,
        }

    return {
        "sachet": {
            "health_state":      sachet_health_state().get("state"),
            "cache_age_seconds": sachet_tele.get("cache_age_seconds"),
            "last_success_ts":   sachet_tele.get("last_success_ts"),
            "active_count":      len(sachet_modifiers),
            "modifiers":         sachet_modifiers,
        },
        "tomtom": tomtom_block,
        "news":   _news_block(),
        "weather": {
            "note": "per_request",
            "reason": "Weather provider is fetched on the alert hot-path "
                      "with the location of the incident; it is not "
                      "pre-warmed, so there is no global active list.",
        },
    }


def _news_block() -> dict:
    """NISCH-012.2 — News provider surface. RSS is always on so the
    provider is never fully disabled; only the NewsAPI channel can
    be disabled (no key)."""
    from app.services.external_signals.news_provider import (
        CACHE_KEY as NEWS_CACHE_KEY,
        CACHE_NAMESPACE as NEWS_CACHE_NS,
        newsapi_enabled,
    )
    from app.services.external_signals.news_prewarmer import (
        get_health_state as news_health_state,
        get_prewarmer_telemetry as news_telemetry,
    )
    from app.services import redis_service

    cached = redis_service.get_json(NEWS_CACHE_NS, NEWS_CACHE_KEY) or []
    tele = news_telemetry()
    return {
        "health_state":     news_health_state().get("state"),
        "cache_age_seconds": tele.get("cache_age_seconds"),
        "last_success_ts":  tele.get("last_success_ts"),
        "active_count":     len(cached),
        "channels":         tele.get("channels", {}),
        "newsapi_enabled":  newsapi_enabled(),
        "modifiers":        cached,
    }


# ── SSE replay tail ─────────────────────────────────────────────────
# `cc:system_health_delta` events are broadcast over WS during normal
# operation. An operator who reloads Command Center mid-incident
# currently misses any transition that fired during the reload — the
# SSE endpoint below replays the last 10 transitions per source so
# the operator catches up before the live WS takes over.
#
# Locked invariants (user-mandated):
#   * Up to 10 transitions per source, in chronological order
#     (oldest first) — matches the natural narrative for catch-up.
#   * Same envelope format as the live WS payload — no new schema.
#   * Sources allow-listed in `system_health_history.KNOWN_SOURCES`.

async def _sh_stream_generator(request: Request):
    """SSE generator: on connect, emit one `system_health_delta`
    event per historical transition (per source, chronological).
    Then keep-alive pings until the client disconnects. Live events
    continue to flow via the existing WS channel — this endpoint is
    purely a reload-gap close.
    """
    from app.services.system_health_history import (
        KNOWN_SOURCES, get_recent_transitions,
    )

    # Initial "connected" handshake so the client can transition out
    # of its loading state immediately.
    handshake = {
        "type":   "stream_connected",
        "ts":     datetime.now(timezone.utc).isoformat(),
        "sources": list(KNOWN_SOURCES),
    }
    yield f"event: connected\ndata: {json.dumps(handshake)}\n\n"

    # Replay: merge sources, sort by timestamp where present so the
    # client sees a single chronological stream of transitions across
    # sources (matches how operators reason about incidents).
    merged: list[dict] = []
    for src in KNOWN_SOURCES:
        merged.extend(get_recent_transitions(src, limit=10))
    merged.sort(key=lambda e: e.get("iso") or e.get("ts") or "")

    for evt in merged:
        # SSE event type matches the WS envelope's `type` so the
        # frontend can route both pipelines through the same
        # `cc:system_health_delta` window dispatch.
        ev_type = evt.get("type", "system_health_delta")
        yield f"event: {ev_type}\ndata: {json.dumps(evt, default=str)}\n\n"

    # Keep-alive: a single comment line every ~25 s so intermediaries
    # don't reap an idle connection. We do NOT forward live events
    # here — the WS channel owns live delivery. This SSE is purely
    # the reload-gap close.
    keepalive_interval_s = 25
    while True:
        if await request.is_disconnected():
            break
        await asyncio.sleep(keepalive_interval_s)
        yield ": keepalive\n\n"


@router.get("/system-health-stream")
async def system_health_stream(
    request: Request,
    token: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_db_session),
):
    """SSE: last-10 transitions per source on connect (chronological),
    then keep-alive. Read-only; admin/operator only.

    Auth: token via query param (browser EventSource cannot set
    custom headers — same pattern as `/api/stream`)."""
    from app.api.stream import get_user_from_token
    # Reuse the canonical SSE auth helper.
    user = await get_user_from_token(token=token, session=session)
    if user.role not in ("admin", "operator"):
        from fastapi import HTTPException, status as _status
        raise HTTPException(
            status_code=_status.HTTP_403_FORBIDDEN,
            detail="admin/operator only",
        )
    return StreamingResponse(
        _sh_stream_generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control":      "no-cache",
            "Connection":         "keep-alive",
            "X-Accel-Buffering":  "no",
        },
    )


@router.get("/system-health-stream/tail", dependencies=[Depends(_read_role)])
async def system_health_stream_tail():
    """REST companion of the SSE stream — returns the same replay
    payload as a JSON document. Useful for diagnostic curl and for
    clients that prefer a one-shot HTTP request over EventSource."""
    from app.services.system_health_history import (
        KNOWN_SOURCES, get_recent_transitions,
    )
    merged: list[dict] = []
    by_source: dict = {}
    for src in KNOWN_SOURCES:
        events = get_recent_transitions(src, limit=10)
        by_source[src] = events
        merged.extend(events)
    merged.sort(key=lambda e: e.get("iso") or e.get("ts") or "")
    return {
        "sources":   list(KNOWN_SOURCES),
        "by_source": by_source,
        "merged":    merged,
    }
