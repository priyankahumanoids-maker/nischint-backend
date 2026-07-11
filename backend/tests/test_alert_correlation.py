"""Tests for NISCH-008d alert correlation —
`ttfa_recorder.get_recent_events` + Slack formatter rendering of the
`recent_ttfa` block."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from app.services import event_dedup, health_alerter, ttfa_recorder


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.delenv("OPS_SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("OPS_DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(
        "app.services.event_dedup.redis_service.is_available", lambda: False
    )
    monkeypatch.setattr(
        "app.services.ttfa_recorder.redis_service.is_available", lambda: False
    )
    event_dedup.reset_local()
    ttfa_recorder.reset_buffer()
    yield
    event_dedup.reset_local()
    ttfa_recorder.reset_buffer()


# ── ttfa_recorder.get_recent_events ────────────────────────────────
def test_get_recent_events_empty_returns_empty_list():
    assert ttfa_recorder.get_recent_events(10) == []


def test_get_recent_events_returns_oldest_first():
    for i, ms in enumerate([10, 20, 30, 40, 50]):
        ttfa_recorder.record(kind=f"k{i}", ttfa_ms=ms, priority="critical")
    out = ttfa_recorder.get_recent_events(3)
    assert len(out) == 3
    # oldest → newest among the LAST 3
    assert [e["kind"] for e in out] == ["k2", "k3", "k4"]
    assert [e["ttfa_ms"] for e in out] == [30, 40, 50]


def test_get_recent_events_zero_returns_empty():
    ttfa_recorder.record(kind="x", ttfa_ms=10)
    assert ttfa_recorder.get_recent_events(0) == []
    assert ttfa_recorder.get_recent_events(-1) == []


def test_get_recent_events_marks_failures_for_twilio_warning():
    ttfa_recorder.record(kind="twilio:sms", ttfa_ms=2100, priority="warning")
    ttfa_recorder.record(kind="twilio:sms", ttfa_ms=300, priority="critical")
    out = ttfa_recorder.get_recent_events(2)
    assert out[0]["status"] == "fail"  # warning + twilio: prefix
    assert out[1]["status"] == "ok"


def test_get_recent_events_non_twilio_warning_is_ok_status():
    ttfa_recorder.record(kind="voice_distress", ttfa_ms=4000, priority="warning")
    out = ttfa_recorder.get_recent_events(1)
    # Non-twilio warning is just a low-priority alert, not a delivery failure.
    assert out[0]["status"] == "ok"


# ── Slack block renders recent_ttfa ────────────────────────────────
def test_slack_block_includes_recent_ttfa_table():
    payload = {
        "level":   "critical",
        "kind":    "sla_transition",
        "message": "Twilio SLA transitioned green → red.",
        "details": {
            "from": "green", "to": "red",
            "recent_ttfa": [
                {"kind": "twilio:sms",       "ttfa_ms": 2100, "priority": "warning", "status": "fail"},
                {"kind": "voice_distress",   "ttfa_ms": 312,  "priority": "critical", "status": "ok"},
                {"kind": "twilio:voice",     "ttfa_ms": 137,  "priority": "critical", "status": "ok"},
            ],
        },
    }
    block = health_alerter._slack_block(payload)
    text = block["text"]
    assert "Last 10 TTFA events:" in text
    assert "twilio:sms" in text
    assert "2100ms" in text
    assert ":x:" in text  # failure marker
    assert "voice_distress" in text
    assert "312ms" in text


def test_slack_block_does_not_mutate_caller_payload():
    payload = {
        "level":   "warn",
        "kind":    "sla_transition",
        "message": "amber",
        "details": {
            "from": "green", "to": "amber",
            "recent_ttfa": [{"kind": "x", "ttfa_ms": 100, "priority": "ok", "status": "ok"}],
        },
    }
    health_alerter._slack_block(payload)
    # caller's `details["recent_ttfa"]` must still be present afterwards
    assert "recent_ttfa" in payload["details"]


def test_slack_block_no_recent_ttfa_falls_back_clean():
    payload = {
        "level":   "warn",
        "kind":    "twilio_give_up",
        "message": "voice fail",
        "details": {"attempts": 2},
    }
    block = health_alerter._slack_block(payload)
    assert "Last 10 TTFA events" not in block["text"]
    assert "twilio_give_up" in block["text"]
    assert "voice fail" in block["text"]


# ── End-to-end: notify_failure preserves recent_ttfa for downstream ─
def test_notify_failure_passes_recent_ttfa_to_slack(monkeypatch):
    monkeypatch.setenv("OPS_SLACK_WEBHOOK_URL", "https://hooks.slack.com/x")
    captured: list[dict] = []
    def fake_post(url, json=None, timeout=None):
        captured.append({"url": url, "json": json})
        r = MagicMock(); r.status_code = 200; r.text = "ok"
        return r
    monkeypatch.setattr("app.services.health_alerter.requests.post", fake_post)

    health_alerter.notify_failure(
        level="critical", kind="sla_transition",
        message="green → red",
        details={
            "from": "green", "to": "red",
            "recent_ttfa": [
                {"kind": "twilio:sms", "ttfa_ms": 2100, "priority": "warning", "status": "fail"},
            ],
        },
    )
    health_alerter._EXECUTOR.shutdown(wait=True)
    import concurrent.futures
    health_alerter._EXECUTOR = concurrent.futures.ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="ops-alert",
    )

    assert len(captured) == 1
    text = captured[0]["json"]["text"]
    assert "Last 10 TTFA events:" in text
    assert "twilio:sms" in text
    assert "2100ms" in text
