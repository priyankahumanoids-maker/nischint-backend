"""
Health Monitor Service — Automated production health checks every 5 minutes.
Checks: PostgreSQL, Redis, MongoDB, memory usage.
Stores results in MongoDB. Sends email alerts via SendGrid on failures.
"""
import os
import logging
import asyncio
import psutil
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler()
_last_alert_at = None
ALERT_COOLDOWN_MINUTES = 30
ALERT_EMAIL = os.environ.get("SES_FROM_EMAIL", "nischint4parents@gmail.com")
PRODUCTION_URL = "https://nischint.care"


async def _check_postgresql():
    try:
        from app.db.session import async_session
        async with async_session() as session:
            from sqlalchemy import text
            result = await session.execute(text("SELECT 1"))
            row = result.scalar()
            return {"status": "up", "latency_ms": 0} if row == 1 else {"status": "down", "error": "unexpected result"}
    except Exception as e:
        return {"status": "down", "error": str(e)[:200]}


async def _check_redis():
    try:
        from app.services.redis_service import _get_client, is_available
        if not is_available():
            return {"status": "down", "error": "redis not configured"}
        client = _get_client()
        if client:
            pong = client.ping()
            return {"status": "up"} if pong else {"status": "down", "error": "no pong"}
        return {"status": "down", "error": "redis client not available"}
    except Exception as e:
        return {"status": "down", "error": str(e)[:200]}


async def _check_mongodb():
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        from app.core.config import settings
        client = AsyncIOMotorClient(settings.mongo_url, serverSelectionTimeoutMS=5000)
        await client.admin.command("ping")
        return {"status": "up"}
    except Exception as e:
        return {"status": "down", "error": str(e)[:200]}


def _check_memory():
    try:
        mem = psutil.virtual_memory()
        return {
            "status": "up" if mem.percent < 90 else "warning",
            "used_percent": round(mem.percent, 1),
            "used_mb": round(mem.used / (1024 * 1024), 1),
            "total_mb": round(mem.total / (1024 * 1024), 1),
        }
    except Exception as e:
        return {"status": "unknown", "error": str(e)[:200]}


async def _check_external_health():
    """Ping the production URL to verify it's reachable."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{PRODUCTION_URL}/health")
            if resp.status_code == 200:
                return {"status": "up", "status_code": 200, "latency_ms": round(resp.elapsed.total_seconds() * 1000)}
            return {"status": "down", "status_code": resp.status_code}
    except Exception as e:
        return {"status": "down", "error": str(e)[:200]}


async def run_health_check():
    """Run all health checks and store results."""
    started = datetime.now(timezone.utc)

    pg, redis_res, mongo, mem = await asyncio.gather(
        _check_postgresql(),
        _check_redis(),
        _check_mongodb(),
        asyncio.coroutine(lambda: _check_memory())() if False else asyncio.get_event_loop().run_in_executor(None, _check_memory),
    )

    external = await _check_external_health()

    components = {
        "postgresql": pg,
        "redis": redis_res,
        "mongodb": mongo,
        "memory": mem,
        "external": external,
    }

    critical_down = [k for k, v in components.items() if v.get("status") == "down" and k != "external"]
    external_down = external.get("status") == "down"
    overall = "down" if critical_down or external_down else ("warning" if mem.get("status") == "warning" else "up")

    record = {
        "timestamp": started.isoformat(),
        "overall": overall,
        "components": components,
        "duration_ms": round((datetime.now(timezone.utc) - started).total_seconds() * 1000),
    }

    # Store in MongoDB
    try:
        from app.core.config import settings
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(settings.mongo_url)
        db = client[settings.db_name]
        await db.health_checks.insert_one(record)

        # Prune old records (keep last 7 days)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        await db.health_checks.delete_many({"timestamp": {"$lt": cutoff}})
    except Exception as e:
        logger.error(f"Failed to store health check: {e}")

    # Alert if something is down
    if overall == "down":
        await _send_alert(components, critical_down, external_down)

    level = logging.WARNING if overall != "up" else logging.DEBUG
    logger.log(level, f"Health check: {overall} | down={critical_down}")

    return record


async def _send_alert(components: dict, critical_down: list, external_down: bool):
    """Send email alert with cooldown."""
    global _last_alert_at

    now = datetime.now(timezone.utc)
    if _last_alert_at and (now - _last_alert_at) < timedelta(minutes=ALERT_COOLDOWN_MINUTES):
        logger.info("Alert cooldown active — skipping email")
        return

    _last_alert_at = now

    down_items = critical_down.copy()
    if external_down:
        down_items.append("external (nischint.care)")

    details_html = ""
    for name, info in components.items():
        icon = "&#x2705;" if info.get("status") == "up" else "&#x274C;"
        error = f' — {info.get("error", "")}' if info.get("status") == "down" else ""
        details_html += f"<tr><td style='padding:8px;border-bottom:1px solid #eee'>{icon} {name}</td><td style='padding:8px;border-bottom:1px solid #eee'>{info.get('status','unknown')}{error}</td></tr>"

    html = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto">
        <div style="background:#dc2626;color:white;padding:20px;border-radius:8px 8px 0 0">
            <h2 style="margin:0">NISCHINT Production Alert</h2>
            <p style="margin:5px 0 0;opacity:0.9">{now.strftime('%Y-%m-%d %H:%M UTC')}</p>
        </div>
        <div style="background:#fff;padding:20px;border:1px solid #e5e7eb;border-radius:0 0 8px 8px">
            <p style="color:#dc2626;font-weight:bold;font-size:16px">Components DOWN: {', '.join(down_items)}</p>
            <table style="width:100%;border-collapse:collapse;margin:15px 0">
                <tr style="background:#f9fafb"><th style="padding:8px;text-align:left;border-bottom:2px solid #e5e7eb">Component</th><th style="padding:8px;text-align:left;border-bottom:2px solid #e5e7eb">Status</th></tr>
                {details_html}
            </table>
            <p style="color:#6b7280;font-size:13px">Alert cooldown: {ALERT_COOLDOWN_MINUTES} min. Next alert suppressed until cooldown expires.</p>
            <a href="{PRODUCTION_URL}/api/health/dashboard" style="display:inline-block;background:#2563eb;color:white;padding:10px 20px;border-radius:6px;text-decoration:none;margin-top:10px">View Status Dashboard</a>
        </div>
    </div>
    """

    try:
        from app.services.email_service import send_email
        send_email(ALERT_EMAIL, f"[NISCHINT ALERT] Production DOWN — {', '.join(down_items)}", html)
        logger.warning(f"Alert email sent to {ALERT_EMAIL}")
    except Exception as e:
        logger.error(f"Failed to send alert email: {e}")


def start_health_monitor():
    if not _scheduler.running:
        _scheduler.add_job(run_health_check, 'interval', minutes=5, id='health_check_5m', replace_existing=True)
        _scheduler.start()
        logger.info("Health monitor started — checking every 5 minutes")


def stop_health_monitor():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Health monitor stopped")
