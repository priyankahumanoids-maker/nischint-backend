"""Tests for NISCH-004 canonical alert formatter.

Strict invariants we assert here (these are the contract everyone relies on):

* Pure function — same args → same output (modulo timestamp).
* Always returns every top-level envelope key, no `None` for required keys.
* Critical kinds (`voice_distress`, `sos`, `fall_detected`, `help_requested`)
  → priority="critical" + louder=True + requires_action=True.
* Generic / unknown kinds → fallback spec + metadata.fallback=True.
* Unknown locale → silently falls back to "en".
* No I/O paths exercised (no DB, no Redis, no broadcaster import).
"""
from __future__ import annotations

import pytest

from app.services.alert_formatter import (
    AlertEnvelope,
    DEFAULT_LOCALE,
    REGISTRY,
    format_alert,
)


REQUIRED_KEYS = {
    "kind", "title", "body", "priority", "sound",
    "channels", "requires_action", "louder", "metadata",
}


# ── Shape ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("kind", [
    "voice_distress", "sos", "fall_detected", "help_requested",
    "geofence_breach", "wandering", "minor_deviation", "low_battery",
    "device_offline", "arrived_safely", "resolved",
    "totally_made_up_kind",  # fallback exercised
    "",                      # empty string exercised
])
def test_envelope_always_has_all_required_keys(kind):
    env = format_alert(kind, {"child_name": "Aarav"})
    assert set(env.keys()) >= REQUIRED_KEYS
    for k in ("title", "body", "kind", "priority", "sound"):
        assert isinstance(env[k], str) and env[k], f"{k} must be non-empty string"
    assert isinstance(env["channels"], list) and len(env["channels"]) > 0
    assert "sse" in env["channels"], "every alert must always reach SSE"
    assert isinstance(env["requires_action"], bool)
    assert isinstance(env["louder"], bool)
    assert isinstance(env["metadata"], dict)


# ── Pure / deterministic ────────────────────────────────────────────
def test_pure_function_same_input_same_output_except_time():
    """Calling twice with identical ctx including a frozen timestamp
    must produce byte-identical envelopes."""
    from datetime import datetime, timezone
    fixed = datetime(2026, 5, 4, 14, 30, tzinfo=timezone.utc)
    ctx = {
        "child_name": "Aarav",
        "location":   {"lat": 12.97, "lng": 77.59},
        "severity":   "critical",
        "timestamp":  fixed,
        "confidence": 0.92,
    }
    a = format_alert("voice_distress", ctx)
    b = format_alert("voice_distress", ctx)
    assert a == b


# ── Critical kinds ──────────────────────────────────────────────────
@pytest.mark.parametrize("kind", [
    "voice_distress", "sos", "emergency_triggered",
    "fall_detected", "help_requested",
])
def test_critical_kinds_are_critical_louder_actionable(kind):
    env = format_alert(kind, {"child_name": "Aarav"})
    assert env["priority"] == "critical"
    assert env["louder"] is True
    assert env["requires_action"] is True
    assert "push" in env["channels"]
    assert "sms"  in env["channels"]


def test_voice_distress_uses_siren_loop_and_call_channel():
    env = format_alert("voice_distress", {"child_name": "A"})
    assert env["sound"] == "siren_loop"
    assert "call" in env["channels"]


def test_sos_uses_siren_loop_and_call_channel():
    env = format_alert("sos", {"child_name": "A"})
    assert env["sound"] == "siren_loop"
    assert "call" in env["channels"]


# ── Distinguishability — no two unrelated kinds collapse to same body ─
def test_voice_distress_vs_sos_vs_geofence_titles_are_distinguishable():
    a = format_alert("voice_distress", {"child_name": "Aarav"})
    b = format_alert("sos",            {"child_name": "Aarav"})
    c = format_alert("geofence_breach", {"child_name": "Aarav"})
    titles = {a["title"], b["title"], c["title"]}
    bodies = {a["body"],  b["body"],  c["body"]}
    assert len(titles) == 3
    assert len(bodies) == 3


