"""
Admin operation end-to-end tests against the PostgreSQL backend.

Admin routes are only registered when running_local is True - which is
the case in this test environment. This mirrors the intended production
setup, where admin operations run on a locally started instance that
connects to the (remote) PostgreSQL database; see the admin-model
decision in doc/migration-strategy.md (Blind Spot 10).

The deferred (background-thread) admin jobs are exercised with real
threads, verifying that the PostgreSQL Client.get_context() shim
establishes a thread-local session and commits it on completion.
"""

from __future__ import annotations

from threading import Thread
from typing import TYPE_CHECKING

from flask.testing import FlaskClient

from tests.api_e2e.conftest import AuthHelper

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol


class TestAdminRoutes:
    """Test the synchronous admin routes."""

    def test_usercount(self, client: FlaskClient, auth: AuthHelper) -> None:
        """POST /admin/usercount returns a positive user count."""
        auth.login_user(
            sub="admin-count-001",
            name="Count Tester",
            email="admincount@example.com",
        )
        resp = client.post("/admin/usercount")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data is not None
        assert data["count"] >= 1

    def test_loaduser(self, client: FlaskClient, auth: AuthHelper) -> None:
        """POST /admin/loaduser finds a user by id and by email."""
        r = auth.login_user(
            sub="admin-load-001",
            name="Load Tester",
            email="adminload@example.com",
        )
        uid = r["user_id"]
        for key in (uid, "adminload@example.com"):
            resp = client.post("/admin/loaduser", data={"id": key})
            assert resp.status_code == 200
            data = resp.get_json()
            assert data is not None
            user = data["user"]
            assert user is not None, f"User not found by key {key!r}"
            assert user["userid"] == uid
            assert user["email"] == "adminload@example.com"

        # Unknown user id yields user=None
        resp = client.post("/admin/loaduser", data={"id": "no-such-user-xyz"})
        data = resp.get_json()
        assert data is not None
        assert data["user"] is None

    def test_setfriend(self, client: FlaskClient, auth: AuthHelper) -> None:
        """GET /admin/setfriend toggles the friend/has_paid state."""
        r = auth.login_user(
            sub="admin-friend-001",
            name="Friend Tester",
            email="adminfriend@example.com",
        )
        uid = r["user_id"]

        resp = client.get(f"/admin/setfriend?uid={uid}&state=1")
        assert resp.status_code == 200
        data = client.post("/admin/loaduser", data={"id": uid}).get_json()
        assert data is not None and data["user"] is not None
        assert data["user"]["friend"] is True
        assert data["user"]["has_paid"] is True

        resp = client.get(f"/admin/setfriend?uid={uid}&state=0")
        assert resp.status_code == 200
        data = client.post("/admin/loaduser", data={"id": uid}).get_json()
        assert data is not None and data["user"] is not None
        assert data["user"]["friend"] is False
        assert data["user"]["has_paid"] is False

        # Unknown user id yields an error message, not a crash
        resp = client.get("/admin/setfriend?uid=no-such-user&state=1")
        assert resp.status_code == 200
        assert b"Unknown user id" in resp.data

    def test_loadgame(
        self, client: FlaskClient, auth: AuthHelper, mock_firebase: object
    ) -> None:
        """POST /admin/loadgame returns a JSON representation of a game."""
        auth.login_user(
            sub="admin-game-001",
            name="Game Tester",
            email="admingame@example.com",
        )
        create = client.post("/initgame", json={"opp": "robot-15"})
        cdata = create.get_json()
        assert cdata is not None
        game_id = cdata["uuid"]

        resp = client.post("/admin/loadgame", data={"uuid": game_id})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data is not None
        g = data["game"]
        assert g is not None
        assert g["uuid"] == game_id
        assert g["robot_level"] == 15
        assert g["over"] is False
        assert isinstance(g["moves"], list)

        # Unknown game uuid yields game=None
        resp = client.post("/admin/loadgame", data={"uuid": "no-such-game"})
        data = resp.get_json()
        assert data is not None
        assert data["game"] is None


