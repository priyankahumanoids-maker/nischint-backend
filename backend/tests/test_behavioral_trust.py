"""NISCH-011.1 — Operator Trust Calibration Layer ("Twin Trust Tile") tests.

Locks the trust-decision matrix + operator reason-code taxonomy +
fail-safe behavior. Strict invariants:

  1. Divergence dampens trust — never elevates it.
  2. Telemetry gaps default to MEDIUM_TRUST, never LOW.
  3. MAE-derived signals are warmup-gated at 168 reconciled predictions.
  4. Trust state is deterministic across identical inputs.
  5. Dispatch is unaffected by trust state — the gate function in
     fusion.py never reads any trust signal.
  6. DLQ fallback path is exercised end-to-end (Redis-failure case).
  7. Reason-code taxonomy is locked at the enum boundary.

  These invariants are non-negotiable per the locked product brief.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.services.behavioral.fusion import should_influence_dispatch
from app.services.behavioral.trust import (
    ALLOWED_REASON_CODES,
    DIVERGENCE_HIGH_OK,
    DIVERGENCE_MEDIUM_RED,
    MAE_WARMUP_RECONCILED,
    ReasonCode,
    TrendDirection,
    TrustLevel,
    derive_trend,
    evaluate_trust,
)


# ── Helper for the all-healthy warm baseline input set ───────────


def _healthy_warm() -> dict:
    """A canonical 'everything healthy and warmed up' input set —
    used as the floor for tests that mutate one signal at a time."""
    return dict(
        divergence_index=0.05,
        reconciliation_lag_s=120.0,
        reconciled_predictions=MAE_WARMUP_RECONCILED * 2,
        critical_precision=0.85,
        false_escalation_rate=0.02,
        dlq_depth=0,
        unresolved_count=0,
    )


# ── Reason-code taxonomy lock ────────────────────────────────────


def test_reason_code_taxonomy_is_locked():
    """The 10-value enum is the operator-facing contract. A future
    PR that silently adds or removes a code surfaces in CI."""
    assert ALLOWED_REASON_CODES == frozenset({
        "all_healthy",
        "divergence_elevated",
        "insufficient_reconciliation_window",
        "delayed_ledger_convergence",
        "dlq_fallback_spike",
        "prediction_precision_degraded",
        "false_escalation_spike",
        "unresolved_backlog",
        "telemetry_unavailable",
        "motion_telemetry_stale",
    })


# ── Deterministic high-trust path ────────────────────────────────


def test_all_healthy_inputs_yield_high_trust():
    """The canonical happy path — every signal in its HIGH band
    AND warmup satisfied → HIGH_TRUST + all_healthy reason."""
    r = evaluate_trust(**_healthy_warm())
    assert r.level == TrustLevel.HIGH.value
    assert r.reason_codes == [ReasonCode.ALL_HEALTHY.value]
    assert r.warmup_satisfied is True


def test_trust_state_is_deterministic():
    """Same inputs → same output, every call. Pure-function
    contract enforced for replay + audit."""
    inputs = _healthy_warm()
    a = evaluate_trust(**inputs)
    b = evaluate_trust(**inputs)
    assert a.level == b.level
    assert a.reason_codes == b.reason_codes


# ── LOCKED INVARIANT 1: divergence cannot elevate trust ──────────


def test_divergence_cannot_elevate_trust():
    """LOCKED: forecast divergence may DROP trust (HIGH→MEDIUM→LOW)
    but NEVER raise it. Exhaustively swept across the band."""
    healthy = _healthy_warm()

    # Sweep divergence from 0 → 1 and assert monotone non-increase
    # in severity (i.e. trust severity ≥ baseline at d=0).
    baseline = evaluate_trust(**{**healthy, "divergence_index": 0.0})
    sev = {TrustLevel.HIGH.value: 0,
           TrustLevel.MEDIUM.value: 1,
           TrustLevel.LOW.value: 2}
    base_sev = sev[baseline.level]

    for d in (0.05, 0.19, 0.20, 0.35, 0.49, 0.50, 0.75, 1.0):
        r = evaluate_trust(**{**healthy, "divergence_index": d})
        assert sev[r.level] >= base_sev, (
            f"divergence={d} produced level={r.level} which is "
            f"better than baseline {baseline.level} — INVARIANT BREACH"
        )


def test_divergence_band_thresholds():
    """Locks the exact band edges. A future tuning change must
    update this test alongside `trust.py` constants."""
    healthy = _healthy_warm()
    # Just-below MEDIUM-OK boundary → still HIGH.
    r = evaluate_trust(**{**healthy,
                           "divergence_index": DIVERGENCE_HIGH_OK - 0.01})
    assert r.level == TrustLevel.HIGH.value
    # At the MEDIUM-OK boundary → MEDIUM (red flag fires here).
    r = evaluate_trust(**{**healthy,
                           "divergence_index": DIVERGENCE_HIGH_OK})
    assert r.level == TrustLevel.MEDIUM.value
    # At the LOW boundary → LOW.
    r = evaluate_trust(**{**healthy,
                           "divergence_index": DIVERGENCE_MEDIUM_RED})
    assert r.level == TrustLevel.LOW.value


# ── LOCKED INVARIANT 2: telemetry gaps default to MEDIUM ─────────


def test_all_telemetry_unavailable_defaults_to_medium_trust():
    """Every non-warmup input None → MEDIUM_TRUST, never LOW.
    Same idiom as the alert-pipeline non-blocking guarantee:
    missing data is not a red flag."""
    r = evaluate_trust(
        divergence_index=None,
        reconciliation_lag_s=None,
        reconciled_predictions=None,
        critical_precision=None,
        false_escalation_rate=None,
        dlq_depth=None,
        unresolved_count=None,
    )
    assert r.level == TrustLevel.MEDIUM.value
    assert r.reason_codes == [ReasonCode.TELEMETRY_UNAVAILABLE.value]


def test_partial_telemetry_gap_does_not_force_low_trust():
    """If SOME signals arrive healthy and the rest are missing,
    the verdict must reflect what was received (HIGH or MEDIUM)
    — never LOW just because of gaps."""
    r = evaluate_trust(
        divergence_index=0.05,
        reconciliation_lag_s=60.0,
        reconciled_predictions=None,   # MAE block treated as unavailable
        critical_precision=None,
        false_escalation_rate=None,
        dlq_depth=0,
        unresolved_count=0,
    )
    # Warmup not satisfied (count is None) → MEDIUM, never LOW.
    assert r.level == TrustLevel.MEDIUM.value
    assert ReasonCode.INSUFFICIENT_RECONCILIATION_WINDOW.value in r.reason_codes


# ── LOCKED INVARIANT 3: warmup gate ──────────────────────────────


def test_warmup_gate_enforced_before_mae_exposure():
    """Below 168 reconciled predictions, even a HORRIBLE precision
    must NOT push trust to LOW — the MAE block is treated as
    unavailable until the warmup ledger fills. Pinned MEDIUM."""
    r = evaluate_trust(
        divergence_index=0.05,
        reconciliation_lag_s=60.0,
        reconciled_predictions=MAE_WARMUP_RECONCILED - 1,
        critical_precision=0.01,     # would be LOW if gate didn't fire
        false_escalation_rate=0.99,  # would be LOW if gate didn't fire
        dlq_depth=0,
        unresolved_count=0,
    )
    # MAE block is gated out — precision/false-escalation IGNORED.
    # The remaining inputs are all healthy, so we land on MEDIUM
    # purely from the warmup gate, NEVER LOW.
    assert r.level == TrustLevel.MEDIUM.value
    assert ReasonCode.INSUFFICIENT_RECONCILIATION_WINDOW.value in r.reason_codes
    assert ReasonCode.PREDICTION_PRECISION_DEGRADED.value not in r.reason_codes
    assert ReasonCode.FALSE_ESCALATION_SPIKE.value not in r.reason_codes


def test_warmup_satisfied_exposes_mae_signals():
    """Above the warmup gate, bad precision/false-escalation MUST
    propagate to LOW_TRUST. The gate IS only a delay; it doesn't
    suppress findings permanently."""
    r = evaluate_trust(
        divergence_index=0.05,
        reconciliation_lag_s=60.0,
        reconciled_predictions=MAE_WARMUP_RECONCILED,
        critical_precision=0.01,
        false_escalation_rate=0.5,
        dlq_depth=0,
        unresolved_count=0,
    )
    assert r.level == TrustLevel.LOW.value
    assert ReasonCode.PREDICTION_PRECISION_DEGRADED.value in r.reason_codes
    assert ReasonCode.FALSE_ESCALATION_SPIKE.value in r.reason_codes


# ── Individual red-flag inputs ───────────────────────────────────


def test_recon_lag_above_4h_yields_low_trust():
    r = evaluate_trust(**{**_healthy_warm(),
                           "reconciliation_lag_s": 5 * 3600})
    assert r.level == TrustLevel.LOW.value
    assert ReasonCode.DELAYED_LEDGER_CONVERGENCE.value in r.reason_codes


def test_recon_lag_between_1h_and_4h_yields_medium_trust():
    r = evaluate_trust(**{**_healthy_warm(),
                           "reconciliation_lag_s": 2 * 3600})
    assert r.level == TrustLevel.MEDIUM.value
    assert ReasonCode.DELAYED_LEDGER_CONVERGENCE.value in r.reason_codes


def test_dlq_spike_yields_low_trust():
    r = evaluate_trust(**{**_healthy_warm(), "dlq_depth": 600})
    assert r.level == TrustLevel.LOW.value
    assert ReasonCode.DLQ_FALLBACK_SPIKE.value in r.reason_codes


def test_unresolved_backlog_yields_low_trust():
    r = evaluate_trust(**{**_healthy_warm(), "unresolved_count": 600})
    assert r.level == TrustLevel.LOW.value
    assert ReasonCode.UNRESOLVED_BACKLOG.value in r.reason_codes


def test_low_precision_yields_low_trust():
    r = evaluate_trust(**{**_healthy_warm(), "critical_precision": 0.30})
    assert r.level == TrustLevel.LOW.value
    assert ReasonCode.PREDICTION_PRECISION_DEGRADED.value in r.reason_codes


def test_false_escalation_spike_yields_low_trust():
    r = evaluate_trust(**{**_healthy_warm(), "false_escalation_rate": 0.40})
    assert r.level == TrustLevel.LOW.value
    assert ReasonCode.FALSE_ESCALATION_SPIKE.value in r.reason_codes


# ── Precedence: worst red flag wins ──────────────────────────────


def test_worst_red_flag_wins():
    """LOW > MEDIUM > HIGH precedence — multiple red flags resolve
    to the WORST one. Locked at `_worse_of`."""
    r = evaluate_trust(**{**_healthy_warm(),
                           "divergence_index": 0.25,        # MEDIUM
                           "reconciliation_lag_s": 5 * 3600})  # LOW
    assert r.level == TrustLevel.LOW.value


# ── Reason-code dedup ────────────────────────────────────────────


def test_reason_codes_deduped():
    """Divergence elevated AND lag elevated SHOULD NOT report
    `divergence_elevated` twice — dedup is locked at evaluator
    exit."""
    r = evaluate_trust(**{**_healthy_warm(),
                           "divergence_index": 0.25,
                           "reconciliation_lag_s": 5 * 3600})
    assert len(set(r.reason_codes)) == len(r.reason_codes)


# ── Trend derivation ─────────────────────────────────────────────


def test_trend_improving_when_severity_drops():
    """HIGH from previous LOW → improving."""
    assert derive_trend(
        current_level=TrustLevel.HIGH.value,
        previous_level=TrustLevel.LOW.value,
    ) == TrendDirection.IMPROVING.value


def test_trend_degrading_when_severity_rises():
    """LOW from previous HIGH → degrading."""
    assert derive_trend(
        current_level=TrustLevel.LOW.value,
        previous_level=TrustLevel.HIGH.value,
    ) == TrendDirection.DEGRADING.value


def test_trend_stable_when_unchanged():
    for lvl in (TrustLevel.HIGH.value, TrustLevel.MEDIUM.value,
                TrustLevel.LOW.value):
        assert derive_trend(current_level=lvl, previous_level=lvl) \
            == TrendDirection.STABLE.value


def test_trend_stable_when_previous_missing():
    """No cached previous level (e.g. Redis down, first-ever call)
    → stable, NOT degrading. Fail-safe contract."""
    assert derive_trend(
        current_level=TrustLevel.LOW.value, previous_level=None,
    ) == TrendDirection.STABLE.value
    assert derive_trend(
        current_level=TrustLevel.LOW.value, previous_level="bogus",
    ) == TrendDirection.STABLE.value


# ── LOCKED INVARIANT: dispatch unaffected by trust tile ──────────


def test_dispatch_unaffected_by_trust_tile():
    """LOCKED: the dispatch-influence gate function in fusion.py
    must NOT read any trust signal. Even a LOW_TRUST verdict can
    NEVER change the dispatch decision — that's the entire point
    of the observability-only contract."""
    # The gate function's signature accepts only (deviation_class,
    # zone_risk, threshold). It has no trust parameter.
    import inspect
    sig = inspect.signature(should_influence_dispatch)
    assert "trust_level" not in sig.parameters
    assert "trust" not in sig.parameters
    # Same as before: critical + corroborating risk → True; else False.
    # A LOW_TRUST verdict from the tile is invisible to dispatch.
    assert should_influence_dispatch(
        deviation_class="critical_behavioral_shift",
        zone_risk=0.7,
    ) is True
    assert should_influence_dispatch(
        deviation_class="critical_behavioral_shift",
        zone_risk=0.3,
    ) is False


# ── LOCKED INVARIANT: trust failure cannot affect dispatch ───────


def test_trust_endpoint_failure_does_not_propagate_to_dispatch():
    """Even if the trust endpoint blew up, dispatch would proceed
    unchanged — the trust module is not imported from
    safety_incident_engine or alert_trigger. Inspection-level
    proof + locked at CI."""
    import importlib
    sie = importlib.import_module("app.services.safety_incident_engine")
    at = importlib.import_module("app.services.alert_trigger")
    # The trust module must be invisible to both critical-path
    # modules — observability isolation.
    sie_source = open(sie.__file__).read()
    at_source = open(at.__file__).read()
    assert "behavioral.trust" not in sie_source
    assert "behavioral.trust" not in at_source


# ── DLQ fallback path ────────────────────────────────────────────


def test_dlq_signal_in_trust_evaluator_when_redis_unavailable(monkeypatch):
    """When the DLQ Redis is unavailable, `ledger_depth()` returns
    0 — the evaluator sees a healthy DLQ signal. Locks the
    end-to-end fail-safe: DLQ unavailability never trips LOW_TRUST."""
    from app.services.behavioral import dlq as dlq_mod
    monkeypatch.setattr(dlq_mod.redis_service, "_get_client",
                        lambda: None)
    assert dlq_mod.ledger_depth() == 0
    # Plug into evaluator — the rest of the signals are healthy and
    # warmed → HIGH_TRUST.
    r = evaluate_trust(**{**_healthy_warm(),
                           "dlq_depth": dlq_mod.ledger_depth()})
    assert r.level == TrustLevel.HIGH.value


# ── API surface ──────────────────────────────────────────────────


@pytest.fixture
def client():
    """Function-scoped TestClient — avoids the asyncpg/event-loop
    teardown race that surfaces with module-scoped sessions."""
    from server import app as fastapi_app
    with TestClient(fastapi_app) as c:
        yield c


def test_api_trust_returns_stable_shape(client):
    """The trust endpoint must always return 200 with the locked
    field set — even on a fresh DB. The cold-start path lands on
    MEDIUM_TRUST with `insufficient_reconciliation_window`."""
    r = client.get("/api/behavioral/trust")
    assert r.status_code == 200
    body = r.json()
    assert body["trust_level"] in {"HIGH_TRUST", "MEDIUM_TRUST", "LOW_TRUST"}
    assert body["trend"] in {"improving", "stable", "degrading"}
    assert isinstance(body["reason_codes"], list)
    assert len(body["reason_codes"]) >= 1
    # Every code must be in the locked taxonomy.
    for c in body["reason_codes"]:
        assert c in ALLOWED_REASON_CODES, f"unknown reason code: {c}"
    assert "anomaly_pipeline_version" in body
    assert "baseline_version" in body
    # Inputs block is the audit envelope — every field present
    # so the operator UI can render the breakdown without
    # branching on missing keys.
    for k in ("divergence_index", "reconciliation_lag_s",
              "reconciled_predictions", "critical_precision",
              "false_escalation_rate", "dlq_depth",
              "unresolved_count"):
        assert k in body["inputs"]


def test_api_trust_never_returns_low_on_fresh_db(client):
    """LOCKED: a freshly-deployed instance MUST NOT report
    LOW_TRUST. The worst it can report is MEDIUM (warmup gate)."""
    r = client.get("/api/behavioral/trust")
    assert r.status_code == 200
    body = r.json()
    assert body["trust_level"] != "LOW_TRUST"
