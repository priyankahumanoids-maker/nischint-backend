"""Limited SOS authentication dependency for Phase 7C-4.

Only emergency trigger endpoints opt into this dependency.  A valid SOS
credential never becomes a general bearer token and is not accepted by ordinary
authentication dependencies.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security.utils import get_authorization_scheme_param
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.core.auth_foundation_policy import SOS_SCOPE
from app.core.security import decode_local_token_claims
from app.models.user import User
from app.services import user_service
from app.services.auth_sos_credential_service import resolve_sos_subject

SOS_CREDENTIAL_HEADER = "X-Nischint-SOS-Credential"
SOS_CREDENTIAL_TTL_DAYS = 30


def current_local_session_id(request: Request) -> UUID | None:
    scheme, token = get_authorization_scheme_param(request.headers.get("authorization"))
    if scheme.lower() != "bearer" or not token:
        return None
    claims = decode_local_token_claims(token)
    if not claims or claims.get("type") == "refresh":
        return None
    try:
        return UUID(str(claims.get("sid") or ""))
    except (TypeError, ValueError):
        return None


async def get_sos_trigger_user(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> User:
    """Authenticate an SOS trigger by limited credential or ordinary bearer.

    A valid SOS credential wins even if an expired ordinary Authorization header
    is also present.  Invalid/missing SOS credentials fall back to the existing
    bearer path so legacy clients continue to work.
    """
    sos_token = str(request.headers.get(SOS_CREDENTIAL_HEADER) or "").strip()
    if sos_token:
        user_id = await resolve_sos_subject(
            session, token=sos_token, requested_scope=SOS_SCOPE,
            now=datetime.now(timezone.utc),
        )
        if user_id is not None:
            user = await user_service.get_user_by_id(session, user_id)
            if user is not None and bool(getattr(user, "is_active", True)):
                return user
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Emergency credential subject is unavailable",
            )

    scheme, token = get_authorization_scheme_param(request.headers.get("authorization"))
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Emergency authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await get_current_user(token=token, session=session)
