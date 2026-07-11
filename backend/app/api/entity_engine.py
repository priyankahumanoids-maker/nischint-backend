"""
NISCHINT GEO + Entity Engine
─────────────────────────────
Entity management, content generation, diff/approval workflow,
GEO SEO validation, build checks, and cache debugging.
All in-memory storage (v1). No database, no auth.
"""

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import requests as http_requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/engine", tags=["GEO + Entity Engine"])

# ═══════════════════════════════════════════════════════════════
# IN-MEMORY STORES
# ═══════════════════════════════════════════════════════════════

_entity = {
    "company_name": "NISCHINT",
    "tagline": "India's AI Safety Operating System",
    "description": "Real-time safety monitoring, GPS tracking, AI-powered risk detection, and guardian alert network for schools, universities, corporates, and smart cities.",
    "features": [
        "Real-time GPS tracking",
        "AI voice distress detection",
        "Geofencing alerts",
        "Guardian alert network",
        "Predictive risk engine",
    ],
    "updated_at": datetime.now(timezone.utc).isoformat(),
}

_updates_queue: dict = {}  # update_id -> update record

# SPA fallback indicators
SPA_INDICATORS = [
    '<div id="root"></div>',
    "India's AI Safety Operating System",
    "NISCHINT - AI Safety Infrastructure | Real-Time Safety Monitoring for India",
]

GENERIC_DESCRIPTIONS = [
    "India's AI Safety Operating System",
    "Real-time safety monitoring, GPS tracking, AI-powered risk detection",
    "Transform real-time safety signals into a unified AI-powered safety network",
]


# ═══════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════════

class EntityInput(BaseModel):
    company_name: str
    tagline: str
    description: str
    features: List[str]


class GenerateInput(BaseModel):
    platform: str


class DiffInput(BaseModel):
    platform: str
    current_data: str


class ApproveInput(BaseModel):
    update_id: str
    action: str  # "approve" or "reject"


class GeoCheckInput(BaseModel):
    url: str


class GeoCompareInput(BaseModel):
    url_clean: str
    url_html: str


class BuildCheckInput(BaseModel):
    list_of_files: List[str]


class CacheCheckInput(BaseModel):
    url: str


# ═══════════════════════════════════════════════════════════════
# MODULE 1: ENTITY ENGINE
# ═══════════════════════════════════════════════════════════════

@router.post("/entity")
def set_entity(payload: EntityInput):
    _entity["company_name"] = payload.company_name
    _entity["tagline"] = payload.tagline
    _entity["description"] = payload.description
    _entity["features"] = payload.features
    _entity["updated_at"] = datetime.now(timezone.utc).isoformat()
    logger.info(f"[ENTITY] Updated: {payload.company_name}")
    return {"status": "ok", "entity": _entity}


@router.get("/entity")
def get_entity():
    return _entity


# ═══════════════════════════════════════════════════════════════
# MODULE 2: CONTENT GENERATION
# ═══════════════════════════════════════════════════════════════

