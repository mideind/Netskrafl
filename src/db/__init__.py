"""
Database abstraction layer for Netskrafl/Explo.

This package provides a backend-agnostic interface for database operations,
supporting both Google Cloud NDB (Datastore) and PostgreSQL backends.

Request-Scoped Sessions (Recommended):
    # In application startup (main.py):
    from src.db import init_session_manager
    init_session_manager("postgresql", database_url="...")

    # In WSGI/middleware:
    from src.db import db_wsgi_middleware
    app.wsgi_app = db_wsgi_middleware(app.wsgi_app)

    # In application code:
    from src.db import get_db
    db = get_db()
    user = db.users.get_by_id("user-123")
    # Changes committed at request end

Legacy Usage (for backward compatibility):
    from src.db import get_backend
    db = get_backend()
    user = db.users.get_by_id("user-123")
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .protocols import DatabaseBackendProtocol

# Import session management functions
from .session import (
    SessionManager,
    init_session_manager,
    get_session_manager,
    get_db,
    db_wsgi_middleware,
    request_context,
)

# Cache the backend instance (for legacy get_backend() function)
_backend_instance: "DatabaseBackendProtocol | None" = None


def get_backend(force_new: bool = False) -> "DatabaseBackendProtocol":
    """Get the configured database backend.

    NOTE: This function is provided for backward compatibility.
    For new code, prefer using get_db() with request-scoped sessions.

    The backend is determined by the DATABASE_BACKEND environment variable:
    - "ndb" (default): Google Cloud NDB/Datastore
    - "postgresql": PostgreSQL with SQLAlchemy

    Args:
        force_new: If True, create a new instance even if one is cached.

    Returns:
        DatabaseBackendProtocol: The configured database backend instance.
    """
    global _backend_instance

    if _backend_instance is not None and not force_new:
        return _backend_instance

    backend_name = os.environ.get("DATABASE_BACKEND", "ndb").lower()

    backend: DatabaseBackendProtocol
    if backend_name == "postgresql":
        from .postgresql import PostgreSQLBackend

        backend = PostgreSQLBackend()
    else:
        from .ndb import NDBBackend

        backend = NDBBackend()

    _backend_instance = backend
    return backend


def reset_backend() -> None:
    """Reset the cached backend instance.

    Useful for testing when you need to switch backends.
    """
    global _backend_instance
    if _backend_instance is not None:
        _backend_instance.close()
        _backend_instance = None


__all__ = [
    # Session management (recommended)
    "SessionManager",
    "init_session_manager",
    "get_session_manager",
    "get_db",
    "db_wsgi_middleware",
    "request_context",
    # Legacy (backward compatibility)
    "get_backend",
    "reset_backend",
]
