# Real-Time Event System — WebSocket gateway + Event pipeline
# Supports both SSE (existing) and WebSocket connections
# Event Pipeline: Signal → Risk Engine → Event Broker → Push + WS + SSE + Command Center
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.security import verify_token
from app.models.user import User
from app.services import user_service
from app.services.event_broadcaster import broadcaster

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ws", tags=["WebSocket"])


# ── WebSocket Connection Manager ──

class ConnectionManager:
    """Manages active WebSocket connections per user/role."""

    def __init__(self):
        self._user_connections: dict[str, set[WebSocket]] = {}
        self._role_connections: dict[str, set[WebSocket]] = {}

    async def connect(self, ws: WebSocket, user_id: str, role: str):
        await ws.accept()
        if user_id not in self._user_connections:
            self._user_connections[user_id] = set()
        self._user_connections[user_id].add(ws)

        if role in ("operator", "admin"):
            if role not in self._role_connections:
                self._role_connections[role] = set()
            self._role_connections[role].add(ws)

        logger.info(f"WS connected: user={user_id} role={role}")

    def disconnect(self, ws: WebSocket, user_id: str, role: str):
        if user_id in self._user_connections:
            self._user_connections[user_id].discard(ws)
            if not self._user_connections[user_id]:
                del self._user_connections[user_id]
        if role in self._role_connections:
            self._role_connections[role].discard(ws)
            if not self._role_connections[role]:
                del self._role_connections[role]
        logger.info(f"WS disconnected: user={user_id}")

    def total_connections(self) -> int:
        """REL-05 — Unique-WebSocket count across both user and role
        registries. Same socket can be in both, so we union the sets
        before counting.
        """
        seen: set = set()
        for s in self._user_connections.values():
            seen.update(s)
        for s in self._role_connections.values():
            seen.update(s)
        return len(seen)

    async def send_to_user(self, user_id: str, event: dict):
        dead = []
        for ws in self._user_connections.get(user_id, set()):
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._user_connections.get(user_id, set()).discard(ws)

    async def send_to_role(self, role: str, event: dict):
        dead = []
        for ws in self._role_connections.get(role, set()):
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._role_connections.get(role, set()).discard(ws)

    @property
    def active_count(self):
        return sum(len(v) for v in self._user_connections.values())


ws_manager = ConnectionManager()


# ── WebSocket Endpoint ──

