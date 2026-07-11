"""
PR Intelligence & Attribution Engine — NISCHINT Media Revenue Engine.
Tracks: PR Outreach -> Media Coverage -> Traffic -> Leads -> Revenue

Phase 1: Data Layer & Event Ingestion
Phase 2: Intelligence Engine (Journalist Scoring, Campaign Effectiveness, Attribution)
Phase 4: Integration Hooks (n8n compatible, UTM parsing, lead pipeline connection)
"""
import logging
import os
import uuid
import json as json_lib
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db_session
from app.core.rate_limiter import limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pr", tags=["PR Intelligence"])


# ──────────────────────────────────────────────
# DB SCHEMA
# ──────────────────────────────────────────────

SCHEMA_SQL = [
    # Campaigns
    """CREATE TABLE IF NOT EXISTS pr_campaigns (
        campaign_id UUID PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        narrative_angle TEXT,
        target_publications TEXT[],
        status TEXT DEFAULT 'active',
        total_outreach INT DEFAULT 0,
        total_responses INT DEFAULT 0,
        total_articles INT DEFAULT 0,
        total_leads INT DEFAULT 0,
        total_revenue NUMERIC DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );""",
    # Journalists
    """CREATE TABLE IF NOT EXISTS pr_journalists (
        journalist_id UUID PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT UNIQUE,
        publication TEXT,
        beat TEXT,
        tier TEXT DEFAULT 'unknown',
        score INT DEFAULT 0,
        priority TEXT DEFAULT 'medium',
        total_pitches INT DEFAULT 0,
        total_responses INT DEFAULT 0,
        total_articles INT DEFAULT 0,
        total_leads INT DEFAULT 0,
        total_revenue NUMERIC DEFAULT 0,
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );""",
    # Events (universal event log)
    """CREATE TABLE IF NOT EXISTS pr_events (
        event_id UUID PRIMARY KEY,
        event_type TEXT NOT NULL,
        campaign_id UUID,
        journalist_id UUID,
        journalist_name TEXT,
        journalist_email TEXT,
        publication TEXT,
        article_url TEXT,
        lead_id UUID,
        revenue NUMERIC,
        utm_source TEXT,
        utm_campaign TEXT,
        utm_content TEXT,
        metadata JSONB DEFAULT '{}',
        timestamp TIMESTAMPTZ NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );""",
    # Articles
    """CREATE TABLE IF NOT EXISTS pr_articles (
        article_id UUID PRIMARY KEY,
        campaign_id UUID,
        journalist_id UUID,
        publication TEXT,
        article_url TEXT UNIQUE,
        title TEXT,
        sentiment TEXT,
        tone TEXT,
        topics TEXT[],
        traffic_count INT DEFAULT 0,
        leads_count INT DEFAULT 0,
        revenue NUMERIC DEFAULT 0,
        publish_date TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );""",
    # Attributions (full chain linkage)
    """CREATE TABLE IF NOT EXISTS pr_attributions (
        attribution_id UUID PRIMARY KEY,
        campaign_id UUID,
        journalist_id UUID,
        article_id UUID,
        lead_id UUID,
        revenue NUMERIC DEFAULT 0,
        utm_source TEXT,
        utm_campaign TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );""",
    # AI Analysis results (batch)
    """CREATE TABLE IF NOT EXISTS pr_ai_analysis (
        analysis_id UUID PRIMARY KEY,
        analysis_type TEXT NOT NULL,
        target_id UUID,
        target_type TEXT,
        result JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ DEFAULT NOW()
    );""",
    # ── RAG-26 Predictive Decision Engine: pr_decisions ──
    """CREATE TABLE IF NOT EXISTS pr_decisions (
        decision_id UUID PRIMARY KEY,
        campaign_id UUID,
        journalist_id UUID,
        narrative_angle TEXT CHECK (narrative_angle IS NULL OR narrative_angle IN (
            'fear','safety','urgency','trust','empowerment','innovation','authority','social_proof'
        )),
        subject_line TEXT,
        headline_variant TEXT,
        cta_type TEXT CHECK (cta_type IS NULL OR cta_type IN (
            'demo_request','free_trial','whitepaper','case_study','interview','exclusive','partnership','webinar'
        )),
        journalist_score INT DEFAULT 0,
        outcome_reply BOOLEAN DEFAULT FALSE,
        outcome_publish BOOLEAN DEFAULT FALSE,
        outcome_leads INT DEFAULT 0,
        outcome_revenue NUMERIC DEFAULT 0,
        utm_source TEXT,
        utm_campaign TEXT,
        utm_content TEXT,
        timestamp TIMESTAMPTZ NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );""",
]

# ── RAG-26: Schema migrations for existing tables ──
MIGRATIONS_SQL = [
    # Extend pr_events with predictive feature columns
    "ALTER TABLE pr_events ADD COLUMN IF NOT EXISTS narrative_angle TEXT;",
    "ALTER TABLE pr_events ADD COLUMN IF NOT EXISTS headline_variant TEXT;",
    "ALTER TABLE pr_events ADD COLUMN IF NOT EXISTS email_subject TEXT;",
    "ALTER TABLE pr_events ADD COLUMN IF NOT EXISTS cta_type TEXT;",
    "ALTER TABLE pr_events ADD COLUMN IF NOT EXISTS journalist_score_at_send INT;",
    # Outcome tracking on pr_events
    "ALTER TABLE pr_events ADD COLUMN IF NOT EXISTS opened BOOLEAN DEFAULT FALSE;",
    "ALTER TABLE pr_events ADD COLUMN IF NOT EXISTS replied BOOLEAN DEFAULT FALSE;",
    "ALTER TABLE pr_events ADD COLUMN IF NOT EXISTS outcome_article BOOLEAN DEFAULT FALSE;",
    "ALTER TABLE pr_events ADD COLUMN IF NOT EXISTS outcome_leads INT DEFAULT 0;",
    "ALTER TABLE pr_events ADD COLUMN IF NOT EXISTS outcome_revenue NUMERIC DEFAULT 0;",
]

INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_pr_events_type ON pr_events(event_type);",
    "CREATE INDEX IF NOT EXISTS idx_pr_events_campaign ON pr_events(campaign_id);",
    "CREATE INDEX IF NOT EXISTS idx_pr_events_journalist ON pr_events(journalist_id);",
    "CREATE INDEX IF NOT EXISTS idx_pr_events_timestamp ON pr_events(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_pr_events_lead ON pr_events(lead_id);",
    "CREATE INDEX IF NOT EXISTS idx_pr_articles_campaign ON pr_articles(campaign_id);",
    "CREATE INDEX IF NOT EXISTS idx_pr_articles_journalist ON pr_articles(journalist_id);",
    "CREATE INDEX IF NOT EXISTS idx_pr_attributions_campaign ON pr_attributions(campaign_id);",
    "CREATE INDEX IF NOT EXISTS idx_pr_attributions_journalist ON pr_attributions(journalist_id);",
    "CREATE INDEX IF NOT EXISTS idx_pr_attributions_lead ON pr_attributions(lead_id);",
    "CREATE INDEX IF NOT EXISTS idx_pr_journalists_email ON pr_journalists(email);",
    "CREATE INDEX IF NOT EXISTS idx_pr_journalists_score ON pr_journalists(score DESC);",
    "CREATE INDEX IF NOT EXISTS idx_pr_ai_analysis_target ON pr_ai_analysis(target_id, target_type);",
    # RAG-26 indexes
    "CREATE INDEX IF NOT EXISTS idx_pr_decisions_campaign ON pr_decisions(campaign_id);",
    "CREATE INDEX IF NOT EXISTS idx_pr_decisions_journalist ON pr_decisions(journalist_id);",
    "CREATE INDEX IF NOT EXISTS idx_pr_decisions_narrative ON pr_decisions(narrative_angle);",
    "CREATE INDEX IF NOT EXISTS idx_pr_decisions_cta ON pr_decisions(cta_type);",
    "CREATE INDEX IF NOT EXISTS idx_pr_decisions_timestamp ON pr_decisions(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_pr_events_narrative ON pr_events(narrative_angle);",
    "CREATE INDEX IF NOT EXISTS idx_pr_events_cta ON pr_events(cta_type);",
]

_tables_ready = False


async def ensure_tables(session: AsyncSession):
    global _tables_ready
    if _tables_ready:
        return
    for sql in SCHEMA_SQL:
        await session.execute(text(sql))
    for sql in MIGRATIONS_SQL:
        await session.execute(text(sql))
    for idx in INDEXES_SQL:
        await session.execute(text(idx))
    await session.commit()
    _tables_ready = True


# ── RAG-26: Enum constants (source of truth) ──
NARRATIVE_ANGLES = ['fear', 'safety', 'urgency', 'trust', 'empowerment', 'innovation', 'authority', 'social_proof']
CTA_TYPES = ['demo_request', 'free_trial', 'whitepaper', 'case_study', 'interview', 'exclusive', 'partnership', 'webinar']


# ──────────────────────────────────────────────
# MODELS
# ──────────────────────────────────────────────

