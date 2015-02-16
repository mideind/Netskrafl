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


@app.route("/admin/fetchgames", methods=['GET', 'POST'])
def admin_fetchgames():
    """ Return a JSON representation of all finished games """
    q = GameModel.query(GameModel.over == True)
    gamelist = []
    for gm in q.fetch():
        gamelist.append(dict(
            player0 = gm.player0.id(),
            player1 = gm.player1.id(),
            rack0 = gm.rack0,
            rack1 = gm.rack1
        ))
    return jsonify(gamelist)


@app.route("/admin/main")
def admin_main():
    """ Show main administration page """

    return render_template("admin.html")

