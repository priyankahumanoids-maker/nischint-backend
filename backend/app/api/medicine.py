"""Senior medicine schedules and dose-adherence API.

This endpoint is intentionally user-account backed.  The legacy ``seniors``
table represents dependent profiles and does not identify the signed-in Senior
account used by the mobile application.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_user_active, get_db_session
from app.core.product_roles import is_guardian_monitor, normalize_role
from app.models.user import User
from app.services.guardian_dashboard_engine import _get_linked_user_ids

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/senior/medicine", tags=["senior-medicine"])

_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_ALLOWED_DOSE_STATUSES = {"taken", "missed", "skipped"}


class MedicationScheduleCreate(BaseModel):
    user_id: str | None = None
    name: str
    dosage: str
    instructions: str | None = None
    time_of_day: str
    timezone: str = "Asia/Kolkata"
    days_of_week: list[int] | None = None
    starts_on: str | None = None
    ends_on: str | None = None


class MedicationScheduleUpdate(BaseModel):
    name: str | None = None
    dosage: str | None = None
    instructions: str | None = None
    time_of_day: str | None = None
    timezone: str | None = None
    days_of_week: list[int] | None = None
    starts_on: str | None = None
    ends_on: str | None = None
    is_active: bool | None = None


class DoseStatusRequest(BaseModel):
    status: str
    scheduled_for: str
    notes: str | None = None


def _model_dict(model: BaseModel, *, exclude_unset: bool = False) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_unset=exclude_unset)
    return model.dict(exclude_unset=exclude_unset)


def _parse_uuid(value: object, field: str = "user_id") -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(status_code=400, detail=f"Invalid {field}")


def _parse_date(value: str | None, *, default: date | None = None) -> date | None:
    if value in (None, ""):
        return default
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise HTTPException(status_code=400, detail="Date must use YYYY-MM-DD format")


def _validate_days(days: list[int] | None) -> list[int]:
    normalized = sorted(set(days if days is not None else range(7)))
    if not normalized or any(day < 0 or day > 6 for day in normalized):
        raise HTTPException(status_code=400, detail="days_of_week must contain values from 0 to 6")
    return normalized


def _validate_time(value: str) -> str:
    value = str(value or "").strip()
    if not _TIME_RE.match(value):
        raise HTTPException(status_code=400, detail="time_of_day must use 24-hour HH:MM format")
    return value


def _validate_timezone(value: str | None) -> str:
    zone = str(value or "Asia/Kolkata").strip() or "Asia/Kolkata"
    try:
        ZoneInfo(zone)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid timezone")
    return zone


async def _load_target_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    result = await session.execute(select(User).where(User.id == user_id, User.is_active == True))  # noqa: E712
    target = result.scalar_one_or_none()
    if not target or normalize_role(target.role) != "senior":
        raise HTTPException(status_code=404, detail="Linked Senior account not found")
    return target


async def _authorize_target(
    session: AsyncSession,
    current_user: User,
    requested_user_id: str | uuid.UUID | None,
    *,
    require_manager: bool = False,
) -> User:
    role = normalize_role(getattr(current_user, "role", None))

    if role == "senior":
        if require_manager:
            raise HTTPException(status_code=403, detail="Only a linked guardian can manage medicine schedules")
        if requested_user_id and _parse_uuid(requested_user_id) != current_user.id:
            raise HTTPException(status_code=403, detail="You can only access your own medicine plan")
        return await _load_target_user(session, current_user.id)

    if role == "admin":
        if not requested_user_id:
            raise HTTPException(status_code=400, detail="user_id is required")
        return await _load_target_user(session, _parse_uuid(requested_user_id))

    if not is_guardian_monitor(role):
        raise HTTPException(status_code=403, detail="Senior or linked guardian access required")
    if not requested_user_id:
        raise HTTPException(status_code=400, detail="Select a linked Senior first")

    target_id = _parse_uuid(requested_user_id)
    linked_ids = await _get_linked_user_ids(
        session,
        current_user.email,
        str(current_user.id),
        user_role=role,
        include_checkin_recovery=False,
    )
    if target_id not in set(linked_ids):
        raise HTTPException(status_code=403, detail="You are not linked as a guardian to this Senior")
    return await _load_target_user(session, target_id)


def _schedule_to_dict(row) -> dict:
    days = row.days_of_week
    if isinstance(days, str):
        try:
            days = json.loads(days)
        except Exception:
            days = []
    return {
        "id": str(row.id),
        "user_id": str(row.user_id),
        "name": row.name,
        "dosage": row.dosage,
        "instructions": row.instructions,
        "time_of_day": row.time_of_day,
        "timezone": row.timezone or "Asia/Kolkata",
        "days_of_week": list(days or []),
        "starts_on": row.starts_on.isoformat() if row.starts_on else None,
        "ends_on": row.ends_on.isoformat() if row.ends_on else None,
        "is_active": bool(row.is_active),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _today_window(zone: ZoneInfo) -> tuple[datetime, datetime, date]:
    now = datetime.now(zone)
    start = datetime.combine(now.date(), time.min, tzinfo=zone)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc), now.date()


async def _build_today(session: AsyncSession, schedules: list[dict]) -> list[dict]:
    if not schedules:
        return []

    owner_id = uuid.UUID(schedules[0]["user_id"])
    # A single India-time window covers the current mobile contract. Individual
    # schedule timezones are still used when building each scheduled instant.
    ist = ZoneInfo("Asia/Kolkata")
    day_start_utc, next_day_utc, today_ist = _today_window(ist)
    event_rows = (
        await session.execute(
            text(
                """
                SELECT schedule_id, scheduled_for, status, responded_at
                FROM medication_dose_events
                WHERE user_id = :user_id
                  AND scheduled_for >= :day_start
                  AND scheduled_for < :day_end
                """
            ),
            {
                "user_id": owner_id,
                "day_start": day_start_utc,
                "day_end": next_day_utc,
            },
        )
    ).fetchall()
    events = {str(row.schedule_id): row for row in event_rows}

    now_utc = datetime.now(timezone.utc)
    today: list[dict] = []
    for schedule in schedules:
        starts_on = _parse_date(schedule.get("starts_on"))
        ends_on = _parse_date(schedule.get("ends_on"))
        if starts_on and today_ist < starts_on:
            continue
        if ends_on and today_ist > ends_on:
            continue
        if today_ist.weekday() not in set(schedule.get("days_of_week") or []):
            continue

        zone = ZoneInfo(schedule.get("timezone") or "Asia/Kolkata")
        hour, minute = [int(part) for part in schedule["time_of_day"].split(":", 1)]
        scheduled_local = datetime.combine(today_ist, time(hour, minute), tzinfo=zone)
        scheduled_utc = scheduled_local.astimezone(timezone.utc)
        event = events.get(schedule["id"])

        if event:
            dose_status = event.status
            responded_at = event.responded_at.isoformat() if event.responded_at else None
        elif now_utc >= scheduled_utc + timedelta(minutes=30):
            dose_status = "missed"
            responded_at = None
        elif now_utc >= scheduled_utc:
            dose_status = "due"
            responded_at = None
        else:
            dose_status = "scheduled"
            responded_at = None

        today.append(
            {
                "schedule_id": schedule["id"],
                "name": schedule["name"],
                "dosage": schedule["dosage"],
                "instructions": schedule.get("instructions"),
                "time_of_day": schedule["time_of_day"],
                "timezone": schedule.get("timezone") or "Asia/Kolkata",
                "scheduled_for": scheduled_utc.isoformat(),
                "status": dose_status,
                "responded_at": responded_at,
            }
        )

    return sorted(today, key=lambda item: item["scheduled_for"])


async def _schedule_owner(session: AsyncSession, schedule_id: uuid.UUID) -> uuid.UUID:
    owner = (
        await session.execute(
            text("SELECT user_id FROM medication_schedules WHERE id = :id"),
            {"id": schedule_id},
        )
    ).scalar_one_or_none()
    if not owner:
        raise HTTPException(status_code=404, detail="Medicine schedule not found")
    return owner


async def _ensure_medicine_notification_table(session: AsyncSession) -> None:
    """Create the idempotency ledger used only for medicine push delivery.

    Existing medication schedule/dose tables stay untouched. The unique key is
    per recipient, so one unavailable co-parent can retry without re-notifying
    guardians who already received the same event.
    """
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS medication_notification_events (
                id UUID PRIMARY KEY,
                schedule_id UUID NOT NULL,
                protected_user_id UUID NOT NULL,
                recipient_user_id UUID NOT NULL,
                scheduled_for TIMESTAMPTZ NOT NULL,
                kind VARCHAR(48) NOT NULL,
                sent_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (schedule_id, recipient_user_id, scheduled_for, kind)
            )
            """
        )
    )


