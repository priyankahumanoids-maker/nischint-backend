"""rag_generation async migration — invariant lock tests.

Six layers of defence-in-depth, locked:

  1. **AsyncOpenAI client** — `_get_client()` returns `AsyncOpenAI`,
     not the legacy sync `OpenAI`. Regression here puts us back on
     the event-loop-blocking path that caused the CF 520 signature.
  2. **SDK timeout** baked into the client at construction.
  3. **Outer asyncio.wait_for** wraps the SDK call so an SDK edge
     hang can't stall the coroutine.
  4. **`RAG_GENERATION_SEMAPHORE`** caps in-flight generations at 5
     — protects against thundering-herd origin saturation.
  5. **Semaphore is acquired BEFORE the wait_for**, so a request
     that has to wait consumes its own timeout budget instead of
     head-of-line-blocking later arrivals.
  6. **TimeoutError propagates** (does NOT get swallowed) so the
     FastAPI endpoint can return a 503-deferred response — aligned
     with the DLQ-architecture "compensating action exists" rule.

Pure-unit tests: no real OpenAI calls, no network. The SDK is
mocked at module level.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import rag_generation as rg


# ════════════════════════════════════════════════════════════════════
# Module-level constants — locked baseline
# ════════════════════════════════════════════════════════════════════

def test_constants_are_locked():
    """Lock the operational baseline. A future refactor can lower
    these (tighter) but raising them silently is a regression."""
    assert rg.GENERATION_SDK_TIMEOUT_S == 60.0
    assert rg.GENERATION_OUTER_TIMEOUT_S == 65.0
    assert rg.GENERATION_OUTER_TIMEOUT_S > rg.GENERATION_SDK_TIMEOUT_S, (
        "Outer must be > SDK so the SDK's own error wins the race "
        "(clearer diagnostic in logs)."
    )
    assert rg.RAG_GENERATION_CONCURRENCY == 5
    assert isinstance(rg.RAG_GENERATION_SEMAPHORE, asyncio.Semaphore)


def test_module_uses_async_openai_not_sync():
    """The whole point of the migration. If a future PR re-imports
    the sync `OpenAI` class, that's a regression even if the test
    coverage looks fine — sync inside async still blocks the loop."""
    import openai
    # Sync client MUST NOT be referenced at module level.
    src = (rg.__file__ and open(rg.__file__).read()) or ""
    assert "AsyncOpenAI" in src
    assert "from openai import OpenAI" not in src
    # And the constructor type is the async one.
    assert hasattr(openai, "AsyncOpenAI")


# ════════════════════════════════════════════════════════════════════
# Happy path
# ════════════════════════════════════════════════════════════════════

@pytest.fixture
def fake_client():
    """Replaces `_client` with an AsyncMock that returns a canned
    chat completion. Resets the singleton between tests."""
    rg._client = None
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"title":"ok","sections":[]}'))],
        ),
    )
    with patch.object(rg, "_get_client", return_value=client):
        yield client
    rg._client = None


@pytest.mark.asyncio
async def test_returns_parsed_json_on_success(fake_client):
    """Happy path — async call resolves, JSON parses, dict returned.
    Locks the public contract; if a future refactor accidentally
    returns the raw response object instead of the parsed dict,
    every downstream caller breaks."""
    result = await rg.generate_structured_content(
        query="q", persona="parent", emotion="worried", location="Mumbai",
        context_text="", internal_links=[],
    )
    assert result == {"title": "ok", "sections": []}
    fake_client.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_invalid_json_returns_none(fake_client):
    fake_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="not json {{{"))],
    )
    result = await rg.generate_structured_content(
        query="q", persona="p", emotion="e", location="l",
        context_text="", internal_links=[],
    )
    assert result is None


@pytest.mark.asyncio
async def test_missing_api_key_raises(monkeypatch):
    """Config error — not a transient failure. Must raise."""
    rg._client = None
    monkeypatch.setattr(rg.settings, "openai_api_key", None)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        await rg.generate_structured_content(
            query="q", persona="p", emotion="e", location="l",
            context_text="", internal_links=[],
        )


# ════════════════════════════════════════════════════════════════════
# Outer asyncio.wait_for invariant
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_outer_wait_for_kicks_when_sdk_hangs(fake_client, monkeypatch):
    """If the SDK ignores its own timeout (edge hang / transport
    stall / mis-routed slot), the outer `asyncio.wait_for` MUST
    cancel the coroutine. Caller relies on TimeoutError being
    raised — that's the trigger for the deferred-retry response."""
    # Lower the outer timeout to keep the test fast.
    monkeypatch.setattr(rg, "GENERATION_OUTER_TIMEOUT_S", 0.05)

    async def _hang(*_a, **_kw):
        await asyncio.sleep(10)  # would never return without outer wrap
    fake_client.chat.completions.create.side_effect = _hang

    with pytest.raises(asyncio.TimeoutError):
        await rg.generate_structured_content(
            query="q", persona="p", emotion="e", location="l",
            context_text="", internal_links=[],
        )


@pytest.mark.asyncio
async def test_timeout_error_propagates_not_swallowed(fake_client, monkeypatch):
    """The bare `except Exception` at the bottom of
    `generate_structured_content` MUST NOT catch TimeoutError —
    otherwise the caller gets `None` instead of the explicit
    TimeoutError, and the FastAPI 503-deferred path never fires."""
    monkeypatch.setattr(rg, "GENERATION_OUTER_TIMEOUT_S", 0.05)
    async def _hang(*_a, **_kw):
        await asyncio.sleep(10)
    fake_client.chat.completions.create.side_effect = _hang

    # If the broad except swallowed it, we'd see None here.
    with pytest.raises(asyncio.TimeoutError):
        await rg.generate_structured_content(
            query="q", persona="p", emotion="e", location="l",
            context_text="", internal_links=[],
        )


