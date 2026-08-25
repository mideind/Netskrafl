"""
Alembic migration environment for the PostgreSQL backend.

The target metadata is the SQLAlchemy Base from
src/db/postgresql/models.py. The database URL is read from the
DATABASE_URL environment variable, falling back to the DatabaseConfig
defaults (src/db/config.py). No application config (secrets,
credentials) is required to run migrations.
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context

# Imported via prepend_sys_path = . src in alembic.ini
from db.config import get_config
from db.postgresql.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """Return the database URL from the environment/config."""
    url = get_config().database_url
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set; refusing to run migrations "
            "against an unknown database"
        )
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode: emit SQL to stdout."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode: connect and execute."""
    connectable = create_engine(
        _database_url(),
        poolclass=pool.NullPool,
        connect_args={"options": "-c timezone=utc"},
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

