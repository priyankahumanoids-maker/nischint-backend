"""DPDP-04-DIGEST — Weekly DPO digest email.

Every Monday at 09:00 IST (03:30 UTC) the scheduler:

  1. Snapshots `compute_consent_health(session)` (same logic the
     Command Center capsule polls).
  2. Loads last week's snapshot from `dpdp_consent_snapshots`.
  3. Diffs every category's grant_rate; anything that fell strictly
     more than DROP_THRESHOLD percentage points is flagged.
  4. Persists this week's snapshot (idempotent on `week_start`).
  5. Renders both a plain-text and HTML email and ships via SendGrid
     to `DPDP_DIGEST_RECIPIENT` (default: dpo@nischint.care).

DPDP §10 obligations require the DPO to demonstrate active monitoring
of consent — this scheduler is that monitoring, auto-archived in the
DPO's mailbox.

Recipient override:
  • Environment variable `DPDP_DIGEST_RECIPIENT`
  • If unset, falls back to `dpo@nischint.care`.

The job is idempotent on `week_start` so re-running it on the same
Monday (e.g. after a deploy/restart) does NOT double-send the email.
The unique constraint guarantees one row per week.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.consents import compute_consent_health
from app.services.email_service import send_email

logger = logging.getLogger(__name__)


# ── Tunables ─────────────────────────────────────────────────────────


# Categories that drop strictly more than this many percentage points
# vs last week are flagged. 5pp matches the §10 obligation guidance —
# anything tighter triggers on weekly noise; anything wider misses
# slow-burn regressions.
DROP_THRESHOLD: float = 0.05  # 5 percentage points

DIGEST_RECIPIENT_DEFAULT = "dpo@nischint.care"


def _get_recipient() -> str:
    return os.environ.get("DPDP_DIGEST_RECIPIENT", DIGEST_RECIPIENT_DEFAULT)


# ── Schema ───────────────────────────────────────────────────────────


_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS dpdp_consent_snapshots (
    id UUID PRIMARY KEY,
    week_start DATE NOT NULL,
    week_end   DATE NOT NULL,
    snapshot_json JSONB NOT NULL DEFAULT '{}',
    diff_json     JSONB NOT NULL DEFAULT '{}',
    email_sent    BOOLEAN DEFAULT FALSE,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(week_start)
);
"""

_tables_ready = False


async def _ensure_snapshot_table(db: AsyncSession) -> None:
    """Create the snapshot table on demand. Idempotent and cheap.

    We don't lean on Alembic for this; the table is internal to the
    scheduler and never appears in API contracts, so an
    `IF NOT EXISTS` create at boot is enough.
    """
    global _tables_ready
    if _tables_ready:
        return
    await db.execute(text(_TABLE_SQL))
    await db.commit()
    _tables_ready = True


# ── Diff logic ───────────────────────────────────────────────────────


def compute_diff(
    current: dict[str, Any],
    last: Optional[dict[str, Any]],
    drop_threshold: float = DROP_THRESHOLD,
) -> dict[str, Any]:
    """Compute the per-category delta vs last week's snapshot.

    Both `current` and `last` are the same shape as
    `ConsentHealthBundle.dict()`. `last` is None on the first-ever
    run (no prior snapshot).

    Returns a dict with:
      • `categories` — per-category {category, label_en, current_rate,
                       previous_rate, delta_pp, dropped} where
                       `delta_pp` is in percentage points
                       (current - previous) * 100, signed.
      • `flagged` — subset of `categories` whose `dropped` is True
                    (delta_pp < -drop_threshold * 100).
      • `has_history` — whether we had a previous snapshot to compare
                        against. First-run digests are not "no
                        regressions"; they're "no history yet".
    """
    last_rates: dict[str, float] = {}
    if last and last.get("categories"):
        for c in last["categories"]:
            last_rates[c["category"]] = float(c.get("grant_rate", 0.0))

    out_categories: list[dict[str, Any]] = []
    for c in current.get("categories", []):
        cat = c["category"]
        cur = float(c.get("grant_rate", 0.0))
        prev = last_rates.get(cat)
        if prev is None:
            delta_pp = 0.0
            dropped = False
        else:
            delta_pp = round((cur - prev) * 100, 2)
            # Compare in percentage-point space (already rounded to 2dp)
            # to avoid IEEE-754 boundary surprises around exactly -5.00pp.
            dropped = delta_pp < -round(drop_threshold * 100, 2)
        out_categories.append({
            "category": cat,
            "label_en": c.get("label_en", cat),
            "current_rate": round(cur, 4),
            "previous_rate": round(prev, 4) if prev is not None else None,
            "delta_pp": delta_pp,
            "current_decided": c.get("decided", 0),
            "current_granted": c.get("granted", 0),
            "dropped": dropped,
        })

    flagged = [c for c in out_categories if c["dropped"]]

    return {
        "categories": out_categories,
        "flagged": flagged,
        "has_history": last is not None,
        "drop_threshold_pp": round(drop_threshold * 100, 2),
    }


