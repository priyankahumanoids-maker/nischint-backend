"""NISCH-008 — Live stream initiator service.

Owns the StreamSession state machine + Twilio NTS credential generation
+ SSE event emission. Strict scope:
  * Pure validation in `is_valid_stream_transition()` (no DB).
  * `transition_stream()` writes the row + emits SSE side-effects.
  * `offer_stream(incident)` is the auto-offer entry point wired into
    the SafetyIncident state machine — fires when an incident reaches
    ESCALATED.

Twilio integration follows the playbook: `client.tokens.create(ttl=N)`
returns `ice_servers` in WebRTC-spec format ready to drop into
`RTCPeerConnection`. We cap TTL at 30s (mobile-recommended) and fall
back to public STUN-only servers if Twilio is unreachable so the
signalling layer never blocks an emergency.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.safety_incident import SafetyIncident
from app.models.safety_incident_event import SafetyIncidentEvent
from app.models.stream_session import (
    ALLOWED_STREAM_TRANSITIONS, STREAM_CONNECTING, STREAM_DECLINED,
    STREAM_ENDED, STREAM_LIVE, STREAM_OFFERED, StreamSession,
)

logger = logging.getLogger(__name__)


# Twilio NTS recommended TTL for mobile is 30s — short window for ICE
# negotiation. Any longer is a security smell (token interception risk).
NTS_TOKEN_TTL_S = 30
# Auto-decline window. If the child doesn't accept within this window
# the offered row is swept to `declined` by `auto_decline_stale_offers()`.
OFFER_TIMEOUT_S = 30


class InvalidStreamTransitionError(ValueError):
    """Raised when a StreamSession transition violates the contract."""


def is_valid_stream_transition(from_state: str, to_state: str) -> bool:
    """Pure check — no DB. Returns True iff the transition is allowed."""
    return to_state in ALLOWED_STREAM_TRANSITIONS.get(from_state, frozenset())


def assert_valid_stream_transition(from_state: str, to_state: str) -> None:
    if not is_valid_stream_transition(from_state, to_state):
        raise InvalidStreamTransitionError(
            f"invalid stream transition {from_state} → {to_state}; "
            f"allowed: {sorted(ALLOWED_STREAM_TRANSITIONS.get(from_state, frozenset()))}"
        )


# ── Twilio NTS credentials ──────────────────────────────────────────

_FALLBACK_ICE_SERVERS = [
    {"urls": "stun:stun.l.google.com:19302"},
    {"urls": "stun:stun1.l.google.com:19302"},
]


def get_ice_servers(*, ttl: int = NTS_TOKEN_TTL_S) -> list[dict]:
    """Generate short-lived ICE servers from Twilio NTS.

    Returns a list of dicts in WebRTC-spec format
    (`[{urls, username?, credential?}, ...]`) ready to pass directly
    to `RTCPeerConnection({iceServers: ...})`.

    Failure modes (rate limit, auth, suspended) → falls back to public
    STUN-only servers. The signalling layer never blocks because
    Twilio is unreachable — direct P2P is still possible on open
    networks; symmetric NAT (Jio/Airtel) will fail without TURN, but
    that's an honest network failure, not a service failure on our
    side.
    """
    sid   = (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip()
    token = (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip()
    if not (sid and token):
        logger.warning("[STREAM] Twilio creds missing — using STUN-only fallback")
        return list(_FALLBACK_ICE_SERVERS)
    try:
        from twilio.rest import Client
        client = Client(sid, token)
        nts = client.tokens.create(ttl=max(30, min(ttl, 86400)))
        servers = list(nts.ice_servers or [])
        if not servers:
            logger.warning("[STREAM] NTS returned empty ice_servers — falling back")
            return list(_FALLBACK_ICE_SERVERS)
        return servers
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[STREAM] NTS token create failed: {e!r} — STUN-only fallback")
        return list(_FALLBACK_ICE_SERVERS)


# ── State transitions ──────────────────────────────────────────────

async def transition_stream(
    session: AsyncSession,
    stream: StreamSession,
    new_state: str,
    *,
    actor_id: Optional[uuid.UUID] = None,
) -> StreamSession:
    """Mutate a StreamSession row + fire side effects.

    Caller owns the transaction. We `flush()` so subsequent reads in
    the same request see the new row state.
    """
    assert_valid_stream_transition(stream.state, new_state)
    now = datetime.now(timezone.utc)

    stream.state = new_state
    if new_state == STREAM_LIVE and stream.started_at is None:
        stream.started_at = now
    if new_state in (STREAM_ENDED, STREAM_DECLINED):
        stream.ended_at = now
        if stream.started_at is not None:
            stream.duration_seconds = max(
                0, int((now - stream.started_at).total_seconds())
            )

    await session.flush()

    # Forensic trail piggy-backs on the existing safety_incident_events
    # log so a single timeline endpoint surfaces both lifecycle and
    # stream events in one stream.
    try:
        evt = SafetyIncidentEvent(
            incident_id=stream.incident_id,
            from_state=str(stream.state),  # current state of incident — we don't have it here
            to_state=str(stream.state),
            actor_id=actor_id,
            actor_type="stream",
            ttfa_tag=f"stream_state:{new_state}",
            sla_degraded=False,
            extra={
                "stream_id":   str(stream.id),
                "stream_type": stream.stream_type,
                "transition":  new_state,
            },
            created_at=now,
        )
        session.add(evt)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[STREAM] event log write failed: {e}")

    _emit_stream_sse(stream, new_state)
    logger.info(
        f"[STREAM] {stream.id} → {new_state} incident={stream.incident_id}"
    )
    return stream


def _emit_stream_sse(stream: StreamSession, new_state: str) -> None:
    """Fire-and-forget SSE event. Mobile listens to:
        * `stream_offer`     — child only
        * `stream_available` — guardians only
        * `stream_state`     — both, on every transition
    """
    try:
        import asyncio
        from app.services.event_broadcaster import broadcaster

        payload = {
            "type":         "stream_state",
            "stream_id":    str(stream.id),
            "incident_id":  str(stream.incident_id),
            "state":        new_state,
            "stream_type":  stream.stream_type,
            "timestamp":    datetime.now(timezone.utc).isoformat(),
        }
        coro = broadcaster.broadcast_to_user(
            str(stream.child_id), "stream_state", payload,
        )
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            asyncio.create_task(coro)
        else:
            asyncio.run(coro)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[STREAM] SSE emit failed (non-fatal): {e}")


# ── Auto-offer hook (called from incident state machine) ───────────

async def offer_stream_for_incident(
    session: AsyncSession,
    incident: SafetyIncident,
    *,
    stream_type: str = "audio",
) -> Optional[StreamSession]:
    """Create a fresh StreamSession in `offered` state for this incident.

    Idempotent on a *per-active-stream* basis: if there's already an
    active (offered/connecting/live) stream for this incident, we
    return it untouched rather than spawning a duplicate.

    Returns the StreamSession (new or existing). Returns None only on
    a hard write failure (logged; never raises into the lifecycle
    transition that triggered us).
    """
    try:
        existing = (await session.execute(
            select(StreamSession)
            .where(StreamSession.incident_id == incident.id)
            .where(StreamSession.state.in_(
                [STREAM_OFFERED, STREAM_CONNECTING, STREAM_LIVE]
            ))
            .order_by(StreamSession.offered_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        if existing is not None:
            logger.info(
                f"[STREAM] reuse active stream {existing.id} for "
                f"incident={incident.id} state={existing.state}"
            )
            return existing

        ice = get_ice_servers()
        stream = StreamSession(
            incident_id=incident.id,
            child_id=incident.child_id,
            state=STREAM_OFFERED,
            stream_type=stream_type if stream_type in ("audio", "video") else "audio",
            ice_servers={"servers": ice, "ttl": NTS_TOKEN_TTL_S},
            offered_at=datetime.now(timezone.utc),
        )
        session.add(stream)
        await session.flush()

        _emit_offer_sse(stream, ice_servers=ice)
        logger.info(
            f"[STREAM] offered stream={stream.id} incident={incident.id} "
            f"child={incident.child_id} type={stream.stream_type}"
        )
        return stream
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[STREAM] offer_stream_for_incident failed: {e!r}")
        return None


def _emit_offer_sse(stream: StreamSession, *, ice_servers: list[dict]) -> None:
    """Emit `stream_offer` to the child + `stream_available` to all
    guardians linked to that child. Best-effort; safety pipeline must
    not block on observability."""
    try:
        import asyncio
        from app.services.event_broadcaster import broadcaster

        # Child-side payload — includes ICE servers + the accept URL.
        child_payload = {
            "type":         "stream_offer",
            "stream_id":    str(stream.id),
            "incident_id":  str(stream.incident_id),
            "stream_type":  stream.stream_type,
            "ice_servers":  ice_servers,
            "ttl_seconds":  NTS_TOKEN_TTL_S,
            "offer_timeout_seconds": OFFER_TIMEOUT_S,
            "timestamp":    datetime.now(timezone.utc).isoformat(),
        }
        # Guardian-side: no ICE servers (issued at /join time so the
        # window is freshest possible), just an availability ping.
        guardian_payload = {
            "type":         "stream_available",
            "stream_id":    str(stream.id),
            "incident_id":  str(stream.incident_id),
            "child_id":     str(stream.child_id),
            "stream_type":  stream.stream_type,
            "timestamp":    datetime.now(timezone.utc).isoformat(),
        }

        async def _emit():
            try:
                await broadcaster.broadcast_to_user(
                    str(stream.child_id), "stream_offer", child_payload,
                )
            except Exception:
                pass
            # Guardians: piggy-back on the same broadcaster — the
            # incident_state SSE pipeline already fans out to them
            # via the relationship-linked subscription set.
            try:
                await broadcaster.broadcast_to_user(
                    str(stream.child_id), "stream_available", guardian_payload,
                )
            except Exception:
                pass

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            asyncio.create_task(_emit())
        else:
            asyncio.run(_emit())
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[STREAM] offer SSE emit failed: {e}")


# ── Sweeper: auto-decline stale offers ─────────────────────────────

async def auto_decline_stale_offers(
    session: AsyncSession, *, now: Optional[datetime] = None,
) -> int:
    """Sweep offered streams older than OFFER_TIMEOUT_S and transition
    them to `declined`. Returns the count of swept rows.

    Designed to run on the scheduler process every 10s. Uses a
    single UPDATE — no per-row state machine call — because the
    declined-from-offered transition is always valid (DB CHECK + the
    state map both allow it)."""
    from sqlalchemy import update
    from datetime import timedelta
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=OFFER_TIMEOUT_S)
    res = await session.execute(
        update(StreamSession)
        .where(StreamSession.state == STREAM_OFFERED)
        .where(StreamSession.offered_at <= cutoff)
        .values(state=STREAM_DECLINED, ended_at=now)
    )
    count = res.rowcount or 0
    if count:
        logger.info(f"[STREAM] auto-declined {count} stale offer(s)")
    return count


__all__ = [
    "NTS_TOKEN_TTL_S",
    "OFFER_TIMEOUT_S",
    "InvalidStreamTransitionError",
    "is_valid_stream_transition",
    "assert_valid_stream_transition",
    "get_ice_servers",
    "transition_stream",
    "offer_stream_for_incident",
    "auto_decline_stale_offers",
]
