"""REL-04 — Tests for the `/admin/db/terminate-backend` endpoint.

What we lock down:
  1. Validation: pid must be > 0.
  2. Audit-row write happens BEFORE the SQL — even a failing
     pg_terminate_backend leaves a row in the audit log.
  3. The endpoint refuses to terminate its own diagnostic backend.
  4. Forensic context from the request body lands in the audit row.

We mock the asyncpg pool and verify what's INSERT-ed. The pytest
session isn't connected to a real DB here — instead we mock
`SessionAddCapture` for `session.add()` and `session.commit()` to
inspect what would be persisted.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException


# ── Fake asyncpg pool ───────────────────────────────────────────────


class _FakeConn:
    def __init__(self, *, own_pid: int = 12345, terminate_result=True):
        self.own_pid = own_pid
        self.terminate_result = terminate_result
        self.calls: list[tuple] = []

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        if "pg_backend_pid" in sql:
            return self.own_pid
        if "pg_terminate_backend" in sql:
            return self.terminate_result
        return None


class _FakeAcquireCM:
    def __init__(self, conn: _FakeConn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_exc):
        return False


class _FakePool:
    def __init__(self, conn: _FakeConn):
        self.conn = conn

    def acquire(self):
        return _FakeAcquireCM(self.conn)


# ── Fake DB session ─────────────────────────────────────────────────


class _FakeSession:
    """Records additions and refreshes — captures the audit row that
    would be written without actually hitting Postgres."""

    def __init__(self):
        self.added: list = []
        self.commits: int = 0
        self._refreshed_ids = 0

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        # Simulate the DB filling an id+created_at if not present.
        self._refreshed_ids += 1
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()

    async def execute(self, *_a, **_kw):
        # _ensure_audit_table calls this; return a stub that supports
        # the chain we don't exercise here.
        return None


# ── Fake user ───────────────────────────────────────────────────────


class _FakeUser:
    def __init__(self):
        self.id = uuid4()
        self.email = "operator@nischint.com"
        self.role = "operator"


class _FakeRequest:
    def __init__(self, ip="10.0.0.1", ua="pytest/1.0"):
        self.client = type("C", (), {"host": ip})()
        self.headers = {"user-agent": ua}


# ── Tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rejects_pid_zero(monkeypatch):
    from app.api.db_rescue import terminate_backend, TerminateRequest
    session = _FakeSession()
    with pytest.raises(HTTPException) as exc:
        await terminate_backend(
            pid=0,
            body=TerminateRequest(),
            request=_FakeRequest(),
            user=_FakeUser(),
            session=session,  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 400
    # No audit row should have been added.
    assert session.added == []


@pytest.mark.asyncio
async def test_rejects_negative_pid(monkeypatch):
    from app.api.db_rescue import terminate_backend, TerminateRequest
    with pytest.raises(HTTPException) as exc:
        await terminate_backend(
            pid=-7,
            body=TerminateRequest(),
            request=_FakeRequest(),
            user=_FakeUser(),
            session=_FakeSession(),  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_happy_path_writes_audit_and_terminates(monkeypatch):
    """The audit row must:
       1. be added BEFORE the SQL fires,
       2. have success=True after a successful pg_terminate_backend."""
    import app.api.db_rescue as mod
    monkeypatch.setattr(mod, "_table_ready", True)  # skip CREATE TABLE
    fake_conn = _FakeConn(own_pid=12345, terminate_result=True)

    async def fake_get_pool():
        return _FakePool(fake_conn)

    monkeypatch.setattr("app.db.session.get_db_pool", fake_get_pool)

    user = _FakeUser()
    session = _FakeSession()
    body = mod.TerminateRequest(
        query_text="SELECT * FROM huge_table",
        duration_ms=15000,
        wait_event="Lock",
        state="active",
        reason="REL-04 smoke",
    )

    resp = await mod.terminate_backend(
        pid=99,
        body=body,
        request=_FakeRequest(),
        user=user,
        session=session,  # type: ignore[arg-type]
    )

    assert resp.success is True
    assert resp.pid == 99
    assert resp.pg_terminate_backend_returned is True
    # Audit row must carry the forensic context the caller provided.
    assert len(session.added) == 1
    row = session.added[0]
    assert row.user_id == user.id
    assert row.user_email == "operator@nischint.com"
    assert row.target_pid == 99
    assert row.query_text == "SELECT * FROM huge_table"
    assert row.duration_ms == 15000
    assert row.wait_event == "Lock"
    assert row.state == "active"
    assert row.reason == "REL-04 smoke"
    assert row.success is True
    assert row.pg_terminate_backend_returned is True
    # Pre-write + outcome-update = at least 2 commits.
    assert session.commits >= 2


@pytest.mark.asyncio
async def test_refuses_to_terminate_own_diagnostic_backend(monkeypatch):
    """If the pid happens to be our own connection's pid we MUST refuse
    — otherwise an operator could nuke the connection that's auditing
    the call."""
    import app.api.db_rescue as mod
    monkeypatch.setattr(mod, "_table_ready", True)
    # Diagnostic conn reports its own pid = 555. We try to terminate
    # exactly that pid.
    fake_conn = _FakeConn(own_pid=555, terminate_result=True)

    async def fake_get_pool():
        return _FakePool(fake_conn)

    monkeypatch.setattr("app.db.session.get_db_pool", fake_get_pool)

    session = _FakeSession()
    resp = await mod.terminate_backend(
        pid=555,
        body=mod.TerminateRequest(),
        request=_FakeRequest(),
        user=_FakeUser(),
        session=session,  # type: ignore[arg-type]
    )
    assert resp.success is False
    assert "diagnostic backend" in (resp.error or "")
    # We must NOT have called pg_terminate_backend on our own pid.
    pg_term_calls = [c for c in fake_conn.calls if "pg_terminate_backend" in c[1]]
    assert pg_term_calls == []
    # The audit row must reflect the refusal.
    row = session.added[0]
    assert row.success is False
    assert "diagnostic backend" in (row.error_message or "")


@pytest.mark.asyncio
async def test_pg_error_is_audited_not_raised(monkeypatch):
    """If pg_terminate_backend raises, we must NOT 500 — we must
    record the error in the audit row and return success=False so the
    operator sees the failure in the UI."""
    import app.api.db_rescue as mod
    monkeypatch.setattr(mod, "_table_ready", True)

    class _BrokenPool:
        def acquire(self_inner):
            class _CM:
                async def __aenter__(_s):
                    raise RuntimeError("network blip")
                async def __aexit__(_s, *_e):
                    return False
            return _CM()

    async def fake_get_pool():
        return _BrokenPool()

    monkeypatch.setattr("app.db.session.get_db_pool", fake_get_pool)

    session = _FakeSession()
    resp = await mod.terminate_backend(
        pid=42,
        body=mod.TerminateRequest(),
        request=_FakeRequest(),
        user=_FakeUser(),
        session=session,  # type: ignore[arg-type]
    )
    assert resp.success is False
    assert "network blip" in (resp.error or "")
    row = session.added[0]
    assert row.success is False
    assert "network blip" in (row.error_message or "")


@pytest.mark.asyncio
async def test_audit_captures_request_metadata(monkeypatch):
    """IP + user-agent must reach the audit row for the trail."""
    import app.api.db_rescue as mod
    monkeypatch.setattr(mod, "_table_ready", True)

    async def fake_get_pool():
        return _FakePool(_FakeConn(terminate_result=True))

    monkeypatch.setattr("app.db.session.get_db_pool", fake_get_pool)

    session = _FakeSession()
    await mod.terminate_backend(
        pid=77,
        body=mod.TerminateRequest(),
        request=_FakeRequest(ip="1.2.3.4", ua="Mozilla/5.0 (op-desk)"),
        user=_FakeUser(),
        session=session,  # type: ignore[arg-type]
    )
    row = session.added[0]
    assert row.ip_address == "1.2.3.4"
    assert "Mozilla" in (row.user_agent or "")
