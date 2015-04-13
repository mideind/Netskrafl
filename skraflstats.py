# -*- coding: utf-8 -*-

""" Server module for Netskrafl statistics and other background tasks

    Author: Vilhjalmur Thorsteinsson, 2015

    Note: SCRABBLE is a registered trademark. This software or its author
    are in no way affiliated with or endorsed by the owners or licensees
    of the SCRABBLE trademark.

"""

import os
import logging
import json
import time
import calendar

from datetime import datetime, timedelta

from google.appengine.api import users
from google.appengine.ext import deferred
from google.appengine.runtime import DeadlineExceededError

from flask import Flask
from flask import render_template, redirect, jsonify
from flask import request, session, url_for

from languages import Alphabet
from skraflgame import User, Game
from skrafldb import Context, UserModel, GameModel, MoveModel, StatsModel, RatingModel


# Standard Flask initialization

app = Flask(__name__)

running_local = os.environ.get('SERVER_SOFTWARE','').startswith('Development')

if running_local:
    logging.info(u"Netskrafl app running with DEBUG set to True")

app.config['DEBUG'] = running_local

# !!! TODO: Change this to read the secret key from a config file at run-time
app.secret_key = '\x03\\_,i\xfc\xaf=:L\xce\x9b\xc8z\xf8l\x000\x84\x11\xe1\xe6\xb4M'

# The K constant used in the Elo calculation
ELO_K = 20.0 # For established players
BEGINNER_K = 32.0 # For beginning players

# How many games a player plays as a provisional player
# before becoming an established one
ESTABLISHED_MARK = 10


def monthdelta(date, delta):
    """ Calculate a date x months from now, in the past or in the future """
    m, y = (date.month + delta) % 12, date.year + (date.month + delta - 1) // 12
    if not m: m = 12
    d = min(date.day, calendar.monthrange(y, m)[1])
    return date.replace(day = d, month = m, year = y)


def _compute_elo(o_elo, sc0, sc1, est0, est1):
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
    # !!! TBD: Use a more fine-grained representation incorporating the score difference?
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
    adj = (int(round(adj0)), int(round(adj1)))

    # Make sure we don't adjust to a negative number
    if adj[0] + elo0 < 0:
        adj[0] = -elo0
    if adj[1] + elo1 < 0:
        adj[1] = -elo1

    return adj


def _write_stats(timestamp, urecs):
    """ Writes the freshly calculated statistics records to the database """
    # Delete all previous stats with the same timestamp, if any
    StatsModel.delete_ts(timestamp = timestamp)
    um_list = []
    for sm in urecs.values():
        # Set the reference timestamp for the entire stats series
        sm.timestamp = timestamp
        # Fetch user information to update Elo statistics
        um = UserModel.fetch(sm.user.id())
        if um:
            um.elo = sm.elo
            um.human_elo = sm.human_elo
            um_list.append(um)
    # Update the statistics records
    StatsModel.put_multi(urecs.values())
    # Update the user records
    UserModel.put_multi(um_list)


