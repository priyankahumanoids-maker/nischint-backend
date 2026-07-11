# Pilot Signup API — Lead capture and notification
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends
from app.api.deps import get_db_session
from app.core.rate_limiter import limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pilot", tags=["Pilot Signup"])

N8N_WEBHOOK_URL = "https://foodflix.app.n8n.cloud/webhook/enquiry"


async def forward_to_n8n(lead_data: dict):
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(N8N_WEBHOOK_URL, json=lead_data)
            logger.info(f"Lead forwarded to n8n: {lead_data.get('email')}")
    except Exception as e:
        logger.warning(f"[N8N ERROR] Failed to forward lead: {e}")


class PilotSignupRequest(BaseModel):
    institution_name: str
    contact_person: str
    email: str
    phone: Optional[str] = None
    city: Optional[str] = None
    institution_type: Optional[str] = None
    headcount: Optional[str] = None
    message: Optional[str] = None


@router.post("/signup")
@limiter.limit("10/hour")
async def pilot_signup(
    request: Request,
    req: PilotSignupRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Capture pilot signup lead — store in DB + send email notification."""
    # Ensure table exists
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS pilot_leads (
            id SERIAL PRIMARY KEY,
            institution_name TEXT NOT NULL,
            contact_person TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT,
            city TEXT,
            institution_type TEXT,
            headcount TEXT,
            message TEXT,
            status TEXT DEFAULT 'new',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """))

    # Insert lead
    await session.execute(text("""
        INSERT INTO pilot_leads (institution_name, contact_person, email, phone, city, institution_type, headcount, message, created_at)
        VALUES (:inst, :person, :email, :phone, :city, :itype, :hc, :msg, :now)
    """), {
        "inst": req.institution_name,
        "person": req.contact_person,
        "email": req.email,
        "phone": req.phone,
        "city": req.city,
        "itype": req.institution_type,
        "hc": req.headcount,
        "msg": req.message,
        "now": datetime.now(timezone.utc),
    })
    await session.commit()

    # Forward lead to n8n webhook for AI-powered automation
    await forward_to_n8n({
        "name": req.contact_person,
        "email": req.email,
        "phone": req.phone,
        "city": req.city,
        "institution": req.institution_name,
        "institution_type": req.institution_type,
        "headcount": req.headcount,
        "message": req.message,
        "source": "pilot_form",
        "channel": "form",
    })

    # Send email notification
    try:
        from app.services.email_service import send_email
        subject = f"New Pilot Request — Nischint | {req.institution_name}"
        html = f"""
        <div style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto; background: #0f172a; color: #e2e8f0; padding: 32px; border-radius: 12px;">
            <h2 style="color: #2dd4bf; margin-bottom: 24px;">New Pilot Deployment Request</h2>
            <table style="width: 100%; border-collapse: collapse;">
                <tr><td style="padding: 8px 0; color: #94a3b8;">Institution</td><td style="padding: 8px 0; color: #f1f5f9; font-weight: 600;">{req.institution_name}</td></tr>
                <tr><td style="padding: 8px 0; color: #94a3b8;">Contact</td><td style="padding: 8px 0; color: #f1f5f9;">{req.contact_person}</td></tr>
                <tr><td style="padding: 8px 0; color: #94a3b8;">Email</td><td style="padding: 8px 0; color: #f1f5f9;">{req.email}</td></tr>
                <tr><td style="padding: 8px 0; color: #94a3b8;">Phone</td><td style="padding: 8px 0; color: #f1f5f9;">{req.phone or 'N/A'}</td></tr>
                <tr><td style="padding: 8px 0; color: #94a3b8;">City</td><td style="padding: 8px 0; color: #f1f5f9;">{req.city or 'N/A'}</td></tr>
                <tr><td style="padding: 8px 0; color: #94a3b8;">Type</td><td style="padding: 8px 0; color: #f1f5f9;">{req.institution_type or 'N/A'}</td></tr>
                <tr><td style="padding: 8px 0; color: #94a3b8;">Headcount</td><td style="padding: 8px 0; color: #f1f5f9;">{req.headcount or 'N/A'}</td></tr>
                <tr><td style="padding: 8px 0; color: #94a3b8;">Message</td><td style="padding: 8px 0; color: #f1f5f9;">{req.message or 'N/A'}</td></tr>
            </table>
            <hr style="border: 1px solid #1e293b; margin: 24px 0;" />
            <p style="color: #64748b; font-size: 12px;">Nischint AI Safety Infrastructure — Pilot Lead System</p>
        </div>
        """
        for recipient in ["partners@nischint.app", "hello@nischint.app"]:
            send_email(recipient, subject, html)
        logger.info(f"Pilot signup email sent for {req.institution_name}")
    except Exception as e:
        logger.warning(f"Pilot email notification failed: {e}")

    return {
        "status": "success",
        "message": "Thank you for your interest in deploying Nischint. Our team will contact you within 48 hours to schedule a pilot deployment discussion.",
    }


@router.get("/leads")
async def get_pilot_leads(
    session: AsyncSession = Depends(get_db_session),
):
    """Get all pilot leads (admin only in production)."""
    try:
        result = await session.execute(text(
            "SELECT id, institution_name, contact_person, email, phone, city, institution_type, headcount, status, created_at FROM pilot_leads ORDER BY created_at DESC"
        ))
        rows = result.fetchall()
        return {"leads": [
            {
                "id": r.id,
                "institution_name": r.institution_name,
                "contact_person": r.contact_person,
                "email": r.email,
                "phone": r.phone,
                "city": r.city,
                "institution_type": r.institution_type,
                "headcount": r.headcount,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]}
    except Exception:
        return {"leads": []}
