# Notification Worker - Polls notification_jobs and delivers via SES/Twilio/FCM
import logging
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, and_, text, update

from app.core.config import settings
from app.db.session import async_session
from app.models.notification_job import NotificationJob

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = settings.worker_max_attempts
BATCH_SIZE = settings.worker_batch_size
POLL_INTERVAL_SECONDS = settings.worker_poll_interval
BACKOFF_BASE = settings.worker_backoff_base

worker_scheduler = AsyncIOScheduler()


def _backoff_seconds(attempts: int) -> int:
    """Exponential backoff based on configured base."""
    return BACKOFF_BASE * (2 ** attempts)


async def _deliver_email(recipient: str, payload: dict) -> bool:
    """Send email via SES."""
    from app.services.notification_service import _send_ses_email, EMAIL_PROVIDER
    if EMAIL_PROVIDER != "ses":
        logger.info(f"EMAIL (stub): To={recipient}, Subject={payload.get('subject', 'N/A')}")
        return True
    subject = payload.get("subject", "NISCHINT Alert")
    body = payload.get("body", "")
    return _send_ses_email(recipient, body)


async def _deliver_sms(recipient: str, payload: dict) -> bool:
    """Send SMS via Twilio."""
    from app.services.sms_service import send_sms, SMS_PROVIDER
    if SMS_PROVIDER != "twilio":
        logger.info(f"SMS (stub): To={recipient}, Body={payload.get('body', '')[:80]}...")
        return True
    body = payload.get("body", "")
    return send_sms(recipient, body)


async def _deliver_push(recipient: str, payload: dict, session) -> bool:
    """Send push via FCM. recipient = user_id (string UUID)."""
    from app.services.push_service import send_push_to_user
    from uuid import UUID
    user_id = UUID(recipient)
    title = payload.get("title", "NISCHINT Alert")
    body = payload.get("body", "")
    count = await send_push_to_user(session=session, user_id=user_id, title=title, body=body)
    return count > 0


async def process_notification_jobs():
    """Poll pending/retrying jobs, deliver, update status."""
    async with async_session() as session:
        try:
            now = datetime.now(timezone.utc)

            # Fetch jobs that are pending OR retrying (with backoff elapsed)
            stmt = (
                select(NotificationJob)
                .where(
                    and_(
                        NotificationJob.status.in_(["pending", "retrying"]),
                        NotificationJob.attempts < MAX_ATTEMPTS,
                    )
                )
                .with_for_update(skip_locked=True)
                .order_by(NotificationJob.created_at.asc())
                .limit(BATCH_SIZE)
            )
            result = await session.execute(stmt)
            jobs = result.scalars().all()

            if not jobs:
                return

            delivered = 0
            failed = 0

            for job in jobs:
                # Exponential backoff check for retrying jobs
                if job.status == "retrying" and job.last_attempt_at:
                    backoff = timedelta(seconds=_backoff_seconds(job.attempts))
                    if now < job.last_attempt_at + backoff:
                        continue  # Not yet time to retry

                job.attempts += 1
                job.last_attempt_at = now

                try:
                    success = False
                    if job.channel == "email":
                        success = await _deliver_email(job.recipient, job.payload)
                    elif job.channel == "sms":
                        success = await _deliver_sms(job.recipient, job.payload)
                    elif job.channel == "push":
                        success = await _deliver_push(job.recipient, job.payload, session)
                    else:
                        logger.warning(f"Unknown channel '{job.channel}' for job {job.id}")
                        job.status = "dead_letter"
                        failed += 1
                        continue

                    if success:
                        job.status = "sent"
                        delivered += 1
                        logger.info(f"Job {job.id} delivered: {job.channel} -> {job.recipient}")
                    else:
                        if job.attempts >= MAX_ATTEMPTS:
                            job.status = "dead_letter"
                            logger.error(f"Job {job.id} dead-lettered after {MAX_ATTEMPTS} attempts")
                            failed += 1
                        else:
                            job.status = "retrying"
                            logger.warning(
                                f"Job {job.id} failed attempt {job.attempts}/{MAX_ATTEMPTS}, "
                                f"next retry in {_backoff_seconds(job.attempts)}s"
                            )

                except Exception as e:
                    logger.error(f"Job {job.id} exception: {e}")
                    if job.attempts >= MAX_ATTEMPTS:
                        job.status = "dead_letter"
                        failed += 1
                    else:
                        job.status = "retrying"

            await session.commit()

            if delivered or failed:
                logger.info(f"Notification worker batch: delivered={delivered}, failed={failed}")

        except Exception as e:
            logger.error(f"Notification worker error: {e}")
            await session.rollback()


def start_notification_worker():
    if not worker_scheduler.running:
        worker_scheduler.add_job(
            process_notification_jobs,
            'interval',
            seconds=POLL_INTERVAL_SECONDS,
            id='notification_worker',
            replace_existing=True,
            # Stabilizers — Phase 1 isolation hardening:
            #   max_instances=3   → parallel pool absorbs spikes (safe:
            #                       SELECT … FOR UPDATE SKIP LOCKED guarantees
            #                       no double-deliver across instances)
            #   coalesce=True     → if N ticks pile up while a run is busy,
            #                       fold them into ONE catch-up run
            #   misfire_grace=30  → don't drop the job when an event-loop
            #                       stall causes the tick to land late
            max_instances=3,
            coalesce=True,
            misfire_grace_time=30,
        )
        worker_scheduler.start()
        logger.info(f"Notification worker started - polling every {POLL_INTERVAL_SECONDS}s")


def stop_notification_worker():
    if worker_scheduler.running:
        worker_scheduler.shutdown()
        logger.info("Notification worker stopped")
