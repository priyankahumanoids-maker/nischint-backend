"""RSS + pg-pool sampler (LT-01).

Polls `/api/admin/monitoring/runtime-info` every N seconds during a
load test or soak test, and writes timestamped CSV rows. Used both
during the headline 60s load test and the 30-min soak.

Usage:
    HOST=https://gps-mic-restart.preview.emergentagent.com \
    LT_ADMIN_EMAIL=... LT_ADMIN_PASSWORD=... \
    python backend/loadtest/runtime_sampler.py \
        --duration 1800 --interval 10 --output /tmp/soak_metrics.csv
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
import time
from datetime import datetime, timezone

import aiohttp


SAMPLE_FIELDS = [
    "ts",
    "memory_rss_mb",
    "memory_vms_mb",
    "cgroup_mem_used_mb",
    "cgroup_mem_pct",
    "num_fds",
    "num_threads",
    "num_inet_connections",
    "asyncio_task_count",
    "asyncio_loop_lag_ms",
    "cc_connections_active",
    "num_ws_connections",
    "pg_pool_size",
    "pg_pool_checked_out",
    "pg_pool_checked_in",
    "pg_pool_overflow",
    "pg_pool_total_capacity",
    "pg_pool_utilization_pct",
    "pg_pool_wait_count",
]


async def _login(http, base_url, email, password):
    async with http.post(
        f"{base_url}/api/auth/login",
        json={"email": email, "password": password},
        timeout=aiohttp.ClientTimeout(total=10),
    ) as r:
        r.raise_for_status()
        d = await r.json()
        return d.get("access_token") or d.get("token") or ""


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--duration", type=int, default=60)
    p.add_argument("--interval", type=int, default=5)
    p.add_argument("--output", default="/tmp/runtime_samples.csv")
    args = p.parse_args()

    base = os.environ.get("HOST", "").rstrip("/")
    email = os.environ.get("LT_ADMIN_EMAIL", "nischint4parents@gmail.com")
    password = os.environ.get("LT_ADMIN_PASSWORD", "secret123")
    if not base or "nischint.care" in base:
        print("ERROR: HOST must be preview URL.", file=sys.stderr)
        return 2

    async with aiohttp.ClientSession() as http:
        token = await _login(http, base, email, password)
        if not token:
            print("ERROR: login failed", file=sys.stderr)
            return 2
        headers = {"Authorization": f"Bearer {token}"}

        with open(args.output, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=SAMPLE_FIELDS)
            w.writeheader()
            deadline = time.time() + args.duration
            samples = 0
            while time.time() < deadline:
                try:
                    async with http.get(
                        f"{base}/api/admin/monitoring/runtime-info",
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as r:
                        d = await r.json()
                except Exception as e:
                    d = {"error": repr(e)}
                row = {k: d.get(k) for k in SAMPLE_FIELDS}
                row["ts"] = datetime.now(timezone.utc).isoformat()
                w.writerow(row)
                f.flush()
                samples += 1
                await asyncio.sleep(args.interval)
        print(f"sampled {samples} rows -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
