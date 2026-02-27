"""
Request-scoped database session management.

This module provides a unified interface for managing database sessions
across both NDB and PostgreSQL backends. It handles:

- Backend selection via configuration
- Request-scoped sessions with automatic cleanup
- Transaction boundaries aligned with API request lifecycle
- Backward compatibility with existing NDB code

Transaction Model:
- Each API request operates within an implicit transaction
- put()/create()/update() operations flush to the database but don't commit
- Commit happens automatically at successful request completion
- Rollback happens on any exception

For NDB:
- Each put() is immediately persisted (NDB's natural behavior)
- commit()/rollback() are no-ops for compatibility

For PostgreSQL:
- Changes accumulate in the session
- flush() writes to DB without committing
- commit()/rollback() finalize the transaction
"""

from __future__ import annotations

import logging
from typing import Optional, Any, TYPE_CHECKING, Iterator
from contextlib import contextmanager
from threading import local

from .config import get_config

if TYPE_CHECKING:
    from .protocols import DatabaseBackendProtocol

# Thread-local storage for request-scoped backend instances
_thread_local = local()

# Logger for this module
_log = logging.getLogger(__name__)


class SessionManager:
    """Manages database sessions and backend lifecycle.

    This class provides a unified interface for both NDB and PostgreSQL
    backends, handling session creation, cleanup, and transaction management.

    Usage:
        # Initialize once at application startup
        session_manager = SessionManager("postgresql", database_url="...")

        # In WSGI middleware or Flask hooks
        with session_manager.request_context():
            # All database operations here use the request-scoped session
            backend = session_manager.get_backend()
            user = backend.users.get_by_id("...")

            # On successful completion, changes are committed
            # On exception, changes are rolled back
    """

    def __init__(
        self,
        backend_type: Optional[str] = None,
        database_url: Optional[str] = None,
    ) -> None:
        """Initialize the session manager.

        Args:
            backend_type: Either "ndb" or "postgresql". If not provided,
                          reads from DATABASE_BACKEND environment variable.
            database_url: PostgreSQL connection URL. If not provided,
                          reads from DATABASE_URL environment variable.
        """
        config = get_config()
        self._backend_type = backend_type or config.backend
        self._database_url = database_url or config.database_url
        # Shared sessionmaker for PostgreSQL (created once, used by all requests)
        self._pg_session_factory: Optional[Any] = None

        if self._backend_type == "postgresql":
            if not self._database_url:
                raise ValueError(
                    "DATABASE_URL required for PostgreSQL backend. "
                    "Set via environment or database_url parameter."
                )
            # Create the shared engine and sessionmaker once at startup
            self._init_pg_pool()

    @property
    def backend_type(self) -> str:
        """Get the configured backend type."""
        return self._backend_type

    def _init_pg_pool(self) -> None:
        """Create the shared SQLAlchemy engine and sessionmaker.

        Called once at startup. The engine manages a connection pool
        that is shared across all requests. Each request creates a
        lightweight Session from the shared sessionmaker, which checks
        out a pooled connection.
        """
        from sqlalchemy.orm import sessionmaker
        from .postgresql.connection import create_db_engine

        engine = create_db_engine(self._database_url)
        self._pg_session_factory = sessionmaker(
            bind=engine,
            expire_on_commit=False,
        )

    def _create_backend(self) -> "DatabaseBackendProtocol":
        """Create a new backend instance for the current request."""
        if self._backend_type == "postgresql":
            from .postgresql import PostgreSQLBackend

            return PostgreSQLBackend(session_factory=self._pg_session_factory)
        else:
            from .ndb import NDBBackend

            return NDBBackend()

    def get_backend(self) -> "DatabaseBackendProtocol":
        """Get the request-scoped backend instance.

        Returns the backend instance for the current request/thread.
        Creates one if it doesn't exist.

        Returns:
            The database backend for the current request.
        """
        backend: Optional["DatabaseBackendProtocol"] = getattr(
            _thread_local, "backend", None
        )
        if backend is None:
            backend = self._create_backend()
            _thread_local.backend = backend
        return backend

    def _cleanup_backend(self) -> None:
        """Clean up the request-scoped backend."""
        backend: Optional["DatabaseBackendProtocol"] = getattr(
            _thread_local, "backend", None
        )
        if backend is not None:
            try:
                backend.close()
            except Exception as e:
                _log.warning(f"Error closing backend: {e}")
            finally:
                _thread_local.backend = None

    @contextmanager
    def request_context(self) -> Iterator["DatabaseBackendProtocol"]:
        """Context manager for request-scoped database operations.

        This wraps the entire request lifecycle:
        1. Creates a backend/session for this request
        2. Yields the backend for use
        3. Commits on successful completion
        4. Rolls back on any exception
        5. Cleans up the session

        For NDB, commit/rollback are no-ops since each put() is immediate.

        Yields:
            The database backend for this request.
        """
        backend = self.get_backend()
        success = False
        try:
            yield backend
            success = True
        except Exception:
            try:
                backend.rollback()
            except Exception as e:
                _log.warning(f"Error during rollback: {e}")
            raise
        finally:
            if success:
                try:
                    backend.commit()
                except Exception as e:
                    _log.error(f"Error during commit: {e}")
                    try:
                        backend.rollback()
                    except Exception:
                        pass
                    raise
            self._cleanup_backend()


