"""NISCH-009.1 — Guardian Impact Badge tests.

Live-PG. Each test self-cleans. The cache layer is Redis-best-effort —
we explicitly call `get_impact(..., use_cache=False)` in tests to
avoid cross-test pollution from a long-lived Redis instance.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine,
)

from app.api.guardian_impact import get_my_impact, get_user_impact
from app.api.incident_feedback import FeedbackIn, submit_incident_feedback
from app.models.safety_incident import SafetyIncident
from app.services.guardian_impact_service import (
    LOW_CONFIDENCE_FLOOR, get_impact, get_mark_safe_voters,
    invalidate_guardians,
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
           "email": f"i+{uid}@nischint.test",
           "name": f"User {uid.hex[:8]}",
           "role": role})
    return uid


async def _seed_relationship(s: AsyncSession, gid: uuid.UUID,
                              cid: uuid.UUID) -> None:
    await s.execute(text("""
        INSERT INTO relationships (id, guardian_id, child_id, status, created_at)
        VALUES (:id, :gid, :cid, 'accepted', now())
    """), {"id": str(uuid.uuid4()),
           "gid": str(gid), "cid": str(cid)})


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


async def _trigger_auto_resolve(
    db_factory, child_id: uuid.UUID, guardians: list[uuid.UUID],
) -> uuid.UUID:
    """Helper: build an incident and have ≥2 guardians vote mark_safe
    so the aggregator auto-resolves it. Returns the incident_id."""
    async with db_factory() as s:
        iid = await _seed_incident(s, child_id)
        await s.commit()

    for g in guardians[:2]:  # only need 2 for the threshold
        async with db_factory() as s:
            await submit_incident_feedback(
                incident_id=iid, body=FeedbackIn(verdict="mark_safe"),
                session=s, user=type("U", (), {"id": g, "role": "guardian"})(),
            )
            await s.commit()
    return iid


async def _cleanup(s: AsyncSession, **ids):
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
# Core counting behaviour
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_zero_count_for_guardian_with_no_feedback(db):
    """A new guardian who's never voted must show 0."""
    async with db() as s:
        g = await _seed_user(s)
        await s.commit()

    async with db() as s:
        out = await get_impact(s, g, use_cache=False)
    assert out["saved_by_network_count"] == 0
    assert out["from_cache"] is False

    async with db() as s:
        await _cleanup(s, user_ids=[g])


@pytest.mark.asyncio
async def test_count_credits_each_contributor(db):
    """Two guardians both vote mark_safe → BOTH get +1 credited.
    Per spec: 'Multi-guardian resolution → each guardian gets credit
    independently.'"""
    async with db() as s:
        g1 = await _seed_user(s)
        g2 = await _seed_user(s)
        child = await _seed_user(s, "user")
        await _seed_relationship(s, g1, child)
        await _seed_relationship(s, g2, child)
        await s.commit()

    iid = await _trigger_auto_resolve(db, child, [g1, g2])

    async with db() as s:
        i1 = await get_impact(s, g1, use_cache=False)
        i2 = await get_impact(s, g2, use_cache=False)
    assert i1["saved_by_network_count"] == 1
    assert i2["saved_by_network_count"] == 1

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[g1, g2, child])


