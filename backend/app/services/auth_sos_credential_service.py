"""Emergency-only credential storage. NOT integrated with any API in 7C-1.

Lifetime is supplied by a later explicit policy. No session FK/refresh dependency.
Tokens are opaque, returned only at issuance and never logged/stored in plaintext.
"""
import hashlib
import secrets
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import text

from app.core.auth_foundation_policy import SOS_SCOPE, aware, sos_valid


def credential_digest(token: str) -> str:
    return hashlib.sha256(("sos-credential-v1:" + token).encode()).hexdigest()


async def issue_sos_credential(session, *, user_id: UUID, installation_id: UUID,
                               now: datetime, expires_at: datetime) -> str:
    if aware(expires_at) <= aware(now):
        raise ValueError("Positive emergency credential lifetime required")
    active = (await session.execute(text("""
        SELECT id FROM auth_installations WHERE id=:iid AND user_id=:uid
            AND revoked_at IS NULL FOR UPDATE
    """), {"iid": installation_id, "uid": user_id})).scalar_one_or_none()
    if active is None:
        raise ValueError("Active subject installation required")
    token = "sos1." + secrets.token_urlsafe(32)
    await session.execute(text("""
        INSERT INTO auth_sos_credentials
            (id,user_id,installation_id,credential_digest,scope,issued_at,expires_at)
        VALUES (:id,:uid,:iid,:digest,:scope,:now,:expires)
    """), {"id": uuid4(), "uid": user_id, "iid": installation_id,
            "digest": credential_digest(token), "scope": SOS_SCOPE, "now": now, "expires": expires_at})
    return token


async def revoke_installation_sos_credentials(session, *, user_id: UUID, installation_id: UUID, now: datetime) -> int:
    result = await session.execute(text("""
        UPDATE auth_sos_credentials SET revoked_at=:now
        WHERE user_id=:uid AND installation_id=:iid AND revoked_at IS NULL
        RETURNING id
    """), {"uid": user_id, "iid": installation_id, "now": aware(now)})
    return len(list(result.scalars().all()))


async def rotate_sos_credential(session, *, user_id: UUID, installation_id: UUID,
                                now: datetime, expires_at: datetime) -> str:
    await revoke_installation_sos_credentials(
        session, user_id=user_id, installation_id=installation_id, now=now,
    )
    return await issue_sos_credential(
        session, user_id=user_id, installation_id=installation_id,
        now=now, expires_at=expires_at,
    )


async def resolve_sos_subject(session, *, token: str, requested_scope: str, now: datetime) -> UUID | None:
    aware(now)
    if requested_scope != SOS_SCOPE or not token.startswith("sos1.") or len(token) != 48:
        return None
    row = (await session.execute(text("""
        SELECT c.user_id,c.scope,c.issued_at,c.expires_at,c.revoked_at
        FROM auth_sos_credentials c JOIN auth_installations i
            ON i.id=c.installation_id AND i.user_id=c.user_id
        WHERE c.credential_digest=:digest AND i.revoked_at IS NULL
    """), {"digest": credential_digest(token)})).mappings().first()
    if row and sos_valid(scope=row["scope"], issued_at=row["issued_at"],
                         expires_at=row["expires_at"], revoked_at=row["revoked_at"], now=now):
        return row["user_id"]
    return None


async def revoke_sos_credential(session, *, credential_id: UUID, user_id: UUID, now: datetime) -> bool:
    result = await session.execute(text("""
        UPDATE auth_sos_credentials SET revoked_at=:now
        WHERE id=:id AND user_id=:uid AND revoked_at IS NULL RETURNING id
    """), {"id": credential_id, "uid": user_id, "now": aware(now)})
    return result.scalar_one_or_none() is not None