# ── Warning / info tier ─────────────────────────────────────────────
def test_low_battery_is_warning_not_actionable():
    env = format_alert("low_battery", {"child_name": "A"})
    assert env["priority"] == "warning"
    assert env["requires_action"] is False
    assert env["louder"] is False
    assert env["sound"] == "default"


def test_arrived_safely_is_low_silent():
    env = format_alert("arrived_safely", {"child_name": "A"})
    assert env["priority"] == "low"
    assert env["sound"] == "silent"
    assert env["requires_action"] is False


# ── Fallback ────────────────────────────────────────────────────────
def test_unknown_kind_falls_back_to_generic_and_marks_metadata():
    env = format_alert("totally_made_up_kind", {
        "child_name": "Aarav",
        "message":    "something happened",
    })
    assert env["priority"] == "warning"
    assert env["metadata"]["fallback"] is True
    assert "something happened" in env["body"]
    assert env["title"].startswith("\U0001F7E1 NISCHINT")


def test_blank_kind_does_not_raise_and_falls_back():
    env = format_alert("", {"child_name": "A"})
    assert env["metadata"]["fallback"] is True
    assert env["kind"] == "unknown"


def test_kind_is_case_insensitive():
    a = format_alert("SOS",            {"child_name": "A"})
    b = format_alert("sos",            {"child_name": "A"})
    c = format_alert("  Voice_Distress  ", {"child_name": "A"})
    d = format_alert("voice_distress", {"child_name": "A"})
    assert a["priority"] == b["priority"] == "critical"
    assert c["title"] == d["title"]


# ── Robust against partial / bad ctx ────────────────────────────────
def test_no_child_name_uses_someone_placeholder():
    env = format_alert("sos", {})
    assert "Someone" in env["body"]


def test_bad_location_does_not_break():
    for bad in ({"lat": "abc", "lng": "def"}, {"lat": None}, {}, None):
        env = format_alert("sos", {"child_name": "A", "location": bad})
        assert "title" in env and "body" in env


def test_bad_confidence_becomes_none():
    env = format_alert("voice_distress", {
        "child_name": "A",
        "confidence": "not-a-number",
    })
    assert env["metadata"]["confidence"] is None


# ── i18n hook ───────────────────────────────────────────────────────
def test_unknown_locale_falls_back_to_default():
    env = format_alert("sos", {"child_name": "A"}, locale="zz-ZZ")
    assert env["metadata"]["locale"] == DEFAULT_LOCALE
    assert env["priority"] == "critical"


def test_default_locale_present_in_registry():
    assert DEFAULT_LOCALE in REGISTRY
    assert "sos" in REGISTRY[DEFAULT_LOCALE]


# ── Title / body content sanity ─────────────────────────────────────
def test_title_always_starts_with_nischint_brand():
    for kind in ("sos", "voice_distress", "fall_detected", "geofence_breach",
                 "low_battery", "arrived_safely", "totally_unknown"):
        env = format_alert(kind, {"child_name": "A"})
        assert " NISCHINT " in f" {env['title']} ", env["title"]


def test_location_renders_in_body_when_present():
    env = format_alert("sos", {
        "child_name": "Aarav",
        "location":   {"lat": 12.9716, "lng": 77.5946},
    })
    assert "12.9716" in env["body"]
    assert "77.5946" in env["body"]


def test_location_absent_does_not_leak_placeholder():
    env = format_alert("sos", {"child_name": "Aarav"})
    assert "{trail}" not in env["body"]
    assert "{loc_str}" not in env["body"]
    assert "{name}" not in env["body"]


# ── Metadata pass-through ───────────────────────────────────────────
def test_metadata_includes_severity_and_category():
    env = format_alert("voice_distress", {
        "child_name": "A",
        "severity":   "critical",
    })
    assert env["metadata"]["severity_input"] == "critical"
    assert env["metadata"]["category"] == "emergency"


def test_metadata_icon_critical_vs_warn():
    crit = format_alert("sos",         {"child_name": "A"})
    warn = format_alert("low_battery", {"child_name": "A"})
    assert crit["metadata"]["icon"] == "siren"
    assert warn["metadata"]["icon"] == "warn"
