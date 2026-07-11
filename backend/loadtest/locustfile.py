"""Locust load test — Days 11-12 launch prep (LT-01).

DESIGN NOTE (revised v2):
  v1 tried to hit `/api/auth/login` from 60 concurrent VUs sharing one
  test account. The brute-force protection correctly fired 429s, which
  is a positive security finding but invalidates the load measurement.

  Revised approach:
   * Login ONCE in `test_start`, share token across all VUs
   * Scenario 1 is now `GET /api/auth/me` (JWT verify + user lookup
     under load) — measures the auth path that >99% of authenticated
     requests actually exercise
   * SOS rate-limit is 10/min/IP — scenario 3 stays at weight=1 so
     we don't fight the limiter during the test window

Per-task weights tuned for a `--users 60` run:
  * S1 /me            weight 5  (~50 share — "auth-verified read")
  * S2 dashboard      weight 3  (~30 share)
  * S3 SOS trigger    weight 1  (~10 share, LT short-circuit on)
  * S4 health-signals weight 2  (~20 share)

Refuses to run against production (nischint.care).

Usage:
    HOST=http://localhost:8001 LT_TOKEN=<token> \
    locust -f backend/loadtest/locustfile.py --headless \
           --users 60 --spawn-rate 10 --run-time 60s \
           --host "$HOST" --csv /tmp/loadtest_results
"""
from __future__ import annotations

import os
import random
import time

from locust import HttpUser, task, between, events


_TEST_EMAIL    = os.environ.get("LT_USER_EMAIL", "nischint4parents@gmail.com")
_TEST_PASSWORD = os.environ.get("LT_USER_PASSWORD", "secret123")
_LT_TOKEN      = os.environ.get("LT_TOKEN", "")

# Shared auth token populated once by the test_start hook.
SHARED_AUTH_TOKEN: str = ""


@events.test_start.add_listener
def _on_test_start(environment, **kwargs):
    if not _LT_TOKEN:
        raise RuntimeError(
            "LT_TOKEN env var is required. Read it from /app/backend/.env "
            "(LOADTEST_TOKEN). Refusing to run without the short-circuit."
        )
    host = environment.host or ""
    if "nischint.care" in host:
        raise RuntimeError(
            "Refusing to run against production (nischint.care). "
            "Use the preview URL or localhost:8001 instead."
        )
    # Login once. We deliberately bypass locust's HTTP session here so
    # the bootstrap login isn't counted in the measured request stream.
    import requests
    global SHARED_AUTH_TOKEN
    r = requests.post(
        f"{host}/api/auth/login",
        json={"email": _TEST_EMAIL, "password": _TEST_PASSWORD},
        timeout=15,
    )
    r.raise_for_status()
    d = r.json()
    SHARED_AUTH_TOKEN = d.get("access_token") or d.get("token") or ""
    if not SHARED_AUTH_TOKEN:
        raise RuntimeError("Bootstrap login returned no token")
    print(f"[LT-01] bootstrap login OK; sharing 1 token across {environment.runner.target_user_count} VUs")


class NischintLoadUser(HttpUser):
    """Single virtual user. Uses the shared bootstrap token."""

    wait_time = between(0.1, 0.6)

    @property
    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {SHARED_AUTH_TOKEN}"}

    # ── Scenario 1: JWT-verified read (~50 concurrent share) ──────
    @task(5)
    def s1_auth_me(self):
        # `GET /api/auth/me` is the canonical "session is alive" probe
        # every authenticated client hits at least once per page load.
        # Measures JWT verify + user lookup under contention.
        self.client.get(
            "/api/auth/me",
            headers=self._auth_headers,
            name="s1:auth/me",
            timeout=10,
        )

    # ── Scenario 2: guardian dashboard list (~30 concurrent share) ─
    @task(3)
    def s2_guardian_dashboard(self):
        self.client.get(
            "/api/guardian/sessions/active",
            headers=self._auth_headers,
            name="s2:guardian/sessions/active",
            timeout=10,
        )

    # ── Scenario 3: SOS trigger (~10 concurrent — SHORT-CIRCUITED) ─
    @task(1)
    def s3_sos_trigger(self):
        self.client.post(
            "/api/sos/trigger",
            json={
                "trigger_type": "loadtest",
                "lat":  12.97 + random.uniform(-0.02, 0.02),
                "lng":  77.59 + random.uniform(-0.02, 0.02),
            },
            headers={
                **self._auth_headers,
                "X-Loadtest-Token": _LT_TOKEN,
            },
            name="s3:sos/trigger (LT shortcircuit)",
            timeout=10,
        )

    # ── Scenario 4: health-signals wearable POST (~20 share) ──────
    @task(2)
    def s4_health_signals(self):
        now_ms = int(time.time() * 1000)
        payload = {
            "signals": [
                {
                    "type": "heart_rate",
                    "value": random.uniform(65, 95),
                    "unit": "bpm",
                    "timestamp": _iso_from_ms(now_ms - 60_000),
                    "source": "wearable",
                },
                {
                    "type": "spo2",
                    "value": random.uniform(96, 99),
                    "unit": "%",
                    "timestamp": _iso_from_ms(now_ms),
                    "source": "wearable",
                },
            ]
        }
        self.client.post(
            "/api/health-signals/wearable",
            json=payload,
            headers={
                **self._auth_headers,
                "X-Device-Id":    random.choice([
                    "loadtest-dev-A-aaaa-bbbb-cccc-111111111111",
                    "loadtest-dev-B-aaaa-bbbb-cccc-222222222222",
                ]),
                "X-Device-Model": random.choice(["LoadtestWatch A", "LoadtestWatch B"]),
            },
            name="s4:health-signals/wearable",
            timeout=10,
        )


def _iso_from_ms(ms: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
