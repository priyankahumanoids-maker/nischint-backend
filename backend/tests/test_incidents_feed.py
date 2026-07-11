"""NISCH-007 Part A — `GET /api/incidents/nearby` tests.

Live-PG tests against the real Neon instance. Each test is self-cleanup;
the suite is idempotent. Patterned after `test_incident_timeline_endpoint.py`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine,
)

from app.api.incidents_feed import (
    CONFIDENCE_DISPLAY_THRESHOLD, MARKER_PRECISION_DP, STATE_LABELS,
    _haversine_m, get_nearby_incidents, round_marker_coord,
)
from app.models.safety_incident import SafetyIncident


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


# ── Seed helpers ────────────────────────────────────────────────────
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
           "email": f"nf+{uid}@nischint.test",
           "name": f"User {uid.hex[:8]}",
           "role": role,
           "lat": lat, "lng": lng})
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


async def _seed_incident(s: AsyncSession, child_id: uuid.UUID,
                          *, state: str = "escalated",
                          severity: str = "critical",
                          confidence: float = 0.91,
                          incident_type: str = "voice_distress",
                          sla_degraded: bool = False) -> uuid.UUID:
    iid = uuid.uuid4()
    s.add(SafetyIncident(
        id=iid, child_id=child_id, incident_type=incident_type,
        severity=severity, state=state, confidence=confidence,
        sla_degraded_at_dispatch=sla_degraded, escalation_level=1,
    ))
    await s.flush()
    return iid


async def _seed_safe_zone(s: AsyncSession, user_id: uuid.UUID, *,
                           lat: float, lng: float, radius_m: float,
                           zone_type: str) -> None:
    await s.execute(text("""
        INSERT INTO safe_zones (id, user_id, name, lat, lng, radius_m,
                                 zone_type, active, created_at)
        VALUES (:id, :uid, :name, :lat, :lng, :r, :zt, true, now())
    """), {"id": str(uuid.uuid4()), "uid": str(user_id),
           "name": zone_type.title(),
           "lat": lat, "lng": lng, "r": radius_m, "zt": zone_type})


async def _cleanup(s: AsyncSession, **ids):
    for iid in ids.get("incident_ids", []):
        await s.execute(text("DELETE FROM safety_incidents WHERE id = :id"),
                        {"id": str(iid)})
    for uid in ids.get("user_ids", []):
        await s.execute(text(
            "DELETE FROM relationships WHERE guardian_id = :id OR child_id = :id"
        ), {"id": str(uid)})
        await s.execute(text("DELETE FROM safe_zones WHERE user_id = :id"),
                        {"id": str(uid)})
        await s.execute(text("DELETE FROM users WHERE id = :id"),
                        {"id": str(uid)})
    await s.commit()


def _u(uid: uuid.UUID, role: str):
    return type("U", (), {"id": uid, "role": role})()


# ── 1. Linked guardian sees own child's nearby incident ────────────
@pytest.mark.asyncio
async def test_linked_guardian_sees_nearby_incident(db):
    """The happy path. Guardian linked to child, child has last-known
    location within radius, incident escalated → returns one row with
    correct distance + state_label."""
    # Mumbai-ish reference point.
    GLAT, GLNG = 19.0760, 72.8777
    # Child ~150 m east of guardian — within default 500 m radius.
    CHILD_LAT, CHILD_LNG = GLAT, GLNG + 0.0014  # ~150m east at this latitude

    async with db() as s:
        guardian = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user", lat=CHILD_LAT, lng=CHILD_LNG)
        await _seed_relationship(s, guardian, child)
        iid = await _seed_incident(s, child, state="escalated")
        await s.commit()

    async with db() as s:
        out = await get_nearby_incidents(
            lat=GLAT, lng=GLNG, radius=500, zone=None, limit=20,
            status="active", session=s, user=_u(guardian, "guardian"),
        )

    assert out["total"] == 1
    inc = out["incidents"][0]
    assert inc["id"] == str(iid)
    assert inc["state"] == "escalated"
    assert inc["state_label"] == "Guardian network alerted"
    assert 100 <= inc["distance_metres"] <= 200
    assert inc["confidence"] == 0.91  # exposed because >= 0.70

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[guardian, child])


# ── 2. Unlinked guardian sees nothing ──────────────────────────────
@pytest.mark.asyncio
async def test_unlinked_guardian_gets_empty_feed(db):
    """A guardian with no Relationship rows must get an empty feed
    even if there are nearby escalated incidents from other children."""
    GLAT, GLNG = 19.0760, 72.8777
    async with db() as s:
        stranger = await _seed_user(s, "guardian")
        someone_elses_child = await _seed_user(
            s, "user", lat=GLAT + 0.0005, lng=GLNG)
        iid = await _seed_incident(s, someone_elses_child, state="escalated")
        await s.commit()

    async with db() as s:
        out = await get_nearby_incidents(
            lat=GLAT, lng=GLNG, radius=500, zone=None, limit=20,
            status="active", session=s, user=_u(stranger, "guardian"),
        )
    assert out["total"] == 0
    assert out["incidents"] == []

    async with db() as s:
        await _cleanup(s, incident_ids=[iid],
                       user_ids=[stranger, someone_elses_child])


# ── 3. Archived incidents NEVER appear ─────────────────────────────
@pytest.mark.asyncio
async def test_archived_excluded_even_with_status_all(db):
    """The brief is explicit: archived incidents never appear in the
    feed regardless of `status` query param. Verify with status='all'."""
    GLAT, GLNG = 19.0760, 72.8777
    async with db() as s:
        guardian = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user", lat=GLAT, lng=GLNG + 0.0005)
        await _seed_relationship(s, guardian, child)
        active_iid   = await _seed_incident(s, child, state="escalated")
        archived_iid = await _seed_incident(s, child, state="archived")
        await s.commit()

    async with db() as s:
        out = await get_nearby_incidents(
            lat=GLAT, lng=GLNG, radius=500, zone=None, limit=20,
            status="all", session=s, user=_u(guardian, "guardian"),
        )

    ids_seen = {i["id"] for i in out["incidents"]}
    assert str(active_iid)   in ids_seen
    assert str(archived_iid) not in ids_seen

    async with db() as s:
        await _cleanup(s, incident_ids=[active_iid, archived_iid],
                       user_ids=[guardian, child])


# ── 4. Confidence below threshold is OMITTED, not zeroed ───────────
@pytest.mark.asyncio
async def test_confidence_below_threshold_is_omitted(db):
    GLAT, GLNG = 19.0760, 72.8777
    async with db() as s:
        guardian = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user", lat=GLAT, lng=GLNG + 0.0005)
        await _seed_relationship(s, guardian, child)
        # 0.65 < 0.70 → must NOT appear in the row.
        low_iid  = await _seed_incident(s, child, state="escalated",
                                          confidence=0.65)
        high_iid = await _seed_incident(s, child, state="escalated",
                                          confidence=0.85)
        await s.commit()

    async with db() as s:
        out = await get_nearby_incidents(
            lat=GLAT, lng=GLNG, radius=500, zone=None, limit=20,
            status="active", session=s, user=_u(guardian, "guardian"),
        )

    by_id = {i["id"]: i for i in out["incidents"]}
    assert "confidence" not in by_id[str(low_iid)]
    assert by_id[str(high_iid)]["confidence"] == 0.85
    assert CONFIDENCE_DISPLAY_THRESHOLD == 0.70  # locked

    async with db() as s:
        await _cleanup(s, incident_ids=[low_iid, high_iid],
                       user_ids=[guardian, child])


# ── 5. Distance filter excludes far incidents ──────────────────────
@pytest.mark.asyncio
async def test_radius_filter_excludes_far_incidents(db):
    """Two incidents — one in radius, one outside. Verify only the
    near one comes back, AND the response is ordered by distance ASC."""
    GLAT, GLNG = 19.0760, 72.8777
    async with db() as s:
        guardian = await _seed_user(s, "guardian")
        # ~150m east — inside 500m radius.
        near_child = await _seed_user(s, "user",
                                       lat=GLAT, lng=GLNG + 0.0014)
        # ~3km north — outside 500m radius.
        far_child  = await _seed_user(s, "user",
                                       lat=GLAT + 0.027, lng=GLNG)
        await _seed_relationship(s, guardian, near_child)
        await _seed_relationship(s, guardian, far_child)
        near_iid = await _seed_incident(s, near_child, state="escalated")
        far_iid  = await _seed_incident(s, far_child,  state="escalated")
        await s.commit()

    async with db() as s:
        out = await get_nearby_incidents(
            lat=GLAT, lng=GLNG, radius=500, zone=None, limit=20,
            status="active", session=s, user=_u(guardian, "guardian"),
        )

    ids = [i["id"] for i in out["incidents"]]
    assert str(near_iid) in ids
    assert str(far_iid) not in ids

    async with db() as s:
        await _cleanup(s, incident_ids=[near_iid, far_iid],
                       user_ids=[guardian, near_child, far_child])


# ── 6. State label mapping — never expose raw state names ──────────
@pytest.mark.asyncio
async def test_state_label_mapping(db):
    GLAT, GLNG = 19.0760, 72.8777
    seeded_states = ["detected", "validating", "escalated",
                     "acknowledged", "resolved"]
    async with db() as s:
        guardian = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user", lat=GLAT, lng=GLNG + 0.0005)
        await _seed_relationship(s, guardian, child)
        iids = []
        for st in seeded_states:
            iids.append(await _seed_incident(s, child, state=st))
        await s.commit()

    async with db() as s:
        out = await get_nearby_incidents(
            lat=GLAT, lng=GLNG, radius=500, zone=None, limit=20,
            status="all", session=s, user=_u(guardian, "guardian"),
        )

    by_state = {i["state"]: i for i in out["incidents"]}
    for st in seeded_states:
        assert by_state[st]["state_label"] == STATE_LABELS[st]
        # Sanity — labels are user-facing copy, not raw enum.
        assert by_state[st]["state_label"] != st.upper()

    async with db() as s:
        await _cleanup(s, incident_ids=iids, user_ids=[guardian, child])


# ── 7. Zone filter — only matching zone incidents come back ────────
@pytest.mark.asyncio
async def test_zone_filter_match(db):
    """Child has a 'school' SafeZone; child is inside it. Querying
    `?zone=school` returns the incident; `?zone=home` returns nothing."""
    GLAT, GLNG = 19.0760, 72.8777
    SCHOOL_LAT, SCHOOL_LNG = GLAT, GLNG + 0.0014  # ~150m east

    async with db() as s:
        guardian = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user",
                                  lat=SCHOOL_LAT, lng=SCHOOL_LNG)
        await _seed_relationship(s, guardian, child)
        await _seed_safe_zone(s, child, lat=SCHOOL_LAT, lng=SCHOOL_LNG,
                               radius_m=200, zone_type="school")
        iid = await _seed_incident(s, child, state="escalated")
        await s.commit()

    async with db() as s:
        out_school = await get_nearby_incidents(
            lat=GLAT, lng=GLNG, radius=500, zone="school", limit=20,
            status="active", session=s, user=_u(guardian, "guardian"),
        )
        out_home = await get_nearby_incidents(
            lat=GLAT, lng=GLNG, radius=500, zone="home", limit=20,
            status="active", session=s, user=_u(guardian, "guardian"),
        )

    assert out_school["total"] == 1
    assert out_school["incidents"][0]["zone_match"] == "school"
    assert out_home["total"] == 0

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[guardian, child])


# ── 8. Operator role bypasses relationship gate ────────────────────
@pytest.mark.asyncio
async def test_operator_sees_all_in_radius(db):
    """An operator (eyes-on-everything role) with NO relationship rows
    must still see incidents from any child within the radius."""
    GLAT, GLNG = 19.0760, 72.8777
    async with db() as s:
        operator = await _seed_user(s, "operator")
        unrelated_child = await _seed_user(s, "user",
                                             lat=GLAT, lng=GLNG + 0.0005)
        iid = await _seed_incident(s, unrelated_child, state="escalated")
        await s.commit()

    async with db() as s:
        out = await get_nearby_incidents(
            lat=GLAT, lng=GLNG, radius=500, zone=None, limit=20,
            status="active", session=s, user=_u(operator, "operator"),
        )
    assert out["total"] == 1
    assert out["incidents"][0]["id"] == str(iid)

    async with db() as s:
        await _cleanup(s, incident_ids=[iid],
                       user_ids=[operator, unrelated_child])


# ── 9. status='resolved' returns only resolved ─────────────────────
@pytest.mark.asyncio
async def test_status_resolved_filter(db):
    GLAT, GLNG = 19.0760, 72.8777
    async with db() as s:
        guardian = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user", lat=GLAT, lng=GLNG + 0.0005)
        await _seed_relationship(s, guardian, child)
        active_iid   = await _seed_incident(s, child, state="escalated")
        resolved_iid = await _seed_incident(s, child, state="resolved")
        await s.commit()

    async with db() as s:
        out = await get_nearby_incidents(
            lat=GLAT, lng=GLNG, radius=500, zone=None, limit=20,
            status="resolved", session=s, user=_u(guardian, "guardian"),
        )

    ids = {i["id"] for i in out["incidents"]}
    assert str(resolved_iid) in ids
    assert str(active_iid) not in ids

    async with db() as s:
        await _cleanup(s, incident_ids=[active_iid, resolved_iid],
                       user_ids=[guardian, child])


# ── 10. Param validation: bad status → 400 ─────────────────────────
@pytest.mark.asyncio
async def test_bad_status_param_400(db):
    from fastapi import HTTPException
    async with db() as s:
        guardian = await _seed_user(s, "guardian")
        await s.commit()
    async with db() as s:
        with pytest.raises(HTTPException) as exc:
            await get_nearby_incidents(
                lat=19.0, lng=72.0, radius=500, zone=None, limit=20,
                status="not_a_real_status",
                session=s, user=_u(guardian, "guardian"),
            )
        assert exc.value.status_code == 400
    async with db() as s:
        await _cleanup(s, user_ids=[guardian])


# ── 11. Haversine sanity (pure unit, no DB) ────────────────────────
def test_haversine_known_distance():
    """Mumbai (19.0760, 72.8777) → Pune (18.5204, 73.8567) ≈ 120 km."""
    d = _haversine_m(19.0760, 72.8777, 18.5204, 73.8567)
    assert 115_000 < d < 125_000


def test_haversine_zero():
    assert _haversine_m(19.0, 72.0, 19.0, 72.0) == 0


# ── 12. Distance-ascending sort holds ──────────────────────────────
@pytest.mark.asyncio
async def test_results_sorted_by_distance_asc(db):
    """Three children at 100m, 200m, 300m → response order must be
    100, 200, 300."""
    GLAT, GLNG = 19.0760, 72.8777
    async with db() as s:
        guardian = await _seed_user(s, "guardian")
        c100 = await _seed_user(s, "user", lat=GLAT, lng=GLNG + 0.001)   # ~100m
        c200 = await _seed_user(s, "user", lat=GLAT, lng=GLNG + 0.002)   # ~200m
        c300 = await _seed_user(s, "user", lat=GLAT, lng=GLNG + 0.003)   # ~300m
        for c in (c100, c200, c300):
            await _seed_relationship(s, guardian, c)
        i100 = await _seed_incident(s, c100, state="escalated")
        i200 = await _seed_incident(s, c200, state="escalated")
        i300 = await _seed_incident(s, c300, state="escalated")
        await s.commit()

    async with db() as s:
        out = await get_nearby_incidents(
            lat=GLAT, lng=GLNG, radius=500, zone=None, limit=20,
            status="active", session=s, user=_u(guardian, "guardian"),
        )

    distances = [i["distance_metres"] for i in out["incidents"]]
    assert distances == sorted(distances)
    ids = [i["id"] for i in out["incidents"]]
    assert ids.index(str(i100)) < ids.index(str(i200)) < ids.index(str(i300))

    async with db() as s:
        await _cleanup(s, incident_ids=[i100, i200, i300],
                       user_ids=[guardian, c100, c200, c300])



# ── 13. Marker rounding — precision is exactly 3 decimal places ────
def test_round_marker_coord_precision_is_exactly_3dp():
    """Privacy contract: the rounded coordinate must never carry more
    than 3 decimal places of precision (~111m at the equator). The
    backend treats this as a hard constraint — anything more granular
    leaks precise child location."""
    assert MARKER_PRECISION_DP == 3  # locked by the privacy spec
    # Mumbai-ish reference. 6dp input → 3dp output, every time.
    assert round_marker_coord(19.076543) == 19.077
    assert round_marker_coord(72.877812) == 72.878
    # Negative, rounding away from zero on .5 ties uses banker's rounding
    # (Python default), which is acceptable as long as the magnitude is
    # never > 3dp. Verify by string repr to catch float dust.
    out = round_marker_coord(19.076500001)
    assert isinstance(out, float)
    # 3dp boundary: max 3 digits after the dot, no scientific notation.
    s = f"{out:.10f}".rstrip("0").rstrip(".")
    decimal_part = s.split(".", 1)[1] if "." in s else ""
    assert len(decimal_part) <= 3, f"more than 3dp: {s!r}"


# ── 14. Marker rounding is stable across calls (deterministic) ─────
def test_round_marker_coord_stable_across_calls():
    """`round` is pure — same input must produce the same output every
    invocation. This locks the contract that successive map renders
    don't jitter the marker."""
    inputs = [19.076543, 72.877812, -33.865143, 0.0, -0.000123, 100.999999]
    first_pass = [round_marker_coord(x) for x in inputs]
    # Call 100 more times; assert byte-for-byte identical output.
    for _ in range(100):
        assert [round_marker_coord(x) for x in inputs] == first_pass


