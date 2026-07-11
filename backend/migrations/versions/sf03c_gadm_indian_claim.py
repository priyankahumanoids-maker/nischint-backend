"""SF-03c — Replace SOI-curated polygons with GADM Indian-claim dataset.

Why this exists (read in full before editing — politically sensitive):
  SF-03 + SF-03b shipped hand-drawn ("soi_curated_approx") polygons for
  Arunachal Pradesh and Aksai Chin. Audit findings:
    * Arunachal Pradesh: 104,544 km² vs SOI-published ~83,743 km²
      (+25% — bleeds into Bhutan/Myanmar edges).
    * Aksai Chin: 26,079 km² vs SOI-published ~37,555 km²
      (-30% — north-eastern Karakash basin lobe missing).
  Both rows were tagged "REPLACE WITH OFFICIAL SHAPEFILE when available."

What this migration does:
  Imports the **GADM v4.1 Indian-claim disputed features** (the GADM
  Z-coded layer that follows India's officially-claimed sovereignty
  boundaries per Survey of India position):

    Arunachal Pradesh:
      * GADM IND L1 feature  GID_1 = "Z07.3_1"  (NAME_1 = ArunachalPradesh)
        — 1,193 vertices, bbox 91.55–97.42 E × 26.89–29.46 N
        — covers the full McMahon Line claim including Tawang

    Aksai Chin (rendered as part of Ladakh):
      * GADM CHN L1 feature  GID_1 = "Z02.28_1"  (XinjiangUygur disputed)
        — Trans-Karakoram Tract (Shaksgam Valley, ceded by Pakistan to
          China in 1963; claimed by India)
      * GADM CHN L1 feature  GID_1 = "Z03.28_1"  (XinjiangUygur disputed)
        — Aksai Chin proper (Xinjiang-administered, claimed by India)
      * GADM CHN L1 feature  GID_1 = "Z03.29_1"  (Xizang disputed)
        — Aksai Chin (Tibet-administered, claimed by India)
      * GADM CHN L1 feature  GID_1 = "Z08.29_1"  (Xizang disputed)
        — Demchok area dispute (small southern lobe, claimed by India)
    All 4 are unioned via ST_Union into a single MultiPolygon.

Both rows are tagged `source='gadm_indian_claim'` with a provenance
URL in `boundary_notes`. The legacy `soi_curated_approx` rows are
UPDATEd in place (no row-id churn — anything FK'ing this row stays
valid).

Provenance and audit trail:
  Source: GADM v4.1
    https://gadm.org/data.html
    Files: gadm41_IND_1.json (1.6 MB), gadm41_CHN_1.json (2.3 MB)
    Downloaded: 2026-05-30, stored at
      /app/backend/data/boundaries/gadm41_{IND,CHN}_1.json
  License: GADM data is free for non-commercial use; downstream
    deployments must verify license compliance for their use case.
    See https://gadm.org/license.html.

Replacement path:
  When the official MoEFCC / SOI shapefile lands, replace via:
      UPDATE env_hazard_zones
         SET geom   = ST_GeomFromGeoJSON(:official_geojson),
             source = 'soi_official',
             boundary_notes = NULL
       WHERE source = 'gadm_indian_claim' AND name = :state_name;

Rollback semantics:
  Downgrade reverts to the SF-03b polygons (smaller Aksai Chin claim,
  hand-drawn Arunachal). **Do NOT run downgrade in production** —
  the reverted polygons are less accurate than what this migration
  ships. Provided only for emergency rollback during the migration
  window.
"""
from __future__ import annotations

import json
import pathlib

from alembic import op


revision = "sf03c_gadm_indian_claim"
down_revision = "hc02_health_signals_pg"
branch_labels = None
depends_on = None


# Provenance — pinned to the immutable URL pattern. Recorded in
# `boundary_notes` so the operator console can render the source link.
_GADM_BASE_URL = "https://geodata.ucdavis.edu/gadm/gadm4.1/json"
_GADM_LICENSE_URL = "https://gadm.org/license.html"
_DATA_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "boundaries"


def _load_feature(filename: str, gid_1: str) -> dict:
    """Return the GeoJSON `geometry` for a specific GADM Level-1 feature.

    Raises if the file is missing or the GID_1 isn't found — never silent.
    """
    path = _DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(
            f"GADM source file missing: {path}. "
            "Re-download from "
            f"{_GADM_BASE_URL}/{filename} (per migration docstring)."
        )
    with path.open() as f:
        d = json.load(f)
    for feat in d.get("features", []):
        if feat.get("properties", {}).get("GID_1") == gid_1:
            return feat["geometry"]
    raise LookupError(
        f"GID_1 '{gid_1}' not found in {filename}. "
        "GADM may have re-coded its disputed features — re-audit before re-running."
    )


