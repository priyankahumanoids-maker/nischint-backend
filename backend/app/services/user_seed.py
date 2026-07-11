"""Idempotent seed of operational accounts.

Runs once at backend startup. INSERTS missing accounts; never updates an
existing row. This means:

  * If `operator@nischint.com` is missing in prod (which is why the user
    couldn't log in), we create it with the documented password.
  * If admin / mother / child are already present (which is the prod
    norm — admin was the first account created), we leave them alone.
    No risk of clobbering a password the user has rotated.

Passwords are read from env vars first; documented defaults are used as
fallbacks. Operators rotating the seed password should set the env var
*before* the next deploy:

    SEED_OPERATOR_PASSWORD=<new-strong-password>

If a seed user already exists with a *different* password than the
default/env, this script does NOT touch it. To force a reset of an
existing seeded password, delete the row first or use the regular
auth/admin tooling.

Logged behaviour:
  [USER_SEED] created email=operator@nischint.com role=operator
  [USER_SEED] skipped email=admin@... (already present)
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.user_service import hash_password

logger = logging.getLogger(__name__)


# ── Defaults: documented in /app/memory/test_credentials.md ─────────
SEED_USERS: list[dict] = [
    {
        "email_env":    "SEED_OPERATOR_EMAIL",
        "password_env": "SEED_OPERATOR_PASSWORD",
        "default_email":    "operator@nischint.com",
        "default_password": "OperatorSecure!2026",
        "role":             "operator",
        "full_name":        "Operator NISCHINT",
    },
    {
        "email_env":    "SEED_ADMIN_EMAIL",
        "password_env": "SEED_ADMIN_PASSWORD",
        "default_email":    "nischint4parents@gmail.com",
        "default_password": "secret123",
        "role":             "admin",
        "full_name":        "Admin Nischint",
    },
    {
        "email_env":    "SEED_MOTHER_EMAIL",
        "password_env": "SEED_MOTHER_PASSWORD",
        "default_email":    "mothernischint@gmail.com",
        "default_password": "nischint123",
        "role":             "guardian",
        "full_name":        "Mother Nischint",
    },
    {
        "email_env":    "SEED_CHILD_EMAIL",
        "password_env": "SEED_CHILD_PASSWORD",
        "default_email":    "kidnischint@gmail.com",
        "default_password": "nischint123",
        "role":             "child",
        "full_name":        "Kid Nischint",
    },
]


async def seed_operational_accounts(session: AsyncSession) -> dict:
    """Insert missing operational accounts. Returns a small report."""
    created: list[str] = []
    skipped: list[str] = []
    errors:  list[str] = []

    for spec in SEED_USERS:
        email = (os.environ.get(spec["email_env"]) or spec["default_email"]).strip().lower()
        if not email:
            continue
        try:
            existing = (await session.execute(
                select(User).where(User.email == email)
            )).scalar_one_or_none()
            if existing is not None:
                skipped.append(email)
                logger.info(f"[USER_SEED] skipped email={email} (already present)")
                continue

            password = os.environ.get(spec["password_env"]) or spec["default_password"]
            user = User(
                id=uuid.uuid4(),
                email=email,
                password_hash=hash_password(password),
                role=spec["role"],
                full_name=spec["full_name"],
                created_at=datetime.now(timezone.utc),
            )
            session.add(user)
            await session.flush()
            created.append(email)
            logger.warning(
                f"[USER_SEED] created email={email} role={spec['role']} "
                f"(password from {'env' if os.environ.get(spec['password_env']) else 'default'})"
            )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{email}: {type(e).__name__}: {e}")
            logger.error(f"[USER_SEED] FAILED email={email}: {e}")

    if created:
        await session.commit()

    return {
        "created": created,
        "skipped": skipped,
        "errors":  errors,
    }


__all__ = ["seed_operational_accounts"]
