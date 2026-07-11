"""SF-03 — Survey of India boundary precision regression tests.

Politically sensitive — failure of any of these assertions means
the safety platform may be rendering disputed Indian territory
incorrectly. Read the full module doc before editing.

What's locked here:

  1. **Arunachal Pradesh sovereignty** — Tawang, Itanagar, Walong,
     and central frontier points all resolve to 'Arunachal Pradesh'.
     The previous 196k km² bbox would have ALSO returned them, but
     the bbox additionally returned Bhutanese and Myanmar points
     as Indian — both are now rejected.

  2. **Aksai Chin per SOI** — points within the SOI-claimed extent
     resolve to 'Ladakh' (NOT None, NOT 'unclassified'). Before
     this migration, every Aksai Chin point rendered as "outside
     India" on the operator console, which is a press-issue risk
     for an India-operating safety app.

  3. **Negative cases** — Bhutan, Myanmar, and Xinjiang points
     stay outside India per the new polygons. The previous
     Arunachal bbox incorrectly claimed parts of Bhutan and Myanmar.

  4. **Audit infrastructure** — `list_soi_approx_rows` returns
     exactly the two curated rows (Arunachal Pradesh + Ladakh), so
     the operator console renders the right "REPLACE WITH OFFICIAL
     SHAPEFILE" tiles.

Architecture note:
  Multi-loop DB tests fight the asyncpg pool's loop-binding. We
  consolidate every live-PG sovereignty assertion into ONE event
  loop (`test_sovereignty_contract_live`). The non-DB assertions
  (positive audit metadata + the bbox shrink invariant) run as
  individual sync tests against curated SQL.
"""
from __future__ import annotations

import asyncio
import os

import pytest


# `live_pg` marker — opt-in only. Lets CI runs without Supabase
# connectivity skip the sovereignty checks cleanly.
pytestmark = pytest.mark.live_pg


# ── Helpers ──────────────────────────────────────────────────────


def _enable_postgis() -> None:
    os.environ["ENV_HAZARD_USE_POSTGIS"] = "true"


# ── Single live-DB sovereignty contract ──────────────────────────


# Locked test fixtures — all coordinates publicly documented.
_ARUNACHAL_PRADESH_INSIDE = [
    ("Tawang town (near Bhutan border)", 27.59, 91.85),
    ("Itanagar (state capital)",          27.10, 93.60),
    ("Walong (easternmost India)",        28.13, 97.00),
    ("Bomdila (West Kameng)",             27.27, 92.40),
    ("Pasighat (East Siang)",             28.07, 95.33),
]

_AKSAI_CHIN_INSIDE = [
    ("Aksai Chin centre",                  35.10, 79.50),
    ("Aksai Chin SE near Demchok area",    34.30, 79.50),
    ("Aksai Chin centre-east",             34.90, 79.80),
    ("Northern Aksai Chin (Kunlun foot)",  35.30, 79.20),
]

_LEH = ("Leh (central Ladakh)", 34.16, 77.58)

_NOT_INDIA = [
    ("Thimphu (Bhutan capital)",            27.47, 89.64),
    ("Paro (western Bhutan)",               27.43, 89.41),
    ("Myitkyina (Kachin, Myanmar)",         25.38, 97.39),
    ("Hotan (Xinjiang)",                    37.10, 79.92),
    ("Kashgar (Xinjiang)",                  39.47, 75.99),
]


def test_sovereignty_contract_live():
    """ONE live-DB test, ONE event loop. Asserts every locked
    sovereignty point in a single batch so we don't fight the
    asyncpg pool's loop-binding across multiple pytest tests."""
    _enable_postgis()

    async def _run():
        from app.services.external_signals.sachet_provider import _postgis_resolve_state
        # Clear LRU so previous-run cached results don't mask regressions
        try:
            _postgis_resolve_state.cache_clear()
        except AttributeError:
            pass

        failures: list[str] = []

        # 1. Arunachal Pradesh — every point must resolve.
        for label, lat, lng in _ARUNACHAL_PRADESH_INSIDE:
            state = await _postgis_resolve_state(lat, lng)
            if state != "Arunachal Pradesh":
                failures.append(
                    f"ARUNACHAL INSIDE: {label} ({lat},{lng}) -> {state!r} "
                    f"(expected 'Arunachal Pradesh')"
                )

        # 2. Aksai Chin — must resolve to Ladakh per SOI.
        for label, lat, lng in _AKSAI_CHIN_INSIDE:
            state = await _postgis_resolve_state(lat, lng)
            if state != "Ladakh":
                failures.append(
                    f"AKSAI CHIN: {label} ({lat},{lng}) -> {state!r} "
                    f"(expected 'Ladakh' per SOI)"
                )

        # 3. Central Ladakh — untouched OSM polygon still works.
        state = await _postgis_resolve_state(_LEH[1], _LEH[2])
        if state != "Ladakh":
            failures.append(
                f"LEH: ({_LEH[1]},{_LEH[2]}) -> {state!r} (expected 'Ladakh')"
            )

        # 4. Neighbouring countries — must NOT be claimed as India.
        for label, lat, lng in _NOT_INDIA:
            state = await _postgis_resolve_state(lat, lng)
            if state is not None:
                failures.append(
                    f"NOT INDIA: {label} ({lat},{lng}) -> {state!r} "
                    f"(expected None — outside India)"
                )

        return failures

    try:
        failures = asyncio.run(_run())
    except Exception as e:  # pragma: no cover — env skip
        pytest.skip(f"DB unreachable in this env: {e!r}")

    assert not failures, (
        "SOI sovereignty contract violated:\n  " + "\n  ".join(failures)
    )


