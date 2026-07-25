"""
NISCHINT Notification Formatter — Unified signature voice system.

Formula:
  [EMOJI] NISCHINT [LABEL]
  [Name] + [what happened in one line]
  [Location] · [Time] · [Key fact]
  [CTA link] →

Severity colour codes:
  🔴 Critical — SOS, fall, no response
  🟡 Warning — zone breach, inactivity
  🔵 Info — journey start, guardian linked
  🟢 Safe — arrived safely, resolved
"""
from datetime import datetime, timezone


APP_URL = "https://nischint.care"


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%I:%M %p UTC")


def _loc_str(location: dict = None) -> str:
    if not location or not location.get("lat"):
        return ""
    return f"{location['lat']:.4f}, {location['lng']:.4f}"


def _loc_short(location: dict = None) -> str:
    if not location or not location.get("lat"):
        return "Unknown location"
    return f"{location['lat']:.4f},{location['lng']:.4f}"


def _map_url(location: dict = None) -> str:
    if not location or not location.get("lat"):
        return ""
    return f"https://maps.google.com/?q={location['lat']},{location['lng']}"


# ──────────────────────────────────────────────
# SMS formatters (≤160 chars target)
# ──────────────────────────────────────────────

def sms_sos(name: str, location: dict = None) -> str:
    loc = _loc_short(location)
    t = _now_str()
    return f"\U0001F534 NISCHINT SOS\n{name} triggered emergency SOS\n{loc} \u00b7 {t}\n{APP_URL}/m/alerts \u2192"


def sms_fall(name: str, location: dict = None) -> str:
    loc = _loc_short(location)
    t = _now_str()
    return f"\U0001F534 NISCHINT FALL\n{name} — fall detected, not moving\n{loc} \u00b7 {t}\n{APP_URL}/m/alerts \u2192"


def sms_zone_breach(name: str, zone_name: str = "safe zone", location: dict = None) -> str:
    loc = _loc_short(location)
    t = _now_str()
    return f"\U0001F7E1 NISCHINT ZONE\n{name} left {zone_name}\n{loc} \u00b7 {t}\n{APP_URL}/m/alerts \u2192"


def sms_journey_started(name: str, destination: str = "") -> str:
    t = _now_str()
    dest = f" to {destination}" if destination else ""
    return f"\U0001F535 NISCHINT JOURNEY\n{name} started a journey{dest}\n{t}\n{APP_URL}/m/live \u2192"


def sms_arrived_safely(name: str, destination: str = "") -> str:
    t = _now_str()
    dest = f" at {destination}" if destination else ""
    return f"\U0001F7E2 NISCHINT SAFE\n{name} arrived safely{dest}\n{t}"


def sms_escalation(name: str, level: int, incident_type: str) -> str:
    t = _now_str()
    emoji = "\U0001F534" if level >= 3 else "\U0001F7E1"
    label = "CRITICAL" if level >= 3 else f"L{level} ESCALATION"
    return f"{emoji} NISCHINT {label}\n{name} \u2014 {incident_type.replace('_', ' ')} unacknowledged\n{t} \u00b7 L{level}\n{APP_URL}/m/alerts \u2192"


def sms_resolved(name: str, incident_type: str) -> str:
    t = _now_str()
    return f"\U0001F7E2 NISCHINT RESOLVED\n{name} \u2014 {incident_type.replace('_', ' ')} resolved\n{t}"


# ──────────────────────────────────────────────
# Push notification formatters (title + body)
# ──────────────────────────────────────────────

def push_sos(name: str, location: dict = None) -> tuple:
    loc = _loc_str(location)
    t = _now_str()
    title = "\U0001F534 NISCHINT ALERT"
    loc_part = loc + " \u00b7 " if loc else ""
    body = f"{name} triggered SOS. {loc_part}{t}\nOpen guardian map \u2192"
    return title, body


def push_fall(name: str, location: dict = None) -> tuple:
    loc = _loc_str(location)
    t = _now_str()
    title = "\U0001F534 NISCHINT ALERT"
    loc_part = loc + " \u00b7 " if loc else ""
    body = f"{name} \u2014 fall detected, not moving. {loc_part}{t}\nOpen guardian map \u2192"
    return title, body


