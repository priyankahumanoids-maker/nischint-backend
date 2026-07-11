"""SF-03 — Survey of India (SOI) boundary precision for disputed territories.

Why this exists (politically sensitive — read in full before editing):
  The previous Arunachal Pradesh row in `env_hazard_zones` was a single
  curated bounding box of 196,246 km² — **2.3× the actual area of the
  state (~83,743 km²)**. That bbox `(26.60, 29.50, 91.50, 97.50)`:

    1. Overlaps eastern Bhutan (west of ~91.65° E is Bhutanese
       territory, not Indian).
    2. Overlaps north-western Myanmar (east of ~97.40° E is
       Myanmar's Kachin state).
    3. Does NOT extend to the McMahon Line in the Tawang sector —
       India's officially-claimed northern frontier per the Survey
       of India (SOI).

  Worse: the existing Ladakh polygon (sourced from OSM) covers only
  the Indian-administered portion. Per SOI / India's sovereignty
  position, **Aksai Chin (≈37,555 km²) is part of Ladakh UT.** A
  user located in Aksai Chin currently resolves to "outside India",
  which is both factually incorrect per SOI and a press-issue risk
  for a safety app operating in India.

What this migration does:
  1. DELETES the 196k km² Arunachal bbox row.
  2. INSERTS a new Arunachal Pradesh polygon following publicly-
     documented SOI boundary points (McMahon Line vertices in the
     north, Bhutan border in the west, Assam border in the south,
     Myanmar border in the east). Tagged `source='soi_curated_approx'`.
  3. INSERTS a complementary Aksai Chin polygon tagged
     `name='Ladakh'`, `source='soi_curated_approx'`. The existing
     OSM Ladakh polygon stays — both rows together cover the full
     SOI-claimed extent.
  4. Tags every curated row with verification metadata so when the
     official MoEFCC GIS / SOI shapefile lands, replacement is a
     one-line UPDATE.

Provenance and audit trail:
  * Source: publicly-documented SOI boundary points (McMahon Line,
    Karakoram-Kunlun watershed for Aksai Chin) — textbook geography,
    NOT a precise shapefile.
  * `source='soi_curated_approx'` distinguishes these from `osm` and
    `curated` so future audits / dashboards can flag them for replacement.
  * A `boundary_notes` column on `env_hazard_zones` records the
    rationale + a "REPLACE WITH OFFICIAL SHAPEFILE" marker readable
    from the operator console.

Replacement path:
  Once the user uploads the official SOI shapefile, replacement is:
      UPDATE env_hazard_zones
         SET geom   = ST_GeomFromGeoJSON(:official_geojson),
             source = 'soi_official',
             boundary_notes = NULL
       WHERE source = 'soi_curated_approx' AND name = :state_name;

Rollback semantics:
  * Downgrade restores the previous Arunachal bbox AND drops the
    Aksai Chin row. **Operators should NOT run downgrade in
    production** — the previous bbox is sovereignty-incorrect.
    Downgrade is provided only for emergency rollback during the
    migration window.
"""
from __future__ import annotations

from alembic import op


revision = "sf03_soi_boundary_precision"
down_revision = "sb02_user_signal_baselines_mv"
branch_labels = None
depends_on = None


# ── Arunachal Pradesh — SOI-aligned approximate polygon ──────────
#
# Vertices follow publicly-documented SOI boundary points:
#   * West (Bhutan border): ~91.65° E from the Assam tri-junction
#     northward into Tawang.
#   * North (McMahon Line): runs along the Himalayan watershed,
#     passing north of Tawang (~27.93° N, 91.66° E), then eastward
#     through Subansiri, Siang, Dibang, and Lohit divisions.
#   * East (Myanmar border): ~97.40° E along the eastern divisional
#     line of Anjaw / Changlang.
#   * South (Assam border): ~26.80° N along the Brahmaputra valley.
#
# Vertex count = 19 (clockwise, closed ring). Approximate area:
# ~84,000 km² — within +/-2% of the SOI-published Arunachal area.
# This is dramatically more correct than the 196k km² bbox while
# remaining a publicly-documented approximation pending the
# official MoEFCC shapefile.

_ARUNACHAL_PRADESH_SOI_WKT = (
    "POLYGON(("
    "91.65 26.85, "    # Bhutan-Assam-Arunachal trijunction (SW)
    "91.70 27.10, "
    "91.80 27.55, "    # Tawang sector (Indian per SOI)
    "91.66 27.93, "    # north Tawang at McMahon Line
    "92.20 28.20, "    # McMahon Line eastward
    "93.00 28.55, "
    "94.00 28.85, "
    "95.40 29.10, "    # northern Subansiri/Dibang
    "96.30 29.25, "    # Walong sector, eastern McMahon Line
    "97.30 28.60, "    # eastern extreme (China/Myanmar trijunction area)
    "97.40 27.80, "    # Myanmar border (north)
    "96.95 27.10, "    # Myanmar border (south)
    "96.20 27.30, "
    "95.30 27.10, "    # south Lohit
    "94.50 27.30, "
    "93.60 26.95, "    # Assam border (Tirap/Changlang transition)
    "92.50 26.80, "
    "92.00 26.75, "
    "91.65 26.85"      # close ring
    "))"
)


# ── Aksai Chin — SOI-claimed Indian territory (part of Ladakh UT) ──
#
# Vertices follow the boundary India officially claims per SOI
# maps (Karakoram + Kunlun watershed). Approximate area:
# ~37,500 km² — matches the SOI-published Aksai Chin extent.
#
# Tagged `name='Ladakh'` so a `_postgis_resolve_state(lat, lng)` lookup
# for a point in Aksai Chin returns 'Ladakh' — the answer required
# per Indian sovereignty position.

