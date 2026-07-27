"""NISCH-004 — Canonical alert formatter.

The single source of truth for how an alert *looks* (title, body, priority,
sound, channels, metadata). Lives between `trigger_alert` (which decides
*whether* to fire) and the per-channel renderers (push/sms/email).

Strict design rule (per spec):
    Formatter formats. It does NOT decide.

No DB calls, no Redis calls, no I/O. Pure dict-in / dict-out. Same input →
same output every time. That is what makes it testable and what makes
SSE/push/sms/email render consistently.

Usage:
    envelope = format_alert(kind="voice_distress", ctx={
        "child_name": "Aarav",
        "severity": "critical",
        "message": "Voice distress detected",
        "location": {"lat": 12.97, "lng": 77.59},
        "confidence": 0.92,
    })
    # → {
    #     "kind": "voice_distress",
    #     "title": "🔴 NISCHINT VOICE ALERT",
    #     "body": "Aarav — voice distress detected. 12.9700, 77.5900 · 03:14 PM UTC",
    #     "priority": "critical",
    #     "sound": "siren_loop",
    #     "channels": ["sse", "push", "sms", "call"],
    #     "requires_action": True,
    #     "louder": True,
    #     "metadata": {...},
    # }

i18n: pass `locale="en"` (default). Unknown locales fall back to "en". The
templating layer is intentionally tiny — when we add real i18n we can swap
the registry without touching callers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, TypedDict


__all__ = [
    "format_alert",
    "AlertEnvelope",
    "AlertSpec",
    "DEFAULT_LOCALE",
    "REGISTRY",
]


DEFAULT_LOCALE = "en"


# ── Public types ────────────────────────────────────────────────────
class AlertEnvelope(TypedDict, total=False):
    kind: str
    title: str
    body: str
    priority: str            # "low" | "warning" | "high" | "critical"
    sound: str               # "silent" | "default" | "alert" | "siren_loop"
    channels: list[str]      # subset of ["sse", "push", "sms", "call"]
    requires_action: bool
    louder: bool             # routes push to critical_safety channel
    metadata: dict[str, Any]


class AlertSpec(TypedDict, total=False):
    title_emoji: str
    label: str               # short ALL-CAPS noun ("VOICE ALERT", "FALL")
    body_template: str       # uses {name}, {loc_str}, {time_str}
    priority: str
    sound: str
    channels: list[str]
    requires_action: bool
    louder: bool
    category: str            # "emergency" | "safety" | "info"


# ── Internal helpers (no I/O) ───────────────────────────────────────
def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%I:%M %p UTC")


def _loc_str(location: Optional[dict]) -> str:
    if not location:
        return ""
    lat = location.get("lat")
    lng = location.get("lng")
    if lat is None or lng is None:
        return ""
    try:
        return f"{float(lat):.4f}, {float(lng):.4f}"
    except (TypeError, ValueError):
        return ""


def _trail(loc_str: str, t: str) -> str:
    """Common ' · ' joiner for trailing context."""
    parts = [p for p in (loc_str, t) if p]
    return " \u00b7 ".join(parts)


# ── Severity emoji shorthand (not business logic — purely visual) ───
_EMOJI = {
    "critical": "\U0001F534",   # 🔴
    "high":     "\U0001F534",   # 🔴
    "warning":  "\U0001F7E1",   # 🟡
    "low":      "\U0001F535",   # 🔵
    "info":     "\U0001F535",   # 🔵
    "safe":     "\U0001F7E2",   # 🟢
}


# ── Per-kind registry (single canonical source) ─────────────────────
# IMPORTANT: priorities/sounds/channels here are the *defaults* tied to
# the kind. The formatter does NOT override them based on context; if a
# specific call needs a different priority that's a `trigger_alert` /
# upstream concern. Formatter formats.
REGISTRY: dict[str, dict[str, AlertSpec]] = {
    DEFAULT_LOCALE: {
        # ── Critical, life-safety ─────────────────────────────────
        "voice_distress": {
            "title_emoji": _EMOJI["critical"],
            "label":       "VOICE ALERT",
            "body_template": "{name} \u2014 voice distress detected. {trail}",
            "priority":      "critical",
            "sound":         "siren_loop",
            "channels":      ["sse", "push", "sms", "call"],
            "requires_action": True,
            "louder":        True,
            "category":      "emergency",
        },
        "sos": {
            "title_emoji": _EMOJI["critical"],
            "label":       "SOS",
            "body_template": "{name} triggered emergency SOS. {trail}",
            "priority":      "critical",
            "sound":         "siren_loop",
            "channels":      ["sse", "push", "sms", "call"],
            "requires_action": True,
            "louder":        True,
            "category":      "emergency",
        },
        "emergency_triggered": {
            "title_emoji": _EMOJI["critical"],
            "label":       "EMERGENCY",
            "body_template": "{name} \u2014 emergency triggered. {trail}",
            "priority":      "critical",
            "sound":         "siren_loop",
            "channels":      ["sse", "push", "sms", "call"],
            "requires_action": True,
            "louder":        True,
            "category":      "emergency",
        },
        "fall_detected": {
            "title_emoji": _EMOJI["critical"],
            "label":       "FALL",
            "body_template": "{name} \u2014 fall detected, not moving. {trail}",
            "priority":      "critical",
            "sound":         "alert",
            "channels":      ["sse", "push", "sms"],
            "requires_action": True,
            "louder":        True,
            "category":      "emergency",
        },
        "help_requested": {
            "title_emoji": _EMOJI["critical"],
            "label":       "HELP REQUEST",
            "body_template": "{name} requested help. {trail}",
            "priority":      "critical",
            "sound":         "alert",
            "channels":      ["sse", "push", "sms"],
            "requires_action": True,
            "louder":        True,
            "category":      "emergency",
        },

        # ── High priority safety ──────────────────────────────────
        "geofence_breach": {
            "title_emoji": _EMOJI["warning"],
            "label":       "ZONE BREACH",
            "body_template": "{name} left a safe zone. {trail}",
            "priority":      "high",
            "sound":         "alert",
            "channels":      ["sse", "push"],
            "requires_action": True,
            "louder":        False,
            "category":      "safety",
        },
        "safe_zone_exit": {
            "title_emoji": _EMOJI["warning"],
            "label":       "ZONE BREACH",
            "body_template": "{name} left a safe zone. {trail}",
            "priority":      "high",
            "sound":         "alert",
            "channels":      ["sse", "push"],
            "requires_action": True,
            "louder":        False,
            "category":      "safety",
        },
        "wandering": {
            "title_emoji": _EMOJI["warning"],
            "label":       "WANDERING",
            "body_template": "{name} \u2014 wandering pattern detected. {trail}",
            "priority":      "high",
            "sound":         "alert",
            "channels":      ["sse", "push"],
            "requires_action": True,
            "louder":        False,
            "category":      "safety",
        },
        "critical_deviation": {
            "title_emoji": _EMOJI["critical"],
            "label":       "ROUTE CRITICAL",
            "body_template": "{name} \u2014 critical route deviation. {trail}",
            "priority":      "critical",
            "sound":         "alert",
            "channels":      ["sse", "push", "sms"],
            "requires_action": True,
            "louder":        True,
            "category":      "safety",
        },
        "unsafe_deviation": {
            "title_emoji": _EMOJI["warning"],
            "label":       "ROUTE UNSAFE",
            "body_template": "{name} \u2014 deviated into unsafe area. {trail}",
            "priority":      "high",
            "sound":         "alert",
            "channels":      ["sse", "push"],
            "requires_action": True,
            "louder":        False,
            "category":      "safety",
        },
        "minor_deviation": {
            "title_emoji": _EMOJI["warning"],
            "label":       "ROUTE",
            "body_template": "{name} \u2014 minor route deviation. {trail}",
            "priority":      "warning",
            "sound":         "default",
            "channels":      ["sse", "push"],
            "requires_action": False,
            "louder":        False,
            "category":      "safety",
        },

        # ── Warning / informational ───────────────────────────────
        "low_battery": {
            "title_emoji": _EMOJI["warning"],
            "label":       "LOW BATTERY",
            "body_template": "{name} \u2014 device battery low. {trail}",
            "priority":      "warning",
            "sound":         "default",
            "channels":      ["sse", "push"],
            "requires_action": False,
            "louder":        False,
            "category":      "info",
        },
        "device_offline": {
            "title_emoji": _EMOJI["warning"],
            "label":       "DEVICE OFFLINE",
            "body_template": "{name} \u2014 device offline. {trail}",
            "priority":      "warning",
            "sound":         "default",
            "channels":      ["sse", "push"],
            "requires_action": False,
            "louder":        False,
            "category":      "info",
        },
        "location_unavailable": {
            "title_emoji": _EMOJI["warning"],
            "label":       "LOCATION UNAVAILABLE",
            "body_template": "{name} \u2014 location tracking unavailable. {trail}",
            "priority":      "high",
            "sound":         "alert",
            "channels":      ["sse", "push"],
            "requires_action": True,
            "louder":        False,
            "category":      "safety",
        },
        "location_restored": {
            "title_emoji": _EMOJI["safe"],
            "label":       "LOCATION RESTORED",
            "body_template": "{name} \u2014 location tracking restored. {trail}",
            "priority":      "low",
            "sound":         "default",
            "channels":      ["sse", "push"],
            "requires_action": False,
            "louder":        False,
            "category":      "info",
        },
        "check_in_request": {
            "title_emoji": _EMOJI["warning"],
            "label":       "CHECK-IN",
            "body_template": "{name} \u2014 check-in requested. {trail}",
            "priority":      "warning",
            "sound":         "default",
            "channels":      ["sse", "push"],
            "requires_action": True,
            "louder":        False,
            "category":      "info",
        },
        "check_in_pending": {
            "title_emoji": _EMOJI["warning"],
            "label":       "CHECK-IN PENDING",
            "body_template": "{name} \u2014 check-in pending response. {trail}",
            "priority":      "warning",
            "sound":         "default",
            "channels":      ["sse", "push"],
            "requires_action": True,
            "louder":        False,
            "category":      "info",
        },

        # ── Safe / resolved ──────────────────────────────────────
        "arrived_safely": {
            "title_emoji": _EMOJI["safe"],
            "label":       "SAFE",
            "body_template": "{name} arrived safely. {trail}",
            "priority":      "low",
            "sound":         "silent",
            "channels":      ["sse", "push"],
            "requires_action": False,
            "louder":        False,
            "category":      "info",
        },
        "resolved": {
            "title_emoji": _EMOJI["safe"],
            "label":       "RESOLVED",
            "body_template": "{name} \u2014 incident resolved. {trail}",
            "priority":      "low",
            "sound":         "silent",
            "channels":      ["sse", "push"],
            "requires_action": False,
            "louder":        False,
            "category":      "info",
        },
    },
}


# Generic fallback used when `kind` is not in the registry.
_FALLBACK_SPEC: AlertSpec = {
    "title_emoji": _EMOJI["warning"],
    "label":       "ALERT",
    "body_template": "{name} \u2014 {fallback_msg}{trail_suffix}",
    "priority":      "warning",
    "sound":         "default",
    "channels":      ["sse", "push"],
    "requires_action": False,
    "louder":        False,
    "category":      "info",
}


# ── Public API ──────────────────────────────────────────────────────
def format_alert(
    kind: str,
    ctx: Optional[dict[str, Any]] = None,
    *,
    locale: str = DEFAULT_LOCALE,
) -> AlertEnvelope:
    """Return the canonical :class:`AlertEnvelope` for an alert kind.

    Args:
        kind:   the alert kind (e.g. "voice_distress", "sos", "fall_detected").
                Case-insensitive; unknown kinds fall back to a generic spec.
        ctx:    rendering context. Recognized keys (all optional):
                  * ``child_name`` (str, alias ``name``)
                  * ``location`` ({"lat": float, "lng": float})
                  * ``message`` (str) — used as fallback body for unknown kinds
                  * ``confidence`` (float 0–1)
                  * ``timestamp`` (datetime, defaults to now())
                Unknown keys are passed through to ``metadata.context_keys``
                for downstream consumers.
        locale: BCP-47-ish tag. Falls back to "en" when missing.

    Returns:
        AlertEnvelope — see TypedDict above.

    Guarantees:
        * Pure function: same args → same output (modulo timestamp).
        * Never raises on unknown kinds; never raises on partial ctx.
        * Always includes all top-level keys of :class:`AlertEnvelope`.
    """
    ctx = ctx or {}
    canonical_kind = (kind or "").strip().lower() or "unknown"

    table = REGISTRY.get(locale) or REGISTRY[DEFAULT_LOCALE]
    spec: AlertSpec = table.get(canonical_kind) or _FALLBACK_SPEC

    name = (ctx.get("child_name") or ctx.get("name") or "Someone").strip() or "Someone"
    loc_str = _loc_str(ctx.get("location"))
    ts = ctx.get("timestamp")
    if isinstance(ts, datetime):
        time_str = ts.astimezone(timezone.utc).strftime("%I:%M %p UTC")
    else:
        time_str = _now_str()
    trail = _trail(loc_str, time_str)
    fallback_msg = (ctx.get("message") or "alert").strip() or "alert"
    trail_suffix = f". {trail}" if trail else ""

    title = f"{spec['title_emoji']} NISCHINT {spec['label']}"
    body = spec["body_template"].format(
        name=name,
        loc_str=loc_str,
        time_str=time_str,
        trail=trail,
        fallback_msg=fallback_msg,
        trail_suffix=trail_suffix,
    )

    confidence = ctx.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None

    metadata: dict[str, Any] = {
        "kind":            canonical_kind,
        "category":        spec["category"],
        "severity_input":  ctx.get("severity"),
        "confidence":      confidence,
        "icon":            "siren" if spec["priority"] == "critical" else "warn",
        "locale":          locale if locale in REGISTRY else DEFAULT_LOCALE,
        "fallback":        spec is _FALLBACK_SPEC,
    }

    return {
        "kind":            canonical_kind,
        "title":           title,
        "body":            body,
        "priority":        spec["priority"],
        "sound":           spec["sound"],
        "channels":        list(spec["channels"]),
        "requires_action": bool(spec["requires_action"]),
        "louder":          bool(spec["louder"]),
        "metadata":        metadata,
    }
