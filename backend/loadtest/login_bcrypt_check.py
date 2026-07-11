"""LT-01 bcrypt-fix validation harness.

Specifically targets `/api/auth/login` to confirm `asyncio.to_thread`
wrapping unblocks the event loop. We cannot use locust here because
the auth endpoint is rate-limited to 5/min/IP — sending 60 logins from
one IP would just measure the rate-limiter.

Strategy: 10 concurrent logins (within the 5/min limit if spaced),
measure how long the slowest one takes vs how long a CONCURRENT
`/api/health` call takes. Pre-fix: /api/health would queue behind
bcrypt and take ~Nx100ms (where N = login concurrency). Post-fix:
/api/health should complete in <50ms regardless of in-flight logins.

Usage:
    python backend/loadtest/login_bcrypt_check.py
"""
from __future__ import annotations

import asyncio
import statistics
import sys
import time

import aiohttp


HOST = "http://localhost:8001"
EMAIL = "nischint4parents@gmail.com"
PASSWORD = "secret123"

# 3 logins so we stay under the 5/min/IP rate limit, but fire them
# concurrently. The bcrypt verify is the only sync-CPU work on this
# path. If asyncio.to_thread is wired correctly, /api/health
# should not be blocked by the in-flight logins.
N_LOGINS = 3


async def _login(http):
    t0 = time.monotonic()
    try:
        async with http.post(
            f"{HOST}/api/auth/login",
            json={"email": EMAIL, "password": PASSWORD},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as r:
            await r.read()
            return time.monotonic() - t0, r.status
    except Exception as e:
        return time.monotonic() - t0, repr(e)


async def _probe_health(http, samples=10, delay=0.02):
    """Hammer /api/health while logins are in flight. If the event
    loop is blocked by bcrypt, these probes will see >100ms tail
    latency. If the fix is wired, they stay near network floor."""
    lats = []
    t_end = time.monotonic() + 3.0
    while time.monotonic() < t_end and len(lats) < samples:
        t0 = time.monotonic()
        try:
            async with http.get(
                f"{HOST}/api/health",
                timeout=aiohttp.ClientTimeout(total=20),
            ) as r:
                await r.read()
            lats.append((time.monotonic() - t0) * 1000)
        except Exception:
            lats.append(None)
        await asyncio.sleep(delay)
    return lats


async def main():
    async with aiohttp.ClientSession() as http:
        # Concurrent logins + health probes
        t0 = time.monotonic()
        login_tasks = [asyncio.create_task(_login(http)) for _ in range(N_LOGINS)]
        probe_task = asyncio.create_task(_probe_health(http))

        login_results = await asyncio.gather(*login_tasks)
        probe_lats = await probe_task
        wall = time.monotonic() - t0

        print(f"\n=== {N_LOGINS} concurrent logins ===")
        for i, (lat, status) in enumerate(login_results):
            print(f"  #{i+1}: {lat*1000:7.1f}ms  status={status}")
        print(f"  wall:    {wall*1000:7.1f}ms")

        good_probes = [x for x in probe_lats if x is not None]
        if good_probes:
            print(f"\n=== /api/health concurrent probes (n={len(good_probes)}) ===")
            print(f"  min: {min(good_probes):.1f}ms")
            print(f"  p50: {statistics.median(good_probes):.1f}ms")
            print(f"  p95: {sorted(good_probes)[max(0, int(len(good_probes)*0.95) - 1)]:.1f}ms")
            print(f"  max: {max(good_probes):.1f}ms")
            print()
            health_p95 = sorted(good_probes)[max(0, int(len(good_probes)*0.95) - 1)]
            if health_p95 < 50:
                print(f"  ✅ PASS — /api/health p95 ({health_p95:.0f}ms) < 50ms")
                print("           bcrypt is NOT blocking the event loop")
            elif health_p95 < 200:
                print(f"  ⚠️  PARTIAL — /api/health p95 ({health_p95:.0f}ms) [50-200ms band]")
                print("           bcrypt offload is partly effective; some inline sync work remains")
            else:
                print(f"  ❌ FAIL — /api/health p95 ({health_p95:.0f}ms) >= 200ms")
                print("           bcrypt is STILL blocking the event loop")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
