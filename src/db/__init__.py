"""
Database abstraction layer for Netskrafl/Explo.

This package provides a backend-agnostic interface for database operations,
supporting both Google Cloud NDB (Datastore) and PostgreSQL backends.

Usage:
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
"""

from __future__ import annotations

# Import session management functions
from .session import (
    SessionManager,
    init_session_manager,
    get_session_manager,
    get_db,
    db_wsgi_middleware,
    request_context,
)


__all__ = [
    "SessionManager",
    "init_session_manager",
    "get_session_manager",
    "get_db",
    "db_wsgi_middleware",
    "request_context",
]
