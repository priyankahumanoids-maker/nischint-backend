"""
SB-01 Day 1 — Safety Brain Hermes learning-loop API.

Path A (read-only):
  GET  /api/admin/sb01/status                — operator/admin only
  GET  /api/admin/sb01/user-baseline/{uid}   — operator/admin only

Path D (ground-truth capture):
  POST /api/safety-events/{event_id}/feedback — auth-gated to the
       event's own user OR a registered guardian OR an operator.

Day 2 (Hermes weight attenuator):
  • `get_user_attenuation(session, user_id)` — per-signal multipliers
    in [0.5, 1.0] from `safety_event_feedback` aggregated by
    `safety_events.primary_event`. New users (no feedback) → empty
    dict (full SF-01 v2 weights, Himalaya invariant holds).
  • `get_time_multiplier(hour)` — pure helper, off-hours nudge.
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.models.user import User

logger = logging.getLogger(__name__)

admin_router = APIRouter(prefix="/admin/sb01", tags=["safety-brain"])
feedback_router = APIRouter(prefix="/safety-events", tags=["safety-brain"])


# ── SB-01 Day 2 — Hermes attenuator tunables ────────────────────────

# Minimum (confirmed + false_positive) verdicts per primary_event
# before we apply ANY attenuation. Below this we trust the SF-01 v2
# locked weights as-is — that's the Himalaya-invariant gate for new
# users. Five samples comes from the same heuristic we use elsewhere
# in this codebase (MIN_SAMPLES_FOR_BASELINE in baseline_scheduler).
MIN_FEEDBACK_SAMPLES = 5

# Full-confidence threshold — total verdicts above this contribute
# their full FP rate; below, we linearly scale the impact so a 1-FP-
# in-5-samples (0.2 rate) doesn't yank a weight as hard as a 4-FP-in-
# 20-samples user (also 0.2 rate but much more evidence).
FULL_CONFIDENCE_AT = 20

# Maximum weight reduction. A signal can be attenuated to AT MOST
# 50% of SF-01 v2 strength. We never zero out — even a chronically
# false-positive user must remain protected against the next real
# emergency.
MAX_ATTENUATION = 0.5

# Time-of-day defaults. Off-hours events get a 1.15 nudge. Falls
# outside the 6am-10pm window when the user is "supposed" to be
# inactive carry slightly elevated suspicion.
DEFAULT_NORMAL_START = 6
DEFAULT_NORMAL_END = 22
OFF_HOURS_MULTIPLIER = 1.15
TIME_MULT_CEILING = 1.30


def _require_operator_or_admin(user: User) -> None:
    if user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Admin or operator only")


# ── Day 2 — Hermes attenuator (pure functions, no router) ───────────


def get_time_multiplier(
    hour: int,
    normal_start: int = DEFAULT_NORMAL_START,
    normal_end: int = DEFAULT_NORMAL_END,
) -> float:
    """
    Return a context multiplier for the time-of-day.

    Inside `[normal_start, normal_end)` → 1.0 (no nudge).
    Outside → `OFF_HOURS_MULTIPLIER` (1.15), capped at `TIME_MULT_CEILING`.

    `normal_start` / `normal_end` will eventually come from per-device
    `device_baselines.hour_of_day` data; for Day 2 we use global
    defaults so the math is deterministic and the Himalaya invariant
    is provable.
    """
    h = int(hour) % 24
    in_window = normal_start <= h < normal_end
    mult = 1.0 if in_window else OFF_HOURS_MULTIPLIER
    return min(mult, TIME_MULT_CEILING)


async def get_user_attenuation(session: AsyncSession, user_id: str) -> dict:
    """
    Compute per-signal weight-attenuation multipliers from this user's
    `safety_event_feedback` history. Aggregated by the **primary_event**
    field of the underlying SafetyEvent (the locked enum, NOT the raw
    `signals` JSON keys).

    Returns:
        {
            "multipliers":  {"fall": 0.85, "voice": 1.0, ...},
            "samples":      {"fall": 12, "voice": 4, ...},
            "verdicts":     12,                # total samples used
            "source":       "12 feedback verdicts" or "no feedback yet",
        }

    New users (no feedback at all) → `multipliers = {}`, source
    `"no feedback yet"`. The brain treats this as "use SF-01 v2
    weights as-is" — that's how the Himalaya invariant survives.

    Per-event-type with < `MIN_FEEDBACK_SAMPLES` (confirmed+FP) verdicts
    → multiplier 1.0 (signal-level new-user path).
    """
    # We aggregate feedback ABOUT events whose *subject* is this user
    # (regardless of who graded — guardian, operator, or self).
    rows = (await session.execute(text("""
        SELECT se.primary_event, sef.verdict, COUNT(*)::int AS n
        FROM safety_event_feedback sef
        JOIN safety_events se ON se.id = sef.safety_event_id
        WHERE se.user_id = :uid
          AND sef.verdict IN ('confirmed', 'false_positive')
        GROUP BY se.primary_event, sef.verdict
    """), {"uid": user_id})).all()

    if not rows:
        return {
            "multipliers": {},
            "samples": {},
            "verdicts": 0,
            "source": "no feedback yet",
        }

    # bucket[event][verdict] = count
    bucket: dict[str, dict[str, int]] = {}
    for r in rows:
        ev = (r.primary_event or "").strip()
        if not ev:
            continue
        bucket.setdefault(ev, {"confirmed": 0, "false_positive": 0})
        bucket[ev][r.verdict] = int(r.n)

    multipliers: dict[str, float] = {}
    samples: dict[str, int] = {}
    total_used = 0

    for event_type, counts in bucket.items():
        confirmed = counts.get("confirmed", 0)
        fp = counts.get("false_positive", 0)
        total = confirmed + fp
        samples[event_type] = total
        total_used += total

        if total < MIN_FEEDBACK_SAMPLES:
            # Not enough evidence yet — no attenuation for this signal.
            multipliers[event_type] = 1.0
            continue

        fp_rate = fp / total
        # Confidence factor scales linearly with sample size up to a
        # plateau at FULL_CONFIDENCE_AT. Below the plateau, a 50% FP
        # rate with 5 samples is treated as half as impactful as a
        # 50% FP rate with 20 samples.
        confidence_factor = min(total / FULL_CONFIDENCE_AT, 1.0)
        reduction = min(fp_rate * confidence_factor, MAX_ATTENUATION)
        # Multiplier ∈ [0.5, 1.0] — clamped also in compute_risk_score
        # as defense-in-depth.
        multipliers[event_type] = round(1.0 - reduction, 4)

    src = f"{total_used} feedback verdicts" if total_used else "no feedback yet"

    return {
        "multipliers": multipliers,
        "samples": samples,
        "verdicts": total_used,
        "source": src,
    }


# ── Path A: read aggregated user baseline + coverage status ────────


@admin_router.get("/status")
async def sb01_status(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Operator-only health snapshot of the per-device baseline coverage.

    The active `baseline_scheduler` writes one row per (device, metric)
    into `device_baselines`. Coverage = how many devices have ≥1
    baseline row vs. the total `devices` count.
    """
    _require_operator_or_admin(user)

    row = (await session.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM devices) AS total_devices,
            (SELECT COUNT(DISTINCT device_id) FROM device_baselines) AS devices_with_baseline,
            (SELECT COUNT(*) FROM device_baselines) AS baseline_rows,
            (SELECT MAX(updated_at) FROM device_baselines) AS last_baseline_run,
            (SELECT COUNT(*) FROM safety_event_feedback) AS feedback_rows,
            (SELECT MAX(created_at) FROM safety_event_feedback) AS last_feedback_at
    """))).one()

    total = row.total_devices or 0
    covered = row.devices_with_baseline or 0
    coverage_pct = round(100.0 * covered / total, 2) if total else 0.0

    return {
        "total_devices": total,
        "devices_with_baseline": covered,
        "baseline_rows": row.baseline_rows or 0,
        "coverage_pct": coverage_pct,
        "last_baseline_run": row.last_baseline_run.isoformat() if row.last_baseline_run else None,
        "feedback_rows": row.feedback_rows or 0,
        "last_feedback_at": row.last_feedback_at.isoformat() if row.last_feedback_at else None,
    }


@admin_router.get("/user-baseline/{user_id}")
async def sb01_user_baseline(
    user_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Aggregate `device_baselines` rows across every device whose owning
    senior is guarded by `user_id`, plus any device whose senior_id IS
    `user_id` (covers the "user IS the senior" case in our data model).
    """
    _require_operator_or_admin(user)

    rows = (await session.execute(text("""
        WITH owned_devices AS (
            SELECT d.id AS device_id, d.device_identifier, d.device_type, d.status, d.last_seen
            FROM devices d
            JOIN seniors s ON s.id = d.senior_id
            WHERE s.guardian_id = :uid
            UNION
            SELECT d.id, d.device_identifier, d.device_type, d.status, d.last_seen
            FROM devices d
            WHERE d.senior_id = :uid
        )
        SELECT od.device_id, od.device_identifier, od.device_type, od.status, od.last_seen,
               db.metric, db.expected_value, db.lower_band, db.upper_band, db.updated_at
        FROM owned_devices od
        LEFT JOIN device_baselines db ON db.device_id = od.device_id
        ORDER BY od.device_id, db.metric
    """), {"uid": user_id})).all()

    if not rows:
        return {
            "user_id": user_id,
            "devices": [],
            "device_count": 0,
            "aggregated": {},
            "message": "No devices linked to this user via senior/guardian relationship.",
        }

    devices_map: dict[str, dict] = {}
    for r in rows:
        did = str(r.device_id)
        if did not in devices_map:
            devices_map[did] = {
                "device_id": did,
                "device_identifier": r.device_identifier,
                "device_type": r.device_type,
                "status": r.status,
                "last_seen": r.last_seen.isoformat() if r.last_seen else None,
                "metrics": {},
            }
        if r.metric:
            devices_map[did]["metrics"][r.metric] = {
                "expected": r.expected_value,
                "lower_band": r.lower_band,
                "upper_band": r.upper_band,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }

    metric_buckets: dict[str, list[float]] = {}
    for dev in devices_map.values():
        for m, vals in dev["metrics"].items():
            metric_buckets.setdefault(m, []).append(vals["expected"])
    aggregated = {
        m: {"expected_mean": round(sum(vs) / len(vs), 4), "device_samples": len(vs)}
        for m, vs in metric_buckets.items()
    }

    return {
        "user_id": user_id,
        "device_count": len(devices_map),
        "devices_with_baseline": sum(1 for d in devices_map.values() if d["metrics"]),
        "aggregated": aggregated,
        "devices": list(devices_map.values()),
    }