class PREventRequest(BaseModel):
    event_type: str  # pr_outreach_sent, journalist_response, article_published, lead_generated, conversion
    campaign_id: Optional[str] = None
    journalist_name: Optional[str] = None
    journalist_email: Optional[str] = None
    publication: Optional[str] = None
    article_url: Optional[str] = None
    article_title: Optional[str] = None
    lead_id: Optional[str] = None
    revenue: Optional[float] = None
    utm_source: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_content: Optional[str] = None
    timestamp: Optional[str] = None
    metadata: Optional[dict] = None
    # RAG-26: Predictive feature columns
    narrative_angle: Optional[str] = None
    headline_variant: Optional[str] = None
    email_subject: Optional[str] = None
    cta_type: Optional[str] = None
    journalist_score_at_send: Optional[int] = None


class PREventBatch(BaseModel):
    events: List[PREventRequest]


class CampaignCreate(BaseModel):
    name: str
    description: Optional[str] = None
    narrative_angle: Optional[str] = None
    target_publications: Optional[List[str]] = None


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    narrative_angle: Optional[str] = None
    status: Optional[str] = None


# ── RAG-26 Models ──

class DecisionCreate(BaseModel):
    campaign_id: Optional[str] = None
    journalist_id: Optional[str] = None
    narrative_angle: Optional[str] = None
    subject_line: Optional[str] = None
    headline_variant: Optional[str] = None
    cta_type: Optional[str] = None
    journalist_score: Optional[int] = None
    utm_source: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_content: Optional[str] = None
    timestamp: Optional[str] = None


class DecisionOutcomeUpdate(BaseModel):
    outcome_reply: Optional[bool] = None
    outcome_publish: Optional[bool] = None
    outcome_leads: Optional[int] = None
    outcome_revenue: Optional[float] = None


class EventOutcomeUpdate(BaseModel):
    opened: Optional[bool] = None
    replied: Optional[bool] = None
    outcome_article: Optional[bool] = None
    outcome_leads: Optional[int] = None
    outcome_revenue: Optional[float] = None


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────

async def upsert_journalist(session: AsyncSession, name: str, email: str = None, publication: str = None) -> str:
    """Find or create journalist by email, return journalist_id."""
    if email:
        row = await session.execute(
            text("SELECT journalist_id FROM pr_journalists WHERE email = :email LIMIT 1"),
            {"email": email}
        )
        existing = row.fetchone()
        if existing:
            return str(existing.journalist_id)

    journalist_id = str(uuid.uuid4())
    await session.execute(text("""
        INSERT INTO pr_journalists (journalist_id, name, email, publication, created_at, updated_at)
        VALUES (:jid, :name, :email, :pub, :now, :now)
        ON CONFLICT (email) DO UPDATE SET
            name = COALESCE(EXCLUDED.name, pr_journalists.name),
            publication = COALESCE(EXCLUDED.publication, pr_journalists.publication),
            updated_at = EXCLUDED.updated_at
        RETURNING journalist_id
    """), {
        "jid": journalist_id, "name": name,
        "email": email, "pub": publication,
        "now": datetime.now(timezone.utc),
    })
    result = await session.execute(
        text("SELECT journalist_id FROM pr_journalists WHERE email = :email LIMIT 1"),
        {"email": email}
    )
    row = result.fetchone()
    return str(row.journalist_id) if row else journalist_id


async def update_counters(session: AsyncSession, event_type: str, campaign_id: str = None, journalist_id: str = None, revenue: float = None):
    """Real-time counter updates on event ingestion."""
    now = datetime.now(timezone.utc)

    if event_type == "pr_outreach_sent":
        if campaign_id:
            await session.execute(text(
                "UPDATE pr_campaigns SET total_outreach = total_outreach + 1, updated_at = :now WHERE campaign_id = :cid"
            ), {"cid": campaign_id, "now": now})
        if journalist_id:
            await session.execute(text(
                "UPDATE pr_journalists SET total_pitches = total_pitches + 1, updated_at = :now WHERE journalist_id = :jid"
            ), {"jid": journalist_id, "now": now})

    elif event_type == "journalist_response":
        if campaign_id:
            await session.execute(text(
                "UPDATE pr_campaigns SET total_responses = total_responses + 1, updated_at = :now WHERE campaign_id = :cid"
            ), {"cid": campaign_id, "now": now})
        if journalist_id:
            await session.execute(text(
                "UPDATE pr_journalists SET total_responses = total_responses + 1, updated_at = :now WHERE journalist_id = :jid"
            ), {"jid": journalist_id, "now": now})

    elif event_type == "article_published":
        if campaign_id:
            await session.execute(text(
                "UPDATE pr_campaigns SET total_articles = total_articles + 1, updated_at = :now WHERE campaign_id = :cid"
            ), {"cid": campaign_id, "now": now})
        if journalist_id:
            await session.execute(text(
                "UPDATE pr_journalists SET total_articles = total_articles + 1, updated_at = :now WHERE journalist_id = :jid"
            ), {"jid": journalist_id, "now": now})

    elif event_type == "lead_generated":
        if campaign_id:
            await session.execute(text(
                "UPDATE pr_campaigns SET total_leads = total_leads + 1, updated_at = :now WHERE campaign_id = :cid"
            ), {"cid": campaign_id, "now": now})
        if journalist_id:
            await session.execute(text(
                "UPDATE pr_journalists SET total_leads = total_leads + 1, updated_at = :now WHERE journalist_id = :jid"
            ), {"jid": journalist_id, "now": now})

    elif event_type == "conversion" and revenue:
        if campaign_id:
            await session.execute(text(
                "UPDATE pr_campaigns SET total_revenue = total_revenue + :rev, updated_at = :now WHERE campaign_id = :cid"
            ), {"cid": campaign_id, "rev": revenue, "now": now})
        if journalist_id:
            await session.execute(text(
                "UPDATE pr_journalists SET total_revenue = total_revenue + :rev, updated_at = :now WHERE journalist_id = :jid"
            ), {"jid": journalist_id, "rev": revenue, "now": now})


# ──────────────────────────────────────────────
# PHASE 1: EVENT INGESTION
# ──────────────────────────────────────────────