# Global session manager instance (lazy initialized)
_session_manager: Optional[SessionManager] = None


def init_session_manager(
    backend_type: Optional[str] = None,
    database_url: Optional[str] = None,
) -> SessionManager:
    """Initialize the global session manager.

    Call this once at application startup, before handling any requests.
    If parameters are not provided, they are read from environment variables
    via DatabaseConfig.

    Args:
        backend_type: Either "ndb" or "postgresql". Defaults to DATABASE_BACKEND env var.
        database_url: PostgreSQL connection URL. Defaults to DATABASE_URL env var.

    Returns:
        The initialized SessionManager instance.
    """
    global _session_manager
    _session_manager = SessionManager(
        backend_type=backend_type,
        database_url=database_url,
    )
    _log.info(f"Database session manager initialized with backend: {backend_type}")
    return _session_manager


def get_session_manager() -> SessionManager:
    """Get the global session manager.

    Returns:
        The global SessionManager instance.

    Raises:
        RuntimeError: If init_session_manager() hasn't been called.
    """
    if _session_manager is None:
        raise RuntimeError(
            "Session manager not initialized. "
            "Call init_session_manager() at application startup."
        )
    return _session_manager


def get_db() -> "DatabaseBackendProtocol":
    """Get the database backend for the current request.

    This is the primary entry point for application code to access
    the database. It returns the appropriate backend based on
    configuration.

    Returns:
        The database backend for the current request.

    Raises:
        RuntimeError: If session manager not initialized.

    Example:
        from db.session import get_db

        def my_api_function():
            db = get_db()
            user = db.users.get_by_id(user_id)
            db.users.update(user, elo=new_elo)
            # Changes committed at request end
    """
    return get_session_manager().get_backend()


def db_wsgi_middleware(wsgi_app: Any) -> Any:
    """WSGI middleware that wraps requests with database context.

    This replaces ndb_wsgi_middleware and handles both backends.
    For NDB, it also establishes the NDB client context.

    Args:
        wsgi_app: The WSGI application to wrap.

    Returns:
        Wrapped WSGI application.
    """
    manager = get_session_manager()

    if manager.backend_type == "ndb":
        # For NDB, we also need the client context
        import skrafldb_ndb as skrafldb

        def middleware(environ: Any, start_response: Any) -> Any:
            with skrafldb.Client.get_context():
                with manager.request_context():
                    return wsgi_app(environ, start_response)

        return middleware
    else:
        # For PostgreSQL, just the session context
        def middleware(environ: Any, start_response: Any) -> Any:
            with manager.request_context():
                return wsgi_app(environ, start_response)

        return middleware


# Convenience alias for backward compatibility
def request_context() -> Any:
    """Get a request context manager.

    Returns:
        Context manager for database operations.
    """
    return get_session_manager().request_context()
