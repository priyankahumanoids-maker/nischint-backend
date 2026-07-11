"""Tests for NISCH-008b health_alerter — proactive ops notifications."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import event_dedup, health_alerter


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    # No real Slack/Discord posts; force local dedup path.
    monkeypatch.delenv("OPS_SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("OPS_DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(
        "app.services.event_dedup.redis_service.is_available", lambda: False
    )
    event_dedup.reset_local()
    yield
    event_dedup.reset_local()


# ── Validation ──────────────────────────────────────────────────────
def test_notify_rejects_empty_required_fields():
    assert health_alerter.notify_failure(level="", kind="x", message="m") is False
    assert health_alerter.notify_failure(level="warn", kind="", message="m") is False
    assert health_alerter.notify_failure(level="warn", kind="x", message="") is False


# ── Logging always fires ────────────────────────────────────────────
def test_notify_always_logs(caplog):
    caplog.set_level("INFO", logger="app.services.health_alerter")
    out = health_alerter.notify_failure(
        level="warn", kind="twilio_auth", message="boot auth failed",
    )
    assert out is True
    assert any("OPS_ALERT" in rec.message for rec in caplog.records)


# ── Dedup ───────────────────────────────────────────────────────────
def test_notify_dedups_identical_repeats(caplog):
    caplog.set_level("INFO", logger="app.services.health_alerter")
    health_alerter.notify_failure(level="warn", kind="x", message="same msg")
    health_alerter.notify_failure(level="warn", kind="x", message="same msg")
    msgs = [r.message for r in caplog.records]
    assert sum("[OPS_ALERT]" in m for m in msgs) == 1
    assert any("OPS_ALERT_DEDUP" in m for m in msgs)


def test_notify_does_not_dedup_different_kinds(caplog):
    caplog.set_level("INFO", logger="app.services.health_alerter")
    health_alerter.notify_failure(level="warn", kind="a", message="m")
    health_alerter.notify_failure(level="warn", kind="b", message="m")
    msgs = [r.message for r in caplog.records]
    assert sum("[OPS_ALERT]" in m for m in msgs) == 2


# ── Slack channel ───────────────────────────────────────────────────
def test_notify_posts_to_slack_when_configured(monkeypatch):
    monkeypatch.setenv("OPS_SLACK_WEBHOOK_URL", "https://hooks.slack.com/x")
    captured: list[dict] = []
    def fake_post(url, json=None, timeout=None):
        captured.append({"url": url, "json": json})
        r = MagicMock(); r.status_code = 200; r.text = "ok"
        return r
    monkeypatch.setattr("app.services.health_alerter.requests.post", fake_post)

    health_alerter.notify_failure(
        level="critical", kind="twilio_auth",
        message="HTTP 401 Authenticate",
        details={"sid_prefix": "AC1ec904..."},
    )
    # The send is queued onto an executor — wait briefly.
    health_alerter._EXECUTOR.shutdown(wait=True)
    # Re-create executor for further tests in same process.
    import concurrent.futures
    health_alerter._EXECUTOR = concurrent.futures.ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="ops-alert",
    )

    assert len(captured) == 1
    assert captured[0]["url"] == "https://hooks.slack.com/x"
    body = captured[0]["json"]
    assert "NISCHINT OPS" in body["text"]
    assert "twilio_auth" in body["text"]
    assert "HTTP 401" in body["text"]


def test_slack_failure_does_not_raise(monkeypatch):
    monkeypatch.setenv("OPS_SLACK_WEBHOOK_URL", "https://hooks.slack.com/x")
    def boom(*a, **kw):
        raise RuntimeError("network blip")
    monkeypatch.setattr("app.services.health_alerter.requests.post", boom)
    out = health_alerter.notify_failure(level="warn", kind="x", message="m")
    health_alerter._EXECUTOR.shutdown(wait=True)
    import concurrent.futures
    health_alerter._EXECUTOR = concurrent.futures.ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="ops-alert",
    )
    assert out is True  # alerter never raises
