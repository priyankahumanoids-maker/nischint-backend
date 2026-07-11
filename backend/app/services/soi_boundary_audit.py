"""SF-03 — Survey of India boundary precision audit service.

Two responsibilities only:
  1. Surface rows in `env_hazard_zones` that are SOI-approximate
     (`source='soi_curated_approx'`) so the operator console can
     flag them for replacement when the official MoEFCC shapefile
     is uploaded.
  2. Provide a sanity check helper — `is_inside_india_per_soi(lat, lng)` —
     that consumers can call without touching the underlying
     `env_hazard_zones` table directly. Used by tests and by any
     future "outside India" UI guard.

Kept deliberately small. The migration owns the curated polygons;
this service is the read-only consumer surface.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


SOI_APPROX_SOURCE = "soi_curated_approx"

# SF-03c (May 30, 2026): rows that defer-to-shapefile now also include
# the GADM Indian-claim layer. Both sources should surface in the audit
# until an official MoEFCC SOI shapefile lands.
SHAPEFILE_PENDING_SOURCES = ("soi_curated_approx", "gadm_indian_claim")


async def list_soi_approx_rows(
    session: AsyncSession,
) -> list[dict[str, Any]]:
    """Return every row awaiting the official MoEFCC SOI shapefile —
    currently both `soi_curated_approx` (legacy hand-drawn) and
    `gadm_indian_claim` (SF-03c GADM v4.1 import). Operator console
    renders these as "REPLACE WITH OFFICIAL SHAPEFILE" tiles."""
    rows = (await session.execute(
        text("""
            SELECT name, state, source, area_km2, boundary_notes,
                   verified_at, created_at
              FROM env_hazard_zones
             WHERE source = ANY(:srcs)
             ORDER BY name
        """),
        {"srcs": list(SHAPEFILE_PENDING_SOURCES)},
    )).fetchall()
    return [
        {
            "name":            r.name,
            "state":           r.state,
            "source":          r.source,
            "area_km2":        float(r.area_km2) if r.area_km2 is not None else None,
            "boundary_notes":  r.boundary_notes,
            "verified_at":     r.verified_at.isoformat() if r.verified_at else None,
            "created_at":      r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


async def is_inside_india_per_soi(
    session: AsyncSession,
    lat: float,
    lng: float,
) -> bool:
    """Returns True iff (lat, lng) falls within any `state_boundary`
    polygon — including the SOI-curated Arunachal Pradesh polygon
    AND the Aksai Chin polygon (claimed as Ladakh per SOI).

    Used by tests and by any future "outside India" guard. Fail-quiet:
    on DB error returns False (callers should treat False as
    "unverified", not "definitely outside India")."""
    try:
        hit = (await session.execute(
            text("""
                SELECT 1 FROM env_hazard_zones
                 WHERE type = 'state_boundary'
                   AND ST_Within(
                          ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), geom
                       )
                 LIMIT 1
            """),
            {"lng": float(lng), "lat": float(lat)},
        )).scalar()
        return bool(hit)
    except Exception as e:  # noqa: BLE001
        logger.warning("[SF-03] is_inside_india_per_soi failed: %r", e)
        return False


__all__ = [
    "SOI_APPROX_SOURCE",
    "SHAPEFILE_PENDING_SOURCES",
    "list_soi_approx_rows",
    "is_inside_india_per_soi",
]
