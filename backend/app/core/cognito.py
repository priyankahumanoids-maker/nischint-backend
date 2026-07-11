# AWS Cognito Integration Service
#
# Handles user pool operations: sign-up, sign-in, token refresh, JWT verification.
# Activates only when COGNITO_USER_POOL_ID is configured in .env.
# Falls back to local JWT auth when Cognito is not configured.

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Optional
from urllib.request import urlopen

import boto3
from botocore.exceptions import ClientError
from jose import jwk, jwt
from jose.utils import base64url_decode

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── State ──
_jwks_cache: dict = {}
_jwks_cache_time: float = 0
JWKS_CACHE_TTL = 3600  # 1 hour


# ── Feature flag ───────────────────────────────────────────────────
# Set COGNITO_ENABLED=true in backend/.env to turn Cognito ON.
# Default is FALSE so preview/dev never talks to AWS and the logs stay clean.
# When disabled, ALL Cognito entry points short-circuit — auth routes through
# the local Postgres fallback in auth.py.
import os as _os
COGNITO_ENABLED: bool = _os.getenv("COGNITO_ENABLED", "false").lower() == "true"


def is_cognito_enabled() -> bool:
    """Single source of truth. Respects the flag first, then verifies config presence."""
    if not COGNITO_ENABLED:
        return False
    return bool(settings.cognito_user_pool_id and settings.cognito_client_id)


def _get_client():
    return boto3.client(
        "cognito-idp",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )


