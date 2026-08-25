"""
PostgreSQL backend implementation using SQLAlchemy ORM.

This package provides the PostgreSQL implementation of the database
protocol interface.

PostgreSQLBackend is imported lazily (PEP 562) so that lightweight
consumers - notably Alembic's migrations/env.py, which only needs
models.Base.metadata - can import db.postgresql.models without pulling
in the repository layer and its application config (which requires
project credentials and secrets at import time).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .backend import PostgreSQLBackend

__all__ = ["PostgreSQLBackend"]


def __getattr__(name: str) -> Any:
    if name == "PostgreSQLBackend":
        from .backend import PostgreSQLBackend

        # Cache in the module namespace so subsequent attribute
        # accesses bypass this hook entirely
        globals()["PostgreSQLBackend"] = PostgreSQLBackend
        return PostgreSQLBackend
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