@router.post("/generate")
def generate_content(payload: GenerateInput):
    if not _entity.get("company_name"):
        raise HTTPException(status_code=400, detail="Entity not configured")

    features_text = ", ".join(_entity["features"])
    content = f"{_entity['company_name']} – {_entity['tagline']}. {_entity['description']} Key features: {features_text}."

    return {
        "platform": payload.platform,
        "generated_content": content,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════
# MODULE 3: DIFF + APPROVAL ENGINE
# ═══════════════════════════════════════════════════════════════

@router.post("/diff")
def check_diff(payload: DiffInput):
    expected = f"{_entity['company_name']} – {_entity['tagline']}"
    current = payload.current_data.strip()

    if current == expected:
        return {"status": "ok", "platform": payload.platform, "message": "Content matches entity"}

    update_id = str(uuid.uuid4())
    record = {
        "id": update_id,
        "platform": payload.platform,
        "old": current,
        "new": expected,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _updates_queue[update_id] = record

    return {
        "status": "mismatch",
        "update_id": update_id,
        "platform": payload.platform,
        "suggested_fix": expected,
        "old": current,
    }


@router.post("/approve")
def approve_update(payload: ApproveInput):
    record = _updates_queue.get(payload.update_id)
    if not record:
        raise HTTPException(status_code=404, detail="Update not found")
    if payload.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Action must be 'approve' or 'reject'")

    record["status"] = "approved" if payload.action == "approve" else "rejected"
    record["actioned_at"] = datetime.now(timezone.utc).isoformat()

    return {"status": "ok", "update_id": payload.update_id, "action": payload.action, "record": record}


@router.get("/queue")
def get_queue():
    return {"updates": list(_updates_queue.values()), "count": len(_updates_queue)}


# ═══════════════════════════════════════════════════════════════
# MODULE 4: GEO SEO VALIDATION ENGINE
# ═══════════════════════════════════════════════════════════════

def _extract_city_from_slug(url: str) -> Optional[str]:
    """Extract city name from a GEO URL slug."""
    path = url.rstrip("/").split("/")[-1].replace(".html", "")
    # Pattern: [best-|personal-]<type>-safety-app-<city>
    m = re.search(r"safety-app-(.+)$", path)
    if m:
        return m.group(1).replace("-", " ")
    return None


def _fetch_url(url: str) -> dict:
    """Fetch a URL and return response data."""
    try:
        resp = http_requests.get(url, timeout=15, allow_redirects=True)
        return {"ok": True, "status_code": resp.status_code, "text": resp.text, "headers": dict(resp.headers)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/geo-check")
def geo_check(payload: GeoCheckInput):
    return _run_geo_check(payload.url)


def _run_geo_check(url: str) -> dict:
    """Core GEO SEO validation logic — reusable by health monitor."""
    result = _fetch_url(url)
    if not result["ok"]:
        return {"status": "fail", "issues": [f"fetch_error: {result['error']}"], "seo_score": 0, "url": url, "city_detected": None}

    html = result["text"]
    issues = []
    score = 100

    # CHECK 1: HTML content exists
    if not html or len(html) < 100:
        issues.append("empty_or_minimal_html")
        score -= 30

    # CHECK 2: SEO tag validation
    title_match = re.search(r"<title>([^<]*)</title>", html)
    title_text = title_match.group(1) if title_match else ""
    if not title_match:
        issues.append("missing_title")
        score -= 20

    desc_match = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html)
    if not desc_match:
        issues.append("missing_meta_description")
        score -= 15

    h1_match = re.search(r"<h1[^>]*>([^<]*)</h1>", html)
    noscript_h1 = re.search(r"<noscript>.*?<h1[^>]*>([^<]*)</h1>", html, re.DOTALL)
    if not h1_match and not noscript_h1:
        issues.append("missing_h1")
        score -= 15

    # CHECK 3: SPA fallback detection
    has_empty_root = '<div id="root"></div>' in html
    body_content = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL)
    body_text = body_content.group(1) if body_content else ""
    # Check if body only has empty root div (no real content outside noscript)
    visible_content = re.sub(r"<noscript>.*?</noscript>", "", body_text, flags=re.DOTALL)
    visible_content = re.sub(r"<script[^>]*>.*?</script>", "", visible_content, flags=re.DOTALL)
    visible_content = re.sub(r"<[^>]+>", "", visible_content).strip()

    if has_empty_root and len(visible_content) < 50:
        # Could be SPA — check if title/description are generic
        is_generic_title = any(g in title_text for g in ["AI Safety Infrastructure", "Real-Time Safety Monitoring for India"])
        is_generic_desc = desc_match and any(g in desc_match.group(1) for g in GENERIC_DESCRIPTIONS) if desc_match else False

        if is_generic_title or is_generic_desc:
            issues.append("spa_fallback_detected")
            score -= 30
        if is_generic_desc:
            issues.append("generic_meta_detected")
            score -= 10

    # CHECK 4: City keyword check
    city = _extract_city_from_slug(url)
    if city:
        city_lower = city.lower()
        content_lower = html.lower()
        city_in_title = city_lower in title_text.lower() if title_text else False
        city_in_h1 = city_lower in (h1_match.group(1).lower() if h1_match else "") or city_lower in (noscript_h1.group(1).lower() if noscript_h1 else "")
        if not city_in_title and not city_in_h1:
            issues.append(f"city_mismatch: '{city}' not found in title or h1")
            score -= 15

    # CHECK 5: Noscript check
    noscript_match = re.search(r"<noscript>(.*?)</noscript>", html, re.DOTALL)
    if noscript_match:
        if "<h1" not in noscript_match.group(1):
            issues.append("noscript_missing_h1")
            score -= 5
    else:
        issues.append("missing_noscript")
        score -= 5

    score = max(score, 0)
    status = "ok" if not issues else ("warning" if score >= 70 else "fail")

    return {"status": status, "url": url, "issues": issues, "seo_score": score, "city_detected": city}


# ═══════════════════════════════════════════════════════════════
# MODULE 5: CLEAN URL VALIDATION
# ═══════════════════════════════════════════════════════════════

@router.post("/geo-compare")
def geo_compare(payload: GeoCompareInput):
    clean = _fetch_url(payload.url_clean)
    html_ver = _fetch_url(payload.url_html)

    if not clean["ok"]:
        return {"match": False, "issue": f"clean_url_fetch_error: {clean.get('error')}"}
    if not html_ver["ok"]:
        return {"match": False, "issue": f"html_url_fetch_error: {html_ver.get('error')}"}

    # Extract titles for comparison
    clean_title = re.search(r"<title>([^<]*)</title>", clean["text"])
    html_title = re.search(r"<title>([^<]*)</title>", html_ver["text"])

    clean_t = clean_title.group(1) if clean_title else ""
    html_t = html_title.group(1) if html_title else ""

    if clean_t == html_t and clean_t:
        return {"match": True, "title": clean_t, "issue": None}

    return {
        "match": False,
        "clean_title": clean_t,
        "html_title": html_t,
        "issue": "nginx_misconfig" if clean_t != html_t else "both_empty",
    }


# ═══════════════════════════════════════════════════════════════
# MODULE 6: BUILD VALIDATION
# ═══════════════════════════════════════════════════════════════

@router.post("/build-check")
def build_check(payload: BuildCheckInput):
    import os
    build_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "frontend", "build")

    missing = []
    found = []
    for f in payload.list_of_files:
        # Check both flat .html and folder/index.html
        flat = os.path.join(build_dir, f)
        stem = f.replace(".html", "") if f.endswith(".html") else f
        folder = os.path.join(build_dir, stem, "index.html")

        if os.path.isfile(flat):
            found.append({"file": f, "type": "flat", "path": flat})
        elif os.path.isfile(folder):
            found.append({"file": f, "type": "folder", "path": folder})
        else:
            missing.append(f)

    return {
        "status": "ok" if not missing else "fail",
        "build_dir": build_dir,
        "found": len(found),
        "missing": missing,
        "missing_count": len(missing),
        "total_checked": len(payload.list_of_files),
    }


