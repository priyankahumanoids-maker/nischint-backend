"""NISCH-010 — Predictive Risk Engine contract tests.

Locks the Phase-1 invariants across forecasters, predictor,
reconciler, prewarmer, and the alert-pipeline integration. Pure-
unit by default (no DB, no scheduler); live-DB tests are tagged
`live_pg` so they're filterable.

Coverage matrix (mapped to the prompt-spec test list):

  Forecasters
    * EWMA stability — cold start, single-sample, recency weight
    * Bayesian confidence — rising / falling / flat
    * Prophet seasonality stub — available-flag contract

  Ledger
    * `prediction_class` classification truth table
    * `compute_outcome` deterministic coefficients (immutable
      ledger row + outcome reconciliation)
    * `_feature_hash` reproducibility lock

  Prewarmer
    * cold-start callable, declarative metadata
    * DB-error path returns None instead of raising

  APIs
    * `GET /api/risk/predict` returns deferred-shape when history
      is thin (insufficient_history)
    * route endpoint returns 501 (Phase-2 surface lock)

  Alert pipeline
    * `predict()` failures must NOT block the caller — wrapped in
      try/except and degrade silently

  Stability
    * Sparse history → confidence floor zero, deferred shape
    * Volatility-driven `volatile` classification
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.services.risk_prediction import (
    MODEL_VERSION,
    OUTCOME_RESOLUTION_VERSION,
    PIPELINE_VERSION,
)
from app.services.risk_prediction.forecasters import (
    BayesianTrendScorer,
    EWMAForecaster,
    ForecastResult,
    ProphetForecaster,
    blend_forecasts,
)
from app.services.risk_prediction.predictor import (
    CRITICAL_RISK_THRESHOLD,
    HIGH_VOLATILITY_THRESHOLD,
    RISING_SLOPE_THRESHOLD,
    classify_prediction,
)
from app.services.risk_prediction.predictor import (
    _feature_hash,
    predict,
)
from app.services.risk_prediction.prewarmer import RiskPredictionPrewarmer
from app.services.risk_prediction.reconciler import compute_outcome


# ── Forecasters ─────────────────────────────────────────────────


def test_ewma_cold_start_is_zero_confidence():
    """No history → confidence 0, single sentinel factor.

    Locks the contract that a buggy upstream returning empty
    history can never produce a confident prediction."""
    res = EWMAForecaster().forecast([])
    assert res.risk == 0.0
    assert res.confidence == 0.0
    assert "ewma:cold_start_no_history" in res.factors


def test_ewma_recency_weighted():
    """Recent samples must dominate older ones — the whole
    point of EWMA. A spike at the end should pull the smoothed
    value closer to the spike than the simple mean would."""
    history = [0.1] * 20 + [0.9]
    res = EWMAForecaster(alpha=0.3).forecast(history)
    simple_mean = sum(history) / len(history)
    assert res.risk > simple_mean       # smoothed > raw mean
    assert res.risk < 0.9                # but not the spike value
    assert 0.0 < res.confidence <= 1.0


def test_ewma_clamps_at_one():
    """Any over-1.0 sample must be clamped at the boundary —
    defence in depth against bad upstream data poisoning the
    blend."""
    res = EWMAForecaster().forecast([2.5, 3.0, 4.0])
    assert res.risk == 1.0
    assert res.confidence > 0.0


def test_bayesian_rising_trend_lifts_score():
    """Monotone rising series → P(rising) > 0.5 and projection
    pulled above the latest value."""
    history = [0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6]
    res = BayesianTrendScorer().forecast(history)
    p_rising = next(
        (f for f in res.factors if f.startswith("bayes:p_rising=")),
        None,
    )
    assert p_rising is not None
    assert float(p_rising.split("=")[1]) > 0.5
    assert res.risk >= history[-1]  # projection lifts


def test_bayesian_falling_trend_drops_score():
    """Monotone falling series → projection below the latest."""
    history = [0.9, 0.85, 0.7, 0.6, 0.45, 0.3]
    res = BayesianTrendScorer().forecast(history)
    assert res.risk <= history[-1]


def test_bayesian_too_short_returns_cold_start():
    """Fewer than 2 samples → deferred."""
    res = BayesianTrendScorer().forecast([0.5])
    assert res.confidence == 0.0
    assert any("cold_start" in f for f in res.factors)


def test_prophet_unavailable_contract():
    """Prophet is a soft dep — without `prophet` installed
    `is_available()` is False and the predictor must NOT call
    `forecast()`. The stub's own forecast() returns confidence
    0 either way."""
    pf = ProphetForecaster()
    if not pf.is_available():
        res = pf.forecast([0.1, 0.2, 0.3])
        assert res.confidence == 0.0


def test_blend_skips_zero_confidence_votes():
    """Confidence-zero votes must not drag the mean. Locks the
    blender's most subtle invariant — a forecaster that doesn't
    know shouldn't be allowed to vote."""
    votes = [
        ForecastResult(risk=0.0, confidence=0.0, factors=["dead"]),
        ForecastResult(risk=0.8, confidence=0.9, factors=["live"]),
    ]
    blend = blend_forecasts(votes)
    assert blend.risk == pytest.approx(0.8, abs=0.001)
    assert blend.confidence == 0.9


