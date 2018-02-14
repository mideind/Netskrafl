# -*- coding: utf-8 -*-

""" Web server for netskrafl.is

    Copyright (C) 2015-2017 Miðeind ehf.
    Author: Vilhjalmur Thorsteinsson

    The GNU General Public License, version 3, applies to this software.
    For further information, see https://github.com/vthorsteinsson/Netskrafl

    This web server module uses the Flask framework to implement
    a crossword game similar to SCRABBLE(tm).

    The actual game logic is found in skraflplayer.py and
    skraflmechanics.py.

    The User and Game classes are found in skraflgame.py.

    The web client code is found in netskrafl.js.

    The server is compatible with Python 2.7 and 3.x, CPython and PyPy.

    Note: SCRABBLE is a registered trademark. This software or its author
    are in no way affiliated with or endorsed by the owners or licensees
    of the SCRABBLE trademark.

"""

import os
import logging
import json
import threading
import re
import random
import urllib

from datetime import datetime, timedelta

from flask import Flask
from flask import render_template, redirect, jsonify
from flask import request, url_for

from google.appengine.api import users, memcache
from google.appengine.runtime import DeadlineExceededError
import google.appengine.api.urlfetch as urlfetch

from languages import Alphabet
from dawgdictionary import Wordbase
from skraflmechanics import Move, PassMove, ExchangeMove, \
    ResignMove, ChallengeMove, ResponseMove, Error
from skraflplayer import AutoPlayer
from skraflgame import User, Game
from skrafldb import Context, UserModel, GameModel, \
    FavoriteModel, ChallengeModel, RatingModel, ChatModel, \
    ZombieModel, PromoModel
import billing
import firebase

# Standard Flask initialization

app = Flask(__name__)

running_local = os.environ.get('SERVER_SOFTWARE', '').startswith('Development')

if running_local:
    logging.info(u"Netskrafl app running with DEBUG set to True")

app.config['DEBUG'] = running_local

# Read secret session key from file
with open(os.path.abspath(os.path.join("resources", "secret_key.bin")), "rb") as f:
    app.secret_key = f.read()

# To try to finish requests as soon as possible and avoid DeadlineExceeded
# exceptions, run the AutoPlayer move generator serially and exclusively
# within an instance
_autoplayer_lock = threading.Lock()

# Promotion parameters
_PROMO_FREQUENCY = 8 # A promo check is done randomly, but on average every 1 out of N times
_PROMO_COUNT = 2 # Max number of times that the same promo is displayed
_PROMO_INTERVAL = timedelta(days = 4) # Min interval between promo displays


@app.before_request
def before_request():
    """ Redirect http requests to https, returning a Moved Permanently code """
    if not running_local and request.url.startswith('http://') \
        and not request.path.startswith('/_ah/'):
        url = request.url.replace('http://', 'https://', 1)
        code = 301 # Moved Permanently
        return redirect(url, code=code)


@app.after_request
def add_headers(response):
    """ Inject additional headers into responses """
    if not running_local:
        # Add HSTS to enforce HTTPS
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.context_processor
def inject_into_context():
    """ Inject variables and functions into all Flask contexts """
    return dict(
        dev_server = running_local # Variable dev_server is True if running on the GAE development server
    )


@app.template_filter('stripwhite')
def stripwhite(s):
    """ Flask/Jinja2 template filter to strip out consecutive whitespace """
    # Convert all consecutive runs of whitespace of 1 char or more into a single space
    return re.sub(r'\s+', ' ', s)


class RequestData:

    """ Wraps the Flask request object to allow error-checked retrieval of query
        parameters either from JSON or from form-encoded POST data """

    _TRUE_SET = frozenset(("true", "True", u"true", u"True", "1", 1, True))
    _FALSE_SET = frozenset(("false", "False", u"false", u"False", "0", 0, False))

    def __init__(self, request):
        # If JSON data is present, assume this is a JSON request
        self.q = request.get_json(silent = True)
        self.using_json = True
        if not self.q:
            # No JSON data: assume this is a form-encoded request
            self.q = request.form
            self.using_json = False
            if not self.q:
                self.q = dict()

    def get(self, key, default = None):
        """ Obtain an arbitrary data item from the request """
        return self.q.get(key, default)

    def get_int(self, key, default = 0):
        """ Obtain an integer data item from the request """
        try:
            return int(self.q.get(key, default))
        except TypeError, ValueError:
            return default

    def get_bool(self, key, default = False):
        """ Obtain a boolean data item from the request """
        try:
            val = self.q.get(key, default)
            if val in self._TRUE_SET:
                # This is a truthy value
                return True
            if val in self._FALSE_SET:
                # This is a falsy value
                return False
        except TypeError, ValueError:
            pass
        # Something else, i.e. neither truthy nor falsy: return the default
        return default

    def get_list(self, key, default = []):
        """ Obtain a list data item from the request """
        if self.using_json:
            # Normal get from a JSON dictionary
            r = self.q.get(key, default)
        else:
            # Use special getlist() call on request.form object
            r = self.q.getlist(key + "[]")
        if not isinstance(r, list):
            return default
        return r

    def __getitem__(self, key):
        """ Shortcut: allow indexing syntax with an empty (Unicode) string default """
        return self.q.get(key, u"")


def _process_move(game, movelist):
    """ Process a move coming in from the client """

    assert game is not None

    if game.is_over():
        return jsonify(result = Error.GAME_NOT_FOUND)

    player_index = game.player_to_move()

    # Parse the move from the movestring we got back
    m = Move(u'', 0, 0)
    try:
        for mstr in movelist:
            if mstr == u"pass":
                # Pass move (or accepting the last move in the game without challenging it)
                m = PassMove()
                break
            if mstr.startswith(u"exch="):
                # Exchange move
                m = ExchangeMove(mstr[5:])
                break
            if mstr == u"rsgn":
                # Resign from game, forfeiting all points
                m = ResignMove(game.state.scores()[player_index])
                break
            if mstr == u"chall":
                # Challenging the last move
                m = ChallengeMove()
                break
            sq, tile = mstr.split(u'=')
            row = u"ABCDEFGHIJKLMNO".index(sq[0])
            col = int(sq[1:]) - 1
            if tile[0] == u'?':
                # If the blank tile is played, the next character contains
                # its meaning, i.e. the letter it stands for
                letter = tile[1]
                tile = tile[0]
            else:
                letter = tile
            m.add_cover(row, col, tile, letter)
    except Exception as e:
        logging.info(u"Exception in _process_move(): {0}".format(e).encode("latin-1"))
        m = None

    # Process the move string here
    # Unpack the error code and message
    err = game.check_legality(m)
    msg = ""
    if isinstance(err, tuple):
        err, msg = err

    if err != Error.LEGAL:
        # Something was wrong with the move:
        # show the user a corresponding error message
        return jsonify(result = err, msg = msg)

    # Serialize access to the following code section
    with _autoplayer_lock:

        # Move is OK: register it and update the state
        game.register_move(m)

        # If it's the autoplayer's move, respond immediately
        # (can be a bit time consuming if rack has one or two blank tiles)
        opponent = game.player_id_to_move()

        is_over = game.is_over()

        if not is_over:

            if opponent is None:
                # Generate an autoplayer move in response
                game.autoplayer_move()
                is_over = game.is_over() # State may change during autoplayer_move()
            elif isinstance(m, ChallengeMove):
                # Challenge: generate a response move
                game.response_move()
                is_over = game.is_over() # State may change during response_move()

        if is_over:
            # If the game is now over, tally the final score
            game.finalize_score()

        # Make sure the new game state is persistently recorded
        game.store()

        # If the game is now over, and the opponent is human, add it to the
        # zombie game list so that the opponent has a better chance to notice
        # the result
        if is_over and opponent is not None:
            ZombieModel.add_game(game.id(), opponent)

    if opponent is not None:
        # Send Firebase notifications
        # Send a game update to the opponent, if human, including
        # the full client state. board.html and main.html listen to this.
        # Also update the user/[opp_id]/move branch with the current timestamp.
        client_state = game.client_state(1 - player_index, m)
        msg = {
            "game/" + game.id() + "/" + opponent + "/move" : client_state,
            "user/" + opponent : { "move" : datetime.utcnow().isoformat() }
        }
        firebase.send_message(msg)

    # Return a state update to the client (board, rack, score, movelist, etc.)
    return jsonify(game.client_state(player_index))


