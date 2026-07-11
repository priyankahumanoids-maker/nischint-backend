"""
NISCHINT Revenue OS — AI-driven lead capture, scoring, follow-up, and revenue intelligence.
Single unified backend for all lead sources: website, WhatsApp, ads, social, DMs.
"""
import logging
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel, model_validator
from typing import Optional, Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db_session
from app.core.rate_limiter import limiter

import json as json_lib

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Revenue OS"])

N8N_WEBHOOK_URL = "https://foodflix.app.n8n.cloud/webhook/enquiry"

# ──────────────────────────────────────────────
# DB SCHEMA INIT
# ──────────────────────────────────────────────

LEADS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS leads (
    lead_id UUID PRIMARY KEY,
    name TEXT,
    email TEXT,
    phone TEXT,
    message TEXT,

    emotion TEXT,
    intent TEXT,
    urgency_score INT,
    priority TEXT,
    pain_type TEXT,
    life_risk_flag BOOLEAN DEFAULT FALSE,

    source TEXT,
    channel TEXT,
    utm_source TEXT,
    utm_campaign TEXT,
    utm_content TEXT,

    device TEXT,
    location TEXT,
    page_url TEXT,
    referrer TEXT,

    status TEXT DEFAULT 'new',
    followup_stage INT DEFAULT 0,
    replied BOOLEAN DEFAULT FALSE,
    closed_status TEXT,

    conversion_value NUMERIC,
    conversion_time TIMESTAMPTZ,
    response_time INT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
"""

LEAD_EVENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS lead_events (
    event_id UUID PRIMARY KEY,
    lead_id UUID REFERENCES leads(lead_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""

INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);",
    "CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone);",
    "CREATE INDEX IF NOT EXISTS idx_leads_source ON leads(source);",
    "CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);",
    "CREATE INDEX IF NOT EXISTS idx_leads_created ON leads(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_lead_events_lead_id ON lead_events(lead_id);",
    "CREATE INDEX IF NOT EXISTS idx_lead_events_type ON lead_events(event_type);",
]


async def ensure_tables(session: AsyncSession):
    """Idempotent table creation."""
    await session.execute(text(LEADS_TABLE_SQL))
    await session.execute(text(LEAD_EVENTS_TABLE_SQL))
    for idx in INDEXES_SQL:
        await session.execute(text(idx))
    await session.commit()


# ──────────────────────────────────────────────
# EVENT LOGGING
# ──────────────────────────────────────────────

async def log_event(session: AsyncSession, lead_id: str, event_type: str, metadata: dict | None = None):
    """Log a lifecycle event for a lead."""
    event_id = str(uuid.uuid4())
    await session.execute(text("""
        INSERT INTO lead_events (event_id, lead_id, event_type, metadata, created_at)
        VALUES (:eid, :lid, :etype, CAST(:meta AS jsonb), :now)
    """), {
        "eid": event_id,
        "lid": lead_id,
        "etype": event_type,
        "meta": json_lib.dumps(metadata or {}),
        "now": datetime.now(timezone.utc),
    })
    logger.info(f"[LEAD_EVENT] {event_type} for lead={lead_id}")


# ──────────────────────────────────────────────
# N8N FORWARDING
# ──────────────────────────────────────────────

async def forward_to_n8n(payload: dict):
    """Non-blocking async forward to n8n webhook. 5s timeout, log on failure."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(N8N_WEBHOOK_URL, json=payload)
            logger.info(f"[N8N_FORWARD] lead={payload.get('lead_id')} status={resp.status_code}")
    except Exception as e:
        logger.warning(f"[N8N_FORWARD_FAIL] lead={payload.get('lead_id')} error={e}")


# ──────────────────────────────────────────────
# MODELS
# ──────────────────────────────────────────────

class EnquiryRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    message: Optional[str] = None

    source: Optional[str] = "website"
    channel: Optional[str] = "form"
    page: Optional[str] = None
    intent: Optional[str] = None

    utm_source: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_content: Optional[str] = None

    device: Optional[str] = None
    location: Optional[str] = None

    page_url: Optional[str] = None
    referrer: Optional[str] = None

    # RAG insight tracking
    blog_slug: Optional[str] = None
    query: Optional[str] = None

    timestamp: Optional[str] = None
    raw_payload: Optional[dict] = None

    @model_validator(mode="after")
    def require_phone_or_email(self):
        if self.source == "seo_page":
            return self
        if not self.phone and not self.email:
            raise ValueError("At least one of phone or email is required")
        return self


class LeadUpdateRequest(BaseModel):
    lead_id: str
    replied: Optional[bool] = None
    status: Optional[str] = None
    closed_status: Optional[str] = None
    followup_stage: Optional[int] = None
    conversion_value: Optional[float] = None
    response_time: Optional[int] = None


class EventRequest(BaseModel):
    lead_id: str
    event_type: str
    metadata: Optional[dict] = None


# ──────────────────────────────────────────────
# PHASE 1 — UNIFIED LEAD CAPTURE
# ──────────────────────────────────────────────

@router.post("/enquiry")
@limiter.limit("60/minute")
async def capture_enquiry(
    request: Request,
    req: EnquiryRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Single unified entry point for all leads. Stores in DB + forwards to n8n."""
    await ensure_tables(session)

    # Idempotency: skip duplicate if same email+phone+message within 5 minutes
    dedup = await session.execute(text("""
        SELECT lead_id FROM leads
        WHERE (email = :email OR phone = :phone)
          AND message = :message
          AND created_at > NOW() - INTERVAL '5 minutes'
        LIMIT 1
    """), {"email": req.email, "phone": req.phone, "message": req.message})
    existing = dedup.fetchone()
    if existing:
        return {
            "status": "duplicate",
            "lead_id": str(existing.lead_id),
            "message": "Lead already captured.",
        }

    lead_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    await session.execute(text("""
        INSERT INTO leads (
            lead_id, name, email, phone, message,
            source, channel, utm_source, utm_campaign, utm_content,
            device, location, page_url, referrer,
            status, followup_stage, replied, created_at, updated_at
        ) VALUES (
            :lead_id, :name, :email, :phone, :message,
            :source, :channel, :utm_source, :utm_campaign, :utm_content,
            :device, :location, :page_url, :referrer,
            'new', 0, FALSE, :now, :now
        )
    """), {
        "lead_id": lead_id,
        "name": req.name,
        "email": req.email,
        "phone": req.phone,
        "message": req.message,
        "source": req.source,
        "channel": req.channel,
        "utm_source": req.utm_source,
        "utm_campaign": req.utm_campaign,
        "utm_content": req.utm_content,
        "device": req.device,
        "location": req.location,
        "page_url": req.page_url,
        "referrer": req.referrer,
        "now": now,
    })

    # Log creation event
    await log_event(session, lead_id, "lead_created", {
        "source": req.source,
        "channel": req.channel,
    })

    await session.commit()

    # Forward to n8n (non-blocking, don't fail if n8n is down)
    await forward_to_n8n({
        "lead_id": lead_id,
        "name": req.name,
        "email": req.email,
        "phone": req.phone,
        "message": req.message,
        "source": req.source,
        "channel": req.channel,
        "timestamp": now.isoformat(),
    })

    # RAG insight tracking — log lead_created event
    try:
        from app.services.rag_insight_service import log_insight as log_rag_insight
        await log_rag_insight(session, {
            "event_type": "lead_created",
            "query": req.query,
            "blog_slug": req.blog_slug,
            "lead_id": lead_id,
            "source": req.source or "website",
            "metadata": {"name": req.name, "email": req.email, "channel": req.channel},
        })
    except Exception as e:
        logger.warning(f"RAG insight logging failed (non-blocking): {e}")

    return {
        "status": "ok",
        "lead_id": lead_id,
        "message": "Enquiry received. We'll get back to you shortly.",
    }


# ──────────────────────────────────────────────
# PHASE 2 — REPLY + STATUS TRACKING
# ──────────────────────────────────────────────

@router.post("/lead/update")
@limiter.limit("60/minute")
async def update_lead(
    request: Request,
    req: LeadUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Update lead status, reply flag, closed status, or conversion data."""
    # Verify lead exists
    check = await session.execute(
        text("SELECT lead_id FROM leads WHERE lead_id = :lid"),
        {"lid": req.lead_id},
    )
    if not check.fetchone():
        raise HTTPException(status_code=404, detail="Lead not found")

    # Build dynamic update
    updates = []
    params: dict[str, Any] = {"lid": req.lead_id, "now": datetime.now(timezone.utc)}

    if req.replied is not None:
        updates.append("replied = :replied")
        params["replied"] = req.replied
    if req.status is not None:
        updates.append("status = :status")
        params["status"] = req.status
    if req.closed_status is not None:
        updates.append("closed_status = :closed_status")
        params["closed_status"] = req.closed_status
    if req.followup_stage is not None:
        updates.append("followup_stage = :followup_stage")
        params["followup_stage"] = req.followup_stage
    if req.conversion_value is not None:
        updates.append("conversion_value = :conversion_value")
        params["conversion_value"] = req.conversion_value
        updates.append("conversion_time = :now")
    if req.response_time is not None:
        updates.append("response_time = :response_time")
        params["response_time"] = req.response_time

    if not updates:
        return {"status": "no_change", "lead_id": req.lead_id}

    updates.append("updated_at = :now")
    sql = f"UPDATE leads SET {', '.join(updates)} WHERE lead_id = :lid"
    await session.execute(text(sql), params)

    # Log update event
    await log_event(session, req.lead_id, "lead_updated", {
        "status": req.status,
        "replied": req.replied,
        "closed_status": req.closed_status,
    })

    await session.commit()

    return {"status": "ok", "lead_id": req.lead_id, "message": "Lead updated."}


@router.post("/events")
@limiter.limit("120/minute")
async def receive_event(
    request: Request,
    req: EventRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Webhook receiver for external events (Twilio callbacks, WhatsApp replies, email opens)."""
    REPLY_EVENTS = {"whatsapp_reply", "email_reply", "call_answered", "user_replied"}

    # Log the event
    await log_event(session, req.lead_id, req.event_type, req.metadata)

    # Auto-update replied flag for reply-type events
    if req.event_type in REPLY_EVENTS:
        now = datetime.now(timezone.utc)
        # Calculate response_time if this is the first reply
        await session.execute(text("""
            UPDATE leads
            SET replied = TRUE,
                status = CASE WHEN status = 'new' THEN 'engaged' ELSE status END,
                response_time = COALESCE(response_time,
                    EXTRACT(EPOCH FROM (:now - created_at))::INT),
                updated_at = :now
            WHERE lead_id = :lid
        """), {"lid": req.lead_id, "now": now})

    await session.commit()

    return {"status": "ok", "event_type": req.event_type, "lead_id": req.lead_id}


# ──────────────────────────────────────────────
# PHASE 3 — REVENUE METRICS
# ──────────────────────────────────────────────

@router.get("/revenue-metrics")
async def revenue_metrics(
    session: AsyncSession = Depends(get_db_session),
):
    """Revenue intelligence dashboard metrics."""
    await ensure_tables(session)

    # Total leads
    total = (await session.execute(text("SELECT COUNT(*) FROM leads"))).scalar() or 0

    # Conversions (closed_status = 'won')
    conversions = (await session.execute(
        text("SELECT COUNT(*) FROM leads WHERE closed_status = 'won'")
    )).scalar() or 0

    # Revenue
    revenue = (await session.execute(
        text("SELECT COALESCE(SUM(conversion_value), 0) FROM leads WHERE closed_status = 'won'")
    )).scalar() or 0

    # Conversion rate
    conversion_rate = round((conversions / total * 100), 2) if total > 0 else 0

    # Avg response time (seconds)
    avg_response = (await session.execute(
        text("SELECT COALESCE(AVG(response_time), 0) FROM leads WHERE response_time IS NOT NULL")
    )).scalar() or 0

    # Replied rate
    replied_count = (await session.execute(
        text("SELECT COUNT(*) FROM leads WHERE replied = TRUE")
    )).scalar() or 0

    # Emotion breakdown
    emotion_rows = (await session.execute(
        text("SELECT emotion, COUNT(*) as cnt FROM leads WHERE emotion IS NOT NULL GROUP BY emotion ORDER BY cnt DESC")
    )).fetchall()
    emotion_breakdown = {r.emotion: r.cnt for r in emotion_rows}

    # Channel breakdown
    channel_rows = (await session.execute(
        text("SELECT channel, COUNT(*) as cnt FROM leads GROUP BY channel ORDER BY cnt DESC")
    )).fetchall()
    channel_breakdown = {r.channel: r.cnt for r in channel_rows}

    # Source breakdown
    source_rows = (await session.execute(
        text("SELECT source, COUNT(*) as cnt FROM leads GROUP BY source ORDER BY cnt DESC")
    )).fetchall()
    source_breakdown = {r.source: r.cnt for r in source_rows}

    # Status breakdown
    status_rows = (await session.execute(
        text("SELECT status, COUNT(*) as cnt FROM leads GROUP BY status ORDER BY cnt DESC")
    )).fetchall()
    status_breakdown = {r.status: r.cnt for r in status_rows}

    return {
        "total_leads": total,
        "conversions": conversions,
        "revenue": float(revenue),
        "conversion_rate": conversion_rate,
        "avg_response_time_seconds": round(float(avg_response)),
        "replied_count": replied_count,
        "reply_rate": round((replied_count / total * 100), 2) if total > 0 else 0,
        "emotion_breakdown": emotion_breakdown,
        "channel_breakdown": channel_breakdown,
        "source_breakdown": source_breakdown,
        "status_breakdown": status_breakdown,
    }