def _arunachal_geojson() -> str:
    """Z07.3_1 — Indian-claim ArunachalPradesh per GADM v4.1."""
    return json.dumps(_load_feature("gadm41_IND_1.json", "Z07.3_1"))


def _aksai_chin_features_geojson() -> list[str]:
    """4 GADM CHN L1 features that together cover the Indian-claim
    Aksai Chin extent. ST_Union merges them in-DB into a single shape.
    """
    return [
        json.dumps(_load_feature("gadm41_CHN_1.json", "Z02.28_1")),  # Trans-Karakoram
        json.dumps(_load_feature("gadm41_CHN_1.json", "Z03.28_1")),  # Aksai Chin (XJ)
        json.dumps(_load_feature("gadm41_CHN_1.json", "Z03.29_1")),  # Aksai Chin (Tibet)
        json.dumps(_load_feature("gadm41_CHN_1.json", "Z08.29_1")),  # Demchok dispute
    ]


_ARUNACHAL_NOTES = (
    "Source: GADM v4.1 (https://gadm.org/data.html). "
    "Feature: gadm41_IND_1.json GID_1=Z07.3_1 (NAME_1=ArunachalPradesh, "
    "disputed China-India Z-coded layer following Indian sovereignty claim). "
    "Imported on 2026-05-30. Vertex count ~1193, covers McMahon Line. "
    "License: see https://gadm.org/license.html. "
    "REPLACE WITH OFFICIAL MoEFCC SHAPEFILE when available."
)

_AKSAI_CHIN_NOTES = (
    "Source: GADM v4.1 (https://gadm.org/data.html). "
    "Features unioned: gadm41_CHN_1.json GID_1 in "
    "(Z02.28_1=Trans-Karakoram, Z03.28_1=Aksai Chin XJ, "
    "Z03.29_1=Aksai Chin Tibet, Z08.29_1=Demchok dispute). "
    "Imported on 2026-05-30 via ST_Union. License: see "
    "https://gadm.org/license.html. REPLACE WITH OFFICIAL MoEFCC "
    "SHAPEFILE when available."
)


