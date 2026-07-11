# Google OAuth Authentication
# REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.config import settings
from app.core.rate_limiter import limiter
from app.core.security import create_access_token
from app.models.user import User
from app.services import user_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/google", tags=["google-auth"])

GOOGLE_TOKEN_INFO_URL = "https://oauth2.googleapis.com/tokeninfo"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleCredentialRequest(BaseModel):
    credential: str  # ID token from Google Sign-In


class GoogleCodeRequest(BaseModel):
    code: str  # Authorization code from Google Sign-In
    redirect_uri: str  # REMINDER: DO NOT HARDCODE THE URL, THIS BREAKS THE AUTH


class GoogleAuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    auth_provider: str = "google"
    email: str
    full_name: Optional[str] = None
    is_new_user: bool = False


async def _verify_google_id_token(id_token: str) -> dict:
    """
    Verify a Google ID token and return user info.
    Uses Google's tokeninfo endpoint for verification.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            GOOGLE_TOKEN_INFO_URL,
            params={"id_token": id_token},
        )

        if resp.status_code != 200:
            logger.error(f"Google token verification failed: {resp.status_code} {resp.text}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Google credential",
            )

        data = resp.json()

        # Verify the token was intended for our app
        if data.get("aud") != settings.google_client_id:
            logger.error(f"Google token audience mismatch: {data.get('aud')}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token not issued for this application",
            )

        return {
            "email": data.get("email"),
            "email_verified": data.get("email_verified") == "true",
            "name": data.get("name"),
            "picture": data.get("picture"),
            "sub": data.get("sub"),  # Google user ID
        }


async def _exchange_code_for_tokens(code: str, redirect_uri: str) -> dict:
    """Exchange authorization code for tokens."""
    # REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )

        if resp.status_code != 200:
            logger.error(f"Google code exchange failed: {resp.status_code} {resp.text}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Failed to exchange authorization code",
            )

        return resp.json()


async def _get_google_userinfo(access_token: str) -> dict:
    """Get user info from Google using access token."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Failed to get user info from Google",
            )

        data = resp.json()
        return {
            "email": data.get("email"),
            "email_verified": data.get("email_verified", False),
            "name": data.get("name"),
            "picture": data.get("picture"),
            "sub": data.get("sub"),
        }


async def _provision_google_user(
    session: AsyncSession,
    google_info: dict,
) -> tuple[User, bool]:
    """
    Find or create a local user for a Google-authenticated user.
    Returns (user, is_new_user).
    """
    email = google_info["email"]
    name = google_info.get("name", "")
    google_sub = google_info.get("sub", "")

    # Check if user exists by email
    user = await user_service.get_user_by_email(session, email)

    if user:
        # Link Google sub if not already linked
        if not user.cognito_sub:
            user.cognito_sub = f"google_{google_sub}"
        if name and not user.full_name:
            user.full_name = name
        await session.flush()
        return user, False

    # Create new user
    user = User(
        email=email,
        password_hash="google-oauth-managed",
        cognito_sub=f"google_{google_sub}",
        role="guardian",
        full_name=name,
    )
    session.add(user)
    await session.flush()
    return user, True


@router.post("", response_model=GoogleAuthResponse)
@limiter.limit("5/minute")
async def google_auth_credential(
    request: Request,
    req: GoogleCredentialRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Authenticate with Google ID token (from Google Sign-In popup).
    Verifies the token, creates/links local user, returns JWT.
    """
    if not settings.google_client_id:
        raise HTTPException(status_code=400, detail="Google OAuth not configured")

    # Verify the Google credential (ID token)
    google_info = await _verify_google_id_token(req.credential)

    if not google_info.get("email"):
        raise HTTPException(status_code=400, detail="Google account has no email")

    # Find or create local user
    user, is_new = await _provision_google_user(session, google_info)
    await session.commit()

    # Issue local JWT
    access_token = create_access_token(data={
        "sub": str(user.id),
        "role": user.role,
        "email": user.email,
        "full_name": user.full_name,
    })

    logger.info(f"Google auth successful for {user.email} (new={is_new})")

    return GoogleAuthResponse(
        access_token=access_token,
        role=user.role,
        email=user.email,
        full_name=user.full_name,
        is_new_user=is_new,
    )


@router.post("/code", response_model=GoogleAuthResponse)
@limiter.limit("5/minute")
async def google_auth_code(
    request: Request,
    req: GoogleCodeRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Authenticate with Google authorization code (from redirect flow).
    Exchanges code for tokens, gets user info, creates/links local user.
    """
    # REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    if not settings.google_client_id:
        raise HTTPException(status_code=400, detail="Google OAuth not configured")

    # Exchange code for tokens
    tokens = await _exchange_code_for_tokens(req.code, req.redirect_uri)

    # Get user info
    if "id_token" in tokens:
        google_info = await _verify_google_id_token(tokens["id_token"])
    elif "access_token" in tokens:
        google_info = await _get_google_userinfo(tokens["access_token"])
    else:
        raise HTTPException(status_code=400, detail="No token in Google response")

    if not google_info.get("email"):
        raise HTTPException(status_code=400, detail="Google account has no email")

    # Find or create local user
    user, is_new = await _provision_google_user(session, google_info)
    await session.commit()

    # Issue local JWT
    access_token = create_access_token(data={
        "sub": str(user.id),
        "role": user.role,
        "email": user.email,
        "full_name": user.full_name,
    })

    logger.info(f"Google auth (code) successful for {user.email} (new={is_new})")

    return GoogleAuthResponse(
        access_token=access_token,
        role=user.role,
        email=user.email,
        full_name=user.full_name,
        is_new_user=is_new,
    )


@router.get("/status")
async def google_auth_status():
    """Check if Google OAuth is configured."""
    return {
        "enabled": bool(settings.google_client_id),
        "client_id": settings.google_client_id if settings.google_client_id else None,
    }
