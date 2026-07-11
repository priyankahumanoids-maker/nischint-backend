# Whisper Voice Verification Service
#
# Async worker service for cloud-level distress detection using OpenAI Whisper.
#
# Architecture:
#   1. Audio chunk arrives via API → saved to temp + queued
#   2. Background worker picks up → transcribes via Whisper
#   3. Transcript analyzed for distress patterns (semantic, not just exact match)
#   4. Confidence score computed → Safety Brain notified
#   5. Audio deleted after verification (privacy)
#
# Scoring formula:
#   confidence = keyword_score*0.35 + scream_score*0.20 + transcript_distress*0.35 + repetition*0.10
#
# Distress levels:
#   0.0–0.3  ignore
#   0.3–0.6  caution
#   0.6–0.8  high alert
#   0.8–1.0  emergency

import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.voice_distress_event import VoiceDistressEvent
from app.services.event_broadcaster import broadcaster

logger = logging.getLogger(__name__)

# Upload directory (ephemeral — deleted after processing)
UPLOAD_DIR = Path("/tmp/nischint_audio")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Max audio duration: 15 seconds
MAX_AUDIO_BYTES = 5 * 1024 * 1024  # 5 MB
AUDIO_COOLDOWN_S = 60

# ─── Distress Phrase Patterns (multi-language) ───

ENGLISH_DISTRESS = [
    "help me", "someone help", "please help", "call police", "call 911",
    "stop", "don't touch me", "leave me alone", "get away", "I'm scared",
    "please stop", "save me", "let me go", "stop following me",
    "don't hurt me", "I need help", "where am I", "take me home",
]

HINDI_DISTRESS = [
    "bachao", "madad karo", "mujhe bachao", "koi madad karo",
    "mat chhoo", "door raho", "mujhe dar lag raha hai",
    "chhod do", "rukho", "police bulao", "mujhe jane do",
    "ghar le chalo", "koi hai", "help karo",
]

HINGLISH_DISTRESS = [
    "please bachao", "koi help karo", "stop yaar", "madad karo please",
    "mujhe leave karo", "please door raho", "help bachao",
]

ALL_DISTRESS_PHRASES = ENGLISH_DISTRESS + HINDI_DISTRESS + HINGLISH_DISTRESS

# Signal weights for phrase categories
PHRASE_WEIGHTS = {
    "help_phrases": 3,       # "help me", "someone help", "bachao"
    "fear_language": 2,       # "I'm scared", "dar lag raha hai"
    "aggressive_words": 2,    # "don't touch", "stop", "leave me"
    "repetition": 1,          # repeated short phrases
    "shouting_tag": 2,        # exclamation marks, ALL CAPS in transcript
}

# Category patterns
HELP_PATTERNS = re.compile(
    r"(help|bachao|madad|save me|police|911|koi hai|someone)", re.IGNORECASE
)
FEAR_PATTERNS = re.compile(
    r"(scared|fear|dar|afraid|frightened|terrif|where am i|ghar le)", re.IGNORECASE
)
AGGRESSIVE_PATTERNS = re.compile(
    r"(stop|don.?t touch|leave.*alone|get away|chhod|mat chhoo|door raho|rukho|let me go|don.?t hurt|following)", re.IGNORECASE
)
REPETITION_PATTERN = re.compile(r"(\b\w+\b)(?:\s+\1){2,}", re.IGNORECASE)


