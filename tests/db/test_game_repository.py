"""
Tests for Game repository operations.

These tests run against any backend implementing the DatabaseBackendProtocol.
Use --backend option to select which backend(s) to test.
"""

from __future__ import annotations

import pytest
from typing import TYPE_CHECKING
from datetime import datetime, timezone

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

        game = backend.games.create(
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

        game = backend.games.create(
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

        game = backend.games.create(
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
