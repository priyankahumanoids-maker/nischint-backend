"""Tests for NISCH-008 — Twilio safety wrapper (timeout + retry + latency)."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from app.services import twilio_safe


# ── Happy path ──────────────────────────────────────────────────────
def test_safe_call_returns_success_on_first_attempt():
    fn = MagicMock(return_value="ok")
    out = twilio_safe.safe_call(fn, kind="sms", args=("body",), kwargs={"to": "+1"})
    assert out["success"] is True
    assert out["result"] == "ok"
    assert out["attempts"] == 1
    assert out["error"] is None
    assert out["latency_ms"] >= 0
    fn.assert_called_once_with("body", to="+1")


# ── Retry behaviour ─────────────────────────────────────────────────
def test_safe_call_retries_on_failure_then_succeeds(monkeypatch):
    monkeypatch.setattr(twilio_safe, "RETRY_BACKOFF_S", 0)  # speed up test
    side_effects = [RuntimeError("blip"), "ok"]
    fn = MagicMock(side_effect=side_effects)
    out = twilio_safe.safe_call(fn, kind="sms")
    assert out["success"] is True
    assert out["attempts"] == 2
    assert out["result"] == "ok"


def test_safe_call_gives_up_after_all_retries(monkeypatch):
    monkeypatch.setattr(twilio_safe, "RETRY_BACKOFF_S", 0)
    fn = MagicMock(side_effect=RuntimeError("HTTP 401 Authenticate"))
    out = twilio_safe.safe_call(fn, kind="sms", retries=1)
    assert out["success"] is False
    assert out["attempts"] == 2  # 1 initial + 1 retry
    assert "401" in out["error"] or "Authenticate" in out["error"]


# ── Timeout ─────────────────────────────────────────────────────────
def test_safe_call_enforces_hard_timeout(monkeypatch):
    monkeypatch.setattr(twilio_safe, "RETRY_BACKOFF_S", 0)

    def slow(*a, **kw):
        time.sleep(2)
        return "too late"

    out = twilio_safe.safe_call(slow, kind="sms", timeout_s=0.2, retries=0)
    assert out["success"] is False
    assert "timeout" in (out["error"] or "").lower()
    assert out["attempts"] == 1


# ── Never raises ────────────────────────────────────────────────────
def test_safe_call_never_raises_even_with_garbage_fn():
    out = twilio_safe.safe_call(None, kind="sms")  # type: ignore[arg-type]
    assert out["success"] is False
    assert out["error"] is not None


# ── TTFA hook is called ─────────────────────────────────────────────
def test_safe_call_records_ttfa_sample_on_success(monkeypatch):
    captured: list[dict] = []
    def fake_record(**kw):
        captured.append(kw)
    monkeypatch.setattr(
        "app.services.ttfa_recorder.record",
        fake_record,
    )
    twilio_safe.safe_call(lambda: "ok", kind="sms")
    assert any(c.get("kind") == "twilio:sms" for c in captured)


def test_safe_call_records_ttfa_sample_on_failure(monkeypatch):
    monkeypatch.setattr(twilio_safe, "RETRY_BACKOFF_S", 0)
    captured: list[dict] = []
    def fake_record(**kw):
        captured.append(kw)
    monkeypatch.setattr(
        "app.services.ttfa_recorder.record",
        fake_record,
    )
    twilio_safe.safe_call(
        MagicMock(side_effect=RuntimeError("boom")),
        kind="voice",
        retries=0,
    )
    assert any(c.get("kind") == "twilio:voice" for c in captured)


# ── Result structure ────────────────────────────────────────────────
def test_safe_call_result_has_all_required_fields():
    out = twilio_safe.safe_call(lambda: "x", kind="sms")
    for key in ("success", "result", "error", "attempts", "latency_ms"):
        assert key in out
