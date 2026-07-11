"""Sentry observability hooks for the OpenWeatherMap provider.

Covers BOTH the existing per-request `WeatherProvider` (via
`weather_service`) AND the new OneCall 3.0 severe-alert prewarmer.
Each call site passes a `channel` tag (`current` | `onecall_alerts`)
so an operator can tell which OWM endpoint is degrading at a glance.

Stable fingerprint `["weather-degraded"]` groups repeat outages into
one Sentry issue.

Tests monkeypatch `_sentry` here — same hook point as
`sachet_sentry._sentry`.
"""
from __future__ import annotations

from typing import Any, Optional

from app.services.external_signals import _provider_sentry_base as _base


_DEGRADED_FINGERPRINT = ["weather-degraded"]
_CONTEXT_KEY = "weather_fetch"
_HEALTH_CONTEXT_KEY = "weather_health"
_METRIC_NAME = "weather.fetch.failure"
_PROVIDER_TAG = "weather"

_TELEMETRY_KEYS = (
    "health_state",
    "active_alert_count",
    "consecutive_failures",
    "consecutive_successes",
    "last_success_ts",
    "last_failure_ts",
    "last_fetch_ts",
    "cache_age_seconds",
    "parse_failure_rate",
    "recovery_progress",
    "metros_covered",
)


def _sentry():
    """Lazy import — module-local so tests can monkeypatch."""
    try:
        import sentry_sdk
        return sentry_sdk
    except Exception:  # pragma: no cover
        return None


def report_fetch_failure(
    *,
    status_code: Optional[int],
    upstream_url: str,
    response_time_ms: Optional[float],
    is_proxy: bool = False,
    colo: Optional[str] = None,
    error: Optional[str] = None,
    channel: Optional[str] = None,
    metro: Optional[str] = None,
) -> None:
    """Capture a single failed OWM fetch.

    `channel` distinguishes `current` (existing per-request weather)
    from `onecall_alerts` (new severe-alert prewarmer). Required for
    operators to triage whether the paid OneCall 3.0 endpoint is
    activated yet — 401/403 on `onecall_alerts` is expected before
    the user activates it on the OWM dashboard.

    `metro` is set when the failure is bound to one of the 6 polled
    cities so a degraded BOM-only response doesn't read as a global
    outage.
    """
    extra: dict[str, str] = {}
    if channel:
        extra["channel"] = channel
    if metro:
        extra["metro"] = metro
    _base.emit_fetch_failure(
        sentry_factory=_sentry,
        provider_tag=_PROVIDER_TAG,
        context_key=_CONTEXT_KEY,
        metric_name=_METRIC_NAME,
        status_code=status_code,
        upstream_url=upstream_url,
        response_time_ms=response_time_ms,
        is_proxy=is_proxy,
        colo=colo,
        error=error,
        extra_tags=extra or None,
    )


def report_health_transition(
    prior_state: str,
    new_state: str,
    telemetry: dict[str, Any],
) -> None:
    """Capture OWM prewarmer health-state transitions. Same
    fingerprint-grouping as SACHET; only `* → degraded` and
    `degraded → healthy` emit."""
    _base.emit_health_transition(
        sentry_factory=_sentry,
        provider_tag=_PROVIDER_TAG,
        context_key=_HEALTH_CONTEXT_KEY,
        fingerprint=_DEGRADED_FINGERPRINT,
        telemetry_keys=_TELEMETRY_KEYS,
        prior_state=prior_state,
        new_state=new_state,
        telemetry=telemetry,
    )


__all__ = [
    "report_fetch_failure",
    "report_health_transition",
]
