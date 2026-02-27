"""
PostgreSQL backend implementation using SQLAlchemy ORM.

This package provides the PostgreSQL implementation of the database
protocol interface.
"""

from __future__ import annotations

from .backend import PostgreSQLBackend

__all__ = ["PostgreSQLBackend"]
