# Twin Delta Broadcaster — Phase 3
#
# Computes live deviation from the user's baseline + active session signals,
# debounces against the last broadcast (Redis-cached), and pushes a
# `twin_delta` event to the operator WebSocket when status changes.
#
# Event payload shape (matches the `digital_twin.live_deviation` slot in the
# v1 unified envelope):
#   {
#     "type": "twin_delta",
#     "data": {
#       "user_id": "<uuid>",
#       "live_deviation": {status, score, confidence, reason, factors, computed_at},
#       "live_location": { lat, lng, ... } | None
#     }
#   }
#
# Designed to be cheap: pure-function compute, single Redis GET/SET, single
# fire-and-forget WS broadcast. Safe to call on every location tick.

import logging
import uuid as uuid_mod
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.live_deviation_engine import compute_live_deviation
from app.services import redis_service
from app.services.guardian_ai_refinement import get_or_create_baseline

logger = logging.getLogger(__name__)

REDIS_NAMESPACE = "twin_state"
REDIS_TTL_SECONDS = 6 * 60 * 60  # 6h — re-broadcast after a long quiet period


async def maybe_broadcast_twin_delta(
    session: AsyncSession,
    user_id: uuid_mod.UUID,
    *,
    lat: Optional[float],
    lng: Optional[float],
    route_deviated: bool = False,
    route_deviation_m: float = 0.0,
    is_idle: bool = False,
    idle_duration_s: float = 0.0,
) -> Optional[dict]:
    """
    Compute live deviation and broadcast `twin_delta` over WS only when the
    status string changes (e.g. normal → slight → high). Returns the
    deviation dict if broadcast, else None.
    """
    try:
        baseline = await get_or_create_baseline(session, user_id)
    except Exception:
        logger.exception("[TWIN_DELTA] baseline fetch failed for %s", user_id)
        return None

    deviation = compute_live_deviation(
        baseline,
        lat=lat,
        lng=lng,
        now=datetime.now(timezone.utc),
        route_deviated=route_deviated,
        route_deviation_m=route_deviation_m,
        is_idle=is_idle,
        idle_duration_s=idle_duration_s,
    )

    new_status = deviation.get("status") or "unknown"

    # Debounce: skip broadcast unless the status changed since last tick.
    prev_status = redis_service.get_json(REDIS_NAMESPACE, str(user_id))
    if isinstance(prev_status, dict):
        prev_status = prev_status.get("status")

    if prev_status == new_status:
        return None  # No change — skip broadcast

    # Update cache (small dict so future enrichments are easy)
    redis_service.set_json(
        REDIS_NAMESPACE,
        str(user_id),
        {"status": new_status, "score": deviation.get("score"), "ts": deviation.get("computed_at")},
        ttl=REDIS_TTL_SECONDS,
    )

    # Fire structured COMMAND_CENTER_DELTA envelope (Phase 5).
    # Only the changed dotted paths under `live_deviation` are emitted.
    try:
        from app.services.cc_delta_emitter import emit_namespaced_delta
        await emit_namespaced_delta(str(user_id), "live_deviation", deviation)
        logger.info(
            "[TWIN_DELTA] user=%s status=%s→%s score=%.3f",
            user_id, prev_status, new_status, deviation.get("score") or 0.0,
        )
    except Exception:
        logger.exception("[TWIN_DELTA] broadcast failed for %s", user_id)

    return deviation
