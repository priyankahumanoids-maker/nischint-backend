"""DLQ Reconciler — drains the three audit-row DLQs created by the
2026-02 reliability ratchet pass.

Compensating action promise (RELIABILITY_DEBT.md):
  When a safety-critical event has already fanned out via SSE +
  push + SMS but the persistence INSERT failed, the planned audit
  row is parked in a bounded Redis list. This reconciler is the
  drain — without it, the `compensating_action_exists` claim is
  only half-true.

Drain semantics (locked, same across all three DLQs):
  * RPOP one entry per cycle, per DLQ. FIFO so the oldest gap
    closes first.
  * Increment `_attempts` and call the per-DLQ replay function.
  * Success → drop the entry, emit `dlq_drained` structured log.
  * Failure & `_attempts < MAX_ATTEMPTS` → LPUSH back to the live
    DLQ; the entry rotates with anything that arrived in this
    cycle (no head-of-line blocking on one bad payload).
  * Failure & `_attempts >= MAX_ATTEMPTS` → LPUSH to a sibling
    `dlq:<key>:poison` list (capped at 200 via LTRIM), emit
    CRITICAL `dlq_poisoned` log. Operators MUST drain poison
    out-of-band; the live DLQ stays clear.

Why RPOP + LPUSH and not a Redis Stream consumer group? The DLQs
are small (max 500–1000 entries) and the drain is intentionally
slow (one entry per source per 60s cycle). A consumer group
adds operational complexity (pending lists, claim, ack) that
buys nothing at this volume.
"""
from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


# ── Locked operational constants ─────────────────────────────────
MAX_ATTEMPTS = 3                    # poison after 3 failures
POISON_MAX = 200                    # bounded per LTRIM
DRAIN_INTERVAL_S = 60               # one tick per minute
DRAIN_JITTER_S = 10                 # ±10s
SCHEDULER_JOB_ID = "dlq_reconciler_cycle"


# ── Replay-function registry ─────────────────────────────────────
#
# A replay function returns True on drain-success, False on
# transient failure (retry next cycle). It MUST NOT raise — the
# reconciler wraps as defence-in-depth but a raise is a contract
# violation that the per-source replay function should have
# handled itself.

ReplayFn = Callable[[dict], Awaitable[bool]]


async def _replay_notification_history(payload: dict) -> bool:
    """Replay an inbox-history row that failed during a schema
    drift / DB outage window."""
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError, ProgrammingError
    from app.db.session import async_session
    try:
        async with async_session() as session:
            await session.execute(
                text("""
                    INSERT INTO push_notifications
                        (user_id, title, body, data, tag, created_at, is_read)
                    VALUES (:uid, :title, :body, :data, :tag, :created_at, false)
                """),
                {
                    "uid":   payload.get("user_id"),
                    "title": payload.get("title"),
                    "body":  payload.get("body"),
                    "data":  json.dumps(payload.get("data") or {}),
                    "tag":   payload.get("tag"),
                    "created_at": datetime.now(timezone.utc),
                },
            )
            await session.commit()
        return True
    except (ProgrammingError, OperationalError):
        # Underlying path still broken — retry next cycle.
        return False


