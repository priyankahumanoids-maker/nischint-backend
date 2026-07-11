"""NISCH-009 — Guardian Feedback Loop tests.

Live-PG against the real Neon instance. Each test self-cleans.
Patterned after `test_incidents_feed.py`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine,
)

from app.api.incident_feedback import (
    FeedbackIn, get_incident_feedback, submit_incident_feedback,
)
from app.models.safety_incident import SafetyIncident
from app.services.feedback_aggregator import (
    CONFIDENCE_DELTA_DOWN, CONFIDENCE_DELTA_UP, CONFIDENCE_THRESHOLD_VOTES,
    _classify, apply_feedback_decision,
)


def _db_url() -> str:
    from app.core.config import settings
    url = settings.database_url or ""
    if not url:
        pytest.skip("database_url not set")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if "sslmode=" in url:
        url = url.split("?")[0]
    return url


@pytest_asyncio.fixture
async def db():
    eng = create_async_engine(_db_url(), poolclass=NullPool,
                              connect_args={"ssl": True})
    factory = async_sessionmaker(eng, expire_on_commit=False)
    yield factory
    await eng.dispose()


# ── Seed helpers ────────────────────────────────────────────────────
async def _seed_user(s: AsyncSession, role: str = "guardian") -> uuid.UUID:
    uid = uuid.uuid4()
    await s.execute(text("""
        INSERT INTO users (id, email, full_name, role, password_hash,
                           preferred_channels, created_at)
        VALUES (:id, :email, :name, :role, 'x',
                '["push"]'::json, now())
    """), {"id": str(uid),
           "email": f"f+{uid}@nischint.test",
           "name": f"User {uid.hex[:8]}",
           "role": role})
    return uid


async def _seed_relationship(s: AsyncSession, guardian_id: uuid.UUID,
                              child_id: uuid.UUID) -> None:
    await s.execute(text("""
        INSERT INTO relationships (id, guardian_id, child_id, status, created_at)
        VALUES (:id, :gid, :cid, 'accepted', now())
    """), {"id": str(uuid.uuid4()),
           "gid": str(guardian_id), "cid": str(child_id)})


async def _seed_incident(s: AsyncSession, child_id: uuid.UUID,
                          *, state: str = "escalated",
                          confidence: float = 0.80) -> uuid.UUID:
    iid = uuid.uuid4()
    s.add(SafetyIncident(
        id=iid, child_id=child_id,
        incident_type="voice_distress", severity="high",
        state=state, confidence=confidence,
        sla_degraded_at_dispatch=False, escalation_level=1,
    ))
    await s.flush()
    return iid


async def _cleanup(s: AsyncSession, **ids):
    # incident_feedback FK CASCADE wipes its rows when the incident dies,
    # but be explicit so partial-fail tests still clean up.
    for iid in ids.get("incident_ids", []):
        await s.execute(text(
            "DELETE FROM incident_feedback WHERE incident_id = :id"
        ), {"id": str(iid)})
        await s.execute(text(
            "DELETE FROM safety_incident_events WHERE incident_id = :id"
        ), {"id": str(iid)})
        await s.execute(text(
            "DELETE FROM safety_incidents WHERE id = :id"
        ), {"id": str(iid)})
    for uid in ids.get("user_ids", []):
        await s.execute(text(
            "DELETE FROM relationships WHERE guardian_id = :id OR child_id = :id"
        ), {"id": str(uid)})
        await s.execute(text(
            "DELETE FROM incident_feedback WHERE guardian_id = :id"
        ), {"id": str(uid)})
        await s.execute(text("DELETE FROM users WHERE id = :id"),
                        {"id": str(uid)})
    await s.commit()


def _u(uid: uuid.UUID, role: str):
    return type("U", (), {"id": uid, "role": role})()


# ════════════════════════════════════════════════════════════════════
# Pure unit tests on the threshold engine — no DB needed
# ════════════════════════════════════════════════════════════════════

def test_classify_below_threshold_returns_none():
    """1 confirm_risk + 0 mark_safe → None (below threshold of 2)."""
    assert _classify({"confirm_risk": 1}) is None
    assert _classify({"mark_safe": 1}) is None


def test_classify_threshold_risk():
    """≥2 confirm_risk AND zero mark_safe → 'risk'."""
    assert _classify({"confirm_risk": 2}) == "risk"
    assert _classify({"confirm_risk": 5}) == "risk"


def test_classify_threshold_safe():
    """≥2 mark_safe AND zero confirm_risk → 'safe'."""
    assert _classify({"mark_safe": 2}) == "safe"


def test_classify_disagreement_holds():
    """Even one opposing vote nullifies — defends against noisy crowds."""
    assert _classify({"confirm_risk": 5, "mark_safe": 1}) is None
    assert _classify({"confirm_risk": 1, "mark_safe": 5}) is None


def test_classify_anomaly_does_not_trigger():
    """report_anomaly never moves confidence — it's a flag, not a vote."""
    assert _classify({"report_anomaly": 5}) is None
    assert _classify({"confirm_risk": 1, "report_anomaly": 5}) is None


