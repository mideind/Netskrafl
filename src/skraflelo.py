"""

    Server module for computing Elo points

    Copyright (C) 2022 Miðeind ehf.
    Author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This module implements compute_elo_points(), a function for
    (provisionally) updating the Elo points and other statistics
    for players after a game finishes. Note that a full and authoritative
    update of statistics happens in a cron job once per day, as
    implemented in skraflstats.py.

"""

from __future__ import annotations
from dataclasses import dataclass

from typing import Optional, Tuple

from skrafldb import GameModel
from skrafluser import User


@dataclass
class EloDict:
    """ A class that encapsulates the Elo scores of a player """

    elo: int
    human_elo: int
    manual_elo: int


# The K constant used in the Elo calculation
ELO_K: float = 20.0  # For established players
BEGINNER_K: float = 32.0  # For beginning players

# How many games a player plays as a provisional player
# before becoming an established one
ESTABLISHED_MARK: int = 10


def compute_elo(
    o_elo: Tuple[int, int], sc0: int, sc1: int, est0: int, est1: int
) -> Tuple[int, int]:
    """ Computes the Elo points of the two users after their game """
    # If no points scored, this is a null game having no effect
    assert sc0 >= 0
    assert sc1 >= 0
    if sc0 + sc1 == 0:
        return (0, 0)

    # Current Elo ratings
    elo0 = o_elo[0]
    elo1 = o_elo[1]

    # Calculate the quotients for each player using a logistic function.
    # For instance, a player with 1_200 Elo points would get a Q of 10^3 = 1_000,
    # a player with 800 Elo points would get Q = 10^2 = 100
    # and a player with 1_600 Elo points would get Q = 10^4 = 10_000.
    # This means that the 1_600 point player would have a 99% expected probability
    # of winning a game against the 800 point one, and a 91% expected probability
    # of winning a game against the 1_200 point player.
    q0 = 10.0 ** (float(elo0) / 400)
    q1 = 10.0 ** (float(elo1) / 400)
    if q0 + q1 < 1.0:
        # Strange corner case: give up
        return (0, 0)

    # Calculate the expected winning probability of each player
    exp0 = q0 / (q0 + q1)
    exp1 = q1 / (q0 + q1)

    # Represent the actual outcome
    if sc0 > sc1:
        # Player 0 won
        act0 = 1.0
        act1 = 0.0
    elif sc1 > sc0:
        # Player 1 won
        act1 = 1.0
        act0 = 0.0
    else:
        # Draw
        act0 = 0.5
        act1 = 0.5

    # Calculate the adjustments to be made (one positive, one negative)
    adj0 = (act0 - exp0) * (ELO_K if est0 else BEGINNER_K)
    adj1 = (act1 - exp1) * (ELO_K if est1 else BEGINNER_K)

    # Calculate the final adjustment tuple
    adj0, adj1 = int(round(adj0)), int(round(adj1))

    # Make sure we don't adjust to a negative number
    if adj0 + elo0 < 0:
        adj0 = -elo0
    if adj1 + elo1 < 0:
        adj1 = -elo1

    return (adj0, adj1)


def compute_elo_for_game(gm: GameModel, u0: Optional[User], u1: Optional[User]) -> None:
    """Compute new Elo points (and evenutally other statistics)
    when a game is over. We calculate provisional points
    for human games only here; the full and authoritative calculation
    happens in a cron job once per day."""
    if not gm.over:
        # The game is not over: something weird going on
        return

    s0 = gm.score0
    s1 = gm.score1

    if (s0 == 0) and (s1 == 0):
        # When a game ends by resigning immediately,
        # make sure that the weaker player
        # doesn't get Elo points for a draw; in fact,
        # ignore such a game altogether in the statistics
        return

    # Number of games played; are the players established players?
    est0, est1 = True, True
    if u0 is not None:
        u0.increment_games()
        est0 = u0.num_games() > ESTABLISHED_MARK
    if u1 is not None:
        u1.increment_games()
        est1 = u1.num_games() > ESTABLISHED_MARK

    if u0 is None or u1 is None:
        # Robot game: we're done
        return

    # Manual (Pro Mode) game?
    manual_game = gm.manual_wordcheck()

    urec0 = EloDict(elo=u0.elo(), human_elo=u0.human_elo(), manual_elo=u0.manual_elo())
    urec1 = EloDict(elo=u1.elo(), human_elo=u1.human_elo(), manual_elo=u1.manual_elo())

    # Save the Elo point state used in the calculation
    uelo0 = urec0.elo or User.DEFAULT_ELO
    uelo1 = urec1.elo or User.DEFAULT_ELO
    gm.elo0, gm.elo1 = uelo0, uelo1

    # Compute the Elo points of both players
    adj = compute_elo((uelo0, uelo1), s0, s1, est0, est1)

    # When an established player is playing a beginning (provisional) player,
    # leave the Elo score of the established player unchanged
    # Adjust player 0
    if est0 and not est1:
        adj = (0, adj[1])
    gm.elo0_adj = adj[0]
    urec0.elo = uelo0 + adj[0]
    # Adjust player 1
    if est1 and not est0:
        adj = (adj[0], 0)
    gm.elo1_adj = adj[1]
    urec1.elo = uelo1 + adj[1]

    # Compute the human-only Elo
    uelo0 = urec0.human_elo or User.DEFAULT_ELO
    uelo1 = urec1.human_elo or User.DEFAULT_ELO
    gm.human_elo0, gm.human_elo1 = uelo0, uelo1

    adj = compute_elo((uelo0, uelo1), s0, s1, est0, est1)

    # Adjust player 0
    if est0 and not est1:
        adj = (0, adj[1])
    gm.human_elo0_adj = adj[0]
    urec0.human_elo = uelo0 + adj[0]
    # Adjust player 1
    if est1 and not est0:
        adj = (adj[0], 0)
    gm.human_elo1_adj = adj[1]
    urec1.human_elo = uelo1 + adj[1]

    # If manual game, compute the manual-only Elo
    if manual_game:
        uelo0 = urec0.manual_elo or User.DEFAULT_ELO
        uelo1 = urec1.manual_elo or User.DEFAULT_ELO
        gm.manual_elo0, gm.manual_elo1 = uelo0, uelo1
        adj = compute_elo((uelo0, uelo1), s0, s1, est0, est1)
        # Adjust player 0
        if est0 and not est1:
            adj = (0, adj[1])
        gm.manual_elo0_adj = adj[0]
        urec0.manual_elo = uelo0 + adj[0]
        # Adjust player 1
        if est1 and not est0:
            adj = (adj[0], 0)
        gm.manual_elo1_adj = adj[1]
        urec1.manual_elo = uelo1 + adj[1]

    # Update the user records
    # This is a provisional update, to be confirmed during
    # the authoritative calculation performed by a cron job
    if u0 is not None:
        u0.set_elo(urec0.elo, urec0.human_elo, urec0.manual_elo)
    if u1 is not None:
        u1.set_elo(urec1.elo, urec1.human_elo, urec1.manual_elo)
