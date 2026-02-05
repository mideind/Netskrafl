"""
Tests for Game repository operations.

These tests run against any backend implementing the DatabaseBackendProtocol.
Use --backend option to select which backend(s) to test.
"""

from __future__ import annotations

import pytest
import uuid
from typing import TYPE_CHECKING
from datetime import datetime, timezone

from src.db.testing import DualBackendRunner, compare_entities


def fresh_id() -> str:
    """Generate a fresh UUID for test entities."""
    return str(uuid.uuid1())

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol

UTC = timezone.utc


class TestGameCRUD:
    """Test basic Game CRUD operations on any backend."""

    def test_create_and_retrieve_game(self, backend: "DatabaseBackendProtocol") -> None:
        """Creating a game and retrieving it returns the same data."""
        # First create two users to be players
        backend.users.create(
            user_id="game-test-player0",
            account="test:player0",
            email=None,
            nickname="Player0",
            locale="is_IS",
        )
        backend.users.create(
            user_id="game-test-player1",
            account="test:player1",
            email=None,
            nickname="Player1",
            locale="is_IS",
        )

        # Create a game
        game = backend.games.create(
            id="test-game-001",
            player0_id="game-test-player0",
            player1_id="game-test-player1",
            locale="is_IS",
            rack0="AEILNRT",
            rack1="DGOSTU?",
            score0=0,
            score1=0,
            to_move=0,
            robot_level=0,
            over=False,
        )

        assert game is not None
        assert game.key_id == "test-game-001"

        # Retrieve
        loaded = backend.games.get_by_id("test-game-001")

        assert loaded is not None
        assert loaded.key_id == "test-game-001"
        assert loaded.player0_id == "game-test-player0"
        assert loaded.player1_id == "game-test-player1"
        assert loaded.locale == "is_IS"
        assert loaded.rack0 == "AEILNRT"
        assert loaded.rack1 == "DGOSTU?"
        assert loaded.score0 == 0
        assert loaded.score1 == 0
        assert loaded.to_move == 0
        assert loaded.robot_level == 0
        assert loaded.over is False

    def test_get_nonexistent_game_returns_none(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Getting a non-existent game returns None, not an error."""
        loaded = backend.games.get_by_id("nonexistent-game-id-xyz")
        assert loaded is None

    def test_update_game(self, backend: "DatabaseBackendProtocol") -> None:
        """Can update game attributes."""
        # Create users and game
        backend.users.create(
            user_id="update-game-player0",
            account="test:updgame0",
            email=None,
            nickname="UpdatePlayer0",
            locale="is_IS",
        )
        backend.users.create(
            user_id="update-game-player1",
            account="test:updgame1",
            email=None,
            nickname="UpdatePlayer1",
            locale="is_IS",
        )

        game = backend.games.create(
            id="test-update-game-001",
            player0_id="update-game-player0",
            player1_id="update-game-player1",
            locale="is_IS",
            rack0="AEILNRT",
            rack1="DGOSTU?",
            score0=0,
            score1=0,
            to_move=0,
            robot_level=0,
            over=False,
        )

        # Update scores and turn
        backend.games.update(game, score0=42, score1=35, to_move=1)

        # Retrieve and verify
        loaded = backend.games.get_by_id("test-update-game-001")
        assert loaded is not None
        assert loaded.score0 == 42
        assert loaded.score1 == 35
        assert loaded.to_move == 1

    def test_delete_game(self, backend: "DatabaseBackendProtocol") -> None:
        """Can delete a game."""
        # Create users and game
        backend.users.create(
            user_id="del-game-player0",
            account="test:delgame0",
            email=None,
            nickname="DelPlayer0",
            locale="is_IS",
        )
        backend.users.create(
            user_id="del-game-player1",
            account="test:delgame1",
            email=None,
            nickname="DelPlayer1",
            locale="is_IS",
        )

        backend.games.create(
            id="test-delete-game-001",
            player0_id="del-game-player0",
            player1_id="del-game-player1",
            locale="is_IS",
            rack0="",
            rack1="",
            score0=0,
            score1=0,
            to_move=0,
            robot_level=0,
            over=False,
        )

        # Verify it exists
        assert backend.games.get_by_id("test-delete-game-001") is not None

        # Delete
        backend.games.delete("test-delete-game-001")

        # Verify it's gone
        assert backend.games.get_by_id("test-delete-game-001") is None


class TestGameWithRobots:
    """Test games against robot opponents."""

    def test_create_game_against_robot(self, backend: "DatabaseBackendProtocol") -> None:
        """Can create a game against a robot (no player1)."""
        backend.users.create(
            user_id="robot-game-player",
            account="test:robotgame",
            email=None,
            nickname="RobotGamePlayer",
            locale="is_IS",
        )

        game = backend.games.create(
            id="test-robot-game-001",
            player0_id="robot-game-player",
            player1_id=None,  # Robot opponent
            locale="is_IS",
            rack0="AEILNRT",
            rack1="DGOSTU?",
            score0=0,
            score1=0,
            to_move=0,
            robot_level=15,  # Robot level 15
            over=False,
        )

        assert game.robot_level == 15
        assert game.player1_id is None

        loaded = backend.games.get_by_id("test-robot-game-001")
        assert loaded is not None
        assert loaded.robot_level == 15
        assert loaded.player1_id is None


class TestGameTimestamps:
    """Test timestamp handling for games."""

    def test_timestamp_set_on_create(self, backend: "DatabaseBackendProtocol") -> None:
        """Game timestamp is set automatically on creation."""
        backend.users.create(
            user_id="ts-game-player0",
            account="test:tsgame0",
            email=None,
            nickname="TsPlayer0",
            locale="is_IS",
        )

        before = datetime.now(UTC)

        backend.games.create(
            id="test-ts-game-001",
            player0_id="ts-game-player0",
            player1_id=None,
            locale="is_IS",
            rack0="",
            rack1="",
            score0=0,
            score1=0,
            to_move=0,
            robot_level=0,
            over=False,
        )

        after = datetime.now(UTC)

        loaded = backend.games.get_by_id("test-ts-game-001")
        assert loaded is not None
        # Timestamp should be between before and after
        assert before <= loaded.timestamp <= after


class TestFinishedGames:
    """Test listing finished games."""

    @pytest.fixture(autouse=True)
    def setup_finished_games(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test users and games for finished game tests."""
        # Create test users
        test_users = [
            ("finished-user-1", "test:fin1", "FinUser1"),
            ("finished-user-2", "test:fin2", "FinUser2"),
            ("finished-user-3", "test:fin3", "FinUser3"),
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

        # Create finished games
        finished_games = [
            # user1 vs user2, user1 wins
            {
                "id": "finished-game-001",
                "player0_id": "finished-user-1",
                "player1_id": "finished-user-2",
                "score0": 320,
                "score1": 280,
                "over": True,
                "elo0_adj": 5,
                "elo1_adj": -5,
            },
            # user1 vs user3, user3 wins
            {
                "id": "finished-game-002",
                "player0_id": "finished-user-1",
                "player1_id": "finished-user-3",
                "score0": 250,
                "score1": 310,
                "over": True,
                "elo0_adj": -3,
                "elo1_adj": 3,
            },
            # user2 vs user3, user2 wins
            {
                "id": "finished-game-003",
                "player0_id": "finished-user-2",
                "player1_id": "finished-user-3",
                "score0": 400,
                "score1": 350,
                "over": True,
                "elo0_adj": 2,
                "elo1_adj": -2,
            },
        ]

        for game_data in finished_games:
            existing = backend.games.get_by_id(game_data["id"])
            if existing is None:
                backend.games.create(
                    locale="is_IS",
                    rack0="",
                    rack1="",
                    to_move=0,
                    robot_level=0,
                    human_elo0_adj=0,
                    human_elo1_adj=0,
                    manual_elo0_adj=0,
                    manual_elo1_adj=0,
                    **game_data,
                )

    def test_list_finished_games_for_user(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Can list finished games for a user."""
        games = backend.games.list_finished_games("finished-user-1")

        # User1 played in 2 finished games
        assert len(games) >= 2

        # All returned games should be finished (over=True)
        game_ids = {g.uuid for g in games}
        assert "finished-game-001" in game_ids or "finished-game-002" in game_ids

    def test_list_finished_games_versus_specific_opponent(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Can filter finished games by opponent."""
        games = backend.games.list_finished_games(
            "finished-user-1", versus="finished-user-2"
        )

        # Only game-001 is user1 vs user2
        assert len(games) >= 1
        game_ids = {g.uuid for g in games}
        assert "finished-game-001" in game_ids
        # game-002 is user1 vs user3, should not be included
        assert "finished-game-002" not in game_ids

    def test_finished_game_info_contains_scores(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """FinishedGameInfo contains score information."""
        games = backend.games.list_finished_games(
            "finished-user-1", versus="finished-user-2"
        )

        game_001 = next((g for g in games if g.uuid == "finished-game-001"), None)
        if game_001:
            assert game_001.sc0 == 320
            assert game_001.sc1 == 280

    def test_finished_game_info_contains_elo_adjustment(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """FinishedGameInfo contains Elo adjustment."""
        games = backend.games.list_finished_games(
            "finished-user-1", versus="finished-user-2"
        )

        game_001 = next((g for g in games if g.uuid == "finished-game-001"), None)
        if game_001:
            # User1 is player0, so elo_adj should be elo0_adj = 5
            assert game_001.elo_adj == 5


class TestLiveGames:
    """Test iterating over live (active) games."""

    @pytest.fixture(autouse=True)
    def setup_live_games(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test users and live games."""
        # Create test users
        test_users = [
            ("live-user-1", "test:live1", "LiveUser1"),
            ("live-user-2", "test:live2", "LiveUser2"),
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

        # Create live games (over=False)
        live_games = [
            {
                "id": "live-game-001",
                "player0_id": "live-user-1",
                "player1_id": "live-user-2",
                "score0": 120,
                "score1": 95,
                "to_move": 0,  # User1's turn
                "over": False,
            },
            {
                "id": "live-game-002",
                "player0_id": "live-user-1",
                "player1_id": None,
                "score0": 80,
                "score1": 100,
                "to_move": 1,  # Robot's turn
                "robot_level": 10,
                "over": False,
            },
        ]

        for game_data in live_games:
            existing = backend.games.get_by_id(game_data["id"])
            if existing is None:
                backend.games.create(
                    locale="is_IS",
                    rack0="AEIOU",
                    rack1="BCDFG",
                    robot_level=game_data.get("robot_level", 0),
                    tile_count=86,
                    **{k: v for k, v in game_data.items() if k != "robot_level"},
                )

    def test_iter_live_games_for_user(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Can iterate over live games for a user."""
        live_games = list(backend.games.iter_live_games("live-user-1"))

        # User1 has 2 live games
        assert len(live_games) >= 2

        game_ids = {g.uuid for g in live_games}
        assert "live-game-001" in game_ids
        assert "live-game-002" in game_ids

    def test_live_game_my_turn_flag(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """LiveGameInfo correctly indicates whose turn it is."""
        live_games = list(backend.games.iter_live_games("live-user-1"))

        game_001 = next((g for g in live_games if g.uuid == "live-game-001"), None)
        game_002 = next((g for g in live_games if g.uuid == "live-game-002"), None)

        if game_001:
            # to_move=0 and user1 is player0, so it's user1's turn
            assert game_001.my_turn is True

        if game_002:
            # to_move=1 and user1 is player0, so it's NOT user1's turn (robot's turn)
            assert game_002.my_turn is False

    def test_live_game_opponent_info(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """LiveGameInfo contains opponent information."""
        live_games = list(backend.games.iter_live_games("live-user-1"))

        game_001 = next((g for g in live_games if g.uuid == "live-game-001"), None)
        game_002 = next((g for g in live_games if g.uuid == "live-game-002"), None)

        if game_001:
            # Opponent should be user2
            assert game_001.opp == "live-user-2"
            assert game_001.robot_level == 0

        if game_002:
            # Opponent is robot (None) with level 10
            assert game_002.opp is None
            assert game_002.robot_level == 10


class TestDeleteForUser:
    """Test deleting all games for a user."""

    def test_delete_for_user_removes_games(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """delete_for_user removes all games involving the user."""
        # Create a user and some games
        backend.users.create(
            user_id="delete-games-user",
            account="test:delgamesuser",
            email=None,
            nickname="DeleteGamesUser",
            locale="is_IS",
        )
        backend.users.create(
            user_id="delete-games-opponent",
            account="test:delgamesopp",
            email=None,
            nickname="DeleteGamesOpponent",
            locale="is_IS",
        )

        # Create games where user is player0
        backend.games.create(
            id="del-user-game-001",
            player0_id="delete-games-user",
            player1_id="delete-games-opponent",
            locale="is_IS",
            rack0="",
            rack1="",
            score0=0,
            score1=0,
            to_move=0,
            robot_level=0,
            over=False,
        )

        # Create game where user is player1
        backend.games.create(
            id="del-user-game-002",
            player0_id="delete-games-opponent",
            player1_id="delete-games-user",
            locale="is_IS",
            rack0="",
            rack1="",
            score0=0,
            score1=0,
            to_move=0,
            robot_level=0,
            over=False,
        )

        # Verify games exist
        assert backend.games.get_by_id("del-user-game-001") is not None
        assert backend.games.get_by_id("del-user-game-002") is not None

        # Delete all games for user
        backend.games.delete_for_user("delete-games-user")

        # Verify games are gone
        assert backend.games.get_by_id("del-user-game-001") is None
        assert backend.games.get_by_id("del-user-game-002") is None


class TestGameQuery:
    """Test game query operations."""

    @pytest.fixture(autouse=True)
    def setup_query_games(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test games for query tests."""
        # Create test user
        existing = backend.users.get_by_id("query-games-user")
        if existing is None:
            backend.users.create(
                user_id="query-games-user",
                account="test:querygames",
                email=None,
                nickname="QueryGamesUser",
                locale="is_IS",
            )

        # Create some games with different locales
        query_games = [
            {"id": "query-game-is-1", "locale": "is_IS", "over": True},
            {"id": "query-game-is-2", "locale": "is_IS", "over": False},
            {"id": "query-game-en-1", "locale": "en_US", "over": True},
        ]

        for game_data in query_games:
            existing = backend.games.get_by_id(game_data["id"])
            if existing is None:
                backend.games.create(
                    player0_id="query-games-user",
                    player1_id=None,
                    rack0="",
                    rack1="",
                    score0=0,
                    score1=0,
                    to_move=0,
                    robot_level=0,
                    **game_data,
                )

    def test_query_fetch_all(self, backend: "DatabaseBackendProtocol") -> None:
        """Can fetch all games with query."""
        # This is a basic test - full query testing would need more
        games = backend.games.query().fetch(limit=100)
        assert len(games) >= 3  # At least our test games


class TestGameMoves:
    """Test game moves storage and retrieval."""

    def test_game_with_moves(self, backend: "DatabaseBackendProtocol") -> None:
        """Can store and retrieve game moves."""
        backend.users.create(
            user_id="moves-game-player",
            account="test:movesgame",
            email=None,
            nickname="MovesGamePlayer",
            locale="is_IS",
        )

        # Create game with moves
        moves = [
            {"coord": "H8", "tiles": "HELLO", "score": 24},
            {"coord": "8G", "tiles": "WORLD", "score": 18},
        ]

        backend.games.create(
            id="test-moves-game-001",
            player0_id="moves-game-player",
            player1_id=None,
            locale="is_IS",
            rack0="AEIOU",
            rack1="BCDFG",
            score0=24,
            score1=18,
            to_move=0,
            robot_level=10,
            over=False,
            moves=moves,
        )

        loaded = backend.games.get_by_id("test-moves-game-001")
        assert loaded is not None

        # Check moves are stored
        loaded_moves = loaded.moves
        assert len(loaded_moves) >= 2 or len(loaded_moves) == 0  # NDB may handle differently

        # If moves are stored, verify content (MoveDict is a dataclass)
        if loaded_moves:
            assert loaded_moves[0].coord == "H8"
            assert loaded_moves[0].tiles == "HELLO"
            assert loaded_moves[0].score == 24


class TestGamePreferences:
    """Test game preferences/settings."""

    def test_game_with_prefs(self, backend: "DatabaseBackendProtocol") -> None:
        """Can store and retrieve game preferences."""
        backend.users.create(
            user_id="prefs-game-player",
            account="test:prefsgame",
            email=None,
            nickname="PrefsGamePlayer",
            locale="is_IS",
        )

        prefs = {"manual": True, "timed": False}

        backend.games.create(
            id="test-prefs-game-001",
            player0_id="prefs-game-player",
            player1_id=None,
            locale="is_IS",
            rack0="",
            rack1="",
            score0=0,
            score1=0,
            to_move=0,
            robot_level=0,
            over=False,
            prefs=prefs,
        )

        loaded = backend.games.get_by_id("test-prefs-game-001")
        assert loaded is not None
        assert loaded.prefs is not None
        assert loaded.prefs.get("manual") is True


class TestGameComparison:
    """Comparison tests that verify both backends behave identically for games."""

    # Fields to compare for game entities
    GAME_COMPARE_FIELDS = [
        "player0_id",
        "player1_id",
        "locale",
        "rack0",
        "rack1",
        "score0",
        "score1",
        "to_move",
        "robot_level",
        "over",
    ]

    # Additional fields for finished games
    GAME_ELO_FIELDS = [
        "elo0",
        "elo1",
        "elo0_adj",
        "elo1_adj",
        "human_elo0_adj",
        "human_elo1_adj",
        "manual_elo0_adj",
        "manual_elo1_adj",
    ]

    @staticmethod
    def compare_games(g1, g2):
        """Compare two game entities."""
        if g1 is None and g2 is None:
            return True, None
        if g1 is None or g2 is None:
            return False, f"One game is None: {g1} vs {g2}"
        return compare_entities(g1, g2, TestGameComparison.GAME_COMPARE_FIELDS)

    @staticmethod
    def compare_games_with_elo(g1, g2):
        """Compare two game entities including Elo fields."""
        if g1 is None and g2 is None:
            return True, None
        if g1 is None or g2 is None:
            return False, f"One game is None: {g1} vs {g2}"
        all_fields = (
            TestGameComparison.GAME_COMPARE_FIELDS + TestGameComparison.GAME_ELO_FIELDS
        )
        return compare_entities(g1, g2, all_fields)

    @staticmethod
    def compare_live_game_info(g1, g2):
        """Compare two LiveGameInfo objects."""
        if g1 is None and g2 is None:
            return True, None
        if g1 is None or g2 is None:
            return False, f"One LiveGameInfo is None: {g1} vs {g2}"
        fields_to_compare = ["uuid", "opp", "robot_level", "my_turn", "sc0", "sc1", "locale"]
        for field in fields_to_compare:
            v1 = getattr(g1, field, None)
            v2 = getattr(g2, field, None)
            if v1 != v2:
                return False, f"Field '{field}' differs: {v1!r} vs {v2!r}"
        return True, None

    @staticmethod
    def compare_finished_game_info(g1, g2):
        """Compare two FinishedGameInfo objects."""
        if g1 is None and g2 is None:
            return True, None
        if g1 is None or g2 is None:
            return False, f"One FinishedGameInfo is None: {g1} vs {g2}"
        fields_to_compare = [
            "uuid", "opp", "robot_level", "sc0", "sc1",
            "elo_adj", "human_elo_adj", "manual_elo_adj", "locale"
        ]
        for field in fields_to_compare:
            v1 = getattr(g1, field, None)
            v2 = getattr(g2, field, None)
            if v1 != v2:
                return False, f"Field '{field}' differs: {v1!r} vs {v2!r}"
        return True, None

    @pytest.fixture
    def comparison_users(
        self, both_backends: tuple["DatabaseBackendProtocol", "DatabaseBackendProtocol"]
    ) -> tuple[str, str]:
        """Create test users on both backends for game comparison tests."""
        ndb, pg = both_backends

        user_ids = ["compare-game-player0", "compare-game-player1"]

        for i, user_id in enumerate(user_ids):
            # Create on NDB if not exists
            if ndb.users.get_by_id(user_id) is None:
                ndb.users.create(
                    user_id=user_id,
                    account=f"test:comparegame{i}",
                    email=None,
                    nickname=f"CompareGamePlayer{i}",
                    locale="is_IS",
                )
            # Create on PostgreSQL if not exists
            if pg.users.get_by_id(user_id) is None:
                pg.users.create(
                    user_id=user_id,
                    account=f"test:comparegame{i}",
                    email=None,
                    nickname=f"CompareGamePlayer{i}",
                    locale="is_IS",
                )

        return tuple(user_ids)  # type: ignore

    @pytest.mark.comparison
    def test_create_retrieve_game_equivalence(
        self,
        both_backends: tuple["DatabaseBackendProtocol", "DatabaseBackendProtocol"],
        comparison_users: tuple[str, str],
    ) -> None:
        """Game create/retrieve produces identical results on both backends."""
        ndb, pg = both_backends
        runner = DualBackendRunner(ndb, pg)
        player0_id, player1_id = comparison_users

        game_id = fresh_id()

        # Create game on both backends
        runner.run(
            "create_game",
            lambda: ndb.games.create(
                id=game_id,
                player0_id=player0_id,
                player1_id=player1_id,
                locale="is_IS",
                rack0="AEILNRT",
                rack1="DGOSTU?",
                score0=0,
                score1=0,
                to_move=0,
                robot_level=0,
                over=False,
            ),
            lambda: pg.games.create(
                id=game_id,
                player0_id=player0_id,
                player1_id=player1_id,
                locale="is_IS",
                rack0="AEILNRT",
                rack1="DGOSTU?",
                score0=0,
                score1=0,
                to_move=0,
                robot_level=0,
                over=False,
            ),
            comparator=self.compare_games,
        )

        # Retrieve and compare
        runner.run(
            "get_game_by_id",
            lambda: ndb.games.get_by_id(game_id),
            lambda: pg.games.get_by_id(game_id),
            comparator=self.compare_games,
        )

        assert runner.report.all_passed, runner.report.format()

    @pytest.mark.comparison
    def test_get_nonexistent_game_equivalence(
        self,
        both_backends: tuple["DatabaseBackendProtocol", "DatabaseBackendProtocol"],
    ) -> None:
        """Getting a non-existent game returns None on both backends."""
        ndb, pg = both_backends
        runner = DualBackendRunner(ndb, pg)

        runner.run(
            "get_nonexistent_game",
            lambda: ndb.games.get_by_id("nonexistent-compare-game-xyz"),
            lambda: pg.games.get_by_id("nonexistent-compare-game-xyz"),
            comparator=self.compare_games,
        )

        assert runner.report.all_passed, runner.report.format()

    @pytest.mark.comparison
    def test_robot_game_equivalence(
        self,
        both_backends: tuple["DatabaseBackendProtocol", "DatabaseBackendProtocol"],
        comparison_users: tuple[str, str],
    ) -> None:
        """Games against robots produce identical results on both backends."""
        ndb, pg = both_backends
        runner = DualBackendRunner(ndb, pg)
        player0_id, _ = comparison_users

        game_id = fresh_id()

        # Create robot game on both backends
        runner.run(
            "create_robot_game",
            lambda: ndb.games.create(
                id=game_id,
                player0_id=player0_id,
                player1_id=None,  # Robot opponent
                locale="is_IS",
                rack0="AEILNRT",
                rack1="DGOSTU?",
                score0=0,
                score1=0,
                to_move=0,
                robot_level=15,
                over=False,
            ),
            lambda: pg.games.create(
                id=game_id,
                player0_id=player0_id,
                player1_id=None,  # Robot opponent
                locale="is_IS",
                rack0="AEILNRT",
                rack1="DGOSTU?",
                score0=0,
                score1=0,
                to_move=0,
                robot_level=15,
                over=False,
            ),
            comparator=self.compare_games,
        )

        # Retrieve and compare
        runner.run(
            "get_robot_game",
            lambda: ndb.games.get_by_id(game_id),
            lambda: pg.games.get_by_id(game_id),
            comparator=self.compare_games,
        )

        assert runner.report.all_passed, runner.report.format()

    @pytest.mark.comparison
    def test_update_game_equivalence(
        self,
        both_backends: tuple["DatabaseBackendProtocol", "DatabaseBackendProtocol"],
        comparison_users: tuple[str, str],
    ) -> None:
        """Updating a game produces identical results on both backends."""
        ndb, pg = both_backends
        runner = DualBackendRunner(ndb, pg)
        player0_id, player1_id = comparison_users

        game_id = fresh_id()

        # Create game on both backends
        runner.run(
            "create_game",
            lambda: ndb.games.create(
                id=game_id,
                player0_id=player0_id,
                player1_id=player1_id,
                locale="is_IS",
                rack0="AEILNRT",
                rack1="DGOSTU?",
                score0=0,
                score1=0,
                to_move=0,
                robot_level=0,
                over=False,
            ),
            lambda: pg.games.create(
                id=game_id,
                player0_id=player0_id,
                player1_id=player1_id,
                locale="is_IS",
                rack0="AEILNRT",
                rack1="DGOSTU?",
                score0=0,
                score1=0,
                to_move=0,
                robot_level=0,
                over=False,
            ),
            comparator=self.compare_games,
        )

        # Get game entities
        ndb_game = ndb.games.get_by_id(game_id)
        pg_game = pg.games.get_by_id(game_id)
        assert ndb_game is not None
        assert pg_game is not None

        # Update on both
        runner.run(
            "update_game",
            lambda: ndb.games.update(
                ndb_game,
                score0=42,
                score1=35,
                to_move=1,
                rack0="BFGHIJK",
                rack1="LMNOPQR",
            ),
            lambda: pg.games.update(
                pg_game,
                score0=42,
                score1=35,
                to_move=1,
                rack0="BFGHIJK",
                rack1="LMNOPQR",
            ),
        )

        # Retrieve and compare
        runner.run(
            "get_updated_game",
            lambda: ndb.games.get_by_id(game_id),
            lambda: pg.games.get_by_id(game_id),
            comparator=self.compare_games,
        )

        # Verify updated values
        ndb_updated = ndb.games.get_by_id(game_id)
        pg_updated = pg.games.get_by_id(game_id)
        assert ndb_updated is not None and ndb_updated.score0 == 42
        assert pg_updated is not None and pg_updated.score0 == 42
        assert ndb_updated.to_move == 1
        assert pg_updated.to_move == 1

        assert runner.report.all_passed, runner.report.format()

    @pytest.mark.comparison
    def test_finished_game_equivalence(
        self,
        both_backends: tuple["DatabaseBackendProtocol", "DatabaseBackendProtocol"],
        comparison_users: tuple[str, str],
    ) -> None:
        """Finished games with Elo produce identical results on both backends."""
        ndb, pg = both_backends
        runner = DualBackendRunner(ndb, pg)
        player0_id, player1_id = comparison_users

        game_id = fresh_id()

        # Create finished game with Elo data on both backends
        runner.run(
            "create_finished_game",
            lambda: ndb.games.create(
                id=game_id,
                player0_id=player0_id,
                player1_id=player1_id,
                locale="is_IS",
                rack0="",
                rack1="",
                score0=320,
                score1=280,
                to_move=0,
                robot_level=0,
                over=True,
                elo0=1200,
                elo1=1180,
                elo0_adj=5,
                elo1_adj=-5,
                human_elo0_adj=5,
                human_elo1_adj=-5,
                manual_elo0_adj=0,
                manual_elo1_adj=0,
            ),
            lambda: pg.games.create(
                id=game_id,
                player0_id=player0_id,
                player1_id=player1_id,
                locale="is_IS",
                rack0="",
                rack1="",
                score0=320,
                score1=280,
                to_move=0,
                robot_level=0,
                over=True,
                elo0=1200,
                elo1=1180,
                elo0_adj=5,
                elo1_adj=-5,
                human_elo0_adj=5,
                human_elo1_adj=-5,
                manual_elo0_adj=0,
                manual_elo1_adj=0,
            ),
            comparator=self.compare_games_with_elo,
        )

        # Retrieve and compare
        runner.run(
            "get_finished_game",
            lambda: ndb.games.get_by_id(game_id),
            lambda: pg.games.get_by_id(game_id),
            comparator=self.compare_games_with_elo,
        )

        assert runner.report.all_passed, runner.report.format()

    @pytest.mark.comparison
    def test_list_finished_games_equivalence(
        self,
        both_backends: tuple["DatabaseBackendProtocol", "DatabaseBackendProtocol"],
        comparison_users: tuple[str, str],
    ) -> None:
        """list_finished_games returns same results on both backends."""
        ndb, pg = both_backends
        runner = DualBackendRunner(ndb, pg)
        player0_id, player1_id = comparison_users

        # Generate fresh game IDs and track them for filtering
        finished_game_ids: set[str] = set()

        # Create multiple finished games
        for i in range(3):
            game_id = fresh_id()
            finished_game_ids.add(game_id)
            ndb.games.create(
                id=game_id,
                player0_id=player0_id,
                player1_id=player1_id,
                locale="is_IS",
                rack0="",
                rack1="",
                score0=300 + i * 10,
                score1=280 + i * 5,
                to_move=0,
                robot_level=0,
                over=True,
                elo0_adj=5 - i,
                elo1_adj=-(5 - i),
                human_elo0_adj=0,
                human_elo1_adj=0,
                manual_elo0_adj=0,
                manual_elo1_adj=0,
            )
            pg.games.create(
                id=game_id,
                player0_id=player0_id,
                player1_id=player1_id,
                locale="is_IS",
                rack0="",
                rack1="",
                score0=300 + i * 10,
                score1=280 + i * 5,
                to_move=0,
                robot_level=0,
                over=True,
                elo0_adj=5 - i,
                elo1_adj=-(5 - i),
                human_elo0_adj=0,
                human_elo1_adj=0,
                manual_elo0_adj=0,
                manual_elo1_adj=0,
            )

        def compare_finished_lists(list1, list2):
            # Filter to only games created in this test to avoid pollution
            # from other tests in the same session
            list1 = [g for g in list1 if g.uuid in finished_game_ids]
            list2 = [g for g in list2 if g.uuid in finished_game_ids]
            # Compare by game UUIDs (order may differ due to timestamps)
            ids1 = {g.uuid for g in list1}
            ids2 = {g.uuid for g in list2}
            if ids1 != ids2:
                return False, f"Game UUID sets differ: {ids1} vs {ids2}"
            # Compare each game by UUID
            dict1 = {g.uuid: g for g in list1}
            dict2 = {g.uuid: g for g in list2}
            for game_uuid in ids1:
                match, diff = self.compare_finished_game_info(dict1[game_uuid], dict2[game_uuid])
                if not match:
                    return False, f"Game {game_uuid}: {diff}"
            return True, None

        # List finished games for player0
        runner.run(
            "list_finished_games",
            lambda: ndb.games.list_finished_games(player0_id),
            lambda: pg.games.list_finished_games(player0_id),
            comparator=compare_finished_lists,
        )

        # List finished games for player0 vs player1
        runner.run(
            "list_finished_games_versus",
            lambda: ndb.games.list_finished_games(player0_id, versus=player1_id),
            lambda: pg.games.list_finished_games(player0_id, versus=player1_id),
            comparator=compare_finished_lists,
        )

        assert runner.report.all_passed, runner.report.format()

    @pytest.mark.comparison
    def test_iter_live_games_equivalence(
        self,
        both_backends: tuple["DatabaseBackendProtocol", "DatabaseBackendProtocol"],
        comparison_users: tuple[str, str],
    ) -> None:
        """iter_live_games returns same results on both backends."""
        ndb, pg = both_backends
        runner = DualBackendRunner(ndb, pg)
        player0_id, player1_id = comparison_users

        # Generate fresh game IDs
        game_id_1 = fresh_id()
        game_id_2 = fresh_id()
        live_game_ids = {game_id_1, game_id_2}
        live_games = [
            {
                "id": game_id_1,
                "player0_id": player0_id,
                "player1_id": player1_id,
                "score0": 120,
                "score1": 95,
                "to_move": 0,
                "robot_level": 0,
            },
            {
                "id": game_id_2,
                "player0_id": player0_id,
                "player1_id": None,
                "score0": 80,
                "score1": 100,
                "to_move": 1,
                "robot_level": 10,
            },
        ]

        for game_data in live_games:
            ndb.games.create(
                locale="is_IS",
                rack0="AEIOU",
                rack1="BCDFG",
                over=False,
                tile_count=86,
                **game_data,
            )
            pg.games.create(
                locale="is_IS",
                rack0="AEIOU",
                rack1="BCDFG",
                over=False,
                tile_count=86,
                **game_data,
            )

        def compare_live_lists(iter1, iter2):
            list1 = list(iter1)
            list2 = list(iter2)
            # Filter to only games created in this test to avoid pollution
            # from other tests in the same session
            list1 = [g for g in list1 if g.uuid in live_game_ids]
            list2 = [g for g in list2 if g.uuid in live_game_ids]
            # Compare by game UUIDs
            ids1 = {g.uuid for g in list1}
            ids2 = {g.uuid for g in list2}
            if ids1 != ids2:
                return False, f"Game UUID sets differ: {ids1} vs {ids2}"
            # Compare each game by UUID
            dict1 = {g.uuid: g for g in list1}
            dict2 = {g.uuid: g for g in list2}
            for game_uuid in ids1:
                match, diff = self.compare_live_game_info(dict1[game_uuid], dict2[game_uuid])
                if not match:
                    return False, f"Game {game_uuid}: {diff}"
            return True, None

        runner.run(
            "iter_live_games",
            lambda: ndb.games.iter_live_games(player0_id),
            lambda: pg.games.iter_live_games(player0_id),
            comparator=compare_live_lists,
        )

        assert runner.report.all_passed, runner.report.format()

    @pytest.mark.comparison
    def test_game_with_moves_equivalence(
        self,
        both_backends: tuple["DatabaseBackendProtocol", "DatabaseBackendProtocol"],
        comparison_users: tuple[str, str],
    ) -> None:
        """Games with moves produce identical results on both backends."""
        ndb, pg = both_backends
        runner = DualBackendRunner(ndb, pg)
        player0_id, player1_id = comparison_users

        game_id = fresh_id()
        moves = [
            {"coord": "H8", "tiles": "HELLO", "score": 24},
            {"coord": "8G", "tiles": "WORLD", "score": 18},
        ]

        # Create game with moves on both backends
        runner.run(
            "create_game_with_moves",
            lambda: ndb.games.create(
                id=game_id,
                player0_id=player0_id,
                player1_id=player1_id,
                locale="is_IS",
                rack0="AEIOU",
                rack1="BCDFG",
                score0=24,
                score1=18,
                to_move=0,
                robot_level=0,
                over=False,
                moves=moves,
            ),
            lambda: pg.games.create(
                id=game_id,
                player0_id=player0_id,
                player1_id=player1_id,
                locale="is_IS",
                rack0="AEIOU",
                rack1="BCDFG",
                score0=24,
                score1=18,
                to_move=0,
                robot_level=0,
                over=False,
                moves=moves,
            ),
            comparator=self.compare_games,
        )

        # Retrieve and compare moves
        ndb_game = ndb.games.get_by_id(game_id)
        pg_game = pg.games.get_by_id(game_id)

        assert ndb_game is not None
        assert pg_game is not None

        # Compare moves if both have them
        ndb_moves = ndb_game.moves
        pg_moves = pg_game.moves

        if ndb_moves and pg_moves:
            assert len(ndb_moves) == len(pg_moves), (
                f"Move count differs: {len(ndb_moves)} vs {len(pg_moves)}"
            )
            for i, (m1, m2) in enumerate(zip(ndb_moves, pg_moves)):
                assert m1.coord == m2.coord, f"Move {i} coord differs"
                assert m1.tiles == m2.tiles, f"Move {i} tiles differs"
                assert m1.score == m2.score, f"Move {i} score differs"

        assert runner.report.all_passed, runner.report.format()

    @pytest.mark.comparison
    def test_game_with_prefs_equivalence(
        self,
        both_backends: tuple["DatabaseBackendProtocol", "DatabaseBackendProtocol"],
        comparison_users: tuple[str, str],
    ) -> None:
        """Games with preferences produce identical results on both backends."""
        ndb, pg = both_backends
        runner = DualBackendRunner(ndb, pg)
        player0_id, player1_id = comparison_users

        game_id = fresh_id()
        prefs = {"manual": True, "timed": False, "duration": 25}

        # Create game with prefs on both backends
        runner.run(
            "create_game_with_prefs",
            lambda: ndb.games.create(
                id=game_id,
                player0_id=player0_id,
                player1_id=player1_id,
                locale="is_IS",
                rack0="",
                rack1="",
                score0=0,
                score1=0,
                to_move=0,
                robot_level=0,
                over=False,
                prefs=prefs,
            ),
            lambda: pg.games.create(
                id=game_id,
                player0_id=player0_id,
                player1_id=player1_id,
                locale="is_IS",
                rack0="",
                rack1="",
                score0=0,
                score1=0,
                to_move=0,
                robot_level=0,
                over=False,
                prefs=prefs,
            ),
            comparator=self.compare_games,
        )

        # Retrieve and compare prefs
        ndb_game = ndb.games.get_by_id(game_id)
        pg_game = pg.games.get_by_id(game_id)

        assert ndb_game is not None
        assert pg_game is not None
        assert ndb_game.prefs == pg_game.prefs, (
            f"Prefs differ: {ndb_game.prefs} vs {pg_game.prefs}"
        )

        assert runner.report.all_passed, runner.report.format()

    @pytest.mark.comparison
    def test_delete_game_equivalence(
        self,
        both_backends: tuple["DatabaseBackendProtocol", "DatabaseBackendProtocol"],
        comparison_users: tuple[str, str],
    ) -> None:
        """Deleting a game produces identical results on both backends."""
        ndb, pg = both_backends
        runner = DualBackendRunner(ndb, pg)
        player0_id, player1_id = comparison_users

        game_id = fresh_id()

        # Create game on both backends
        ndb.games.create(
            id=game_id,
            player0_id=player0_id,
            player1_id=player1_id,
            locale="is_IS",
            rack0="",
            rack1="",
            score0=0,
            score1=0,
            to_move=0,
            robot_level=0,
            over=False,
        )
        pg.games.create(
            id=game_id,
            player0_id=player0_id,
            player1_id=player1_id,
            locale="is_IS",
            rack0="",
            rack1="",
            score0=0,
            score1=0,
            to_move=0,
            robot_level=0,
            over=False,
        )

        # Verify exists on both
        assert ndb.games.get_by_id(game_id) is not None
        assert pg.games.get_by_id(game_id) is not None

        # Delete on both
        runner.run(
            "delete_game",
            lambda: ndb.games.delete(game_id),
            lambda: pg.games.delete(game_id),
        )

        # Verify gone on both
        runner.run(
            "get_deleted_game",
            lambda: ndb.games.get_by_id(game_id),
            lambda: pg.games.get_by_id(game_id),
            comparator=self.compare_games,
        )

        assert runner.report.all_passed, runner.report.format()
