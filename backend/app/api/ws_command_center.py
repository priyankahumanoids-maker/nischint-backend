# WebSocket endpoint for Command Center real-time incident streaming
# Pipeline: SOS Trigger → Redis Pub/Sub → WebSocket → Command Center UI
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.security import verify_token
from app.services import user_service
from app.services.event_broadcaster import broadcaster

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ws", tags=["Command Center WebSocket"])

# Active Command Center WebSocket connections
_cc_connections: set[WebSocket] = set()


async def broadcast_to_command_center(event: dict):
    """Send event to all connected Command Center clients."""
    dead = []
    for ws in _cc_connections.copy():
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _cc_connections.discard(ws)


def cc_connections_count() -> int:
    """Snapshot the number of active Command Center WebSocket connections.

    Exposed so the monitoring/runtime-info endpoint and the periodic
    sweeper can both observe the live set without importing the
    module-level global directly.
    """
    return len(_cc_connections)


async def sweep_dead_cc_connections() -> dict[str, int]:
    """REL-05 — Periodic liveness probe for `_cc_connections`.

    Iterates the set, sends a `ping` JSON frame to each socket, and
    discards any that:
      * raise WebSocketDisconnect during send,
      * raise any other Exception during send (network-level RST,
        write to a half-closed socket, etc.),
      * report `client_state != CONNECTED` after Starlette has already
        torn the socket down without our `finally` block firing.

    Returns a small stats dict so the scheduler tick can log how many
    sockets were reaped — useful for catching leak regressions early.
    """
    from starlette.websockets import WebSocketState

    probed = 0
    removed = 0
    # `.copy()` so we don't mutate the set while iterating, and so a
    # concurrent connect/disconnect doesn't trip "Set changed size
    # during iteration".
    for ws in _cc_connections.copy():
        probed += 1
        try:
            # Cheap pre-check before touching the socket — Starlette
            # marks a closed socket here long before any send call
            # would raise.
            if getattr(ws, "client_state", None) != WebSocketState.CONNECTED:
                _cc_connections.discard(ws)
                removed += 1
                continue
            # Application-level ping. The forward_events loop already
            # sends a `{"type":"ping"}` heartbeat every 25s, so this
            # uses the same envelope shape to avoid surprising the
            # client.
            await ws.send_json({
                "type": "ping",
                "source": "sweeper",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except WebSocketDisconnect:
            _cc_connections.discard(ws)
            removed += 1
        except Exception as e:
            # Any failure to write means the socket is dead from our
            # perspective. Better to drop now than wait for the next
            # broadcast attempt to discover it.
            logger.debug(f"[CC_WS_SWEEP] dropping dead socket: {e}")
            _cc_connections.discard(ws)
            removed += 1
    if removed:
        logger.info(
            f"[CC_WS_SWEEP] swept probed={probed} removed={removed} "
            f"remaining={len(_cc_connections)}"
        )
    return {
        "probed": probed,
        "removed": removed,
        "remaining": len(_cc_connections),
    }


@router.websocket("/command-center")
async def ws_command_center(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
):
    """
    Dedicated WebSocket for Command Center real-time incident streaming.
    Connect: wss://host/api/ws/command-center?token=<jwt>
    Only accepts admin/operator connections.
    """
    if not token:
        await websocket.close(code=4001, reason="Token required")
        return

    user_id = verify_token(token)
    if not user_id:
        await websocket.close(code=4001, reason="Invalid token")
        return

    from app.db.session import async_session as async_session_factory
    async with async_session_factory() as session:
        try:
            user = await user_service.get_user_by_id(session, UUID(user_id))
        except (ValueError, Exception):
            await websocket.close(code=4001, reason="Invalid user")
            return
        if not user:
            await websocket.close(code=4001, reason="User not found")
            return
        role = user.role or "guardian"

    if role not in ("operator", "admin"):
        await websocket.close(code=4003, reason="Unauthorized: operator/admin only")
        return

    await websocket.accept()
    _cc_connections.add(websocket)
    logger.info(f"Command Center WS connected: user={user_id}, active={len(_cc_connections)}")

    channel = broadcaster.operator_channel()
    queue = await broadcaster.subscribe(channel)

    try:
        await websocket.send_json({
            "type": "connected",
            "data": {
                "channel": "command-center",
                "user_id": user_id,
                "role": role,
                "active_connections": len(_cc_connections),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        await broadcaster.unsubscribe(channel, queue)
        _cc_connections.discard(websocket)
        return

    async def forward_events():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25.0)
                    event_type = event.get("type", "")
                    if event_type in (
                        "sos_triggered", "incident_created", "incident_updated",
                        "emergency_triggered", "emergency_location_update",
                        "emergency_cancelled", "emergency_resolved",
                        "risk_score_change", "session_alert",
                        "sos_resolved", "location_update",
                        "SOS_ALERT",
                        "live_tracking_started", "live_tracking_ended",
                        "tracking_stop_detected", "tracking_deviation",
                        "safe_zone_exit", "unknown_area_entry",
                        "safe_zone_arrival", "danger_zone_entry",
                        # Phase 2 — events previously routed via SSE only
                        "safety_risk_alert", "fake_call_incoming",
                        # Phase 3 — live Digital Twin deviation deltas
                        "twin_delta",
                        # Phase 5 — canonical structured delta envelope
                        "COMMAND_CENTER_DELTA",
                        # Phase 7 — fleet change summary (perception layer)
                        "FLEET_CHANGE_SUMMARY",
                    ):
                        await websocket.send_json(event)
                except asyncio.TimeoutError:
                    await websocket.send_json({
                        "type": "ping",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
        except (WebSocketDisconnect, Exception):
            pass

    async def receive_messages():
        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type", "")
                if msg_type == "pong":
                    continue
                elif msg_type == "request_ai_response":
                    incident_data = data.get("data", {})
                    ai_response = await _generate_ai_suggestions(incident_data)
                    await websocket.send_json({
                        "type": "ai_response",
                        "data": ai_response,
                        "incident_id": data.get("incident_id"),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                elif msg_type == "ack_incident":
                    logger.info(f"CC: Incident acked by {user_id}: {data.get('incident_id')}")
        except (WebSocketDisconnect, Exception):
            pass

    try:
        await asyncio.gather(forward_events(), receive_messages(), return_exceptions=True)
    finally:
        await broadcaster.unsubscribe(channel, queue)
        _cc_connections.discard(websocket)
        logger.info(f"Command Center WS disconnected: user={user_id}, remaining={len(_cc_connections)}")


@router.get("/command-center/status")
async def cc_ws_status():
    """Get Command Center WebSocket connection stats."""
    return {
        "active_connections": len(_cc_connections),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def _generate_ai_suggestions(incident_data: dict) -> dict:
    """Generate AI suggested response actions for an incident."""
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage

        api_key = os.environ.get("EMERGENT_LLM_KEY")
        if not api_key:
            from app.core.config import settings
            api_key = settings.emergent_llm_key
        if not api_key:
            return _fallback_suggestions()

        chat = LlmChat(
            api_key=api_key,
            session_id=f"cc-ai-{datetime.now(timezone.utc).strftime('%H%M%S')}",
            system_message=(
                "You are a safety operations AI for NISCHINT child safety platform. "
                "Generate exactly 3 concise, actionable safety recommendations. "
                "Return ONLY a JSON array of 3 objects with 'action' (string, max 60 chars) "
                "and 'priority' (1-3) keys. No markdown, no explanation."
            ),
        ).with_model("openai", "gpt-5.2")

        risk_score = incident_data.get("risk_score", 7.0)
        user_name = incident_data.get("user_name", "Unknown")
        lat = incident_data.get("lat", "unknown")
        lng = incident_data.get("lng", "unknown")

        prompt = (
            f"SOS Emergency triggered. User: {user_name}. "
            f"Location: ({lat}, {lng}). Risk Score: {risk_score}/10. "
            f"Generate 3 response actions as JSON array."
        )

        from app.services.ai_metrics import track
        async with track("ws_command_center.sos_response"):
            response = await chat.send_message(UserMessage(text=prompt))
        text = response.strip()
        if "```" in text:
            parts = text.split("```")
            if len(parts) >= 3:
                inner = parts[1]
                if inner.startswith("json"):
                    inner = inner[4:]
                text = inner.strip()

        actions = json.loads(text)
        return {"actions": actions[:3], "source": "ai"}
    except Exception as e:
        logger.warning(f"AI suggestion generation failed: {e}")
        return _fallback_suggestions()


def _fallback_suggestions() -> dict:
    return {
        "actions": [
            {"action": "Contact guardians immediately", "priority": 1},
            {"action": "Start live location monitoring", "priority": 2},
            {"action": "Notify nearby trusted contacts", "priority": 3},
        ],
        "source": "rule_based",
    }
