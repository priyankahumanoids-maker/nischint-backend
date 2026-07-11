"""
NISCHINT RAG Insights Service — Tracks Query → Blog → CTA → Lead → Conversion lifecycle.
Powers AI learning loop, SEO optimization, and revenue intelligence.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_table_ready = False

SCHEMA_SQL = [
    """CREATE TABLE IF NOT EXISTS rag_insights (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        query TEXT,
        persona TEXT,
        emotion TEXT,
        blog_id TEXT,
        blog_slug TEXT,
        event_type TEXT,
        lead_id TEXT,
        conversion BOOLEAN DEFAULT FALSE,
        score INT,
        priority TEXT,
        source TEXT,
        metadata JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ DEFAULT NOW()
    );""",
    "CREATE INDEX IF NOT EXISTS rag_insights_query_idx ON rag_insights(query);",
    "CREATE INDEX IF NOT EXISTS rag_insights_blog_idx ON rag_insights(blog_slug);",
    "CREATE INDEX IF NOT EXISTS rag_insights_event_idx ON rag_insights(event_type);",
    "CREATE INDEX IF NOT EXISTS rag_insights_created_idx ON rag_insights(created_at DESC);",
]


async def ensure_table(session: AsyncSession):
    global _table_ready
    if _table_ready:
        return
    for sql in SCHEMA_SQL:
        try:
            await session.execute(text(sql))
        except Exception as e:
            logger.warning(f"Insight schema statement skipped: {e}")
            await session.rollback()
    await session.commit()
    _table_ready = True


async def log_insight(session: AsyncSession, data: dict) -> str:
    """Log a single RAG insight event. Returns the insight ID."""
    await ensure_table(session)

    insight_id = str(uuid.uuid4())
    meta = data.get("metadata") or {}

    await session.execute(text("""
        INSERT INTO rag_insights
            (id, query, persona, emotion, blog_id, blog_slug, event_type,
             lead_id, conversion, score, priority, source, metadata, created_at)
        VALUES
            (:id, :query, :persona, :emotion, :blog_id, :blog_slug, :event_type,
             :lead_id, :conversion, :score, :priority, :source,
             CAST(:metadata AS jsonb), :created_at)
    """), {
        "id": insight_id,
        "query": data.get("query"),
        "persona": data.get("persona"),
        "emotion": data.get("emotion"),
        "blog_id": data.get("blog_id"),
        "blog_slug": data.get("blog_slug"),
        "event_type": data.get("event_type", "unknown"),
        "lead_id": data.get("lead_id"),
        "conversion": data.get("conversion", False),
        "score": data.get("score"),
        "priority": data.get("priority"),
        "source": data.get("source"),
        "metadata": json.dumps(meta),
        "created_at": datetime.now(timezone.utc),
    })
    await session.commit()

    logger.info(f"RAG insight logged: event={data.get('event_type')}, query={str(data.get('query', ''))[:50]}")
    return insight_id


async def get_insights(
    session: AsyncSession,
    event_type: Optional[str] = None,
    query: Optional[str] = None,
    blog_slug: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Retrieve insights with optional filters."""
    await ensure_table(session)

    conditions = []
    params: dict = {"lim": limit, "off": offset}

    if event_type:
        conditions.append("event_type = :event_type")
        params["event_type"] = event_type
    if query:
        conditions.append("query ILIKE :query")
        params["query"] = f"%{query}%"
    if blog_slug:
        conditions.append("blog_slug = :blog_slug")
        params["blog_slug"] = blog_slug
    if source:
        conditions.append("source = :source")
        params["source"] = source

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # Count total
    count_row = await session.execute(text(f"SELECT COUNT(*) FROM rag_insights {where}"), params)
    total = count_row.scalar() or 0

    # Fetch rows
    rows = await session.execute(text(f"""
        SELECT id, query, persona, emotion, blog_id, blog_slug, event_type,
               lead_id, conversion, score, priority, source, metadata, created_at
        FROM rag_insights
        {where}
        ORDER BY created_at DESC
        LIMIT :lim OFFSET :off
    """), params)

    results = []
    for row in rows.fetchall():
        results.append({
            "id": str(row.id),
            "query": row.query,
            "persona": row.persona,
            "emotion": row.emotion,
            "blog_id": row.blog_id,
            "blog_slug": row.blog_slug,
            "event_type": row.event_type,
            "lead_id": row.lead_id,
            "conversion": row.conversion,
            "score": row.score,
            "priority": row.priority,
            "source": row.source,
            "metadata": row.metadata if isinstance(row.metadata, dict) else {},
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })

    return {"total": total, "results": results, "limit": limit, "offset": offset}


async def get_top_performing_queries(session: AsyncSession, limit: int = 10) -> list[dict]:
    """Get queries ranked by conversion funnel progression."""
    await ensure_table(session)

    rows = await session.execute(text("""
        SELECT
            query,
            COUNT(*) FILTER (WHERE event_type = 'blog_generated') AS generated,
            COUNT(*) FILTER (WHERE event_type = 'cta_clicked') AS cta_clicks,
            COUNT(*) FILTER (WHERE event_type = 'lead_created') AS leads,
            COUNT(*) FILTER (WHERE conversion = TRUE) AS conversions,
            COUNT(*) AS total_events
        FROM rag_insights
        WHERE query IS NOT NULL
        GROUP BY query
        ORDER BY leads DESC, cta_clicks DESC, generated DESC
        LIMIT :lim
    """), {"lim": limit})

    results = []
    for row in rows.fetchall():
        results.append({
            "query": row.query,
            "generated": row.generated,
            "cta_clicks": row.cta_clicks,
            "leads": row.leads,
            "conversions": row.conversions,
            "total_events": row.total_events,
        })

    return results