@router.websocket("/events")
async def ws_events(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
):
    """
    WebSocket endpoint for real-time events.
    Connect: ws://host/api/ws/events?token=<jwt>

    Sends JSON events:
    {
        "type": "risk_score_change",
        "data": {...},
        "timestamp": "..."
    }
    """
    if not token:
        await websocket.close(code=4001, reason="Token required")
        return

    user_id = verify_token(token)
    if not user_id:
        await websocket.close(code=4001, reason="Invalid token")
        return

    # Get user from DB
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

    await ws_manager.connect(websocket, user_id, role)

    # Subscribe to the event broadcaster
    if role in ("operator", "admin"):
        channel = broadcaster.operator_channel()
    else:
        channel = broadcaster.user_channel(user_id)

    queue = await broadcaster.subscribe(channel)

    # Send connected confirmation
    try:
        await websocket.send_json({
            "type": "connected",
            "data": {"channel": channel, "user_id": user_id, "role": role},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        await broadcaster.unsubscribe(channel, queue)
        ws_manager.disconnect(websocket, user_id, role)
        return

    # Bridge: broadcaster queue → websocket
    async def forward_events():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    await websocket.send_json(event)
                except asyncio.TimeoutError:
                    # Send ping to keep connection alive
                    await websocket.send_json({
                        "type": "ping",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
        except (WebSocketDisconnect, Exception):
            pass

    # Listen for client messages (e.g., location updates, acknowledgements)
    async def receive_messages():
        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type", "")

                if msg_type == "pong":
                    continue  # keepalive response
                elif msg_type == "location_update":
                    # Broadcast location to guardians + operators
                    await broadcaster.broadcast_to_operators("location_update", {
                        "user_id": user_id,
                        "location": data.get("location"),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                elif msg_type == "ack_alert":
                    logger.info(f"Alert acknowledged by {user_id}: {data.get('alert_id')}")
                else:
                    logger.debug(f"WS message from {user_id}: {msg_type}")
        except (WebSocketDisconnect, Exception):
            pass

    try:
        # Run both tasks concurrently
        await asyncio.gather(forward_events(), receive_messages(), return_exceptions=True)
    finally:
        await broadcaster.unsubscribe(channel, queue)
        ws_manager.disconnect(websocket, user_id, role)


# ── Event Pipeline Functions ──
# These are called by services to trigger the full notification chain

async def emit_risk_score_change(user_id: str, score: float, level: str, factors: list):
    """Risk score changed → notify guardians + command center."""
    event_data = {
        "user_id": user_id,
        "risk_score": score,
        "risk_level": level,
        "top_factors": factors[:3],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # 1. Notify via broadcaster (SSE + in-memory)
    await broadcaster.broadcast_to_user(user_id, "risk_score_change", event_data)
    await broadcaster.broadcast_to_operators("risk_score_change", event_data)

    # 2. Notify via WebSocket
    await ws_manager.send_to_user(user_id, {"type": "risk_score_change", "data": event_data})
    await ws_manager.send_to_role("operator", {"type": "risk_score_change", "data": event_data})
    await ws_manager.send_to_role("admin", {"type": "risk_score_change", "data": event_data})

    # 3. Push notification for high/critical
    if level in ("high", "critical"):
        await _push_to_guardian_network(user_id, "risk_alert", event_data)


async def emit_location_update(user_id: str, lat: float, lng: float, session_id: str):
    """Location update → notify guardians (during active session)."""
    event_data = {
        "user_id": user_id,
        "session_id": session_id,
        "location": {"lat": lat, "lng": lng},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await broadcaster.broadcast_to_user(user_id, "location_update", event_data)
    await broadcaster.broadcast_to_operators("location_update", event_data)
    await ws_manager.send_to_role("operator", {"type": "location_update", "data": event_data})


async def emit_sos_triggered(user_id: str, sos_data: dict):
    """SOS triggered → highest priority notification to everyone."""
    event_data = {
        "user_id": user_id,
        **sos_data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await broadcaster.broadcast_to_user(user_id, "sos_triggered", event_data)
    await broadcaster.broadcast_to_operators("sos_triggered", event_data)
    await ws_manager.send_to_user(user_id, {"type": "sos_triggered", "data": event_data})
    await ws_manager.send_to_role("operator", {"type": "sos_triggered", "data": event_data})
    await ws_manager.send_to_role("admin", {"type": "sos_triggered", "data": event_data})
    await _push_to_guardian_network(user_id, "sos_emergency", event_data)


async def emit_incident_created(user_id: str, incident_data: dict):
    """New incident → notify guardians + operators."""
    await broadcaster.broadcast_to_user(user_id, "incident_created", incident_data)
    await broadcaster.broadcast_to_operators("incident_created", incident_data)
    await ws_manager.send_to_role("operator", {"type": "incident_created", "data": incident_data})


async def emit_session_alert(user_id: str, alert_data: dict):
    """Session alert (geofence breach, idle timeout, etc.)."""
    await broadcaster.broadcast_to_user(user_id, "session_alert", alert_data)
    await broadcaster.broadcast_to_operators("session_alert", alert_data)
    await ws_manager.send_to_user(user_id, {"type": "session_alert", "data": alert_data})
    await ws_manager.send_to_role("operator", {"type": "session_alert", "data": alert_data})

    severity = alert_data.get("severity", "medium")
    if severity in ("high", "critical"):
        await _push_to_guardian_network(user_id, "safety_alert", alert_data)


# ── Push Notification Helper ──

async def _push_to_guardian_network(user_id: str, notification_type: str, data: dict):
    """Send push notifications to all guardians in the user's network."""
    from app.models.guardian_network import GuardianRelationship
    from app.db.session import async_session as async_session_factory
    from sqlalchemy import select, and_

    try:
        async with async_session_factory() as session:
            guardians = (await session.execute(
                select(GuardianRelationship)
                .where(and_(
                    GuardianRelationship.user_id == UUID(user_id),
                    GuardianRelationship.is_active == True,
                ))
                .order_by(GuardianRelationship.priority)
            )).scalars().all()

            for g in guardians:
                if "push" in (g.notification_channels or []) and g.guardian_user_id:
                    # Send via broadcaster to the guardian's user channel
                    await broadcaster.broadcast_to_user(
                        str(g.guardian_user_id),
                        notification_type,
                        {**data, "guardian_name": g.guardian_name, "relationship": g.relationship_type},
                    )
                    # Also via WebSocket
                    await ws_manager.send_to_user(
                        str(g.guardian_user_id),
                        {"type": notification_type, "data": {**data, "guardian_name": g.guardian_name}},
                    )

                logger.info(f"Push notification sent to guardian {g.guardian_name} ({notification_type})")

    except Exception as e:
        logger.warning(f"Failed to push to guardian network: {e}")


# ── Status endpoint ──

@router.get("/status")
async def ws_status():
    """Get WebSocket connection stats."""
    return {
        "active_connections": ws_manager.active_count,
        "broadcaster_channels": len(broadcaster._subscribers),
    }
