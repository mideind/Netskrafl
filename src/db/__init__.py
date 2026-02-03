"""
Database abstraction layer for Netskrafl/Explo.

This package provides a backend-agnostic interface for database operations,
supporting both Google Cloud NDB (Datastore) and PostgreSQL backends.

Usage:
    from src.db import get_backend

    db = get_backend()
    user = db.users.get_by_id("user-123")
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from .protocols import DatabaseBackendProtocol

# Cache the backend instance
_backend_instance: "DatabaseBackendProtocol | None" = None


def get_backend(force_new: bool = False) -> "DatabaseBackendProtocol":
    """Get the configured database backend.

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

        backend = cast("DatabaseBackendProtocol", PostgreSQLBackend())
    else:
        from .ndb import NDBBackend

        backend = cast("DatabaseBackendProtocol", NDBBackend())

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


__all__ = ["get_backend", "reset_backend"]
