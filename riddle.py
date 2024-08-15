"""

    Riddle generator for Netskrafl (Icelandic Scrabble)

    Copyright (C) 2024 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The GNU General Public License, version 3, applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    Note: SCRABBLE is a registered trademark. This software or its author
    are in no way affiliated with or endorsed by the owners or licensees
    of the SCRABBLE trademark.

"""

from __future__ import annotations

from random import randint
from typing import Iterable, Iterator, List, Optional, Tuple, TypedDict, cast
import json
import itertools

from datetime import datetime, UTC

from languages import Alphabet
from skrafldb import ndb, GameModel
from skraflgame import Game
from skraflmechanics import Move
from skraflplayer import AutoPlayer


TileTuple = Tuple[str, str, str, int]  # coord, letter, score

class Riddle(TypedDict):
    uuid: str
    timestamp: str
    tiles: List[TileTuple]
    rack: List[str]
    bestmove: List[Tuple[int, int, str]]  # row, col, letter
    word: str
    score: int


class RiddleResponse(TypedDict):
    riddles: List[Riddle]
    end_time: str  # ISO format timestamp


def fetch_games(start_time: datetime) -> Iterator[GameModel]:
    """Fetch games that are over and ended strictly after the given time stamp"""
    q = cast(
        ndb.Query,
        GameModel
            .query(GameModel.over == True)
            .filter(GameModel.ts_last_move > start_time)
            .order(GameModel.ts_last_move),
    )
    yield from q.iter()


def filter_games(it: Iterable[GameModel]) -> Iterator[GameModel]:
    """Filter out games that are not suitable for riddle generation"""
    for gm in it:
        # Filter out Pro Mode ('manual') games and games against the strongest robot
        if gm.prefs.get("manual", False) or gm.robot_level == 0:
            continue
        # Filter out games that are not in the Icelandic locale
        if gm.prefs.get("locale", "is_IS") != "is_IS":
            continue
        yield gm


def generate_riddle(gm: GameModel, min_score: int) -> Optional[Riddle]:
    """Generate a riddle from a GameModel instance"""
    uuid = cast(str, gm.key.id())
    game = Game.load(uuid)
    if game is None:
        return None
    # Find a random move number in the range (11, 17) inclusive
    move_number = randint(11, 17)
    if len(game.moves) <= move_number:
        return None
    state = game.state_after_move(move_number)
    if state.is_game_over():
        # At this point, the game was over
        return None
    # Find the rack of the player who is to move
    rack = state.rack_details(1 - game.moves[move_number-1].player)
    rack_letters = [t[0] for t in rack if t[0] != "?"]
    if len(rack_letters) < 7:
        # Skip games where the rack is not full or contains a blank tile
        return None
    # Find the best possible move for the player
    apl = AutoPlayer.create(state, robot_level = 0)
    best_moves = apl.generate_best_moves(1)
    if not best_moves:
        return None
    best_move, score = best_moves[0]
    if not isinstance(best_move, Move):
        # The best move is not a tile move
        return None
    if min_score > 0 and score < min_score:
        # Skip games where the best move is not good enough
        return None
    # Accumulate the tiles that are already on the board
    tiles = list(game.enum_tiles(state))
    # Assemble the best move (note that it never contains a blank tile)
    bm = [(m.row, m.col, m.letter) for m in best_move.covers()]
    # Return the completed riddle
    return Riddle(
        uuid=uuid,
        timestamp=Alphabet.format_timestamp(game.ts_last_move or datetime.now(UTC)),
        tiles=tiles,
        rack=rack_letters,
        bestmove=bm,
        word=best_move.word(),
        score=score,
    )


def generate_riddles(start_time: datetime, min_score: int) -> Iterator[Riddle]:
    """Generate a list of riddles and return them as JSON """
    games = fetch_games(start_time)
    games = filter_games(games)
    for gm in games:
        if (r := generate_riddle(gm, min_score)) is not None:
            yield r


def riddles(start_time: datetime, limit: int, *, min_score: int = 0) -> RiddleResponse:
    """Generate a list of riddles and return them as JSON """
    # Take up to 'limit' riddles from the generator, but no more
    riddles = list(itertools.islice(generate_riddles(start_time, min_score), limit))
    # Calculate the time stamp of the last riddle returned
    end_time: str = datetime.now(UTC).isoformat() if not riddles else riddles[-1]["timestamp"]
    return RiddleResponse(riddles=riddles, end_time=end_time)


# Create a main function for testing purposes
def main() -> None:
    # Establish an ndb Context
    ndb_client = ndb.Client()
    with ndb_client.context():
        # Note: the start_time must be a naive datetime object
        # (i.e. not timezone-aware)
        start_time = datetime(2022, 1, 1, 0, 0, 0, 0)
        limit = 8
        rr = riddles(start_time, limit, min_score=40)
        # Print the riddle response as JSON
        with open("riddles.json", "w", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    rr,
                    indent=2,
                    ensure_ascii=False
                )
            )


# Call the main function if this is invoked as a script
if __name__ == "__main__":
    main()

