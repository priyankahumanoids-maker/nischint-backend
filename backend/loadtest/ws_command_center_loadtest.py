"""Scenario 5: Command Center WebSocket harness (LT-01).

Locust doesn't natively support WS, so we run this as a standalone
asyncio script. Spawns 5 admin/operator connections to
`/api/ws/command-center` and holds them open for the configured
duration, sampling RSS + ws_connections every 5s.

Usage:
    HOST=https://gps-mic-restart.preview.emergentagent.com \
    LT_ADMIN_EMAIL=nischint4parents@gmail.com \
    LT_ADMIN_PASSWORD=secret123 \
    python backend/loadtest/ws_command_center_loadtest.py --duration 60 --concurrency 5
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from urllib.parse import urlparse

import aiohttp


async def _login(http: aiohttp.ClientSession, base_url: str, email: str, password: str) -> str:
    async with http.post(
        f"{base_url}/api/auth/login",
        json={"email": email, "password": password},
        timeout=aiohttp.ClientTimeout(total=10),
    ) as r:
        r.raise_for_status()
        d = await r.json()
        return d.get("access_token") or d.get("token") or ""


async def _ws_connection_worker(
    idx: int,
    http: aiohttp.ClientSession,
    ws_url: str,
    token: str,
    duration_s: float,
    stats: dict,
) -> None:
    start = time.time()
    try:
        async with http.ws_connect(
            f"{ws_url}?token={token}",
            heartbeat=20,
        ) as ws:
            stats["connected"] += 1
            connect_latency_ms = (time.time() - start) * 1000
            stats["connect_latencies_ms"].append(connect_latency_ms)
            # Hold open, drain messages
            deadline = time.time() + duration_s
            async for msg in ws:
                if msg.type in (aiohttp.WSMsgType.CLOSE,
                                aiohttp.WSMsgType.CLOSED,
                                aiohttp.WSMsgType.ERROR):
                    break
                stats["messages_recvd"] += 1
                if time.time() >= deadline:
                    await ws.close()
                    break
                if time.time() >= deadline:
                    break
    except Exception as e:
        stats["errors"].append(f"WS#{idx}: {type(e).__name__}: {e}")
    finally:
        stats["disconnected"] += 1


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--concurrency", type=int, default=5)
    args = parser.parse_args()

    base = os.environ.get("HOST", "").rstrip("/")
    email = os.environ.get("LT_ADMIN_EMAIL", "nischint4parents@gmail.com")
    password = os.environ.get("LT_ADMIN_PASSWORD", "secret123")

    if not base:
        print("ERROR: set HOST env var to the preview URL.", file=sys.stderr)
        return 2
    if "nischint.care" in base:
        print("ERROR: refusing to run against production.", file=sys.stderr)
        return 2

    parsed = urlparse(base)
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    ws_url = f"{ws_scheme}://{parsed.netloc}/api/ws/command-center"

    stats: dict = {
        "connected": 0,
        "disconnected": 0,
        "messages_recvd": 0,
        "connect_latencies_ms": [],
        "errors": [],
    }

    async with aiohttp.ClientSession() as http:
        token = await _login(http, base, email, password)
        if not token:
            print("ERROR: login failed.", file=sys.stderr)
            return 2
        print(f"[scen5-ws] login OK; spawning {args.concurrency} WS for {args.duration}s …")

        workers = [
            asyncio.create_task(
                _ws_connection_worker(i, http, ws_url, token, args.duration, stats)
            )
            for i in range(args.concurrency)
        ]
        await asyncio.gather(*workers, return_exceptions=True)

    lat = stats["connect_latencies_ms"]
    p50 = round(statistics.median(lat), 1) if lat else None
    p95 = round(_percentile(lat, 95), 1) if lat else None
    p99 = round(_percentile(lat, 99), 1) if lat else None
    print(json.dumps({
        "scenario": "s5_command_center_ws",
        "concurrency": args.concurrency,
        "duration_s": args.duration,
        "connected": stats["connected"],
        "disconnected": stats["disconnected"],
        "messages_recvd": stats["messages_recvd"],
        "connect_latency_ms": {"p50": p50, "p95": p95, "p99": p99},
        "errors": stats["errors"][:10],
    }, indent=2))
    return 0 if not stats["errors"] and stats["connected"] == args.concurrency else 1


def _percentile(xs, pct):
    if not xs:
        return 0.0
    xs2 = sorted(xs)
    k = max(0, min(len(xs2) - 1, int(round((pct / 100) * (len(xs2) - 1)))))
    return xs2[k]


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
