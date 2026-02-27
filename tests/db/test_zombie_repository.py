"""
Tests for Zombie repository operations.

These tests run against any backend implementing the DatabaseBackendProtocol.
Use --backend option to select which backend(s) to test.
"""

from __future__ import annotations

import pytest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol


class TestZombieCRUD:
    """Test basic Zombie CRUD operations."""

    @pytest.fixture(autouse=True)
    def setup_zombie_data(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test users and games for Zombie tests."""
        # Create test users
        for user_id, account, nickname in [
            ("zombie-user-1", "test:zombie1", "ZombieUser1"),
            ("zombie-user-2", "test:zombie2", "ZombieUser2"),
        ]:
            existing = backend.users.get_by_id(user_id)
            if existing is None:
                backend.users.create(
                    user_id=user_id,
                    account=account,
                    email=None,
                    nickname=nickname,
                    locale="is_IS",
                )

        # Create a test game
        existing_game = backend.games.get_by_id("zombie-test-game-1")
        if existing_game is None:
            backend.games.create(
                id="zombie-test-game-1",
                player0_id="zombie-user-1",
                player1_id="zombie-user-2",
                locale="is_IS",
                rack0="ABCDEFG",
                rack1="HIJKLMN",
                score0=300,
                score1=250,
                to_move=0,
                over=True,
            )

    def test_add_zombie_game(self, backend: "DatabaseBackendProtocol") -> None:
        """Can mark a game as zombie for a user."""
        # Should not raise
        backend.zombies.add_game("zombie-test-game-1", "zombie-user-1")

        # Verify by listing
        zombies = list(backend.zombies.list_games("zombie-user-1"))
        game_ids = [z.uuid for z in zombies]
        assert "zombie-test-game-1" in game_ids

    def test_delete_zombie_game(self, backend: "DatabaseBackendProtocol") -> None:
        """Can remove zombie marking for a game."""
        # First add
        backend.zombies.add_game("zombie-test-game-1", "zombie-user-2")

        # Then delete
        backend.zombies.delete_game("zombie-test-game-1", "zombie-user-2")

        # Verify it's gone
        zombies = list(backend.zombies.list_games("zombie-user-2"))
        game_ids = [z.uuid for z in zombies]
        assert "zombie-test-game-1" not in game_ids


class TestZombieList:
    """Test Zombie listing operations."""

    @pytest.fixture(autouse=True)
    def setup_zombie_list_data(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test data for listing tests."""
        # Create test user
        existing = backend.users.get_by_id("zombie-list-user")
        if existing is None:
            backend.users.create(
                user_id="zombie-list-user",
                account="test:zombielist",
                email=None,
                nickname="ZombieListUser",
                locale="is_IS",
            )

        # Create test games
        for game_id in ["zombie-list-game-1", "zombie-list-game-2"]:
            existing_game = backend.games.get_by_id(game_id)
            if existing_game is None:
                backend.games.create(
                    id=game_id,
                    player0_id="zombie-list-user",
                    player1_id=None,
                    locale="is_IS",
                    rack0="ABCDEFG",
                    rack1="HIJKLMN",
                    robot_level=5,
                    over=True,
                    score0=300,
                    score1=250,
                    to_move=0,
                )

        # Mark games as zombies
        backend.zombies.add_game("zombie-list-game-1", "zombie-list-user")
        backend.zombies.add_game("zombie-list-game-2", "zombie-list-user")

    def test_list_games(self, backend: "DatabaseBackendProtocol") -> None:
        """Can list zombie games for a user."""
        zombies = list(backend.zombies.list_games("zombie-list-user"))

        # Should have the games we added
        assert len(zombies) >= 2

    def test_zombie_info_has_expected_fields(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """ZombieGameInfo has expected fields."""
        zombies = list(backend.zombies.list_games("zombie-list-user"))

        assert len(zombies) >= 1
        z = zombies[0]

        # Check expected fields
        assert z.uuid is not None
        assert z.ts is not None
        assert isinstance(z.sc0, int)
        assert isinstance(z.sc1, int)


class TestZombieDeleteForUser:
    """Test deleting all zombies for a user."""

    def test_delete_for_user(self, backend: "DatabaseBackendProtocol") -> None:
        """Can delete all zombie entries for a user."""
        # Create test user
        existing = backend.users.get_by_id("zombie-del-user")
        if existing is None:
            backend.users.create(
                user_id="zombie-del-user",
                account="test:zombiedel",
                email=None,
                nickname="ZombieDelUser",
                locale="is_IS",
            )

        # Create test games
        for game_id in ["zombie-del-game-1", "zombie-del-game-2"]:
            existing_game = backend.games.get_by_id(game_id)
            if existing_game is None:
                backend.games.create(
                    id=game_id,
                    player0_id="zombie-del-user",
                    player1_id=None,
                    locale="is_IS",
                    rack0="ABCDEFG",
                    rack1="HIJKLMN",
                    robot_level=5,
                    over=True,
                    score0=0,
                    score1=0,
                    to_move=0,
                )

        # Add zombie entries
        backend.zombies.add_game("zombie-del-game-1", "zombie-del-user")
        backend.zombies.add_game("zombie-del-game-2", "zombie-del-user")

        # Verify they exist
        zombies_before = list(backend.zombies.list_games("zombie-del-user"))
        assert len(zombies_before) >= 2

        # Delete all for user
        backend.zombies.delete_for_user("zombie-del-user")

        # Verify they're gone
        zombies_after = list(backend.zombies.list_games("zombie-del-user"))
        assert len(zombies_after) == 0