async def _claim_medicine_notification(
    session: AsyncSession,
    *,
    schedule_id: uuid.UUID,
    protected_user_id: uuid.UUID,
    recipient_user_id: uuid.UUID,
    scheduled_for: datetime,
    kind: str,
) -> uuid.UUID | None:
    await _ensure_medicine_notification_table(session)
    notification_id = uuid.uuid4()
    return (
        await session.execute(
            text(
                """
                INSERT INTO medication_notification_events
                    (id, schedule_id, protected_user_id, recipient_user_id,
                     scheduled_for, kind)
                VALUES
                    (:id, :schedule_id, :protected_user_id, :recipient_user_id,
                     :scheduled_for, :kind)
                ON CONFLICT (schedule_id, recipient_user_id, scheduled_for, kind)
                DO NOTHING
                RETURNING id
                """
            ),
            {
                "id": notification_id,
                "schedule_id": schedule_id,
                "protected_user_id": protected_user_id,
                "recipient_user_id": recipient_user_id,
                "scheduled_for": scheduled_for,
                "kind": kind,
            },
        )
    ).scalar_one_or_none()


async def _finish_medicine_notification(
    session: AsyncSession,
    notification_id: uuid.UUID,
    *,
    success: bool,
) -> None:
    if success:
        await session.execute(
            text(
                """
                UPDATE medication_notification_events
                SET sent_at = NOW()
                WHERE id = :id
                """
            ),
            {"id": notification_id},
        )
    else:
        # No successful push means the next scheduler/status retry may try again.
        await session.execute(
            text("DELETE FROM medication_notification_events WHERE id = :id"),
            {"id": notification_id},
        )
    await session.commit()


