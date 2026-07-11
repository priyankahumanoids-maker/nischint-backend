"""
DPDP-compliant privacy export endpoint.

Implements the Data Principal's right of access under §11 of the Digital
Personal Data Protection Act, 2023 (India). Returns a structured summary
of every category of personal data processed by Nischint for the calling
user, along with retention, third-party processor disclosures, and rights
information.

Endpoint:
    GET /api/privacy/me              -> application/json
    GET /api/privacy/me?format=pdf   -> application/pdf

Auth: Bearer JWT (user can only export THEIR OWN data).
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.models.device import Device
from app.models.incident import Incident
from app.models.safety_event import SafetyEvent
from app.models.senior import Senior
from app.models.user import User


router = APIRouter(prefix="/privacy", tags=["privacy", "dpdp"])

EXPORT_VERSION = "1.0"

# Static disclosures (kept in code so they version with the app and are
# auditable via git history — DPDP §6 transparency requirement).
THIRD_PARTY_PROCESSORS = [
    {
        "name": "Supabase (ap-south-1, Mumbai)",
        "purpose": "Primary relational data store (PostgreSQL)",
        "data_categories": ["profile", "seniors", "devices", "incidents", "telemetry"],
        "data_residency": "India",
    },
    {
        "name": "Twilio",
        "purpose": "Emergency SMS delivery to guardians",
        "data_categories": ["phone number", "alert message text"],
        "data_residency": "United States",
    },
    {
        "name": "Firebase Cloud Messaging",
        "purpose": "Mobile push notifications",
        "data_categories": ["device push token", "alert message text"],
        "data_residency": "United States / Global",
    },
    {
        "name": "Emergent LLM Gateway",
        "purpose": "AI inference for chatbot, summarisation, behavioural scoring",
        "data_categories": ["chatbot text", "anonymised event metadata"],
        "data_residency": "United States (no audio or video forwarded)",
    },
    {
        "name": "Upstash Redis",
        "purpose": "Real-time event broadcasting and short-lived caching",
        "data_categories": ["incident IDs", "session tokens (TTL <= 24h)"],
        "data_residency": "ap-south-1 (Mumbai)",
    },
]

PRIVACY_DISCLOSURES = {
    "audio": (
        "No audio stored — inference only. Voice trigger and Whisper "
        "transcription run in-memory; raw audio bytes are discarded "
        "immediately after the classification result is recorded."
    ),
    "video": (
        "No video stored under normal operation. Live emergency streams "
        "(NISCH-008) are recorded only while an SOS incident is active "
        "and are auto-purged after 30 days unless evidence-locked."
    ),
    "biometrics": (
        "No facial or fingerprint biometric templates stored. "
        "Fall-detection and motion features are derived numeric vectors only."
    ),
    "retention_days": {
        "telemetry": 180,
        "location_trail": 90,
        "incidents": 365,
        "behavioural_baselines": 365,
        "chatbot_history": 30,
    },
}

DATA_PRINCIPAL_RIGHTS = {
    "access": "GET /api/privacy/me (this endpoint)",
    "portability": "GET /api/privacy/me?format=pdf",
    "correction": "PATCH /api/users/me (profile fields)",
    "erasure": (
        "Email privacy@nischint.care with subject 'DPDP Erasure Request'. "
        "Self-serve deletion (NISCH-009) is on the roadmap."
    ),
    "grievance_officer": {
        "name": "Data Protection Officer",
        "email": "privacy@nischint.care",
        "response_sla_days": 7,
    },
    "consent_withdrawal": "Disable notification channels in app settings.",
}


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()


async def _build_export(session: AsyncSession, user: User) -> dict[str, Any]:
    """Assemble the user's DPDP data summary."""

    # Seniors under care + per-senior device/incident counts.
    seniors = (
        await session.execute(
            select(Senior).where(Senior.guardian_id == user.id).order_by(Senior.created_at.asc())
        )
    ).scalars().all()

    senior_ids = [s.id for s in seniors]

    device_counts: dict[str, int] = {}
    incident_counts: dict[str, int] = {}
    if senior_ids:
        dev_rows = await session.execute(
            select(Device.senior_id, func.count(Device.id))
            .where(Device.senior_id.in_(senior_ids))
            .group_by(Device.senior_id)
        )
        device_counts = {str(sid): int(cnt) for sid, cnt in dev_rows.all()}

        inc_rows = await session.execute(
            select(Incident.senior_id, func.count(Incident.id))
            .where(Incident.senior_id.in_(senior_ids))
            .group_by(Incident.senior_id)
        )
        incident_counts = {str(sid): int(cnt) for sid, cnt in inc_rows.all()}

    seniors_out = [
        {
            "id": str(s.id),
            "full_name": s.full_name,
            "age": s.age,
            "medical_notes_present": bool(s.medical_notes),
            "device_count": device_counts.get(str(s.id), 0),
            "incident_count": incident_counts.get(str(s.id), 0),
            "created_at": _iso(s.created_at),
        }
        for s in seniors
    ]

    total_devices = sum(device_counts.values())
    total_incidents = sum(incident_counts.values())

    safety_event_total = int(
        (
            await session.execute(
                select(func.count(SafetyEvent.id)).where(
                    SafetyEvent.user_id == user.id
                )
            )
        ).scalar_one()
    )

    last_location = None
    if user.last_known_lat is not None and user.last_known_lng is not None:
        last_location = {
            "lat": user.last_known_lat,
            "lng": user.last_known_lng,
            "captured_at": _iso(user.last_known_at),
        }

    return {
        "export_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "format_version": EXPORT_VERSION,
            "regulation": "Digital Personal Data Protection Act, 2023 (India)",
            "data_residency": "ap-south-1 (Mumbai, India)",
            "data_principal_id": str(user.id),
            "data_fiduciary": "Nischint Care Technologies",
        },
        "data_principal": {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "phone": user.phone,
            "role": user.role,
            "facility_id": user.facility_id,
            "is_active": user.is_active,
            "preferred_channels": user.preferred_channels,
            "created_at": _iso(user.created_at),
        },
        "last_known_location": last_location,
        "seniors_under_care": seniors_out,
        "data_categories": {
            "profile":            {"records": 1,                  "purpose": "Account identification & authentication"},
            "seniors":            {"records": len(seniors_out),   "purpose": "Caregiving relationship"},
            "devices":            {"records": total_devices,      "purpose": "Telemetry ingestion & alerting"},
            "incidents":          {"records": total_incidents,    "purpose": "Safety event history & escalation"},
            "safety_events":      {"records": safety_event_total, "purpose": "Behavioural / environmental signal log"},
        },
        "privacy_disclosures": PRIVACY_DISCLOSURES,
        "third_party_processors": THIRD_PARTY_PROCESSORS,
        "rights": DATA_PRINCIPAL_RIGHTS,
    }


