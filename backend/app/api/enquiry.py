# Public Enquiry API — Lead capture + n8n webhook forwarding
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db_session
from app.core.rate_limiter import limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/enquiry", tags=["Enquiry"])

N8N_WEBHOOK_URL = "https://foodflix.app.n8n.cloud/webhook/enquiry"


class EnquiryRequest(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    message: Optional[str] = None
    source: Optional[str] = "website"
    blog_slug: Optional[str] = None
    query: Optional[str] = None


async def forward_to_n8n(payload: dict):
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(N8N_WEBHOOK_URL, json=payload)
            logger.info(f"Enquiry forwarded to n8n: {payload.get('email')} status={resp.status_code}")
    except Exception as e:
        logger.warning(f"[N8N ERROR] Failed to forward enquiry: {e}")


@router.post("")
@limiter.limit("20/hour")
async def submit_enquiry(
    request: Request,
    req: EnquiryRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Public enquiry endpoint — no auth required. Saves to DB + forwards to n8n."""
    # Ensure table exists
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS enquiries (
            id SERIAL PRIMARY KEY,
            name TEXT,
            email TEXT,
            phone TEXT,
            message TEXT,
            source TEXT DEFAULT 'website',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """))

    # Save to DB first (no lead loss)
    await session.execute(text("""
        INSERT INTO enquiries (name, email, phone, message, source, created_at)
        VALUES (:name, :email, :phone, :message, :source, :now)
    """), {
        "name": req.name,
        "email": req.email,
        "phone": req.phone,
        "message": req.message,
        "source": req.source,
        "now": datetime.now(timezone.utc),
    })
    await session.commit()

    # Forward to n8n webhook
    await forward_to_n8n({
        "name": req.name,
        "email": req.email,
        "phone": req.phone,
        "message": req.message,
        "source": req.source,
    })

    # Log RAG insight for lead tracking
    try:
        from app.services.rag_insight_service import log_insight
        await log_insight(session, {
            "event_type": "lead_created",
            "query": req.query,
            "blog_slug": req.blog_slug,
            "source": req.source or "website",
            "metadata": {"name": req.name, "email": req.email},
        })
    except Exception as e:
        logger.warning(f"Insight logging failed (non-blocking): {e}")

    return {"status": "ok", "message": "Enquiry received. We'll get back to you shortly."}