async def _replay_failsafe_audit(payload: dict) -> bool:
    """Replay a guardian-failsafe GuardianAlert audit row."""
    import uuid as _uuid
    from sqlalchemy import select
    from sqlalchemy.exc import SQLAlchemyError
    from app.db.session import async_session
    from app.models.guardian import GuardianAlert, GuardianSession
    try:
        async with async_session() as session:
            child_user_id = payload.get("child_user_id")
            if not child_user_id:
                # Malformed payload — drop on first poison cycle.
                return False
            res = await session.execute(
                select(GuardianSession).where(
                    GuardianSession.user_id == _uuid.UUID(child_user_id),
                    GuardianSession.status == "active",
                ).order_by(GuardianSession.started_at.desc()).limit(1)
            )
            active_ses = res.scalar_one_or_none()
            if not active_ses:
                # No active session to attach to — incident has
                # already concluded. Treat as drained; the audit
                # gap is now historical.
                return True
            seq = payload.get("seq_summary") or {}
            alert = GuardianAlert(
                session_id=active_ses.id,
                user_id=_uuid.UUID(child_user_id),
                alert_type="guardian_failsafe",
                severity="critical",
                message=(
                    f"FAILSAFE (replayed): No guardian responded for "
                    f"{payload.get('child_name', 'child')}"
                ),
                details=(
                    f"REPLAYED FROM DLQ — original_failure_at="
                    f"{payload.get('failed_at')}. "
                    f"event_id={payload.get('event_id')}. "
                    f"Original: {payload.get('alert_type')}. "
                    f"Guardians SSE-pinged: {payload.get('notified_count')}. "
                    f"Sequential: contacts={payload.get('seq_contacts')}, "
                    f"calls={seq.get('total_calls')}, "
                    f"sms={seq.get('total_sms')}, "
                    f"resolved_by={seq.get('resolved_by') or 'NONE'}, "
                    f"sms_blast={seq.get('sms_blast_sent')}."
                ),
                recommendation="Historical record only — incident already concluded.",
            )
            session.add(alert)
            await session.commit()
        return True
    except SQLAlchemyError:
        return False


async def _replay_voice_distress_audit(payload: dict) -> bool:
    """Replay a voice-distress GuardianAlert audit row."""
    import uuid as _uuid
    from sqlalchemy import select
    from sqlalchemy.exc import SQLAlchemyError
    from app.db.session import async_session
    from app.models.guardian import GuardianAlert, GuardianSession
    try:
        async with async_session() as session:
            child_user_id = payload.get("child_user_id")
            if not child_user_id:
                return False
            res = await session.execute(
                select(GuardianSession).where(
                    GuardianSession.user_id == _uuid.UUID(child_user_id),
                    GuardianSession.status == "active",
                )
            )
            active_ses = res.scalar_one_or_none()
            if not active_ses:
                return True
            score = float(payload.get("score") or 0.0)
            scream = bool(payload.get("scream_detected"))
            severity = "critical" if payload.get("is_auto_sos") else "high"
            child_name = payload.get("child_name", "child")
            msg = f"Voice distress (replayed) from {child_name}!"
            if scream:
                msg = (
                    f"Scream (replayed) from {child_name} — "
                    f"distress score {score:.1f}"
                )
            matched = payload.get("matched_keywords") or []
            if matched:
                msg += f" (keywords: {', '.join(matched)})"
            lat = payload.get("lat")
            lng = payload.get("lng")
            alert = GuardianAlert(
                session_id=active_ses.id,
                user_id=_uuid.UUID(child_user_id),
                alert_type="voice_distress",
                severity=severity,
                message=msg,
                details=(
                    f"REPLAYED FROM DLQ — original_failure_at="
                    f"{payload.get('failed_at')}. "
                    f"event_id={payload.get('event_id')}. "
                    f"Score: {score:.2f}, Scream: {scream}, Keywords: {matched}"
                ),
                recommendation="Historical record only — incident already concluded.",
                location={"lat": lat, "lng": lng} if lat and lng else None,
            )
            session.add(alert)
            await session.commit()
        return True
    except SQLAlchemyError:
        return False


