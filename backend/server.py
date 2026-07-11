from fastapi import FastAPI, APIRouter, Request
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
import asyncpg
import logging
import os
import pathlib
import ssl
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
import uuid
from datetime import datetime, timezone
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# ── Phase 1 process isolation ─────────────────────────────────────────
# Load /app/backend/.env into os.environ BEFORE anything that reads
# NISCHINT_ROLE (role.py, scheduler_runner). Pydantic Settings reads .env
# into its own model only — it does NOT populate os.environ — so role
# gating must be wired up here, at import time.
from dotenv import load_dotenv
load_dotenv(dotenv_path=str(pathlib.Path(__file__).resolve().parent / ".env"),
            override=False)
# FORCE NISCHINT_ROLE=all — Emergent UI secret is read-only (set to "api"),
# this line overrides it at runtime so single-process Emergent deployments
# always run schedulers. Safe to remove once Emergent allows secret editing.
os.environ["NISCHINT_ROLE"] = "all"

# ── Sentry Error Monitoring ──
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    _traces_rate = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1"))
    _profiles_rate = float(os.environ.get("SENTRY_PROFILES_SAMPLE_RATE", "0.1"))
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[FastApiIntegration()],
        traces_sample_rate=_traces_rate,
        profiles_sample_rate=_profiles_rate,
        environment=os.environ.get("SENTRY_ENV", "production"),
        auto_enabling_integrations=False,
        default_integrations=True,
    )
    print(
        f"Sentry monitoring + performance tracing enabled "
        f"(traces={_traces_rate}, profiles={_profiles_rate}, "
        f"auto_enabling_integrations=False)"
    )


from app.core.config import settings
# FORCE NISCHINT_ROLE=all before role module is imported and caches the value
import os as _os; _os.environ["NISCHINT_ROLE"] = "all"
from app.core.role import runs_schedulers, get_role
from app.core.rate_limiter import limiter
from app.core.security_headers import SecurityHeadersMiddleware
from app.api import api_router as domain_api_router
from app.services.escalation_scheduler import start_scheduler, stop_scheduler
from app.services.notification_worker import start_notification_worker, stop_notification_worker
from app.services.baseline_scheduler import start_baseline_scheduler, stop_baseline_scheduler
from app.services.behavior_ai import start_behavior_scheduler, stop_behavior_scheduler
from app.services.digital_twin_builder import start_twin_builder_scheduler, stop_twin_builder_scheduler
from app.services.predictive_engine import start_prediction_scheduler, stop_prediction_scheduler
from app.services.risk_learning_scheduler import start_risk_learning_scheduler, stop_risk_learning_scheduler
from app.services.dynamic_risk_scheduler import start_dynamic_risk_scheduler, stop_dynamic_risk_scheduler
from app.services.forecast_prewarm_scheduler import start_forecast_prewarm_scheduler, stop_forecast_prewarm_scheduler
from app.services.external_signals.sachet_prewarmer import start_sachet_prewarm_scheduler, stop_sachet_prewarm_scheduler
from app.services.external_signals.tomtom_prewarmer import start_tomtom_prewarm_scheduler, stop_tomtom_prewarm_scheduler
from app.services.external_signals.news_prewarmer import start_news_prewarm_scheduler, stop_news_prewarm_scheduler
from app.services.external_signals.owm_alerts_prewarmer import start_owm_alerts_prewarm_scheduler, stop_owm_alerts_prewarm_scheduler
from app.services.user_signal_baselines_scheduler import start_user_signal_baselines_scheduler, stop_user_signal_baselines_scheduler
from app.services.health_monitor import start_health_monitor, stop_health_monitor
from app.api.pr_intelligence import start_pr_nightly_scheduler
from app.services.geo_digest_service import start_geo_digest_scheduler
from app.services.dpdp_digest_service import start_dpdp_digest_scheduler
from app.services.db_pool_monitor import start_db_pool_monitor, stop_db_pool_monitor
from app.services.cc_ws_sweeper import start_cc_ws_sweeper, stop_cc_ws_sweeper
from app.api.entity_engine import start_geo_health_scheduler
from app.services.fleet_weather_service import start_fleet_weather_scheduler, shutdown_fleet_weather_scheduler
from app.services.sla_monitor import start_sla_monitor
from app.services.safety_incident_scheduler import start_safety_incident_scheduler
from app.services.risk_prediction.prewarmer import start_risk_prediction_prewarmer, stop_risk_prediction_prewarmer
from app.services.risk_prediction.reconciler_scheduler import start_risk_prediction_reconciler, stop_risk_prediction_reconciler
from app.services.behavioral.prewarmer import start_behavioral_baseline_prewarmer, stop_behavioral_baseline_prewarmer