@admin_router.get("/attenuation-summary")
async def sb01_attenuation_summary(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    System-wide Hermes learning-loop telemetry. Operator/admin only.

    Aggregates `safety_event_feedback` across the whole platform:
      • users_with_active_attenuation — at least one primary_event
        with ≥ MIN_FEEDBACK_SAMPLES and a multiplier < 1.0
      • avg per-event attenuation drop (in % from 1.0)
      • total verdicts collected to date (confirmed + false_positive)
      • top 5 users by raw false-positive rate (≥ MIN samples)
    """
    _require_operator_or_admin(user)

    # Per-(user, primary_event) tally of confirmed + false_positive.
    rows = (await session.execute(text("""
        SELECT se.user_id, se.primary_event, sef.verdict, COUNT(*)::int AS n
        FROM safety_event_feedback sef
        JOIN safety_events se ON se.id = sef.safety_event_id
        WHERE sef.verdict IN ('confirmed', 'false_positive')
        GROUP BY se.user_id, se.primary_event, sef.verdict
    """))).all()

    # Pivot into per_user[event] = {confirmed: n, fp: n}.
    per_user: dict[str, dict[str, dict[str, int]]] = {}
    grand_total = 0
    for r in rows:
        uid = str(r.user_id)
        ev = (r.primary_event or "").strip()
        if not ev:
            continue
        slot = per_user.setdefault(uid, {}).setdefault(ev, {"confirmed": 0, "false_positive": 0})
        slot[r.verdict] = int(r.n)
        grand_total += int(r.n)

    # Walk each (user, event) and compute the same multiplier the brain
    # actually applies. This is the source of truth — re-using the live
    # formula tunables guarantees the summary stays in lockstep with
    # `compute_risk_score`.
    users_active = 0
    drop_buckets: dict[str, list[float]] = {}
    user_fp_rates: list[dict] = []

    for uid, events in per_user.items():
        user_active = False
        user_total = 0
        user_fp = 0
        for ev, counts in events.items():
            confirmed = counts.get("confirmed", 0)
            fp = counts.get("false_positive", 0)
            total = confirmed + fp
            user_total += total
            user_fp += fp
            if total < MIN_FEEDBACK_SAMPLES:
                continue
            fp_rate = fp / total
            confidence_factor = min(total / FULL_CONFIDENCE_AT, 1.0)
            reduction = min(fp_rate * confidence_factor, MAX_ATTENUATION)
            if reduction > 0:
                user_active = True
                drop_buckets.setdefault(ev, []).append(reduction)
        if user_active:
            users_active += 1

        if user_total >= MIN_FEEDBACK_SAMPLES:
            user_fp_rates.append({
                "user_id": uid,
                "fp_rate": round(user_fp / user_total, 4),
                "samples": user_total,
            })

    avg_drops = {
        ev: {
            "users_affected": len(drops),
            "avg_drop_pct": round(100.0 * (sum(drops) / len(drops)), 2),
        }
        for ev, drops in drop_buckets.items()
    }

    top_fp = sorted(user_fp_rates, key=lambda r: r["fp_rate"], reverse=True)[:5]

    return {
        "users_with_active_attenuation": users_active,
        "total_verdicts": grand_total,
        "per_event_drops": avg_drops,
        "top_fp_users": top_fp,
        "thresholds": {
            "min_feedback_samples": MIN_FEEDBACK_SAMPLES,
            "full_confidence_at": FULL_CONFIDENCE_AT,
            "max_attenuation": MAX_ATTENUATION,
        },
    }



# ── Path D: capture feedback verdicts on SafetyEvents ──────────────


class FeedbackIn(BaseModel):
    verdict: Literal["confirmed", "false_positive", "unsure"]
    notes: str | None = Field(default=None, max_length=2000)


async def _can_caller_grade_event(
    session: AsyncSession,
    caller: User,
    event_user_id: str,
) -> tuple[bool, str]:
    """
    Return (allowed, feedback_source).

    Allowed when:
      • caller IS the event's user           → source=user
      • caller has admin/operator role       → source=operator
      • caller is a registered guardian of   → source=guardian
        the event's user
    """
    caller_id = str(caller.id)

    if caller_id == event_user_id:
        return True, "user"

    if caller.role in ("admin", "operator"):
        return True, "operator"

    from app.services.geofence_alerts import _resolve_guardian_ids
    try:
        guardian_ids = await _resolve_guardian_ids(session, event_user_id)
    except Exception as e:
        logger.warning("[SB-01] guardian-resolve failed for event_user=%s err=%s",
                       event_user_id, e)
        guardian_ids = set()

    if caller_id in guardian_ids:
        return True, "guardian"

    return False, ""


@feedback_router.post("/{event_id}/feedback")
async def submit_safety_event_feedback(
    body: FeedbackIn,
    event_id: str = Path(..., description="SafetyEvent UUID"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Record a verdict on a SafetyEvent.

    Caller must be (a) the event's own user, (b) a registered guardian
    of that user, or (c) an admin/operator. One verdict per
    (event, source) — re-submitting overwrites silently via the unique
    index. This avoids accidental dup-clicks creating multiple rows.
    """
    row = (await session.execute(text("""
        SELECT user_id FROM safety_events WHERE id = :eid
    """), {"eid": event_id})).first()

    if not row:
        raise HTTPException(status_code=404, detail="SafetyEvent not found")

    event_user_id = str(row.user_id)

    allowed, source = await _can_caller_grade_event(session, user, event_user_id)
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="You can only grade SafetyEvents for yourself or your dependents.",
        )

    await session.execute(text("""
        INSERT INTO safety_event_feedback
            (safety_event_id, user_id, verdict, feedback_source, notes)
        VALUES
            (:eid, :uid, :verdict, :source, :notes)
        ON CONFLICT (safety_event_id, feedback_source)
        DO UPDATE SET
            verdict    = EXCLUDED.verdict,
            notes      = EXCLUDED.notes,
            user_id    = EXCLUDED.user_id,
            created_at = NOW()
    """), {
        "eid": event_id,
        "uid": str(user.id),
        "verdict": body.verdict,
        "source": source,
        "notes": body.notes,
    })
    await session.commit()

    logger.info(
        "[SB-01 feedback] event=%s caller=%s source=%s verdict=%s",
        event_id, user.id, source, body.verdict,
    )

    return {
        "event_id": event_id,
        "verdict": body.verdict,
        "feedback_source": source,
        "stored": True,
    }