async def _medicine_guardian_ids(
    session: AsyncSession,
    protected_user_id: uuid.UUID,
) -> list[uuid.UUID]:
    """Primary guardian + active co-parent/co-guardian accounts for a member."""
    ordered: list[uuid.UUID] = []

    def add(value: object) -> None:
        if not value:
            return
        try:
            parsed = uuid.UUID(str(value))
        except (TypeError, ValueError, AttributeError):
            return
        if parsed not in ordered:
            ordered.append(parsed)

    primary = (
        await session.execute(
            text("SELECT guardian_id FROM users WHERE id = :uid"),
            {"uid": protected_user_id},
        )
    ).scalar_one_or_none()
    add(primary)

    # Active Guardian Network links cover explicit guardian/co-guardian links.
    rows = (
        await session.execute(
            text(
                """
                SELECT guardian_user_id
                FROM guardian_relationships
                WHERE user_id = :uid
                  AND is_active = TRUE
                  AND guardian_user_id IS NOT NULL
                ORDER BY is_primary DESC, priority ASC
                """
            ),
            {"uid": protected_user_id},
        )
    ).fetchall()
    for row in rows:
        add(getattr(row, "guardian_user_id", None))

    # Family-invite co-parent accounts may be represented by users.guardian_id
    # -> primary guardian even when no GuardianRelationship row exists.
    if primary:
        co_rows = (
            await session.execute(
                text(
                    """
                    SELECT id
                    FROM users
                    WHERE guardian_id = :primary_id
                      AND is_active = TRUE
                      AND LOWER(REPLACE(COALESCE(role, ''), '-', '_'))
                          IN ('co_parent', 'coparent', 'co_guardian')
                    ORDER BY created_at ASC
                    """
                ),
                {"primary_id": primary},
            )
        ).fetchall()
        for row in co_rows:
            add(getattr(row, "id", None))

    return ordered


