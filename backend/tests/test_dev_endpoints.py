"""Regression: /api/_dev/risk-emitter/state — admin/operator-only state dump."""
from unittest.mock import MagicMock

import pytest

from app.api import _dev


def _user(roles, role=None):
    u = MagicMock()
    u.roles = roles
    u.role = role
    return u


class TestRoleGate:
    def test_admin_allowed(self):
        # Should not raise
        _dev._require_admin_or_operator(_user(["admin"]))

    def test_operator_allowed(self):
        _dev._require_admin_or_operator(_user(["operator"]))

    def test_admin_via_role_field(self):
        _dev._require_admin_or_operator(_user([], role="admin"))

    def test_guardian_denied(self):
        with pytest.raises(Exception) as exc:
            _dev._require_admin_or_operator(_user(["guardian"]))
        assert "403" in str(exc.value) or "admin or operator role required" in str(exc.value)

    def test_no_roles_denied(self):
        with pytest.raises(Exception):
            _dev._require_admin_or_operator(_user([]))

    def test_case_insensitive(self):
        _dev._require_admin_or_operator(_user(["ADMIN"]))
        _dev._require_admin_or_operator(_user(["Operator"]))


@pytest.mark.asyncio
async def test_summary_mode_for_unknown_child(monkeypatch):
    # Force the in-memory fallback so the test is independent of Redis.
    monkeypatch.setattr(_dev.redis_service, "is_available", lambda: False)
    user = _user(["operator"])
    out = await _dev.risk_emitter_state(child_id=None, user=user)
    assert "summary" in out
    assert out["summary"]["local_state_entries"] == 0
    assert out["redis_available"] is False
    assert "score_delta_threshold" in out
    assert isinstance(out["ts"], str)


@pytest.mark.asyncio
async def test_per_child_mode_returns_next_emit_key(monkeypatch):
    monkeypatch.setattr(_dev.redis_service, "is_available", lambda: False)
    user = _user(["admin"])
    out = await _dev.risk_emitter_state(child_id="abc-123", user=user)
    assert out["child_id"] == "abc-123"
    assert out["state"] is None        # no prior state for this child
    assert out["next_emit_key_would_be"] == "abc-123:1"


# ── /api/_dev/alert-ttfa/stats ──────────────────────────────────────
@pytest.mark.asyncio
async def test_ttfa_stats_empty_returns_zeros_with_low_confidence():
    from app.services import ttfa_recorder
    ttfa_recorder.reset_buffer()
    user = _user(["admin"])
    out = await _dev.alert_ttfa_stats(
        since=3600, kind=None, include_redis=False, user=user,
    )
    assert out["samples_considered"] == 0
    assert out["overall"]["count"] == 0
    assert out["confidence"] == "low"
    assert "ts" in out


@pytest.mark.asyncio
async def test_ttfa_stats_aggregates_recorded_samples():
    from app.services import ttfa_recorder
    ttfa_recorder.reset_buffer()
    for ms in range(20, 220, 10):  # 20 samples
        ttfa_recorder.record(kind="sos", ttfa_ms=ms, louder=True)

    user = _user(["operator"])
    out = await _dev.alert_ttfa_stats(
        since=3600, kind="sos", include_redis=False, user=user,
    )
    assert out["samples_considered"] == 20
    assert out["confidence"] == "ok"
    assert out["overall"]["p50"] >= 100
    assert out["filter_kind_stats"]["count"] == 20
    assert "sos" in out["by_kind"]
    ttfa_recorder.reset_buffer()


@pytest.mark.asyncio
async def test_ttfa_stats_rejects_negative_since():
    user = _user(["admin"])
    with pytest.raises(Exception) as exc:
        await _dev.alert_ttfa_stats(
            since=-1, kind=None, include_redis=False, user=user,
        )
    assert "since" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_ttfa_stats_role_gated():
    user = _user(["guardian"])
    with pytest.raises(Exception) as exc:
        await _dev.alert_ttfa_stats(
            since=3600, kind=None, include_redis=False, user=user,
        )
    assert "403" in str(exc.value) or "admin or operator" in str(exc.value)


# ── /api/_dev/twilio/sla ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_twilio_sla_red_when_not_configured(monkeypatch):
    from app.services import ttfa_recorder, sms_service
    ttfa_recorder.reset_buffer()
    monkeypatch.setattr(sms_service, "_twilio_client", None)
    user = _user(["admin"])
    out = await _dev.twilio_sla(since=3600, user=user)
    assert out["status"] == "red"
    assert any("twilio_not_configured" in r for r in out["reasons"])
    assert out["auth_ok"] is False


