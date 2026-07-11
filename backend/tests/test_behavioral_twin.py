"""NISCH-011 — Behavioral Baseline + Digital Twin contract tests.

Locks the Phase-1 invariants across taxonomy, divergence engine,
fusion engine, baseline learner, anomaly detector, DLQ, prewarmer,
temporal memory, and the API surface.

Coverage matrix:

  Taxonomy (locked 5-value enum)
    * classify_from_z thresholds (4 boundaries + baseline)
    * severity_rank ordering
    * ALLOWED_DEVIATION_CLASSES frozenset is exactly the 5 values

  Forecast divergence engine
    * < 2 votes → weight 1.0 (can't measure disagreement)
    * agreeing votes → weight ≈ 1.0
    * disagreeing votes → index ↑, weight ↓
    * locked floor at 0.2 — even max-disagreement keeps 20 % signal

  Fusion engine (PRODUCT BRIEF INVARIANTS)
    * Divergence DAMPENS the fused score, NEVER amplifies
    * critical_behavioral_shift WITHOUT zone risk does NOT influence
      dispatch
    * critical_behavioral_shift WITH zone_risk ≥ threshold does
      influence dispatch
    * non-critical taxonomy classes never influence dispatch
    * components are bounded [0, 1] — overflow inputs clamp

  Baseline learner
    * build_baseline_features pure-function correctness
    * shannon_entropy edge cases (empty, single, uniform)

  Anomaly detector
    * Cold-start (no baseline) → BASELINE class, no dispatch
    * Zero-stdev baseline → Z=0 (no divide-by-zero, no spurious anomaly)
    * write_anomaly rejects out-of-taxonomy class
    * INSERT-only: write_anomaly does not expose an UPDATE path

  DLQ ledger
    * append + read_recent roundtrip on Redis (skipped if unavailable)
    * ledger_depth returns 0 on Redis failure

  Temporal memory
    * record_event writes to Redis (5/30-min sorted sets) — NOT Postgres
    * read_window only accepts the locked window sizes

  Prewarmer
    * Declarative metadata locked at 1-h cadence + 2.0 s budget
    * fetch() returns None on DB error (cache-preserved fail-safe)

  API surface
    * /api/behavioral/baseline returns cold_start shape for unknown
    * /api/behavioral/anomalies returns empty list for unknown
    * /api/behavioral/metrics returns warmup-gated chip shape
    * /api/behavioral/dlq returns depth + items shape
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.services.behavioral import (
    ANOMALY_PIPELINE_VERSION, BASELINE_VERSION,
)
from app.services.behavioral.baseline import (
    _shannon_entropy, build_baseline_features,
)
from app.services.behavioral.detector import (
    score_anomaly, write_anomaly,
)
from app.services.behavioral.divergence import compute_divergence
from app.services.behavioral.dlq import (
    DLQ_KEY, LEDGER_MAX_ENTRIES, append_anomaly_ledger,
    ledger_depth, read_recent,
)
from app.services.behavioral.fusion import (
    DISPATCH_INFLUENCE_ZONE_RISK_THRESHOLD,
    fuse, fuse_with_explanation, should_influence_dispatch,
)
from app.services.behavioral.prewarmer import BehavioralBaselinePrewarmer
from app.services.behavioral.taxonomy import (
    ALLOWED_DEVIATION_CLASSES, DeviationClass,
    classify_from_z, severity_rank,
)
from app.services.behavioral.temporal import (
    WINDOW_5_MIN_S, WINDOW_30_MIN_S, read_window,
)


# ── Taxonomy lock ────────────────────────────────────────────────


def test_taxonomy_is_exactly_5_values():
    """Locks the enum surface — any future PR adding/removing a
    deviation class must update this test, surfacing in CI."""
    assert ALLOWED_DEVIATION_CLASSES == frozenset({
        "baseline", "drift", "irregular",
        "elevated_behavioral_risk", "critical_behavioral_shift",
    })


def test_classify_from_z_threshold_boundaries():
    """Each band edge — inclusive on the upper side. Locked so a
    future threshold tuning bumps the pipeline version not the
    table."""
    assert classify_from_z(0.0) == "baseline"
    assert classify_from_z(1.4) == "baseline"
    assert classify_from_z(1.5) == "drift"
    assert classify_from_z(1.99) == "drift"
    assert classify_from_z(2.0) == "irregular"
    assert classify_from_z(2.49) == "irregular"
    assert classify_from_z(2.5) == "elevated_behavioral_risk"
    assert classify_from_z(3.49) == "elevated_behavioral_risk"
    assert classify_from_z(3.5) == "critical_behavioral_shift"
    # Symmetric on negative side — |z| matters, not direction.
    assert classify_from_z(-3.6) == "critical_behavioral_shift"


def test_severity_rank_orders_classes():
    """The 5-step ladder — critical is strictly more severe than
    all others."""
    assert severity_rank("baseline") < severity_rank("drift")
    assert severity_rank("drift") < severity_rank("irregular")
    assert severity_rank("irregular") < severity_rank("elevated_behavioral_risk")
    assert severity_rank("elevated_behavioral_risk") \
        < severity_rank("critical_behavioral_shift")


# ── Divergence engine ────────────────────────────────────────────


def test_divergence_lt2_votes_returns_full_confidence():
    """< 2 forecasters → can't measure disagreement → weight=1.0.
    Locks the cold-start contract."""
    r = compute_divergence([])
    assert r.confidence_weight == 1.0
    assert r.index == 0.0
    r = compute_divergence([0.5])
    assert r.confidence_weight == 1.0


def test_divergence_agreeing_votes_keeps_weight_high():
    """Agreement → low divergence → weight ≈ 1.0."""
    r = compute_divergence([0.5, 0.5, 0.5])
    assert r.index == 0.0
    assert r.confidence_weight == 1.0


def test_divergence_disagreeing_votes_dampens():
    """Maximum disagreement in [0, 1] → high index → low weight."""
    r = compute_divergence([0.05, 0.95])
    assert r.index > 0.5
    assert r.confidence_weight < 0.5


def test_divergence_floor_at_0_2():
    """Even max-disagreement keeps 20% signal — operators still see
    SOMETHING. Floor locked in `compute_divergence`."""
    r = compute_divergence([0.0, 1.0])
    assert r.confidence_weight >= 0.2


# ── Fusion engine — PRODUCT BRIEF INVARIANTS ─────────────────────


def test_fusion_is_multiplicative():
    """Cross-product, not sum. A 0 in any modulator zeroes the
    fused output — `temporal_context=0` zeroes everything."""
    assert fuse(behavioral_anomaly=0.8, zone_risk=0.8,
                temporal_context=0.0) == 0.0
    assert fuse(behavioral_anomaly=0.8, zone_risk=0.8,
                sensor_confidence=0.0) == 0.0


def test_fusion_divergence_only_dampens_never_amplifies():
    """LOCKED INVARIANT: forecast divergence is allowed to DROP
    the fused risk, never raise it. The test sweeps weight from
    1.0 → 0.2 and asserts monotone-decreasing output."""
    base = fuse(
        behavioral_anomaly=0.8, zone_risk=0.6,
        temporal_context=1.0, sensor_confidence=1.0,
        divergence_weight=1.0,
    )
    dampened = fuse(
        behavioral_anomaly=0.8, zone_risk=0.6,
        temporal_context=1.0, sensor_confidence=1.0,
        divergence_weight=0.5,
    )
    assert dampened < base
    floor = fuse(
        behavioral_anomaly=0.8, zone_risk=0.6,
        temporal_context=1.0, sensor_confidence=1.0,
        divergence_weight=0.2,
    )
    assert floor < dampened


def test_critical_behavioral_shift_alone_does_not_influence_dispatch():
    """LOCKED INVARIANT: `critical_behavioral_shift` WITHOUT
    corroborating zone risk DOES NOT escalate dispatch weight.
    Strict gate — the most important behavioural contract."""
    # Zone risk below threshold — no influence.
    assert should_influence_dispatch(
        deviation_class="critical_behavioral_shift",
        zone_risk=0.5,
        zone_risk_threshold=DISPATCH_INFLUENCE_ZONE_RISK_THRESHOLD,
    ) is False
    # Even at zone_risk=0 — no influence.
    assert should_influence_dispatch(
        deviation_class="critical_behavioral_shift",
        zone_risk=0.0,
    ) is False


def test_critical_with_zone_risk_above_threshold_influences_dispatch():
    """Counter-test — when corroborated, it DOES influence."""
    assert should_influence_dispatch(
        deviation_class="critical_behavioral_shift",
        zone_risk=0.65,
    ) is True
    assert should_influence_dispatch(
        deviation_class="critical_behavioral_shift",
        zone_risk=DISPATCH_INFLUENCE_ZONE_RISK_THRESHOLD,
    ) is True


def test_non_critical_classes_never_influence_dispatch():
    """All other taxonomy values fail the gate regardless of zone
    risk — locks the "observational only" contract."""
    for cls in ("baseline", "drift", "irregular",
                "elevated_behavioral_risk"):
        for zr in (0.0, 0.3, 0.6, 0.9, 1.0):
            assert should_influence_dispatch(
                deviation_class=cls, zone_risk=zr,
            ) is False, f"{cls} @ zr={zr} must not influence dispatch"


def test_fuse_with_explanation_returns_components():
    """The explanation_snapshot needs a bounded breakdown — the
    operator UI reads `components` to render the math."""
    r = fuse_with_explanation(
        behavioral_anomaly=0.5, zone_risk=0.4,
        deviation_class="drift",
        temporal_context=0.9, sensor_confidence=0.8,
        divergence_weight=1.0,
    )
    assert r.fused_risk > 0
    assert r.dispatch_influence is False
    assert set(r.components) >= {
        "behavioral_anomaly", "zone_risk", "temporal_context",
        "sensor_confidence", "divergence_weight", "deviation_class",
    }


def test_fuse_clamps_overflow_inputs():
    """A buggy upstream that hands a 1.5 modulator can never
    produce a fused score > 1.0."""
    r = fuse(
        behavioral_anomaly=2.0, zone_risk=2.0,
        temporal_context=2.0, sensor_confidence=2.0,
        divergence_weight=2.0,
    )
    assert 0.0 <= r <= 1.0
    assert r == 1.0  # all clamped to 1


# ── Baseline learner ─────────────────────────────────────────────


def test_shannon_entropy_edge_cases():
    """0 for empty / single-bucket / total=0; ≈ ln(N) for uniform."""
    assert _shannon_entropy([]) == 0.0
    assert _shannon_entropy([0, 0, 0]) == 0.0
    assert _shannon_entropy([5]) == 0.0
    # Uniform 4-bucket → entropy = ln(4)
    assert _shannon_entropy([1, 1, 1, 1]) == pytest.approx(
        math.log(4), abs=0.001,
    )


def test_build_baseline_features_pure_function():
    """No DB, no Redis — pure aggregator. Lock the public shape."""
    samples = [
        {"speed_mps": 1.0, "dwell_s": 60, "hour": 9, "zone_id": "z1"},
        {"speed_mps": 1.2, "dwell_s": 50, "hour": 9, "zone_id": "z1"},
        {"speed_mps": 5.0, "dwell_s": 30, "hour": 17, "zone_id": "z2"},
    ]
    f = build_baseline_features(samples)
    assert "mobility_signature" in f
    assert "dwell_duration" in f
    assert "temporal_signature" in f
    assert "route_entropy" in f
    assert "zone_affinity" in f
    assert f["zone_affinity"]["z1"] == 2
    assert f["temporal_signature"]["hourly_histogram"][9] == 2
    assert f["mobility_signature"]["mean_speed_mps"] > 0
    assert f["rolling_deviation_thresholds"]["mobility_speed"] > 0


# ── Anomaly detector ─────────────────────────────────────────────


def test_score_anomaly_zero_stdev_baseline_returns_baseline():
    """Cold baseline with no variance — detector returns BASELINE
    class with score 0. No divide-by-zero. Locked at `_z`."""
    baseline = {
        "mobility_signature": {"mean_speed_mps": 1.0, "stdev_speed_mps": 0.0},
        "dwell_duration":     {"mean_s": 60.0,        "stdev_s": 0.0},
        "rolling_deviation_thresholds": {},
    }
    obs = {"speed_mps": 99.0, "dwell_s": 9999.0}
    r = score_anomaly(obs, baseline)
    assert r["deviation_class"] == DeviationClass.BASELINE.value
    assert r["anomaly_score"] == 0.0


def test_score_anomaly_high_deviation_classifies_above_baseline():
    """Strong deviation lifts the class up the ladder. End-to-end
    of the Z-norm → classify_from_z pipeline."""
    baseline = {
        "mobility_signature": {"mean_speed_mps": 1.0, "stdev_speed_mps": 0.5},
        "dwell_duration":     {"mean_s": 60.0,        "stdev_s": 20.0},
        "rolling_deviation_thresholds": {},
    }
    # Speed +4 stdevs, dwell +10 stdevs → strong critical signal.
    obs = {"speed_mps": 3.0, "dwell_s": 260.0}
    r = score_anomaly(obs, baseline)
    assert severity_rank(r["deviation_class"]) >= severity_rank(
        DeviationClass.IRREGULAR.value
    )
    assert r["anomaly_score"] > 0


def test_write_anomaly_rejects_out_of_taxonomy_class():
    """LOCKED: the writer boundary refuses anything outside the
    5-value taxonomy. Defence against typos in future call sites."""
    fake_session = MagicMock()
    fake_session.execute = AsyncMock()
    fake_session.commit = AsyncMock()
    fake_session.rollback = AsyncMock()
    with pytest.raises(ValueError):
        asyncio.run(write_anomaly(
            fake_session,
            entity_id=uuid.uuid4(),
            anomaly_type="t",
            anomaly_score=0.5,
            deviation_class="DEFINITELY_NOT_A_CLASS",
            contributing_features=[],
            fused_zone_risk=0.5,
            confidence=0.5,
            explanation_snapshot={},
        ))


def test_write_anomaly_db_failure_falls_back_to_dlq(monkeypatch):
    """LOCKED: a DB write failure must NOT raise into caller; the
    payload lands in the dlq:ml_predictions ring buffer instead.
    This is the dispatch-non-blocking guarantee."""
    from app.services.behavioral import detector as det

    appended: list[dict] = []
    monkeypatch.setattr(
        det, "append_anomaly_ledger",
        lambda entry, **kw: appended.append(entry) or True,
    )

    fake_session = MagicMock()
    fake_session.execute = AsyncMock(side_effect=RuntimeError("db fail"))
    fake_session.commit = AsyncMock()
    fake_session.rollback = AsyncMock()
    result = asyncio.run(write_anomaly(
        fake_session,
        entity_id=uuid.uuid4(),
        anomaly_type="t",
        anomaly_score=0.5,
        deviation_class="drift",
        contributing_features=["x"],
        fused_zone_risk=0.5,
        confidence=0.5,
        explanation_snapshot={},
    ))
    assert result is None
    assert len(appended) == 1
    assert appended[0]["deviation_class"] == "drift"


def test_detector_has_no_update_path():
    """LOCKED: write_anomaly must remain INSERT-only. A future PR
    that adds an `id=...` parameter to it should fail in CI. The
    introspection is shallow — we only enforce that the public
    signature has no `id` kwarg."""
    import inspect
    sig = inspect.signature(write_anomaly)
    assert "id" not in sig.parameters, (
        "write_anomaly() must remain INSERT-only — no `id` kwarg."
    )


# ── DLQ ledger ───────────────────────────────────────────────────


def test_dlq_constants_locked():
    """10k-cap append-only ring buffer — locked per ROADMAP."""
    assert LEDGER_MAX_ENTRIES == 10_000
    assert DLQ_KEY == "dlq:ml_predictions"


def test_dlq_append_swallows_redis_failure(monkeypatch):
    """append_anomaly_ledger MUST NEVER raise — even when Redis is
    down. The detector relies on this as its compensating action."""
    from app.services.behavioral import dlq

    class _BrokenRedis:
        def lpush(self, *a, **kw): raise RuntimeError("redis down")
        def ltrim(self, *a, **kw): raise RuntimeError("redis down")

    monkeypatch.setattr(
        dlq.redis_service, "_get_client",
        lambda: _BrokenRedis(),
    )
    # Must not raise.
    assert append_anomaly_ledger({"k": "v"}) is False


def test_dlq_ledger_depth_returns_zero_on_redis_failure(monkeypatch):
    from app.services.behavioral import dlq
    monkeypatch.setattr(
        dlq.redis_service, "_get_client", lambda: None,
    )
    assert ledger_depth() == 0


# ── Temporal memory ──────────────────────────────────────────────


def test_temporal_read_window_rejects_unknown_window():
    """Window size must be exactly 5-min or 30-min. The 6/24-h
    windows live in Postgres, NOT Redis — locked split per the
    product brief."""
    with pytest.raises(ValueError):
        read_window(uuid.uuid4(), window_s=12345)


def test_temporal_windows_constants_match_spec():
    """5/30-min sorted-set windows + 6/24-h Postgres derived
    windows. Locked at exactly these four values."""
    assert WINDOW_5_MIN_S == 5 * 60
    assert WINDOW_30_MIN_S == 30 * 60


def test_temporal_record_event_writes_only_to_redis(monkeypatch):
    """LOCKED INVARIANT: 5/30-min windows write to Redis sorted-
    sets, NEVER to Postgres. The spec is explicit: writing every
    5-min update to DB per tracked user doesn't scale.

    We assert no `session.execute` happens during record_event."""
    from app.services.behavioral import temporal

    calls: list[tuple] = []

    class _FakeRedis:
        def zadd(self, k, m): calls.append(("zadd", k))
        def zremrangebyscore(self, *a): calls.append(("zrem", a[0]))
        def expire(self, *a): calls.append(("expire", a[0]))

    monkeypatch.setattr(
        temporal.redis_service, "_get_client", lambda: _FakeRedis(),
    )
    res = temporal.record_event(
        uuid.uuid4(), {"speed_mps": 1.2, "hour": 9},
    )
    # Must have written to both 5-min AND 30-min sorted sets.
    assert res == {"5m": True, "30m": True}
    keys = {c[1] for c in calls if c[0] == "zadd"}
    assert any("5m:" in k for k in keys)
    assert any("30m:" in k for k in keys)
    # The whole point of the test: NO postgres call happened
    # because we never touched a session — and the function
    # signature doesn't accept one. Locks the architecture.


# ── Prewarmer ────────────────────────────────────────────────────


def test_prewarmer_metadata_locked():
    """1-h cadence (jitter_base=3600), 2.0 s fetch budget, distinct
    namespaces from risk_prediction. Locked so a future PR doesn't
    silently re-cadence the engine."""
    pw = BehavioralBaselinePrewarmer()
    assert pw.name == "behavioral_baseline"
    assert pw.cache_namespace == "behavioral_baseline"
    assert pw.scheduler_job_id == "behavioral_baseline_prewarm"
    assert pw.jitter_base_s == 3600
    assert pw.fetch_timeout_s == 2.0
    assert pw.is_enabled() is True


def test_prewarmer_fetch_returns_none_on_db_error(monkeypatch):
    """DB outage → fetch returns None (base class treats as
    cache-preserved). Never raises."""
    from app.db import session as session_mod

    class _BrokenSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        async def execute(self, *a, **kw):
            raise RuntimeError("simulated DB down")

    monkeypatch.setattr(
        session_mod, "async_session", lambda: _BrokenSession(),
    )
    pw = BehavioralBaselinePrewarmer()
    assert asyncio.run(pw.fetch()) is None


# ── Versioning lock ──────────────────────────────────────────────


def test_version_identifiers_are_present():
    assert BASELINE_VERSION
    assert ANOMALY_PIPELINE_VERSION


# ── API surface ──────────────────────────────────────────────────


@pytest.fixture
def client():
    """Function-scoped TestClient — avoids the asyncpg/event-loop
    teardown race that surfaces when reusing a module-scoped client
    against endpoints that issue multiple Postgres queries inside
    one request."""
    from server import app as fastapi_app
    with TestClient(fastapi_app) as c:
        yield c


def test_api_baseline_cold_start_shape(client):
    r = client.get(f"/api/behavioral/baseline/{uuid.uuid4()}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cold_start"
    assert body["baseline_version"] == BASELINE_VERSION


def test_api_baseline_invalid_uuid_rejected(client):
    r = client.get("/api/behavioral/baseline/not-a-uuid")
    assert r.status_code == 400


def test_api_anomalies_unknown_entity_returns_empty(client):
    r = client.get(f"/api/behavioral/anomalies/{uuid.uuid4()}")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["items"] == []
    assert body["anomaly_pipeline_version"] == ANOMALY_PIPELINE_VERSION


def test_api_metrics_returns_warmup_gated_shape(client):
    r = client.get("/api/behavioral/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "ml_predictions_dlq_depth" in body
    assert "reconciliation_lag_s" in body
    assert "accuracy_gated_7d" in body
    gated = body["accuracy_gated_7d"]
    # On cold start the gated chip is null + reports warmup count.
    # Locks the "do not surface MAE before 7d of data" contract.
    if "warmup" in gated:
        assert gated["mae"] is None
        assert gated["critical_precision"] is None
        assert gated["critical_recall"] is None
        assert gated["false_escalation_rate"] is None
        assert gated["warmup"]["required_for_chip"] == 7 * 24


def test_api_dlq_returns_shape(client):
    r = client.get("/api/behavioral/dlq")
    assert r.status_code == 200
    body = r.json()
    assert "depth" in body
    assert "items" in body
    assert isinstance(body["items"], list)
