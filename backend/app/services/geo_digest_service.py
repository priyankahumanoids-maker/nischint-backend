"""
GEO Weekly Intelligence Digest — Automated weekly comparison of GEO SEO performance.
Compares current vs previous week, detects category changes, CVR shifts, and generates
structured highlights/risks/opportunities/recommendations. Sends via SendGrid email.
Stores snapshots in geo_weekly_reports table.
"""
import logging
import math
import uuid
import json
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MIN_VIEWS = 30
DIGEST_RECIPIENT = "Founder.nischint@gmail.com"

CATEGORY_THRESHOLDS = {
    "high_performer": 1.5,
    "above_average": 1.0,
    "below_average": 0.7,
}

ACTION_MAP = {
    "high_performer": "scale aggressively",
    "above_average": "expand variants",
    "below_average": "optimize content",
    "weak": "rework or drop",
}

REPORT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS geo_weekly_reports (
    id UUID PRIMARY KEY,
    week_start DATE NOT NULL,
    week_end DATE NOT NULL,
    summary_json JSONB NOT NULL DEFAULT '{}',
    top_cities JSONB DEFAULT '[]',
    top_variants JSONB DEFAULT '[]',
    city_benchmarking JSONB DEFAULT '[]',
    global_avg_cvr FLOAT DEFAULT 0,
    email_sent BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(week_start)
);
"""

_tables_ready = False


async def _ensure_report_table(db: AsyncSession):
    global _tables_ready
    if _tables_ready:
        return
    await db.execute(text(REPORT_TABLE_SQL))
    await db.commit()
    _tables_ready = True


async def _get_week_metrics(db: AsyncSession, start: datetime, end: datetime):
    """Compute city-level metrics for a date range."""
    rows = await db.execute(
        text("""
            SELECT city, variant,
                COUNT(*) FILTER (WHERE event = 'geo_page_view') as views,
                COUNT(*) FILTER (WHERE event = 'geo_cta_click') as clicks
            FROM geo_events
            WHERE city IS NOT NULL AND variant IS NOT NULL
              AND created_at >= :start AND created_at < :end
            GROUP BY city, variant
        """),
        {"start": start, "end": end},
    )
    city_variants = {}
    for r in rows.fetchall():
        c, v, views, clicks = r[0], r[1], r[2], r[3]
        cvr = round((clicks / views) * 100, 1) if views > 0 else 0.0
        city_variants.setdefault(c, {})[v] = {"views": views, "clicks": clicks, "cvr": cvr}

    # Pick best variant per city (highest CVR with enough views)
    city_best = {}
    for c, variants in city_variants.items():
        eligible = {v: d for v, d in variants.items() if d["views"] >= MIN_VIEWS}
        if eligible:
            best_v = max(eligible, key=lambda v: eligible[v]["cvr"])
            city_best[c] = {
                "variant": best_v,
                "cvr": eligible[best_v]["cvr"],
                "views": eligible[best_v]["views"],
                "clicks": eligible[best_v]["clicks"],
            }

    # Global avg CVR
    if city_best:
        global_avg = round(sum(cb["cvr"] for cb in city_best.values()) / len(city_best), 2)
    else:
        global_avg = 0.0

    # Classify
    for c, cb in city_best.items():
        ratio = round(cb["cvr"] / global_avg, 2) if global_avg > 0 else 0.0
        if ratio >= 1.5:
            cat = "high_performer"
        elif ratio >= 1.0:
            cat = "above_average"
        elif ratio >= 0.7:
            cat = "below_average"
        else:
            cat = "weak"
        cb["performance_ratio"] = ratio
        cb["category"] = cat
        cb["priority_score"] = round(cb["cvr"] * math.log(cb["views"] + 1), 1)

    # Variant totals
    variant_totals = {}
    for c, variants in city_variants.items():
        for v, d in variants.items():
            vt = variant_totals.setdefault(v, {"views": 0, "clicks": 0})
            vt["views"] += d["views"]
            vt["clicks"] += d["clicks"]
    for v, vt in variant_totals.items():
        vt["cvr"] = round((vt["clicks"] / vt["views"]) * 100, 1) if vt["views"] > 0 else 0.0

    return {
        "city_best": city_best,
        "global_avg": global_avg,
        "variant_totals": variant_totals,
        "city_variants": city_variants,
    }


def _compare_weeks(current, previous):
    """Compare two weeks of metrics and detect events."""
    highlights = []
    risks = []
    opportunities = []
    recommendations = []

    curr_cities = current["city_best"]
    prev_cities = previous["city_best"]
    curr_variants = current["variant_totals"]

    # 1. New high performers (not high_performer last week)
    for c, cb in curr_cities.items():
        if cb["category"] == "high_performer":
            prev = prev_cities.get(c, {})
            if prev.get("category") != "high_performer":
                highlights.append(f"{c} ({cb['variant']}) is now a high performer — CVR {cb['cvr']}%")

    # 2. Cities that dropped category
    for c, prev_cb in prev_cities.items():
        curr_cb = curr_cities.get(c)
        if curr_cb:
            rank = {"high_performer": 4, "above_average": 3, "below_average": 2, "weak": 1}
            if rank.get(curr_cb["category"], 0) < rank.get(prev_cb["category"], 0):
                risks.append(f"{c} dropped from {prev_cb['category']} to {curr_cb['category']}")

    # 3. Biggest CVR increase
    cvr_changes = []
    for c, cb in curr_cities.items():
        prev = prev_cities.get(c)
        if prev:
            delta = round(cb["cvr"] - prev["cvr"], 1)
            cvr_changes.append({"city": c, "variant": cb["variant"], "delta": delta, "cvr": cb["cvr"]})
    cvr_changes.sort(key=lambda x: x["delta"], reverse=True)

    if cvr_changes and cvr_changes[0]["delta"] > 0:
        top = cvr_changes[0]
        highlights.append(f"{top['city']} ({top['variant']}) — CVR up +{top['delta']}% to {top['cvr']}%")

    # 4. Biggest CVR drop
    if cvr_changes and cvr_changes[-1]["delta"] < 0:
        bottom = cvr_changes[-1]
        risks.append(f"{bottom['city']} ({bottom['variant']}) — CVR down {bottom['delta']}% to {bottom['cvr']}%")

    # 5. Top performing variant overall
    if curr_variants:
        best_variant = max(curr_variants.items(), key=lambda x: x[1]["cvr"])
        highlights.append(f"Top variant this week: '{best_variant[0]}' with {best_variant[1]['cvr']}% CVR ({best_variant[1]['views']} views)")

    # Opportunities: variants doing well in Tier 2 / smaller cities
    tier1 = {"Mumbai", "Delhi", "Bangalore", "Chennai", "Hyderabad", "Pune", "Kolkata"}
    tier2_performers = []
    for c, cb in curr_cities.items():
        if c not in tier1 and cb["category"] in ("high_performer", "above_average"):
            tier2_performers.append(f"{c} ({cb['variant']}, {cb['cvr']}%)")
    if tier2_performers:
        opportunities.append(f"Strong performance in non-Tier-1 cities: {', '.join(tier2_performers[:5])}")

    # Opportunities: variant winning in multiple cities
    variant_wins = {}
    for c, cb in curr_cities.items():
        if cb["category"] in ("high_performer", "above_average"):
            variant_wins.setdefault(cb["variant"], []).append(c)
    for v, cities in variant_wins.items():
        if len(cities) >= 2:
            opportunities.append(f"'{v}' variant winning in {len(cities)} cities — consider expanding to more")

    # Recommendations
    scale_cities = [c for c, cb in curr_cities.items() if cb["category"] == "high_performer"]
    weak_cities = [c for c, cb in curr_cities.items() if cb["category"] == "weak"]
    if scale_cities:
        recommendations.append(f"Scale aggressively: {', '.join(scale_cities)}")
    if weak_cities:
        recommendations.append(f"Optimize content for: {', '.join(weak_cities[:5])}")

    # New cities not in previous week
    new_cities = [c for c in curr_cities if c not in prev_cities]
    if new_cities:
        recommendations.append(f"New cities with enough data: {', '.join(new_cities)} — monitor closely")

    # If no events detected, add a note
    if not highlights:
        highlights.append("No significant performance changes detected this week")

    return {
        "highlights": highlights,
        "risks": risks,
        "opportunities": opportunities,
        "recommendations": recommendations,
        "cvr_changes": cvr_changes[:10],
    }


def _build_email_html(summary, current_metrics, week_start, week_end):
    """Build a clean HTML email for the weekly digest."""
    highlights_html = "".join(f'<li style="color:#2dd4bf;padding:4px 0;">{h}</li>' for h in summary["highlights"])
    risks_html = "".join(f'<li style="color:#f87171;padding:4px 0;">{r}</li>' for r in summary["risks"]) or '<li style="color:#64748b;">No risks detected</li>'
    opps_html = "".join(f'<li style="color:#fbbf24;padding:4px 0;">{o}</li>' for o in summary["opportunities"]) or '<li style="color:#64748b;">No new opportunities</li>'
    recs_html = "".join(f'<li style="color:#818cf8;padding:4px 0;">{r}</li>' for r in summary["recommendations"]) or '<li style="color:#64748b;">No action items</li>'

    # City ranking table rows
    sorted_cities = sorted(current_metrics["city_best"].items(), key=lambda x: x[1].get("priority_score", 0), reverse=True)
    city_rows = ""
    for i, (c, cb) in enumerate(sorted_cities[:10]):
        cat = cb.get("category", "weak")
        cat_color = {"high_performer": "#2dd4bf", "above_average": "#5eead4", "below_average": "#fbbf24", "weak": "#f87171"}.get(cat, "#64748b")
        city_rows += f'<tr style="border-bottom:1px solid #1e293b;"><td style="padding:8px;color:#e2e8f0;">{i+1}</td><td style="padding:8px;color:#e2e8f0;font-weight:600;">{c}</td><td style="padding:8px;color:{cat_color};">{cb["variant"]}</td><td style="padding:8px;color:{cat_color};font-weight:700;">{cb["cvr"]}%</td><td style="padding:8px;color:{cat_color};">{cb.get("performance_ratio", 0)}x</td><td style="padding:8px;color:{cat_color};">{cat.replace("_", " ").title()}</td></tr>'

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
    <body style="margin:0;padding:0;background-color:#020617;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#020617;padding:40px 20px;">
        <tr><td align="center">
          <table width="600" cellpadding="0" cellspacing="0" style="background-color:#0f172a;border-radius:16px;border:1px solid #1e293b;">
            <tr><td style="background:linear-gradient(135deg,#0d9488,#6366f1);padding:28px 24px;text-align:center;border-radius:16px 16px 0 0;">
              <h1 style="color:#fff;font-size:20px;margin:0 0 4px;">NISCHINT GEO Intelligence</h1>
              <p style="color:rgba(255,255,255,0.8);font-size:13px;margin:0;">Weekly Performance Digest — {week_start.strftime('%b %d')} to {week_end.strftime('%b %d, %Y')}</p>
            </td></tr>
            <tr><td style="padding:24px;">
              <p style="color:#94a3b8;font-size:13px;margin:0 0 8px;">Network Avg CVR: <strong style="color:#2dd4bf;">{current_metrics['global_avg']:.1f}%</strong> &nbsp;|&nbsp; Cities tracked: <strong style="color:#e2e8f0;">{len(current_metrics['city_best'])}</strong></p>

              <h2 style="color:#2dd4bf;font-size:15px;margin:20px 0 8px;">Highlights</h2>
              <ul style="margin:0;padding-left:20px;font-size:13px;line-height:1.8;">{highlights_html}</ul>

              <h2 style="color:#f87171;font-size:15px;margin:20px 0 8px;">Risks</h2>
              <ul style="margin:0;padding-left:20px;font-size:13px;line-height:1.8;">{risks_html}</ul>

              <h2 style="color:#fbbf24;font-size:15px;margin:20px 0 8px;">Opportunities</h2>
              <ul style="margin:0;padding-left:20px;font-size:13px;line-height:1.8;">{opps_html}</ul>

              <h2 style="color:#818cf8;font-size:15px;margin:20px 0 8px;">Recommendations</h2>
              <ul style="margin:0;padding-left:20px;font-size:13px;line-height:1.8;">{recs_html}</ul>

              <h2 style="color:#e2e8f0;font-size:15px;margin:24px 0 8px;">City Priority Ranking</h2>
              <table width="100%" cellpadding="0" cellspacing="0" style="font-size:12px;border-collapse:collapse;">
                <tr style="border-bottom:1px solid #334155;">
                  <th style="padding:8px;color:#64748b;text-align:left;">#</th>
                  <th style="padding:8px;color:#64748b;text-align:left;">City</th>
                  <th style="padding:8px;color:#64748b;text-align:left;">Variant</th>
                  <th style="padding:8px;color:#64748b;text-align:left;">CVR</th>
                  <th style="padding:8px;color:#64748b;text-align:left;">vs Avg</th>
                  <th style="padding:8px;color:#64748b;text-align:left;">Category</th>
                </tr>
                {city_rows}
              </table>
            </td></tr>
            <tr><td style="background-color:#0b1120;padding:16px 24px;text-align:center;border-top:1px solid #1e293b;border-radius:0 0 16px 16px;">
              <p style="color:#475569;font-size:11px;margin:0;">NISCHINT GEO Intelligence — Automated Weekly Report</p>
              <p style="color:#334155;font-size:10px;margin:4px 0 0;">View full dashboard: <a href="https://nischint.care/admin/geo" style="color:#6366f1;">nischint.care/admin/geo</a></p>
            </td></tr>
          </table>
        </td></tr>
      </table>
    </body></html>"""


