"""DPDP-03: Localisation strings for the privacy export PDF.

Currently supports English (`en`, default) and Hindi (`hi`). Hindi is
required for DPDP compliance — Indian regulators expect at least one
official language. Other Indian languages are easy to add later: drop
a new key into `TRANSLATIONS` and translate the strings.

Lookup contract:
  - `t(lang, key)` returns the localised string for `key` in `lang`.
  - If `lang` is unknown OR a key is missing in the target language,
    the English version is returned (graceful fallback — no broken
    PDFs in production).

Devanagari font:
  PDFs containing Hindi must use a font that supports the Devanagari
  script. We bundle `NotoSansDevanagari-Regular.ttf` (OFL-licensed,
  redistributable) at `/app/backend/assets/fonts/`. The privacy module
  registers it at first use via `reportlab.pdfbase.pdfmetrics`.
"""
from __future__ import annotations

DEFAULT_LANG = "en"
SUPPORTED_LANGS = ("en", "hi")

# When a Hindi label is missing, the renderer falls back to the
# corresponding English label. New keys: add to BOTH dicts when
# possible. If you don't have a translation yet, leave it out of the
# Hindi dict — it will fall back automatically.
TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        # Document chrome
        "doc_title": "Nischint — DPDP Personal Data Export",
        "generated_label": "Generated",
        "data_residency_label": "Data residency",
        "regulation_label": (
            "Digital Personal Data Protection Act, 2023 (India)"
        ),
        "export_date": "Export date",
        "export_id_label": "Export ID",
        "version_label": "Version",

        # Section headings — these are the six the spec asked for.
        "section_data_principal": "1. Data Principal",
        "section_right_to_access": "2. Right to Access · Data collected",
        "section_incident_timeline": "3. Incident timeline",
        "section_emergency_contacts": "4. Emergency contacts",
        "section_health_signals": "5. Health signals",
        "section_third_parties": "6. Third-party processors",
        "section_your_rights": "7. Your rights",
        "section_what_we_dont_store": "What we do NOT store",

        # Field labels (Data Principal table)
        "field_user_id": "User ID",
        "field_email": "Email",
        "field_full_name": "Full name",
        "field_phone": "Phone",
        "field_role": "Role",
        "field_account_created": "Account created",
        "field_active": "Active",
        "yes": "yes",
        "no": "no",
        "none_dash": "—",

        # Tables
        "col_category": "Category",
        "col_records": "Records",
        "col_purpose": "Purpose",
        "col_processor": "Processor",
        "col_residency": "Residency",
        "col_data_type": "Data type",
        "col_retention_days": "Retention (days)",
        "col_right": "Right",
        "col_how_to_exercise": "How to exercise",

        # Audio/Video/Biometrics labels
        "label_audio": "Audio",
        "label_video": "Video",
        "label_biometrics": "Biometrics",

        # Rights enumeration (the row labels)
        "right_access": "Access",
        "right_portability": "Portability",
        "right_correction": "Correction",
        "right_erasure": "Erasure",
        "right_consent_withdrawal": "Withdraw consent",
        "right_grievance_officer": "Grievance officer",

        # Footer / status
        "no_incidents": "No incidents recorded.",
        "no_emergency_contacts": "No emergency contacts on file.",
        "no_health_signals": "No health signals on file.",
    },
    "hi": {
        # Document chrome
        "doc_title": "निश्चिंत — डीपीडीपी व्यक्तिगत डेटा निर्यात",
        "generated_label": "बनाया गया",
        "data_residency_label": "डेटा निवास",
        "regulation_label": (
            "डिजिटल व्यक्तिगत डेटा संरक्षण अधिनियम, 2023 (भारत)"
        ),
        "export_date": "निर्यात तिथि",
        "export_id_label": "निर्यात आईडी",
        "version_label": "संस्करण",

        # Section headings
        "section_data_principal": "1. डेटा प्रिंसिपल",
        "section_right_to_access": "2. प्राप्त करने का अधिकार · एकत्रित डेटा",
        "section_incident_timeline": "3. घटना समयरेखा",
        "section_emergency_contacts": "4. आपातकालीन संपर्क",
        "section_health_signals": "5. स्वास्थ्य संकेत",
        "section_third_parties": "6. तृतीय-पक्ष प्रोसेसर",
        "section_your_rights": "7. आपके अधिकार",
        "section_what_we_dont_store": "हम क्या संग्रहीत नहीं करते",

        # Field labels
        "field_user_id": "उपयोगकर्ता आईडी",
        "field_email": "ईमेल",
        "field_full_name": "पूरा नाम",
        "field_phone": "फ़ोन",
        "field_role": "भूमिका",
        "field_account_created": "खाता बनाया गया",
        "field_active": "सक्रिय",
        "yes": "हाँ",
        "no": "नहीं",
        "none_dash": "—",

        # Tables
        "col_category": "श्रेणी",
        "col_records": "अभिलेख",
        "col_purpose": "उद्देश्य",
        "col_processor": "प्रोसेसर",
        "col_residency": "निवास",
        "col_data_type": "डेटा प्रकार",
        "col_retention_days": "अवधारण (दिन)",
        "col_right": "अधिकार",
        "col_how_to_exercise": "कैसे प्रयोग करें",

        # Audio/Video/Biometrics
        "label_audio": "ऑडियो",
        "label_video": "वीडियो",
        "label_biometrics": "बायोमेट्रिक्स",

        # Rights enumeration
        "right_access": "पहुँच",
        "right_portability": "पोर्टेबिलिटी",
        "right_correction": "सुधार",
        "right_erasure": "मिटाना",
        "right_consent_withdrawal": "सहमति वापस लेना",
        "right_grievance_officer": "शिकायत अधिकारी",

        # Footer / status
        "no_incidents": "कोई घटना दर्ज नहीं है।",
        "no_emergency_contacts": "फ़ाइल पर कोई आपातकालीन संपर्क नहीं।",
        "no_health_signals": "फ़ाइल पर कोई स्वास्थ्य संकेत नहीं।",
    },
}


