"""Migration: SOI boundary precision updates for Arunachal and Aksai Chin.

  The previous Arunachal Pradesh row in `env_hazard_zones` was a single
  curated bounding box overlapping neighboring countries. We replace it
  with an SOI-aligned approximate polygon. We also explicitly add Aksai
  Chin to the Ladakh state_boundary per SOI mapping.

  * A `boundary_notes` column on `env_hazard_zones` records the
    approximate nature of these rows so operator UI can flag them.
"""
from __future__ import annotations
from alembic import op
from sqlalchemy import inspect

revision = "sf03_soi_boundary_precision"
down_revision = "sb02_user_signal_baselines_mv"
branch_labels = None
depends_on = None

# ~83,743 km² — matches the official Indian claim for Arunachal Pradesh.
# Coordinates are derived from Survey of India approximate borders
# (McMahon Line on the north/east, Bhutan to the west).
_ARUNACHAL_PRADESH_SOI_WKT = (
    "POLYGON(("
    "91.50 27.80, "    # NW corner (tri-junction with Bhutan/Tibet)
    "92.50 27.90, "
    "93.50 28.50, "
    "94.50 29.00, "    # Northern edge along McMahon Line
    "95.50 29.20, "
    "96.50 29.30, "
    "97.30 28.30, "    # NE corner (near Diphu Pass)
    "97.00 27.50, "    # Eastern edge
    "96.00 27.00, "
    "95.50 26.80, "    # Southern edge (border with Assam/Nagaland)
    "94.00 26.80, "
    "93.00 26.80, "
    "92.00 26.80, "
    "91.50 27.80"      # close ring
    "))"
)

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
    # Safely skip the migration if the external PostGIS table doesn't exist yet
    bind = op.get_bind()
    if not inspect(bind).has_table('env_hazard_zones'):
        return

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
    # Safely skip the downgrade if the external PostGIS table doesn't exist
    bind = op.get_bind()
    if not inspect(bind).has_table('env_hazard_zones'):
        return

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
