"""AUTH-04 server-side authentication session lifecycle.

This module binds locally issued JWTs to durable PostgreSQL sessions so logout,
logout-all, password reset, disabled accounts, and hard-deleted accounts can be
honoured by the API immediately rather than waiting for access-token expiry.

Legacy tokens issued before AUTH-04 remain temporarily compatible.  Once a
security epoch is bumped (for example password reset / logout-all), all older
legacy credentials are rejected and cannot resurrect a session.
"""
from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services import redis_service

AUTH_SESSION_CACHE_NAMESPACE = "auth_session_state"
AUTH_SESSION_ACTIVE_CACHE_TTL_S = 2
AUTH_SESSION_REVOKED_CACHE_TTL_S = 2 * 60 * 60


def _safe_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _request_metadata(request: Any | None) -> tuple[str | None, str | None, str | None]:
    if request is None:
        return None, None, None

    try:
        user_agent = str(request.headers.get("user-agent") or "").strip()[:512] or None
    except Exception:
        user_agent = None

    try:
        explicit_label = str(request.headers.get("x-device-name") or "").strip()[:255]
    except Exception:
        explicit_label = ""

    device_label = explicit_label or (user_agent[:120] if user_agent else None)

    try:
        host = str(getattr(getattr(request, "client", None), "host", "") or "").strip()
    except Exception:
        host = ""

    ip_hash = None
    if host:
        ip_hash = hmac.new(
            settings.jwt_secret.encode("utf-8"),
            host.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    return device_label, user_agent, ip_hash


def _cache_session_state(
    session_id: str,
    *,
    user_id: str,
    state: str,
    ttl: int,
) -> None:
    try:
        redis_service.set_json(
            AUTH_SESSION_CACHE_NAMESPACE,
            session_id,
            {"user_id": user_id, "state": state},
            ttl=ttl,
        )
    except Exception:
        pass


def _get_cached_session_state(session_id: str) -> dict[str, Any] | None:
    try:
        cached = redis_service.get_json(AUTH_SESSION_CACHE_NAMESPACE, session_id)
        return cached if isinstance(cached, dict) else None
    except Exception:
        return None


async def create_auth_session(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    provider: str,
    request: Any | None = None,
) -> str:
    """Create one durable login session and return its UUID string."""
    sid = uuid.uuid4()
    device_label, user_agent, ip_hash = _request_metadata(request)
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.jwt_refresh_expires_days
    )

    await session.execute(
        text(
            """
            INSERT INTO auth_sessions (
                id,
                user_id,
                provider,
                device_label,
                user_agent,
                ip_hash,
                created_at,
                last_seen_at,
                expires_at
            )
            VALUES (
                CAST(:id AS UUID),
                CAST(:user_id AS UUID),
                :provider,
                :device_label,
                :user_agent,
                :ip_hash,
                NOW(),
                NOW(),
                :expires_at
            )
            """
        ),
        {
            "id": str(sid),
            "user_id": str(user_id),
            "provider": str(provider or "local")[:32],
            "device_label": device_label,
            "user_agent": user_agent,
            "ip_hash": ip_hash,
            "expires_at": expires_at,
        },
    )
    return str(sid)


async def validate_auth_session(
    session: AsyncSession,
    session_id: str,
    user_id: str | uuid.UUID,
    *,
    token_iat: int | float | None = None,
) -> bool:
    """Validate an AUTH-04 session and account state in one DB round-trip."""
    sid = _safe_uuid(session_id)
    uid = _safe_uuid(user_id)
    if not sid or not uid:
        return False

    cached = _get_cached_session_state(str(sid))
    if cached:
        cached_user_id = str(cached.get("user_id") or "")
        cached_state = str(cached.get("state") or "")
        if cached_user_id == str(uid):
            if cached_state == "revoked":
                return False
            if cached_state == "active":
                return True

    try:
        issued_at = float(token_iat) if token_iat is not None else None
    except (TypeError, ValueError):
        issued_at = None

    epoch_clause = ""
    params: dict[str, Any] = {"sid": str(sid), "uid": str(uid)}
    if issued_at is not None:
        epoch_clause = (
            " AND (e.tokens_valid_after IS NULL "
            "OR to_timestamp(:issued_at) >= e.tokens_valid_after)"
        )
        params["issued_at"] = issued_at

    result = await session.execute(
        text(
            f"""
            SELECT 1
            FROM auth_sessions s
            JOIN users u ON u.id = s.user_id
            LEFT JOIN auth_user_token_epochs e ON e.user_id = u.id
            WHERE s.id = CAST(:sid AS UUID)
              AND s.user_id = CAST(:uid AS UUID)
              AND s.revoked_at IS NULL
              AND s.expires_at > NOW()
              AND u.is_active = TRUE
              {epoch_clause}
            LIMIT 1
            """
        ),
        params,
    )
    valid = result.scalar_one_or_none() is not None
    _cache_session_state(
        str(sid),
        user_id=str(uid),
        state="active" if valid else "revoked",
        ttl=(
            AUTH_SESSION_ACTIVE_CACHE_TTL_S
            if valid
            else AUTH_SESSION_REVOKED_CACHE_TTL_S
        ),
    )
    return valid


