"""
Tests for the RatingArchive repository and the batch/leaderboard helper
operations added for the optimized ratings process:

    * rating_archive.put_archive / get_archive / delete_archive
    * stats.newest_before_multi (including robot keys)
    * users.list_top_elo

These tests run against any backend implementing the DatabaseBackendProtocol.
Use the --backend option to select which backend(s) to test.

Note: against the NDB backend, these tests write to the explo-dev
Datastore; all entities that are created are deleted again on teardown.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from typing import Iterator, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol

UTC = timezone.utc

# A robot level that is not used by any real autoplayer configuration
TEST_ROBOT_LEVEL = 971


def _delete_robot_stats(backend: "DatabaseBackendProtocol", robot_level: int) -> None:
    """Delete robot stats rows created by these tests. There is no
    protocol-level deletion method for robot stats, so this reaches
    into the backend implementations."""
    from src.db.ndb.backend import NDBBackend

    if isinstance(backend, NDBBackend):
        import skrafldb_ndb

        delete_keys = list(
            skrafldb_ndb.StatsModel.query(
                skrafldb_ndb.ndb.AND(
                    skrafldb_ndb.StatsModel.robot_level == robot_level,
                    skrafldb_ndb.StatsModel.user == None,  # noqa: E711
                )
            ).iter(keys_only=True)
        )
        skrafldb_ndb.delete_multi(delete_keys)
    else:
        from sqlalchemy import delete
        from src.db.postgresql.models import Stats
        from src.db.postgresql.backend import PostgreSQLBackend

        assert isinstance(backend, PostgreSQLBackend)
        session = backend._session  # noqa: SLF001 - test-only cleanup
        session.execute(
            delete(Stats).where(
                Stats.user_id.is_(None), Stats.robot_level == robot_level
            )
        )
        session.flush()


class TestRatingArchive:
    """Test the RatingArchive repository operations."""

    KIND = "test-kind"
    DATE = "2020-01-15"

    @pytest.fixture(autouse=True)
    def cleanup_archive(
        self, backend: "DatabaseBackendProtocol"
    ) -> Iterator[None]:
        """Delete the test archive rows after each test."""
        yield
        backend.rating_archive.delete_archive(self.KIND, self.DATE)

    def test_get_missing_returns_none(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Fetching a nonexistent archive returns None."""
        assert backend.rating_archive.get_archive(self.KIND, "1999-12-31") is None

    def test_put_get_roundtrip(self, backend: "DatabaseBackendProtocol") -> None:
        """An archived table can be stored and fetched unchanged."""
        table = json.dumps([{"user": "u1", "elo": 1500, "rank": 1}])
        backend.rating_archive.put_archive(self.KIND, self.DATE, table)
        assert backend.rating_archive.get_archive(self.KIND, self.DATE) == table

    def test_put_overwrites(self, backend: "DatabaseBackendProtocol") -> None:
        """Storing again for the same (kind, date) overwrites the table."""
        backend.rating_archive.put_archive(self.KIND, self.DATE, "[1]")
        backend.rating_archive.put_archive(self.KIND, self.DATE, "[2]")
        assert backend.rating_archive.get_archive(self.KIND, self.DATE) == "[2]"

    def test_keys_are_distinct(self, backend: "DatabaseBackendProtocol") -> None:
        """Tables are keyed by both kind and date."""
        backend.rating_archive.put_archive(self.KIND, self.DATE, "[1]")
        assert backend.rating_archive.get_archive(self.KIND, "2020-01-16") is None
        assert backend.rating_archive.get_archive("other-kind", self.DATE) is None

    def test_delete(self, backend: "DatabaseBackendProtocol") -> None:
        """A deleted archive is no longer fetchable."""
        backend.rating_archive.put_archive(self.KIND, self.DATE, "[1]")
        backend.rating_archive.delete_archive(self.KIND, self.DATE)
        assert backend.rating_archive.get_archive(self.KIND, self.DATE) is None
        # Deleting a nonexistent archive is a no-op
        backend.rating_archive.delete_archive(self.KIND, self.DATE)