async def _replay_rag_reindex(payload: dict) -> bool:
    """Re-trigger the RAG chunk + embed + INSERT pipeline for a blog
    that was published but failed indexing. The blog post itself
    already exists — this only re-runs the chunking + embedding +
    `blog_chunks` insert. Returns True when the index entry lands
    (or the post no longer exists, in which case the audit gap is
    historical and accepted as drained)."""
    import uuid as _uuid
    from sqlalchemy import text as _text
    from sqlalchemy.exc import SQLAlchemyError
    from app.db.session import async_session

    post_id = payload.get("post_id")
    if not post_id:
        return False

    try:
        async with async_session() as session:
            row = (await session.execute(
                _text("SELECT title, content FROM blog_posts WHERE id = :id"),
                {"id": post_id},
            )).first()
            if not row:
                return True
            title, content = row[0], row[1] or ""
            try:
                from app.services.embedding_service import embed_text
                from app.services.rag_chunking import chunk_blog_content
            except ImportError:
                return False
            chunks = chunk_blog_content(content) if content else []
            if not chunks:
                return True
            for i, chunk_item in enumerate(chunks):
                chunk_id = str(_uuid.uuid4())
                meta = {
                    "replayed_from":      "dlq:rag_reindex",
                    "original_failed_at": payload.get("failed_at"),
                }
                try:
                    emb = await embed_text(chunk_item)
                except Exception:  # noqa: BLE001
                    emb = None
                if emb:
                    emb_str = "[" + ",".join(f"{x:.6f}" for x in emb) + "]"
                    await session.execute(_text("""
                        INSERT INTO blog_chunks
                            (id, blog_id, title, content, chunk_text, chunk_index, embedding, metadata)
                        VALUES (:id, :bid, :title, :content, :chunk, :ci,
                                CAST(:emb AS vector), CAST(:meta AS jsonb))
                    """), {
                        "id": chunk_id, "bid": post_id, "title": title,
                        "content": (content or "")[:500],
                        "chunk": chunk_item, "ci": i, "emb": emb_str,
                        "meta": json.dumps(meta),
                    })
                else:
                    await session.execute(_text("""
                        INSERT INTO blog_chunks
                            (id, blog_id, title, content, chunk_text, chunk_index, metadata)
                        VALUES (:id, :bid, :title, :content, :chunk, :ci,
                                CAST(:meta AS jsonb))
                    """), {
                        "id": chunk_id, "bid": post_id, "title": title,
                        "content": (content or "")[:500],
                        "chunk": chunk_item, "ci": i,
                        "meta": json.dumps(meta),
                    })
            await session.commit()
        return True
    except SQLAlchemyError:
        return False



async def _replay_checkin_audit(payload: dict) -> bool:
    """Replay a check-in audit row (help_requested GuardianAlert or
    SafetyEvent). Dispatches by `row_type` discriminator carried in
    the payload."""
    import uuid as _uuid
    from sqlalchemy import select
    from sqlalchemy.exc import SQLAlchemyError
    from app.db.session import async_session
    from app.models.guardian import GuardianAlert, GuardianSession

    row_type = payload.get("row_type")
    child_id = payload.get("child_id")
    if not row_type or not child_id:
        return False

    try:
        async with async_session() as session:
            child_uuid = _uuid.UUID(child_id)
            if row_type == "help_requested":
                res = await session.execute(
                    select(GuardianSession).where(
                        GuardianSession.user_id == child_uuid,
                        GuardianSession.status == "active",
                    )
                )
                active_session = res.scalar_one_or_none()
                alert = GuardianAlert(
                    session_id=active_session.id if active_session else None,
                    user_id=child_uuid,
                    alert_type="help_requested",
                    severity="critical",
                    message=(
                        f"(replayed) {payload.get('child_name', 'child')} "
                        "needs help! Responded to safety check requesting "
                        "assistance."
                    ),
                    details=(
                        f"REPLAYED FROM DLQ — original_failure_at="
                        f"{payload.get('failed_at')}. "
                        f"Check-in ID: {payload.get('check_in_id')}."
                    ),
                    recommendation="Historical record only — incident already concluded.",
                )
                session.add(alert)
                await session.commit()
                return True
            if row_type == "safety_event":
                from app.models.safety_event import SafetyEvent
                safety_event = SafetyEvent(
                    user_id=child_uuid,
                    risk_score=0.9,
                    risk_level="critical",
                    signals={
                        "help_request":    1.0,
                        "check_in_id":     payload.get("check_in_id"),
                        "replayed_from":   "dlq:checkin_audit",
                        "original_failed_at": payload.get("failed_at"),
                    },
                    primary_event="help_request",
                    location_lat=0.0,
                    location_lng=0.0,
                    status="active",
                )
                session.add(safety_event)
                await session.commit()
                return True
            # Unknown row_type — poison so an operator investigates.
            return False
    except SQLAlchemyError:
        return False


