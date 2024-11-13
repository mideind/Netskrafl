"""

    Server module for computing Elo points

    Copyright © 2024 Miðeind ehf.
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

from typing import Optional, Tuple, Union

import logging

from config import DEFAULT_LOCALE, ESTABLISHED_MARK, DEFAULT_ELO
from skrafldb import EloModel, GameModel, EloDict, RobotModel
from skrafluser import User


# The K constant used in the Elo calculation
ELO_K: float = 20.0  # For established players
BEGINNER_K: float = 32.0  # For beginning players


def compute_elo(
    o_elo: Tuple[int, int], sc0: int, sc1: int, est0: int, est1: int
) -> Tuple[int, int]:
    """Computes the Elo points of the two users after their game"""
    # If no points scored, this is a null game having no effect
    assert sc0 >= 0
    assert sc1 >= 0
    if sc0 + sc1 == 0:
        return (0, 0)

    # Current Elo ratings
    elo0, elo1 = o_elo

    # Calculate the quotients for each player using a logistic function.
    # For instance, a player with 1_200 Elo points would get a Q of 10^3 = 1_000,
    # a player with 800 Elo points would get Q = 10^2 = 100
    # and a player with 1_600 Elo points would get Q = 10^4 = 10_000.
    # This means that the 1_600 point player would have a 99% expected probability
    # of winning a game against the 800 point one, and a 91% expected probability
    # of winning a game against the 1_200 point player.
    q0: float = 10.0 ** (float(elo0) / 400.0)
    q1: float = 10.0 ** (float(elo1) / 400.0)
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


def compute_elo_for_game(
    gm: GameModel,
    u0: Optional[User],
    u1: Optional[User],
) -> None:
    """Compute new Elo points (and evenutally other statistics)
    when a game is over. We calculate provisional points
    for human games only here; the full and authoritative calculation
    happens in a cron job once per day."""
    if not gm.over:
        # The game is not over: something weird going on
        return

    if u0 is None or u1 is None:
        # Robot game: nothing to do
        return

    s0 = gm.score0
    s1 = gm.score1

    if (s0 == 0) and (s1 == 0):
        # When a game ends by resigning immediately,
        # make sure that the weaker player
        # doesn't get Elo points for a draw; in fact,
        # ignore such a game altogether in the statistics
        return

    # Number of human games played; are the players established players?
    est0 = u0.num_human_games() > ESTABLISHED_MARK
    est1 = u1.num_human_games() > ESTABLISHED_MARK

    # Manual (Pro Mode) game?
    manual_game = gm.manual_wordcheck()

    urec0 = u0.elo_dict()
    urec1 = u1.elo_dict()

    # Save the Elo point state used in the calculation
    uelo0 = urec0.elo or DEFAULT_ELO
    uelo1 = urec1.elo or DEFAULT_ELO
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
    uelo0 = urec0.human_elo or DEFAULT_ELO
    uelo1 = urec1.human_elo or DEFAULT_ELO
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
        uelo0 = urec0.manual_elo or DEFAULT_ELO
        uelo1 = urec1.manual_elo or DEFAULT_ELO
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

    # Update the user records ('old-style' Elo ratings)
    # This is a provisional update, to be confirmed during
    # the authoritative calculation performed by a cron job
    u0.set_elo(urec0)
    u1.set_elo(urec1)


def compute_locale_elo_for_game(
    gm: GameModel,
    u0: Optional[User],
    u1: Optional[User],
    # The following parameters contain the Elo ratings of the
    # players as they were before the current game
    orig0: EloDict,
    orig1: EloDict,
) -> None:
    """Compute new Elo points when a game is over, for the
    particular locale in which it was played."""
    if not gm.over:
        # The game is not over: something weird is going on
        logging.warning(f"compute_locale_elo_for_game: game {gm.key.id()} is not over")
        return
    if u0 is None and u1 is None:
        # No users: something weird is going on
        logging.warning(f"compute_locale_elo_for_game: game {gm.key.id()} has no users")
        return

    s0 = gm.score0
    s1 = gm.score1

    # If no_adjust is True, we apply a zero Elo adjustment
    # as a result of this game, but it is still recorded in the
    # GameModel entity, and the EloModel timestamps are updated.
    no_adjust = False

    if (s0 == 0) and (s1 == 0):
        # A game that never properly starts doesn't count in Elo calculations
        no_adjust = True
    elif len(gm.moves) >= 1 and gm.moves[0].is_resignation():
        # A game that ends by immediate resignation
        # doesn't count in Elo calculations
        no_adjust = True
    elif len(gm.moves) >= 2 and gm.moves[1].is_resignation():
        # A game that ends by immediate resignation after the first move
        # doesn't count in Elo calculations
        no_adjust = True

    locale = gm.locale or DEFAULT_LOCALE
    robot_game = (u0 is None) or (u1 is None)
    robot_level = gm.robot_level if robot_game else 0
    em0: Union[None, EloModel, RobotModel] = None
    em1: Union[None, EloModel, RobotModel] = None

    # Number of human games played; are the players established players?
    # For this purpose, robots are always "established".
    # We look at all games played, not just in the current locale.
    est0 = u0.num_human_games() > ESTABLISHED_MARK if u0 else True
    est1 = u1.num_human_games() > ESTABLISHED_MARK if u1 else True

    # Manual (Pro Mode) game?
    manual_game = False if robot_game else gm.manual_wordcheck()

    # Fetch the EloModel entities to modify, if they already exist
    if u0 is None:
        # Robot player
        uid0 = ""
        em0 = RobotModel.robot_elo(locale, robot_level)
    else:
        # Human player
        uid0 = u0.id() or ""
        if not uid0:
            # Something is wrong
            no_adjust = True
        em0 = EloModel.user_elo(locale, uid0)
    if u1 is None:
        # Robot player
        uid1 = ""
        em1 = RobotModel.robot_elo(locale, robot_level)
    else:
        # Human player
        uid1 = u1.id() or ""
        if not uid1:
            # Something is wrong
            no_adjust = True
        em1 = EloModel.user_elo(locale, uid1)

    # Obtain the current Elo status of the players (users or robots)
    if em0 is None:
        # There was no EloModel or RobotModel entity for player 0
        if u0 is not None and u0.locale == locale:
            # Obtain Elo ratings from the user entity, via the 'old' mechanism
            uelo0 = orig0.elo
            u0_human = orig0.human_elo
            u0_manual = orig0.manual_elo
        else:
            # TODO: Is there a way to obtain the 'old-style' Elo rating of a robot?
            uelo0, u0_human, u0_manual = DEFAULT_ELO, DEFAULT_ELO, DEFAULT_ELO
    elif u0 is None:
        # Robot
        assert isinstance(em0, RobotModel)
        # Robots never have 'human' or 'manual' Elo ratings
        uelo0, u0_human, u0_manual = em0.elo, DEFAULT_ELO, DEFAULT_ELO
    else:
        # Human player
        assert isinstance(em0, EloModel)
        uelo0, u0_human, u0_manual = em0.elo, em0.human_elo, em0.manual_elo
    if em1 is None:
        if u1 is not None and u1.locale == locale:
            # Obtain Elo ratings from the user entity, via the 'old' mechanism
            uelo1 = orig1.elo
            u1_human = orig1.human_elo
            u1_manual = orig1.manual_elo
        else:
            # TODO: Is there a way to obtain the 'old-style' Elo rating of a robot?
            uelo1, u1_human, u1_manual = DEFAULT_ELO, DEFAULT_ELO, DEFAULT_ELO
    elif u1 is None:
        # Robot
        assert isinstance(em1, RobotModel)
        # Robots never have 'human' or 'manual' Elo ratings
        uelo1, u1_human, u1_manual = em1.elo, DEFAULT_ELO, DEFAULT_ELO
    else:
        # Human player
        assert isinstance(em1, EloModel)
        uelo1, u1_human, u1_manual = em1.elo, em1.human_elo, em1.manual_elo

    # Collect the current Elo status into EloDict objects
    urec0 = EloDict(elo=uelo0, human_elo=u0_human, manual_elo=u0_manual)
    urec1 = EloDict(elo=uelo1, human_elo=u1_human, manual_elo=u1_manual)

    # Save the Elo point state used in the calculation
    gm.elo0, gm.elo1 = uelo0, uelo1

    # Compute the Elo points of both players
    if no_adjust:
        # ...or not
        adj = (0, 0)
    else:
        adj = compute_elo((uelo0, uelo1), s0, s1, est0, est1)
        # logging.info(f"compute_locale_elo_for_game: {locale} {s0=} {s1=} {uelo0=} {uelo1=} {adj=}")

    # When an established player is playing a beginning (provisional) player,
    # leave the Elo score of the established player unchanged.
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

    if not robot_game:
        # Compute the Elo rating for human games only
        uelo0 = urec0.human_elo
        uelo1 = urec1.human_elo
        gm.human_elo0, gm.human_elo1 = uelo0, uelo1
        if no_adjust:
            adj = (0, 0)
        else:
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

        # If manual game (always between humans), compute the manual-only Elo
        if manual_game:
            uelo0 = urec0.manual_elo
            uelo1 = urec1.manual_elo
            gm.manual_elo0, gm.manual_elo1 = uelo0, uelo1
            if no_adjust:
                adj = (0, 0)
            else:
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

    # Upsert the EloModel/RobotModel entities
    if uid0:
        assert em0 is None or isinstance(em0, EloModel)
        EloModel.upsert(
            em0,
            locale,
            uid0,
            urec0,
        )
    else:
        assert em0 is None or isinstance(em0, RobotModel)
        RobotModel.upsert(
            em0,
            locale,
            robot_level,
            urec0.elo,
        )
    if uid1:
        assert em1 is None or isinstance(em1, EloModel)
        EloModel.upsert(
            em1,
            locale,
            uid1,
            urec1,
        )
    else:
        assert em1 is None or isinstance(em1, RobotModel)
        RobotModel.upsert(
            em1,
            locale,
            robot_level,
            urec1.elo,
        )