async def _push_medicine_event(
    session: AsyncSession,
    recipient_user_id: uuid.UUID,
    *,
    title: str,
    body: str,
    data: dict,
) -> bool:
    try:
        from app.services.push_service import send_push_to_user
        sent = await send_push_to_user(
            session,
            recipient_user_id,
            title,
            body,
            data=data,
        )
        return int(sent or 0) > 0
    except Exception:
        logger.exception(
            "[MEDICINE_PUSH] recipient=%s event=%s failed",
            recipient_user_id,
            data.get("eventType") or data.get("type"),
        )
        return False


async def _deliver_due_reminder(
    session: AsyncSession,
    *,
    schedule_id: uuid.UUID,
    protected_user_id: uuid.UUID,
    medicine_name: str,
    dosage: str,
    scheduled_for: datetime,
) -> bool:
    claim = await _claim_medicine_notification(
        session,
        schedule_id=schedule_id,
        protected_user_id=protected_user_id,
        recipient_user_id=protected_user_id,
        scheduled_for=scheduled_for,
        kind="due",
    )
    if not claim:
        return False
    await session.commit()  # claim before FCM so concurrent workers cannot duplicate

    ok = await _push_medicine_event(
        session,
        protected_user_id,
        title="Medicine Reminder",
        body=f"Time to take {medicine_name} ({dosage}).",
        data={
            "eventType": "medicine_due",
            "type": "medicine_due",
            "screen": "medicine",
            "protected_member_id": str(protected_user_id),
            "schedule_id": str(schedule_id),
            "scheduled_for": scheduled_for.isoformat(),
            "medicine": medicine_name,
            "dosage": dosage,
            "status": "due",
        },
    )
    await _finish_medicine_notification(session, claim, success=ok)
    return ok


async def _schedule_name(session: AsyncSession, schedule_id: uuid.UUID) -> str:
    value = (
        await session.execute(
            text("SELECT name FROM medication_schedules WHERE id = :id"),
            {"id": schedule_id},
        )
    ).scalar_one_or_none()
    return str(value or "Medicine").strip() or "Medicine"


async def _protected_name(session: AsyncSession, protected_user_id: uuid.UUID) -> str:
    value = (
        await session.execute(
            text("SELECT full_name FROM users WHERE id = :uid"),
            {"uid": protected_user_id},
        )
    ).scalar_one_or_none()
    return str(value or "Protected member").strip() or "Protected member"


async def _deliver_status_to_guardians(
    session: AsyncSession,
    *,
    schedule_id: uuid.UUID,
    protected_user_id: uuid.UUID,
    scheduled_for: datetime,
    dose_status: str,
    medicine_name: str | None = None,
) -> int:
    normalized = str(dose_status or "").strip().lower()
    if normalized not in _ALLOWED_DOSE_STATUSES:
        return 0

    name = medicine_name or await _schedule_name(session, schedule_id)
    protected_name = await _protected_name(session, protected_user_id)
    guardian_ids = await _medicine_guardian_ids(session, protected_user_id)
    delivered = 0

    for guardian_id in guardian_ids:
        claim = await _claim_medicine_notification(
            session,
            schedule_id=schedule_id,
            protected_user_id=protected_user_id,
            recipient_user_id=guardian_id,
            scheduled_for=scheduled_for,
            kind=f"status:{normalized}",
        )
        if not claim:
            continue
        await session.commit()

        ok = await _push_medicine_event(
            session,
            guardian_id,
            title=f"{protected_name} - Medicine {normalized.title()}",
            body=f"{name} was marked as {normalized}.",
            data={
                "eventType": "medicine_status",
                "type": "medicine_status",
                "screen": "medicine",
                "protected_member_id": str(protected_user_id),
                "schedule_id": str(schedule_id),
                "scheduled_for": scheduled_for.isoformat(),
                "medicine": name,
                "status": normalized,
            },
        )
        await _finish_medicine_notification(session, claim, success=ok)
        delivered += int(ok)

    return delivered


def _schedule_days(value: object) -> set[int]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            value = []
    if not isinstance(value, (list, tuple, set)):
        return set()
    days: set[int] = set()
    for item in value:
        try:
            day = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= day <= 6:
            days.add(day)
    return days