# MongoDB connection
client = AsyncIOMotorClient(settings.mongo_url)
db = client[settings.db_name]

# PostgreSQL connection pool (Neon)
pg_pool: Optional[asyncpg.Pool] = None

async def get_pg_pool() -> Optional[asyncpg.Pool]:
    global pg_pool
    if pg_pool is None:
        try:
            _ssl_ctx = ssl.create_default_context()
            _ssl_ctx.check_hostname = False
            _ssl_ctx.verify_mode = ssl.CERT_NONE
            dsn = (os.environ.get("SUPABASE_DSN") or settings.database_url).split("?")[0]
            pg_pool = await asyncpg.create_pool(
                dsn,
                min_size=1,
                max_size=5,
                ssl=_ssl_ctx,
            )
        except Exception as e:
            logging.getLogger(__name__).error(f"PostgreSQL connection failed: {e}")
            pg_pool = None
    return pg_pool

# Create the main app with docs under /api prefix for ingress routing
app = FastAPI(docs_url="/api/docs", redoc_url="/api/redoc", openapi_url="/api/openapi.json")

# Root-level health check — deployment health check expects /health at root
@app.get("/health")
async def root_health():
    return {"status": "ok", "service": "nischint-api", "version": "1.0.0"}

# Rate limiter setup
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"error": "Too many requests. Please try again later."},
    )

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")


# Define Models
class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class StatusCheckCreate(BaseModel):
    client_name: str

# Add your routes to the router instead of directly to app
@api_router.get("/")
async def root():
    return {"message": "Hello World"}

@api_router.get("/health")
async def health():
    return {"status": "ok", "service": "nischint-api", "version": "1.0.0"}

@api_router.post("/sms/test")
async def test_sms(to: str, message: str = "NISCHINT test SMS — your SMS integration is working!"):
    """Send a test SMS to verify Twilio integration."""
    from app.services.sms_service import send_sms, is_available
    if not is_available():
        return {"success": False, "error": "Twilio not configured"}
    ok = send_sms(to, message)
    return {"success": ok, "to": to}

@api_router.get("/debug-sentry")
async def trigger_error():
    division_by_zero = 1 / 0

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.model_dump()
    status_obj = StatusCheck(**status_dict)
    
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()
    
    _ = await db.status_checks.insert_one(doc)
    return status_obj

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    status_checks = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    
    for check in status_checks:
        if isinstance(check['timestamp'], str):
            check['timestamp'] = datetime.fromisoformat(check['timestamp'])
    
    return status_checks

# Health check endpoint for PostgreSQL (Neon)
@api_router.get("/health/db")
async def health_check_db():
    try:
        pool = await get_pg_pool()
        if pool is None:
            return {"status": "error", "message": "DATABASE_URL not configured"}
        
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return {"status": "error", "message": str(e)}


@api_router.get("/system/cache-status")
async def cache_status():
    """Redis cache health check and status."""
    from app.services.redis_service import get_info
    return get_info()


@api_router.get("/system/osrm-status")
async def osrm_status():
    """OSRM routing engine health check."""
    from app.services.osrm_service import get_status
    return get_status()


