"""
NISCHINT RAG Generation Service — Structured content generation using OpenAI GPT.
Produces high-conversion blog structures with emotional hooks, SEO, and internal links.

Async semantics — locked invariants
-----------------------------------
This module BLOCKED the asyncio event loop pre-2026-02. The fix is
three layers of defence-in-depth so a slow / hung / mis-routed LLM
call can never again take down unrelated coroutines:

  1. `AsyncOpenAI` instead of `OpenAI` — the network wait yields the
     event loop back to the scheduler instead of pinning it.
  2. SDK-level `timeout=` on the client — protects against
     well-behaved-but-slow upstream slots.
  3. Outer `asyncio.wait_for(..., timeout=...)` — protects against
     SDK edge hangs, transport stalls, or any code path inside the
     SDK that ignores its own timeout.

Concurrency cap — locked at `RAG_GENERATION_SEMAPHORE = Semaphore(5)`.
Without this, a burst of simultaneous `/api/rag/generate` requests
can saturate origin workers, starve the event loop's other tasks,
and cause the same Cloudflare 520 signature this fix was written to
eliminate. 5 in-flight generations is conservative — operator chip
in a future PR will surface saturation pressure to ops.
"""
import asyncio
import json
import logging
from typing import Optional

from openai import AsyncOpenAI
from app.core.config import settings

logger = logging.getLogger(__name__)

_client: Optional[AsyncOpenAI] = None

GENERATION_MODEL = "gpt-4o-mini"

# ── Locked operational constants ─────────────────────────────────
# SDK timeout — well-behaved upstream slot upper bound.
# Outer asyncio timeout — slightly higher than SDK so SDK's own
# error is preferred when both could fire (clearer diagnostic in
# logs: "openai timed out" vs "asyncio cancelled").
GENERATION_SDK_TIMEOUT_S = 60.0
GENERATION_OUTER_TIMEOUT_S = 65.0

# Concurrency cap on in-flight LLM generations. A semaphore acquired
# at the FastAPI boundary; never inside the SDK call itself.
# Module-level singleton so every endpoint shares the same gate.
RAG_GENERATION_CONCURRENCY = 5
RAG_GENERATION_SEMAPHORE = asyncio.Semaphore(RAG_GENERATION_CONCURRENCY)

SYSTEM_PROMPT = """You are an expert in human psychology, safety technology, and SEO content strategy.
You work for NISCHINT — India's first AI-powered urban safety platform that protects women, children, and families.

Your job is to generate HIGH-CONVERSION structured blog content that:
- Starts with an emotional hook that connects immediately
- Uses real-life relatable scenarios from Indian context
- Builds the emotional arc: fear → clarity → control → action
- Introduces NISCHINT naturally as the solution (never forced)
- Includes internal linking opportunities to existing content
- Follows SEO best practices

IMPORTANT: Output ONLY valid JSON. No markdown, no code blocks, no extra text."""


def _get_client() -> Optional[AsyncOpenAI]:
    """Lazy singleton — keeps `AsyncOpenAI` instantiation outside the
    request hot path. SDK timeout is baked in at construction time."""
    global _client
    if _client is None:
        if not settings.openai_api_key:
            return None
        _client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=GENERATION_SDK_TIMEOUT_S,
        )
    return _client


