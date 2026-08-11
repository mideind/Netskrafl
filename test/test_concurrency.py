"""

    Concurrency tests for Netskrafl / Explo Word Game
    Copyright © 2026 Miðeind ehf.

    This module tests the server's handling of concurrent, conflicting
    /submitmove requests for the *same* game: duplicate submissions of
    the same move (client retries), two different moves racing under
    the same move count, and out-of-turn submissions racing the player
    to move. In every case, exactly one move may be applied; the loser
    must receive a clean error (OUT_OF_SYNC or WRONG_USER) and the
    stored game state must remain consistent.

    On the PostgreSQL backend, this exercises the for_update row
    locking in submit_move(); on NDB, the transactional decorator
    provides the equivalent protection.

    Each race is repeated a few times (with a fresh game each round)
    to increase the chance of genuinely overlapping execution.

"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional, Tuple

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from config import Error
from skrafldb import Client, GameModel, ZombieModel
from skraflgame import Game

from utils import (
    CustomClient,
    UserPair,
    create_worker_user_pair,
    flask_client,
    login_user,
)

# Number of times each race is run (fresh game each time)
ROUNDS = 3
# Watchdog for concurrent requests; exceeding it suggests a deadlock,
# e.g. between an in-process lock and a database row lock
TIMEOUT_SECONDS = 60.0


@pytest.fixture
def users() -> UserPair:
    """A pytest-xdist-safe pair of test users"""
    return create_worker_user_pair()


@pytest.fixture
def cleanup_games(users: UserPair) -> Iterator[None]:
    """Teardown-only fixture: delete the games and zombie markers
    created by a concurrency test"""
    yield
    with Client.get_context():
        for _, uid in users:
            ZombieModel.delete_for_user(uid)
            GameModel.delete_for_user(uid)


def new_game(users: UserPair) -> Tuple[str, Tuple[int, str], Tuple[int, str]]:
    """Create a fresh game between the two users. Returns the game id,
    plus (index, user_id) of the first mover and of the opponent."""
    (ix1, u1), (ix2, u2) = users
    c1, c2 = flask_client(), flask_client()
    resp = login_user(c1, ix1)
    assert resp.status_code == 200
    resp = login_user(c2, ix2)
    assert resp.status_code == 200
    resp = c1.post("/challenge", json=dict(action="issue", destuser=u2))
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json["result"] == Error.LEGAL
    resp = c2.post("/initgame", json=dict(opp=u1))
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json.get("ok"), f"initgame failed: {resp.json}"
    game_id: str = resp.json["uuid"]
    first_mover: str = resp.json["to_move"]
    if first_mover == u1:
        return game_id, (ix1, u1), (ix2, u2)
    assert first_mover == u2
    return game_id, (ix2, u2), (ix1, u1)


def logged_in_client(idx: int) -> CustomClient:
    """Return a fresh API client logged in as the given test user"""
    c = flask_client()
    resp = login_user(c, idx)
    assert resp.status_code == 200
    return c


def fire_concurrently(
    shots: List[Tuple[CustomClient, Dict[str, Any]]]
) -> List[Dict[str, Any]]:
    """POST all payloads to /submitmove at the same time, one thread
    per client, released simultaneously by a barrier. Returns the JSON
    responses, in the same order as the shots."""
    barrier = threading.Barrier(len(shots))

    def fire(client: CustomClient, payload: Dict[str, Any]) -> Dict[str, Any]:
        barrier.wait()
        resp = client.post("/submitmove", json=payload)
        assert resp.status_code == 200
        assert resp.json is not None
        return resp.json

    executor = ThreadPoolExecutor(max_workers=len(shots))
    try:
        futures = [executor.submit(fire, c, p) for c, p in shots]
        try:
            return [f.result(timeout=TIMEOUT_SECONDS) for f in futures]
        except TimeoutError:
            pytest.fail(
                f"Concurrent /submitmove did not complete within "
                f"{TIMEOUT_SECONDS} seconds - possible deadlock between "
                f"in-process locking and database row locking"
            )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def load_moves(game_id: str) -> Tuple[int, List[str]]:
    """Return the server-side move count and the move summaries"""
    with Client.get_context():
        g = Game.load(game_id, use_cache=False)
        assert g is not None
        assert g.state is not None
        return g.num_moves(), [m.move.summary(g.state)[1] for m in g.moves]


def assert_single_winner(
    results: List[Dict[str, Any]], game_id: str
) -> None:
    """Exactly one racing request must succeed; every other request
    must be cleanly rejected as out of sync or out of turn, and the
    game must contain exactly one registered move"""
    codes = [r.get("result") for r in results]
    winners = [c for c in codes if c == Error.LEGAL]
    losers = [c for c in codes if c != Error.LEGAL]
    assert len(winners) == 1, f"Expected exactly one winner, got {codes}"
    assert all(
        c in (Error.OUT_OF_SYNC, Error.WRONG_USER) for c in losers
    ), f"Unexpected loser result codes: {codes}"
    num_moves, _ = load_moves(game_id)
    assert num_moves == 1, (
        f"Expected exactly one registered move, found {num_moves}"
    )


@pytest.mark.usefixtures("cleanup_games")
def test_duplicate_submit_race(users: UserPair) -> None:
    """A client retry storm: the player to move submits the same move
    several times concurrently; it must be applied exactly once"""
    for _ in range(ROUNDS):
        game_id, (first_ix, _), _ = new_game(users)
        clients = [logged_in_client(first_ix) for _ in range(3)]
        payload = dict(uuid=game_id, moves=["pass"], mcount=0)
        results = fire_concurrently([(c, dict(payload)) for c in clients])
        assert_single_winner(results, game_id)


@pytest.mark.usefixtures("cleanup_games")
def test_out_of_turn_race(users: UserPair) -> None:
    """The player to move and the opponent submit simultaneously with
    the same move count; only the player to move may succeed"""
    for _ in range(ROUNDS):
        game_id, (first_ix, _), (second_ix, _) = new_game(users)
        c_first = logged_in_client(first_ix)
        c_second = logged_in_client(second_ix)
        payload = dict(uuid=game_id, moves=["pass"], mcount=0)
        results = fire_concurrently(
            [(c_first, dict(payload)), (c_second, dict(payload))]
        )
        # The first mover must win; the opponent must be rejected
        # (WRONG_USER if it arrived before the winning move was
        # committed, OUT_OF_SYNC if after)
        assert results[0].get("result") == Error.LEGAL, (
            f"Player to move was rejected: {results[0]}"
        )
        assert results[1].get("result") in (
            Error.WRONG_USER,
            Error.OUT_OF_SYNC,
        ), f"Opponent got unexpected result: {results[1]}"
        num_moves, _ = load_moves(game_id)
        assert num_moves == 1


@pytest.mark.usefixtures("cleanup_games")
def test_conflicting_moves_race(users: UserPair) -> None:
    """The player to move submits two *different* moves concurrently
    under the same move count (e.g. from two devices); exactly one of
    them may be applied, and the stored move must match the winner"""
    for _ in range(ROUNDS):
        game_id, (first_ix, _), _ = new_game(users)
        # Find a tile in the first mover's rack to construct an
        # exchange move that conflicts with a simultaneous pass
        with Client.get_context():
            g = Game.load(game_id, use_cache=False)
            assert g is not None
            assert g.state is not None
            tile = g.state.rack(g.player_to_move())[0]
            if tile == "?":
                tile = g.state.rack(g.player_to_move())[1]
        c_pass = logged_in_client(first_ix)
        c_exch = logged_in_client(first_ix)
        results = fire_concurrently(
            [
                (c_pass, dict(uuid=game_id, moves=["pass"], mcount=0)),
                (c_exch, dict(uuid=game_id, moves=[f"exch={tile}"], mcount=0)),
            ]
        )
        assert_single_winner(results, game_id)
        # The single stored move must be the one whose request won
        _, summaries = load_moves(game_id)
        winner_ix = next(
            ix for ix, r in enumerate(results)
            if r.get("result") == Error.LEGAL
        )
        expected = "PASS" if winner_ix == 0 else f"EXCH {tile}"
        assert summaries[0] == expected, (
            f"Stored move {summaries[0]!r} does not match the winning "
            f"request ({expected!r})"
        )


@pytest.mark.usefixtures("cleanup_games")
def test_row_lock_vs_class_lock(users: UserPair) -> None:
    """Force the interleaving where one thread holds the database row
    lock of a game (a for_update load with its transaction still open)
    while another thread starts a for_update load of the same game.
    The second load blocks on the row lock until the first thread's
    transaction commits; if it were to block while holding an
    in-process lock that the first thread's store() needs, the two
    threads would deadlock. On NDB, for_update is a no-op and the test
    passes trivially."""
    game_id, _, _ = new_game(users)
    a_loaded = threading.Event()
    done: Dict[str, bool] = {"a": False, "b": False}
    errors: List[str] = []

    def thread_a() -> None:
        try:
            with Client.get_context():
                g: Optional[Game] = Game.load(
                    game_id, use_cache=False, for_update=True
                )
                assert g is not None
                a_loaded.set()
                # Give thread B ample time to reach its for_update
                # fetch and block on our row lock
                time.sleep(1.5)
                # Pre-fix, this deadlocks: store() needs the class
                # lock, which thread B holds while it blocks on the
                # row lock that only our commit releases
                g.store(calc_elo_points=False)
            # Transaction commits on context exit, releasing the row lock
            done["a"] = True
        except Exception as e:
            errors.append(f"thread A: {e!r}")

    def thread_b() -> None:
        try:
            a_loaded.wait(timeout=TIMEOUT_SECONDS)
            time.sleep(0.3)  # Make sure A is inside its sleep
            with Client.get_context():
                g = Game.load(game_id, use_cache=False, for_update=True)
                assert g is not None
            done["b"] = True
        except Exception as e:
            errors.append(f"thread B: {e!r}")

    ta = threading.Thread(target=thread_a, daemon=True)
    tb = threading.Thread(target=thread_b, daemon=True)
    ta.start()
    tb.start()
    ta.join(timeout=15.0)
    tb.join(timeout=15.0)
    assert not errors, f"Thread errors: {errors}"
    assert done["a"] and done["b"], (
        f"Deadlock: completed={done} - a for_update load is blocking "
        f"on the game row lock while holding an in-process lock that "
        f"the row-lock holder needs in order to commit"
    )