# ═══════════════════════════════════════════════════════════════
# MODULE 7: CACHE DEBUG HELPER
# ═══════════════════════════════════════════════════════════════

@router.post("/cache-check")
def cache_check(payload: CacheCheckInput):
    result = _fetch_url(payload.url)
    if not result["ok"]:
        return {"status": "error", "error": result.get("error")}

    headers = result["headers"]
    cf_cache = headers.get("cf-cache-status", headers.get("CF-Cache-Status", "unknown"))
    age = headers.get("age", "0")
    cache_control = headers.get("cache-control", "")
    x_cache = headers.get("x-cache", "")

    is_cached = cf_cache in ("HIT", "STALE", "REVALIDATED") or int(age) > 0

    if cf_cache == "HIT" and int(age) > 3600:
        recommendation = "purge_cache"
    elif cf_cache == "STALE":
        recommendation = "purge_cache"
    else:
        recommendation = "ok"

    return {
        "url": payload.url,
        "cache_status": cf_cache,
        "age_seconds": int(age),
        "cache_control": cache_control,
        "x_cache": x_cache,
        "is_cached": is_cached,
        "recommendation": recommendation,
    }



# ═══════════════════════════════════════════════════════════════
# MODULE 8: GEO HEALTH MONITOR
# ═══════════════════════════════════════════════════════════════

BASE_DOMAIN = "https://nischint.care"

