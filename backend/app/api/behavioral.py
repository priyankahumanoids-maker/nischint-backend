"""NISCH-011 — Behavioral Digital Twin API.

Read-only endpoints. The detector writes through the alert
pipeline; the API surfaces the ledger and the operator chip
metrics. Same non-blocking discipline as `/api/risk/*`.

Endpoints:
  GET /api/behavioral/baseline/{entity_id}
  GET /api/behavioral/anomalies/{entity_id}
  GET /api/behavioral/metrics                # operator chip feed
  GET /api/behavioral/dlq                    # operator introspection
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.services.behavioral import (
    ANOMALY_PIPELINE_VERSION,
    BASELINE_VERSION,
)
from app.services.behavioral.dlq import ledger_depth, read_recent
from app.services.behavioral.badge import (
    BADGE_CACHE_TTL_S, _cache_read, _cache_write,
    build_badge_fallback, level_to_color, pick_priority_reason,
)
from app.services.behavioral.trust import (
    derive_trend, evaluate_trust, severity_delta,
)

router = APIRouter(prefix="/behavioral", tags=["behavioral-twin"])


@router.get("/baseline/{entity_id}")
async def get_baseline(
    entity_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Return the warm baseline for an entity. `status='cold_start'`
    when no row exists yet."""
    try:
        eid = uuid.UUID(entity_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid entity_id UUID")

    row = (await session.execute(text("""
        SELECT zone_affinity, route_entropy, dwell_duration,
               temporal_signature, mobility_signature,
               risk_exposure_averages, rolling_deviation_thresholds,
               baseline_version, sample_count,
               computed_at, updated_at
          FROM behavioral_baselines
         WHERE entity_id = :eid
         LIMIT 1
    """), {"eid": str(eid)})).first()

    if not row:
        return {
            "status":           "cold_start",
            "entity_id":        str(eid),
            "baseline_version": BASELINE_VERSION,
        }

    return {
        "status":          "ok",
        "entity_id":       str(eid),
        "zone_affinity":   row[0],
        "route_entropy":   row[1],
        "dwell_duration":  row[2],
        "temporal_signature":   row[3],
        "mobility_signature":   row[4],
        "risk_exposure_averages":      row[5],
        "rolling_deviation_thresholds": row[6],
        "baseline_version":            row[7],
        "sample_count":                int(row[8] or 0),
        "computed_at":  row[9].isoformat() if row[9] else None,
        "updated_at":   row[10].isoformat() if row[10] else None,
    }


@router.get("/anomalies/{entity_id}")
async def list_anomalies(
    entity_id: str,
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Newest-first anomaly ledger view. Bounded — defaults to 50,
    capped at 500 per request."""
    try:
        eid = uuid.UUID(entity_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid entity_id UUID")

    rows = (await session.execute(text("""
        SELECT id, anomaly_type, anomaly_score, deviation_class,
               contributing_features, linked_prediction_id,
               fused_zone_risk, confidence, explanation_snapshot,
               anomaly_pipeline_version, reconciliation_status,
               created_at
          FROM behavioral_anomalies
         WHERE entity_id = :eid
         ORDER BY created_at DESC
         LIMIT :limit
    """), {"eid": str(eid), "limit": int(limit)})).all()

    return {
        "entity_id":         str(eid),
        "anomaly_pipeline_version": ANOMALY_PIPELINE_VERSION,
        "count":             len(rows),
        "items": [{
            "id":               str(r[0]),
            "anomaly_type":     r[1],
            "anomaly_score":    float(r[2]),
            "deviation_class":  r[3],
            "contributing_features": r[4] or [],
            "linked_prediction_id":  str(r[5]) if r[5] else None,
            "fused_zone_risk":  float(r[6]) if r[6] is not None else None,
            "confidence":       float(r[7]),
            "explanation_snapshot": r[8],
            "anomaly_pipeline_version": r[9],
            "reconciliation_status":   r[10],
            "created_at":       r[11].isoformat() if r[11] else None,
        } for r in rows],
    }


@router.get("/metrics")
async def get_metrics(
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Operator-chip aggregate. Gated metrics (MAE + critical
    precision/recall) only surface when the ledger has at least
    7 days of reconciled data — per the locked product brief.
    Until then, those fields are explicitly null and the caller
    can render the chip in 'warming up' state."""
    # Reconciled count + status distribution.
    counts = (await session.execute(text("""
        SELECT
            reconciliation_status,
            COUNT(*)::int                 AS n,
            MAX(created_at)               AS latest
          FROM behavioral_anomalies
         GROUP BY reconciliation_status
    """))).all()
    status_breakdown = {r[0]: int(r[1] or 0) for r in counts}
    pending_count = status_breakdown.get("pending", 0)

    # Reconciliation lag — age of oldest pending row.
    lag_row = (await session.execute(text("""
        SELECT EXTRACT(EPOCH FROM (now() - MIN(created_at)))::float
          FROM behavioral_anomalies
         WHERE reconciliation_status = 'pending'
    """))).first()
    reconciliation_lag_s = float(lag_row[0] or 0.0) if lag_row else 0.0

    # 7-day gate for the predictive-accuracy chips. The NISCH-010
    # ledger drives this; the API just exposes the read-through.
    accuracy_window_days = 7
    cutoff = datetime.now(timezone.utc) - timedelta(days=accuracy_window_days)
    rp_stats = (await session.execute(text("""
        SELECT COUNT(*)::int  AS n,
               AVG(ABS(delta))::float   AS mae,
               COUNT(*) FILTER (
                 WHERE predicted_risk >= 0.75 AND actual_outcome >= 0.75
               )::int  AS critical_tp,
               COUNT(*) FILTER (
                 WHERE predicted_risk >= 0.75 AND actual_outcome <  0.75
               )::int  AS critical_fp,
               COUNT(*) FILTER (
                 WHERE predicted_risk <  0.75 AND actual_outcome >= 0.75
               )::int  AS critical_fn
          FROM risk_predictions
         WHERE actual_outcome IS NOT NULL
           AND predicted_at >= :cutoff
    """), {"cutoff": cutoff})).first()
    rp_n = int(rp_stats[0] or 0) if rp_stats else 0
    if rp_n >= 7 * 24:                # ≥ 7 days * 24 reconciled / day
        tp = int(rp_stats[2] or 0)
        fp = int(rp_stats[3] or 0)
        fn = int(rp_stats[4] or 0)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        false_escalation = fp / (tp + fp + fn) if (tp + fp + fn) > 0 else 0.0
        gated = {
            "mae":                float(rp_stats[1] or 0.0),
            "critical_precision": precision,
            "critical_recall":    recall,
            "false_escalation_rate": false_escalation,
        }
    else:
        gated = {
            "mae":                None,
            "critical_precision": None,
            "critical_recall":    None,
            "false_escalation_rate": None,
            "warmup": {
                "reconciled_predictions": rp_n,
                "required_for_chip":      7 * 24,
            },
        }

    return {
        "status":              "ok",
        "anomaly_pipeline_version": ANOMALY_PIPELINE_VERSION,
        "baseline_version":         BASELINE_VERSION,
        "anomaly_counts":           status_breakdown,
        "unresolved_prediction_count": pending_count,
        "reconciliation_lag_s":     reconciliation_lag_s,
        "ml_predictions_dlq_depth": ledger_depth(),
        "accuracy_gated_7d":        gated,
    }


@router.get("/dlq")
async def get_dlq_recent(
    limit: int = Query(50, ge=1, le=500),
) -> dict:
    """Operator introspection of the append-only DLQ ring buffer.
    Useful for post-mortem reconstruction when the Postgres
    anomaly ledger is unavailable."""
    return {
        "depth":   ledger_depth(),
        "items":   read_recent(limit=limit),
    }


# ── NISCH-011.1 Twin Trust Tile ─────────────────────────────────

# Redis key for the previous trust level — enables trend derivation
# across calls. TTL is generous (24 h) so a process restart doesn't
# erase the trend signal. NEVER queried for dispatch logic; only
# the trust endpoint touches it.
_TRUST_PREV_LEVEL_KEY = "nischint:behavioral:trust:prev_level"
_TRUST_PREV_LEVEL_TTL_S = 24 * 3600


def _read_prev_trust_level() -> str | None:
    """Best-effort previous-level read. Returns None on any Redis
    failure — the caller treats that as `stable` trend rather than
    flipping to LOW_TRUST. Fail-safe by design."""
    try:
        from app.services import redis_service
        r = redis_service._get_client()
        if r is None:
            return None
        v = r.get(_TRUST_PREV_LEVEL_KEY)
        if v is None:
            return None
        return v.decode("utf-8") if isinstance(v, bytes) else str(v)
    except Exception:  # noqa: BLE001
        # Compensating action: trend defaults to `stable`. Logged
        # below; registered in test_swallow_audit allowlist.
        return None


def _write_trust_level(level: str) -> None:
    """Best-effort current-level cache. Failure is a no-op — the
    trend signal degrades gracefully to `stable` on the next call."""
    try:
        from app.services import redis_service
        r = redis_service._get_client()
        if r is None:
            return
        r.set(_TRUST_PREV_LEVEL_KEY, level, ex=_TRUST_PREV_LEVEL_TTL_S)
    except Exception:  # noqa: BLE001
        # Compensating action: next call uses `stable`. Registered
        # in test_swallow_audit allowlist.
        return


@router.get("/trust")
async def get_trust(
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Operator Trust Calibration Layer (Twin Trust Tile).

    Synthesises existing observability signals into a single
    3-state verdict (HIGH_TRUST / MEDIUM_TRUST / LOW_TRUST) +
    locked reason-code taxonomy + trend direction. Pure
    observability — NEVER influences dispatch routing.

    Fail-safe contract:
      * Every query is wrapped in try/except. On any failure the
        affected signal is treated as `None` (unavailable) — the
        evaluator handles that by reporting MEDIUM_TRUST with
        `telemetry_unavailable`, NEVER LOW_TRUST.
      * Redis access for the previous-level cache is best-effort.
        Failure → trend `stable`.
    """
    # ── Average divergence (last 60 min) ────────────────────────
    div_idx: float | None = None
    try:
        row = (await session.execute(text("""
            SELECT AVG(
                     ((explanation_snapshot
                       -> 'divergence'
                       ->> 'index')::float)
                   )::float AS avg_div
              FROM behavioral_anomalies
             WHERE created_at >= now() - interval '60 minutes'
               AND explanation_snapshot ? 'divergence'
        """))).first()
        if row and row[0] is not None:
            div_idx = float(row[0])
    except Exception:  # noqa: BLE001
        # Compensating action: div_idx stays None → MEDIUM, not LOW.
        # Registered in test_swallow_audit allowlist.
        div_idx = None

    # ── Reconciliation lag + unresolved count ───────────────────
    reconciliation_lag_s: float | None = None
    unresolved_count: int | None = None
    try:
        lag_row = (await session.execute(text("""
            SELECT
              COUNT(*) FILTER (WHERE reconciliation_status = 'pending')::int
                AS pending_n,
              EXTRACT(EPOCH FROM (now() - MIN(created_at)
                FILTER (WHERE reconciliation_status = 'pending')))::float
                AS lag_s
              FROM behavioral_anomalies
        """))).first()
        if lag_row:
            unresolved_count = int(lag_row[0] or 0)
            reconciliation_lag_s = float(lag_row[1] or 0.0)
    except Exception:  # noqa: BLE001
        # Compensating action: leave None → MEDIUM via fail-safe.
        # Registered in test_swallow_audit allowlist.
        pass

    # ── Reconciled count + precision + false escalation ─────────
    reconciled_n: int | None = None
    critical_precision: float | None = None
    false_escalation_rate: float | None = None
    try:
        rp = (await session.execute(text("""
            SELECT COUNT(*)::int  AS n,
                   COUNT(*) FILTER (
                     WHERE predicted_risk >= 0.75
                       AND actual_outcome >= 0.75
                   )::int  AS tp,
                   COUNT(*) FILTER (
                     WHERE predicted_risk >= 0.75
                       AND actual_outcome <  0.75
                   )::int  AS fp,
                   COUNT(*) FILTER (
                     WHERE predicted_risk <  0.75
                       AND actual_outcome >= 0.75
                   )::int  AS fn
              FROM risk_predictions
             WHERE actual_outcome IS NOT NULL
               AND predicted_at >= now() - interval '7 days'
        """))).first()
        if rp:
            reconciled_n = int(rp[0] or 0)
            tp = int(rp[1] or 0)
            fp = int(rp[2] or 0)
            fn = int(rp[3] or 0)
            if (tp + fp) > 0:
                critical_precision = tp / (tp + fp)
            if (tp + fp + fn) > 0:
                false_escalation_rate = fp / (tp + fp + fn)
    except Exception:  # noqa: BLE001
        # Compensating action: leave Nones → warmup-gate handles it.
        # Registered in test_swallow_audit allowlist.
        pass

    # ── DLQ depth (Redis) ───────────────────────────────────────
    # Already swallows Redis failures internally — returns 0 on
    # unavailability. We pass that through unchanged.
    dlq = ledger_depth()

    # ── Motion telemetry freshness (NISCH-012) ──────────────────
    # Latest motion-feature window upload across all entities.
    # Stale stream → MEDIUM `motion_telemetry_stale` (never LOW).
    motion_freshness_s: float | None = None
    try:
        mf_row = (await session.execute(text("""
            SELECT EXTRACT(EPOCH FROM (now() - MAX(window_started_at)))::float
              FROM motion_features
        """))).first()
        if mf_row and mf_row[0] is not None:
            motion_freshness_s = float(mf_row[0])
    except Exception:  # noqa: BLE001
        # Compensating action: motion_freshness_s stays None →
        # evaluator treats as unavailable, never LOW.
        pass

    result = evaluate_trust(
        divergence_index=div_idx,
        reconciliation_lag_s=reconciliation_lag_s,
        reconciled_predictions=reconciled_n,
        critical_precision=critical_precision,
        false_escalation_rate=false_escalation_rate,
        dlq_depth=dlq,
        unresolved_count=unresolved_count,
        motion_signal_freshness_s=motion_freshness_s,
    )

    # Trend = compare against last recorded level. Both reads and
    # writes are best-effort.
    prev_level = _read_prev_trust_level()
    trend = derive_trend(
        current_level=result.level, previous_level=prev_level,
    )
    _write_trust_level(result.level)

    # Structured log for the operations dashboard / SIEM pipeline.
    # Single log line per call — cheap and deterministic.
    import logging
    _log = logging.getLogger("app.api.behavioral")
    _log.info(
        "twin_trust_evaluated",
        extra={
            "event":         "twin_trust_evaluated",
            "trust_level":   result.level,
            "trend":         trend,
            "reason_codes":  result.reason_codes,
            "warmup_satisfied": result.warmup_satisfied,
            "divergence_index": div_idx,
            "reconciliation_lag_s": reconciliation_lag_s,
            "dlq_depth":     dlq,
            "motion_signal_freshness_s": motion_freshness_s,
        },
    )

    return {
        "trust_level":         result.level,
        "reason_codes":        result.reason_codes,
        "trend":               trend,
        "warmup_satisfied":    result.warmup_satisfied,
        "inputs":              result.inputs,
        "anomaly_pipeline_version": ANOMALY_PIPELINE_VERSION,
        "baseline_version":         BASELINE_VERSION,
    }



# ── NISCH-011.2 Badge surface ───────────────────────────────────


async def _maybe_emit_trust_level_changed(
    *, current_level: str, current_reason: str, current_trend: str,
    previous_level: str | None,
) -> None:
    """Optional real-time propagation. Emit `trust_level_changed`
    on the operator broadcast channel ONLY when the level
    actually changed across calls.

    Fire-and-forget: WebSocket emission is best-effort. Per the
    spec, WebSocket failures must have ZERO operational impact —
    the polling endpoint remains the source of truth."""
    if previous_level is None or previous_level == current_level:
        return
    try:
        from app.services.event_broadcaster import broadcaster
        delta = severity_delta(
            current_level=current_level, previous_level=previous_level,
        )
        await broadcaster.broadcast_to_operators(
            "trust_level_changed",
            {
                "level":          current_level,
                "reason":         current_reason,
                "trend":          current_trend,
                "severity_delta": delta,
            },
        )
        import logging
        logging.getLogger("app.api.behavioral").info(
            "trust_level_changed",
            extra={
                "event":          "trust_level_changed",
                "from":           previous_level,
                "to":             current_level,
                "reason":         current_reason,
                "trend":          current_trend,
                "severity_delta": delta,
            },
        )
    except Exception as e:  # noqa: BLE001
        # WebSocket emission failure is non-fatal — the polling
        # endpoint still serves authoritative state on the next call.
        import logging
        logging.getLogger("app.api.behavioral").warning(
            "trust_level_changed_emit_failed",
            extra={"event": "trust_level_changed_emit_failed",
                   "error_type": type(e).__name__},
        )


@router.get("/trust/badge")
async def get_trust_badge(
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Three-field trust badge for cheap polling. Locked shape:

        {"level": "...", "color": "...", "reason": "..."}

    LOCKED CONTRACTS (per the locked product brief):
      * Fail-safe on ANY exception → MEDIUM_TRUST / yellow /
        telemetry_unavailable. NEVER LOW_TRUST.
      * No raw metrics ever leaked — only the three fields above.
      * Redis cache TTL 10 s (5–15 s band per spec). Stale-while-
        revalidate is acceptable.
      * WebSocket `trust_level_changed` is enhancement only —
        failure is silent.
      * Endpoint is dispatch-isolated.
    """
    # Fast path — cache hit (stale-while-revalidate).
    cached = _cache_read()
    if cached is not None:
        try:
            import logging
            logging.getLogger("app.api.behavioral").info(
                "trust_badge_served",
                extra={"event": "trust_badge_served",
                       "source": "cache",
                       "level":  cached.get("level"),
                       "reason": cached.get("reason")},
            )
        except Exception:
            # Logging must NEVER fail the request.
            pass
        return cached

    # Slow path — live recompute. Single top-level try/except so
    # ANY uncaught failure returns the locked fallback shape.
    try:
        # Reuse the full trust queries — single source of truth
        # for the underlying numbers.
        div_idx: float | None = None
        try:
            row = (await session.execute(text("""
                SELECT AVG(
                         ((explanation_snapshot
                           -> 'divergence'
                           ->> 'index')::float)
                       )::float AS avg_div
                  FROM behavioral_anomalies
                 WHERE created_at >= now() - interval '60 minutes'
                   AND explanation_snapshot ? 'divergence'
            """))).first()
            if row and row[0] is not None:
                div_idx = float(row[0])
        except Exception:  # noqa: BLE001
            div_idx = None

        reconciliation_lag_s: float | None = None
        unresolved_count: int | None = None
        try:
            lag_row = (await session.execute(text("""
                SELECT
                  COUNT(*) FILTER (WHERE reconciliation_status = 'pending')::int
                    AS pending_n,
                  EXTRACT(EPOCH FROM (now() - MIN(created_at)
                    FILTER (WHERE reconciliation_status = 'pending')))::float
                    AS lag_s
                  FROM behavioral_anomalies
            """))).first()
            if lag_row:
                unresolved_count = int(lag_row[0] or 0)
                reconciliation_lag_s = float(lag_row[1] or 0.0)
        except Exception:  # noqa: BLE001
            pass

        reconciled_n: int | None = None
        critical_precision: float | None = None
        false_escalation_rate: float | None = None
        try:
            rp = (await session.execute(text("""
                SELECT COUNT(*)::int  AS n,
                       COUNT(*) FILTER (
                         WHERE predicted_risk >= 0.75
                           AND actual_outcome >= 0.75
                       )::int  AS tp,
                       COUNT(*) FILTER (
                         WHERE predicted_risk >= 0.75
                           AND actual_outcome <  0.75
                       )::int  AS fp,
                       COUNT(*) FILTER (
                         WHERE predicted_risk <  0.75
                           AND actual_outcome >= 0.75
                       )::int  AS fn
                  FROM risk_predictions
                 WHERE actual_outcome IS NOT NULL
                   AND predicted_at >= now() - interval '7 days'
            """))).first()
            if rp:
                reconciled_n = int(rp[0] or 0)
                tp = int(rp[1] or 0)
                fp = int(rp[2] or 0)
                fn = int(rp[3] or 0)
                if (tp + fp) > 0:
                    critical_precision = tp / (tp + fp)
                if (tp + fp + fn) > 0:
                    false_escalation_rate = fp / (tp + fp + fn)
        except Exception:  # noqa: BLE001
            pass

        dlq = ledger_depth()

        # Motion-freshness signal — same query as `/trust` but
        # tolerated as None on any failure (fail-safe MEDIUM).
        motion_freshness_s: float | None = None
        try:
            mf_row = (await session.execute(text("""
                SELECT EXTRACT(EPOCH FROM (now() - MAX(window_started_at)))::float
                  FROM motion_features
            """))).first()
            if mf_row and mf_row[0] is not None:
                motion_freshness_s = float(mf_row[0])
        except Exception:  # noqa: BLE001
            pass

        result = evaluate_trust(
            divergence_index=div_idx,
            reconciliation_lag_s=reconciliation_lag_s,
            reconciled_predictions=reconciled_n,
            critical_precision=critical_precision,
            false_escalation_rate=false_escalation_rate,
            dlq_depth=dlq,
            unresolved_count=unresolved_count,
            motion_signal_freshness_s=motion_freshness_s,
        )

        prev_level = _read_prev_trust_level()
        trend = derive_trend(
            current_level=result.level, previous_level=prev_level,
        )
        _write_trust_level(result.level)

        reason = pick_priority_reason(result.reason_codes)
        badge = {
            "level":  result.level,
            "color":  level_to_color(result.level),
            "reason": reason,
        }

        # Cache for 5–15 s per spec.
        _cache_write(badge)

        # Optional real-time push on level transitions.
        await _maybe_emit_trust_level_changed(
            current_level=result.level,
            current_reason=reason,
            current_trend=trend,
            previous_level=prev_level,
        )

        try:
            import logging
            logging.getLogger("app.api.behavioral").info(
                "trust_badge_served",
                extra={"event":            "trust_badge_served",
                       "source":           "live",
                       "level":            badge["level"],
                       "reason":           badge["reason"],
                       "trend":            trend,
                       "warmup_satisfied": result.warmup_satisfied},
            )
        except Exception:
            pass

        return badge
    except Exception as e:  # noqa: BLE001
        # FAIL-SAFE: any uncaught path returns the locked fallback.
        # NEVER LOW_TRUST.
        try:
            import logging
            logging.getLogger("app.api.behavioral").warning(
                "trust_badge_fallback",
                extra={"event": "trust_badge_fallback",
                       "error_type": type(e).__name__},
            )
        except Exception:
            pass
        return build_badge_fallback()
