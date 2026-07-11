# Keyword Engine — Hinglish + Phonetic Distress Detection
#
# Supports: English, Hindi, Hinglish, phonetic variants
# Normalizes noisy speech-to-text output before matching

import re
import logging

logger = logging.getLogger(__name__)

# ── Distress Keywords (English + Hindi + Hinglish) ──
DISTRESS_KEYWORDS = [
    # English
    "help", "please help", "save me", "help me",
    "leave me", "let go", "stop", "don't touch",
    "call police", "emergency", "someone help",
    # Hindi / Hinglish
    "bachao", "madad", "madad karo", "bachao mujhe",
    "help karo", "chor do", "chhod do", "koi bachao",
    "police bulao", "mujhe bachao", "ruk", "mat karo",
    "hatao", "jane do", "mujhe jane do",
]

# Pre-compile normalized keyword set for fast lookup
_NORMALIZED_KEYWORDS: list[str] = []


def _normalize_text(text: str) -> str:
    """
    Normalize noisy transcription for phonetic matching.
    Handles: doubled vowels, common Hinglish spelling variants, punctuation.
    """
    t = text.lower().strip()
    # Remove punctuation
    t = re.sub(r"[^\w\s]", "", t)
    # Collapse doubled vowels (bachaao → bachao, madat → madat)
    t = re.sub(r"aa+", "a", t)
    t = re.sub(r"oo+", "o", t)
    t = re.sub(r"ee+", "e", t)
    t = re.sub(r"ii+", "i", t)
    t = re.sub(r"uu+", "u", t)
    # Common phonetic normalizations
    t = t.replace("chh", "ch")
    t = t.replace("kro", "karo")
    t = t.replace("kre", "kare")
    t = t.replace("bchao", "bachao")
    t = t.replace("madat", "madad")
    # Collapse multiple spaces
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _init_keywords():
    """Build normalized keyword list once."""
    global _NORMALIZED_KEYWORDS
    if not _NORMALIZED_KEYWORDS:
        _NORMALIZED_KEYWORDS = [_normalize_text(kw) for kw in DISTRESS_KEYWORDS]


def match_distress_keywords(transcript: str) -> list[str]:
    """
    Match distress keywords against a transcript.
    Returns list of matched keywords (original form).
    """
    _init_keywords()
    normalized = _normalize_text(transcript)
    matched = []
    for i, norm_kw in enumerate(_NORMALIZED_KEYWORDS):
        if norm_kw in normalized:
            matched.append(DISTRESS_KEYWORDS[i])
    return matched


def is_distress_text(transcript: str) -> tuple[bool, list[str]]:
    """
    Check if transcript contains distress keywords.
    Returns (is_distress, matched_keywords).
    """
    matched = match_distress_keywords(transcript)
    return len(matched) > 0, matched


def compute_keyword_score(matched_keywords: list[str]) -> float:
    """
    Score based on number and type of keywords matched.
    0 keywords = 0.0, 1 keyword = 0.5, 2+ keywords = 1.0
    """
    if not matched_keywords:
        return 0.0
    if len(matched_keywords) >= 2:
        return 1.0
    return 0.5
