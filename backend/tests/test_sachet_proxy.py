"""REL-07 — Tests for the SACHET proxy switch.

Locks down the `effective_url(path)` resolution:
  • No `SACHET_PROXY_URL` env → upstream is `sachet.ndma.gov.in`.
  • Env set                  → upstream is the proxy origin + path.
  • Path normalisation       → leading slash handled, trailing slash
                              on the proxy stripped.
  • `_fetch_feed_uncached`   → uses the proxy URL when set.

We don't try to assert on the worker's behaviour itself — that's
JavaScript living in CF's runtime and out of scope for pytest.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def fresh_sachet(monkeypatch):
    """Reload the module so module-level constants reflect env state.

    `SACHET_PROXY_URL` is read inside `_proxy_origin()` (per-request,
    not at import) so a reload isn't strictly necessary — but it makes
    these tests robust against future caching tweaks.
    """
    import app.services.external_signals.sachet_provider as mod
    return mod


def test_no_proxy_env_uses_upstream(monkeypatch, fresh_sachet):
    monkeypatch.delenv("SACHET_PROXY_URL", raising=False)
    assert fresh_sachet.effective_url() == (
        "https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml"
    )


def test_proxy_env_replaces_origin(monkeypatch, fresh_sachet):
    monkeypatch.setenv(
        "SACHET_PROXY_URL",
        "https://sachet-proxy.example.workers.dev",
    )
    assert fresh_sachet.effective_url() == (
        "https://sachet-proxy.example.workers.dev"
        "/cap_public_website/rss/rss_india.xml"
    )


def test_proxy_env_trailing_slash_stripped(monkeypatch, fresh_sachet):
    """A pasted-in env value with a trailing slash must not produce
    `//cap_public_website/...`."""
    monkeypatch.setenv(
        "SACHET_PROXY_URL",
        "https://sachet-proxy.example.workers.dev/",
    )
    url = fresh_sachet.effective_url()
    assert url.startswith("https://sachet-proxy.example.workers.dev/cap_public_website/")
    assert "//cap_public_website" not in url.replace("https://", "")


def test_effective_url_path_param_is_used(monkeypatch, fresh_sachet):
    """Any SACHET path can be proxied — not just the RSS feed."""
    monkeypatch.setenv(
        "SACHET_PROXY_URL",
        "https://sachet-proxy.example.workers.dev",
    )
    url = fresh_sachet.effective_url(
        "/cap_public_website/FetchAllAlertDetails",
    )
    assert url == (
        "https://sachet-proxy.example.workers.dev"
        "/cap_public_website/FetchAllAlertDetails"
    )


def test_effective_url_adds_leading_slash_when_missing(monkeypatch, fresh_sachet):
    monkeypatch.setenv(
        "SACHET_PROXY_URL",
        "https://sachet-proxy.example.workers.dev",
    )
    # A caller passing the bare path without the leading slash should
    # still get a well-formed URL.
    url = fresh_sachet.effective_url("cap_public_website/FetchAllAlertDetails")
    assert url == (
        "https://sachet-proxy.example.workers.dev"
        "/cap_public_website/FetchAllAlertDetails"
    )


def test_empty_proxy_env_falls_back_to_upstream(monkeypatch, fresh_sachet):
    """An empty-string env var must be treated the same as unset —
    Cloudflare's wrangler dashboard sometimes blanks a var instead of
    deleting it, and we don't want that to break NDMA fetches."""
    monkeypatch.setenv("SACHET_PROXY_URL", "")
    assert fresh_sachet.effective_url() == (
        "https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml"
    )


@pytest.mark.asyncio
async def test_fetch_feed_uncached_uses_proxy(monkeypatch, fresh_sachet):
    """End-to-end through the fetch helper — the URL that ends up in
    `httpx.AsyncClient.get` must be the proxy URL when the env var is
    set."""
    monkeypatch.setenv(
        "SACHET_PROXY_URL",
        "https://sachet-proxy.example.workers.dev",
    )

    captured = {}

    class _FakeResponse:
        status_code = 200
        # Minimal RSS that parses to one alert.
        content = (
            b"<?xml version='1.0'?><rss><channel>"
            b"<item><title>Heavy rain warning for Kerala</title>"
            b"<guid>abc</guid><link>http://upstream/x</link>"
            b"<pubDate>Mon, 01 Jan 2026 00:00:00 +0000</pubDate>"
            b"</item></channel></rss>"
        )

    class _FakeClient:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def get(self, url, headers=None):
            captured["url"] = url
            captured["headers"] = headers
            return _FakeResponse()

    monkeypatch.setattr(
        "app.services.external_signals.sachet_provider.httpx.AsyncClient",
        _FakeClient,
    )

    out = await fresh_sachet._fetch_feed_uncached()
    assert len(out) == 1
    assert captured["url"].startswith(
        "https://sachet-proxy.example.workers.dev/cap_public_website/"
    )
    # Pinned user-agent is unchanged (the proxy adds its own).
    assert captured["headers"]["User-Agent"] == "nischint-safety/1.0"


@pytest.mark.asyncio
async def test_fetch_feed_uncached_falls_back_to_upstream(
    monkeypatch, fresh_sachet,
):
    monkeypatch.delenv("SACHET_PROXY_URL", raising=False)

    captured = {}

    class _FakeResponse:
        status_code = 200
        content = b"<rss><channel></channel></rss>"

    class _FakeClient:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def get(self, url, headers=None):
            captured["url"] = url
            return _FakeResponse()

    monkeypatch.setattr(
        "app.services.external_signals.sachet_provider.httpx.AsyncClient",
        _FakeClient,
    )

    await fresh_sachet._fetch_feed_uncached()
    assert captured["url"] == (
        "https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml"
    )