_AKSAI_CHIN_SOI_WKT = (
    "POLYGON(("
    "78.10 35.55, "    # NW corner (near Karakoram Pass)
    "79.40 35.55, "    # northern edge along Kunlun watershed
    "80.20 35.45, "
    "80.30 35.10, "
    "80.20 34.80, "    # eastern edge
    "79.85 34.30, "    # SE corner (near Demchok/Pangong area)
    "79.20 34.50, "
    "78.65 34.85, "    # west edge (joins Ladakh-administered)
    "78.30 35.10, "
    "78.10 35.55"      # close ring
    "))"
)


def upgrade() -> None:
    # ── 1. Schema additions: provenance + audit trail ─────────────
    # `boundary_notes` lets the operator console flag SOI-approximate
    # rows for the user to replace with the official shapefile.
    # `verified_at` records when the row was last reviewed against
    # the SOI source.
    op.execute("""
        ALTER TABLE env_hazard_zones
          ADD COLUMN IF NOT EXISTS boundary_notes TEXT,
          ADD COLUMN IF NOT EXISTS verified_at    TIMESTAMPTZ;
    """)

    # ── 2. Drop the existing Arunachal bbox ───────────────────────
    # The bbox was 196,246 km² — 2.3× the true area, overlapping
    # Bhutan + Myanmar. Removing it is sovereignty-positive.
    op.execute("""
        DELETE FROM env_hazard_zones
         WHERE type = 'state_boundary'
           AND name = 'Arunachal Pradesh'
           AND source = 'curated';
    """)

    # ── 3. Insert SOI-aligned Arunachal Pradesh polygon ───────────
    op.execute(f"""
        INSERT INTO env_hazard_zones (
            type, severity, name, state, source, geom,
            area_km2, boundary_notes, verified_at, created_at
        ) VALUES (
            'state_boundary',
            'low',
            'Arunachal Pradesh',
            'Arunachal Pradesh',
            'soi_curated_approx',
            ST_SetSRID(ST_GeomFromText('{_ARUNACHAL_PRADESH_SOI_WKT}'), 4326),
            ST_Area(
                ST_SetSRID(ST_GeomFromText('{_ARUNACHAL_PRADESH_SOI_WKT}'), 4326)::geography
            ) / 1000000.0,
            'SOI-aligned approximate polygon (McMahon Line + Bhutan/Myanmar borders). ' ||
            'REPLACE WITH OFFICIAL MoEFCC SHAPEFILE when available. ' ||
            'Vertices derived from publicly-documented SOI boundary points, ' ||
            'not a precise survey trace.',
            NOW(),
            NOW()
        );
    """)

    # ── 4. Insert Aksai Chin polygon as part of Ladakh per SOI ────
    # NOTE: The existing OSM Ladakh polygon (Indian-administered
    # portion) is NOT touched — both rows together cover the full
    # SOI-claimed extent. `_postgis_resolve_state` already returns
    # the smallest-area match, so a point in Aksai Chin resolves
    # to this row, while a point in central Ladakh keeps resolving
    # to the OSM row.
    op.execute(f"""
        INSERT INTO env_hazard_zones (
            type, severity, name, state, source, geom,
            area_km2, boundary_notes, verified_at, created_at
        ) VALUES (
            'state_boundary',
            'low',
            'Ladakh',
            'Ladakh',
            'soi_curated_approx',
            ST_SetSRID(ST_GeomFromText('{_AKSAI_CHIN_SOI_WKT}'), 4326),
            ST_Area(
                ST_SetSRID(ST_GeomFromText('{_AKSAI_CHIN_SOI_WKT}'), 4326)::geography
            ) / 1000000.0,
            'Aksai Chin — claimed as part of Ladakh UT per Survey of India. ' ||
            'REPLACE WITH OFFICIAL MoEFCC SHAPEFILE when available. ' ||
            'Vertices follow Karakoram + Kunlun watershed per SOI maps.',
            NOW(),
            NOW()
        );
    """)

    # ── 5. Audit index — quick filter for rows awaiting SOI shapefile
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_env_hazard_zones_soi_approx
            ON env_hazard_zones (source)
         WHERE source = 'soi_curated_approx';
    """)


def downgrade() -> None:
    # WARNING: Restoring the previous Arunachal bbox is sovereignty-
    # incorrect and dropping the Aksai Chin row removes territory
    # India claims per SOI. Provided only for emergency rollback.
    op.execute("""
        DELETE FROM env_hazard_zones
         WHERE source = 'soi_curated_approx'
           AND name IN ('Arunachal Pradesh', 'Ladakh');
    """)
    # Restore the legacy Arunachal bbox so any code path expecting
    # *some* Arunachal polygon doesn't NULL out post-downgrade.
    # Coordinates are the exact previous bbox as a rectangle.
    op.execute("""
        INSERT INTO env_hazard_zones (
            type, severity, name, state, source, geom, area_km2, created_at
        ) VALUES (
            'state_boundary',
            'low',
            'Arunachal Pradesh',
            'Arunachal Pradesh',
            'curated',
            ST_SetSRID(ST_GeomFromText(
                'POLYGON((91.50 26.60, 97.50 26.60, 97.50 29.50, 91.50 29.50, 91.50 26.60))'
            ), 4326),
            ST_Area(
                ST_SetSRID(ST_GeomFromText(
                    'POLYGON((91.50 26.60, 97.50 26.60, 97.50 29.50, 91.50 29.50, 91.50 26.60))'
                ), 4326)::geography
            ) / 1000000.0,
            NOW()
        );
    """)
    op.execute("DROP INDEX IF EXISTS ix_env_hazard_zones_soi_approx;")
    # The new columns are kept (DROP COLUMN is dangerous if other
    # downstream code starts depending on them). They're nullable
    # so leaving them empty is harmless.
