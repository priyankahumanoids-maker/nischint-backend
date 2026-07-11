"""
Health API — Detailed health checks and status dashboard.
"""
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])


@router.get("/detailed")
async def detailed_health():
    """Run an on-demand health check and return results."""
    from app.services.health_monitor import run_health_check
    result = await run_health_check()
    result.pop("_id", None)
    return result


@router.get("/history")
async def health_history(hours: int = Query(default=24, le=168)):
    """Return health check history for the last N hours (max 168 = 7 days)."""
    from app.core.config import settings
    from motor.motor_asyncio import AsyncIOMotorClient

    try:
        client = AsyncIOMotorClient(settings.mongo_url)
        db = client[settings.db_name]
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        cursor = db.health_checks.find(
            {"timestamp": {"$gte": cutoff}},
            {"_id": 0}
        ).sort("timestamp", -1).limit(500)
        records = await cursor.to_list(length=500)
        total = len(records)
        up_count = sum(1 for r in records if r.get("overall") == "up")
        uptime_pct = round((up_count / total) * 100, 2) if total > 0 else 0
        return {
            "period_hours": hours,
            "total_checks": total,
            "uptime_percent": uptime_pct,
            "checks": records,
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/dashboard", response_class=HTMLResponse)
async def health_dashboard():
    """Beautiful status dashboard page."""
    from app.core.config import settings
    from motor.motor_asyncio import AsyncIOMotorClient

    try:
        client = AsyncIOMotorClient(settings.mongo_url)
        db = client[settings.db_name]

        # Last 24h of checks
        cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        cursor = db.health_checks.find({"timestamp": {"$gte": cutoff_24h}}, {"_id": 0}).sort("timestamp", -1).limit(288)
        checks = await cursor.to_list(length=288)

        total = len(checks)
        up_count = sum(1 for c in checks if c.get("overall") == "up")
        uptime_24h = round((up_count / total) * 100, 2) if total > 0 else 100.0
        latest = checks[0] if checks else None

        # Last 7d for uptime
        cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        count_7d = await db.health_checks.count_documents({"timestamp": {"$gte": cutoff_7d}})
        up_7d = await db.health_checks.count_documents({"timestamp": {"$gte": cutoff_7d}, "overall": "up"})
        uptime_7d = round((up_7d / count_7d) * 100, 2) if count_7d > 0 else 100.0

        incidents_24h = [c for c in checks if c.get("overall") != "up"]

    except Exception as e:
        logger.error(f"Dashboard data error: {e}")
        checks, total, uptime_24h, uptime_7d, latest, incidents_24h = [], 0, 0, 0, None, []

    # Build timeline bars (last 50 checks)
    timeline_bars = ""
    for c in reversed(checks[:50]):
        color = "#22c55e" if c.get("overall") == "up" else ("#eab308" if c.get("overall") == "warning" else "#ef4444")
        ts = c.get("timestamp", "")[:16].replace("T", " ")
        timeline_bars += f'<div class="bar" style="background:{color}" title="{ts} — {c.get("overall","?")}"></div>'

    # Component status from latest check
    components_html = ""
    if latest and latest.get("components"):
        for name, info in latest["components"].items():
            status = info.get("status", "unknown")
            if status == "up":
                badge_cls, icon = "badge-up", "check_circle"
            elif status == "warning":
                badge_cls, icon = "badge-warn", "warning"
            else:
                badge_cls, icon = "badge-down", "cancel"
            extra = ""
            if name == "memory" and "used_percent" in info:
                extra = f'<span class="meta">{info["used_percent"]}% used ({info.get("used_mb",0)} MB / {info.get("total_mb",0)} MB)</span>'
            if name == "external" and "latency_ms" in info:
                extra = f'<span class="meta">{info["latency_ms"]}ms latency</span>'
            if info.get("error"):
                extra = f'<span class="meta err">{info["error"][:80]}</span>'
            components_html += f"""
            <div class="comp-card">
                <div class="comp-header">
                    <span class="material-symbols-outlined {badge_cls}">{icon}</span>
                    <span class="comp-name">{name.replace('_',' ').title()}</span>
                </div>
                <span class="badge {badge_cls}">{status.upper()}</span>
                {extra}
            </div>"""

    # Incidents list
    incidents_html = ""
    if incidents_24h:
        for inc in incidents_24h[:10]:
            ts = inc.get("timestamp", "")[:19].replace("T", " ")
            down = [k for k, v in inc.get("components", {}).items() if v.get("status") == "down"]
            incidents_html += f'<div class="incident"><span class="inc-time">{ts} UTC</span><span class="inc-detail">{", ".join(down) if down else inc.get("overall","unknown")}</span></div>'
    else:
        incidents_html = '<div class="no-incidents">No incidents in the last 24 hours</div>'

    overall_status = latest.get("overall", "unknown") if latest else "no data"
    overall_color = "#22c55e" if overall_status == "up" else ("#eab308" if overall_status == "warning" else "#ef4444")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nischint Status</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL@20..48,100..700,0..1" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Inter',sans-serif;background:#0a0a0a;color:#e5e5e5;min-height:100vh}}
.container{{max-width:900px;margin:0 auto;padding:40px 20px}}
.header{{text-align:center;margin-bottom:40px}}
.header h1{{font-size:28px;font-weight:700;letter-spacing:-0.5px;margin-bottom:4px}}
.header .sub{{color:#737373;font-size:14px}}
.status-hero{{background:#171717;border:1px solid #262626;border-radius:16px;padding:32px;text-align:center;margin-bottom:32px}}
.status-dot{{width:14px;height:14px;border-radius:50%;display:inline-block;margin-right:8px;vertical-align:middle;animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:0.5}}}}
.status-text{{font-size:22px;font-weight:600;vertical-align:middle}}
.uptime-row{{display:flex;gap:16px;justify-content:center;margin-top:20px}}
.uptime-card{{background:#1a1a1a;border:1px solid #262626;border-radius:10px;padding:16px 28px;text-align:center}}
.uptime-val{{font-size:28px;font-weight:700;color:#22c55e}}
.uptime-label{{font-size:12px;color:#737373;margin-top:4px}}
.section{{margin-bottom:32px}}
.section-title{{font-size:16px;font-weight:600;margin-bottom:16px;color:#a3a3a3;text-transform:uppercase;letter-spacing:1px;font-size:12px}}
.timeline{{display:flex;gap:2px;align-items:flex-end;height:40px;background:#171717;border-radius:8px;padding:8px;border:1px solid #262626}}
.bar{{flex:1;min-width:4px;height:100%;border-radius:2px;transition:opacity 0.2s}}
.bar:hover{{opacity:0.7}}
.comp-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}}
.comp-card{{background:#171717;border:1px solid #262626;border-radius:12px;padding:16px}}
.comp-header{{display:flex;align-items:center;gap:8px;margin-bottom:8px}}
.comp-name{{font-weight:500;font-size:15px}}
.badge{{font-size:11px;font-weight:600;padding:3px 10px;border-radius:20px;display:inline-block}}
.badge-up{{color:#22c55e;background:rgba(34,197,94,0.1)}}
.badge-warn{{color:#eab308;background:rgba(234,179,8,0.1)}}
.badge-down{{color:#ef4444;background:rgba(239,68,68,0.1)}}
.material-symbols-outlined{{font-size:20px}}
.material-symbols-outlined.badge-up{{color:#22c55e}}
.material-symbols-outlined.badge-warn{{color:#eab308}}
.material-symbols-outlined.badge-down{{color:#ef4444}}
.meta{{display:block;font-size:12px;color:#737373;margin-top:6px}}
.meta.err{{color:#ef4444}}
.incident{{display:flex;justify-content:space-between;padding:12px 16px;background:#171717;border:1px solid #262626;border-radius:8px;margin-bottom:8px}}
.inc-time{{color:#737373;font-size:13px;font-family:monospace}}
.inc-detail{{color:#ef4444;font-size:13px;font-weight:500}}
.no-incidents{{text-align:center;padding:24px;color:#525252;background:#171717;border:1px solid #262626;border-radius:8px}}
.footer{{text-align:center;margin-top:40px;color:#525252;font-size:12px}}
.refresh-btn{{background:#262626;color:#a3a3a3;border:1px solid #404040;padding:8px 16px;border-radius:8px;cursor:pointer;font-size:13px;margin-top:12px}}
.refresh-btn:hover{{background:#333;color:#e5e5e5}}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>Nischint System Status</h1>
        <p class="sub">Last updated: {now_str}</p>
    </div>

    <div class="status-hero">
        <div>
            <span class="status-dot" style="background:{overall_color}"></span>
            <span class="status-text">{"All Systems Operational" if overall_status == "up" else ("Degraded Performance" if overall_status == "warning" else "System Outage")}</span>
        </div>
        <div class="uptime-row">
            <div class="uptime-card">
                <div class="uptime-val">{uptime_24h}%</div>
                <div class="uptime-label">Uptime (24h)</div>
            </div>
            <div class="uptime-card">
                <div class="uptime-val">{uptime_7d}%</div>
                <div class="uptime-label">Uptime (7 days)</div>
            </div>
            <div class="uptime-card">
                <div class="uptime-val">{total}</div>
                <div class="uptime-label">Checks (24h)</div>
            </div>
        </div>
        <button class="refresh-btn" onclick="location.reload()">Refresh</button>
    </div>

    <div class="section">
        <div class="section-title">Uptime Timeline (Last 50 Checks)</div>
        <div class="timeline">{timeline_bars if timeline_bars else '<div style="flex:1;text-align:center;color:#525252;align-self:center">No data yet — checks run every 5 min</div>'}</div>
    </div>

    <div class="section">
        <div class="section-title">Components</div>
        <div class="comp-grid">{components_html if components_html else '<div class="no-incidents">Waiting for first health check...</div>'}</div>
    </div>

    <div class="section">
        <div class="section-title">Recent Incidents (24h)</div>
        {incidents_html}
    </div>

    <div class="footer">
        <p>Nischint Health Monitor &middot; Checks every 5 minutes &middot; Alerts via email</p>
    </div>
</div>
</body>
</html>"""
    return HTMLResponse(content=html)
