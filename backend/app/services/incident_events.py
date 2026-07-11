# Incident Event Logger - Forensic Audit Trail
import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def log_event(
    session: AsyncSession,
    incident_id: UUID,
    event_type: str,
    channel: str = None,
    metadata: dict = None,
):
    """Log a structured lifecycle event for an incident."""
    await session.execute(
        text(
            "INSERT INTO incident_events (incident_id, event_type, event_channel, event_metadata) "
            "VALUES (:iid, :etype, :echan, :emeta)"
        ),
        {
            "iid": incident_id,
            "etype": event_type,
            "echan": channel,
            "emeta": json.dumps(metadata or {}),
        },
    )
    logger.debug(f"Event logged: {event_type} [{channel or '-'}] for incident {incident_id}")


async def get_events(session: AsyncSession, incident_id: UUID) -> list[dict]:
    """Get all events for an incident, ordered chronologically."""
    result = await session.execute(
        text(
            "SELECT id, event_type, event_channel, event_metadata, created_at "
            "FROM incident_events WHERE incident_id = :iid ORDER BY created_at ASC"
        ),
        {"iid": incident_id},
    )
    return [
        {
            "id": str(row[0]),
            "event_type": row[1],
            "event_channel": row[2],
            "event_metadata": row[3],
            "created_at": row[4].isoformat() if row[4] else None,
        }
        for row in result.fetchall()
    ]
