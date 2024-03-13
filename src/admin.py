"""

    Admin web server for netskrafl.is

    Copyright (C) 2023 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

"""

from __future__ import annotations

from typing import List, Optional, Dict, Any

import logging
from threading import Thread
from datetime import UTC, datetime

from flask import request
from flask.wrappers import Response

from basics import jsonify
from languages import Alphabet
from skrafldb import Client, iter_q, Query, UserModel, GameModel
from skrafluser import User
from skraflgame import Game


def admin_usercount() -> Response:
    """Return a count of UserModel entities"""
    count = UserModel.count()
    return jsonify(count=count)


def deferred_user_update() -> None:
    """Update all users in the datastore with lowercase nick and full name"""
    logging.info("Deferred user update starting")
    CHUNK_SIZE = 200
    scan = 0
    count = 0
    with Client.get_context():
        try:
            q: Query[UserModel] = UserModel.query()
            for um in iter_q(q, chunk_size=CHUNK_SIZE):
                scan += 1
                if um.email and not um.email.islower():
                    um.email = um.email.lower()
                    um.put()
                    count += 1
                if scan % 1000 == 0:
                    logging.info(
                        "Completed scanning {0} and updating {1} user entities".format(
                            scan, count
                        )
                    )
        except Exception as e:
            logging.info(
                f"Exception in deferred_user_update(): {e}, "
                f"already scanned {scan} entities and updated {count}"
            )
    logging.info(f"Completed scanning {scan} and updating {count} user entities")


'''
def deferred_game_update() -> None:
    """Reindex all games in the datastore by loading them and saving them again"""
    logging.info("Deferred game update starting")
    CHUNK_SIZE = 250
    count = 0
    updated = 0
    with Client.get_context():
        Context.disable_cache()
        Context.disable_global_cache()
        try:
            q: Query[GameModel] = GameModel.query()
            result: List[GameModel] = []
            for gm in iter_q(q, chunk_size=CHUNK_SIZE):
                if not gm.index_updated:
                    # Not already updated
                    gm.index_updated = True
                    result.append(gm)
                    if len(result) >= CHUNK_SIZE:
                        GameModel.put_multi(result)
                        updated += len(result)
                        result = []
                count += 1
                if count % 1000 == 0:
                    logging.info(
                        f"Completed scanning {count} game entities, updated {updated} entities"
                    )
            if result:
                GameModel.put_multi(result)
                updated += len(result)
        except Exception as e:
            logging.info(
                f"Exception in deferred_game_update(): {e}, already scanned {count} entities, updated {updated} entities"
            )
    logging.info(
        f"Completed scanning {count} and updating {updated} game entities"
    )
'''


def admin_userupdate() -> Response:
    """Start a user update background task"""
    logging.info("Starting user update")
    Thread(target=deferred_user_update).start()
    return jsonify(ok=True, result="User update started")


'''
def admin_gameupdate() -> Response:
    """Start a game update background task"""
    Thread(target=deferred_game_update).start()
    return jsonify(ok=True, result="Game update started")
'''


def admin_setfriend() -> str:
    """Set the friend state of a user"""
    uid = request.args.get("uid", "")
    state = request.args.get("state", "1")  # Default: set as friend
    try:
        bstate = bool(int(state))
    except Exception:
        return "<html><body><p>Invalid state string: '{0}'</p></body></html>".format(
            state
        )
    u = User.load_if_exists(uid) if uid else None
    if u is None:
        return "<html><body><p>Unknown user id '{0}'</p></body></html>".format(uid)
    was_friend = u.friend()
    u.add_transaction("friend" if bstate else "", "admin", "setfriend")
    logging.info("Friend state of user {0} manually set to {1}".format(uid, bstate))
    return (
        f"<html><body><p>User '{uid}': friend state was {was_friend}; "
        f"set to friend={u.friend()}, has_paid={u.has_paid()}</p></body></html>"
    )


def admin_fetchgames() -> Response:
    """Return a JSON representation of all finished games"""
    # pylint: disable=singleton-comparison
    q = GameModel.query(GameModel.over == True).order(GameModel.ts_last_move)
    gamelist: List[Dict[str, Any]] = []
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
                pr=gm.prefs,
            )
        )
    return jsonify(gamelist=gamelist)


def admin_loadgame() -> Response:
    """Fetch a game object and return it as JSON"""

    uuid = request.form.get("uuid", None)
    game = None

    g: Optional[Dict[str, Any]] = None

    if uuid:
        # Attempt to load the game by its UUID
        game = Game.load(uuid, set_locale=True, use_cache=False)

    if game is not None and game.state is not None:
        now = datetime.now(UTC)
        g = dict(
            uuid=game.uuid,
            timestamp=Alphabet.format_timestamp(game.timestamp or now),
            player0=game.player_ids[0],
            player1=game.player_ids[1],
            robot_level=game.robot_level,
            ts_last_move=Alphabet.format_timestamp(game.ts_last_move or now),
            irack0=game.initial_racks[0],
            irack1=game.initial_racks[1],
            prefs=game.preferences,
            over=game.is_over(),
            moves=[
                (
                    m.player,
                    m.move.summary(game.state),
                    m.rack,
                    Alphabet.format_timestamp(m.ts or now),
                )
                for m in game.moves
            ],
        )

    return jsonify(game=g)


def admin_loaduser() -> Response:
    """Fetch a user object and return it as JSON"""

    userid = request.form.get("id", None)
    user = None

    u: Optional[Dict[str, Any]] = None

    if userid:
        # Attempt to load the user by UUID, account id, email or nickname
        user = User.load_if_exists(userid)
        if user is None:
            user = User.load_by_account(userid)
        if user is None and "@" in userid:
            user = User.load_by_email(userid)
        if user is None:
            user = User.load_by_nickname(userid, ignore_case=True)

    if user is not None:
        now = datetime.now(UTC)
        u = dict(
            userid=user.id(),
            account=user.account(),
            timestamp=Alphabet.format_timestamp(user.timestamp() or now),
            email=user.email(),
            nick=user.nickname(),
            full_name=user.full_name(),
            friend=user.friend(),
            has_paid=user.has_paid(),
            plan=user.plan(),
            locale=user.locale,
            location=user.location,
            inactive=user.is_inactive(),
            blocked_by=list(user.blocked_by()),
            reported_by=list(user.reported_by()),
        )

    return jsonify(user=u)
