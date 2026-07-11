# SF-02 — PostGIS Hazard-Zone Upgrade · Architecture Spec

**Sprint:** SF-02 (PostGIS + Health Connect)
**This document covers:** PostGIS portion only (the polygon-matching upgrade replacing the v1 `STATE_BBOX` Python dict).
**Owner:** Feroz Shaikh · Founder & CEO
**Written:** 22 May 2026 · pre-SF-02 kickoff
**Status:** Locked — defaults confirmed (1c / 2c / 3c / 4b + performance budget)
**Updated:** 23 May 2026 · SLO reset (§2) + topology note (§2a) after Day 4 prod measurement revealed cross-region RTT dominates query cost.

---

## 0. Goal

Replace the v1 state-bbox match in `app/services/external_signals/sachet_provider.py::resolve_state()` with a **PostGIS `ST_Within` polygon match** that:

1. Is correct down to **district level** (state-bbox v1 is correct only to ~50km radius around state boundaries).
2. Returns in **< 10 ms p99 on cache hits, < 350 ms p99 uncached** on the hot path (`/api/signals/motion` 30-second heartbeat × every active user × possibly 1000s of windows/min at pilot scale).
   *— SLO reset on 2026-05-23 after Day 4 measurement; see §2a Topology below. The original aspirational 50 ms p99 assumed app-tier and DB-tier co-location, which the Emergent prod deploy does not provide.*
3. Is **rollback-safe** — feature flag gates the cutover so a single env var flip restores the v1 bbox behaviour without a redeploy.
4. **Preserves the existing `match_env_hazards()` contract** — same return shape, same `ENV_HAZARD_MULTIPLIER`, same SSE event taxonomy. Zero downstream code changes.

