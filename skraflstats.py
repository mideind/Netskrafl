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

from datetime import datetime, timedelta

from flask import Flask
from flask import render_template, redirect, jsonify
from flask import request, session, url_for

from languages import Alphabet
from skraflgame import User, Game
from skrafldb import UserModel, GameModel, MoveModel, StatsModel


# Standard Flask initialization

app = Flask(__name__)

running_local = os.environ.get('SERVER_SOFTWARE','').startswith('Development')

if running_local:
    logging.info(u"Netskrafl app running with DEBUG set to True")

app.config['DEBUG'] = running_local

# !!! TODO: Change this to read the secret key from a config file at run-time
app.secret_key = '\x03\\_,i\xfc\xaf=:L\xce\x9b\xc8z\xf8l\x000\x84\x11\xe1\xe6\xb4M'


def _compute_elo(p0, p1, o_elo, sc0, sc1):
    """ Computes the ELO points of the two users after their game """

    # If no points scored, this is a null game having no effect
    assert sc0 >= 0
    assert sc1 >= 0
    if sc0 + sc1 == 0:
        return (0, 0)

    # The constant K used for adjustments
    # !!! TBD: select K depending on number of games played and other factors
    K = 32.0

    # Current ELO ratings
    elo0 = o_elo[0]
    elo1 = o_elo[1]

    # Calculate the quotients for each player using a logistic function.
    # For instance, a player with 1_200 ELO points would get a Q of 10^3 = 1_000,
    # a player with 800 ELO points would get Q = 10^2 = 100
    # and a player with 1_600 ELO points would get Q = 10^4 = 10_000.
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
    adj0 = (act0 - exp0) * K
    adj1 = (act1 - exp1) * K

    # Calculate the final adjustment tuple
    adj = (int(round(adj0)), int(round(adj1)))

    # Make sure we don't adjust to a negative number
    if adj[0] + elo0 < 0:
        adj[0] = -elo0
    if adj[1] + elo1 < 0:
        adj[1] = -elo1

    logging.info(u"Game with score {0}:{1}".format(sc0, sc1))
    logging.info(u"Adjusted ELO of player {0} by {3:.2f} from {1} to {2}, exp {4:.2f} act {5:.2f}".format(p0, elo0, elo0 + adj[0], adj0, exp0, act0))
    logging.info(u"Adjusted ELO of player {0} by {3:.2f} from {1} to {2}, exp {4:.2f} act {5:.2f}".format(p1, elo1, elo1 + adj[1], adj1, exp1, act1))

    return adj


def _write_stats(urecs):
    """ Writes the freshly calculated statistics records to the database """
    # Establish the reference timestamp for the entire stats series
    ts = datetime.utcnow()
    for sm in urecs.values():
        sm.timestamp = ts
    StatsModel.put_multi(urecs.values())


def _make_stat(user_id):
    """ Makes a fresh StatsModel instance for the given user """
    sm = StatsModel.create(user_id)
    return sm


def _run_stats():
    """ Runs a process to update user statistics and ELO ratings """
    # Iterate over all finished games in temporal order
    q = GameModel.query(GameModel.over == True).order(GameModel.ts_last_move)
    # The accumulated user statistics
    users = dict()
    for gm in q.fetch():
        uuid = gm.key.id()
        ts = Alphabet.format_timestamp(gm.timestamp)
        lm = Alphabet.format_timestamp(gm.ts_last_move or gm.timestamp)
        p0 = None if gm.player0 is None else gm.player0.id()
        p1 = None if gm.player1 is None else gm.player1.id()
        robot_game = (p0 is None) or (p1 is None)
        rl = gm.robot_level
        s0 = gm.score0
        s1 = gm.score1
        pr = gm.prefs
        if p0 is None:
            p0 = "robot_" + str(rl)
        if p1 is None:
            p1 = "robot_" + str(rl)
        if p0 in users:
            urec0 = users[p0]
        else:
            users[p0] = urec0 = _make_stat(p0)
        if p1 in users:
            urec1 = users[p1]
        else:
            users[p1] = urec1 = _make_stat(p1)
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
        # Compute the ELO points of both players
        adj = _compute_elo(p0, p1, (urec0.elo, urec1.elo), s0, s1)
        urec0.elo += adj[0]
        urec1.elo += adj[1]
        # If not a robot game, compute the human-only ELO
        if not robot_game:
            adj = _compute_elo(p0, p1, (urec0.human_elo, urec1.human_elo), s0, s1)
            urec0.human_elo += adj[0]
            urec1.human_elo += adj[1]

    logging.info(u"Generated stats for {0} users".format(len(users)))
    _write_stats(users)

    return users


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


# Use a simple flag to avoid re-entrancy
stats_running = False

@app.route("/stats/run")
def stats_run():
    """ Calculate a new set of statistics """
    global stats_running
    if stats_running:
        return u"/stats/run already running", 200

    logging.info(u"Starting stats calculation")
    stats_running = True
    t0 = time.time()
    stats = _run_stats()
    t1 = time.time()
    stats_running = False

    return u"Stats calculation finished in {0:.2f} seconds".format(t1 - t0), 200


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
