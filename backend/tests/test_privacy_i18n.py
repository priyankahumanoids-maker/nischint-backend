"""Unit tests for the Accept-Language negotiation in privacy_i18n.

The helper handles content negotiation for the DPDP §11 export endpoint.
These tests pin the parser behaviour so RFC 7231 §5.3.5 compliance
doesn't regress silently.
"""
from __future__ import annotations

import pytest

from app.api.privacy_i18n import (
    DEFAULT_LANG,
    SUPPORTED_LANGS,
    negotiate_language,
    t,
)


# ── Explicit-wins precedence ─────────────────────────────────────────


def test_explicit_overrides_accept_language():
    assert negotiate_language("hi-IN,hi;q=0.9", explicit="en") == "en"
    assert negotiate_language("en,en-US;q=0.9", explicit="hi") == "hi"


def test_explicit_unsupported_falls_through_to_header():
    # The route layer's regex validates the query param to en|hi, but
    # if the helper is ever called with an unsupported explicit (e.g.
    # programmatic caller), it should ignore it rather than break.
    assert negotiate_language("hi-IN", explicit="fr") == "hi"
    assert negotiate_language(None, explicit="fr") == DEFAULT_LANG


# ── Accept-Language parsing ──────────────────────────────────────────


@pytest.mark.parametrize("header,expected", [
    # Direct primary tag.
    ("hi", "hi"),
    ("en", "en"),
    # Subtags collapse to primary.
    ("hi-IN", "hi"),
    ("en-US", "en"),
    # Multi-tag, highest q wins.
    ("en-US,en;q=0.9,hi;q=0.5", "en"),
    ("hi-IN,hi;q=0.95,en;q=0.7", "hi"),
    # Equal q-values: client order is preserved.
    ("en;q=0.8,hi;q=0.8", "en"),
    ("hi;q=0.8,en;q=0.8", "hi"),
    # Wildcards and zero-q are skipped.
    ("*;q=1.0", DEFAULT_LANG),
    ("en;q=0,hi;q=0.8", "hi"),
    # Unsupported languages → fallback to English.
    ("fr,de;q=0.9", DEFAULT_LANG),
    ("ja-JP,zh-CN;q=0.7", DEFAULT_LANG),
    # Missing/empty header.
    (None, DEFAULT_LANG),
    ("", DEFAULT_LANG),
    # Malformed input degrades to English instead of raising.
    ("garbage;;;", DEFAULT_LANG),
    ("hi;q=invalid", DEFAULT_LANG),  # invalid q → 0 → skipped
    # Mixed valid + garbage: valid entries still resolve.
    ("garbage,hi", "hi"),
    # Whitespace tolerance.
    ("  hi-IN ,  en;q=0.5  ", "hi"),
])
def test_accept_language_parsing(header, expected):
    assert negotiate_language(header) == expected


def test_supported_langs_pinned():
    """Lock the supported-language set so silent additions don't break
    the i18n contract (each new lang requires a translation bundle)."""
    assert SUPPORTED_LANGS == ("en", "hi")
    assert DEFAULT_LANG == "en"


# ── t() fallback behaviour (existing, kept for completeness) ─────────


def test_t_falls_back_to_english_for_missing_hindi_key():
    # If a key isn't in the 'hi' bundle, English is returned.
    # Use a fake key that we know isn't translated.
    assert t("hi", "__definitely_not_a_real_key__") == "__definitely_not_a_real_key__"


def test_t_returns_english_for_unknown_lang():
    assert t("zz", "export_date") == "Export date"


def test_t_returns_hindi_when_key_present():
    assert t("hi", "export_date") == "निर्यात तिथि"