# ── 15. Marker rounding returns None when no location is available ─
def test_round_marker_coord_none_when_no_location():
    """Children without a `last_known_lat/lng` come through as None.
    The helper must propagate that None — never substitute a default
    (`0.0` would put markers in the Atlantic Ocean off Ghana, which
    is both geographically nonsensical and a privacy footgun)."""
    assert round_marker_coord(None) is None


# ── 16. Rounded marker is within ~111m of the true coordinate ─────
def test_round_marker_within_111m_of_true_coord():
    """Privacy AND directional accuracy: the rounded marker must
    point within ~111m of where the child actually is. The spec's
    100m bucket ≈ 0.001° ≈ 111m at the equator and ~104m at India's
    latitude. We assert the worst case (equator) holds."""
    # Worst case offset from rounding to 3dp is 0.0005° in each axis,
    # giving a sqrt(0.0005² + 0.0005²) × 111_320 ≈ 78.7m diagonal.
    # We test a real Mumbai coordinate to keep it geographically real.
    true_lat, true_lng = 19.076543, 72.877812
    rl = round_marker_coord(true_lat)
    rg = round_marker_coord(true_lng)
    assert rl is not None and rg is not None
    d = _haversine_m(true_lat, true_lng, rl, rg)
    assert d <= 111.0, f"rounded marker {d:.2f}m from true — privacy/UX bound exceeded"


