# Dashboard Service — FAMILY-SCOPED incident queries
import re
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.senior import Senior
from app.models.device import Device
from app.models.incident import Incident
from app.models.guardian import Guardian as GuardianLink
from app.models.user import User


# Names that look like stale seed/test rows and should be excluded from user-facing counts.
_TEST_SENIOR_PATTERNS = re.compile(
    r"^(John Doe|TEST_|E2E_|Test_|Seed_|Demo_).*",
    re.IGNORECASE,
)


def is_test_senior_name(name: str | None) -> bool:
    """True if the senior name looks like a leftover test / seed row."""
    if not name:
        return False
    return bool(_TEST_SENIOR_PATTERNS.match(name.strip()))


async def _get_family_senior_ids(session: AsyncSession, guardian_id: UUID) -> list[UUID]:
    """
    Get ALL senior_ids in this guardian's family scope.

    Family scope: all seniors belonging to ANY guardian who monitors
    the same children as this guardian. This ensures mother and father
    both see the same incident pool.

    BEFORE: WHERE Senior.guardian_id == guardian_id  (per-user scope)
    AFTER:  WHERE Senior.guardian_id IN family_user_ids (family scope)
    """
    # Step 1: Get this guardian's email
    user_result = await session.execute(select(User.email).where(User.id == guardian_id))
    row = user_result.first()
    if not row:
        sr = await session.execute(select(Senior.id).where(Senior.guardian_id == guardian_id))
        return [r[0] for r in sr.fetchall()]

    guardian_email = row[0]

    # Step 2: Find children this guardian monitors (via guardians table)
    children = await session.execute(
        select(GuardianLink.user_id).where(
            GuardianLink.email == guardian_email,
            GuardianLink.is_active == True,  # noqa: E712
        )
    )
    child_ids = list(set(r[0] for r in children.all()))

    # Step 3: Find ALL guardian emails linked to those same children
    family_user_ids = {guardian_id}
    if child_ids:
        all_guardian_emails = await session.execute(
            select(GuardianLink.email).where(
                GuardianLink.user_id.in_(child_ids),
                GuardianLink.is_active == True,  # noqa: E712
                GuardianLink.email.isnot(None),
            )
        )
        family_emails = set(r[0] for r in all_guardian_emails.all())

        # Step 4: Resolve emails to user_ids
        if family_emails:
            family_users = await session.execute(
                select(User.id).where(User.email.in_(family_emails))
            )
            family_user_ids.update(r[0] for r in family_users.all())

    # Step 5: Get ALL seniors belonging to any family member — excluding test/seed rows
    senior_stmt = (
        select(Senior.id, Senior.full_name)
        .where(Senior.guardian_id.in_(list(family_user_ids)))
    )
    senior_result = await session.execute(senior_stmt)
    return [
        r[0]
        for r in senior_result.fetchall()
        if not is_test_senior_name(r[1])
    ]


async def get_guardian_summary(
    session: AsyncSession,
    guardian_id: UUID,
) -> dict:
    """
    Get aggregated dashboard summary for a guardian (FAMILY-SCOPED).
    `total_seniors` counts elderly seniors + real linked child/woman users.
    Test/seed seniors are excluded.
    """
    senior_ids = await _get_family_senior_ids(session, guardian_id)

    # Count unique elderly seniors by name (two rows named "Kid Nischint" count once).
    unique_senior_names: set[str] = set()
    if senior_ids:
        try:
            sn_rows = await session.execute(
                select(Senior.full_name).where(Senior.id.in_(senior_ids))
            )
            unique_senior_names = {
                (r[0] or "").strip().lower()
                for r in sn_rows.fetchall()
                if r[0]
            }
        except Exception:
            unique_senior_names = set()
    senior_names_lower = unique_senior_names

    # Also count real monitored users (children/women) linked via guardians table.
    # Dedupe against senior rows with the same name to avoid double-counting.
    monitored_user_count = 0
    try:
        user_row = await session.execute(select(User.email, User.role).where(User.id == guardian_id))
        urow = user_row.first()
        if urow:
            guardian_email, user_role = urow[0], urow[1]
            from app.services.guardian_dashboard_engine import get_loved_ones as _get_loved_ones
            lo = await _get_loved_ones(session, guardian_email, str(guardian_id), user_role=user_role)
            for m in (lo.get("monitored_users") or []):
                nm = (m.get("name") or "").strip().lower()
                if nm and nm in senior_names_lower:
                    continue  # de-duped: a senior entry already counted this person
                monitored_user_count += 1
    except Exception:
        # Never fail the whole summary over this enrichment.
        monitored_user_count = 0

    total_seniors = len(unique_senior_names) + monitored_user_count

    # When there are only monitored users (no elderly seniors), still return accurate counts.
    if not senior_ids:
        return {
            "total_seniors": total_seniors,
            "total_devices": 0,
            "active_incidents": 0,
            "critical_incidents": 0,
            "devices_online": 0,
            "devices_offline": 0,
        }

    # Count devices by status
    device_counts = await session.execute(
        select(
            Device.status,
            func.count(Device.id)
        )
        .where(Device.senior_id.in_(senior_ids))
        .group_by(Device.status)
    )
    device_status_map = {row[0]: row[1] for row in device_counts.fetchall()}

    total_devices = sum(device_status_map.values())
    devices_online = device_status_map.get("online", 0)
    devices_offline = device_status_map.get("offline", 0)

    # Count active incidents (FAMILY-SCOPED)
    active_incidents_result = await session.execute(
        select(func.count(Incident.id))
        .where(Incident.senior_id.in_(senior_ids))
        .where(Incident.status == "open")
    )
    active_incidents = active_incidents_result.scalar() or 0

    # Count critical incidents (FAMILY-SCOPED)
    critical_incidents_result = await session.execute(
        select(func.count(Incident.id))
        .where(Incident.senior_id.in_(senior_ids))
        .where(Incident.status == "open")
        .where(Incident.severity == "critical")
    )
    critical_incidents = critical_incidents_result.scalar() or 0

    return {
        "total_seniors": total_seniors,
        "total_devices": total_devices,
        "active_incidents": active_incidents,
        "critical_incidents": critical_incidents,
        "devices_online": devices_online,
        "devices_offline": devices_offline,
    }