def _run_stats(from_time, to_time):
    """ Runs a process to update user statistics and Elo ratings """

    logging.info(u"Generating stats from {0} to {1}".format(from_time, to_time))

    if from_time is None or to_time is None:
        # Time range must be specified
        return

    if from_time >= to_time:
        # Null time range
        return

    # Iterate over all finished games within the time span in temporal order
    q = GameModel.query(GameModel.over == True).order(GameModel.ts_last_move) \
        .filter(GameModel.ts_last_move > from_time) \
        .filter(GameModel.ts_last_move <= to_time)

    # The accumulated user statistics
    users = dict()

    def _init_stat(user_id, robot_level):
        """ Returns the newest StatsModel instance available for the given user """
        return StatsModel.newest_before(from_time, user_id, robot_level)

    cnt = 0
    ts_last_processed = None

    try:
        # Use i as a progress counter
        for i, gm in enumerate(q):
            uuid = gm.key.id()
            ts = Alphabet.format_timestamp(gm.timestamp)
            lm = Alphabet.format_timestamp(gm.ts_last_move or gm.timestamp)
            p0 = None if gm.player0 is None else gm.player0.id()
            p1 = None if gm.player1 is None else gm.player1.id()
            robot_game = (p0 is None) or (p1 is None)
            if robot_game:
                rl = gm.robot_level
            else:
                rl = 0
            s0 = gm.score0
            s1 = gm.score1

            if (s0 == 0) and (s1 == 0):
                # When a game ends by resigning immediately,
                # make sure that the weaker player
                # doesn't get Elo points for a draw; in fact,
                # ignore such a game altogether in the statistics
                continue

            pr = gm.prefs
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
                gm.human_elo0, gm.human_elo1 = urec0.human_elo, urec1.human_elo
                adj = _compute_elo((urec0.human_elo, urec1.human_elo), s0, s1, est0, est1)
                # Adjust player 0
                if est0 and not est1:
                    adj = (0, adj[1])
                gm.human_elo0_adj = adj[0]
                urec0.human_elo += adj[0]
                # Adjust player 1
                if est1 and not est0:
                    adj = (adj[0], 0)
                gm.human_elo1_adj = adj[1]
                urec1.human_elo += adj[1]
            # Save the game object with the new Elo adjustment statistics
            gm.put()
            # Save the last processed timestamp
            ts_last_processed = lm
            cnt += 1
            # Report on our progress
            if (i + 1) % 1000 == 0:
                logging.info(u"Processed {0} games".format(i + 1))

    except DeadlineExceededError as ex:
        # Hit deadline: save the stuff we already have and
        # defer a new task to continue where we left off
        logging.info(u"Deadline exceeded in stats loop after {0} games and {1} users"
            .format(cnt, len(users)))
        logging.info(u"Resuming from timestamp {0}".format(ts_last_processed))
        if ts_last_processed is not None:
            _write_stats(ts_last_processed, users)
        deferred.defer(deferred_stats,
            from_time = ts_last_processed or from_time, to_time = to_time)
        # Normal return prevents this task from being run again
        return

    except Exception as ex:
        logging.info(u"Exception in stats loop: {0}".format(ex))
        # Avoid having the task retried
        raise deferred.PermanentTaskFailure()

    # Completed without incident
    logging.info(u"Normal completion of stats for {1} games and {0} users".format(len(users), cnt))

    _write_stats(to_time, users)


def _create_ratings(timestamp):
    """ Create the Top 100 ratings tables """

    logging.info(u"Starting _create_ratings")

    _key = StatsModel.dict_key

    def _augment_table(t, t_yesterday, t_week_ago, t_month_ago):
        """ Go through a table of top scoring users and augment it with data from previous time points """

        for sm in t:
            # Augment the rating with info about progress
            key = _key(sm)

            def _augment(prop):
                sm[prop + "_yesterday"] = t_yesterday[key][prop] if key in t_yesterday else 0
                sm[prop + "_week_ago"] = t_week_ago[key][prop] if key in t_week_ago else 0
                sm[prop + "_month_ago"] = t_month_ago[key][prop] if key in t_month_ago else 0

            _augment("rank")
            _augment("games")
            _augment("elo")
            _augment("wins")
            _augment("losses")
            _augment("score")
            _augment("score_against")

    # All players including robot games

    top100_all = [ sm for sm in StatsModel.list_elo(timestamp, 100) ]
    top100_all_yesterday = { _key(sm) : sm for sm in StatsModel.list_elo(timestamp - timedelta(days = 1), 100) }
    top100_all_week_ago = { _key(sm) : sm for sm in StatsModel.list_elo(timestamp - timedelta(days = 7), 100) }
    top100_all_month_ago = { _key(sm) : sm for sm in StatsModel.list_elo(monthdelta(timestamp, -1), 100) }

    # Augment the table for all games
    _augment_table(top100_all, top100_all_yesterday, top100_all_week_ago, top100_all_month_ago)

    # Human only games

    top100_human = [ sm for sm in StatsModel.list_human_elo(timestamp, 100) ]
    top100_human_yesterday = { _key(sm) : sm for sm in StatsModel.list_human_elo(timestamp - timedelta(days = 1), 100) }
    top100_human_week_ago = { _key(sm) : sm for sm in StatsModel.list_human_elo(timestamp - timedelta(days = 7), 100) }
    top100_human_month_ago = { _key(sm) : sm for sm in StatsModel.list_human_elo(monthdelta(timestamp, -1), 100) }

    # Augment the table for human only games
    _augment_table(top100_human, top100_human_yesterday, top100_human_week_ago, top100_human_month_ago)

    logging.info(u"Writing top 100 tables to the database")

    # Write the Top 100 tables to the database
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
        rm.put()

        # Humans only
        rm = RatingModel.get_or_create("human", rank + 1)
        if rank < len(top100_human):
            rm.assign(top100_human[rank])
        else:
            # Sentinel empty records
            rm.user = None
            rm.robot_level = -1
            rm.games = -1
        rm.put()

    logging.info(u"Finishing _create_ratings")


