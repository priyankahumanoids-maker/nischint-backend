# Phase 5 — Command Center Delta Emitter unit tests
import asyncio
from unittest.mock import AsyncMock, patch

from app.services.cc_delta_emitter import (
    DELTA_VERSION,
    diff_paths,
    emit_cc_delta,
    emit_namespaced_delta,
)


def _run(coro):
    return asyncio.run(coro)


def test_diff_paths_detects_changed_leaves():
    old = {"a": 1, "b": {"c": 2, "d": 3}}
    new = {"a": 1, "b": {"c": 99, "d": 3}, "e": 4}
    out = diff_paths(old, new)
    assert out == {"b.c": 99, "e": 4}


def test_diff_paths_include_only_filters_namespaces():
    old = {"risk": {"score": 1}, "live_deviation": {"status": "normal"}}
    new = {"risk": {"score": 5}, "live_deviation": {"status": "high"}}
    out = diff_paths(old, new, include_only=["risk"])
    assert out == {"risk.score": 5}


def test_diff_paths_returns_empty_when_unchanged():
    payload = {"risk": {"score": 1, "level": "low"}}
    assert diff_paths(payload, payload) == {}


def test_diff_paths_handles_none_old():
    new = {"risk": {"score": 1}}
    assert diff_paths(None, new) == {"risk.score": 1}


def test_emit_cc_delta_skips_empty_changes():
    with patch("app.services.cc_delta_emitter.broadcaster") as mock_b:
        mock_b.broadcast_to_operators = AsyncMock()
        result = _run(emit_cc_delta("u1", {}))
        assert result is False
        mock_b.broadcast_to_operators.assert_not_called()


def test_emit_cc_delta_publishes_envelope():
    with patch("app.services.cc_delta_emitter.broadcaster") as mock_b:
        mock_b.broadcast_to_operators = AsyncMock()
        _run(emit_cc_delta("user-1", {"risk.final_score": 7.5}))
        mock_b.broadcast_to_operators.assert_awaited_once()
        args, _ = mock_b.broadcast_to_operators.call_args
        assert args[0] == "COMMAND_CENTER_DELTA"
        envelope = args[1]
        assert envelope["version"] == DELTA_VERSION
        assert envelope["user_id"] == "user-1"
        assert envelope["changes"] == {"risk.final_score": 7.5}
        assert "timestamp" in envelope


def test_emit_namespaced_delta_no_change_skips():
    state = {"final_score": 7.5, "risk_level": "high"}
    with patch("app.services.cc_delta_emitter.get_state_slice", return_value=state), \
         patch("app.services.cc_delta_emitter.cache_state_slice") as mock_cache, \
         patch("app.services.cc_delta_emitter.broadcaster") as mock_b:
        mock_b.broadcast_to_operators = AsyncMock()
        out = _run(emit_namespaced_delta("u2", "risk", state))
        assert out is False
        mock_b.broadcast_to_operators.assert_not_called()
        mock_cache.assert_not_called()


def test_emit_namespaced_delta_only_emits_changed_paths():
    prev = {"final_score": 1.0, "risk_level": "low"}
    new = {"final_score": 7.5, "risk_level": "low"}  # only score changed
    with patch("app.services.cc_delta_emitter.get_state_slice", return_value=prev), \
         patch("app.services.cc_delta_emitter.cache_state_slice"), \
         patch("app.services.cc_delta_emitter.broadcaster") as mock_b:
        mock_b.broadcast_to_operators = AsyncMock()
        out = _run(emit_namespaced_delta("u3", "risk", new))
        assert out is True
        envelope = mock_b.broadcast_to_operators.call_args.args[1]
        assert envelope["changes"] == {"risk.final_score": 7.5}
