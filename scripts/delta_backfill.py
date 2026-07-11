#!/usr/bin/env python3
"""SF-02 Mumbai cutover — delta backfill (Neon → Supabase).

Designed to be run ONE FINAL TIME immediately before the Emergent prod
`DATABASE_URL` redeploy. Catches whatever rows landed on Neon between
the initial backfill (~2026-05-23 09:57 UTC) and the redeploy moment.

Pattern:
  1. Read NEON_DSN + SUPABASE_DSN from environment.
  2. SELECT all `behavior_anomalies` from Neon with
     `created_at > $LAST_MAX_TS` (default 2026-05-23 09:57:53.072).
  3. INSERT into Supabase using a TEMP staging table + COPY +
     `INSERT ... ON CONFLICT (id) DO NOTHING` — fully idempotent.
  4. Report rows inserted, new max created_at on both DBs.
  5. Assert both DBs have IDENTICAL `COUNT(*)` for the table
     before exit. Non-zero exit code on mismatch.

Safety:
  * Identity guard: refuses to proceed unless Neon resolves to db
    `neondb` AND Supabase resolves to db `postgres`. Prevents a
    cross-write if either DSN is misconfigured.
  * Idempotent — safe to re-run. Duplicate rows skip via ON CONFLICT.
  * Read-only on Neon (just SELECT).
  * No credential echo; DSN is masked in all log output.
  * Defaults to `--dry-run` unless `--apply` is passed. Apply mode
    is what the cutover runner uses; dry-run is for sanity-checking
    "how many rows will I move?" before commitment.

Invocation:
  # Smoke test (no writes) — count-only:
  NEON_DSN=...  SUPABASE_DSN=...  python /app/scripts/delta_backfill.py
  
  # Real run, default cutoff:
  NEON_DSN=...  SUPABASE_DSN=...  python /app/scripts/delta_backfill.py --apply
  
  # Real run with explicit cutoff (after a previous delta backfill):
  NEON_DSN=...  SUPABASE_DSN=...  python /app/scripts/delta_backfill.py --apply \
      --since '2026-05-23 12:34:56.789'

Exit codes:
  0 — success (or dry-run summary)
  1 — env vars missing / DSN identity mismatch
  2 — backfill ran but final counts diverge (manual intervention needed)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import ssl
import sys
from datetime import datetime
from typing import Optional

import asyncpg


# Default cutoff = the max `created_at` recorded at the end of the
# 09:57 UTC initial backfill on 2026-05-23. Subsequent invocations
# should pass --since the previous run's reported "new max".
DEFAULT_SINCE = "2026-05-23 09:57:53.072"
TABLE = "behavior_anomalies"


def _mask(dsn: str) -> str:
    return re.sub(r"://[^@]+@", "://****@", dsn)


def _ssl_ctx() -> ssl.SSLContext:
    """Same SSL posture used by the live cutover code in
    `app/db/session.py` — encrypted on the wire, chain unverified
    (Supabase pooler presents a self-signed leaf)."""
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


async def _connect(dsn: str) -> asyncpg.Connection:
    return await asyncpg.connect(
        dsn.split("?")[0],
        ssl=_ssl_ctx(),
        timeout=20,
        statement_cache_size=0,
    )


async def _identity_guard(neon: asyncpg.Connection,
                          supa: asyncpg.Connection) -> None:
    """Fail loudly if either DSN doesn't resolve to the expected DB."""
    n_db = await neon.fetchval("SELECT current_database()")
    s_db = await supa.fetchval("SELECT current_database()")
    if n_db != "neondb":
        raise SystemExit(f"FATAL: NEON_DSN connects to {n_db!r}, expected 'neondb'")
    if s_db != "postgres":
        raise SystemExit(f"FATAL: SUPABASE_DSN connects to {s_db!r}, expected 'postgres'")
    print(f"  identity guard ✓ Neon=neondb  Supabase=postgres")  # noqa: F541


