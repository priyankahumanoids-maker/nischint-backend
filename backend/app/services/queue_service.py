# Queue Service — Redis Streams-based persistent event queues
# Provides FIFO processing with consumer groups, retry logic, and in-memory fallback.
#
# Queue streams:
#   nischint:stream:incident     — SOS events, critical alerts
#   nischint:stream:ai_signal    — Risk signals, heatmap events, behavior alerts
#   nischint:stream:notification — Guardian notifications, operator alerts, push messages

import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

STREAM_PREFIX = "nischint:stream"
GROUP_PREFIX = "nischint:group"

# Stream names
INCIDENT_STREAM = f"{STREAM_PREFIX}:incident"
AI_SIGNAL_STREAM = f"{STREAM_PREFIX}:ai_signal"
NOTIFICATION_STREAM = f"{STREAM_PREFIX}:notification"

# Consumer group names
INCIDENT_GROUP = f"{GROUP_PREFIX}:incident_workers"
AI_SIGNAL_GROUP = f"{GROUP_PREFIX}:ai_workers"
NOTIFICATION_GROUP = f"{GROUP_PREFIX}:notification_workers"

# In-memory fallback queues (when Redis unavailable)
_fallback_queues: dict[str, deque] = {
    "incident": deque(maxlen=5000),
    "ai_signal": deque(maxlen=10000),
    "notification": deque(maxlen=5000),
}

# Processing stats
_stats = {
    "incident": {"enqueued": 0, "processed": 0, "failed": 0},
    "ai_signal": {"enqueued": 0, "processed": 0, "failed": 0},
    "notification": {"enqueued": 0, "processed": 0, "failed": 0},
}


def _get_client():
    from app.services.redis_service import _get_client as _rc
    return _rc()


def _ensure_groups():
    """Create consumer groups if they don't exist."""
    c = _get_client()
    if not c:
        return
    groups = [
        (INCIDENT_STREAM, INCIDENT_GROUP),
        (AI_SIGNAL_STREAM, AI_SIGNAL_GROUP),
        (NOTIFICATION_STREAM, NOTIFICATION_GROUP),
    ]
    for stream, group in groups:
        try:
            c.xgroup_create(stream, group, id="0", mkstream=True)
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                logger.warning(f"Failed to create group {group}: {e}")


def _serialize(data: dict) -> dict:
    """Convert dict values to strings for Redis Stream compatibility."""
    return {"payload": json.dumps(data, default=str)}


def _deserialize(fields: dict) -> dict:
    """Parse payload back from Redis Stream entry."""
    raw = fields.get("payload") or fields.get(b"payload")
    if raw:
        return json.loads(raw)
    return dict(fields)


# ── Enqueue Operations ──

def enqueue_incident(data: dict, priority: str = "normal") -> bool:
    """Push an incident event (SOS, critical alert) to the queue."""
    data["_priority"] = priority
    data["_enqueued_at"] = datetime.now(timezone.utc).isoformat()
    _stats["incident"]["enqueued"] += 1

    c = _get_client()
    if c:
        try:
            _ensure_groups()
            c.xadd(INCIDENT_STREAM, _serialize(data), maxlen=10000)
            return True
        except Exception as e:
            logger.error(f"Redis incident enqueue failed: {e}")

    # Fallback to in-memory
    _fallback_queues["incident"].append(data)
    return True


def enqueue_ai_signal(data: dict) -> bool:
    """Push an AI safety signal (risk, heatmap, anomaly) to the buffer."""
    data["_enqueued_at"] = datetime.now(timezone.utc).isoformat()
    _stats["ai_signal"]["enqueued"] += 1

    c = _get_client()
    if c:
        try:
            _ensure_groups()
            c.xadd(AI_SIGNAL_STREAM, _serialize(data), maxlen=50000)
            return True
        except Exception as e:
            logger.error(f"Redis AI signal enqueue failed: {e}")

    _fallback_queues["ai_signal"].append(data)
    return True


def enqueue_notification(data: dict, priority: str = "normal") -> bool:
    """Push a notification (guardian alert, operator push, SMS) to the queue."""
    data["_priority"] = priority
    data["_enqueued_at"] = datetime.now(timezone.utc).isoformat()
    _stats["notification"]["enqueued"] += 1

    c = _get_client()
    if c:
        try:
            _ensure_groups()
            c.xadd(NOTIFICATION_STREAM, _serialize(data), maxlen=10000)
            return True
        except Exception as e:
            logger.error(f"Redis notification enqueue failed: {e}")

    _fallback_queues["notification"].append(data)
    return True


# ── Consume Operations (for workers) ──