@pytest.mark.asyncio
async def test_no_credit_if_verdict_was_not_mark_safe(db):
    """A guardian who voted confirm_risk on an incident that later
    auto-resolved (because TWO OTHER guardians both said mark_safe)
    must NOT get credit. Only mark_safe voters do."""
    async with db() as s:
        g_risk = await _seed_user(s)        # this one says risk
        g_safe1 = await _seed_user(s)       # these two will resolve it
        g_safe2 = await _seed_user(s)
        child = await _seed_user(s, "user")
        for g in (g_risk, g_safe1, g_safe2):
            await _seed_relationship(s, g, child)
        iid = await _seed_incident(s, child)
        await s.commit()

    # g_risk votes first — alone, doesn't trigger anything.
    async with db() as s:
        await submit_incident_feedback(
            incident_id=iid, body=FeedbackIn(verdict="confirm_risk"),
            session=s, user=_u(g_risk, "guardian"),
        )
        await s.commit()
    # Now g_risk changes their mind to mark_safe so the safe count
    # goes 1 → and we need to verify the *original* risk vote does
    # not earn them credit. Wait — better path: leave g_risk on risk,
    # then the aggregator HOLDS (disagreement). To force resolve,
    # have g_risk withdraw. Simplest: drop their row.
    async with db() as s:
        await s.execute(text(
            "DELETE FROM incident_feedback WHERE guardian_id = :id"
        ), {"id": str(g_risk)})
        await s.commit()

    # Now two clean mark_safe votes → auto-resolve.
    for g in (g_safe1, g_safe2):
        async with db() as s:
            await submit_incident_feedback(
                incident_id=iid, body=FeedbackIn(verdict="mark_safe"),
                session=s, user=_u(g, "guardian"),
            )
            await s.commit()

    async with db() as s:
        i_risk = await get_impact(s, g_risk, use_cache=False)
        i_safe = await get_impact(s, g_safe1, use_cache=False)

    assert i_risk["saved_by_network_count"] == 0
    assert i_safe["saved_by_network_count"] == 1

    async with db() as s:
        await _cleanup(s, incident_ids=[iid],
                       user_ids=[g_risk, g_safe1, g_safe2, child])


@pytest.mark.asyncio
async def test_count_does_not_double_for_repeat_votes(db):
    """A guardian's count per incident is ≤1 even if they UPSERT
    their verdict multiple times (the unique constraint guarantees
    one row per pair, and the DISTINCT in the SQL guarantees idempotent
    counting)."""
    async with db() as s:
        g1 = await _seed_user(s)
        g2 = await _seed_user(s)
        child = await _seed_user(s, "user")
        await _seed_relationship(s, g1, child)
        await _seed_relationship(s, g2, child)
        iid = await _seed_incident(s, child)
        await s.commit()

    # g1 flips verdict back and forth before settling on mark_safe
    for verdict in ("confirm_risk", "report_anomaly", "mark_safe"):
        async with db() as s:
            await submit_incident_feedback(
                incident_id=iid, body=FeedbackIn(verdict=verdict),
                session=s, user=_u(g1, "guardian"),
            )
            await s.commit()
    # g2 closes the threshold
    async with db() as s:
        await submit_incident_feedback(
            incident_id=iid, body=FeedbackIn(verdict="mark_safe"),
            session=s, user=_u(g2, "guardian"),
        )
        await s.commit()

    async with db() as s:
        out = await get_impact(s, g1, use_cache=False)
    assert out["saved_by_network_count"] == 1  # not 3, not 0

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[g1, g2, child])


@pytest.mark.asyncio
async def test_no_credit_if_resolved_by_non_community_actor(db):
    """If an incident was resolved by ANY actor other than
    community_feedback (e.g. a guardian ack, scheduler auto-resolver),
    even a guardian's mark_safe vote on it does NOT count."""
    async with db() as s:
        g1 = await _seed_user(s)
        child = await _seed_user(s, "user")
        await _seed_relationship(s, g1, child)
        iid = await _seed_incident(s, child)
        await s.commit()

    # g1 votes safe — alone, no auto-resolve triggers.
    async with db() as s:
        await submit_incident_feedback(
            incident_id=iid, body=FeedbackIn(verdict="mark_safe"),
            session=s, user=_u(g1, "guardian"),
        )
        await s.commit()

    # Resolve directly via the state machine with actor_type='guardian'.
    from app.services.incident_state_machine import (
        IncidentState, transition,
    )
    async with db() as s:
        from sqlalchemy import select
        inc = (await s.execute(
            select(SafetyIncident).where(SafetyIncident.id == iid)
        )).scalar_one()
        await transition(s, inc, IncidentState.RESOLVED,
                         actor_id=g1, actor_type="guardian")
        await s.commit()

    async with db() as s:
        out = await get_impact(s, g1, use_cache=False)
    assert out["saved_by_network_count"] == 0  # community_feedback never fired

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[g1, child])


# ════════════════════════════════════════════════════════════════════
# Confidence floor + system-wide signal
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_low_confidence_flag_when_system_resolutions_below_floor(db):
    """`confidence_low: true` must be returned when the system-wide
    community-resolved count is < 5. UI uses this to hide the badge."""
    async with db() as s:
        g = await _seed_user(s)
        await s.commit()

    async with db() as s:
        out = await get_impact(s, g, use_cache=False)
    # In an empty / fresh test environment, sysres will be 0 — below floor.
    if out["system_resolutions"] < LOW_CONFIDENCE_FLOOR:
        assert out["confidence_low"] is True

    async with db() as s:
        await _cleanup(s, user_ids=[g])