def fetch_users(ulist, uid_func):
    """ Return a dictionary of users found in the ulist """
    # Make a list of user ids by applying the uid_func to ulist entries (!= None)
    uids = []
    for u in ulist:
        uid = None if u is None else uid_func(u)
        if uid:
            uids.append(uid)
    # No need for a special case for an empty list
    users = User.load_multi(uids)
    # Return a dictionary mapping user ids to users
    return { uid : user for uid, user in zip(uids, users) }


def _userlist(query, spec):
    """ Return a list of users matching the filter criteria """

    result = []

    def elo_str(elo):
        """ Return a string representation of an Elo score, or a hyphen if none """
        return unicode(elo) if elo else u"-"

    # We will be returning a list of human players
    cuser = User.current()
    cuid = None if cuser is None else cuser.id()

    if query == u"robots":
        # Return the list of available autoplayers
        for r in Game.AUTOPLAYERS:
            result.append({
                "userid": u"robot-" + str(r[2]),
                "nick": r[0],
                "fullname": r[1],
                "human_elo": elo_str(None),
                "fav": False,
                "chall": False,
                "fairplay": False, # The robots don't play fair ;-)
                "newbag": cuser is not None and cuser.new_bag(),
                "ready": True, # The robots are always ready for a challenge
                "ready_timed": False # Timed games are not available for robots
            })
        # That's it; we're done (no sorting required)
        return result

    # Generate a list of challenges issued by this user
    challenges = set()
    if cuid:
        challenges.update([ch[0] # Identifier of challenged user
            for ch in ChallengeModel.list_issued(cuid, max_len = 20)])

    # Get the list of online users

    # Start by looking in the cache
    online = memcache.get("live", namespace="userlist")
    if online is None:
        # Not found: do a query
        online = firebase.get_connected_users() # Returns a set
        # Store the result in the cache with a lifetime of 3 minutes
        memcache.set("live", online, time=3 * 60, namespace="userlist")

    if query == u"live":
        # Return all online (live) users

        ousers = User.load_multi(online)
        for lu in ousers:
            if lu and lu.is_displayable() and lu.id() != cuid:
                # Don't display the current user in the online list
                uid = lu.id()
                chall = uid in challenges
                result.append({
                    "userid": uid,
                    "nick": lu.nickname(),
                    "fullname": lu.full_name(),
                    "human_elo": elo_str(lu.human_elo()),
                    "fav": False if cuser is None else cuser.has_favorite(uid),
                    "chall": chall,
                    "fairplay": lu.fairplay(),
                    "newbag": lu.new_bag(),
                    "ready": lu.is_ready() and not chall,
                    "ready_timed": lu.is_ready_timed() and not chall
                })

    elif query == u"fav":
        # Return favorites of the current user
        if cuid is not None:
            i = FavoriteModel.list_favorites(cuid)
            # Do a multi-get of the entire favorites list
            fusers = User.load_multi(i)
            for fu in fusers:
                if fu and fu.is_displayable():
                    favid = fu.id()
                    chall = favid in challenges
                    result.append({
                        "userid": favid,
                        "nick": fu.nickname(),
                        "fullname": fu.full_name(),
                        "human_elo": elo_str(fu.human_elo()),
                        "fav": True,
                        "chall": chall,
                        "fairplay": fu.fairplay(),
                        "newbag": fu.new_bag(),
                        "ready": fu.is_ready() and favid in online and not chall,
                        "ready_timed": fu.is_ready_timed() and favid in online and not chall
                    })

    elif query == u"alike":
        # Return users with similar Elo ratings
        if cuid is not None:
            i = UserModel.list_similar_elo(cuser.human_elo(), max_len = 40)
            ausers = User.load_multi(i)
            for au in ausers:
                if au and au.is_displayable() and au.id() != cuid:
                    uid = au.id()
                    chall = uid in challenges
                    result.append({
                        "userid": uid,
                        "nick": au.nickname(),
                        "fullname": au.full_name(),
                        "human_elo": elo_str(au.human_elo()),
                        "fav": False if cuser is None else cuser.has_favorite(uid),
                        "chall": chall,
                        "fairplay": au.fairplay(),
                        "newbag": au.new_bag(),
                        "ready": au.is_ready() and uid in online and not chall,
                        "ready_timed": au.is_ready_timed() and uid in online and not chall
                    })

    elif query == u"search":
        # Return users with nicknames matching a pattern

        if not spec:
            i = []
        else:
            # Limit the spec to 16 characters
            spec = spec[0:16]

            # The "N:" prefix is a version header
            cache_range = "4:" + spec.lower() # Case is not significant

            # Start by looking in the cache
            i = memcache.get(cache_range, namespace = "userlist")
            if i is None:
                # Not found: do an query, returning max 25 users
                i = list(UserModel.list_prefix(spec, max_len = 25))
                # Store the result in the cache with a lifetime of 2 minutes
                memcache.set(cache_range, i, time = 2 * 60, namespace = "userlist")

        def displayable(ud):
            """ Determine whether a user entity is displayable in a list """
            return User.is_valid_nick(ud["nickname"])

        for ud in i:
            uid = ud["id"]
            if uid == cuid:
                # Do not include the current user, if any, in the list
                continue
            if displayable(ud):
                chall = uid in challenges
                result.append({
                    "userid": uid,
                    "nick": ud["nickname"],
                    "fullname": User.full_name_from_prefs(ud["prefs"]),
                    "human_elo": elo_str(ud["human_elo"] or User.DEFAULT_ELO),
                    "fav": False if cuser is None else cuser.has_favorite(uid),
                    "chall": chall,
                    "fairplay": User.fairplay_from_prefs(ud["prefs"]),
                    "newbag": User.new_bag_from_prefs(ud["prefs"]),
                    "ready": ud["ready"] and uid in online and not chall,
                    "ready_timed": ud["ready_timed"] and uid in online and not chall
                })

    # Sort the user list. The list is ordered so that users who are
    # ready for any kind of challenge come first, then users who are ready for
    # a timed game, and finally all other users. Each category is sorted
    # by nickname, case-insensitive.
    result.sort(key = lambda x: (
        # First by readiness
        0 if x["ready"] else 1 if x["ready_timed"] else 2,
        # Then by nickname
        Alphabet.sortkey_nocase(x["nick"])
        )
    )
    return result