@router.post("/events")
@limiter.limit("120/minute")
async def ingest_event(
    request: Request,
    req: PREventRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Universal PR event ingestion. Accepts all event types, auto-links entities."""
    await ensure_tables(session)

    event_ts = datetime.fromisoformat(req.timestamp) if req.timestamp else datetime.now(timezone.utc)
    event_id = str(uuid.uuid4())

    # Deduplication: same event_type + campaign + journalist_email within 5 minutes
    dedup_check = await session.execute(text("""
        SELECT event_id FROM pr_events
        WHERE event_type = :etype
          AND COALESCE(campaign_id::text, '') = COALESCE(:cid, '')
          AND COALESCE(journalist_email, '') = COALESCE(:jemail, '')
          AND timestamp > :cutoff
        LIMIT 1
    """), {
        "etype": req.event_type,
        "cid": req.campaign_id,
        "jemail": req.journalist_email,
        "cutoff": event_ts - timedelta(minutes=5),
    })
    if dedup_check.fetchone():
        return {"status": "duplicate", "message": "Event already recorded within dedup window."}

    # Auto-resolve journalist
    journalist_id = None
    if req.journalist_name or req.journalist_email:
        journalist_id = await upsert_journalist(
            session,
            name=req.journalist_name or "Unknown",
            email=req.journalist_email,
            publication=req.publication,
        )

    # Insert event
    await session.execute(text("""
        INSERT INTO pr_events (
            event_id, event_type, campaign_id, journalist_id,
            journalist_name, journalist_email, publication,
            article_url, lead_id, revenue,
            utm_source, utm_campaign, utm_content,
            narrative_angle, headline_variant, email_subject,
            cta_type, journalist_score_at_send,
            metadata, timestamp, created_at
        ) VALUES (
            :eid, :etype, :cid, :jid,
            :jname, :jemail, :pub,
            :aurl, :lid, :rev,
            :usrc, :ucmp, :ucnt,
            :nangle, :hvariant, :esubject,
            :ctype, :jscore,
            CAST(:meta AS jsonb), :ts, :now
        )
    """), {
        "eid": event_id,
        "etype": req.event_type,
        "cid": req.campaign_id,
        "jid": journalist_id,
        "jname": req.journalist_name,
        "jemail": req.journalist_email,
        "pub": req.publication,
        "aurl": req.article_url,
        "lid": req.lead_id,
        "rev": req.revenue,
        "usrc": req.utm_source,
        "ucmp": req.utm_campaign,
        "ucnt": req.utm_content,
        "nangle": req.narrative_angle,
        "hvariant": req.headline_variant,
        "esubject": req.email_subject,
        "ctype": req.cta_type,
        "jscore": req.journalist_score_at_send,
        "meta": json_lib.dumps(req.metadata or {}),
        "ts": event_ts,
        "now": datetime.now(timezone.utc),
    })

    # Auto-create article record on article_published
    if req.event_type == "article_published" and req.article_url:
        article_id = str(uuid.uuid4())
        await session.execute(text("""
            INSERT INTO pr_articles (
                article_id, campaign_id, journalist_id, publication,
                article_url, title, publish_date, created_at
            ) VALUES (:aid, :cid, :jid, :pub, :aurl, :title, :ts, :now)
            ON CONFLICT (article_url) DO NOTHING
        """), {
            "aid": article_id, "cid": req.campaign_id,
            "jid": journalist_id, "pub": req.publication,
            "aurl": req.article_url, "title": req.article_title,
            "ts": event_ts, "now": datetime.now(timezone.utc),
        })

    # Auto-create attribution on lead_generated or conversion
    if req.event_type in ("lead_generated", "conversion") and req.lead_id:
        attr_id = str(uuid.uuid4())
        await session.execute(text("""
            INSERT INTO pr_attributions (
                attribution_id, campaign_id, journalist_id, lead_id,
                revenue, utm_source, utm_campaign, created_at
            ) VALUES (:atid, :cid, :jid, :lid, :rev, :usrc, :ucmp, :now)
        """), {
            "atid": attr_id, "cid": req.campaign_id,
            "jid": journalist_id, "lid": req.lead_id,
            "rev": req.revenue or 0, "usrc": req.utm_source,
            "ucmp": req.utm_campaign, "now": datetime.now(timezone.utc),
        })

    # Update real-time counters
    await update_counters(session, req.event_type, req.campaign_id, journalist_id, req.revenue)

    logger.info(f"[PR_EVENT] {req.event_type} campaign={req.campaign_id} journalist={req.journalist_email}")

    return {
        "status": "ok",
        "event_id": event_id,
        "event_type": req.event_type,
        "journalist_id": journalist_id,
    }


@router.post("/events/batch")
@limiter.limit("30/minute")
async def ingest_events_batch(
    request: Request,
    req: PREventBatch,
    session: AsyncSession = Depends(get_db_session),
):
    """Batch event ingestion for n8n/webhook bulk imports."""
    await ensure_tables(session)
    results = []
    for ev in req.events:
        event_ts = datetime.fromisoformat(ev.timestamp) if ev.timestamp else datetime.now(timezone.utc)
        event_id = str(uuid.uuid4())

        journalist_id = None
        if ev.journalist_name or ev.journalist_email:
            journalist_id = await upsert_journalist(
                session, name=ev.journalist_name or "Unknown",
                email=ev.journalist_email, publication=ev.publication,
            )

        await session.execute(text("""
            INSERT INTO pr_events (
                event_id, event_type, campaign_id, journalist_id,
                journalist_name, journalist_email, publication,
                article_url, lead_id, revenue,
                utm_source, utm_campaign, utm_content,
                narrative_angle, headline_variant, email_subject,
                cta_type, journalist_score_at_send,
                metadata, timestamp, created_at
            ) VALUES (
                :eid, :etype, :cid, :jid,
                :jname, :jemail, :pub,
                :aurl, :lid, :rev,
                :usrc, :ucmp, :ucnt,
                :nangle, :hvariant, :esubject,
                :ctype, :jscore,
                CAST(:meta AS jsonb), :ts, :now
            )
        """), {
            "eid": event_id, "etype": ev.event_type,
            "cid": ev.campaign_id, "jid": journalist_id,
            "jname": ev.journalist_name, "jemail": ev.journalist_email,
            "pub": ev.publication, "aurl": ev.article_url,
            "lid": ev.lead_id, "rev": ev.revenue,
            "usrc": ev.utm_source, "ucmp": ev.utm_campaign, "ucnt": ev.utm_content,
            "nangle": ev.narrative_angle, "hvariant": ev.headline_variant,
            "esubject": ev.email_subject, "ctype": ev.cta_type,
            "jscore": ev.journalist_score_at_send,
            "meta": json_lib.dumps(ev.metadata or {}),
            "ts": event_ts, "now": datetime.now(timezone.utc),
        })

        await update_counters(session, ev.event_type, ev.campaign_id, journalist_id, ev.revenue)

        # Auto-create article on article_published
        if ev.event_type == "article_published" and ev.article_url:
            article_id = str(uuid.uuid4())
            await session.execute(text("""
                INSERT INTO pr_articles (article_id, campaign_id, journalist_id, publication, article_url, title, publish_date, created_at)
                VALUES (:aid, :cid, :jid, :pub, :aurl, :title, :ts, :now)
                ON CONFLICT (article_url) DO NOTHING
            """), {"aid": article_id, "cid": ev.campaign_id, "jid": journalist_id,
                   "pub": ev.publication, "aurl": ev.article_url, "title": ev.article_title,
                   "ts": event_ts, "now": datetime.now(timezone.utc)})

        # Auto-create attribution on lead/conversion
        if ev.event_type in ("lead_generated", "conversion") and ev.lead_id:
            attr_id = str(uuid.uuid4())
            await session.execute(text("""
                INSERT INTO pr_attributions (attribution_id, campaign_id, journalist_id, lead_id, revenue, utm_source, utm_campaign, created_at)
                VALUES (:atid, :cid, :jid, :lid, :rev, :usrc, :ucmp, :now)
            """), {"atid": attr_id, "cid": ev.campaign_id, "jid": journalist_id,
                   "lid": ev.lead_id, "rev": ev.revenue or 0,
                   "usrc": ev.utm_source, "ucmp": ev.utm_campaign,
                   "now": datetime.now(timezone.utc)})

        results.append({"event_id": event_id, "event_type": ev.event_type})

    logger.info(f"[PR_BATCH] Ingested {len(results)} events")
    return {"status": "ok", "count": len(results), "events": results}


# ──────────────────────────────────────────────
# CAMPAIGNS CRUD
# ──────────────────────────────────────────────

@router.post("/campaigns")
@limiter.limit("30/minute")
async def create_campaign(
    request: Request,
    req: CampaignCreate,
    session: AsyncSession = Depends(get_db_session),
):
    """Create a new PR campaign."""
    await ensure_tables(session)
    campaign_id = str(uuid.uuid4())
    await session.execute(text("""
        INSERT INTO pr_campaigns (campaign_id, name, description, narrative_angle, target_publications, created_at, updated_at)
        VALUES (:cid, :name, :desc, :angle, :pubs, :now, :now)
    """), {
        "cid": campaign_id, "name": req.name,
        "desc": req.description, "angle": req.narrative_angle,
        "pubs": req.target_publications or [],
        "now": datetime.now(timezone.utc),
    })
    return {"status": "ok", "campaign_id": campaign_id}


@router.get("/campaigns")
async def list_campaigns(
    status: Optional[str] = None,
    session: AsyncSession = Depends(get_db_session),
):
    """List all PR campaigns with counters."""
    await ensure_tables(session)
    where = "WHERE status = :status" if status else ""
    params = {"status": status} if status else {}
    rows = await session.execute(text(f"""
        SELECT campaign_id, name, description, narrative_angle, status,
               total_outreach, total_responses, total_articles, total_leads, total_revenue,
               created_at, updated_at
        FROM pr_campaigns {where}
        ORDER BY created_at DESC
    """), params)
    campaigns = []
    for r in rows.fetchall():
        outreach = r.total_outreach or 0
        campaigns.append({
            "campaign_id": str(r.campaign_id), "name": r.name,
            "description": r.description, "narrative_angle": r.narrative_angle,
            "status": r.status,
            "total_outreach": outreach,
            "total_responses": r.total_responses or 0,
            "total_articles": r.total_articles or 0,
            "total_leads": r.total_leads or 0,
            "total_revenue": float(r.total_revenue or 0),
            "response_rate": round((r.total_responses or 0) / max(outreach, 1) * 100, 1),
            "coverage_rate": round((r.total_articles or 0) / max(outreach, 1) * 100, 1),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return {"campaigns": campaigns, "total": len(campaigns)}


@router.get("/campaigns/{campaign_id}")
async def get_campaign_detail(
    campaign_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Get campaign detail with all associated events."""
    await ensure_tables(session)
    row = await session.execute(text("""
        SELECT campaign_id, name, description, narrative_angle, status,
               total_outreach, total_responses, total_articles, total_leads, total_revenue,
               created_at
        FROM pr_campaigns WHERE campaign_id = :cid
    """), {"cid": campaign_id})
    c = row.fetchone()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")

    outreach = c.total_outreach or 0
    responses = c.total_responses or 0
    articles = c.total_articles or 0
    leads = c.total_leads or 0

    # Get recent events for this campaign
    events_row = await session.execute(text("""
        SELECT event_id, event_type, journalist_name, publication, timestamp
        FROM pr_events WHERE campaign_id = :cid
        ORDER BY timestamp DESC LIMIT 50
    """), {"cid": campaign_id})

    events = [
        {"event_id": str(e.event_id), "event_type": e.event_type,
         "journalist_name": e.journalist_name, "publication": e.publication,
         "timestamp": e.timestamp.isoformat() if e.timestamp else None}
        for e in events_row.fetchall()
    ]

    return {
        "campaign_id": str(c.campaign_id), "name": c.name,
        "description": c.description, "narrative_angle": c.narrative_angle,
        "status": c.status,
        "metrics": {
            "outreach": outreach, "responses": responses,
            "articles": articles, "leads": leads,
            "revenue": float(c.total_revenue or 0),
            "response_rate": round(responses / max(outreach, 1) * 100, 1),
            "coverage_rate": round(articles / max(outreach, 1) * 100, 1),
            "conversion_rate": round(leads / max(outreach, 1) * 100, 1),
        },
        "recent_events": events,
    }


# ──────────────────────────────────────────────
# PHASE 2: JOURNALIST PERFORMANCE SCORING
# ──────────────────────────────────────────────

@router.get("/journalists")
async def list_journalists(
    sort_by: str = "score",
    limit: int = 50,
    session: AsyncSession = Depends(get_db_session),
):
    """List journalists ranked by performance score."""
    await ensure_tables(session)

    # Compute live scores
    await session.execute(text("""
        UPDATE pr_journalists SET
            score = LEAST(100, GREATEST(0,
                (CASE WHEN total_pitches > 0 THEN (total_responses::FLOAT / total_pitches * 25) ELSE 0 END) +
                (CASE WHEN total_pitches > 0 THEN (total_articles::FLOAT / total_pitches * 30) ELSE 0 END) +
                (LEAST(total_leads, 10) * 2.5) +
                (LEAST(total_revenue::FLOAT / GREATEST(1, 1000), 1) * 20)
            )::INT),
            priority = CASE
                WHEN (CASE WHEN total_pitches > 0 THEN (total_responses::FLOAT / total_pitches * 25) ELSE 0 END) +
                     (CASE WHEN total_pitches > 0 THEN (total_articles::FLOAT / total_pitches * 30) ELSE 0 END) +
                     (LEAST(total_leads, 10) * 2.5) +
                     (LEAST(total_revenue::FLOAT / GREATEST(1, 1000), 1) * 20) >= 60 THEN 'high'
                WHEN (CASE WHEN total_pitches > 0 THEN (total_responses::FLOAT / total_pitches * 25) ELSE 0 END) +
                     (CASE WHEN total_pitches > 0 THEN (total_articles::FLOAT / total_pitches * 30) ELSE 0 END) +
                     (LEAST(total_leads, 10) * 2.5) +
                     (LEAST(total_revenue::FLOAT / GREATEST(1, 1000), 1) * 20) >= 30 THEN 'medium'
                ELSE 'low'
            END,
            updated_at = NOW()
        WHERE total_pitches > 0 OR total_responses > 0 OR total_articles > 0
    """))

    order_col = {"score": "score DESC", "revenue": "total_revenue DESC", "articles": "total_articles DESC", "leads": "total_leads DESC"}.get(sort_by, "score DESC")

    rows = await session.execute(text(f"""
        SELECT journalist_id, name, email, publication, beat, tier,
               score, priority,
               total_pitches, total_responses, total_articles, total_leads, total_revenue,
               created_at
        FROM pr_journalists
        ORDER BY {order_col}
        LIMIT :lim
    """), {"lim": limit})

    journalists = []
    for r in rows.fetchall():
        pitches = r.total_pitches or 0
        journalists.append({
            "journalist_id": str(r.journalist_id), "name": r.name,
            "email": r.email, "publication": r.publication,
            "beat": r.beat, "tier": r.tier,
            "score": r.score or 0, "priority": r.priority or "medium",
            "metrics": {
                "pitches": pitches,
                "responses": r.total_responses or 0,
                "articles": r.total_articles or 0,
                "leads": r.total_leads or 0,
                "revenue": float(r.total_revenue or 0),
                "response_rate": round((r.total_responses or 0) / max(pitches, 1) * 100, 1),
                "publication_rate": round((r.total_articles or 0) / max(pitches, 1) * 100, 1),
            },
        })

    return {"journalists": journalists, "total": len(journalists)}


# ──────────────────────────────────────────────
# PHASE 2: ATTRIBUTION ENGINE
# ──────────────────────────────────────────────

@router.get("/attribution")
async def get_attribution(
    days: int = 30,
    group_by: str = "journalist",
    session: AsyncSession = Depends(get_db_session),
):
    """Full attribution chain: Journalist -> Article -> Lead -> Revenue."""
    await ensure_tables(session)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    if group_by == "journalist":
        rows = await session.execute(text("""
            SELECT j.journalist_id, j.name, j.email, j.publication,
                   COUNT(DISTINCT a.lead_id) as leads,
                   COALESCE(SUM(a.revenue), 0) as revenue,
                   COUNT(DISTINCT a.attribution_id) as touchpoints
            FROM pr_attributions a
            LEFT JOIN pr_journalists j ON j.journalist_id = a.journalist_id
            WHERE a.created_at >= :since
            GROUP BY j.journalist_id, j.name, j.email, j.publication
            ORDER BY revenue DESC
        """), {"since": since})
        items = [{"journalist_id": str(r.journalist_id) if r.journalist_id else None,
                   "name": r.name, "email": r.email, "publication": r.publication,
                   "leads": r.leads, "revenue": float(r.revenue), "touchpoints": r.touchpoints}
                 for r in rows.fetchall()]

    elif group_by == "campaign":
        rows = await session.execute(text("""
            SELECT c.campaign_id, c.name, c.narrative_angle,
                   COUNT(DISTINCT a.lead_id) as leads,
                   COALESCE(SUM(a.revenue), 0) as revenue
            FROM pr_attributions a
            LEFT JOIN pr_campaigns c ON c.campaign_id = a.campaign_id
            WHERE a.created_at >= :since
            GROUP BY c.campaign_id, c.name, c.narrative_angle
            ORDER BY revenue DESC
        """), {"since": since})
        items = [{"campaign_id": str(r.campaign_id) if r.campaign_id else None,
                   "name": r.name, "narrative_angle": r.narrative_angle,
                   "leads": r.leads, "revenue": float(r.revenue)}
                 for r in rows.fetchall()]

    elif group_by == "publication":
        rows = await session.execute(text("""
            SELECT j.publication,
                   COUNT(DISTINCT a.lead_id) as leads,
                   COALESCE(SUM(a.revenue), 0) as revenue,
                   COUNT(DISTINCT a.journalist_id) as journalists
            FROM pr_attributions a
            LEFT JOIN pr_journalists j ON j.journalist_id = a.journalist_id
            WHERE a.created_at >= :since AND j.publication IS NOT NULL
            GROUP BY j.publication
            ORDER BY revenue DESC
        """), {"since": since})
        items = [{"publication": r.publication, "leads": r.leads,
                   "revenue": float(r.revenue), "journalists": r.journalists}
                 for r in rows.fetchall()]
    else:
        items = []

    return {"group_by": group_by, "period_days": days, "attributions": items}


# ──────────────────────────────────────────────
# PHASE 2: CEO DASHBOARD METRICS
# ──────────────────────────────────────────────

@router.get("/dashboard")
async def pr_dashboard(
    days: int = 30,
    session: AsyncSession = Depends(get_db_session),
):
    """CEO-level PR Intelligence dashboard — aggregated KPIs."""
    await ensure_tables(session)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Campaign totals
    camp_row = await session.execute(text("""
        SELECT COUNT(*) as total,
               COALESCE(SUM(total_outreach), 0) as outreach,
               COALESCE(SUM(total_responses), 0) as responses,
               COALESCE(SUM(total_articles), 0) as articles,
               COALESCE(SUM(total_leads), 0) as leads,
               COALESCE(SUM(total_revenue), 0) as revenue
        FROM pr_campaigns
    """))
    c = camp_row.fetchone()

    # Event type breakdown (time-filtered)
    event_rows = await session.execute(text("""
        SELECT event_type, COUNT(*) as cnt
        FROM pr_events WHERE timestamp >= :since
        GROUP BY event_type ORDER BY cnt DESC
    """), {"since": since})
    event_breakdown = {r.event_type: r.cnt for r in event_rows.fetchall()}

    # Top 5 journalists by revenue
    top_j_rows = await session.execute(text("""
        SELECT name, publication, score, total_revenue, total_articles
        FROM pr_journalists
        ORDER BY total_revenue DESC, score DESC
        LIMIT 5
    """))
    top_journalists = [
        {"name": r.name, "publication": r.publication, "score": r.score or 0,
         "revenue": float(r.total_revenue or 0), "articles": r.total_articles or 0}
        for r in top_j_rows.fetchall()
    ]

    # Top 5 campaigns by revenue
    top_c_rows = await session.execute(text("""
        SELECT name, narrative_angle, total_leads, total_revenue, total_articles
        FROM pr_campaigns
        ORDER BY total_revenue DESC
        LIMIT 5
    """))
    top_campaigns = [
        {"name": r.name, "narrative_angle": r.narrative_angle,
         "leads": r.total_leads or 0, "revenue": float(r.total_revenue or 0),
         "articles": r.total_articles or 0}
        for r in top_c_rows.fetchall()
    ]

    # Daily event trend
    daily_rows = await session.execute(text("""
        SELECT DATE(timestamp) as day, event_type, COUNT(*) as cnt
        FROM pr_events WHERE timestamp >= :since
        GROUP BY day, event_type ORDER BY day
    """), {"since": since})
    daily_trend = {}
    for r in daily_rows.fetchall():
        day_str = str(r.day)
        daily_trend.setdefault(day_str, {})[r.event_type] = r.cnt

    # Pipeline summary
    outreach = c.outreach if c else 0
    responses = c.responses if c else 0
    articles = c.articles if c else 0
    leads = c.leads if c else 0
    revenue = float(c.revenue) if c else 0

    return {
        "period_days": days,
        "overview": {
            "total_campaigns": c.total if c else 0,
            "total_outreach": outreach,
            "total_responses": responses,
            "articles_published": articles,
            "leads_generated": leads,
            "revenue_influenced": revenue,
        },
        "conversion_rates": {
            "outreach_to_response": round(responses / max(outreach, 1) * 100, 1),
            "response_to_article": round(articles / max(responses, 1) * 100, 1),
            "article_to_lead": round(leads / max(articles, 1) * 100, 1),
            "overall_pr_roi": round(leads / max(outreach, 1) * 100, 1),
        },
        "event_breakdown": event_breakdown,
        "top_journalists": top_journalists,
        "top_campaigns": top_campaigns,
        "daily_trend": daily_trend,
    }


# ──────────────────────────────────────────────
# PHASE 2: ON-DEMAND AI ANALYSIS
# ──────────────────────────────────────────────

@router.post("/analyze")
@limiter.limit("10/minute")
async def trigger_analysis(
    request: Request,
    campaign_id: Optional[str] = None,
    session: AsyncSession = Depends(get_db_session),
):
    """On-demand AI narrative analysis for a campaign or all campaigns."""
    await ensure_tables(session)

    try:
        from emergentintegrations.llm.chat import ChatConfig, chat
    except ImportError:
        return {"status": "error", "message": "AI module not available"}

    emergent_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not emergent_key:
        return {"status": "error", "message": "EMERGENT_LLM_KEY not configured"}

    # Gather campaign data
    if campaign_id:
        where = "WHERE campaign_id = :cid"
        params = {"cid": campaign_id}
    else:
        where = ""
        params = {}

    events_row = await session.execute(text(f"""
        SELECT event_type, journalist_name, publication, article_url,
               metadata, timestamp
        FROM pr_events {where}
        ORDER BY timestamp DESC LIMIT 100
    """), params)
    events = [{"type": r.event_type, "journalist": r.journalist_name,
               "publication": r.publication, "timestamp": r.timestamp.isoformat() if r.timestamp else None}
              for r in events_row.fetchall()]

    if not events:
        return {"status": "ok", "message": "No events to analyze", "insights": {}}

    prompt = f"""You are NISCHINT's PR Intelligence AI. Analyze these {len(events)} PR events and provide:

1. **Narrative Intelligence**: Which emotional tones (fear, safety, urgency, trust) and topics (AI, women safety, parenting, tech) are most present? Which narratives drive the most journalist responses and coverage?

2. **Campaign Recommendations**: Based on the data, which PR angles should be prioritized? Which headlines would work best?

3. **Journalist Prioritization**: Which journalists/publications should be targeted next and why?

4. **Risk Assessment**: Any campaigns that are underperforming? What should change?

PR Events Data:
{json_lib.dumps(events[:50], indent=2)}

Respond in valid JSON with keys: narrative_analysis, recommendations, journalist_priorities, risk_assessment"""

    config = ChatConfig(
        api_key=emergent_key,
        model="gpt-5.2",
        system_prompt="You are a PR Intelligence analyst. Respond ONLY in valid JSON.",
        temperature=0.3,
        max_tokens=2000,
    )

    try:
        result = await chat(config=config, user_message=prompt)
        analysis = json_lib.loads(result.message) if result.message else {}
    except Exception as e:
        logger.warning(f"[PR_AI_ANALYSIS] AI call failed: {e}")
        analysis = {"error": str(e)}

    # Store analysis result
    analysis_id = str(uuid.uuid4())
    await session.execute(text("""
        INSERT INTO pr_ai_analysis (analysis_id, analysis_type, target_id, target_type, result, created_at)
        VALUES (:aid, 'narrative', :tid, :ttype, CAST(:result AS jsonb), :now)
    """), {
        "aid": analysis_id,
        "tid": campaign_id,
        "ttype": "campaign" if campaign_id else "global",
        "result": json_lib.dumps(analysis),
        "now": datetime.now(timezone.utc),
    })

    return {"status": "ok", "analysis_id": analysis_id, "insights": analysis}


@router.get("/analysis/latest")
async def get_latest_analysis(
    target_type: str = "global",
    session: AsyncSession = Depends(get_db_session),
):
    """Get the most recent AI analysis results."""
    await ensure_tables(session)
    row = await session.execute(text("""
        SELECT analysis_id, analysis_type, target_id, target_type, result, created_at
        FROM pr_ai_analysis
        WHERE target_type = :ttype
        ORDER BY created_at DESC LIMIT 1
    """), {"ttype": target_type})
    r = row.fetchone()
    if not r:
        return {"status": "ok", "message": "No analysis available yet", "insights": {}}

    return {
        "analysis_id": str(r.analysis_id),
        "analysis_type": r.analysis_type,
        "target_type": r.target_type,
        "insights": r.result if isinstance(r.result, dict) else json_lib.loads(r.result) if r.result else {},
        "analyzed_at": r.created_at.isoformat() if r.created_at else None,
    }


# ──────────────────────────────────────────────
# PHASE 4: INTEGRATION HOOKS
# ──────────────────────────────────────────────

@router.post("/webhook/n8n")
@limiter.limit("60/minute")
async def n8n_webhook(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    """Generic n8n webhook receiver. Accepts any JSON payload and routes to event ingestion."""
    await ensure_tables(session)
    body = await request.json()

    # Support both single event and array
    events = body if isinstance(body, list) else [body]
    results = []

    for ev in events:
        event_type = ev.get("event_type", ev.get("type", "unknown"))
        event_id = str(uuid.uuid4())
        event_ts = datetime.now(timezone.utc)

        if ev.get("timestamp"):
            try:
                event_ts = datetime.fromisoformat(ev["timestamp"])
            except (ValueError, TypeError):
                pass

        # ── n8n: decision recording ──
        if event_type == "decision":
            decision_id = str(uuid.uuid4())
            n_angle = ev.get("narrative_angle")
            c_type = ev.get("cta_type")
            if n_angle and n_angle not in NARRATIVE_ANGLES:
                results.append({"event_id": decision_id, "event_type": "decision", "error": f"invalid narrative_angle: {n_angle}"})
                continue
            if c_type and c_type not in CTA_TYPES:
                results.append({"event_id": decision_id, "event_type": "decision", "error": f"invalid cta_type: {c_type}"})
                continue

            j_id = ev.get("journalist_id")
            await session.execute(text("""
                INSERT INTO pr_decisions (
                    decision_id, campaign_id, journalist_id,
                    narrative_angle, subject_line, headline_variant,
                    cta_type, journalist_score,
                    utm_source, utm_campaign, utm_content,
                    timestamp, created_at, updated_at
                ) VALUES (
                    :did, :cid, :jid, :nangle, :subj, :hvariant,
                    :ctype, :jscore, :usrc, :ucmp, :ucnt, :ts, :now, :now
                )
            """), {
                "did": decision_id, "cid": ev.get("campaign_id"), "jid": j_id,
                "nangle": n_angle, "subj": ev.get("subject_line"),
                "hvariant": ev.get("headline_variant"), "ctype": c_type,
                "jscore": ev.get("journalist_score", 0),
                "usrc": ev.get("utm_source"), "ucmp": ev.get("utm_campaign"),
                "ucnt": ev.get("utm_content"), "ts": event_ts,
                "now": datetime.now(timezone.utc),
            })
            results.append({"event_id": decision_id, "event_type": "decision"})
            continue

        # ── n8n: outcome updates ──
        if event_type == "outcome_update":
            target_event_id = ev.get("event_id")
            target_decision_id = ev.get("decision_id")
            updated = 0

            if target_event_id:
                e_sets, e_params = [], {"eid": target_event_id}
                for fld, col in [("opened", "opened"), ("replied", "replied"),
                                 ("outcome_article", "outcome_article"),
                                 ("outcome_leads", "outcome_leads"),
                                 ("outcome_revenue", "outcome_revenue")]:
                    if ev.get(fld) is not None:
                        e_sets.append(f"{col} = :{fld}")
                        e_params[fld] = ev[fld]
                if e_sets:
                    await session.execute(text(
                        f"UPDATE pr_events SET {', '.join(e_sets)} WHERE event_id = :eid"
                    ), e_params)
                    updated += len(e_sets)

            if target_decision_id:
                d_sets, d_params = [], {"did": target_decision_id, "now": datetime.now(timezone.utc)}
                for fld, col in [("outcome_reply", "outcome_reply"), ("outcome_publish", "outcome_publish"),
                                 ("outcome_leads", "outcome_leads"), ("outcome_revenue", "outcome_revenue")]:
                    if ev.get(fld) is not None:
                        d_sets.append(f"{col} = :{fld}")
                        d_params[fld] = ev[fld]
                if d_sets:
                    d_sets.append("updated_at = :now")
                    await session.execute(text(
                        f"UPDATE pr_decisions SET {', '.join(d_sets)} WHERE decision_id = :did"
                    ), d_params)
                    updated += len(d_sets) - 1

            results.append({"event_id": target_event_id or target_decision_id, "event_type": "outcome_update", "fields_updated": updated})
            continue

        journalist_id = None
        j_email = ev.get("journalist_email", ev.get("email"))
        j_name = ev.get("journalist_name", ev.get("journalist", ev.get("name")))
        if j_name or j_email:
            journalist_id = await upsert_journalist(
                session, name=j_name or "Unknown",
                email=j_email, publication=ev.get("publication"),
            )

        await session.execute(text("""
            INSERT INTO pr_events (
                event_id, event_type, campaign_id, journalist_id,
                journalist_name, journalist_email, publication,
                article_url, lead_id, revenue,
                utm_source, utm_campaign, utm_content,
                narrative_angle, headline_variant, email_subject,
                cta_type, journalist_score_at_send,
                metadata, timestamp, created_at
            ) VALUES (
                :eid, :etype, :cid, :jid,
                :jname, :jemail, :pub,
                :aurl, :lid, :rev,
                :usrc, :ucmp, :ucnt,
                :nangle, :hvariant, :esubject,
                :ctype, :jscore,
                CAST(:meta AS jsonb), :ts, :now
            )
        """), {
            "eid": event_id, "etype": event_type,
            "cid": ev.get("campaign_id"),
            "jid": journalist_id,
            "jname": j_name, "jemail": j_email,
            "pub": ev.get("publication"),
            "aurl": ev.get("article_url"),
            "lid": ev.get("lead_id"),
            "rev": ev.get("revenue"),
            "usrc": ev.get("utm_source"),
            "ucmp": ev.get("utm_campaign"),
            "ucnt": ev.get("utm_content"),
            "nangle": ev.get("narrative_angle"),
            "hvariant": ev.get("headline_variant"),
            "esubject": ev.get("email_subject"),
            "ctype": ev.get("cta_type"),
            "jscore": ev.get("journalist_score_at_send"),
            "meta": json_lib.dumps(ev),
            "ts": event_ts,
            "now": datetime.now(timezone.utc),
        })

        await update_counters(session, event_type, ev.get("campaign_id"), journalist_id, ev.get("revenue"))
        results.append({"event_id": event_id, "event_type": event_type})

    logger.info(f"[PR_N8N_WEBHOOK] Processed {len(results)} events")
    return {"status": "ok", "count": len(results), "events": results}


# ──────────────────────────────────────────────
# RAG-26: DECISION RECORDING
# ──────────────────────────────────────────────

@router.post("/decisions")
@limiter.limit("60/minute")
async def record_decision(
    request: Request,
    req: DecisionCreate,
    session: AsyncSession = Depends(get_db_session),
):
    """Record a PR decision (outreach choice) for predictive feature storage."""
    await ensure_tables(session)

    if req.narrative_angle and req.narrative_angle not in NARRATIVE_ANGLES:
        raise HTTPException(status_code=422, detail=f"narrative_angle must be one of: {NARRATIVE_ANGLES}")
    if req.cta_type and req.cta_type not in CTA_TYPES:
        raise HTTPException(status_code=422, detail=f"cta_type must be one of: {CTA_TYPES}")

    decision_id = str(uuid.uuid4())
    ts = datetime.fromisoformat(req.timestamp) if req.timestamp else datetime.now(timezone.utc)

    await session.execute(text("""
        INSERT INTO pr_decisions (
            decision_id, campaign_id, journalist_id,
            narrative_angle, subject_line, headline_variant,
            cta_type, journalist_score,
            utm_source, utm_campaign, utm_content,
            timestamp, created_at, updated_at
        ) VALUES (
            :did, :cid, :jid,
            :nangle, :subj, :hvariant,
            :ctype, :jscore,
            :usrc, :ucmp, :ucnt,
            :ts, :now, :now
        )
    """), {
        "did": decision_id, "cid": req.campaign_id, "jid": req.journalist_id,
        "nangle": req.narrative_angle, "subj": req.subject_line,
        "hvariant": req.headline_variant, "ctype": req.cta_type,
        "jscore": req.journalist_score or 0,
        "usrc": req.utm_source, "ucmp": req.utm_campaign, "ucnt": req.utm_content,
        "ts": ts, "now": datetime.now(timezone.utc),
    })

    logger.info(f"[PR_DECISION] id={decision_id} angle={req.narrative_angle} cta={req.cta_type}")
    return {"status": "ok", "decision_id": decision_id}


@router.patch("/decisions/{decision_id}")
async def update_decision_outcome(
    decision_id: str,
    req: DecisionOutcomeUpdate,
    session: AsyncSession = Depends(get_db_session),
):
    """Update outcome fields on an existing decision record."""
    await ensure_tables(session)

    # Verify exists
    check = await session.execute(
        text("SELECT decision_id FROM pr_decisions WHERE decision_id = :did"),
        {"did": decision_id}
    )
    if not check.fetchone():
        raise HTTPException(status_code=404, detail="Decision not found")

    sets = []
    params = {"did": decision_id, "now": datetime.now(timezone.utc)}
    if req.outcome_reply is not None:
        sets.append("outcome_reply = :reply")
        params["reply"] = req.outcome_reply
    if req.outcome_publish is not None:
        sets.append("outcome_publish = :publish")
        params["publish"] = req.outcome_publish
    if req.outcome_leads is not None:
        sets.append("outcome_leads = :leads")
        params["leads"] = req.outcome_leads
    if req.outcome_revenue is not None:
        sets.append("outcome_revenue = :rev")
        params["rev"] = req.outcome_revenue
    sets.append("updated_at = :now")

    await session.execute(
        text(f"UPDATE pr_decisions SET {', '.join(sets)} WHERE decision_id = :did"),
        params,
    )
    return {"status": "ok", "decision_id": decision_id, "updated_fields": len(sets) - 1}


# ──────────────────────────────────────────────
# RAG-26: EVENT OUTCOME UPDATES
# ──────────────────────────────────────────────

@router.patch("/events/{event_id}/outcome")
async def update_event_outcome(
    event_id: str,
    req: EventOutcomeUpdate,
    session: AsyncSession = Depends(get_db_session),
):
    """Update outcome tracking fields on an existing PR event."""
    await ensure_tables(session)

    check = await session.execute(
        text("SELECT event_id FROM pr_events WHERE event_id = :eid"),
        {"eid": event_id}
    )
    if not check.fetchone():
        raise HTTPException(status_code=404, detail="Event not found")

    sets = []
    params = {"eid": event_id}
    if req.opened is not None:
        sets.append("opened = :opened")
        params["opened"] = req.opened
    if req.replied is not None:
        sets.append("replied = :replied")
        params["replied"] = req.replied
    if req.outcome_article is not None:
        sets.append("outcome_article = :oart")
        params["oart"] = req.outcome_article
    if req.outcome_leads is not None:
        sets.append("outcome_leads = :oleads")
        params["oleads"] = req.outcome_leads
    if req.outcome_revenue is not None:
        sets.append("outcome_revenue = :orev")
        params["orev"] = req.outcome_revenue

    if not sets:
        return {"status": "ok", "message": "No fields to update"}

    await session.execute(
        text(f"UPDATE pr_events SET {', '.join(sets)} WHERE event_id = :eid"),
        params,
    )
    return {"status": "ok", "event_id": event_id, "updated_fields": len(sets)}


# ──────────────────────────────────────────────
# RAG-26: ENUM DISCOVERY (API-first)
# ──────────────────────────────────────────────

@router.get("/enums")
async def get_enums():
    """Return valid enum values for narrative_angle and cta_type. Consumers should use these to validate input."""
    return {
        "narrative_angles": NARRATIVE_ANGLES,
        "cta_types": CTA_TYPES,
    }


@router.get("/decisions")
async def list_decisions(
    campaign_id: Optional[str] = None,
    narrative_angle: Optional[str] = None,
    cta_type: Optional[str] = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
):
    """List decision records with optional filters."""
    await ensure_tables(session)

    where_parts = []
    params = {"lim": limit}
    if campaign_id:
        where_parts.append("campaign_id = :cid")
        params["cid"] = campaign_id
    if narrative_angle:
        where_parts.append("narrative_angle = :nangle")
        params["nangle"] = narrative_angle
    if cta_type:
        where_parts.append("cta_type = :ctype")
        params["ctype"] = cta_type

    where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    rows = await session.execute(text(f"""
        SELECT decision_id, campaign_id, journalist_id,
               narrative_angle, subject_line, headline_variant,
               cta_type, journalist_score,
               outcome_reply, outcome_publish, outcome_leads, outcome_revenue,
               utm_source, utm_campaign, timestamp, created_at
        FROM pr_decisions {where}
        ORDER BY timestamp DESC
        LIMIT :lim
    """), params)

    decisions = []
    for r in rows.fetchall():
        decisions.append({
            "decision_id": str(r.decision_id),
            "campaign_id": str(r.campaign_id) if r.campaign_id else None,
            "journalist_id": str(r.journalist_id) if r.journalist_id else None,
            "narrative_angle": r.narrative_angle,
            "subject_line": r.subject_line,
            "headline_variant": r.headline_variant,
            "cta_type": r.cta_type,
            "journalist_score": r.journalist_score,
            "outcome_reply": r.outcome_reply,
            "outcome_publish": r.outcome_publish,
            "outcome_leads": r.outcome_leads,
            "outcome_revenue": float(r.outcome_revenue or 0),
            "utm_source": r.utm_source,
            "utm_campaign": r.utm_campaign,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        })

    return {"decisions": decisions, "total": len(decisions)}


# ──────────────────────────────────────────────
# RAG-26: FEATURE SUMMARY AGGREGATION
# ──────────────────────────────────────────────

@router.get("/features/summary")
async def features_summary(
    days: int = 90,
    session: AsyncSession = Depends(get_db_session),
):
    """Aggregated feature summary for the Predictive Decision Engine.
    Groups decisions by narrative_angle and cta_type, computes
    reply/publish/lead/revenue rates — ready for model training."""
    await ensure_tables(session)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # ── By narrative_angle ──
    angle_rows = await session.execute(text("""
        SELECT narrative_angle,
               COUNT(*) as total_decisions,
               SUM(CASE WHEN outcome_reply THEN 1 ELSE 0 END) as replies,
               SUM(CASE WHEN outcome_publish THEN 1 ELSE 0 END) as publishes,
               COALESCE(SUM(outcome_leads), 0) as total_leads,
               COALESCE(SUM(outcome_revenue), 0) as total_revenue,
               ROUND(AVG(journalist_score), 1) as avg_journalist_score
        FROM pr_decisions
        WHERE timestamp >= :since AND narrative_angle IS NOT NULL
        GROUP BY narrative_angle
        ORDER BY total_revenue DESC
    """), {"since": since})

    by_narrative = []
    for r in angle_rows.fetchall():
        total = r.total_decisions or 1
        by_narrative.append({
            "narrative_angle": r.narrative_angle,
            "total_decisions": r.total_decisions,
            "reply_rate": round(r.replies / total * 100, 1),
            "publish_rate": round(r.publishes / total * 100, 1),
            "total_leads": r.total_leads,
            "total_revenue": float(r.total_revenue),
            "avg_journalist_score": float(r.avg_journalist_score or 0),
        })

    # ── By cta_type ──
    cta_rows = await session.execute(text("""
        SELECT cta_type,
               COUNT(*) as total_decisions,
               SUM(CASE WHEN outcome_reply THEN 1 ELSE 0 END) as replies,
               SUM(CASE WHEN outcome_publish THEN 1 ELSE 0 END) as publishes,
               COALESCE(SUM(outcome_leads), 0) as total_leads,
               COALESCE(SUM(outcome_revenue), 0) as total_revenue
        FROM pr_decisions
        WHERE timestamp >= :since AND cta_type IS NOT NULL
        GROUP BY cta_type
        ORDER BY total_revenue DESC
    """), {"since": since})

    by_cta = []
    for r in cta_rows.fetchall():
        total = r.total_decisions or 1
        by_cta.append({
            "cta_type": r.cta_type,
            "total_decisions": r.total_decisions,
            "reply_rate": round(r.replies / total * 100, 1),
            "publish_rate": round(r.publishes / total * 100, 1),
            "total_leads": r.total_leads,
            "total_revenue": float(r.total_revenue),
        })

    # ── By narrative + cta cross-tab ──
    cross_rows = await session.execute(text("""
        SELECT narrative_angle, cta_type,
               COUNT(*) as total_decisions,
               SUM(CASE WHEN outcome_reply THEN 1 ELSE 0 END) as replies,
               COALESCE(SUM(outcome_revenue), 0) as total_revenue
        FROM pr_decisions
        WHERE timestamp >= :since
          AND narrative_angle IS NOT NULL AND cta_type IS NOT NULL
        GROUP BY narrative_angle, cta_type
        ORDER BY total_revenue DESC
        LIMIT 20
    """), {"since": since})

    cross_tab = []
    for r in cross_rows.fetchall():
        total = r.total_decisions or 1
        cross_tab.append({
            "narrative_angle": r.narrative_angle,
            "cta_type": r.cta_type,
            "total_decisions": r.total_decisions,
            "reply_rate": round(r.replies / total * 100, 1),
            "total_revenue": float(r.total_revenue),
        })

    # ── Event-level outcome stats (from pr_events) ──
    event_stats = await session.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE narrative_angle IS NOT NULL) as tagged_events,
            COUNT(*) FILTER (WHERE opened) as opened_count,
            COUNT(*) FILTER (WHERE replied) as replied_count,
            COUNT(*) FILTER (WHERE outcome_article) as article_count,
            COALESCE(SUM(outcome_leads), 0) as total_event_leads,
            COALESCE(SUM(outcome_revenue), 0) as total_event_revenue
        FROM pr_events
        WHERE timestamp >= :since
    """), {"since": since})
    es = event_stats.fetchone()

    # ── Overall readiness stats ──
    decision_count = await session.execute(text(
        "SELECT COUNT(*) as cnt FROM pr_decisions WHERE timestamp >= :since"
    ), {"since": since})
    dc = decision_count.fetchone()

    return {
        "period_days": days,
        "readiness": {
            "total_decisions": dc.cnt if dc else 0,
            "tagged_events": es.tagged_events if es else 0,
            "prediction_ready": (dc.cnt if dc else 0) >= 50,
            "message": "Collect 50+ decisions with outcomes to enable predictive model training" if (dc.cnt if dc else 0) < 50 else "Sufficient data for model training",
        },
        "by_narrative_angle": by_narrative,
        "by_cta_type": by_cta,
        "cross_tab": cross_tab,
        "event_outcome_stats": {
            "opened": es.opened_count if es else 0,
            "replied": es.replied_count if es else 0,
            "articles": es.article_count if es else 0,
            "leads": es.total_event_leads if es else 0,
            "revenue": float(es.total_event_revenue) if es else 0,
        },
    }



# ──────────────────────────────────────────────
# RAG-26: PR SIMULATOR (Historical Decision Support)
# ──────────────────────────────────────────────

class SimulatorRequest(BaseModel):
    journalist_id: Optional[str] = None
    publication: Optional[str] = None
    narrative_angle: Optional[str] = None
    cta_type: Optional[str] = None


def _confidence_label(n: int) -> dict:
    if n < 5:
        return {"level": "insufficient", "label": "Insufficient data — results unreliable", "min_recommended": 5}
    if n < 20:
        return {"level": "low", "label": "Low confidence — limited sample size", "min_recommended": 20}
    if n < 50:
        return {"level": "moderate", "label": "Moderate confidence — interpret with caution", "min_recommended": 50}
    return {"level": "high", "label": "High confidence — reliable historical pattern", "min_recommended": 50}


@router.post("/simulator")
async def pr_simulator(
    req: SimulatorRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Historical decision support tool. Returns past performance for a
    journalist / publication / narrative / CTA combination.
    No prediction — purely historical aggregation with confidence labels."""
    await ensure_tables(session)

    if req.narrative_angle and req.narrative_angle not in NARRATIVE_ANGLES:
        raise HTTPException(status_code=422, detail=f"narrative_angle must be one of: {NARRATIVE_ANGLES}")
    if req.cta_type and req.cta_type not in CTA_TYPES:
        raise HTTPException(status_code=422, detail=f"cta_type must be one of: {CTA_TYPES}")

    # ── Build dynamic WHERE from inputs ──
    where_parts = []
    params = {}

    if req.journalist_id:
        where_parts.append("d.journalist_id = :jid")
        params["jid"] = req.journalist_id
    if req.publication:
        where_parts.append("j.publication ILIKE :pub")
        params["pub"] = f"%{req.publication}%"
    if req.narrative_angle:
        where_parts.append("d.narrative_angle = :nangle")
        params["nangle"] = req.narrative_angle
    if req.cta_type:
        where_parts.append("d.cta_type = :ctype")
        params["ctype"] = req.cta_type

    if not where_parts:
        raise HTTPException(status_code=422, detail="Provide at least one filter: journalist_id, publication, narrative_angle, or cta_type")

    where_clause = " AND ".join(where_parts)

    # ── Primary query: exact match ──
    row = await session.execute(text(f"""
        SELECT
            COUNT(*) as sample_size,
            SUM(CASE WHEN d.outcome_reply THEN 1 ELSE 0 END) as replies,
            SUM(CASE WHEN d.outcome_publish THEN 1 ELSE 0 END) as publishes,
            COALESCE(SUM(d.outcome_leads), 0) as total_leads,
            COALESCE(SUM(d.outcome_revenue), 0) as total_revenue,
            ROUND(AVG(d.journalist_score), 1) as avg_score
        FROM pr_decisions d
        LEFT JOIN pr_journalists j ON j.journalist_id = d.journalist_id
        WHERE {where_clause}
    """), params)
    r = row.fetchone()
    n = r.sample_size if r else 0
    confidence = _confidence_label(n)

    result = {
        "query": {
            "journalist_id": req.journalist_id,
            "publication": req.publication,
            "narrative_angle": req.narrative_angle,
            "cta_type": req.cta_type,
        },
        "sample_size": n,
        "confidence": confidence,
    }

    if n == 0:
        result["historical_rates"] = None
        result["message"] = "No historical data matches this combination. Try broadening your filters."

        # ── Fallback: suggest closest matches ──
        suggestions = []
        if req.narrative_angle:
            s_row = await session.execute(text("""
                SELECT narrative_angle, COUNT(*) as cnt,
                       ROUND((SUM(CASE WHEN outcome_reply THEN 1 ELSE 0 END)::NUMERIC / GREATEST(COUNT(*), 1) * 100), 1) as reply_rate
                FROM pr_decisions WHERE narrative_angle IS NOT NULL
                GROUP BY narrative_angle ORDER BY cnt DESC LIMIT 3
            """))
            for s in s_row.fetchall():
                suggestions.append({"type": "narrative_angle", "value": s.narrative_angle,
                                    "sample_size": s.cnt, "reply_rate": float(s.reply_rate)})
        if req.cta_type:
            s_row = await session.execute(text("""
                SELECT cta_type, COUNT(*) as cnt,
                       ROUND((SUM(CASE WHEN outcome_reply THEN 1 ELSE 0 END)::NUMERIC / GREATEST(COUNT(*), 1) * 100), 1) as reply_rate
                FROM pr_decisions WHERE cta_type IS NOT NULL
                GROUP BY cta_type ORDER BY cnt DESC LIMIT 3
            """))
            for s in s_row.fetchall():
                suggestions.append({"type": "cta_type", "value": s.cta_type,
                                    "sample_size": s.cnt, "reply_rate": float(s.reply_rate)})
        result["suggestions"] = suggestions
        return result

    total = max(n, 1)
    result["historical_rates"] = {
        "reply_rate": round((r.replies or 0) / total * 100, 1),
        "publish_rate": round((r.publishes or 0) / total * 100, 1),
        "total_leads": r.total_leads or 0,
        "total_revenue": float(r.total_revenue or 0),
        "avg_revenue_per_decision": round(float(r.total_revenue or 0) / total, 2),
        "avg_journalist_score": float(r.avg_score or 0),
    }

    # ── Comparison: how does this combo compare to global average? ──
    global_row = await session.execute(text("""
        SELECT COUNT(*) as cnt,
               SUM(CASE WHEN outcome_reply THEN 1 ELSE 0 END) as replies,
               SUM(CASE WHEN outcome_publish THEN 1 ELSE 0 END) as publishes,
               COALESCE(SUM(outcome_revenue), 0) as revenue
        FROM pr_decisions
    """))
    g = global_row.fetchone()
    g_total = max(g.cnt, 1) if g else 1
    global_reply = round((g.replies or 0) / g_total * 100, 1)
    global_publish = round((g.publishes or 0) / g_total * 100, 1)

    combo_reply = result["historical_rates"]["reply_rate"]
    combo_publish = result["historical_rates"]["publish_rate"]

    result["vs_global"] = {
        "global_reply_rate": global_reply,
        "global_publish_rate": global_publish,
        "reply_delta": round(combo_reply - global_reply, 1),
        "publish_delta": round(combo_publish - global_publish, 1),
        "global_sample_size": g.cnt if g else 0,
    }

    return result


# ──────────────────────────────────────────────
# RAG-26: NIGHTLY BATCH REFRESH
# ──────────────────────────────────────────────

async def run_nightly_feature_refresh():
    """Nightly job: recompute feature summary and store snapshot in pr_ai_analysis."""
    from app.api.deps import get_db_session as _get_session

    logger.info("[PR_NIGHTLY] Starting feature summary refresh")

    async for session in _get_session():
        try:
            await ensure_tables(session)
            since = datetime.now(timezone.utc) - timedelta(days=90)

            # Recompute journalist scores
            await session.execute(text("""
                UPDATE pr_journalists SET
                    score = LEAST(100, GREATEST(0,
                        (CASE WHEN total_pitches > 0 THEN (total_responses::FLOAT / total_pitches * 25) ELSE 0 END) +
                        (CASE WHEN total_pitches > 0 THEN (total_articles::FLOAT / total_pitches * 30) ELSE 0 END) +
                        (LEAST(total_leads, 10) * 2.5) +
                        (LEAST(total_revenue::FLOAT / GREATEST(1, 1000), 1) * 20)
                    )::INT),
                    priority = CASE
                        WHEN (CASE WHEN total_pitches > 0 THEN (total_responses::FLOAT / total_pitches * 25) ELSE 0 END) +
                             (CASE WHEN total_pitches > 0 THEN (total_articles::FLOAT / total_pitches * 30) ELSE 0 END) +
                             (LEAST(total_leads, 10) * 2.5) +
                             (LEAST(total_revenue::FLOAT / GREATEST(1, 1000), 1) * 20) >= 60 THEN 'high'
                        WHEN (CASE WHEN total_pitches > 0 THEN (total_responses::FLOAT / total_pitches * 25) ELSE 0 END) +
                             (CASE WHEN total_pitches > 0 THEN (total_articles::FLOAT / total_pitches * 30) ELSE 0 END) +
                             (LEAST(total_leads, 10) * 2.5) +
                             (LEAST(total_revenue::FLOAT / GREATEST(1, 1000), 1) * 20) >= 30 THEN 'medium'
                        ELSE 'low'
                    END,
                    updated_at = NOW()
                WHERE total_pitches > 0 OR total_responses > 0 OR total_articles > 0
            """))

            # Compute snapshot
            dc_row = await session.execute(text(
                "SELECT COUNT(*) as cnt FROM pr_decisions WHERE timestamp >= :since"
            ), {"since": since})
            dc = dc_row.fetchone()

            angle_rows = await session.execute(text("""
                SELECT narrative_angle,
                       COUNT(*) as total,
                       SUM(CASE WHEN outcome_reply THEN 1 ELSE 0 END) as replies,
                       COALESCE(SUM(outcome_revenue), 0) as revenue
                FROM pr_decisions
                WHERE timestamp >= :since AND narrative_angle IS NOT NULL
                GROUP BY narrative_angle ORDER BY revenue DESC
            """), {"since": since})

            cta_rows = await session.execute(text("""
                SELECT cta_type,
                       COUNT(*) as total,
                       SUM(CASE WHEN outcome_reply THEN 1 ELSE 0 END) as replies,
                       COALESCE(SUM(outcome_revenue), 0) as revenue
                FROM pr_decisions
                WHERE timestamp >= :since AND cta_type IS NOT NULL
                GROUP BY cta_type ORDER BY revenue DESC
            """), {"since": since})

            snapshot = {
                "total_decisions": dc.cnt if dc else 0,
                "prediction_ready": (dc.cnt if dc else 0) >= 50,
                "by_narrative": [{"angle": r.narrative_angle, "n": r.total,
                                  "reply_rate": round(r.replies / max(r.total, 1) * 100, 1),
                                  "revenue": float(r.revenue)} for r in angle_rows.fetchall()],
                "by_cta": [{"cta": r.cta_type, "n": r.total,
                            "reply_rate": round(r.replies / max(r.total, 1) * 100, 1),
                            "revenue": float(r.revenue)} for r in cta_rows.fetchall()],
                "refreshed_at": datetime.now(timezone.utc).isoformat(),
            }

            aid = str(uuid.uuid4())
            await session.execute(text("""
                INSERT INTO pr_ai_analysis (analysis_id, analysis_type, target_type, result, created_at)
                VALUES (:aid, 'feature_refresh', 'nightly', CAST(:result AS jsonb), :now)
            """), {"aid": aid, "result": json_lib.dumps(snapshot), "now": datetime.now(timezone.utc)})

            logger.info(f"[PR_NIGHTLY] Feature refresh complete — {dc.cnt if dc else 0} decisions, snapshot={aid}")
        except Exception as e:
            logger.error(f"[PR_NIGHTLY] Feature refresh failed: {e}")


def start_pr_nightly_scheduler():
    """Register the nightly batch job with APScheduler."""
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            run_nightly_feature_refresh,
            CronTrigger(hour=0, minute=0),
            id="pr_nightly_feature_refresh",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("[PR_NIGHTLY] Scheduler registered — runs daily at 00:00 UTC")
    except ImportError:
        logger.warning("[PR_NIGHTLY] apscheduler not available — nightly refresh disabled")
    except Exception as e:
        logger.error(f"[PR_NIGHTLY] Scheduler setup failed: {e}")


@router.post("/features/refresh")
@limiter.limit("5/minute")
async def manual_feature_refresh(request: Request):
    """Manually trigger a feature summary refresh (same as nightly batch)."""
    await run_nightly_feature_refresh()
    return {"status": "ok", "message": "Feature refresh completed"}
