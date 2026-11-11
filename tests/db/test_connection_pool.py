"""
Tests for the PostgreSQL connection pool (src/db/postgresql/connection.py).

PostgreSQL only: these tests need a live server, and use a second
connection to it to play the part of the server dropping a connection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol


def test_pool_survives_connections_closed_by_server(
    pg_backend: "DatabaseBackendProtocol",
) -> None:
    """A pooled connection that the server has closed while it sat idle
    (as a managed database does to all connections when it restarts or
    moves to another node) is replaced when it is next checked out, without
    an error reaching the caller."""
    from src.db.config import get_config, DEFAULT_TEST_DATABASE_URL
    from src.db.postgresql.connection import create_db_engine

    url = get_config().get_database_url(DEFAULT_TEST_DATABASE_URL)
    assert url is not None
    # A pool of exactly one connection, so that the next checkout
    # is certain to be handed the connection that was closed
    engine = create_db_engine(url, pool_size=1, max_overflow=0)
    killer = create_db_engine(url, pool_size=1, max_overflow=0)
    try:
        with engine.connect() as conn:
            pid = conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
        # The connection is now idle in the pool: close it from the server
        # side (a role may terminate its own sessions)
        with killer.connect() as conn:
            assert conn.execute(
                text("SELECT pg_terminate_backend(:pid)"), {"pid": pid}
            ).scalar_one()
        # The next checkout must just work, on a fresh connection
        with engine.connect() as conn:
            new_pid = conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
        assert new_pid != pid
    finally:
        engine.dispose()
        killer.dispose()