def _gamelist(cuid, include_zombies = True):
    """ Return a list of active and zombie games for the current user """
    result = []
    if not cuid:
        return result
    now = datetime.utcnow()
    # Place zombie games (recently finished games that this player
    # has not seen) at the top of the list
    if include_zombies:
        for g in ZombieModel.list_games(cuid):
            opp = g["opp"] # User id of opponent
            u = User.load(opp)
            nick = u.nickname()
            prefs = g.get("prefs", None)
            fairplay = Game.fairplay_from_prefs(prefs)
            newbag = Game.new_bag_from_prefs(prefs)
            manual = Game.manual_wordcheck_from_prefs(prefs)
            timed = Game.get_duration_from_prefs(prefs) # Time per player in minutes
            result.append({
                "uuid": g["uuid"],
                "url": url_for('board', game = g["uuid"], zombie = "1"), # Mark zombie state
                "oppid": opp,
                "opp": nick,
                "fullname": u.full_name(),
                "sc0": g["sc0"],
                "sc1": g["sc1"],
                "ts": Alphabet.format_timestamp_short(g["ts"]),
                "my_turn": False,
                "overdue": False,
                "zombie": True,
                "fairplay": fairplay,
                "newbag": newbag,
                "manual": manual,
                "timed": timed,
                "tile_count": 100 # All tiles (100%) accounted for
            })
        # Sort zombies in decreasing order by last move, i.e. most recently completed games first
        result.sort(key = lambda x: x["ts"], reverse = True)

    # Obtain up to 50 live games where this user is a player
    i = list(GameModel.iter_live_games(cuid, max_len = 50))
    # Sort in reverse order by turn and then by timestamp of the last move,
    # i.e. games with newest moves first
    i.sort(key = lambda x: (x["my_turn"], x["ts"]), reverse = True)
    # Multi-fetch the opponents in the game list
    opponents = fetch_users(i, lambda g: g["opp"])
    # Iterate through the game list
    for g in i:
        opp = g["opp"] # User id of opponent
        ts = g["ts"]
        overdue = False
        prefs = g.get("prefs", None)
        tileset = Game.tileset_from_prefs(prefs)
        fairplay = Game.fairplay_from_prefs(prefs)
        newbag = Game.new_bag_from_prefs(prefs)
        manual = Game.manual_wordcheck_from_prefs(prefs)
        timed = Game.get_duration_from_prefs(prefs) # Time per player in minutes
        fullname = ""
        if opp is None:
            # Autoplayer opponent
            nick = Game.autoplayer_name(g["robot_level"])
        else:
            # Human opponent
            u = opponents[opp] # Was User.load(opp)
            nick = u.nickname()
            fullname = u.full_name()
            delta = now - ts
            if g["my_turn"]:
                # Start to show warning after 12 days
                overdue = (delta >= timedelta(days = Game.OVERDUE_DAYS - 2))
            else:
                # Show mark after 14 days
                overdue = (delta >= timedelta(days = Game.OVERDUE_DAYS))
        result.append({
            "uuid": g["uuid"],
            "url": url_for('board', game = g["uuid"]),
            "oppid": opp,
            "opp": nick,
            "fullname": fullname,
            "sc0": g["sc0"],
            "sc1": g["sc1"],
            "ts": Alphabet.format_timestamp_short(ts),
            "my_turn": g["my_turn"],
            "overdue": overdue,
            "zombie": False,
            "fairplay": fairplay,
            "newbag": newbag,
            "manual": manual,
            "timed": timed,
            "tile_count": int(g["tile_count"] * 100 / tileset.num_tiles())
        })
    return result


def _rating(kind):
    """ Return a list of Elo ratings of the given kind ('all' or 'human') """
    result = []
    cuser = User.current()
    cuid = None if cuser is None else cuser.id()

    # Generate a list of challenges issued by this user
    challenges = set()
    if cuid:
        challenges.update([ch[0] # Identifier of challenged user
            for ch in iter(ChallengeModel.list_issued(cuid, max_len = 20))])

    rating = memcache.get(kind, namespace="rating")
    if rating is None:
        # Not found: do a query
        rating = list(RatingModel.list_rating(kind))
        # Store the result in the cache with a lifetime of 1 hour
        memcache.set(kind, rating, time=1 * 60 * 60, namespace="rating")

    for ru in rating:

        uid = ru["userid"]
        if not uid:
            # Hit the end of the list
            break
        inactive = False
        if uid.startswith(u"robot-"):
            nick = Game.autoplayer_name(int(uid[6:]))
            fullname = nick
            chall = False
            fairplay = False
            # Robots have the same new bag preference as the user
            newbag = cuser and cuser.new_bag()
        else:
            usr = User.load(uid)
            if usr is None:
                # Something wrong with this one: don't bother
                continue
            nick = usr.nickname()
            if not User.is_valid_nick(nick):
                nick = u"--"
            fullname = usr.full_name()
            chall = uid in challenges
            fairplay = usr.fairplay()
            newbag = usr.new_bag()
            inactive = usr.is_inactive()

        games = ru["games"]
        if games == 0:
            ratio = 0
            avgpts = 0
        else:
            ratio = int(round(100.0 * float(ru["wins"]) / games))
            avgpts = int(round(float(ru["score"]) / games))

        result.append({
            "rank": ru["rank"],
            "rank_yesterday": ru["rank_yesterday"],
            "rank_week_ago": ru["rank_week_ago"],
            "rank_month_ago": ru["rank_month_ago"],

            "userid": uid,
            "nick": nick,
            "fullname": fullname,
            "chall": chall,
            "fairplay": fairplay,
            "newbag": newbag,
            "inactive": inactive,

            "elo": ru["elo"],
            "elo_yesterday": ru["elo_yesterday"],
            "elo_week_ago": ru["elo_week_ago"],
            "elo_month_ago": ru["elo_month_ago"],

            "games": games,
            "games_yesterday": ru["games_yesterday"],
            "games_week_ago": ru["games_week_ago"],
            "games_month_ago": ru["games_month_ago"],

            "ratio": ratio,
            "avgpts": avgpts
        })

    return result


def _recentlist(cuid, versus, max_len):
    """ Return a list of recent games for the indicated user, eventually
        filtered by the opponent id (versus) """
    if cuid is None:
        return []
    result = []
    # Obtain a list of recently finished games where the indicated user was a player
    rlist = GameModel.list_finished_games(cuid, versus = versus, max_len = max_len)
    # Multi-fetch the opponents in the list into a dictionary
    opponents = fetch_users(rlist, lambda g: g["opp"])
    for g in rlist:
        opp = g["opp"]
        if opp is None:
            # Autoplayer opponent
            nick = Game.autoplayer_name(g["robot_level"])
        else:
            # Human opponent
            u = opponents[opp] # Was User.load(opp)
            nick = u.nickname()

        # Calculate the duration of the game in days, hours, minutes
        ts_start = g["ts"]
        ts_end = g["ts_last_move"]

        prefs = g["prefs"]

        if (ts_start is None) or (ts_end is None):
            days, hours, minutes = (0, 0, 0)
        else:
            td = ts_end - ts_start # Timedelta
            tsec = td.total_seconds()
            days, tsec = divmod(tsec, 24 * 60 * 60)
            hours, tsec = divmod(tsec, 60 * 60)
            minutes, tsec = divmod(tsec, 60) # Ignore the remaining seconds

        result.append({
            "url": url_for('board', game = g["uuid"]),
            "opp": nick,
            "opp_is_robot": opp is None,
            "sc0": g["sc0"],
            "sc1": g["sc1"],
            "elo_adj": g["elo_adj"],
            "human_elo_adj": g["human_elo_adj"],
            "ts_last_move": Alphabet.format_timestamp_short(ts_end),
            "days": int(days),
            "hours": int(hours),
            "minutes": int(minutes),
            "duration": Game.get_duration_from_prefs(prefs),
            "manual": Game.manual_wordcheck_from_prefs(prefs)
        })
    return result


