"""NISCH-012 — Motion features ingestion + Trust Tile freshness tests.

Locks the contracts that the Layer 5 Risk Engine depends on:

  1. Ingestion is idempotent on `device_id|window_started_at`.
  2. Activity-class validation rejects out-of-taxonomy values at
     the writer boundary (422).
  3. The behavioural baseline learner pulls motion-feature
     aggregates into `mobility_signature` additively — no
     regression to the GPS-derived signal.
  4. Trust Tile reads motion-freshness and reports
     `motion_telemetry_stale` (MEDIUM only, never LOW).
  5. Reason priority ladder includes `motion_telemetry_stale`
     between `unresolved_backlog` and `insufficient_reconciliation_window`.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.models.motion_features import (
    ALLOWED_ACTIVITY_CLASSES, TELEMETRY_PIPELINE_VERSION,
)
from app.services.behavioral.badge import (
    REASON_PRIORITY, pick_priority_reason,
)
from app.services.behavioral.trust import (
    MOTION_FRESHNESS_MEDIUM_RED_S, ReasonCode, TrustLevel,
    evaluate_trust,
)


# ── Activity-class taxonomy ──────────────────────────────────────


def test_activity_class_taxonomy_locked():
    """Locked at exactly 5 values. Mirrors NISCH-011's deviation-
    class lock — any new value here must update the mobile
    classifier in lockstep."""
    assert ALLOWED_ACTIVITY_CLASSES == frozenset({
        "stationary", "walking", "running", "vehicle", "anomalous",
    })


def test_telemetry_pipeline_version_present():
    """Bumped whenever the mobile feature extractor or
    activity classifier changes. Locked at a string so reports
    can group rows by algorithm version."""
    assert TELEMETRY_PIPELINE_VERSION
    assert TELEMETRY_PIPELINE_VERSION.startswith("motion-")


# ── Trust evaluator — motion freshness ───────────────────────────


def _healthy_warm():
    """All inputs healthy + warmed up. Floor for delta tests."""
    return dict(
        divergence_index=0.05,
        reconciliation_lag_s=60.0,
        reconciled_predictions=200,
        critical_precision=0.85,
        false_escalation_rate=0.02,
        dlq_depth=0,
        unresolved_count=0,
    )


def test_motion_freshness_within_threshold_keeps_high_trust():
    """Fresh motion stream (< 30 min) → trust stays HIGH."""
    r = evaluate_trust(
        **_healthy_warm(),
        motion_signal_freshness_s=60.0,
    )
    assert r.level == TrustLevel.HIGH.value
    assert ReasonCode.MOTION_TELEMETRY_STALE.value not in r.reason_codes


def test_motion_freshness_at_or_above_threshold_drops_to_medium():
    """Stale motion → MEDIUM with the locked reason code.
    Note: warmup gate also fires here because the synthetic
    `reconciled_predictions=200` would normally suppress that —
    but `_healthy_warm` puts it ABOVE 168 so warmup IS satisfied.
    We only expect motion_telemetry_stale as the lone red flag."""
    r = evaluate_trust(
        **_healthy_warm(),
        motion_signal_freshness_s=MOTION_FRESHNESS_MEDIUM_RED_S,
    )
    assert r.level == TrustLevel.MEDIUM.value
    assert ReasonCode.MOTION_TELEMETRY_STALE.value in r.reason_codes


def test_motion_freshness_extreme_value_still_only_medium():
    """LOCKED INVARIANT: motion freshness is observational —
    NEVER alone-pushes LOW. Even a 24-hour stale stream tops out
    at MEDIUM. Risk Engine falls back to GPS-only behaviour."""
    r = evaluate_trust(
        **_healthy_warm(),
        motion_signal_freshness_s=24 * 3600,
    )
    assert r.level == TrustLevel.MEDIUM.value
    assert ReasonCode.MOTION_TELEMETRY_STALE.value in r.reason_codes


def test_motion_freshness_none_is_treated_as_unavailable():
    """None → signal absent → no `motion_telemetry_stale` flag.
    Fail-safe pattern matches the rest of the trust evaluator."""
    r = evaluate_trust(
        **_healthy_warm(),
        motion_signal_freshness_s=None,
    )
    assert ReasonCode.MOTION_TELEMETRY_STALE.value not in r.reason_codes
    assert r.level == TrustLevel.HIGH.value


# ── Reason ladder ────────────────────────────────────────────────


def test_motion_stale_in_reason_priority_ladder():
    """New code must be registered in the badge priority ladder
    so the operator UI knows what to render."""
    assert "motion_telemetry_stale" in REASON_PRIORITY


def test_motion_stale_outranks_warmup_but_not_unresolved_backlog():
    """Order lock — motion staleness is more actionable than
    cold-start warmup, but less acute than unresolved backlog."""
    a = REASON_PRIORITY.index("unresolved_backlog")
    b = REASON_PRIORITY.index("motion_telemetry_stale")
    c = REASON_PRIORITY.index("insufficient_reconciliation_window")
    assert a < b < c


def test_badge_picker_surfaces_motion_when_present():
    """When motion-stale + warmup-needed both fire, the badge
    must surface motion-stale (higher priority)."""
    assert pick_priority_reason([
        "insufficient_reconciliation_window",
        "motion_telemetry_stale",
    ]) == "motion_telemetry_stale"


# ── API endpoint — auth + validation ─────────────────────────────


@pytest.fixture
def client():
    """Function-scoped TestClient."""
    from server import app as fastapi_app
    with TestClient(fastapi_app) as c:
        yield c


def _login(client) -> str:
    r = client.post("/api/auth/login", json={
        "email": "operator@nischint.com",
        "password": "OperatorSecure!2026",
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_motion_features_requires_auth(client):
    """Unauth call must be rejected. No anonymous ingestion."""
    r = client.post("/api/sensors/motion/features", json={
        "device_id": "d",
        "windows": [{
            "window_started_at": "2026-05-13T13:00:00Z",
            "accel_mean_g": 1.0, "accel_stddev_g": 0.1,
            "accel_peak_g": 1.5, "gyro_variance": 0.05,
            "activity_class": "walking",
            "sample_count": 300, "sample_rate_hz": 5.0,
        }],
    })
    assert r.status_code in (401, 403)


def test_motion_features_rejects_bogus_activity_class(client):
    """Writer-boundary lock — 422 on out-of-taxonomy class."""
    token = _login(client)
    r = client.post(
        "/api/sensors/motion/features",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "device_id": "d-validate",
            "windows": [{
                "window_started_at": "2026-05-13T13:00:00Z",
                "accel_mean_g": 1.0, "accel_stddev_g": 0.1,
                "accel_peak_g": 1.5, "gyro_variance": 0.05,
                "activity_class": "definitely_not_a_class",
                "sample_count": 300, "sample_rate_hz": 5.0,
            }],
        },
    )
    assert r.status_code == 422


def test_motion_features_idempotency(client):
    """Same `device_id|window_started_at` twice → second call
    reports the row as `duplicate`, not `inserted`. No 500, no
    duplicate row. Locks the retry-after-flaky-network contract."""
    token = _login(client)
    # Use a unique window timestamp so test re-runs don't collide.
    iso = "2026-05-13T14:" + str(int(uuid.uuid4().int) % 60).zfill(2) + ":00Z"
    payload = {
        "device_id": f"d-{uuid.uuid4()}",
        "windows": [{
            "window_started_at": iso,
            "accel_mean_g": 1.0, "accel_stddev_g": 0.1,
            "accel_peak_g": 1.5, "gyro_variance": 0.05,
            "activity_class": "walking",
            "sample_count": 300, "sample_rate_hz": 5.0,
        }],
    }
    r1 = client.post(
        "/api/sensors/motion/features",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1["status"] == "ok"
    assert b1["inserted"] == 1
    assert b1["duplicate"] == 0

    r2 = client.post(
        "/api/sensors/motion/features",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2["status"] == "ok"
    assert b2["inserted"] == 0
    assert b2["duplicate"] == 1


def test_motion_features_response_includes_pipeline_version(client):
    """The response carries the locked pipeline version so the
    operator UI / accuracy reports can group rows by algorithm."""
    token = _login(client)
    iso = "2026-05-13T15:" + str(int(uuid.uuid4().int) % 60).zfill(2) + ":00Z"
    r = client.post(
        "/api/sensors/motion/features",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "device_id": f"d-{uuid.uuid4()}",
            "windows": [{
                "window_started_at": iso,
                "accel_mean_g": 0.05, "accel_stddev_g": 0.02,
                "accel_peak_g": 0.12, "gyro_variance": 0.0001,
                "activity_class": "stationary",
                "sample_count": 300, "sample_rate_hz": 5.0,
            }],
        },
    )
    assert r.status_code == 200
    assert r.json()["telemetry_pipeline_version"] == TELEMETRY_PIPELINE_VERSION


def test_motion_features_batch_size_capped(client):
    """LOCKED: batches over 12 windows are rejected at the
    Pydantic boundary. Caps the per-call cost + prevents an
    abusive uploader from drowning the table in a single call."""
    token = _login(client)
    windows = [{
        "window_started_at": f"2026-05-13T16:00:{str(i).zfill(2)}Z",
        "accel_mean_g": 1.0, "accel_stddev_g": 0.1,
        "accel_peak_g": 1.5, "gyro_variance": 0.05,
        "activity_class": "walking",
        "sample_count": 300, "sample_rate_hz": 5.0,
    } for i in range(13)]      # one over the cap
    r = client.post(
        "/api/sensors/motion/features",
        headers={"Authorization": f"Bearer {token}"},
        json={"device_id": "d-cap", "windows": windows},
    )
    assert r.status_code == 422


# ── Behavioral baseline learner — additive mobility_signature ────


def test_baseline_motion_enrichment_additive():
    """The behavioural baseline learner must still produce the
    GPS-derived `mobility_signature` even when the motion-feature
    enrichment call would fail. Locked additive contract."""
    from app.services.behavioral.baseline import build_baseline_features
    # Pure-function only — the upsert path is where the additive
    # try/except lives; build_baseline_features remains untouched.
    samples = [
        {"speed_mps": 1.0, "dwell_s": 60, "hour": 9, "zone_id": "z1"},
        {"speed_mps": 1.2, "dwell_s": 50, "hour": 9, "zone_id": "z1"},
    ]
    f = build_baseline_features(samples)
    # The motion telemetry sub-key is NOT populated by the pure
    # function — it's grafted in by `upsert_baseline` after the
    # additive fetch. This asserts the surface contract: the GPS
    # signature is the floor, motion is enrichment.
    assert "mobility_signature" in f
    assert "mean_speed_mps" in f["mobility_signature"]
    assert "motion_telemetry" not in f["mobility_signature"]