def test_constants_locked():
    """Public constants must remain stable — they're tested externally."""
    assert CONFIDENCE_THRESHOLD_VOTES == 2
    assert CONFIDENCE_DELTA_UP   == 0.10
    assert CONFIDENCE_DELTA_DOWN == 0.15


# ════════════════════════════════════════════════════════════════════
# Endpoint tests — closed-network gate, UPSERT, aggregation
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_unlinked_guardian_gets_403(db):
    """Stranger with NO Relationship row must be rejected — closed
    network only, no anonymous reports."""
    async with db() as s:
        stranger = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user")
        iid = await _seed_incident(s, child)
        await s.commit()

    async with db() as s:
        with pytest.raises(HTTPException) as exc:
            await submit_incident_feedback(
                incident_id=iid,
                body=FeedbackIn(verdict="mark_safe"),
                session=s, user=_u(stranger, "guardian"),
            )
        assert exc.value.status_code == 403

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[stranger, child])


@pytest.mark.asyncio
async def test_admin_bypasses_relationship_gate(db):
    """Admin role can submit feedback even without a Relationship row."""
    async with db() as s:
        admin = await _seed_user(s, "admin")
        child = await _seed_user(s, "user")
        iid = await _seed_incident(s, child)
        await s.commit()

    async with db() as s:
        out = await submit_incident_feedback(
            incident_id=iid,
            body=FeedbackIn(verdict="confirm_risk"),
            session=s, user=_u(admin, "admin"),
        )
    assert out["feedback"]["verdict"] == "confirm_risk"

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[admin, child])


@pytest.mark.asyncio
async def test_invalid_verdict_400(db):
    async with db() as s:
        guardian = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user")
        await _seed_relationship(s, guardian, child)
        iid = await _seed_incident(s, child)
        await s.commit()

    async with db() as s:
        with pytest.raises(HTTPException) as exc:
            await submit_incident_feedback(
                incident_id=iid,
                body=FeedbackIn(verdict="not_a_verdict"),
                session=s, user=_u(guardian, "guardian"),
            )
        assert exc.value.status_code == 400

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[guardian, child])


@pytest.mark.asyncio
async def test_unknown_incident_404(db):
    async with db() as s:
        guardian = await _seed_user(s, "guardian")
        await s.commit()
    async with db() as s:
        with pytest.raises(HTTPException) as exc:
            await submit_incident_feedback(
                incident_id=uuid.uuid4(),  # never inserted
                body=FeedbackIn(verdict="mark_safe"),
                session=s, user=_u(guardian, "guardian"),
            )
        assert exc.value.status_code == 404
    async with db() as s:
        await _cleanup(s, user_ids=[guardian])


@pytest.mark.asyncio
async def test_upsert_latest_wins(db):
    """A guardian can change their verdict — UPSERT semantics. The
    aggregate counts must reflect the LATEST verdict, not double-count."""
    async with db() as s:
        guardian = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user")
        await _seed_relationship(s, guardian, child)
        iid = await _seed_incident(s, child)
        await s.commit()

    async with db() as s:
        await submit_incident_feedback(
            incident_id=iid,
            body=FeedbackIn(verdict="confirm_risk"),
            session=s, user=_u(guardian, "guardian"),
        )
        await s.commit()
    async with db() as s:
        out = await submit_incident_feedback(
            incident_id=iid,
            body=FeedbackIn(verdict="mark_safe"),
            session=s, user=_u(guardian, "guardian"),
        )
        await s.commit()

    assert out["feedback"]["is_update"] is True
    assert out["aggregate"]["counts"]["mark_safe"] == 1
    assert out["aggregate"]["counts"]["confirm_risk"] == 0

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[guardian, child])


