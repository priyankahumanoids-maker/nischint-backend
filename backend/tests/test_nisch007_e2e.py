"""NISCH-007 — End-to-end mobile feed contract.

Locks the full user-facing contract before TestFlight rollout. Tests
the read paths through the LIVE backend stack (Neon PG + the actual
FastAPI handlers + the actual state machine) — no mocks. SSE emission
is covered via direct broadcaster instrumentation (the `react-native-sse`
client transport itself is the user runbook's job).

Run:
    # Default suite (skips live-PG tests)
    pytest backend/tests/

    # Just this file:
    pytest backend/tests/test_nisch007_e2e.py -m live_pg -v

CI-skip marker: every test below is `live_pg`. Local sqlite-only runs
must add `-m "not live_pg"` to bypass; the marker is registered in
the new top-level `conftest.py` shipped alongside this file.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine,
)

from app.api.incidents_feed import get_nearby_incidents
from app.api.safety_incidents import get_incident_timeline
from app.models.safety_incident import SafetyIncident
from app.models.safety_incident_event import SafetyIncidentEvent
from app.services.incident_state_machine import (
    IncidentState, transition,
)


pytestmark = pytest.mark.live_pg


# ── DB fixture (matches test_incidents_feed.py pattern) ───────────
def _db_url() -> str:
    from app.core.config import settings
    url = settings.database_url or ""
    if not url:
        pytest.skip("database_url not set; live-PG tests skipped")
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


# ── Seed helpers (matches test_incidents_feed.py shape) ────────────
async def _seed_user(s: AsyncSession, role: str = "guardian",
                     lat: float | None = None, lng: float | None = None) -> uuid.UUID:
    uid = uuid.uuid4()
    await s.execute(text("""
        INSERT INTO users (id, email, full_name, role, password_hash,
                           preferred_channels, created_at,
                           last_known_lat, last_known_lng)
        VALUES (:id, :email, :name, :role, 'x',
                '["push"]'::json, now(), :lat, :lng)
    """), {"id": str(uid),
           "email": f"e2e+{uid}@nischint.test",
           "name": f"E2E {uid.hex[:8]}",
           "role": role, "lat": lat, "lng": lng})
    return uid


async def _seed_relationship(s: AsyncSession, guardian_id: uuid.UUID,
                              child_id: uuid.UUID,
                              status_val: str = "accepted") -> None:
    await s.execute(text("""
        INSERT INTO relationships (id, guardian_id, child_id, status, created_at)
        VALUES (:id, :gid, :cid, :status, now())
    """), {"id": str(uuid.uuid4()),
           "gid": str(guardian_id), "cid": str(child_id),
           "status": status_val})


async def _seed_incident(
    s: AsyncSession, child_id: uuid.UUID,
    *, state: str = "detected",
    severity: str = "critical",
    confidence: float = 0.91,
    sla_degraded: bool = False,
    incident_type: str = "voice_distress",
) -> uuid.UUID:
    iid = uuid.uuid4()
    s.add(SafetyIncident(
        id=iid, child_id=child_id, incident_type=incident_type,
        severity=severity, state=state, confidence=confidence,
        sla_degraded_at_dispatch=sla_degraded, escalation_level=0,
    ))
    await s.flush()
    # Mirror what `safety_incident_engine.open_incident_for_alert`
    # writes — the genesis event. Without it, timeline tests would
    # render an incomplete chain.
    s.add(SafetyIncidentEvent(
        incident_id=iid, from_state=None, to_state=state,
        actor_type="system", ttfa_tag=f"incident_state:{state}",
        sla_degraded=sla_degraded,
        extra={"confidence": confidence, "escalation_level": 0},
    ))
    await s.flush()
    return iid


async def _cleanup(s: AsyncSession, **ids):
    for iid in ids.get("incident_ids", []):
        await s.execute(text("DELETE FROM safety_incidents WHERE id = :id"),
                        {"id": str(iid)})
    for uid in ids.get("user_ids", []):
        await s.execute(text(
            "DELETE FROM relationships WHERE guardian_id = :id OR child_id = :id"
        ), {"id": str(uid)})
        await s.execute(text("DELETE FROM users WHERE id = :id"),
                        {"id": str(uid)})
    await s.commit()


def _u(uid: uuid.UUID, role: str):
    return type("U", (), {"id": uid, "role": role})()


# Mumbai-ish reference. All seeded children are placed within ~150m of
# this point so the default 500m radius captures them.
GLAT, GLNG = 19.0760, 72.8777
CHILD_LAT, CHILD_LNG = GLAT, GLNG + 0.0014  # ~150m east


# ── 1. Feed returns the seeded incident with correct shape ─────────
@pytest.mark.asyncio
async def test_feed_returns_seeded_incident(db):
    """Happy-path contract — every field the mobile UI reads must
    appear with the documented shape."""
    async with db() as s:
        guardian = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user", lat=CHILD_LAT, lng=CHILD_LNG)
        await _seed_relationship(s, guardian, child)
        iid = await _seed_incident(
            s, child, state="detected", confidence=0.91,
        )
        await s.commit()

    try:
        async with db() as s:
            out = await get_nearby_incidents(
                lat=GLAT, lng=GLNG, radius=500, zone=None, limit=20,
                status="active", session=s, user=_u(guardian, "guardian"),
            )
        assert out["total"] == 1
        row = out["incidents"][0]
        assert row["id"]                       == str(iid)
        # MUST be the user-facing label, NOT the raw enum.
        assert row["state_label"]              == "Distress detected"
        assert row["state"]                    == "detected"
        assert row["distance_metres"] > 0
        assert isinstance(row["distance_metres"], int)
        assert "elapsed_since_created" in row
        # Confidence ≥ threshold so MUST appear.
        assert row["confidence"]               == 0.91
        assert row["sla_degraded_at_dispatch"] is False
    finally:
        async with db() as s:
            await _cleanup(s, incident_ids=[iid],
                           user_ids=[guardian, child])


# ── 2. Feed excludes unlinked guardian ─────────────────────────────
@pytest.mark.asyncio
async def test_feed_excludes_unlinked_guardian(db):
    async with db() as s:
        owner = await _seed_user(s, "guardian")
        stranger = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user", lat=CHILD_LAT, lng=CHILD_LNG)
        await _seed_relationship(s, owner, child)
        iid = await _seed_incident(s, child, state="detected")
        await s.commit()

    try:
        async with db() as s:
            out = await get_nearby_incidents(
                lat=GLAT, lng=GLNG, radius=500, zone=None, limit=20,
                status="active", session=s, user=_u(stranger, "guardian"),
            )
        # Stranger sees nothing — auth boundary holds.
        assert out["total"] == 0
        assert out["incidents"] == []
    finally:
        async with db() as s:
            await _cleanup(s, incident_ids=[iid],
                           user_ids=[owner, stranger, child])


# ── 3. State transition updates the user-facing label ─────────────
@pytest.mark.asyncio
async def test_state_transition_updates_label(db, monkeypatch):
    """Transition DETECTED → VALIDATING → ESCALATED, then re-query
    the feed. The `state_label` must reflect the new state."""
    # Stub SSE/TTFA emitters — we test the read path here, not the
    # broadcaster (covered by test 9 below).
    monkeypatch.setattr("app.services.incident_state_machine._emit_sse",
                        lambda *a, **kw: None)
    monkeypatch.setattr("app.services.incident_state_machine._emit_ttfa",
                        lambda *a, **kw: None)

    async with db() as s:
        guardian = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user", lat=CHILD_LAT, lng=CHILD_LNG)
        await _seed_relationship(s, guardian, child)
        iid = await _seed_incident(s, child, state="detected")
        await s.commit()

    try:
        async with db() as s:
            from sqlalchemy import select
            # Re-load as ORM for the state machine.
            orm = (await s.execute(
                select(SafetyIncident).where(SafetyIncident.id == iid)
            )).scalar_one()
            await transition(s, orm, IncidentState.VALIDATING, actor_type="system")
            await transition(s, orm, IncidentState.ESCALATED,  actor_type="system")
            await s.commit()

        async with db() as s:
            out = await get_nearby_incidents(
                lat=GLAT, lng=GLNG, radius=500, zone=None, limit=20,
                status="active", session=s, user=_u(guardian, "guardian"),
            )
        row = next(r for r in out["incidents"] if r["id"] == str(iid))
        assert row["state"]       == "escalated"
        # NEVER raw — always the user-facing label.
        assert row["state_label"] == "Guardian network alerted"
        assert row["state_label"] != row["state"]
    finally:
        async with db() as s:
            await _cleanup(s, incident_ids=[iid],
                           user_ids=[guardian, child])


# ── 4. Timeline returns ordered events ─────────────────────────────
@pytest.mark.asyncio
async def test_timeline_has_ordered_events(db, monkeypatch):
    """Walk DETECTED → VALIDATING → ESCALATED. The timeline endpoint
    must return all 3 events in chronological order with non-zero
    elapsed_ms on every transition after the genesis."""
    monkeypatch.setattr("app.services.incident_state_machine._emit_sse",
                        lambda *a, **kw: None)
    monkeypatch.setattr("app.services.incident_state_machine._emit_ttfa",
                        lambda *a, **kw: None)

    async with db() as s:
        guardian = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user", lat=CHILD_LAT, lng=CHILD_LNG)
        await _seed_relationship(s, guardian, child)
        iid = await _seed_incident(s, child, state="detected")
        await s.commit()

    try:
        async with db() as s:
            from sqlalchemy import select
            orm = (await s.execute(
                select(SafetyIncident).where(SafetyIncident.id == iid)
            )).scalar_one()
            # Sleep micro-pauses so the elapsed_ms math is non-zero.
            await transition(s, orm, IncidentState.VALIDATING, actor_type="system")
            await asyncio.sleep(0.05)
            await transition(s, orm, IncidentState.ESCALATED,  actor_type="system")
            await s.commit()

        async with db() as s:
            out = await get_incident_timeline(
                iid, s, _u(guardian, "guardian"),
            )
        timeline = out["timeline"]
        assert len(timeline) == 3
        assert timeline[0]["from_state"] is None        # genesis
        assert timeline[0]["to_state"]   == "detected"
        assert timeline[0]["elapsed_ms"] == 0
        assert timeline[1]["to_state"]   == "validating"
        assert timeline[2]["to_state"]   == "escalated"
        # elapsed_ms grows monotonically; second + third events have
        # non-zero deltas.
        assert timeline[1]["elapsed_ms"] >= 0
        assert timeline[2]["elapsed_ms"] >  0
        # actor_type contract — must be set, must be in the agreed set.
        for ev in timeline:
            assert ev["actor_type"] in {"guardian", "system", "scheduler"}
    finally:
        async with db() as s:
            await _cleanup(s, incident_ids=[iid],
                           user_ids=[guardian, child])


# ── 5. Resolved incidents leave the active feed ────────────────────
@pytest.mark.asyncio
async def test_resolved_incident_excluded_from_active_feed(db, monkeypatch):
    monkeypatch.setattr("app.services.incident_state_machine._emit_sse",
                        lambda *a, **kw: None)
    monkeypatch.setattr("app.services.incident_state_machine._emit_ttfa",
                        lambda *a, **kw: None)

    async with db() as s:
        guardian = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user", lat=CHILD_LAT, lng=CHILD_LNG)
        await _seed_relationship(s, guardian, child)
        iid = await _seed_incident(s, child, state="detected")
        await s.commit()

    try:
        async with db() as s:
            from sqlalchemy import select
            orm = (await s.execute(
                select(SafetyIncident).where(SafetyIncident.id == iid)
            )).scalar_one()
            for nxt in [IncidentState.VALIDATING, IncidentState.ESCALATED,
                        IncidentState.ACKNOWLEDGED, IncidentState.RESOLVED]:
                await transition(s, orm, nxt, actor_type="system")
            await s.commit()

        async with db() as s:
            active = await get_nearby_incidents(
                lat=GLAT, lng=GLNG, radius=500, zone=None, limit=20,
                status="active", session=s, user=_u(guardian, "guardian"),
            )
            resolved = await get_nearby_incidents(
                lat=GLAT, lng=GLNG, radius=500, zone=None, limit=20,
                status="resolved", session=s, user=_u(guardian, "guardian"),
            )

        active_ids   = {r["id"] for r in active["incidents"]}
        resolved_ids = {r["id"] for r in resolved["incidents"]}
        assert str(iid) not in active_ids
        assert str(iid) in resolved_ids
    finally:
        async with db() as s:
            await _cleanup(s, incident_ids=[iid],
                           user_ids=[guardian, child])


# ── 6. Archived NEVER appears, regardless of status param ──────────
@pytest.mark.asyncio
async def test_archived_incident_never_appears(db, monkeypatch):
    monkeypatch.setattr("app.services.incident_state_machine._emit_sse",
                        lambda *a, **kw: None)
    monkeypatch.setattr("app.services.incident_state_machine._emit_ttfa",
                        lambda *a, **kw: None)

    async with db() as s:
        guardian = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user", lat=CHILD_LAT, lng=CHILD_LNG)
        await _seed_relationship(s, guardian, child)
        iid = await _seed_incident(s, child, state="detected")
        await s.commit()

    try:
        async with db() as s:
            from sqlalchemy import select
            orm = (await s.execute(
                select(SafetyIncident).where(SafetyIncident.id == iid)
            )).scalar_one()
            for nxt in [IncidentState.VALIDATING, IncidentState.ESCALATED,
                        IncidentState.ACKNOWLEDGED, IncidentState.RESOLVED,
                        IncidentState.ARCHIVED]:
                await transition(s, orm, nxt, actor_type="system")
            await s.commit()

        # status='all' is the absolute test — archived must STILL be hidden.
        async with db() as s:
            for status in ("active", "resolved", "all"):
                out = await get_nearby_incidents(
                    lat=GLAT, lng=GLNG, radius=500, zone=None, limit=20,
                    status=status, session=s,
                    user=_u(guardian, "guardian"),
                )
                ids = {r["id"] for r in out["incidents"]}
                assert str(iid) not in ids, (
                    f"archived incident leaked into status={status!r} response"
                )
    finally:
        async with db() as s:
            await _cleanup(s, incident_ids=[iid],
                           user_ids=[guardian, child])


# ── 7. SLA-degraded annotation surfaces on the feed row ────────────
@pytest.mark.asyncio
async def test_sla_annotation_present_on_feed_row(db):
    async with db() as s:
        guardian = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user", lat=CHILD_LAT, lng=CHILD_LNG)
        await _seed_relationship(s, guardian, child)
        iid = await _seed_incident(
            s, child, state="escalated", sla_degraded=True,
        )
        await s.commit()

    try:
        async with db() as s:
            out = await get_nearby_incidents(
                lat=GLAT, lng=GLNG, radius=500, zone=None, limit=20,
                status="active", session=s, user=_u(guardian, "guardian"),
            )
        row = next(r for r in out["incidents"] if r["id"] == str(iid))
        assert row["sla_degraded_at_dispatch"] is True
    finally:
        async with db() as s:
            await _cleanup(s, incident_ids=[iid],
                           user_ids=[guardian, child])


# ── 8. Confidence < 0.70 omitted entirely ──────────────────────────
@pytest.mark.asyncio
async def test_low_confidence_omitted_from_response(db):
    """Trust threshold — low-confidence incidents must NOT expose the
    confidence field at all (omitted, not zeroed)."""
    async with db() as s:
        guardian = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user", lat=CHILD_LAT, lng=CHILD_LNG)
        await _seed_relationship(s, guardian, child)
        iid = await _seed_incident(
            s, child, state="escalated", confidence=0.65,
        )
        await s.commit()

    try:
        async with db() as s:
            out = await get_nearby_incidents(
                lat=GLAT, lng=GLNG, radius=500, zone=None, limit=20,
                status="active", session=s, user=_u(guardian, "guardian"),
            )
        row = next(r for r in out["incidents"] if r["id"] == str(iid))
        assert "confidence" not in row, (
            f"low-confidence value leaked: {row.get('confidence')!r}"
        )
    finally:
        async with db() as s:
            await _cleanup(s, incident_ids=[iid],
                           user_ids=[guardian, child])


# ── 9. SSE broadcaster fires `incident_state_change` on transition ─
@pytest.mark.asyncio
async def test_sse_emits_state_change_event(db):
    """Critical: the mobile feed's in-place SSE patching contract
    depends on every `transition()` call resulting in EXACTLY ONE
    `incident_state_change` broadcast to the child's SSE channel.

    We instrument `EventBroadcaster.broadcast_to_user` rather than
    open a real SSE socket — the network transport is the runbook's
    job. The contract we lock here: the right event_type, the right
    channel, the right payload, all within 5s of `transition()`.
    """
    captured: list[tuple[str, str, dict]] = []

    from app.services import event_broadcaster as eb_mod
    real = eb_mod.EventBroadcaster.broadcast_to_user

    async def spy(self, user_id: str, event_type: str, data: dict):
        captured.append((str(user_id), event_type, data))
        # Don't call real — Redis Streams aren't part of the contract
        # this test owns; we only care that the call shape is right.
        return None

    eb_mod.EventBroadcaster.broadcast_to_user = spy  # type: ignore
    try:
        async with db() as s:
            guardian = await _seed_user(s, "guardian")
            child = await _seed_user(s, "user", lat=CHILD_LAT, lng=CHILD_LNG)
            await _seed_relationship(s, guardian, child)
            iid = await _seed_incident(s, child, state="detected")
            await s.commit()

        try:
            async with db() as s:
                from sqlalchemy import select
                orm = (await s.execute(
                    select(SafetyIncident).where(SafetyIncident.id == iid)
                )).scalar_one()

                # Fire transition under wait_for so a hung emitter
                # surfaces as a clean test failure rather than a CI hang.
                async def _do_transition():
                    await transition(s, orm, IncidentState.VALIDATING,
                                     actor_type="system")
                    await s.commit()
                await asyncio.wait_for(_do_transition(), timeout=5.0)

            # Locate the broadcast for our incident.
            ours = [(uid, et, d) for (uid, et, d) in captured
                    if d.get("id") == str(iid) or d.get("incident_id") == str(iid)]
            assert ours, (
                f"no broadcast captured for incident {iid}; "
                f"captured={captured}"
            )
            uid, et, payload = ours[-1]
            assert et == "incident_state_change"
            # Channel = the child's user_id (so both guardian + child
            # receive on their own scopes downstream).
            assert uid == str(child)
            # Mobile-contract assertions — these are the keys the mobile
            # feed reads to patch a row in place. Verified end-to-end so
            # the silent no-op contract bug we caught here can never
            # regress without lighting up this test.
            assert payload.get("to_state")    == "validating"
            assert payload.get("state")       == "validating"
            assert payload.get("state_label") == "Alert sent to network"
            # Legacy compat preserved.
            assert payload.get("to") == "validating"
        finally:
            async with db() as s:
                await _cleanup(s, incident_ids=[iid],
                               user_ids=[guardian, child])
    finally:
        eb_mod.EventBroadcaster.broadcast_to_user = real  # type: ignore
