"""Standalone scheduler entrypoint.

Bootstrapped by supervisor with NISCHINT_ROLE=scheduler. Runs every
APScheduler job currently registered in the monolith — the same code,
just in its own process, so the API event loop never competes with
the scheduler tick.

Run: NISCHINT_ROLE=scheduler python -m app.workers.scheduler_runner
"""

from __future__ import annotations
import asyncio
import logging
import os
import pathlib
import signal

# Force the role BEFORE importing anything that reads it, so any
# accidental imports of server.py or settings see the right role.
os.environ.setdefault("NISCHINT_ROLE", "scheduler")

# Load /app/backend/.env so child services pick up DATABASE_URL etc.
# Must happen before app.* imports.
from dotenv import load_dotenv  # noqa: E402
load_dotenv(
    dotenv_path=str(pathlib.Path(__file__).resolve().parents[2] / ".env"),
    override=False,
)

from app.core.role import runs_schedulers, get_role  # noqa: E402
from app.logging_config import setup_logging  # noqa: E402

setup_logging()
logger = logging.getLogger("nischint.scheduler")


def _start_all_schedulers() -> list[str]:
    """Fire every `start_*` we already register in server.py — same code path."""
    from app.services.escalation_scheduler import start_scheduler
    from app.services.notification_worker import start_notification_worker
    from app.services.baseline_scheduler import start_baseline_scheduler
    from app.services.behavior_ai import start_behavior_scheduler
    from app.services.digital_twin_builder import start_twin_builder_scheduler
    from app.services.predictive_engine import start_prediction_scheduler
    from app.services.risk_learning_scheduler import start_risk_learning_scheduler
    from app.services.dynamic_risk_scheduler import start_dynamic_risk_scheduler
    from app.services.forecast_prewarm_scheduler import start_forecast_prewarm_scheduler
    from app.services.external_signals.sachet_prewarmer import start_sachet_prewarm_scheduler
    from app.services.external_signals.tomtom_prewarmer import start_tomtom_prewarm_scheduler
    from app.services.external_signals.news_prewarmer import start_news_prewarm_scheduler
    from app.services.external_signals.owm_alerts_prewarmer import start_owm_alerts_prewarm_scheduler
    from app.services.user_signal_baselines_scheduler import start_user_signal_baselines_scheduler
    from app.services.dlq_reconciler import start_dlq_reconciler
    from app.services.health_monitor import start_health_monitor
    from app.api.pr_intelligence import start_pr_nightly_scheduler
    from app.services.geo_digest_service import start_geo_digest_scheduler
    from app.services.dpdp_digest_service import start_dpdp_digest_scheduler
    from app.services.db_pool_monitor import start_db_pool_monitor
    from app.services.cc_ws_sweeper import start_cc_ws_sweeper
    from app.api.entity_engine import start_geo_health_scheduler
    from app.services.fleet_weather_service import start_fleet_weather_scheduler
    from app.services.alert_ack_engine import start_alert_ack_engine
    from app.services.journey_watchdog import start_journey_watchdog
    from app.services.sla_monitor import start_sla_monitor
    from app.services.safety_incident_scheduler import start_safety_incident_scheduler
    from app.services.risk_prediction.prewarmer import start_risk_prediction_prewarmer
    from app.services.risk_prediction.reconciler_scheduler import start_risk_prediction_reconciler
    from app.services.behavioral.prewarmer import start_behavioral_baseline_prewarmer
    from app.services.ai_confidence_history_scheduler import start_ai_confidence_history_scheduler
    from app.services.synthetic_monitor import start_synthetic_monitor

    started: list[str] = []
    for name, fn in [
        ("escalation", start_scheduler),
        ("notifications", start_notification_worker),
        ("baseline", start_baseline_scheduler),
        ("behavior_ai", start_behavior_scheduler),
        ("twin_builder", start_twin_builder_scheduler),
        ("prediction", start_prediction_scheduler),
        ("risk_learning", start_risk_learning_scheduler),
        ("dynamic_risk", start_dynamic_risk_scheduler),
        ("forecast_prewarm", start_forecast_prewarm_scheduler),
        ("sachet_prewarm", start_sachet_prewarm_scheduler),
        ("tomtom_prewarm", start_tomtom_prewarm_scheduler),
        ("news_prewarm", start_news_prewarm_scheduler),
        ("owm_alerts_prewarm", start_owm_alerts_prewarm_scheduler),
        ("user_signal_baselines_refresh", start_user_signal_baselines_scheduler),
        ("dlq_reconciler", start_dlq_reconciler),
        ("health_monitor", start_health_monitor),
        ("pr_nightly", start_pr_nightly_scheduler),
        ("geo_digest", start_geo_digest_scheduler),
        ("dpdp_digest", start_dpdp_digest_scheduler),
        ("db_pool_monitor", start_db_pool_monitor),
        ("cc_ws_sweeper", start_cc_ws_sweeper),
        ("geo_health", start_geo_health_scheduler),
        ("fleet_weather", start_fleet_weather_scheduler),
        ("alert_ack", start_alert_ack_engine),
        ("journey_watchdog", start_journey_watchdog),
        ("sla_monitor", start_sla_monitor),
        ("safety_incident_lifecycle", start_safety_incident_scheduler),
        ("risk_prediction_prewarm", start_risk_prediction_prewarmer),
        ("risk_prediction_reconciler", start_risk_prediction_reconciler),
        ("behavioral_baseline_prewarm", start_behavioral_baseline_prewarmer),
        ("ai_confidence_history", start_ai_confidence_history_scheduler),
        ("synthetic_monitor", start_synthetic_monitor),
    ]:
        try:
            fn()
            started.append(name)
        except Exception as e:
            logger.warning(f"Scheduler '{name}' failed to start: {e}")
    return started


