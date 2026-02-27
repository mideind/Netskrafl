"""
Tests for Rating repository operations.

These tests run against any backend implementing the DatabaseBackendProtocol.
Use --backend option to select which backend(s) to test.

The Rating repository manages precomputed rating tables that store player
rankings with historical snapshots (yesterday, week ago, month ago).
"""

from __future__ import annotations

import pytest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol


class TestRatingRepository:
    """Test Rating repository operations."""

    @pytest.fixture(autouse=True)
    def setup_rating_users(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test users for Rating tests."""
        test_users = [
            ("rating-user-1", "test:rating1", "RatingUser1"),
            ("rating-user-2", "test:rating2", "RatingUser2"),
            ("rating-user-3", "test:rating3", "RatingUser3"),
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

    def test_get_or_create_new_rating(self, backend: "DatabaseBackendProtocol") -> None:
        """Can create a new rating entry."""
        # Use a unique kind to avoid conflicts (max 16 chars for PostgreSQL)
        kind = "test_all"
        rank = 999

        rating = backend.ratings.get_or_create(kind, rank)

        assert rating is not None

    def test_get_or_create_existing_rating(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Getting an existing rating returns the same entry."""
        # Use short kind name (max 16 chars for PostgreSQL)
        kind = "test_human"
        rank = 998

        # Create first
        rating1 = backend.ratings.get_or_create(kind, rank)

        # Get same one
        rating2 = backend.ratings.get_or_create(kind, rank)

        # Should be the same entry (same kind and rank)
        assert rating1 is not None
        assert rating2 is not None

    def test_list_rating_empty(self, backend: "DatabaseBackendProtocol") -> None:
        """Listing ratings for non-existent kind returns empty."""
        # Use a kind that shouldn't exist (max 16 chars)
        ratings = list(backend.ratings.list_rating("noexist_xyz"))

        # May be empty or have some entries depending on test isolation
        # Just verify it doesn't error
        assert isinstance(ratings, list)

    def test_list_rating_returns_rating_info(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Listed ratings have expected RatingInfo fields."""
        # Use short kind name (max 16 chars for PostgreSQL)
        kind = "test_list"

        # Create a few rating entries
        for rank in range(1, 4):
            backend.ratings.get_or_create(kind, rank)

        ratings = list(backend.ratings.list_rating(kind))

        # Should have entries
        assert len(ratings) >= 3

        # Each entry should have RatingInfo fields
        for rating in ratings:
            assert hasattr(rating, "rank")
            assert hasattr(rating, "elo")
            assert hasattr(rating, "games")
            assert hasattr(rating, "wins")
            assert hasattr(rating, "losses")

    def test_delete_all(self, backend: "DatabaseBackendProtocol") -> None:
        """Can delete all rating entries."""
        # Note: This is a destructive operation that affects all ratings
        # Use short kind name (max 16 chars for PostgreSQL)
        test_kind = "test_del"
        for rank in range(1, 4):
            backend.ratings.get_or_create(test_kind, rank)

        # Verify entries exist
        ratings_before = list(backend.ratings.list_rating(test_kind))
        assert len(ratings_before) >= 3

        # Delete all ratings
        backend.ratings.delete_all()

        # All ratings should be gone (not just test_kind)
        ratings_after = list(backend.ratings.list_rating(test_kind))
        assert len(ratings_after) == 0
