"""NISCH-010 — RiskPredictionPrewarmer.

Subclass of `ProviderPrewarmer` per the locked design constraint
(`/app/memory/ROADMAP.md`). Inheriting from the prewarmer base
class gives the predictive layer:

  * Asymmetric hysteresis (healthy / stale / degraded / unknown)
  * Latency exporter (p50 / p95 / p99 + `budget_warning` amber)
  * Operator chip surface via `/admin/monitoring/prewarmers`
  * Same scheduler-lifecycle plumbing as Sachet / TomTom / News

What it warms (Phase 1):
  Probes the `safety_incidents` table once per cycle and caches
  the last-24 h incident count. This serves two purposes:
    1. Keeps the asyncpg pool warm so the first prediction
       request never hits a cold connection.
    2. Surfaces DB connectivity as a health signal on the
       prewarmer rollup chip — if Postgres goes degraded, the
       predictive layer goes amber/red automatically.

Phase 2 (when `active_zones` table exists):
  Pre-compute per-zone feature contexts (30-day history,
  guardian density, weather modifier) and cache under
  `prediction:zone:{zone_id}`. The predictor will read from
  Redis instead of issuing per-request Postgres queries.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.services.external_signals.base_prewarmer import ProviderPrewarmer
from app.services.risk_prediction import MODEL_VERSION

logger = logging.getLogger(__name__)


class RiskPredictionPrewarmer(ProviderPrewarmer):
    name = "risk_prediction"
    cache_namespace = "risk_prediction"
    cache_key = "warm_context"
    cache_ttl_s = 3600                    # 1h — prompt-specified

    telemetry_namespace = "risk_prediction"
    history_source_name = "risk_prediction"

    # Locked jitter — distinct base from Sachet (240s), TomTom (60s),
    # News (180s) to avoid stampeding the DB at the same instant.
    jitter_base_s = 3600
    jitter_range_s = 60
    scheduler_job_id = "risk_prediction_prewarm"

    active_count_field = "active_incident_count"

    # Per-cycle DB-query budget. Phase 1 issues one query; 2.0 s is
    # generous. p95 > 1.6 s will trip `budget_warning` amber via the
    # base class's 80 % rule.
    fetch_timeout_s = 2.0

    # Wider freshness window than the HTTP prewarmers — 1h cache TTL
    # means we tolerate up to 2h before declaring stale.
    healthy_max_age_s = 7200
    stale_max_age_s = 10800

    async def fetch(self) -> list[dict] | None:
        """One warm cycle — single DB probe to keep the pool hot
        and surface DB connectivity as a prewarmer-chip signal."""
        from app.db.session import async_session
        try:
            async with async_session() as session:
                cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                row = (await session.execute(
                    text("""
                        SELECT COUNT(*)::int AS incident_count
                          FROM safety_incidents
                         WHERE created_at >= :cutoff
                    """), {"cutoff": cutoff},
                )).first()
                incident_count = int(row[0] or 0) if row else 0
        except Exception as e:  # noqa: BLE001 — base wraps anyway
            logger.warning(
                "risk_prediction_prewarm_db_failed",
                extra={"event": "risk_prediction_prewarm_db_failed",
                       "error_type": type(e).__name__},
            )
            return None

        return [{
            "incident_count_24h": incident_count,
            "model_version":      MODEL_VERSION,
            "queried_at":         datetime.now(timezone.utc).isoformat(),
        }]


# Module-level scheduler helpers — mirror the prewarmer convention
# `scheduler_runner.py` imports.
_INSTANCE: RiskPredictionPrewarmer | None = None


def _get_instance() -> RiskPredictionPrewarmer:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = RiskPredictionPrewarmer()
    return _INSTANCE


def start_risk_prediction_prewarmer() -> None:
    _get_instance().start()


def stop_risk_prediction_prewarmer() -> None:
    if _INSTANCE is not None:
        _INSTANCE.stop()


__all__ = [
    "RiskPredictionPrewarmer",
    "start_risk_prediction_prewarmer",
    "stop_risk_prediction_prewarmer",
]
