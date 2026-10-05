"""Internal, post-fresh-OTP proof persistence in auth_otps; no public API.

Issuance is an internal trusted primitive AFTER successful fresh OTP verification
in the same transaction, not a substitute for verification or Family permission.
Caller commits proof consumption together with the authorized action/audit.
"""
import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import text

from app.core.auth_foundation_policy import ActionBinding, OTP_TTL_SECONDS, aware


def _identity(binding):
    return hashlib.sha256(("stepup-user:" + str(binding.user_id)).encode()).hexdigest()


def _digest(token):
    return hashlib.sha256(("stepup-proof-v1:" + token).encode()).hexdigest()


async def issue_after_verified_otp(session, *, binding: ActionBinding,
                                   verified_at: datetime, now: datetime) -> str:
    aware(now)
    expires = aware(verified_at) + timedelta(seconds=OTP_TTL_SECONDS)
    if not verified_at <= now < expires:
        raise ValueError("Fresh OTP verification required")
    active = (await session.execute(text("""
        SELECT id FROM auth_sessions WHERE id=:sid AND user_id=:uid
            AND revoked_at IS NULL AND expires_at>:now FOR UPDATE
    """), {"sid": binding.session_id, "uid": binding.user_id, "now": now})).scalar_one_or_none()
    if active is None:
        raise ValueError("Active subject session required")
    token = "stepup1." + secrets.token_urlsafe(32)
    await session.execute(text("""
        INSERT INTO auth_otps (email_hash,purpose,code_digest,attempts,expires_at,
            resend_available_at,proof_user_id,proof_session_id,proof_circle_id,
            proof_target_id,proof_verified_at)
        VALUES (:identity,:purpose,:digest,0,:expires,:now,:uid,:sid,:circle,:target,:verified)
        ON CONFLICT (email_hash,purpose) DO UPDATE SET code_digest=EXCLUDED.code_digest,
            attempts=0, expires_at=EXCLUDED.expires_at, resend_available_at=EXCLUDED.resend_available_at,
            proof_user_id=EXCLUDED.proof_user_id,proof_session_id=EXCLUDED.proof_session_id,
            proof_circle_id=EXCLUDED.proof_circle_id,proof_target_id=EXCLUDED.proof_target_id,
            proof_verified_at=EXCLUDED.proof_verified_at,created_at=:now
    """), {"identity": _identity(binding), "purpose": binding.purpose, "digest": _digest(token),
            "expires": expires, "now": now, "uid": binding.user_id, "sid": binding.session_id,
            "circle": binding.circle_id, "target": binding.target_id, "verified": verified_at})
    return token


async def consume_bound_proof(session, *, token: str, binding: ActionBinding, now: datetime) -> bool:
    aware(now)
    if not token.startswith("stepup1.") or len(token) != 51:
        return False
    # Serialize with revocation at the session row, then atomically consume.
    active = (await session.execute(text("""
        SELECT id FROM auth_sessions WHERE id=:sid AND user_id=:uid
            AND revoked_at IS NULL AND expires_at>:now FOR UPDATE
    """), {"sid": binding.session_id, "uid": binding.user_id, "now": now})).scalar_one_or_none()
    if active is None:
        return False
    result = await session.execute(text("""
        DELETE FROM auth_otps WHERE email_hash=:identity AND purpose=:purpose
            AND code_digest=:digest AND proof_user_id=:uid AND proof_session_id=:sid
            AND proof_circle_id IS NOT DISTINCT FROM CAST(:circle AS UUID)
            AND proof_target_id IS NOT DISTINCT FROM CAST(:target AS UUID)
            AND proof_verified_at<=:now AND expires_at>:now
            AND expires_at<=proof_verified_at + INTERVAL '300 seconds'
        RETURNING email_hash
    """), {"identity": _identity(binding), "purpose": binding.purpose, "digest": _digest(token),
            "uid": binding.user_id, "sid": binding.session_id,
            "circle": binding.circle_id, "target": binding.target_id, "now": now})
    return result.scalar_one_or_none() is not None