@pytest.mark.asyncio
async def test_threshold_risk_bumps_confidence(db):
    """2 confirm_risk votes from different guardians (no opposing) →
    confidence bumps by +0.10 (anchored, capped at 0.99)."""
    async with db() as s:
        g1 = await _seed_user(s, "guardian")
        g2 = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user")
        await _seed_relationship(s, g1, child)
        await _seed_relationship(s, g2, child)
        iid = await _seed_incident(s, child, confidence=0.70)
        await s.commit()

    async with db() as s:
        await submit_incident_feedback(
            incident_id=iid, body=FeedbackIn(verdict="confirm_risk"),
            session=s, user=_u(g1, "guardian"),
        )
        await s.commit()
    async with db() as s:
        out = await submit_incident_feedback(
            incident_id=iid, body=FeedbackIn(verdict="confirm_risk"),
            session=s, user=_u(g2, "guardian"),
        )
        await s.commit()

    assert out["aggregate"]["classification"] == "risk"
    # Anchor was 0.70, bump +0.10 → 0.80
    assert abs(out["aggregate"]["confidence_after"] - 0.80) < 1e-9
    assert out["aggregate"]["auto_resolved"] is False

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[g1, g2, child])


@pytest.mark.asyncio
async def test_threshold_safe_auto_resolves(db):
    """2 mark_safe votes (no opposing) → confidence drops AND incident
    auto-transitions to RESOLVED via the state machine."""
    async with db() as s:
        g1 = await _seed_user(s, "guardian")
        g2 = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user")
        await _seed_relationship(s, g1, child)
        await _seed_relationship(s, g2, child)
        iid = await _seed_incident(s, child, state="escalated", confidence=0.80)
        await s.commit()

    async with db() as s:
        await submit_incident_feedback(
            incident_id=iid, body=FeedbackIn(verdict="mark_safe"),
            session=s, user=_u(g1, "guardian"),
        )
        await s.commit()
    async with db() as s:
        out = await submit_incident_feedback(
            incident_id=iid, body=FeedbackIn(verdict="mark_safe"),
            session=s, user=_u(g2, "guardian"),
        )
        await s.commit()

    assert out["aggregate"]["classification"] == "safe"
    # Anchor was 0.80, drop 0.15 → 0.65
    assert abs(out["aggregate"]["confidence_after"] - 0.65) < 1e-9
    assert out["aggregate"]["auto_resolved"] is True
    assert out["aggregate"]["current_state"] == "resolved"

    # Forensic trail: must have a community_feedback transition row.
    async with db() as s:
        rows = (await s.execute(text("""
            SELECT actor_type, from_state, to_state
            FROM safety_incident_events WHERE incident_id = :id
            ORDER BY created_at ASC
        """), {"id": str(iid)})).all()
    actor_types = [r[0] for r in rows]
    assert "guardian_feedback" in actor_types  # the votes
    assert "community_feedback" in actor_types  # the auto-resolve

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[g1, g2, child])


@pytest.mark.asyncio
async def test_disagreement_holds_confidence(db):
    """1 risk + 1 safe → no classification, confidence unchanged."""
    async with db() as s:
        g1 = await _seed_user(s, "guardian")
        g2 = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user")
        await _seed_relationship(s, g1, child)
        await _seed_relationship(s, g2, child)
        iid = await _seed_incident(s, child, confidence=0.75)
        await s.commit()

    async with db() as s:
        await submit_incident_feedback(
            incident_id=iid, body=FeedbackIn(verdict="confirm_risk"),
            session=s, user=_u(g1, "guardian"),
        )
        await s.commit()
    async with db() as s:
        out = await submit_incident_feedback(
            incident_id=iid, body=FeedbackIn(verdict="mark_safe"),
            session=s, user=_u(g2, "guardian"),
        )
        await s.commit()

    assert out["aggregate"]["classification"] is None
    # Confidence unchanged from anchor.
    assert out["aggregate"]["confidence_after"] == 0.75
    assert out["aggregate"]["auto_resolved"] is False

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[g1, g2, child])


