# Guardian Family Dashboard Engine
# Provides data for the consumer-facing guardian dashboard.
# Links guardians to their monitored loved ones via the guardians table.

import logging
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guardian import Guardian, GuardianSession, GuardianAlert
from app.models.user import User
from app.models.senior import Senior

logger = logging.getLogger(__name__)
DEVICE_TELEMETRY_FRESHNESS = timedelta(minutes=15)

# Accounts that supervise a family circle are never protected members.  Keep
# this guard at the relationship-source query so Home, Family, Protection,
# alerts, sessions, and history all receive the same protected-member scope.
MONITOR_ONLY_ROLES = {
    "guardian",
    "parent",
    "primary_guardian",
    "primaryguardian",
    "co_parent",
    "coparent",
    "co_guardian",
    "coguardian",
    "admin",
    "operator",
}


def _normalized_role_sql(column):
    """Normalize role spellings for SQL-side monitor/protected filtering."""
    return func.lower(
        func.replace(
            func.replace(column, "-", "_"),
            " ",
            "_",
        )
    )


def _fresh_device_telemetry(raw: object, now: datetime) -> tuple[dict | None, datetime | None]:
    """Return only recent, real protected-device telemetry."""
    if not isinstance(raw, dict):
        return None, None
    updated_raw = raw.get("updated_at")
    if not updated_raw:
        return None, None
    try:
        updated_at = datetime.fromisoformat(str(updated_raw).replace("Z", "+00:00"))
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        else:
            updated_at = updated_at.astimezone(timezone.utc)
        # New protected-device snapshots explicitly tell us whether the point
        # is current (<=2 min). A delayed offline replay remains valid as
        # last-known history but must never be presented as live telemetry.
        if raw.get("is_current") is False:
            return None, updated_at
        if now - updated_at > DEVICE_TELEMETRY_FRESHNESS:
            return None, updated_at
    except (TypeError, ValueError):
        return None, None
    return raw, updated_at


