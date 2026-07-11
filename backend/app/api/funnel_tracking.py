"""
Funnel Tracking — Conversion event ingestion and metrics for SEO pages.
Tracks: page_view → cta_click → modal_open → lead_submit → whatsapp_redirect
"""
import logging
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db_session
from app.core.rate_limiter import limiter

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Funnel Tracking"])

FUNNEL_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS funnel_events (
    id UUID PRIMARY KEY,
    event TEXT NOT NULL,
    page TEXT,
    session_id TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""

FUNNEL_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_funnel_event ON funnel_events(event);",
    "CREATE INDEX IF NOT EXISTS idx_funnel_page ON funnel_events(page);",
    "CREATE INDEX IF NOT EXISTS idx_funnel_session ON funnel_events(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_funnel_created ON funnel_events(created_at);",
]

_tables_ready = False


async def ensure_table(session: AsyncSession):
    global _tables_ready
    if _tables_ready:
        return
    await session.execute(text(FUNNEL_TABLE_SQL))
    for idx in FUNNEL_INDEXES_SQL:
        await session.execute(text(idx))
    await session.commit()
    _tables_ready = True


# ── Models ──

class FunnelEvent(BaseModel):
    event: str
    page: Optional[str] = None
    session_id: Optional[str] = None
    timestamp: Optional[float] = None
    metadata: Optional[dict] = None


class FunnelBatch(BaseModel):
    events: List[FunnelEvent]


# ── Endpoints ──

@router.post("/track")
@limiter.limit("120/minute")
async def track_event(
    request: Request,
    req: FunnelEvent,
    session: AsyncSession = Depends(get_db_session),
):
    """Single funnel event ingestion."""
    await ensure_table(session)
    event_id = str(uuid.uuid4())
    await session.execute(text("""
        INSERT INTO funnel_events (id, event, page, session_id, metadata, created_at)
        VALUES (:id, :event, :page, :sid, CAST(:meta AS jsonb), :now)
    """), {
        "id": event_id,
        "event": req.event,
        "page": req.page,
        "sid": req.session_id,
        "meta": "{}",
        "now": datetime.now(timezone.utc),
    })
    return {"status": "ok"}


@router.post("/track/batch")
@limiter.limit("30/minute")
async def track_batch(
    request: Request,
    req: FunnelBatch,
    session: AsyncSession = Depends(get_db_session),
):
    """Batch funnel event ingestion."""
    await ensure_table(session)
    for ev in req.events:
        event_id = str(uuid.uuid4())
        await session.execute(text("""
            INSERT INTO funnel_events (id, event, page, session_id, metadata, created_at)
            VALUES (:id, :event, :page, :sid, CAST(:meta AS jsonb), :now)
        """), {
            "id": event_id,
            "event": ev.event,
            "page": ev.page,
            "sid": ev.session_id,
            "meta": "{}",
            "now": datetime.now(timezone.utc),
        })
    return {"status": "ok", "count": len(req.events)}


@router.get("/funnel-metrics")
async def funnel_metrics(
    days: int = 7,
    page: Optional[str] = None,
    session: AsyncSession = Depends(get_db_session),
):
    """Funnel conversion metrics with optional page filter."""
    await ensure_table(session)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    page_filter = "AND page = :page" if page else ""
    params = {"since": since}
    if page:
        params["page"] = page

    # Event counts
    counts = {}
    for event_name in ["page_view", "cta_click", "modal_open", "lead_submit", "whatsapp_redirect"]:
        row = await session.execute(text(f"""
            SELECT COUNT(*) FROM funnel_events
            WHERE event = :ev AND created_at >= :since {page_filter}
        """), {**params, "ev": event_name})
        counts[event_name] = row.scalar() or 0

    pv = counts["page_view"] or 1  # avoid div-by-zero

    # Per-page breakdown
    page_rows = await session.execute(text(f"""
        SELECT page, event, COUNT(*) as cnt
        FROM funnel_events
        WHERE created_at >= :since AND page IS NOT NULL
        GROUP BY page, event
        ORDER BY page, cnt DESC
    """), {"since": since})
    by_page = {}
    for r in page_rows.fetchall():
        by_page.setdefault(r.page, {})[r.event] = r.cnt

    # Unique sessions
    sessions_row = await session.execute(text(f"""
        SELECT COUNT(DISTINCT session_id) FROM funnel_events
        WHERE created_at >= :since {page_filter}
    """), params)
    unique_sessions = sessions_row.scalar() or 0

    # Daily trend (last N days)
    daily_rows = await session.execute(text(f"""
        SELECT DATE(created_at) as day, event, COUNT(*) as cnt
        FROM funnel_events
        WHERE created_at >= :since {page_filter}
        GROUP BY day, event
        ORDER BY day
    """), params)
    daily = {}
    for r in daily_rows.fetchall():
        day_str = str(r.day)
        daily.setdefault(day_str, {})[r.event] = r.cnt

    return {
        "period_days": days,
        "filter_page": page,
        "funnel": {
            "page_views": counts["page_view"],
            "cta_clicks": counts["cta_click"],
            "modal_opens": counts["modal_open"],
            "leads": counts["lead_submit"],
            "whatsapp_redirects": counts["whatsapp_redirect"],
        },
        "conversion_rates": {
            "view_to_click": round(counts["cta_click"] / pv * 100, 1),
            "click_to_modal": round(counts["modal_open"] / max(counts["cta_click"], 1) * 100, 1),
            "modal_to_lead": round(counts["lead_submit"] / max(counts["modal_open"], 1) * 100, 1),
            "lead_to_whatsapp": round(counts["whatsapp_redirect"] / max(counts["lead_submit"], 1) * 100, 1),
            "overall": round(counts["lead_submit"] / pv * 100, 1),
        },
        "unique_sessions": unique_sessions,
        "by_page": by_page,
        "daily_trend": daily,
    }
