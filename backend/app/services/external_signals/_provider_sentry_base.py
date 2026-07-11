"""Shared building blocks for per-provider Sentry observability.

Why this module exists:
  * `sachet_sentry.py` shipped first and locked the SHAPE of the
    Sentry call (push_scope → tags → context → fingerprint →
    capture_message + metrics.incr). We deliberately keep that
    contract identical for the TomTom / Weather / News mirrors so a
    single Sentry filter (`provider=*-degraded`) renders all four
    providers' outage timelines the same way.
  * Each per-provider module (`tomtom_sentry`, `weather_sentry`,
    `news_sentry`) keeps its OWN `_sentry()` callable + fingerprint
    constant. Tests therefore continue to monkeypatch the
    per-provider `_sentry` symbol the same way they do today for
    `sachet_sentry._sentry`. No cross-module coupling.

This file holds the bodies; the wrapping per-provider modules
inject (provider_name, fingerprint, context_key, metric_name).
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional, Sequence

logger = logging.getLogger(__name__)


def emit_fetch_failure(
    *,
    sentry_factory: Callable[[], Any],
    provider_tag: str,
    context_key: str,
    metric_name: str,
    status_code: Optional[int],
    upstream_url: str,
    response_time_ms: Optional[float],
    is_proxy: bool,
    colo: Optional[str] = None,
    error: Optional[str] = None,
    extra_tags: Optional[dict[str, str]] = None,
) -> None:
    """Capture a single failed upstream fetch for one provider.

    Severity is `warning` (matching SACHET) — provider failures are
    degraded states, not application errors. The operator dashboard
    already conveys it; Sentry exists for trend analysis.

    `extra_tags` lets a provider attach a small number of additional
    discriminators (e.g. TomTom's `zone`, News' `channel`). These are
    written as tags AND echoed into the context dict so they show on
    the issue overview without diluting the canonical tag set.
    """
    sdk = sentry_factory()
    if sdk is None:
        return

    # ── 1. Capture a contextual warning ──────────────────────────
    try:
        with sdk.push_scope() as scope:
            scope.set_tag("provider", provider_tag)
            scope.set_tag("via_proxy", "true" if is_proxy else "false")
            scope.set_tag(
                "status_code",
                str(status_code) if status_code is not None else "exception",
            )
            if colo:
                scope.set_tag("cf_colo", colo)
            for k, v in (extra_tags or {}).items():
                scope.set_tag(k, v)
            ctx = {
                "upstream_url":     upstream_url,
                "status_code":      status_code,
                "response_time_ms": (
                    round(response_time_ms, 2)
                    if response_time_ms is not None else None
                ),
                "is_proxy":         is_proxy,
                "colo":             colo,
                "error":            error,
            }
            for k, v in (extra_tags or {}).items():
                ctx[k] = v
            scope.set_context(context_key, ctx)
            msg = (
                f"{provider_tag.upper()} fetch failed "
                f"status={status_code} via_proxy={is_proxy}"
                if status_code is not None
                else f"{provider_tag.upper()} fetch exception "
                     f"via_proxy={is_proxy}"
            )
            sdk.capture_message(msg, level="warning")
    except Exception as e:  # pragma: no cover — best-effort
        logger.debug(f"[sentry] capture failure (ignored): {e}")

    # ── 2. Custom metric ─────────────────────────────────────────
    try:
        metrics = getattr(sdk, "metrics", None)
        if metrics is not None and hasattr(metrics, "incr"):
            tags = {
                "status_code": (
                    str(status_code) if status_code is not None else "exception"
                ),
                "via_proxy":   "true" if is_proxy else "false",
            }
            for k, v in (extra_tags or {}).items():
                tags[k] = v
            metrics.incr(metric_name, tags=tags)
    except Exception as e:  # pragma: no cover
        logger.debug(f"[sentry-metrics] incr failed (ignored): {e}")


def emit_health_transition(
    *,
    sentry_factory: Callable[[], Any],
    provider_tag: str,
    context_key: str,
    fingerprint: Sequence[str],
    telemetry_keys: Sequence[str],
    prior_state: str,
    new_state: str,
    telemetry: dict[str, Any],
) -> None:
    """Capture prewarmer health transitions.

    Only two transitions emit (mirrors `sachet_sentry`):
      * `* → degraded`  — outage opened (level=warning).
      * `degraded → healthy` — outage closed (level=info).

    Both share the same `fingerprint` so repeated outages group into
    one Sentry issue. Every other transition is silent.
    """
    sdk = sentry_factory()
    if sdk is None:
        return

    try:
        if new_state == "degraded" and prior_state != "degraded":
            with sdk.push_scope() as scope:
                scope.set_tag("provider", provider_tag)
                scope.set_tag("transition", f"{prior_state}->{new_state}")
                scope.fingerprint = list(fingerprint)
                scope.set_context(
                    context_key,
                    _project_telemetry(telemetry, telemetry_keys),
                )
                sdk.capture_message(
                    f"{provider_tag.upper()} prewarmer flipped to degraded",
                    level="warning",
                )
        elif new_state == "healthy" and prior_state == "degraded":
            with sdk.push_scope() as scope:
                scope.set_tag("provider", provider_tag)
                scope.set_tag("transition", f"{prior_state}->{new_state}")
                scope.fingerprint = list(fingerprint)
                scope.set_context(
                    context_key,
                    _project_telemetry(telemetry, telemetry_keys),
                )
                sdk.capture_message(
                    f"{provider_tag.upper()} prewarmer recovered to healthy",
                    level="info",
                )
    except Exception as e:  # pragma: no cover
        logger.debug(f"[sentry] transition capture failed (ignored): {e}")


def _project_telemetry(
    telemetry: dict[str, Any],
    keys: Sequence[str],
) -> dict[str, Any]:
    """Pick only the fields that matter for the issue's context tab.
    Excluding the rest keeps issue diffs readable in Sentry."""
    return {k: telemetry.get(k) for k in keys if k in telemetry}


__all__ = [
    "emit_fetch_failure",
    "emit_health_transition",
]
