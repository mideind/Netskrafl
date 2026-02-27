"""
Tests for Challenge repository operations.

These tests run against any backend implementing the DatabaseBackendProtocol.
Use --backend option to select which backend(s) to test.
"""

from __future__ import annotations

import pytest
from typing import TYPE_CHECKING

from src.db.protocols import PrefsDict

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol


class TestChallengeCRUD:
    """Test basic Challenge CRUD operations."""

    @pytest.fixture(autouse=True)
    def setup_challenge_users(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test users for Challenge tests."""
        test_users = [
            ("chal-user-1", "test:chal1", "ChalUser1"),
            ("chal-user-2", "test:chal2", "ChalUser2"),
            ("chal-user-3", "test:chal3", "ChalUser3"),
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

    def test_add_challenge(self, backend: "DatabaseBackendProtocol") -> None:
        """Can add a challenge."""
        backend.challenges.add_relation("chal-user-1", "chal-user-2")

        # Verify the challenge exists
        assert backend.challenges.has_relation("chal-user-1", "chal-user-2")

    def test_add_challenge_with_prefs(self, backend: "DatabaseBackendProtocol") -> None:
        """Can add a challenge with game preferences."""
        prefs: PrefsDict = {"duration": 10, "manual": True}
        backend.challenges.add_relation("chal-user-1", "chal-user-3", prefs=prefs)

        found, loaded_prefs = backend.challenges.find_relation(
            "chal-user-1", "chal-user-3"
        )

        assert found
        assert loaded_prefs is not None
        assert loaded_prefs.get("duration") == 10
        assert loaded_prefs.get("manual") is True

    def test_has_relation_returns_false_for_nonexistent(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """has_relation returns False when no challenge exists."""
        assert not backend.challenges.has_relation("chal-user-2", "chal-user-3")

    def test_delete_challenge(self, backend: "DatabaseBackendProtocol") -> None:
        """Can delete a challenge."""
        backend.challenges.add_relation("chal-user-2", "chal-user-3")
        assert backend.challenges.has_relation("chal-user-2", "chal-user-3")

        found, prefs = backend.challenges.delete_relation("chal-user-2", "chal-user-3")

        assert found
        assert not backend.challenges.has_relation("chal-user-2", "chal-user-3")

    def test_delete_returns_prefs(self, backend: "DatabaseBackendProtocol") -> None:
        """Deleting a challenge returns its preferences."""
        prefs: PrefsDict = {"fairplay": True, "duration": 5}
        backend.challenges.add_relation("chal-user-3", "chal-user-1", prefs=prefs)

        found, returned_prefs = backend.challenges.delete_relation(
            "chal-user-3", "chal-user-1"
        )

        assert found
        assert returned_prefs is not None
        assert returned_prefs.get("fairplay") is True
        assert returned_prefs.get("duration") == 5

    def test_challenge_is_directional(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Challenge is directional (A challenges B doesn't mean B challenges A)."""
        backend.challenges.add_relation("chal-user-1", "chal-user-2")

        assert backend.challenges.has_relation("chal-user-1", "chal-user-2")
        assert not backend.challenges.has_relation("chal-user-2", "chal-user-1")


class TestChallengeLists:
    """Test Challenge listing operations."""

    @pytest.fixture(autouse=True)
    def setup_listing_users(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test users and challenges for listing tests."""
        test_users = [
            ("chal-list-user", "test:challist", "ChalListUser"),
            ("chal-recipient-1", "test:chalrecip1", "ChalRecip1"),
            ("chal-recipient-2", "test:chalrecip2", "ChalRecip2"),
            ("chal-issuer-1", "test:chalissuer1", "ChalIssuer1"),
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

        # Add challenges - issued by list-user
        backend.challenges.add_relation("chal-list-user", "chal-recipient-1")
        backend.challenges.add_relation(
            "chal-list-user", "chal-recipient-2", prefs={"duration": 5}
        )

        # Add challenges - received by list-user
        backend.challenges.add_relation(
            "chal-issuer-1", "chal-list-user", prefs={"manual": True}
        )

    def test_list_issued(self, backend: "DatabaseBackendProtocol") -> None:
        """Can list challenges issued by a user."""
        issued = list(backend.challenges.list_issued("chal-list-user"))

        # Should have challenges issued
        assert len(issued) >= 2
        opponents = {c.opp for c in issued}
        assert "chal-recipient-1" in opponents or "chal-recipient-2" in opponents

    def test_list_received(self, backend: "DatabaseBackendProtocol") -> None:
        """Can list challenges received by a user."""
        received = list(backend.challenges.list_received("chal-list-user"))

        # Should have at least the challenge from chal-issuer-1
        assert len(received) >= 1
        opponents = {c.opp for c in received}
        assert "chal-issuer-1" in opponents

    def test_challenge_info_has_prefs(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """ChallengeInfo includes preferences."""
        issued = list(backend.challenges.list_issued("chal-list-user"))

        # Find the challenge with prefs
        with_prefs = [c for c in issued if c.prefs is not None]
        assert len(with_prefs) >= 1

    def test_challenge_info_has_timestamp(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """ChallengeInfo has a timestamp."""
        issued = list(backend.challenges.list_issued("chal-list-user"))

        assert len(issued) >= 1
        assert issued[0].ts is not None


class TestChallengeDeleteForUser:
    """Test deleting all challenges for a user."""

    def test_delete_for_user(self, backend: "DatabaseBackendProtocol") -> None:
        """Can delete all challenges involving a user."""
        # Create users
        for user_id, account, nickname in [
            ("chal-delete-user", "test:chaldelete", "ChalDeleteUser"),
            ("chal-del-target-1", "test:chaldeltarget1", "ChalDelTarget1"),
            ("chal-del-target-2", "test:chaldeltarget2", "ChalDelTarget2"),
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

        # Add challenges (issued and received)
        backend.challenges.add_relation("chal-delete-user", "chal-del-target-1")
        backend.challenges.add_relation("chal-del-target-2", "chal-delete-user")

        # Verify they exist
        assert backend.challenges.has_relation("chal-delete-user", "chal-del-target-1")
        assert backend.challenges.has_relation("chal-del-target-2", "chal-delete-user")

        # Delete all challenges for user
        backend.challenges.delete_for_user("chal-delete-user")

        # Verify they're gone
        assert not backend.challenges.has_relation(
            "chal-delete-user", "chal-del-target-1"
        )
        assert not backend.challenges.has_relation(
            "chal-del-target-2", "chal-delete-user"
        )