# Ordered list — each (key, max_size, replay_fn). `max_size` is the
# bound the producing site declared; the chip uses it to compute
# pressure %. Keep the order stable — the rollup endpoint exposes
# this same list to the operator UI.
_DLQS: list[tuple[str, int, ReplayFn]] = [
    ("dlq:notification_history",  1000, _replay_notification_history),
    ("dlq:failsafe_audit",         500, _replay_failsafe_audit),
    ("dlq:voice_distress_audit",   500, _replay_voice_distress_audit),
    ("dlq:checkin_audit",          500, _replay_checkin_audit),
    ("dlq:rag_reindex",            500, _replay_rag_reindex),
]


# ── Drain primitives ─────────────────────────────────────────────

def _poison_key(dlq_key: str) -> str:
    return f"{dlq_key}:poison"


async def _drain_one(dlq_key: str, replay_fn: ReplayFn) -> str:
    """Drain at most one entry from `dlq_key`. Returns a verb
    describing what happened: `drained`, `requeued`, `poisoned`,
    `empty`, or `redis_unavailable`."""
    try:
        from app.services.redis_service import _get_client
    except Exception:  # noqa: BLE001
        return "redis_unavailable"
    c = _get_client()
    if not c:
        return "redis_unavailable"
    raw = c.rpop(dlq_key)
    if raw is None:
        return "empty"

    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        # Corrupt entry — straight to poison so the drain stays
        # unblocked. Operators investigate via the poison list.
        c.lpush(_poison_key(dlq_key), raw if isinstance(raw, str) else str(raw))
        c.ltrim(_poison_key(dlq_key), 0, POISON_MAX - 1)
        logger.critical(
            "dlq_poisoned",
            extra={
                "event":  "dlq_poisoned",
                "dlq":    dlq_key,
                "reason": "json_decode_failed",
            },
        )
        return "poisoned"

    attempts = int(payload.get("_attempts", 0)) + 1
    payload["_attempts"] = attempts

    try:
        ok = await replay_fn(payload)
    except Exception as e:  # noqa: BLE001 — defence-in-depth
        logger.warning(
            "dlq_replay_raised",
            extra={
                "event":      "dlq_replay_raised",
                "dlq":        dlq_key,
                "error_type": type(e).__name__,
                "attempts":   attempts,
            },
        )
        ok = False

    if ok:
        logger.info(
            "dlq_drained",
            extra={
                "event":    "dlq_drained",
                "dlq":      dlq_key,
                "attempts": attempts,
            },
        )
        return "drained"

    if attempts >= MAX_ATTEMPTS:
        c.lpush(_poison_key(dlq_key), json.dumps(payload, default=str))
        c.ltrim(_poison_key(dlq_key), 0, POISON_MAX - 1)
        logger.critical(
            "dlq_poisoned",
            extra={
                "event":    "dlq_poisoned",
                "dlq":      dlq_key,
                "attempts": attempts,
                "error_type": payload.get("error_type"),
            },
        )
        return "poisoned"

    # Transient — back to the live DLQ for next cycle.
    c.lpush(dlq_key, json.dumps(payload, default=str))
    return "requeued"


async def run_cycle() -> dict:
    """One reconciler tick — drains up to one entry per DLQ.
    Returns a per-DLQ verb map for the rollup endpoint."""
    results: dict[str, str] = {}
    for key, _max, fn in _DLQS:
        try:
            results[key] = await _drain_one(key, fn)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "dlq_cycle_error",
                extra={"event": "dlq_cycle_error", "dlq": key, "err": repr(e)},
            )
            results[key] = "error"
    return results


# ── Poison-list drain (operator-triggered) ───────────────────────

def is_known_dlq(dlq_key: str) -> bool:
    """Whether `dlq_key` is one of the registered DLQs. Used to
    reject arbitrary poison-key drains at the API surface."""
    return dlq_key in {k for k, _m, _fn in _DLQS}


