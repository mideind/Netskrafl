#!/usr/bin/env pypy
# -*- coding: utf-8 -*-

""" Skrafltester

    Author: Vilhjalmur Thorsteinsson, 2014

    This program implements a testing function for the
    functionality in skraflmechanics.py and skraflplayer.py

    Usage: python skrafltester.py
        [-n number_of_games_to_run (default 4)]
        [-o minimax|autoplayer (to choose opponent, default minimax)]
        [-s (to run silently, i.e. only with ending summary)]

"""

from __future__ import print_function

import getopt
import sys
import time

from languages import NewTileSet
from skraflmechanics import State, Board, Move, ExchangeMove, ChallengeMove, ResponseMove, Error
from skraflplayer import AutoPlayer, AutoPlayer_MiniMax


_PROFILING = False


def test_move(state, movestring):
    """ Test placing a simple tile move """
    coord, word = movestring.split(u' ')
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
        if c == u'?':
            next_is_blank = True
            continue
        if not state.board().is_covered(row, col):
            move.add_cover(row, col, u'?' if next_is_blank else c, c)
            next_is_blank = False
        row += xd
        col += yd
    legal = state.check_legality(move)
    msg = ""
    if isinstance(legal, tuple):
        legal, msg = legal
    if legal != Error.LEGAL:
        print(u"Play is not legal, code {0} {1}".format(Error.errortext(legal), msg))
        return False
    print(u"Play {0} is legal and scores {1} points".format(move, state.score(move)))
    state.apply_move(move)
    print(state.__str__())
    return True


def test_exchange(state, numtiles):
    """ Test exchange move """
    exch = state.player_rack().contents()[0:numtiles]
    move = ExchangeMove(exch)
    legal = state.check_legality(move)
    msg = ""
    if isinstance(legal, tuple):
        legal, msg = legal
    if legal != Error.LEGAL:
        print(u"Play is not legal, code {0} {1}".format(Error.errortext(legal), msg))
        return False
    print(u"Play {0} is legal and scores {1} points".format(move, state.score(move)))
    state.apply_move(move)
    print(state.__str__())
    return True


def test_challenge(state):
    """ Test challenge move """
    move = ChallengeMove()
    legal = state.check_legality(move)
    msg = ""
    if isinstance(legal, tuple):
        legal, msg = legal
    if legal != Error.LEGAL:
        print(u"Play is not legal, code {0} {1}".format(Error.errortext(legal), msg))
        return False
    print(u"Play {0} is legal and scores {1} points".format(move, state.score(move)))
    state.apply_move(move)
    print(state.__str__())
    return True


def test_response(state):
    """ Test response move """
    move = ResponseMove()
    legal = state.check_legality(move)
    msg = ""
    if isinstance(legal, tuple):
        legal, msg = legal
    if legal != Error.LEGAL:
        print(u"Play is not legal, code {0} {1}".format(Error.errortext(legal), msg))
        return False
    print(u"Play {0} is legal and scores {1} points".format(move, state.score(move)))
    state.apply_move(move)
    print(state.__str__())
    return True


def test_game(players, silent):
    """ Go through a whole game by pitting two AutoPlayers against each other """
    # The players parameter is a list of tuples: (playername, constructorfunc)
    # where constructorfunc accepts a State parameter and returns a freshly
    # created AutoPlayer (or subclass thereof) that will generate moves
    # on behalf of the player.

    # Initial, empty game state
    state = State(tileset = NewTileSet, drawtiles = True)

    print(u"After initial draw, bag contains {0} tiles".format(state.bag().num_tiles()))
    print(u"Bag contents are:\n{0}".format(state.bag().contents()))
    print(u"Rack 0 is {0}".format(state.rack(0)))
    print(u"Rack 1 is {0}".format(state.rack(1)))

    # Set player names
    for ix in range(2):
        state.set_player_name(ix, players[ix][0])

    if not silent:
        print(state.__str__()) # This works in Python 2 and 3

    # Generate a sequence of moves, switching player sides automatically

    t0 = time.time()

    while not state.is_game_over():

        # Call the appropriate player creation function
        apl = players[state.player_to_move()][1](state)

        g0 = time.time()
        move = apl.generate_move()
        g1 = time.time()

        legal = state.check_legality(move)
        if legal != Error.LEGAL:
            # Oops: the autoplayer generated an illegal move
            print(u"Play is not legal, code {0}".format(Error.errortext(legal)))
            return

        if not silent:
            print(u"Play {0} scores {1} points ({2:.2f} seconds)".format(move, state.score(move), g1 - g0))

        # Apply the move to the state and switch players
        state.apply_move(move)

        if not silent:
            print(state.__str__())

    # Tally the tiles left and calculate the final score
    state.finalize_score()
    p0, p1 = state.scores()
    t1 = time.time()

    if not silent:
        print(u"Game over, final score {4} {0} : {5} {1} after {2} moves ({3:.2f} seconds)".format(p0, p1,
            state.num_moves(), t1 - t0, state.player_name(0), state.player_name(1)))

    return state.scores()


