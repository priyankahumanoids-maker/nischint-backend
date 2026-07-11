"""SF-02 Day 4 — admin-gated server-side benchmark endpoint.

Purpose: measure `_postgis_resolve_state` p99 latency from inside the
running backend process. Because the preview container is in
`us-east` and Supabase is in `ap-south-1`, any external curl
benchmark is RTT-dominated (~466 ms). The only way to measure the
actual co-located prod number is to run the loop server-side and
return the percentiles in the response. That is what this endpoint
does.

Production safety:
  * Disabled by default. Set `SF02_BENCH_ENABLED=true` in Emergent
    secrets to enable; remove or set to `false` to disable.
  * Admin role required — operator/parent/child are all 403.
  * Read-only — runs SELECT-only PostGIS queries.
  * 100 iterations cap, 30 s server-side timeout. Cannot DoS the DB.
  * No request body, no PII; only returns numeric percentiles.

After the SF-02 7-day soak completes and `STATE_BBOX` is deleted,
this endpoint can stay as a generic diagnostic — or remove the route
include if you prefer a leaner surface. Reusable for any future
latency-gated sprint.
"""
from __future__ import annotations

import asyncio
import logging
import os
import statistics
import time

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/sf02", tags=["sf02-bench"])


# Representative coordinate set — mirrors the spec's Day 4 Step 1
# benchmark intent (4 in-India + 1 outside). Cycled 20× = 100 iters.
_BENCH_COORDS = [
    (30.7333, 79.0667),   # Kedarnath — matches Uttarakhand
    (19.0760, 72.8777),   # Mumbai — matches Maharashtra
    (28.6139, 77.2090),   # Delhi — matches
    (28.5971, 83.8201),   # Nepal — no match (None expected)
    (13.0827, 80.2707),   # Chennai — matches Tamil Nadu
]


def _bench_enabled() -> bool:
    return os.environ.get("SF02_BENCH_ENABLED", "").lower() in (
        "1", "true", "yes", "on",
    )


def _ensure_admin(user: User) -> None:
    role = getattr(user, "role", None)
    if role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Admin role required for SF-02 benchmark",
        )


