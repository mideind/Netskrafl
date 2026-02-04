"""
Tests for Favorite repository operations.

These tests run against any backend implementing the DatabaseBackendProtocol.
Use --backend option to select which backend(s) to test.
"""

from __future__ import annotations

import pytest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol


class TestFavoriteCRUD:
    """Test basic Favorite CRUD operations."""

    @pytest.fixture(autouse=True)
    def setup_favorite_users(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test users for Favorite tests."""
        test_users = [
            ("fav-user-1", "test:fav1", "FavUser1"),
            ("fav-user-2", "test:fav2", "FavUser2"),
            ("fav-user-3", "test:fav3", "FavUser3"),
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

    def test_add_favorite(self, backend: "DatabaseBackendProtocol") -> None:
        """Can add a favorite relationship."""
        backend.favorites.add_relation("fav-user-1", "fav-user-2")

        # Verify the relation exists
        assert backend.favorites.has_relation("fav-user-1", "fav-user-2")

    def test_has_relation_returns_false_for_nonexistent(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """has_relation returns False when no relationship exists."""
        # Use a reverse pair that shouldn't exist (directional check)
        assert not backend.favorites.has_relation("fav-user-3", "fav-user-1")

    def test_delete_favorite(self, backend: "DatabaseBackendProtocol") -> None:
        """Can delete a favorite relationship."""
        # Add and then delete - use unique pair
        backend.favorites.add_relation("fav-user-2", "fav-user-1")
        assert backend.favorites.has_relation("fav-user-2", "fav-user-1")

        backend.favorites.delete_relation("fav-user-2", "fav-user-1")
        assert not backend.favorites.has_relation("fav-user-2", "fav-user-1")

    def test_favorite_is_directional(self, backend: "DatabaseBackendProtocol") -> None:
        """Favorite relationship is directional (A favorites B doesn't mean B favorites A)."""
        backend.favorites.add_relation("fav-user-1", "fav-user-3")

        # fav-user-1 has fav-user-3 as favorite
        assert backend.favorites.has_relation("fav-user-1", "fav-user-3")
        # But fav-user-3 doesn't have fav-user-1 as favorite
        assert not backend.favorites.has_relation("fav-user-3", "fav-user-1")


class TestFavoriteList:
    """Test Favorite listing operations."""

    @pytest.fixture(autouse=True)
    def setup_listing_users(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test users and favorites for listing tests."""
        test_users = [
            ("fav-list-user", "test:favlist", "FavListUser"),
            ("fav-target-1", "test:favtarget1", "FavTarget1"),
            ("fav-target-2", "test:favtarget2", "FavTarget2"),
            ("fav-target-3", "test:favtarget3", "FavTarget3"),
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

        # Add favorites
        backend.favorites.add_relation("fav-list-user", "fav-target-1")
        backend.favorites.add_relation("fav-list-user", "fav-target-2")

    def test_list_favorites(self, backend: "DatabaseBackendProtocol") -> None:
        """Can list favorites for a user."""
        favorites = list(backend.favorites.list_favorites("fav-list-user"))

        # Should have at least the favorites we added
        assert "fav-target-1" in favorites
        assert "fav-target-2" in favorites

    def test_list_favorites_respects_max_len(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """list_favorites respects max_len parameter."""
        favorites = list(backend.favorites.list_favorites("fav-list-user", max_len=1))

        assert len(favorites) == 1


class TestFavoriteDeleteForUser:
    """Test deleting all favorites for a user."""

    def test_delete_for_user(self, backend: "DatabaseBackendProtocol") -> None:
        """Can delete all favorites for a user."""
        # Create users
        for user_id, account, nickname in [
            ("fav-delete-user", "test:favdelete", "FavDeleteUser"),
            ("fav-del-target-1", "test:favdeltarget1", "FavDelTarget1"),
            ("fav-del-target-2", "test:favdeltarget2", "FavDelTarget2"),
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

        # Add favorites
        backend.favorites.add_relation("fav-delete-user", "fav-del-target-1")
        backend.favorites.add_relation("fav-delete-user", "fav-del-target-2")

        # Verify they exist
        assert backend.favorites.has_relation("fav-delete-user", "fav-del-target-1")
        assert backend.favorites.has_relation("fav-delete-user", "fav-del-target-2")

        # Delete all favorites for user
        backend.favorites.delete_for_user("fav-delete-user")

        # Verify they're gone
        assert not backend.favorites.has_relation("fav-delete-user", "fav-del-target-1")
        assert not backend.favorites.has_relation("fav-delete-user", "fav-del-target-2")