def deferred_stats(from_time, to_time):
    """ This is the deferred stats collection process """
    # Disable the in-context cache to save memory
    # (it doesn't give any speed advantage for this processing)
    Context.disable_cache()

    t0 = time.time()
    _run_stats(from_time, to_time)
    t1 = time.time()

    logging.info(u"Stats calculation finished in {0:.2f} seconds".format(t1 - t0))


def deferred_ratings(timestamp):
    """ This is the deferred ratings table calculation process """
    # Disable the in-context cache to save memory
    # (it doesn't give any speed advantage for this processing)
    Context.disable_cache()

    t0 = time.time()
    _create_ratings(timestamp)
    t1 = time.time()

    logging.info(u"Ratings calculation finished in {0:.2f} seconds".format(t1 - t0))


@app.route("/_ah/start")
def start():
    """ App Engine is starting a fresh instance """

    logging.info(u"Start instance {0}".format(os.environ.get("INSTANCE_ID", "")))
    return jsonify(ok = True)


@app.route("/_ah/stop")
def stop():
    """ App Engine is stopping this instance """

    logging.info(u"Stop instance {0}".format(os.environ.get("INSTANCE_ID", "")))
    return jsonify(ok = True)


@app.route("/_ah/warmup")
def warmup():
    """ App Engine is warming up this instance """
    logging.info(u"Warmup instance {0}".format(os.environ.get("INSTANCE_ID", "")))
    return jsonify(ok = True)


@app.route("/stats/run")
def stats_run():
    """ Calculate a new set of statistics """

    logging.info(u"Starting stats calculation")

    # If invoked without parameters (such as from a cron job),
    # this will calculate yesterday's statistics
    now = datetime.utcnow()
    yesterday = now - timedelta(days = 1)

    year = int(request.args.get("year", str(yesterday.year)))
    month = int(request.args.get("month", str(yesterday.month)))
    day = int(request.args.get("day", str(yesterday.day)))

    try:
        from_time = datetime(year = year, month = month, day = day)
        to_time = from_time + timedelta(days = 1)
        deferred.defer(deferred_stats, from_time = from_time, to_time = to_time)
    except Exception as ex:
        return u"Stats calculation failed with exception {0}".format(ex), 200

    # All is well so far and the calculation has been submitted to a task queue
    return u"Stats calculation has been started", 200


@app.route("/stats/ratings")
def stats_ratings():
    """ Calculate new ratings tables """

    logging.info(u"Starting ratings calculation")
    # A normal ratings calculation is based on the present point in time
    timestamp = datetime.utcnow()
    deferred.defer(deferred_ratings, timestamp = timestamp)

    return u"Ratings calculation has been started", 200


@app.route("/stats/login")
def stats_login():
    """ Handler for the login & greeting page """

    login_url = users.create_login_url(url_for("stats_ping"))

    return render_template("statslogin.html", login_url = login_url)


@app.route("/stats/ping")
def stats_ping():
    """ Confirm that the stats module is ready and serving """
    return u"Stats module is up and running", 200


@app.errorhandler(404)
def page_not_found(e):
    """ Return a custom 404 error """
    return u'Incorrect URL path', 404


@app.errorhandler(500)
def server_error(e):
    """ Return a custom 500 error """
    return u'Server error: {}'.format(e), 500


# Run a default Flask web server for testing if invoked directly as a main program

if __name__ == "__main__":
    app.run(debug=True)