@api_router.get("/system/forecast-cache-status")
async def forecast_cache_status():
    """Risk forecast cache monitoring."""
    from app.services.redis_service import get_all_forecast_keys, _forecast_mem_cache
    keys = get_all_forecast_keys()
    mem_entries = len(_forecast_mem_cache)
    return {
        "redis_keys": len(keys),
        "memory_entries": mem_entries,
        "ttl_seconds": 1800,
        "grid_cell_size_m": 250,
    }


@api_router.get("/system/live-status")
async def live_system_status():
    """
    Live system status for the public status page.
    Pings API, Database, Redis, and returns real latencies.
    """
    import time
    from app.services.redis_service import is_available as redis_ping, get_info as redis_info

    results = {}

    # 1. API health (always up if this runs)
    results["api"] = {"status": "operational", "latency_ms": 0}

    # 2. Database ping
    try:
        t0 = time.monotonic()
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        db_latency = round((time.monotonic() - t0) * 1000, 1)
        results["database"] = {"status": "operational", "latency_ms": db_latency}
    except Exception as e:
        results["database"] = {"status": "degraded", "latency_ms": None, "error": str(e)[:100]}

    # 3. Redis ping
    try:
        t0 = time.monotonic()
        ok = redis_ping()
        redis_latency = round((time.monotonic() - t0) * 1000, 1)
        if ok:
            info = redis_info()
            results["redis"] = {
                "status": "operational",
                "latency_ms": redis_latency,
                "used_memory_mb": info.get("used_memory_mb"),
                "connected_clients": info.get("connected_clients"),
            }
        else:
            results["redis"] = {"status": "degraded", "latency_ms": None}
    except Exception as e:
        results["redis"] = {"status": "degraded", "latency_ms": None, "error": str(e)[:100]}

    # 4. Event system (scheduler running?)
    try:
        from app.services.escalation_scheduler import scheduler
        sched_running = scheduler.running
        results["escalation_engine"] = {"status": "operational" if sched_running else "degraded"}
    except Exception:
        results["escalation_engine"] = {"status": "unknown"}

    # 5. Notification worker
    try:
        from app.services.notification_worker import worker_scheduler as notif_scheduler
        results["notification_worker"] = {"status": "operational" if notif_scheduler.running else "degraded"}
    except Exception:
        results["notification_worker"] = {"status": "unknown"}

    # 6. SMS (Twilio)
    try:
        from app.services.sms_service import is_available as sms_available
        results["sms_twilio"] = {"status": "operational" if sms_available() else "degraded"}
    except Exception:
        results["sms_twilio"] = {"status": "unknown"}

    # Overall status
    statuses = [v["status"] for v in results.values()]
    if all(s == "operational" for s in statuses):
        overall = "operational"
    elif any(s == "degraded" for s in statuses):
        overall = "degraded"
    else:
        overall = "incident"

    return {
        "overall_status": overall,
        "services": results,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

# Include the router in the main app
app.include_router(api_router)

# Include domain API routers (users, seniors, devices)
app.include_router(domain_api_router, prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=settings.cors_origins.split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.core.monitoring_middleware import MonitoringMiddleware
app.add_middleware(MonitoringMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SlowAPIMiddleware)

# Configure logging
from app.logging_config import setup_logging
setup_logging()
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
    global pg_pool
    if pg_pool:
        await pg_pool.close()
    if runs_schedulers():
        stop_scheduler()
        stop_notification_worker()
        stop_baseline_scheduler()
        stop_behavior_scheduler()
        stop_risk_learning_scheduler()
        stop_dynamic_risk_scheduler()
        stop_health_monitor()
        try:
            shutdown_fleet_weather_scheduler()
        except Exception:
            pass
        try:
            stop_risk_prediction_prewarmer()
        except Exception:
            pass
        try:
            stop_risk_prediction_reconciler()
        except Exception:
            pass
        try:
            stop_behavioral_baseline_prewarmer()
        except Exception:
            pass
    else:
        try:
            from app.services.pool_stats_publisher import stop_pool_stats_publisher
            await stop_pool_stats_publisher()
        except Exception:
            pass
    logger.info(f"{settings.app_name} shutdown complete (role={get_role().value})")

@app.on_event("startup")
async def startup_db():
    logger.info(f"Starting {settings.app_name} in {settings.app_env} environment")

    # Patch nginx to route SEO pages to FastAPI (persists across deployments)
    import subprocess
    patch_script = pathlib.Path(__file__).resolve().parent.parent / "deploy" / "nginx-patch.sh"
    if patch_script.is_file():
        try:
            result = subprocess.run(
                ["bash", str(patch_script)],
                capture_output=True, text=True, timeout=15,
            )
            for line in result.stdout.strip().splitlines():
                logger.info(line)
            if result.returncode != 0 and result.stderr:
                logger.warning(f"nginx-patch stderr: {result.stderr.strip()}")
        except Exception as e:
            logger.warning(f"nginx-patch skipped: {e}")

    async def _nginx_routing_watchdog() -> None:
        import asyncio
        import httpx
        await asyncio.sleep(30)
        reapply_attempts = 0
        REAPPLY_CIRCUIT_BREAK = 3
        while True:
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    resp = await client.get(
                        "http://127.0.0.1/health",
                        headers={"Host": "nischint.care"},
                    )
                body_head = (resp.text or "")[:50].lstrip().lower()
                ok = (
                    resp.status_code == 200
                    and ("status" in body_head or body_head.startswith("{"))
                    and "<!doctype" not in body_head
                )
                if ok:
                    reapply_attempts = 0
                else:
                    if reapply_attempts < REAPPLY_CIRCUIT_BREAK and patch_script.is_file():
                        reapply_attempts += 1
                        logger.warning(
                            "[nginx-watchdog] /health degraded "
                            f"(http {resp.status_code}, body={body_head!r}) — "
                            f"reapply attempt {reapply_attempts}/{REAPPLY_CIRCUIT_BREAK}"
                        )
                        try:
                            proc = await asyncio.create_subprocess_exec(
                                "bash", str(patch_script),
                                stdout=asyncio.subprocess.DEVNULL,
                                stderr=asyncio.subprocess.DEVNULL,
                            )
                            asyncio.create_task(proc.wait())
                        except Exception as e:
                            logger.warning(f"[nginx-watchdog] spawn failed: {e}")
                    elif reapply_attempts >= REAPPLY_CIRCUIT_BREAK:
                        logger.error(
                            "[nginx-watchdog] /health still degraded after "
                            f"{REAPPLY_CIRCUIT_BREAK} reapply attempts — "
                            "circuit breaker open, NOT re-running patch. "
                            "Manual intervention required."
                        )
            except Exception as e:
                logger.debug(f"[nginx-watchdog] probe failed: {e}")
            await asyncio.sleep(60)

    import asyncio as _asyncio
    _asyncio.create_task(_nginx_routing_watchdog())

    # PostgreSQL — non-blocking (app starts even if Neon quota exceeded)
    pool = await get_pg_pool()
    if pool:
        logger.info("PostgreSQL connection pool initialized")
    else:
        logger.warning("PostgreSQL unavailable — DB-dependent features degraded")

    if pool:
        try:
            from app.db.session import async_session
            from app.services.user_seed import seed_operational_accounts
            async with async_session() as _seed_sess:
                _report = await seed_operational_accounts(_seed_sess)
            logger.info(
                f"[USER_SEED] startup complete: created={_report['created']} "
                f"skipped={len(_report['skipped'])} errors={len(_report['errors'])}"
            )
        except Exception as _e:
            logger.error(f"[USER_SEED] startup seed failed (non-fatal): {_e}")

    if pool:
        try:
            from app.migrations.sb01_safety_event_feedback import (
                ensure_safety_event_feedback_table,
            )
            await ensure_safety_event_feedback_table()
        except Exception as _e:
            logger.error(f"[SB-01] startup DDL failed (non-fatal): {_e}")

    if os.environ.get("ENV_HAZARD_USE_POSTGIS", "false").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        _SF02_WARM_COORDS = [
            (19.0760,  72.8777, "Mumbai"),
            (28.6139,  77.2090, "Delhi"),
            (12.9716,  77.5946, "Bangalore"),
            (13.0827,  80.2707, "Chennai"),
            (22.5726,  88.3639, "Kolkata"),
            (17.3850,  78.4867, "Hyderabad"),
            (18.5204,  73.8567, "Pune"),
            (23.0225,  72.5714, "Ahmedabad"),
            (30.7333,  79.0667, "Kedarnath"),
            (26.9124,  75.7873, "Jaipur"),
            (26.8467,  80.9462, "Lucknow"),
            (23.2599,  77.4126, "Bhopal"),
            (25.5941,  85.1376, "Patna"),
            (20.2961,  85.8245, "Bhubaneswar"),
            (26.1445,  91.7362, "Guwahati"),
            (34.0837,  74.7973, "Srinagar"),
            (31.1048,  77.1734, "Shimla"),
            (27.3389,  88.6065, "Gangtok"),
            (27.0844,  93.6053, "Itanagar"),
            (11.6234,  92.7265, "Port Blair"),
            (28.5971,  83.8201, "_bench_nepal_probe"),
        ]

        async def _warm_sf02_postgis_cache() -> None:
            from app.services.external_signals.sachet_provider import (
                _postgis_resolve_state,
            )
            primed = 0
            for lat, lng, _name in _SF02_WARM_COORDS:
                try:
                    await _postgis_resolve_state(lat, lng)
                    primed += 1
                except Exception as warm_exc:
                    logger.warning(
                        "[SF-02] cache warm failed for %s: %r", _name, warm_exc
                    )
            primed_public = primed - 1 if primed > 0 else 0
            total_public = len(_SF02_WARM_COORDS) - 1
            logger.info(
                "[SF-02] PostGIS cache warmed: %d/%d coords primed",
                primed_public, total_public,
            )

        asyncio.create_task(_warm_sf02_postgis_cache())
    else:
        logger.info(
            "[SF-02] PostGIS cache warm-up skipped (ENV_HAZARD_USE_POSTGIS != true)"
        )

    try:
        from app.services.auth_metrics import start_summary_thread as _start_auth_summary
        _start_auth_summary()
    except Exception:
        logger.exception("auth_metrics summary thread failed to start")

    # Background schedulers — gated by NISCHINT_ROLE so the API and the
    # scheduler tick can be split into separate processes without forking
    # this file. With NISCHINT_ROLE=api this whole block is skipped and
    # the API event loop stops competing with 14 in-process schedulers.
    if runs_schedulers():
        # ── FIX: allow DB pool to stabilise before 27 schedulers
        # simultaneously acquire connections. Without this delay the
        # asyncpg pool hits a TimeoutError on first boot when all
        # scheduler init functions race get_pg_pool() at the same time.
        await asyncio.sleep(3)
        for name, fn in [
            ("escalation", start_scheduler),
            ("notifications", start_notification_worker),
            ("baseline", start_baseline_scheduler),
            ("behavior_ai", start_behavior_scheduler),
            ("twin_builder", start_twin_builder_scheduler),
            ("prediction", start_prediction_scheduler),
            ("risk_learning", start_risk_learning_scheduler),
            ("dynamic_risk", start_dynamic_risk_scheduler),
            ("forecast_prewarm", start_forecast_prewarm_scheduler),
            ("sachet_prewarm", start_sachet_prewarm_scheduler),
            ("tomtom_prewarm", start_tomtom_prewarm_scheduler),
            ("news_prewarm", start_news_prewarm_scheduler),
            ("owm_alerts_prewarm", start_owm_alerts_prewarm_scheduler),
            ("user_signal_baselines_refresh", start_user_signal_baselines_scheduler),
            ("health_monitor", start_health_monitor),
            ("pr_nightly", start_pr_nightly_scheduler),
            ("geo_digest", start_geo_digest_scheduler),
            ("dpdp_digest", start_dpdp_digest_scheduler),
            ("db_pool_monitor", start_db_pool_monitor),
            ("cc_ws_sweeper", start_cc_ws_sweeper),
            ("geo_health", start_geo_health_scheduler),
            ("fleet_weather", start_fleet_weather_scheduler),
            ("sla_monitor", start_sla_monitor),
            ("safety_incident_lifecycle", start_safety_incident_scheduler),
            ("risk_prediction_prewarm", start_risk_prediction_prewarmer),
            ("risk_prediction_reconciler", start_risk_prediction_reconciler),
            ("behavioral_baseline_prewarm", start_behavioral_baseline_prewarmer),
        ]:
            try:
                fn()
            except Exception as e:
                logger.warning(f"Scheduler '{name}' failed to start: {e}")
        logger.info(f"Schedulers started (role={get_role().value})")

        try:
            from app.services.scheduler_metrics import attach_to_all_running
            attach_to_all_running()
        except Exception as e:
            logger.warning(f"scheduler_metrics attach failed: {e}")
    else:
        logger.info(f"Schedulers SKIPPED in this process (role={get_role().value})")
        try:
            from app.services.pool_stats_publisher import start_pool_stats_publisher
            start_pool_stats_publisher()
        except Exception as e:
            logger.warning(f"pool_stats_publisher failed to start: {e}")

    # Start Redis Pub/Sub listener for real-time SSE broadcasts
    try:
        from app.services.event_broadcaster import broadcaster
        loop = asyncio.get_event_loop()
        broadcaster.start_redis_listener(loop)
        logger.info("Redis Pub/Sub listener initialized for emergency broadcasts")
    except Exception as e:
        logger.warning(f"Redis Pub/Sub listener failed: {e}")

    try:
        from app.services.loop_lag_monitor import start_monitor as start_loop_lag_monitor
        if start_loop_lag_monitor() is not None:
            logger.info("LT-03 loop-lag monitor armed")
    except Exception as e:
        logger.warning(f"LT-03 loop-lag monitor failed to start: {e}")

# ── Serve React frontend build (single-app architecture) ──
# This MUST come after all API route registration.

FRONTEND_BUILD = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "build"

# ── SEO: Sitemap + Robots — ALWAYS available, independent of frontend build ──

STATIC_PAGES = [
    {"loc": "https://nischint.care/", "changefreq": "weekly", "priority": "1.0"},
    {"loc": "https://nischint.care/women-safety-app", "changefreq": "weekly", "priority": "0.95"},
    {"loc": "https://nischint.care/kids-safety-app", "changefreq": "weekly", "priority": "0.95"},
    {"loc": "https://nischint.care/family-safety-app", "changefreq": "weekly", "priority": "0.95"},
    {"loc": "https://nischint.care/pilot", "changefreq": "monthly", "priority": "0.9"},
    {"loc": "https://nischint.care/investors", "changefreq": "monthly", "priority": "0.8"},
    {"loc": "https://nischint.care/blog", "changefreq": "daily", "priority": "0.85"},
]

ROBOTS_TXT = """User-agent: *
Allow: /
Disallow: /api/
Disallow: /ws/
Disallow: /login
Disallow: /dashboard
Disallow: /admin/

Sitemap: https://nischint.care/sitemap.xml
"""


@app.get("/sitemap.xml", include_in_schema=False)
async def serve_sitemap():
    """Proxy to the canonical sitemap at /api/blog/sitemap."""
    from app.api.deps import get_db_session as _get_session
    from app.api.blog import blog_sitemap
    async for session in _get_session():
        return await blog_sitemap(session)


@app.get("/robots.txt", include_in_schema=False)
async def serve_robots():
    return Response(
        content=ROBOTS_TXT.strip(),
        media_type="text/plain",
        headers={
            "Cache-Control": "public, max-age=86400",
            "CDN-Cache-Control": "max-age=86400",
        },
    )


if FRONTEND_BUILD.is_dir():
    if (FRONTEND_BUILD / "static").is_dir():
        class _ImmutableStatic(StaticFiles):
            async def get_response(self, path, scope):
                response = await super().get_response(path, scope)
                if getattr(response, "status_code", 0) == 200:
                    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                return response
        app.mount("/static", _ImmutableStatic(directory=str(FRONTEND_BUILD / "static")), name="static-assets")

    @app.get("/manifest.json")
    @app.get("/asset-manifest.json")
    @app.get("/sw.js")
    @app.get("/firebase-messaging-sw.js")
    async def serve_root_files(request: Request):
        filename = request.url.path.lstrip("/")
        filepath = FRONTEND_BUILD / filename
        if filepath.is_file():
            return FileResponse(
                str(filepath),
                headers={"Cache-Control": "public, max-age=3600, must-revalidate"},
            )
        return JSONResponse({"error": "not found"}, status_code=404)

    @app.get("/icons/{path:path}")
    async def serve_icons(path: str):
        filepath = FRONTEND_BUILD / "icons" / path
        if filepath.is_file():
            return FileResponse(
                str(filepath),
                headers={"Cache-Control": "public, max-age=604800"},
            )
        return JSONResponse({"error": "not found"}, status_code=404)

    @app.get("/sounds/{path:path}")
    async def serve_sounds(path: str):
        filepath = FRONTEND_BUILD / "sounds" / path
        if filepath.is_file():
            return FileResponse(str(filepath))
        return JSONResponse({"error": "not found"}, status_code=404)

    logger.info("SEO_INJECTION_LOADED: starting nischint with SEO routes")
    try:
        from fastapi.responses import HTMLResponse
        from app.seo_pages import SEO_PAGES, get_seo_config
        from app.seo_injector import inject_seo

        @app.get("/women-safety-app", response_class=HTMLResponse, include_in_schema=False)
        async def seo_women_safety():
            return HTMLResponse(content=inject_seo(SEO_PAGES["/women-safety-app"]))

        @app.get("/kids-safety-app", response_class=HTMLResponse, include_in_schema=False)
        async def seo_kids_safety():
            return HTMLResponse(content=inject_seo(SEO_PAGES["/kids-safety-app"]))

        @app.get("/family-safety-app", response_class=HTMLResponse, include_in_schema=False)
        async def seo_family_safety():
            return HTMLResponse(content=inject_seo(SEO_PAGES["/family-safety-app"]))

        @app.get("/pilot", response_class=HTMLResponse, include_in_schema=False)
        async def seo_pilot():
            return HTMLResponse(content=inject_seo(SEO_PAGES["/pilot"]))

        @app.get("/what-is-nischint", response_class=HTMLResponse, include_in_schema=False)
        async def seo_what_is_nischint():
            return HTMLResponse(content=inject_seo(SEO_PAGES["/what-is-nischint"]))

        @app.get("/blog", response_class=HTMLResponse, include_in_schema=False)
        async def seo_blog():
            return HTMLResponse(content=inject_seo(SEO_PAGES["/blog"]))

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        async def seo_homepage():
            return HTMLResponse(content=inject_seo(SEO_PAGES["/"]))

        @app.get("/.well-known/security.txt", include_in_schema=False)
        async def security_txt():
            from fastapi.responses import PlainTextResponse
            content = (
                "Contact: mailto:security@nischint.app\n"
                "Contact: https://nischint.care/pilot\n"
                "Expires: 2027-12-31T23:59:59.000Z\n"
                "Preferred-Languages: en, hi\n"
                "Canonical: https://nischint.care/.well-known/security.txt\n"
                "Policy: https://nischint.care/what-is-nischint\n"
            )
            return PlainTextResponse(content=content, media_type="text/plain")

        @app.get("/security.txt", include_in_schema=False)
        async def security_txt_alias():
            return await security_txt()

        logger.info(f"SEO injection enabled for {len(SEO_PAGES)} landing pages: {list(SEO_PAGES.keys())}")
    except Exception as e:
        logger.error(f"SEO_INJECTION_FAILED: Could not load SEO routes: {e}", exc_info=True)

    from app.api.entity_engine import GEO_HEALTH_DASHBOARD_HTML
    @app.get("/admin/geo-health", response_class=HTMLResponse, include_in_schema=False)
    async def admin_geo_health():
        return HTMLResponse(content=GEO_HEALTH_DASHBOARD_HTML)

    from app.api.journey_rollout_dashboard import ROLLOUT_DASHBOARD_HTML
    @app.get("/admin/journey/rollout", response_class=HTMLResponse, include_in_schema=False)
    async def admin_journey_rollout():
        return HTMLResponse(content=ROLLOUT_DASHBOARD_HTML)

    from app.api.ai_brain_timeline import AI_BRAIN_TIMELINE_HTML
    @app.get("/admin/ai-brain/timeline", response_class=HTMLResponse, include_in_schema=False)
    async def admin_ai_brain_timeline():
        return HTMLResponse(content=AI_BRAIN_TIMELINE_HTML)

    @app.get("/{path:path}", include_in_schema=False)
    async def serve_spa(path: str):
        if path.startswith("api/") or path.startswith("ws/"):
            return JSONResponse({"error": "not found"}, status_code=404)
        if path == "robots.txt":
            return await serve_robots()
        requested_file = FRONTEND_BUILD / path
        if path and requested_file.is_file() and FRONTEND_BUILD in requested_file.resolve().parents:
            return FileResponse(str(requested_file))
        if path.endswith(".html"):
            stem = path[:-5]
            folder_index = FRONTEND_BUILD / stem / "index.html"
            if folder_index.is_file():
                return FileResponse(str(folder_index))
            return JSONResponse({"error": "not found"}, status_code=404)
        folder_index = FRONTEND_BUILD / path / "index.html"
        if folder_index.is_file():
            return FileResponse(str(folder_index))
        return FileResponse(str(FRONTEND_BUILD / "index.html"))

    logger.info(f"React frontend mounted from {FRONTEND_BUILD}")
else:
    logger.warning(f"Frontend build not found at {FRONTEND_BUILD} — SPA serving disabled. Fallback root + catch-all active.")

    _FALLBACK_HTML = """<!DOCTYPE html><html><head><meta charset=utf-8><title>NISCHINT</title>
<style>body{background:#0a0e17;color:#e6ebf5;font-family:system-ui;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
.box{text-align:center;padding:32px;border:1px solid #1f2937;border-radius:10px;background:#121826;max-width:520px}
h1{margin:0 0 8px;color:#818cf8;font-size:22px}
p{margin:8px 0;color:#94a3b8;font-size:14px}
code{background:#0b1120;padding:2px 6px;border-radius:4px;color:#fbbf24;font-size:12px}
</style></head><body><div class=box>
<h1>NISCHINT API is healthy</h1>
<p>The frontend build has not been generated yet. API endpoints are fully operational.</p>
<p>Rebuild with <code>cd /app/frontend && yarn build</code></p>
<p style="margin-top:16px"><a href="/api/health" style="color:#6ee7b7">/api/health</a> · <a href="/admin/journey/rollout" style="color:#6ee7b7">/admin/journey/rollout</a></p>
</div></body></html>"""

    @app.get("/", include_in_schema=False)
    async def fallback_root():
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=_FALLBACK_HTML, status_code=200)

    @app.get("/{path:path}", include_in_schema=False)
    async def fallback_catch_all(path: str):
        from fastapi.responses import HTMLResponse
        if path.startswith("api/") or path.startswith("ws/"):
            return JSONResponse({"error": "not found"}, status_code=404)
        return HTMLResponse(content=_FALLBACK_HTML, status_code=200)

