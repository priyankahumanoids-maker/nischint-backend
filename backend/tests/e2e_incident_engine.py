"""E2E test for Incident State Engine — triggers a real transition,
waits past START_DEBOUNCE_S, and asserts the DB row exists.
Run: cd /app/backend && python -m tests.e2e_incident_engine
"""
import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


async def main():
    # Bootstrap DB session
    from app.db.session import async_session

    from app.services import system_incident_engine as eng
    from app.models.system_incident import SystemIncident
    from sqlalchemy import select

    # Compress debounce so the test runs in seconds.
    eng.START_DEBOUNCE_S = 1.0

    print("[e2e] Resolving any pre-existing active incident…")
    await eng.handle_transition(
        prev_severity="degraded", new_severity="healthy",
        source="scheduler", metric=None,
    )

    print("[e2e] Forcing healthy → degraded (scheduler / drift_p95)…")
    await eng.handle_transition(
        prev_severity="healthy", new_severity="degraded",
        source="scheduler", metric="drift_p95",
    )

    print("[e2e] Sleeping 2.5 s past debounce…")
    await asyncio.sleep(2.5)

    async with async_session() as s:
        rows = (await s.execute(
            select(SystemIncident)
            .where(SystemIncident.status == "active")
            .order_by(SystemIncident.started_at.desc())
        )).scalars().all()
    if not rows:
        print("[e2e] FAIL — no active incident written to DB")
        sys.exit(2)
    inc = rows[0]
    print(f"[e2e] OPENED  id={inc.id}  severity={inc.severity_peak}  "
          f"source={inc.trigger_source}  metric={inc.trigger_metric}")
    snap = inc.snapshot_json or {}
    print(f"[e2e] snapshot keys = {sorted(snap.keys())}")
    assert "scheduler" in snap and "ai" in snap and "queue" in snap and "ws" in snap, \
        f"snapshot incomplete: {snap}"

    print("[e2e] Forcing degraded → healthy (resolve)…")
    await eng.handle_transition(
        prev_severity="degraded", new_severity="healthy",
        source="scheduler", metric=None,
    )
    async with async_session() as s:
        row = (await s.execute(
            select(SystemIncident).where(SystemIncident.id == inc.id)
        )).scalar_one()
    assert row.status == "resolved", f"expected resolved, got {row.status}"
    assert row.resolved_at is not None
    assert row.duration_ms is not None and row.duration_ms >= 0
    assert row.resolution_json is not None
    print(f"[e2e] RESOLVED id={row.id}  duration_ms={row.duration_ms}")
    print("[e2e] PASS — full lifecycle (open → snapshot → resolve) verified")


if __name__ == "__main__":
    asyncio.run(main())