def _scheduled_instant(row, local_day: date) -> datetime | None:
    if row.starts_on and local_day < row.starts_on:
        return None
    if row.ends_on and local_day > row.ends_on:
        return None
    days = _schedule_days(row.days_of_week)
    if days and local_day.weekday() not in days:
        return None
    try:
        zone = ZoneInfo(row.timezone or "Asia/Kolkata")
        hour, minute = [int(part) for part in str(row.time_of_day).split(":", 1)]
        return datetime.combine(local_day, time(hour, minute), tzinfo=zone).astimezone(timezone.utc)
    except Exception:
        logger.exception("[MEDICINE_SCHEDULER] invalid schedule id=%s", row.id)
        return None


@router.post("/internal/process-reminders")
async def process_medicine_reminders(
    x_nischint_scheduler_token: str | None = Header(
        default=None,
        alias="X-Nischint-Scheduler-Token",
    ),
    session: AsyncSession = Depends(get_db_session),
):
    """Idempotent Cloud Scheduler entry point for due + missed medicine events."""
    expected = str(os.getenv("NISCHINT_MEDICINE_SCHEDULER_TOKEN", "")).strip()
    supplied = str(x_nischint_scheduler_token or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Medicine scheduler token is not configured")
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="Invalid scheduler token")

    await _ensure_medicine_notification_table(session)
    await session.commit()
    rows = (
        await session.execute(
            text(
                """
                SELECT id, user_id, name, dosage, time_of_day, timezone,
                       days_of_week, starts_on, ends_on
                FROM medication_schedules
                WHERE is_active = TRUE
                """
            )
        )
    ).fetchall()

    now_utc = datetime.now(timezone.utc)
    due_sent = 0
    missed_created = 0
    guardian_status_pushes = 0

    for row in rows:
        try:
            schedule_id = uuid.UUID(str(row.id))
            protected_user_id = uuid.UUID(str(row.user_id))
            zone = ZoneInfo(row.timezone or "Asia/Kolkata")
            local_today = now_utc.astimezone(zone).date()
        except Exception:
            logger.exception("[MEDICINE_SCHEDULER] invalid schedule identity id=%s", getattr(row, "id", None))
            continue

        # Yesterday is included so a brief scheduler outage around midnight cannot
        # permanently lose a missed-dose transition.
        for local_day in (local_today, local_today - timedelta(days=1)):
            scheduled_for = _scheduled_instant(row, local_day)
            if not scheduled_for:
                continue
            age = now_utc - scheduled_for
            if age.total_seconds() < 0 or age >= timedelta(hours=24):
                continue

            existing = (
                await session.execute(
                    text(
                        """
                        SELECT status
                        FROM medication_dose_events
                        WHERE schedule_id = :schedule_id
                          AND scheduled_for = :scheduled_for
                        """
                    ),
                    {"schedule_id": schedule_id, "scheduled_for": scheduled_for},
                )
            ).first()

            if existing:
                guardian_status_pushes += await _deliver_status_to_guardians(
                    session,
                    schedule_id=schedule_id,
                    protected_user_id=protected_user_id,
                    scheduled_for=scheduled_for,
                    dose_status=str(existing.status or ""),
                    medicine_name=str(row.name or "Medicine"),
                )
                continue

            if age < timedelta(minutes=30):
                due_sent += int(
                    await _deliver_due_reminder(
                        session,
                        schedule_id=schedule_id,
                        protected_user_id=protected_user_id,
                        medicine_name=str(row.name or "Medicine"),
                        dosage=str(row.dosage or ""),
                        scheduled_for=scheduled_for,
                    )
                )
                continue

            inserted = (
                await session.execute(
                    text(
                        """
                        INSERT INTO medication_dose_events
                            (id, schedule_id, user_id, scheduled_for, status,
                             responded_at, responded_by, notes, updated_at)
                        VALUES
                            (:id, :schedule_id, :user_id, :scheduled_for,
                             'missed', NOW(), NULL,
                             'Automatically marked missed after 30 minutes', NOW())
                        ON CONFLICT (schedule_id, scheduled_for) DO NOTHING
                        RETURNING id
                        """
                    ),
                    {
                        "id": uuid.uuid4(),
                        "schedule_id": schedule_id,
                        "user_id": protected_user_id,
                        "scheduled_for": scheduled_for,
                    },
                )
            ).scalar_one_or_none()
            await session.commit()
            missed_created += int(bool(inserted))

            guardian_status_pushes += await _deliver_status_to_guardians(
                session,
                schedule_id=schedule_id,
                protected_user_id=protected_user_id,
                scheduled_for=scheduled_for,
                dose_status="missed",
                medicine_name=str(row.name or "Medicine"),
            )

    return {
        "ok": True,
        "schedules_checked": len(rows),
        "due_notifications_sent": due_sent,
        "missed_events_created": missed_created,
        "guardian_status_pushes_sent": guardian_status_pushes,
        "processed_at": now_utc.isoformat(),
    }


