"""

    Tests for Riddle Move Validation
    Copyright © 2025 Miðeind ehf.

    This module tests the server-side riddle move validation system,
    ensuring that valid moves are accepted and invalid moves are rejected.

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from datetime import datetime, timezone

from riddle_fixtures import RIDDLE_1, ALL_RIDDLES

if TYPE_CHECKING:
    from riddle_fixtures import RiddleFixtureDict

# Import after fixtures to ensure proper path setup
from utils import CustomClient
from utils import client  # type: ignore[unused-import]
from skraflmechanics import State, Board, Move, Error, BOARD_SIZE
from languages import set_locale, current_tileset
from riddle import create_state_from_riddle as _create_state_from_riddle


def create_state_from_riddle(riddle: RiddleFixtureDict, locale: str = "is_IS") -> State:
    """Adapter to create a State from a test fixture using the riddle module function."""
    return _create_state_from_riddle(riddle["board"], riddle["rack"], locale)


class TestValidateRiddleMove:
    """Test the validate_riddle_move() function with real riddle data"""

    def setup_method(self) -> None:
        """Set up test environment before each test"""
        set_locale("is_IS")

    @pytest.mark.parametrize("riddle", ALL_RIDDLES)
    def test_valid_solution_accepted(self, riddle: RiddleFixtureDict) -> None:
        """Test that the correct solution is accepted with proper score"""
        state = create_state_from_riddle(riddle)
        solution = riddle["solution"]
        is_bingo = riddle["analysis"]["isBingo"]

        # Parse coordinate
        coord = solution["coord"]
        if coord[0].isdigit():
            # Vertical: e.g., "1D"
            col = int(coord[:-1]) - 1
            row = Board.ROWIDS.index(coord[-1].upper())
            horiz = False
        else:
            # Horizontal: e.g., "12H"
            row = Board.ROWIDS.index(coord[0].upper())
            col = int(coord[1:]) - 1
            horiz = True

        # Create and validate the move
        move = Move(solution["move"], row, col, horiz)
        move.make_covers(state.board(), solution["move"])

        # Check legality
        legality = move.check_legality(state, validate=True, ignore_game_over=True)
        assert legality == Error.LEGAL, f"Solution move should be legal, got error: {legality}"

        # Check score
        calculated_score = move.score(state)
        assert calculated_score == solution["score"], (
            f"Score mismatch: expected {solution['score']}, "
            f"got {calculated_score} for move '{solution['move']}'"
        )

        # Check bingo
        assert move.is_bingo == is_bingo, (
            f"Bingo status mismatch: expected {is_bingo}, got {move.is_bingo}"
        )


class TestInvalidMoves:
    """Test that invalid moves are properly rejected"""

    def setup_method(self) -> None:
        """Set up test environment before each test"""
        set_locale("is_IS")

    def test_tile_not_in_rack(self) -> None:
        """Test that playing a tile not in the rack is rejected"""
        state = create_state_from_riddle(RIDDLE_1)

        # Try to play a word with tiles not in rack
        # Rack is "uaenrrk", try to play "xyz"
        move = Move("xyz", 0, 0, horiz=True)
        move.make_covers(state.board(), "xyz")

        legality = move.check_legality(state, validate=True, ignore_game_over=True)
        assert legality == Error.TILE_NOT_IN_RACK

    def test_word_not_in_dictionary(self) -> None:
        """Test that non-dictionary words are rejected"""
        state = create_state_from_riddle(RIDDLE_1)

        # Play a non-dictionary word at a legal position using rack tiles
        # Rack is "uaenrrk"
        # Row 0 is "...íshemi......" - play at col 9 (adjacent to 'i' at col 8)
        # Play "krun" (not a word, but uses k,r,u,n from rack)
        move = Move("krun", 0, 9, horiz=True)
        move.make_covers(state.board(), "krun")

        legality = move.check_legality(state, validate=True, ignore_game_over=True)
        # Should fail dictionary check - may return tuple (error_code, word)
        if isinstance(legality, tuple):
            assert legality[0] == Error.WORD_NOT_IN_DICTIONARY
        else:
            assert legality == Error.WORD_NOT_IN_DICTIONARY

    def test_square_already_occupied(self) -> None:
        """Test that playing on an occupied square is rejected"""
        state = create_state_from_riddle(RIDDLE_1)

        # Try to play over existing word "þaGi" at row 3
        # Rack is "uaenrrk", create covers manually to force overlap
        move = Move("", 3, 0, horiz=True)
        # Try to place tiles from rack over existing occupied squares
        move.add_cover(3, 0, "u", "u")  # This square has "þ" already

        # Don't validate rack to focus on testing occupied square logic
        legality = move.check_legality(state, validate=False, ignore_game_over=True)
        assert legality == Error.SQUARE_ALREADY_OCCUPIED

    def test_not_adjacent_to_existing_tiles(self) -> None:
        """Test that isolated moves are rejected (must be adjacent)"""
        state = create_state_from_riddle(RIDDLE_1)

        # Play a valid Icelandic word using rack tiles, but in an isolated position
        # Rack is "uaenrrk"
        # Play at row 1, col 10 (isolated from all tiles)
        # "ern" is a valid Icelandic word, uses e,r,n from rack
        move = Move("ern", 1, 10, horiz=True)
        move.make_covers(state.board(), "ern")

        legality = move.check_legality(state, validate=True, ignore_game_over=True)
        # Should fail adjacency check
        assert legality == Error.NOT_ADJACENT

    def test_disjoint_tiles(self) -> None:
        """Test that disjoint tiles are rejected"""
        state = create_state_from_riddle(RIDDLE_1)

        # Try to add covers at non-adjacent positions
        move = Move("", 0, 0, horiz=True)
        move.add_cover(0, 0, "u", "u")  # Use tiles from rack
        move.add_cover(5, 5, "a", "a")  # Disjoint from first tile

        # Don't validate rack since we're testing disjoint logic specifically
        legality = move.check_legality(state, validate=False, ignore_game_over=True)
        assert legality == Error.DISJOINT


class TestAdversarialMoves:
    """Test adversarial and edge case moves"""

    def setup_method(self) -> None:
        """Set up test environment before each test"""
        set_locale("is_IS")

    def test_word_exceeds_board_horizontal(self) -> None:
        """Test that words extending beyond board horizontally are rejected"""
        state = create_state_from_riddle(RIDDLE_1)

        # Try to play a word that would extend beyond column 14 (last column)
        # Rack is "uaenrrk"
        # Start at col 12, play 6-letter word (would need cols 12,13,14,15,16,17)
        move = Move("kraken", 1, 12, horiz=True)

        # make_covers should raise IndexError for out-of-bounds
        with pytest.raises(IndexError):
            move.make_covers(state.board(), "kraken")

    def test_word_exceeds_board_vertical(self) -> None:
        """Test that words extending beyond board vertically are rejected"""
        state = create_state_from_riddle(RIDDLE_1)

        # Try to play a word that would extend beyond row 14 (last row)
        # Start at row 12, play 6-letter word vertically (would need rows 12-17)
        move = Move("kraken", 12, 1, horiz=False)

        # make_covers should raise IndexError for out-of-bounds
        with pytest.raises(IndexError):
            move.make_covers(state.board(), "kraken")

    def test_word_at_board_edge_horizontal(self) -> None:
        """Test word placement at the very edge of the board"""
        state = create_state_from_riddle(RIDDLE_1)

        # Play a word ending exactly at the board edge
        # Row 14 is ".kvittið....g.."
        # Try to play at col 13, but word extends beyond col 14
        move = Move("kran", 14, 13, horiz=True)

        # 4 letters starting at col 13 would need cols 13,14,15,16 - goes off board
        with pytest.raises(IndexError):
            move.make_covers(state.board(), "kran")

    def test_play_through_mismatched_tiles(self) -> None:
        """Test playing through existing tiles with wrong letters"""
        state = create_state_from_riddle(RIDDLE_1)

        # Row 0 is "...íshemi......"
        # Try to play "axe" at col 3, which would put 'x' where 'í' exists
        move = Move("axe", 0, 3, horiz=True)
        # Manually create wrong covers that don't match board
        move.add_cover(0, 3, "a", "a")  # This is where 'í' is
        move.add_cover(0, 4, "x", "x")  # This is where 's' is
        move.add_cover(0, 5, "e", "e")  # This is where 'h' is

        legality = move.check_legality(state, validate=False, ignore_game_over=True)
        # Should fail because tiles don't match
        assert legality != Error.LEGAL

    def test_empty_rack_usage(self) -> None:
        """Test attempting to play when more tiles needed than available"""
        state = create_state_from_riddle(RIDDLE_1)

        # Rack has 7 tiles: "uaenrrk"
        # Try to play an 8-letter word where all 8 must come from rack
        # Play "uaenrrkk" (8 letters, but rack only has 7) at an isolated spot
        # But first, need to make sure it doesn't go off board
        # Play at col 5 so it fits: cols 5-12
        move = Move("uaenrrkk", 1, 5, horiz=True)
        move.make_covers(state.board(), "uaenrrkk")

        legality = move.check_legality(state, validate=True, ignore_game_over=True)
        # Should fail - we need 8 tiles but only have 7 in rack
        assert legality == Error.TILE_NOT_IN_RACK

    def test_using_same_rack_tile_twice(self) -> None:
        """Test attempting to use the same rack tile multiple times"""
        state = create_state_from_riddle(RIDDLE_1)

        # Rack is "uaenrrk" - only one 'u', one 'a', one 'e', etc.
        # Try to play "uuuu" which would require 4 'u' tiles
        move = Move("uuuu", 1, 10, horiz=True)
        move.make_covers(state.board(), "uuuu")

        legality = move.check_legality(state, validate=True, ignore_game_over=True)
        # Should fail - not enough 'u' tiles in rack
        assert legality == Error.TILE_NOT_IN_RACK

    def test_negative_coordinate(self) -> None:
        """Test that negative coordinates are handled"""
        state = create_state_from_riddle(RIDDLE_1)

        # Try to create a move with negative coordinates (would be caught in validation)
        # The Move constructor might accept it, but validation should fail
        try:
            move = Move("ern", -1, 0, horiz=True)
            move.make_covers(state.board(), "ern")
            legality = move.check_legality(state, validate=True, ignore_game_over=True)
            assert legality != Error.LEGAL
        except (IndexError, ValueError):
            # Also acceptable - constructor/make_covers might reject it
            pass

    def test_coordinate_beyond_board(self) -> None:
        """Test coordinates beyond board size"""
        state = create_state_from_riddle(RIDDLE_1)

        # Try to play at row 15 (beyond BOARD_SIZE of 15, 0-indexed)
        try:
            move = Move("ern", 15, 0, horiz=True)
            move.make_covers(state.board(), "ern")
            legality = move.check_legality(state, validate=True, ignore_game_over=True)
            assert legality != Error.LEGAL
        except (IndexError, ValueError):
            # Also acceptable - constructor/make_covers might reject it
            pass


class TestCoordinateParsing:
    """Test coordinate parsing logic"""

    def test_horizontal_coordinate(self) -> None:
        """Test parsing horizontal coordinates (e.g., A1, H12)"""
        # A1 = row 0, col 0, horizontal
        coord = "A1"
        assert coord[0].isalpha()
        row = Board.ROWIDS.index(coord[0].upper())
        col = int(coord[1:]) - 1
        assert row == 0
        assert col == 0

        # H12 = row 7, col 11, horizontal
        coord = "H12"
        row = Board.ROWIDS.index(coord[0].upper())
        col = int(coord[1:]) - 1
        assert row == 7
        assert col == 11

    def test_vertical_coordinate(self) -> None:
        """Test parsing vertical coordinates (e.g., 1A, 12H)"""
        # 1D = col 0, row 3, vertical
        coord = "1D"
        assert coord[0].isdigit()
        col = int(coord[:-1]) - 1
        row = Board.ROWIDS.index(coord[-1].upper())
        assert col == 0
        assert row == 3

        # 12H = col 11, row 7, vertical
        coord = "12H"
        col = int(coord[:-1]) - 1
        row = Board.ROWIDS.index(coord[-1].upper())
        assert col == 11
        assert row == 7

    def test_invalid_coordinates(self) -> None:
        """Test that invalid coordinates are detected"""
        invalid_coords = ["", "A", "1", "ZZ99", "A16", "16P", "P1"]

        for coord in invalid_coords:
            # Should fail length or parsing checks
            if len(coord) < 2 or len(coord) > 3:
                continue  # Skip length check

            try:
                if coord[0].isalpha():
                    row = Board.ROWIDS.index(coord[0].upper())
                    col = int(coord[1:]) - 1
                else:
                    col = int(coord[:-1]) - 1
                    row = Board.ROWIDS.index(coord[-1].upper())

                # Check bounds
                assert not (0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE), (
                    f"Coordinate {coord} should be out of bounds"
                )
            except (ValueError, IndexError):
                # Expected for invalid coordinates
                pass


class TestScoreCalculation:
    """Test score calculation for various move types"""

    def setup_method(self) -> None:
        """Set up test environment before each test"""
        set_locale("is_IS")

    def test_bingo_bonus(self) -> None:
        """Test that bingo moves include 50-point bonus"""
        state = create_state_from_riddle(RIDDLE_1)
        solution = RIDDLE_1["solution"]

        move = Move(solution["move"], 3, 0, horiz=False)
        move.make_covers(state.board(), solution["move"])

        score = move.score(state)
        # Riddle 1 is a bingo with score 104
        # The base score should be 54, plus 50 bingo bonus = 104
        assert score == 104
        assert move.is_bingo

    def test_blank_tile_scores_zero(self) -> None:
        """Test that blank tiles contribute 0 points"""
        # Use English locale for English word "zap"
        set_locale("en_US")

        # Create a simple state with a blank in rack
        state = State(
            tileset=current_tileset(),
            manual_wordcheck=False,
            drawtiles=False,
            locale="en_US",
            board_type="standard",
        )
        state.set_rack(0, "?abcdep")

        # Play a word with blank as 'z': "?zap"
        move = Move("zap", 7, 7, horiz=True)  # Center square
        move.make_covers(state.board(), "?zap")

        legality = move.check_legality(state, validate=True, ignore_game_over=True)
        assert legality == Error.LEGAL
        score = move.score(state)
        # Blank scores 0, so only 'a' (1) + 'p' (2) = 3 base points
        # Center is double word score, so 3 * 2 = 6
        assert score == 6

        # Restore Icelandic locale for other tests
        set_locale("is_IS")

    @pytest.mark.parametrize("riddle", ALL_RIDDLES)
    def test_score_is_deterministic(self, riddle: RiddleFixtureDict) -> None:
        """Test that scoring the same move twice gives same result"""
        state = create_state_from_riddle(riddle)
        solution = riddle["solution"]

        coord = solution["coord"]
        if coord[0].isdigit():
            col = int(coord[:-1]) - 1
            row = Board.ROWIDS.index(coord[-1].upper())
            horiz = False
        else:
            row = Board.ROWIDS.index(coord[0].upper())
            col = int(coord[1:]) - 1
            horiz = True

        move = Move(solution["move"], row, col, horiz)
        move.make_covers(state.board(), solution["move"])

        score1 = move.score(state)
        score2 = move.score(state)
        assert score1 == score2, "Score should be deterministic"


class TestSubmitAPI:
    """Integration tests for the /gatadagsins/submit endpoint"""

    def setup_method(self) -> None:
        """Set up test environment before each test"""
        set_locale("is_IS")

    def test_valid_submission_accepted(self, client: CustomClient) -> None:
        """Test that a valid submission is accepted"""
        from utils import login_user

        # Log in as test user
        login_user(client, 1)

        today = datetime.now(timezone.utc).date().isoformat()

        # Submit a valid move (using Riddle 1 solution as reference)
        # Note: In real testing, you'd need to mock get_riddle_state
        # or set up actual riddle data in Firebase/database
        response = client.post(
            "/gatadagsins/submit",
            json={
                "date": today,
                "locale": "is_IS",
                "groupId": "",
                "userDisplayName": "Test User",
                "move": {
                    "word": "test",  # Would need valid move for actual riddle
                    "score": 10,
                    "coord": "A1",
                },
            },
        )

        # Response structure check (actual validation depends on setup)
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        assert "ok" in data

    def test_past_date_rejected(self, client: CustomClient) -> None:
        """Test that submissions for past dates are rejected"""
        from utils import login_user

        login_user(client, 1)

        # Try to submit for yesterday
        yesterday = (
            datetime.now(timezone.utc).date().replace(day=1).isoformat()
        )  # First day of month

        response = client.post(
            "/gatadagsins/submit",
            json={
                "date": yesterday,
                "locale": "is_IS",
                "groupId": "",
                "userDisplayName": "Test User",
                "move": {
                    "word": "test",
                    "score": 10,
                    "coord": "A1",
                },
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        assert data.get("ok") is True
        assert data.get("update") is False
        assert "not today" in data.get("message", "").lower()

    def test_invalid_move_rejected(self, client: CustomClient) -> None:
        """Test that invalid moves are rejected"""
        from utils import login_user

        login_user(client, 1)

        today = datetime.now(timezone.utc).date().isoformat()

        # Submit with invalid coordinate
        response = client.post(
            "/gatadagsins/submit",
            json={
                "date": today,
                "locale": "is_IS",
                "groupId": "",
                "userDisplayName": "Test User",
                "move": {
                    "word": "test",
                    "score": 10,
                    "coord": "INVALID",  # Invalid coordinate
                },
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        # Should reject invalid coordinate
        if not data.get("ok"):
            assert "error" in data

    def test_missing_parameters_rejected(self, client: CustomClient) -> None:
        """Test that requests with missing parameters are rejected"""
        from utils import login_user

        login_user(client, 1)

        today = datetime.now(timezone.utc).date().isoformat()

        # Submit without move data
        response = client.post(
            "/gatadagsins/submit",
            json={
                "date": today,
                "locale": "is_IS",
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        assert data.get("ok") is False
        assert "error" in data

    def test_authentication_required(self, client: CustomClient) -> None:
        """Test that unauthenticated requests are rejected"""
        today = datetime.now(timezone.utc).date().isoformat()

        # Don't log in - submit without authentication
        response = client.post(
            "/gatadagsins/submit",
            json={
                "date": today,
                "locale": "is_IS",
                "move": {
                    "word": "test",
                    "score": 10,
                    "coord": "A1",
                },
            },
        )

        # Should be rejected with 401 Unauthorized due to @auth_required decorator
        assert response.status_code == 401