async def _get_linked_user_ids(
    session: AsyncSession,
    guardian_email: str,
    guardian_user_id: str | None = None,
    user_role: str | None = None,
    *,
    include_checkin_recovery: bool = True,
) -> list[uuid.UUID]:
    """Find all protected users that the signed-in guardian may monitor.

    Relationship sources are deliberately centralized here so Home, Family,
    Protection, safety-checks, and co-guardian access cannot disagree about
    the same family circle.  A co-parent inherits the primary guardian's
    family scope, but is still a guardian relationship — never a protected
    member.

    ``include_checkin_recovery`` exists only for legacy dashboard recovery.
    Authorization-sensitive callers (for example creating a new safety check)
    must set it to ``False`` so an old CheckIn row cannot grant new access.
    """
    ids: set[uuid.UUID] = set()

    normalized_role = (user_role or "").strip().lower()

    # Admin sees all protected-role users for oversight.
    if normalized_role == "admin":
        admin_result = await session.execute(
            select(User.id).where(
                User.role.in_(
                    [
                        "child",
                        "kid",
                        "woman",
                        "senior",
                        "family",
                        "family_member",
                        "protected_member",
                    ]
                )
            )
        )
        ids.update(row[0] for row in admin_result.all())
        return list(ids)

    guardian_scope_ids: set[uuid.UUID] = set()
    guardian_scope_emails: set[str] = (
        {guardian_email} if guardian_email else set()
    )

    if guardian_user_id:
        try:
            guardian_uuid = uuid.UUID(str(guardian_user_id))
        except (TypeError, ValueError, AttributeError):
            logger.warning(
                "Guardian dashboard received invalid guardian id=%s",
                guardian_user_id,
            )
            return []

        guardian_scope_ids.add(guardian_uuid)

        # Co-parent/co-guardian invites point to the primary guardian through
        # User.guardian_id. Give the co-guardian the same read/monitor scope
        # without converting the guardian into a protected family member.
        if normalized_role in {
            "co_parent",
            "co-parent",
            "coparent",
            "co_guardian",
            "co-guardian",
        }:
            co_parent_result = await session.execute(
                select(User).where(User.id == guardian_uuid)
            )
            co_parent = co_parent_result.scalar_one_or_none()

            if co_parent and co_parent.guardian_id:
                guardian_scope_ids.add(co_parent.guardian_id)

                owner_result = await session.execute(
                    select(User.email).where(
                        User.id == co_parent.guardian_id
                    )
                )
                owner_email = owner_result.scalar_one_or_none()
                if owner_email:
                    guardian_scope_emails.add(owner_email)

    # Fast path: resolve all relationship sources in one SQL round trip.
    #
    # The previous implementation performed one sequential execute() per
    # relationship source.  UNION ALL preserves all sources while the set
    # below keeps the original de-duplication semantics.
    link_queries = []

    if guardian_scope_emails:
        link_queries.append(
            select(Guardian.user_id.label("user_id")).where(
                Guardian.email.in_(guardian_scope_emails),
                Guardian.is_active.is_(True),
            )
        )

    if guardian_scope_ids:
        link_queries.append(
            select(User.id.label("user_id")).where(
                User.guardian_id.in_(guardian_scope_ids),
                User.is_active == True,  # noqa: E712
                _normalized_role_sql(User.role).notin_(MONITOR_ONLY_ROLES),
            )
        )

        try:
            from app.models.relationship import Relationship

            link_queries.append(
                select(Relationship.child_id.label("user_id")).where(
                    Relationship.guardian_id.in_(guardian_scope_ids),
                    Relationship.status == "accepted",
                )
            )
        except Exception as exc:
            logger.warning(
                "Guardian dashboard Relationship lookup setup failed guardian=%s: %s",
                guardian_user_id,
                exc,
            )

        try:
            from app.models.guardian_network import GuardianRelationship

            link_queries.append(
                select(GuardianRelationship.user_id.label("user_id")).where(
                    GuardianRelationship.guardian_user_id.in_(
                        guardian_scope_ids
                    ),
                    GuardianRelationship.is_active.is_(True),
                )
            )
        except Exception as exc:
            logger.warning(
                "Guardian dashboard network lookup setup failed guardian=%s: %s",
                guardian_user_id,
                exc,
            )

        if include_checkin_recovery:
            try:
                from app.models.checkin import CheckIn

                link_queries.append(
                    select(CheckIn.child_id.label("user_id")).where(
                        CheckIn.guardian_id.in_(guardian_scope_ids)
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Guardian dashboard check-in relationship lookup setup failed guardian=%s: %s",
                    guardian_user_id,
                    exc,
                )

    if not link_queries:
        return list(ids)

    try:
        if len(link_queries) == 1:
            linked_result = await session.execute(link_queries[0])
        else:
            from sqlalchemy import union_all

            linked_result = await session.execute(
                union_all(*link_queries)
            )

        ids.update(
            row[0]
            for row in linked_result.all()
            if row[0] is not None
        )
        return list(ids)

    except Exception as exc:
        # Preserve the old fault-tolerant behavior if a deployment has a
        # partially migrated optional relationship table.  The optimized
        # path is used normally; this fallback matches the previous lookup
        # semantics source-by-source.
        logger.warning(
            "Guardian dashboard combined relationship lookup failed guardian=%s: %s; "
            "falling back to sequential lookups",
            guardian_user_id,
            exc,
        )

    # Fallback: original source-by-source relationship resolution.
    if guardian_scope_emails:
        guardian_rows = await session.execute(
            select(Guardian.user_id).where(
                Guardian.email.in_(guardian_scope_emails),
                Guardian.is_active.is_(True),
            )
        )
        ids.update(row[0] for row in guardian_rows.all())

    if guardian_scope_ids:
        user_result = await session.execute(
            select(User.id).where(
                User.guardian_id.in_(guardian_scope_ids),
                User.is_active == True,  # noqa: E712
                _normalized_role_sql(User.role).notin_(MONITOR_ONLY_ROLES),
            )
        )
        ids.update(row[0] for row in user_result.all())

        try:
            from app.models.relationship import Relationship

            rel_result = await session.execute(
                select(Relationship.child_id).where(
                    Relationship.guardian_id.in_(guardian_scope_ids),
                    Relationship.status == "accepted",
                )
            )
            ids.update(row[0] for row in rel_result.all())
        except Exception as exc:
            logger.warning(
                "Guardian dashboard Relationship lookup failed guardian=%s: %s",
                guardian_user_id,
                exc,
            )

        try:
            from app.models.guardian_network import GuardianRelationship

            network_result = await session.execute(
                select(GuardianRelationship.user_id).where(
                    GuardianRelationship.guardian_user_id.in_(
                        guardian_scope_ids
                    ),
                    GuardianRelationship.is_active.is_(True),
                )
            )
            ids.update(row[0] for row in network_result.all())
        except Exception as exc:
            logger.warning(
                "Guardian dashboard network lookup failed guardian=%s: %s",
                guardian_user_id,
                exc,
            )

        if include_checkin_recovery:
            try:
                from app.models.checkin import CheckIn

                checkin_result = await session.execute(
                    select(CheckIn.child_id).where(
                        CheckIn.guardian_id.in_(guardian_scope_ids)
                    )
                )
                ids.update(row[0] for row in checkin_result.all())
            except Exception as exc:
                logger.warning(
                    "Guardian dashboard check-in relationship lookup failed guardian=%s: %s",
                    guardian_user_id,
                    exc,
                )

    return list(ids)

async def get_loved_ones(session: AsyncSession, guardian_email: str, guardian_user_id: str, user_role: str | None = None) -> dict:
    """Get all people this guardian monitors, with their live status, location, and last_updated."""
    from app.models.emergency import EmergencyEvent
    from app.models.checkin import CheckIn
    from app.models.location_trail import LocationTrailPoint
    from app.models.location_share import LocationShare

    user_ids = await _get_linked_user_ids(
        session,
        guardian_email,
        guardian_user_id,
        user_role,
    )
    now = datetime.now(timezone.utc)
    guardian_uuid = uuid.UUID(guardian_user_id)

    # Batch-load dashboard state. The previous implementation performed
    # repeated SQL round trips once per loved one.
    users_by_id: dict[uuid.UUID, User] = {}
    active_sessions_by_user: dict[uuid.UUID, GuardianSession] = {}
    active_emergencies_by_user: dict[uuid.UUID, EmergencyEvent] = {}
    latest_checkins_by_user: dict[uuid.UUID, CheckIn] = {}
    ended_sessions_by_user: dict[uuid.UUID, GuardianSession] = {}
    trail_by_user: dict[uuid.UUID, tuple] = {}
    past_emergencies_by_user: dict[uuid.UUID, EmergencyEvent] = {}
    alert_counts_by_session: dict[uuid.UUID, int] = {}

    if user_ids:
        users_result = await session.execute(
            select(User).where(User.id.in_(user_ids))
        )
        users_by_id = {u.id: u for u in users_result.scalars().all()}

        active_session_ranked = (
            select(
                GuardianSession.id.label("id"),
                func.row_number().over(
                    partition_by=GuardianSession.user_id,
                    order_by=GuardianSession.started_at.desc(),
                ).label("rn"),
            )
            .where(
                GuardianSession.user_id.in_(user_ids),
                GuardianSession.status == "active",
            )
            .subquery()
        )
        active_session_result = await session.execute(
            select(GuardianSession)
            .join(
                active_session_ranked,
                GuardianSession.id == active_session_ranked.c.id,
            )
            .where(active_session_ranked.c.rn == 1)
        )
        active_sessions_by_user = {
            gs.user_id: gs
            for gs in active_session_result.scalars().all()
        }

        active_emergency_ranked = (
            select(
                EmergencyEvent.id.label("id"),
                func.row_number().over(
                    partition_by=EmergencyEvent.user_id,
                    order_by=EmergencyEvent.created_at.desc(),
                ).label("rn"),
            )
            .where(
                EmergencyEvent.user_id.in_(user_ids),
                EmergencyEvent.status == "active",
            )
            .subquery()
        )
        active_emergency_result = await session.execute(
            select(EmergencyEvent)
            .join(
                active_emergency_ranked,
                EmergencyEvent.id == active_emergency_ranked.c.id,
            )
            .where(active_emergency_ranked.c.rn == 1)
        )
        active_emergencies_by_user = {
            event.user_id: event
            for event in active_emergency_result.scalars().all()
        }

        checkin_ranked = (
            select(
                CheckIn.id.label("id"),
                func.row_number().over(
                    partition_by=CheckIn.child_id,
                    order_by=CheckIn.created_at.desc(),
                ).label("rn"),
            )
            .where(
                CheckIn.child_id.in_(user_ids),
                CheckIn.guardian_id == guardian_uuid,
            )
            .subquery()
        )
        checkin_result = await session.execute(
            select(CheckIn)
            .join(checkin_ranked, CheckIn.id == checkin_ranked.c.id)
            .where(checkin_ranked.c.rn == 1)
        )
        latest_checkins_by_user = {
            checkin.child_id: checkin
            for checkin in checkin_result.scalars().all()
        }

        ended_session_ranked = (
            select(
                GuardianSession.id.label("id"),
                func.row_number().over(
                    partition_by=GuardianSession.user_id,
                    order_by=GuardianSession.ended_at.desc().nullslast(),
                ).label("rn"),
            )
            .where(
                GuardianSession.user_id.in_(user_ids),
                GuardianSession.status != "active",
                GuardianSession.current_location.isnot(None),
            )
            .subquery()
        )
        ended_session_result = await session.execute(
            select(GuardianSession)
            .join(
                ended_session_ranked,
                GuardianSession.id == ended_session_ranked.c.id,
            )
            .where(ended_session_ranked.c.rn == 1)
        )
        ended_sessions_by_user = {
            gs.user_id: gs
            for gs in ended_session_result.scalars().all()
        }

        trail_ranked = (
            select(
                LocationShare.user_id.label("user_id"),
                LocationTrailPoint.lat.label("lat"),
                LocationTrailPoint.lng.label("lng"),
                LocationTrailPoint.recorded_at.label("recorded_at"),
                func.row_number().over(
                    partition_by=LocationShare.user_id,
                    order_by=LocationTrailPoint.recorded_at.desc(),
                ).label("rn"),
            )
            .join(
                LocationShare,
                LocationShare.token == LocationTrailPoint.share_token,
            )
            .where(LocationShare.user_id.in_(user_ids))
            .subquery()
        )
        trail_result = await session.execute(
            select(
                trail_ranked.c.user_id,
                trail_ranked.c.lat,
                trail_ranked.c.lng,
                trail_ranked.c.recorded_at,
            ).where(trail_ranked.c.rn == 1)
        )
        trail_by_user = {
            row[0]: (row[1], row[2], row[3])
            for row in trail_result.all()
        }

        past_emergency_ranked = (
            select(
                EmergencyEvent.id.label("id"),
                func.row_number().over(
                    partition_by=EmergencyEvent.user_id,
                    order_by=EmergencyEvent.created_at.desc(),
                ).label("rn"),
            )
            .where(
                EmergencyEvent.user_id.in_(user_ids),
                EmergencyEvent.lat.isnot(None),
            )
            .subquery()
        )
        past_emergency_result = await session.execute(
            select(EmergencyEvent)
            .join(
                past_emergency_ranked,
                EmergencyEvent.id == past_emergency_ranked.c.id,
            )
            .where(past_emergency_ranked.c.rn == 1)
        )
        past_emergencies_by_user = {
            event.user_id: event
            for event in past_emergency_result.scalars().all()
        }

        active_session_ids = [
            gs.id for gs in active_sessions_by_user.values()
        ]
        if active_session_ids:
            alert_count_result = await session.execute(
                select(
                    GuardianAlert.session_id,
                    func.count(),
                )
                .where(GuardianAlert.session_id.in_(active_session_ids))
                .group_by(GuardianAlert.session_id)
            )
            alert_counts_by_session = {
                session_id: int(count or 0)
                for session_id, count in alert_count_result.all()
            }

    monitored = []

    for uid in user_ids:
        user = users_by_id.get(uid)
        if not user:
            continue

        rel_type = "family"
        active_session = active_sessions_by_user.get(uid)

        telemetry_raw = None
        try:
            from app.services.redis_service import get_json

            telemetry_raw = get_json("protected_telemetry", str(uid))
        except Exception:
            pass

        if telemetry_raw is None and active_session:
            telemetry_raw = active_session.current_location

        device_telemetry, telemetry_updated_at = _fresh_device_telemetry(
            telemetry_raw,
            now,
        )
        battery_pct = (
            device_telemetry.get("battery_pct")
            if device_telemetry is not None
            else None
        )

        active_emergency = active_emergencies_by_user.get(uid)
        latest_checkin = latest_checkins_by_user.get(uid)

        status = "SAFE"
        if active_emergency:
            status = "EMERGENCY"
        elif latest_checkin and latest_checkin.status == "help":
            status = "HELP"
        elif latest_checkin and latest_checkin.status == "pending":
            status = "CHECK_IN_PENDING"
        elif active_session:
            status = "LIVE_JOURNEY"

        location = None
        location_ts = None
        location_type = None

        # 1. Active emergency
        if active_emergency:
            location = {
                "lat": active_emergency.lat,
                "lng": active_emergency.lng,
            }
            location_ts = active_emergency.created_at
            location_type = "emergency"
            if (
                active_emergency.location_trail
                and len(active_emergency.location_trail) > 0
            ):
                last_trail = active_emergency.location_trail[-1]
                if isinstance(last_trail, dict) and "lat" in last_trail:
                    location = {
                        "lat": last_trail["lat"],
                        "lng": last_trail["lng"],
                    }

        # 2. Fresh protected-device telemetry
        if (
            not location
            and device_telemetry
            and device_telemetry.get("lat") is not None
            and device_telemetry.get("lng") is not None
        ):
            location = {
                "lat": device_telemetry["lat"],
                "lng": device_telemetry["lng"],
            }
            location_ts = telemetry_updated_at
            location_type = "live"

        # 3. Active session
        if not location and active_session and active_session.current_location:
            loc = active_session.current_location
            if isinstance(loc, dict) and "lat" in loc:
                location = {"lat": loc["lat"], "lng": loc["lng"]}
                location_ts = (
                    active_session.previous_update_at
                    or active_session.started_at
                )
                location_type = "live"

        # 4. Durable protected-device last-known location. These columns are
        # updated by both passive/background GPS and SOS GPS, so Guardian Home
        # and Family retain the exact last fix even after Redis expires or the
        # protected phone goes offline.
        if (
            not location
            and user.last_known_lat is not None
            and user.last_known_lng is not None
            and user.last_known_at is not None
        ):
            location = {
                "lat": float(user.last_known_lat),
                "lng": float(user.last_known_lng),
            }
            location_ts = user.last_known_at
            normalized_last_known_at = user.last_known_at
            if normalized_last_known_at.tzinfo is None:
                normalized_last_known_at = normalized_last_known_at.replace(
                    tzinfo=timezone.utc,
                )
            else:
                normalized_last_known_at = normalized_last_known_at.astimezone(
                    timezone.utc,
                )
            age = now - normalized_last_known_at
            location_type = (
                "live"
                if age <= timedelta(minutes=2)
                else "recent"
                if age <= timedelta(hours=24)
                else "historical"
            )

        # 5. Last ended session
        if not location:
            last_sess = ended_sessions_by_user.get(uid)
            if last_sess:
                loc = last_sess.current_location
                if isinstance(loc, dict) and "lat" in loc:
                    location = {"lat": loc["lat"], "lng": loc["lng"]}
                    location_ts = (
                        last_sess.ended_at
                        or last_sess.previous_update_at
                        or last_sess.started_at
                    )
                    location_type = "recent"

        # 6. Last location trail point
        if not location:
            trail_row = trail_by_user.get(uid)
            if trail_row and trail_row[0] is not None:
                location = {
                    "lat": trail_row[0],
                    "lng": trail_row[1],
                }
                location_ts = trail_row[2]
                location_type = "recent"

        # 7. Last emergency with coordinates
        if not location:
            past_em = past_emergencies_by_user.get(uid)
            if past_em:
                location = {"lat": past_em.lat, "lng": past_em.lng}
                location_ts = past_em.created_at
                location_type = "historical"

        last_updated = None
        if location_ts:
            last_updated = (
                location_ts.isoformat()
                if hasattr(location_ts, "isoformat")
                else str(location_ts)
            )
        elif active_emergency:
            last_updated = active_emergency.created_at.isoformat()
        elif active_session:
            ts = active_session.previous_update_at or active_session.started_at
            last_updated = ts.isoformat()
        elif latest_checkin:
            ts = latest_checkin.responded_at or latest_checkin.created_at
            last_updated = ts.isoformat()

        item = {
            "id": str(uid),
            "user_id": str(uid),
            "name": user.full_name or user.email,
            "email": user.email,
            "phone": user.phone,
            "is_active": bool(user.is_active),
            "role": user.role,
            "relationship": rel_type,
            "status": status,
            "location": location,
            "location_type": location_type,
            "last_updated": last_updated,
            "battery": battery_pct,
            "battery_percent": battery_pct,
            "battery_updated_at": (
                telemetry_updated_at.isoformat()
                if device_telemetry is not None and telemetry_updated_at
                else None
            ),
            "telemetry_fresh": device_telemetry is not None,
            "has_active_session": active_session is not None,
            "active_session": None,
        }

        if active_session:
            dur = round(
                (now - active_session.started_at).total_seconds() / 60,
                1,
            )
            item["active_session"] = {
                "session_id": str(active_session.id),
                "started_at": active_session.started_at.isoformat(),
                "duration_minutes": dur,
                "current_location": active_session.current_location,
                "destination": active_session.destination,
                "risk_level": active_session.risk_level,
                "risk_score": round(active_session.risk_score, 2),
                "zone_name": active_session.zone_name,
                "eta_minutes": active_session.eta_minutes,
                "speed_mps": round(active_session.speed_mps, 2),
                "speed_kmh": round(active_session.speed_mps * 3.6, 1),
                "total_distance_m": round(
                    active_session.total_distance_m,
                    1,
                ),
                "escalation_level": active_session.escalation_level,
                "is_night": active_session.is_night,
                "is_idle": active_session.is_idle,
                "route_deviated": active_session.route_deviated,
                "location_updates": active_session.location_updates,
                "alert_count": alert_counts_by_session.get(
                    active_session.id,
                    0,
                ),
            }

        monitored.append(item)

    seniors_result = await session.execute(
        select(Senior).where(Senior.guardian_id == guardian_uuid)
    )
    seniors = [
        {
            "senior_id": str(s.id),
            "name": s.full_name,
            "age": s.age,
        }
        for s in seniors_result.scalars().all()
    ]

    return {
        "monitored_users": monitored,
        "seniors": seniors,
        "total_loved_ones": len(monitored) + len(seniors),
        "active_journeys": sum(
            1 for m in monitored if m["has_active_session"]
        ),
    }

async def get_active_sessions(session: AsyncSession, guardian_email: str, guardian_user_id: str | None = None, user_role: str | None = None) -> list[dict]:
    """Get all active sessions for guardian's loved ones. Auto-expire stale ones."""
    user_ids = await _get_linked_user_ids(session, guardian_email, guardian_user_id, user_role)
    if not user_ids:
        return []

    result = await session.execute(
        select(GuardianSession).where(
            GuardianSession.user_id.in_(user_ids),
            GuardianSession.status == "active",
        )
    )
    now = datetime.now(timezone.utc)
    STALE_MINUTES = 30
    sessions = []

    for gs in result.scalars().all():
        # Auto-expire stale sessions (no telemetry for 30 min)
        last_activity = gs.previous_update_at if gs.previous_update_at else gs.started_at
        minutes_idle = (now - last_activity).total_seconds() / 60
        if minutes_idle > STALE_MINUTES:
            gs.status = "expired"
            gs.ended_at = now
            await session.flush()
            continue

        user_result = await session.execute(select(User).where(User.id == gs.user_id))
        user = user_result.scalar_one_or_none()
        ac = await session.execute(
            select(func.count()).where(GuardianAlert.session_id == gs.id)
        )
        sessions.append({
            "session_id": str(gs.id),
            "user_id": str(gs.user_id),
            "user_name": (user.full_name or user.email) if user else "Unknown",
            "user_role": user.role if user else "child",
            "status": gs.status,
            "started_at": gs.started_at.isoformat(),
            "duration_minutes": round((now - gs.started_at).total_seconds() / 60, 1),
            "current_location": gs.current_location,
            "destination": gs.destination,
            "risk_level": gs.risk_level,
            "risk_score": round(gs.risk_score, 2),
            "zone_name": gs.zone_name,
            "eta_minutes": gs.eta_minutes,
            "speed_mps": round(gs.speed_mps, 2),
            "speed_kmh": round(gs.speed_mps * 3.6, 1),
            "total_distance_m": round(gs.total_distance_m, 1),
            "escalation_level": gs.escalation_level,
            "is_night": gs.is_night,
            "is_idle": gs.is_idle,
            "route_deviated": gs.route_deviated,
            "alert_count": ac.scalar() or 0,
        })

    await session.commit()
    sessions.sort(key=lambda x: x["risk_score"], reverse=True)
    return sessions


async def get_alerts(session: AsyncSession, guardian_email: str, limit: int = 50, guardian_user_id: str | None = None, user_role: str | None = None) -> list[dict]:
    """Get recent alerts for guardian's loved ones (session alerts + check-in help responses)."""
    user_ids = await _get_linked_user_ids(session, guardian_email, guardian_user_id, user_role)

    alerts_list: list[dict] = []

    # ── Part 1: GuardianAlert rows (standalone or session-linked) ──
    if user_ids:
        user_result = await session.execute(select(User).where(User.id.in_(user_ids)))
        user_names = {u.id: u.full_name or u.email for u in user_result.scalars().all()}

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        alerts_result = await session.execute(
            select(GuardianAlert).where(
                GuardianAlert.user_id.in_(user_ids),
                GuardianAlert.created_at >= cutoff,
            ).order_by(GuardianAlert.created_at.desc()).limit(limit)
        )
        alert_rows = alerts_result.scalars().all()

        # Fallback: if 24h returns empty, get latest 5 regardless of age
        if not alert_rows:
            fallback_result = await session.execute(
                select(GuardianAlert).where(
                    GuardianAlert.user_id.in_(user_ids),
                ).order_by(GuardianAlert.created_at.desc()).limit(5)
            )
            alert_rows = fallback_result.scalars().all()

        for a in alert_rows:
            a_type = a.alert_type
            alerts_list.append({
                "id": str(a.id),
                "session_id": str(a.session_id) if a.session_id else None,
                "user_name": user_names.get(a.user_id, "Unknown"),
                "alert_type": a_type,
                "type": a_type,
                "severity": a.severity,
                "message": a.message,
                "details": a.details,
                "recommendation": a.recommendation,
                "location": a.location,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "ack_status": a.ack_status,
                "ack_type": a.ack_type,
                "acknowledged": a.ack_status == "acknowledged" or a.ack_type == "resolved",
                "acked_at": a.acked_at.isoformat() if a.acked_at else None,
            })

    # ── Part 2: Check-in records (all states — pending, safe, help, expired) ──
    guardian_user_result = await session.execute(
        select(User).where(User.email == guardian_email)
    )
    guardian_user = guardian_user_result.scalar_one_or_none()

    if guardian_user:
        from app.models.checkin import CheckIn
        cutoff_ci = datetime.now(timezone.utc) - timedelta(hours=24)
        checkin_result = await session.execute(
            select(CheckIn).where(
                CheckIn.guardian_id == guardian_user.id,
                CheckIn.created_at >= cutoff_ci,
            ).order_by(CheckIn.created_at.desc()).limit(limit)
        )
        ci_rows = checkin_result.scalars().all()

        # Fallback: if 24h returns empty, get latest 5
        if not ci_rows:
            fallback_ci = await session.execute(
                select(CheckIn).where(
                    CheckIn.guardian_id == guardian_user.id,
                ).order_by(CheckIn.created_at.desc()).limit(5)
            )
            ci_rows = fallback_ci.scalars().all()
        CHECKIN_SEVERITY = {"help": "critical", "pending": "medium", "expired": "high", "safe": "low"}
        CHECKIN_TYPE = {"help": "help_requested", "pending": "check_in_pending", "expired": "check_in_expired", "safe": "check_in_safe"}

        for ci in ci_rows:
            child_result = await session.execute(select(User).where(User.id == ci.child_id))
            child = child_result.scalar_one_or_none()
            child_name = child.full_name if child else "Unknown"

            ci_status = ci.status or "pending"
            msg_map = {
                "help": f"{child_name} needs help! Responded to safety check requesting assistance.",
                "pending": f"Safety check sent to {child_name} — waiting for response.",
                "expired": f"{child_name} did not respond to safety check.",
                "safe": f"{child_name} confirmed they are safe.",
            }

            alerts_list.append({
                "id": str(ci.id),
                "session_id": None,
                "user_name": child_name,
                "alert_type": CHECKIN_TYPE.get(ci_status, "check_in_request"),
                "type": CHECKIN_TYPE.get(ci_status, "check_in_request"),
                "severity": CHECKIN_SEVERITY.get(ci_status, "medium"),
                "message": msg_map.get(ci_status, f"Check-in for {child_name}: {ci_status}"),
                "details": f"Check-in ID: {ci.id}",
                "recommendation": "Contact the child immediately." if ci_status in ("help", "expired") else None,
                "location": None,
                "created_at": (ci.responded_at or ci.created_at).isoformat(),
                "responded": ci.status not in ("pending",),
                "response": ci_status,
            })

    # Sort combined list by created_at descending
    alerts_list.sort(key=lambda x: x.get("created_at") or "", reverse=True)

    # Deduplicate: keep latest per (user_name + alert_type + session_id)
    # Exception: check_in_pending/check_in_request always pass through
    seen = set()
    deduped = []
    for a in alerts_list:
        if a["alert_type"] in ("check_in_pending", "check_in_request"):
            deduped.append(a)
            continue
        key = (a.get("user_name", ""), a["alert_type"], a.get("session_id") or "")
        if key not in seen:
            seen.add(key)
            deduped.append(a)

    logger.info(f"ALERTS_FETCH guardian={guardian_email} raw={len(alerts_list)} deduped={len(deduped)}")
    return deduped[:limit]


async def get_session_history(session: AsyncSession, guardian_email: str, limit: int = 20, guardian_user_id: str | None = None, user_role: str | None = None) -> list[dict]:
    """Get completed journey history for guardian's loved ones."""
    user_ids = await _get_linked_user_ids(session, guardian_email, guardian_user_id, user_role)
    if not user_ids:
        return []

    # Pre-fetch user names
    user_result = await session.execute(select(User).where(User.id.in_(user_ids)))
    user_names = {u.id: u.full_name or u.email for u in user_result.scalars().all()}

    result = await session.execute(
        select(GuardianSession).where(
            GuardianSession.user_id.in_(user_ids),
            GuardianSession.status.in_(["ended", "expired"]),
        ).order_by(GuardianSession.ended_at.desc()).limit(limit)
    )

    history = []
    for gs in result.scalars().all():
        ac = await session.execute(
            select(func.count()).where(GuardianAlert.session_id == gs.id)
        )
        duration = round(((gs.ended_at or gs.started_at) - gs.started_at).total_seconds() / 60, 1)
        history.append({
            "session_id": str(gs.id),
            "user_name": user_names.get(gs.user_id, "Unknown"),
            "started_at": gs.started_at.isoformat(),
            "ended_at": gs.ended_at.isoformat() if gs.ended_at else None,
            "duration_minutes": duration,
            "max_risk_level": gs.risk_level,
            "total_distance_m": round(gs.total_distance_m, 1),
            "alert_count": ac.scalar() or 0,
            "escalation_level": gs.escalation_level,
        })

    return history


async def request_safety_check(session: AsyncSession, session_id: str, guardian_email: str) -> dict:
    """Guardian requests a safety check from the monitored user."""
    # Verify guardian has access to this session
    gs_result = await session.execute(
        select(GuardianSession).where(
            GuardianSession.id == uuid.UUID(session_id),
            GuardianSession.status == "active",
        )
    )
    gs = gs_result.scalar_one_or_none()
    if not gs:
        return {"error": "No active session found"}

    # Find the guardian user to get their ID
    g_res = await session.execute(select(User).where(User.email == guardian_email))
    g_user = g_res.scalar_one_or_none()
    if not g_user:
        return {"error": "Guardian not found"}

    # Verify this guardian is linked to the user via User.guardian_id
    c_res = await session.execute(
        select(User).where(
            User.id == gs.user_id,
            User.guardian_id == g_user.id,
            User.is_active == True
        )
    )
    if not c_res.scalar_one_or_none():
        return {"error": "Not authorized for this session"}

    from app.services.guardian_mode_engine import _create_alert
    alert = await _create_alert(
        session, session_id, "check_in_request", "medium",
        "Guardian requested safety confirmation",
        "A guardian has requested that you confirm you are safe",
        "Please confirm your safety status",
        gs.current_location, user_id=str(gs.user_id),
    )

    return {
        "requested": True,
        "session_id": session_id,
        "alert_id": str(alert.id),
    }


async def get_child_alerts(session: AsyncSession, child_user_id: str, limit: int = 50) -> list[dict]:
    """Get alerts/check-ins addressed TO this child."""
    child_uuid = uuid.UUID(child_user_id)
    alerts_list: list[dict] = []

    # Check-ins where this child is the subject (last 24 hours, pending only)
    from app.models.checkin import CheckIn
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    ci_result = await session.execute(
        select(CheckIn).where(
            CheckIn.child_id == child_uuid,
            CheckIn.created_at >= cutoff,
            CheckIn.status == 'pending',
        ).order_by(CheckIn.created_at.desc()).limit(limit)
    )
    ci_rows = ci_result.scalars().all()

    # Fallback: if 24h pending returns empty, get latest 5 of any status for history
    if not ci_rows:
        fallback = await session.execute(
            select(CheckIn).where(
                CheckIn.child_id == child_uuid,
            ).order_by(CheckIn.created_at.desc()).limit(5)
        )
        ci_rows = fallback.scalars().all()

    logger.info(f"ALERTS_FETCH child={child_user_id} checkin_rows={len(ci_rows)}")

    CHECKIN_TYPE = {"help": "help_requested", "pending": "check_in_pending", "expired": "check_in_expired", "safe": "check_in_safe"}
    CHECKIN_SEVERITY = {"help": "critical", "pending": "medium", "expired": "high", "safe": "low"}

    for ci in ci_rows:
        guardian_result = await session.execute(select(User).where(User.id == ci.guardian_id))
        guardian = guardian_result.scalar_one_or_none()
        guardian_name = guardian.full_name if guardian else "Guardian"

        ci_status = ci.status or "pending"
        msg_map = {
            "pending": f"{guardian_name} is checking on you — please respond.",
            "help": "You responded that you need help. Guardian has been notified.",
            "safe": "You confirmed you are safe.",
            "expired": f"{guardian_name}'s safety check expired without response.",
        }

        alerts_list.append({
            "id": str(ci.id),
            "session_id": None,
            "user_name": guardian_name,
            "alert_type": CHECKIN_TYPE.get(ci_status, "check_in_request"),
            "type": CHECKIN_TYPE.get(ci_status, "check_in_request"),
            "severity": CHECKIN_SEVERITY.get(ci_status, "medium"),
            "message": msg_map.get(ci_status, f"Check-in from {guardian_name}: {ci_status}"),
            "details": f"Check-in ID: {ci.id}",
            "recommendation": "Respond to let your guardian know you are safe." if ci_status == "pending" else None,
            "location": None,
            "created_at": (ci.responded_at or ci.created_at).isoformat(),
            "responded": ci_status != "pending",
            "response": ci_status,
        })

    alerts_list.sort(key=lambda a: a["created_at"], reverse=True)

    # Deduplicate: keep latest per (user_name + alert_type + session_id)
    # Exception: check_in_pending/check_in_request always pass through
    seen = set()
    deduped = []
    for a in alerts_list:
        if a["alert_type"] in ("check_in_pending", "check_in_request"):
            deduped.append(a)
            continue
        key = (a.get("user_name", ""), a["alert_type"], a.get("session_id") or "")
        if key not in seen:
            seen.add(key)
            deduped.append(a)

    logger.info(f"ALERTS_FETCH child={child_user_id} raw={len(alerts_list)} deduped={len(deduped)}")
    return deduped