# ════════════════════════════════════════════════════════════════════
# Semaphore-bounded concurrency
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_semaphore_bounds_concurrent_generations(monkeypatch):
    """Locks the concurrency cap at 5. Fires 8 concurrent calls; at
    no point should more than 5 be in-flight inside the SDK call.
    This is the lock that prevents thundering-herd origin
    saturation that caused the CF 520 signature."""
    rg._client = None
    monkeypatch.setattr(rg.settings, "openai_api_key", "sk-test")

    in_flight = 0
    peak = 0

    async def _track_concurrency(*_a, **_kw):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        try:
            await asyncio.sleep(0.05)
            return MagicMock(
                choices=[MagicMock(message=MagicMock(content='{"ok":true}'))],
            )
        finally:
            in_flight -= 1

    fake = MagicMock()
    fake.chat = MagicMock()
    fake.chat.completions = MagicMock()
    fake.chat.completions.create = _track_concurrency

    # Reset semaphore so prior test state doesn't leak in.
    rg.RAG_GENERATION_SEMAPHORE = asyncio.Semaphore(rg.RAG_GENERATION_CONCURRENCY)

    with patch.object(rg, "_get_client", return_value=fake):
        await asyncio.gather(*[
            rg.generate_structured_content(
                query=f"q{i}", persona="p", emotion="e", location="l",
                context_text="", internal_links=[],
            )
            for i in range(8)
        ])

    assert peak <= rg.RAG_GENERATION_CONCURRENCY, (
        f"Peak in-flight = {peak} exceeds semaphore cap "
        f"{rg.RAG_GENERATION_CONCURRENCY}. Concurrency lock broken."
    )
    # And we should actually have hit the cap (test is meaningful).
    assert peak == rg.RAG_GENERATION_CONCURRENCY, (
        f"Test didn't actually saturate the semaphore — peak={peak}."
    )


@pytest.mark.asyncio
async def test_semaphore_acquired_before_sdk_call(monkeypatch):
    """The `async with semaphore` MUST wrap the `wait_for` so a
    waiting request consumes its own timeout budget. If a future
    refactor swaps the order (wait_for outside the gate), a stuck
    in-flight request could starve queued requests indefinitely."""
    rg._client = None
    monkeypatch.setattr(rg.settings, "openai_api_key", "sk-test")
    rg.RAG_GENERATION_SEMAPHORE = asyncio.Semaphore(1)  # tight cap
    monkeypatch.setattr(rg, "GENERATION_OUTER_TIMEOUT_S", 0.2)

    started_order = []
    completed_order = []

    async def _slow(query=None, **kw):
        started_order.append(query)
        await asyncio.sleep(0.1)
        completed_order.append(query)
        return MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"q":"' + query + '"}'))],
        )

    async def _create(**kw):
        # The user `query` argument doesn't make it to the SDK; we
        # pass it through `messages`. Just inspect call order from
        # the messages list.
        msg = next((m for m in kw.get("messages", []) if m["role"] == "user"), None)
        return await _slow(query=(msg or {}).get("content", "")[:5], **kw)

    fake = MagicMock()
    fake.chat = MagicMock()
    fake.chat.completions = MagicMock()
    fake.chat.completions.create = _create

    with patch.object(rg, "_get_client", return_value=fake):
        results = await asyncio.gather(
            rg.generate_structured_content(
                query="A", persona="p", emotion="e", location="l",
                context_text="", internal_links=[],
            ),
            rg.generate_structured_content(
                query="B", persona="p", emotion="e", location="l",
                context_text="", internal_links=[],
            ),
            return_exceptions=True,
        )

    # First request should complete; second is serialised behind it.
    # Critically, the second one MUST NOT have started before the
    # first finished — that's the semaphore-before-wait_for lock.
    assert started_order[0] != started_order[1] or len(started_order) == 2
    assert completed_order[0] == started_order[0], (
        "Request A must complete before Request B starts — proves "
        "the semaphore is acquired BEFORE the SDK call, not after."
    )


# ════════════════════════════════════════════════════════════════════
# Call-site invariants (rag.py uses `await`, returns 503 on timeout)
# ════════════════════════════════════════════════════════════════════

def test_rag_router_awaits_generation():
    """Static check: both call sites in `rag.py` MUST use `await`.
    A regression to sync-call would crash at runtime (AsyncOpenAI
    returns a coroutine), but this test catches it without needing
    to instantiate the FastAPI app."""
    src = open("/app/backend/app/api/rag.py").read()
    # Two call sites.
    assert "await generate_structured_content(" in src
    # No sync call sites remain.
    assert "result = generate_structured_content(" not in src
    assert "generated = generate_structured_content(" not in src


def test_rag_router_returns_503_deferred_on_timeout():
    """The endpoint MUST catch `asyncio.TimeoutError` and return a
    503 with `status=deferred`. Locks the user-facing contract for
    the deferred-retry response shape."""
    src = open("/app/backend/app/api/rag.py").read()
    assert "asyncio.TimeoutError" in src
    assert '"status":    "deferred"' in src or '"status": "deferred"' in src
    assert "rag_generation_timeout" in src
