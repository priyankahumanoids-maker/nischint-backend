"""
End-to-end test for the Confidence-Weighted Adaptive Feedback Loop.

Validates:
    1. true_positive / false_alarm / missed feedback are all accepted
    2. decision_confidence is captured into each feedback record
    3. _update_user_adjustment applies confidence-weighted step sizes
       — high-confidence wrongs drive BIGGER threshold shifts than low-confidence ones
    4. Missed feedback LOWERS threshold (more sensitive)
       False-alarm feedback RAISES threshold (less sensitive)
    5. get_user_adjustment exposes weighted rates alongside raw rates

Run:  pytest -q backend/tests/test_ai_brain_feedback_loop.py
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services import ai_brain_service as brain


def _inject_decision(uid: str, event_id: str, confidence: float, action: str = "NOTIFY_GUARDIAN"):
    """Push a fake decision into the log so we can feedback against it."""
    brain._DECISION_LOG.append({
        "event_id": event_id,
        "user_id": uid,
        "user_type": "adult",
        "risk_score": 55,
        "risk_level": "RED",
        "confidence": confidence,
        "recommended_action": action,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    })


@pytest.fixture(autouse=True)
def _reset_brain_state():
    # Snapshot & restore
    brain._DECISION_LOG.clear()
    brain._USER_ADJUSTMENTS.clear()
    brain._USER_ADAPT_PROFILES.clear()
    yield
    brain._DECISION_LOG.clear()
    brain._USER_ADJUSTMENTS.clear()
    brain._USER_ADAPT_PROFILES.clear()


def test_records_all_three_feedback_outcomes():
    uid = "user_basic"
    for i, outcome in enumerate(["true_positive", "false_alarm", "missed"]):
        eid = f"e_{i}"
        _inject_decision(uid, eid, confidence=0.6)
        res = brain.record_feedback(eid, outcome)
        assert res["status"] == "ok"
        assert res["feedback"]["outcome"] == outcome
        assert res["feedback"]["decision_confidence"] == 0.6


def test_high_confidence_false_alarm_raises_threshold_more():
    """
    High-confidence (0.9) false alarms should drive a BIGGER +adj than
    low-confidence (0.3) ones, even with the same count.
    """
    # Need ≥ _FEEDBACK_MIN_SAMPLE (5) feedbacks + fp_rate > 0.20
    uid_hi = "user_hi_conf"
    uid_lo = "user_lo_conf"

    # 5 feedbacks, all false_alarm, high confidence
    for i in range(5):
        _inject_decision(uid_hi, f"h_{i}", confidence=0.95)
        brain.record_feedback(f"h_{i}", "false_alarm")

    # 5 feedbacks, all false_alarm, low confidence
    for i in range(5):
        _inject_decision(uid_lo, f"l_{i}", confidence=0.30)
        brain.record_feedback(f"l_{i}", "false_alarm")

    adj_hi = brain._USER_ADJUSTMENTS[uid_hi]
    adj_lo = brain._USER_ADJUSTMENTS[uid_lo]

    assert adj_hi > 0, "Any false alarm over threshold should raise adj"
    assert adj_lo > 0
    assert adj_hi > adj_lo, (
        f"High-conf FA must drive bigger correction than low-conf. "
        f"hi={adj_hi} lo={adj_lo}"
    )


def test_missed_lowers_threshold_and_false_alarm_raises():
    """Direction invariant: missed → -adj; false_alarm → +adj."""
    uid_miss = "user_miss"
    uid_fa = "user_fa"

    # missed_rate needs > 0.10 weighted
    for i in range(5):
        _inject_decision(uid_miss, f"m_{i}", confidence=0.8)
        brain.record_feedback(f"m_{i}", "missed")

    for i in range(5):
        _inject_decision(uid_fa, f"f_{i}", confidence=0.8)
        brain.record_feedback(f"f_{i}", "false_alarm")

    assert brain._USER_ADJUSTMENTS[uid_miss] < 0
    assert brain._USER_ADJUSTMENTS[uid_fa] > 0


def test_true_positive_does_not_shift_threshold():
    uid = "user_tp"
    for i in range(5):
        _inject_decision(uid, f"t_{i}", confidence=0.9)
        brain.record_feedback(f"t_{i}", "true_positive")
    # No adjustment (all feedbacks positive)
    assert brain._USER_ADJUSTMENTS.get(uid, 0) == 0


def test_min_sample_gate_prevents_early_drift():
    """Fewer than _FEEDBACK_MIN_SAMPLE feedbacks → no adjustment."""
    uid = "user_sparse"
    for i in range(brain._FEEDBACK_MIN_SAMPLE - 1):
        _inject_decision(uid, f"s_{i}", confidence=0.9)
        brain.record_feedback(f"s_{i}", "false_alarm")
    assert brain._USER_ADJUSTMENTS.get(uid, 0) == 0


def test_get_user_adjustment_exposes_weighted_rates():
    uid = "user_diag"
    for i in range(5):
        _inject_decision(uid, f"d_{i}", confidence=0.4 if i < 2 else 0.9)
        brain.record_feedback(f"d_{i}", "false_alarm" if i < 3 else "true_positive")
    info = brain.get_user_adjustment(uid)
    assert info["feedback_count"] == 5
    assert info["false_alarm_count"] == 3
    assert info["true_positive_count"] == 2
    assert "false_positive_rate_weighted" in info
    assert info["false_positive_rate_weighted"] > 0
    # Weighted rate should differ from raw rate because confidences differ
    assert info["false_positive_rate_weighted"] != info["false_positive_rate"]


def test_adjustment_bounded():
    """Runaway protection — adjustment clipped to ±_USER_ADJUST_MAX."""
    uid = "user_runaway"
    # 30 high-conf false alarms → would blow past cap without bounds
    for i in range(30):
        _inject_decision(uid, f"r_{i}", confidence=0.99)
        brain.record_feedback(f"r_{i}", "false_alarm")
    assert brain._USER_ADJUSTMENTS[uid] <= brain._USER_ADJUST_MAX
    assert brain._USER_ADJUSTMENTS[uid] >= brain._USER_ADJUST_MIN


# ── V3: Smoothing, Decay, Personalization ──────────────────────────────

def test_smoothing_dampens_single_burst():
    """
    Smoothing: new = round(0.7 * old + 0.3 * target).
    A FIRST adaptation event should NOT push adjustment all the way to the target —
    it should land around 30% of the way there. Subsequent feedbacks converge slowly.
    """
    uid = "user_smooth"
    # 5 high-conf false alarms — the 5th trips min_sample=5 and fires ONE adaptation
    for i in range(5):
        _inject_decision(uid, f"sm_{i}", confidence=0.95)
        brain.record_feedback(f"sm_{i}", "false_alarm")
    adj_first = brain._USER_ADJUSTMENTS[uid]
    # target ≈ +7, smoothed from 0: round(0.7*0 + 0.3*7) = 2
    assert 1 <= adj_first <= 3, f"First adaptation should dampen to ~2, got {adj_first}"

    # One more feedback — adj should climb CLOSER to target but not jump:
    # round(0.7*2 + 0.3*7) = round(1.4 + 2.1) = 4
    _inject_decision(uid, "sm_5", confidence=0.95)
    brain.record_feedback("sm_5", "false_alarm")
    adj_second = brain._USER_ADJUSTMENTS[uid]
    assert adj_first < adj_second < 7, (
        f"Second step should climb but not reach target. "
        f"first={adj_first} second={adj_second} target=7"
    )


def test_time_decay_fades_old_adjustment():
    """
    Read-path: _current_adjustment applies exp(-days/30) to stored raw value.
    A 30-day-old +10 should decay to ~+4 (10 * e^-1 ≈ 3.68).
    """
    from datetime import datetime, timezone, timedelta

    uid = "user_stale"
    brain._USER_ADJUSTMENTS[uid] = 10
    old_iso = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    brain._USER_ADAPT_PROFILES[uid] = {"updated_at": old_iso}

    decayed = brain._current_adjustment(uid)
    assert 3 <= decayed <= 5, f"30d decay of 10 should ≈4, got {decayed}"

    # 60d → ~1.4 rounds to 1
    older_iso = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    brain._USER_ADAPT_PROFILES[uid] = {"updated_at": older_iso}
    decayed60 = brain._current_adjustment(uid)
    assert 0 <= decayed60 <= 2, f"60d decay of 10 should ≈1, got {decayed60}"


def test_recent_adjustment_not_decayed():
    """Fresh adjustment (just updated) should not be decayed."""
    from datetime import datetime, timezone

    uid = "user_fresh"
    brain._USER_ADJUSTMENTS[uid] = 7
    brain._USER_ADAPT_PROFILES[uid] = {
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    assert brain._current_adjustment(uid) == 7


def test_same_signal_different_users_produces_different_risk_levels():
    """
    THE PERSONALIZATION TEST: three users receive the SAME marginal signal
    (baseline risk just around thresholds). Their learned adjustments must
    produce DIFFERENT recommended actions / risk levels.

    Sensitive user: adjustment = -10 (lower thresholds → more sensitive)
    Normal user:    adjustment =  0
    Tolerant user:  adjustment = +10 (higher thresholds → less sensitive)
    """
    from datetime import datetime, timezone

    def _seed_user(uid: str, adjustment: int):
        brain._USER_ADJUSTMENTS[uid] = adjustment
        brain._USER_ADAPT_PROFILES[uid] = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "adjustment": adjustment,
        }

    _seed_user("u_sensitive", -10)
    _seed_user("u_normal",     0)
    _seed_user("u_tolerant",  +10)

    # _classify is the personalised pre-execution gate we want to validate
    # effective_score = 62 sits between adult's alert (60) and sos (80) normally
    # With adjustment -10 → new alert=50, sos=70  → 62 crosses alert+
    # With adjustment 0  → 62 just above alert=60 → RED / NOTIFY_GUARDIAN
    # With adjustment +10 → alert=70, sos=90 → 62 below alert → YELLOW / MONITOR
    score = 62

    lvl_s, act_s, _ = brain._classify(score, "adult", "u_sensitive")
    lvl_n, act_n, _ = brain._classify(score, "adult", "u_normal")
    lvl_t, act_t, _ = brain._classify(score, "adult", "u_tolerant")

    # The three must NOT all be the same — that's the whole point of personalization
    levels = {lvl_s, lvl_n, lvl_t}
    assert len(levels) >= 2, (
        f"Same signal must produce different decisions across personalised users. "
        f"sensitive={lvl_s} normal={lvl_n} tolerant={lvl_t}"
    )
    # Sensitive user must escalate HIGHER (or equal) than tolerant user
    rank = {"CRITICAL": 3, "RED": 2, "YELLOW": 1, "GREEN": 0}
    assert rank[lvl_s] >= rank[lvl_t], (
        f"Sensitive user must react at least as strongly as tolerant. "
        f"sensitive={lvl_s} tolerant={lvl_t}"
    )


def test_build_profile_shape():
    """Rich profile has both feedback_summary and confidence_profile."""
    from app.services import brain_adaptation_store as store

    feedbacks = [
        {"outcome": "true_positive", "decision_confidence": 0.9},
        {"outcome": "true_positive", "decision_confidence": 0.8},
        {"outcome": "false_alarm",   "decision_confidence": 0.75},
        {"outcome": "missed",        "decision_confidence": 0.4},
    ]
    doc = store.build_profile("u_rich", 5, feedbacks)
    assert doc["user_id"] == "u_rich"
    assert doc["adjustment"] == 5
    assert "updated_at" in doc
    fs = doc["feedback_summary"]
    assert fs["true_positive"] == 2 and fs["false_alarm"] == 1 and fs["missed"] == 1
    assert 0 <= fs["weighted_fp_rate"] <= 1
    cp = doc["confidence_profile"]
    assert 0 <= cp["avg_confidence"] <= 1
    assert 0 <= cp["high_conf_error_rate"] <= 1


def test_smoothing_function_math():
    """Unit test for the pure smoothing helper: new = round(0.7*old + 0.3*target)."""
    from app.services import brain_adaptation_store as store
    assert store.smooth(0, 10) == 3       # 0*0.7 + 10*0.3 = 3
    assert store.smooth(10, 0) == 7       # 10*0.7 + 0*0.3 = 7
    assert store.smooth(5, 5) == 5
    assert store.smooth(-4, 4) == round(-4 * 0.7 + 4 * 0.3)  # -1.6 → -2