def _compute_secret_hash(username: str) -> str:
    """Compute SECRET_HASH for Cognito App Client with a secret."""
    if not settings.cognito_client_secret:
        return ""
    msg = username + settings.cognito_client_id
    dig = hmac.new(
        settings.cognito_client_secret.encode("utf-8"),
        msg.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(dig).decode("utf-8")


# ── Sign Up ──

def _ensure_enabled(fn_name: str = "") -> None:
    """Guard used at the top of every Cognito network call."""
    if not is_cognito_enabled():
        raise RuntimeError(
            f"Cognito is disabled (COGNITO_ENABLED=false). Skipped: {fn_name or 'call'}"
        )


def sign_up(email: str, password: str, full_name: str = "", phone: str = "") -> dict:
    """
    Register a new user in Cognito User Pool.
    Returns: {user_sub, user_confirmed, ...}
    """
    _ensure_enabled("sign_up")
    client = _get_client()
    attrs = [{"Name": "email", "Value": email}]
    if full_name:
        attrs.append({"Name": "name", "Value": full_name})
    if phone:
        attrs.append({"Name": "phone_number", "Value": phone})

    params = {
        "ClientId": settings.cognito_client_id,
        "Username": email,
        "Password": password,
        "UserAttributes": attrs,
    }
    secret_hash = _compute_secret_hash(email)
    if secret_hash:
        params["SecretHash"] = secret_hash

    try:
        resp = client.sign_up(**params)
        return {
            "user_sub": resp["UserSub"],
            "user_confirmed": resp["UserConfirmed"],
            "code_delivery": resp.get("CodeDeliveryDetails"),
        }
    except ClientError as e:
        code = e.response["Error"]["Code"]
        msg = e.response["Error"]["Message"]
        logger.error(f"Cognito sign_up error: {code} — {msg}")
        raise ValueError(f"{code}: {msg}")


def admin_confirm_user(email: str):
    """Admin-confirm a user (skip email verification for dev/staging)."""
    _ensure_enabled("admin_confirm_user")
    client = _get_client()
    try:
        client.admin_confirm_sign_up(
            UserPoolId=settings.cognito_user_pool_id,
            Username=email,
        )
    except ClientError as e:
        logger.error(f"Cognito admin_confirm error: {e}")
        raise


def confirm_sign_up(email: str, code: str) -> bool:
    """Confirm sign-up with verification code."""
    _ensure_enabled("confirm_sign_up")
    client = _get_client()
    params = {
        "ClientId": settings.cognito_client_id,
        "Username": email,
        "ConfirmationCode": code,
    }
    secret_hash = _compute_secret_hash(email)
    if secret_hash:
        params["SecretHash"] = secret_hash

    try:
        client.confirm_sign_up(**params)
        return True
    except ClientError as e:
        logger.error(f"Cognito confirm_sign_up error: {e}")
        raise ValueError(e.response["Error"]["Message"])


# ── Sign In ──

def sign_in(email: str, password: str) -> dict:
    """
    Authenticate user via Cognito USER_PASSWORD_AUTH.
    Returns: {access_token, id_token, refresh_token, expires_in}
    """
    _ensure_enabled("sign_in")
    client = _get_client()
    auth_params = {
        "USERNAME": email,
        "PASSWORD": password,
    }
    secret_hash = _compute_secret_hash(email)
    if secret_hash:
        auth_params["SECRET_HASH"] = secret_hash

    try:
        resp = client.initiate_auth(
            ClientId=settings.cognito_client_id,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters=auth_params,
        )

        # Handle challenges (e.g., NEW_PASSWORD_REQUIRED)
        if resp.get("ChallengeName"):
            return {
                "challenge": resp["ChallengeName"],
                "session": resp["Session"],
                "challenge_parameters": resp.get("ChallengeParameters", {}),
            }

        auth_result = resp["AuthenticationResult"]
        
        # Extract Cognito username from the access token for use in refresh
        cognito_username = None
        try:
            claims = jwt.get_unverified_claims(auth_result["AccessToken"])
            cognito_username = claims.get("username") or claims.get("sub")
        except Exception:
            pass
        
        return {
            "access_token": auth_result["AccessToken"],
            "id_token": auth_result["IdToken"],
            "refresh_token": auth_result.get("RefreshToken", ""),
            "expires_in": auth_result["ExpiresIn"],
            "token_type": auth_result["TokenType"],
            "cognito_username": cognito_username,
        }
    except ClientError as e:
        code = e.response["Error"]["Code"]
        msg = e.response["Error"]["Message"]
        logger.error(f"Cognito sign_in error: {code} — {msg}")
        raise ValueError(f"{code}: {msg}")


# ── Token Refresh ──

def refresh_tokens(refresh_token: str, cognito_username: str = "", email: str = "") -> dict:
    """Refresh Cognito tokens using refresh_token.
    
    For SECRET_HASH, cognito_username (the Cognito internal UUID) must be used,
    not the email, when the User Pool uses email as username attribute.
    """
    _ensure_enabled("refresh_tokens")
    client = _get_client()
    auth_params = {"REFRESH_TOKEN": refresh_token}
    
    # SECRET_HASH: prefer cognito_username (UUID), fall back to email
    username_for_hash = cognito_username or email
    if username_for_hash:
        secret_hash = _compute_secret_hash(username_for_hash)
        if secret_hash:
            auth_params["SECRET_HASH"] = secret_hash

    try:
        resp = client.initiate_auth(
            ClientId=settings.cognito_client_id,
            AuthFlow="REFRESH_TOKEN_AUTH",
            AuthParameters=auth_params,
        )
        auth_result = resp["AuthenticationResult"]
        return {
            "access_token": auth_result["AccessToken"],
            "id_token": auth_result["IdToken"],
            "expires_in": auth_result["ExpiresIn"],
        }
    except ClientError as e:
        logger.error(f"Cognito refresh error: {e}")
        raise ValueError(e.response["Error"]["Message"])


# ── JWT Verification ──

def _get_jwks() -> dict:
    """Fetch and cache JWKS from Cognito."""
    global _jwks_cache, _jwks_cache_time

    _ensure_enabled("_get_jwks")

    if _jwks_cache and (time.time() - _jwks_cache_time) < JWKS_CACHE_TTL:
        return _jwks_cache

    region = settings.aws_region
    pool_id = settings.cognito_user_pool_id
    url = f"https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/jwks.json"

    try:
        with urlopen(url) as resp:
            _jwks_cache = json.loads(resp.read().decode("utf-8"))
            _jwks_cache_time = time.time()
            return _jwks_cache
    except Exception as e:
        logger.error(f"Failed to fetch Cognito JWKS: {e}")
        raise


def verify_cognito_token(token: str) -> Optional[dict]:
    """
    Verify a Cognito JWT (access_token or id_token).
    Returns decoded claims if valid, None otherwise.
    When COGNITO_ENABLED=false, returns None silently (no AWS traffic).
    """
    if not is_cognito_enabled():
        return None
    try:
        jwks_data = _get_jwks()
        headers = jwt.get_unverified_headers(token)
        kid = headers.get("kid")

        # Find matching key
        key_data = None
        for k in jwks_data.get("keys", []):
            if k["kid"] == kid:
                key_data = k
                break

        if not key_data:
            logger.warning("Cognito JWT kid not found in JWKS")
            return None

        public_key = jwk.construct(key_data)
        message, encoded_sig = token.rsplit(".", 1)
        decoded_sig = base64url_decode(encoded_sig.encode("utf-8"))

        if not public_key.verify(message.encode("utf-8"), decoded_sig):
            logger.warning("Cognito JWT signature verification failed")
            return None

        claims = jwt.get_unverified_claims(token)

        # Verify expiration
        if time.time() > claims.get("exp", 0):
            logger.warning("Cognito JWT expired")
            return None

        # Verify issuer
        region = settings.aws_region
        pool_id = settings.cognito_user_pool_id
        expected_iss = f"https://cognito-idp.{region}.amazonaws.com/{pool_id}"
        if claims.get("iss") != expected_iss:
            logger.warning("Cognito JWT issuer mismatch")
            return None

        return claims

    except Exception as e:
        logger.error(f"Cognito JWT verification error: {e}")
        return None


# ── Admin Operations ──

def admin_create_user(email: str, password: str, full_name: str = "", role: str = "guardian") -> dict:
    """Create a user in Cognito via admin API (for migrating existing users)."""
    _ensure_enabled("admin_create_user")
    client = _get_client()
    attrs = [
        {"Name": "email", "Value": email},
        {"Name": "email_verified", "Value": "true"},
    ]
    if full_name:
        attrs.append({"Name": "name", "Value": full_name})

    try:
        resp = client.admin_create_user(
            UserPoolId=settings.cognito_user_pool_id,
            Username=email,
            UserAttributes=attrs,
            TemporaryPassword=password,
            MessageAction="SUPPRESS",
        )

        # Set permanent password
        client.admin_set_user_password(
            UserPoolId=settings.cognito_user_pool_id,
            Username=email,
            Password=password,
            Permanent=True,
        )

        user_sub = None
        for attr in resp["User"]["Attributes"]:
            if attr["Name"] == "sub":
                user_sub = attr["Value"]
                break

        return {"user_sub": user_sub, "email": email}

    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "UsernameExistsException":
            # User already exists in Cognito — get their sub
            try:
                user_resp = client.admin_get_user(
                    UserPoolId=settings.cognito_user_pool_id,
                    Username=email,
                )
                user_sub = None
                for attr in user_resp["UserAttributes"]:
                    if attr["Name"] == "sub":
                        user_sub = attr["Value"]
                        break
                return {"user_sub": user_sub, "email": email, "already_exists": True}
            except Exception:
                pass
        logger.error(f"Cognito admin_create_user error: {e}")
        raise ValueError(f"{code}: {e.response['Error']['Message']}")


def admin_get_user(email: str) -> Optional[dict]:
    """Get user info from Cognito."""
    if not is_cognito_enabled():
        return None
    client = _get_client()
    try:
        resp = client.admin_get_user(
            UserPoolId=settings.cognito_user_pool_id,
            Username=email,
        )
        attrs = {a["Name"]: a["Value"] for a in resp["UserAttributes"]}
        return {
            "username": resp["Username"],
            "sub": attrs.get("sub"),
            "email": attrs.get("email"),
            "name": attrs.get("name"),
            "status": resp["UserStatus"],
            "enabled": resp["Enabled"],
        }
    except ClientError as e:
        if e.response["Error"]["Code"] == "UserNotFoundException":
            return None
        raise


def global_sign_out(access_token: str):
    """Invalidate all tokens for the user."""
    if not is_cognito_enabled():
        return  # No-op when disabled — local JWT invalidation is the caller's concern
    client = _get_client()
    try:
        client.global_sign_out(AccessToken=access_token)
    except ClientError as e:
        logger.error(f"Cognito global_sign_out error: {e}")
        raise
