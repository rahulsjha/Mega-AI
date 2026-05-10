"""
Database configuration and session management.
"""

import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from api.db.models import Base
import logging

logger = logging.getLogger(__name__)


class DatabaseConfig:
    """Database configuration."""
    
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://user:password@localhost/mega_ai"
    )


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
    
    engine = create_async_engine(
        DatabaseConfig.DATABASE_URL,
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20
    )
    
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