@pytest.mark.asyncio
async def test_anomaly_votes_never_trigger_threshold(db):
    """5 report_anomaly votes — confidence stays put, no auto-resolve."""
    async with db() as s:
        guardians = [await _seed_user(s, "guardian") for _ in range(5)]
        child = await _seed_user(s, "user")
        for g in guardians:
            await _seed_relationship(s, g, child)
        iid = await _seed_incident(s, child, confidence=0.80)
        await s.commit()

    out = None
    for g in guardians:
        async with db() as s:
            out = await submit_incident_feedback(
                incident_id=iid, body=FeedbackIn(verdict="report_anomaly"),
                session=s, user=_u(g, "guardian"),
            )
            await s.commit()

    assert out is not None
    assert out["aggregate"]["classification"] is None
    assert out["aggregate"]["confidence_after"] == 0.80
    assert out["aggregate"]["auto_resolved"] is False
    assert out["aggregate"]["counts"]["report_anomaly"] == 5

    async with db() as s:
        await _cleanup(s, incident_ids=[iid],
                       user_ids=[*guardians, child])


@pytest.mark.asyncio
async def test_get_endpoint_returns_counts_and_own_verdict(db):
    """GET /feedback returns aggregated counts AND the caller's own
    verdict so the UI can render "you voted: …" without an extra call."""
    async with db() as s:
        g1 = await _seed_user(s, "guardian")
        g2 = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user")
        await _seed_relationship(s, g1, child)
        await _seed_relationship(s, g2, child)
        iid = await _seed_incident(s, child)
        await s.commit()

    async with db() as s:
        await submit_incident_feedback(
            incident_id=iid, body=FeedbackIn(verdict="confirm_risk"),
            session=s, user=_u(g1, "guardian"),
        )
        await s.commit()
    async with db() as s:
        await submit_incident_feedback(
            incident_id=iid, body=FeedbackIn(verdict="report_anomaly"),
            session=s, user=_u(g2, "guardian"),
        )
        await s.commit()

    async with db() as s:
        out_g1 = await get_incident_feedback(
            incident_id=iid, session=s, user=_u(g1, "guardian"),
        )
        out_g2 = await get_incident_feedback(
            incident_id=iid, session=s, user=_u(g2, "guardian"),
        )

    assert out_g1["counts"]["confirm_risk"] == 1
    assert out_g1["counts"]["report_anomaly"] == 1
    assert out_g1["total"] == 2
    assert out_g1["own_verdict"]["verdict"] == "confirm_risk"
    assert out_g2["own_verdict"]["verdict"] == "report_anomaly"

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[g1, g2, child])


@pytest.mark.asyncio
async def test_archived_incident_rejects_feedback(db):
    """Archived incidents are terminal — feedback no longer moves the
    AI loop, so the API rejects with 409."""
    async with db() as s:
        guardian = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user")
        await _seed_relationship(s, guardian, child)
        iid = await _seed_incident(s, child, state="archived")
        await s.commit()

    async with db() as s:
        with pytest.raises(HTTPException) as exc:
            await submit_incident_feedback(
                incident_id=iid, body=FeedbackIn(verdict="mark_safe"),
                session=s, user=_u(guardian, "guardian"),
            )
        assert exc.value.status_code == 409

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[guardian, child])


@pytest.mark.asyncio
async def test_idempotent_aggregate_on_double_apply(db):
    """If `apply_feedback_decision` is invoked twice on the same vote
    set, confidence must converge — not drift further."""
    async with db() as s:
        g1 = await _seed_user(s, "guardian")
        g2 = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user")
        await _seed_relationship(s, g1, child)
        await _seed_relationship(s, g2, child)
        iid = await _seed_incident(s, child, confidence=0.50)
        await s.commit()

    async with db() as s:
        await submit_incident_feedback(
            incident_id=iid, body=FeedbackIn(verdict="confirm_risk"),
            session=s, user=_u(g1, "guardian"),
        )
        await s.commit()
    async with db() as s:
        out_first = await submit_incident_feedback(
            incident_id=iid, body=FeedbackIn(verdict="confirm_risk"),
            session=s, user=_u(g2, "guardian"),
        )
        await s.commit()

    # Now manually re-apply the aggregator. Confidence should not move.
    async with db() as s:
        inc = (await s.execute(text(
            "SELECT id, state, confidence, extra FROM safety_incidents "
            "WHERE id = :id"
        ), {"id": str(iid)})).one()
        confidence_before_replay = float(inc[2])
        # Reattach via ORM
        from sqlalchemy import select
        loaded = (await s.execute(
            select(SafetyIncident).where(SafetyIncident.id == iid)
        )).scalar_one()
        decision = await apply_feedback_decision(s, loaded, actor_id=g1)
        await s.commit()

    assert decision["confidence_after"] == out_first["aggregate"]["confidence_after"]
    assert decision["confidence_after"] == confidence_before_replay

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[g1, g2, child])
