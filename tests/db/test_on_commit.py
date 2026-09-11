"""
Tests for DatabaseBackendProtocol.on_commit().

Side effects that make clients re-read the database, such as Firebase
move notifications, must not run before the data they announce has been
committed. on_commit() defers a callback until the enclosing transaction
has committed: the request-scoped transaction on PostgreSQL, the
ndb.transactional() function on NDB (immediately when no NDB transaction
is active, since each put() is then already persisted).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

import pytest

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol


def _is_postgresql(backend: "DatabaseBackendProtocol") -> bool:
    from src.db.postgresql import PostgreSQLBackend

    return isinstance(backend, PostgreSQLBackend)


class TestOnCommit:
    """Test deferred post-commit callbacks."""

    def test_runs_once_after_commit(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Callbacks run exactly once, in registration order, by the time
        commit() returns."""
        calls: List[str] = []
        backend.on_commit(lambda: calls.append("a"))
        backend.on_commit(lambda: calls.append("b"))
        if _is_postgresql(backend):
            # Deferred until the request-scoped transaction commits
            assert calls == []
        else:
            # NDB, no transaction active: puts are already persisted,
            # so the callback runs immediately
            assert calls == ["a", "b"]
        backend.commit()
        assert calls == ["a", "b"]
        # A later commit does not run them again
        backend.commit()
        assert calls == ["a", "b"]

    def test_discarded_on_rollback(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """A rolled-back transaction drops its pending callbacks."""
        if not _is_postgresql(backend):
            pytest.skip("Request-level rollback is a no-op on NDB")
        calls: List[str] = []
        backend.on_commit(lambda: calls.append("x"))
        backend.rollback()
        backend.commit()
        assert calls == []

    def test_failing_callback_does_not_block_the_rest(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """The data is committed when the callbacks run, so a failing
        callback is logged and the remaining ones still run."""
        if not _is_postgresql(backend):
            pytest.skip("NDB lets callback exceptions propagate")
        calls: List[str] = []

        def boom() -> None:
            raise RuntimeError("boom")

        backend.on_commit(boom)
        backend.on_commit(lambda: calls.append("after"))
        backend.commit()
        assert calls == ["after"]

    def test_ndb_transaction_defers_until_commit(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Inside an NDB transaction (the production path of
        logic.submit_move()), the callback waits for the commit."""
        if _is_postgresql(backend):
            pytest.skip("NDB only")
        from google.cloud import ndb

        calls: List[str] = []

        def txn() -> None:
            backend.on_commit(lambda: calls.append("committed"))
            # Still inside the transaction: nothing has run yet
            assert calls == []

        ndb.transaction(txn)
        assert calls == ["committed"]

