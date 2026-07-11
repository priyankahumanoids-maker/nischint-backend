"""
SB-01 Day 2 — Hermes attenuator unit tests.

Pure in-process tests of `compute_risk_score` with attenuation +
time multiplier kwargs. No backend / network — these lock the
math contract as permanent behaviour:

  1. **Himalaya invariant** — new user (no attenuation, no time
     shift) produces the canonical 0.61 base (× env 1.30 = 0.793).
  2. Heavy-FP user with `fall: 0.5` attenuation produces a strictly
     lower composite than the no-att path, blunting the alarm.
  3. Off-hours `time_multiplier=1.15` nudges composite up — but
     stays bounded by the 1.30 ceiling.
  4. Guardrails: time-mult above 1.30 is clamped; per-signal
     attenuation below 0.5 is clamped (never zero life-critical).

Plus pure tests of `get_time_multiplier(...)`.
"""
from app.api.sb01_hermes import (
    DEFAULT_NORMAL_END,
    DEFAULT_NORMAL_START,
    MAX_ATTENUATION,
    OFF_HOURS_MULTIPLIER,
    TIME_MULT_CEILING,
    get_time_multiplier,
)
from app.services.safety_brain_service import (
    ENV_HAZARD_MULTIPLIER,
    compute_risk_score,
)


# ── Himalaya invariant — the hard gate ─────────────────────────────


def test_himalaya_new_user_base_composite_unchanged():
    """No attenuation, no time mult → SF-01 v2 math, unchanged."""
    score, level, primary = compute_risk_score({"fall": 0.90, "voice": 0.65})
    assert score == 0.61, f"new-user base composite drifted: {score} (expected 0.61)"
    assert primary == "fall"
    assert level == "dangerous"


def test_himalaya_explicit_no_attenuation_matches_default():
    """Passing explicit no-op kwargs must produce identical math."""
    base, _, _ = compute_risk_score({"fall": 0.90, "voice": 0.65})
    explicit, _, _ = compute_risk_score(
        {"fall": 0.90, "voice": 0.65},
        weight_attenuation={},
        time_multiplier=1.0,
    )
    assert base == explicit == 0.61


def test_himalaya_with_env_mult_lands_on_0793():
    """0.61 base × 1.30 env = 0.793 — the Himalaya number."""
    base, _, _ = compute_risk_score({"fall": 0.90, "voice": 0.65})
    composite = round(min(1.0, base * ENV_HAZARD_MULTIPLIER), 3)
    assert composite == 0.793, f"Himalaya math regressed: {composite}"


# ── Heavy-FP user — attenuation must blunt ─────────────────────────


def test_heavy_fp_fall_user_composite_drops():
    """Same signals, fall attenuated to 0.5 → composite strictly lower."""
    no_att, _, _ = compute_risk_score({"fall": 0.90, "voice": 0.65})
    att, _, _ = compute_risk_score(
        {"fall": 0.90, "voice": 0.65},
        weight_attenuation={"fall": 0.5},
    )
    assert att < no_att, f"attenuator didn't blunt: att={att} ≥ no_att={no_att}"
    # Expected: 0.90*0.35*0.5 + 0.65*0.30 + 0.10 = 0.1575+0.195+0.10 = 0.4525
    assert att == 0.453, f"heavy-FP math drifted: {att}"


def test_voice_attenuator_does_not_zero_signal():
    """Even worst-case attenuator must leave voice contributing something."""
    s_default, _, _ = compute_risk_score({"voice": 1.0})
    s_floor, _, _ = compute_risk_score({"voice": 1.0}, weight_attenuation={"voice": 0.0})
    # Voice weight = 0.30. Default → 0.30. Floor → 0.30 * 0.5 = 0.15.
    assert s_default == 0.30
    assert s_floor == 0.15, f"voice floor broken: {s_floor}"
    assert s_floor > 0, "voice must never zero out"


def test_attenuation_only_applies_to_known_keys():
    """Unknown signal type (e.g. 'wearable_fall') has weight 0 anyway."""
    s, _, _ = compute_risk_score(
        {"wearable_fall": 1.0},
        weight_attenuation={"wearable_fall": 0.5},
    )
    assert s == 0.0


# ── Time-of-day multiplier ─────────────────────────────────────────


def test_time_mult_in_window_is_1_0():
    for h in range(DEFAULT_NORMAL_START, DEFAULT_NORMAL_END):
        assert get_time_multiplier(h) == 1.0, f"in-window hour {h} not 1.0"


def test_time_mult_off_hours_is_1_15():
    for h in (0, 1, 5, 22, 23):
        assert get_time_multiplier(h) == OFF_HOURS_MULTIPLIER, f"hour {h} not off-hours"


def test_time_mult_ceiling_clamp_in_compute():
    """Even a buggy caller passing 99 can't push above 1.30 ceiling."""
    s_huge, _, _ = compute_risk_score({"fall": 0.90}, time_multiplier=99.0)
    s_ceil, _, _ = compute_risk_score({"fall": 0.90}, time_multiplier=TIME_MULT_CEILING)
    assert s_huge == s_ceil


def test_off_hours_nudge_lifts_composite_within_bound():
    base, _, _ = compute_risk_score({"fall": 0.90, "voice": 0.65})  # 0.61
    nudged, _, _ = compute_risk_score(
        {"fall": 0.90, "voice": 0.65},
        time_multiplier=OFF_HOURS_MULTIPLIER,
    )
    assert nudged > base, "off-hours should lift composite"
    # Expected: 0.61 * 1.15 = 0.7015 → rounded 0.701 (well below 0.793 Himalaya).
    assert nudged == 0.701
    # And critically below env-multiplied Himalaya, so off-hours
    # alone never reaches alert-tier from a 0.5-band signal pair.


# ── Guardrails ─────────────────────────────────────────────────────


def test_per_signal_attenuator_floor_locked_at_max_attenuation():
    """No matter how aggressive the attenuator, weight stays ≥ 50%."""
    s_aggressive, _, _ = compute_risk_score(
        {"fall": 0.90}, weight_attenuation={"fall": -1.0},
    )
    s_floor, _, _ = compute_risk_score(
        {"fall": 0.90}, weight_attenuation={"fall": 1.0 - MAX_ATTENUATION},
    )
    assert s_aggressive == s_floor


def test_per_signal_attenuator_ceiling_clamped_to_1_0():
    """Attenuator > 1.0 must not amplify."""
    s_amp, _, _ = compute_risk_score(
        {"fall": 0.90}, weight_attenuation={"fall": 5.0},
    )
    s_default, _, _ = compute_risk_score({"fall": 0.90})
    assert s_amp == s_default