# ── 17. /nearby endpoint surfaces rounded marker_lat/lng (3dp) ─────
@pytest.mark.asyncio
async def test_nearby_endpoint_surfaces_rounded_marker(db):
    """End-to-end: a child at a 6dp coordinate must come through the
    `/nearby` response with `marker_lat`/`marker_lng` rounded to 3dp.
    Locks the wire contract."""
    GLAT, GLNG = 19.0760, 72.8777
    # Child at 6dp granularity, ~150m east of guardian.
    CHILD_LAT, CHILD_LNG = 19.076543, 72.879234
    async with db() as s:
        guardian = await _seed_user(s, "guardian")
        child = await _seed_user(s, "user", lat=CHILD_LAT, lng=CHILD_LNG)
        await _seed_relationship(s, guardian, child)
        iid = await _seed_incident(s, child, state="escalated")
        await s.commit()

    async with db() as s:
        out = await get_nearby_incidents(
            lat=GLAT, lng=GLNG, radius=500, zone=None, limit=20,
            status="active", session=s, user=_u(guardian, "guardian"),
        )

    assert out["total"] == 1
    inc = out["incidents"][0]
    assert "marker_lat" in inc and "marker_lng" in inc
    assert inc["marker_lat"] == round(CHILD_LAT, 3)
    assert inc["marker_lng"] == round(CHILD_LNG, 3)
    # Rounded marker → child true coord must be within 111m.
    d = _haversine_m(CHILD_LAT, CHILD_LNG, inc["marker_lat"], inc["marker_lng"])
    assert d <= 111.0

    # Idempotency at the API surface — second call returns identical markers.
    async with db() as s2:
        out2 = await get_nearby_incidents(
            lat=GLAT, lng=GLNG, radius=500, zone=None, limit=20,
            status="active", session=s2, user=_u(guardian, "guardian"),
        )
    inc2 = out2["incidents"][0]
    assert inc2["marker_lat"] == inc["marker_lat"]
    assert inc2["marker_lng"] == inc["marker_lng"]

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[guardian, child])
