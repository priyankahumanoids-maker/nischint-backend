"""
HC-01 Day 4 — End-to-end smoke test for the BitwellBand → Health
Connect → NISCHINT pipeline. Runs against the live preview backend.

Pre-requisites: /app/memory/test_credentials.md mother account is
seeded; `REACT_APP_BACKEND_URL` available via conftest bootstrap.
"""
import os
import time
from datetime import datetime, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
MOTHER_EMAIL = "mothernischint@gmail.com"
MOTHER_PASSWORD = "nischint123"


pytestmark = pytest.mark.skipif(
    not BASE_URL,
    reason="REACT_APP_BACKEND_URL not configured; skipping live HC-01 E2E",
)


def _login() -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": MOTHER_EMAIL, "password": MOTHER_PASSWORD},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _post_signals(token: str, signals: list[dict]) -> requests.Response:
    return requests.post(
        f"{BASE_URL}/api/health-signals/wearable",
        headers={"Authorization": f"Bearer {token}"},
        json={"signals": signals},
        timeout=20,
    )


def test_bitwellband_hr_spike_triggers_alert():
    """HR=138 + SpO2=89 from a simulated BitwellBand → both fire breaches."""
    token = _login()

    # Warm-up: the brain's `evaluate_risk` lazy-loads an ML model on
    # first invocation (Phase-5 risk_model). Cold POST on the Mumbai
    # pooler is ~4s; warm path is <1s. We measure the *warm* p50,
    # which is what a real user experiences (the first sample they
    # ever send already happens after the app's auth round-trip and
    # backgroundLocation warmup).
    _post_signals(token, [{
        "type": "steps", "value": 100, "unit": "steps",
        "source": "warmup", "timestamp": _utc_now(),
    }])

    now = _utc_now()
    started = time.time()
    r = _post_signals(
        token,
        [
            {"type": "heart_rate", "value": 138, "unit": "bpm",
             "source": "BitwellBand", "timestamp": now},
            {"type": "spo2", "value": 89, "unit": "%",
             "source": "BitwellBand", "timestamp": now},
        ],
    )
    elapsed_ms = (time.time() - started) * 1000

    assert r.status_code == 200, r.text
    body = r.json()

    assert body["ingested"] == 2
    tags = sorted(b["tag"] for b in body["breaches"])
    assert tags == ["HR_HIGH", "SPO2_LOW"], tags

    # Latency budget for a 2-breach BitwellBand POST:
    #   • ~2.2s baseline = cross-region Mumbai auth DB lookup
    #     (get_current_user → SELECT users WHERE id=?). This is the
    #     same penalty every authenticated endpoint pays today; it's
    #     not specific to wearable ingest.
    #   • ~0.6s × 2 = brain SafetyEvent INSERT + env-hazard polygon
    #     check on each breach.
    # Total realistic warm budget on the Mumbai pooler: ~3.6s.
    # We pick 5000ms (1.4s of headroom) so this test stays green
    # through normal jitter without giving the brain hook a free
    # ride on regressions.
    assert elapsed_ms < 5000, f"warm-path latency {elapsed_ms:.0f}ms exceeded 5000ms"


def test_bitwellband_cooldown_idempotency():
    """
    Same sample posted twice within the TTL window must dedupe at the
    Redis-ZSET level (deterministic member based on sha1(type|ts|value)).
    Brain hook still fires both times — the brain has its own 300s
    composite-alert cooldown (`ALERT_COOLDOWN_TTL_S`) handled internally
    by `evaluate_risk`; we don't try to verify that here because it
    short-circuits silently. The behavioural contract we DO verify:
      • Re-posting the same payload returns 200, not an error.
      • Both responses report the same breach set.
    """
    token = _login()
    now = _utc_now()
    signal = [{"type": "heart_rate", "value": 142, "unit": "bpm",
               "source": "BitwellBand", "timestamp": now}]

    r1 = _post_signals(token, signal)
    r2 = _post_signals(token, signal)

    assert r1.status_code == 200 and r2.status_code == 200
    tags1 = sorted(b["tag"] for b in r1.json()["breaches"])
    tags2 = sorted(b["tag"] for b in r2.json()["breaches"])
    assert tags1 == tags2 == ["HR_HIGH"], (tags1, tags2)


def test_out_of_range_rejected():
    token = _login()
    now = _utc_now()

    # HR over the 300 bpm physiological ceiling.
    r1 = _post_signals(token, [{"type": "heart_rate", "value": 500,
                                "unit": "bpm", "source": "x", "timestamp": now}])
    assert r1.status_code == 422
    assert "out of range" in r1.text.lower()

    # SpO2 below the 70% floor.
    r2 = _post_signals(token, [{"type": "spo2", "value": 50,
                                "unit": "%", "source": "x", "timestamp": now}])
    assert r2.status_code == 422
    assert "out of range" in r2.text.lower()


def test_bad_iso_timestamp_rejected():
    token = _login()
    r = _post_signals(token, [{"type": "steps", "value": 100,
                               "unit": "steps", "source": "x",
                               "timestamp": "yesterday"}])
    assert r.status_code == 422


def test_dependent_endpoint_403_for_stranger():
    """A random UUID is not a guardian of anyone — must 403."""
    token = _login()
    r = requests.get(
        f"{BASE_URL}/api/health-signals/dependent/00000000-0000-0000-0000-000000000000/latest",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    assert r.status_code == 403
    assert "guardian" in r.text.lower()


def test_self_read_returns_latest_after_ingest():
    """Round-trip: ingest → self-read returns the values we just sent."""
    import base64
    import json as _json

    token = _login()
    sub = _json.loads(base64.urlsafe_b64decode(
        token.split(".")[1] + "==="
    ))["sub"]
    now = _utc_now()
    hr_val = 84.0
    spo2_val = 96.0

    r_in = _post_signals(token, [
        {"type": "heart_rate", "value": hr_val, "unit": "bpm",
         "source": "BitwellBand", "timestamp": now},
        {"type": "spo2", "value": spo2_val, "unit": "%",
         "source": "BitwellBand", "timestamp": now},
    ])
    assert r_in.status_code == 200

    r_out = requests.get(
        f"{BASE_URL}/api/health-signals/dependent/{sub}/latest",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    assert r_out.status_code == 200
    body = r_out.json()
    assert body["dependent_id"] == sub
    assert body["hr"] == hr_val
    assert body["spo2"] == spo2_val
    assert body["last_sync"] is not None


def test_dependent_endpoint_requires_auth():
    r = requests.get(
        f"{BASE_URL}/api/health-signals/dependent/00000000-0000-0000-0000-000000000000/latest",
        timeout=15,
    )
    assert r.status_code == 401