class TestStatsRun:
    """Test the /stats/run batch job against PG.

    Like the deferred admin jobs, /stats/run iterates NDB-style queries
    (GameModel.query) through the skrafldb facade, so it exercises the
    same FacadeQuery machinery on the PostgreSQL backend."""

    def test_stats_run(
        self, client: FlaskClient, auth: AuthHelper, mock_firebase: object
    ) -> None:
        """/stats/run completes successfully, processing games finished
        today (which includes games finished during this test session)."""
        from datetime import UTC, datetime

        auth.login_user(
            sub="admin-stats-001",
            name="Stats Tester",
            email="adminstats@example.com",
        )
        # Create and immediately resign a robot game, so that at least
        # one finished game exists in today's processing window
        create = client.post("/initgame", json={"opp": "robot-15"})
        cdata = create.get_json()
        assert cdata is not None
        game_id = cdata["uuid"]
        state = client.post("/gamestate", json={"game": game_id}).get_json()
        assert state is not None and state.get("ok") is True
        num_moves = state["game"].get("num_moves", 0)
        move = client.post(
            "/submitmove",
            json={"uuid": game_id, "mcount": num_moves, "moves": ["rsgn"]},
        ).get_json()
        assert move is not None and move.get("result") == 99  # GAME_OVER

        # Run the stats job for today's window (from 00:00 today to
        # 00:00 tomorrow); running_local implies synchronous execution
        now = datetime.now(UTC)
        resp = client.post(
            f"/stats/run?year={now.year}&month={now.month}&day={now.day}"
        )
        assert resp.status_code == 200
        assert b"completed" in resp.data


class TestAdminDeferred:
    """Test the deferred (background-thread) admin jobs against PG."""

    @staticmethod
    def _run_deferred(target: object) -> None:
        """Run a deferred admin job on a real background thread,
        as the admin routes do."""
        t = Thread(target=target)
        t.start()
        t.join(timeout=60)
        assert not t.is_alive(), "Deferred admin job did not complete"

    @staticmethod
    def _fresh_backend() -> "DatabaseBackendProtocol":
        """Create a fresh backend/session for verification reads.
        The fixture backend's session caches previously loaded entities
        in its identity map, so it could serve stale data written by
        the deferred job's own (separate) session."""
        from src.db.config import get_config, DEFAULT_TEST_DATABASE_URL
        from src.db.postgresql import PostgreSQLBackend

        url = get_config().get_database_url(DEFAULT_TEST_DATABASE_URL)
        return PostgreSQLBackend(database_url=url)

    def test_deferred_user_update(
        self,
        client: FlaskClient,
        auth: AuthHelper,
        pg_backend: "DatabaseBackendProtocol",
    ) -> None:
        """deferred_user_update lowercases mixed-case emails, and its
        background-thread session is actually committed."""
        r = auth.login_user(
            sub="admin-defer-001",
            name="Defer Tester",
            email="deferupdate@example.com",
        )
        uid = r["user_id"]

        # Give the user a mixed-case email directly in the database
        user = pg_backend.users.get_by_id(uid)
        assert user is not None
        pg_backend.users.update(user, email="MiXeD.Case@Example.COM")
        pg_backend.commit()

        import admin

        self._run_deferred(admin.deferred_user_update)

        # Verify through a fresh session
        verify = self._fresh_backend()
        try:
            user = verify.users.get_by_id(uid)
            assert user is not None
            assert user.email == "mixed.case@example.com"
        finally:
            verify.close()

    def test_deferred_elo_init(
        self,
        client: FlaskClient,
        auth: AuthHelper,
        pg_backend: "DatabaseBackendProtocol",
    ) -> None:
        """deferred_elo_init creates EloModel entries for users in its
        target locale (hardcoded to nb_NO in admin.py)."""
        r = auth.login_user(
            sub="admin-elo-001",
            name="Elo Tester",
            email="adminelo@example.com",
        )
        uid = r["user_id"]

        # Make the user eligible: nb_NO locale, completed games,
        # nonzero Elo ratings (manual_elo deliberately 0 to check the
        # DEFAULT_ELO fallback)
        user = pg_backend.users.get_by_id(uid)
        assert user is not None
        pg_backend.users.update(
            user, locale="nb_NO", games=5, elo=1350, human_elo=1300, manual_elo=0
        )
        pg_backend.commit()

        import admin

        self._run_deferred(admin.deferred_elo_init)

        verify = self._fresh_backend()
        try:
            em = verify.elo.get_for_user("nb_NO", uid)
            assert em is not None
            assert em.elo == 1350
            assert em.human_elo == 1300
            # manual_elo == 0 falls back to DEFAULT_ELO
            assert em.manual_elo == 1200
        finally:
            verify.close()

        # Running it again is idempotent (existing entries are skipped)
        self._run_deferred(admin.deferred_elo_init)
        verify = self._fresh_backend()
        try:
            em = verify.elo.get_for_user("nb_NO", uid)
            assert em is not None
            assert em.elo == 1350
        finally:
            verify.close()