def _stop_all_schedulers() -> None:
    from app.services.escalation_scheduler import stop_scheduler
    from app.services.notification_worker import stop_notification_worker
    from app.services.baseline_scheduler import stop_baseline_scheduler
    from app.services.behavior_ai import stop_behavior_scheduler
    from app.services.risk_learning_scheduler import stop_risk_learning_scheduler
    from app.services.dynamic_risk_scheduler import stop_dynamic_risk_scheduler
    from app.services.health_monitor import stop_health_monitor
    from app.services.fleet_weather_service import shutdown_fleet_weather_scheduler
    from app.services.external_signals.sachet_prewarmer import stop_sachet_prewarm_scheduler
    from app.services.external_signals.tomtom_prewarmer import stop_tomtom_prewarm_scheduler
    from app.services.external_signals.news_prewarmer import stop_news_prewarm_scheduler
    from app.services.dlq_reconciler import stop_dlq_reconciler
    from app.services.risk_prediction.prewarmer import stop_risk_prediction_prewarmer
    from app.services.risk_prediction.reconciler_scheduler import stop_risk_prediction_reconciler
    from app.services.behavioral.prewarmer import stop_behavioral_baseline_prewarmer
    from app.services.db_pool_monitor import stop_db_pool_monitor
    from app.services.cc_ws_sweeper import stop_cc_ws_sweeper

    for name, fn in [
        ("escalation", stop_scheduler),
        ("notifications", stop_notification_worker),
        ("baseline", stop_baseline_scheduler),
        ("behavior_ai", stop_behavior_scheduler),
        ("risk_learning", stop_risk_learning_scheduler),
        ("dynamic_risk", stop_dynamic_risk_scheduler),
        ("health_monitor", stop_health_monitor),
        ("fleet_weather", shutdown_fleet_weather_scheduler),
        ("sachet_prewarm", stop_sachet_prewarm_scheduler),
        ("tomtom_prewarm", stop_tomtom_prewarm_scheduler),
        ("news_prewarm", stop_news_prewarm_scheduler),
        ("dlq_reconciler", stop_dlq_reconciler),
        ("risk_prediction_prewarm", stop_risk_prediction_prewarmer),
        ("risk_prediction_reconciler", stop_risk_prediction_reconciler),
        ("behavioral_baseline_prewarm", stop_behavioral_baseline_prewarmer),
        ("db_pool_monitor", stop_db_pool_monitor),
        ("cc_ws_sweeper", stop_cc_ws_sweeper),
    ]:
        try:
            fn()
        except Exception as e:
            logger.warning(f"Scheduler '{name}' failed to stop cleanly: {e}")


async def _main() -> None:
    if not runs_schedulers():
        logger.error(
            f"Scheduler runner refusing to start: NISCHINT_ROLE={get_role().value} "
            f"is not 'scheduler' or 'all'."
        )
        return

    started = _start_all_schedulers()
    logger.info(
        f"Scheduler runner online. role={get_role().value} "
        f"started={len(started)}: {','.join(started)}"
    )

    # Hook scheduler-health metrics. Listeners survive across job runs
    # and write to Redis so the API process can read the same truth.
    try:
        from app.services.scheduler_metrics import attach_to_all_running
        attach_to_all_running()
    except Exception as e:
        logger.warning(f"scheduler_metrics attach failed: {e}")

    # Park forever — supervisor controls the lifecycle.
    stop = asyncio.Event()

    def _handler(*_):
        logger.info("Scheduler runner received shutdown signal")
        stop.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handler)
        except NotImplementedError:  # pragma: no cover — Windows
            pass

    try:
        await stop.wait()
    finally:
        _stop_all_schedulers()
        logger.info("Scheduler runner stopped")


def run() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    run()
