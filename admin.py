# -*- coding: utf-8 -*-

""" Admin web server for netskrafl.appspot.com

    Author: Vilhjalmur Thorsteinsson, 2015

    This web server module uses the Flask framework to implement
    an admin web area for Netskrafl.

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

from google.appengine.ext import ndb

from languages import Alphabet
from skraflgame import User, Game
from skrafldb import Unique, UserModel, GameModel, MoveModel,\
    FavoriteModel, ChallengeModel, ChannelModel

import netskrafl


# We're plugging in to the normal Netskrafl Flask app
app = netskrafl.app


@app.route("/admin/usercount", methods=['POST'])
def admin_usercount():
    """ Return a count of UserModel entities """
    count = UserModel.count()
    return jsonify(count = count)


@app.route("/admin/userupdate", methods=['GET'])
def admin_userupdate():
    """ Update all users in the datastore with lowercase nick and full name """
    CHUNK_SIZE = 200
    count = 0
    offset = 0
    q = UserModel.query()
    while True:
        ulist = []
        chunk = 0
        for um in q.fetch(CHUNK_SIZE, offset = offset):
            chunk += 1
            if um.nick_lc == None:
                try:
                    um.nick_lc = um.nickname.lower()
                    um.name_lc = um.prefs.get("full_name", "").lower() if um.prefs else ""
                    ulist.append(um)
                except Exception as e:
                    logging.info("Exception in /admin/userupdate when setting nick_lc: {0}".format(e))
        if ulist:
            try:
                ndb.put_multi(ulist)
                count += len(ulist)
            except Exception as e:
                logging.info("Exception in /admin/userupdate when updating ndb: {0}".format(e))
        if chunk < CHUNK_SIZE:
            break
        offset += CHUNK_SIZE
    return "<html><body><p>Updated {0} user records</p></body></html>".format(count)


@app.route("/admin/fetchgames", methods=['GET', 'POST'])
def admin_fetchgames():
    """ Return a JSON representation of all finished games """
    q = GameModel.query(GameModel.over == True).order(GameModel.ts_last_move)
    gamelist = []
    for gm in q.fetch():
        gamelist.append(dict(
            id = gm.key.id(),
            ts = Alphabet.format_timestamp(gm.timestamp),
            lm = Alphabet.format_timestamp(gm.ts_last_move or gm.timestamp),
            p0 = None if gm.player0 is None else gm.player0.id(),
            p1 = None if gm.player1 is None else gm.player1.id(),
            rl = gm.robot_level,
            s0 = gm.score0,
            s1 = gm.score1,
            pr = gm.prefs
        ))
    return jsonify(gamelist = gamelist)


@app.route("/admin/loadgame", methods=['POST'])
def admin_loadgame():
    """ Fetch a game object and return it as JSON """

    uuid = request.form.get("uuid", None)
    game = None

    if uuid:
        # Attempt to load the game whose id is in the URL query string
        game = Game.load(uuid)

    if game:
        board = game.state.board()
        g = dict(
            uuid = game.uuid,
            timestamp = Alphabet.format_timestamp(game.timestamp),
            player0 = game.player_ids[0],
            player1 = game.player_ids[1],
            robot_level = game.robot_level,
            ts_last_move = Alphabet.format_timestamp(game.ts_last_move),
            irack0 = game.initial_racks[0],
            irack1 = game.initial_racks[1],
            prefs = game._preferences,
            over = game.is_over(),
            moves = [ (m.player, m.move.summary(board),
                m.rack, Alphabet.format_timestamp(m.ts)) for m in game.moves ]
        )
    else:
        g = None

    return jsonify(game = g)


@app.route("/admin/main")
def admin_main():
    """ Show main administration page """

    return render_template("admin.html")

