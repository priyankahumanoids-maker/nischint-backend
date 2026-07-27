"""Regression test for the louder_push notification-channel contract.

These tests protect the wire format that the Android critical safety
notification channel depends on. If any of these assertions fails, the
mobile client will silently fall back to the default channel and the
"interruption" guarantee is lost.
"""
import json
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import push_service


class _FakeResp:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


def test_fcm_access_token_is_reused_while_valid():
    """A valid OAuth token must not be refreshed for every notification."""

    class FakeCredentials:
        token = None
        valid = False
        refresh_count = 0

        def refresh(self, _request):
            self.refresh_count += 1
            self.token = "cached-access-token"
            self.valid = True

    credentials = FakeCredentials()
    with patch.object(push_service, "_get_credentials", return_value=credentials):
        first = push_service._get_access_token()
        second = push_service._get_access_token()

    assert first == second == "cached-access-token"
    assert credentials.refresh_count == 1


@pytest.mark.asyncio
async def test_multiple_device_tokens_dispatch_without_blocking_each_other():
    """A stale first device must not delay a guardian's current device."""
    started = 0
    both_started = asyncio.Event()

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def post(self, url, json=None, headers=None):
            nonlocal started
            started += 1
            if started == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=0.5)
            return _FakeResp(200)

    with patch.object(push_service, "_get_access_token", return_value="fake-token"), \
         patch.object(push_service, "_record_token_success", new=AsyncMock()), \
         patch.object(push_service.httpx, "AsyncClient", lambda: FakeClient()), \
         patch.object(push_service, "settings", MagicMock(firebase_project_id="test-proj")):
        sent = await push_service.send_push_to_tokens(
            tokens=["old-token", "current-token", "current-token"],
            title="Safety alert",
            body="Open NISCHINT",
        )

    assert sent == 2
    assert started == 2


@pytest.mark.asyncio
async def test_louder_push_payload_uses_critical_safety_channel():
    """louder=True MUST use the current critical channel, sound=siren_loop,
    sticky=True, and the `louder_push=true` data flag."""
    captured: list[dict] = []

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            captured.append(json)
            return _FakeResp(200)

    with patch.object(push_service, "_get_access_token", return_value="fake-token"), \
         patch.object(push_service, "_record_token_success", new=AsyncMock()), \
         patch.object(push_service.httpx, "AsyncClient", lambda: FakeClient()), \
         patch.object(push_service, "settings", MagicMock(firebase_project_id="test-proj")):
        sent = await push_service.send_push_to_tokens(
            tokens=["dev_token_abcdef12345"],
            title="EMERGENCY",
            body="Tap to respond",
            data={"tag": "louder_push", "alert_id": "abc"},
            louder=True,
        )

    assert sent == 1
    assert len(captured) == 1
    msg = captured[0]["message"]

    # Android contract
    android_notif = msg["android"]["notification"]
    assert android_notif["channel_id"] == push_service.CRITICAL_SAFETY_CHANNEL_ID, \
        "louder_push MUST land on the current critical safety channel"
    assert android_notif["sound"] == "siren_loop", \
        "louder_push MUST use the bundled siren_loop sound"
    assert android_notif["sticky"] is True
    assert android_notif["notification_priority"] == "PRIORITY_MAX"
    assert android_notif["visibility"] == "PUBLIC"
    assert msg["android"]["priority"] == "high"

    # Data payload contract — mobile client keys off `louder_push="true"`
    assert msg["data"]["louder_push"] == "true"

    # iOS critical-alert contract
    aps = msg["apns"]["payload"]["aps"]
    assert aps["interruption-level"] == "critical"
    assert aps["sound"]["critical"] == 1
    assert aps["sound"]["name"] == "siren_loop.caf"


@pytest.mark.asyncio
async def test_default_push_does_not_use_critical_channel():
    """Routine pushes use the versioned guardian channel, not critical —
    we don't want to spam DND with low-importance alerts."""
    captured: list[dict] = []

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            captured.append(json)
            return _FakeResp(200)

    with patch.object(push_service, "_get_access_token", return_value="fake-token"), \
         patch.object(push_service, "_record_token_success", new=AsyncMock()), \
         patch.object(push_service.httpx, "AsyncClient", lambda: FakeClient()), \
         patch.object(push_service, "settings", MagicMock(firebase_project_id="test-proj")):
        await push_service.send_push_to_tokens(
            tokens=["dev_token_abcdef12345"],
            title="Journey ended",
            body="Trip complete",
            data={"tag": "journey.end"},
            louder=False,
        )

    msg = captured[0]["message"]
    android_notif = msg["android"]["notification"]
    assert android_notif["channel_id"] == push_service.GUARDIAN_ALERT_CHANNEL_ID
    assert android_notif["sound"] == "default"
    assert "louder_push" not in msg["data"]
