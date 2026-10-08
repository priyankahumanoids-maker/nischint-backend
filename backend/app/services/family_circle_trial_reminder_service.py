"""Day 5/6/7 Trial reminder enqueueing using the existing Family outbox."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.family_circle_notification_outbox import enqueue_family_notifications


async def enqueue_due_trial_reminders(session: AsyncSession, *, now: datetime | None = None) -> int:
    point = now or datetime.now(timezone.utc)
    rows = (await session.execute(text("""
        SELECT c.id AS circle_id, c.owner_user_id, c.trial_started_at, c.trial_ends_at
          FROM family_circles c
          JOIN family_circle_entitlements e ON e.circle_id=c.id
         WHERE c.status='active' AND c.plan='trial' AND e.state='trial_active'
           AND c.trial_started_at IS NOT NULL AND c.trial_ends_at IS NOT NULL
           AND :now >= c.trial_started_at + INTERVAL '4 days'
           AND :now < c.trial_ends_at
    """), {'now': point})).mappings().all()
    created = 0
    for row in rows:
        elapsed = point - row['trial_started_at']
        day = min(7, max(5, int(elapsed.total_seconds() // 86400) + 1))
        day_start = row['trial_started_at'] + timedelta(days=day - 1)
        day_end = min(row['trial_ends_at'], day_start + timedelta(days=1))
        if not (day_start <= point < day_end) or day not in {5, 6, 7}:
            continue
        remaining_days = max(0, 7 - day)
        body = (
            f"Your NISCHINT trial is on Day {day}. "
            + ("Full protection ends today unless the plan is renewed." if day == 7
               else f"{remaining_days} day{'s' if remaining_days != 1 else ''} remain after today.")
        )
        ids = await enqueue_family_notifications(
            session, circle_id=row['circle_id'], recipient_user_ids=[row['owner_user_id']],
            event_type='family_trial_reminder', title='NISCHINT trial reminder', body=body,
            payload={'trial_day': day, 'trial_ends_at': row['trial_ends_at'].isoformat()},
            event_key_prefix=f"trial-reminder:{row['circle_id']}:day{day}",
        )
        created += len(ids)
    return created


__all__ = ['enqueue_due_trial_reminders']
