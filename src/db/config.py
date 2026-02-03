"""
Database configuration settings.

This module provides configuration for database backends, reading from
environment variables with sensible defaults.
"""

from __future__ import annotations

import os
from typing import Optional
from dataclasses import dataclass


@dataclass
class DatabaseConfig:
    """Database configuration settings."""

    # Backend selection: "ndb" or "postgresql"
    backend: str

    # PostgreSQL connection URL (only used when backend="postgresql")
    # Format: postgresql://user:password@host:port/database
    database_url: Optional[str]

    # Connection pool settings for PostgreSQL
    pool_size: int
    max_overflow: int
    pool_timeout: int
    pool_recycle: int

    # Echo SQL statements (for debugging)
    echo_sql: bool

    @classmethod
    def from_env(cls) -> DatabaseConfig:
        """Create configuration from environment variables."""
        return cls(
            backend=os.environ.get("DATABASE_BACKEND", "ndb").lower(),
            database_url=os.environ.get("DATABASE_URL"),
            pool_size=int(os.environ.get("DB_POOL_SIZE", "5")),
            max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "10")),
            pool_timeout=int(os.environ.get("DB_POOL_TIMEOUT", "30")),
            pool_recycle=int(os.environ.get("DB_POOL_RECYCLE", "1800")),
            echo_sql=os.environ.get("DB_ECHO_SQL", "").lower() in ("1", "true", "yes"),
        )


# Global configuration instance
_config: Optional[DatabaseConfig] = None


def get_config() -> DatabaseConfig:
    """Get the database configuration, initializing from environment if needed."""
    global _config
    if _config is None:
        _config = DatabaseConfig.from_env()
    return _config


def set_config(config: DatabaseConfig) -> None:
    """Set the database configuration (useful for testing)."""
    global _config
    _config = config