def _replay_fn_for(dlq_key: str) -> Optional[ReplayFn]:
    for k, _m, fn in _DLQS:
        if k == dlq_key:
            return fn
    return None


async def drain_poison_list(
    dlq_key: str,
    *,
    replay: bool = False,
    max_drain: int = 100,
) -> dict:
    """Operator-triggered drain of a `dlq:<key>:poison` list.

    `replay=False` (default): hard-discard. Drains up to `max_drain`
    entries via RPOP, returns the payloads in the response so the
    caller can hand them to an offline reconciler / CSV export.
    The live DLQ is unaffected.

    `replay=True`: routes each poisoned entry back through the
    per-DLQ replay function with `_attempts` reset to 0. Successes
    leave the entry drained; failures are LPUSHed back onto the
    poison list (the same defensive behaviour as the regular
    drain cycle, just at operator request).

    Returns a verb summary suitable for surfacing in the UI:
        {
          "dlq": "dlq:failsafe_audit",
          "mode": "replay" | "discard",
          "attempted": int,
          "drained": int,     # only for replay mode
          "requeued": int,    # only for replay mode
          "discarded": int,   # only for discard mode
          "items": [...],     # only for discard mode (payload echo)
        }
    """
    if not is_known_dlq(dlq_key):
        raise ValueError(f"unknown dlq key: {dlq_key}")
    if max_drain < 1 or max_drain > POISON_MAX:
        raise ValueError(
            f"max_drain must be 1..{POISON_MAX}, got {max_drain}"
        )

    try:
        from app.services.redis_service import _get_client
    except Exception:  # noqa: BLE001
        return {
            "dlq": dlq_key, "mode": "replay" if replay else "discard",
            "attempted": 0, "error": "redis_unavailable",
        }
    c = _get_client()
    if not c:
        return {
            "dlq": dlq_key, "mode": "replay" if replay else "discard",
            "attempted": 0, "error": "redis_unavailable",
        }

    pkey = _poison_key(dlq_key)
    replay_fn = _replay_fn_for(dlq_key) if replay else None

    # Snapshot up to `max_drain` entries first via RPOP, then process
    # in memory. Without the snapshot, a failed replay's LPUSH would
    # land back on the same list and the next RPOP picks it up
    # immediately — burning the drain budget on one broken payload.
    snapshot: list = []
    for _ in range(max_drain):
        raw = c.rpop(pkey)
        if raw is None:
            break
        snapshot.append(raw)

    attempted = len(snapshot)
    drained = 0
    requeued = 0
    discarded_items: list[dict] = []
    requeue_payloads: list[dict] = []

    for raw in snapshot:
        try:
            payload = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        except (TypeError, ValueError):
            # Corrupt poison entry. Discard regardless of mode —
            # operators can never replay a malformed blob.
            discarded_items.append({"_corrupt": True, "raw": str(raw)[:200]})
            continue

        if not replay:
            discarded_items.append(payload if isinstance(payload, dict) else {"raw": payload})
            continue

        # Replay mode — reset attempts so this drain doesn't
        # immediately re-poison on the first failure.
        if isinstance(payload, dict):
            payload["_attempts"] = 0
        try:
            ok = await replay_fn(payload) if replay_fn else False
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "poison_replay_raised",
                extra={
                    "event": "poison_replay_raised",
                    "dlq": dlq_key,
                    "error_type": type(e).__name__,
                },
            )
            ok = False

        if ok:
            drained += 1
            logger.info(
                "poison_drained",
                extra={"event": "poison_drained", "dlq": dlq_key},
            )
        else:
            requeue_payloads.append(payload if isinstance(payload, dict) else {"raw": payload})
            requeued += 1
            logger.warning(
                "poison_replay_requeued",
                extra={"event": "poison_replay_requeued", "dlq": dlq_key},
            )

    # Re-park requeued payloads in one batch *after* draining is done.
    # LTRIM after the LPUSH burst keeps the poison list bounded even
    # if the burst would otherwise exceed POISON_MAX.
    for payload in requeue_payloads:
        c.lpush(pkey, json.dumps(payload, default=str))
    if requeue_payloads:
        c.ltrim(pkey, 0, POISON_MAX - 1)

    out: dict = {
        "dlq": dlq_key,
        "mode": "replay" if replay else "discard",
        "attempted": attempted,
    }
    if replay:
        out["drained"] = drained
        out["requeued"] = requeued
    else:
        out["discarded"] = len(discarded_items)
        out["items"] = discarded_items
    return out


