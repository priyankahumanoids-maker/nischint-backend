"""Regression tests for DPDP §11 right-of-access export.

Endpoint: GET /api/privacy/me
Hits the live preview backend (REACT_APP_BACKEND_URL) using seeded
mother account credentials from /app/memory/test_credentials.md.
"""
import os

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
MOTHER_EMAIL = "mothernischint@gmail.com"
MOTHER_PASSWORD = "nischint123"


pytestmark = pytest.mark.skipif(
    not BASE_URL,
    reason="REACT_APP_BACKEND_URL not configured; skipping live integration test",
)


def _login() -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": MOTHER_EMAIL, "password": MOTHER_PASSWORD},
        timeout=15,
    )
    r.raise_for_status()
    body = r.json()
    return body.get("access_token") or body["token"]


def test_privacy_me_requires_auth():
    r = requests.get(f"{BASE_URL}/api/privacy/me", timeout=15)
    assert r.status_code == 401


def test_privacy_me_json_export_shape():
    token = _login()
    r = requests.get(
        f"{BASE_URL}/api/privacy/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    assert r.status_code == 200
    assert r.headers.get("X-DPDP-Export-Version") == "1.0"
    assert r.headers.get("content-type", "").startswith("application/json")

    body = r.json()

    # Required top-level sections.
    for key in (
        "export_meta",
        "data_principal",
        "seniors_under_care",
        "data_categories",
        "privacy_disclosures",
        "third_party_processors",
        "rights",
    ):
        assert key in body, f"missing section: {key}"

    # Data residency disclosure — must be Mumbai (DPDP requirement).
    assert "ap-south-1" in body["export_meta"]["data_residency"]
    assert "Mumbai" in body["export_meta"]["data_residency"]

    # Critical "no audio" disclosure must be present verbatim.
    audio_disc = body["privacy_disclosures"]["audio"]
    assert "No audio stored" in audio_disc
    assert "inference only" in audio_disc

    # Principal echoes the authenticated identity.
    assert body["data_principal"]["email"] == MOTHER_EMAIL

    # Counts are integers (not None / not "0").
    for cat in body["data_categories"].values():
        assert isinstance(cat["records"], int)
        assert cat["records"] >= 0

    # Rights section must list erasure contact.
    assert "privacy@nischint.care" in body["rights"]["erasure"]


def test_privacy_me_pdf_export():
    token = _login()
    r = requests.get(
        f"{BASE_URL}/api/privacy/me?format=pdf",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"
    # Reasonable size — not an empty 1-page placeholder.
    assert len(r.content) > 2000


def test_privacy_me_rejects_invalid_format():
    token = _login()
    r = requests.get(
        f"{BASE_URL}/api/privacy/me?format=xml",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    assert r.status_code == 422
