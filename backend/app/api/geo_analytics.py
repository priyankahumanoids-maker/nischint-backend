"""
GEO Analytics — Track and aggregate GEO SEO page performance.
Events: geo_page_view, geo_cta_click
"""
import logging
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db_session

logger = logging.getLogger(__name__)
router = APIRouter(tags=["GEO Analytics"])

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS geo_events (
    id UUID PRIMARY KEY,
    event TEXT NOT NULL,
    city TEXT,
    type TEXT,
    variant TEXT DEFAULT 'default',
    channel TEXT DEFAULT 'seo_geo',
    url TEXT,
    session_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""

INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_geo_event ON geo_events(event);",
    "CREATE INDEX IF NOT EXISTS idx_geo_city ON geo_events(city);",
    "CREATE INDEX IF NOT EXISTS idx_geo_variant ON geo_events(variant);",
    "CREATE INDEX IF NOT EXISTS idx_geo_channel ON geo_events(channel);",
    "CREATE INDEX IF NOT EXISTS idx_geo_session ON geo_events(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_geo_created ON geo_events(created_at);",
]

_tables_ready = False


async def _ensure_tables(db: AsyncSession):
    global _tables_ready
    if _tables_ready:
        return
    await db.execute(text(TABLE_SQL))
    # Add columns that may not exist on older tables
    for col, defn in [("channel", "TEXT DEFAULT 'seo_geo'"), ("session_id", "TEXT")]:
        try:
            await db.execute(text(f"ALTER TABLE geo_events ADD COLUMN IF NOT EXISTS {col} {defn};"))
        except Exception:
            pass
    for idx in INDEXES_SQL:
        await db.execute(text(idx))
    await db.commit()
    _tables_ready = True


class GeoEvent(BaseModel):
    event: str
    city: Optional[str] = None
    type: Optional[str] = None
    variant: Optional[str] = "default"
    channel: Optional[str] = "seo_geo"
    url: Optional[str] = None
    session_id: Optional[str] = None


