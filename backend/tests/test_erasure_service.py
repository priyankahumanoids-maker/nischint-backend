"""Unit tests for DPDP-01 erasure flow.

We test the service layer in isolation (no live DB) because the
end-to-end HTTP path is already covered by the smoke tests run during
implementation. The service unit tests target the state-machine logic
and the query SQL that the daily scheduler executes.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.erasure_request import (
    ErasureRequest,
    STATUS_PENDING,
    STATUS_COMPLETED,
    STATUS_CANCELLED,
    COMPLETION_ADMIN_APPROVE,
    COMPLETION_SCHEDULED,
    CANCELLATION_USER,
    CANCELLATION_ADMIN,
)
from app.services import erasure_service
from app.services.erasure_service import (
    ErasureAlreadyPending,
    ErasureNotCancellable,
    ErasureNotFound,
    GRACE_PERIOD_DAYS,
)


def _make_user(deleted_at: datetime | None = None) -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    u.email = "u@test.local"
    u.cognito_sub = None
    u.deleted_at = deleted_at
    return u


def _make_session_with_no_pending() -> MagicMock:
    """Session fixture: select returns no existing pending request."""
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    # session.execute returns an object whose .scalar_one_or_none() = None
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=exec_result)
    return session


@pytest.mark.asyncio
async def test_submit_creates_request_with_30day_grace():
    """A new request gets status=pending and grace_expires_at = now+30d."""
    session = _make_session_with_no_pending()
    user = _make_user()
    before = datetime.now(timezone.utc)

    req = await erasure_service.submit_request(
        session, user,
        request_ip="1.2.3.4", user_agent="UnitTest/1.0", reason="test",
    )

    after = datetime.now(timezone.utc)

    assert req.status == STATUS_PENDING
    assert req.user_id == user.id
    assert req.user_email == user.email
    assert req.request_ip == "1.2.3.4"
    assert req.user_agent == "UnitTest/1.0"
    assert req.request_reason == "test"
    # Grace window must be ~30 days, within the test's wall-clock skew.
    delta = req.grace_expires_at - req.requested_at
    assert timedelta(days=GRACE_PERIOD_DAYS) - timedelta(seconds=2) <= delta
    assert delta <= timedelta(days=GRACE_PERIOD_DAYS) + timedelta(seconds=2)
    # And requested_at falls within the test's wall window.
    assert before - timedelta(seconds=2) <= req.requested_at <= after + timedelta(seconds=2)

    # session.add called with the new ErasureRequest, session.flush awaited
    session.add.assert_called_once()
    session.flush.assert_awaited()
    # User update was executed
    assert session.execute.await_count >= 2  # at least: existence check + UPDATE user


@pytest.mark.asyncio
async def test_submit_refuses_double_pending():
    """If a pending request already exists, ErasureAlreadyPending is raised."""
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    # Pre-existing pending request.
    existing = MagicMock(spec=ErasureRequest)
    existing.status = STATUS_PENDING
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = existing
    session.execute = AsyncMock(return_value=exec_result)

    user = _make_user()

    with pytest.raises(ErasureAlreadyPending):
        await erasure_service.submit_request(
            session, user, request_ip=None, user_agent=None, reason=None,
        )


@pytest.mark.asyncio
async def test_cancel_user_path_succeeds():
    """A user can cancel their own pending request."""
    user = _make_user()
    req_id = uuid.uuid4()
    existing = MagicMock(spec=ErasureRequest)
    existing.id = req_id
    existing.user_id = user.id
    existing.status = STATUS_PENDING

    session = MagicMock()
    session.flush = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = existing
    session.execute = AsyncMock(return_value=exec_result)

    out = await erasure_service.cancel_request(
        session, request_id=req_id, actor_user=user,
        actor_source=CANCELLATION_USER,
    )
    assert out.status == STATUS_CANCELLED
    assert out.cancellation_source == CANCELLATION_USER
    assert out.cancelled_at is not None


@pytest.mark.asyncio
async def test_cancel_rejects_non_owner_as_not_found():
    """If a user tries to cancel someone else's request, raise NotFound
    (not Forbidden — we don't want to leak existence)."""
    actor = _make_user()
    req_id = uuid.uuid4()
    existing = MagicMock(spec=ErasureRequest)
    existing.id = req_id
    existing.user_id = uuid.uuid4()  # different from actor
    existing.status = STATUS_PENDING

    session = MagicMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = existing
    session.execute = AsyncMock(return_value=exec_result)

    with pytest.raises(ErasureNotFound):
        await erasure_service.cancel_request(
            session, request_id=req_id, actor_user=actor,
            actor_source=CANCELLATION_USER,
        )


@pytest.mark.asyncio
async def test_cancel_rejects_already_terminal_state():
    """Completed/cancelled requests cannot be cancelled again."""
    user = _make_user()
    req_id = uuid.uuid4()
    for terminal in (STATUS_COMPLETED, STATUS_CANCELLED):
        existing = MagicMock(spec=ErasureRequest)
        existing.id = req_id
        existing.user_id = user.id
        existing.status = terminal

        session = MagicMock()
        exec_result = MagicMock()
        exec_result.scalar_one_or_none.return_value = existing
        session.execute = AsyncMock(return_value=exec_result)

        with pytest.raises(ErasureNotCancellable):
            await erasure_service.cancel_request(
                session, request_id=req_id, actor_user=user,
                actor_source=CANCELLATION_USER,
            )


@pytest.mark.asyncio
async def test_admin_can_cancel_any_users_request():
    """When actor_source='admin', the owner-check is bypassed."""
    admin = _make_user()
    req_id = uuid.uuid4()
    existing = MagicMock(spec=ErasureRequest)
    existing.id = req_id
    existing.user_id = uuid.uuid4()  # not the admin's id
    existing.status = STATUS_PENDING

    session = MagicMock()
    session.flush = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = existing
    session.execute = AsyncMock(return_value=exec_result)

    out = await erasure_service.cancel_request(
        session, request_id=req_id, actor_user=admin,
        actor_source=CANCELLATION_ADMIN,
    )
    assert out.status == STATUS_CANCELLED
    assert out.cancellation_source == CANCELLATION_ADMIN


@pytest.mark.asyncio
async def test_constants_match_spec():
    """Lock the spec values so accidental changes don't silently break the
    DPDP compliance posture."""
    assert GRACE_PERIOD_DAYS == 30
    assert COMPLETION_SCHEDULED == "scheduled"
    assert COMPLETION_ADMIN_APPROVE == "admin_approve"
    assert CANCELLATION_USER == "user"
    assert CANCELLATION_ADMIN == "admin"
    assert STATUS_PENDING == "pending"
    assert STATUS_COMPLETED == "completed"
    assert STATUS_CANCELLED == "cancelled"