# ── Templating ───────────────────────────────────────────────────────


def render_subject(week_end: date) -> str:
    """Single source of truth for the email subject line."""
    return f"NISCHINT Weekly Consent Health — {week_end.isoformat()}"


def render_text(current: dict[str, Any], diff: dict[str, Any], week_end: date) -> str:
    """Plain-text body. Intentionally compact; the HTML version is
    the marketing-grade rendering.
    """
    lines: list[str] = []
    lines.append(f"NISCHINT Weekly Consent Health — week ending {week_end.isoformat()}")
    lines.append("=" * 64)
    lines.append("")
    lines.append(f"Total users prompted (cumulative): {current.get('total_users_prompted', 0)}")
    lines.append(f"Overall state: {current.get('overall_state', 'nodata').upper()}")
    lines.append("")

    if not diff.get("has_history"):
        lines.append(
            "First snapshot — no prior week to compare against. "
            "Future digests will flag any category that fell more than "
            f"{diff.get('drop_threshold_pp', 5)} pp week-over-week."
        )
        lines.append("")

    flagged = diff.get("flagged", [])
    if flagged:
        lines.append(f"!! FLAGGED — {len(flagged)} categor{'y' if len(flagged) == 1 else 'ies'} dropped > {diff.get('drop_threshold_pp', 5)} pp:")
        for c in flagged:
            lines.append(
                f"  • {c['label_en']}: "
                f"{c['previous_rate'] * 100:.1f}% → {c['current_rate'] * 100:.1f}% "
                f"({c['delta_pp']:+.1f} pp)"
            )
        lines.append("")

    lines.append("Per-category grant rate this week:")
    for c in diff.get("categories", []):
        cur_pct = f"{c['current_rate'] * 100:.1f}%"
        if c.get("previous_rate") is None:
            change = "(new)"
        else:
            change = f"({c['delta_pp']:+.1f} pp)"
        lines.append(
            f"  - {c['label_en']:<22} {cur_pct:>7}  {change:>12}  "
            f"n={c['current_decided']}"
        )

    lines.append("")
    lines.append("— Nischint DPDP compliance scheduler (automated)")
    lines.append("DPDP §10 — DPO active-monitoring log.")
    return "\n".join(lines)


def _row_tone(c: dict[str, Any]) -> tuple[str, str]:
    """(bg_color, text_color) for a single category row in the HTML
    table. Mirrors the in-app capsule colour spec.
    """
    if c.get("dropped"):
        return ("#7f1d1d", "#fecaca")   # rose-900 / rose-200
    rate = c.get("current_rate", 0.0)
    if rate >= 0.80:
        return ("#064e3b", "#a7f3d0")   # emerald-900 / emerald-200
    if rate >= 0.50:
        return ("#78350f", "#fde68a")   # amber-900 / amber-200
    return ("#7f1d1d", "#fecaca")        # critical


