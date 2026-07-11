# Database Session Configuration
import os
import ssl
from typing import AsyncGenerator, Optional

import asyncpg
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.config import settings


def _effective_dsn() -> str:
    """Pick the DSN at process boot time.

    Priority:
      1. `SUPABASE_DSN` env var — set via Emergent Secrets during the
         May 2026 Mumbai cutover. Override mechanism because Emergent's
         dashboard does not allow editing an existing secret (`DATABASE_URL`).
      2. `DATABASE_URL` from `.env` / settings — the original value.

    Removing the `SUPABASE_DSN` secret reverts the backend to the
    `.env` value on next supervisor restart. Zero credential touches
    `/app/backend/.env` on disk.
    """
    return (os.environ.get("SUPABASE_DSN") or "").strip() or settings.database_url


DATABASE_URL = _effective_dsn()

# Convert postgres:// to postgresql+asyncpg:// for SQLAlchemy async
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Remove sslmode from URL (asyncpg uses 'ssl' parameter instead)
# and handle it via connect_args
if "sslmode=" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.split("?")[0]

# SSL context: encryption-required, chain not verified.
# Matches libpq `sslmode=require` semantics — same posture psql and the
# Step 7 migration smoke test used. Supabase's pooler at
# `*.pooler.supabase.com` presents a self-signed leaf certificate that
# Python's default CA bundle does not trust; cert chain verification would
# break the connection. Connection is still TLS-encrypted on the wire.
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

# Create async engine with production-grade connection pooling
#
# asyncpg `timeout` / `command_timeout` rationale (June 2026 hardening) —
# under Supabase pooler pressure the default asyncpg connect timeout of
# 60s caused tens of seconds of event-loop starvation: every scheduler
# job that tried to acquire a fresh connection waited the full 60s
# before giving up, blocking the loop for unrelated probes (e.g. the
# synthetic monitor) that share the same loop. The new values fail
# fast (`timeout=10s`) and cap any single query at `command_timeout=30s`
# so a stuck transaction can't wedge the loop indefinitely.
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=20,
    max_overflow=10,
    pool_timeout=15,
    pool_recycle=1800,
    pool_pre_ping=True,
    connect_args={
        "ssl": _ssl_ctx,
        # pgbouncer transaction-mode (Supabase port 6543) reuses physical
        # backend connections across queries — prepared statements created
        # in one query may not exist on the next backend. Disable both the
        # asyncpg statement cache AND its prepared-statement reuse to keep
        # SQLAlchemy compatible with transaction-pooling.
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        # Fail-fast guards. Without these asyncpg uses 60s connect and no
        # query cap, which under network blips causes 60s event-loop
        # stalls in every scheduler tick.
        "timeout": 10,
        "command_timeout": 30,
        "server_settings": {
            # Hard limit on transaction wall time at the Postgres side —
            # so a stuck SELECT in a scheduler can't sit forever holding
            # a backend slot.
            "idle_in_transaction_session_timeout": "30000",  # ms
            "statement_timeout": "30000",                    # ms
        },
    },
)

# Create async session factory
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting async database session."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# Raw asyncpg pool — for callers that need direct PostGIS / pgvector access
# without the SQLAlchemy ORM layer (e.g. SF-02 ST_Within hot path, bulk
# GeoJSON loaders). Mirrors the SSL posture of the SQLAlchemy engine.
_pg_pool: Optional[asyncpg.Pool] = None


async def get_db_pool() -> asyncpg.Pool:
    """Lazily-initialised asyncpg connection pool.

    Returns the singleton pool, creating it on first call. Same SSL context
    as the SQLAlchemy engine (`check_hostname=False, verify_mode=CERT_NONE`)
    so Supabase pooler's self-signed leaf is accepted.
    """
    global _pg_pool
    if _pg_pool is None:
        dsn = _effective_dsn().split("?")[0]
        _pg_pool = await asyncpg.create_pool(
            dsn,
            min_size=2,
            max_size=10,
            ssl=_ssl_ctx,
            statement_cache_size=0,  # pgbouncer transaction-pooling safe
            timeout=10,              # connect fail-fast (default 60s)
            command_timeout=30,      # cap any single statement
        )
    return _pg_pool