def analyze_transcript(transcript: str) -> dict:
    """
    Semantic distress analysis of a Whisper transcript.
    Returns: {score, phrases_found, categories, details}
    """
    if not transcript or not transcript.strip():
        return {"score": 0.0, "phrases_found": [], "categories": {}, "details": {}}

    text = transcript.strip().lower()
    phrases_found = []
    category_scores = {}

    # 1. Help phrases (+3)
    help_matches = HELP_PATTERNS.findall(text)
    if help_matches:
        category_scores["help_phrases"] = min(1.0, len(help_matches) / 2.0)
        phrases_found.extend(help_matches[:5])

    # 2. Fear language (+2)
    fear_matches = FEAR_PATTERNS.findall(text)
    if fear_matches:
        category_scores["fear_language"] = min(1.0, len(fear_matches) / 2.0)
        phrases_found.extend(fear_matches[:3])

    # 3. Aggressive / command words (+2)
    aggro_matches = AGGRESSIVE_PATTERNS.findall(text)
    if aggro_matches:
        category_scores["aggressive_words"] = min(1.0, len(aggro_matches) / 2.0)
        phrases_found.extend(aggro_matches[:3])

    # 4. Repetition detection (+1) — "stop stop stop", "no no no"
    rep_matches = REPETITION_PATTERN.findall(text)
    if rep_matches:
        category_scores["repetition"] = min(1.0, len(rep_matches))
        phrases_found.extend([f"{m} (repeated)" for m in rep_matches[:2]])

    # 5. Shouting markers (+2) — check for ALL CAPS words or exclamation emphasis
    upper_words = [w for w in transcript.split() if w.isupper() and len(w) > 2]
    exclaim_count = transcript.count("!")
    if upper_words or exclaim_count > 1:
        category_scores["shouting_tag"] = min(1.0, (len(upper_words) + exclaim_count) / 3.0)

    # 6. Exact phrase matching (bonus)
    exact_matches = []
    for phrase in ALL_DISTRESS_PHRASES:
        if phrase.lower() in text:
            exact_matches.append(phrase)
    if exact_matches:
        # Boost score for exact phrase matches
        category_scores["exact_phrases"] = min(1.0, len(exact_matches) / 2.0)
        phrases_found.extend(exact_matches[:5])

    # Weighted composite score
    total_weight = sum(PHRASE_WEIGHTS.get(cat, 1) for cat in category_scores)
    if total_weight == 0:
        return {"score": 0.0, "phrases_found": [], "categories": {}, "details": {}}

    max_possible = sum(PHRASE_WEIGHTS.values()) + 3  # +3 for exact phrases
    weighted_sum = sum(
        category_scores[cat] * PHRASE_WEIGHTS.get(cat, 1)
        for cat in category_scores
    )
    transcript_score = min(1.0, weighted_sum / max_possible)

    return {
        "score": round(transcript_score, 3),
        "phrases_found": list(set(phrases_found))[:10],
        "categories": category_scores,
        "details": {
            "help_matches": len(help_matches) if help_matches else 0,
            "fear_matches": len(fear_matches) if fear_matches else 0,
            "aggressive_matches": len(aggro_matches) if aggro_matches else 0,
            "repetitions": len(rep_matches) if rep_matches else 0,
            "exact_phrases": len(exact_matches),
            "shouting_markers": len(upper_words) + exclaim_count if 'upper_words' in dir() else 0,
        },
    }


def compute_whisper_confidence(
    keyword_score: float,
    scream_score: float,
    transcript_distress_score: float,
    repetition_score: float,
) -> float:
    """
    Compute final voice distress confidence.
    Formula: keyword*0.35 + scream*0.20 + transcript_distress*0.35 + repetition*0.10
    """
    confidence = (
        keyword_score * 0.35 +
        scream_score * 0.20 +
        transcript_distress_score * 0.35 +
        repetition_score * 0.10
    )
    return round(min(1.0, max(0.0, confidence)), 3)


async def transcribe_audio(audio_path: str) -> dict:
    """
    Transcribe audio using OpenAI Whisper via Emergent LLM key.
    Returns: {text, segments, language, duration}
    """
    from emergentintegrations.llm.openai import OpenAISpeechToText
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise ValueError("EMERGENT_LLM_KEY not configured")

    stt = OpenAISpeechToText(api_key=api_key)

    try:
        with open(audio_path, "rb") as audio_file:
            response = await stt.transcribe(
                file=audio_file,
                model="whisper-1",
                response_format="verbose_json",
                language="en",
                prompt="This audio may contain distress signals, calls for help, screaming, or whispered pleas. Transcribe exactly what is said.",
                temperature=0.0,
                timestamp_granularities=["segment"],
            )

        segments = []
        if hasattr(response, 'segments') and response.segments:
            for s in response.segments:
                if isinstance(s, dict):
                    segments.append({"start": s.get("start"), "end": s.get("end"), "text": s.get("text", "")})
                else:
                    segments.append({"start": getattr(s, 'start', None), "end": getattr(s, 'end', None), "text": getattr(s, 'text', "")})

        return {
            "text": response.text or "",
            "segments": segments,
            "language": getattr(response, 'language', 'en'),
            "duration": getattr(response, 'duration', None),
        }
    except Exception as e:
        logger.error(f"Whisper transcription failed: {e}")
        raise


