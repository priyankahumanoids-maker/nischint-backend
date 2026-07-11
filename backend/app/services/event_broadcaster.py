# Event Broadcaster for SSE — Redis Streams backed with in-memory fallback
#
# Architecture:
#   publish() → Redis Stream (XADD) → _stream_listener (XREADGROUP) → local asyncio queues → SSE clients
#   If Redis unavailable: publish() → local asyncio queues directly (single-process)
#
#   REPLAY: Recent events stored per-channel (5 min ring buffer).
#   On SSE reconnect, missed events are replayed immediately.
import asyncio
import json
import logging
import threading
import time as _time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, Set
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

_USER_PREFIX = "user:"
_ROLE_PREFIX = "role:"
_REPLAY_WINDOW_S = 300  # 5 minutes — keep events for replay
_REPLAY_MAX_PER_CHANNEL = 50  # max events stored per channel


class EventBroadcaster:
    """
    SSE event broadcaster with Redis Streams backing + replay buffer.
    Supports scoped channels:
      - user:{user_id}  — guardian sees their own events
      - role:operator    — operators see all events
    """

    def __init__(self):
        self._subscribers: Dict[str, Set[asyncio.Queue]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._redis_listener_started = False
        # Replay buffer: channel → deque of (timestamp, event_dict)
        self._replay_buffer: Dict[str, deque] = defaultdict(lambda: deque(maxlen=_REPLAY_MAX_PER_CHANNEL))
        self._replay_lock = asyncio.Lock()

    # ── Subscribe / Unsubscribe ──

    async def subscribe(self, channel: str) -> asyncio.Queue:
        queue = asyncio.Queue()
        async with self._lock:
            self._subscribers[channel].add(queue)
            logger.info(f"Subscribed to {channel}. Active: {len(self._subscribers[channel])}")
        return queue

    async def unsubscribe(self, channel: str, queue: asyncio.Queue):
        async with self._lock:
            self._subscribers[channel].discard(queue)
            if not self._subscribers[channel]:
                del self._subscribers[channel]
            logger.info(f"Unsubscribed from {channel}")

    # ── Replay: get missed events for a channel ──

    async def get_replay_events(self, channel: str, max_age_s: float = _REPLAY_WINDOW_S) -> list[dict]:
        """Return recent events for replay on SSE reconnect."""
        cutoff = _time.time() - max_age_s
        async with self._replay_lock:
            buf = self._replay_buffer.get(channel, deque())
            events = [evt for ts, evt in buf if ts > cutoff]
        if events:
            logger.info(f"[SSE_REPLAY] {len(events)} events for {channel} (window={max_age_s}s)")
        return events

    async def _store_for_replay(self, channel: str, event: dict):
        """Store event in replay buffer."""
        now = _time.time()
        async with self._replay_lock:
            buf = self._replay_buffer[channel]
            buf.append((now, event))
            # Prune old entries
            cutoff = now - _REPLAY_WINDOW_S
            while buf and buf[0][0] < cutoff:
                buf.popleft()

    # ── Internal: deliver to local asyncio queues ──

    async def _deliver(self, channel: str, event: dict):
        # Always store for replay (even if 0 subscribers — they'll get it on reconnect)
        await self._store_for_replay(channel, event)

        async with self._lock:
            subscribers = self._subscribers.get(channel, set()).copy()
        for queue in subscribers:
            try:
                await queue.put(event)
            except Exception as e:
                logger.error(f"Error delivering to {channel}: {e}")
        event_type = event.get('type', '?')
        if subscribers:
            logger.info(f"[SSE_DELIVERY] OK {event_type} → {len(subscribers)} subscriber(s) on {channel}")
        else:
            logger.warning(f"[SSE_DELIVERY] QUEUED {event_type} for replay on {channel} (0 live subscribers)")

    # ── Publish (local delivery only — single-process deployment) ──

    async def _publish(self, channel: str, event_type: str, data: dict):
        event = {
            "id": str(uuid4()),
            "type": event_type,
            "channel": channel,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Deliver to local subscribers (same-process SSE clients)
        await self._deliver(channel, event)

    # ── Redis Streams Listener (background thread → asyncio loop bridge) ──

    def start_redis_listener(self, loop: asyncio.AbstractEventLoop):
        """Start background thread that consumes from Redis Stream and bridges to asyncio."""
        if self._redis_listener_started:
            return

        from app.services.redis_service import (
            ensure_stream_group, stream_read, stream_ack, is_available,
        )

        def _listener():
            import time
            backoff = 2
            max_backoff = 60

            while True:
                if not is_available():
                    logger.info("Redis unavailable — using in-memory broadcast only")
                    time.sleep(max_backoff)
                    continue

                # Ensure consumer group exists
                if not ensure_stream_group():
                    time.sleep(backoff)
                    backoff = min(backoff * 2, max_backoff)
                    continue

                logger.info("Redis Stream consumer started (group=nischint_guardians)")
                consecutive_timeouts = 0

                try:
                    while True:
                        # Use 1000ms block to stay under Upstash connection timeout
                        entries = stream_read(count=10, block_ms=1000)
                        if entries:
                            consecutive_timeouts = 0
                            for event_id, fields in entries:
                                try:
                                    payload_raw = fields.get("payload", "{}")
                                    event = json.loads(payload_raw)
                                    channel = event.get("channel", fields.get("channel", ""))
                                    asyncio.run_coroutine_threadsafe(
                                        self._deliver(channel, event), loop
                                    )
                                    stream_ack(event_id)
                                except Exception as e:
                                    logger.error(f"Redis Stream parse error for {event_id}: {e}")
                                    stream_ack(event_id)
                        else:
                            consecutive_timeouts += 1
                            # Sleep between empty polls to reduce connection pressure
                            if consecutive_timeouts > 5:
                                time.sleep(2)
                except Exception as e:
                    # Only log at warning level occasionally, not every 3 seconds
                    if backoff <= 4:
                        logger.warning(f"Redis Stream listener disconnected: {e}")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, max_backoff)

        thread = threading.Thread(target=_listener, daemon=True, name="redis-stream")
        thread.start()
        self._redis_listener_started = True

    # ── Public broadcast helpers ──

    async def broadcast_to_user(self, user_id: str, event_type: str, data: dict):
        await self._publish(f"{_USER_PREFIX}{user_id}", event_type, data)

    async def broadcast_to_operators(self, event_type: str, data: dict):
        await self._publish(f"{_ROLE_PREFIX}operator", event_type, data)

    # ── Emergency-specific broadcasts ──

    async def broadcast_emergency_triggered(self, user_id: str, guardian_ids: list[str], event_data: dict):
        """SOS triggered — notify all guardians + operators."""
        for gid in guardian_ids:
            await self.broadcast_to_user(gid, "emergency_triggered", event_data)
        await self.broadcast_to_operators("emergency_triggered", event_data)

    async def broadcast_emergency_location(self, guardian_ids: list[str], event_data: dict):
        """Location update during active emergency."""
        for gid in guardian_ids:
            await self.broadcast_to_user(gid, "emergency_location_update", event_data)
        await self.broadcast_to_operators("emergency_location_update", event_data)

    async def broadcast_emergency_cancelled(self, guardian_ids: list[str], event_data: dict):
        """Emergency cancelled — notify guardians + operators."""
        for gid in guardian_ids:
            await self.broadcast_to_user(gid, "emergency_cancelled", event_data)
        await self.broadcast_to_operators("emergency_cancelled", event_data)

    async def broadcast_emergency_resolved(self, guardian_ids: list[str], event_data: dict):
        """Emergency resolved — notify guardians + operators."""
        for gid in guardian_ids:
            await self.broadcast_to_user(gid, "emergency_resolved", event_data)
        await self.broadcast_to_operators("emergency_resolved", event_data)

    # ── Incident broadcasts (existing) ──

    async def broadcast_incident_created(self, guardian_id: str, incident_data: dict):
        await self.broadcast_to_user(guardian_id, "incident_created", incident_data)
        await self.broadcast_to_operators("incident_created", incident_data)

    async def broadcast_incident_updated(self, guardian_id: str, incident_data: dict):
        await self.broadcast_to_user(guardian_id, "incident_updated", incident_data)
        await self.broadcast_to_operators("incident_updated", incident_data)

    async def broadcast_incident_escalated(self, guardian_id: str, incident_data: dict):
        await self.broadcast_to_user(guardian_id, "incident_escalated", incident_data)
        await self.broadcast_to_operators("incident_escalated", incident_data)

    # ── Escalation broadcasts (real-time call chain visibility) ──

    async def broadcast_escalation_update(self, guardian_ids: list[str], payload: dict):
        """Broadcast escalation state change to all guardians + operators.
        Used by sequential_escalation.py to stream live call chain progress.
        """
        for gid in guardian_ids:
            await self.broadcast_to_user(gid, "escalation_update", payload)
        await self.broadcast_to_operators("escalation_update", payload)

    # ── Channel key builders ──

    @staticmethod
    def user_channel(user_id: str) -> str:
        return f"{_USER_PREFIX}{user_id}"

    @staticmethod
    def operator_channel() -> str:
        return f"{_ROLE_PREFIX}operator"


# Global broadcaster instance
broadcaster = EventBroadcaster()


def serialize_for_sse(data: Any) -> dict:
    """Convert data to JSON-serializable format."""
    if isinstance(data, dict):
        return {k: serialize_for_sse(v) for k, v in data.items()}
    elif isinstance(data, (list, tuple)):
        return [serialize_for_sse(item) for item in data]
    elif isinstance(data, UUID):
        return str(data)
    elif isinstance(data, datetime):
        return data.isoformat()
    else:
        return data