async def validate_legacy_token_epoch(
    session: AsyncSession,
    user_id: str | uuid.UUID,
    *,
    token_iat: int | float | None = None,
) -> bool:
    """Validate a pre-AUTH-04 local token.

    Legacy credentials are allowed only while no user-level security epoch has
    been bumped.  If an epoch exists, tokens without ``iat`` are rejected.
    """
    uid = _safe_uuid(user_id)
    if not uid:
        return False

    try:
        issued_at = float(token_iat) if token_iat is not None else None
    except (TypeError, ValueError):
        issued_at = None

    result = await session.execute(
        text(
            """
            SELECT
                u.is_active AS is_active,
                e.tokens_valid_after AS tokens_valid_after
            FROM users u
            LEFT JOIN auth_user_token_epochs e ON e.user_id = u.id
            WHERE u.id = CAST(:uid AS UUID)
            LIMIT 1
            """
        ),
        {"uid": str(uid)},
    )
    row = result.mappings().first()
    if not row or not bool(row["is_active"]):
        return False

    valid_after = row["tokens_valid_after"]
    if valid_after is None:
        return True
    if issued_at is None:
        return False

    issued_dt = datetime.fromtimestamp(issued_at, tz=timezone.utc)
    return issued_dt >= valid_after


async def touch_auth_session(
    session: AsyncSession,
    session_id: str,
    user_id: str | uuid.UUID,
    *,
    extend_expiry: bool = True,
) -> bool:
    sid = _safe_uuid(session_id)
    uid = _safe_uuid(user_id)
    if not sid or not uid:
        return False

    result = await session.execute(
        text(
            """
            UPDATE auth_sessions
            SET last_seen_at = NOW(),
                expires_at = CASE
                    WHEN :extend_expiry THEN
                        NOW() + (:refresh_days * INTERVAL '1 day')
                    ELSE expires_at
                END
            WHERE id = CAST(:sid AS UUID)
              AND user_id = CAST(:uid AS UUID)
              AND revoked_at IS NULL
              AND expires_at > NOW()
            RETURNING id
            """
        ),
        {
            "sid": str(sid),
            "uid": str(uid),
            "extend_expiry": bool(extend_expiry),
            "refresh_days": int(settings.jwt_refresh_expires_days),
        },
    )
    touched = result.scalar_one_or_none() is not None
    if touched:
        _cache_session_state(
            str(sid),
            user_id=str(uid),
            state="active",
            ttl=AUTH_SESSION_ACTIVE_CACHE_TTL_S,
        )
    return touched


async def revoke_auth_session(
    session: AsyncSession,
    session_id: str,
    user_id: str | uuid.UUID,
    *,
    reason: str,
) -> bool:
    sid = _safe_uuid(session_id)
    uid = _safe_uuid(user_id)
    if not sid or not uid:
        return False

    result = await session.execute(
        text(
            """
            UPDATE auth_sessions
            SET revoked_at = COALESCE(revoked_at, NOW()),
                revoked_reason = COALESCE(revoked_reason, :reason)
            WHERE id = CAST(:sid AS UUID)
              AND user_id = CAST(:uid AS UUID)
            RETURNING id
            """
        ),
        {
            "sid": str(sid),
            "uid": str(uid),
            "reason": str(reason or "revoked")[:80],
        },
    )
    revoked = result.scalar_one_or_none() is not None
    if revoked:
        _cache_session_state(
            str(sid),
            user_id=str(uid),
            state="revoked",
            ttl=AUTH_SESSION_REVOKED_CACHE_TTL_S,
        )
    return revoked


async def revoke_all_auth_sessions(
    session: AsyncSession,
    user_id: str | uuid.UUID,
    *,
    reason: str,
) -> int:
    uid = _safe_uuid(user_id)
    if not uid:
        return 0

    result = await session.execute(
        text(
            """
            UPDATE auth_sessions
            SET revoked_at = COALESCE(revoked_at, NOW()),
                revoked_reason = COALESCE(revoked_reason, :reason)
            WHERE user_id = CAST(:uid AS UUID)
              AND revoked_at IS NULL
            RETURNING id
            """
        ),
        {
            "uid": str(uid),
            "reason": str(reason or "revoked_all")[:80],
        },
    )
    revoked_ids = [str(value) for value in result.scalars().all()]
    for sid in revoked_ids:
        _cache_session_state(
            sid,
            user_id=str(uid),
            state="revoked",
            ttl=AUTH_SESSION_REVOKED_CACHE_TTL_S,
        )
    return len(revoked_ids)


async def bump_user_token_epoch(
    session: AsyncSession,
    user_id: str | uuid.UUID,
) -> None:
    """Invalidate all local credentials issued before this transaction."""
    uid = _safe_uuid(user_id)
    if not uid:
        return

    await session.execute(
        text(
            """
            INSERT INTO auth_user_token_epochs (user_id, tokens_valid_after)
            VALUES (CAST(:uid AS UUID), NOW())
            ON CONFLICT (user_id)
            DO UPDATE SET tokens_valid_after = EXCLUDED.tokens_valid_after
            """
        ),
        {"uid": str(uid)},
    )


async def list_auth_sessions(
    session: AsyncSession,
    user_id: str | uuid.UUID,
) -> list[dict[str, Any]]:
    uid = _safe_uuid(user_id)
    if not uid:
        return []

    result = await session.execute(
        text(
            """
            SELECT
                id,
                provider,
                device_label,
                created_at,
                last_seen_at,
                expires_at
            FROM auth_sessions
            WHERE user_id = CAST(:uid AS UUID)
              AND revoked_at IS NULL
              AND expires_at > NOW()
            ORDER BY last_seen_at DESC, created_at DESC
            """
        ),
        {"uid": str(uid)},
    )
    return [dict(row) for row in result.mappings().all()]
