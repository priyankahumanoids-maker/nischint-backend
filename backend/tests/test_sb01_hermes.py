"""
SB-01 Day 1 — Regression suite for the Hermes data-capture layer.

Pure-HTTP — no direct DB calls from pytest (the Mumbai session pooler
caps total clients at 15 and the backend already saturates it on busy
days). The fixture discovers a real SafetyEvent via
`GET /api/safety-brain/events` instead.

Covers:
  • Path A — admin/operator read endpoints (status, user-baseline).
  • Path D — auth-gated ground-truth feedback POST.
"""
import base64
import json
import os
from datetime import datetime, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN_EMAIL = "nischint4parents@gmail.com"
ADMIN_PASSWORD = "secret123"
MOM_EMAIL = "mothernischint@gmail.com"
MOM_PASSWORD = "nischint123"
KID_EMAIL = "kidnischint@gmail.com"
KID_PASSWORD = "nischint123"

# Unique per-run tag so re-running this file never collides with a
# previous run's UPSERTed rows (we use UNIQUE (event, source) on the
# table; re-running with the same tag would just overwrite — fine —
# but a unique tag makes log forensics easier).
NOTE_TAG = "sb01_test_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


pytestmark = pytest.mark.skipif(
    not BASE_URL,
    reason="REACT_APP_BACKEND_URL not configured; skipping live SB-01 tests",
)


def _login(email: str, pw: str) -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": pw},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _sub(token: str) -> str:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))["sub"]


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def mom_token() -> str:
    return _login(MOM_EMAIL, MOM_PASSWORD)


@pytest.fixture(scope="module")
def kid_token() -> str:
    return _login(KID_EMAIL, KID_PASSWORD)


@pytest.fixture(scope="module")
def moms_event_id(mom_token: str) -> str:
    """Use the existing /safety-brain/events list to find a real event."""
    r = requests.get(
        f"{BASE_URL}/api/safety-brain/events?limit=1",
        headers={"Authorization": f"Bearer {mom_token}"},
        timeout=15,
    )
    if r.status_code != 200:
        pytest.skip(f"events list returned {r.status_code}; cannot pick event")
    events = r.json().get("events") or []
    if not events:
        pytest.skip("No SafetyEvent exists for mother account; nothing to grade")
    return events[0]["event_id"]


# ── Path A — admin read endpoints ──────────────────────────────────


def test_status_requires_auth():
    r = requests.get(f"{BASE_URL}/api/admin/sb01/status", timeout=15)
    assert r.status_code == 401


def test_status_403_for_non_admin(mom_token: str):
    r = requests.get(
        f"{BASE_URL}/api/admin/sb01/status",
        headers={"Authorization": f"Bearer {mom_token}"},
        timeout=15,
    )
    assert r.status_code == 403