def _opponent_waiting(user_id, opp_id):
    """ Return True if the given opponent is waiting on this user's challenge """
    return firebase.check_wait(opp_id, user_id)


def _challengelist():
    """ Return a list of challenges issued or received by the current user """

    result = []
    cuid = User.current_id()

    def is_timed(prefs):
        """ Return True if the challenge is for a timed game """
        if prefs is None:
            return False
        return prefs.get("duration", 0) > 0

    def opp_ready(c):
        """ Returns True if this is a timed challenge and the opponent is ready to play """
        if not is_timed(c[1]):
            return False
        # Timed challenge: see if there is a Firebase path indicating
        # that the opponent is waiting for this user
        return _opponent_waiting(cuid, c[0])

    if cuid is not None:

        # List received challenges
        received = list(ChallengeModel.list_received(cuid, max_len = 20))
        # List issued challenges
        issued = list(ChallengeModel.list_issued(cuid, max_len = 20))
        # Multi-fetch all opponents involved
        opponents = fetch_users(received + issued, lambda c: c[0])
        # List the received challenges
        for c in received:
            u = opponents[c[0]] # User.load(c[0]) # User id
            nick = u.nickname()
            result.append({
                "received": True,
                "userid": c[0],
                "opp": nick,
                "fullname": u.full_name(),
                "prefs": c[1],
                "ts": Alphabet.format_timestamp_short(c[2]),
                "opp_ready" : False
            })
        # List the issued challenges
        for c in issued:
            u = opponents[c[0]] # User.load(c[0]) # User id
            nick = u.nickname()
            result.append({
                "received": False,
                "userid": c[0],
                "opp": nick,
                "fullname": u.full_name(),
                "prefs": c[1],
                "ts": Alphabet.format_timestamp_short(c[2]),
                "opp_ready" : opp_ready(c)
            })
    return result


@app.route("/_ah/start")
def start():
    """ App Engine is starting a fresh instance - warm it up by loading word database """

    wdb = Wordbase.dawg()
    ok = u"upphitun" in wdb # Use a random word to check ('upphitun' means warm-up)
    logging.info(u"Start/warmup, instance {0}, ok is {1}".format(
        os.environ.get("INSTANCE_ID", ""), ok))
    return "", 200 # jsonify(ok = ok)


@app.route("/_ah/stop")
def stop():
    """ App Engine is stopping an instance """
    return "", 200


@app.route("/_ah/warmup")
def warmup():
    """ App Engine is starting a fresh instance - warm it up by loading word database """
    return start()


@app.route("/submitmove", methods=['POST'])
def submitmove():
    """ Handle a move that is being submitted from the client """

    if not User.current_id():
        return jsonify(result = Error.LOGIN_REQUIRED)

    # This URL should only receive Ajax POSTs from the client
    rq = RequestData(request)
    movelist = rq.get_list("moves")
    movecount = rq.get_int("mcount")
    uuid = rq.get("uuid")

    game = None if uuid is None else Game.load(uuid, use_cache = False)

    if game is None:
        return jsonify(result = Error.GAME_NOT_FOUND)

    # Make sure the client is in sync with the server:
    # check the move count
    if movecount != game.num_moves():
        return jsonify(result = Error.OUT_OF_SYNC)

    if game.player_id_to_move() != User.current_id():
        return jsonify(result = Error.WRONG_USER)

    # Process the movestring
    # Try twice in case of timeout or other exception
    result = None
    for attempt in reversed(range(2)):
        try:
            result = _process_move(game, movelist)
        except DeadlineExceededError:
            logging.info("Deadline exceeded in submitmove()")
            result = jsonify(result = Error.SERVER_ERROR)
            # No use attempting to retry if deadline exceeded: get out
            break
        except Exception as e:
            logging.info("Exception in submitmove(): {0} {1}"
                .format(e, "- retrying" if attempt > 0 else "").encode("latin-1"))
            if attempt == 0:
                # Final attempt failed
                result = jsonify(result = Error.SERVER_ERROR)
        else:
            # No exception: done
            break
    return result


@app.route("/gamestate", methods=['POST'])
def gamestate():
    """ Returns the current state of a game """

    rq = RequestData(request)
    uuid = rq.get("game")

    user_id = User.current_id()
    game = Game.load(uuid) if uuid and user_id else None

    if not user_id or not game:
        # We must have a logged-in user and a valid game
        return jsonify(ok = False)

    player_index = game.player_index(user_id)
    if player_index is None:
        # The current user is not a player in this game
        return jsonify(ok = False)

    return jsonify(ok = True, game = game.client_state(player_index, deep = True))


@app.route("/forceresign", methods=['POST'])
def forceresign():
    """ Forces a tardy user to resign, if the game is overdue """

    user_id = User.current_id()
    if user_id is None:
        # We must have a logged-in user
        return jsonify(result = Error.LOGIN_REQUIRED)

    rq = RequestData(request)
    uuid = rq.get("game")
    movecount = rq.get_int("mcount", -1)

    game = None if uuid is None else Game.load(uuid, use_cache = False)

    if game is None:
        return jsonify(result = Error.GAME_NOT_FOUND)

    # Only the user who is the opponent of the tardy user can force a resign
    if game.player_id(1 - game.player_to_move()) != User.current_id():
        return jsonify(result = Error.WRONG_USER)

    # Make sure the client is in sync with the server:
    # check the move count
    if movecount != game.num_moves():
        return jsonify(result = Error.OUT_OF_SYNC)

    if not game.is_overdue():
        return jsonify(result = Error.GAME_NOT_OVERDUE)

    # Send in a resign move on behalf of the opponent
    return _process_move(game, [u"rsgn"])


@app.route("/wordcheck", methods=['POST'])
def wordcheck():
    """ Check a list of words for validity """

    if not User.current_id():
        # If no user is logged in, we always return False
        return jsonify(ok = False)

    rq = RequestData(request)
    words = rq.get_list("words")
    word = rq["word"]

    # Check the words against the dictionary
    wdb = Wordbase.dawg()
    ok = all([w in wdb for w in words])
    return jsonify(word = word, ok = ok)


@app.route("/gamestats", methods=['POST'])
def gamestats():
    """ Calculate and return statistics on a given finished game """

    rq = RequestData(request)
    uuid = rq.get('game')
    game = None

    if uuid is not None:
        game = Game.load(uuid)
        # Check whether the game is still in progress
        if (game is not None) and not game.is_over():
            # Don't allow looking at the stats in this case
            game = None

    if game is None:
        return jsonify(result = Error.GAME_NOT_FOUND)

    return jsonify(game.statistics())


