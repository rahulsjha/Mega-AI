# Migration env.py for Alembic

from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
import os
from api.db.models import Base

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# set the target metadata for 'autogenerate' support
target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    sqlalchemy_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://user:password@localhost/mega_ai"
    )
    
    context.configure(
        url=sqlalchemy_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    # This requires async support
    import asyncio
    
    sqlalchemy_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://user:password@localhost/mega_ai"
    )
    
    # For now, use simple sync approach
    from sqlalchemy import create_engine
    
    engine = create_engine(
        sqlalchemy_url.replace("+asyncpg", ""),  # Use sync driver for migrations
        poolclass=pool.NullPool,
    )

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
