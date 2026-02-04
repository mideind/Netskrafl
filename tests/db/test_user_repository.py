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

    # Fields to compare for user entities
    USER_COMPARE_FIELDS = [
        "nickname",
        "email",
        "locale",
        "inactive",
        "account",
        "image",
        "ready",
        "ready_timed",
        "chat_disabled",
        "elo",
        "human_elo",
        "manual_elo",
    ]

    @staticmethod
    def compare_users(u1, u2):
        """Compare two user entities."""
        if u1 is None and u2 is None:
            return True, None
        if u1 is None or u2 is None:
            return False, f"One user is None: {u1} vs {u2}"
        return compare_entities(u1, u2, TestUserComparison.USER_COMPARE_FIELDS)

    @staticmethod
    def compare_user_lists(list1, list2):
        """Compare two lists of users by their IDs (order-independent)."""
        ids1 = {u.key_id for u in list1 if u is not None}
        ids2 = {u.key_id for u in list2 if u is not None}
        if ids1 != ids2:
            return False, f"User ID sets differ: {ids1} vs {ids2}"
        return True, None

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

        # Retrieve and compare by ID
        runner.run(
            "get_user_by_id",
            lambda: ndb.users.get_by_id(user_id),
            lambda: pg.users.get_by_id(user_id),
            comparator=self.compare_users,
        )

        # Retrieve and compare by account
        runner.run(
            "get_user_by_account",
            lambda: ndb.users.get_by_account(account),
            lambda: pg.users.get_by_account(account),
            comparator=self.compare_users,
        )

        # Retrieve and compare by email
        runner.run(
            "get_user_by_email",
            lambda: ndb.users.get_by_email(email),
            lambda: pg.users.get_by_email(email),
            comparator=self.compare_users,
        )

        # Retrieve and compare by nickname (exact match)
        runner.run(
            "get_user_by_nickname_exact",
            lambda: ndb.users.get_by_nickname(nickname),
            lambda: pg.users.get_by_nickname(nickname),
            comparator=self.compare_users,
        )

        # Retrieve and compare by nickname (case insensitive)
        runner.run(
            "get_user_by_nickname_case_insensitive",
            lambda: ndb.users.get_by_nickname(nickname.lower(), ignore_case=True),
            lambda: pg.users.get_by_nickname(nickname.lower(), ignore_case=True),
            comparator=self.compare_users,
        )

        # Verify all comparisons passed
        assert runner.report.all_passed, runner.report.format()

    @pytest.mark.comparison
    def test_get_nonexistent_user_equivalence(
        self,
        both_backends: tuple["DatabaseBackendProtocol", "DatabaseBackendProtocol"],
    ) -> None:
        """Getting a non-existent user returns None on both backends."""
        ndb, pg = both_backends
        runner = DualBackendRunner(ndb, pg)

        nonexistent_id = "nonexistent-compare-user-xyz"

        runner.run(
            "get_nonexistent_by_id",
            lambda: ndb.users.get_by_id(nonexistent_id),
            lambda: pg.users.get_by_id(nonexistent_id),
            comparator=self.compare_users,
        )

        runner.run(
            "get_nonexistent_by_account",
            lambda: ndb.users.get_by_account("nonexistent:account"),
            lambda: pg.users.get_by_account("nonexistent:account"),
            comparator=self.compare_users,
        )

        runner.run(
            "get_nonexistent_by_email",
            lambda: ndb.users.get_by_email("nonexistent@example.com"),
            lambda: pg.users.get_by_email("nonexistent@example.com"),
            comparator=self.compare_users,
        )

        assert runner.report.all_passed, runner.report.format()

    @pytest.mark.comparison
    def test_get_multi_equivalence(
        self,
        both_backends: tuple["DatabaseBackendProtocol", "DatabaseBackendProtocol"],
    ) -> None:
        """get_multi returns users in same order on both backends."""
        ndb, pg = both_backends
        runner = DualBackendRunner(ndb, pg)

        # Create test users on both backends
        for i in range(3):
            user_id = f"compare-multi-{i:03d}"
            runner.run(
                f"create_user_{i}",
                lambda uid=user_id, idx=i: ndb.users.create(
                    user_id=uid,
                    account=f"test:comparemulti{idx}",
                    email=None,
                    nickname=f"CompareMulti{idx}",
                    locale="is_IS",
                ),
                lambda uid=user_id, idx=i: pg.users.create(
                    user_id=uid,
                    account=f"test:comparemulti{idx}",
                    email=None,
                    nickname=f"CompareMulti{idx}",
                    locale="is_IS",
                ),
            )

        # Fetch multiple, including one that doesn't exist
        user_ids = [
            "compare-multi-000",
            "compare-multi-001",
            "nonexistent-compare",
            "compare-multi-002",
        ]

        def compare_multi_results(r1, r2):
            if len(r1) != len(r2):
                return False, f"Length mismatch: {len(r1)} vs {len(r2)}"
            for i, (u1, u2) in enumerate(zip(r1, r2)):
                match, diff = self.compare_users(u1, u2)
                if not match:
                    return False, f"User at index {i}: {diff}"
            return True, None

        runner.run(
            "get_multi",
            lambda: ndb.users.get_multi(user_ids),
            lambda: pg.users.get_multi(user_ids),
            comparator=compare_multi_results,
        )

        assert runner.report.all_passed, runner.report.format()

    @pytest.mark.comparison
    def test_update_user_equivalence(
        self,
        both_backends: tuple["DatabaseBackendProtocol", "DatabaseBackendProtocol"],
    ) -> None:
        """Updating a user produces identical results on both backends."""
        ndb, pg = both_backends
        runner = DualBackendRunner(ndb, pg)

        user_id = "compare-update-user-001"

        # Create user on both backends
        runner.run(
            "create_user",
            lambda: ndb.users.create(
                user_id=user_id,
                account="test:compareupd001",
                email="original@test.com",
                nickname="OriginalNick",
                locale="is_IS",
            ),
            lambda: pg.users.create(
                user_id=user_id,
                account="test:compareupd001",
                email="original@test.com",
                nickname="OriginalNick",
                locale="is_IS",
            ),
        )

        # Get user entities
        ndb_user = ndb.users.get_by_id(user_id)
        pg_user = pg.users.get_by_id(user_id)

        assert ndb_user is not None
        assert pg_user is not None

        # Update on both
        runner.run(
            "update_user",
            lambda: ndb.users.update(ndb_user, nickname="UpdatedNick", elo=1250),
            lambda: pg.users.update(pg_user, nickname="UpdatedNick", elo=1250),
        )

        # Retrieve and compare
        runner.run(
            "get_updated_user",
            lambda: ndb.users.get_by_id(user_id),
            lambda: pg.users.get_by_id(user_id),
            comparator=self.compare_users,
        )

        # Verify updated values
        ndb_updated = ndb.users.get_by_id(user_id)
        pg_updated = pg.users.get_by_id(user_id)
        assert ndb_updated is not None and ndb_updated.nickname == "UpdatedNick"
        assert pg_updated is not None and pg_updated.nickname == "UpdatedNick"
        assert ndb_updated.elo == 1250
        assert pg_updated.elo == 1250

        assert runner.report.all_passed, runner.report.format()

    @pytest.mark.comparison
    def test_list_prefix_equivalence(
        self,
        both_backends: tuple["DatabaseBackendProtocol", "DatabaseBackendProtocol"],
    ) -> None:
        """list_prefix returns same users on both backends."""
        ndb, pg = both_backends
        runner = DualBackendRunner(ndb, pg)

        # Create test users with predictable prefixes
        test_users = [
            ("compare-prefix-001", "PrefixAlice"),
            ("compare-prefix-002", "PrefixAlbert"),
            ("compare-prefix-003", "PrefixBob"),
        ]

        for user_id, nickname in test_users:
            runner.run(
                f"create_{user_id}",
                lambda uid=user_id, nick=nickname: ndb.users.create(
                    user_id=uid,
                    account=f"test:{uid}",
                    email=None,
                    nickname=nick,
                    locale="is_IS",
                ),
                lambda uid=user_id, nick=nickname: pg.users.create(
                    user_id=uid,
                    account=f"test:{uid}",
                    email=None,
                    nickname=nick,
                    locale="is_IS",
                ),
            )

        def compare_prefix_results(r1, r2):
            # Convert to lists and compare by user IDs
            list1 = list(r1)
            list2 = list(r2)
            ids1 = {u.id for u in list1}
            ids2 = {u.id for u in list2}
            if ids1 != ids2:
                return False, f"User ID sets differ: {ids1} vs {ids2}"
            return True, None

        # Search for "PrefixAl" - should find Alice and Albert
        runner.run(
            "list_prefix_al",
            lambda: ndb.users.list_prefix("PrefixAl", locale="is_IS"),
            lambda: pg.users.list_prefix("PrefixAl", locale="is_IS"),
            comparator=compare_prefix_results,
        )

        # Search for "PrefixB" - should find Bob
        runner.run(
            "list_prefix_b",
            lambda: ndb.users.list_prefix("PrefixB", locale="is_IS"),
            lambda: pg.users.list_prefix("PrefixB", locale="is_IS"),
            comparator=compare_prefix_results,
        )

        assert runner.report.all_passed, runner.report.format()
