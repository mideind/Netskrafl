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