# ── Stats (rollup endpoint + capsule chip) ───────────────────────

def get_dlq_stats() -> dict:
    """Operator-facing snapshot. Includes pressure % per DLQ so the
    capsule chip can colour itself without re-implementing the
    thresholds: amber at ≥10 %, red at ≥50 %."""
    try:
        from app.services.redis_service import _get_client
        c = _get_client()
    except Exception:  # noqa: BLE001
        c = None
    out: dict = {"dlqs": [], "any_amber": False, "any_red": False}
    for key, max_size, _fn in _DLQS:
        depth = 0
        poison_depth = 0
        if c:
            try:
                depth = int(c.llen(key) or 0)
                poison_depth = int(c.llen(_poison_key(key)) or 0)
            except Exception:  # noqa: BLE001
                pass
        pressure_pct = round(depth / max_size * 100.0, 1) if max_size else 0.0
        amber = pressure_pct >= 10.0
        red = pressure_pct >= 50.0
        if amber:
            out["any_amber"] = True
        if red:
            out["any_red"] = True
        out["dlqs"].append({
            "key":          key,
            "depth":        depth,
            "max_size":     max_size,
            "poison_depth": poison_depth,
            "poison_max":   POISON_MAX,
            "pressure_pct": pressure_pct,
            "amber":        amber,
            "red":          red,
        })
    out["redis_available"] = c is not None
    out["max_attempts"] = MAX_ATTEMPTS
    return out


# ── Scheduler lifecycle ──────────────────────────────────────────

_scheduler: Optional[AsyncIOScheduler] = None


def start() -> None:
    """Idempotent scheduler start. Called once at app startup."""
    global _scheduler
    if _scheduler is not None:
        logger.info("[DLQ_RECONCILER] already running")
        return
    _scheduler = AsyncIOScheduler()
    trigger = IntervalTrigger(
        seconds=DRAIN_INTERVAL_S,
        jitter=DRAIN_JITTER_S,
    )
    _scheduler.add_job(
        run_cycle,
        trigger=trigger,
        id=SCHEDULER_JOB_ID,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "[DLQ_RECONCILER] started — interval=%ds ± %ds",
        DRAIN_INTERVAL_S, DRAIN_JITTER_S,
    )


def stop() -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception as e:  # noqa: BLE001
        logger.warning("[DLQ_RECONCILER] shutdown failed: %r", e)
    finally:
        _scheduler = None


# Module-level names matching the prewarmer convention used by
# `app/workers/scheduler_runner.py`.
def start_dlq_reconciler() -> None:
    start()


def stop_dlq_reconciler() -> None:
    stop()


def compute_next_interval_seconds(
    rng: Optional[random.Random] = None,
) -> float:
    """Testable jitter seam — mirrors the prewarmer convention."""
    r = rng or random
    return DRAIN_INTERVAL_S + r.uniform(-DRAIN_JITTER_S, DRAIN_JITTER_S)


__all__ = [
    "MAX_ATTEMPTS", "POISON_MAX", "DRAIN_INTERVAL_S", "DRAIN_JITTER_S",
    "SCHEDULER_JOB_ID",
    "run_cycle", "get_dlq_stats", "start", "stop",
    "start_dlq_reconciler", "stop_dlq_reconciler",
    "drain_poison_list", "is_known_dlq",
    "_DLQS", "_poison_key", "_drain_one", "_replay_fn_for",
    "_replay_notification_history",
    "_replay_failsafe_audit",
    "_replay_voice_distress_audit",
    "_replay_checkin_audit",
    "_replay_rag_reindex",
]
