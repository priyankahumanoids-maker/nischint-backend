"""
Unit tests for the V2 risk-coupled + time-decayed Guardian Trust Service.

Validates:
    1. Dynamic weighting (CRITICAL=0.8/0.2, RED=0.7/0.3, YELLOW=0.6/0.4, GREEN=0.5/0.5)
    2. Time-decay: inactive-20d guardian ranks below recent-active guardian
    3. Confidence-damping: 1-event guardian ranks below many-events guardian
    4. Legacy risk aliases: "critical" → CRITICAL, "safe" → GREEN
    5. Empty / None risk_level → DEFAULT_RISK (RED)
    6. Graceful behaviour for unknown contacts (neutral 0.5)

Run:  pytest -q backend/tests/test_guardian_trust_risk_weighted.py
"""
from __future__ import annotations

import math
import time

import pytest

from app.services import guardian_trust_service as gts


# ── helpers ──────────────────────────────────────────────────────────

def _inject(contact_id: str, trust: float, *, last_event_at=None, total=10, acks=None):
    """Seed the in-memory cache with a controlled record (bypasses Mongo)."""
    acks = acks if acks is not None else total
    gts._CACHE[contact_id] = {
        "contact_id": contact_id,
        "total_alerts": total,
        "ack_count": acks,
        "avg_response_ms": 1000.0,
        "missed_consecutive": 0,
        "last_event_at": last_event_at if last_event_at is not None else time.time(),
        "trust_score": trust,
    }


@pytest.fixture(autouse=True)
def _reset_cache():
    gts._CACHE.clear()
    gts._ESCALATION_LOCK.clear()
    yield
    gts._CACHE.clear()
    gts._ESCALATION_LOCK.clear()


# ── 1. Dynamic weighting ─────────────────────────────────────────────

def test_critical_favours_trust_over_priority():
    """
    High-trust guardian with BAD priority must beat low-trust guardian with
    GREAT priority when risk is CRITICAL (0.8 weight on trust).
    """
    _inject("high_trust", trust=0.9)
    _inject("low_trust", trust=0.2)

    guardians = [
        {"id": "low_trust",  "name": "Mom",  "priority": 1},   # best priority
        {"id": "high_trust", "name": "Uncle", "priority": 5},  # worst priority
    ]
    result = gts.sort_guardians_by_trust(guardians, risk_level="CRITICAL")
    assert result[0]["id"] == "high_trust", "CRITICAL must rank trust first"


def test_green_favours_priority_over_trust():
    """
    In low-risk GREEN scenarios priority gets 0.5 weight (equal) — when trust
    is close, priority breaks the tie and the configured family order wins.
    """
    _inject("slightly_higher", trust=0.55)
    _inject("configured_first", trust=0.50)

    guardians = [
        {"id": "slightly_higher", "name": "Aunt", "priority": 9},
        {"id": "configured_first", "name": "Mom", "priority": 1},
    ]
    result = gts.sort_guardians_by_trust(guardians, risk_level="GREEN")
    assert result[0]["id"] == "configured_first"


def test_tiered_weights_return_correct_coefficients():
    assert gts._risk_weights("CRITICAL") == {"trust": 0.8, "priority": 0.2}
    assert gts._risk_weights("RED") == {"trust": 0.7, "priority": 0.3}
    assert gts._risk_weights("YELLOW") == {"trust": 0.6, "priority": 0.4}
    assert gts._risk_weights("GREEN") == {"trust": 0.5, "priority": 0.5}


# ── 2. Time-decay ────────────────────────────────────────────────────

def test_time_decay_demotes_stale_guardian():
    """
    Guardian A: high trust (0.9) but silent 20 days → decay e^(-2.0) ≈ 0.135
    Guardian B: medium trust (0.6) but active yesterday → decay ≈ 0.905

    effective_trust:  A ≈ 0.9 * 0.135 ≈ 0.122   vs   B ≈ 0.6 * 0.905 ≈ 0.543
    → B ranks higher.
    """
    now = time.time()
    _inject("stale_A",  trust=0.9, last_event_at=now - 20 * 86400, total=20)
    _inject("fresh_B",  trust=0.6, last_event_at=now - 1 * 86400,  total=20)

    guardians = [
        {"id": "stale_A", "name": "A", "priority": 1},
        {"id": "fresh_B", "name": "B", "priority": 1},
    ]
    result = gts.sort_guardians_by_trust(guardians, risk_level="CRITICAL")
    assert result[0]["id"] == "fresh_B", "Stale guardian must decay below fresh one"


def test_decay_factor_math():
    """Spot-check exp(-days/10) computation."""
    now = time.time()
    ten_days_ago = now - 10 * 86400
    df = gts._decay_factor(ten_days_ago)
    assert abs(df - math.exp(-1.0)) < 0.01


# ── 3. Confidence damping ────────────────────────────────────────────

def test_confidence_factor_damps_low_event_counts():
    """
    1 event → log(2)/3 ≈ 0.23
    20 events → log(21)/3 ≈ 1.0
    """
    assert gts._confidence_factor(1) < 0.3
    assert gts._confidence_factor(20) >= 0.99


