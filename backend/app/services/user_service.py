# User Service
import asyncio
from uuid import UUID

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.user import UserCreate

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a plain password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password.

    SYNC variant — keep for legacy callers (tests, scripts, password
    reset flow). For request-path call sites, use `verify_password_async`
    so bcrypt's ~100-300 ms CPU-sync work doesn't block the asyncio
    event loop.

    LT-01 (2026-05-30): under 60 concurrent logins this single call was
    the dominant cause of event-loop saturation (peak loop_lag 2228 ms,
    94.75 % timeout rate).
    """
    return pwd_context.verify(plain_password, hashed_password)


async def verify_password_async(plain_password: str, hashed_password: str) -> bool:
    """Async-safe bcrypt verify — offloads to the default executor.

    Wrapping the sync passlib call in `asyncio.to_thread` lets other
    coroutines (DB lookups, JWT signing, WS heartbeats) interleave
    during the ~100-300 ms bcrypt round. The thread-pool default is
    `min(32, os.cpu_count() + 4)` which is more than enough to absorb
    realistic login bursts.
    """
    return await asyncio.to_thread(pwd_context.verify, plain_password, hashed_password)


async def hash_password_async(password: str) -> str:
    """Async-safe bcrypt hash — same rationale as verify_password_async.
    Use on signup / password-change request paths."""
    return await asyncio.to_thread(pwd_context.hash, password)


async def create_user(session: AsyncSession, user_create: UserCreate) -> User:
    """
    Create a new user with hashed password.
    Raises ValueError if email already exists.
    """
    # Check if email already exists
    existing = await get_user_by_email(session, user_create.email)
    if existing:
        raise ValueError(f"User with email {user_create.email} already exists")

    # Create user with hashed password
    user = User(
        email=user_create.email,
        password_hash=hash_password(user_create.password),
    )

    session.add(user)
    try:
        await session.commit()
        await session.refresh(user)
    except IntegrityError:
        await session.rollback()
        raise ValueError(f"User with email {user_create.email} already exists")

    return user


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    """Get a user by email address."""
    stmt = select(User).where(User.email == email)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: UUID) -> User | None:
    """Get a user by ID."""
    stmt = select(User).where(User.id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_cognito_sub(session: AsyncSession, cognito_sub: str) -> User | None:
    """Get a user by Cognito sub (external ID)."""
    stmt = select(User).where(User.cognito_sub == cognito_sub)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def auto_provision_cognito_user(
    session: AsyncSession,
    cognito_sub: str,
    email: str,
    full_name: str = None,
    phone: str = None,
    role: str = "guardian",
) -> User:
    """
    Auto-provision a local DB user for a Cognito-authenticated user.
    If user with this email exists, link the cognito_sub.
    If not, create a new user.
    """
    # Check if already linked
    existing = await get_user_by_cognito_sub(session, cognito_sub)
    if existing:
        return existing

    # Check if email already exists (link cognito_sub)
    by_email = await get_user_by_email(session, email)
    if by_email:
        by_email.cognito_sub = cognito_sub
        if full_name and not by_email.full_name:
            by_email.full_name = full_name
        await session.flush()
        return by_email

    # Create new user
    user = User(
        email=email,
        password_hash="cognito-managed",
        cognito_sub=cognito_sub,
        role=role,
        full_name=full_name,
        phone=phone,
    )
    session.add(user)
    await session.flush()
    return user
