"""
Tests for User repository operations.

These tests run against any backend implementing the DatabaseBackendProtocol.
Use --backend option to select which backend(s) to test.
"""

from __future__ import annotations

import pytest
from typing import TYPE_CHECKING
from datetime import datetime, timezone

from src.db.testing import sequential_ids, DualBackendRunner, compare_entities

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol

UTC = timezone.utc


class TestUserCRUD:
    """Test basic User CRUD operations on any backend."""

    def test_create_and_retrieve_user(self, backend: "DatabaseBackendProtocol") -> None:
        """Creating a user and retrieving it returns the same data."""
        with sequential_ids("test-user"):
            user_id, prefs = backend.users.create(
                user_id="test-crud-001",
                account="test:account001",
                email="test@example.com",
                nickname="TestNick",
                locale="is_IS",
            )

        # Retrieve
        loaded = backend.users.get_by_id("test-crud-001")

        assert loaded is not None
        assert loaded.key_id == "test-crud-001"
        assert loaded.nickname == "TestNick"
        assert loaded.email == "test@example.com"
        assert loaded.locale == "is_IS"
        assert loaded.inactive is False

    def test_get_nonexistent_user_returns_none(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Getting a non-existent user returns None, not an error."""
        loaded = backend.users.get_by_id("nonexistent-user-id-xyz")
        assert loaded is None

    def test_get_by_account(self, backend: "DatabaseBackendProtocol") -> None:
        """Can retrieve user by OAuth2 account identifier."""
        backend.users.create(
            user_id="test-account-001",
            account="google:12345",
            email=None,
            nickname="GoogleUser",
            locale="en_US",
        )

        loaded = backend.users.get_by_account("google:12345")

        assert loaded is not None
        assert loaded.key_id == "test-account-001"
        assert loaded.account == "google:12345"

    def test_get_by_nickname(self, backend: "DatabaseBackendProtocol") -> None:
        """Can retrieve user by nickname."""
        backend.users.create(
            user_id="test-nick-001",
            account="test:nick001",
            email=None,
            nickname="UniqueNickname",
            locale="is_IS",
        )

        # Exact match
        loaded = backend.users.get_by_nickname("UniqueNickname")
        assert loaded is not None
        assert loaded.key_id == "test-nick-001"

        # Case insensitive
        loaded_ci = backend.users.get_by_nickname("uniquenickname", ignore_case=True)
        assert loaded_ci is not None
        assert loaded_ci.key_id == "test-nick-001"

    def test_get_multi(self, backend: "DatabaseBackendProtocol") -> None:
        """Can retrieve multiple users at once."""
        # Create test users
        for i in range(3):
            backend.users.create(
                user_id=f"test-multi-{i:03d}",
                account=f"test:multi{i}",
                email=None,
                nickname=f"MultiUser{i}",
                locale="is_IS",
            )

        # Fetch multiple, including one that doesn't exist
        results = backend.users.get_multi([
            "test-multi-000",
            "test-multi-001",
            "nonexistent",
            "test-multi-002",
        ])

        assert len(results) == 4
        assert results[0] is not None
        assert results[0].key_id == "test-multi-000"
        assert results[1] is not None
        assert results[1].key_id == "test-multi-001"
        assert results[2] is None  # nonexistent
        assert results[3] is not None
        assert results[3].key_id == "test-multi-002"


class TestUserTimestamps:
    """Test timestamp handling for users."""

    def test_timestamp_set_on_create(self, backend: "DatabaseBackendProtocol") -> None:
        """User timestamp is set automatically on creation."""
        # Record time before creation
        before = datetime.now(UTC)

        backend.users.create(
            user_id="test-ts-001",
            account="test:ts001",
            email=None,
            nickname="TimestampUser",
            locale="is_IS",
        )

        after = datetime.now(UTC)

        loaded = backend.users.get_by_id("test-ts-001")
        assert loaded is not None
        # Timestamp should be between before and after
        assert before <= loaded.timestamp <= after


class TestUserQueries:
    """Test User query operations on any backend."""

    @pytest.fixture(autouse=True)
    def setup_test_users(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test users for query tests."""
        test_users = [
            {
                "user_id": "query-is-1",
                "account": "test:is1",
                "nickname": "Jon",
                "locale": "is_IS",
            },
            {
                "user_id": "query-is-2",
                "account": "test:is2",
                "nickname": "Sigga",
                "locale": "is_IS",
            },
            {
                "user_id": "query-is-3",
                "account": "test:is3",
                "nickname": "Jonatan",
                "locale": "is_IS",
            },
            {
                "user_id": "query-en-1",
                "account": "test:en1",
                "nickname": "John",
                "locale": "en_US",
            },
            {
                "user_id": "query-en-2",
                "account": "test:en2",
                "nickname": "Jane",
                "locale": "en_US",
            },
        ]

        for user_data in test_users:
            # Check if user already exists before trying to create
            existing = backend.users.get_by_id(user_data["user_id"])
            if existing is None:
                try:
                    backend.users.create(
                        user_id=user_data["user_id"],
                        account=user_data["account"],
                        email=None,
                        nickname=user_data["nickname"],
                        locale=user_data["locale"],
                    )
                except Exception:
                    pass  # May already exist from previous test run

    def test_list_prefix(self, backend: "DatabaseBackendProtocol") -> None:
        """Finding users by nickname prefix returns matching users."""
        # Should match "Jon" and "Jonatan" (Icelandic users starting with Jon)
        matches = list(backend.users.list_prefix("Jon", locale="is_IS"))

        nicknames = {m.nickname for m in matches}
        assert "Jon" in nicknames or "Jonatan" in nicknames

    def test_count(self, backend: "DatabaseBackendProtocol") -> None:
        """Count returns the total number of users."""
        count = backend.users.count()
        assert count >= 5  # At least our test users


class TestUserComparison:
    """Comparison tests that verify both backends behave identically."""

    @pytest.mark.comparison
    def test_create_retrieve_equivalence(
        self,
        both_backends: tuple["DatabaseBackendProtocol", "DatabaseBackendProtocol"],
    ) -> None:
        """User create/retrieve produces identical results on both backends."""
        ndb, pg = both_backends
        runner = DualBackendRunner(ndb, pg)

        user_id = "compare-user-001"
        account = "test:compare001"
        nickname = "CompareUser"
        email = "compare@test.com"
        locale = "is_IS"

        # Create on both
        runner.run(
            "create_user",
            lambda: ndb.users.create(
                user_id=user_id,
                account=account,
                email=email,
                nickname=nickname,
                locale=locale,
            ),
            lambda: pg.users.create(
                user_id=user_id,
                account=account,
                email=email,
                nickname=nickname,
                locale=locale,
            ),
        )

        # Retrieve and compare
        def compare_users(u1, u2):
            if u1 is None and u2 is None:
                return True, None
            if u1 is None or u2 is None:
                return False, "One user is None"
            return compare_entities(
                u1, u2, ["nickname", "email", "locale", "inactive"]
            )

        runner.run(
            "get_user_by_id",
            lambda: ndb.users.get_by_id(user_id),
            lambda: pg.users.get_by_id(user_id),
            comparator=compare_users,
        )

        runner.run(
            "get_user_by_account",
            lambda: ndb.users.get_by_account(account),
            lambda: pg.users.get_by_account(account),
            comparator=compare_users,
        )

        # Verify all comparisons passed
        assert runner.report.all_passed, runner.report.format()
