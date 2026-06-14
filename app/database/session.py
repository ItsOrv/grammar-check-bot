from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.database.models import Base


def create_engine_and_sessionmaker(db_path: str) -> tuple[AsyncEngine, async_sessionmaker]:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    return engine, async_sessionmaker(engine, expire_on_commit=False)


# Columns added to existing tables after the first release. create_all() only
# makes missing tables, so older DBs need these patched in by hand.
_MIGRATIONS = {
    "chat_settings": {"enabled": "BOOLEAN NOT NULL DEFAULT 1"},
}


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for table, columns in _MIGRATIONS.items():
            rows = await conn.execute(text(f"PRAGMA table_info({table})"))
            existing = {r[1] for r in rows}
            for column, ddl in columns.items():
                if column not in existing:
                    await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