@app.route("/userstats", methods=['POST'])
def userstats():
    """ Calculate and return statistics on a given user """

    cid = User.current_id()
    if not cid:
        return jsonify(result = Error.LOGIN_REQUIRED)

    rq = RequestData(request)
    uid = rq.get('user', cid) # Current user is implicit
    user = None

    if uid is not None:
        user = User.load(uid)

    if user is None:
        return jsonify(result = Error.WRONG_USER)

    cuser = User.current()
    stats = user.statistics()

    # Include info on whether this user is a favorite of the current user
    fav = False
    if uid != cuser.id():
        fav = cuser.has_favorite(uid)
    stats["favorite"] = fav

    # Include info on whether the current user has challenged this user
    chall = False
    if uid != cuser.id():
        chall = cuser.has_challenge(uid)
    stats["challenge"] = chall

    return jsonify(stats)


@app.route("/userlist", methods=['POST'])
def userlist():
    """ Return user lists with particular criteria """

    if not User.current_id():
        return jsonify(result = Error.LOGIN_REQUIRED)

    rq = RequestData(request)
    query = rq.get('query')
    spec = rq.get('spec')

    # Disable the in-context cache to save memory
    # (it doesn't give any speed advantage for user lists anyway)
    Context.disable_cache()

    return jsonify(result = Error.LEGAL, spec = spec, userlist = _userlist(query, spec))


@app.route("/gamelist", methods=['POST'])
def gamelist():
    """ Return a list of active games for the current user """

    # Specify "zombies":false to omit zombie games from the returned list
    rq = RequestData(request)
    include_zombies = rq.get_bool('zombies', True)
    # _gamelist() returns an empty list if no user is logged in
    cuid = User.current_id()
    return jsonify(result = Error.LEGAL,
        gamelist = _gamelist(cuid, include_zombies))


@app.route("/rating", methods=['POST'])
def rating():
    """ Return the newest Elo ratings table (top 100) of a given kind ('all' or 'human') """

    if not User.current_id():
        return jsonify(result = Error.LOGIN_REQUIRED)

    rq = RequestData(request)
    kind = rq.get('kind', 'all')

    return jsonify(result = Error.LEGAL, rating = _rating(kind))


@app.route("/recentlist", methods=['POST'])
def recentlist():
    """ Return a list of recently completed games for the indicated user """

    rq = RequestData(request)
    user_id = rq.get('user')
    versus = rq.get('versus')
    count = rq.get_int("count", 14) # Default number of recent games to return

    # Limit count to 50 games
    if count > 50:
        count = 50
    elif count < 1:
        count = 1

    if user_id is None:
        user_id = User.current_id()

    # _recentlist() returns an empty list for a nonexistent user

    return jsonify(result = Error.LEGAL,
        recentlist = _recentlist(user_id, versus = versus, max_len = count))


@app.route("/challengelist", methods=['POST'])
def challengelist():
    """ Return a list of challenges issued or received by the current user """
    # _challengelist() returns an empty list if no user is logged in
    return jsonify(result = Error.LEGAL, challengelist = _challengelist())


@app.route("/favorite", methods=['POST'])
def favorite():
    """ Create or delete an A-favors-B relation """

    user = User.current()
    if user is None:
        # We must have a logged-in user
        return jsonify(result = Error.LOGIN_REQUIRED)

    rq = RequestData(request)
    destuser = rq.get('destuser')
    action = rq.get('action', u"add")

    if destuser is not None:
        if action == u"add":
            user.add_favorite(destuser)
        elif action == u"delete":
            user.del_favorite(destuser)

    return jsonify(result = Error.LEGAL)


@app.route("/challenge", methods=['POST'])
def challenge():
    """ Create or delete an A-challenges-B relation """

    user = User.current()
    if user is None:
        # We must have a logged-in user
        return jsonify(result = Error.LOGIN_REQUIRED)

    rq = RequestData(request)
    destuser = rq.get('destuser')
    if not destuser:
        return jsonify(result = Error.WRONG_USER)
    action = rq.get('action', u"issue")
    duration = rq.get_int("duration")
    fairplay = rq.get_bool('fairplay')
    newbag = rq.get_bool('newbag')
    manual = rq.get_bool('manual')

    # Ensure that the duration is reasonable
    if duration < 0:
        duration = 0
    elif duration > 90:
        duration = 90

    if action == u"issue":
        user.issue_challenge(destuser,
            { "duration": duration, "fairplay": fairplay,
                "newbag": newbag, "manual": manual })
    elif action == u"retract":
        user.retract_challenge(destuser)
    elif action == u"decline":
        # Decline challenge previously made by the destuser (really srcuser)
        user.decline_challenge(destuser)
    elif action == u"accept":
        # Accept a challenge previously made by the destuser (really srcuser)
        user.accept_challenge(destuser)
    # Notify the destination user via a
    # Firebase notification to /user/[user_id]/challenge
    # main.html listens to this
    firebase.send_update("user", destuser, "challenge")

    return jsonify(result = Error.LEGAL)


@app.route("/setuserpref", methods=['POST'])
def setuserpref():
    """ Set a user preference """

    user = User.current()
    if user is None:
        # We must have a logged-in user
        return jsonify(result = Error.LOGIN_REQUIRED)

    rq = RequestData(request)

    # Check for the beginner preference and convert it to bool if we can
    beginner = rq.get_bool('beginner', None)
    # Setting a new state for the beginner preference
    if beginner is not None:
        user.set_beginner(beginner)

    # Check for the ready state and convert it to bool if we can
    ready = rq.get_bool('ready', None)
    # Setting a new state for the ready preference
    if ready is not None:
        user.set_ready(ready)

    # Check for the ready_timed state and convert it to bool if we can
    ready_timed = rq.get_bool('ready_timed', None)
    # Setting a new state for the ready_timed preference
    if ready_timed is not None:
        user.set_ready_timed(ready_timed)

    user.update()

    return jsonify(result = Error.LEGAL)


@app.route("/onlinecheck", methods=['POST'])
def onlinecheck():
    """ Check whether a particular user is online """

    if not User.current_id():
        # We must have a logged-in user
        return jsonify(online = False)

    rq = RequestData(request)
    user_id = rq.get('user')
    online = False
    if user_id is not None:
        online = firebase.check_presence(user_id)
    return jsonify(online = online)


@app.route("/waitcheck", methods=['POST'])
def waitcheck():
    """ Check whether a particular opponent is waiting on a challenge """

    if not User.current_id():
        # We must have a logged-in user
        return jsonify(waiting = False)

    rq = RequestData(request)
    opp_id = rq.get('user')
    waiting = False
    if opp_id is not None:
        waiting = _opponent_waiting(User.current_id(), opp_id)
    return jsonify(userid = opp_id, waiting = waiting)


@app.route("/cancelwait", methods=['POST'])
def cancelwait():
    """ A wait on a challenge has been cancelled """

    if not User.current_id():
        # We must have a logged-in user
        return jsonify(ok = False)

    rq = RequestData(request)
    user_id = rq.get('user')
    opp_id = rq.get('opp')

    if not user_id or not opp_id:
        return jsonify(ok = False)

    # Delete the current wait and force update of the opponent's challenge list
    msg = {
        "user/" + user_id + "/wait/" + opp_id : None,
        "user/" + opp_id : { "challenge" : datetime.utcnow().isoformat() }
    }
    firebase.send_message(msg)

    return jsonify(ok = True)