async def get_sla_metrics(
    session: AsyncSession,
    guardian_id: UUID,
) -> dict:
    """Compute SLA metrics for a guardian's incidents (FAMILY-SCOPED)."""
    senior_ids = await _get_family_senior_ids(session, guardian_id)

    if not senior_ids:
        return {
            "total_incidents": 0,
            "acknowledged_count": 0,
            "resolved_count": 0,
            "avg_time_to_ack_seconds": None,
            "avg_time_to_resolve_seconds": None,
        }

    result = await session.execute(
        select(Incident).where(Incident.senior_id.in_(senior_ids))
    )
    incidents = result.scalars().all()

    acknowledged = [i for i in incidents if i.acknowledged_at]
    resolved = [i for i in incidents if i.resolved_at]

    avg_ack = None
    avg_resolve = None

    if acknowledged:
        avg_ack = sum(
            (i.acknowledged_at - i.created_at).total_seconds()
            for i in acknowledged
        ) / len(acknowledged)

    if resolved:
        avg_resolve = sum(
            (i.resolved_at - i.created_at).total_seconds()
            for i in resolved
        ) / len(resolved)

    return {
        "total_incidents": len(incidents),
        "acknowledged_count": len(acknowledged),
        "resolved_count": len(resolved),
        "avg_time_to_ack_seconds": round(avg_ack, 2) if avg_ack else None,
        "avg_time_to_resolve_seconds": round(avg_resolve, 2) if avg_resolve else None,
    }


async def get_response_metrics(session: AsyncSession) -> dict:
    """Get aggregated response metrics for all incidents (last 30 days)."""
    from sqlalchemy import text

    result = await session.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'open') AS active_unresolved,
            COUNT(*) FILTER (WHERE acknowledged_at IS NOT NULL) AS acknowledged_count,
            COUNT(*) FILTER (WHERE resolved_at IS NOT NULL) AS resolved_count,
            COUNT(*) FILTER (WHERE escalated = TRUE) AS escalation_count,
            AVG(EXTRACT(EPOCH FROM (acknowledged_at - created_at))) FILTER (WHERE acknowledged_at IS NOT NULL) AS avg_response_seconds,
            AVG(EXTRACT(EPOCH FROM (resolved_at - created_at))) FILTER (WHERE resolved_at IS NOT NULL) AS avg_resolution_seconds
        FROM incidents
        WHERE created_at > NOW() - INTERVAL '30 days'
    """))
    row = result.fetchone()

    total = row[0] or 0
    ack_count = row[2] or 0
    ack_rate = round((ack_count / total * 100), 1) if total > 0 else 0

    return {
        "period": "30d",
        "total_incidents": total,
        "active_unresolved": row[1] or 0,
        "acknowledged_count": ack_count,
        "resolved_count": row[3] or 0,
        "escalation_count": row[4] or 0,
        "acknowledgment_rate_pct": ack_rate,
        "avg_response_seconds": round(row[5] or 0, 1),
        "avg_resolution_seconds": round(row[6] or 0, 1),
    }