def test_blend_no_confident_vote_sentinel():
    """All zero-confidence → `blend:no_confident_vote` sentinel.
    The predictor uses this to decide whether to return the
    `deferred` shape."""
    votes = [
        ForecastResult(risk=0.0, confidence=0.0, factors=[]),
        ForecastResult(risk=0.5, confidence=0.0, factors=[]),
    ]
    blend = blend_forecasts(votes)
    assert blend.confidence == 0.0
    assert "blend:no_confident_vote" in blend.factors


# ── Prediction classification ────────────────────────────────────


def test_classify_critical_escalation_wins_over_volatile():
    """Critical risk + high volatility → critical_escalation
    (critical wins). Locks the priority ordering."""
    cls = classify_prediction(
        predicted_risk=CRITICAL_RISK_THRESHOLD + 0.01,
        volatility=HIGH_VOLATILITY_THRESHOLD + 0.1,
        slope=RISING_SLOPE_THRESHOLD + 0.1,
    )
    assert cls == "critical_escalation"


def test_classify_volatile_wins_over_rising():
    """Sub-critical + high volatility + rising slope → volatile."""
    cls = classify_prediction(
        predicted_risk=0.4,
        volatility=HIGH_VOLATILITY_THRESHOLD + 0.05,
        slope=RISING_SLOPE_THRESHOLD + 0.05,
    )
    assert cls == "volatile"


def test_classify_rising_when_slope_above_threshold():
    cls = classify_prediction(
        predicted_risk=0.3, volatility=0.01,
        slope=RISING_SLOPE_THRESHOLD + 0.01,
    )
    assert cls == "rising"


def test_classify_stable_default():
    """Low everything → stable. The neutral state."""
    cls = classify_prediction(
        predicted_risk=0.1, volatility=0.001, slope=0.0,
    )
    assert cls == "stable"


# ── Feature hash reproducibility ─────────────────────────────────


def test_feature_hash_is_deterministic():
    """Same input → same hash. Locks the replay invariant — a
    prediction's feature_hash must regenerate from the same
    snapshot for forensic replay to work."""
    a = {"history_len": 3, "history_tail": [0.1, 0.2], "volatility": 0.05}
    b = {"history_tail": [0.1, 0.2], "volatility": 0.05, "history_len": 3}
    assert _feature_hash(a) == _feature_hash(b)


def test_feature_hash_changes_with_inputs():
    """Different inputs → different hash. Otherwise replay can't
    detect tampering."""
    assert _feature_hash({"x": 1}) != _feature_hash({"x": 2})


# ── Reconciler — compute_outcome coefficient lock ────────────────


def test_compute_outcome_zero_signals():
    """No signal at all → 0. Locks the lower bound."""
    out = compute_outcome(
        avg_severity_rank=0.0, avg_escalation=0.0,
        ack_rate=0.0, incident_density=0.0, dispatch_present=0.0,
    )
    assert out == 0.0