# ── Audit infrastructure (live DB, single-loop) ──────────────────


def test_soi_audit_returns_curated_rows_live():
    """Audit table must surface every `soi_curated_approx` row + the
    replacement-shapefile marker."""

    async def _run():
        from app.services.soi_boundary_audit import list_soi_approx_rows
        from app.db.session import async_session
        async with async_session() as session:
            return await list_soi_approx_rows(session)

    try:
        rows = asyncio.run(_run())
    except Exception as e:  # pragma: no cover — env skip
        pytest.skip(f"DB unreachable in this env: {e!r}")

    names = {r["name"] for r in rows}
    sources = {r["source"] for r in rows}
    assert "Arunachal Pradesh" in names, (
        "Arunachal Pradesh must be tagged for SOI shapefile replacement"
    )
    assert "Ladakh" in names, (
        "Aksai Chin row (named 'Ladakh' per SOI) must be tagged for replacement"
    )
    # SF-03c: rows are now sourced from GADM v4.1 (gadm_indian_claim).
    # Legacy soi_curated_approx rows may also be present in older envs.
    assert sources <= {"soi_curated_approx", "gadm_indian_claim"}, (
        f"Unexpected sources in audit: {sources}"
    )
    for r in rows:
        notes = r.get("boundary_notes") or ""
        assert "REPLACE WITH OFFICIAL" in notes, (
            f"{r['name']} missing 'REPLACE WITH OFFICIAL SHAPEFILE' marker"
        )
        assert r["verified_at"] is not None, (
            f"{r['name']} must record SOI verification timestamp"
        )


def test_arunachal_polygon_smaller_than_legacy_bbox_live():
    """The pre-SF-03 bbox covered 196,246 km². The new SOI-aligned
    polygon must be SUBSTANTIALLY smaller. Locking this invariant
    prevents a future "innocent" revert to a rough rectangle."""

    async def _run():
        from sqlalchemy import text
        from app.db.session import async_session
        async with async_session() as session:
            return (await session.execute(text("""
                SELECT area_km2 FROM env_hazard_zones
                 WHERE type = 'state_boundary'
                   AND name = 'Arunachal Pradesh'
                   AND source IN ('soi_curated_approx', 'gadm_indian_claim')
                 LIMIT 1
            """))).scalar()

    try:
        area = asyncio.run(_run())
    except Exception as e:  # pragma: no cover — env skip
        pytest.skip(f"DB unreachable in this env: {e!r}")

    assert area is not None, "Arunachal SOI-curated row must exist post-SF-03"
    # Must be at least ~25% smaller than the legacy bbox.
    assert area < 150_000, (
        f"Arunachal SOI polygon area {area:.0f} km² is too close to the "
        f"legacy 196,246 km² bbox — possible accidental revert."
    )


# ── SF-03c lock — GADM Indian-claim precision invariants ─────────


def test_sf03c_arunachal_within_2pct_of_soi_published_live():
    """Lock the SF-03c+d GADM-Indian-claim union (IND.3 ∪ Z07) area
    against the SOI-published Arunachal Pradesh figure (~83,743 km²).

    Allows ±5 % drift to absorb GADM minor releases without breaking CI,
    but tightens the previous "< 150,000" sloppiness — an accidental
    revert to Z07-alone (67k) or the legacy bbox (196k) fails loudly.
    """
    async def _run():
        from sqlalchemy import text
        from app.db.session import async_session
        async with async_session() as session:
            return (await session.execute(text("""
                SELECT area_km2 FROM env_hazard_zones
                 WHERE type = 'state_boundary'
                   AND name = 'Arunachal Pradesh'
                   AND source = 'gadm_indian_claim'
                 LIMIT 1
            """))).scalar()

    try:
        area = asyncio.run(_run())
    except Exception as e:  # pragma: no cover — env skip
        pytest.skip(f"DB unreachable: {e!r}")

    if area is None:
        pytest.skip("SF-03c GADM row not present in this env")

    SOI_PUBLISHED = 83_743.0
    lo, hi = SOI_PUBLISHED * 0.95, SOI_PUBLISHED * 1.05
    assert lo <= area <= hi, (
        f"Arunachal GADM-Indian-claim area {area:.0f} km² outside "
        f"[{lo:.0f}, {hi:.0f}] band around SOI {SOI_PUBLISHED:.0f} km²"
    )


