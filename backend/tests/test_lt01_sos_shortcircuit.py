"""LT-01 — SOS loadtest short-circuit invariants.

These tests lock the two-key gate so a future refactor can't accidentally
let `X-Loadtest-Token` route around the real SOS pipeline in production.

Threat model:
  * If only `X-Loadtest-Token` matters (no env gate)  → header alone bypasses SOS in prod. CRITICAL.
  * If only `LOADTEST_MODE` matters (no token check) → preview accidentally exposes bypass to anyone. HIGH.
  * If token is compared via `==` instead of constant-time → token discovery via timing. MEDIUM.

All three failure modes are tested below.
"""
from __future__ import annotations

import os

import pytest

from app.api import sos as sos_module


def _set_env(monkeypatch, mode: str | None, token: str | None) -> None:
    if mode is None:
        monkeypatch.delenv("LOADTEST_MODE", raising=False)
    else:
        monkeypatch.setenv("LOADTEST_MODE", mode)
    if token is None:
        monkeypatch.delenv("LOADTEST_TOKEN", raising=False)
    else:
        monkeypatch.setenv("LOADTEST_TOKEN", token)


def test_lt01_production_default_rejects_header(monkeypatch):
    """LOADTEST_MODE unset (production default) → header has zero effect."""
    _set_env(monkeypatch, mode=None, token=None)
    assert sos_module._loadtest_short_circuit_allowed("any-token") is False
    assert sos_module._loadtest_short_circuit_allowed("") is False
    assert sos_module._loadtest_short_circuit_allowed(None) is False


def test_lt01_mode_explicitly_false_rejects_header(monkeypatch):
    """LOADTEST_MODE=false → header has zero effect (defence in depth)."""
    _set_env(monkeypatch, mode="false", token="secret")
    assert sos_module._loadtest_short_circuit_allowed("secret") is False


def test_lt01_mode_true_but_no_token_env_rejects(monkeypatch):
    """LOADTEST_MODE=true but no LOADTEST_TOKEN env → rejected (no oracle)."""
    _set_env(monkeypatch, mode="true", token=None)
    assert sos_module._loadtest_short_circuit_allowed("any-token") is False
    assert sos_module._loadtest_short_circuit_allowed("") is False


def test_lt01_mode_true_token_set_but_no_header_rejects(monkeypatch):
    """Both env vars set but no client header → rejected."""
    _set_env(monkeypatch, mode="true", token="secret")
    assert sos_module._loadtest_short_circuit_allowed(None) is False
    assert sos_module._loadtest_short_circuit_allowed("") is False


def test_lt01_mode_true_token_mismatch_rejects(monkeypatch):
    """Both env vars set, client sends wrong token → rejected."""
    _set_env(monkeypatch, mode="true", token="secret-A")
    assert sos_module._loadtest_short_circuit_allowed("secret-B") is False
    assert sos_module._loadtest_short_circuit_allowed("secret-A-") is False
    assert sos_module._loadtest_short_circuit_allowed("-secret-A") is False


def test_lt01_mode_true_token_match_allows(monkeypatch):
    """Both env vars set, client sends matching token → allowed."""
    _set_env(monkeypatch, mode="true", token="secret-correct")
    assert sos_module._loadtest_short_circuit_allowed("secret-correct") is True


def test_lt01_case_sensitive_mode(monkeypatch):
    """LOADTEST_MODE check is .lower()=='true' — variants behave predictably."""
    _set_env(monkeypatch, mode="TRUE", token="secret")
    assert sos_module._loadtest_short_circuit_allowed("secret") is True

    _set_env(monkeypatch, mode="True", token="secret")
    assert sos_module._loadtest_short_circuit_allowed("secret") is True

    _set_env(monkeypatch, mode="yes", token="secret")
    assert sos_module._loadtest_short_circuit_allowed("secret") is False

    _set_env(monkeypatch, mode="1", token="secret")
    assert sos_module._loadtest_short_circuit_allowed("secret") is False


def test_lt01_token_compare_is_constant_time(monkeypatch):
    """Token compare uses hmac.compare_digest — no early-exit on first mismatch.

    We can't directly test timing under pytest, but we can verify the
    implementation calls hmac.compare_digest via monkeypatching it and
    asserting it was reached.
    """
    import hmac as hmac_module
    calls = []

    real_cmp = hmac_module.compare_digest

    def _wrapped(a, b):
        calls.append((a, b))
        return real_cmp(a, b)

    monkeypatch.setattr(hmac_module, "compare_digest", _wrapped)
    _set_env(monkeypatch, mode="true", token="abc123")
    sos_module._loadtest_short_circuit_allowed("abc123")
    assert calls, "_loadtest_short_circuit_allowed must call hmac.compare_digest"
    assert calls[0] == ("abc123", "abc123")