def t(lang: str | None, key: str) -> str:
    """Translate `key` into `lang`. Fall back to English if missing.

    Never raises — a missing key returns `key` itself so the PDF still
    renders (and the missing label is obvious in QA).
    """
    target = (lang or DEFAULT_LANG).lower()
    if target not in TRANSLATIONS:
        target = DEFAULT_LANG
    bundle = TRANSLATIONS.get(target, {})
    if key in bundle:
        return bundle[key]
    # Fallback to English.
    en_bundle = TRANSLATIONS.get(DEFAULT_LANG, {})
    return en_bundle.get(key, key)


def negotiate_language(
    accept_language: str | None,
    explicit: str | None = None,
) -> str:
    """RFC 7231 §5.3.5 Accept-Language negotiation, bounded to
    `SUPPORTED_LANGS`.

    Precedence (highest first):
      1. `explicit` — when a user passes `?lang=hi`, we honour their
         direct choice unconditionally. Validation that the value is
         supported is the caller's job (FastAPI Query pattern handles
         this at the route layer).
      2. The highest-q-value language in `accept_language` that we
         actually support. Subtags like `hi-IN` match the primary tag
         `hi` (per the RFC's basic-filtering algorithm).
      3. `DEFAULT_LANG` (English) as the final fallback.

    Parsing is intentionally permissive — malformed headers degrade
    silently to English rather than 400-ing the request.

    Examples:
      negotiate_language('hi-IN,hi;q=0.9,en;q=0.7') → 'hi'
      negotiate_language('en-US,en;q=0.9,*;q=0.5') → 'en'
      negotiate_language('fr,de;q=0.8')           → 'en'  (none supported)
      negotiate_language(None)                    → 'en'
      negotiate_language('hi', explicit='en')     → 'en'  (explicit wins)
    """
    if explicit:
        explicit_lower = explicit.lower()
        if explicit_lower in SUPPORTED_LANGS:
            return explicit_lower

    if not accept_language:
        return DEFAULT_LANG

    # Parse each item: "<tag>[;q=<weight>]". Missing q defaults to 1.0.
    # Sort descending by quality, stable on input order to honour
    # client priority within the same q-value.
    candidates: list[tuple[float, int, str]] = []
    for idx, item in enumerate(accept_language.split(",")):
        item = item.strip()
        if not item:
            continue
        if ";" in item:
            tag, _, params = item.partition(";")
            tag = tag.strip().lower()
            q = 1.0
            for p in params.split(";"):
                p = p.strip()
                if p.startswith("q="):
                    try:
                        q = float(p[2:])
                    except ValueError:
                        q = 0.0
        else:
            tag = item.lower()
            q = 1.0
        if q <= 0:
            continue
        # Subtag stripping: "hi-IN" → "hi" so we match the primary tag.
        primary = tag.split("-", 1)[0]
        candidates.append((q, idx, primary))

    # Highest q first; ties broken by original order. Then take the
    # first supported.
    candidates.sort(key=lambda x: (-x[0], x[1]))
    for _, _, primary in candidates:
        if primary in SUPPORTED_LANGS:
            return primary

    return DEFAULT_LANG
