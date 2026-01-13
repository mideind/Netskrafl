#!/usr/bin/env python3
"""

    Skrafltester

    Copyright © 2025 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl


    This program implements a testing function for the
    functionality in skraflmechanics.py and skraflplayer.py

    Usage: python skrafltester.py
        [-n number_of_games_to_run (default 4)]
        [-o minimax|autoplayer|midlungur|amlodi (to choose opponent, default autoplayer)]
        [-s (to run silently, i.e. only with ending summary)]
        [-l locale (is_IS for Icelandic, en_US or en_GB for English, pl_PL for Polish)]

"""

from __future__ import annotations

from typing import List, NamedTuple, Optional, Tuple, Callable, cast

import getopt
import os
import sys
import time

base_path = os.path.dirname(__file__)  # Assumed to be in the /utils directory

# Add the ../src directory to the Python path
sys.path.append(os.path.join(base_path, "../src"))

from languages import (  # noqa: E402
    NewTileSet,
    set_locale,
    current_tileset,
    current_vocabulary,
    current_board_type,
)
from skraflmechanics import (  # noqa: E402
    State,
    Board,
    Move,
    ExchangeMove,
    ChallengeMove,
    ResponseMove,
    Error,
)
from skraflplayer import (  # noqa: E402
    AutoPlayer,
    AutoPlayer_Custom,
    AutoPlayer_MiniMax,
)
from autoplayers import autoplayer_create  # noqa: E402


PlayerTuple = Tuple[str, Callable[[State], AutoPlayer]]
PlayerList = List[PlayerTuple]


class GameResult(NamedTuple):
    """Represents the result of a single game"""

    scores: Tuple[int, int] = (0, 0)
    avg_word_move_score: float = 0.0
    avg_word_move_length: float = 0.0


_PROFILING = False


def test_move(state: State, movestring: str) -> bool:
    """Test placing a simple tile move"""
    coord, word = movestring.split(" ")
    rowid = Board.ROWIDS
    xd, yd = 0, 0
    horiz = True
    if coord[0] in rowid:
        row = rowid.index(coord[0])
        col = int(coord[1:]) - 1
        yd = 1
    else:
        row = rowid.index(coord[-1])
        col = int(coord[0:-1]) - 1
        xd = 1
        horiz = False
    move = Move(word, row, col, horiz)
    next_is_blank = False
    for c in word:
        if c == "?":
            next_is_blank = True
            continue
        if not state.board().is_covered(row, col):
            move.add_cover(row, col, "?" if next_is_blank else c, c)
            next_is_blank = False
        row += xd
        col += yd
    legal = state.check_legality(move, True)
    msg = ""
    if isinstance(legal, tuple):
        legal, msg = legal
    if legal != Error.LEGAL:
        print("Play is not legal, code {0} {1}".format(Error.errortext(legal), msg))
        return False
    print("Play {0} is legal and scores {1} points".format(move, state.score(move)))
    state.apply_move(move)
    print(state.__str__())
    return True


def test_exchange(state: State, numtiles: int) -> bool:
    """Test exchange move"""
    exch = state.player_rack().contents()[0:numtiles]
    move = ExchangeMove(exch)
    legal = state.check_legality(move, True)
    msg = ""
    if isinstance(legal, tuple):
        legal, msg = legal
    if legal != Error.LEGAL:
        print("Play is not legal, code {0} {1}".format(Error.errortext(legal), msg))
        return False
    print("Play {0} is legal and scores {1} points".format(move, state.score(move)))
    state.apply_move(move)
    print(state.__str__())
    return True


def test_challenge(state: State) -> bool:
    """Test challenge move"""
    move = ChallengeMove()
    legal = state.check_legality(move, True)
    msg = ""
    if isinstance(legal, tuple):
        legal, msg = legal
    if legal != Error.LEGAL:
        print("Play is not legal, code {0} {1}".format(Error.errortext(legal), msg))
        return False
    print("Play {0} is legal and scores {1} points".format(move, state.score(move)))
    state.apply_move(move)
    print(state.__str__())
    return True


def test_response(state: State) -> bool:
    """Test response move"""
    move = ResponseMove()
    legal = state.check_legality(move, True)
    msg = ""
    if isinstance(legal, tuple):
        legal, msg = legal
    if legal != Error.LEGAL:
        print("Play is not legal, code {0} {1}".format(Error.errortext(legal), msg))
        return False
    print("Play {0} is legal and scores {1} points".format(move, state.score(move)))
    state.apply_move(move)
    print(state.__str__())
    return True


