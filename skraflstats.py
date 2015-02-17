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

from datetime import datetime, timedelta

from flask import Flask
from flask import render_template, redirect, jsonify
from flask import request, session, url_for

from google.appengine.api import users, memcache

from languages import Alphabet
from skraflmechanics import Move, PassMove, ExchangeMove, ResignMove, Error
from skraflgame import User, Game
from skrafldb import Unique, UserModel, GameModel, MoveModel,\
    FavoriteModel, ChallengeModel, ChannelModel


# Standard Flask initialization

app = Flask(__name__)

running_local = os.environ.get('SERVER_SOFTWARE','').startswith('Development')

if running_local:
    logging.info(u"Netskrafl app running with DEBUG set to True")

app.config['DEBUG'] = running_local

# !!! TODO: Change this to read the secret key from a config file at run-time
app.secret_key = '\x03\\_,i\xfc\xaf=:L\xce\x9b\xc8z\xf8l\x000\x84\x11\xe1\xe6\xb4M'

class UserRecord(object):

    def __init__(self, key):
        self.key = key
        self.elo = 1200 # Initial rating
        self.num_games = 0
        self.num_human_games = 0
        self.total_score = 0
        self.total_human_score = 0
        self.total_score_against = 0
        self.total_human_score_against = 0
        self.num_wins = 0
        self.num_losses = 0
        self.num_human_wins = 0
        self.num_human_losses = 0


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
            users[p0] = urec0 = UserRecord(p0)
        if p1 in users:
            urec1 = users[p1]
        else:
            users[p1] = urec1 = UserRecord(p1)
        # Number of games played
        urec0.num_games += 1
        urec1.num_games += 1
        if not robot_game:
            urec0.num_human_games += 1
            urec1.num_human_games += 1
        # Total scores
        urec0.total_score += s0
        urec1.total_score += s1
        urec0.total_score_against += s1
        urec1.total_score_against += s0
        if not robot_game:
            urec0.total_human_score += s0
            urec1.total_human_score += s1
            urec0.total_human_score_against += s1
            urec1.total_human_score_against += s0
        # Wins and losses
        if s0 > s1:
            urec0.num_wins += 1
            urec1.num_losses += 1
        elif s1 > s0:
            urec1.num_wins += 1
            urec0.num_losses += 1
        if not robot_game:
            if s0 > s1:
                urec0.num_human_wins += 1
                urec1.num_human_losses += 1
            elif s1 > s0:
                urec1.num_human_wins += 1
                urec0.num_human_losses += 1
    logging.info(u"Generated stats for {0} users".format(len(users)))
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

    stats_running = True
    stats = _run_stats()
    ser_stats = [val.__dict__ for k, val in stats.items()]
    stats_running = False

    return jsonify(stats = ser_stats)


@app.errorhandler(404)
def page_not_found(e):
    """ Return a custom 404 error """
    return u'Þessi vefslóð er ekki rétt', 404


@app.errorhandler(500)
def server_error(e):
    """ Return a custom 500 error """
    return u'Eftirfarandi villa kom upp: {}'.format(e), 500

# Run a default Flask web server for testing if invoked directly as a main program

if __name__ == "__main__":
    app.run(debug=True)