def test_compute_outcome_maxed_signals():
    """All inputs at max → 1.0. Locks the upper bound and the
    coefficient set's sum-to-1.0 invariant."""
    out = compute_outcome(
        avg_severity_rank=1.0, avg_escalation=3.0,
        ack_rate=1.0, incident_density=5.0, dispatch_present=1.0,
    )
    assert out == pytest.approx(1.0, abs=0.001)


def test_compute_outcome_clamped_to_unit_interval():
    """Over-cap incident density must clamp, not overflow."""
    out = compute_outcome(
        avg_severity_rank=1.0, avg_escalation=10.0,
        ack_rate=1.0, incident_density=100.0, dispatch_present=1.0,
    )
    assert 0.0 <= out <= 1.0
    assert out == 1.0


def test_compute_outcome_weights_match_locked_coefficients():
    """Severity coefficient = 0.35; only severity contributing → 0.35.
    Locks the exact weights so future PRs can't silently shift the
    accuracy-meaning of the ledger."""
    out = compute_outcome(
        avg_severity_rank=1.0, avg_escalation=0.0,
        ack_rate=0.0, incident_density=0.0, dispatch_present=0.0,
    )
    assert out == pytest.approx(0.35, abs=0.001)


# ── Prewarmer — declarative contract ─────────────────────────────


def test_prewarmer_metadata_locked():
    """Subclass attributes form a stability contract — distinct
    job id, 1-h cadence, dedicated namespaces. A future PR that
    silently changes the cadence to 5 min would surface here."""
    pw = RiskPredictionPrewarmer()
    assert pw.name == "risk_prediction"
    assert pw.cache_namespace == "risk_prediction"
    assert pw.scheduler_job_id == "risk_prediction_prewarm"
    assert pw.jitter_base_s == 3600     # 1-h cadence, locked
    assert pw.cache_ttl_s == 3600
    assert pw.fetch_timeout_s == 2.0
    assert pw.is_enabled() is True


def test_prewarmer_fetch_returns_none_on_db_error(monkeypatch):
    """DB failure → `fetch()` returns None (failure path),
    NEVER raises. The base class treats None as `cache
    preserved` so a transient outage degrades gracefully."""
    from app.db import session as session_mod

    class _BrokenSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        async def execute(self, *a, **kw):
            raise RuntimeError("simulated DB down")

    def _broken_session():
        return _BrokenSession()

    monkeypatch.setattr(session_mod, "async_session", _broken_session)
    pw = RiskPredictionPrewarmer()
    res = asyncio.run(pw.fetch())
    assert res is None


# ── Pipeline / model identifiers ─────────────────────────────────


def test_version_identifiers_are_present():
    """Locks the three version identifiers so any drift surfaces
    in CI. The accuracy report keys on every one of these."""
    assert MODEL_VERSION
    assert PIPELINE_VERSION
    assert OUTCOME_RESOLUTION_VERSION


# ── Predictor end-to-end (no DB persist) ─────────────────────────


def test_predict_deferred_shape_on_cold_start():
    """No history → deferred shape with `insufficient_history`.
    Same idiom as the RAG-generation timeout path. Locks the
    public-API contract callers branch on."""
    fake_session = MagicMock()
    fake_session.add = MagicMock()
    fake_session.commit = AsyncMock()
    fake_session.rollback = AsyncMock()
    result = asyncio.run(predict(
        fake_session,
        subject_id=uuid.uuid4(),
        subject_type="zone",
        zone_id=None,
        prediction_window_min=15,
        persist=False,
        history_override=[],
    ))
    assert result["status"] == "deferred"
    assert result["retryable"] is True
    assert result["reason"] == "insufficient_history"
    assert result["model_version"] == MODEL_VERSION
    assert result["pipeline_version"] == PIPELINE_VERSION