def push_zone_breach(name: str, zone_name: str = "safe zone", location: dict = None) -> tuple:
    loc = _loc_str(location)
    t = _now_str()
    title = "\U0001F7E1 NISCHINT ALERT"
    loc_part = loc + " \u00b7 " if loc else ""
    body = f"{name} left {zone_name}. {loc_part}{t}\nOpen guardian map \u2192"
    return title, body


def push_journey_started(name: str, destination: str = "") -> tuple:
    t = _now_str()
    dest = f" to {destination}" if destination else ""
    title = "\U0001F535 NISCHINT JOURNEY"
    body = f"{name} started a journey{dest}. {t}\nOpen guardian map \u2192"
    return title, body


def push_arrived_safely(name: str, destination: str = "") -> tuple:
    t = _now_str()
    dest = f" at {destination}" if destination else ""
    title = "\U0001F7E2 NISCHINT SAFE"
    body = f"{name} arrived safely{dest}. {t}"
    return title, body


def push_escalation(name: str, level: int, incident_type: str) -> tuple:
    t = _now_str()
    emoji = "\U0001F534" if level >= 3 else "\U0001F7E1"
    label = "CRITICAL" if level >= 3 else f"L{level} ESCALATION"
    title = f"{emoji} NISCHINT {label}"
    body = f"{name} \u2014 {incident_type.replace('_', ' ')} unacknowledged. {t} \u00b7 Level {level}\nOpen guardian map \u2192"
    return title, body


def push_resolved(name: str, incident_type: str) -> tuple:
    t = _now_str()
    title = "\U0001F7E2 NISCHINT RESOLVED"
    body = f"{name} \u2014 {incident_type.replace('_', ' ')} resolved. {t}"
    return title, body


def push_emergency_cancelled(name: str) -> tuple:
    t = _now_str()
    title = "\U0001F7E2 NISCHINT ALL CLEAR"
    body = f"{name} is safe now. SOS has been resolved. {t}"
    return title, body


# ──────────────────────────────────────────────
# Email formatters (subject + styled HTML)
# ──────────────────────────────────────────────

def _email_wrap(header_bg: str, header_text: str, name: str, body_html: str, cta_url: str = "", cta_label: str = "") -> str:
    cta_block = ""
    if cta_url and cta_label:
        cta_block = f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:20px;">
          <tr><td align="center">
            <a href="{cta_url}" style="display:inline-block;background-color:#0d9488;color:#fff;text-decoration:none;font-weight:bold;font-size:14px;padding:12px 28px;border-radius:10px;">
              {cta_label} &rarr;
            </a>
          </td></tr>
        </table>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#020617;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#020617;padding:40px 20px;">
    <tr><td align="center">
      <table width="440" cellpadding="0" cellspacing="0" style="background:#0f172a;border-radius:16px;border:1px solid #1e293b;overflow:hidden;">
        <tr><td style="background:{header_bg};padding:24px;text-align:center;">
          <h1 style="color:#fff;font-size:18px;margin:0;">{header_text}</h1>
        </td></tr>
        <tr><td style="padding:28px 24px;">
          {body_html}
          {cta_block}
        </td></tr>
        <tr><td style="background:#0b1120;padding:14px 24px;text-align:center;border-top:1px solid #1e293b;">
          <p style="color:#475569;font-size:11px;margin:0;">NISCHINT Safety &mdash; Protecting What Matters Most</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def email_sos(name: str, location: dict = None) -> tuple:
    t = _now_str()
    loc = _loc_str(location)
    map_link = _map_url(location)
    loc_html = f'<p style="color:#94a3b8;font-size:13px;margin:8px 0 0;">{loc} &middot; {t}</p>' if loc else f'<p style="color:#94a3b8;font-size:13px;margin:8px 0 0;">{t}</p>'
    map_html = f'<p style="margin:6px 0 0;"><a href="{map_link}" style="color:#2dd4bf;font-size:12px;">View on map &rarr;</a></p>' if map_link else ""

    subject = f"\U0001F534 NISCHINT SOS \u2014 {name} triggered emergency"
    html = _email_wrap(
        "#ef4444",
        "\U0001F534 NISCHINT SOS",
        name,
        f'<p style="color:#e2e8f0;font-size:15px;margin:0;"><strong>{name}</strong> triggered an emergency SOS</p>'
        f'{loc_html}{map_html}',
        f"{APP_URL}/m/alerts",
        "Open Live Tracking",
    )
    return subject, html


