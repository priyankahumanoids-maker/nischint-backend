from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.push import PushTokenRequest, register_push_token


class RecordingSession:
    def __init__(self):
        self.calls = []
        self.committed = False

    async def execute(self, statement, params):
        self.calls.append((str(statement), params))

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_register_push_token_upserts_on_installation_token_constraint():
    session = RecordingSession()
    user_id = uuid4()

    result = await register_push_token(
        PushTokenRequest(token="guardian-fcm-token"),
        current_user=SimpleNamespace(id=user_id),
        session=session,
    )

    assert result == {"status": "registered"}
    assert session.committed is True
    assert len(session.calls) == 1

    statement, params = session.calls[0]
    assert "ON CONFLICT (token) DO UPDATE" in statement
    assert "user_id = EXCLUDED.user_id" in statement
    assert "ON CONFLICT (user_id, token)" not in statement
    assert params == {"uid": user_id, "tok": "guardian-fcm-token"}