def render_html(current: dict[str, Any], diff: dict[str, Any], week_end: date) -> str:
    flagged = diff.get("flagged", [])
    cats = diff.get("categories", [])

    rows_html = []
    for c in cats:
        bg, fg = _row_tone(c)
        prev = c.get("previous_rate")
        prev_str = f"{prev * 100:.1f}%" if prev is not None else "—"
        delta_str = "new" if prev is None else f"{c['delta_pp']:+.1f} pp"
        rows_html.append(
            f'<tr style="background:{bg};color:{fg};">'
            f'<td style="padding:8px 10px;font-weight:600;">{c["label_en"]}</td>'
            f'<td style="padding:8px 10px;text-align:right;font-variant-numeric:tabular-nums;">{c["current_rate"] * 100:.1f}%</td>'
            f'<td style="padding:8px 10px;text-align:right;font-variant-numeric:tabular-nums;color:#cbd5e1;">{prev_str}</td>'
            f'<td style="padding:8px 10px;text-align:right;font-variant-numeric:tabular-nums;">{delta_str}</td>'
            f'<td style="padding:8px 10px;text-align:right;font-variant-numeric:tabular-nums;color:#94a3b8;">n={c["current_decided"]}</td>'
            f'</tr>'
        )
    rows_block = "\n".join(rows_html) or (
        '<tr><td colspan="5" style="padding:14px;text-align:center;color:#94a3b8;">No consent rows yet.</td></tr>'
    )

    flag_block = ""
    if flagged:
        flag_items = "\n".join([
            f'<li style="margin:4px 0;">'
            f'<strong>{c["label_en"]}</strong>: '
            f'{c["previous_rate"] * 100:.1f}% → {c["current_rate"] * 100:.1f}% '
            f'<span style="color:#fca5a5;">({c["delta_pp"]:+.1f} pp)</span>'
            f'</li>'
            for c in flagged
        ])
        flag_block = (
            f'<div style="margin:0 0 16px;padding:14px 16px;background:#7f1d1d;border-radius:8px;border-left:4px solid #ef4444;">'
            f'<div style="color:#fecaca;font-weight:700;margin-bottom:6px;">'
            f'⚠ {len(flagged)} categor{"y" if len(flagged) == 1 else "ies"} dropped &gt; '
            f'{diff.get("drop_threshold_pp", 5)} pp this week'
            f'</div>'
            f'<ul style="margin:0;padding-left:20px;color:#fecaca;font-size:13px;">'
            f'{flag_items}'
            f'</ul></div>'
        )

    history_note = ""
    if not diff.get("has_history"):
        history_note = (
            '<p style="color:#94a3b8;font-size:13px;line-height:1.5;margin:0 0 16px;">'
            'This is the first snapshot — no prior week to compare against. '
            'Future digests will flag any category that fell more than '
            f'{diff.get("drop_threshold_pp", 5)} pp week-over-week.'
            '</p>'
        )

    overall = current.get("overall_state", "nodata").upper()
    overall_color = {
        "OK":       "#10b981",
        "WARNING":  "#f59e0b",
        "CRITICAL": "#ef4444",
        "NODATA":   "#64748b",
    }.get(overall, "#64748b")

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#020617;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#e2e8f0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#020617;padding:32px 16px;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#0f172a;border-radius:16px;border:1px solid #1e293b;overflow:hidden;">

        <tr><td style="padding:24px 24px 8px;">
          <div style="font-size:11px;font-weight:700;letter-spacing:1.5px;color:#22d3ee;text-transform:uppercase;">DPDP §10 Active-monitoring</div>
          <h1 style="font-size:22px;margin:6px 0 4px;color:#f1f5f9;">Weekly Consent Health</h1>
          <div style="color:#94a3b8;font-size:13px;">Week ending <strong style="color:#cbd5e1;">{week_end.isoformat()}</strong></div>
        </td></tr>

        <tr><td style="padding:16px 24px 4px;">
          <table cellpadding="0" cellspacing="0" style="width:100%;background:#1e293b;border-radius:10px;">
            <tr>
              <td style="padding:14px 16px;color:#94a3b8;font-size:12px;">Users prompted (cumulative)</td>
              <td style="padding:14px 16px;text-align:right;font-size:20px;font-weight:700;color:#f1f5f9;">{current.get("total_users_prompted", 0)}</td>
            </tr>
            <tr><td colspan="2" style="border-top:1px solid #334155;"></td></tr>
            <tr>
              <td style="padding:14px 16px;color:#94a3b8;font-size:12px;">Overall state</td>
              <td style="padding:14px 16px;text-align:right;font-size:14px;font-weight:700;color:{overall_color};">{overall}</td>
            </tr>
          </table>
        </td></tr>

        <tr><td style="padding:20px 24px 0;">{history_note}{flag_block}</td></tr>

        <tr><td style="padding:0 24px 16px;">
          <table cellpadding="0" cellspacing="0" style="width:100%;border-collapse:separate;border-spacing:0 4px;font-size:13px;">
            <thead><tr style="color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;">
              <th align="left"  style="padding:4px 10px;">Category</th>
              <th align="right" style="padding:4px 10px;">This week</th>
              <th align="right" style="padding:4px 10px;">Last week</th>
              <th align="right" style="padding:4px 10px;">Δ</th>
              <th align="right" style="padding:4px 10px;">Sample</th>
            </tr></thead>
            <tbody>
              {rows_block}
            </tbody>
          </table>
        </td></tr>

        <tr><td style="padding:14px 24px 24px;border-top:1px solid #1e293b;color:#64748b;font-size:11px;line-height:1.5;">
          Generated automatically by the Nischint DPDP scheduler. Source:
          <code style="color:#22d3ee;">/api/admin/consents/health</code>.
          Snapshot row id stored in <code style="color:#22d3ee;">dpdp_consent_snapshots</code> for §10 audit.
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


# ── Orchestrator ─────────────────────────────────────────────────────