def test_lucky_guardian_does_not_outrank_proven_one():
    """
    Lucky:  1 event, perfect trust 1.0
    Proven: 20 events, trust 0.7
      effective_lucky  ≈ 1.0 * 1.0 * 0.23 ≈ 0.23
      effective_proven ≈ 0.7 * 1.0 * 1.0  ≈ 0.70
    """
    now = time.time()
    _inject("lucky",  trust=1.0, last_event_at=now, total=1, acks=1)
    _inject("proven", trust=0.7, last_event_at=now, total=20, acks=14)

    guardians = [
        {"id": "lucky",  "name": "Lucky",  "priority": 1},
        {"id": "proven", "name": "Proven", "priority": 5},
    ]
    result = gts.sort_guardians_by_trust(guardians, risk_level="CRITICAL")
    assert result[0]["id"] == "proven"


# ── 4. Legacy aliases ────────────────────────────────────────────────

@pytest.mark.parametrize("alias,expected", [
    ("critical", "CRITICAL"),
    ("high", "RED"),
    ("medium", "YELLOW"),
    ("safe", "GREEN"),
    ("low", "GREEN"),
    ("severe", "CRITICAL"),
])
def test_legacy_risk_aliases(alias, expected):
    weights = gts._risk_weights(alias)
    assert weights == gts.WEIGHTS_BY_RISK[expected]


# ── 5. Edge cases ────────────────────────────────────────────────────

def test_none_risk_level_falls_back_to_default():
    weights = gts._risk_weights(None)
    assert weights == gts.WEIGHTS_BY_RISK[gts.DEFAULT_RISK]


def test_unknown_contact_returns_neutral_effective_trust():
    assert gts.get_effective_trust("does_not_exist") == gts.DEFAULT_NEW_SCORE


def test_empty_guardian_list_returns_empty():
    assert gts.sort_guardians_by_trust([], risk_level="CRITICAL") == []


def test_backward_compatible_call_without_risk_level():
    """Existing callers passing no risk_level must still work."""
    _inject("any", trust=0.7)
    guardians = [{"id": "any", "name": "A", "priority": 1}]
    result = gts.sort_guardians_by_trust(guardians)
    assert len(result) == 1


# ── 6. Escalation Lock ───────────────────────────────────────────────

def test_escalation_lock_freezes_order_after_first_sort():
    """
    First call with incident_id establishes the frozen order.
    Subsequent calls (even with different risk_level / mutated trust)
    must return the SAME order.
    """
    _inject("A", trust=0.9)
    _inject("B", trust=0.3)
    guardians = [
        {"id": "B", "priority": 1},
        {"id": "A", "priority": 5},
    ]
    # First sort (CRITICAL → trust wins → A first)
    first = gts.sort_guardians_by_trust(guardians, risk_level="CRITICAL", incident_id="sos_xyz")
    assert [g["id"] for g in first] == ["A", "B"]

    # Flip trust mid-incident — lock must hold
    _inject("A", trust=0.1)
    _inject("B", trust=0.99)
    second = gts.sort_guardians_by_trust(guardians, risk_level="GREEN", incident_id="sos_xyz")
    assert [g["id"] for g in second] == ["A", "B"], "Lock must freeze order"

    gts.release_escalation_lock("sos_xyz")


def test_release_escalation_lock_allows_fresh_sort():
    _inject("A", trust=0.9)
    _inject("B", trust=0.3)
    guardians = [{"id": "B", "priority": 1}, {"id": "A", "priority": 5}]

    gts.sort_guardians_by_trust(guardians, risk_level="CRITICAL", incident_id="sos_1")
    assert gts.get_escalation_lock("sos_1") == ["A", "B"]

    assert gts.release_escalation_lock("sos_1") is True
    assert gts.get_escalation_lock("sos_1") is None

    # Flip trust; next incident should reflect new order
    _inject("A", trust=0.1)
    _inject("B", trust=0.9)
    fresh = gts.sort_guardians_by_trust(guardians, risk_level="CRITICAL", incident_id="sos_2")
    assert [g["id"] for g in fresh] == ["B", "A"]

    gts.release_escalation_lock("sos_2")


def test_escalation_lock_appends_new_guardians_at_end():
    """If a new guardian is added mid-incident, they go last — not re-sorted in."""
    _inject("A", trust=0.5)
    _inject("B", trust=0.5)
    initial = [{"id": "A", "priority": 1}, {"id": "B", "priority": 2}]
    gts.sort_guardians_by_trust(initial, risk_level="RED", incident_id="sos_lock_add")

    _inject("C", trust=0.99)  # super-trusted late-joiner
    extended = initial + [{"id": "C", "priority": 1}]
    result = gts.sort_guardians_by_trust(extended, risk_level="RED", incident_id="sos_lock_add")
    # C must NOT jump to front — lock protects original order
    assert [g["id"] for g in result][:2] == [r["id"] for r in gts.sort_guardians_by_trust(initial, risk_level="RED", incident_id="sos_lock_add")]
    assert result[-1]["id"] == "C"

    gts.release_escalation_lock("sos_lock_add")


def test_no_incident_id_skips_lock():
    """Legacy callers (no incident_id) must NOT populate the lock dict."""
    _inject("A", trust=0.9)
    guardians = [{"id": "A", "priority": 1}]
    before = dict(gts._ESCALATION_LOCK)
    gts.sort_guardians_by_trust(guardians, risk_level="CRITICAL")
    assert gts._ESCALATION_LOCK == before, "No incident_id → no lock entry"
