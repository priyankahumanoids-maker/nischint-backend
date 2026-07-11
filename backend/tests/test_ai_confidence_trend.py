"""OCE-01b — Tests for the history+trend logic in ai_confidence.

We exercise the trend computation in isolation. The DB-backed
`_fetch_history` is integration-tested by the live curl in the OCE-01b
CHANGELOG entry (seed 6 days, hit endpoint, verify trend label).
"""
from datetime import date, timedelta


def _trend_from_scores(scores):
    """Re-implement the trend computation from `_fetch_history` so we
    can unit-test the math without spinning up a DB.

    Keep this in sync with the inline logic in `ai_confidence.py`.
    """
    if len(scores) < 4:
        return "stable"
    recent_mean = sum(scores[-3:]) / 3
    older_mean = sum(scores[:-3]) / max(1, len(scores) - 3)
    delta = recent_mean - older_mean
    if delta >= 0.05:
        return "improving"
    if delta <= -0.05:
        return "degrading"
    return "stable"


# ── Length-floor: < 4 points always stable ─────────────────────────


def test_empty_history_is_stable():
    assert _trend_from_scores([]) == "stable"


def test_one_point_is_stable():
    assert _trend_from_scores([0.5]) == "stable"


def test_two_points_jump_still_stable():
    """Two points with a huge jump is too noisy to label as a trend."""
    assert _trend_from_scores([0.1, 0.9]) == "stable"


def test_three_points_stable_floor():
    assert _trend_from_scores([0.1, 0.5, 0.9]) == "stable"


# ── Trend labels ──────────────────────────────────────────────────


def test_improving_clear_uptrend():
    """4+ points, recent half clearly higher than older half."""
    scores = [0.18, 0.21, 0.20, 0.25, 0.27, 0.27, 0.30]
    # recent_mean = (0.27 + 0.27 + 0.30) / 3 = 0.28
    # older_mean  = (0.18 + 0.21 + 0.20 + 0.25) / 4 = 0.21
    # delta = 0.07 → improving
    assert _trend_from_scores(scores) == "improving"


def test_degrading_clear_downtrend():
    scores = [0.85, 0.82, 0.80, 0.75, 0.65, 0.60, 0.55]
    # recent_mean = (0.65 + 0.60 + 0.55) / 3 ≈ 0.60
    # older_mean  = (0.85 + 0.82 + 0.80 + 0.75) / 4 = 0.805
    # delta ≈ -0.205 → degrading
    assert _trend_from_scores(scores) == "degrading"


def test_stable_low_noise():
    scores = [0.50, 0.51, 0.49, 0.50, 0.52, 0.50, 0.51]
    # Both halves average ~ 0.50, delta ≈ 0 → stable
    assert _trend_from_scores(scores) == "stable"


def test_just_below_threshold_stable():
    """4.99% improvement should NOT cross the 5% threshold."""
    scores = [0.50, 0.50, 0.50, 0.50, 0.549, 0.549, 0.549]
    # recent_mean = 0.549, older_mean = 0.50, delta = 0.049 → stable
    assert _trend_from_scores(scores) == "stable"


def test_exactly_at_threshold_improving():
    """Exactly +5% → 'improving' (>= not >)."""
    scores = [0.50, 0.50, 0.50, 0.50, 0.55, 0.55, 0.55]
    assert _trend_from_scores(scores) == "improving"


def test_exactly_at_negative_threshold_degrading():
    scores = [0.55, 0.55, 0.55, 0.55, 0.50, 0.50, 0.50]
    assert _trend_from_scores(scores) == "degrading"


def test_recovery_pattern_recent_half_dominates():
    """User crashed mid-week then recovered. Recent 3 days good → improving."""
    scores = [0.40, 0.30, 0.25, 0.20, 0.55, 0.62, 0.68]
    # recent = (0.55 + 0.62 + 0.68)/3 ≈ 0.617
    # older = (0.40 + 0.30 + 0.25 + 0.20)/4 = 0.2875
    # delta ≈ +0.33 → improving
    assert _trend_from_scores(scores) == "improving"


def test_relapse_pattern_recent_dip_dominates():
    scores = [0.78, 0.80, 0.82, 0.80, 0.50, 0.45, 0.40]
    # recent ≈ 0.45, older = 0.80 → degrading
    assert _trend_from_scores(scores) == "degrading"


# ── Math floors ───────────────────────────────────────────────────


def test_exactly_four_points_uses_one_older_one_recent_three():
    scores = [0.30, 0.50, 0.55, 0.60]
    # recent_mean = (0.50 + 0.55 + 0.60)/3 = 0.55
    # older_mean = 0.30
    # delta = 0.25 → improving
    assert _trend_from_scores(scores) == "improving"
