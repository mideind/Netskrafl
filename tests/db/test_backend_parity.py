"""
Cross-backend parity regression tests.

These lock in fixes for divergences found in the NDB<->PostgreSQL parity audit
(see DB_PARITY_AUDIT.md). Two layers:

1. Per-fix regression tests (the `backend` fixture) run on BOTH backends via
   --backend=both and assert the SAME correct behavior, so a regression on
   either backend fails the test. Each seeds the specific condition that used
   to diverge (e.g. the querying user being player1, multiple stats snapshots).

2. A compare harness (TestCompareHarness, --compare) runs identical operations
   on both backends simultaneously and asserts the outputs are equal.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol

UTC = timezone.utc


def _mk_user(backend: "DatabaseBackendProtocol", uid: str, nick: str = "Nick") -> None:
    """Create a test user if it doesn't already exist."""
    if backend.users.get_by_id(uid) is None:
        backend.users.create(
            user_id=uid, account="test:" + uid, email=None, nickname=nick, locale="is_IS"
        )


def _naive(dt: Optional[datetime]) -> Optional[datetime]:
    """Strip tzinfo so NDB (naive) and PG (aware) datetimes compare equal."""
    if dt is None:
        return None
    return dt.replace(tzinfo=None)


class TestGameDisplayParity:
    """Scores must be oriented to the querying user (sc0 = user's score) and the
    live/zombie `ts` must be the last-move time — on BOTH backends."""

    def test_finished_game_scores_oriented(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        _mk_user(backend, "par-fin-p0", "P0")
        _mk_user(backend, "par-fin-p1", "P1")
        backend.games.delete_for_user("par-fin-p0")
        backend.games.create(
            id="par-fin-game",
            player0_id="par-fin-p0",
            player1_id="par-fin-p1",
            locale="is_IS",
            rack0="",
            rack1="",
            score0=10,
            score1=20,
            to_move=0,
            robot_level=0,
            over=True,
        )

        # Querying as player1: sc0 must be player1's OWN score (20)
        as_p1 = [g for g in backend.games.list_finished_games("par-fin-p1")
                 if g.uuid == "par-fin-game"]
        assert len(as_p1) == 1
        assert as_p1[0].opp == "par-fin-p0"
        assert as_p1[0].sc0 == 20  # user's score
        assert as_p1[0].sc1 == 10  # opponent's score

        # Querying as player0: orientation flips
        as_p0 = [g for g in backend.games.list_finished_games("par-fin-p0")
                 if g.uuid == "par-fin-game"]
        assert len(as_p0) == 1
        assert as_p0[0].opp == "par-fin-p1"
        assert as_p0[0].sc0 == 10
        assert as_p0[0].sc1 == 20

    def test_live_game_scores_oriented_and_ts_is_last_move(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        _mk_user(backend, "par-live-p0", "P0")
        _mk_user(backend, "par-live-p1", "P1")
        backend.games.delete_for_user("par-live-p0")
        t_create = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        t_move = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        backend.games.create(
            id="par-live-game",
            player0_id="par-live-p0",
            player1_id="par-live-p1",
            locale="is_IS",
            rack0="",
            rack1="",
            score0=5,
            score1=8,
            to_move=1,
            robot_level=0,
            over=False,
            timestamp=t_create,
            ts_last_move=t_move,
        )

        live = [g for g in backend.games.iter_live_games("par-live-p1")
                if g.uuid == "par-live-game"]
        assert len(live) == 1
        g = live[0]
        assert g.sc0 == 8 and g.sc1 == 5  # oriented to player1
        assert g.my_turn is True  # to_move == 1, user is player1
        # ts must be the last-move time, not creation time
        assert _naive(g.ts) == _naive(t_move)

    def test_zombie_game_scores_oriented_and_ts_is_last_move(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        _mk_user(backend, "par-zomb-p0", "P0")
        _mk_user(backend, "par-zomb-p1", "P1")
        backend.games.delete_for_user("par-zomb-p0")
        backend.zombies.delete_for_user("par-zomb-p1")
        t_move = datetime(2024, 7, 1, 12, 0, 0, tzinfo=UTC)
        backend.games.create(
            id="par-zomb-game",
            player0_id="par-zomb-p0",
            player1_id="par-zomb-p1",
            locale="is_IS",
            rack0="",
            rack1="",
            score0=3,
            score1=9,
            to_move=0,
            robot_level=0,
            over=True,
            ts_last_move=t_move,
        )
        backend.zombies.add_game("par-zomb-game", "par-zomb-p1")

        z = [g for g in backend.zombies.list_games("par-zomb-p1")
             if g.uuid == "par-zomb-game"]
        assert len(z) == 1
        assert z[0].sc0 == 9 and z[0].sc1 == 3  # oriented to player1
        assert _naive(z[0].ts) == _naive(t_move)


class TestStatsParity:
    """Leaderboard must dedup to one row per user; newest_before is inclusive
    and must not persist a junk row."""

    def test_leaderboard_dedups_per_user(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        _mk_user(backend, "par-elo-user", "EloUser")
        backend.stats.delete_for_user("par-elo-user")
        # Two snapshots for the same user
        backend.stats.create(user_id="par-elo-user")
        backend.stats.create(user_id="par-elo-user")

        # A large max_len so the (default-Elo) user is included regardless of rank
        rows, _ = backend.stats.list_elo(max_len=10000)
        mine = [r for r in rows if r.user == "par-elo-user"]
        assert len(mine) == 1  # deduped to the single newest snapshot

    def test_newest_before_is_inclusive(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        _mk_user(backend, "par-nb-user", "NbUser")
        backend.stats.delete_for_user("par-nb-user")
        backend.stats.create(user_id="par-nb-user")
        snapshot = backend.stats.newest_for_user("par-nb-user")
        assert snapshot is not None
        ts = snapshot.timestamp

        # newest_before AT the exact timestamp must return that record (<=)
        found = backend.stats.newest_before(ts, "par-nb-user")
        assert _naive(found.timestamp) == _naive(ts)

    def test_newest_before_does_not_persist(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        # A user with no stats at all
        _mk_user(backend, "par-nb-empty", "NbEmpty")
        backend.stats.delete_for_user("par-nb-empty")
        assert backend.stats.newest_for_user("par-nb-empty") is None

        # Asking for a default must NOT write a row
        default = backend.stats.newest_before(datetime.now(UTC), "par-nb-empty")
        assert default.elo == 1200  # sane default
        assert backend.stats.newest_for_user("par-nb-empty") is None  # nothing persisted


class TestRelationParity:
    """Reporters are de-duplicated. (Favorite idempotency is enforced at the
    User.add_favorite call site, not the repository layer — see
    test/test_favorite.py — so it is intentionally not asserted here.)"""

    def test_list_reported_by_dedups(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        _mk_user(backend, "par-rep-er", "Reporter")
        _mk_user(backend, "par-rep-ed", "Reported")

        backend.reports.report_user("par-rep-er", "par-rep-ed", 1, "a")
        backend.reports.report_user("par-rep-er", "par-rep-ed", 2, "b")

        reporters = [r for r in backend.reports.list_reported_by("par-rep-ed")
                     if r == "par-rep-er"]
        assert len(reporters) == 1  # reporter listed once despite two reports


class TestCompareHarness:
    """General --compare harness: run identical operations on both backends
    simultaneously and assert equal results. Skipped unless --compare is set."""

    def test_finished_game_orientation_matches(
        self, both_backends: Any
    ) -> None:
        ndb, pg = both_backends
        for be in (ndb, pg):
            _mk_user(be, "cmp-fin-p0", "P0")
            _mk_user(be, "cmp-fin-p1", "P1")
            be.games.delete_for_user("cmp-fin-p0")
            be.games.create(
                id="cmp-fin-game",
                player0_id="cmp-fin-p0",
                player1_id="cmp-fin-p1",
                locale="is_IS",
                rack0="",
                rack1="",
                score0=11,
                score1=22,
                to_move=0,
                robot_level=0,
                over=True,
            )

        def summary(be: Any) -> Any:
            g = [x for x in be.games.list_finished_games("cmp-fin-p1")
                 if x.uuid == "cmp-fin-game"][0]
            return (g.opp, g.sc0, g.sc1)

        assert summary(ndb) == summary(pg) == ("cmp-fin-p0", 22, 11)
