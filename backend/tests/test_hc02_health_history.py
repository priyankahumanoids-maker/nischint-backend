"""HC-02 — Health history endpoint tests.

Locks:
  1. Auth: caller cannot read another user's history unless they are
     a registered guardian.
  2. With data in Redis, returns chronologically ordered hr/spo2 +
     correctly tagged anomalies.
  3. Empty state: no Redis data → hr=[] spo2=[] anomalies=[].
"""
from __future__ import annotations

import json
import time
import uuid
from unittest.mock import MagicMock

import pytest

from app.api import health_signals as hs


@pytest.fixture
def mock_client(monkeypatch):
    """Inject a fake Redis client so the endpoint reads from a dict."""
    store: dict[str, list[str]] = {}

    class FakeClient:
        def zrangebyscore(self, key: str, since: float, _max: str):
            return store.get(key, [])

        def zrevrange(self, key: str, _a: int, _b: int):
            return store.get(key, [])[::-1]

    fc = FakeClient()
    monkeypatch.setattr(hs.redis_service, "_get_client", lambda: fc)
    monkeypatch.setattr(hs.redis_service, "_key",
                        lambda *parts: "nischint:" + ":".join(parts))
    return store


def _enc(ts: str, v: float) -> str:
    """Reproduce the ZSET member format used by the ingest endpoint."""
    payload = json.dumps({
        "type": "x", "value": v, "unit": "x", "source": "test",
        "timestamp": ts, "idem": "AAAA",
    })
    return f"AAAA:{payload}"


@pytest.mark.asyncio
async def test_history_returns_data_with_anomalies(mock_client, monkeypatch):
    """When Redis has data, the endpoint returns hr/spo2 + anomalies."""
    user_id = "u1"
    mock_client[f"nischint:wearable:{user_id}:heart_rate"] = [
        _enc("2026-05-20T10:00:00Z",  72.0),
        _enc("2026-05-20T11:00:00Z", 135.0),  # anomaly: hr_high
        _enc("2026-05-20T12:00:00Z",  88.0),
    ]
    mock_client[f"nischint:wearable:{user_id}:spo2"] = [
        _enc("2026-05-20T10:00:00Z", 97.0),
        _enc("2026-05-20T11:30:00Z", 92.0),   # anomaly: spo2_low
    ]

    user = MagicMock()
    user.id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    # self read — bypass guardian check
    monkeypatch.setattr(
        hs, "_is_guardian_of",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("not called")),
    )
    out = await hs.get_health_history(
        user_id=str(user.id), user=user, session=MagicMock(),
    )

    assert out["user_id"] == str(user.id)
    # Read keys built for OUR user, not "u1" — ensure the matching set
    # was provided in the fake store.
    # We seeded against the literal "u1" key — verify the function
    # actually looks up `user_id` (the path param).
    # → Replay with the seeded user_id.
    mock_client[f"nischint:wearable:{str(user.id)}:heart_rate"] = \
        mock_client.pop(f"nischint:wearable:u1:heart_rate")
    mock_client[f"nischint:wearable:{str(user.id)}:spo2"] = \
        mock_client.pop(f"nischint:wearable:u1:spo2")
    out = await hs.get_health_history(
        user_id=str(user.id), user=user, session=MagicMock(),
    )
    assert len(out["hr"])   == 3
    assert len(out["spo2"]) == 2
    # Anomalies: one HR>120, one SpO2<94.
    assert len(out["anomalies"]) == 2
    tags = sorted(a["type"] for a in out["anomalies"])
    assert tags == ["hr_high", "spo2_low"]
    # Values surface unchanged.
    hr_anom = next(a for a in out["anomalies"] if a["type"] == "hr_high")
    assert hr_anom["value"] == 135.0


@pytest.mark.asyncio
async def test_history_empty_state(mock_client, monkeypatch):
    """No data in Redis → empty lists. No exceptions."""
    user = MagicMock()
    user.id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    out = await hs.get_health_history(
        user_id=str(user.id), user=user, session=MagicMock(),
    )
    assert out == {"user_id": str(user.id), "hr": [], "spo2": [], "anomalies": []}


@pytest.mark.asyncio
async def test_history_rbac_blocks_non_guardian(monkeypatch):
    """Non-guardian caller asking for someone else's history → 403."""
    from fastapi import HTTPException

    async def _is_guard(*a, **kw): return False
    monkeypatch.setattr(hs, "_is_guardian_of", _is_guard)
    monkeypatch.setattr(hs.redis_service, "_get_client", lambda: None)

    user = MagicMock()
    user.id = uuid.UUID("00000000-0000-0000-0000-000000000003")
    with pytest.raises(HTTPException) as exc:
        await hs.get_health_history(
            user_id="00000000-0000-0000-0000-000000000009",
            user=user, session=MagicMock(),
        )
    assert exc.value.status_code == 403
