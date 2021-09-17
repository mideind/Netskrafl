"""

    Server module for Netskrafl statistics and other background tasks

    Copyright (C) 2021 Miðeind ehf.
    Author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This module implements two endpoints, /stats/run and /stats/ratings.
    The first one is normally called by the Google Cloud Scheduler at 02:00
    UTC each night, and the second one at 02:20 UTC. The endpoints cannot
    be invoked manually via HTTP except when running on a local development
    server.

    /stats/run looks at the games played during the preceding day (UTC time)
    and calculates Elo scores and high scores for each game and player.

    /stats/ratings creates the top 100 Elo scoreboard, for human-only
    games and for all games (including human-vs-robot).

"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple, Any, cast

import calendar
import logging
import time
import gc

from datetime import datetime, timedelta
from threading import Thread

from flask.wrappers import Request

from skrafldb import (
    ndb,
    Client,
    UserModel,
    GameModel,
    StatsModel,
    RatingModel,
    CompletionModel,
    iter_q,
    StatsDict,
)
from skrafluser import User
from skraflgame import Game


# The K constant used in the Elo calculation
ELO_K: float = 20.0  # For established players
BEGINNER_K: float = 32.0  # For beginning players

# How many games a player plays as a provisional player
# before becoming an established one
ESTABLISHED_MARK: int = 10


def monthdelta(date: datetime, delta: int) -> datetime:
    """ Calculate a date x months from now, in the past or in the future """
    m, y = (date.month + delta) % 12, date.year + (date.month + delta - 1) // 12
    if not m:
        m = 12
    d = min(date.day, calendar.monthrange(y, m)[1])
    return date.replace(day=d, month=m, year=y)


def _compute_elo(
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


def _write_stats(timestamp: datetime, urecs: Dict[str, StatsModel]) -> None:
    """ Writes the freshly calculated statistics records to the database """
    # Delete all previous stats with the same timestamp, if any
    StatsModel.delete_ts(timestamp=timestamp)
    um_list: List[UserModel] = []
    for sm in urecs.values():
        # Set the reference timestamp for the entire stats series
        sm.timestamp = timestamp
        # Fetch user information to update Elo statistics
        um = sm.fetch_user()
        if um:
            # Not robot
            um.elo = sm.elo
            um.human_elo = sm.human_elo
            um.manual_elo = sm.manual_elo
            um_list.append(um)
    # Update the statistics records
    StatsModel.put_multi(urecs.values())
    # Update the user records
    UserModel.put_multi(um_list)


def _run_stats(from_time: datetime, to_time: datetime) -> bool:
    """ Runs a process to update user statistics and Elo ratings """
    logging.info("Generating stats from {0} to {1}".format(from_time, to_time))

    if from_time is None or to_time is None:
        # Time range must be specified
        return False

    if from_time >= to_time:
        # Null time range
        return False

    # Collect any stray garbage before we start
    gc.collect()

    # Clear previous cache contents, if any
    StatsModel.clear_cache()

    # Iterate over all finished games within the time span in temporal order
    # pylint: disable=singleton-comparison
    q = (
        GameModel.query(
            ndb.AND(
                cast(datetime, GameModel.ts_last_move) > from_time,
                cast(datetime, GameModel.ts_last_move) <= to_time,
            )
        )
        .order(GameModel.ts_last_move)
        .filter(GameModel.over == True)
    )

    # The accumulated user statistics
    users: Dict[str, StatsModel] = dict()

    def _init_stat(user_id: Optional[str], robot_level: int) -> StatsModel:
        """ Returns the newest StatsModel instance available for the given user """
        return StatsModel.newest_before(from_time, user_id, robot_level)

    cnt = 0
    p0: Optional[str]
    p1: Optional[str]

    try:
        # Use i as a progress counter
        i = 0
        for gm in iter_q(q, chunk_size=250):
            i += 1

            s0 = gm.score0
            s1 = gm.score1

            if (s0 == 0) and (s1 == 0):
                # When a game ends by resigning immediately,
                # make sure that the weaker player
                # doesn't get Elo points for a draw; in fact,
                # ignore such a game altogether in the statistics
                continue

            # lm = Alphabet.format_timestamp(gm.ts_last_move or gm.timestamp)
            p0 = None if gm.player0 is None else gm.player0.id()
            p1 = None if gm.player1 is None else gm.player1.id()
            robot_game = (p0 is None) or (p1 is None)
            manual_game = False
            if robot_game:
                rl = gm.robot_level
            else:
                rl = 0
                manual_game = Game.manual_wordcheck_from_prefs(gm.prefs)

            if p0 is None:
                k0 = "robot-" + str(rl)
            else:
                k0 = p0
            if p1 is None:
                k1 = "robot-" + str(rl)
            else:
                k1 = p1

            if k0 in users:
                urec0 = users[k0]
            else:
                users[k0] = urec0 = _init_stat(p0, rl if p0 is None else 0)
            if k1 in users:
                urec1 = users[k1]
            else:
                users[k1] = urec1 = _init_stat(p1, rl if p1 is None else 0)

            # Number of games played
            urec0.games += 1
            urec1.games += 1
            if not robot_game:
                urec0.human_games += 1
                urec1.human_games += 1
                if manual_game:
                    urec0.manual_games += 1
                    urec1.manual_games += 1

            # Total scores
            urec0.score += s0
            urec1.score += s1
            urec0.score_against += s1
            urec1.score_against += s0
            if not robot_game:
                urec0.human_score += s0
                urec1.human_score += s1
                urec0.human_score_against += s1
                urec1.human_score_against += s0
                if manual_game:
                    urec0.manual_score += s0
                    urec1.manual_score += s1
                    urec0.manual_score_against += s1
                    urec1.manual_score_against += s0

            # Wins and losses
            if s0 > s1:
                urec0.wins += 1
                urec1.losses += 1
            elif s1 > s0:
                urec1.wins += 1
                urec0.losses += 1
            if not robot_game:
                if s0 > s1:
                    urec0.human_wins += 1
                    urec1.human_losses += 1
                elif s1 > s0:
                    urec1.human_wins += 1
                    urec0.human_losses += 1
                if manual_game:
                    if s0 > s1:
                        urec0.manual_wins += 1
                        urec1.manual_losses += 1
                    elif s1 > s0:
                        urec1.manual_wins += 1
                        urec0.manual_losses += 1

            # Find out whether players are established or beginners
            est0 = urec0.games > ESTABLISHED_MARK
            est1 = urec1.games > ESTABLISHED_MARK

            # Save the Elo point state used in the calculation
            gm.elo0, gm.elo1 = urec0.elo, urec1.elo

            # Compute the Elo points of both players
            adj = _compute_elo((urec0.elo, urec1.elo), s0, s1, est0, est1)

            # When an established player is playing a beginning (provisional) player,
            # leave the Elo score of the established player unchanged
            # Adjust player 0
            if est0 and not est1:
                adj = (0, adj[1])
            gm.elo0_adj = adj[0]
            urec0.elo += adj[0]
            # Adjust player 1
            if est1 and not est0:
                adj = (adj[0], 0)
            gm.elo1_adj = adj[1]
            urec1.elo += adj[1]
            # If not a robot game, compute the human-only Elo
            if not robot_game:
                uelo0 = urec0.human_elo or User.DEFAULT_ELO
                uelo1 = urec1.human_elo or User.DEFAULT_ELO
                gm.human_elo0, gm.human_elo1 = uelo0, uelo1
                adj = _compute_elo((uelo0, uelo1), s0, s1, est0, est1)
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
                    adj = _compute_elo((uelo0, uelo1), s0, s1, est0, est1)
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

            # Save the game object with the new Elo adjustment statistics
            gm.put()

            # Report on our progress
            cnt += 1
            if i % 500 == 0:
                logging.info("Stats processed {0} games".format(i))

    except Exception as ex:
        logging.error(
            "Exception in _run_stats(from={0}, to={1}) after {2} games and {3} users: {4!r}".format(
                from_time, to_time, cnt, len(users), ex
            )
        )
        return False

    # Completed without incident
    logging.info(
        "Normal completion of stats from {0} to {1}; {2} games and {3} users".format(
            from_time, to_time, cnt, len(users)
        )
    )
    _write_stats(to_time, users)
    return True


def _create_ratings() -> None:
    """ Create the Top 100 ratings tables """
    logging.info("Starting _create_ratings")

    _key = StatsModel.dict_key

    timestamp = datetime.utcnow()
    yesterday = timestamp - timedelta(days=1)
    week_ago = timestamp - timedelta(days=7)
    month_ago = monthdelta(timestamp, -1)

    # Collect any stray garbage before we start
    gc.collect()

    def _augment_table(
        t: Iterable[StatsDict],
        t_yesterday: Dict[str, StatsDict],
        t_week_ago: Dict[str, StatsDict],
        t_month_ago: Dict[str, StatsDict],
    ) -> None:
        """Go through a table of top scoring users and augment it
        with data from previous time points"""

        for sm in t:
            # Augment the rating with info about progress
            key = _key(sm)

            # pylint: disable=cell-var-from-loop
            def _augment(prop: str) -> None:
                asm = cast(Any, sm)  # Type checking hack
                asm[prop + "_yesterday"] = (
                    t_yesterday[key][prop] if key in t_yesterday else 0  # type: ignore
                )
                asm[prop + "_week_ago"] = (
                    t_week_ago[key][prop] if key in t_week_ago else 0  # type: ignore
                )
                asm[prop + "_month_ago"] = (
                    t_month_ago[key][prop] if key in t_month_ago else 0  # type: ignore
                )

            _augment("rank")
            _augment("games")
            _augment("elo")
            _augment("wins")
            _augment("losses")
            _augment("score")
            _augment("score_against")

    # All players including robot games

    top100_all = [sm for sm in StatsModel.list_elo(timestamp, 100)]
    top100_all_yesterday = {_key(sm): sm for sm in StatsModel.list_elo(yesterday, 100)}
    top100_all_week_ago = {_key(sm): sm for sm in StatsModel.list_elo(week_ago, 100)}
    top100_all_month_ago = {_key(sm): sm for sm in StatsModel.list_elo(month_ago, 100)}

    # Augment the table for all games
    _augment_table(
        top100_all, top100_all_yesterday, top100_all_week_ago, top100_all_month_ago
    )

    # Human only games

    top100_human = [sm for sm in StatsModel.list_human_elo(timestamp, 100)]
    top100_human_yesterday = {
        _key(sm): sm for sm in StatsModel.list_human_elo(yesterday, 100)
    }
    top100_human_week_ago = {
        _key(sm): sm for sm in StatsModel.list_human_elo(week_ago, 100)
    }
    top100_human_month_ago = {
        _key(sm): sm for sm in StatsModel.list_human_elo(month_ago, 100)
    }

    # Augment the table for human only games
    _augment_table(
        top100_human,
        top100_human_yesterday,
        top100_human_week_ago,
        top100_human_month_ago,
    )

    # Manual (and human only) games

    top100_manual = [sm for sm in StatsModel.list_manual_elo(timestamp, 100)]
    top100_manual_yesterday = {
        _key(sm): sm for sm in StatsModel.list_manual_elo(yesterday, 100)
    }
    top100_manual_week_ago = {
        _key(sm): sm for sm in StatsModel.list_manual_elo(week_ago, 100)
    }
    top100_manual_month_ago = {
        _key(sm): sm for sm in StatsModel.list_manual_elo(month_ago, 100)
    }

    # Augment the table for manual only games
    _augment_table(
        top100_manual,
        top100_manual_yesterday,
        top100_manual_week_ago,
        top100_manual_month_ago,
    )

    logging.info("Deleting top 100 tables")
    # FIXME: Note that the following call can be deleted after
    # it has been run once and the indexes have thereby been cleaned up in ndb
    RatingModel.delete_all()
    logging.info("Writing top 100 tables to the database")
    t0 = time.time()

    # Write the Top 100 tables to the database
    rlist: List[RatingModel] = []

    for rank in range(0, 100):

        # All players including robots
        rm = RatingModel.get_or_create("all", rank + 1)
        if rank < len(top100_all):
            rm.assign(top100_all[rank])
        else:
            # Sentinel empty records
            rm.user = None
            rm.robot_level = -1
            rm.games = -1
        rlist.append(rm)

        # Humans only
        rm = RatingModel.get_or_create("human", rank + 1)
        if rank < len(top100_human):
            rm.assign(top100_human[rank])
        else:
            # Sentinel empty records
            rm.user = None
            rm.robot_level = -1
            rm.games = -1
        rlist.append(rm)

        # Manual (and human) only
        rm = RatingModel.get_or_create("manual", rank + 1)
        if rank < len(top100_manual):
            rm.assign(top100_manual[rank])
        else:
            # Sentinel empty records
            rm.user = None
            rm.robot_level = -1
            rm.games = -1
        rlist.append(rm)

    # Put the entire top 100 table in one RPC call
    RatingModel.put_multi(rlist)

    t1 = time.time()
    logging.info("Finishing _create_ratings in {0:.1f} seconds".format(t1 - t0))


def deferred_stats(from_time: datetime, to_time: datetime, wait: bool) -> bool:
    """ This is the deferred stats collection process """

    def _deferred_stats() -> bool:
        success = False
        t0 = time.time()
        error = "Gave up after two retries"
        try:
            # Try up to two times to execute _run_stats()
            attempts = 0
            while attempts < 2:
                if _run_stats(from_time, to_time):
                    # Success: we're done
                    success = True
                    break
                attempts += 1
                logging.warning("Retrying _run_stats()")

        except Exception as ex:
            logging.error("Exception in deferred_stats: {0!r}".format(ex))
            success = False
            error = str(ex)

        t1 = time.time()
        if success:
            logging.info(
                "Stats calculation successfully finished in {0:.2f} seconds".format(
                    t1 - t0
                )
            )
            CompletionModel.add_completion("stats", from_time, to_time)
        else:
            logging.error(
                "Stats calculation did not complete, after running for {0:.2f} seconds".format(
                    t1 - t0
                )
            )
            CompletionModel.add_failure("stats", from_time, to_time, error)
        return success

    if wait:
        # Synchronous
        return _deferred_stats()

    # Asynchronous: we need a new context for this thread
    with Client.get_context():
        return _deferred_stats()


def deferred_ratings(wait: bool) -> bool:
    """ This is the deferred ratings table calculation process """

    def _deferred_ratings() -> bool:

        t0 = time.time()

        try:
            _create_ratings()
        except Exception as ex:
            logging.error("Exception in deferred_ratings: {0!r}".format(ex))
            now = datetime.utcnow()
            CompletionModel.add_failure("ratings", now, now, str(ex))
            return False

        t1 = time.time()

        StatsModel.log_cache_stats()
        # Do not maintain the cache in memory between runs
        StatsModel.clear_cache()

        logging.info("Ratings calculation finished in {0:.2f} seconds".format(t1 - t0))
        now = datetime.utcnow()
        CompletionModel.add_completion("ratings", now, now)

        return True

    if wait:
        # Synchronous: we don't need a client context
        return _deferred_ratings()

    # Asynchronous: this thread needs a fresh client context
    with Client.get_context():
        return _deferred_ratings()


def run(request: Request, *, wait: bool) -> Tuple[str, int]:
    """ Calculate a new set of statistics """
    logging.info("Starting stats calculation")

    # If invoked without parameters (such as from a cron job),
    # this will calculate yesterday's statistics.
    # If invoked with a year=YYYY&month=MM&day=DD parameter,
    # the parameter is the starting date (from_time) for the calculation.
    now = datetime.utcnow()
    yesterday = now - timedelta(days=1)

    year = int(request.args.get("year", str(yesterday.year)))
    month = int(request.args.get("month", str(yesterday.month)))
    day = int(request.args.get("day", str(yesterday.day)))

    from_time = datetime(year=year, month=month, day=day)
    to_time = from_time + timedelta(days=1)

    kwargs: Dict[str, Any] = dict(from_time=from_time, to_time=to_time, wait=wait)

    if not wait:
        # Asynchronous execution
        Thread(target=deferred_stats, kwargs=kwargs).start()
        # All is well so far and the calculation has been started
        # on a separate thread
        return "Stats calculation has been started", 200

    # Synchronous execution
    success = deferred_stats(**kwargs)
    if not success:
        return "Stats calculation failed", 500

    return "Stats calculation has been completed", 200


def ratings(request: Request, *, wait: bool) -> Tuple[str, int]:
    """ Calculate new ratings tables """
    logging.info("Starting ratings calculation")
    kwargs: Dict[str, Any] = dict(wait=wait)
    if not wait:
        Thread(target=deferred_ratings, kwargs=kwargs).start()
        return "Ratings calculation has been started", 200

    success = deferred_ratings(**kwargs)
    if not success:
        return "Ratings calculation failed", 500

    return "Ratings calculation completed", 200