async def generate_structured_content(
    query: str,
    persona: str,
    emotion: str,
    location: str,
    context_text: str,
    internal_links: list[dict],
) -> Optional[dict]:
    """Generate structured blog content using RAG context.

    Async — never blocks the event loop. Bounded by
    `RAG_GENERATION_SEMAPHORE` so a burst of concurrent generations
    can never saturate origin workers. Outer `asyncio.wait_for`
    enforces an upper bound regardless of the SDK's own timeout
    behaviour.

    Raises:
        RuntimeError: OPENAI_API_KEY not configured (config error,
            not a transient failure).
        asyncio.TimeoutError: total wall-clock exceeded
            `GENERATION_OUTER_TIMEOUT_S` — caller decides whether to
            return `{"status": "deferred", "retryable": true}` or
            propagate to the user. Same shape callers handled before
            the async migration; just a different exception class.
    """
    client = _get_client()
    if client is None:
        raise RuntimeError("OPENAI_API_KEY not configured for generation")

    # Build the link reference for the prompt
    link_refs = ""
    if internal_links:
        link_items = []
        for link in internal_links[:5]:
            link_items.append(f'- "{link["title"]}" (blog_id: {link["blog_id"]})')
        link_refs = "\n".join(link_items)

    user_prompt = f"""User Context:
- Persona: {persona}
- Emotion: {emotion}
- Query: "{query}"
- Location: {location}

Retrieved Knowledge Context:
{context_text[:4000]}

Existing Blog Posts for Internal Linking:
{link_refs or "No existing posts found"}

Task:
Generate a HIGH-CONVERSION structured blog based on the query and context above.

Rules:
- Start with an emotional hook that a {persona} feeling {emotion} would connect with
- Use a real-life relatable scenario set in {location}
- Build the arc: fear → clarity → control → action
- Introduce NISCHINT naturally as the technology solution
- Reference existing blog posts as internal links where relevant
- Keep Indian cultural context
- Generate 3-5 content sections

Output this EXACT JSON structure:
{{
  "title": "SEO-optimized blog title (50-60 chars)",
  "hook": "Opening emotional hook paragraph (2-3 sentences)",
  "sections": [
    {{
      "type": "problem",
      "heading": "Section heading",
      "content": "Section content (2-3 paragraphs)"
    }},
    {{
      "type": "scenario",
      "heading": "Section heading",
      "content": "Real-life scenario content"
    }},
    {{
      "type": "data",
      "heading": "Section heading",
      "content": "Statistics and facts supporting the narrative"
    }},
    {{
      "type": "solution",
      "heading": "Section heading",
      "content": "How NISCHINT addresses this"
    }},
    {{
      "type": "action",
      "heading": "Section heading",
      "content": "What the reader should do next"
    }}
  ],
  "cta": "Call-to-action text (compelling, specific)",
  "internal_links": [
    {{
      "blog_id": "existing blog_id from the list above",
      "anchor": "suggested anchor text for the link"
    }}
  ],
  "seo": {{
    "meta_title": "SEO meta title (50-60 chars)",
    "meta_description": "SEO meta description (150-160 chars)",
    "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"]
  }},
  "intent_analysis": {{
    "intent_level": "informational|navigational|transactional",
    "urgency": "low|medium|high|critical",
    "scenario_type": "awareness|prevention|response|recovery"
  }}
}}"""

    try:
        # Semaphore-bounded + outer asyncio timeout. Order matters:
        # acquire the gate FIRST so a request that has to wait
        # consumes wall-clock against its OWN timeout budget — fair-
        # queueing instead of head-of-line-blocking.
        async with RAG_GENERATION_SEMAPHORE:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=GENERATION_MODEL,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.7,
                    max_tokens=3000,
                    response_format={"type": "json_object"},
                ),
                timeout=GENERATION_OUTER_TIMEOUT_S,
            )

        raw = response.choices[0].message.content
        result = json.loads(raw)

        logger.info(f"Generated content for query='{query[:50]}', persona={persona}, sections={len(result.get('sections', []))}")
        return result

    except asyncio.TimeoutError:
        # Outer asyncio.wait_for — SDK didn't release the coroutine
        # within `GENERATION_OUTER_TIMEOUT_S`. Re-raise so the caller
        # (FastAPI endpoint) can return a deferred-retry response.
        # Distinct from SDK's own timeout for diagnostic clarity.
        logger.warning(
            "rag_generation_outer_timeout",
            extra={
                "event":     "rag_generation_outer_timeout",
                "query":     query[:80],
                "timeout_s": GENERATION_OUTER_TIMEOUT_S,
            },
        )
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Generation returned invalid JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"Content generation failed: {e}")
        raise