GEO_SLUGS = [
    "women-safety-app-mumbai", "women-safety-app-delhi", "women-safety-app-bangalore",
    "women-safety-app-chennai", "women-safety-app-hyderabad", "women-safety-app-pune",
    "women-safety-app-kolkata", "women-safety-app-ahmedabad", "women-safety-app-jaipur",
    "women-safety-app-lucknow",
    "kids-safety-app-mumbai", "kids-safety-app-delhi", "kids-safety-app-bangalore",
    "kids-safety-app-chennai", "kids-safety-app-hyderabad", "kids-safety-app-pune",
    "kids-safety-app-kolkata",
    "family-safety-app-mumbai", "family-safety-app-delhi", "family-safety-app-bangalore",
    "family-safety-app-chennai", "family-safety-app-hyderabad", "family-safety-app-pune",
    "best-women-safety-app-mumbai", "best-women-safety-app-delhi", "best-women-safety-app-bangalore",
    "best-women-safety-app-chennai", "best-women-safety-app-hyderabad",
    "personal-safety-app-mumbai", "personal-safety-app-delhi", "personal-safety-app-bangalore",
    "personal-safety-app-chennai", "personal-safety-app-hyderabad",
    "best-women-safety-app-pune", "personal-safety-app-pune",
]

GEO_URLS = [f"{BASE_DOMAIN}/{slug}" for slug in GEO_SLUGS]

ALERT_THRESHOLD = 80

_health_logs: list = []
_health_alerts: list = []

# ── Trend Tracking ──
_geo_history: dict = {}   # url -> list of {date, score, issues}
_regressions: list = []   # detected regressions
LAST_DEPLOY_TIME: str = datetime.now(timezone.utc).isoformat()  # set via POST /geo-health/deploy-tag


def _send_alert_email(alerts: list):
    """Send alert email. Currently logs to console; wire to SendGrid later."""
    if not alerts:
        return
    logger.warning(f"[GEO_HEALTH] === ALERT: {len(alerts)} pages need attention ===")
    for a in alerts:
        reg_tag = f" [REGRESSION drop={a.get('drop',0)}]" if a.get("regression_type") else ""
        logger.warning(f"[GEO_HEALTH]   {a['url']} → score {a['score']}{reg_tag}, issues: {a['issues']}")


def _detect_regression(url: str, current_score: int, ts: str) -> Optional[dict]:
    """Compare latest score against previous. Returns regression info or None."""
    history = _geo_history.get(url, [])
    if len(history) < 2:
        return None

    prev = history[-2]
    drop = prev["score"] - current_score

    if drop <= 0:
        return None

    reg_type = "critical_regression" if drop >= 10 else "regression"
    deploy_related = ts > LAST_DEPLOY_TIME and drop > 0

    regression = {
        "url": url,
        "previous_score": prev["score"],
        "current_score": current_score,
        "drop": drop,
        "drop_pct": round((drop / prev["score"]) * 100, 1) if prev["score"] > 0 else 100.0,
        "regression_type": reg_type,
        "deployment_related": deploy_related,
        "previous_date": prev["date"],
        "current_date": ts,
    }
    _regressions.append(regression)
    return regression


def run_geo_health_scan() -> dict:
    """Scan all GEO URLs, log results, track trends, detect regressions."""
    ts = datetime.now(timezone.utc).isoformat()
    date_str = ts[:10]
    scan_id = str(uuid.uuid4())[:8]
    logger.info(f"[GEO_HEALTH] Scan {scan_id} started — {len(GEO_URLS)} URLs")

    results = []
    new_alerts = []
    new_regressions = []

    for url in GEO_URLS:
        try:
            check = _run_geo_check(url)
        except Exception as e:
            check = {"url": url, "seo_score": 0, "issues": [f"scan_error: {e}"], "status": "fail", "city_detected": None}

        score = check.get("seo_score", 0)
        issues = check.get("issues", [])

        entry = {
            "url": url,
            "score": score,
            "status": check.get("status", "fail"),
            "issues": issues,
            "city": check.get("city_detected"),
            "timestamp": ts,
            "scan_id": scan_id,
        }
        results.append(entry)
        _health_logs.append(entry)

        # Track history
        _geo_history.setdefault(url, []).append({"date": date_str, "score": score, "issues": issues})
        # Cap per-URL history at 90 entries
        if len(_geo_history[url]) > 90:
            _geo_history[url] = _geo_history[url][-90:]

        # Detect regression
        regression = _detect_regression(url, score, ts)
        if regression:
            new_regressions.append(regression)

        # Alert: threshold breach OR regression
        if score < ALERT_THRESHOLD or regression:
            alert = {
                "url": url,
                "score": score,
                "previous_score": regression["previous_score"] if regression else None,
                "drop": regression["drop"] if regression else None,
                "regression_type": regression["regression_type"] if regression else None,
                "deployment_related": regression["deployment_related"] if regression else False,
                "issues": issues,
                "city": check.get("city_detected"),
                "timestamp": ts,
                "scan_id": scan_id,
            }
            new_alerts.append(alert)
            _health_alerts.append(alert)

    # Trim logs
    if len(_health_logs) > 500:
        del _health_logs[:-500]
    if len(_regressions) > 200:
        del _regressions[:-200]

    _send_alert_email(new_alerts)

    ok_count = sum(1 for r in results if r["score"] >= ALERT_THRESHOLD)
    fail_count = len(results) - ok_count
    avg_score = round(sum(r["score"] for r in results) / len(results), 1) if results else 0

    summary = {
        "scan_id": scan_id,
        "timestamp": ts,
        "total_checked": len(results),
        "passed": ok_count,
        "failed": fail_count,
        "avg_score": avg_score,
        "alerts_generated": len(new_alerts),
        "regressions_detected": len(new_regressions),
        "results": results,
    }

    logger.info(f"[GEO_HEALTH] Scan {scan_id} complete — {ok_count} ok, {fail_count} fail, avg {avg_score}, regressions {len(new_regressions)}")
    return summary


