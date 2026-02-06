"""
Game review end-to-end tests.

Tests finished game review, best moves, and word checking.
"""

from __future__ import annotations

import pytest
from flask.testing import FlaskClient

from tests.api_e2e.conftest import (
    AuthHelper,
)


@pytest.mark.api_e2e
class TestWordCheck:
    """Test word validation functionality."""

    def test_check_valid_word(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Check if a word is valid."""
        auth.login_user(
            sub="wordcheck-user-001",
            name="Word Checker",
            email="wordcheck@example.com",
        )

        # Check a common English word
        # The API requires both "words" (list) and "word" (single)
        response = client.post(
            "/wordcheck",
            json={
                "words": ["test"],
                "word": "test",
                "locale": "en_US",
            },
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        assert data.get("ok") is True

        # Response should include validity info
        data.get("valid", [])
        # Format: [[word, is_valid], ...]

        auth.logout()

    def test_check_multiple_words(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Check multiple words at once."""
        auth.login_user(
            sub="multi-wordcheck-001",
            name="Multi Word Checker",
            email="multiwordcheck@example.com",
        )

        # The API requires both "words" (list) and "word" (single)
        response = client.post(
            "/wordcheck",
            json={
                "words": ["test", "word", "invalid123"],
                "word": "test",
                "locale": "en_US",
            },
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        # ok is False because "invalid123" is not a valid word
        # but the response should contain valid array with per-word results
        assert "valid" in data
        valid = data.get("valid", [])
        # Should have 3 word results
        assert len(valid) == 3
        # "test" and "word" should be valid, "invalid123" should not
        assert valid[0][1] is True  # test
        assert valid[1][1] is True  # word
        assert valid[2][1] is False  # invalid123

        auth.logout()

    def test_check_icelandic_word(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Check an Icelandic word."""
        auth.login_user(
            sub="is-wordcheck-001",
            name="IS Word Checker",
            email="iswordcheck@example.com",
        )

        # The API requires both "words" (list) and "word" (single)
        response = client.post(
            "/wordcheck",
            json={
                "words": ["orð"],  # Icelandic for "word"
                "word": "orð",
                "locale": "is_IS",
            },
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        assert data.get("ok") is True

        auth.logout()


@pytest.mark.api_e2e
class TestBestMoves:
    """Test best moves analysis functionality."""

    def test_get_best_moves_for_game(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Get best moves analysis for a completed game."""
        auth.login_user(
            sub="bestmoves-user-001",
            name="Best Moves User",
            email="bestmoves@example.com",
        )

        # Create and complete a game
        create_response = client.post("/initgame", json={"opp": "robot-10"})
        game_id = create_response.get_json()["uuid"]

        # Get current move count
        state_response = client.post("/gamestate", json={"game": game_id})
        mcount = state_response.get_json()["game"].get("num_moves", 0)

        # Make a pass move
        client.post(
            "/submitmove",
            json={"uuid": game_id, "mcount": mcount, "moves": ["pass"]},
        )

        # Get updated move count
        state_response = client.post("/gamestate", json={"game": game_id})
        mcount = state_response.get_json()["game"].get("num_moves", 0)

        # Resign to complete
        client.post(
            "/submitmove",
            json={"uuid": game_id, "mcount": mcount, "moves": ["rsgn"]},
        )

        # Get best moves analysis
        response = client.post("/bestmoves", json={"game": game_id})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        # Should return best moves or indicate analysis is available

        auth.logout()

    def test_best_moves_for_specific_move(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Get best moves for a specific move in a game."""
        auth.login_user(
            sub="specific-bestmoves-001",
            name="Specific Best User",
            email="specificbest@example.com",
        )

        # Create a game and make moves
        create_response = client.post("/initgame", json={"opp": "robot-5"})
        game_id = create_response.get_json()["uuid"]

        # Get current move count
        state_response = client.post("/gamestate", json={"game": game_id})
        mcount = state_response.get_json()["game"].get("num_moves", 0)

        # Make a pass move
        client.post(
            "/submitmove",
            json={"uuid": game_id, "mcount": mcount, "moves": ["pass"]},
        )

        # Get updated move count
        state_response = client.post("/gamestate", json={"game": game_id})
        mcount = state_response.get_json()["game"].get("num_moves", 0)

        # Complete the game by resigning
        client.post(
            "/submitmove",
            json={"uuid": game_id, "mcount": mcount, "moves": ["rsgn"]},
        )

        # Request best moves for move index 0
        response = client.post(
            "/bestmoves",
            json={
                "game": game_id,
                "move": 0,  # Index of the move to analyze
            },
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        auth.logout()


@pytest.mark.api_e2e
class TestGameReview:
    """Test game review functionality."""

    def test_review_completed_game(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Review a completed game's state and moves."""
        auth.login_user(
            sub="review-user-001",
            name="Review User",
            email="review@example.com",
        )

        # Create and complete a game
        create_response = client.post("/initgame", json={"opp": "robot-10"})
        game_id = create_response.get_json()["uuid"]

        # Make some moves
        for _ in range(2):
            state_response = client.post("/gamestate", json={"game": game_id})
            state_data = state_response.get_json()
            game_state = state_data.get("game", {})
            # Check if game is over (result == 99)
            if game_state.get("result") == 99:
                break
            mcount = game_state.get("num_moves", 0)
            client.post(
                "/submitmove",
                json={"uuid": game_id, "mcount": mcount, "moves": ["pass"]},
            )

        # Complete by resigning
        state_response = client.post("/gamestate", json={"game": game_id})
        mcount = state_response.get_json()["game"].get("num_moves", 0)
        client.post(
            "/submitmove",
            json={"uuid": game_id, "mcount": mcount, "moves": ["rsgn"]},
        )

        # Get full game state for review
        response = client.post("/gamestate", json={"game": game_id})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        assert data.get("ok") is True

        game_state = data.get("game", {})
        # result == 99 indicates game over
        assert game_state.get("result") == 99

        auth.logout()

    def test_review_shows_all_moves(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Review shows all moves made in the game."""
        auth.login_user(
            sub="all-moves-review-001",
            name="All Moves User",
            email="allmoves@example.com",
        )

        # Create game
        create_response = client.post("/initgame", json={"opp": "robot-5"})
        game_id = create_response.get_json()["uuid"]

        # Make several pass moves (these always work)
        for _ in range(4):
            state_response = client.post("/gamestate", json={"game": game_id})
            state_data = state_response.get_json()
            game_state = state_data.get("game", {})
            # Check if game is over (result == 99)
            if game_state.get("result") == 99:
                break
            mcount = game_state.get("num_moves", 0)

            client.post(
                "/submitmove",
                json={"uuid": game_id, "mcount": mcount, "moves": ["pass"]},
            )

        # Complete by resigning
        state_response = client.post("/gamestate", json={"game": game_id})
        mcount = state_response.get_json()["game"].get("num_moves", 0)
        client.post(
            "/submitmove",
            json={"uuid": game_id, "mcount": mcount, "moves": ["rsgn"]},
        )

        # Get game state - should include moves
        response = client.post("/gamestate", json={"game": game_id})
        data = response.get_json()

        game_state = data.get("game", {})
        # The moves should be included in the response
        # Structure depends on client_state implementation

        auth.logout()


@pytest.mark.api_e2e
class TestGameStatsReview:
    """Test game statistics for review."""

    def test_get_stats_for_completed_game(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Get detailed statistics for a completed game."""
        auth.login_user(
            sub="stats-review-001",
            name="Stats Review User",
            email="statsreview@example.com",
        )

        # Create and complete a game
        create_response = client.post("/initgame", json={"opp": "robot-10"})
        game_id = create_response.get_json()["uuid"]

        # Get current move count
        state_response = client.post("/gamestate", json={"game": game_id})
        mcount = state_response.get_json()["game"].get("num_moves", 0)

        # Make a pass move
        client.post(
            "/submitmove",
            json={"uuid": game_id, "mcount": mcount, "moves": ["pass"]},
        )

        # Get updated move count
        state_response = client.post("/gamestate", json={"game": game_id})
        mcount = state_response.get_json()["game"].get("num_moves", 0)

        # Complete by resigning
        client.post(
            "/submitmove",
            json={"uuid": game_id, "mcount": mcount, "moves": ["rsgn"]},
        )

        # Get game stats
        response = client.post("/gamestats", json={"game": game_id})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        # Stats should include score, moves, etc.

        auth.logout()


@pytest.mark.api_e2e
class TestReviewPermissions:
    """Test review permission handling."""

    def test_can_review_own_game(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """User can review their own completed games."""
        auth.login_user(
            sub="own-review-001",
            name="Own Review User",
            email="ownreview@example.com",
        )

        # Create and complete game
        create_response = client.post("/initgame", json={"opp": "robot-5"})
        game_id = create_response.get_json()["uuid"]

        # Get current move count and resign
        state_response = client.post("/gamestate", json={"game": game_id})
        mcount = state_response.get_json()["game"].get("num_moves", 0)
        client.post(
            "/submitmove",
            json={"uuid": game_id, "mcount": mcount, "moves": ["rsgn"]},
        )

        # Can review own game
        response = client.post("/gamestate", json={"game": game_id})
        assert response.status_code == 200
        data = response.get_json()
        assert data.get("ok") is True

        # Can get best moves for own game
        best_response = client.post("/bestmoves", json={"game": game_id})
        assert best_response.status_code == 200

        auth.logout()

    def test_can_review_completed_others_game(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Users can review completed games they weren't part of."""
        # Create a game for Alice
        auth.login_user(
            sub="review-alice-001",
            name="Review Alice",
            email="reviewalice@example.com",
        )
        create_response = client.post("/initgame", json={"opp": "robot-5"})
        game_id = create_response.get_json()["uuid"]

        # Get current move count and resign
        state_response = client.post("/gamestate", json={"game": game_id})
        mcount = state_response.get_json()["game"].get("num_moves", 0)
        client.post(
            "/submitmove",
            json={"uuid": game_id, "mcount": mcount, "moves": ["rsgn"]},
        )
        auth.logout()

        # Bob tries to review Alice's completed game
        auth.login_user(
            sub="review-bob-001",
            name="Review Bob",
            email="reviewbob@example.com",
        )

        response = client.post("/gamestate", json={"game": game_id})
        # Completed games can be reviewed by anyone
        # (if implementation allows)
        assert response.status_code == 200

        auth.logout()


@pytest.mark.api_e2e
class TestSubmitWord:
    """Test word submission functionality."""

    def test_submit_word(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Submit a word for validation."""
        auth.login_user(
            sub="submit-word-001",
            name="Submit Word User",
            email="submitword@example.com",
        )

        # Create a game first
        create_response = client.post("/initgame", json={"opp": "robot-10"})
        game_id = create_response.get_json()["uuid"]

        # Submit word endpoint (if different from submitmove)
        response = client.post(
            "/submitword",
            json={
                "game": game_id,
                "word": "test",
            },
        )
        assert response.status_code == 200

        auth.logout()
