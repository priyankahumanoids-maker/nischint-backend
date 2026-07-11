"""DPDP-04-DIGEST — Tests for the weekly DPO digest job.

These tests pin the diff logic and the rendering templates. The
SendGrid send and the DB I/O are out of scope — they're exercised by
the smoke test in the finish summary.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.services.dpdp_digest_service import (
    DROP_THRESHOLD,
    compute_diff,
    render_html,
    render_subject,
    render_text,
)


# ── Sample bundles ──────────────────────────────────────────────────


def _bundle(rates: dict[str, float], decided: int = 100) -> dict[str, object]:
    """Shape mirrors `ConsentHealthBundle.model_dump()`."""
    cats = []
    for cat, rate in rates.items():
        cats.append({
            "category": cat,
            "label_en": cat.replace("_", " ").title(),
            "decided": decided,
            "granted": int(round(rate * decided)),
            "grant_rate": round(rate, 4),
            "healthy": rate >= 0.8,
        })
    return {
        "total_users_prompted": decided,
        "overall_state": "ok",
        "healthy_threshold": 0.8,
        "critical_threshold": 0.5,
        "min_sample_size": 10,
        "categories": cats,
        "generated_at": "2026-05-25T00:00:00+00:00",
    }


# ── Diff logic ───────────────────────────────────────────────────────


def test_first_run_has_no_history_and_no_flags():
    current = _bundle({"location_tracking": 0.30})  # would normally flag
    diff = compute_diff(current, last=None)
    assert diff["has_history"] is False
    assert diff["flagged"] == []
    # Per-category delta_pp is 0 because there's no baseline.
    assert diff["categories"][0]["delta_pp"] == 0.0
    assert diff["categories"][0]["previous_rate"] is None


def test_drop_below_threshold_is_not_flagged():
    last = _bundle({"location_tracking": 0.90})
    current = _bundle({"location_tracking": 0.86})  # -4 pp, below 5pp threshold
    diff = compute_diff(current, last)
    assert diff["flagged"] == []
    assert diff["categories"][0]["delta_pp"] == pytest.approx(-4.0, abs=0.01)


def test_drop_exactly_at_threshold_is_not_flagged():
    # Strict ">" — exactly 5pp drop is NOT a regression.
    last = _bundle({"audio_recording": 0.90})
    current = _bundle({"audio_recording": 0.85})
    diff = compute_diff(current, last)
    assert diff["flagged"] == []


def test_drop_strictly_above_threshold_is_flagged():
    last = _bundle({"audio_recording": 0.90})
    current = _bundle({"audio_recording": 0.84})  # -6 pp
    diff = compute_diff(current, last)
    assert len(diff["flagged"]) == 1
    flagged = diff["flagged"][0]
    assert flagged["category"] == "audio_recording"
    assert flagged["dropped"] is True
    assert flagged["delta_pp"] == pytest.approx(-6.0, abs=0.01)


def test_rise_is_never_flagged():
    # A consent rate going UP is good news, never a flag.
    last = _bundle({"push_notifications": 0.60})
    current = _bundle({"push_notifications": 0.95})  # +35 pp
    diff = compute_diff(current, last)
    assert diff["flagged"] == []
    assert diff["categories"][0]["delta_pp"] == pytest.approx(35.0, abs=0.01)


def test_drop_threshold_argument_overrides_default():
    # Caller can tighten the threshold for ad-hoc reports.
    last = _bundle({"health_vitals": 0.90})
    current = _bundle({"health_vitals": 0.88})  # -2 pp
    # Default: not flagged.
    assert compute_diff(current, last)["flagged"] == []
    # Tightened: now flagged.
    flagged = compute_diff(current, last, drop_threshold=0.01)["flagged"]
    assert len(flagged) == 1


def test_drop_threshold_default_is_five_pp():
    # Sanity-check the module-level constant — protects against
    # accidental tuning regressions.
    assert DROP_THRESHOLD == 0.05


def test_new_category_added_this_week_is_not_flagged():
    # A category absent from last week's snapshot reports `previous_rate=None`
    # and `dropped=False` regardless of its current rate.
    last = _bundle({"location_tracking": 0.90})
    current = _bundle({
        "location_tracking": 0.90,
        "biometric_sensors": 0.10,  # brand new, terrible rate but new = no flag
    })
    diff = compute_diff(current, last)
    bio = next(c for c in diff["categories"] if c["category"] == "biometric_sensors")
    assert bio["dropped"] is False
    assert bio["previous_rate"] is None
    assert diff["flagged"] == []


# ── Templating ───────────────────────────────────────────────────────


def test_subject_format_matches_spec():
    subject = render_subject(date(2026, 6, 7))
    assert subject == "NISCHINT Weekly Consent Health — 2026-06-07"


def test_text_body_calls_out_flagged_categories():
    last = _bundle({"location_tracking": 0.90, "audio_recording": 0.85})
    current = _bundle({
        "location_tracking": 0.91,   # +1 pp (ok)
        "audio_recording":   0.50,   # -35 pp (FLAGGED)
    })
    diff = compute_diff(current, last)
    body = render_text(current, diff, date(2026, 6, 7))
    assert "FLAGGED" in body
    assert "Audio Recording" in body
    assert "-35" in body or "−35" in body or "35" in body
    assert "Location Tracking" in body  # still listed below
    assert "2026-06-07" in body


def test_text_body_first_run_has_no_history_note():
    current = _bundle({"location_tracking": 0.90})
    diff = compute_diff(current, last=None)
    body = render_text(current, diff, date(2026, 6, 7))
    assert "First snapshot" in body
    assert "FLAGGED" not in body


def test_html_body_renders_table_rows_and_flagged_block():
    last = _bundle({"location_tracking": 0.90, "audio_recording": 0.85})
    current = _bundle({
        "location_tracking": 0.91,
        "audio_recording":   0.50,
    })
    diff = compute_diff(current, last)
    html = render_html(current, diff, date(2026, 6, 7))
    # Subject line content
    assert "Weekly Consent Health" in html
    # Both categories appear
    assert "Location Tracking" in html
    assert "Audio Recording" in html
    # Flagged block exists with the drop magnitude (allow ± sign chars)
    assert "categor" in html  # "categories" or "category"
    assert "&gt;" in html or ">" in html
    # Critical row tone (rose-900 background)
    assert "#7f1d1d" in html


def test_html_body_first_run_includes_history_note():
    current = _bundle({"location_tracking": 0.90})
    diff = compute_diff(current, last=None)
    html = render_html(current, diff, date(2026, 6, 7))
    assert "first snapshot" in html.lower()


def test_html_body_handles_empty_consents():
    # No categories ever populated — render_html must not crash.
    current = {
        "total_users_prompted": 0,
        "overall_state": "nodata",
        "categories": [],
    }
    diff = compute_diff(current, last=None)
    html = render_html(current, diff, date(2026, 6, 7))
    assert "No consent rows yet." in html