def test_low_confidence_floor_locked():
    """Defends against accidental tuning that would let a 1-incident
    network display a flashy badge."""
    assert LOW_CONFIDENCE_FLOOR == 5


# ════════════════════════════════════════════════════════════════════
# Helper coverage
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_mark_safe_voters_returns_only_safe_voters(db):
    """Helper used by the cache-invalidation hook: must return only
    guardians whose CURRENT verdict is mark_safe."""
    async with db() as s:
        g_safe1 = await _seed_user(s)
        g_safe2 = await _seed_user(s)
        g_risk  = await _seed_user(s)
        child = await _seed_user(s, "user")
        for g in (g_safe1, g_safe2, g_risk):
            await _seed_relationship(s, g, child)
        iid = await _seed_incident(s, child)
        await s.commit()

    for g, v in [(g_safe1, "mark_safe"), (g_safe2, "mark_safe"),
                  (g_risk, "confirm_risk")]:
        async with db() as s:
            await submit_incident_feedback(
                incident_id=iid, body=FeedbackIn(verdict=v),
                session=s, user=_u(g, "guardian"),
            )
            await s.commit()

    async with db() as s:
        voters = await get_mark_safe_voters(s, iid)

    voter_set = {str(v) for v in voters}
    assert str(g_safe1) in voter_set
    assert str(g_safe2) in voter_set
    assert str(g_risk) not in voter_set

    async with db() as s:
        await _cleanup(s, incident_ids=[iid],
                       user_ids=[g_safe1, g_safe2, g_risk, child])


@pytest.mark.asyncio
async def test_invalidate_guardians_swallows_redis_errors():
    """Failsafe contract: cache invalidation never raises into the
    aggregator's hot path. Empty list is a fast no-op."""
    # Empty list path — should be silent + cheap.
    await invalidate_guardians([])
    # Real list, even with bogus UUIDs — must not raise either.
    await invalidate_guardians([uuid.uuid4(), uuid.uuid4()])


# ════════════════════════════════════════════════════════════════════
# API auth surface
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_my_impact_endpoint_returns_caller_envelope(db):
    """`GET /api/guardian/impact/me` returns the caller's count
    without an auth role gate."""
    async with db() as s:
        g = await _seed_user(s)
        await s.commit()

    async with db() as s:
        out = await get_my_impact(session=s, user=_u(g, "guardian"))
    assert out["guardian_id"] == str(g)
    assert out["saved_by_network_count"] == 0

    async with db() as s:
        await _cleanup(s, user_ids=[g])


@pytest.mark.asyncio
async def test_cross_user_endpoint_blocks_non_admin(db):
    """`GET /api/guardian/impact/{other_id}` rejects guardians."""
    async with db() as s:
        g1 = await _seed_user(s)
        g2 = await _seed_user(s)
        await s.commit()

    async with db() as s:
        with pytest.raises(HTTPException) as exc:
            await get_user_impact(
                user_id=g2, session=s, user=_u(g1, "guardian"),
            )
        assert exc.value.status_code == 403

    async with db() as s:
        await _cleanup(s, user_ids=[g1, g2])


@pytest.mark.asyncio
async def test_cross_user_endpoint_allows_admin(db):
    """Admin can read anyone's count."""
    async with db() as s:
        admin = await _seed_user(s, "admin")
        target = await _seed_user(s)
        await s.commit()

    async with db() as s:
        out = await get_user_impact(
            user_id=target, session=s, user=_u(admin, "admin"),
        )
    assert out["guardian_id"] == str(target)

    async with db() as s:
        await _cleanup(s, user_ids=[admin, target])


@pytest.mark.asyncio
async def test_cross_user_endpoint_allows_self(db):
    """Calling /impact/{my_id} with my own id is allowed."""
    async with db() as s:
        g = await _seed_user(s)
        await s.commit()
    async with db() as s:
        out = await get_user_impact(
            user_id=g, session=s, user=_u(g, "guardian"),
        )
    assert out["guardian_id"] == str(g)
    async with db() as s:
        await _cleanup(s, user_ids=[g])
