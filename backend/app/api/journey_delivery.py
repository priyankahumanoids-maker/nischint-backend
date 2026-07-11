"""
NISCHINT Journey Engine — Real Delivery Layer

Responsibilities:
    • Delivery Guard — gate real dispatch behind JOURNEY_LIVE_DELIVERY flag + rate limits
    • Real SMS via Twilio (reuses app.services.sms_service.send_sms)
    • Real Push via FCM (reuses app.services.push_service.send_push_to_tokens)

Modes:
    Simulator (default): logs only, no real SMS/Push sent — safe for dev/preview
    Live: flag=true → real dispatch with per-session rate limiting

Rate limit:
    Max N SOS deliveries per session_id per rolling hour (JOURNEY_MAX_SOS_PER_HOUR).
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)

# Rate limiter: session_id -> deque of timestamps (seconds) within rolling 1h window
_sos_rate: Dict[str, deque] = defaultdict(deque)
RATE_WINDOW_SEC = 3600
# SMS dedup: (sos_id, phone) -> ts (prevent duplicate SMS within 60s)
_sms_dedup: Dict[Tuple[str, str], float] = {}
SMS_DEDUP_WINDOW_SEC = 60


def is_live() -> bool:
    return bool(settings.journey_live_delivery)


def can_deliver(session_id: Optional[str]) -> Tuple[bool, str]:
    """
    Delivery Guard — 4-layer gate:
      1. KILL SWITCH (emergency_stop in rollout config) — overrides everything
      2. Global live flag (JOURNEY_LIVE_DELIVERY env)
      3. Session allowlist (rollout allowlist)
      4. Rate limit (per-session hourly)

    Returns (allowed, reason).
    """
    # 1. Kill switch (highest priority, even higher than live flag)
    try:
        from app.api import journey_rollout
        cfg = journey_rollout._config_cache
        if cfg.get("emergency_stop"):
            return False, "emergency_stop"
    except Exception:
        pass  # rollout module unavailable → fall through

    # 2. Global live flag
    if not is_live():
        return False, "simulator_mode"

    if not session_id:
        return False, "no_session_id"

    # 3. Session allowlist
    try:
        from app.api import journey_rollout as _r
        gate = _r.rollout_gate(session_id)
        if not gate["allowed"]:
            return False, gate["reason"]
    except Exception as e:
        logger.error(f"[DELIVERY_GUARD] allowlist check failed: {e}")
        return False, "allowlist_error"

    # 4. Rate limit
    now = time.time()
    q = _sos_rate[session_id]
    while q and q[0] < now - RATE_WINDOW_SEC:
        q.popleft()
    if len(q) >= settings.journey_max_sos_per_hour:
        return False, f"rate_limited({len(q)}/{settings.journey_max_sos_per_hour}_per_hour)"

    q.append(now)
    return True, "ok"


def _sms_is_dup(sos_id: str, phone: str) -> bool:
    key = (sos_id, phone)
    now = time.time()
    last = _sms_dedup.get(key)
    if last and now - last < SMS_DEDUP_WINDOW_SEC:
        return True
    _sms_dedup[key] = now
    # Prune
    if len(_sms_dedup) > 500:
        for k, t in list(_sms_dedup.items()):
            if now - t > SMS_DEDUP_WINDOW_SEC * 5:
                _sms_dedup.pop(k, None)
    return False


# ── SMS (real, sync — Twilio) ──

def send_sms_real(sos_id: str, phone: str, body: str) -> Dict[str, Any]:
    """
    Send a real SMS via Twilio (or log-only in simulator mode).
    Returns dict {status, provider, dedup?, error?}.
    """
    if not phone:
        return {"status": "skipped", "reason": "no_phone"}
    if _sms_is_dup(sos_id, phone):
        return {"status": "skipped", "reason": "dedup"}

    if not is_live():
        logger.info(f"[SMS_SIM] sos={sos_id} to={phone} body={body[:60]}")
        return {"status": "simulated", "provider": "stub"}

    try:
        from app.services.sms_service import send_sms, is_available
        if not is_available():
            logger.warning(f"[SMS_LIVE] Twilio not configured, falling back to log: sos={sos_id}")
            return {"status": "failed", "reason": "twilio_unconfigured"}
        ok = send_sms(phone, body)
        if ok:
            logger.warning(f"[SMS_LIVE] Dispatched sos={sos_id} to={phone}")
            return {"status": "sent", "provider": "twilio"}
        return {"status": "failed", "provider": "twilio"}
    except Exception as e:
        logger.error(f"[SMS_LIVE_ERROR] sos={sos_id} to={phone}: {e}")
        return {"status": "error", "error": str(e)}


# ── PUSH (real, async — FCM) ──

def _run_coro(coro):
    """Run an async coroutine from a sync context safely."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Schedule without blocking
            asyncio.ensure_future(coro)
            return {"status": "dispatched"}
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def send_push_real(sos_id: str, tokens: List[str], title: str, body: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Send a real FCM push (or log-only in simulator mode).
    Returns dict {status, sent?, tokens?}.
    """
    tokens = [t for t in (tokens or []) if t]
    if not tokens:
        return {"status": "skipped", "reason": "no_tokens"}

    if not is_live():
        logger.info(f"[PUSH_SIM] sos={sos_id} tokens={len(tokens)} title={title}")
        return {"status": "simulated", "tokens": len(tokens)}

    try:
        from app.services.push_service import send_push_to_tokens
        merged_data = {"sos_id": sos_id, **(data or {})}
        result = _run_coro(send_push_to_tokens(tokens, title, body, merged_data, channel_id="safety-alerts"))
        if isinstance(result, int):
            logger.warning(f"[PUSH_LIVE] Dispatched sos={sos_id} sent={result}/{len(tokens)}")
            return {"status": "sent", "sent": result, "tokens": len(tokens)}
        return {"status": "dispatched", "tokens": len(tokens)}
    except Exception as e:
        logger.error(f"[PUSH_LIVE_ERROR] sos={sos_id}: {e}")
        return {"status": "error", "error": str(e)}


# ── Status helper (for dashboard) ──

def delivery_status() -> Dict[str, Any]:
    now = time.time()
    active_sessions = {}
    for sid, q in _sos_rate.items():
        while q and q[0] < now - RATE_WINDOW_SEC:
            q.popleft()
        if q:
            active_sessions[sid] = len(q)
    # Rollout state
    rollout = {}
    try:
        from app.api import journey_rollout as _r
        cfg = _r._config_cache
        rollout = {
            "emergency_stop": bool(cfg.get("emergency_stop")),
            "current_stage": cfg.get("current_stage"),
            "allowlisted_sessions": sum(1 for r in _r._allowlist_cache.values() if r.get("enabled")),
        }
    except Exception:
        rollout = {"emergency_stop": False, "current_stage": None, "allowlisted_sessions": 0}
    return {
        "live": is_live(),
        "max_per_hour": settings.journey_max_sos_per_hour,
        "require_verified_user": settings.journey_require_verified_user,
        "mongo_enabled_flag": settings.journey_mongo_enabled,
        "active_sessions_in_window": active_sessions,
        "sms_dedup_cache_size": len(_sms_dedup),
        "rollout": rollout,
    }
