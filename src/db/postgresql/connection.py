"""
PostgreSQL connection management using SQLAlchemy.

This module provides database engine creation for the PostgreSQL backend.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple

import logging
import threading
import time

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from ..config import get_config


class ConnectRetry:
    """Opens database connections for the pool, and keeps trying for a
    few seconds when the server cannot be reached.

    A managed database is unreachable for some seconds now and then: its
    endpoint refuses connections while the node or the network in front
    of it is being changed, and it drops the existing connections at the
    same time. Without a retry, every request that needs a new connection
    during those seconds fails with a server error (as on 2026-11-16, when
    new connections were refused for ten seconds). With it, such a request
    waits and is then served.

    Only the opening of a connection is retried, before anything has been
    sent on it, so nothing can be done twice.

    If the server stays unreachable for the whole retry period, it is
    considered down: further attempts are made once only and fail at once,
    until one succeeds. Otherwise every request would hold a worker thread
    for the whole period during a long outage, and the health checks, which
    need no database, would starve with them.
    """

    # Pause before the second attempt; doubled for each further one
    FIRST_PAUSE = 0.25
    MAX_PAUSE = 2.0

    def __init__(
        self,
        retry_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._retry_seconds = retry_seconds
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._down = False

    @property
    def down(self) -> bool:
        """True if the server was unreachable for a whole retry period
        and no connection has been opened since"""
        return self._down

    def _set_down(self, down: bool) -> bool:
        """Set the state; return True if it changed"""
        with self._lock:
            changed = self._down != down
            self._down = down
            return changed

    @staticmethod
    def _log(level: int, message: str, **fields: Any) -> None:
        logging.log(
            level, message, extra={"json_fields": dict(event="db_connect", **fields)}
        )

    def __call__(
        self,
        dialect: Any,
        conn_rec: Any,
        cargs: Tuple[Any, ...],
        cparams: Dict[str, Any],
    ) -> Any:
        """Handler of the engine's do_connect event: return a new
        DBAPI connection, or raise the error of the last attempt"""
        retryable = dialect.loaded_dbapi.OperationalError
        t0 = self._clock()
        # While the server is considered down, there is one attempt only
        deadline = t0 + (0.0 if self._down else self._retry_seconds)
        pause = self.FIRST_PAUSE
        failed = 0
        while True:
            try:
                connection = dialect.connect(*cargs, **cparams)
            except retryable as e:
                failed += 1
                remaining = deadline - self._clock()
                if remaining <= 0:
                    if self._set_down(True):
                        self._log(
                            logging.ERROR,
                            f"Database unreachable: gave up after {failed} "
                            f"attempts in {self._clock() - t0:.1f} s; further "
                            f"attempts fail at once until it answers: {e}",
                            outcome="down",
                            attempts=failed,
                        )
                    raise
                if failed == 1:
                    self._log(
                        logging.WARNING,
                        "Database connection failed, retrying for up to "
                        f"{self._retry_seconds:.0f} s: {e}",
                        outcome="retrying",
                    )
                self._sleep(min(pause, remaining))
                pause = min(pause * 2, self.MAX_PAUSE)
            else:
                was_down = self._set_down(False)
                if failed or was_down:
                    self._log(
                        logging.WARNING,
                        f"Database connection opened after {failed} failed "
                        f"attempts, {self._clock() - t0:.1f} s"
                        + (" (the database is reachable again)" if was_down else ""),
                        outcome="recovered",
                        attempts=failed + 1,
                        seconds=round(self._clock() - t0, 2),
                    )
                return connection


def create_db_engine(
    database_url: Optional[str] = None,
    pool_size: Optional[int] = None,
    max_overflow: Optional[int] = None,
    pool_timeout: Optional[int] = None,
    pool_recycle: Optional[int] = None,
    echo: Optional[bool] = None,
) -> Engine:
    """Create a SQLAlchemy engine with connection pooling.

    All parameters default to values from DatabaseConfig if not provided.

    Args:
        database_url: PostgreSQL connection URL.
        pool_size: Number of connections to keep in the pool.
        max_overflow: Maximum overflow connections beyond pool_size.
        pool_timeout: Seconds to wait for a connection from the pool.
        pool_recycle: Seconds after which to recycle connections.
        echo: If True, log all SQL statements.

    Returns:
        SQLAlchemy Engine instance.
    """
    config = get_config()
    url = database_url or config.database_url
    if not url:
        raise ValueError(
            "DATABASE_URL environment variable not set. "
            "Expected format: postgresql://user:password@host:port/database"
        )

    engine = create_engine(
        url,
        pool_size=pool_size if pool_size is not None else config.pool_size,
        max_overflow=max_overflow if max_overflow is not None else config.max_overflow,
        pool_timeout=pool_timeout if pool_timeout is not None else config.pool_timeout,
        pool_recycle=pool_recycle if pool_recycle is not None else config.pool_recycle,
        echo=echo if echo is not None else config.echo_sql,
        # Test each pooled connection with a lightweight ping when it is
        # checked out, and replace it transparently if the server has gone
        # away in the meantime. A managed database closes all connections
        # when it moves to another node (maintenance, failover) or restarts;
        # without the ping, the first request that draws such a stale
        # connection from the pool fails with an OperationalError.
        pool_pre_ping=True,
        connect_args={
            # Ensure all connections use UTC timezone
            "options": "-c timezone=utc",
            # Give up on a single attempt to connect after this many
            # seconds. Without it, an attempt to reach a server that does
            # not answer at all waits for the operating system's timeout,
            # which is minutes.
            "connect_timeout": config.connect_timeout,
        },
    )

    # Keep trying for a few seconds when a connection cannot be opened
    if config.connect_retry_seconds > 0:
        event.listen(engine, "do_connect", ConnectRetry(config.connect_retry_seconds))

    # Set timezone on each connection checkout
    @event.listens_for(engine, "connect")
    def set_timezone(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("SET TIME ZONE 'UTC'")
        cursor.close()

    return engine
