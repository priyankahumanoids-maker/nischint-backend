"""SF-03d — Arunachal Pradesh proper-union refinement.

Why this exists:
  SF-03c imported GADM `Z07.3_1` alone for Arunachal Pradesh, yielding
  67,130 km². Audit against SOI-published figure (83,743 km²): -20 %.
  Root cause: GADM v4.1 splits Arunachal into TWO Level-1 features —
    * IND.3_1 (~14,866 km²) — internationally-accepted core
    * Z07.3_1 (~67,130 km²) — disputed-additional (China-contested)
  Either alone is incomplete; the SOI claim is their UNION.

What this does:
  UPDATE the existing Arunachal Pradesh row (still `gadm_indian_claim`)
  to ST_Union(IND.3_1, Z07.3_1). Result: 81,996 km² — within 2 % of
  SOI's published figure.

  Aksai Chin is unchanged from SF-03c (already a 4-feature union).

Provenance unchanged: GADM v4.1 (https://gadm.org/data.html). The
feature set is now both `IND.3_1` AND `Z07.3_1` from the same file.
"""
from __future__ import annotations

import json
import pathlib

from alembic import op


revision = "sf03d_arunachal_union"
down_revision = "sf03c_gadm_indian_claim"
branch_labels = None
depends_on = None


_DATA_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "boundaries"


def _load_feature(filename: str, gid_1: str) -> dict:
    path = _DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"GADM source missing: {path}")
    with path.open() as f:
        d = json.load(f)
    for feat in d.get("features", []):
        if feat.get("properties", {}).get("GID_1") == gid_1:
            return feat["geometry"]
    raise LookupError(f"GID_1 '{gid_1}' not found in {filename}")


_ARUNACHAL_UNION_NOTES = (
    "Source: GADM v4.1 (https://gadm.org/data.html). "
    "Features unioned: gadm41_IND_1.json GID_1 in "
    "(IND.3_1=internationally-accepted core, Z07.3_1=China-disputed extension). "
    "Together = SOI-claim Arunachal Pradesh. Imported on 2026-05-30 via ST_Union. "
    "License: see https://gadm.org/license.html. "
    "REPLACE WITH OFFICIAL MoEFCC SHAPEFILE when available."
)


def upgrade() -> None:
    from sqlalchemy import text as sa_text
    bind = op.get_bind()

    ind3 = json.dumps(_load_feature("gadm41_IND_1.json", "IND.3_1"))
    z07 = json.dumps(_load_feature("gadm41_IND_1.json", "Z07.3_1"))

    bind.execute(
        sa_text("""
            UPDATE env_hazard_zones
               SET geom = ST_Multi(ST_Union(
                       ST_SetSRID(ST_GeomFromGeoJSON(:a), 4326),
                       ST_SetSRID(ST_GeomFromGeoJSON(:b), 4326)
                   )),
                   area_km2 = ST_Area((ST_Multi(ST_Union(
                       ST_SetSRID(ST_GeomFromGeoJSON(:a), 4326),
                       ST_SetSRID(ST_GeomFromGeoJSON(:b), 4326)
                   )))::geography) / 1000000.0,
                   boundary_notes = :notes,
                   verified_at = NOW()
             WHERE type = 'state_boundary'
               AND name = 'Arunachal Pradesh'
               AND source = 'gadm_indian_claim';
        """),
        {"a": ind3, "b": z07, "notes": _ARUNACHAL_UNION_NOTES},
    )


def downgrade() -> None:
    # Revert to Z07-alone (the SF-03c state). Aksai Chin not touched.
    from sqlalchemy import text as sa_text
    bind = op.get_bind()

    z07 = json.dumps(_load_feature("gadm41_IND_1.json", "Z07.3_1"))
    revert_notes = (
        "Source: GADM v4.1 (https://gadm.org/data.html). "
        "Feature: gadm41_IND_1.json GID_1=Z07.3_1 (NAME_1=ArunachalPradesh, "
        "disputed China-India Z-coded layer following Indian sovereignty claim). "
        "Imported on 2026-05-30. Vertex count ~1193, covers McMahon Line. "
        "License: see https://gadm.org/license.html. "
        "REPLACE WITH OFFICIAL MoEFCC SHAPEFILE when available."
    )

    bind.execute(
        sa_text("""
            UPDATE env_hazard_zones
               SET geom = ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:gj), 4326)),
                   area_km2 = ST_Area(
                       ST_SetSRID(ST_GeomFromGeoJSON(:gj), 4326)::geography
                   ) / 1000000.0,
                   boundary_notes = :notes,
                   verified_at = NOW()
             WHERE type = 'state_boundary'
               AND name = 'Arunachal Pradesh'
               AND source = 'gadm_indian_claim';
        """),
        {"gj": z07, "notes": revert_notes},
    )
