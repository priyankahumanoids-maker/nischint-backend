"""Soak-test locustfile — Days 11-12 launch prep (LT-01).

Steady-state low-concurrency run for 30 minutes. Goal: surface memory
leaks, connection-pool growth, file-descriptor leaks, and scheduler
drift that the headline 60s test can't catch.

JWT refresh (LT-01 v2): the first soak run died ~20 min in when the
bootstrap JWT expired and 100% of requests returned 401. We now
re-login every 5 minutes (token TTL is typically 30 min in this
codebase, refreshed at 1/6 of TTL for a comfortable safety margin).

Mix matches the headline test (auth/me, dashboard, SOS short-circuit,
health-signals) but at 5 VUs total → ~3 req/s aggregate, well under
any rate limiter and well under single-worker CPU saturation.
"""
from __future__ import annotations

import os
import random
import threading
import time

import requests
from locust import HttpUser, task, between, events


_TEST_EMAIL    = os.environ.get("LT_USER_EMAIL", "nischint4parents@gmail.com")
_TEST_PASSWORD = os.environ.get("LT_USER_PASSWORD", "secret123")
_LT_TOKEN      = os.environ.get("LT_TOKEN", "")
_HOST          = ""

# Shared token + lock. The refresh thread updates this every 5 min.
SHARED_AUTH_TOKEN: str = ""
_token_lock = threading.Lock()
_refresh_stop = threading.Event()


def _login_once() -> str:
    """Single login. Bypasses locust's session so the refresh isn't
    counted in measured request stats."""
    r = requests.post(
        f"{_HOST}/api/auth/login",
        json={"email": _TEST_EMAIL, "password": _TEST_PASSWORD},
        timeout=15,
    )
    r.raise_for_status()
    d = r.json()
    return d.get("access_token") or d.get("token") or ""


def _refresh_loop():
    """Background thread — re-login every 5 min so the shared JWT
    never expires mid-soak. Idempotent; safe to run alongside the
    VU traffic since /api/auth/login has a 5/min/IP rate limit and
    our refresh is 1/5min, comfortably under."""
    while not _refresh_stop.wait(300):  # 5 minutes
        try:
            new_token = _login_once()
            with _token_lock:
                global SHARED_AUTH_TOKEN
                SHARED_AUTH_TOKEN = new_token
            print(f"[LT-01 soak] JWT refreshed at t={time.strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"[LT-01 soak] JWT refresh FAILED: {e!r}")


@events.test_start.add_listener
def _on_test_start(environment, **kwargs):
    if not _LT_TOKEN:
        raise RuntimeError("LT_TOKEN env var required")
    host = environment.host or ""
    if "nischint.care" in host:
        raise RuntimeError("Refusing to run against production")
    global _HOST, SHARED_AUTH_TOKEN
    _HOST = host
    SHARED_AUTH_TOKEN = _login_once()
    if not SHARED_AUTH_TOKEN:
        raise RuntimeError("Bootstrap login returned no token")
    threading.Thread(target=_refresh_loop, daemon=True).start()
    print(f"[LT-01 soak] bootstrap login OK; JWT refresh thread armed (every 5 min)")


@events.test_stop.add_listener
def _on_test_stop(environment, **kwargs):
    _refresh_stop.set()


def _current_token() -> str:
    with _token_lock:
        return SHARED_AUTH_TOKEN


class SoakUser(HttpUser):
    # 1-3 second pacing → ~0.5 req/s per VU → ~2.5 req/s aggregate at 5 VUs
    wait_time = between(1.0, 3.0)

    @property
    def _h(self):
        return {"Authorization": f"Bearer {_current_token()}"}

    @task(5)
    def s1_me(self):
        self.client.get("/api/auth/me", headers=self._h, name="soak:auth/me", timeout=15)

    @task(3)
    def s2_dashboard(self):
        self.client.get("/api/guardian/sessions/active", headers=self._h,
                        name="soak:guardian/sessions/active", timeout=15)

    @task(1)
    def s3_sos(self):
        self.client.post(
            "/api/sos/trigger",
            json={"trigger_type": "loadtest", "lat": 12.97, "lng": 77.59},
            headers={**self._h, "X-Loadtest-Token": _LT_TOKEN},
            name="soak:sos/trigger (LT)",
            timeout=15,
        )

    @task(2)
    def s4_signals(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.client.post(
            "/api/health-signals/wearable",
            json={"signals": [{
                "type": "heart_rate", "value": random.uniform(65, 95),
                "unit": "bpm", "timestamp": now, "source": "wearable",
            }]},
            headers={**self._h,
                     "X-Device-Id": "soaktest-aaaa-bbbb-cccc-soak",
                     "X-Device-Model": "SoakWatch"},
            name="soak:health-signals/wearable",
            timeout=15,
        )