@router.post("/geo-events")
async def track_event(payload: GeoEvent, db: AsyncSession = Depends(get_db_session)):
    await _ensure_tables(db)
    event_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO geo_events (id, event, city, type, variant, channel, url, session_id, created_at)
            VALUES (:id, :event, :city, :type, :variant, :channel, :url, :sid, :ts)
        """),
        {
            "id": event_id,
            "event": payload.event,
            "city": payload.city,
            "type": payload.type,
            "variant": payload.variant,
            "channel": payload.channel,
            "url": payload.url,
            "sid": payload.session_id,
            "ts": datetime.now(timezone.utc),
        },
    )
    await db.commit()
    return {"ok": True, "id": event_id}


@router.get("/geo-analytics")
async def geo_analytics(
    days: int = 30,
    city: Optional[str] = None,
    variant: Optional[str] = None,
    type: Optional[str] = None,
    db: AsyncSession = Depends(get_db_session),
):
    await _ensure_tables(db)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Build optional WHERE fragments
    filters = ["created_at >= :since"]
    params = {"since": since}
    if city:
        filters.append("city = :city")
        params["city"] = city
    if variant:
        filters.append("variant = :variant")
        params["variant"] = variant
    if type:
        filters.append("type = :vtype")
        params["vtype"] = type
    where = " AND ".join(filters)

    # Top cities by page views
    top_cities_q = await db.execute(
        text(f"""
            SELECT city, COUNT(*) as views
            FROM geo_events
            WHERE event = 'geo_page_view' AND city IS NOT NULL AND {where}
            GROUP BY city ORDER BY views DESC LIMIT 20
        """),
        params,
    )
    top_cities = [{"city": r[0], "views": r[1]} for r in top_cities_q.fetchall()]

    # Top variants by page views
    top_variants_q = await db.execute(
        text(f"""
            SELECT variant, COUNT(*) as views
            FROM geo_events
            WHERE event = 'geo_page_view' AND variant IS NOT NULL AND {where}
            GROUP BY variant ORDER BY views DESC
        """),
        params,
    )
    top_variants = [{"variant": r[0], "views": r[1]} for r in top_variants_q.fetchall()]

    # Conversion rates: cta_clicks / page_views per city
    conversion_q = await db.execute(
        text(f"""
            SELECT
                city,
                COUNT(*) FILTER (WHERE event = 'geo_page_view') as views,
                COUNT(*) FILTER (WHERE event = 'geo_cta_click') as clicks
            FROM geo_events
            WHERE city IS NOT NULL AND {where}
            GROUP BY city
            HAVING COUNT(*) FILTER (WHERE event = 'geo_page_view') > 0
            ORDER BY clicks DESC LIMIT 20
        """),
        params,
    )
    conversion_rates = []
    for r in conversion_q.fetchall():
        views = r[1]
        clicks = r[2]
        rate = round((clicks / views) * 100, 1) if views > 0 else 0
        conversion_rates.append({"city": r[0], "views": views, "clicks": clicks, "rate": rate})

    # Conversion rates by variant
    conv_variant_q = await db.execute(
        text(f"""
            SELECT
                variant,
                COUNT(*) FILTER (WHERE event = 'geo_page_view') as views,
                COUNT(*) FILTER (WHERE event = 'geo_cta_click') as clicks
            FROM geo_events
            WHERE variant IS NOT NULL AND {where}
            GROUP BY variant
            HAVING COUNT(*) FILTER (WHERE event = 'geo_page_view') > 0
            ORDER BY clicks DESC
        """),
        params,
    )
    conversion_by_variant = []
    for r in conv_variant_q.fetchall():
        v, views, clicks = r[0], r[1], r[2]
        rate = round((clicks / views) * 100, 1) if views > 0 else 0
        conversion_by_variant.append({"variant": v, "views": views, "clicks": clicks, "rate": rate})

    # Top types by page views
    top_types_q = await db.execute(
        text(f"""
            SELECT type, COUNT(*) as views
            FROM geo_events
            WHERE event = 'geo_page_view' AND type IS NOT NULL AND {where}
            GROUP BY type ORDER BY views DESC
        """),
        params,
    )
    top_types = [{"type": r[0], "views": r[1]} for r in top_types_q.fetchall()]

    # Totals
    totals_q = await db.execute(
        text(f"""
            SELECT
                COUNT(*) FILTER (WHERE event = 'geo_page_view') as total_views,
                COUNT(*) FILTER (WHERE event = 'geo_cta_click') as total_clicks
            FROM geo_events WHERE {where}
        """),
        params,
    )
    totals = totals_q.fetchone()

    # Daily trend (last N days)
    daily_q = await db.execute(
        text(f"""
            SELECT DATE(created_at) as day, event, COUNT(*) as cnt
            FROM geo_events
            WHERE {where}
            GROUP BY day, event ORDER BY day
        """),
        params,
    )
    daily_trend = {}
    for r in daily_q.fetchall():
        day_str = str(r[0])
        daily_trend.setdefault(day_str, {})[r[1]] = r[2]

    # Recent events (last 25)
    recent_q = await db.execute(
        text(f"""
            SELECT event, city, type, variant, url, created_at
            FROM geo_events
            WHERE {where}
            ORDER BY created_at DESC LIMIT 25
        """),
        params,
    )
    recent_events = [
        {"event": r[0], "city": r[1], "type": r[2], "variant": r[3], "url": r[4], "created_at": r[5].isoformat() if r[5] else None}
        for r in recent_q.fetchall()
    ]

    # Distinct filter options
    cities_q = await db.execute(text("SELECT DISTINCT city FROM geo_events WHERE city IS NOT NULL ORDER BY city"))
    variants_q = await db.execute(text("SELECT DISTINCT variant FROM geo_events WHERE variant IS NOT NULL ORDER BY variant"))
    types_q = await db.execute(text("SELECT DISTINCT type FROM geo_events WHERE type IS NOT NULL ORDER BY type"))

    # ── Decision Engine: variant_performance_by_city ──
    vp_q = await db.execute(
        text(f"""
            SELECT
                city, variant,
                COUNT(*) FILTER (WHERE event = 'geo_page_view') as views,
                COUNT(*) FILTER (WHERE event = 'geo_cta_click') as clicks
            FROM geo_events
            WHERE city IS NOT NULL AND variant IS NOT NULL AND {where}
            GROUP BY city, variant
            ORDER BY city, views DESC
        """),
        params,
    )
    MIN_VIEWS = 30
    city_variants = {}
    for r in vp_q.fetchall():
        c, v, views, clicks = r[0], r[1], r[2], r[3]
        cvr = round((clicks / views) * 100, 1) if views > 0 else 0.0
        city_variants.setdefault(c, {})[v] = {"views": views, "clicks": clicks, "cvr": cvr}

    variant_performance_by_city = {}
    for c, variants_data in city_variants.items():
        entry = dict(variants_data)
        # Find winner among variants with enough views
        eligible = {v: d for v, d in variants_data.items() if d["views"] >= MIN_VIEWS}
        if eligible:
            best_v = max(eligible, key=lambda v: eligible[v]["cvr"])
            best_cvr = eligible[best_v]["cvr"]
            entry["winner"] = best_v
            if best_cvr > 5:
                entry["action"] = "scale"
            elif best_cvr >= 2:
                entry["action"] = "test_more"
            else:
                entry["action"] = "optimize"
                entry["winner"] = "weak_city"
        else:
            # Not enough data for any variant
            total_views = sum(d["views"] for d in variants_data.values())
            entry["winner"] = "insufficient_data"
            entry["action"] = "test_more" if total_views > 0 else "optimize"
        variant_performance_by_city[c] = entry

    # ── Auto Recommendations ──
    recommendations = []
    scale_variants = {}
    weak_cities = []
    for c, entry in variant_performance_by_city.items():
        if entry["action"] == "scale":
            w = entry["winner"]
            scale_variants.setdefault(w, []).append(c)
        elif entry.get("winner") == "weak_city":
            weak_cities.append(c)
    for v, cities_list in scale_variants.items():
        recommendations.append(f"Expand '{v}' variant to more cities — already winning in {', '.join(cities_list)}")
    if weak_cities:
        recommendations.append(f"Optimize or pause {len(weak_cities)} weak cities: {', '.join(weak_cities[:5])}")
    insufficient = [c for c, e in variant_performance_by_city.items() if e.get("winner") == "insufficient_data"]
    if insufficient:
        recommendations.append(f"Need more traffic data for {len(insufficient)} cities before making decisions")

    # ── City-to-City Benchmarking ──
    import math

    ACTION_MAP = {
        "high_performer": "scale aggressively",
        "above_average": "expand variants",
        "below_average": "optimize content",
        "weak": "rework or drop",
    }

    # Step 1: For each city, pick best variant (highest CVR with views >= MIN_VIEWS)
    city_best = {}
    for c, variants_data in city_variants.items():
        eligible = {v: d for v, d in variants_data.items() if isinstance(d, dict) and d.get("views", 0) >= MIN_VIEWS}
        if eligible:
            best_v = max(eligible, key=lambda v: eligible[v]["cvr"])
            city_best[c] = {"variant": best_v, "cvr": eligible[best_v]["cvr"], "views": eligible[best_v]["views"]}

    # Step 2: Global average CVR across eligible cities
    if city_best:
        global_avg_cvr = round(sum(cb["cvr"] for cb in city_best.values()) / len(city_best), 2)
    else:
        global_avg_cvr = 0.0

    # Step 3+4: Classify and score each city
    city_benchmarking = []
    for c, cb in city_best.items():
        perf_ratio = round(cb["cvr"] / global_avg_cvr, 2) if global_avg_cvr > 0 else 0.0
        if perf_ratio >= 1.5:
            category = "high_performer"
        elif perf_ratio >= 1.0:
            category = "above_average"
        elif perf_ratio >= 0.7:
            category = "below_average"
        else:
            category = "weak"
        priority_score = round(cb["cvr"] * math.log(cb["views"] + 1), 1)
        city_benchmarking.append({
            "city": c,
            "best_variant": cb["variant"],
            "cvr": cb["cvr"],
            "views": cb["views"],
            "performance_ratio": perf_ratio,
            "category": category,
            "priority_score": priority_score,
            "action": ACTION_MAP[category],
        })

    city_benchmarking.sort(key=lambda x: x["priority_score"], reverse=True)

    # Add benchmarking recommendations
    high_perf = [cb["city"] for cb in city_benchmarking if cb["category"] == "high_performer"]
    weak_bench = [cb["city"] for cb in city_benchmarking if cb["category"] == "weak"]
    if high_perf:
        recommendations.append(f"Top performers to scale: {', '.join(high_perf)}")
    if weak_bench:
        recommendations.append(f"Underperforming vs network: {', '.join(weak_bench[:5])} — consider content rework")

    return {
        "period_days": days,
        "total_views": totals[0] if totals else 0,
        "total_clicks": totals[1] if totals else 0,
        "top_cities": top_cities,
        "top_variants": top_variants,
        "top_types": top_types,
        "conversion_rates": conversion_rates,
        "conversion_by_variant": conversion_by_variant,
        "daily_trend": daily_trend,
        "recent_events": recent_events,
        "variant_performance_by_city": variant_performance_by_city,
        "city_benchmarking": city_benchmarking,
        "global_avg_cvr": global_avg_cvr,
        "recommendations": recommendations,
        "filter_options": {
            "cities": [r[0] for r in cities_q.fetchall()],
            "variants": [r[0] for r in variants_q.fetchall()],
            "types": [r[0] for r in types_q.fetchall()],
        },
    }


@router.post("/geo-weekly-report/generate")
async def generate_digest(db: AsyncSession = Depends(get_db_session)):
    """Manually trigger a weekly GEO intelligence digest."""
    from app.services.geo_digest_service import generate_weekly_digest
    result = await generate_weekly_digest(db)
    return result


@router.get("/geo-weekly-report")
async def get_reports(limit: int = 12, db: AsyncSession = Depends(get_db_session)):
    """Get historical weekly GEO digest reports."""
    from app.services.geo_digest_service import get_weekly_reports
    reports = await get_weekly_reports(db, limit)
    return {"reports": reports, "count": len(reports)}