def _render_pdf(payload: dict[str, Any], lang: str = "en") -> bytes:
    """Render the export as a simple, audit-friendly PDF (ReportLab).

    Supports English (`lang='en'`, default) and Hindi (`lang='hi'`) via
    `privacy_i18n.t()` lookups. When `lang='hi'`, the renderer registers
    Noto Sans Devanagari (bundled at /app/backend/assets/fonts/) and
    uses a hybrid font strategy:

      * Devanagari labels → NotoSansDevanagari (the font has full
        Devanagari coverage but only partial Latin — no A-Z/a-z/@).
      * Latin-script values (emails, UUIDs, ISO dates) → Helvetica.
      * Mixed-script paragraphs → Paragraph with inline
        `<font name="NotoSansDevanagari">…</font>` tags wrapping the
        Devanagari spans only. Everything outside the tags falls
        through to the Paragraph's base font (Helvetica).

    Missing translations gracefully fall back to English — DPDP §11
    compliance never breaks because a label wasn't translated.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    from reportlab.lib import colors

    from app.api.privacy_i18n import t

    hindi = lang == "hi"
    deva_font = _ensure_devanagari_font() if hindi else None

    def _wrap(s: str) -> str:
        """Wrap a possibly-Devanagari string for use inside a Paragraph.

        In Hindi mode, wraps the string in `<font name="NotoDev">…</font>`
        so Devanagari glyphs render correctly while the surrounding
        Paragraph base font (Helvetica) handles any adjacent ASCII.
        In English mode, this is the identity transform.
        """
        if not hindi or deva_font in (None, "Helvetica"):
            return s
        return f'<font name="{deva_font}">{s}</font>'

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=t(lang, "doc_title"),
    )

    styles = getSampleStyleSheet()
    # Paragraph base font stays Helvetica even in Hindi mode — Devanagari
    # spans get wrapped with inline <font> tags so adjacent Latin works.
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18, leading=22)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=13, leading=16)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10, leading=13)
    mono = ParagraphStyle(
        "mono", parent=body, fontName="Courier", fontSize=8, leading=10,
    )

    # Table label column font (column 0). Switch to Devanagari in Hindi
    # mode so Hindi labels render. The value columns stay Helvetica.
    label_font = deva_font if (hindi and deva_font != "Helvetica") else "Helvetica"

    story: list[Any] = []
    meta = payload["export_meta"]
    principal = payload["data_principal"]

    story.append(Paragraph(_wrap(t(lang, "doc_title")), h1))
    story.append(Paragraph(
        f'{_wrap(t(lang, "export_date"))}: {meta["generated_at"]}',
        body,
    ))
    story.append(Paragraph(
        f'{_wrap(t(lang, "generated_label"))} {meta["generated_at"]} '
        f'&nbsp;|&nbsp; {_wrap(t(lang, "data_residency_label"))}: '
        f'{meta["data_residency"]}',
        body,
    ))
    story.append(Paragraph(_wrap(t(lang, "regulation_label")), body))
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph(_wrap(t(lang, "section_data_principal")), h2))
    dash = t(lang, "none_dash")
    principal_rows = [
        [t(lang, "field_user_id"), principal["id"]],
        [t(lang, "field_email"), principal["email"] or dash],
        [t(lang, "field_full_name"), principal["full_name"] or dash],
        [t(lang, "field_phone"), principal["phone"] or dash],
        [t(lang, "field_role"), principal["role"]],
        [t(lang, "field_account_created"), principal["created_at"] or dash],
        [
            t(lang, "field_active"),
            # Value is "हाँ"/"नहीं" in Hindi mode → wrap in a Paragraph
            # so the inline <font> tag picks up the Devanagari glyphs.
            # In English mode this stays a plain string ("yes"/"no").
            Paragraph(_wrap(t(lang, "yes")), body) if principal["is_active"]
            else Paragraph(_wrap(t(lang, "no")), body),
        ],
    ]
    t_principal = Table(principal_rows, colWidths=[40 * mm, 130 * mm])
    t_principal.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        # Label column (Hindi text) gets Devanagari font; value column
        # (UUIDs, emails, dates) gets Helvetica for Latin coverage.
        ("FONTNAME", (0, 0), (0, -1), label_font),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story.append(t_principal)
    story.append(Spacer(1, 5 * mm))

    story.append(Paragraph(_wrap(t(lang, "section_right_to_access")), h2))
    cat_rows = [[
        t(lang, "col_category"),
        t(lang, "col_records"),
        t(lang, "col_purpose"),
    ]]
    for name, info in payload["data_categories"].items():
        cat_rows.append([name, str(info["records"]), info["purpose"]])
    t_cat = Table(cat_rows, colWidths=[40 * mm, 20 * mm, 110 * mm])
    t_cat.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        # Header row in Hindi — needs Devanagari font.
        ("FONTNAME", (0, 0), (-1, 0), label_font),
        # Body rows: category names + purpose strings come from English
        # payload data, so Helvetica is correct.
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story.append(t_cat)
    story.append(Spacer(1, 5 * mm))

    # ── 3a. Incident timeline (DPDP-03 spec label) ────────────────────
    # The detailed per-incident list is a P1 follow-up — `_build_export`
    # currently aggregates counts into `data_categories.incidents`. The
    # section header is rendered now so the PDF surface matches the
    # spec; an empty payload shows the "no records" line.
    story.append(Paragraph(_wrap(t(lang, "section_incident_timeline")), h2))
    incidents = payload.get("incidents") or []
    if incidents:
        rows = [["#", "When", "Type", "Status"]]
        for i, inc in enumerate(incidents, 1):
            rows.append([
                str(i),
                inc.get("occurred_at") or dash,
                inc.get("type") or dash,
                inc.get("status") or dash,
            ])
        t_inc = Table(rows, colWidths=[10 * mm, 50 * mm, 50 * mm, 60 * mm])
        t_inc.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        story.append(t_inc)
    else:
        story.append(Paragraph(_wrap(t(lang, "no_incidents")), body))
    story.append(Spacer(1, 5 * mm))

    # ── 3b. Emergency contacts ────────────────────────────────────────
    story.append(Paragraph(_wrap(t(lang, "section_emergency_contacts")), h2))
    ecs = payload.get("emergency_contacts") or []
    if ecs:
        rows = [["Name", "Phone", "Relationship"]]
        for c in ecs:
            rows.append([
                c.get("name") or dash,
                c.get("phone") or dash,
                c.get("relationship") or dash,
            ])
        t_ec = Table(rows, colWidths=[60 * mm, 50 * mm, 60 * mm])
        t_ec.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        story.append(t_ec)
    else:
        story.append(Paragraph(_wrap(t(lang, "no_emergency_contacts")), body))
    story.append(Spacer(1, 5 * mm))

    # ── 3c. Health signals ────────────────────────────────────────────
    story.append(Paragraph(_wrap(t(lang, "section_health_signals")), h2))
    hs = payload.get("health_signals") or []
    if hs:
        rows = [["Recorded", "Signal", "Value"]]
        for s in hs:
            rows.append([
                s.get("recorded_at") or dash,
                s.get("type") or dash,
                str(s.get("value", dash)),
            ])
        t_hs = Table(rows, colWidths=[55 * mm, 50 * mm, 65 * mm])
        t_hs.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        story.append(t_hs)
    else:
        story.append(Paragraph(_wrap(t(lang, "no_health_signals")), body))
    story.append(Spacer(1, 5 * mm))

    story.append(Paragraph(_wrap(t(lang, "section_what_we_dont_store")), h2))
    disc = payload["privacy_disclosures"]
    story.append(Paragraph(
        f"<b>{_wrap(t(lang, 'label_audio'))}:</b> {disc['audio']}", body,
    ))
    story.append(Paragraph(
        f"<b>{_wrap(t(lang, 'label_video'))}:</b> {disc['video']}", body,
    ))
    story.append(Paragraph(
        f"<b>{_wrap(t(lang, 'label_biometrics'))}:</b> {disc['biometrics']}", body,
    ))
    story.append(Spacer(1, 3 * mm))
    ret = disc["retention_days"]
    ret_rows = [[t(lang, "col_data_type"), t(lang, "col_retention_days")]] + [
        [k, str(v)] for k, v in ret.items()
    ]
    t_ret = Table(ret_rows, colWidths=[60 * mm, 30 * mm])
    t_ret.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTNAME", (0, 0), (-1, 0), label_font),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story.append(t_ret)
    story.append(Spacer(1, 5 * mm))

    story.append(Paragraph(_wrap(t(lang, "section_third_parties")), h2))
    proc_rows = [[
        t(lang, "col_processor"),
        t(lang, "col_purpose"),
        t(lang, "col_residency"),
    ]]
    for p in payload["third_party_processors"]:
        proc_rows.append([p["name"], p["purpose"], p["data_residency"]])
    t_proc = Table(proc_rows, colWidths=[55 * mm, 80 * mm, 35 * mm])
    t_proc.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTNAME", (0, 0), (-1, 0), label_font),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(t_proc)
    story.append(Spacer(1, 5 * mm))

    story.append(Paragraph(_wrap(t(lang, "section_your_rights")), h2))
    rights = payload["rights"]
    rights_rows = [
        [t(lang, "col_right"), t(lang, "col_how_to_exercise")],
        [t(lang, "right_access"),             rights["access"]],
        [t(lang, "right_portability"),        rights["portability"]],
        [t(lang, "right_correction"),         rights["correction"]],
        [t(lang, "right_erasure"),            rights["erasure"]],
        [t(lang, "right_consent_withdrawal"), rights["consent_withdrawal"]],
        [
            t(lang, "right_grievance_officer"),
            f"{rights['grievance_officer']['name']} — "
            f"{rights['grievance_officer']['email']} "
            f"(SLA {rights['grievance_officer']['response_sla_days']}d)",
        ],
    ]
    t_rights = Table(rights_rows, colWidths=[40 * mm, 130 * mm])
    t_rights.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTNAME", (0, 0), (0, -1), label_font),
        ("FONTNAME", (1, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(t_rights)
    story.append(Spacer(1, 5 * mm))

    story.append(Paragraph(
        f"{_wrap(t(lang, 'export_id_label'))}: {meta['data_principal_id']} "
        f"&nbsp;·&nbsp; {_wrap(t(lang, 'version_label'))} {meta['format_version']}",
        mono,
    ))

    doc.build(story)
    return buf.getvalue()


_DEVANAGARI_FONT_REGISTERED: bool = False
_DEVANAGARI_FONT_NAME = "NotoSansDevanagari"


def _ensure_devanagari_font() -> str:
    """Register the bundled Noto Sans Devanagari TTF with ReportLab.

    Idempotent — registration only happens on the first Hindi PDF
    request, then the font name is reused. If the bundled TTF is
    missing (shouldn't happen in production, but a useful guard for
    test environments), we log a warning and return 'Helvetica' so the
    PDF still renders (with garbled Hindi — visible signal in QA, not
    a 500 to the user).
    """
    global _DEVANAGARI_FONT_REGISTERED
    if _DEVANAGARI_FONT_REGISTERED:
        return _DEVANAGARI_FONT_NAME

    import logging
    from pathlib import Path
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    log = logging.getLogger(__name__)
    font_path = (
        Path(__file__).resolve().parent.parent.parent
        / "assets" / "fonts" / "NotoSansDevanagari-Regular.ttf"
    )
    if not font_path.is_file():
        log.error(
            "[DPDP-03] Devanagari font missing at %s — Hindi PDFs will "
            "render with garbled glyphs. Re-add the file from "
            "https://fonts.google.com/noto/specimen/Noto+Sans+Devanagari",
            font_path,
        )
        return "Helvetica"

    try:
        pdfmetrics.registerFont(TTFont(_DEVANAGARI_FONT_NAME, str(font_path)))
        _DEVANAGARI_FONT_REGISTERED = True
        log.info("[DPDP-03] Registered Devanagari font: %s", font_path.name)
        return _DEVANAGARI_FONT_NAME
    except Exception as e:  # noqa: BLE001 — never break PDF rendering
        log.error("[DPDP-03] Devanagari font registration failed: %s", e)
        return "Helvetica"


@router.get("/me")
async def get_my_privacy_export(
    request: Request,
    format: str = Query("json", pattern="^(json|pdf)$"),
    lang: str | None = Query(
        None,
        pattern="^(en|hi)$",
        description=(
            "Output language. 'en' or 'hi' (Hindi). When omitted, the "
            "server negotiates via the Accept-Language request header "
            "(RFC 7231 §5.3.5), falling back to 'en'. The JSON body is "
            "always returned with English keys/values; only the PDF and "
            "the `Content-Language` response header reflect the chosen "
            "locale. DPDP-04 will localise the JSON body separately."
        ),
    ),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    DPDP §11 right-of-access export of the calling user's personal data.

    Query params:
      - format=json (default): machine-readable JSON
      - format=pdf:            human-readable PDF receipt
      - lang=en | lang=hi:     explicit locale (overrides Accept-Language)

    Headers honoured:
      - Accept-Language: parsed for content negotiation when no `lang`
        query param is supplied. e.g. `Accept-Language: hi-IN,hi;q=0.9`
        will resolve to `hi`.

    Response headers:
      - Content-Language: the negotiated locale ('en' or 'hi').
      - Vary: Accept-Language (so caches treat per-locale variants as
        distinct responses).
      - X-DPDP-Export-Version: schema version of the export envelope.
    """
    # Resolve effective locale: explicit query param wins; otherwise
    # parse Accept-Language; fall back to English.
    from app.api.privacy_i18n import negotiate_language
    resolved_lang = negotiate_language(
        request.headers.get("accept-language"),
        explicit=lang,
    )

    payload = await _build_export(session, user)

    if format == "pdf":
        pdf_bytes = _render_pdf(payload, lang=resolved_lang)
        # Include lang in the filename so users downloading both
        # variants don't overwrite each other.
        lang_suffix = f"-{resolved_lang}" if resolved_lang != "en" else ""
        filename = f"nischint-dpdp-export-{user.id}{lang_suffix}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Language": resolved_lang,
                "Vary": "Accept-Language",
                "X-DPDP-Export-Version": EXPORT_VERSION,
            },
        )

    return JSONResponse(
        content=payload,
        headers={
            "Content-Disposition": (
                f'attachment; filename="nischint-dpdp-export-{user.id}.json"'
            ),
            # JSON body stays English (see DPDP-04 backlog), but signal
            # the negotiated locale so clients can decide whether to
            # auto-prompt for a localised PDF re-download.
            "Content-Language": resolved_lang,
            "Vary": "Accept-Language",
            "X-DPDP-Export-Version": EXPORT_VERSION,
        },
    )
