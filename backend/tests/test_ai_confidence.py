"""OCE-01 — Tests for the AI confidence composer.

Pure unit tests over the composition helpers — no DB / Redis required.
The endpoint-level RBAC + cache behaviour is exercised by the live
smoke (see CHANGELOG "OCE-01"); these tests pin the math and the
explanation copy so a refactor can't silently regress them.
"""
import pytest

from app.api.ai_confidence import (
    _weighted_overall,
    _build_explanation,
    W_TWIN, W_TELEMETRY, W_BEHAVIOURAL, W_ATTENUATION,
)


# ── Weighted overall ──────────────────────────────────────────────


def test_weights_sum_to_one():
    """Catches accidental drift if someone bumps a single weight without recalibrating."""
    total = W_TWIN + W_TELEMETRY + W_BEHAVIOURAL + W_ATTENUATION
    assert abs(total - 1.0) < 1e-6, f"weights must sum to 1.0, got {total}"


def test_overall_all_zeros():
    assert _weighted_overall(0.0, 0.0, 0.0, 0.0) == 0.0


def test_overall_all_ones():
    assert _weighted_overall(1.0, 1.0, 1.0, 1.0) == 1.0


def test_overall_matches_hand_computation():
    """0.30*0.8 + 0.30*0.6 + 0.25*0.7 + 0.15*0.9 = 0.24 + 0.18 + 0.175 + 0.135 = 0.730"""
    out = _weighted_overall(0.8, 0.6, 0.7, 0.9)
    assert out == 0.73


def test_overall_clamps_to_unit_interval():
    """Inputs outside [0,1] (e.g. a math bug elsewhere) shouldn't break the contract."""
    assert _weighted_overall(2.0, 2.0, 2.0, 2.0) == 1.0
    assert _weighted_overall(-1.0, -1.0, -1.0, -1.0) == 0.0


def test_no_twin_baseline_baseline_floor():
    """A user with no data at all gets 0 twin + 0 telemetry + 0.5 behav (default) + 1.0 att.
    Expected: 0.30*0 + 0.30*0 + 0.25*0.5 + 0.15*1.0 = 0.125 + 0.15 = 0.275.
    """
    out = _weighted_overall(0.0, 0.0, 0.5, 1.0)
    assert out == 0.275  # matches the live smoke observation


# ── Explanation array ──────────────────────────────────────────────


def _meta(**kw):
    """Build a meta dict with sensible defaults so each test only
    overrides what it cares about."""
    return {
        "n_twins": 0,
        "n_devices_with_baseline": 0,
        "source": "no_data",
        "verdicts": 0,
    } | kw


def test_explanation_min_three_max_five():
    """Contract: 3..5 strings, no fewer no more."""
    out = _build_explanation(
        0.0, _meta(n_twins=0),
        0.0, _meta(n_devices_with_baseline=0),
        0.5, _meta(source="no_data"),
        1.0, _meta(verdicts=0),
        0.275,
    )
    assert 3 <= len(out) <= 5


def test_explanation_high_overall_headline():
    out = _build_explanation(
        0.85, _meta(n_twins=2),
        0.92, _meta(n_devices_with_baseline=2, hours_filled_avg=22.1),
        0.85, _meta(source="safety_events_24h", risk_score=0.15),
        0.95, _meta(verdicts=12),
        0.88,
    )
    # The last string is the overall headline
    assert "high" in out[-1].lower()
    assert "0.88" in out[-1]


def test_explanation_low_overall_headline():
    out = _build_explanation(
        0.1, _meta(n_twins=1),
        0.2, _meta(n_devices_with_baseline=1, hours_filled_avg=4.0),
        0.3, _meta(source="safety_events_24h", risk_score=0.7),
        0.6, _meta(verdicts=4),
        0.27,
    )
    last = out[-1].lower()
    assert "very low" in last or "low" in last


def test_explanation_no_twin_says_so():
    out = _build_explanation(
        0.0, _meta(n_twins=0),
        0.5, _meta(n_devices_with_baseline=1, hours_filled_avg=12),
        0.5, _meta(source="no_data"),
        1.0, _meta(verdicts=0),
        0.275,
    )
    assert any("twin not built" in s.lower() or "not built" in s.lower() for s in out)


def test_explanation_no_baseline_says_so():
    out = _build_explanation(
        0.7, _meta(n_twins=1),
        0.0, _meta(n_devices_with_baseline=0),
        0.5, _meta(source="no_data"),
        1.0, _meta(verdicts=0),
        0.50,
    )
    assert any("0%" in s or "no behavioural baseline" in s.lower() for s in out)


def test_explanation_strong_deviation_warns():
    out = _build_explanation(
        0.7, _meta(n_twins=1),
        0.8, _meta(n_devices_with_baseline=1, hours_filled_avg=19),
        0.1, _meta(source="safety_events_24h", risk_score=0.9),
        1.0, _meta(verdicts=0),
        0.6,
    )
    matched = [s for s in out if "strongly off" in s.lower() or "review recent activity" in s.lower()]
    assert matched, f"expected 'strongly off' warning, got {out}"


def test_explanation_attenuation_only_shown_when_verdicts_exist():
    """Zero-verdicts users shouldn't get a noisy attenuation line."""
    out = _build_explanation(
        0.7, _meta(n_twins=1),
        0.7, _meta(n_devices_with_baseline=1, hours_filled_avg=18),
        0.8, _meta(source="safety_events_24h", risk_score=0.2),
        1.0, _meta(verdicts=0),
        0.74,
    )
    assert not any("verdicts" in s.lower() or "attenuation" in s.lower() or "feedback" in s.lower() for s in out)


def test_explanation_attenuation_strong_dampening_warns():
    out = _build_explanation(
        0.7, _meta(n_twins=1),
        0.7, _meta(n_devices_with_baseline=1, hours_filled_avg=18),
        0.8, _meta(source="safety_events_24h", risk_score=0.2),
        0.6, _meta(verdicts=20),
        0.69,
    )
    assert any("strongly dampens" in s.lower() for s in out)
