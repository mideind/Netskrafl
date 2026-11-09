"""

    Tests for the /moves API endpoint
    Copyright © 2026 Miðeind ehf.

    The /moves endpoint forwards authenticated requests to the GoSkrafl
    moves service (see src/movesservice.py). In the test environment no
    sidecar is running, so the request is forwarded to the external
    GAE-hosted moves service - i.e. this test exercises the real
    forwarding path over the network.

"""

from typing import Any, Dict, List, Tuple

from collections import Counter

import pytest

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


# Board positions for the engine tests, as (row, col, horizontal, word)
# placements: a single word through the center, and an L shape in which
# single tiles can touch tiles both across and down
LINE_LAYOUT: List[Tuple[int, int, bool, str]] = [(7, 5, True, "hestur")]
L_LAYOUT: List[Tuple[int, int, bool, str]] = [
    (7, 5, True, "hestur"),
    (7, 7, False, "stór"),
    (10, 8, True, "ós"),
]


def _engine_position(layout: List[Tuple[int, int, bool, str]], rack: str) -> Any:
    """Return an is_IS State with the given words on the board
    (all real tiles) and the given rack for player 0"""
    from skraflmechanics import State
    from languages import tileset_for_locale, set_locale

    locale = "is_IS"
    set_locale(locale)
    state = State(
        tileset=tileset_for_locale(locale),
        drawtiles=False,
        locale=locale,
        board_type="standard",
    )
    board = state.board()
    for row, col, horizontal, word in layout:
        for k, letter in enumerate(word):
            r, c = (row, col + k) if horizontal else (row + k, col)
            board.set_tile(r, c, letter)
            board.set_letter(r, c, letter)
    state.set_rack(0, rack)
    return state


@pytest.mark.parametrize(
    "layout,rack",
    [
        (LINE_LAYOUT, "aðeinst"),
        (LINE_LAYOUT, "aðeins?"),
        (L_LAYOUT, "aðeinst"),
        (L_LAYOUT, "aaði?nn"),
        (L_LAYOUT, "eeirr?s"),
    ],
)
def test_best_moves_equivalence(
    layout: List[Tuple[int, int, bool, str]], rack: str
) -> None:
    """The in-process Python engine and the moves service must generate
    the same moves, with the same scores, for the same position: the
    same multiset, so that a move generated twice by one engine fails
    the test too. The racks with a blank exercise every placement of
    the blank; the L-shaped layout has single-tile moves that form
    words both across and down.

    Note: the position must not be an empty board - empty-board first
    moves have a horizontal/vertical mirror symmetry, and the two engines
    (nondeterministically, in the Go case) differ in which orientation
    they report for each placement. On a non-empty board every placement
    is unique and the move lists must match exactly."""
    from skraflplayer import AutoPlayer
    from movesservice import best_moves_from_service

    state = _engine_position(layout, rack)
    # All moves from the Python engine (n=0 means no limit)
    apl = AutoPlayer(0, state)
    python_moves = Counter(m.summary(state) for m, _ in apl.generate_best_moves(0))

    # All moves from the moves service (limit=0 means no limit)
    service_moves = best_moves_from_service(
        locale="is_IS",
        board_type="standard",
        board=state.board().row_strings(),
        rack=rack,
        limit=0,
    )
    assert service_moves is not None
    assert len(python_moves) > 0
    assert python_moves == Counter(tuple(m) for m in service_moves)


def test_engine_blank_placements_and_no_duplicates() -> None:
    """The Python engine generates a move for every placement of a blank,
    and each single-tile move only once. Runs without the moves service."""
    from skraflmechanics import Move
    from skraflplayer import AutoPlayer

    state = _engine_position(L_LAYOUT, "aaði?nn")
    moves = [m for m, _ in AutoPlayer(0, state).generate_best_moves(0)]
    assert all(isinstance(m, Move) for m in moves)
    summaries = {m.summary(state) for m in moves}
    # 'naðrana' needs three a's and the rack has two, so the blank stands
    # for one of them. Each choice is a distinct move: the engine once
    # generated only the last one, which scores the least
    for placement, score in (("n?aðrana", 40), ("naðr?ana", 40), ("naðran?a", 38)):
        assert ("11E", placement, score) in summaries
    # No two moves lay down the same tiles on the same squares
    covers = Counter(
        frozenset((c.row, c.col, c.tile, c.letter) for c in m.covers())
        for m in moves
        if isinstance(m, Move)
    )
    assert max(covers.values()) == 1


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