@pytest.mark.asyncio
async def test_twilio_sla_red_when_auth_fails(monkeypatch):
    from app.services import ttfa_recorder, sms_service
    ttfa_recorder.reset_buffer()
    fake_client = MagicMock()
    fake_client.api.accounts.return_value.fetch.side_effect = RuntimeError("HTTP 401 Authenticate")
    monkeypatch.setattr(sms_service, "_twilio_client", fake_client)
    user = _user(["operator"])
    out = await _dev.twilio_sla(since=3600, user=user)
    assert out["status"] == "red"
    assert out["auth_ok"] is False
    assert any("auth_failed" in r for r in out["reasons"])


@pytest.mark.asyncio
async def test_twilio_sla_amber_on_low_volume(monkeypatch):
    from app.services import ttfa_recorder, sms_service
    ttfa_recorder.reset_buffer()
    monkeypatch.setattr(
        "app.services.ttfa_recorder.redis_service.is_available", lambda: False
    )
    fake_client = MagicMock()
    fake_client.api.accounts.return_value.fetch.return_value = MagicMock()
    monkeypatch.setattr(sms_service, "_twilio_client", fake_client)
    user = _user(["admin"])
    out = await _dev.twilio_sla(since=3600, user=user)
    assert out["auth_ok"] is True
    assert out["status"] == "amber"
    assert any("low_sample_volume" in r for r in out["reasons"])
    ttfa_recorder.reset_buffer()


@pytest.mark.asyncio
async def test_twilio_sla_green_on_healthy_volume(monkeypatch):
    from app.services import ttfa_recorder, sms_service
    ttfa_recorder.reset_buffer()
    fake_client = MagicMock()
    fake_client.api.accounts.return_value.fetch.return_value = MagicMock()
    monkeypatch.setattr(sms_service, "_twilio_client", fake_client)
    monkeypatch.setattr(
        "app.services.ttfa_recorder.redis_service.is_available", lambda: False
    )
    # Seed 6 samples each, p95 well under thresholds (and tagged critical).
    for ms in (50, 60, 70, 80, 90, 100):
        ttfa_recorder.record(kind="twilio:sms",   ttfa_ms=ms, priority="critical")
        ttfa_recorder.record(kind="twilio:voice", ttfa_ms=ms, priority="critical")
    user = _user(["admin"])
    out = await _dev.twilio_sla(since=3600, user=user)
    assert out["auth_ok"] is True
    assert out["status"] == "green", out["reasons"]
    assert out["sms_p95"] < 2000
    assert out["voice_p95"] < 4000
    assert out["success_rate"] == 1.0
    ttfa_recorder.reset_buffer()


@pytest.mark.asyncio
async def test_twilio_sla_red_on_high_failure_rate(monkeypatch):
    from app.services import ttfa_recorder, sms_service
    ttfa_recorder.reset_buffer()
    fake_client = MagicMock()
    fake_client.api.accounts.return_value.fetch.return_value = MagicMock()
    monkeypatch.setattr(sms_service, "_twilio_client", fake_client)
    monkeypatch.setattr(
        "app.services.ttfa_recorder.redis_service.is_available", lambda: False
    )
    # Mostly failures (warning) — success rate below 95%.
    for _ in range(10):
        ttfa_recorder.record(kind="twilio:sms", ttfa_ms=200, priority="warning")
    ttfa_recorder.record(kind="twilio:sms", ttfa_ms=200, priority="critical")
    user = _user(["admin"])
    out = await _dev.twilio_sla(since=3600, user=user)
    assert out["status"] == "red"
    assert any("success_rate_below_fail" in r for r in out["reasons"])
    ttfa_recorder.reset_buffer()


@pytest.mark.asyncio
async def test_twilio_sla_rejects_invalid_since():
    user = _user(["admin"])
    with pytest.raises(Exception):
        await _dev.twilio_sla(since=10, user=user)
    with pytest.raises(Exception):
        await _dev.twilio_sla(since=99999999, user=user)


@pytest.mark.asyncio
async def test_twilio_sla_role_gated():
    user = _user(["guardian"])
    with pytest.raises(Exception) as exc:
        await _dev.twilio_sla(since=3600, user=user)
    assert "403" in str(exc.value) or "admin or operator" in str(exc.value)
