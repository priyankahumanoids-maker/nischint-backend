import asyncio
import sys
import os

sys.path.insert(0, os.getcwd())

from app.db.session import engine
from app.db.base import Base
import app.models.monitored_route
from sqlalchemy import text

async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("""
            ALTER TABLE monitored_routes 
            ADD COLUMN IF NOT EXISTS created_by_guardian_id UUID REFERENCES users(id) ON DELETE SET NULL;
        """))
    print("[DB_INIT] monitored_routes table and created_by_guardian_id column verified in PostgreSQL!")

if __name__ == "__main__":
    asyncio.run(main())
