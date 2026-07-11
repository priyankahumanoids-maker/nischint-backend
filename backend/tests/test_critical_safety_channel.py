"""Regression test for the louder_push (critical_safety) payload contract.

These tests protect the wire format that the Android `critical_safety`
notification channel depends on. If any of these assertions fails, the
mobile client will silently fall back to the default channel and the
"interruption" guarantee is lost.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import push_service


class _FakeResp:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


@pytest.mark.asyncio
async def test_louder_push_payload_uses_critical_safety_channel():
    """louder=True MUST send `channel_id=critical_safety`, sound=siren_loop,
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
    assert android_notif["channel_id"] == "critical_safety", \
        "louder_push MUST land on the critical_safety channel"
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
    """Routine (non-louder) pushes MUST NOT land on critical_safety —
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
    assert android_notif["channel_id"] != "critical_safety"
    assert android_notif["sound"] == "default"
    assert "louder_push" not in msg["data"]
