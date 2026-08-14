"""

    Tests for the /moves API endpoint
    Copyright © 2026 Miðeind ehf.

    The /moves endpoint forwards authenticated requests to the GoSkrafl
    moves service (see src/movesservice.py). In the test environment no
    sidecar is running, so the request is forwarded to the external
    GAE-hosted moves service - i.e. this test exercises the real
    forwarding path over the network.

"""

from typing import Any, Dict, List

from utils import CustomClient, login_user

# An empty 15x15 board, as 15 rows of 15 spaces
EMPTY_BOARD: List[str] = [" " * 15] * 15


def test_moves_requires_login(client: CustomClient) -> None:
    resp = client.post(
        "/moves",
        data=dict(locale="is_IS", board_type="standard", rack="aeinrs"),
    )
    assert resp.status_code == 401


def test_moves(client: CustomClient, u1: str) -> None:
    login_user(client, 1)
    resp = client.post(
        "/moves",
        json=dict(
            locale="is_IS",
            board_type="standard",
            board=EMPTY_BOARD,
            rack="aðeins",
            limit=10,
        ),
    )
    assert resp.status_code == 200
    assert resp.json is not None
    result: Dict[str, Any] = resp.json
    # The moves service replies with {version, count, moves}
    assert result.get("count", 0) > 0
    moves = result.get("moves")
    assert isinstance(moves, list)
    assert 0 < len(moves) <= 10
    assert len(moves) == result["count"]


def test_board_row_strings() -> None:
    """The Board→moves-service serialization: '.' for empty squares,
    lowercase for normal tiles, uppercase for assigned blanks"""
    from skraflmechanics import Board

    b = Board(board_type="standard")
    b.set_tile(7, 7, "h")
    b.set_letter(7, 7, "h")
    # A blank tile assigned the letter 'ú'
    b.set_tile(7, 8, "?")
    b.set_letter(7, 8, "ú")
    rows = b.row_strings()
    assert len(rows) == 15
    assert all(len(r) == 15 for r in rows)
    assert rows[0] == "." * 15
    assert rows[7][7] == "h"
    assert rows[7][8] == "Ú"


def test_best_moves_equivalence() -> None:
    """The in-process Python engine and the moves service must generate
    the same move set, with the same scores, for the same position.

    Note: the position must not be an empty board - empty-board first
    moves have a horizontal/vertical mirror symmetry, and the two engines
    (nondeterministically, in the Go case) differ in which orientation
    they report for each placement. On a non-empty board every placement
    is unique and the move sets must match exactly."""
    from skraflmechanics import State
    from skraflplayer import AutoPlayer
    from languages import tileset_for_locale, set_locale
    from movesservice import best_moves_from_service

    locale = "is_IS"
    set_locale(locale)
    state = State(
        tileset=tileset_for_locale(locale),
        drawtiles=False,
        locale=locale,
        board_type="standard",
    )
    # Place "hún" horizontally through the center square,
    # with the ú being a blank tile
    board = state.board()
    for col, (tile, letter) in enumerate(
        [("h", "h"), ("?", "ú"), ("n", "n")], start=6
    ):
        board.set_tile(7, col, tile)
        board.set_letter(7, col, letter)
    rack = "aðeins"
    state.set_rack(0, rack)

    # All moves from the Python engine (n=0 means no limit)
    apl = AutoPlayer(0, state)
    python_moves = {m.summary(state) for m, _ in apl.generate_best_moves(0)}

    # All moves from the moves service (limit=0 means no limit)
    service_moves = best_moves_from_service(
        locale=locale,
        board_type="standard",
        board=board.row_strings(),
        rack=rack,
        limit=0,
    )
    assert service_moves is not None
    assert len(python_moves) > 0
    assert python_moves == set(service_moves)


def test_moves_invalid_board(client: CustomClient, u1: str) -> None:
    login_user(client, 1)
    # Wrong number of board rows: rejected locally with a 400 status
    resp = client.post(
        "/moves",
        json=dict(
            locale="is_IS",
            board_type="standard",
            board=[" " * 15] * 14,
            rack="aeinrs",
        ),
    )
    assert resp.status_code == 400