@router.get("/geo-health/logs")
def get_health_logs(limit: int = 100):
    """Return recent health check logs."""
    logs = _health_logs[-limit:]
    return {"logs": logs, "count": len(logs), "total_stored": len(_health_logs)}


@router.get("/geo-health/alerts")
def get_health_alerts(limit: int = 50):
    """Return pages that failed the health threshold."""
    alerts = _health_alerts[-limit:]
    return {"alerts": alerts, "count": len(alerts), "threshold": ALERT_THRESHOLD}


@router.post("/geo-health/run")
def trigger_health_scan():
    """Manually trigger a full GEO health scan."""
    return run_geo_health_scan()


@router.get("/geo-health/trends")
def get_trends(url: Optional[str] = None):
    """Return score history per URL. Optionally filter by URL."""
    if url:
        history = _geo_history.get(url, [])
        return {"url": url, "history": history, "data_points": len(history)}

    # Return all with 7-day rolling avg + volatility
    trends = {}
    for u, history in _geo_history.items():
        scores = [h["score"] for h in history]
        recent_7 = scores[-7:] if len(scores) >= 7 else scores
        rolling_avg = round(sum(recent_7) / len(recent_7), 1) if recent_7 else 0
        # Volatility: standard deviation of recent scores
        if len(recent_7) >= 2:
            mean = sum(recent_7) / len(recent_7)
            variance = sum((s - mean) ** 2 for s in recent_7) / len(recent_7)
            volatility = round(variance ** 0.5, 1)
        else:
            volatility = 0.0

        slug = u.split("/")[-1]
        trends[slug] = {
            "url": u,
            "data_points": len(history),
            "latest_score": scores[-1] if scores else None,
            "rolling_avg_7d": rolling_avg,
            "volatility": volatility,
            "history": history[-14:],  # last 14 entries
        }
    return {"trends": trends, "tracked_urls": len(trends)}


@router.get("/geo-health/regressions")
def get_regressions(limit: int = 50):
    """Return all detected score regressions."""
    recent = _regressions[-limit:]
    return {"regressions": recent, "count": len(recent), "total_stored": len(_regressions)}


@router.get("/geo-health/summary")
def get_health_summary():
    """Return overall health summary: avg, lowest, unstable pages."""
    if not _geo_history:
        return {"status": "no_data", "message": "No scans recorded yet"}

    latest_scores = {}
    unstable = []
    for u, history in _geo_history.items():
        if not history:
            continue
        scores = [h["score"] for h in history]
        latest_scores[u] = scores[-1]

        # Unstable = volatility > 5 over last 7 entries
        recent = scores[-7:] if len(scores) >= 7 else scores
        if len(recent) >= 2:
            mean = sum(recent) / len(recent)
            variance = sum((s - mean) ** 2 for s in recent) / len(recent)
            vol = round(variance ** 0.5, 1)
            if vol > 5:
                unstable.append({"url": u, "volatility": vol, "recent_scores": recent})

    all_scores = list(latest_scores.values())
    avg = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0
    lowest_url = min(latest_scores, key=latest_scores.get) if latest_scores else None
    lowest_score = latest_scores.get(lowest_url, 0) if lowest_url else 0

    return {
        "avg_score": avg,
        "lowest_score": lowest_score,
        "lowest_url": lowest_url,
        "total_tracked": len(latest_scores),
        "healthy_count": sum(1 for s in all_scores if s >= ALERT_THRESHOLD),
        "failing_count": sum(1 for s in all_scores if s < ALERT_THRESHOLD),
        "unstable_pages": unstable,
        "total_regressions": len(_regressions),
        "last_deploy": LAST_DEPLOY_TIME,
    }