@app.route("/chatmsg", methods=['POST'])
def chatmsg():
    """ Send a chat message on a conversation channel """

    rq = RequestData(request)
    channel = rq["channel"]
    msg = rq["msg"]

    user_id = User.current_id()
    if not user_id or not channel:
        # We must have a logged-in user and a valid channel
        return jsonify(ok = False)

    game = None
    if channel.startswith(u"game:"):
        # Send notifications to both players on the game channel
        uuid = channel[5:][:36] # The game id
        if uuid:
            game = Game.load(uuid)

    if game is None or not game.has_player(user_id):
        # The logged-in user must be a player in the game
        return jsonify(ok = False)

    # Add a message entity to the data store and remember its timestamp
    ts = ChatModel.add_msg(channel, user_id, msg)

    if msg:
        # No need to send empty messages, which are to be interpreted
        # as read confirmations
        # The message to be sent in JSON form via Firebase
        md = dict(from_userid = user_id, msg = msg, ts = Alphabet.format_timestamp(ts))
        msg = { }
        for p in range(0, 2):
            # Send a Firebase notification to /game/[gameid]/[userid]/chat
            msg["game/" + uuid + "/" + game.player_id(p) + "/chat"] = md
        firebase.send_message(msg)

    return jsonify(ok = True)


@app.route("/chatload", methods=['POST'])
def chatload():
    """ Load all chat messages on a conversation channel """

    rq = RequestData(request)
    channel = rq["channel"]

    user_id = User.current_id()
    if not user_id or not channel:
        # We must have a logged-in user and a valid channel
        return jsonify(ok = False)

    game = None
    if channel.startswith(u"game:"):
        uuid = channel[5:][:36] # The game id
        if uuid:
            game = Game.load(uuid)

    if game is None or not game.has_player(user_id):
        # The logged-in user must be a player in the game
        return jsonify(ok = False)

    # Return the messages sorted in ascending timestamp order.
    # ChatModel.list_conversations returns them in descending
    # order since its maxlen limit cuts off the oldest messages.
    messages = [
        dict(
            from_userid = cm["user"],
            msg = cm["msg"],
            ts = Alphabet.format_timestamp(cm["ts"])
        )
        for cm in sorted(ChatModel.list_conversation(channel), key=lambda x: x["ts"])
    ]

    return jsonify(ok = True, messages = messages)


@app.route("/review")
def review():
    """ Show game review page """

    # Only logged-in users who are paying friends can view this page
    user = User.current()
    if user is None:
        # User hasn't logged in yet: redirect to login page
        return redirect(url_for('login'))

    if not user.has_paid():
        # Only paying users can see game reviews
        return redirect(url_for('friend', action = 1))

    game = None
    uuid = request.args.get("game", None)

    if uuid is not None:
        # Attempt to load the game whose id is in the URL query string
        game = Game.load(uuid)

    if game is None or not game.is_over():
        # The game is not found: abort
        return redirect(url_for("main"))

    try:
        move_number = int(request.args.get("move", "0"))
    except:
        move_number = 0

    if move_number > game.num_moves():
        move_number = game.num_moves()
    elif move_number < 0:
        move_number = 0

    state = game.state_after_move(move_number if move_number == 0 else move_number - 1)

    best_moves = None
    if game.allows_best_moves():

        # Serialize access to the following section
        with _autoplayer_lock:

            # Show best moves if available and it is proper to do so (i.e. the game is finished)
            apl = AutoPlayer(state)
            best_moves = apl.generate_best_moves(19) # 19 is what fits on screen

    player_index = state.player_to_move()
    if game.has_player(user.id()):
        # Look at the game from the point of view of this player
        user_index = game.player_index(user.id())
    else:
        # This is an outside spectator: look at it from the point of view of
        # player 0, or the human player if player 0 is an autoplayer
        user_index = 1 if game.is_autoplayer(0) else 0

    return render_template("review.html",
        game = game, state = state,
        player_index = player_index, user_index = user_index,
        move_number = move_number, best_moves = best_moves)


class UserForm:
    """ Encapsulates the data in the user preferences form """

    def __init__(self, usr = None):
        self.logout_url = User.logout_url()
        if usr:
            self.init_from_user(usr)
        else:
            self.nickname = u''
            self.full_name = u''
            self.email = u''
            self.audio = True
            self.fanfare = True
            self.beginner = True
            self.fairplay = False # Defaults to False, must be explicitly set to True
            self.newbag = False # Defaults to False, must be explicitly set to True
            self.friend = False

    def init_from_form(self, form):
        """ The form has been submitted after editing: retrieve the entered data """
        try:
            self.nickname = u'' + form['nickname'].strip()
        except:
            pass
        try:
            self.full_name = u'' + form['full_name'].strip()
        except:
            pass
        try:
            self.email = u'' + form['email'].strip()
        except:
            pass
        try:
            self.audio = 'audio' in form # State of the checkbox
            self.fanfare = 'fanfare' in form
            self.beginner = 'beginner' in form
            self.fairplay = 'fairplay' in form
            self.newbag = 'newbag' in form
        except:
            pass

    def init_from_dict(self, d):
        """ The form has been submitted after editing: retrieve the entered data """
        try:
            self.nickname = u'' + d.get("nickname", "").strip()
        except:
            pass
        try:
            self.full_name = u'' + d.get("full_name", "").strip()
        except:
            pass
        try:
            self.email = u'' + d.get("email", "").strip()
        except:
            pass
        try:
            self.audio = bool(d.get("audio", False))
            self.fanfare = bool(d.get("fanfare", False))
            self.beginner = bool(d.get("beginner", False))
            self.fairplay = bool(d.get("fairplay", False))
            self.newbag = bool(d.get("newbag", False))
        except:
            pass

    def init_from_user(self, usr):
        """ Load the data to be edited upon initial display of the form """
        self.nickname = usr.nickname()
        self.full_name = usr.full_name()
        self.email = usr.email()
        self.audio = usr.audio()
        self.fanfare = usr.fanfare()
        self.beginner = usr.beginner()
        self.fairplay = usr.fairplay()
        self.newbag = usr.new_bag()
        self.friend = usr.friend()

    def validate(self):
        """ Check the current form data for validity and return a dict of errors, if any """
        errors = dict()
        if not self.nickname:
            errors['nickname'] = u"Notandi verður að hafa einkenni"
        elif (self.nickname[0] not in Alphabet.full_order) and (self.nickname[0] not in Alphabet.full_upper):
            errors['nickname'] = u"Einkenni verður að byrja á bókstaf"
        elif len(self.nickname) > 15:
            errors['nickname'] = u"Einkenni má ekki vera lengra en 15 stafir"
        elif u'"' in self.nickname:
            errors['nickname'] = u"Einkenni má ekki innihalda gæsalappir"
        if u'"' in self.full_name:
            errors['full_name'] = u"Nafn má ekki innihalda gæsalappir"
        if self.email and u'@' not in self.email:
            errors['email'] = u"Tölvupóstfang verður að innihalda @-merki"
        return errors

    def store(self, usr):
        """ Store validated form data back into the user entity """
        usr.set_nickname(self.nickname)
        usr.set_full_name(self.full_name)
        usr.set_email(self.email)
        usr.set_audio(self.audio)
        usr.set_fanfare(self.fanfare)
        usr.set_beginner(self.beginner)
        usr.set_fairplay(self.fairplay)
        usr.set_new_bag(self.newbag)
        usr.update()

    def as_dict(self):
        """ Return the user preferences as a dictionary """
        return self.__dict__


