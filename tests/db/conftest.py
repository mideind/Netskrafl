"""
Pytest configuration and fixtures for database backend tests.

This module provides fixtures that enable running the same tests against
both NDB and PostgreSQL backends, as well as comparison testing mode.

Usage:
    # Run tests against NDB only
    pytest tests/db/ --backend=ndb

    # Run tests against PostgreSQL only
    pytest tests/db/ --backend=postgresql

    # Run tests against both backends
    pytest tests/db/ --backend=both

    # Run comparison tests (execute on both and compare)
    pytest tests/db/ --compare
"""

from __future__ import annotations

import os
import pytest
from typing import Iterator, TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add command-line options for backend selection."""
    parser.addoption(
        "--backend",
        action="store",
        default="ndb",
        choices=["ndb", "postgresql", "both"],
        help="Database backend to test: ndb, postgresql, or both",
    )
    parser.addoption(
        "--compare",
        action="store_true",
        default=False,
        help="Run comparison tests (execute on both backends and compare results)",
    )


def get_requested_backends(config: pytest.Config) -> list[str]:
    """Get list of backends to test based on command-line option."""
    backend = config.getoption("--backend")
    if backend == "both":
        return ["ndb", "postgresql"]
    return [str(backend)]


def _create_ndb_backend() -> "DatabaseBackendProtocol":
    """Create an NDB backend instance for testing."""
    # Import here to avoid loading NDB dependencies when not needed
    from src.db.ndb import NDBBackend

    return NDBBackend()


# Global NDB context manager for the test session
_ndb_context = None


def _ensure_ndb_context():
    """Ensure we have an active NDB context for the test session."""
    global _ndb_context
    if _ndb_context is None:
        import skrafldb
        _ndb_context = skrafldb.Client.get_context()
        _ndb_context.__enter__()
    return _ndb_context


def _create_postgresql_backend(
    database_url: str | None = None,
) -> "DatabaseBackendProtocol":
    """Create a PostgreSQL backend instance for testing."""
    from src.db.postgresql import PostgreSQLBackend

    # Use test database URL from environment or default
    url = database_url or os.environ.get(
        "DATABASE_URL",
        "postgresql://test:test@localhost:5432/netskrafl_test",
    )
    return PostgreSQLBackend(database_url=url)


@pytest.fixture(scope="session")
def _reset_postgresql_tables() -> Iterator[None]:
    """Session-scoped fixture that resets PostgreSQL tables once per test session.

    This fixture is automatically used by all PostgreSQL-related fixtures.
    It drops and recreates all tables to ensure a clean state.
    """
    from src.db.postgresql import PostgreSQLBackend

    url = os.environ.get(
        "DATABASE_URL",
        "postgresql://test:test@localhost:5432/netskrafl_test",
    )

    # Reset tables at session start
    try:
        db = PostgreSQLBackend(database_url=url)
        db.drop_tables()
        db.create_tables()
        db.close()
    except Exception:
        pass  # PostgreSQL may not be available

    yield


@pytest.fixture(params=["ndb", "postgresql"])
def backend(
    request: pytest.FixtureRequest, _reset_postgresql_tables: None
) -> Iterator["DatabaseBackendProtocol"]:
    """Fixture that provides each database backend.

    Tests using this fixture run twice: once with NDB, once with PostgreSQL.
    Use --backend option to limit which backends to test.

    Example:
        def test_create_user(backend):
            user = backend.users.create(...)
            assert backend.users.get_by_id(user.key_id) is not None
    """
    backend_name: str = request.param
    config = request.config

    # Skip if not in requested backends
    requested = get_requested_backends(config)
    if backend_name not in requested:
        pytest.skip(f"Skipping {backend_name} backend (not in --backend={config.getoption('--backend')})")

    # Create backend instance
    if backend_name == "ndb":
        try:
            # Ensure NDB context is active
            _ensure_ndb_context()
            db = _create_ndb_backend()
        except NotImplementedError:
            pytest.skip("NDB backend not yet implemented")
            return  # type: ignore[return-value]
    else:
        try:
            db = _create_postgresql_backend()
        except NotImplementedError:
            pytest.skip("PostgreSQL backend not yet implemented")
            return  # type: ignore[return-value]

    yield db

    # Cleanup
    db.close()


@pytest.fixture
def ndb_backend(request: pytest.FixtureRequest) -> Iterator["DatabaseBackendProtocol"]:
    """Fixture that provides only the NDB backend.

    Use this for NDB-specific tests.
    """
    try:
        _ensure_ndb_context()
        db = _create_ndb_backend()
    except NotImplementedError:
        pytest.skip("NDB backend not yet implemented")
        return  # type: ignore[return-value]

    yield db
    db.close()


@pytest.fixture
def pg_backend(
    request: pytest.FixtureRequest, _reset_postgresql_tables: None
) -> Iterator["DatabaseBackendProtocol"]:
    """Fixture that provides only the PostgreSQL backend.

    Use this for PostgreSQL-specific tests.
    """
    try:
        db = _create_postgresql_backend()
    except NotImplementedError:
        pytest.skip("PostgreSQL backend not yet implemented")
        return  # type: ignore[return-value]

    yield db
    db.close()


@pytest.fixture
def both_backends(
    request: pytest.FixtureRequest, _reset_postgresql_tables: None
) -> Iterator[Tuple["DatabaseBackendProtocol", "DatabaseBackendProtocol"]]:
    """Fixture for comparison tests - provides both backends simultaneously.

    This fixture is only available when running with --compare flag.

    Example:
        def test_equivalence(both_backends):
            ndb, pg = both_backends
            # Run same operation on both and compare
    """
    if not request.config.getoption("--compare"):
        pytest.skip("Comparison tests require --compare flag")

    try:
        _ensure_ndb_context()
        ndb = _create_ndb_backend()
    except NotImplementedError:
        pytest.skip("NDB backend not yet implemented for comparison")
        return  # type: ignore[return-value]

    try:
        pg = _create_postgresql_backend()
    except NotImplementedError:
        pytest.skip("PostgreSQL backend not yet implemented for comparison")
        return  # type: ignore[return-value]

    yield (ndb, pg)

    ndb.close()
    pg.close()


@pytest.fixture
def clean_backend(
    backend: "DatabaseBackendProtocol",
) -> Iterator["DatabaseBackendProtocol"]:
    """Fixture that provides a backend with transaction rollback for cleanup.

    Use this for tests that modify data - changes will be rolled back.

    Example:
        def test_create_and_delete(clean_backend):
            # All changes here will be rolled back after the test
            user = clean_backend.users.create(...)
    """
    # Begin transaction that will be rolled back
    # Note: This assumes the backend supports transactions
    # For NDB, we may need different cleanup strategy
    try:
        ctx = backend.transaction()
        ctx.__enter__()
    except NotImplementedError:
        # If transactions not supported, just yield the backend
        yield backend
        return

    try:
        yield backend
    finally:
        # Rollback to restore clean state
        # Note: We don't call __exit__ with exc_info to trigger rollback
        try:
            ctx.__exit__(Exception, Exception("rollback"), None)
        except Exception:
            pass  # Rollback may fail if no real transaction


# =============================================================================
# Markers
# =============================================================================


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "ndb_only: mark test to run only with NDB backend",
    )
    config.addinivalue_line(
        "markers",
        "postgresql_only: mark test to run only with PostgreSQL backend",
    )
    config.addinivalue_line(
        "markers",
        "comparison: mark test as requiring both backends for comparison",
    )