def consume_batch(
    stream: str,
    group: str,
    consumer: str,
    count: int = 10,
    block_ms: int = 1000,
) -> list[tuple[str, dict]]:
    """Read a batch of messages from a Redis Stream using consumer groups.
    Returns list of (message_id, payload) tuples.
    """
    c = _get_client()
    if not c:
        return _consume_fallback(stream)

    try:
        _ensure_groups()
        result = c.xreadgroup(
            group, consumer, {stream: ">"}, count=count, block=block_ms
        )
        if not result:
            return []

        messages = []
        for _, entries in result:
            for msg_id, fields in entries:
                messages.append((msg_id, _deserialize(fields)))
        return messages
    except Exception as e:
        logger.error(f"Redis consume error ({stream}): {e}")
        return _consume_fallback(stream)


def acknowledge(stream: str, group: str, *message_ids: str) -> int:
    """Acknowledge processed messages."""
    c = _get_client()
    if not c or not message_ids:
        return 0
    try:
        return c.xack(stream, group, *message_ids)
    except Exception as e:
        logger.error(f"Redis ack error: {e}")
        return 0


def _consume_fallback(stream: str) -> list[tuple[str, dict]]:
    """Consume from in-memory fallback queue."""
    queue_name = stream.split(":")[-1]
    q = _fallback_queues.get(queue_name, deque())
    messages = []
    while q and len(messages) < 10:
        msg = q.popleft()
        messages.append((f"fallback-{time.time()}", msg))
    return messages


# ── Queue Stats (for monitoring) ──

def get_queue_stats() -> dict:
    """Get depth and processing stats for all queues."""
    c = _get_client()
    result = {"using_redis": c is not None, "queues": {}}

    streams = {
        "incident": (INCIDENT_STREAM, INCIDENT_GROUP),
        "ai_signal": (AI_SIGNAL_STREAM, AI_SIGNAL_GROUP),
        "notification": (NOTIFICATION_STREAM, NOTIFICATION_GROUP),
    }

    for name, (stream, group) in streams.items():
        q_info = {
            "enqueued": _stats[name]["enqueued"],
            "processed": _stats[name]["processed"],
            "failed": _stats[name]["failed"],
        }

        if c:
            try:
                length = c.xlen(stream)
                q_info["depth"] = length

                # Get pending info
                try:
                    pending = c.xpending(stream, group)
                    q_info["pending"] = pending.get("pending", 0) if isinstance(pending, dict) else 0
                except Exception:
                    q_info["pending"] = 0

            except Exception:
                q_info["depth"] = 0
                q_info["pending"] = 0
        else:
            q_info["depth"] = len(_fallback_queues.get(name, []))
            q_info["pending"] = 0

        result["queues"][name] = q_info

    return result


# ── Queue Processor (async worker) ──

async def process_incident(payload: dict) -> bool:
    """Process a single incident event. Override with actual business logic."""
    logger.info(f"Processing incident: {payload.get('type', 'unknown')} — {payload.get('user_id', 'unknown')}")
    _stats["incident"]["processed"] += 1
    # Business logic: persist to DB, notify guardians, escalate to operators
    # This is where the actual incident handler chain runs
    return True


async def process_ai_signal(payload: dict) -> bool:
    """Process a batch AI signal. Override with actual business logic."""
    logger.info(f"Processing AI signal: {payload.get('signal_type', 'unknown')}")
    _stats["ai_signal"]["processed"] += 1
    return True


async def process_notification(payload: dict) -> bool:
    """Process a notification dispatch. Override with actual business logic."""
    logger.info(f"Processing notification: {payload.get('type', 'unknown')} to {payload.get('recipient', 'unknown')}")
    _stats["notification"]["processed"] += 1
    return True


async def run_worker(
    stream: str,
    group: str,
    consumer: str,
    processor,
    batch_size: int = 10,
    poll_interval_ms: int = 2000,
):
    """Run a queue worker that continuously processes messages.
    Call this in a background task / asyncio.create_task().
    """
    import asyncio
    logger.info(f"Queue worker started: {consumer} on {stream}")

    while True:
        try:
            messages = consume_batch(stream, group, consumer, count=batch_size, block_ms=poll_interval_ms)
            if not messages:
                await asyncio.sleep(0.1)
                continue

            ack_ids = []
            for msg_id, payload in messages:
                try:
                    success = await processor(payload)
                    if success and not msg_id.startswith("fallback"):
                        ack_ids.append(msg_id)
                except Exception as e:
                    queue_name = stream.split(":")[-1]
                    _stats.get(queue_name, {})["failed"] = _stats.get(queue_name, {}).get("failed", 0) + 1
                    logger.error(f"Worker processing error ({stream}): {e}")

            if ack_ids:
                acknowledge(stream, group, *ack_ids)

        except Exception as e:
            logger.error(f"Worker loop error ({stream}): {e}")
            await asyncio.sleep(5)