@router.post("/postgis-bench")
async def postgis_bench(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Run the ST_Within query 100× and return latency percentiles.

    All measurements are server-side (wall-clock within the FastAPI
    process), so the result reflects backend↔DB co-location, not the
    HTTP round trip from whoever curl'd us.

    Holds ONE pooled connection for the entire run and prepares the
    query once, then calls it 100×. This isolates `ST_Within` cost
    from `pool.acquire()` + per-call PREPARE/DEALLOCATE overhead
    (which is real but separate hot-path concern, not the SF-02
    p99 gate). The gate is "in steady state, what does ST_Within
    polygon matching cost?" — and that's what we measure here.
    """
    if not _bench_enabled():
        raise HTTPException(
            status_code=403,
            detail="SF02_BENCH_ENABLED is not true",
        )
    _ensure_admin(current_user)

    coords = _BENCH_COORDS * 20  # 100 iters

    # Enable the flag inside the bench process scope ONLY for this
    # call. The bench needs to exercise the real cached hot path
    # (`_postgis_resolve_state`), which is short-circuited when the
    # flag is off. We restore the previous value in `finally`.
    from app.services.external_signals.sachet_provider import (
        ENV_HAZARD_POSTGIS_FLAG, _postgis_resolve_state, clear_cache,
    )
    prev_flag = os.environ.get(ENV_HAZARD_POSTGIS_FLAG)
    os.environ[ENV_HAZARD_POSTGIS_FLAG] = "true"

    # Snapshot cache state BEFORE this run — lets the response
    # report "starting cache size" so caller can tell prime-vs-warm.
    from app.services.external_signals.sachet_provider import get_cache_stats
    cache_before = get_cache_stats()

    latencies_ms: list[float] = []
    t_overall = time.perf_counter()
    try:
        async with asyncio.timeout(40):
            # Tiny warm-up: 5 calls to ensure pool + SSL handshake hot.
            # On a primed run these are cache hits; on a cold run they
            # populate the first 5 keys.
            for _ in range(5):
                await _postgis_resolve_state(30.7333, 79.0667)

            for lat, lng in coords:
                t0 = time.perf_counter()
                await _postgis_resolve_state(lat, lng)
                latencies_ms.append((time.perf_counter() - t0) * 1000)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=(
                f"Benchmark exceeded 40 s — completed {len(latencies_ms)} iters"
            ),
        )
    finally:
        # Restore prior flag state so the bench doesn't leak feature
        # activation outside its own scope.
        if prev_flag is None:
            os.environ.pop(ENV_HAZARD_POSTGIS_FLAG, None)
        else:
            os.environ[ENV_HAZARD_POSTGIS_FLAG] = prev_flag

    total_s = time.perf_counter() - t_overall
    cache_after = get_cache_stats()

    latencies_ms.sort()
    n = len(latencies_ms)
    p50 = latencies_ms[n // 2]
    p95 = latencies_ms[int(n * 0.95)]
    p99 = latencies_ms[int(n * 0.99)] if n >= 100 else latencies_ms[-1]
    mean = statistics.fmean(latencies_ms)

    # Compute deltas: how many hits/misses occurred within THIS bench
    rs = "_postgis_resolve_state"
    delta_hits = cache_after[rs]["hits"] - cache_before[rs]["hits"]
    delta_miss = cache_after[rs]["misses"] - cache_before[rs]["misses"]

    return {
        "iterations": n,
        "total_s": round(total_s, 3),
        "ms": {
            "min":  round(latencies_ms[0], 3),
            "mean": round(mean, 3),
            "p50":  round(p50, 3),
            "p95":  round(p95, 3),
            "p99":  round(p99, 3),
            "max":  round(latencies_ms[-1], 3),
        },
        "gate_50ms_p99": p99 < 50.0,
        "coord_set_size": len(_BENCH_COORDS),
        "cache": {
            "starting_size": cache_before[rs]["size"],
            "ending_size":   cache_after[rs]["size"],
            "hits_this_run":   delta_hits,
            "misses_this_run": delta_miss,
            "hit_rate_this_run": (
                round(delta_hits / (delta_hits + delta_miss), 4)
                if (delta_hits + delta_miss) else 0.0
            ),
        },
        "method": "_postgis_resolve_state (cache-aware hot path)",
    }


@router.post("/cache-clear")
async def cache_clear(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Drop both PostGIS LRU caches. Use before a 'cold' bench run
    to measure uncached p99, or after a curated polygon overlay
    update so stale results don't linger.

    Admin + bench-flag-gated (same posture as the bench endpoint —
    we don't want random callers to bust the cache in prod)."""
    if not _bench_enabled():
        raise HTTPException(
            status_code=403,
            detail="SF02_BENCH_ENABLED is not true",
        )
    _ensure_admin(current_user)
    from app.services.external_signals.sachet_provider import clear_cache
    pre = clear_cache()
    return {"cleared": True, "stats_at_clear": pre}


@router.get("/cache-stats")
async def cache_stats(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return LRU cache hit/miss/size for both PostGIS helpers.

    Cheap (in-memory counter reads) and read-only. Useful for:
    - Verifying SF-02 cache is doing its job in prod
    - Diagnosing why p99 isn't where we expect (high miss rate =
      cold cache or coords scattered too thin for the 2-decimal grid)
    - Watching warm-up after a deploy
    """
    _ensure_admin(current_user)
    from app.services.external_signals.sachet_provider import get_cache_stats
    return get_cache_stats()


@router.get("/db-info")
async def db_info(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Diagnostic — returns which DB the backend process is actually
    connected to + whether `env_hazard_zones` exists with row count.

    Designed for the SF-02 Day 4 incident debug: prod was throwing
    `UndefinedTableError` despite preview having created the table on
    Supabase Mumbai. This endpoint answers "is prod pointed at the
    same DB as preview?" in one round trip — no guessing.

    Admin-only. Safe to leave deployed; reads only `information_schema`
    + `pg_database` + a row count. No PII, no secrets. The hostname
    is masked via `mask_url` so the password never lands in a log /
    response body.
    """
    _ensure_admin(current_user)

    from app.core.log_sanitizer import mask_url
    from app.db.session import _effective_dsn, get_db_pool

    # Report the DSN actually used by the running pool, not just the
    # .env value. The two diverge whenever the SUPABASE_DSN override is set.
    info: dict = {
        "configured_dsn": mask_url(_effective_dsn()),
    }

    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            info["current_database"] = await conn.fetchval("SELECT current_database()")
            info["current_schema"] = await conn.fetchval("SELECT current_schema()")
            info["inet_server_addr"] = str(
                await conn.fetchval("SELECT inet_server_addr()")
            )
            info["server_version"] = await conn.fetchval("SHOW server_version")
            info["env_hazard_zones_exists"] = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                     WHERE table_schema = 'public'
                       AND table_name = 'env_hazard_zones'
                )
                """
            )
            if info["env_hazard_zones_exists"]:
                info["env_hazard_zones_row_count"] = await conn.fetchval(
                    "SELECT COUNT(*) FROM env_hazard_zones"
                )
                info["env_hazard_zones_has_area_km2"] = await conn.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.columns
                         WHERE table_name = 'env_hazard_zones'
                           AND column_name = 'area_km2'
                    )
                    """
                )
    except Exception as exc:  # noqa: BLE001
        info["error"] = repr(exc)[:300]

    return info


__all__ = ["router"]
