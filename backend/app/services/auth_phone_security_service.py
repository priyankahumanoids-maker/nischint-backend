"""Caller-transaction phone locks; never opens a connection or commits.

Future issue/resend/verify routes MUST hold this row lock throughout challenge
work. Denials/failures must be committed by that caller, not rolled back by an
HTTP exception. No route is wired by 7C-1.
"""
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable

from sqlalchemy import text

from app.core.auth_foundation_policy import PhoneState, aware, phone_result, phone_security_key


@dataclass
class PhoneGuard:
    session: object
    digest: str
    state: PhoneState
    now: datetime

    @property
    def locked(self):
        return self.state.locked(self.now)

    async def record(self, *, success: bool):
        self.state = phone_result(self.state, success=success, now=self.now)
        await self.session.execute(text("""
            UPDATE auth_phone_security SET failure_count=:failures,
                locked_until=:locked_until, updated_at=:now WHERE phone_digest=:digest
        """), {"digest": self.digest, "failures": self.state.failures,
               "locked_until": self.state.locked_until, "now": self.now})


@asynccontextmanager
async def locked_phone(session, *, phone: str, key: bytes, now: datetime):
    aware(now)
    digest = phone_security_key(phone, key)
    # Concurrent first requests serialize on the PK before taking the row lock.
    await session.execute(text("""
        INSERT INTO auth_phone_security (phone_digest, updated_at)
        VALUES (:digest, :now) ON CONFLICT (phone_digest) DO NOTHING
    """), {"digest": digest, "now": now})
    row = (await session.execute(text("""
        SELECT failure_count, locked_until FROM auth_phone_security
        WHERE phone_digest=:digest FOR UPDATE
    """), {"digest": digest})).mappings().one()
    yield PhoneGuard(session, digest, PhoneState(row["failure_count"], row["locked_until"]), now)


async def verify_under_phone_lock(session, *, phone: str, key: bytes, now: datetime,
                                 verify: Callable[[], Awaitable[bool]]) -> bool:
    """verify must use this transaction; no provider/network work inside it."""
    async with locked_phone(session, phone=phone, key=key, now=now) as guard:
        if guard.locked:
            return False
        valid = await verify()
        if type(valid) is not bool:
            raise TypeError("Challenge verifier must return a boolean")
        await guard.record(success=valid)
        return valid