async def _fetch_last_snapshot(
    db: AsyncSession,
    before_week: date,
) -> Optional[dict[str, Any]]:
    """Most recent snapshot prior to `before_week`.

    We look up the latest row strictly before this week's `week_start`
    so even if a previous run was skipped / delayed, the diff still
    compares against the most recent historical evidence.
    """
    res = await db.execute(
        text(
            "SELECT snapshot_json FROM dpdp_consent_snapshots "
            "WHERE week_start < :ws "
            "ORDER BY week_start DESC LIMIT 1"
        ),
        {"ws": before_week},
    )
    row = res.fetchone()
    if not row:
        return None
    snap = row[0]
    if isinstance(snap, str):
        snap = json.loads(snap)
    return snap


def _week_window(now_utc: Optional[datetime] = None) -> tuple[date, date]:
    """Returns (week_start, week_end) inclusive for the *current* ISO week
    using Monday as the anchor. The job runs Monday 09:00 IST, so the
    "current week" is the one that *just started* — week_end will be 6
    days later.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    today = now_utc.date()
    # ISO Monday = 0
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=6)


async def generate_weekly_digest(
    db: AsyncSession,
    now_utc: Optional[datetime] = None,
    *,
    force_resend: bool = False,
) -> dict[str, Any]:
    """End-to-end orchestrator. Idempotent on `week_start`.

    Returns a status dict describing the run for callers that want
    introspection (the scheduler tick logs it).
    """
    await _ensure_snapshot_table(db)

    week_start, week_end = _week_window(now_utc)

    # If a row already exists for this week we DO NOT re-send unless
    # `force_resend=True`. This guards against supervisor restarts
    # firing the same Monday tick twice.
    existing = await db.execute(
        text("SELECT id, email_sent FROM dpdp_consent_snapshots WHERE week_start = :ws"),
        {"ws": week_start},
    )
    existing_row = existing.fetchone()
    if existing_row is not None and existing_row[1] and not force_resend:
        logger.info(f"[DPDP_DIGEST] week_start={week_start} already sent — skipping")
        return {
            "skipped": True,
            "reason": "already_sent",
            "week_start": week_start.isoformat(),
        }

    bundle = await compute_consent_health(db)
    current = bundle.model_dump()
    # JSON-friendly datetime
    if isinstance(current.get("generated_at"), datetime):
        current["generated_at"] = current["generated_at"].isoformat()

    last = await _fetch_last_snapshot(db, week_start)
    diff = compute_diff(current, last)

    subject = render_subject(week_end)
    text_body = render_text(current, diff, week_end)
    html_body = render_html(current, diff, week_end)

    recipient = _get_recipient()
    email_sent = False
    try:
        email_sent = send_email(
            to=recipient,
            subject=subject,
            html_content=html_body,
            text_content=text_body,
        )
    except Exception as e:  # pragma: no cover — defensive
        logger.error(f"[DPDP_DIGEST] send_email raised: {e}")

    snapshot_row_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO dpdp_consent_snapshots "
            "  (id, week_start, week_end, snapshot_json, diff_json, email_sent) "
            "VALUES (:id, :ws, :we, CAST(:snap AS JSONB), CAST(:diff AS JSONB), :sent) "
            "ON CONFLICT (week_start) DO UPDATE SET "
            "  snapshot_json = EXCLUDED.snapshot_json, "
            "  diff_json     = EXCLUDED.diff_json, "
            "  email_sent    = dpdp_consent_snapshots.email_sent OR EXCLUDED.email_sent"
        ),
        {
            "id": snapshot_row_id,
            "ws": week_start,
            "we": week_end,
            "snap": json.dumps(current),
            "diff": json.dumps(diff),
            "sent": email_sent,
        },
    )
    await db.commit()

    logger.info(
        f"[DPDP_DIGEST] week_start={week_start} recipient={recipient} "
        f"email_sent={email_sent} flagged={len(diff.get('flagged', []))}"
    )
    return {
        "skipped": False,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "recipient": recipient,
        "email_sent": email_sent,
        "flagged_count": len(diff.get("flagged", [])),
        "has_history": diff.get("has_history", False),
        "subject": subject,
    }


# ── Scheduler ────────────────────────────────────────────────────────


def start_dpdp_digest_scheduler() -> None:
    """Register the cron job — Monday 09:00 IST (03:30 UTC)."""
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        async def _run() -> None:
            from app.api.deps import get_db_session  # local import to break cycle
            async for session in get_db_session():
                await generate_weekly_digest(session)

        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            _run,
            CronTrigger(day_of_week="mon", hour=3, minute=30),
            id="dpdp_weekly_digest",
            replace_existing=True,
        )
        scheduler.start()
        logger.info(
            "[DPDP_DIGEST] Scheduler registered — runs every Monday 03:30 UTC (09:00 IST)"
        )
    except ImportError:
        logger.warning("[DPDP_DIGEST] apscheduler not available — weekly digest disabled")
    except Exception as e:
        logger.error(f"[DPDP_DIGEST] Scheduler setup failed: {e}")