async def _columns_in_order(conn: asyncpg.Connection,
                            table: str) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT column_name FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = $1
         ORDER BY ordinal_position
        """,
        table,
    )
    return [r["column_name"] for r in rows]


async def run(since: str, apply: bool) -> int:
    neon_dsn = os.environ.get("NEON_DSN")
    supa_dsn = os.environ.get("SUPABASE_DSN")
    if not neon_dsn or not supa_dsn:
        print("FATAL: NEON_DSN and SUPABASE_DSN env vars are required")
        return 1

    print(f"Source (read-only):  {_mask(neon_dsn)}")
    print(f"Target (writable):   {_mask(supa_dsn)}")
    print(f"Cutoff (created_at > {since!r})")
    print(f"Mode: {'APPLY (will write)' if apply else 'DRY-RUN (count only)'}")
    print()

    neon = await _connect(neon_dsn)
    supa = await _connect(supa_dsn)

    print("Phase 1 — Identity & schema preflight")
    await _identity_guard(neon, supa)

    cols = await _columns_in_order(supa, TABLE)
    n_cols = await _columns_in_order(neon, TABLE)
    if cols != n_cols:
        print(f"  ⚠ column mismatch — Supabase={cols}  Neon={n_cols}")
        await neon.close()
        await supa.close()
        return 2
    print(f"  schema OK ({len(cols)} cols): {cols}")

    print()
    print("Phase 2 — Compute delta window")
    select_cols = ", ".join(cols)
    delta_count = await neon.fetchval(
        f"SELECT COUNT(*) FROM {TABLE} WHERE created_at > $1",
        datetime.fromisoformat(since),
    )
    neon_max_pre = await neon.fetchval(
        f"SELECT MAX(created_at) FROM {TABLE} WHERE created_at > $1",
        datetime.fromisoformat(since),
    )
    supa_total_pre = await supa.fetchval(f"SELECT COUNT(*) FROM {TABLE}")
    neon_total = await neon.fetchval(f"SELECT COUNT(*) FROM {TABLE}")
    print(f"  Neon rows in window      : {delta_count:,}")
    print(f"  Neon max created_at      : {neon_max_pre}")
    print(f"  Neon total               : {neon_total:,}")
    print(f"  Supabase total (pre)     : {supa_total_pre:,}")

    if delta_count == 0:
        print()
        print("  ✓ No new rows on Neon since cutoff — nothing to backfill.")
        await neon.close()
        await supa.close()
        return 0

    if not apply:
        print()
        print(f"  DRY-RUN — would copy {delta_count:,} rows. Re-run with --apply.")
        await neon.close()
        await supa.close()
        return 0

    print()
    print("Phase 3 — Stream rows from Neon")
    rows = await neon.fetch(
        f"SELECT {select_cols} FROM {TABLE} "
        f"WHERE created_at > $1 ORDER BY created_at",
        datetime.fromisoformat(since),
    )
    print(f"  fetched {len(rows):,} rows")

    print()
    print("Phase 4 — Stage + insert with ON CONFLICT DO NOTHING")
    async with supa.transaction():
        await supa.execute(
            f"CREATE TEMP TABLE _delta_stage "
            f"(LIKE {TABLE} INCLUDING DEFAULTS) ON COMMIT DROP"
        )
        tuples = [tuple(r[c] for c in cols) for r in rows]
        await supa.copy_records_to_table(
            "_delta_stage", records=tuples, columns=cols,
        )
        ins = await supa.execute(
            f"INSERT INTO {TABLE} ({select_cols}) "
            f"SELECT {select_cols} FROM _delta_stage "
            f"ON CONFLICT (id) DO NOTHING"
        )
    print(f"  {ins}")

    print()
    print("Phase 5 — Verify both DBs match")
    supa_total_post = await supa.fetchval(f"SELECT COUNT(*) FROM {TABLE}")
    neon_total_post = await neon.fetchval(f"SELECT COUNT(*) FROM {TABLE}")
    supa_max = await supa.fetchval(f"SELECT MAX(created_at) FROM {TABLE}")
    neon_max_post = await neon.fetchval(f"SELECT MAX(created_at) FROM {TABLE}")
    print(f"  Supabase total (post)    : {supa_total_post:,}")
    print(f"  Neon     total           : {neon_total_post:,}")
    print(f"  Supabase max created_at  : {supa_max}")
    print(f"  Neon     max created_at  : {neon_max_post}")

    if supa_total_post != neon_total_post:
        print(
            f"  ✗ MISMATCH — Supabase={supa_total_post:,}  "
            f"Neon={neon_total_post:,}  delta={neon_total_post - supa_total_post:,}"
        )
        print("    Manual reconcile required before swapping DATABASE_URL.")
        await neon.close()
        await supa.close()
        return 2

    print(f"  ✓ counts match ({supa_total_post:,} = {neon_total_post:,})")

    if supa_max != neon_max_post:
        print(
            "  ⚠ max created_at differs — likely prod kept writing during "
            "the backfill. Re-run delta_backfill.py with "
            f"--since '{supa_max}' OR freeze prod writes before the redeploy."
        )

    await neon.close()
    await supa.close()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--since", default=DEFAULT_SINCE,
                   help=f"cutoff timestamp (default: {DEFAULT_SINCE})")
    p.add_argument("--apply", action="store_true",
                   help="actually write (default: dry-run)")
    args = p.parse_args()
    return asyncio.run(run(args.since, args.apply))


if __name__ == "__main__":
    sys.exit(main())
