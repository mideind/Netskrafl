# -*- coding: utf-8 -*-

""" Admin web server for netskrafl.is

    Copyright (C) 2020 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The GNU General Public License, version 3, applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    Note: SCRABBLE is a registered trademark. This software or its author
    are in no way affiliated with or endorsed by the owners or licensees
    of the SCRABBLE trademark.

"""

import logging
from threading import Thread

from flask import jsonify
from flask import request

from languages import Alphabet
from skrafldb import ndb, iter_q, Client, UserModel, GameModel
from skraflgame import User, Game


def admin_usercount():
    """ Return a count of UserModel entities """
    count = UserModel.count()
    return jsonify(count=count)


def deferred_update():
    """ Update all users in the datastore with lowercase nick and full name """
    logging.info("Deferred user update starting")
    CHUNK_SIZE = 200
    scan = 0
    count = 0
    with ndb.Client().context():
        try:
            q = UserModel.query()
            for um in iter_q(q, chunk_size=CHUNK_SIZE):
                scan += 1
                if um.email and not um.email.islower():
                    um.email = um.email.lower()
                    um.put()
                    count += 1
                if scan % 1000 == 0:
                    logging.info("Completed scanning {0} and updating {1} user records".format(scan, count))
        except Exception as e:
            logging.info(
                "Exception in deferred_update(): {0}, already scanned {1} records and updated {2}"
                .format(e, scan, count)
            )
            # Do not retry the task
            # !!! TODO: Alternative solution for Python 3 GAE environment
            # raise deferred.PermanentTaskFailure()
    logging.info("Completed scanning {0} and updating {1} user records".format(scan, count))


def admin_userupdate():
    """ Start a user update background task """
    logging.info("Starting user update")
    Thread(target=deferred_update).start()
    return "<html><body><p>User update started</p></body></html>"


def admin_setfriend():
    """ Set the friend state of a user """
    uid = request.args.get("uid", "")
    state = request.args.get("state", "1")  # Default: set as friend
    try:
        state = bool(int(state))
    except Exception:
        return (
            "<html><body><p>Invalid state string: '{0}'</p></body></html>"
            .format(state)
        )
    u = User.load_if_exists(uid) if uid else None
    if u is None:
        return "<html><body><p>Unknown user id '{0}'</p></body></html>".format(uid)
    was_friend = u.friend()
    u.set_friend(state)
    u.set_has_paid(state)
    u.update()
    logging.info("Friend state of user {0} manually set to {1}".format(uid, state))
    return (
        "<html><body><p>User '{0}': friend state was '{2}', set to '{1}'</p></body></html>"
        .format(uid, state, was_friend)
    )


def admin_fetchgames():
    """ Return a JSON representation of all finished games """
    # noinspection PyPep8
    # pylint: disable=singleton-comparison
    q = GameModel.query(GameModel.over == True).order(GameModel.ts_last_move)
    gamelist = []
    for gm in q.fetch():
        gamelist.append(
            dict(
                id=gm.key.id(),
                ts=Alphabet.format_timestamp(gm.timestamp),
                lm=Alphabet.format_timestamp(gm.ts_last_move or gm.timestamp),
                p0=None if gm.player0 is None else gm.player0.id(),
                p1=None if gm.player1 is None else gm.player1.id(),
                rl=gm.robot_level,
                s0=gm.score0,
                s1=gm.score1,
                pr=gm.prefs
            )
        )
    return jsonify(gamelist=gamelist)


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
            uuid=game.uuid,
            timestamp=Alphabet.format_timestamp(game.timestamp),
            player0=game.player_ids[0],
            player1=game.player_ids[1],
            robot_level=game.robot_level,
            ts_last_move=Alphabet.format_timestamp(game.ts_last_move),
            irack0=game.initial_racks[0],
            irack1=game.initial_racks[1],
            prefs=game._preferences,
            over=game.is_over(),
            moves=[
                (
                    m.player,
                    m.move.summary(board),
                    m.rack,
                    Alphabet.format_timestamp(m.ts),
                )
                for m in game.moves
            ]
        )
    else:
        g = None

    return jsonify(game=g)