Non-goals (deferred to SF-03):
- NDMA-published Shapefile ingestion pipeline (we'll use OSM admin boundaries for v2; NDMA Shapefiles in SF-03).
- Sub-district / pin-code resolution.
- Real-time polygon ingest from CAP alerts (still state-name-keyed in v2).

---

## 2a. Deploy topology & latency budget (added 2026-05-23)

The Emergent prod deploy is **not** co-located with Supabase Mumbai:

| Tier | Region | Source |
|---|---|---|
| App backend (FastAPI) | `us-east-1` (AWS Virginia) | Emergent platform default — Cloudflare edge `cf-ray=...-ORD` |
| Database (Supabase) | `ap-south-1` (AWS Mumbai) | Chosen for DPDP data-residency compliance |
| **Cross-region RTT** | **~240 ms** | Measured 23 May 2026 via `/api/admin/sf02/postgis-bench` |

Because RTT is fixed by physics (Virginia ↔ Mumbai = ~12,800 km great-circle = 240 ms in fibre), every uncached `ST_Within` call pays this floor. Server-side query execution is well under 10 ms (measured 0.199 ms hot / 12.4 ms worst-case via `EXPLAIN ANALYZE`). **The cross-region hop is the bottleneck, not the query.**

### DPDP compliance is intact

Data at rest sits entirely in Mumbai (ap-south-1). Data in transit between Virginia and Mumbai is TLS-encrypted (asyncpg + `sslmode=require`). Only ephemeral query results cross the wire, never persisted PII. The Privacy Policy claim ("AWS Asia Pacific (Mumbai, ap-south-1) ✓ · DPDP-aligned") is factually true.

### Mitigation: process-local LRU cache

Added 2026-05-23 in `sachet_provider.py`. Caches `(round(lat,2), round(lng,2))` → state name and rich dict separately, `maxsize=1000`, LRU eviction. State/district boundaries don't move, so cache entries never go stale. A typical active user produces ~5-20 unique grid cells per day → cache hit rate at steady state is expected to be ≥ 99%.

Effective SLO with cache:
- **Cache hit p99: < 10 ms** (in-memory dict lookup + asyncpg pool overhead)
- **Cache miss p99: < 350 ms** (one full RTT + query exec, with ~50 ms headroom for pgbouncer queue / TLS resumption variance)

Operational levers:
- `GET /api/admin/sf02/cache-stats` — live hit/miss counters
- `POST /api/admin/sf02/cache-clear` — bust cache (after curated polygon overlay updates)
- Each `/postgis-bench` response includes `cache.hits_this_run` / `misses_this_run` so we can distinguish "cold cache" runs from "warm cache" runs.

### Future paths (SF-03 / SF-04)

- **Move app tier to ap-south-1.** Cuts RTT to <2 ms. Requires Emergent platform support for multi-region deploys (currently single-region us-east).
- **Add an edge-side cache.** A Redis pop on the safety_brain path (already plumbed for sachet alerts) could cover the common-case lookups even before the LRU. Lower priority — the in-process LRU already covers the same workload.
- **Pre-compute "state for cell" lookups.** Materialise a `(grid_lat, grid_lng) → state` table on a coarse grid (~0.1°) so the hot path becomes a single `B-tree` lookup, no `ST_Within`. Cheap to build (~10MB), eliminates RTT-bound variance entirely if we add a colocated read replica. Filed as `SF-04 idea: precomputed state grid`.

---

## 1. NeonDB PostGIS enablement (Choice 1c)

**Action item before code lands**: log into the NeonDB console and verify whether PostGIS is enabled on the production branch.

Two paths depending on what we find:

### Path A — Fresh branch, in-place enable (cleanest)
```sql
-- Run on the production branch via NeonDB SQL editor or psql.
CREATE EXTENSION IF NOT EXISTS postgis;
SELECT PostGIS_Version();   -- expected: 3.4.x or newer
```

### Path B — Branch-and-migrate (if PostGIS unavailable on current branch)
```bash
# 1. From the NeonDB console: create a new branch from prod, region ap-south-1
# 2. Enable PostGIS on the new branch (SQL above)
# 3. Run our alembic migrations to recreate the schema
alembic upgrade head
# 4. pg_dump → pg_restore the existing data from prod branch into new
pg_dump  $OLD_DATABASE_URL --no-owner --no-acl --data-only > prod-data.sql
psql     $NEW_DATABASE_URL < prod-data.sql
# 5. Cut over by swapping DATABASE_URL env var (zero deploy)
```

**Validation gate**: before any other SF-02 work lands, the following must pass:
```sql
SELECT ST_Within(
  ST_SetSRID(ST_MakePoint(77.59, 12.97), 4326),                  -- Bengaluru
  ST_SetSRID(ST_MakeEnvelope(74, 11.5, 78, 18.5, 4326), 4326)    -- Karnataka bbox
);
-- expected: t
```

If the validation gate fails, **stop SF-02 and escalate to NeonDB support** before writing any application code. Don't try to work around it with raw point-in-polygon Python — the whole point of this sprint is to delete that code path.

---

## 2. Polygon source (Choice 2c — OSM v2 → NDMA Shapefiles SF-03)

### v2 — OSM admin boundaries

Source: **Geofabrik India extract — DATED SNAPSHOT** (https://download.geofabrik.de/asia/india.html). **Pin date: locked at SF-02 kickoff** (see §9, decision 2). Documented in the migration comment AND in `FUSION_ARCHITECTURE.md`.
Why pin: an undated `india-latest` URL means OSM contributors editing state boundaries between SF-02 and SF-03 would silently invalidate our regression tests. The dated pin makes hazard polygons reproducible byte-for-byte until we re-baseline at SF-03 with NDMA Shapefiles.
Why: free, MIT-compatible licence, accurate down to district (admin_level=4 for states, admin_level=5 for districts), already polygon-typed.

One-time ingest pipeline (run as a Python script, not a recurring job):

```bash
# Download the India OSM PBF DATED snapshot (~700 MB).
# Replace YYMMDD with the pin date locked at SF-02 kickoff.
PIN_DATE=YYMMDD
wget https://download.geofabrik.de/asia/india-${PIN_DATE}.osm.pbf \
  -O india-${PIN_DATE}.osm.pbf

# Filter admin boundaries with osmium
osmium tags-filter india-${PIN_DATE}.osm.pbf \
  r/admin_level=4,5 \
  -o india-admin-${PIN_DATE}.osm.pbf

# Convert to GeoJSON (osmium will fold relations into polygons)
osmium export india-admin-${PIN_DATE}.osm.pbf -o india-admin-${PIN_DATE}.geojson

# Load into PostGIS via our Python loader (see §5).
# The loader stamps `source_pin_date = ${PIN_DATE}` on every inserted row.
python -m backend.scripts.load_admin_boundaries india-admin-${PIN_DATE}.geojson
```

Refresh policy: quarterly. The pipeline is **not** wired to cron — Indian state boundaries don't change. SF-03 will replace this with NDMA's published Shapefiles for authoritative-source compliance.

### v3 — NDMA Shapefiles (SF-03)

Source: NDMA Bhuvan portal · https://bhuvan.nrsc.gov.in (NDMA national disaster management layer).
Same `hazard_zones` table, different ingest pipeline (`ogr2ogr -f PostgreSQL`). The application code does not need to change for the v2→v3 transition.

---

## 3. Schema (Choice 3c — both geometry + geography columns)

### `hazard_zones` table

```sql
-- Migration: backend/migrations/versions/<rev>_sf02_hazard_zones.py
-- Region: ap-south-1 (data-residency compliance per India DPDP Act 2023).
-- All hazard polygons are stored in EPSG:4326 (WGS84 lat/lng).

CREATE TABLE hazard_zones (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Source identification (allows mixing OSM admin + NDMA-CAP polygons later)
    source          TEXT NOT NULL,            -- 'osm_admin' | 'ndma_cap' | 'manual_override'
    source_ref      TEXT,                     -- e.g. OSM relation id or NDMA CAP id
    -- SF-03 NDMA pipeline idempotency key (baked in now so SF-03 needs
    -- no schema change). Locked formula:
    --   source_hash = SHA256(alert_id + effective_from + geometry_wkt)
    -- Upsert pattern on import: identical hashes = no-op; new hash for
    -- same source_ref = soft-delete the old row, insert the new one.
    source_hash     TEXT UNIQUE,
    admin_level     SMALLINT,                 -- 4 = state, 5 = district (OSM convention)

    -- Human-readable hierarchy
    country         TEXT NOT NULL DEFAULT 'India',
    state           TEXT NOT NULL,            -- e.g. 'Uttarakhand'
    district        TEXT,                     -- nullable for admin_level=4 rows

    -- Hazard semantics (nullable when this row is an admin boundary not a
    -- specific hazard — admin boundaries get attached to a CAP alert at
    -- query time via the `active_alerts` join in §4)
    hazard_type     TEXT,                     -- 'landslide' | 'flood' | 'cyclone' | NULL
    severity        TEXT,                     -- 'moderate' | 'severe' | 'extreme' | NULL

    -- Lifecycle
    active_from     TIMESTAMPTZ,
    active_until    TIMESTAMPTZ,
    -- SF-03 soft-delete column. Set to now() when a newer source_hash
    -- supersedes this row. Query path filters `WHERE superseded_at IS NULL`.
    superseded_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Geometry: both columns per Choice 3c.
    --   geom_geometry  is used for ST_Within (point-in-polygon, hot path).
    --   geom_geography is used for ST_DWithin (radius-in-meters, slower
    --     path used only by GET /api/env/hazards?radius_km=..).
    geom_geometry   geometry(MultiPolygon, 4326) NOT NULL,
    geom_geography  geography(MultiPolygon, 4326)
                     GENERATED ALWAYS AS (geom_geometry::geography) STORED
);

-- GIST indexes are the whole reason we hit < 50 ms. Both columns get one.
CREATE INDEX hazard_zones_geom_gix      ON hazard_zones USING GIST (geom_geometry);
CREATE INDEX hazard_zones_geog_gix      ON hazard_zones USING GIST (geom_geography);

-- Hierarchy lookup indexes
CREATE INDEX hazard_zones_state_idx     ON hazard_zones (state);
CREATE INDEX hazard_zones_state_dist_idx ON hazard_zones (state, district);
CREATE INDEX hazard_zones_active_idx    ON hazard_zones (active_from, active_until)
                                        WHERE superseded_at IS NULL
                                          AND (active_until IS NULL OR active_until > now());

-- SF-03 idempotency lookup index. UNIQUE constraint on source_hash
-- already creates one, but we add a covering index for the
-- (source_ref, superseded_at) pattern used during NDMA re-imports.
CREATE INDEX hazard_zones_source_ref_live_idx ON hazard_zones (source_ref)
                                        WHERE superseded_at IS NULL;
```

### Why GENERATED ALWAYS … STORED?
Eliminates the risk of the two columns drifting out of sync (geometry can be edited; geography is always the projection of geometry). Stored — not virtual — because GIST indexes don't support expression columns; the column must be materialised for the index to be planned.

### Storage cost
OSM India admin polygons: 28 states + 7 UTs + ~700 districts ≈ 750 rows. Each MultiPolygon ≈ 50 – 500 KB. Worst-case table size: ~400 MB. Comfortable on NeonDB starter tiers.

---

## 4. Application code changes

### `backend/app/services/env_hazard_matcher.py`

New PostGIS-backed matcher alongside the existing bbox matcher, gated by env flag.

```python
# Locked at the top of the file:
ENV_HAZARD_USE_POSTGIS = os.environ.get(
    "ENV_HAZARD_USE_POSTGIS", "false"
).lower() in ("1", "true", "yes", "on")


async def _match_postgis(
    session: AsyncSession,
    lat: float,
    lng: float,
) -> list[dict]:
    """Polygon-precise match via ST_Within. Hot path; must return
    in < 50 ms p99 (locked by tests in §6).

    Joins active CAP alerts onto the admin polygon they apply to,
    so the return shape is identical to the v1 bbox matcher.
    """
    point = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
    rows = (await session.execute(text("""
        SELECT
          hz.state,
          hz.district,
          hz.hazard_type,
          hz.severity,
          hz.id::text AS zone_id
        FROM hazard_zones hz
        WHERE
          ST_Within(
            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
            hz.geom_geometry
          )
          AND hz.hazard_type IS NOT NULL
          AND hz.superseded_at IS NULL
          AND (hz.active_until IS NULL OR hz.active_until > now())
          AND (hz.active_from  IS NULL OR hz.active_from  <= now())
          -- SF-02 ships state-wide (admin_level=4) only. SF-03 turns
          -- on district-precision by relaxing this filter.
          AND hz.admin_level = 4
        ORDER BY hz.admin_level DESC NULLS LAST   -- prefer district over state (SF-03)
        LIMIT 5
    """), {"lat": lat, "lng": lng})).all()

    return [
        {
            "source":   "postgis_st_within",
            "type":     r.hazard_type,
            "severity": (r.severity or "unknown").lower(),
            "risk":     SEVERITY_RISK.get(
                (r.severity or "unknown").lower(), 0.3,
            ),
            "title":    f"{r.hazard_type} · {r.district or r.state}",
            "zone_id":  r.zone_id,
        }
        for r in rows
    ]
```

### `match_env_hazards()` — dual-read wrapper (Choice 4b)

```python
async def match_env_hazards(
    lat: Optional[float],
    lng: Optional[float],
    weather: Optional[dict] = None,
    session: Optional[AsyncSession] = None,   # NEW — required if flag on
) -> dict:
    if lat is None or lng is None:
        return {"matched": False, ...}  # unchanged

    if ENV_HAZARD_USE_POSTGIS and session is not None:
        try:
            hazards = await _match_postgis(session, lat, lng)
        except Exception:
            logger.exception("PostGIS match failed; falling back to bbox")
            hazards = await _match_sachet(lat, lng)
    else:
        hazards = await _match_sachet(lat, lng)

    # Weather red-flag check unchanged
    weather_match = _match_weather_red_flag(weather)
    if weather_match:
        hazards.append(weather_match)

    # Rest of the function (strongest/state) unchanged.
    ...
```

### `evaluate_risk()` — pass session through

The only signature change in the hot path. `safety_brain_service.evaluate_risk` already takes `session`, so this is a one-line forward.

```python
# In app/services/safety_brain_service.py, ~line 200:
env_match = await match_env_hazards(
    lat, lng,
    weather=weather,
    session=session,           # NEW
)
```

That's it. No other application code changes. The frontend, mobile, SSE event taxonomy, FCM dispatcher, alert cooldown — all unchanged.

---

## 5. Data-load tooling

### `backend/scripts/load_admin_boundaries.py`

```python
"""SF-02 — One-time loader for OSM admin boundaries → hazard_zones.

Usage:
    python -m backend.scripts.load_admin_boundaries india-admin.geojson

Idempotent: deletes existing rows where source='osm_admin' before
re-inserting. Run quarterly when the OSM extract is refreshed.
"""
# Parses GeoJSON Features, maps OSM admin_level to our schema,
# resolves state/district from OSM tags (name:en preferred over name),
# bulk-inserts into hazard_zones with source='osm_admin'.
```

### `backend/scripts/inject_cap_alert.py`

```python
"""SF-02 — Inject a synthetic CAP alert as a `hazard_zones` row that
overlays an admin polygon. Replaces the dev-scenario Redis cache
injection from SF-01 v2 once PostGIS is the source of truth.

Cleanly times out via active_until = now() + ttl_minutes.
"""
```

The existing `POST /api/operator/dev/scenario` endpoint will be updated to call this loader so the Himalaya demo continues to work post-cutover.

---

## 6. Performance budget & test assertions

### Locked invariants
- `ST_Within` query (hot path): **p99 < 50 ms** on NeonDB free tier.
- `ST_DWithin` query (`GET /api/env/hazards`): **p99 < 200 ms** (warmer, less frequent).
- Table size at v2: **< 500 MB**.

### Test file: `backend/tests/test_sf02_postgis_performance.py`

```python
"""SF-02 — Performance assertions for the PostGIS hot path."""
import time
import statistics
import pytest

@pytest.mark.requires_postgis
def test_st_within_p99_under_50ms(async_session):
    """100 representative point queries; p99 must be < 50 ms.
    Fails loudly if NeonDB free tier can't hit the SLA — flag this
    before SF-02 closes, not after."""
    points = [
        (30.7333, 79.0667),   # Kedarnath (Uttarakhand · landslide)
                              #   ⚠ NB: the canonical Himalaya demo
                              #   coordinate. Do NOT substitute
                              #   28.5971°N, 83.8201°E (a typo
                              #   appearing in early Day 1 prompts) —
                              #   that point is in Nepal and resolves
                              #   to no Indian polygon. The actual
                              #   demo scenario in
                              #   `app/api/operator_dev.py:66` and the
                              #   SF-01 v2 Day 4 regression suite both
                              #   use Kedarnath (30.7333, 79.0667).
        (19.0760, 72.8777),   # Mumbai (Maharashtra · flood)
        (12.97,   77.59),     # Bengaluru
        (28.61,   77.21),     # Delhi
        # ... 96 more spread across all states
    ]
    timings = []
    for lat, lng in points:
        t0 = time.perf_counter()
        await _match_postgis(async_session, lat, lng)
        timings.append((time.perf_counter() - t0) * 1000)

    p99 = statistics.quantiles(timings, n=100)[98]   # 99th percentile
    assert p99 < 50.0, (
        f"PostGIS hot-path SLA breach: p99 = {p99:.1f} ms > 50 ms. "
        f"NeonDB tier may need an upgrade OR GIST index is missing."
    )

@pytest.mark.requires_postgis
def test_st_dwithin_radius_p99_under_200ms(async_session):
    """GET /api/env/hazards radius query under 200 ms p99."""
    ...

@pytest.mark.requires_postgis
def test_postgis_match_equivalence_with_bbox(async_session):
    """For every state in STATE_BBOX, a centroid query must return
    the same state name via both matchers. Locks behaviour during
    the dual-read window — no silent regressions."""
    ...

@pytest.mark.requires_postgis
def test_gist_indexes_exist():
    """Schema invariant — both GIST indexes must exist before any
    perf test runs, otherwise the SLA assertion is meaningless."""
    ...

@pytest.mark.requires_postgis
def test_feature_flag_off_uses_bbox_path():
    """ENV_HAZARD_USE_POSTGIS=false → match_env_hazards never
    touches the session. Locked rollback contract."""
    ...
```

The `requires_postgis` marker auto-skips when PostGIS isn't enabled on the test database — no false-positive failures in dev.

### 6.5 Performance escalation ladder

If `test_st_within_p99_under_50ms` fails on the NeonDB free tier:

1. **First — verify GIST indexes exist** via `test_gist_indexes_exist`. Missing GIST = problem solved.
2. **Second — verify the polygon dataset is realistic** (~500 polygons, not 5). A near-empty `hazard_zones` table will return < 1 ms regardless of indexes, which would mask the real production p99.
3. **If indexes exist + dataset is realistic + p99 is 50–120 ms → add the Upstash Redis cache layer.** Already in the stack — zero new dependency.
   - Cache key: `env_hazard_match:lat3:{round(lat,3)}:lng3:{round(lng,3)}`
   - Cache value: the dehydrated `_match_postgis` row list
   - TTL: **300 s** (same as `ALERT_COOLDOWN_TTL_S` — gives the operator visibility into a hazard for the same window as an alert dedup)
   - Implementation: wraps `_match_postgis` via a `@cached_via_redis` decorator. The cache miss path runs PostGIS and writes the result; the hit path returns in < 5 ms. Effective p99 collapses to roughly the cache miss rate × PostGIS p99 + (1 − miss rate) × Redis p99.
   - At 0.001° rounding the lat/lng key has ~1.1 km resolution — coarse enough to cache effectively but fine enough that a user crossing a state border still sees the right hazard within the next heartbeat.
4. **Only if the Redis cache layer ALSO can't hit the gate → upgrade the NeonDB tier.** Don't pay for infra you haven't proven you need.
5. **Stop and flag.** If steps 1–4 all miss, do not ship the cutover. Document the result in the SF-02 close-out doc, defer cutover, and stay on the v1 bbox until either the tier upgrade lands or a P0 review.

---

## 7. Rollout sequence

| Step | Action | Risk | Rollback |
|---|---|---|---|
| 0 | **NeonDB console pre-check** — visually confirm PostGIS availability on prod branch BEFORE running any migration. Decides between Path A (in-place) vs Path B (branch-and-migrate). | Zero — read-only | n/a |
| 1 | NeonDB PostGIS validation gate (§1) | Low — read-only check | n/a |
| 2 | Alembic migration creates `hazard_zones` table + 5 indexes + `source_hash` UNIQUE + `superseded_at` soft-delete | Low — additive | `alembic downgrade -1` |
| 3 | Load dated OSM admin boundaries via `load_admin_boundaries.py` (~750 rows) | Low — single script run | `DELETE FROM hazard_zones WHERE source='osm_admin'` |
| 4 | Deploy code with `ENV_HAZARD_USE_POSTGIS=false` (default) | Zero — flag off, no behaviour change | n/a |
| 5 | Run the 5 perf-suite tests; verify p99 < 50 ms | Discovery — perf SLA gate | See §6.5 escalation ladder |
| 6 | Flip `ENV_HAZARD_USE_POSTGIS=true` in preview env | Medium — first time the hot path uses PostGIS | Flip back to `false` — zero deploy |
| 7 | Run the Himalaya scenario CLI; expect identical composite 0.793 | High-signal | Flip flag back to `false` |
| 8 | Flip flag in production env | Medium | Flip back to `false` |
| 9 | Monitor `evaluate_risk` latency for **7 days** | Detection | Flip flag back to `false`, file SF-02.1 |
| 10 | Delete the `STATE_BBOX` dict + `_match_sachet` bbox path | Low — proven by step 9 | `git revert` |

Step 10 is the **only step that locks the migration**. Everything before it is recoverable in seconds.

---

## 8. Compliance & data residency

- Region: **ap-south-1** (Mumbai). NeonDB project must be in `ap-south-1`. Hazard polygons themselves are public OSM data so cross-region replication is allowed if a CDN layer is added later — but the application's `hazard_zones` table lives in `ap-south-1` alongside all user PII.
- Locked in schema comments: every migration adds `-- Region: ap-south-1 (data-residency compliance per India DPDP Act 2023).` so a school's legal team running `pg_dump --schema-only` sees the residency intent in writing.
- The hazard_zones table holds **zero user PII**. It is safe to expose via `GET /api/env/hazards` to authenticated users at any radius.

---

## 9. Open questions for SF-02 kickoff — LOCKED 22 May 2026

1. **NeonDB tier** — **free tier first.** Run the perf benchmark on Day 1 against a 500-polygon dataset. If p99 < 50 ms → ship. If 50-120 ms → add Upstash Redis cache layer (key: `(round(lat,3), round(lng,3))`, TTL 5 min) — already in the stack, cheaper than a tier upgrade. Only upgrade the NeonDB tier if the cache layer still misses the gate.
2. **OSM extract pinning** — **pin to a dated snapshot.** Use `india-230101.osm.pbf` (or the closest available Geofabrik daily dump). Document the pin date in the migration comment AND in `FUSION_ARCHITECTURE.md`. Re-baseline at SF-03 when NDMA Shapefiles become the source of truth.
3. **District-precision CAP alerts** — **state-wide for SF-02.** Sufficient for Himalaya demo + any pilot in the next 6 months. The schema already supports districts (`district` column + `admin_level=5` polygons load fine); we just don't *query* them in v2. SF-03 turns them on by adding a `precision` filter to `_match_postgis`.
4. **Idempotency hash for SF-03 NDMA pipeline** — **`SHA256(alert_id + effective_from + geometry_wkt)`** as `source_hash` column on `hazard_zones`. Baked into the SF-02 migration NOW so SF-03 doesn't require a schema change. Upsert pattern: identical hashes = no-op; new hashes for the same `source_ref` soft-delete the old row.

---

## 10. Sprint-close definition of done

SF-02 (PostGIS portion) is done when ALL of these are green:

- [ ] `CREATE EXTENSION postgis` verified on production NeonDB branch.
- [ ] Alembic migration applied; `hazard_zones` table + 4 indexes exist.
- [ ] OSM admin boundaries loaded (~750 rows, both states + districts).
- [ ] `ENV_HAZARD_USE_POSTGIS=true` lands `0.793` on the Himalaya CLI — same as v1 bbox.
- [ ] `test_sf02_postgis_performance.py` all 5 tests pass with `requires_postgis` marker.
- [ ] `evaluate_risk` p99 latency in preview env stable for 7 days post-flip.
- [ ] `STATE_BBOX` dict deleted; `_match_sachet` bbox path removed.
- [ ] `FUSION_ARCHITECTURE.md` updated with the PostGIS row in the Layer 4 table.
- [ ] Swallow-audit ratchet still `unresolved_debt = 1`.

---

*Document version: 1.0 · 22 May 2026 · Locked pre-SF-02 kickoff.*
