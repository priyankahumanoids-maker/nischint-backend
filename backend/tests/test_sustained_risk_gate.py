"""
Unit tests for the Sustained-Risk Gate.

Validates the gate logic directly by exercising `_sustained_high_risk()` and
the `decide()` flow with a monkey-patched classifier so we control exactly
what action the gate sees. This is more robust than full-signal e2e tuning,
which depends on the current weights of every sub-engine.

Outcomes validated:
    1. First high-risk spike → TRIGGER_SOS downgraded to NOTIFY_GUARDIAN
    2. Two spikes inside the window → second one fires TRIGGER_SOS
    3. Stale history outside the window → still downgraded
    4. Ultra-high score + confidence → bypass gate
    5. `sustained_gate_applied` flag surfaced on decision
    6. SUSTAINED_MIN_COUNT=1 → gate disabled (bootstrap guardrail)
    7. Cross-user pollution does not satisfy the gate
    8. Non-SOS actions pass through untouched

Run:  pytest -q backend/tests/test_sustained_risk_gate.py
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from app.services import ai_brain_service as brain


# ── Fixtures & helpers ─────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_brain_state():
    brain._DECISION_LOG.clear()
    brain._USER_ADJUSTMENTS.clear()
    brain._USER_ADAPT_PROFILES.clear()
    brain._LAST_TRIGGER_AT.clear()
    yield
    brain._DECISION_LOG.clear()
    brain._USER_ADJUSTMENTS.clear()
    brain._USER_ADAPT_PROFILES.clear()
    brain._LAST_TRIGGER_AT.clear()


def _inject_past_decision(user_id: str, effective_score: float, seconds_ago: float = 5) -> None:
    """Put a synthetic past decision into the ring so the gate can see it."""
    ts = (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()
    brain._DECISION_LOG.append({
        "event_id": f"past_{user_id}_{seconds_ago}",
        "user_id": user_id,
        "effective_score": float(effective_score),
        "decided_at": ts,
    })


# ── 1. Core helper logic ────────────────────────────────────────────

def test_helper_false_when_no_history():
    assert brain._sustained_high_risk("u_empty") is False


def test_helper_true_when_prior_high_risk_in_window():
    _inject_past_decision("u_prior", 85, seconds_ago=10)
    assert brain._sustained_high_risk("u_prior") is True


def test_helper_false_when_prior_outside_window():
    _inject_past_decision(
        "u_stale", 90,
        seconds_ago=brain.SUSTAINED_WINDOW_SEC + 30,
    )
    assert brain._sustained_high_risk("u_stale") is False


def test_helper_false_when_prior_below_threshold():
    _inject_past_decision("u_low", brain.SUSTAINED_MIN_SCORE - 5, seconds_ago=10)
    assert brain._sustained_high_risk("u_low") is False


def test_helper_cross_user_pollution_ignored():
    _inject_past_decision("other_user", 95, seconds_ago=5)
    assert brain._sustained_high_risk("target_user") is False


def test_helper_true_when_min_count_is_one():
    """Bootstrap guardrail: SUSTAINED_MIN_COUNT=1 disables the gate."""
    with patch.object(brain, "SUSTAINED_MIN_COUNT", 1):
        assert brain._sustained_high_risk("whoever") is True


# ── 2. Full `decide()` flow — gate integration ──────────────────────

# Patch _classify so we control exactly what action reaches the gate,
# regardless of signal fusion weights. This isolates the gate behaviour.

def _patched_classify_critical(effective_score, user_type="adult", user_id=None):
    return ("CRITICAL", "TRIGGER_SOS", {"sos": 70, "alert": 50, "monitor": 30})


def _patched_classify_yellow(effective_score, user_type="adult", user_id=None):
    return ("YELLOW", "INCREASE_MONITORING", {"sos": 80, "alert": 60, "monitor": 35})


async def _run_decide(user_id, signals=None, classify_fn=_patched_classify_critical):
    with patch.object(brain, "_classify", side_effect=classify_fn):
        return await brain.decide(
            session=None,
            user_id=user_id,
            user_type="adult",
            signals=signals or {"time": {"hour": 14}},
            skip_behavior=True,
            auto_execute=False,
        )


def test_first_spike_downgrades_to_advisory():
    d = asyncio.run(_run_decide("u_first"))
    assert d["risk_level"] == "CRITICAL"            # honest risk reporting
    assert d["recommended_action"] == "NOTIFY_GUARDIAN"
    assert d["sustained_gate_applied"] is True
    assert d["original_action"] == "TRIGGER_SOS"


def test_two_consecutive_spikes_inside_window_fires_sos():
    """
    Simulates the second of two real high-risk events within the window.
    We inject the first as history (so it has the high effective_score
    regardless of the patched classifier), then call decide() as the second.
    """
    uid = "u_consec"
    # First spike already recorded with qualifying effective_score
    _inject_past_decision(uid, effective_score=85.0, seconds_ago=5)

    d = asyncio.run(_run_decide(uid))

    assert d["sustained_gate_applied"] is False
    assert d["recommended_action"] == "TRIGGER_SOS"
    assert d["risk_level"] == "CRITICAL"


def test_first_ever_spike_is_downgraded_even_without_history():
    """Companion to the test above — a fresh user's very first TRIGGER_SOS is held."""
    d = asyncio.run(_run_decide("u_brand_new"))
    assert d["sustained_gate_applied"] is True
    assert d["recommended_action"] == "NOTIFY_GUARDIAN"
    assert d["original_action"] == "TRIGGER_SOS"


