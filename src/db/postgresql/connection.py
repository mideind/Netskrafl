"""
PostgreSQL connection management using SQLAlchemy.

This module provides database engine creation for the PostgreSQL backend.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from ..config import get_config


def create_db_engine(
    database_url: Optional[str] = None,
    pool_size: Optional[int] = None,
    max_overflow: Optional[int] = None,
    pool_timeout: Optional[int] = None,
    pool_recycle: Optional[int] = None,
    echo: Optional[bool] = None,
) -> Engine:
    """Create a SQLAlchemy engine with connection pooling.

    All parameters default to values from DatabaseConfig if not provided.

    Args:
        database_url: PostgreSQL connection URL.
        pool_size: Number of connections to keep in the pool.
        max_overflow: Maximum overflow connections beyond pool_size.
        pool_timeout: Seconds to wait for a connection from the pool.
        pool_recycle: Seconds after which to recycle connections.
        echo: If True, log all SQL statements.

    Returns:
        SQLAlchemy Engine instance.
    """
    config = get_config()
    url = database_url or config.database_url
    if not url:
        raise ValueError(
            "DATABASE_URL environment variable not set. "
            "Expected format: postgresql://user:password@host:port/database"
        )

    engine = create_engine(
        url,
        pool_size=pool_size if pool_size is not None else config.pool_size,
        max_overflow=max_overflow if max_overflow is not None else config.max_overflow,
        pool_timeout=pool_timeout if pool_timeout is not None else config.pool_timeout,
        pool_recycle=pool_recycle if pool_recycle is not None else config.pool_recycle,
        echo=echo if echo is not None else config.echo_sql,
        # Ensure all connections use UTC timezone
        connect_args={
            "options": "-c timezone=utc"
        },
    )

    # Set timezone on each connection checkout
    @event.listens_for(engine, "connect")
    def set_timezone(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("SET TIME ZONE 'UTC'")
        cursor.close()

    return engine