async def generate_weekly_digest(db: AsyncSession):
    """Generate the weekly GEO intelligence digest. Called by scheduler or manually."""
    await _ensure_report_table(db)

    now = datetime.now(timezone.utc)
    # Current week = last 7 days, previous week = 7-14 days ago
    curr_end = now
    curr_start = now - timedelta(days=7)
    prev_end = curr_start
    prev_start = curr_start - timedelta(days=7)

    # Check for duplicate report this week
    week_start_date = curr_start.date()
    dup = await db.execute(
        text("SELECT id FROM geo_weekly_reports WHERE week_start = :ws"),
        {"ws": week_start_date},
    )
    if dup.fetchone():
        logger.info(f"[GEO_DIGEST] Report already exists for week starting {week_start_date} — skipping")
        return {"status": "duplicate", "week_start": str(week_start_date)}

    # Get metrics for both weeks
    current = await _get_week_metrics(db, curr_start, curr_end)
    previous = await _get_week_metrics(db, prev_start, prev_end)

    # Compare and generate summary
    summary = _compare_weeks(current, previous)

    # Top cities sorted by priority
    top_cities = sorted(
        [{"city": c, **cb} for c, cb in current["city_best"].items()],
        key=lambda x: x.get("priority_score", 0),
        reverse=True,
    )

    # Top variants
    top_variants = sorted(
        [{"variant": v, **d} for v, d in current["variant_totals"].items()],
        key=lambda x: x["cvr"],
        reverse=True,
    )

    # Store report
    report_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO geo_weekly_reports (id, week_start, week_end, summary_json, top_cities, top_variants, city_benchmarking, global_avg_cvr, email_sent, created_at)
            VALUES (:id, :ws, :we, CAST(:summary AS jsonb), CAST(:tc AS jsonb), CAST(:tv AS jsonb), CAST(:cb AS jsonb), :avg, :sent, :now)
        """),
        {
            "id": report_id,
            "ws": week_start_date,
            "we": curr_end.date(),
            "summary": json.dumps(summary),
            "tc": json.dumps(top_cities),
            "tv": json.dumps(top_variants),
            "cb": json.dumps(top_cities),
            "avg": current["global_avg"],
            "sent": False,
            "now": now,
        },
    )
    await db.commit()

    # Send email
    email_sent = False
    try:
        from app.services.email_service import send_email
        html = _build_email_html(summary, current, curr_start, curr_end)
        email_sent = send_email(DIGEST_RECIPIENT, f"GEO Weekly Digest — {curr_start.strftime('%b %d')} to {curr_end.strftime('%b %d')}", html)
        if email_sent:
            await db.execute(text("UPDATE geo_weekly_reports SET email_sent = TRUE WHERE id = :id"), {"id": report_id})
            await db.commit()
            logger.info(f"[GEO_DIGEST] Email sent to {DIGEST_RECIPIENT}")
        else:
            logger.warning(f"[GEO_DIGEST] Email send failed for {DIGEST_RECIPIENT}")
    except (SQLAlchemyError, OSError, RuntimeError) as e:
        # Compensating action: `email_sent` defaults to False and is
        # the state-flag the next weekly digest cycle reads. A failure
        # here means the digest row is persisted with `email_sent=False`
        # → next Friday's cycle (or a manual retry endpoint) picks it
        # up. No DLQ needed; the schema IS the queue.
        logger.error(
            "geo_digest_email_failed",
            extra={
                "event":      "geo_digest_email_failed",
                "report_id":  report_id,
                "recipient":  DIGEST_RECIPIENT,
                "error_type": type(e).__name__,
            },
        )

    logger.info(f"[GEO_DIGEST] Weekly report generated: {report_id}, highlights={len(summary['highlights'])}, risks={len(summary['risks'])}")

    return {
        "status": "ok",
        "report_id": report_id,
        "week_start": str(week_start_date),
        "week_end": str(curr_end.date()),
        "summary": summary,
        "top_cities": top_cities[:10],
        "top_variants": top_variants,
        "global_avg_cvr": current["global_avg"],
        "email_sent": email_sent,
    }


async def get_weekly_reports(db: AsyncSession, limit: int = 12):
    """Get historical weekly reports."""
    await _ensure_report_table(db)
    rows = await db.execute(
        text("""
            SELECT id, week_start, week_end, summary_json, top_cities, top_variants, global_avg_cvr, email_sent, created_at
            FROM geo_weekly_reports
            ORDER BY week_start DESC LIMIT :lim
        """),
        {"lim": limit},
    )
    return [
        {
            "id": str(r[0]),
            "week_start": str(r[1]),
            "week_end": str(r[2]),
            "summary": r[3] if isinstance(r[3], dict) else json.loads(r[3]) if r[3] else {},
            "top_cities": r[4] if isinstance(r[4], list) else json.loads(r[4]) if r[4] else [],
            "top_variants": r[5] if isinstance(r[5], list) else json.loads(r[5]) if r[5] else [],
            "global_avg_cvr": r[6],
            "email_sent": r[7],
            "created_at": r[8].isoformat() if r[8] else None,
        }
        for r in rows.fetchall()
    ]


def start_geo_digest_scheduler():
    """Register the weekly GEO digest job — Monday 9AM IST (3:30 AM UTC)."""
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        async def _run():
            from app.api.deps import get_db_session
            async for session in get_db_session():
                await generate_weekly_digest(session)

        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            _run,
            CronTrigger(day_of_week="mon", hour=3, minute=30),
            id="geo_weekly_digest",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("[GEO_DIGEST] Scheduler registered — runs every Monday 3:30 UTC (9:00 AM IST)")
    except ImportError:
        logger.warning("[GEO_DIGEST] apscheduler not available — weekly digest disabled")
    except Exception as e:
        logger.error(f"[GEO_DIGEST] Scheduler setup failed: {e}")