def email_fall(name: str, location: dict = None) -> tuple:
    t = _now_str()
    loc = _loc_str(location)
    map_link = _map_url(location)
    loc_html = f'<p style="color:#94a3b8;font-size:13px;margin:8px 0 0;">{loc} &middot; {t}</p>' if loc else f'<p style="color:#94a3b8;font-size:13px;margin:8px 0 0;">{t}</p>'
    map_html = f'<p style="margin:6px 0 0;"><a href="{map_link}" style="color:#2dd4bf;font-size:12px;">View on map &rarr;</a></p>' if map_link else ""

    subject = f"\U0001F534 NISCHINT FALL \u2014 {name} fall detected"
    html = _email_wrap(
        "#ef4444",
        "\U0001F534 NISCHINT FALL DETECTED",
        name,
        f'<p style="color:#e2e8f0;font-size:15px;margin:0;"><strong>{name}</strong> &mdash; fall detected, not moving</p>'
        f'{loc_html}{map_html}',
        f"{APP_URL}/m/alerts",
        "View Incident",
    )
    return subject, html


def email_zone_breach(name: str, zone_name: str = "safe zone", location: dict = None) -> tuple:
    t = _now_str()
    loc = _loc_str(location)
    map_link = _map_url(location)
    loc_html = f'<p style="color:#94a3b8;font-size:13px;margin:8px 0 0;">{loc} &middot; {t}</p>' if loc else f'<p style="color:#94a3b8;font-size:13px;margin:8px 0 0;">{t}</p>'
    map_html = f'<p style="margin:6px 0 0;"><a href="{map_link}" style="color:#2dd4bf;font-size:12px;">View on map &rarr;</a></p>' if map_link else ""

    subject = f"\U0001F7E1 NISCHINT ZONE \u2014 {name} left {zone_name}"
    html = _email_wrap(
        "#f59e0b",
        "\U0001F7E1 NISCHINT ZONE BREACH",
        name,
        f'<p style="color:#e2e8f0;font-size:15px;margin:0;"><strong>{name}</strong> left {zone_name}</p>'
        f'{loc_html}{map_html}',
        f"{APP_URL}/m/alerts",
        "View Location",
    )
    return subject, html


def email_journey_started(name: str, destination: str = "") -> tuple:
    t = _now_str()
    dest = f" to {destination}" if destination else ""
    subject = f"\U0001F535 NISCHINT JOURNEY \u2014 {name} started a journey{dest}"
    html = _email_wrap(
        "#3b82f6",
        "\U0001F535 NISCHINT JOURNEY",
        name,
        f'<p style="color:#e2e8f0;font-size:15px;margin:0;"><strong>{name}</strong> started a journey{dest}</p>'
        f'<p style="color:#94a3b8;font-size:13px;margin:8px 0 0;">{t}</p>',
        f"{APP_URL}/m/live",
        "Track Live",
    )
    return subject, html


def email_arrived_safely(name: str, destination: str = "") -> tuple:
    t = _now_str()
    dest = f" at {destination}" if destination else ""
    subject = f"\U0001F7E2 NISCHINT SAFE \u2014 {name} arrived safely{dest}"
    html = _email_wrap(
        "#10b981",
        "\U0001F7E2 NISCHINT SAFE",
        name,
        f'<p style="color:#e2e8f0;font-size:15px;margin:0;"><strong>{name}</strong> arrived safely{dest}</p>'
        f'<p style="color:#94a3b8;font-size:13px;margin:8px 0 0;">{t}</p>',
    )
    return subject, html


def email_escalation(name: str, level: int, incident_type: str) -> tuple:
    t = _now_str()
    emoji = "\U0001F534" if level >= 3 else "\U0001F7E1"
    label = "CRITICAL" if level >= 3 else f"L{level} ESCALATION"
    bg = "#ef4444" if level >= 3 else "#f59e0b"
    subject = f"{emoji} NISCHINT {label} \u2014 {name} {incident_type.replace('_', ' ')}"
    html = _email_wrap(
        bg,
        f"{emoji} NISCHINT {label}",
        name,
        f'<p style="color:#e2e8f0;font-size:15px;margin:0;"><strong>{name}</strong> &mdash; {incident_type.replace("_", " ")} unacknowledged</p>'
        f'<p style="color:#94a3b8;font-size:13px;margin:8px 0 0;">{t} &middot; Level {level}</p>',
        f"{APP_URL}/m/alerts",
        "Respond Now",
    )
    return subject, html