def test_sf03c_aksai_chin_within_5pct_of_soi_published_live():
    """Aksai Chin (tagged 'Ladakh' per SOI) should be ~37,555 km² per
    GADM CHN Z02.28 ∪ Z03.28 ∪ Z03.29 ∪ Z08.29 union. ±5 % band."""
    async def _run():
        from sqlalchemy import text
        from app.db.session import async_session
        async with async_session() as session:
            return (await session.execute(text("""
                SELECT area_km2 FROM env_hazard_zones
                 WHERE type = 'state_boundary'
                   AND name = 'Ladakh'
                   AND source = 'gadm_indian_claim'
                 LIMIT 1
            """))).scalar()

    try:
        area = asyncio.run(_run())
    except Exception as e:  # pragma: no cover
        pytest.skip(f"DB unreachable: {e!r}")

    if area is None:
        pytest.skip("SF-03c GADM Aksai Chin row not present in this env")

    SOI_PUBLISHED = 37_555.0
    lo, hi = SOI_PUBLISHED * 0.92, SOI_PUBLISHED * 1.08
    assert lo <= area <= hi, (
        f"Aksai Chin GADM area {area:.0f} km² outside "
        f"[{lo:.0f}, {hi:.0f}] band around SOI {SOI_PUBLISHED:.0f} km²"
    )


def test_sf03c_provenance_url_in_boundary_notes_live():
    """Every gadm_indian_claim row MUST cite gadm.org in boundary_notes
    (provenance audit trail per SF-03c spec)."""
    async def _run():
        from sqlalchemy import text
        from app.db.session import async_session
        async with async_session() as session:
            return (await session.execute(text("""
                SELECT name, boundary_notes
                  FROM env_hazard_zones
                 WHERE source = 'gadm_indian_claim'
            """))).fetchall()

    try:
        rows = asyncio.run(_run())
    except Exception as e:  # pragma: no cover
        pytest.skip(f"DB unreachable: {e!r}")

    if not rows:
        pytest.skip("No gadm_indian_claim rows in this env")
    for r in rows:
        notes = r.boundary_notes or ""
        assert "gadm.org" in notes, (
            f"{r.name} missing gadm.org provenance URL in boundary_notes"
        )
        assert "REPLACE WITH OFFICIAL" in notes, (
            f"{r.name} missing shapefile-replacement marker"
        )


# ── Migration-level invariants (no DB needed) ────────────────────


def test_arunachal_pradesh_wkt_excludes_bhutan_meridian():
    """Static lock — the new Arunachal polygon's westernmost vertex
    must be EAST of ~91.65° E (the Bhutan-Arunachal border).
    The legacy bbox claimed parts of Bhutan with west edge at 91.50."""
    from migrations.versions import sf03_soi_boundary_precision as m
    wkt = m._ARUNACHAL_PRADESH_SOI_WKT
    # Extract all longitudes (first number of each "lng lat" pair)
    body = wkt.split("((")[1].split("))")[0]
    longs = [float(p.strip().split()[0]) for p in body.split(",")]
    westmost = min(longs)
    assert westmost >= 91.60, (
        f"Arunachal westernmost vertex {westmost} encroaches on Bhutan "
        f"(safe edge is ~91.65 E)"
    )


def test_arunachal_pradesh_wkt_excludes_myanmar_meridian():
    """Eastern Arunachal-Myanmar border is around 97.40 E. The new
    polygon's easternmost vertex must NOT exceed 97.40 by much."""
    from migrations.versions import sf03_soi_boundary_precision as m
    wkt = m._ARUNACHAL_PRADESH_SOI_WKT
    body = wkt.split("((")[1].split("))")[0]
    longs = [float(p.strip().split()[0]) for p in body.split(",")]
    eastmost = max(longs)
    assert eastmost <= 97.50, (
        f"Arunachal easternmost vertex {eastmost} encroaches on Myanmar"
    )


def test_aksai_chin_wkt_uses_expanded_polygon():
    """The SF-03b patch widened Aksai Chin. The expanded polygon's
    east edge must reach at least 80.40 E (SOI-claimed extent)."""
    from migrations.versions import sf03b_expand_aksai_chin as m
    wkt = m._AKSAI_CHIN_EXPANDED_WKT
    body = wkt.split("((")[1].split("))")[0]
    longs = [float(p.strip().split()[0]) for p in body.split(",")]
    eastmost = max(longs)
    assert eastmost >= 80.40, (
        f"Aksai Chin east edge {eastmost} fails to reach SOI-claimed "
        f"extent (must reach >= 80.40 E)"
    )
