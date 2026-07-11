"""NISCH-008 — Daily emergency-stream retention sweeper.

DPDP-mandated: emergency media must be deleted 90 days after capture.
The S3 lifecycle rule will eventually catch real-S3 objects, but:
  * Stub-mode local-disk files have NO bucket lifecycle.
  * The `stream_recording_chunks` / `stream_playback_audits` ROWS
    must vanish too — auditors must not see "this chunk existed but
    we won't tell you its key" because that's still data.

This sweeper closes both gaps:
  1. Scans for chunks where `expires_at <= now()`.
  2. Best-effort deletes the underlying object (local file or S3).
  3. Deletes the row (cascade kills the audit rows via FK ON DELETE).
  4. Logs `[NISCH-008-SWEEP] purged=N failed=M` for SRE visibility.

Schedule: daily at **03:00 IST** = 21:30 UTC. Low-traffic window;
the per-chunk delete is cheap so there's no need for batching beyond
a single SQL DELETE.

Idempotent: a second sweep finds nothing to delete.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.stream_playback_audit import StreamPlaybackAudit
from app.models.stream_recording_chunk import StreamRecordingChunk
from app.services import emergency_stream_service as svc

logger = logging.getLogger(__name__)


async def run_emergency_stream_retention_sweep(
    db: AsyncSession | None = None,
) -> dict:
    """Delete expired stream-recording chunks + their underlying objects.

    Returns: `{"purged": N, "failed": M, "scanned": K}`.
    """
    own_session = db is None
    session = db or async_session()
    try:
        if own_session:
            session = await session.__aenter__()
        now = datetime.now(timezone.utc)
        expired = (await session.execute(
            select(StreamRecordingChunk).where(
                StreamRecordingChunk.expires_at <= now
            )
        )).scalars().all()

        purged = 0
        failed = 0
        for chunk in expired:
            try:
                if svc.MOCK_S3:
                    # Stub mode — best-effort unlink the local file.
                    try:
                        p = svc._local_path(chunk.s3_key)
                        if p.exists():
                            p.unlink()
                    except (FileNotFoundError, ValueError):
                        pass
                else:
                    # Real S3 — issue a single DeleteObject. The bucket
                    # lifecycle rule normally handles this, but explicit
                    # is better than waiting for the S3 sweeper window.
                    try:
                        import boto3
                        client = boto3.client(
                            "s3",
                            region_name=os.environ.get("AWS_REGION", "ap-south-1"),
                            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
                            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
                        )
                        client.delete_object(Bucket=svc.BUCKET, Key=chunk.s3_key)
                    except Exception as e:
                        logger.debug(f"[NISCH-008-SWEEP] s3 delete failed "
                                     f"key={chunk.s3_key}: {e}")
                await session.delete(chunk)  # ← cascades to audits
                # SQLite ignores ON DELETE CASCADE without an explicit
                # PRAGMA. Be defensive and delete audits ourselves —
                # cheap and works on every backend.
                await session.execute(
                    delete(StreamPlaybackAudit)
                    .where(StreamPlaybackAudit.chunk_id == chunk.id)
                )
                purged += 1
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"[NISCH-008-SWEEP] chunk purge failed id={chunk.id}: {e}"
                )
                failed += 1
        await session.commit()
        logger.info(
            f"[NISCH-008-SWEEP] purged={purged} failed={failed} "
            f"scanned={len(expired)}"
        )
        return {"purged": purged, "failed": failed, "scanned": len(expired)}
    finally:
        if own_session:
            await session.__aexit__(None, None, None)