class TestNewestBeforeMulti:
    """Test the batch newest_before_multi operation."""

    USER_1 = "nbm-test-user-1"
    USER_2 = "nbm-test-user-2"

    @pytest.fixture(autouse=True)
    def setup_and_cleanup(
        self, backend: "DatabaseBackendProtocol"
    ) -> Iterator[None]:
        """Create test users, per-user stats and robot stats;
        delete them all afterwards."""
        for i, user_id in enumerate((self.USER_1, self.USER_2)):
            if backend.users.get_by_id(user_id) is None:
                backend.users.create(
                    user_id=user_id,
                    account=f"test:nbm{i}",
                    email=None,
                    nickname=f"NbmUser{i}",
                    locale="is_IS",
                )
            backend.stats.create(user_id=user_id)
        # A robot stats row
        backend.stats.create(user_id=None, robot_level=TEST_ROBOT_LEVEL)
        yield
        backend.stats.delete_for_user(self.USER_1)
        backend.stats.delete_for_user(self.USER_2)
        _delete_robot_stats(backend, TEST_ROBOT_LEVEL)
        backend.users.delete(self.USER_1)
        backend.users.delete(self.USER_2)

    def test_results_aligned_with_keys(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Results come back in the same order as the requested keys,
        including robot keys and keys without stored records."""
        future = datetime.now(UTC) + timedelta(hours=1)
        keys: List[Tuple[Optional[str], int]] = [
            (self.USER_2, 0),
            (None, TEST_ROBOT_LEVEL),
            ("nbm-test-nonexistent", 0),
            (self.USER_1, 0),
        ]
        results = backend.stats.newest_before_multi(future, keys)
        assert len(results) == len(keys)
        assert results[0].user_id == self.USER_2
        assert results[1].user_id is None
        assert results[1].robot_level == TEST_ROBOT_LEVEL
        # Nonexistent key yields an unpersisted default record
        assert results[2].user_id == "nbm-test-nonexistent"
        assert results[2].elo == 1200
        assert results[2].games == 0
        assert results[3].user_id == self.USER_1

    def test_matches_newest_before(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """The batch operation returns the same data as individual
        newest_before calls, for both humans and robots."""
        future = datetime.now(UTC) + timedelta(hours=1)
        keys: List[Tuple[Optional[str], int]] = [
            (self.USER_1, 0),
            (None, TEST_ROBOT_LEVEL),
        ]
        multi = backend.stats.newest_before_multi(future, keys)
        for (user_id, robot_level), batched in zip(keys, multi):
            single = backend.stats.newest_before(future, user_id, robot_level)
            assert batched.user_id == single.user_id
            assert batched.robot_level == single.robot_level
            assert batched.elo == single.elo
            assert batched.games == single.games

    def test_respects_timestamp_bound(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Records newer than the cutoff timestamp are not returned."""
        past = datetime.now(UTC) - timedelta(days=365)
        results = backend.stats.newest_before_multi(past, [(self.USER_1, 0)])
        # The only stored record is from now, i.e. after the cutoff,
        # so a default record is returned
        assert results[0].elo == 1200
        assert results[0].games == 0


class TestListTopElo:
    """Test the users.list_top_elo operation."""

    # Elo values high enough to outrank any real data in a shared
    # test datastore
    USERS = [
        ("lte-test-user-1", "test:lte1", 99999, 99997, 99998),
        ("lte-test-user-2", "test:lte2", 99997, 99999, 99997),
        ("lte-test-user-3", "test:lte3", 99998, 99998, 99999),
    ]

    @pytest.fixture(autouse=True)
    def setup_and_cleanup(
        self, backend: "DatabaseBackendProtocol"
    ) -> Iterator[None]:
        """Create test users with distinct Elo ratings;
        delete them afterwards."""
        for user_id, account, elo, human_elo, manual_elo in self.USERS:
            if backend.users.get_by_id(user_id) is None:
                backend.users.create(
                    user_id=user_id,
                    account=account,
                    email=None,
                    nickname=user_id,
                    locale="is_IS",
                )
            user = backend.users.get_by_id(user_id)
            assert user is not None
            backend.users.update(
                user, elo=elo, human_elo=human_elo, manual_elo=manual_elo
            )
        yield
        for user_id, _, _, _, _ in self.USERS:
            backend.users.delete(user_id)

    def _ranking(self, backend: "DatabaseBackendProtocol", kind: str) -> List[str]:
        """Return our test users in the order they appear in the top list."""
        top = backend.users.list_top_elo(kind, 10)
        ours = {u[0] for u in self.USERS}
        return [uid for uid in top if uid in ours]

    def test_list_top_elo_all(self, backend: "DatabaseBackendProtocol") -> None:
        """Users are returned in descending order of 'all' Elo."""
        assert self._ranking(backend, "all") == [
            "lte-test-user-1",
            "lte-test-user-3",
            "lte-test-user-2",
        ]

    def test_list_top_elo_human(self, backend: "DatabaseBackendProtocol") -> None:
        """Users are returned in descending order of human Elo."""
        assert self._ranking(backend, "human") == [
            "lte-test-user-2",
            "lte-test-user-3",
            "lte-test-user-1",
        ]

    def test_list_top_elo_manual(self, backend: "DatabaseBackendProtocol") -> None:
        """Users are returned in descending order of manual Elo."""
        assert self._ranking(backend, "manual") == [
            "lte-test-user-3",
            "lte-test-user-1",
            "lte-test-user-2",
        ]

    def test_limit_is_respected(self, backend: "DatabaseBackendProtocol") -> None:
        """No more than `limit` ids are returned."""
        assert len(backend.users.list_top_elo("all", 2)) == 2