def test_manual_game():
    """ Manual game test """

    # Initial, empty game state
    state = State(tileset = NewTileSet, manual_wordcheck = True, drawtiles = True)

    print(u"Manual game")
    print(u"After initial draw, bag contains {0} tiles".format(state.bag().num_tiles()))
    print(u"Bag contents are:\n{0}".format(state.bag().contents()))
    print(u"Rack 0 is {0}".format(state.rack(0)))
    print(u"Rack 1 is {0}".format(state.rack(1)))

    # Set player names
    for ix in range(2):
        state.set_player_name(ix, "Player " + ("A", "B")[ix])

    # print(state.__str__()) # This works in Python 2 and 3

    state.player_rack().set_tiles(u"stuðinn")
    test_move(state, u"H4 stuði")
    state.player_rack().set_tiles(u"dettsfj")
    test_move(state, u"5E detts")
    test_exchange(state, 3)
    state.player_rack().set_tiles(u"dýsturi")
    test_move(state, u"I3 dýs")
    state.player_rack().set_tiles(u"?xalmen")
    test_move(state, u"6E ?óx") # The question mark indicates a blank tile for the subsequent cover
    state.player_rack().set_tiles(u"eiðarps")

    test_move(state, u"9F eipar")
    test_challenge(state)
    test_response(state)

    state.player_rack().set_tiles(u"sóbetis")
    test_move(state, u"J3 ós")

    test_move(state, u"9F eiðar")
    test_challenge(state)
    test_response(state)

    # Tally the tiles left and calculate the final score
    state.finalize_score()
    p0, p1 = state.scores()

    print(u"Manual game over, final score {3} {0} : {4} {1} after {2} moves".format(p0, p1,
        state.num_moves(), state.player_name(0), state.player_name(1)))


def test(num_games, opponent, silent):

    def autoplayer_creator(state):
        return AutoPlayer(state)

    def minimax_creator(state):
        return AutoPlayer_MiniMax(state)

    players = [None, None]
    if opponent == u'minimax':
        players[0] = (u"AutoPlayer", autoplayer_creator)
        players[1] = (u"MiniMax", minimax_creator)
    else:
        players[0] = (u"AutoPlayer A", autoplayer_creator)
        players[1] = (u"AutoPlayer B", autoplayer_creator)

    gameswon = [0, 0]
    totalpoints = [0, 0]
    sumofmargin = [0, 0]

    t0 = time.time()

    # Run games
    for ix in range(num_games):
        if not silent:
            print(u"\nGame {0}/{1} starting".format(ix + 1, num_games))
        if ix % 2 == 1:
            # Odd game: swap players
            players[0], players[1] = players[1], players[0]
            p1, p0 = test_game(players, silent)
            # Swap back
            players[0], players[1] = players[1], players[0]
        else:
            # Even game
            p0, p1 = test_game(players, silent)
        if p0 > p1:
            gameswon[0] += 1
            sumofmargin[0] += (p0 - p1)
        elif p1 > p0:
            gameswon[1] += 1
            sumofmargin[1] += (p1 - p0)
        totalpoints[0] += p0
        totalpoints[1] += p1

    t1 = time.time()

    print(u"Test completed, {0} games played in {1:.2f} seconds, {2:.2f} seconds per game"
        .format(num_games,
            t1 - t0, (t1 - t0) / num_games)
    )

    def reportscore(player):
        if gameswon[player] == 0:
            print(u"{2} won {0} games and scored an average of {1:.1f} points per game"
                .format(gameswon[player],
                    float(totalpoints[player]) / num_games,
                    players[player][0])
            )
        else:
            print(u"{3} won {0} games with an average margin of {2:.1f} and scored an average of {1:.1f} points per game"
                .format(gameswon[player],
                    float(totalpoints[player]) / num_games,
                    float(sumofmargin[player]) / gameswon[player],
                    players[player][0])
            )

    reportscore(0)
    reportscore(1)


class Usage(Exception):

    def __init__(self, msg):
        self.msg = msg


def main(argv=None):
    """ Guido van Rossum's pattern for a Python main function """

    if argv is None:
        argv = sys.argv
    try:
        try:
            opts, _ = getopt.getopt(argv[1:], "hn:o:sm", ["help", "numgames", "opponent", "silent", "manual"])
        except getopt.error as msg:
             raise Usage(msg)
        num_games = 4
        opponent = "autoplayer"
        silent = False
        manual = False
        # process options
        for o, a in opts:
            if o in ("-h", "--help"):
                print(__doc__)
                sys.exit(0)
            elif o in ("-n", "--numgames"):
                num_games = int(a)
            elif o in ("-o", "--opponent"):
                opponent = str(a).lower()
            elif o in ("-s", "--silent"):
                silent = True
            elif o in ("-m", "--manual"):
                manual = True

        print(u"Welcome to the Skrafl game tester")

        if manual:
            test_manual_game()
        else:
            print(u"Running {0} games against {1}".format(num_games, opponent or u"autoplayer"))
            test(num_games, opponent, silent)

    except Usage as err:
        print(err.msg, file=sys.stderr)
        print("for help use --help", file=sys.stderr)
        return 2


def profile_main():

    """ Main function to invoke for profiling """

    import cProfile as profile
    import pstats

    global _PROFILING

    _PROFILING = True

    filename = 'skrafltester.profile'

    profile.run('main()', filename)

    stats = pstats.Stats(filename)

    # Clean up filenames for the report
    stats.strip_dirs()

    # Sort the statistics by the total time spent in the function itself
    stats.sort_stats('tottime')

    stats.print_stats(100) # Print 100 most significant lines


if __name__ == "__main__":
    sys.exit(main())
    #sys.exit(profile_main())