async def verify_voice_event(session: AsyncSession, event_id: str, audio_path: str | None = None) -> dict:
    """
    Full Whisper verification pipeline for a voice distress event.

    1. Update status to 'processing'
    2. Transcribe audio via Whisper
    3. Analyze transcript for distress patterns
    4. Compute confidence score
    5. Update event record
    6. Feed to Safety Brain
    7. Broadcast updated SSE
    8. Delete audio (privacy)
    """
    # Fetch event
    result = await session.execute(
        select(VoiceDistressEvent).where(VoiceDistressEvent.id == uuid.UUID(event_id))
    )
    event = result.scalar_one_or_none()
    if not event:
        return {"error": "Voice event not found"}

    # Update status
    event.verification_status = "processing"
    await session.commit()

    try:
        # Step 1: Transcribe
        if audio_path and os.path.exists(audio_path):
            whisper_result = await transcribe_audio(audio_path)
            transcript = whisper_result.get("text", "")
        else:
            # No audio — synthesize from existing keywords for re-verification
            kw_list = event.keywords if isinstance(event.keywords, list) else []
            transcript = " ".join(kw_list) if kw_list else ""

        # Step 2: Analyze transcript
        analysis = analyze_transcript(transcript)

        # Step 3: Compute confidence
        # Keyword score from on-device detection
        kw_list = event.keywords if isinstance(event.keywords, list) else []
        keyword_score = min(1.0, len(kw_list) / 2.0) if kw_list else 0.0
        scream_score = 0.8 if event.scream_detected else 0.0
        repetition_score = 1.0 if event.repeated_detection else 0.0

        confidence = compute_whisper_confidence(
            keyword_score=keyword_score,
            scream_score=scream_score,
            transcript_distress_score=analysis["score"],
            repetition_score=repetition_score,
        )

        # Step 4: Update event
        event.whisper_verified = confidence >= 0.3
        event.whisper_transcript = transcript[:500] if transcript else None
        event.whisper_confidence = confidence
        event.verification_status = "verified"
        event.distress_phrases_found = analysis["phrases_found"]
        await session.commit()

        # Step 5: Feed verified signal to Safety Brain
        if confidence >= 0.3:
            try:
                from app.services.safety_brain_service import on_voice_distress
                # Use the whisper-verified confidence (higher weight than on-device)
                boosted_score = min(1.0, confidence * 1.2)  # 20% boost for verified signals
                await on_voice_distress(session, str(event.user_id), boosted_score, event.lat, event.lng)
            except Exception as e:
                logger.error(f"Safety Brain voice verification hook failed: {e}")

        # Step 6: Broadcast verification result SSE
        sse_data = {
            "event_id": event_id,
            "user_id": str(event.user_id),
            "verification_status": "verified",
            "transcript": transcript[:200] if transcript else None,
            "whisper_confidence": confidence,
            "distress_detected": confidence >= 0.3,
            "phrases_found": analysis["phrases_found"],
            "distress_level": (
                "emergency" if confidence >= 0.8 else
                "high_alert" if confidence >= 0.6 else
                "caution" if confidence >= 0.3 else "ignore"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await broadcaster.broadcast_to_user(str(event.user_id), "voice_verification_complete", sse_data)
        await broadcaster.broadcast_to_operators("voice_verification_complete", sse_data)

        logger.warning(
            f"Whisper verified: event={event_id}, confidence={confidence:.2f}, "
            f"distress={'YES' if confidence >= 0.3 else 'NO'}, "
            f"phrases={analysis['phrases_found'][:3]}"
        )

        return {
            "event_id": event_id,
            "status": "verified",
            "transcript": transcript[:200] if transcript else None,
            "whisper_confidence": confidence,
            "distress_detected": confidence >= 0.3,
            "distress_level": (
                "emergency" if confidence >= 0.8 else
                "high_alert" if confidence >= 0.6 else
                "caution" if confidence >= 0.3 else "ignore"
            ),
            "phrases_found": analysis["phrases_found"],
            "analysis": analysis["categories"],
        }

    except Exception as e:
        logger.error(f"Whisper verification failed: event={event_id}, error={e}")
        event.verification_status = "failed"
        await session.commit()
        return {"event_id": event_id, "status": "failed", "error": str(e)}

    finally:
        # Step 7: Delete audio (privacy safeguard)
        if audio_path and os.path.exists(audio_path):
            try:
                os.remove(audio_path)
                logger.info(f"Audio deleted (privacy): {audio_path}")
            except OSError:
                pass


async def queue_whisper_verification(session: AsyncSession, event_id: str, audio_path: str | None = None):
    """
    Queue Whisper verification as a background task.
    Non-blocking — returns immediately.
    """
    # Launch as background task
    asyncio.create_task(_run_verification(event_id, audio_path))
    logger.info(f"Whisper verification queued: event={event_id}")


async def _run_verification(event_id: str, audio_path: str | None):
    """Background task that runs Whisper verification with its own DB session."""
    await asyncio.sleep(0.5)  # Small delay to let the original request complete
    try:
        from app.db.session import async_session
        async with async_session() as session:
            await verify_voice_event(session, event_id, audio_path)
    except Exception as e:
        logger.error(f"Background Whisper verification failed: event={event_id}, error={e}")


async def get_verification_status(session: AsyncSession, event_id: str) -> dict:
    """Get verification status and result for a voice distress event."""
    result = await session.execute(
        select(VoiceDistressEvent).where(VoiceDistressEvent.id == uuid.UUID(event_id))
    )
    event = result.scalar_one_or_none()
    if not event:
        return {"error": "Voice event not found"}

    return {
        "event_id": str(event.id),
        "user_id": str(event.user_id),
        "distress_score": event.distress_score,
        "verification_status": event.verification_status,
        "whisper_verified": event.whisper_verified,
        "whisper_confidence": event.whisper_confidence,
        "transcript": event.whisper_transcript,
        "distress_detected": event.whisper_confidence >= 0.3 if event.whisper_confidence else None,
        "distress_level": (
            "emergency" if (event.whisper_confidence or 0) >= 0.8 else
            "high_alert" if (event.whisper_confidence or 0) >= 0.6 else
            "caution" if (event.whisper_confidence or 0) >= 0.3 else "ignore"
        ) if event.whisper_confidence is not None else None,
        "phrases_found": event.distress_phrases_found,
        "status": event.status,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }
