"""
Nischint AI Chatbot — Public-facing conversational AI for the marketing website.
Handles platform questions, safety demos, and lead capture.
Routes general questions to n8n RAG pipeline.
"""
import logging
import os
import uuid
from datetime import datetime, timezone
from json import JSONDecodeError

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, EmailStr
from typing import Optional
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.api.deps import get_db_session
from app.core.rate_limiter import limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chatbot", tags=["AI Chatbot"])

N8N_FAQ_WEBHOOK = "https://foodflix.app.n8n.cloud/webhook/faq-bot"

DEMO_STEPS = [
    {"delay": 0, "message": "Initializing safety monitoring session...", "type": "system"},
    {"delay": 2, "message": "Session active. Monitoring behavioral patterns, location signals, and environmental data.", "type": "system"},
    {"delay": 3, "message": "ANOMALY DETECTED: Unusual route deviation identified. Risk score: 0.34 → 0.58", "type": "warning"},
    {"delay": 3, "message": "AI Safety Brain analyzing behavioral pattern... Extended stop detected in unfamiliar zone.", "type": "warning"},
    {"delay": 2, "message": "ALERT: Risk score escalating. 0.58 → 0.78. Geofence boundary approached.", "type": "alert"},
    {"delay": 2, "message": "Guardian notification dispatched. Response window: 30 seconds.", "type": "system"},
    {"delay": 2, "message": "Command Center alert triggered. Patrol unit notified for Zone Delta.", "type": "alert"},
    {"delay": 3, "message": "Guardian response confirmed. Location verified. Safer route generated.", "type": "success"},
    {"delay": 2, "message": "Risk score normalizing. 0.78 → 0.31. Behavioral pattern stabilized.", "type": "success"},
    {"delay": 2, "message": "Session completed safely. Incident replay generated. AI narrative logged.", "type": "success"},
    {"delay": 1, "message": "This is how Nischint protects in real-time — from detection to resolution in under 30 seconds. Would you like to request a pilot deployment for your institution?", "type": "info"},
]


class ChatMessage(BaseModel):
    session_id: str
    message: str


class LeadCaptureRequest(BaseModel):
    session_id: str
    name: str
    institution: str
    email: str
    city: Optional[str] = None


@router.post("/message")
@limiter.limit("30/minute")
async def chat_message(request: Request, body: ChatMessage):
    """Process a chat message and return AI response."""
    user_msg = body.message.strip().lower()

    # Handle demo trigger
    if "demo" in user_msg and ("run" in user_msg or "safety" in user_msg or "live" in user_msg or "show" in user_msg or "start" in user_msg):
        return {
            "type": "demo",
            "steps": DEMO_STEPS,
            "session_id": body.session_id,
        }

    # Handle city simulation trigger
    if "city" in user_msg and ("simulation" in user_msg or "simulate" in user_msg or "grid" in user_msg):
        return {
            "type": "text",
            "message": "You can watch the City Safety Simulation on our homepage. It demonstrates how Nischint detects, propagates, and resolves safety incidents across an entire city network.\n\nScroll to the 'AI Safety Network Simulation' section on the homepage, or visit /",
            "session_id": body.session_id,
        }

    # Handle lead capture trigger
    if any(kw in user_msg for kw in ["schedule", "pilot", "deploy", "sign up", "signup", "contact sales"]):
        return {
            "type": "lead_prompt",
            "message": "I'd be happy to help you get started. You can:\n\n1. Fill out our pilot request form at /pilot\n2. Email us directly at hello@nischint.app\n3. Share your details here and we'll reach out within 48 hours.\n\nWould you like to share your contact information now?",
            "session_id": body.session_id,
        }

    # Forward to n8n RAG pipeline for general questions
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                N8N_FAQ_WEBHOOK,
                json={"question": body.message, "session_id": body.session_id},
            )
            try:
                rag_result = response.json()
            except (ValueError, JSONDecodeError):
                rag_result = {"answer": None}  # graceful fallback (non-JSON / empty body)
            logger.info(f"n8n RAG response for session {body.session_id}: status={response.status_code}")
            answer = rag_result.get("message") or rag_result.get("answer")
            if not answer:
                # n8n returned non-JSON or empty payload — fall through to canned reply
                raise ValueError("empty n8n payload")
            return {
                "type": rag_result.get("type", "text"),
                "message": answer,
                "session_id": body.session_id,
            }
    except Exception as e:
        logger.error(f"n8n RAG error: {e}")
        return {
            "type": "text",
            "message": "I can help you learn about Nischint's AI Safety Infrastructure. You can ask about our platform capabilities, school safety solutions, corporate safety, or request a pilot deployment. For immediate assistance, email hello@nischint.app.",
            "session_id": body.session_id,
        }


@router.get("/demo-steps")
async def get_demo_steps():
    """Return the safety demo sequence."""
    return {"steps": DEMO_STEPS}


@router.post("/lead")
@limiter.limit("10/hour")
async def capture_lead(
    request: Request,
    body: LeadCaptureRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Capture a lead from the chatbot conversation."""
    try:
        # pilot_leads uses SERIAL id (auto-increment), so don't specify id
        await session.execute(
            text("""
                INSERT INTO pilot_leads (institution_name, contact_person, email, city, created_at)
                VALUES (:inst, :contact, :email, :city, :now)
            """),
            {
                "inst": body.institution,
                "contact": body.name,
                "email": body.email,
                "city": body.city or "",
                "now": datetime.now(timezone.utc),
            },
        )
        await session.commit()

        # Send email notification
        try:
            from app.services.email_service import send_email
            html = f"""
            <h2>New Lead from Nischint AI Chatbot</h2>
            <p><b>Name:</b> {body.name}</p>
            <p><b>Institution:</b> {body.institution}</p>
            <p><b>Email:</b> {body.email}</p>
            <p><b>City:</b> {body.city or 'Not provided'}</p>
            <p><b>Source:</b> AI Chatbot</p>
            <p><b>Session:</b> {body.session_id}</p>
            """
            send_email("partners@nischint.app", "New Chatbot Lead — Nischint", html)
            send_email("hello@nischint.app", "New Chatbot Lead — Nischint", html)
        except Exception as email_err:
            logger.warning(f"Lead email notification failed: {email_err}")

        return {
            "type": "text",
            "message": "Thank you! Your information has been received. Our team will contact you within 48 hours to discuss a pilot deployment. In the meantime, explore our live telemetry at /telemetry.",
            "session_id": body.session_id,
        }
    except (SQLAlchemyError, RuntimeError, ValueError) as e:
        # Compensating action: user receives a fallback "email us"
        # response (line 163-166 below) — the lead path is NOT silently
        # dropped from the user's perspective. Structured log so a
        # spike in failures surfaces to alerting; narrow types so a
        # coding bug (KeyError / AttributeError) still propagates.
        logger.error(
            "lead_capture_failed",
            extra={
                "event":      "lead_capture_failed",
                "session_id": body.session_id,
                "error_type": type(e).__name__,
            },
        )
        return {
            "type": "text",
            "message": "Thank you for your interest. Please email hello@nischint.app and we'll get back to you within 48 hours.",
            "session_id": body.session_id,
        }
