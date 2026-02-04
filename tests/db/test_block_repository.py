"""
Tests for Block repository operations.

These tests run against any backend implementing the DatabaseBackendProtocol.
Use --backend option to select which backend(s) to test.
"""

from __future__ import annotations

import pytest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol


class TestBlockCRUD:
    """Test basic Block CRUD operations."""

    @pytest.fixture(autouse=True)
    def setup_block_users(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test users for Block tests."""
        test_users = [
            ("block-user-1", "test:block1", "BlockUser1"),
            ("block-user-2", "test:block2", "BlockUser2"),
            ("block-user-3", "test:block3", "BlockUser3"),
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

    def test_block_user(self, backend: "DatabaseBackendProtocol") -> None:
        """Can block a user."""
        # Use unique user pair for this test
        result = backend.blocks.block_user("block-user-1", "block-user-2")

        # Returns True if newly blocked (first time)
        # Note: may already be blocked from previous test run
        assert backend.blocks.is_blocking("block-user-1", "block-user-2")

    def test_block_user_already_blocked(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Blocking an already blocked user returns False."""
        # Use unique pair for this test to avoid interference
        # First block
        first_result = backend.blocks.block_user("block-user-2", "block-user-1")
        # Second block attempt should return False
        result = backend.blocks.block_user("block-user-2", "block-user-1")

        # The second attempt should return False (already blocked)
        assert result is False

    def test_unblock_user(self, backend: "DatabaseBackendProtocol") -> None:
        """Can unblock a user."""
        # Block first
        backend.blocks.block_user("block-user-1", "block-user-3")
        assert backend.blocks.is_blocking("block-user-1", "block-user-3")

        # Unblock
        result = backend.blocks.unblock_user("block-user-1", "block-user-3")

        assert result is True
        assert not backend.blocks.is_blocking("block-user-1", "block-user-3")

    def test_unblock_not_blocked(self, backend: "DatabaseBackendProtocol") -> None:
        """Unblocking a not-blocked user returns False."""
        # Use a unique pair that should never be blocked
        result = backend.blocks.unblock_user("block-user-3", "block-user-1")
        assert result is False

    def test_is_blocking_returns_false_for_nonexistent(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """is_blocking returns False when no block exists."""
        # Check a unique pair that shouldn't exist
        assert not backend.blocks.is_blocking("block-user-3", "block-user-2")

    def test_block_is_directional(self, backend: "DatabaseBackendProtocol") -> None:
        """Block is directional (A blocks B doesn't mean B blocks A)."""
        backend.blocks.block_user("block-user-2", "block-user-3")

        assert backend.blocks.is_blocking("block-user-2", "block-user-3")
        assert not backend.blocks.is_blocking("block-user-3", "block-user-2")


class TestBlockLists:
    """Test Block listing operations."""

    @pytest.fixture(autouse=True)
    def setup_listing_users(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test users and blocks for listing tests."""
        test_users = [
            ("block-list-user", "test:blocklist", "BlockListUser"),
            ("block-victim-1", "test:blockvictim1", "BlockVictim1"),
            ("block-victim-2", "test:blockvictim2", "BlockVictim2"),
            ("block-aggressor", "test:blockaggressor", "BlockAggressor"),
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

        # Add blocks - blocked by list-user
        backend.blocks.block_user("block-list-user", "block-victim-1")
        backend.blocks.block_user("block-list-user", "block-victim-2")

        # Add blocks - blocking list-user
        backend.blocks.block_user("block-aggressor", "block-list-user")

    def test_list_blocked_users(self, backend: "DatabaseBackendProtocol") -> None:
        """Can list users blocked by a user."""
        blocked = list(backend.blocks.list_blocked_users("block-list-user"))

        assert "block-victim-1" in blocked
        assert "block-victim-2" in blocked

    def test_list_blocked_by(self, backend: "DatabaseBackendProtocol") -> None:
        """Can list users who have blocked a user."""
        blocked_by = list(backend.blocks.list_blocked_by("block-list-user"))

        assert "block-aggressor" in blocked_by

    def test_list_blocked_users_respects_max_len(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """list_blocked_users respects max_len parameter."""
        blocked = list(backend.blocks.list_blocked_users("block-list-user", max_len=1))

        assert len(blocked) == 1