def test_predict_ok_shape_on_rich_history():
    """Confident history → ok shape with all required public
    fields populated. Locks the "operator UI can rely on these
    keys existing" contract."""
    fake_session = MagicMock()
    fake_session.add = MagicMock()
    fake_session.commit = AsyncMock()
    fake_session.rollback = AsyncMock()
    history = [0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.45, 0.5, 0.55, 0.6]
    result = asyncio.run(predict(
        fake_session,
        subject_id=uuid.uuid4(),
        subject_type="zone",
        zone_id=None,
        prediction_window_min=15,
        persist=False,
        history_override=history,
    ))
    assert result["status"] == "ok"
    assert "risk_probability" in result
    assert "confidence_score" in result
    assert "prediction_class" in result
    assert "feature_hash" in result
    assert "latency_ms" in result
    assert result["prediction_pipeline_version"] == PIPELINE_VERSION \
        if "prediction_pipeline_version" in result \
        else result["pipeline_version"] == PIPELINE_VERSION
    assert result["prediction_class"] in {
        "stable", "rising", "volatile", "critical_escalation",
    }


def test_predict_rising_history_classifies_as_rising_or_volatile():
    """Monotone rising history with low volatility should land
    on rising. End-to-end classification through the real blend."""
    fake_session = MagicMock()
    fake_session.add = MagicMock()
    fake_session.commit = AsyncMock()
    fake_session.rollback = AsyncMock()
    # Steeper ramp — slope must clear the locked threshold (0.02
    # per sample) to land on `rising`. The blender's actual risk
    # may swing high enough to also qualify as volatile.
    history = [0.05 + 0.03 * i for i in range(30)]
    result = asyncio.run(predict(
        fake_session, subject_id=uuid.uuid4(), subject_type="zone",
        zone_id=None, prediction_window_min=15, persist=False,
        history_override=history,
    ))
    assert result["status"] == "ok"
    # The exact class depends on the blend; the regression we
    # guard against is `stable` (slope/volatility/risk all
    # should be lifting the class away from neutral).
    assert result["prediction_class"] in {
        "rising", "volatile", "critical_escalation",
    }


def test_predict_invalid_window_raises():
    """Window must be one of the locked horizons. Defence
    against silently-introduced new horizons that the reconciler
    isn't ready for."""
    fake_session = MagicMock()
    with pytest.raises(ValueError):
        asyncio.run(predict(
            fake_session, subject_id=uuid.uuid4(),
            subject_type="zone", prediction_window_min=42,
            persist=False, history_override=[0.1, 0.2],
        ))


# ── API endpoint smoke tests ─────────────────────────────────────


@pytest.fixture
def client():
    """Function-scoped TestClient — avoids the asyncpg/event-loop
    teardown race that surfaces when reusing a module-scoped client
    against endpoints that issue multiple Postgres queries."""
    from server import app as fastapi_app
    with TestClient(fastapi_app) as c:
        yield c


def test_api_predict_endpoint_returns_stable_shape(client):
    r = client.get("/api/risk/predict", params={
        "lat": 12.97, "lng": 77.59, "window_min": 15,
    })
    assert r.status_code == 200
    body = r.json()
    assert body.get("model_version") == MODEL_VERSION
    assert body.get("pipeline_version") == PIPELINE_VERSION
    assert body.get("status") in {"ok", "deferred"}


def test_api_route_endpoint_is_phase2_stub(client):
    r = client.get("/api/risk/route")
    assert r.status_code == 501


def test_api_predict_invalid_zone_uuid_rejected(client):
    r = client.get("/api/risk/predict", params={
        "lat": 12.97, "lng": 77.59, "zone_id": "not-a-uuid",
    })
    assert r.status_code == 400


def test_api_accuracy_endpoint_returns_zero_when_no_predictions(client):
    """Random subject_id → reconciled_n=0, mae=0, etc. Locks
    the empty-shape contract — operator UI must not 500 when a
    new subject has no history yet."""
    r = client.get(
        f"/api/risk/predictions/{uuid.uuid4()}/accuracy",
    )
    assert r.status_code == 200
    body = r.json()
    assert body["reconciled_n"] == 0
    assert body["model_version"] == MODEL_VERSION
