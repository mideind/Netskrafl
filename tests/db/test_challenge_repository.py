"""
Tests for Challenge repository operations.

These tests run against any backend implementing the DatabaseBackendProtocol.
Use --backend option to select which backend(s) to test.
"""

from __future__ import annotations

import time

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

    def test_find_and_delete_by_key(self, backend: "DatabaseBackendProtocol") -> None:
        """A challenge can be found and deleted by the key that the lists give."""
        backend.challenges.add_relation(
            "chal-user-2", "chal-user-1", prefs={"duration": 7}
        )
        keys = [
            c.key
            for c in backend.challenges.list_issued("chal-user-2")
            if c.opp == "chal-user-1"
        ]
        assert len(keys) == 1

        found, prefs = backend.challenges.find_relation(
            "chal-user-2", "chal-user-1", key=keys[0]
        )
        assert found
        assert prefs is not None and prefs.get("duration") == 7

        found, prefs = backend.challenges.delete_relation(
            "chal-user-2", "chal-user-1", key=keys[0]
        )
        assert found
        assert prefs is not None and prefs.get("duration") == 7
        assert not backend.challenges.has_relation("chal-user-2", "chal-user-1")

    @pytest.mark.parametrize(
        "foreign_key",
        [
            # The other backend's kind of key: an integer on Datastore, a
            # UUID on PostgreSQL. A client can hold one from before a move
            # between the two
            "5629499534213120",
            "0d0e3a52-6a55-5d0c-9b5c-6a3a1c1f0a11",
            "not-a-key",
        ],
    )
    def test_unknown_key_is_not_found(
        self, backend: "DatabaseBackendProtocol", foreign_key: str
    ) -> None:
        """A key that is no challenge's key means 'not found', not an error,
        and leaves the challenge between the two users in place."""
        backend.challenges.add_relation("chal-user-3", "chal-user-2")

        found, prefs = backend.challenges.find_relation(
            "chal-user-3", "chal-user-2", key=foreign_key
        )
        assert not found
        assert prefs is None

        found, prefs = backend.challenges.delete_relation(
            "chal-user-3", "chal-user-2", key=foreign_key
        )
        assert not found
        assert prefs is None
        assert backend.challenges.has_relation("chal-user-3", "chal-user-2")

        # Clean up, so that the challenge does not leak into other tests
        backend.challenges.delete_relation("chal-user-3", "chal-user-2")


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

    def test_list_issued_newest_first(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Issued challenges are returned newest-first.

        The list is capped at max_len, so newest-first ordering ensures recent
        challenges are shown rather than buried behind an old backlog. This is a
        regression test for a bug where the NDB backend returned the oldest
        challenges first, hiding newer ones once a user had >max_len of them.
        """
        for uid, account, nick in [
            ("chal-order-issuer", "test:chalorderissuer", "ChalOrderIssuer"),
            ("chal-order-dest-1", "test:chalorderdest1", "ChalOrderDest1"),
            ("chal-order-dest-2", "test:chalorderdest2", "ChalOrderDest2"),
            ("chal-order-dest-3", "test:chalorderdest3", "ChalOrderDest3"),
        ]:
            if backend.users.get_by_id(uid) is None:
                backend.users.create(
                    user_id=uid, account=account, email=None,
                    nickname=nick, locale="is_IS",
                )

        # Start from a clean slate: the NDB backend persists to a shared
        # Datastore, so clear any challenges left over from previous runs.
        backend.challenges.delete_for_user("chal-order-issuer")

        # Issue challenges in a known order, with distinct timestamps
        order = ["chal-order-dest-1", "chal-order-dest-2", "chal-order-dest-3"]
        for dest in order:
            backend.challenges.add_relation("chal-order-issuer", dest)
            time.sleep(0.01)

        issued = list(backend.challenges.list_issued("chal-order-issuer"))
        opps = [c.opp for c in issued]
        # Newest-first: the last one issued comes first. Assert on the newest
        # len(order) entries to be robust against any lingering data.
        assert opps[: len(order)] == list(reversed(order))
        # Timestamps are non-increasing
        ts = [c.ts for c in issued]
        assert ts == sorted(ts, reverse=True)

    def test_list_received_newest_first(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Received challenges are returned newest-first (see above)."""
        for uid, account, nick in [
            ("chal-order-recipient", "test:chalorderrecip", "ChalOrderRecip"),
            ("chal-order-src-1", "test:chalordersrc1", "ChalOrderSrc1"),
            ("chal-order-src-2", "test:chalordersrc2", "ChalOrderSrc2"),
            ("chal-order-src-3", "test:chalordersrc3", "ChalOrderSrc3"),
        ]:
            if backend.users.get_by_id(uid) is None:
                backend.users.create(
                    user_id=uid, account=account, email=None,
                    nickname=nick, locale="is_IS",
                )

        # Start from a clean slate (see note in test_list_issued_newest_first).
        backend.challenges.delete_for_user("chal-order-recipient")

        order = ["chal-order-src-1", "chal-order-src-2", "chal-order-src-3"]
        for src in order:
            backend.challenges.add_relation(src, "chal-order-recipient")
            time.sleep(0.01)

        received = list(backend.challenges.list_received("chal-order-recipient"))
        opps = [c.opp for c in received]
        # Newest-first: the last issuer to challenge comes first. Assert on the
        # newest len(order) entries to be robust against any lingering data.
        assert opps[: len(order)] == list(reversed(order))
        ts = [c.ts for c in received]
        assert ts == sorted(ts, reverse=True)


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


class TestUniqueChallenge:
    """A user can have one challenge of each type pending to another user.
    The type is the duration of the game: no clock, or a clock of N minutes."""

    USERS = [
        ("chal-uniq-a", "test:chaluniqa", "ChalUniqA"),
        ("chal-uniq-b", "test:chaluniqb", "ChalUniqB"),
        ("chal-uniq-c", "test:chaluniqc", "ChalUniqC"),
    ]

    @staticmethod
    def _create_users(db: "DatabaseBackendProtocol") -> None:
        for user_id, account, nickname in TestUniqueChallenge.USERS:
            if db.users.get_by_id(user_id) is None:
                db.users.create(
                    user_id=user_id,
                    account=account,
                    email=None,
                    nickname=nickname,
                    locale="is_IS",
                )

    @pytest.fixture(autouse=True)
    def setup_users(self, backend: "DatabaseBackendProtocol") -> None:
        """Create the test users, with no challenges between them."""
        self._create_users(backend)
        for user_id, _, _ in self.USERS:
            # An earlier run may have left challenges behind
            # (the Datastore backend keeps what the tests write)
            backend.challenges.delete_for_user(user_id)

    @staticmethod
    def _durations(
        backend: "DatabaseBackendProtocol", src: str, dest: str
    ) -> list[int]:
        """The durations of the challenges pending from src to dest"""
        return sorted(
            (c.prefs or {}).get("duration", 0)
            for c in backend.challenges.list_issued(src)
            if c.opp == dest
        )

    def test_same_type_is_added_once(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """A second challenge of a type that is pending is not added."""
        a, b = "chal-uniq-a", "chal-uniq-b"
        assert backend.challenges.add_unique_relation(a, b, {"duration": 0})
        assert not backend.challenges.add_unique_relation(a, b, {"duration": 0})
        assert self._durations(backend, a, b) == [0]

        assert backend.challenges.add_unique_relation(a, b, {"duration": 10})
        assert not backend.challenges.add_unique_relation(a, b, {"duration": 10})
        assert self._durations(backend, a, b) == [0, 10]

    def test_distinct_types_are_all_added(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Challenges of distinct types can be pending side by side."""
        a, b = "chal-uniq-a", "chal-uniq-b"
        for duration in (0, 3, 10, 25):
            assert backend.challenges.add_unique_relation(
                a, b, {"duration": duration}
            )
        assert self._durations(backend, a, b) == [0, 3, 10, 25]

    def test_other_preferences_do_not_make_a_type(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Only the duration tells challenges apart."""
        a, b = "chal-uniq-a", "chal-uniq-b"
        assert backend.challenges.add_unique_relation(
            a, b, {"duration": 10, "fairplay": False, "locale": "is_IS"}
        )
        for prefs in (
            PrefsDict(duration=10, fairplay=True, locale="is_IS"),
            PrefsDict(duration=10, manual=True, locale="is_IS"),
            PrefsDict(duration=10, locale="en_US"),
        ):
            assert not backend.challenges.add_unique_relation(a, b, prefs)
        assert self._durations(backend, a, b) == [10]

    def test_no_preferences_mean_no_clock(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """A challenge without preferences, or without a duration among
        them, is for a game without a clock."""
        a, b, c = "chal-uniq-a", "chal-uniq-b", "chal-uniq-c"
        assert backend.challenges.add_unique_relation(a, b)
        assert not backend.challenges.add_unique_relation(a, b, {"duration": 0})
        assert not backend.challenges.add_unique_relation(a, b, {"manual": True})
        assert backend.challenges.add_unique_relation(a, c, {"fairplay": True})
        assert not backend.challenges.add_unique_relation(a, c)

    def test_only_the_same_pair_and_direction_count(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """A challenge to somebody else, or in the other direction, is not
        in the way."""
        a, b, c = "chal-uniq-a", "chal-uniq-b", "chal-uniq-c"
        assert backend.challenges.add_unique_relation(a, b, {"duration": 5})
        assert backend.challenges.add_unique_relation(a, c, {"duration": 5})
        assert backend.challenges.add_unique_relation(b, a, {"duration": 5})
        assert backend.challenges.add_unique_relation(c, b, {"duration": 5})
        assert not backend.challenges.add_unique_relation(a, b, {"duration": 5})

    def test_can_be_added_again_once_answered(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """When the pending challenge is gone (accepted, declined or
        retracted), a challenge of its type can be added again."""
        a, b = "chal-uniq-a", "chal-uniq-b"
        assert backend.challenges.add_unique_relation(a, b, {"duration": 5})
        assert backend.challenges.add_unique_relation(a, b, {"duration": 0})
        key = next(
            c.key
            for c in backend.challenges.list_issued(a)
            if c.opp == b and (c.prefs or {}).get("duration") == 5
        )
        found, _ = backend.challenges.delete_relation(a, b, key)
        assert found
        # The other one is still pending, and still in the way of its type
        assert not backend.challenges.add_unique_relation(a, b, {"duration": 0})
        assert backend.challenges.add_unique_relation(a, b, {"duration": 5})
        assert self._durations(backend, a, b) == [0, 5]

    def test_plain_add_is_not_restricted(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """add_relation() adds whatever it is given; such duplicates, as the
        databases hold from before, are in the way of their type like any
        other challenge."""
        a, b = "chal-uniq-a", "chal-uniq-b"
        backend.challenges.add_relation(a, b, {"duration": 5})
        backend.challenges.add_relation(a, b, {"duration": 5})
        assert self._durations(backend, a, b) == [5, 5]
        assert not backend.challenges.add_unique_relation(a, b, {"duration": 5})


class TestUniqueChallengeConcurrency:
    """Two requests at the same moment must not both add the challenge."""

    def test_simultaneous_requests_add_one(
        self, pg_backend: "DatabaseBackendProtocol"
    ) -> None:
        import threading

        from tests.db.conftest import _create_postgresql_backend

        a, b = "chal-uniq-a", "chal-uniq-b"
        first = pg_backend
        TestUniqueChallenge._create_users(first)
        first.challenges.delete_for_user(a)
        # The users must be visible to the other session
        first.commit()
        second = _create_postgresql_backend()
        results: dict[str, bool] = {}
        first_has_added = threading.Event()

        def first_request() -> None:
            results["first"] = first.challenges.add_unique_relation(
                a, b, {"duration": 15}
            )
            first_has_added.set()
            # Give the other request ample time to look for the challenge
            # before this one is committed: it has to wait instead
            time.sleep(0.4)
            first.commit()

        def second_request() -> None:
            first_has_added.wait(timeout=10)
            results["second"] = second.challenges.add_unique_relation(
                a, b, {"duration": 15}
            )
            second.commit()

        threads = [
            threading.Thread(target=first_request),
            threading.Thread(target=second_request),
        ]
        try:
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
            assert results == {"first": True, "second": False}
            assert len([c for c in second.challenges.list_issued(a) if c.opp == b]) == 1
        finally:
            first.challenges.delete_for_user(a)
            first.commit()
            second.close()

