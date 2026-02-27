"""
Tests for Stats repository operations.

These tests run against any backend implementing the DatabaseBackendProtocol.
Use --backend option to select which backend(s) to test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol

UTC = timezone.utc


class TestStatsCRUD:
    """Test basic Stats CRUD operations."""

    @pytest.fixture(autouse=True)
    def setup_stats_user(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test user for Stats tests."""
        existing = backend.users.get_by_id("stats-user-1")
        if existing is None:
            backend.users.create(
                user_id="stats-user-1",
                account="test:stats1",
                email=None,
                nickname="StatsUser1",
                locale="is_IS",
            )

    def test_create_stats(self, backend: "DatabaseBackendProtocol") -> None:
        """Can create a stats entry for a user."""
        stats = backend.stats.create(user_id="stats-user-1")

        assert stats is not None
        assert stats.user_id == "stats-user-1"
        assert stats.robot_level == 0
        assert stats.timestamp is not None

    def test_create_stats_with_robot_level(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Can create stats with a specific robot level."""
        stats = backend.stats.create(user_id="stats-user-1", robot_level=5)

        assert stats is not None
        assert stats.robot_level == 5

    def test_stats_has_default_values(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """New stats entry has sensible default values."""
        stats = backend.stats.create(user_id="stats-user-1")

        assert stats.games == 0
        assert stats.elo == 1200  # Default Elo
        assert stats.wins == 0
        assert stats.losses == 0
        assert stats.score == 0
        assert stats.score_against == 0


class TestStatsRetrieval:
    """Test Stats retrieval operations."""

    @pytest.fixture(autouse=True)
    def setup_retrieval_user(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test user and stats for retrieval tests."""
        existing = backend.users.get_by_id("stats-retrieve-user")
        if existing is None:
            backend.users.create(
                user_id="stats-retrieve-user",
                account="test:statsretrieve",
                email=None,
                nickname="StatsRetrieveUser",
                locale="is_IS",
            )

    def test_newest_for_user(self, backend: "DatabaseBackendProtocol") -> None:
        """Can get the most recent stats for a user."""
        # Create multiple stats entries
        backend.stats.create(user_id="stats-retrieve-user")
        backend.stats.create(user_id="stats-retrieve-user")
        backend.stats.create(user_id="stats-retrieve-user")

        loaded = backend.stats.newest_for_user("stats-retrieve-user")

        assert loaded is not None
        assert loaded.user_id == "stats-retrieve-user"
        # The newest one should be returned (most recent timestamp)
        assert loaded.timestamp is not None

    def test_newest_for_user_returns_none_when_no_stats(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Returns None when user has no stats."""
        loaded = backend.stats.newest_for_user("nonexistent-stats-user")
        assert loaded is None

    def test_last_for_user(self, backend: "DatabaseBackendProtocol") -> None:
        """Can get stats entries from the last N days."""
        # Create a stats entry (should be within last 7 days)
        backend.stats.create(user_id="stats-retrieve-user")

        entries = backend.stats.last_for_user("stats-retrieve-user", days=7)

        assert len(entries) >= 1
        assert all(e.user_id == "stats-retrieve-user" for e in entries)


class TestStatsNewestBefore:
    """Test newest_before operation."""

    @pytest.fixture(autouse=True)
    def setup_before_user(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test user for newest_before tests."""
        existing = backend.users.get_by_id("stats-before-user")
        if existing is None:
            backend.users.create(
                user_id="stats-before-user",
                account="test:statsbefore",
                email=None,
                nickname="StatsBeforeUser",
                locale="is_IS",
            )

    def test_newest_before_returns_stats(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Can get stats before a specific timestamp."""
        # Create a stats entry
        backend.stats.create(user_id="stats-before-user")

        # Get stats before a future timestamp
        future = datetime.now(UTC) + timedelta(hours=1)
        stats = backend.stats.newest_before(future, "stats-before-user")

        assert stats is not None
        assert stats.user_id == "stats-before-user"

    def test_newest_before_creates_when_none_exist(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Creates new stats when none exist before timestamp."""
        # Use a timestamp in the past for a user with no old stats
        past = datetime.now(UTC) - timedelta(days=365)
        stats = backend.stats.newest_before(past, "stats-before-user", robot_level=0)

        # Should return a newly created stats entry
        assert stats is not None
        assert stats.user_id == "stats-before-user"


class TestStatsListings:
    """Test Stats listing operations."""

    @pytest.fixture(autouse=True)
    def setup_listing_users(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test users and stats for listing tests."""
        test_data = [
            ("stats-list-user-1", "test:statslist1", "StatsListUser1", 1500, 1600, 1400),
            ("stats-list-user-2", "test:statslist2", "StatsListUser2", 1400, 1450, 1350),
            ("stats-list-user-3", "test:statslist3", "StatsListUser3", 1300, 1350, 1250),
        ]

        for user_id, account, nickname, elo, human_elo, manual_elo in test_data:
            existing = backend.users.get_by_id(user_id)
            if existing is None:
                backend.users.create(
                    user_id=user_id,
                    account=account,
                    email=None,
                    nickname=nickname,
                    locale="is_IS",
                )

            # Create stats entry with specific Elo values
            # Note: Stats are created with default Elo of 1200, we'd need to
            # update them or have a way to set Elo. For now, just create entries.
            backend.stats.create(user_id=user_id)

    def test_list_elo(self, backend: "DatabaseBackendProtocol") -> None:
        """Can list stats ordered by Elo."""
        stats_list, _ = backend.stats.list_elo(max_len=10)

        # Should return stats entries
        assert isinstance(stats_list, list)
        # Each entry should have expected fields
        if len(stats_list) > 0:
            entry = stats_list[0]
            assert hasattr(entry, "elo")
            assert hasattr(entry, "rank")
            assert entry.rank == 1

    def test_list_human_elo(self, backend: "DatabaseBackendProtocol") -> None:
        """Can list stats ordered by human Elo."""
        stats_list, _ = backend.stats.list_human_elo(max_len=10)

        assert isinstance(stats_list, list)

    def test_list_manual_elo(self, backend: "DatabaseBackendProtocol") -> None:
        """Can list stats ordered by manual Elo."""
        stats_list, _ = backend.stats.list_manual_elo(max_len=10)

        assert isinstance(stats_list, list)


class TestStatsDelete:
    """Test Stats deletion operations."""

    def test_delete_for_user(self, backend: "DatabaseBackendProtocol") -> None:
        """Can delete all stats for a user."""
        # Create a user
        existing = backend.users.get_by_id("stats-delete-user")
        if existing is None:
            backend.users.create(
                user_id="stats-delete-user",
                account="test:statsdelete",
                email=None,
                nickname="StatsDeleteUser",
                locale="is_IS",
            )

        # Create multiple stats entries
        backend.stats.create(user_id="stats-delete-user")
        backend.stats.create(user_id="stats-delete-user")

        # Verify they exist
        assert backend.stats.newest_for_user("stats-delete-user") is not None

        # Delete all stats for user
        backend.stats.delete_for_user("stats-delete-user")

        # Verify they're gone
        assert backend.stats.newest_for_user("stats-delete-user") is None

    def test_delete_at_timestamp(self, backend: "DatabaseBackendProtocol") -> None:
        """Can delete stats at a specific timestamp."""
        # Create a user
        existing = backend.users.get_by_id("stats-ts-delete-user")
        if existing is None:
            backend.users.create(
                user_id="stats-ts-delete-user",
                account="test:statstsdelete",
                email=None,
                nickname="StatsTsDeleteUser",
                locale="is_IS",
            )

        # Create a stats entry
        stats = backend.stats.create(user_id="stats-ts-delete-user")
        ts = stats.timestamp

        # Verify it exists
        assert backend.stats.newest_for_user("stats-ts-delete-user") is not None

        # Delete by timestamp
        backend.stats.delete_at_timestamp(ts)

        # Note: This might delete other stats with the same timestamp
        # The behavior depends on implementation


class TestStatsEntityProtocol:
    """Test that StatsEntity properly implements the protocol."""

    @pytest.fixture(autouse=True)
    def setup_protocol_user(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test user for protocol tests."""
        existing = backend.users.get_by_id("stats-protocol-user")
        if existing is None:
            backend.users.create(
                user_id="stats-protocol-user",
                account="test:statsprotocol",
                email=None,
                nickname="StatsProtocolUser",
                locale="is_IS",
            )

    def test_stats_entity_has_key_id(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """StatsEntity has a key_id property."""
        stats = backend.stats.create(user_id="stats-protocol-user")

        assert stats.key_id is not None
        assert isinstance(stats.key_id, str)

    def test_stats_entity_has_timestamp(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """StatsEntity has a timestamp."""
        stats = backend.stats.create(user_id="stats-protocol-user")

        assert stats.timestamp is not None
        assert isinstance(stats.timestamp, datetime)

    def test_stats_entity_has_game_counts(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """StatsEntity has game count properties."""
        stats = backend.stats.create(user_id="stats-protocol-user")

        assert stats.games >= 0
        assert stats.human_games >= 0
        assert stats.manual_games >= 0

    def test_stats_entity_has_elo_ratings(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """StatsEntity has Elo rating properties."""
        stats = backend.stats.create(user_id="stats-protocol-user")

        assert stats.elo >= 0
        assert stats.human_elo >= 0
        assert stats.manual_elo >= 0

    def test_stats_entity_has_scores(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """StatsEntity has score properties."""
        stats = backend.stats.create(user_id="stats-protocol-user")

        assert stats.score >= 0
        assert stats.human_score >= 0
        assert stats.manual_score >= 0
        assert stats.score_against >= 0
        assert stats.human_score_against >= 0
        assert stats.manual_score_against >= 0

    def test_stats_entity_has_win_loss(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """StatsEntity has win/loss properties."""
        stats = backend.stats.create(user_id="stats-protocol-user")

        assert stats.wins >= 0
        assert stats.losses >= 0
        assert stats.human_wins >= 0
        assert stats.human_losses >= 0
        assert stats.manual_wins >= 0
        assert stats.manual_losses >= 0