def test_game(players: PlayerList, silent: bool) -> GameResult:
    """Go through a whole game by pitting two AutoPlayers against each other"""
    # The players parameter is a list of tuples: (playername, constructorfunc)
    # where constructorfunc accepts a State parameter and returns a freshly
    # created AutoPlayer (or subclass thereof) that will generate moves
    # on behalf of the player.

    # Initial, empty game state
    state = State(
        tileset=current_tileset(), drawtiles=True, board_type=current_board_type()
    )

    if not silent:
        print(
            "After initial draw, bag contains {0} tiles".format(state.bag().num_tiles())
        )
        print("Bag contents are:\n{0}".format(state.bag().contents()))
        print("Rack 0 is {0}".format(state.rack(0)))
        print("Rack 1 is {0}".format(state.rack(1)))

    # Set player names
    for ix in range(2):
        state.set_player_name(ix, players[ix][0])

    if not silent:
        print(state.__str__())  # This works in Python 2 and 3

    # Generate a sequence of moves, switching player sides automatically

    t0 = time.time()
    total_word_move_score = 0
    total_word_move_length = 0
    num_word_moves = 0

    while not state.is_game_over():

        # Call the appropriate player creation function
        apl = players[state.player_to_move()][1](state)

        g0 = time.time()
        move = apl.generate_move()
        g1 = time.time()

        legal = state.check_legality(move, True)
        if legal != Error.LEGAL:
            # Oops: the autoplayer generated an illegal move
            if isinstance(legal, tuple):
                legal = legal[0]
            print("Move is not legal, code {0}".format(Error.errortext(legal)))
            return GameResult()

        move_score = state.score(move)

        if isinstance(move, Move):
            # This is a word move: update the word move statistics
            num_word_moves += 1
            total_word_move_score += move_score
            total_word_move_length += move.num_covers()

        if not silent:
            print(
                "Move {0} scores {1} points ({2:.2f} seconds)".format(
                    move, move_score, g1 - g0
                )
            )

        # Apply the move to the state and switch players
        state.apply_move(move)

        if not silent:
            print(state.__str__())

    # Tally the tiles left and calculate the final score
    state.finalize_score()
    score0, score1 = state.scores()
    pname0, pname1 = state.player_name(0), state.player_name(1)
    t1 = time.time()

    if not silent:
        print(
            f"Game over, final score {pname0} {score0} : {pname1} {score1} "
            f"after {state.num_moves()} moves ({t1 - t0:.2f} seconds)"
        )

    avg_word_move_score = total_word_move_score / num_word_moves if num_word_moves else 0
    avg_word_move_length = total_word_move_length / num_word_moves if num_word_moves else 0
    return GameResult(
        scores=state.scores(),
        avg_word_move_score=avg_word_move_score,
        avg_word_move_length=avg_word_move_length,
    )


def test_manual_game() -> None:
    """Manual game test"""

    # Initial, empty game state
    state = State(
        tileset=NewTileSet, manual_wordcheck=True, drawtiles=True, board_type="standard"
    )

    print("Manual game")
    print("After initial draw, bag contains {0} tiles".format(state.bag().num_tiles()))
    print("Bag contents are:\n{0}".format(state.bag().contents()))
    print("Rack 0 is {0}".format(state.rack(0)))
    print("Rack 1 is {0}".format(state.rack(1)))

    # Set player names
    for ix in range(2):
        state.set_player_name(ix, "Player " + ("A", "B")[ix])

    # print(state.__str__()) # This works in Python 2 and 3

    state.player_rack().set_tiles("stuðinn")
    test_move(state, "H4 stuði")
    state.player_rack().set_tiles("dettsfj")
    test_move(state, "5E detts")
    test_exchange(state, 3)
    state.player_rack().set_tiles("dýsturi")
    test_move(state, "I3 dýs")
    state.player_rack().set_tiles("?xalmen")
    # The question mark indicates a blank tile for the subsequent cover
    test_move(state, "6E ?óx")
    state.player_rack().set_tiles("eiðarps")

    test_move(state, "9F eipar")
    test_challenge(state)
    test_response(state)

    state.player_rack().set_tiles("sóbetis")
    test_move(state, "J3 ós")

    test_move(state, "9F eiðar")
    test_challenge(state)
    test_response(state)

    # Tally the tiles left and calculate the final score
    state.finalize_score()
    p0, p1 = state.scores()

    print(
        "Manual game over, final score {3} {0} : {4} {1} after {2} moves".format(
            p0, p1, state.num_moves(), state.player_name(0), state.player_name(1)
        )
    )