@app.route("/userprefs", methods=['GET', 'POST'])
def userprefs():
    """ Handler for the user preferences page """

    user = User.current()
    if user is None:
        # User hasn't logged in yet: redirect to login page
        return redirect(users.create_login_url(url_for("userprefs")))

    uf = UserForm()
    err = dict()

    # The URL to go back to, if not main.html
    from_url = request.args.get("from", None)

    if request.method == 'GET':
        # Entering the form for the first time: load the user data
        uf.init_from_user(user)
    elif request.method == 'POST':
        # Attempting to submit modified data: retrieve it and validate
        uf.init_from_form(request.form)
        err = uf.validate()
        if not err:
            # All is fine: store the data back in the user entity
            uf.store(user)
            return redirect(from_url or url_for("main"))

    # Render the form with the current data and error messages, if any
    return render_template("userprefs.html", uf = uf, err = err, from_url = from_url)


@app.route("/loaduserprefs", methods=['POST'])
def loaduserprefs():
    """ Fetch the preferences of the current user in JSON form """

    user = User.current()
    if user is None:
        # User hasn't logged in
        return jsonify(ok = False)

    # Return the user preferences in JSON form
    uf = UserForm(user)
    return jsonify(ok = True, userprefs = uf.as_dict())


@app.route("/saveuserprefs", methods=['POST'])
def saveuserprefs():
    """ Fetch the preferences of the current user in JSON form """

    user = User.current()
    if user is None:
        # User hasn't logged in
        return jsonify(ok = False)

    j = request.get_json(silent=True)

    # Return the user preferences in JSON form
    uf = UserForm()
    uf.init_from_dict(j)
    err = uf.validate()
    if not err:
        uf.store(user)
        return jsonify(ok = True)
    return jsonify(ok = False, err = err)


@app.route("/wait")
def wait():
    """ Show page to wait for a timed game to start """

    user = User.current()
    if user is None:
        # User hasn't logged in yet: redirect to login page
        return redirect(url_for('login'))

    # Get the opponent id
    opp = request.args.get("opp", None)
    if opp is None or opp.startswith(u"robot-"):
        return redirect(url_for("main", tab = "2")) # Go directly to opponents tab

    # Find the challenge being accepted
    found, prefs = user.find_challenge(opp)
    if not found:
        # No challenge existed between the users: redirect to main page
        return redirect(url_for("main"))

    opp_user = User.load(opp)
    if opp_user is None:
        # Opponent id not found
        return redirect(url_for("main"))

    # Notify the opponent of a change in the challenge list
    # via a Firebase notification to /user/[user_id]/challenge
    msg = {
        "user/" + opp : { "challenge" : datetime.utcnow().isoformat() },
        "user/" + user.id() + "/wait/" + opp : True
    }
    firebase.send_message(msg)

    # Create a Firebase token for the logged-0in user
    # to enable refreshing of the client page when
    # the user state changes (game moves made, challenges
    # issued or accepted, etc.)
    firebase_token = firebase.create_custom_token(user.id())

    # Go to the wait page
    return render_template("wait.html",
        user = user, opp = opp_user, prefs = prefs,
        firebase_token = firebase_token)


@app.route("/newgame")
def newgame():
    """ Show page to initiate a new game """

    user = User.current()
    if user is None:
        # User hasn't logged in yet: redirect to login page
        return redirect(url_for('login'))

    # Get the opponent id
    opp = request.args.get("opp", None)

    # Is this a reverse action, i.e. the challenger initiating a timed game,
    # instead of the challenged player initiating a normal one?
    rev = request.args.get("rev", None) is not None

    if opp is None:
        return redirect(url_for("main", tab = "2")) # Go directly to opponents tab

    if opp.startswith(u"robot-"):
        # Start a new game against an autoplayer (robot)
        robot_level = int(opp[6:])
        # Play the game with the new bag if the user prefers it
        prefs = { "newbag" : True } if user.new_bag() else None
        game = Game.new(user.id(), None, robot_level, prefs = prefs)
        return redirect(url_for("board", game = game.id()))

    # Start a new game between two human users
    if rev:
        # Timed game: load the opponent
        opp_user = User.load(opp)
        if opp_user is None:
            return redirect(url_for("main"))
        # In this case, the opponent accepts the challenge
        found, prefs = opp_user.accept_challenge(user.id())
    else:
        # The current user accepts the challenge
        found, prefs = user.accept_challenge(opp)

    if not found:
        # No challenge existed between the users: redirect to main page
        return redirect(url_for("main"))

    # Create a fresh game object
    game = Game.new(user.id(), opp, 0, prefs)

    # Notify the opponent's main.html that there is a new game
    # !!! board.html eventually needs to listen to this as well
    msg = {
        "user/" + opp + "/move" : datetime.utcnow().isoformat()
    }

    # If this is a timed game, notify the waiting party
    if prefs and prefs.get("duration", 0) > 0:
        msg["user/" + opp + "/wait/" + user.id()] = { "game" : game.id() }

    firebase.send_message(msg)

    # Go to the game page
    return redirect(url_for("board", game = game.id()))


@app.route("/board")
def board():
    """ The main game page """

    uuid = request.args.get("game", None)
    zombie = request.args.get("zombie", None) # Requesting a look at a newly finished game
    try:
        # If the og argument is present, it indicates that OpenGraph data
        # should be included in the page header, from the point of view of
        # the player that the argument represents (i.e. og=0 or og=1).
        # If og=-1, OpenGraph data should be included but from a neutral
        # (third party) point of view.
        og = request.args.get("og", None)
        if og is not None:
            # This should be a player index: -1 (third party), 0 or 1
            og = int(og) # May throw an exception
            if og < -1:
                og = -1
            elif og > 1:
                og = 1
    except:
        og = None

    game = None
    if uuid:
        # Attempt to load the game whose id is in the URL query string
        game = Game.load(uuid, use_cache = False)

    if game is None:
        # No active game to display: go back to main screen
        return redirect(url_for("main"))

    user = User.current()
    is_over = game.is_over()
    opp = None # The opponent

    if not is_over:
        # Game still in progress
        if user is None:
            # User hasn't logged in yet: redirect to login page
            return redirect(url_for('login'))
        if not game.has_player(user.id()):
            # This user is not a party to the game: redirect to main page
            return redirect(url_for("main"))

    # user can be None if the game is over - we do not require a login in that case
    player_index = None if user is None else game.player_index(user.id())

    # If a logged-in user is looking at the board, we create a Firebase
    # token in order to maintain presence info
    firebase_token = None if user is None else firebase.create_custom_token(user.id())

    if player_index is not None and not game.is_autoplayer(1 - player_index):
        # Load information about the opponent
        opp = User.load(game.player_id(1 - player_index))

    if zombie and player_index is not None:
        # This is a newly finished game that is now being viewed by clicking
        # on it from a zombie list: remove it from the list
        ZombieModel.del_game(game.id(), user.id())

    ogd = None # OpenGraph data
    if og is not None and is_over:
        # This game is a valid and visible OpenGraph object
        # Calculate the OpenGraph stuff to be included in the page header
        pix = 0 if og < 0 else og # Player indexing
        sc = game.final_scores()
        winner = game.winning_player() # -1 if draw
        bingoes = game.bingoes()
        ogd = dict(
            og = og,
            player0 = game.player_nickname(pix),
            player1 = game.player_nickname(1 - pix),
            winner = winner,
            win = False if og == -1 else (og == winner),
            draw = (winner == -1),
            score0 = str(sc[pix]),
            score1 = str(sc[1 - pix]),
            bingo0 = bingoes[pix],
            bingo1 = bingoes[1 - pix]
        )

    # Delete the Firebase subtree for this game,
    # to get earlier move and chat notifications out of the way
    if firebase_token is not None:
        msg = {
            "game/" + game.id() + "/" + user.id() : None,
            "user/" + user.id() + "/wait" : None
        }
        firebase.send_message(msg)
        # No need to clear other stuff on the /user/[user_id]/ path,
        # since we're not listening to it in board.html

    return render_template("board.html",
        game = game, user = user, opp = opp,
        player_index = player_index, zombie = bool(zombie),
        time_info = game.time_info(), og = ogd, # OpenGraph data
        firebase_token = firebase_token)


