"""
Move timestamp round-trip end-to-end tests.

These tests verify that move timestamps survive the full round-trip through
the application: submitmove API -> Game.register_move() -> MoveModel.to_dict()
-> JSONB storage -> MoveModel.from_dict() -> Game._load_locked().

This was added because a bug was discovered where timestamps stored as ISO
strings in JSONB were not being deserialized back to datetime objects when
reading from PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from flask.testing import FlaskClient

from tests.api_e2e.conftest import (
    AuthHelper,
    DatabaseVerifier,
    DeterministicGameContext,
    FirebaseMock,
)

UTC = timezone.utc


def assert_utc_datetime(value: object, label: str) -> datetime:
    """Assert that value is a timezone-aware UTC datetime and return it."""
    assert isinstance(value, datetime), (
        f"{label}: expected datetime, got {type(value).__name__}: {value!r}"
    )
    assert value.tzinfo is not None, f"{label}: timestamp must be timezone-aware"
    utcoffset = value.utcoffset()
    assert utcoffset is not None and utcoffset.total_seconds() == 0, (
        f"{label}: timestamp must be UTC, got utcoffset={utcoffset}"
    )
    return value


@pytest.mark.api_e2e
class TestMoveTimestampRoundTrip:
    """Verify that move timestamps are correctly stored and retrieved."""

    def test_pass_move_has_timestamp_in_database(
        self,
        client: FlaskClient,
        auth: AuthHelper,
        db: DatabaseVerifier,
        mock_firebase: FirebaseMock,
        deterministic_game: DeterministicGameContext,
    ) -> None:
        """A pass move stores a UTC datetime timestamp in the JSONB moves array."""
        auth.login_user(
            sub="ts-pass-user-001",
            name="Timestamp Tester",
            email="tspass@example.com",
        )

        # Ensure the human player moves first so we can submit immediately
        deterministic_game.set_player_order(player0_first=True)
        deterministic_game.set_game_id("ts-pass-game-001")

        # Create a robot game
        create_resp = client.post("/initgame", json={"opp": "robot-0"})
        data = create_resp.get_json()
        assert data is not None
        assert data.get("ok") is True
        game_id = data["uuid"]
        assert game_id == "ts-pass-game-001"

        # Get the current move count (robot may have auto-played)
        state_resp = client.post("/gamestate", json={"game": game_id})
        state_data = state_resp.get_json()
        assert state_data is not None and state_data.get("ok") is True
        num_moves = state_data["game"].get("num_moves", 0)

        # Record the time before the move
        before_move = datetime.now(UTC)

        # Submit a pass move (always valid, no rack dependency)
        move_resp = client.post(
            "/submitmove",
            json={
                "uuid": game_id,
                "mcount": num_moves,
                "moves": ["pass"],
            },
        )
        move_data = move_resp.get_json()
        assert move_data is not None
        assert move_data.get("result") == 0  # Error.LEGAL

        after_move = datetime.now(UTC)

        # Verify the game in the database has moves with proper timestamps
        game = db.get_game(game_id)
        assert game is not None
        moves = game.moves
        # At least our pass + robot's response (plus any initial robot move)
        assert len(moves) >= num_moves + 2

        # Find our pass move (first human pass after any initial robot move)
        human_pass_idx = num_moves  # Our move is at this index
        human_move = moves[human_pass_idx]
        assert human_move.tiles == "PASS"
        human_ts = assert_utc_datetime(human_move.timestamp, "Human pass move")
        # Must be between our before/after markers
        assert before_move <= human_ts <= after_move, (
            f"Timestamp {human_ts} not in expected range [{before_move}, {after_move}]"
        )

        # Check the robot's response move (immediately after ours)
        robot_ts = assert_utc_datetime(
            moves[human_pass_idx + 1].timestamp, "Robot response move"
        )
        # Robot moves after the human, so its timestamp >= human's
        assert robot_ts >= human_ts

        auth.logout()

    def test_multiple_moves_preserve_timestamps(
        self,
        client: FlaskClient,
        auth: AuthHelper,
        db: DatabaseVerifier,
        mock_firebase: FirebaseMock,
        deterministic_game: DeterministicGameContext,
    ) -> None:
        """Multiple moves each get distinct, monotonically increasing UTC timestamps."""
        auth.login_user(
            sub="ts-multi-user-001",
            name="Multi Move",
            email="tsmulti@example.com",
        )

        deterministic_game.set_player_order(player0_first=True)
        deterministic_game.set_game_id("ts-multi-game-001")

        create_resp = client.post("/initgame", json={"opp": "robot-0"})
        data = create_resp.get_json()
        assert data is not None
        game_id = data["uuid"]

        # Play two rounds of pass moves
        for i in range(2):
            # Get current move count
            state_resp = client.post("/gamestate", json={"game": game_id})
            state_data = state_resp.get_json()
            assert state_data is not None and state_data.get("ok") is True
            game_state = state_data["game"]
            if game_state.get("over"):
                break
            num_moves = game_state.get("num_moves", 0)

            move_resp = client.post(
                "/submitmove",
                json={
                    "uuid": game_id,
                    "mcount": num_moves,
                    "moves": ["pass"],
                },
            )
            move_data = move_resp.get_json()
            assert move_data is not None
            # Accept either LEGAL (0) or GAME_OVER (99)
            assert move_data.get("result") in (0, 99)

        # Verify timestamps in database
        game = db.get_game(game_id)
        assert game is not None
        moves = game.moves
        # We submitted 2 passes; robot responded to each (unless game ended)
        assert len(moves) >= 3  # At least: pass, robot, pass

        # All moves must have UTC datetime timestamps
        for i, move in enumerate(moves):
            assert_utc_datetime(move.timestamp, f"Move {i}")

        # Timestamps must be monotonically non-decreasing
        for i in range(1, len(moves)):
            assert moves[i].timestamp >= moves[i - 1].timestamp, (
                f"Move {i} timestamp ({moves[i].timestamp}) is before "
                f"move {i - 1} timestamp ({moves[i - 1].timestamp})"
            )

        auth.logout()

    def test_game_reload_preserves_move_timestamps(
        self,
        client: FlaskClient,
        auth: AuthHelper,
        db: DatabaseVerifier,
        mock_firebase: FirebaseMock,
        deterministic_game: DeterministicGameContext,
    ) -> None:
        """Timestamps survive the full store-then-reload cycle via Game.load().

        Game.get_elapsed() performs datetime arithmetic on move timestamps.
        If timestamps were strings instead of datetimes, it would raise
        a TypeError on the subtraction.
        """
        auth.login_user(
            sub="ts-reload-user-001",
            name="Reload Tester",
            email="tsreload@example.com",
        )

        deterministic_game.set_player_order(player0_first=True)
        deterministic_game.set_game_id("ts-reload-game-001")

        create_resp = client.post("/initgame", json={"opp": "robot-0"})
        data = create_resp.get_json()
        assert data is not None
        game_id = data["uuid"]

        # Get the current move count (robot may have auto-played first)
        state_resp = client.post("/gamestate", json={"game": game_id})
        state_data = state_resp.get_json()
        assert state_data is not None and state_data.get("ok") is True
        num_moves = state_data["game"].get("num_moves", 0)

        # Submit a pass move
        move_resp = client.post(
            "/submitmove",
            json={
                "uuid": game_id,
                "mcount": num_moves,
                "moves": ["pass"],
            },
        )
        move_data = move_resp.get_json()
        assert move_data is not None
        assert move_data.get("result") == 0

        # Now reload the game via the API (this goes through Game.load()
        # which calls _load_locked -> GameModel.fetch -> MoveModel.from_dict)
        state_resp = client.post("/gamestate", json={"game": game_id})
        state_data = state_resp.get_json()
        assert state_data is not None
        assert state_data.get("ok") is True

        # The game state returned to the client includes time_info
        # with elapsed times computed from move timestamps.
        # If timestamps were strings instead of datetimes, get_elapsed()
        # would raise a TypeError on the subtraction.
        game_state = state_data["game"]

        # Verify time_info exists and has valid elapsed times
        # (this field is populated by Game.time_info() -> get_elapsed()
        # which requires datetime arithmetic on move timestamps)
        time_info = game_state.get("time_info")
        if time_info is not None:
            elapsed = time_info.get("elapsed")
            if elapsed is not None:
                # Elapsed times should be non-negative numbers
                assert isinstance(elapsed[0], (int, float))
                assert isinstance(elapsed[1], (int, float))
                assert elapsed[0] >= 0
                assert elapsed[1] >= 0

        auth.logout()

    def test_resign_move_has_timestamp(
        self,
        client: FlaskClient,
        auth: AuthHelper,
        db: DatabaseVerifier,
        mock_firebase: FirebaseMock,
        deterministic_game: DeterministicGameContext,
    ) -> None:
        """A resignation move also stores a proper UTC timestamp."""
        auth.login_user(
            sub="ts-resign-user-001",
            name="Resign Tester",
            email="tsresign@example.com",
        )

        deterministic_game.set_player_order(player0_first=True)
        deterministic_game.set_game_id("ts-resign-game-001")

        create_resp = client.post("/initgame", json={"opp": "robot-0"})
        data = create_resp.get_json()
        assert data is not None
        game_id = data["uuid"]

        # Get the current move count
        state_resp = client.post("/gamestate", json={"game": game_id})
        state_data = state_resp.get_json()
        assert state_data is not None and state_data.get("ok") is True
        num_moves = state_data["game"].get("num_moves", 0)

        # Resign immediately
        move_resp = client.post(
            "/submitmove",
            json={
                "uuid": game_id,
                "mcount": num_moves,
                "moves": ["rsgn"],
            },
        )
        move_data = move_resp.get_json()
        assert move_data is not None
        # Resignation returns GAME_OVER (99)
        assert move_data.get("result") == 99

        # Verify the resignation move has a UTC timestamp
        game = db.get_game(game_id)
        assert game is not None
        assert game.over is True
        moves = game.moves
        # Find the resignation move (may not be the first if robot played first)
        resign_moves = [m for m in moves if m.tiles == "RSGN"]
        assert len(resign_moves) == 1
        assert_utc_datetime(resign_moves[0].timestamp, "Resign move")

        auth.logout()

    def test_exchange_move_has_timestamp(
        self,
        client: FlaskClient,
        auth: AuthHelper,
        db: DatabaseVerifier,
        mock_firebase: FirebaseMock,
        deterministic_game: DeterministicGameContext,
    ) -> None:
        """An exchange move stores a proper UTC timestamp."""
        auth.login_user(
            sub="ts-exch-user-001",
            name="Exchange Tester",
            email="tsexch@example.com",
        )

        deterministic_game.set_player_order(player0_first=True)
        deterministic_game.set_game_id("ts-exch-game-001")

        create_resp = client.post("/initgame", json={"opp": "robot-0"})
        data = create_resp.get_json()
        assert data is not None
        game_id = data["uuid"]

        # Get the rack and current move count
        # rack is a list of [letter, score] pairs, e.g. [["A", 1], ["B", 3], ...]
        state_resp = client.post("/gamestate", json={"game": game_id})
        state_data = state_resp.get_json()
        assert state_data is not None and state_data.get("ok") is True
        rack = state_data["game"].get("rack", [])
        num_moves = state_data["game"].get("num_moves", 0)
        assert rack, "Player should have tiles in rack"

        # Exchange the first tile (rack[0][0] is the tile letter)
        first_tile = rack[0][0]
        move_resp = client.post(
            "/submitmove",
            json={
                "uuid": game_id,
                "mcount": num_moves,
                "moves": [f"exch={first_tile}"],
            },
        )
        move_data = move_resp.get_json()
        assert move_data is not None
        assert move_data.get("result") == 0  # Error.LEGAL

        # Verify the exchange move has a UTC timestamp
        game = db.get_game(game_id)
        assert game is not None
        moves = game.moves
        assert len(moves) >= num_moves + 2  # exchange + robot response

        exch_move = moves[num_moves]  # Our exchange move
        assert exch_move.tiles.startswith("EXCH")
        assert_utc_datetime(exch_move.timestamp, "Exchange move")

        auth.logout()

    def test_ts_last_move_is_utc_datetime(
        self,
        client: FlaskClient,
        auth: AuthHelper,
        db: DatabaseVerifier,
        mock_firebase: FirebaseMock,
        deterministic_game: DeterministicGameContext,
    ) -> None:
        """The game's ts_last_move field is a proper UTC datetime after moves."""
        auth.login_user(
            sub="ts-lastmove-user-001",
            name="LastMove Tester",
            email="tslast@example.com",
        )

        deterministic_game.set_player_order(player0_first=True)
        deterministic_game.set_game_id("ts-lastmove-game-001")

        before_game = datetime.now(UTC)

        create_resp = client.post("/initgame", json={"opp": "robot-0"})
        data = create_resp.get_json()
        assert data is not None
        game_id = data["uuid"]

        # Get the current move count
        state_resp = client.post("/gamestate", json={"game": game_id})
        state_data = state_resp.get_json()
        assert state_data is not None and state_data.get("ok") is True
        num_moves = state_data["game"].get("num_moves", 0)

        # Submit a pass
        move_resp = client.post(
            "/submitmove",
            json={
                "uuid": game_id,
                "mcount": num_moves,
                "moves": ["pass"],
            },
        )
        move_data = move_resp.get_json()
        assert move_data is not None
        assert move_data.get("result") == 0

        after_move = datetime.now(UTC)

        # Verify ts_last_move on the game entity
        game = db.get_game(game_id)
        assert game is not None
        ts_last = assert_utc_datetime(game.ts_last_move, "Game.ts_last_move")
        assert before_game <= ts_last <= after_move

        # ts_last_move should match the last move's timestamp
        last_move_ts = assert_utc_datetime(
            game.moves[-1].timestamp, "Last move timestamp"
        )
        assert ts_last == last_move_ts

        auth.logout()
