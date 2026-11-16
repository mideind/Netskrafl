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



# =============================================================================
# Retrying to open a connection
# =============================================================================


class FakeOperationalError(Exception):
    """Stands in for the DBAPI's OperationalError"""


class FakeDbapi:
    OperationalError = FakeOperationalError


class FakeDialect:
    """A dialect whose connect() fails a given number of times,
    each attempt taking a given time on the fake clock"""

    loaded_dbapi = FakeDbapi

    def __init__(self, clock: "FakeClock", failures: int, attempt_seconds: float = 0.0):
        self.clock = clock
        self.failures = failures
        self.attempt_seconds = attempt_seconds
        self.attempts = 0

    def connect(self, *cargs: object, **cparams: object) -> str:
        self.attempts += 1
        self.clock.now += self.attempt_seconds
        if self.attempts <= self.failures:
            raise FakeOperationalError("Connection refused")
        return "a connection"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.pauses: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.pauses.append(seconds)
        self.now += seconds


def make_retry(clock: FakeClock, retry_seconds: float = 10.0):  # type: ignore[no-untyped-def]
    from src.db.postgresql.connection import ConnectRetry

    return ConnectRetry(retry_seconds, clock=clock, sleep=clock.sleep)


def db_connect_events(caplog) -> list[str]:  # type: ignore[no-untyped-def]
    return [
        r.json_fields["outcome"]
        for r in caplog.records
        if getattr(r, "json_fields", {}).get("event") == "db_connect"
    ]


def test_connect_without_trouble_is_not_delayed(caplog) -> None:  # type: ignore[no-untyped-def]
    clock = FakeClock()
    dialect = FakeDialect(clock, failures=0)
    assert make_retry(clock)(dialect, None, (), {}) == "a connection"
    assert dialect.attempts == 1
    assert clock.pauses == []
    assert db_connect_events(caplog) == []


def test_connect_is_retried_while_the_server_refuses(caplog) -> None:  # type: ignore[no-untyped-def]
    """A server that refuses connections for a few seconds (as the managed
    database did for ten seconds on 2026-11-16) costs the request those
    seconds, not an error."""
    import logging

    clock = FakeClock()
    dialect = FakeDialect(clock, failures=5)
    retry = make_retry(clock)
    with caplog.at_level(logging.WARNING):
        assert retry(dialect, None, (), {}) == "a connection"
    assert dialect.attempts == 6
    # The pauses grow, up to a limit
    assert clock.pauses == [0.25, 0.5, 1.0, 2.0, 2.0]
    assert not retry.down
    assert db_connect_events(caplog) == ["retrying", "recovered"]


def test_connect_gives_up_after_the_retry_period(caplog) -> None:  # type: ignore[no-untyped-def]
    """A server that stays unreachable is considered down: the attempt
    fails after the retry period, and later attempts fail at once, so that
    requests do not pile up on the worker threads during a long outage.
    The first connection that opens ends that state."""
    import logging

    import pytest

    clock = FakeClock()
    dialect = FakeDialect(clock, failures=1000)
    retry = make_retry(clock, retry_seconds=10.0)
    with caplog.at_level(logging.WARNING):
        t0 = clock.now
        with pytest.raises(FakeOperationalError):
            retry(dialect, None, (), {})
        # It kept trying for the retry period, and no longer
        assert 10.0 <= clock.now - t0 < 10.5
        assert retry.down
        first_attempts = dialect.attempts
        assert first_attempts > 3

        # While the server is down, an attempt is made once and fails at once
        t1 = clock.now
        with pytest.raises(FakeOperationalError):
            retry(dialect, None, (), {})
        assert dialect.attempts == first_attempts + 1
        assert clock.now == t1

        # The server answers again
        dialect.failures = 0
        assert retry(dialect, None, (), {}) == "a connection"
        assert not retry.down
    # Going down is logged once, not for every request that fails
    assert db_connect_events(caplog) == ["retrying", "down", "recovered"]


def test_connect_attempts_that_hang_use_up_the_period() -> None:
    """If each attempt runs into the connect timeout (a server that does
    not answer at all), the retry period still bounds the total wait."""
    import pytest

    clock = FakeClock()
    dialect = FakeDialect(clock, failures=1000, attempt_seconds=5.0)
    retry = make_retry(clock, retry_seconds=10.0)
    t0 = clock.now
    with pytest.raises(FakeOperationalError):
        retry(dialect, None, (), {})
    assert dialect.attempts == 2
    assert clock.now - t0 <= 10.5


def test_other_errors_are_not_retried() -> None:
    import pytest

    class BrokenDialect(FakeDialect):
        def connect(self, *cargs: object, **cparams: object) -> str:
            self.attempts += 1
            raise ValueError("a programming error")

    clock = FakeClock()
    dialect = BrokenDialect(clock, failures=0)
    retry = make_retry(clock)
    with pytest.raises(ValueError):
        retry(dialect, None, (), {})
    assert dialect.attempts == 1
    assert clock.pauses == []
    assert not retry.down


def test_engine_retries_a_refused_connection(
    pg_backend: "DatabaseBackendProtocol", monkeypatch, caplog  # type: ignore[no-untyped-def]
) -> None:
    """The retry is in place in a real engine: its first two attempts to
    connect are refused, and the caller gets a working connection."""
    import logging

    import psycopg2

    from src.db.config import get_config, DEFAULT_TEST_DATABASE_URL
    from src.db.postgresql import connection as connection_module

    url = get_config().get_database_url(DEFAULT_TEST_DATABASE_URL)
    assert url is not None
    monkeypatch.setattr(connection_module.ConnectRetry, "FIRST_PAUSE", 0.01)
    real_connect = psycopg2.connect
    calls = {"n": 0}

    def flaky_connect(*args: object, **kwargs: object) -> object:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise psycopg2.OperationalError("Connection refused")
        # The engine passes its connect timeout on to the driver
        assert kwargs.get("connect_timeout") == get_config().connect_timeout
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(psycopg2, "connect", flaky_connect)
    engine = connection_module.create_db_engine(url, pool_size=1, max_overflow=0)
    try:
        with caplog.at_level(logging.WARNING):
            with engine.connect() as conn:
                assert conn.execute(text("SELECT 1")).scalar_one() == 1
        assert calls["n"] == 3
        assert db_connect_events(caplog) == ["retrying", "recovered"]
    finally:
        engine.dispose()
