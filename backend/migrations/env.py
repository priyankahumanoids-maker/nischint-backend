import asyncio
from logging.config import fileConfig
import os
from dotenv import load_dotenv

from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config, create_async_engine

from alembic import context

# Load environment variables
load_dotenv()

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Get DATABASE_URL from environment
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Convert postgres:// to postgresql+asyncpg:// for SQLAlchemy async
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Remove sslmode from URL (asyncpg uses 'ssl' parameter instead)
if "sslmode=" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.split("?")[0]

# Set the sqlalchemy.url in config
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
from app.db.base import Base
target_metadata = Base.metadata

# Preserve existing revision values, including the 39-character FC06 stamp.
# TEXT widens storage without truncating installations already using >32 chars.
VERSION_STORAGE_DDL = (
    "CREATE TABLE IF NOT EXISTS alembic_version (version_num TEXT NOT NULL PRIMARY KEY)",
    "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE TEXT",
)

# Either duplicate historical dp01 file may have produced a dp01/dp02 stamp.
# ab1a2b3c4dq01 builds an ack_type index BEFORE FC07, so repair only those
# ambiguous stamps before walking the graph. Fresh/pre-dp01 databases still
# receive their ACK columns from the unchanged original ACK revision.
AMBIGUOUS_ACK_DDL = """
DO $compat$ BEGIN
  IF EXISTS (SELECT 1 FROM alembic_version
             WHERE version_num IN ('aa1a2b3c4dp01','aa1a2b3c4dp02')) THEN
    ALTER TABLE guardian_alerts ADD COLUMN IF NOT EXISTS context_json JSONB NOT NULL DEFAULT '{}'::jsonb;
    ALTER TABLE guardian_alerts ADD COLUMN IF NOT EXISTS ack_type VARCHAR(16);
    ALTER TABLE guardian_alerts ADD COLUMN IF NOT EXISTS seen_deadline TIMESTAMPTZ;
    CREATE INDEX IF NOT EXISTS ix_guardian_alerts_seen_lapse
      ON guardian_alerts(seen_deadline) WHERE ack_type='seen';
  END IF;
END $compat$;
"""


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        for statement in VERSION_STORAGE_DDL:
            context.execute(statement)
        context.execute(AMBIGUOUS_ACK_DDL)
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    with connection.begin():
        for statement in VERSION_STORAGE_DDL:
            connection.execute(text(statement))
        connection.execute(text(AMBIGUOUS_ACK_DDL))
        context.configure(connection=connection, target_metadata=target_metadata)
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    import ssl
    # Match the runtime engine — Supabase pooler presents a self-signed
    # leaf; default CA bundle would reject. Encryption stays on the wire.
    _ssl_ctx = ssl.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = ssl.CERT_NONE

    connectable = create_async_engine(
        DATABASE_URL,
        poolclass=pool.NullPool,
        connect_args={
            "ssl": _ssl_ctx,
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
        },
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
