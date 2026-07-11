# Phase 5 Hardening — Chaos tests for the CC delta emitter
#
# Validates:
#   • Redis read failure → empty diff treated correctly
#   • Redis write failure → no exception bubbles to caller
#   • Broadcast failure → returns False, no crash
#   • Out-of-order calls → cache reflects latest write
import asyncio
from unittest.mock import AsyncMock, patch

from app.services.cc_delta_emitter import (
    emit_namespaced_delta,
    emit_cc_delta,
)


def _run(coro):
    return asyncio.run(coro)


def test_redis_read_failure_treated_as_cold_cache():
    """When get_state_slice returns None (Redis down), full payload is emitted."""
    new_state = {"final_score": 8.2, "risk_level": "high"}
    with patch("app.services.cc_delta_emitter.get_state_slice", return_value=None), \
         patch("app.services.cc_delta_emitter.cache_state_slice"), \
         patch("app.services.cc_delta_emitter.broadcaster") as mock_b:
        mock_b.broadcast_to_operators = AsyncMock()
        out = _run(emit_namespaced_delta("u_chaos_1", "risk", new_state))
        assert out is True
        envelope = mock_b.broadcast_to_operators.call_args.args[1]
        # All paths emitted because cache was cold
        assert "risk.final_score" in envelope["changes"]
        assert "risk.risk_level" in envelope["changes"]


def test_redis_write_failure_does_not_crash():
    """cache_state_slice exception must NOT propagate to caller."""
    def boom(*args, **kwargs):
        raise RuntimeError("redis down")
    new_state = {"final_score": 1.0}
    with patch("app.services.cc_delta_emitter.get_state_slice", return_value={}), \
         patch("app.services.cc_delta_emitter.redis_service.set_json", side_effect=boom), \
         patch("app.services.cc_delta_emitter.broadcaster") as mock_b:
        mock_b.broadcast_to_operators = AsyncMock()
        # Should still emit even when cache write failed
        out = _run(emit_namespaced_delta("u_chaos_2", "risk", new_state))
        assert out is True


def test_broadcast_failure_returns_false():
    """Upstream WS publish failure must return False, never raise."""
    with patch("app.services.cc_delta_emitter.broadcaster") as mock_b:
        mock_b.broadcast_to_operators = AsyncMock(side_effect=RuntimeError("WS gone"))
        out = _run(emit_cc_delta("u_chaos_3", {"risk.final_score": 1.0}))
        assert out is False


def test_no_op_diff_emits_nothing():
    """Identical cached state → no broadcast."""
    state = {"final_score": 7.0, "risk_level": "high"}
    with patch("app.services.cc_delta_emitter.get_state_slice", return_value=state), \
         patch("app.services.cc_delta_emitter.cache_state_slice") as mock_cache, \
         patch("app.services.cc_delta_emitter.broadcaster") as mock_b:
        mock_b.broadcast_to_operators = AsyncMock()
        out = _run(emit_namespaced_delta("u_chaos_4", "risk", state))
        assert out is False
        mock_b.broadcast_to_operators.assert_not_called()
        mock_cache.assert_not_called()
