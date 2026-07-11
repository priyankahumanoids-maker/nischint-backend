"""OCE-01 — Public-facing AI confidence read endpoint.

Single endpoint, single user_id, four underlying signals that are
already computed elsewhere in the platform. We fan them in, weight
them, and emit a single 0-1 number for the operator console and the
guardian app to consume.

Why a dedicated module?

The four inputs live in four different subsystems:
  • `digital_twins.confidence_score`           — twin builder
  • `user_signal_baselines.sample_count`       — baseline matview
  • `live_deviation_engine` / route_monitor    — behavioural divergence
  • `sb01_hermes.get_user_attenuation`         — feedback-driven dampening

Composing them in a single place keeps the formula auditable and the
explanation strings consistent. The endpoint is read-only, RBAC-gated
(guardian / operator / admin), and Redis-cached for 30 s per user_id so
the operator console can poll it freely without hammering the DB.

Cache invalidation strategy: time-based only. 30 s is the same window
used by `/api/operator/command-center` and is short enough for an
on-call review yet long enough to absorb a polling SPA.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, require_role
from app.services import redis_service


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai-confidence"])

# ── Constants ──────────────────────────────────────────────────────

_RBAC = require_role(["guardian", "operator", "admin"])

CACHE_NS = "ai_confidence"
CACHE_TTL_S = 30

# Weights for the overall confidence. Sum to 1.0. Twin and telemetry
# carry equal top-billing because they reflect *direct* AI quality;
# behavioural match is slightly lower because it's noisier
# (deviation events are episodic); attenuation is least because it's
# user-feedback driven, which is sparse for most users.
W_TWIN          = 0.30
W_TELEMETRY     = 0.30
W_BEHAVIOURAL   = 0.25
W_ATTENUATION   = 0.15

# Twin confidence buckets — used for the explanation copy.
TWIN_HIGH_TH    = 0.7
TWIN_MEDIUM_TH  = 0.4

# Baseline cells: 24 hours × max devices we consider per user.
BASELINE_HOURS_TARGET = 24


# ── Sub-signal fetchers ────────────────────────────────────────────


async def _fetch_twin_confidence(session: AsyncSession, user_id: str) -> tuple[float, dict]:
    """Best twin confidence across the user's devices + metadata for the
    explanation. Returns (score 0..1, {n_twins, n_devices, last_trained}).
    """
    # JOIN twin → device → senior → guardian-user. Pulls both the count
    # and the max confidence in a single round-trip.
    rows = (await session.execute(
        text("""
            SELECT dt.confidence_score, dt.training_data_points, dt.last_trained_at
              FROM device_digital_twins dt
              JOIN devices d ON d.id = dt.device_id
              JOIN seniors s ON s.id = d.senior_id
             WHERE s.guardian_id = :uid
        """),
        {"uid": user_id},
    )).fetchall()

    if not rows:
        return 0.0, {"n_twins": 0, "last_trained": None}

    scores = [float(r.confidence_score or 0.0) for r in rows]
    best = max(scores) if scores else 0.0
    latest_trained = max((r.last_trained_at for r in rows if r.last_trained_at), default=None)
    return best, {
        "n_twins": len(rows),
        "last_trained": latest_trained.isoformat() if latest_trained else None,
        "best_score": round(best, 3),
    }


async def _fetch_telemetry_quality(session: AsyncSession, user_id: str) -> tuple[float, dict]:
    """Signal completeness — how filled is the user's 24-hour baseline?

    Score = `filled_hour_buckets / 24` averaged across the user's
    devices. Each device contributes one 24-bucket profile; missing
    devices count as 0-filled.
    """
    rows = (await session.execute(
        text("""
            SELECT device_id, COUNT(*) FILTER (WHERE sample_count > 0)::int AS filled_hours
              FROM user_signal_baselines
             WHERE user_id = :uid
             GROUP BY device_id
        """),
        {"uid": user_id},
    )).fetchall()

    if not rows:
        return 0.0, {"n_devices_with_baseline": 0, "hours_filled_avg": 0}

    per_device = [min(int(r.filled_hours or 0), BASELINE_HOURS_TARGET) for r in rows]
    avg_filled = sum(per_device) / len(per_device) if per_device else 0.0
    score = round(avg_filled / BASELINE_HOURS_TARGET, 3)
    return score, {
        "n_devices_with_baseline": len(rows),
        "hours_filled_avg": round(avg_filled, 1),
    }


async def _fetch_behavioural_match(session: AsyncSession, user_id: str) -> tuple[float, dict]:
    """How well does the user's last 24 h of activity match their baseline?

    Best available proxy for "is the user *currently* off pattern":
      1. Most-recent `safety_events.risk_score` in the last 24 h. The
         risk score is the safety brain's per-event 0..1 estimate; a
         high score means the AI thinks something is off, which maps
         to a LOW behavioural match. We invert: match = 1 - risk_score.
      2. Fallback to digital_twin.data_quality string ("high"→0.9,
         "medium"→0.6, "low"→0.3).
      3. Default 0.5 when no data — neither confirms a match nor a
         deviation.

    The deviation engine itself (live_deviation_engine.py) doesn't
    persist a row, so we can't read directly from it; risk_score is
    the closest stored proxy with the same semantic.
    """
    # Most recent risk score in the last 24 hours
    row = (await session.execute(
        text("""
            SELECT risk_score
              FROM safety_events
             WHERE user_id = :uid
               AND created_at >= NOW() - INTERVAL '24 hours'
             ORDER BY created_at DESC
             LIMIT 1
        """),
        {"uid": user_id},
    )).fetchone()

    if row is not None and row.risk_score is not None:
        risk = max(0.0, min(1.0, float(row.risk_score)))
        return round(1.0 - risk, 3), {"source": "safety_events_24h", "risk_score": round(risk, 3)}

    # Fallback: digital_twin.data_quality string via twin → device → senior → guardian
    row2 = (await session.execute(
        text("""
            SELECT dt.profile_summary ->> 'data_quality' AS data_quality
              FROM device_digital_twins dt
              JOIN devices d ON d.id = dt.device_id
              JOIN seniors s ON s.id = d.senior_id
             WHERE s.guardian_id = :uid
             ORDER BY dt.last_trained_at DESC NULLS LAST
             LIMIT 1
        """),
        {"uid": user_id},
    )).fetchone()
    if row2 and row2.data_quality:
        score = {"high": 0.9, "medium": 0.6, "low": 0.3}.get(row2.data_quality.lower(), 0.5)
        return score, {"source": f"twin_data_quality:{row2.data_quality}"}

    return 0.5, {"source": "no_data"}


async def _fetch_attenuation_factor(session: AsyncSession, user_id: str) -> tuple[float, dict]:
    """Hermes per-user attenuation rolled into a single 0..1 score.

    `get_user_attenuation` returns per-event-type multipliers in [0.5,
    1.0] (1.0 = no attenuation, 0.5 = max). For the confidence card we
    want a single number that's high when the AI's signals are being
    trusted as-is, low when feedback has driven big dampenings.

    Score = mean(multipliers) when feedback exists, else 1.0 (treat "no
    feedback" as "AI is trusted by default" — same semantic as the
    safety brain).
    """
    try:
        from app.api.sb01_hermes import get_user_attenuation
        att = await get_user_attenuation(session, user_id)
    except Exception as e:
        logger.debug(f"hermes get_user_attenuation failed: {e}")
        return 1.0, {"source": "unavailable", "verdicts": 0}

    multipliers = att.get("multipliers") or {}
    verdicts = int(att.get("verdicts") or 0)
    if not multipliers:
        return 1.0, {"verdicts": 0, "source": att.get("source", "no feedback yet")}

    mean_mult = sum(multipliers.values()) / len(multipliers)
    return round(mean_mult, 3), {
        "verdicts": verdicts,
        "per_signal": {k: round(v, 3) for k, v in multipliers.items()},
        "source": att.get("source", "feedback"),
    }


# ── Composition ────────────────────────────────────────────────────


def _weighted_overall(twin: float, telemetry: float, behav: float, att: float) -> float:
    raw = (
        W_TWIN        * twin
        + W_TELEMETRY * telemetry
        + W_BEHAVIOURAL * behav
        + W_ATTENUATION * att
    )
    return round(max(0.0, min(1.0, raw)), 3)


def _build_explanation(
    twin: float, twin_meta: dict,
    telemetry: float, tel_meta: dict,
    behav: float, behav_meta: dict,
    att: float, att_meta: dict,
    overall: float,
) -> list[str]:
    """Return 3-5 plain English sentences. We pick the most informative
    statements: always overall + telemetry + twin (in some form), then
    add behavioural + attenuation when they carry meaningful info.
    """
    out: list[str] = []

    # 1. Twin
    n_twins = twin_meta.get("n_twins", 0)
    if n_twins == 0:
        out.append("Digital twin not built yet — no per-device model available.")
    else:
        bucket = "high" if twin >= TWIN_HIGH_TH else ("medium" if twin >= TWIN_MEDIUM_TH else "low")
        out.append(
            f"Digital twin {bucket} confidence ({twin:.2f}) across "
            f"{n_twins} device{'s' if n_twins != 1 else ''}."
        )

    # 2. Telemetry
    nbase = tel_meta.get("n_devices_with_baseline", 0)
    if nbase == 0:
        out.append("Signal coverage 0% — no behavioural baseline recorded yet.")
    else:
        pct = int(round(telemetry * 100))
        hrs = tel_meta.get("hours_filled_avg", 0)
        out.append(
            f"Signal coverage {pct}% — averaged {hrs}/24 hourly buckets across {nbase} "
            f"device{'s' if nbase != 1 else ''}."
        )

    # 3. Behavioural
    src = behav_meta.get("source", "no_data")
    if src.startswith("safety_events"):
        risk = behav_meta.get("risk_score")
        if behav >= 0.8:
            out.append(f"Behaviour closely matches baseline (recent risk score {risk}).")
        elif behav >= 0.5:
            out.append(f"Behaviour moderately off baseline (recent risk score {risk}).")
        else:
            out.append(f"Behaviour strongly off baseline (recent risk score {risk}) — review recent activity.")
    elif src.startswith("twin_data_quality"):
        out.append(f"Behavioural match inferred from twin training quality ({src.split(':',1)[1]}).")
    # If src == "no_data", we skip this line to keep the 3-5 cap.

    # 4. Attenuation
    verdicts = att_meta.get("verdicts", 0)
    if verdicts == 0:
        # Skip — no feedback line is just noise.
        pass
    else:
        if att >= 0.95:
            out.append(f"Feedback ({verdicts} verdicts) confirms model — no attenuation applied.")
        elif att >= 0.8:
            out.append(f"Feedback ({verdicts} verdicts) lightly dampens model (mean multiplier {att:.2f}).")
        else:
            out.append(f"Feedback ({verdicts} verdicts) strongly dampens model (mean multiplier {att:.2f}).")

    # 5. Always close with the overall headline
    if overall >= 0.8:
        head = "Overall confidence high — trust this user's AI signals."
    elif overall >= 0.6:
        head = "Overall confidence medium — corroborate with operator review."
    elif overall >= 0.4:
        head = "Overall confidence low — treat AI signals as advisory."
    else:
        head = "Overall confidence very low — manual review recommended."
    out.append(f"{head} (score {overall:.2f})")

    # Clamp 3..5 — never fewer than 3 (always have twin + telemetry + overall),
    # never more than 5.
    return out[:5]


async def _fetch_history(session: AsyncSession, user_id: str) -> tuple[list[dict], str]:
    """Pull the last 7 days of snapshots and compute a trend label.

    Trend is `improving` / `degrading` / `stable` based on a comparison
    of the recent half (most recent 3 days) against the older half
    (next 3 days back). We require ≥4 data points to call anything
    other than `stable` — sparser histories are too noisy to label.

    The 0.05 threshold corresponds to roughly 5 % change on the unit
    interval; smaller swings are within the normal day-to-day noise
    of the underlying inputs.
    """
    rows = (await session.execute(
        text("""
            SELECT snapshot_date, overall_confidence
              FROM ai_confidence_history
             WHERE user_id = :uid
               AND snapshot_date >= CURRENT_DATE - INTERVAL '6 days'
             ORDER BY snapshot_date ASC
        """),
        {"uid": user_id},
    )).fetchall()

    series = [
        {
            "date":  r.snapshot_date.isoformat() if r.snapshot_date else None,
            "score": round(float(r.overall_confidence), 3),
        }
        for r in rows
    ]

    if len(series) < 4:
        return series, "stable"

    scores = [pt["score"] for pt in series]
    recent_mean = sum(scores[-3:]) / 3
    older_mean = sum(scores[:-3]) / max(1, len(scores) - 3)
    delta = recent_mean - older_mean
    if delta >= 0.05:
        return series, "improving"
    if delta <= -0.05:
        return series, "degrading"
    return series, "stable"


async def _build_envelope(session: AsyncSession, user_id: str) -> dict[str, Any]:
    """Compose all sub-signals into the response envelope."""
    twin_score,     twin_meta     = await _fetch_twin_confidence(session, user_id)
    tel_score,      tel_meta      = await _fetch_telemetry_quality(session, user_id)
    behav_score,    behav_meta    = await _fetch_behavioural_match(session, user_id)
    att_score,      att_meta      = await _fetch_attenuation_factor(session, user_id)
    history, trend                = await _fetch_history(session, user_id)

    overall = _weighted_overall(twin_score, tel_score, behav_score, att_score)
    explanation = _build_explanation(
        twin_score, twin_meta,
        tel_score, tel_meta,
        behav_score, behav_meta,
        att_score, att_meta,
        overall,
    )

    return {
        "user_id":            user_id,
        "overall_confidence": overall,
        "twin_confidence":    round(twin_score, 3),
        "telemetry_quality":  round(tel_score, 3),
        "behavioral_match":   round(behav_score, 3),
        "attenuation_factor": round(att_score, 3),
        "weights": {
            "twin":         W_TWIN,
            "telemetry":    W_TELEMETRY,
            "behavioral":   W_BEHAVIOURAL,
            "attenuation":  W_ATTENUATION,
        },
        "meta": {
            "twin":         twin_meta,
            "telemetry":    tel_meta,
            "behavioral":   behav_meta,
            "attenuation":  att_meta,
        },
        "explanation": explanation,
        "history":     history,    # last 7 days, oldest→newest
        "trend":       trend,      # "improving" | "degrading" | "stable"
    }


# ── Endpoint ───────────────────────────────────────────────────────


@router.get("/confidence/{user_id}")
async def get_user_confidence(
    user_id: str = Path(..., min_length=8, description="UUID of the monitored user"),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(_RBAC),
) -> dict[str, Any]:
    """OCE-01 — operator-facing AI confidence read.

    Returns a 0..1 `overall_confidence` plus the four input scores and
    a short plain-English explanation array. Cached in Redis for
    `CACHE_TTL_S` seconds per `user_id` — the cache key is namespaced
    so a Redis flush of `ai_confidence` invalidates ALL users at once
    (useful for emergency cache busts after a model change).
    """
    # Lightweight UUID sanity — reject malformed paths before DB hit.
    if not user_id or len(user_id) > 64:
        raise HTTPException(status_code=400, detail="invalid user_id")

    # Fast path: Redis cache
    try:
        cached = redis_service.get_json(CACHE_NS, user_id)
        if cached is not None:
            cached["_cache_hit"] = True
            return cached
    except Exception:
        pass

    envelope = await _build_envelope(session, user_id)

    try:
        redis_service.set_json(CACHE_NS, user_id, envelope, ttl=CACHE_TTL_S)
    except Exception:
        pass

    envelope["_cache_hit"] = False
    return envelope
