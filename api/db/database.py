"""
Database configuration and session management.
"""

import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from api.db.models import Base
import logging

logger = logging.getLogger(__name__)


class DatabaseConfig:
    """Database configuration."""
    
    DATABASE_URL = (
        os.getenv("DATABASE_URL")
        or os.getenv("DB_EXTERNAL_LINK")
        or os.getenv("DB_INTERNAL_LINK")
        or "postgresql+asyncpg://user:password@localhost/mega_ai"
    )


def _normalize_db_url(db_url: str) -> str:
    """Normalize postgres URLs to the asyncpg dialect if needed."""
    if db_url.startswith("postgresql://"):
        return db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if db_url.startswith("postgres://"):
        return db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    return db_url


def _database_url_candidates() -> list[tuple[str, str]]:
    """Return database URL candidates in preferred probe order."""
    candidates: list[tuple[str, str]] = []

    for source, env_name in (
        ("DATABASE_URL", "DATABASE_URL"),
        ("DB_EXTERNAL_LINK", "DB_EXTERNAL_LINK"),
        ("DB_INTERNAL_LINK", "DB_INTERNAL_LINK"),
    ):
        value = os.getenv(env_name)
        if value:
            candidates.append((source, _normalize_db_url(value)))

    if not candidates:
        candidates.append(("default", DatabaseConfig.DATABASE_URL))

    return candidates


async def init_db():
    """Initialize database and create tables."""
    engine = create_async_engine(
        DatabaseConfig.DATABASE_URL,
        echo=False,
        future=True
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    await engine.dispose()
    logger.info("Database initialized")


async def probe_db_connection() -> dict:
    """Probe PostgreSQL connectivity using all configured URL candidates."""
    last_error = None

    for source, db_url in _database_url_candidates():
        engine = create_async_engine(
            db_url,
            echo=False,
            future=True,
            pool_pre_ping=True,
        )

        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return {
                "connected": True,
                "source": source,
                "url": db_url,
            }
        except Exception as e:
            last_error = str(e)
            logger.warning(f"Database probe failed for {source}: {e}")
        finally:
            await engine.dispose()

    return {
        "connected": False,
        "source": None,
        "url": None,
        "error": last_error or "Unknown database connection failure",
    }


async def check_db_connection() -> bool:
    """Check whether PostgreSQL is reachable."""
    return (await probe_db_connection())["connected"]


async def get_db_session():
    """Get a database session."""
    engine = create_async_engine(
        DatabaseConfig.DATABASE_URL,
        echo=False,
        future=True
    )
    
    async_session = sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    
    async with async_session() as session:
        yield session
    
    await engine.dispose()


# Global session factory
engine = None
AsyncSessionLocal = None


def setup_db():
    """Setup global database engine and session factory."""
    global engine, AsyncSessionLocal
    # For SQLite (aiosqlite) the engine uses NullPool and does not accept
    # pool_size/max_overflow options. Only pass pooling kwargs for DBs that
    # support them (e.g., asyncpg/Postgres).
    db_url = DatabaseConfig.DATABASE_URL
    engine_kwargs = dict(echo=False, future=True)
    # Treat any sqlite-based URL (e.g. sqlite:// or sqlite+aiosqlite://) as
    # using the NullPool backend which does not accept pool size kwargs.
    if "sqlite" not in db_url:
        engine_kwargs.update(pool_pre_ping=True, pool_size=10, max_overflow=20)

    engine = create_async_engine(db_url, **engine_kwargs)
    
    AsyncSessionLocal = sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    
    logger.info("Database engine setup complete")


async def get_session() -> AsyncSession:
    """Get a database session."""
    if AsyncSessionLocal is None:
        setup_db()
    
    async with AsyncSessionLocal() as session:
        yield session


# Alias for FastAPI dependency injection
get_async_session = get_session