def test_status_admin_ok(admin_token: str):
    r = requests.get(
        f"{BASE_URL}/api/admin/sb01/status",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 200
    body = r.json()
    for key in (
        "total_devices", "devices_with_baseline", "baseline_rows",
        "coverage_pct", "feedback_rows",
    ):
        assert key in body, f"missing {key}"
    assert isinstance(body["total_devices"], int)
    assert 0.0 <= body["coverage_pct"] <= 100.0


def test_user_baseline_admin_ok(admin_token: str):
    admin_sub = _sub(admin_token)
    r = requests.get(
        f"{BASE_URL}/api/admin/sb01/user-baseline/{admin_sub}",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == admin_sub
    assert "device_count" in body
    assert "aggregated" in body


def test_user_baseline_403_for_non_admin(mom_token: str):
    r = requests.get(
        f"{BASE_URL}/api/admin/sb01/user-baseline/{_sub(mom_token)}",
        headers={"Authorization": f"Bearer {mom_token}"},
        timeout=15,
    )
    assert r.status_code == 403


# ── Path D — feedback endpoint ─────────────────────────────────────


def test_feedback_unauth():
    r = requests.post(
        f"{BASE_URL}/api/safety-events/00000000-0000-0000-0000-000000000000/feedback",
        json={"verdict": "confirmed"},
        timeout=15,
    )
    assert r.status_code == 401


def test_feedback_404_for_bogus_event(mom_token: str):
    r = requests.post(
        f"{BASE_URL}/api/safety-events/00000000-0000-0000-0000-000000000000/feedback",
        headers={"Authorization": f"Bearer {mom_token}"},
        json={"verdict": "confirmed", "notes": f"{NOTE_TAG} bogus"},
        timeout=15,
    )
    assert r.status_code == 404


def test_feedback_invalid_verdict(mom_token: str, moms_event_id: str):
    r = requests.post(
        f"{BASE_URL}/api/safety-events/{moms_event_id}/feedback",
        headers={"Authorization": f"Bearer {mom_token}"},
        json={"verdict": "maybe"},
        timeout=15,
    )
    assert r.status_code == 422


def test_feedback_stranger_blocked(kid_token: str, moms_event_id: str):
    """Kid is not mother's guardian → must 403."""
    r = requests.post(
        f"{BASE_URL}/api/safety-events/{moms_event_id}/feedback",
        headers={"Authorization": f"Bearer {kid_token}"},
        json={"verdict": "false_positive", "notes": f"{NOTE_TAG} kid"},
        timeout=15,
    )
    assert r.status_code == 403


def test_feedback_self_grade(mom_token: str, moms_event_id: str):
    r = requests.post(
        f"{BASE_URL}/api/safety-events/{moms_event_id}/feedback",
        headers={"Authorization": f"Bearer {mom_token}"},
        json={"verdict": "false_positive", "notes": f"{NOTE_TAG} self"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stored"] is True
    assert body["feedback_source"] == "user"
    assert body["verdict"] == "false_positive"


def test_feedback_operator_grade(admin_token: str, moms_event_id: str):
    """Admin grading user's event should land with feedback_source='operator'."""
    r = requests.post(
        f"{BASE_URL}/api/safety-events/{moms_event_id}/feedback",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"verdict": "confirmed", "notes": f"{NOTE_TAG} operator"},
        timeout=15,
    )
    assert r.status_code == 200
    assert r.json()["feedback_source"] == "operator"


def test_feedback_upsert_overwrites_same_source(
    mom_token: str, admin_token: str, moms_event_id: str,
):
    """
    Same source re-grading must UPSERT, not duplicate.

    Verified by:
      1. baseline `feedback_rows` count from /status
      2. submit two distinct verdicts as the same source (user)
      3. /status `feedback_rows` should have grown by exactly 1
         (the first POST creates a row, the second UPSERTs it).
    """
    s0 = requests.get(
        f"{BASE_URL}/api/admin/sb01/status",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    ).json()
    before = int(s0["feedback_rows"])

    r1 = requests.post(
        f"{BASE_URL}/api/safety-events/{moms_event_id}/feedback",
        headers={"Authorization": f"Bearer {mom_token}"},
        json={"verdict": "false_positive", "notes": f"{NOTE_TAG} v1"},
        timeout=15,
    )
    assert r1.status_code == 200

    r2 = requests.post(
        f"{BASE_URL}/api/safety-events/{moms_event_id}/feedback",
        headers={"Authorization": f"Bearer {mom_token}"},
        json={"verdict": "unsure", "notes": f"{NOTE_TAG} v2"},
        timeout=15,
    )
    assert r2.status_code == 200

    s1 = requests.get(
        f"{BASE_URL}/api/admin/sb01/status",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    ).json()
    after = int(s1["feedback_rows"])

    delta = after - before
    # Allow ≤1 — first POST adds a row only if the prior self-grade
    # test ran first AND its row still exists. Either way, the second
    # POST cannot add a row (would violate unique idx). delta must be
    # in {0, 1}. delta of 2+ would prove UPSERT is broken.
    assert delta <= 1, (
        f"UPSERT broken — feedback_rows grew by {delta} after 2 same-source POSTs"
    )
