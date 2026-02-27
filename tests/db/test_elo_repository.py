"""
Tests for Elo repository operations.

These tests run against any backend implementing the DatabaseBackendProtocol.
Use --backend option to select which backend(s) to test.
"""

from __future__ import annotations

import pytest
from typing import TYPE_CHECKING

from src.db.protocols import EloDict

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol


class TestEloCRUD:
    """Test basic Elo CRUD operations."""

    @pytest.fixture(autouse=True)
    def setup_elo_users(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test users for Elo tests."""
        test_users = [
            ("elo-user-1", "test:elo1", "EloUser1"),
            ("elo-user-2", "test:elo2", "EloUser2"),
            ("elo-user-3", "test:elo3", "EloUser3"),
        ]
        for user_id, account, nickname in test_users:
            existing = backend.users.get_by_id(user_id)
            if existing is None:
                backend.users.create(
                    user_id=user_id,
                    account=account,
                    email=None,
                    nickname=nickname,
                    locale="is_IS",
                )

    def test_create_and_retrieve_elo(self, backend: "DatabaseBackendProtocol") -> None:
        """Can create and retrieve Elo ratings for a user."""
        ratings = EloDict(elo=1250, human_elo=1300, manual_elo=1200)

        elo = backend.elo.create("is_IS", "elo-user-1", ratings)

        assert elo is not None
        assert elo.user_id == "elo-user-1"
        assert elo.locale == "is_IS"
        assert elo.elo == 1250
        assert elo.human_elo == 1300
        assert elo.manual_elo == 1200

    def test_get_for_user(self, backend: "DatabaseBackendProtocol") -> None:
        """Can retrieve Elo ratings for a user in a specific locale."""
        ratings = EloDict(elo=1400, human_elo=1450, manual_elo=1350)
        backend.elo.create("en_US", "elo-user-2", ratings)

        loaded = backend.elo.get_for_user("en_US", "elo-user-2")

        assert loaded is not None
        assert loaded.elo == 1400
        assert loaded.human_elo == 1450
        assert loaded.manual_elo == 1350

    def test_get_nonexistent_elo_returns_none(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Getting Elo for a user without ratings returns None."""
        loaded = backend.elo.get_for_user("pl_PL", "elo-user-nonexistent")
        assert loaded is None

    def test_elo_is_locale_specific(self, backend: "DatabaseBackendProtocol") -> None:
        """Elo ratings are specific to locale."""
        # Create ratings for different locales
        backend.elo.create("is_IS", "elo-user-3", EloDict(1200, 1200, 1200))
        backend.elo.create("en_US", "elo-user-3", EloDict(1500, 1500, 1500))

        is_elo = backend.elo.get_for_user("is_IS", "elo-user-3")
        en_elo = backend.elo.get_for_user("en_US", "elo-user-3")

        assert is_elo is not None
        assert en_elo is not None
        assert is_elo.elo == 1200
        assert en_elo.elo == 1500


class TestEloUpsert:
    """Test Elo upsert operations."""

    @pytest.fixture(autouse=True)
    def setup_upsert_user(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test user for upsert tests."""
        existing = backend.users.get_by_id("elo-upsert-user")
        if existing is None:
            backend.users.create(
                user_id="elo-upsert-user",
                account="test:eloupsert",
                email=None,
                nickname="EloUpsertUser",
                locale="is_IS",
            )

    def test_upsert_creates_when_not_exists(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Upsert creates a new entry when none exists."""
        ratings = EloDict(elo=1300, human_elo=1300, manual_elo=1300)

        # Pass None for existing to indicate creation
        result = backend.elo.upsert(None, "nb_NO", "elo-upsert-user", ratings)

        assert result is True

        # Verify it was created
        loaded = backend.elo.get_for_user("nb_NO", "elo-upsert-user")
        assert loaded is not None
        assert loaded.elo == 1300

    def test_upsert_updates_when_exists(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Upsert updates an existing entry."""
        # Create initial entry
        initial_ratings = EloDict(elo=1200, human_elo=1200, manual_elo=1200)
        backend.elo.create("nn_NO", "elo-upsert-user", initial_ratings)

        # Get the existing entry
        existing = backend.elo.get_for_user("nn_NO", "elo-upsert-user")
        assert existing is not None

        # Upsert with new ratings
        new_ratings = EloDict(elo=1350, human_elo=1400, manual_elo=1300)
        result = backend.elo.upsert(existing, "nn_NO", "elo-upsert-user", new_ratings)

        assert result is True

        # Verify it was updated
        loaded = backend.elo.get_for_user("nn_NO", "elo-upsert-user")
        assert loaded is not None
        assert loaded.elo == 1350
        assert loaded.human_elo == 1400
        assert loaded.manual_elo == 1300


class TestEloDelete:
    """Test Elo deletion operations."""

    def test_delete_for_user(self, backend: "DatabaseBackendProtocol") -> None:
        """Can delete all Elo ratings for a user."""
        # Create a user
        existing = backend.users.get_by_id("elo-delete-user")
        if existing is None:
            backend.users.create(
                user_id="elo-delete-user",
                account="test:elodelete",
                email=None,
                nickname="EloDeleteUser",
                locale="is_IS",
            )

        # Create Elo in multiple locales
        backend.elo.create("is_IS", "elo-delete-user", EloDict(1200, 1200, 1200))
        backend.elo.create("en_US", "elo-delete-user", EloDict(1300, 1300, 1300))

        # Verify they exist
        assert backend.elo.get_for_user("is_IS", "elo-delete-user") is not None
        assert backend.elo.get_for_user("en_US", "elo-delete-user") is not None

        # Delete all for user
        backend.elo.delete_for_user("elo-delete-user")

        # Verify they're gone
        assert backend.elo.get_for_user("is_IS", "elo-delete-user") is None
        assert backend.elo.get_for_user("en_US", "elo-delete-user") is None


class TestEloListings:
    """Test Elo listing operations."""

    @pytest.fixture(autouse=True)
    def setup_elo_listings(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test users and Elo entries for listing tests."""
        test_data = [
            ("elo-list-user-1", "test:elolist1", "EloListUser1", 1500, 1600, 1400),
            ("elo-list-user-2", "test:elolist2", "EloListUser2", 1400, 1450, 1350),
            ("elo-list-user-3", "test:elolist3", "EloListUser3", 1300, 1350, 1250),
            ("elo-list-user-4", "test:elolist4", "EloListUser4", 1200, 1200, 1200),
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

            existing_elo = backend.elo.get_for_user("is_IS", user_id)
            if existing_elo is None:
                backend.elo.create(
                    "is_IS", user_id, EloDict(elo, human_elo, manual_elo)
                )

    def test_list_rating(self, backend: "DatabaseBackendProtocol") -> None:
        """Can list ratings by kind for a locale."""
        ratings = list(backend.elo.list_rating("human", "is_IS", limit=10))

        # Should have at least our test users
        assert len(ratings) >= 4

        # Check that ratings are returned (note: RatingForLocale has 'userid' not 'user_id')
        user_ids = {r.userid for r in ratings}
        assert "elo-list-user-1" in user_ids

    def test_list_similar(self, backend: "DatabaseBackendProtocol") -> None:
        """Can list users with similar Elo."""
        # List users similar to 1350 Elo
        similar = list(backend.elo.list_similar("is_IS", 1350, max_len=10))

        # Should return users near 1350
        assert len(similar) >= 2

    def test_load_multi(self, backend: "DatabaseBackendProtocol") -> None:
        """Can load Elo for multiple users at once."""
        user_ids = ["elo-list-user-1", "elo-list-user-2", "nonexistent-user"]

        result = backend.elo.load_multi("is_IS", user_ids)

        # Should have entries for existing users
        assert "elo-list-user-1" in result
        assert "elo-list-user-2" in result

        # Check values
        assert result["elo-list-user-1"].elo == 1500
        assert result["elo-list-user-2"].elo == 1400


class TestEloEntityProtocol:
    """Test that EloEntity properly implements the protocol."""

    def test_elo_entity_key_id(self, backend: "DatabaseBackendProtocol") -> None:
        """EloEntity has a proper key_id."""
        existing = backend.users.get_by_id("elo-key-user")
        if existing is None:
            backend.users.create(
                user_id="elo-key-user",
                account="test:elokey",
                email=None,
                nickname="EloKeyUser",
                locale="is_IS",
            )

        backend.elo.create("is_IS", "elo-key-user", EloDict(1200, 1200, 1200))

        elo = backend.elo.get_for_user("is_IS", "elo-key-user")
        assert elo is not None

        # key_id should be a combination of user_id and locale
        assert "elo-key-user" in elo.key_id
        assert "is_IS" in elo.key_id

    def test_elo_entity_has_timestamp(self, backend: "DatabaseBackendProtocol") -> None:
        """EloEntity has a timestamp."""
        existing = backend.users.get_by_id("elo-ts-user")
        if existing is None:
            backend.users.create(
                user_id="elo-ts-user",
                account="test:elots",
                email=None,
                nickname="EloTsUser",
                locale="is_IS",
            )

        backend.elo.create("is_IS", "elo-ts-user", EloDict(1200, 1200, 1200))

        elo = backend.elo.get_for_user("is_IS", "elo-ts-user")
        assert elo is not None
        assert elo.timestamp is not None
