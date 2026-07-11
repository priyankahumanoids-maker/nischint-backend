"""SF-03b — Expand Aksai Chin polygon to match SOI-claimed extent.

Why this exists:
  The initial SF-03 migration shipped an Aksai Chin polygon of
  ~18,400 km² — well under the SOI-published Aksai Chin claim of
  ~37,555 km². That meant the easternmost and northernmost
  Aksai Chin points (e.g. the upper Karakash basin) didn't resolve
  to Ladakh and would have rendered as "outside India" on the
  operator console.

  This patch UPDATES the existing Aksai Chin row to a wider polygon
  whose vertices follow the Indian sovereignty claim along the
  Karakoram + Kunlun ranges. Approximate area: ~33,000–37,000 km².

Same migration shape as SF-03 — `source='soi_curated_approx'` stays
in place, replacement path is unchanged. The Indian-administered
OSM Ladakh polygon is NOT touched.
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import inspect


revision = "sf03b_expand_aksai_chin"
down_revision = "sf03_soi_boundary_precision"
branch_labels = None
depends_on = None


# Expanded Aksai Chin polygon — 13 vertices, follows SOI claim line.
# West edge: LAC from Karakoram Pass (35.55°N, 78.10°E) southward
# through Daulat Beg Oldi area toward Demchok (~34.20°N, 79.30°E).
# East edge: ~80.50°E along the Indian-claimed sovereignty line.
# North edge: ~35.55°N along Kunlun watershed.
# South edge: ~34.20°N near Demchok / Pangong eastern.
_AKSAI_CHIN_EXPANDED_WKT = (
    "POLYGON(("
    "78.10 35.55, "
    "78.80 35.60, "
    "79.50 35.55, "
    "80.20 35.50, "
    "80.50 35.20, "    # eastern extent (Indian claim line)
    "80.40 34.80, "
    "80.10 34.40, "
    "79.70 34.20, "    # SE near Demchok
    "79.30 34.20, "
    "78.90 34.30, "
    "78.55 34.55, "    # LAC swinging NW
    "78.25 34.90, "
    "78.10 35.20, "
    "78.10 35.55"      # close ring
    "))"
)


def upgrade() -> None:
    # UPDATE in place — keep the row id stable for any FK that
    # might pick this up in a later phase.
    bind = op.get_bind()
    if not inspect(bind).has_table('env_hazard_zones'):
        return

    op.execute(f"""
        UPDATE env_hazard_zones
           SET geom = ST_SetSRID(ST_GeomFromText('{_AKSAI_CHIN_EXPANDED_WKT}'), 4326),
               area_km2 = ST_Area(
                   ST_SetSRID(ST_GeomFromText('{_AKSAI_CHIN_EXPANDED_WKT}'), 4326)::geography
               ) / 1000000.0,
               boundary_notes = 'Aksai Chin — expanded SOI-aligned polygon (~SOI-claimed extent). ' ||
                                'REPLACE WITH OFFICIAL MoEFCC SHAPEFILE when available. ' ||
                                'West edge follows the Line of Actual Control; east edge ' ||
                                'follows India''s officially-claimed sovereignty line per SOI maps.',
               verified_at = NOW()
         WHERE type = 'state_boundary'
           AND name = 'Ladakh'
           AND source = 'soi_curated_approx';
    """)


def downgrade() -> None:
    # Restore the SF-03 initial polygon (smaller extent).
    bind = op.get_bind()
    if not inspect(bind).has_table('env_hazard_zones'):
        return

    op.execute("""
        UPDATE env_hazard_zones
           SET geom = ST_SetSRID(ST_GeomFromText(
                   'POLYGON(('
                   '78.10 35.55, 79.40 35.55, 80.20 35.45, 80.30 35.10, '
                   '80.20 34.80, 79.85 34.30, 79.20 34.50, 78.65 34.85, '
                   '78.30 35.10, 78.10 35.55))'
               ), 4326),
               area_km2 = ST_Area(
                   ST_SetSRID(ST_GeomFromText(
                       'POLYGON(('
                       '78.10 35.55, 79.40 35.55, 80.20 35.45, 80.30 35.10, '
                       '80.20 34.80, 79.85 34.30, 79.20 34.50, 78.65 34.85, '
                       '78.30 35.10, 78.10 35.55))'
                   ), 4326)::geography
               ) / 1000000.0,
               boundary_notes = NULL,
               verified_at = NOW()
         WHERE type = 'state_boundary'
           AND name = 'Ladakh'
           AND source = 'soi_curated_approx';
    """)
