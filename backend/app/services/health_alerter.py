"""NISCH-008b — Proactive failure alerting (push, not pull).

Fires a one-line incident notification to operator channels (Slack +
log) when the safety pipeline starts misbehaving. Designed for "you'll
know within seconds, not when a user complains."

Triggers:
  1. `[TWILIO_AUTH_FAIL]` at boot (credentials rotated / invalid).
  2. `[TWILIO_GIVE_UP]`   — every dispatched alert that exhausted retries.
  3. SLA verdict transitions from green → amber/red (poll-based, 60s).

Channels (any combination, all optional via env vars):
  * `OPS_SLACK_WEBHOOK_URL`   — Slack incoming-webhook URL.
  * `OPS_DISCORD_WEBHOOK_URL` — Discord webhook URL (slack-compatible body).
  * (future) email via Resend if `OPS_ALERT_EMAIL` is set.

If no destination is configured, the alerter still logs an `[OPS_ALERT]`
line — which is what you grep with `tail -F` during incidents.

Strict invariants:
  * `notify_failure(...)` MUST never raise (it sits inside other
    failure-handling paths; can't itself blow up the alert pipeline).
  * Dedups identical incidents inside `IDEMPOTENCY_WINDOW_S` so a single
    auth outage doesn't spam channels with 60 messages.
  * Best-effort: a flaky Slack endpoint should NOT delay the caller.
    Sends are spawned via the same `twilio_safe`-style executor so the
    call returns in milliseconds.
"""
from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

import requests

from app.services.event_dedup import should_emit as _dedup_should_emit

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────
IDEMPOTENCY_WINDOW_S = 300       # 5 min — same incident silenced inside this window
SEND_TIMEOUT_S       = 3.0       # never spend > 3s posting to a webhook
_EXECUTOR            = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ops-alert")


# ── Public ──────────────────────────────────────────────────────────
def notify_failure(
    *,
    level: str,
    kind: str,
    message: str,
    details: Optional[dict[str, Any]] = None,
    dedup_key: Optional[str] = None,
) -> bool:
    """Fire-and-forget notification.

    Args:
        level:      "warn" | "critical".
        kind:       short slug ("twilio_auth", "twilio_give_up", "sla_red").
        message:    one-line human summary.
        details:    optional context dict (account, error, latency, ...).
        dedup_key:  override default dedup; pass `None` for "kind+message".

    Returns:
        True if a send was queued (or skipped due to dedup).
        False only on hard validation failure (level/kind missing).
    """
    if not level or not kind or not message:
        return False

    key = dedup_key or f"{kind}::{message[:120]}"
    if not _dedup_should_emit(
        f"ops_alert:{kind}", key, cooldown_s=IDEMPOTENCY_WINDOW_S
    ):
        logger.info(f"[OPS_ALERT_DEDUP] {kind}: {message[:80]}")
        return True

    payload = {
        "level":   level,
        "kind":    kind,
        "message": message,
        "details": {
            **(details or {}),
            "env":     (os.environ.get("ENV") or os.environ.get("ENVIRONMENT") or "preview").lower(),
            "service": (os.environ.get("NISCHINT_ROLE") or "api").lower(),
        },
        "ts":      int(time.time()),
    }

    # Always log — that's the channel that always works.
    logger.warning(
        f"[OPS_ALERT] level={level} kind={kind} {message} "
        f"details={json.dumps(details or {}, default=str)[:200]}"
    )

    # Best-effort fan-out to webhooks.
    slack = (os.environ.get("OPS_SLACK_WEBHOOK_URL") or "").strip()
    discord = (os.environ.get("OPS_DISCORD_WEBHOOK_URL") or "").strip()
    if slack:
        _EXECUTOR.submit(_post_slack, slack, payload)
    if discord:
        _EXECUTOR.submit(_post_discord, discord, payload)
    return True


# ── Channel-specific senders ────────────────────────────────────────
def _slack_block(payload: dict) -> dict:
    """Build a Slack-style payload. Compatible with Discord webhooks via
    a small translation in `_post_discord`."""
    emoji = {
        "critical": ":rotating_light:",
        "warn":     ":warning:",
    }.get(payload["level"], ":bell:")
    details = dict(payload.get("details") or {})  # local copy — safe to pop
    recent_ttfa = details.pop("recent_ttfa", None)

    # 1) Generic details block (small JSON dump).
    details_str = ""
    if details:
        try:
            details_str = "\n```\n" + json.dumps(details, indent=2, default=str)[:1000] + "\n```"
        except Exception:
            details_str = ""

    # 2) NISCH-008d — recent_ttfa table. One line per event so the
    #    on-call instantly sees *which* alerts went slow.
    ttfa_str = ""
    if recent_ttfa:
        try:
            lines = []
            for ev in recent_ttfa[-10:]:
                kind = str(ev.get("kind", "?"))[:24]
                ms   = int(ev.get("ttfa_ms", 0))
                pri  = str(ev.get("priority", "?"))
                marker = (
                    ":x:" if ev.get("status") == "fail"
                    else ":warning:" if ms >= 2000
                    else ":white_check_mark:"
                )
                lines.append(f"{marker}  `{kind:<24}` {ms:>6}ms  {pri}")
            ttfa_str = "\n*Last 10 TTFA events:*\n" + "\n".join(lines)
        except Exception:
            ttfa_str = ""

    return {
        "text": (
            f"{emoji} *NISCHINT OPS* `{payload['kind']}`\n"
            f"{payload['message']}{details_str}{ttfa_str}"
        ),
    }


def _post_slack(url: str, payload: dict) -> None:
    try:
        body = _slack_block(payload)
        r = requests.post(url, json=body, timeout=SEND_TIMEOUT_S)
        if not (200 <= r.status_code < 300):
            logger.warning(
                f"[OPS_ALERT_SLACK_FAIL] status={r.status_code} body={r.text[:120]}"
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[OPS_ALERT_SLACK_FAIL] {type(e).__name__}: {e}")


def _post_discord(url: str, payload: dict) -> None:
    """Discord webhooks accept Slack-like `content` plus their own
    `username`/`embeds`. We send the simplest possible compatible body."""
    try:
        body = {
            "username": "Nischint Ops",
            "content":  _slack_block(payload)["text"][:1900],
        }
        r = requests.post(url, json=body, timeout=SEND_TIMEOUT_S)
        if not (200 <= r.status_code < 300):
            logger.warning(
                f"[OPS_ALERT_DISCORD_FAIL] status={r.status_code} body={r.text[:120]}"
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[OPS_ALERT_DISCORD_FAIL] {type(e).__name__}: {e}")


__all__ = ["notify_failure", "IDEMPOTENCY_WINDOW_S"]