def test_two_spikes_outside_window_still_blocked():
    """First spike was long ago → second one is still 'first real spike' → advisory."""
    uid = "u_far_apart"
    _inject_past_decision(uid, 85, seconds_ago=brain.SUSTAINED_WINDOW_SEC + 60)
    d = asyncio.run(_run_decide(uid))
    assert d["sustained_gate_applied"] is True
    assert d["recommended_action"] == "NOTIFY_GUARDIAN"


def test_ultra_crisis_bypasses_gate():
    """
    Decision where effective_score >= SUSTAINED_BYPASS_SCORE AND
    confidence >= SUSTAINED_BYPASS_CONF should fire SOS immediately
    even without prior history.
    """
    uid = "u_ultra"
    # Patch effective_score + confidence computation. Easiest: patch the whole
    # compute flow by overriding _classify AND directly injecting values via
    # a fake pipeline. Since effective_score and confidence are built inside
    # decide(), we patch the bypass constants low enough that any critical
    # decision satisfies them, then confirm the bypass flag ONLY fires there.
    with patch.object(brain, "SUSTAINED_BYPASS_SCORE", 0), \
         patch.object(brain, "SUSTAINED_BYPASS_CONF", 0.0):
        d = asyncio.run(_run_decide(uid))
    assert d["sustained_gate_applied"] is False, \
        "With zero bypass thresholds, every critical decision should skip gate"
    assert d["recommended_action"] == "TRIGGER_SOS"


def test_non_sos_actions_pass_through_unchanged():
    """YELLOW / INCREASE_MONITORING decisions must ignore the gate entirely."""
    d = asyncio.run(_run_decide("u_yellow", classify_fn=_patched_classify_yellow))
    assert d["recommended_action"] == "INCREASE_MONITORING"
    assert d["sustained_gate_applied"] is False
    assert d["risk_level"] == "YELLOW"


def test_gate_flag_always_present_on_decision():
    d = asyncio.run(_run_decide("u_any", classify_fn=_patched_classify_yellow))
    assert "sustained_gate_applied" in d
    assert d["sustained_gate_applied"] is False


def test_configured_constants_are_sensible():
    """Sanity check — prevents accidental misconfiguration."""
    assert brain.SUSTAINED_MIN_COUNT >= 1
    assert 0 < brain.SUSTAINED_MIN_SCORE <= 100
    assert brain.SUSTAINED_WINDOW_SEC > 0
    assert brain.SUSTAINED_BYPASS_SCORE >= brain.SUSTAINED_MIN_SCORE
    assert 0 < brain.SUSTAINED_BYPASS_CONF <= 1.0
