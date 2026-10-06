"""Protected-member Behavioral Advisory V1.

Launch-safe, advisory-only routine learning for NISCHINT protected members.

Design constraints:
- Learns only from the authenticated protected phone's already-existing
  /api/geofence/location-update stream.
- Runs after the location HTTP response as a best-effort background task.
- Uses protected user_id as the identity; no legacy Senior/Device requirement.
- Never calls SOS, incident, escalation, check-in, route, or siren code.
- Sends only ordinary Guardian/Co-Guardian routine insights.
- Keeps all existing behavior_* / behavioral_* pipelines untouched.

The first release intentionally learns a conservative movement routine.  It
requires multi-day observations before it can emit a deviation.  Until then
its truthful state is ``learning``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.db.session import async_session

logger = logging.getLogger(__name__)

PROTECTED_ROLES = {
    "child",
    "kid",
    "woman",
    "women",
    "senior",
    "elder",
    "elderly",
    "dependent",
    "ward",
    "protectedmember",
    "familymember",
    "family",
}

OBSERVATION_BUCKET_MINUTES = 5
MAX_OBSERVATION_AGE_MINUTES = 10
MAX_ACCURACY_M = 250.0
MIN_OBSERVATIONS = 36
MIN_DISTINCT_DAYS = 3
MIN_REFERENCE_OBSERVATIONS = 12
MIN_REFERENCE_DAYS = 2
RECENT_WINDOW_MINUTES = 20
ADVISORY_COOLDOWN_MINUTES = 60

FEATURE_ENV = "PROTECTED_BEHAVIOR_ADVISORY_ENABLED"
NOTIFICATIONS_ENV = "PROTECTED_BEHAVIOR_NOTIFICATIONS_ENABLED"


def is_protected_behavior_enabled() -> bool:
    return os.environ.get(FEATURE_ENV, "false").strip().lower() in {"1", "true", "yes", "on"}


def are_protected_behavior_notifications_enabled() -> bool:
    return os.environ.get(NOTIFICATIONS_ENV, "false").strip().lower() in {"1", "true", "yes", "on"}


_tables_ready = False
_tables_lock = asyncio.Lock()
_local_seen_bucket: dict[str, datetime] = {}


def _normalize_role(value: Any) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .replace("_", "")
        .replace("-", "")
        .replace(" ", "")
    )


def _as_utc(value: datetime | str | None) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            value = None
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _bucket_start(value: datetime) -> datetime:
    value = _as_utc(value)
    minute = value.minute - (value.minute % OBSERVATION_BUCKET_MINUTES)
    return value.replace(minute=minute, second=0, microsecond=0)


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000.0
    p1 = math.radians(float(lat1))
    p2 = math.radians(float(lat2))
    dp = math.radians(float(lat2) - float(lat1))
    dl = math.radians(float(lng2) - float(lng1))
    a = (
        math.sin(dp / 2.0) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    )
    a = min(1.0, max(0.0, a))
    return 2.0 * r * math.asin(math.sqrt(a))


def _learning_progress(sample_count: int, distinct_days: int) -> int:
    sample_ratio = min(1.0, max(0.0, sample_count / float(MIN_OBSERVATIONS)))
    day_ratio = min(1.0, max(0.0, distinct_days / float(MIN_DISTINCT_DAYS)))
    if sample_ratio >= 1.0 and day_ratio >= 1.0:
        return 99
    return int(max(0.0, min(99.0, min(sample_ratio, day_ratio) * 100.0)))


def _classify_deviation(
    expected_active_ratio: float,
    current_active_ratio: float,
    confidence: float,
) -> dict | None:
    """Return an advisory classification, never an emergency classification."""
    deviation = abs(float(expected_active_ratio) - float(current_active_ratio))
    if confidence < 0.65 or deviation < 0.55:
        return None

    if expected_active_ratio >= 0.65 and current_active_ratio <= 0.20:
        key = "lower_activity_than_usual"
        reason = "Phone movement is lower than the learned routine for this time."
    elif expected_active_ratio <= 0.25 and current_active_ratio >= 0.80:
        key = "activity_outside_usual_pattern"
        reason = "Phone movement is higher than the learned routine for this time."
    else:
        return None

    severity = "high" if deviation >= 0.75 and confidence >= 0.80 else "medium"
    return {
        "key": key,
        "severity": severity,
        "score": round(min(1.0, deviation), 3),
        "reason": reason,
    }


async def _ensure_tables() -> bool:
    """Create only isolated advisory tables; never modify existing safety tables."""
    global _tables_ready
    if _tables_ready:
        return True

    async with _tables_lock:
        if _tables_ready:
            return True
        try:
            async with async_session() as session:
                await session.execute(text("""
                    CREATE TABLE IF NOT EXISTS protected_behavior_observations (
                        id BIGSERIAL PRIMARY KEY,
                        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        bucket_start TIMESTAMPTZ NOT NULL,
                        captured_at TIMESTAMPTZ NOT NULL,
                        lat DOUBLE PRECISION NOT NULL,
                        lng DOUBLE PRECISION NOT NULL,
                        speed_mps DOUBLE PRECISION NULL,
                        accuracy_m DOUBLE PRECISION NULL,
                        movement_m DOUBLE PRECISION NULL,
                        is_active BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        CONSTRAINT uq_protected_behavior_user_bucket
                            UNIQUE (user_id, bucket_start)
                    )
                """))
                await session.execute(text("""
                    CREATE INDEX IF NOT EXISTS ix_protected_behavior_obs_user_time
                    ON protected_behavior_observations (user_id, captured_at DESC)
                """))
                await session.execute(text("""
                    CREATE TABLE IF NOT EXISTS protected_behavior_profiles (
                        user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                        state VARCHAR(24) NOT NULL DEFAULT 'learning',
                        current_state VARCHAR(32) NOT NULL DEFAULT 'learning',
                        confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
                        learning_progress INTEGER NOT NULL DEFAULT 0,
                        sample_count INTEGER NOT NULL DEFAULT 0,
                        distinct_days INTEGER NOT NULL DEFAULT 0,
                        current_score DOUBLE PRECISION NULL,
                        current_reason TEXT NULL,
                        hourly_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
                        last_observation_at TIMESTAMPTZ NULL,
                        last_evaluated_at TIMESTAMPTZ NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """))
                await session.execute(text("""
                    CREATE TABLE IF NOT EXISTS protected_behavior_advisories (
                        id BIGSERIAL PRIMARY KEY,
                        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        advisory_key VARCHAR(80) NOT NULL,
                        severity VARCHAR(16) NOT NULL,
                        score DOUBLE PRECISION NOT NULL,
                        confidence DOUBLE PRECISION NOT NULL,
                        message TEXT NOT NULL,
                        details JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """))
                await session.execute(text("""
                    CREATE INDEX IF NOT EXISTS ix_protected_behavior_adv_user_time
                    ON protected_behavior_advisories (user_id, created_at DESC)
                """))
                await session.commit()
            _tables_ready = True
            return True
        except Exception as exc:  # best-effort feature; never break location
            logger.warning(
                "[PROTECTED_BEHAVIOR] isolated table ensure skipped: %s",
                exc,
            )
            return False


async def record_protected_behavior_observation(
    user_id: str,
    lat: float,
    lng: float,
    *,
    speed_mps: float | None = None,
    accuracy_m: float | None = None,
    captured_at: datetime | str | None = None,
) -> None:
    """Best-effort post-response learner entry point.

    All exceptions are contained here.  This function must never raise into the
    already-completed protected location request.
    """
    try:
        if not is_protected_behavior_enabled():
            return
        observed_at = _as_utc(captured_at)
        now = datetime.now(timezone.utc)
        if observed_at > now + timedelta(seconds=30):
            observed_at = now
        if now - observed_at > timedelta(minutes=MAX_OBSERVATION_AGE_MINUTES):
            return

        if accuracy_m is not None:
            try:
                accuracy_m = max(0.0, float(accuracy_m))
            except Exception:
                accuracy_m = None
        if accuracy_m is not None and accuracy_m > MAX_ACCURACY_M:
            return

        bucket = _bucket_start(observed_at)
        # Per-process hot-path throttle.  DB UNIQUE remains the cross-instance
        # source of truth, but repeated fixes in the same five-minute bucket do
        # not need to open a DB session on this instance.
        if _local_seen_bucket.get(str(user_id)) == bucket:
            return
        _local_seen_bucket[str(user_id)] = bucket
        if len(_local_seen_bucket) > 5000:
            cutoff = now - timedelta(hours=1)
            stale = [key for key, value in _local_seen_bucket.items() if value < cutoff]
            for key in stale[:2500]:
                _local_seen_bucket.pop(key, None)

        if not await _ensure_tables():
            return

        async with async_session() as session:
            user_row = (await session.execute(text("""
                SELECT role, full_name, email
                  FROM users
                 WHERE id = CAST(:uid AS uuid)
                   AND is_active = TRUE
                 LIMIT 1
            """), {"uid": str(user_id)})).first()
            if not user_row:
                return

            from app.core.family_circle_permissions import ACTION_PRODUCE_AI_PROFILE
            from app.services.family_circle_runtime_authority import runtime_decision
            eligibility = await runtime_decision(
                session, actor_user_id=user_id, action=ACTION_PRODUCE_AI_PROFILE,
            )
            if eligibility.canonical:
                if not eligibility.allowed:
                    return
            elif _normalize_role(user_row.role) not in PROTECTED_ROLES:
                return

            previous = (await session.execute(text("""
                SELECT lat, lng, captured_at
                  FROM protected_behavior_observations
                 WHERE user_id = CAST(:uid AS uuid)
                 ORDER BY captured_at DESC
                 LIMIT 1
            """), {"uid": str(user_id)})).first()

            movement_m = None
            derived_speed = None
            if previous and previous.captured_at:
                previous_at = _as_utc(previous.captured_at)
                dt_s = (observed_at - previous_at).total_seconds()
                if 0 < dt_s <= 30 * 60:
                    movement_m = _haversine_m(
                        float(previous.lat), float(previous.lng), float(lat), float(lng)
                    )
                    derived_speed = movement_m / dt_s

            normalized_speed = None
            if speed_mps is not None:
                try:
                    normalized_speed = max(0.0, min(60.0, float(speed_mps)))
                except Exception:
                    normalized_speed = None
            if normalized_speed is None and derived_speed is not None:
                normalized_speed = max(0.0, min(60.0, derived_speed))

            distance_is_reliable = accuracy_m is None or accuracy_m <= 120.0
            is_active = bool(
                (normalized_speed is not None and normalized_speed >= 0.8)
                or (
                    distance_is_reliable
                    and movement_m is not None
                    and movement_m >= 120.0
                )
            )

            inserted = (await session.execute(text("""
                INSERT INTO protected_behavior_observations
                    (user_id, bucket_start, captured_at, lat, lng,
                     speed_mps, accuracy_m, movement_m, is_active)
                VALUES
                    (CAST(:uid AS uuid), :bucket, :captured_at, :lat, :lng,
                     :speed, :accuracy, :movement, :active)
                ON CONFLICT (user_id, bucket_start) DO NOTHING
                RETURNING id
            """), {
                "uid": str(user_id),
                "bucket": bucket,
                "captured_at": observed_at,
                "lat": float(lat),
                "lng": float(lng),
                "speed": normalized_speed,
                "accuracy": accuracy_m,
                "movement": movement_m,
                "active": is_active,
            })).first()
            await session.commit()
            if not inserted:
                return

            member_name = user_row.full_name or (
                str(user_row.email).split("@")[0] if user_row.email else "Protected member"
            )
            await _evaluate_profile(
                session,
                str(user_id),
                member_name,
                observed_at,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[PROTECTED_BEHAVIOR] observation skipped user=%s error=%s",
            user_id,
            exc,
        )


async def _upsert_profile(
    session,
    *,
    user_id: str,
    state: str,
    current_state: str,
    confidence: float,
    learning_progress: int,
    sample_count: int,
    distinct_days: int,
    current_score: float | None,
    current_reason: str | None,
    hourly_profile: dict,
    observed_at: datetime,
) -> None:
    await session.execute(text("""
        INSERT INTO protected_behavior_profiles
            (user_id, state, current_state, confidence, learning_progress,
             sample_count, distinct_days, current_score, current_reason,
             hourly_profile, last_observation_at, last_evaluated_at, updated_at)
        VALUES
            (CAST(:uid AS uuid), :state, :current_state, :confidence, :progress,
             :sample_count, :distinct_days, :current_score, :current_reason,
             CAST(:hourly_profile AS jsonb), :observed_at, NOW(), NOW())
        ON CONFLICT (user_id) DO UPDATE SET
            state = EXCLUDED.state,
            current_state = EXCLUDED.current_state,
            confidence = EXCLUDED.confidence,
            learning_progress = EXCLUDED.learning_progress,
            sample_count = EXCLUDED.sample_count,
            distinct_days = EXCLUDED.distinct_days,
            current_score = EXCLUDED.current_score,
            current_reason = EXCLUDED.current_reason,
            hourly_profile = EXCLUDED.hourly_profile,
            last_observation_at = EXCLUDED.last_observation_at,
            last_evaluated_at = NOW(),
            updated_at = NOW()
    """), {
        "uid": user_id,
        "state": state,
        "current_state": current_state,
        "confidence": float(max(0.0, min(1.0, confidence))),
        "progress": int(max(0, min(100, learning_progress))),
        "sample_count": int(sample_count),
        "distinct_days": int(distinct_days),
        "current_score": current_score,
        "current_reason": current_reason,
        "hourly_profile": json.dumps(hourly_profile),
        "observed_at": observed_at,
    })
    await session.commit()


async def _evaluate_profile(
    session,
    user_id: str,
    member_name: str,
    observed_at: datetime,
) -> None:
    cutoff = observed_at - timedelta(days=7)
    totals = (await session.execute(text("""
        SELECT COUNT(*)::int AS sample_count,
               COUNT(DISTINCT ((captured_at AT TIME ZONE 'UTC')::date))::int AS distinct_days
          FROM protected_behavior_observations
         WHERE user_id = CAST(:uid AS uuid)
           AND captured_at >= :cutoff
           AND captured_at <= :observed_at
    """), {
        "uid": user_id,
        "cutoff": cutoff,
        "observed_at": observed_at,
    })).first()
    sample_count = int(totals.sample_count or 0) if totals else 0
    distinct_days = int(totals.distinct_days or 0) if totals else 0

    hourly_rows = (await session.execute(text("""
        SELECT EXTRACT(HOUR FROM captured_at AT TIME ZONE 'UTC')::int AS hour_utc,
               COUNT(*)::int AS samples,
               AVG(CASE WHEN is_active THEN 1.0 ELSE 0.0 END)::float AS active_ratio
          FROM protected_behavior_observations
         WHERE user_id = CAST(:uid AS uuid)
           AND captured_at >= :cutoff
           AND captured_at <= :observed_at
         GROUP BY 1
         ORDER BY 1
    """), {
        "uid": user_id,
        "cutoff": cutoff,
        "observed_at": observed_at,
    })).all()
    hourly_profile = {
        str(int(row.hour_utc)): {
            "samples": int(row.samples or 0),
            "active_ratio": round(float(row.active_ratio or 0.0), 3),
        }
        for row in hourly_rows
    }

    if sample_count < MIN_OBSERVATIONS or distinct_days < MIN_DISTINCT_DAYS:
        progress = _learning_progress(sample_count, distinct_days)
        await _upsert_profile(
            session,
            user_id=user_id,
            state="learning",
            current_state="learning",
            confidence=min(0.29, progress / 100.0 * 0.29),
            learning_progress=progress,
            sample_count=sample_count,
            distinct_days=distinct_days,
            current_score=None,
            current_reason="Learning this protected member's normal phone-movement routine.",
            hourly_profile=hourly_profile,
            observed_at=observed_at,
        )
        return

    hour = observed_at.hour
    reference_hours = ((hour - 1) % 24, hour, (hour + 1) % 24)
    reference_cutoff = observed_at - timedelta(minutes=30)
    ref = (await session.execute(text("""
        SELECT COUNT(*)::int AS samples,
               COUNT(DISTINCT ((captured_at AT TIME ZONE 'UTC')::date))::int AS days,
               AVG(CASE WHEN is_active THEN 1.0 ELSE 0.0 END)::float AS active_ratio
          FROM protected_behavior_observations
         WHERE user_id = CAST(:uid AS uuid)
           AND captured_at >= :cutoff
           AND captured_at < :reference_cutoff
           AND EXTRACT(HOUR FROM captured_at AT TIME ZONE 'UTC')::int
               IN (:h1, :h2, :h3)
    """), {
        "uid": user_id,
        "cutoff": cutoff,
        "reference_cutoff": reference_cutoff,
        "h1": reference_hours[0],
        "h2": reference_hours[1],
        "h3": reference_hours[2],
    })).first()
    ref_count = int(ref.samples or 0) if ref else 0
    ref_days = int(ref.days or 0) if ref else 0
    expected_ratio = float(ref.active_ratio or 0.0) if ref else 0.0

    recent_start = observed_at - timedelta(minutes=RECENT_WINDOW_MINUTES)
    recent = (await session.execute(text("""
        SELECT COUNT(*)::int AS samples,
               AVG(CASE WHEN is_active THEN 1.0 ELSE 0.0 END)::float AS active_ratio
          FROM protected_behavior_observations
         WHERE user_id = CAST(:uid AS uuid)
           AND captured_at >= :recent_start
           AND captured_at <= :observed_at
    """), {
        "uid": user_id,
        "recent_start": recent_start,
        "observed_at": observed_at,
    })).first()
    recent_count = int(recent.samples or 0) if recent else 0
    current_ratio = float(recent.active_ratio or 0.0) if recent else 0.0

    if (
        ref_count < MIN_REFERENCE_OBSERVATIONS
        or ref_days < MIN_REFERENCE_DAYS
        or recent_count < 3
    ):
        progress = min(99, _learning_progress(sample_count, distinct_days))
        await _upsert_profile(
            session,
            user_id=user_id,
            state="learning",
            current_state="learning",
            confidence=min(0.49, 0.30 + min(ref_count, 12) / 120.0),
            learning_progress=progress,
            sample_count=sample_count,
            distinct_days=distinct_days,
            current_score=None,
            current_reason="Learning enough observations for this time-of-day routine.",
            hourly_profile=hourly_profile,
            observed_at=observed_at,
        )
        return

    confidence = min(
        0.95,
        0.50
        + min(distinct_days, 7) * 0.04
        + min(ref_count, 30) * 0.006,
    )
    classification = _classify_deviation(expected_ratio, current_ratio, confidence)

    current_state = "deviation" if classification else "normal"
    current_score = classification["score"] if classification else round(
        abs(expected_ratio - current_ratio), 3
    )
    current_reason = (
        classification["reason"]
        if classification
        else "Current phone movement is within the learned routine for this time."
    )

    await _upsert_profile(
        session,
        user_id=user_id,
        state="ready",
        current_state=current_state,
        confidence=confidence,
        learning_progress=100,
        sample_count=sample_count,
        distinct_days=distinct_days,
        current_score=current_score,
        current_reason=current_reason,
        hourly_profile=hourly_profile,
        observed_at=observed_at,
    )

    if classification:
        await _record_and_deliver_advisory(
            session,
            user_id=user_id,
            member_name=member_name,
            classification=classification,
            confidence=confidence,
            expected_active_ratio=expected_ratio,
            current_active_ratio=current_ratio,
        )


async def _record_and_deliver_advisory(
    session,
    *,
    user_id: str,
    member_name: str,
    classification: dict,
    confidence: float,
    expected_active_ratio: float,
    current_active_ratio: float,
) -> None:
    cooldown_cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=ADVISORY_COOLDOWN_MINUTES
    )
    existing = (await session.execute(text("""
        SELECT id
          FROM protected_behavior_advisories
         WHERE user_id = CAST(:uid AS uuid)
           AND advisory_key = :key
           AND created_at >= :cutoff
         ORDER BY created_at DESC
         LIMIT 1
    """), {
        "uid": user_id,
        "key": classification["key"],
        "cutoff": cooldown_cutoff,
    })).first()
    if existing:
        return

    message = (
        f"{member_name}'s activity pattern is different from their usual routine "
        "for this time. This is an advisory signal, not an emergency."
    )
    if classification["key"] == "lower_activity_than_usual":
        message = (
            f"{member_name}'s phone activity is lower than their usual routine "
            "for this time. This is an advisory signal, not an emergency. "
            "Consider checking in if appropriate."
        )
    elif classification["key"] == "activity_outside_usual_pattern":
        message = (
            f"{member_name}'s phone activity is higher than their usual routine "
            "for this time. This is an advisory signal, not an emergency."
        )

    details = {
        "advisory_only": True,
        "model": "protected_behavior_advisory_v1",
        "expected_active_ratio": round(expected_active_ratio, 3),
        "current_active_ratio": round(current_active_ratio, 3),
        "learning_confidence": round(confidence, 3),
    }
    inserted = (await session.execute(text("""
        INSERT INTO protected_behavior_advisories
            (user_id, advisory_key, severity, score, confidence, message, details)
        VALUES
            (CAST(:uid AS uuid), :key, :severity, :score, :confidence,
             :message, CAST(:details AS jsonb))
        RETURNING id, created_at
    """), {
        "uid": user_id,
        "key": classification["key"],
        "severity": classification["severity"],
        "score": float(classification["score"]),
        "confidence": float(confidence),
        "message": message,
        "details": json.dumps(details),
    })).first()
    await session.commit()
    if not inserted:
        return

    try:
        await _deliver_advisory(
            session,
            advisory_id=int(inserted.id),
            created_at=_as_utc(inserted.created_at),
            user_id=user_id,
            member_name=member_name,
            severity=classification["severity"],
            message=message,
            score=float(classification["score"]),
            confidence=float(confidence),
        )
    except Exception as exc:  # delivery can never affect learned state
        logger.warning(
            "[PROTECTED_BEHAVIOR] guardian advisory delivery skipped user=%s: %s",
            user_id,
            exc,
        )


async def _deliver_advisory(
    session,
    *,
    advisory_id: int,
    created_at: datetime,
    user_id: str,
    member_name: str,
    severity: str,
    message: str,
    score: float,
    confidence: float,
) -> None:
    if not are_protected_behavior_notifications_enabled():
        return

    from app.services.event_broadcaster import broadcaster
    from app.services.geofence_alerts import _resolve_guardian_ids

    guardian_ids = await _resolve_guardian_ids(session, user_id)
    guardian_ids = list(dict.fromkeys(str(gid) for gid in guardian_ids if gid))

    # Behavioral advisories are AI-purpose disclosures, not implicit location
    # disclosures. Re-check each canonical recipient at delivery time.
    try:
        from app.core.family_circle_permissions import ACTION_VIEW_AI_PROFILE
        from app.services.family_circle_runtime_authority import (
            canonical_membership_state, runtime_decision,
        )
        target_state = await canonical_membership_state(session, user_id)
        if target_state != "legacy":
            allowed_guardians: list[str] = []
            for guardian_id in guardian_ids:
                decision = await runtime_decision(
                    session,
                    actor_user_id=guardian_id,
                    target_user_id=user_id,
                    action=ACTION_VIEW_AI_PROFILE,
                )
                if decision.allowed:
                    allowed_guardians.append(guardian_id)
            guardian_ids = allowed_guardians
    except Exception as exc:
        logger.warning(
            "[PROTECTED_BEHAVIOR] canonical advisory audience resolution failed user=%s: %s",
            user_id, exc,
        )
        guardian_ids = []

    if not guardian_ids:
        return

    payload = {
        "id": f"behavioral-advisory-{advisory_id}",
        "type": "BEHAVIORAL_ADVISORY",
        "event_type": "behavioral_advisory",
        "alert_type": "behavioral_advisory",
        "severity": severity,
        "child_id": user_id,
        "user_id": user_id,
        "child_name": member_name,
        "user_name": member_name,
        "message": message,
        "score": round(score, 3),
        "confidence": round(confidence, 3),
        "timestamp": created_at.isoformat(),
        "source": "protected_behavior_advisory_v1",
        "advisory_only": True,
        "screen": "alerts",
    }

    # Reuse the existing Guardian SSE transport and its already-supported
    # `safety_alert` event family.  The payload type is deliberately neither
    # SOS nor EMERGENCY, so the existing mobile bridge treats it as a normal
    # informational alert and never enters emergency UI.
    for guardian_id in guardian_ids:
        try:
            await broadcaster.broadcast_to_user(
                guardian_id,
                "safety_alert",
                payload,
            )
        except Exception as exc:
            logger.warning(
                "[PROTECTED_BEHAVIOR] SSE advisory skipped guardian=%s: %s",
                guardian_id,
                exc,
            )

    # Closed/background-app delivery is a normal FCM notification only.
    # No GuardianAlert row, incident, SOS, siren, escalation, or check-in is
    # created by this feature.
    try:
        from app.services.push_service import get_users_push_tokens, send_push_to_tokens

        guardian_uuids = []
        for guardian_id in guardian_ids:
            try:
                guardian_uuids.append(uuid.UUID(guardian_id))
            except Exception:
                continue
        if not guardian_uuids:
            return

        tokens = await get_users_push_tokens(session, guardian_uuids)
        if not tokens:
            return

        fcm_data = {
            "type": "BEHAVIORAL_ADVISORY",
            "event_type": "behavioral_advisory",
            "alert_type": "behavioral_advisory",
            "severity": severity,
            "child_id": user_id,
            "child_name": member_name,
            "message": message,
            "screen": "alerts",
            "advisory_only": "true",
            "source": "protected_behavior_advisory_v1",
            "advisory_id": str(advisory_id),
        }
        await send_push_to_tokens(
            tokens,
            "NISCHINT Routine Insight",
            message,
            data=fcm_data,
            channel_id="safety-alerts",
            louder=False,
        )
    except Exception as exc:
        logger.warning(
            "[PROTECTED_BEHAVIOR] ordinary push advisory skipped user=%s: %s",
            user_id,
            exc,
        )


async def get_protected_behavior_summary(session, user_id: str) -> dict:
    """Return aggregate, non-location behavioral state for one protected user."""
    if not is_protected_behavior_enabled():
        return {
            "user_id": str(user_id),
            "status": "disabled",
            "state": "disabled",
            "reason": "protected_behavior_feature_disabled",
            "advisory_only": True,
            "notifications_enabled": False,
        }
    if not await _ensure_tables():
        return {
            "user_id": str(user_id),
            "status": "unavailable",
            "state": "unavailable",
            "reason": "behavioral_storage_unavailable",
        }

    user_row = (await session.execute(text("""
        SELECT role, full_name, email, last_known_at
          FROM users
         WHERE id = CAST(:uid AS uuid)
           AND is_active = TRUE
         LIMIT 1
    """), {"uid": str(user_id)})).first()
    if not user_row:
        return {
            "user_id": str(user_id),
            "status": "unavailable",
            "state": "unavailable",
            "reason": "protected_member_not_found",
        }
    from app.core.family_circle_permissions import ACTION_PRODUCE_AI_PROFILE
    from app.services.family_circle_runtime_authority import runtime_decision
    eligibility = await runtime_decision(
        session, actor_user_id=user_id, action=ACTION_PRODUCE_AI_PROFILE,
    )
    if eligibility.canonical:
        if not eligibility.allowed:
            return {
                "user_id": str(user_id),
                "status": "unavailable",
                "state": "unavailable",
                "reason": eligibility.code,
            }
    elif _normalize_role(user_row.role) not in PROTECTED_ROLES:
        return {
            "user_id": str(user_id),
            "status": "unavailable",
            "state": "unavailable",
            "reason": "not_a_protected_member",
        }

    profile = (await session.execute(text("""
        SELECT state, current_state, confidence, learning_progress,
               sample_count, distinct_days, current_score, current_reason,
               last_observation_at, last_evaluated_at, updated_at
          FROM protected_behavior_profiles
         WHERE user_id = CAST(:uid AS uuid)
         LIMIT 1
    """), {"uid": str(user_id)})).first()

    name = user_row.full_name or (
        str(user_row.email).split("@")[0] if user_row.email else "Protected member"
    )
    if not profile:
        return {
            "user_id": str(user_id),
            "name": name,
            "status": "learning",
            "state": "learning",
            "current_state": "learning",
            "confidence": 0.0,
            "learning_progress": 0,
            "sample_count": 0,
            "distinct_days": 0,
            "message": "NISCHINT is waiting for enough protected-phone activity to learn this routine.",
            "advisory_only": True,
            "notifications_enabled": are_protected_behavior_notifications_enabled(),
        }

    latest = (await session.execute(text("""
        SELECT id, advisory_key, severity, score, confidence, message, created_at
          FROM protected_behavior_advisories
         WHERE user_id = CAST(:uid AS uuid)
         ORDER BY created_at DESC
         LIMIT 1
    """), {"uid": str(user_id)})).first()

    return {
        "user_id": str(user_id),
        "name": name,
        "status": str(profile.state),
        "state": str(profile.state),
        "current_state": str(profile.current_state),
        "confidence": round(float(profile.confidence or 0.0), 3),
        "learning_progress": int(profile.learning_progress or 0),
        "sample_count": int(profile.sample_count or 0),
        "distinct_days": int(profile.distinct_days or 0),
        "current_score": (
            round(float(profile.current_score), 3)
            if profile.current_score is not None
            else None
        ),
        "message": profile.current_reason,
        "last_observation_at": (
            profile.last_observation_at.isoformat()
            if profile.last_observation_at
            else None
        ),
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
        "latest_advisory": (
            {
                "id": int(latest.id),
                "type": str(latest.advisory_key),
                "severity": str(latest.severity),
                "score": round(float(latest.score), 3),
                "confidence": round(float(latest.confidence), 3),
                "message": latest.message,
                "created_at": latest.created_at.isoformat() if latest.created_at else None,
            }
            if latest
            else None
        ),
        "advisory_only": True,
        "notifications_enabled": are_protected_behavior_notifications_enabled(),
    }


__all__ = [
    "record_protected_behavior_observation",
    "get_protected_behavior_summary",
    "is_protected_behavior_enabled",
    "are_protected_behavior_notifications_enabled",
]