def test(num_games: int, opponent: str, silent: bool) -> None:
    """Test running a number of games"""

    def autoplayer_creator(state: State) -> AutoPlayer:
        """Create a normal autoplayer instance"""
        return AutoPlayer(0, state)

    def common_creator(state: State) -> AutoPlayer:
        """Create a common autoplayer instance"""
        return AutoPlayer_Custom(15, state, pick_from=20)

    def medium_creator(state: State) -> AutoPlayer:
        """Create a medium autoplayer instance"""
        return AutoPlayer_Custom(8, state, pick_from=10)

    def minimax_creator(state: State) -> AutoPlayer:
        """Create a minimax autoplayer instance"""
        return AutoPlayer_MiniMax(0, state)

    players: PlayerList = cast(PlayerList, [None, None])
    opponent = opponent.lower()
    if opponent.startswith("robot-"):
        level = int(opponent[6:])

        def robot_creator(state: State) -> AutoPlayer:
            return autoplayer_create(state, level)

        players[0] = (f"Robot-{level}", robot_creator)
        players[1] = (f"Robot-{level}", robot_creator)
    elif opponent == "amlodi":
        players[0] = ("Amlóði A", common_creator)
        players[1] = ("Amlóði B", common_creator)
    elif opponent == "midlungur":
        players[0] = ("Miðlungur A", medium_creator)
        players[1] = ("Miðlungur B", medium_creator)
    elif opponent == "minimax":
        players[0] = ("AutoPlayer", autoplayer_creator)
        players[1] = ("MiniMax", minimax_creator)
    else:
        # Fullsterkur - always plays the top scoring move
        players[0] = ("AutoPlayer A", autoplayer_creator)
        players[1] = ("AutoPlayer B", autoplayer_creator)

    gameswon = [0, 0]
    totalpoints = [0, 0]
    sumofmargin = [0, 0]
    total_word_length = 0.0
    total_word_score = 0.0
    draws = 0

    t0 = time.time()

    # Run games
    for ix in range(num_games):
        if not silent:
            print("\nGame {0}/{1} starting".format(ix + 1, num_games))
        if ix % 2 == 1:
            # Odd game: swap players
            players[0], players[1] = players[1], players[0]
            gr = test_game(players, silent)
            p1, p0 = gr.scores
            # Swap back
            players[0], players[1] = players[1], players[0]
        else:
            # Even game
            gr = test_game(players, silent)
            p0, p1 = gr.scores
        if p0 > p1:
            gameswon[0] += 1
            sumofmargin[0] += p0 - p1
        elif p1 > p0:
            gameswon[1] += 1
            sumofmargin[1] += p1 - p0
        else:
            draws += 1
        totalpoints[0] += p0
        totalpoints[1] += p1
        # Accumulate the average word length and score
        total_word_length += gr.avg_word_move_length
        total_word_score += gr.avg_word_move_score

    t1 = time.time()

    print(
        "Test completed, {0} games played in {1:.2f} seconds, "
        "{2:.2f} seconds per game".format(num_games, t1 - t0, (t1 - t0) / num_games)
    )
    print(f"Average word move length: {total_word_length / num_games:.2f}")
    print(f"Average word move score: {total_word_score / num_games:.2f}")

    def reportscore(player: int) -> None:
        """Report the result of a number of games"""
        player_name = players[player][0]
        avg_points = float(totalpoints[player]) / num_games
        games_won = gameswon[player]
        if games_won == 0:
            print(
                f"{player_name} won {games_won} games and scored "
                f"an average of {avg_points:.1f} points per game"
            )
        else:
            avg_margin = float(sumofmargin[player]) / games_won
            print(
                f"{player_name} won {games_won} games with an "
                f"average margin of {avg_margin:.1f} and "
                f"scored an average of {avg_points:.1f} points per game"
            )

    if draws == 1:
        print("There was 1 draw")
    elif draws > 1:
        print(f"There were {draws} draws")

    reportscore(0)
    reportscore(1)


class Usage(Exception):
    """Error reporting exception for wrong command line arguments"""

    def __init__(self, msg: getopt.GetoptError) -> None:
        super().__init__(msg.msg)
        self.msg = msg


def main(argv: Optional[List[str]] = None) -> int:
    """Guido van Rossum's pattern for a Python main function"""

    if argv is None:
        argv = sys.argv
    try:
        try:
            opts, _ = getopt.getopt(
                argv[1:],
                "hl:n:o:sm",
                ["help", "locale", "numgames", "opponent", "silent", "manual"],
            )
        except getopt.error as msg:
            raise Usage(msg)
        num_games = 4
        opponent = "autoplayer"
        silent = False
        manual = False
        locale = "is_IS"
        # process options
        for o, a in opts:
            if o in ("-h", "--help"):
                print(__doc__)
                sys.exit(0)
            elif o in ("-l", "--locale"):
                locale = str(a)
            elif o in ("-n", "--numgames"):
                num_games = int(a)
            elif o in ("-o", "--opponent"):
                opponent = str(a).lower()
            elif o in ("-s", "--silent"):
                silent = True
            elif o in ("-m", "--manual"):
                manual = True

        print("Welcome to the Skrafl game tester")

        set_locale(locale)
        print(f"Using vocabulary {current_vocabulary()}")

        if manual:
            test_manual_game()
        else:
            print(
                "Running {0} games against {1}".format(
                    num_games, opponent or "autoplayer"
                )
            )
            test(num_games, opponent, silent)

    except Usage as err:
        print(err.msg, file=sys.stderr)
        print("for help use --help", file=sys.stderr)
        return 2

    # Normal exit with no error
    return 0


def profile_main() -> None:
    """Main function to invoke for profiling"""

    import profile
    import pstats

    global _PROFILING

    _PROFILING = True  # type: ignore

    filename = "skrafltester.profile"

    profile.run("main()", filename)

    stats = pstats.Stats(filename)

    # Clean up filenames for the report
    stats.strip_dirs()

    # Sort the statistics by the total time spent in the function itself
    stats.sort_stats("tottime")

    stats.print_stats(100)  # Print 100 most significant lines


if __name__ == "__main__":
    sys.exit(main())
    # sys.exit(profile_main())