@router.get("")
async def get_medicine_plan(
    user_id: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    target = await _authorize_target(session, current_user, user_id)
    rows = (
        await session.execute(
            text(
                """
                SELECT id, user_id, name, dosage, instructions, time_of_day,
                       timezone, days_of_week, starts_on, ends_on, is_active,
                       created_at, updated_at
                FROM medication_schedules
                WHERE user_id = :user_id
                  AND (:include_inactive OR is_active = TRUE)
                ORDER BY is_active DESC, time_of_day ASC, created_at ASC
                """
            ),
            {"user_id": target.id, "include_inactive": include_inactive},
        )
    ).fetchall()
    schedules = [_schedule_to_dict(row) for row in rows]
    today = await _build_today(session, [item for item in schedules if item["is_active"]])
    return {
        "senior": {
            "id": str(target.id),
            "user_id": str(target.id),
            "full_name": target.full_name,
            "email": target.email,
            "role": normalize_role(target.role),
        },
        "schedules": schedules,
        "today": today,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_medicine_schedule(
    payload: MedicationScheduleCreate,
    current_user: User = Depends(get_current_user_active),
    session: AsyncSession = Depends(get_db_session),
):
    target = await _authorize_target(
        session,
        current_user,
        payload.user_id,
        require_manager=True,
    )
    name = payload.name.strip()
    dosage = payload.dosage.strip()
    if not name or not dosage:
        raise HTTPException(status_code=400, detail="Medicine name and dosage are required")
    time_of_day = _validate_time(payload.time_of_day)
    zone = _validate_timezone(payload.timezone)
    days = _validate_days(payload.days_of_week)
    starts_on = _parse_date(
        payload.starts_on,
        default=datetime.now(ZoneInfo("Asia/Kolkata")).date(),
    )
    ends_on = _parse_date(payload.ends_on)
    if ends_on and starts_on and ends_on < starts_on:
        raise HTTPException(status_code=400, detail="ends_on cannot be before starts_on")

    schedule_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO medication_schedules
                (id, user_id, created_by, name, dosage, instructions, time_of_day,
                 timezone, days_of_week, starts_on, ends_on, is_active)
            VALUES
                (:id, :user_id, :created_by, :name, :dosage, :instructions,
                 :time_of_day, :timezone, CAST(:days AS jsonb), :starts_on,
                 :ends_on, TRUE)
            """
        ),
        {
            "id": schedule_id,
            "user_id": target.id,
            "created_by": current_user.id,
            "name": name,
            "dosage": dosage,
            "instructions": payload.instructions.strip() if payload.instructions else None,
            "time_of_day": time_of_day,
            "timezone": zone,
            "days": json.dumps(days),
            "starts_on": starts_on,
            "ends_on": ends_on,
        },
    )
    return {"id": str(schedule_id), "user_id": str(target.id), "status": "created"}


@router.patch("/{schedule_id}")
async def update_medicine_schedule(
    schedule_id: str,
    payload: MedicationScheduleUpdate,
    current_user: User = Depends(get_current_user_active),
    session: AsyncSession = Depends(get_db_session),
):
    sid = _parse_uuid(schedule_id, "schedule_id")
    owner_id = await _schedule_owner(session, sid)
    await _authorize_target(session, current_user, owner_id, require_manager=True)

    values = _model_dict(payload, exclude_unset=True)
    if not values:
        return {"id": str(sid), "status": "unchanged"}

    setters: list[str] = []
    params: dict = {"id": sid}
    for field in ("name", "dosage", "instructions", "time_of_day", "timezone", "starts_on", "ends_on", "is_active"):
        if field not in values:
            continue
        value = values[field]
        if field in {"name", "dosage"}:
            value = str(value or "").strip()
            if not value:
                raise HTTPException(status_code=400, detail=f"{field} cannot be empty")
        elif field == "time_of_day":
            value = _validate_time(str(value))
        elif field == "timezone":
            value = _validate_timezone(str(value))
        elif field in {"starts_on", "ends_on"}:
            value = _parse_date(value)
        elif field == "instructions" and value is not None:
            value = str(value).strip() or None
        setters.append(f"{field} = :{field}")
        params[field] = value

    if "days_of_week" in values:
        setters.append("days_of_week = CAST(:days_of_week AS jsonb)")
        params["days_of_week"] = json.dumps(_validate_days(values["days_of_week"]))

    if setters:
        setters.append("updated_at = NOW()")
        await session.execute(
            text(f"UPDATE medication_schedules SET {', '.join(setters)} WHERE id = :id"),
            params,
        )
    return {"id": str(sid), "status": "updated"}


@router.delete("/{schedule_id}")
async def deactivate_medicine_schedule(
    schedule_id: str,
    current_user: User = Depends(get_current_user_active),
    session: AsyncSession = Depends(get_db_session),
):
    sid = _parse_uuid(schedule_id, "schedule_id")
    owner_id = await _schedule_owner(session, sid)
    await _authorize_target(session, current_user, owner_id, require_manager=True)
    await session.execute(
        text("UPDATE medication_schedules SET is_active = FALSE, updated_at = NOW() WHERE id = :id"),
        {"id": sid},
    )
    return {"id": str(sid), "status": "inactive"}


@router.post("/{schedule_id}/status")
async def record_dose_status(
    schedule_id: str,
    payload: DoseStatusRequest,
    current_user: User = Depends(get_current_user_active),
    session: AsyncSession = Depends(get_db_session),
):
    sid = _parse_uuid(schedule_id, "schedule_id")
    owner_id = await _schedule_owner(session, sid)
    await _authorize_target(session, current_user, owner_id)

    dose_status = str(payload.status or "").strip().lower()
    if dose_status not in _ALLOWED_DOSE_STATUSES:
        raise HTTPException(status_code=400, detail="status must be taken, missed, or skipped")
    try:
        scheduled_for = datetime.fromisoformat(payload.scheduled_for.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="scheduled_for must be an ISO-8601 timestamp")
    if scheduled_for.tzinfo is None:
        scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
    scheduled_for = scheduled_for.astimezone(timezone.utc)

    await session.execute(
        text(
            """
            INSERT INTO medication_dose_events
                (id, schedule_id, user_id, scheduled_for, status, responded_at,
                 responded_by, notes, updated_at)
            VALUES
                (:id, :schedule_id, :user_id, :scheduled_for, :status, NOW(),
                 :responded_by, :notes, NOW())
            ON CONFLICT (schedule_id, scheduled_for)
            DO UPDATE SET
                status = EXCLUDED.status,
                responded_at = NOW(),
                responded_by = EXCLUDED.responded_by,
                notes = EXCLUDED.notes,
                updated_at = NOW()
            """
        ),
        {
            "id": uuid.uuid4(),
            "schedule_id": sid,
            "user_id": owner_id,
            "scheduled_for": scheduled_for,
            "status": dose_status,
            "responded_by": current_user.id,
            "notes": payload.notes.strip() if payload.notes else None,
        },
    )
    # Persist the dose first. Push delivery is best-effort and idempotent.
    await session.commit()
    guardians_notified = await _deliver_status_to_guardians(
        session,
        schedule_id=sid,
        protected_user_id=owner_id,
        scheduled_for=scheduled_for,
        dose_status=dose_status,
    )
    return {
        "schedule_id": str(sid),
        "scheduled_for": scheduled_for.isoformat(),
        "status": dose_status,
        "guardians_notified": guardians_notified,
    }
