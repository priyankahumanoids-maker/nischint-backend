# Security utilities for JWT authentication
# Supports dual-mode: local JWT + Cognito JWT
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import settings

SECRET_KEY = settings.jwt_secret
ALGORITHM = settings.jwt_algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = settings.jwt_expires_minutes


class TokenData(BaseModel):
    """Token payload data."""
    sub: str  # user_id
    exp: datetime
    sid: Optional[str] = None


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a local JWT access token.
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    issued_at = datetime.now(timezone.utc)
    to_encode.update({"type": "access", "iat": issued_at.timestamp(), "exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """Create a unique, long-lived refresh token for a local-auth session."""
    to_encode = data.copy()
    issued_at = datetime.now(timezone.utc)
    to_encode.update({
        "type": "refresh",
        "jti": uuid4().hex,
        "iat": issued_at.timestamp(),
        "exp": issued_at + timedelta(days=settings.jwt_refresh_expires_days),
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_refresh_token(token: str) -> Optional[dict]:
    """Validate a local refresh token and reject access-token substitution."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh" or not payload.get("sub"):
            return None
        return payload
    except JWTError:
        return None


def verify_token(token: str) -> Optional[str]:
    """
    Verify and decode a JWT token.
    Tries local JWT first. If Cognito is enabled and local fails, tries Cognito.

    Returns:
        User ID (sub claim) if valid, None otherwise
    """
    # Try local JWT first
    user_id = _verify_local_token(token)
    if user_id:
        return user_id

    # Try Cognito JWT if enabled
    from app.core.cognito import is_cognito_enabled, verify_cognito_token
    if is_cognito_enabled():
        claims = verify_cognito_token(token)
        if claims:
            # For Cognito access_token, sub is the Cognito user UUID
            # For id_token, sub is also present
            return claims.get("sub")

    return None


def decode_local_token_claims(token: str) -> Optional[dict]:
    """Decode only a locally-signed JWT, without Cognito fallback."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def _verify_local_token(token: str) -> Optional[str]:
    """Verify a locally-issued ACCESS JWT. Refresh tokens are never bearer tokens."""
    payload = decode_local_token_claims(token)
    if not payload:
        return None
    if payload.get("type") == "refresh":
        return None
    if payload.get("type") not in (None, "access"):
        return None
    user_id: str = payload.get("sub")
    if user_id is None:
        return None
    return user_id


def decode_token_claims(token: str) -> Optional[dict]:
    """
    Decode token and return all claims (for extracting role, email, etc.).
    Works with both local and Cognito tokens.
    """
    # Try local
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        pass

    # Try Cognito
    from app.core.cognito import is_cognito_enabled, verify_cognito_token
    if is_cognito_enabled():
        claims = verify_cognito_token(token)
        if claims:
            return claims

    return None