@app.route("/gameover", methods=['POST'])
def gameover():
    """ A player has seen a game finish: remove it from the zombie list, if it is there """

    cuid = User.current_id()
    if not cuid:
        # We must have a logged-in user
        return jsonify(result = Error.LOGIN_REQUIRED)

    rq = RequestData(request)
    game_id = rq.get('game')
    user_id = rq.get('player')

    if not game_id or cuid != user_id:
        # A user can only remove her own games from the zombie list
        return jsonify(result = Error.GAME_NOT_FOUND)

    ZombieModel.del_game(game_id, user_id)

    return jsonify(result = Error.LEGAL)


@app.route("/friend")
def friend():
    """ Page for users to register or unregister themselves as friends of Netskrafl """
    user = User.current()
    if user is None:
        return redirect(url_for("login"))
    try:
        action = int(request.args.get("action", "0"))
    except:
        action =  0
    if action == 0:
        # Launch the actual payment procedure
        # render_template displays a thank-you note in this case
        pass
    elif action == 1:
        # Display a friendship promotion
        pass
    elif action == 2:
        # Request to cancel a friendship
        if not user.friend():
            # Not a friend: nothing to cancel
            return redirect(url_for("main"))
    elif action == 3:
        # Actually cancel a friendship
        if not user.friend():
            # Not a friend: nothing to cancel
            return redirect(url_for("main"))
        billing.cancel_friend(user)

    return render_template("friend.html", user = user, action = action)


@app.route("/promo", methods=['POST'])
def promo():
    """ Return promotional HTML corresponding to a given key (category) """
    user = User.current()
    if user is None:
        return redirect(url_for("login"))
    rq = RequestData(request)
    key = rq.get("key", "")
    VALID_PROMOS = { "friend", "krafla" }
    if key not in VALID_PROMOS:
        key = "error"
    return render_template("promo-" + key + ".html", user = user)


@app.route("/signup", methods=['GET'])
def signup():
    """ Sign up as a friend, enter card info, etc. """
    user = User.current()
    if user is None:
        return redirect(url_for("login"))
    return render_template("signup.html", user = user)


@app.route("/skilmalar", methods=['GET'])
def skilmalar():
    """ Conditions """
    user = User.current()
    if user is None:
        return redirect(url_for("login"))
    return render_template("skilmalar.html", user = user)


@app.route("/billing", methods=['GET', 'POST'])
def handle_billing():
    """ Receive signup and billing confirmations """
    return billing.handle(request)


@app.route("/")
def main():
    """ Handler for the main (index) page """

    user = User.current()
    if user is None:
        # User hasn't logged in yet: redirect to login page
        return redirect(url_for('login'))

    # Initial tab to show, if any
    tab = request.args.get("tab", None)

    uid = user.id()

    # Create a Firebase token for the logged-0in user
    # to enable refreshing of the client page when
    # the user state changes (game moves made, challenges
    # issued or accepted, etc.)
    firebase_token = firebase.create_custom_token(uid)

    # Promotion display logic
    promo = None
    if random.randint(1, _PROMO_FREQUENCY) == 1:
        # Once every N times, check whether this user may be due for
        # a promotion display

        # promo = 'krafla' # Un-comment this to enable promo

        # The list_promotions call yields a list of timestamps
        if promo:
            promos = sorted(list(PromoModel.list_promotions(uid, promo)))
            now = datetime.utcnow()
            if len(promos) >= _PROMO_COUNT:
                # Already seen too many of these
                promo = None
            elif promos and (now - promos[-1] < _PROMO_INTERVAL):
                # Less than one interval since last promo was displayed: don't display this one
                promo = None

    if promo:
        # Note the fact that we have displayed this promotion to this user
        logging.info("Displaying promo {1} to user {0} who has already seen it {2} times"
            .format(uid, promo, len(promos)))
        PromoModel.add_promotion(uid, promo)

    # Get earlier challenge, move and wait notifications out of the way
    msg = {
        "challenge" : None,
        "move" : None,
        "wait" : None
    }
    firebase.send_message(msg, "user", uid)

    return render_template("main.html",
        user = user, tab = tab,
        firebase_token = firebase_token,
        promo = promo)


@app.route("/login")
def login():
    """ Handler for the login & greeting page """
    login_url = users.create_login_url("/")
    return render_template("login.html", login_url = login_url)


@app.route("/help")
def help():
    """ Show help page """
    user = User.current()
    # We tolerate a null (not logged in) user here
    return render_template("nshelp.html", user = user, tab = None)


@app.route("/rawhelp")
def rawhelp():
    """ Return raw help page HTML """

    def override_url_for(endpoint, **values):
        """ Convert URLs from old-format plain ones to single-page fancy ones """
        if endpoint == 'twoletter':
            return "/page#!/help?tab=2"
        if endpoint == 'newbag':
            return "/page#!/help?tab=3"
        if endpoint == 'userprefs':
            # Insert special token that will be caught by client-side
            # code and converted to a dialog invocation in the single-page UI
            return "$$userprefs$$"
        return url_for(endpoint, **values)

    return render_template("rawhelp.html", url_for = override_url_for)


@app.route("/twoletter")
def twoletter():
    """ Show help page """
    user = User.current()
    # We tolerate a null (not logged in) user here
    return render_template("nshelp.html", user = user, tab = "twoletter")


@app.route("/faq")
def faq():
    """ Show help page """
    user = User.current()
    # We tolerate a null (not logged in) user here
    return render_template("nshelp.html", user = user, tab = "faq")


@app.route("/page")
def page():
    """ Show single-page UI test """
    user = User.current()
    if user is None:
        # User hasn't logged in yet: redirect to login page
        return redirect(url_for('login'))
    # If a logged-in user is looking at the board, we create a Firebase
    # token in order to maintain presence info
    firebase_token = "" if user is None else firebase.create_custom_token(user.id())
    return render_template("page.html",
        user = user, firebase_token = firebase_token)


@app.route("/newbag")
def newbag():
    """ Show help page """
    user = User.current()
    # We tolerate a null (not logged in) user here
    return render_template("nshelp.html", user = user, tab = "newbag")


# noinspection PyUnusedLocal
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
