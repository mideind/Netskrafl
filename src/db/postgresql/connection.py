"""
PostgreSQL connection management using SQLAlchemy.

This module provides database engine creation, session management,
and transaction handling for the PostgreSQL backend.
"""

from __future__ import annotations

from typing import Iterator, Optional
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session

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


class DatabaseSession:
    """Manages database sessions and transactions.

    This class provides a thread-safe way to manage database sessions
    with proper transaction handling.

    Usage:
        db_session = DatabaseSession(engine)

        # Using context manager (recommended)
        with db_session.session() as session:
            user = session.query(User).first()

        # Using transaction context
        with db_session.transaction() as session:
            session.add(new_user)
            # Auto-commits on success, rolls back on exception
    """

    def __init__(self, engine: Engine) -> None:
        """Initialize with a SQLAlchemy engine."""
        self._engine = engine
        self._session_factory = sessionmaker(
            bind=engine,
            expire_on_commit=False,  # Don't expire objects after commit
        )

    @property
    def engine(self) -> Engine:
        """Get the underlying SQLAlchemy engine."""
        return self._engine

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Get a database session.

        The session is automatically closed when the context exits.
        No automatic commit - use transaction() for that.

        Yields:
            SQLAlchemy Session instance.
        """
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Get a database session with automatic transaction handling.

        Commits on successful exit, rolls back on exception.

        Yields:
            SQLAlchemy Session instance.
        """
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def close(self) -> None:
        """Close the database engine and all connections."""
        self._engine.dispose()


# Global session instance (lazy initialized)
_db_session: Optional[DatabaseSession] = None


def get_db_session(database_url: Optional[str] = None) -> DatabaseSession:
    """Get or create the global database session manager.

    Args:
        database_url: Optional database URL. Only used on first call.

    Returns:
        DatabaseSession instance.
    """
    global _db_session
    if _db_session is None:
        engine = create_db_engine(database_url)
        _db_session = DatabaseSession(engine)
    return _db_session


def reset_db_session() -> None:
    """Reset the global database session (for testing)."""
    global _db_session
    if _db_session is not None:
        _db_session.close()
        _db_session = None