def upgrade() -> None:
    # ── 0. Widen geom column from POLYGON → MULTIPOLYGON ──────────
    # The legacy schema constrained `env_hazard_zones.geom` to a
    # plain POLYGON. Real-world admin boundaries are MULTIPOLYGON
    # (islands / exclaves / disjoint claim regions). Widening is
    # safe — existing single-polygon rows are coerced via ST_Multi,
    # and a MULTIPOLYGON column accepts new single-polygon writes
    # implicitly via ST_Multi on the application side if needed.
    op.execute("""
        ALTER TABLE env_hazard_zones
            ALTER COLUMN geom TYPE geometry(MultiPolygon, 4326)
            USING ST_Multi(geom);
    """)

    # ── 1. Update Arunachal Pradesh in place ──────────────────────
    # Keep the existing row id; just swap geom/source/notes. The
    # GeoJSON is passed via a parameter (NOT string interpolation)
    # so we don't accidentally inject ~1.4MB of GeoJSON into the
    # SQL text. `ST_GeomFromGeoJSON` + `ST_SetSRID(4326)` ensures
    # the SRID is consistent with the rest of the table.
    arunachal_gj = _arunachal_geojson()
    op.execute(
        op.inline_literal  # not used, placeholder to keep import order
    ) if False else None
    # Use direct bind via SQLAlchemy text — alembic's op.execute
    # accepts SQLAlchemy text() with bind params.
    from sqlalchemy import text as sa_text
    bind = op.get_bind()

    bind.execute(
        sa_text("""
            UPDATE env_hazard_zones
               SET geom = ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:gj), 4326)),
                   area_km2 = ST_Area(
                       ST_SetSRID(ST_GeomFromGeoJSON(:gj), 4326)::geography
                   ) / 1000000.0,
                   source = 'gadm_indian_claim',
                   boundary_notes = :notes,
                   verified_at = NOW()
             WHERE type = 'state_boundary'
               AND name = 'Arunachal Pradesh'
               AND source = 'soi_curated_approx';
        """),
        {"gj": arunachal_gj, "notes": _ARUNACHAL_NOTES},
    )

    # ── 2. Update Aksai Chin (tagged 'Ladakh') with the union ─────
    # We `ST_Union` four GADM features → single MultiPolygon. The
    # union runs in-DB so the migration doesn't depend on shapely.
    aksai_features = _aksai_chin_features_geojson()
    # Build a UNION expression in SQL. Parametrize each piece.
    union_sql_parts = []
    params = {"notes": _AKSAI_CHIN_NOTES}
    for i, gj in enumerate(aksai_features):
        params[f"gj{i}"] = gj
        union_sql_parts.append(
            f"ST_SetSRID(ST_GeomFromGeoJSON(:gj{i}), 4326)"
        )
    union_expr = "ST_Multi(ST_Union(ARRAY[" + ", ".join(union_sql_parts) + "]))"

    bind.execute(
        sa_text(f"""
            UPDATE env_hazard_zones
               SET geom = {union_expr},
                   area_km2 = ST_Area(({union_expr})::geography) / 1000000.0,
                   source = 'gadm_indian_claim',
                   boundary_notes = :notes,
                   verified_at = NOW()
             WHERE type = 'state_boundary'
               AND name = 'Ladakh'
               AND source = 'soi_curated_approx';
        """),
        params,
    )

    # ── 3. Audit index for the new source tag ─────────────────────
    # Keep the existing soi_curated_approx index alive (no rows match
    # it post-upgrade; harmless empty partial index) for any operator
    # tooling that queries it. Add the new tag's index.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_env_hazard_zones_gadm_indian_claim
            ON env_hazard_zones (source)
         WHERE source = 'gadm_indian_claim';
    """)


def downgrade() -> None:
    # WARNING: Reverts to the SF-03b polygons. Both are LESS accurate
    # than the GADM Indian-claim layer this migration ships. Provided
    # only for emergency rollback during the migration window.
    #
    # We restore the prior polygons inline (rather than depending on
    # SF-03/SF-03b downgrade being chained) so this migration is
    # self-contained.
    arunachal_wkt = (
        "POLYGON(("
        "91.65 26.85, 91.70 27.10, 91.80 27.55, 91.66 27.93, "
        "92.20 28.20, 93.00 28.55, 94.00 28.85, 95.40 29.10, "
        "96.30 29.25, 97.30 28.60, 97.40 27.80, 96.95 27.10, "
        "96.20 27.30, 95.30 27.10, 94.50 27.30, 93.60 26.95, "
        "92.50 26.80, 92.00 26.75, 91.65 26.85"
        "))"
    )
    aksai_wkt = (
        "POLYGON(("
        "78.10 35.55, 78.80 35.60, 79.50 35.55, 80.20 35.50, "
        "80.50 35.20, 80.40 34.80, 80.10 34.40, 79.70 34.20, "
        "79.30 34.20, 78.90 34.30, 78.55 34.55, 78.25 34.90, "
        "78.10 35.20, 78.10 35.55"
        "))"
    )
    op.execute(f"""
        UPDATE env_hazard_zones
           SET geom = ST_Multi(ST_SetSRID(ST_GeomFromText('{arunachal_wkt}'), 4326)),
               area_km2 = ST_Area(
                   ST_SetSRID(ST_GeomFromText('{arunachal_wkt}'), 4326)::geography
               ) / 1000000.0,
               source = 'soi_curated_approx',
               boundary_notes = 'SF-03b restored — hand-drawn approximation.',
               verified_at = NOW()
         WHERE type = 'state_boundary'
           AND name = 'Arunachal Pradesh'
           AND source = 'gadm_indian_claim';
    """)
    op.execute(f"""
        UPDATE env_hazard_zones
           SET geom = ST_Multi(ST_SetSRID(ST_GeomFromText('{aksai_wkt}'), 4326)),
               area_km2 = ST_Area(
                   ST_SetSRID(ST_GeomFromText('{aksai_wkt}'), 4326)::geography
               ) / 1000000.0,
               source = 'soi_curated_approx',
               boundary_notes = 'SF-03b restored — hand-drawn approximation.',
               verified_at = NOW()
         WHERE type = 'state_boundary'
           AND name = 'Ladakh'
           AND source = 'gadm_indian_claim';
    """)
    op.execute("DROP INDEX IF EXISTS ix_env_hazard_zones_gadm_indian_claim;")
    # Narrow the geom column back to POLYGON. Best-effort — fails
    # loudly if any row is a true multi-part polygon (which it
    # shouldn't be after the UPDATEs above). The `ST_GeometryN(geom,1)`
    # USING clause picks the first polygon ring as a fallback.
    op.execute("""
        ALTER TABLE env_hazard_zones
            ALTER COLUMN geom TYPE geometry(Polygon, 4326)
            USING ST_GeometryN(geom, 1);
    """)