@router.post("/geo-health/deploy-tag")
def tag_deployment():
    """Mark current time as last deployment. Used for regression correlation."""
    global LAST_DEPLOY_TIME
    LAST_DEPLOY_TIME = datetime.now(timezone.utc).isoformat()
    logger.info(f"[GEO_HEALTH] Deploy tagged at {LAST_DEPLOY_TIME}")
    return {"status": "ok", "deploy_time": LAST_DEPLOY_TIME}


def start_geo_health_scheduler():
    """Register daily GEO health scan — runs at 6:00 AM UTC (11:30 AM IST)."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        scheduler = BackgroundScheduler()
        scheduler.add_job(
            run_geo_health_scan,
            IntervalTrigger(hours=24),
            id="geo_health_daily",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("[GEO_HEALTH] Scheduler registered — runs every 24 hours")
    except ImportError:
        logger.warning("[GEO_HEALTH] apscheduler not available — daily scan disabled")
    except Exception as e:
        logger.error(f"[GEO_HEALTH] Scheduler setup failed: {e}")


# ═══════════════════════════════════════════════════════════════
# GEO HEALTH DASHBOARD (HTML)
# ═══════════════════════════════════════════════════════════════

GEO_HEALTH_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>GEO Health Monitor — NISCHINT</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  body{background:#060b18;color:#cbd5e1;font-family:Inter,-apple-system,BlinkMacSystemFont,sans-serif}
  .card{background:rgba(255,255,255,.025);border:1px solid rgba(100,116,139,.18);border-radius:16px;padding:20px 24px}
  .spark{display:inline-flex;align-items:end;gap:2px;height:28px}
  .spark b{width:5px;border-radius:2px;background:#6366f1;min-height:2px}
  .badge{font-size:11px;font-weight:600;padding:2px 10px;border-radius:9999px;display:inline-block}
  .bg-ok{background:rgba(16,185,129,.15);color:#34d399}
  .bg-warn{background:rgba(245,158,11,.15);color:#fbbf24}
  .bg-fail{background:rgba(239,68,68,.15);color:#f87171}
  .trend-up{color:#34d399}.trend-down{color:#f87171}.trend-flat{color:#64748b}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{text-align:left;padding:8px 12px;color:#475569;font-size:11px;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid rgba(51,65,85,.3)}
  td{padding:8px 12px;border-bottom:1px solid rgba(51,65,85,.15)}
  tr:hover{background:rgba(255,255,255,.02)}
  .scan-btn{background:linear-gradient(135deg,#6366f1,#4f46e5);color:#fff;border:none;padding:8px 20px;border-radius:10px;font-size:13px;font-weight:600;cursor:pointer}
  .scan-btn:hover{opacity:.9}.scan-btn:disabled{opacity:.4;cursor:wait}
  .loader{display:none;width:16px;height:16px;border:2px solid #4f46e5;border-top-color:transparent;border-radius:50%;animation:spin .6s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>
<div style="max-width:1100px;margin:0 auto;padding:24px 16px">

  <!-- NAV -->
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:28px">
    <div style="display:flex;align-items:center;gap:10px">
      <div style="width:32px;height:32px;border-radius:10px;background:linear-gradient(135deg,#14b8a6,#6366f1);display:flex;align-items:center;justify-content:center">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
      </div>
      <span style="font-weight:700;font-size:15px;color:#e2e8f0">NISCHINT</span>
      <span style="color:#475569;font-size:13px">/ GEO Health</span>
    </div>
    <div style="display:flex;align-items:center;gap:10px">
      <span id="last-update" style="font-size:11px;color:#475569"></span>
      <div id="loader" class="loader"></div>
      <button class="scan-btn" id="scan-btn" onclick="runScan()">Run Scan</button>
    </div>
  </div>

  <!-- SUMMARY CARDS -->
  <div id="cards" style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px">
    <div class="card"><div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">Avg Score</div><div id="c-avg" style="font-size:28px;font-weight:700;color:#fff">—</div></div>
    <div class="card"><div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">Lowest Score</div><div id="c-low" style="font-size:28px;font-weight:700;color:#fff">—</div><div id="c-low-url" style="font-size:11px;color:#475569;margin-top:2px"></div></div>
    <div class="card"><div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">Unstable Pages</div><div id="c-unstable" style="font-size:28px;font-weight:700;color:#fff">—</div></div>
    <div class="card"><div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">Regressions</div><div id="c-reg" style="font-size:28px;font-weight:700;color:#fff">—</div></div>
  </div>

  <!-- GEO GRID -->
  <div class="card" style="margin-bottom:20px;overflow-x:auto">
    <div style="font-size:14px;font-weight:600;color:#e2e8f0;margin-bottom:12px">GEO Page Grid</div>
    <table>
      <thead><tr><th>Page</th><th>City</th><th>Type</th><th style="text-align:center">Score</th><th style="text-align:center">Status</th><th style="text-align:center">Trend</th><th style="text-align:center">7d Avg</th><th>Sparkline</th></tr></thead>
      <tbody id="grid-body"><tr><td colspan="8" style="text-align:center;color:#475569;padding:24px">Loading…</td></tr></tbody>
    </table>
  </div>

  <!-- REGRESSIONS -->
  <div class="card" id="reg-panel" style="display:none;margin-bottom:20px">
    <div style="font-size:14px;font-weight:600;color:#e2e8f0;margin-bottom:12px">Regressions Detected</div>
    <table>
      <thead><tr><th>Page</th><th style="text-align:center">Previous</th><th style="text-align:center">Current</th><th style="text-align:center">Drop</th><th style="text-align:center">Type</th><th style="text-align:center">Deploy?</th></tr></thead>
      <tbody id="reg-body"></tbody>
    </table>
  </div>

</div>

<script>
const API=window.location.origin+'/api/engine';
const slugCity=s=>{const m=s.match(/safety-app-(.+)/);return m?m[1].replace(/-/g,' ').replace(/\\b\\w/g,c=>c.toUpperCase()):s};
const slugType=s=>{if(s.includes('women'))return'Women';if(s.includes('kids'))return'Kids';if(s.includes('family'))return'Family';if(s.includes('personal'))return'Personal';return'—'};
const slugVariant=s=>s.startsWith('best-')?'Best':s.startsWith('personal-')?'Personal':'Default';

function scoreBadge(s){
  if(s>=90)return `<span class="badge bg-ok">${s}</span>`;
  if(s>=70)return `<span class="badge bg-warn">${s}</span>`;
  return `<span class="badge bg-fail">${s}</span>`;
}

function sparkline(history){
  if(!history||!history.length)return'<span style="color:#334155">—</span>';
  const scores=history.map(h=>h.score);
  const mx=Math.max(...scores,1);
  return '<span class="spark">'+scores.slice(-7).map(s=>`<b style="height:${Math.max((s/mx)*26,2)}px;background:${s>=90?'#10b981':s>=70?'#f59e0b':'#ef4444'}"></b>`).join('')+'</span>';
}

function trendArrow(history){
  if(!history||history.length<2)return'<span class="trend-flat">→</span>';
  const cur=history[history.length-1].score,prev=history[history.length-2].score;
  if(cur>prev)return'<span class="trend-up">↑ +'+(cur-prev)+'</span>';
  if(cur<prev)return'<span class="trend-down">↓ '+(cur-prev)+'</span>';
  return'<span class="trend-flat">→ 0</span>';
}

async function load(){
  try{
    const[sumR,trendR,regR]=await Promise.all([
      fetch(API+'/geo-health/summary').then(r=>r.json()),
      fetch(API+'/geo-health/trends').then(r=>r.json()),
      fetch(API+'/geo-health/regressions').then(r=>r.json()),
    ]);

    // Summary cards
    if(sumR.status==='no_data'){
      document.getElementById('c-avg').textContent='—';
      document.getElementById('c-low').textContent='—';
      document.getElementById('c-unstable').textContent='0';
      document.getElementById('c-reg').textContent='0';
      document.getElementById('grid-body').innerHTML='<tr><td colspan="8" style="text-align:center;color:#64748b;padding:32px">No scan data yet. Click <b>Run Scan</b> to start.</td></tr>';
      return;
    }
    document.getElementById('c-avg').textContent=sumR.avg_score;
    document.getElementById('c-avg').style.color=sumR.avg_score>=90?'#34d399':sumR.avg_score>=70?'#fbbf24':'#f87171';
    document.getElementById('c-low').textContent=sumR.lowest_score;
    document.getElementById('c-low').style.color=sumR.lowest_score>=90?'#34d399':sumR.lowest_score>=70?'#fbbf24':'#f87171';
    document.getElementById('c-low-url').textContent=sumR.lowest_url?slugCity(sumR.lowest_url.split('/').pop()):'';
    document.getElementById('c-unstable').textContent=sumR.unstable_pages?sumR.unstable_pages.length:0;
    document.getElementById('c-reg').textContent=sumR.total_regressions||0;

    // Grid
    const trends=trendR.trends||{};
    const slugs=Object.keys(trends).sort((a,b)=>(trends[a].latest_score||0)-(trends[b].latest_score||0));
    if(slugs.length===0){
      document.getElementById('grid-body').innerHTML='<tr><td colspan="8" style="text-align:center;color:#64748b;padding:32px">No trend data. Run a scan first.</td></tr>';
    }else{
      document.getElementById('grid-body').innerHTML=slugs.map(slug=>{
        const t=trends[slug];
        const city=slugCity(slug);
        const type=slugType(slug);
        const score=t.latest_score!=null?t.latest_score:'—';
        const status=score>=90?'<span class="badge bg-ok">Healthy</span>':score>=70?'<span class="badge bg-warn">Warning</span>':'<span class="badge bg-fail">Failing</span>';
        return `<tr><td style="color:#e2e8f0;font-weight:500">${slug}</td><td>${city}</td><td>${type}</td><td style="text-align:center">${scoreBadge(score)}</td><td style="text-align:center">${status}</td><td style="text-align:center">${trendArrow(t.history)}</td><td style="text-align:center;color:#94a3b8">${t.rolling_avg_7d}</td><td>${sparkline(t.history)}</td></tr>`;
      }).join('');
    }

    // Regressions
    const regs=regR.regressions||[];
    if(regs.length>0){
      document.getElementById('reg-panel').style.display='block';
      document.getElementById('reg-body').innerHTML=regs.map(r=>{
        const slug=r.url.split('/').pop();
        const dropColor=r.drop>=10?'#f87171':'#fbbf24';
        return `<tr><td style="color:#e2e8f0;font-weight:500">${slug}</td><td style="text-align:center">${r.previous_score}</td><td style="text-align:center;color:${dropColor}">${r.current_score}</td><td style="text-align:center;color:${dropColor}">-${r.drop} (${r.drop_pct}%)</td><td style="text-align:center"><span class="badge ${r.regression_type==='critical_regression'?'bg-fail':'bg-warn'}">${r.regression_type}</span></td><td style="text-align:center">${r.deployment_related?'<span style="color:#f87171">Yes</span>':'<span style="color:#475569">No</span>'}</td></tr>`;
      }).join('');
    }else{
      document.getElementById('reg-panel').style.display='none';
    }

    document.getElementById('last-update').textContent='Updated: '+new Date().toLocaleTimeString();
  }catch(e){console.error('Dashboard load error:',e)}
}

async function runScan(){
  const btn=document.getElementById('scan-btn');
  const ldr=document.getElementById('loader');
  btn.disabled=true;btn.textContent='Scanning…';ldr.style.display='block';
  try{
    await fetch(API+'/geo-health/run',{method:'POST'});
    await load();
  }catch(e){console.error('Scan error:',e)}
  btn.disabled=false;btn.textContent='Run Scan';ldr.style.display='none';
}

load();
setInterval(load,60000);
</script>
</body>
</html>"""


@router.get("/geo-health/dashboard", response_class=HTMLResponse, include_in_schema=False)
def geo_health_dashboard():
    return HTMLResponse(content=GEO_HEALTH_DASHBOARD_HTML)
