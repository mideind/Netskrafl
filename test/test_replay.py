"""

    Replay tests for Netskrafl / Explo Word Game
    Copyright © 2026 Miðeind ehf.

    This module replays production games, sampled and exported as JSON
    fixtures by utils/sample_replay_games.py, through the /initgame and
    /submitmove APIs against the active database backend. It verifies
    that the engine reproduces the original games exactly: same move
    legality, same per-move scores, same challenge verdicts (in manual
    wordcheck games), same game-over detection and same final scores
    including endgame rack adjustments.

    Since tile draws from the bag are random, the harness forces them to
    conform to history: after each submitted move, the mover's rack is
    overwritten with the rack recorded in the original game (the same
    override mechanism that Game._load_locked uses when deserializing a
    stored game). The bag is derived state (recalculated on every load
    as full bag minus board minus racks), so forcing the racks keeps the
    entire game state consistent with history.

    Challenge responses (RESP moves) are not submitted by the client;
    the server generates them when a challenge (CHALL) is submitted.
    The harness therefore submits only the CHALL move and verifies the
    engine's verdict and rack retraction against the recorded RESP move.

    NOTE: Replayed moves are validated against the *current* vocabulary.
    A fixture may fail because a word has been added to or removed from
    the vocabulary since the original game was played ("vocabulary
    drift"), without any engine divergence. Such fixtures should be
    inspected and, if drift is confirmed, removed from the fixture set.

"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Tuple

import json
import os
from glob import glob

import pytest

from skrafldb import Client, GameModel, PrefsDict, ZombieModel
from skraflgame import Game

from utils import CustomClient, login_user

# Error codes used in API responses
LEGAL = 0
GAME_OVER = 99

ROWIDS = "ABCDEFGHIJKLMNO"

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "replay_fixtures")
FIXTURE_FILES = sorted(glob(os.path.join(FIXTURE_DIR, "game_*.json")))

pytestmark = pytest.mark.skipif(
    not FIXTURE_FILES,
    reason="No replay fixtures found; run utils/sample_replay_games.py first",
)

Fixture = Dict[str, Any]
MoveDict = Dict[str, Any]
CoverList = List[Tuple[int, int, str]]


def tile_pairs(tiles: str) -> List[Tuple[str, str]]:
    """Split a stored tiles string into (tile, letter) pairs, where a
    blank tile is stored as '?' followed by the letter it stands for"""
    pairs: List[Tuple[str, str]] = []
    ix = 0
    while ix < len(tiles):
        t = tiles[ix]
        if t == "?":
            ix += 1
            pairs.append(("?" + tiles[ix], tiles[ix]))
        else:
            pairs.append((t, t))
        ix += 1
    return pairs


def decode_coord(coord: str) -> Tuple[int, int, bool]:
    """Decode a stored move coordinate: 'A15' means horizontal,
    '15A' means vertical (same convention as Game._load_locked)"""
    if coord[0] in ROWIDS:
        return ROWIDS.index(coord[0]), int(coord[1:]) - 1, True
    return ROWIDS.index(coord[-1]), int(coord[:-1]) - 1, False


class BoardSim:
    """Tracks board square occupancy during a replay, in order to
    compute which squares of a stored tile move are fresh covers
    (mirroring Move.make_covers()) and to un-cover retracted moves
    after successful challenges"""

    def __init__(self) -> None:
        self.occupied = [[False] * 15 for _ in range(15)]

    def fresh_covers(self, coord: str, tiles: str) -> CoverList:
        """Return the (row, col, tile) covers that a stored move lays
        down on squares not already occupied"""
        row, col, horiz = decode_coord(coord)
        rd, cd = (0, 1) if horiz else (1, 0)
        covers: CoverList = []
        for tile, _ in tile_pairs(tiles):
            if not self.occupied[row][col]:
                covers.append((row, col, tile))
            row += rd
            col += cd
        return covers

    def place(self, covers: CoverList) -> None:
        for row, col, _ in covers:
            self.occupied[row][col] = True

    def retract(self, covers: CoverList) -> None:
        for row, col, _ in covers:
            self.occupied[row][col] = False


def load_game(game_id: str) -> Game:
    """Load a game from the active backend, bypassing the cache"""
    g = Game.load(game_id, use_cache=False)
    assert g is not None, f"Game {game_id} not found"
    assert g.state is not None
    return g


def move_tokens(board: BoardSim, mv: MoveDict) -> Tuple[List[str], CoverList]:
    """Translate a stored move into the token list that the client
    would send to /submitmove, plus the fresh covers of a tile move"""
    coord: str = mv["coord"]
    tiles: str = mv["tiles"]
    if coord:
        covers = board.fresh_covers(coord, tiles)
        assert covers, f"Tile move {coord} {tiles!r} yields no fresh covers"
        return [f"{ROWIDS[row]}{col + 1}={tile}" for row, col, tile in covers], covers
    if tiles.startswith("EXCH"):
        return ["exch=" + tiles[5:]], []
    if tiles == "PASS":
        return ["pass"], []
    if tiles == "RSGN":
        return ["rsgn"], []
    if tiles == "CHALL":
        return ["chall"], []
    pytest.fail(f"Unexpected stored move: coord={coord!r} tiles={tiles!r}")


def create_game(
    fixture: Fixture,
    client1: CustomClient,
    client2: CustomClient,
    u1: str,
    u2: str,
) -> Tuple[str, Dict[int, CustomClient]]:
    """Create a game between the two test users with the fixture's
    preferences and initial racks. Returns the game id and a mapping
    from fixture player index (0 moves first) to the API client that
    plays that side."""
    resp = login_user(client1, 1)
    assert resp.status_code == 200
    resp = login_user(client2, 2)
    assert resp.status_code == 200

    locale: str = fixture["locale"]
    prefs: Dict[str, Any] = fixture["prefs"]
    for c in (client1, client2):
        resp = c.post("/setuserpref", json=dict(locale=locale))
        assert resp.status_code == 200

    # User 1 challenges user 2 with the fixture's game preferences
    resp = client1.post(
        "/challenge",
        json=dict(
            action="issue",
            destuser=u2,
            manual=bool(prefs.get("manual", False)),
            fairplay=bool(prefs.get("fairplay", False)),
        ),
    )
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json["result"] == LEGAL

    # User 2 accepts the challenge, creating the game
    resp = client2.post("/initgame", json=dict(opp=u1))
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json.get("ok"), f"initgame failed: {resp.json}"
    game_id: str = resp.json["uuid"]

    # Game.new() randomizes which user moves first; map the fixture's
    # player 0 (who always moves first) onto whoever won the toss
    first_mover: str = resp.json["to_move"]
    if first_mover == u1:
        clients = {0: client1, 1: client2}
    else:
        assert first_mover == u2
        clients = {0: client2, 1: client1}

    # Force the fixture's preferences (board type, manual wordcheck,
    # tile bag) and initial racks onto the newly created game. The
    # board is still empty, so this is safe; every subsequent load
    # derives board type, tileset and bag from what we store here.
    with Client.get_context():
        g = load_game(game_id)
        game_prefs = PrefsDict(
            locale=locale,
            newbag=bool(prefs.get("newbag", True)),
            fairplay=bool(prefs.get("fairplay", False)),
            manual=bool(prefs.get("manual", False)),
            duration=int(prefs.get("duration", 0)),
        )
        if "board_type" in prefs:
            game_prefs["board_type"] = str(prefs["board_type"])
        g._preferences = game_prefs  # noqa: SLF001
        g.initial_racks[0] = fixture["irack0"]
        g.initial_racks[1] = fixture["irack1"]
        assert g.state is not None
        g.state.set_rack(0, fixture["irack0"])
        g.state.set_rack(1, fixture["irack1"])
        g.store(calc_elo_points=False)

    return game_id, clients


def replay_game(
    fixture: Fixture, game_id: str, clients: Dict[int, CustomClient]
) -> None:
    """Replay the fixture's moves through /submitmove, forcing racks to
    history after each move and verifying engine behavior throughout"""
    moves: List[MoveDict] = fixture["moves"]
    racks: List[str] = [fixture["irack0"], fixture["irack1"]]
    board = BoardSim()
    last_tile_covers: CoverList = []
    over = False
    i = 0

    while i < len(moves):
        mv = moves[i]
        player: int = mv["player"]
        tiles: str = mv["tiles"]
        assert tiles != "RESP", (
            f"Move {i}: RESP not preceded by CHALL in fixture"
        )
        tokens, covers = move_tokens(board, mv)

        resp = clients[player].post(
            "/submitmove",
            json=dict(uuid=game_id, moves=tokens, mcount=i),
        )
        assert resp.status_code == 200
        assert resp.json is not None
        result = resp.json.get("result")
        assert result in (LEGAL, GAME_OVER), (
            f"Move {i} ({mv['coord']!r} {tiles!r}) rejected: "
            f"result={result} msg={resp.json.get('msg')!r} "
            f"(if the word is no longer in the vocabulary, this is "
            f"vocabulary drift - consider removing this fixture)"
        )

        # A challenge move makes the server register two moves:
        # the CHALL and the auto-generated RESP verdict
        n_registered = 2 if tiles == "CHALL" else 1

        with Client.get_context():
            g = load_game(game_id)
            assert g.state is not None
            assert g.num_moves() == i + n_registered, (
                f"Move {i}: server has {g.num_moves()} moves, "
                f"expected {i + n_registered}"
            )
            # Verify the newly registered move(s) against history
            for k in range(i, i + n_registered):
                fm = moves[k]
                mt = g.moves[k]
                s_coord, s_tiles, s_score = mt.move.summary(g.state)
                assert mt.player == fm["player"]
                assert (s_coord, s_tiles, s_score) == (
                    fm["coord"],
                    fm["tiles"],
                    fm["score"],
                ), (
                    f"Move {k} diverges from history: engine produced "
                    f"{(s_coord, s_tiles, s_score)}, original game had "
                    f"{(fm['coord'], fm['tiles'], fm['score'])}"
                )
            if tiles == "CHALL":
                # The RESP move involves no tile draws, so the engine's
                # resulting rack must match history exactly: a successful
                # challenge returns the retracted tiles to the rack
                fm = moves[i + 1]
                mt = g.moves[i + 1]
                assert sorted(mt.rack) == sorted(fm["rack"]), (
                    f"Move {i + 1} (RESP): rack after challenge response "
                    f"is {mt.rack!r}, original game had {fm['rack']!r}"
                )
                if fm["score"] < 0:
                    # Successful challenge: the challenged tile move
                    # is retracted from the board
                    board.retract(last_tile_covers)
                    last_tile_covers = []
            over = g.is_over()

            # Update local tracking state
            for k in range(i, i + n_registered):
                fm = moves[k]
                racks[fm["player"]] = fm["rack"]
            if covers:
                board.place(covers)
                last_tile_covers = covers

            if not over:
                # Force the racks to conform to history, overriding the
                # random draws made by the server; also patch the rack
                # recorded with the stored move(s) so that the persisted
                # game history stays identical to the original
                g.state.set_rack(0, racks[0])
                g.state.set_rack(1, racks[1])
                for k in range(i, i + n_registered):
                    g.moves[k] = g.moves[k]._replace(rack=moves[k]["rack"])
                g.store(calc_elo_points=False)

        i += n_registered
        if over:
            break

    assert i == len(moves), (
        f"Game ended after {i} moves; original game had {len(moves)}"
    )

    # Verify the final state: game over, final scores (including
    # endgame rack adjustments) and final racks as in the original
    with Client.get_context():
        g = load_game(game_id)
        assert g.is_over(), "Game is not over after replaying all moves"
        assert g.state is not None
        fs = g.final_scores()
        assert (fs[0], fs[1]) == (fixture["score0"], fixture["score1"]), (
            f"Final scores diverge: engine {fs}, original game "
            f"({fixture['score0']}, {fixture['score1']})"
        )
        assert sorted(g.state.rack(0)) == sorted(fixture["rack0_final"]), (
            f"Final rack 0 diverges: engine {g.state.rack(0)!r}, "
            f"original game {fixture['rack0_final']!r}"
        )
        assert sorted(g.state.rack(1)) == sorted(fixture["rack1_final"]), (
            f"Final rack 1 diverges: engine {g.state.rack(1)!r}, "
            f"original game {fixture['rack1_final']!r}"
        )


@pytest.fixture
def cleanup_games(u1: str, u2: str) -> Iterator[None]:
    """Teardown-only fixture: after a replay test completes (pass or
    fail), delete the games and zombie markers it created, so that no
    test data accumulates in the database"""
    yield
    with Client.get_context():
        ZombieModel.delete_for_user(u1)
        ZombieModel.delete_for_user(u2)
        GameModel.delete_for_user(u1)
        GameModel.delete_for_user(u2)


@pytest.mark.usefixtures("cleanup_games")
@pytest.mark.parametrize(
    "fixture_file",
    FIXTURE_FILES,
    ids=[os.path.basename(p)[len("game_"):-len(".json")] for p in FIXTURE_FILES],
)
def test_replay(
    fixture_file: str,
    client1: CustomClient,
    client2: CustomClient,
    u1: str,
    u2: str,
) -> None:
    """Replay a sampled production game and verify that the engine
    behaves identically to the original"""
    with open(fixture_file, encoding="utf-8") as f:
        fixture: Fixture = json.load(f)
    game_id, clients = create_game(fixture, client1, client2, u1, u2)
    replay_game(fixture, game_id, clients)

