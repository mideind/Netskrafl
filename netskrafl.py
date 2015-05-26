# -*- coding: utf-8 -*-

""" Web server for netskrafl.appspot.com

    Author: Vilhjalmur Thorsteinsson, 2014

    This web server module uses the Flask framework to implement
    a crossword game similar to SCRABBLE(tm).

    The actual game logic is found in skraflplayer.py and
    skraflmechanics.py.

    The User and Game classes are found in skraflgame.py.

    The web client code is found in netskrafl.js.

    The server is compatible with Python 2.7 and 3.x, CPython and PyPy.
    (To get it to run under PyPy 2.7.6 the author had to patch
    \pypy\lib-python\2.7\mimetypes.py to fix a bug that was not
    present in the CPython 2.7 distribution of the same file.)

    Note: SCRABBLE is a registered trademark. This software or its author
    are in no way affiliated with or endorsed by the owners or licensees
    of the SCRABBLE trademark.

"""

import os
import logging
import json
import threading
import re

from datetime import datetime, timedelta

from flask import Flask
from flask import render_template, redirect, jsonify
from flask import request, session, url_for

from google.appengine.api import users, memcache

from languages import Alphabet
from dawgdictionary import Wordbase
from skraflmechanics import Move, PassMove, ExchangeMove, ResignMove, Error
from skraflplayer import AutoPlayer
from skraflgame import User, Game
from skrafldb import Context, Unique, UserModel, GameModel, MoveModel,\
    FavoriteModel, ChallengeModel, ChannelModel, RatingModel, ChatModel,\
    ZombieModel


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
                # Pass move
                m = PassMove()
                break
            if mstr[0:5] == u"exch=":
                # Exchange move
                m = ExchangeMove(mstr[5:])
                break
            if mstr == u"rsgn":
                # Resign from game, forfeiting all points
                m = ResignMove(game.state.scores()[game.state.player_to_move()])
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
            # print(u"Cover: row {0} col {1}".format(row, col))
            m.add_cover(row, col, tile, letter)
    except Exception as e:
        logging.info(u"Exception in _process_move(): {0}".format(e).encode("latin-1"))
        m = None

    # Process the move string here
    # Unpack the error code and message
    err = game.state.check_legality(m)
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

        if not is_over and opponent is None:
            game.autoplayer_move()
            is_over = game.is_over() # State may change during autoplayer_move()

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

    # Notify the opponent, if he is not a robot and has one or more active channels
    if opponent is not None:
        # Send a game update to the opponent channel, if any, including
        # the full client state. board.html listens to this.
        ChannelModel.send_message(u"game", game.id() + u":" + str(1 - player_index),
            json.dumps(game.client_state(1 - player_index, m)))
        # Notify the opponent that it's his turn to move. main.html listens to this.
        # !!! TODO: Figure out a way to have board.html listen to these
        # !!! notifications as well, since we now have a gamelist there
        ChannelModel.send_message(u"user", opponent, u'{ "kind": "game" }')

    # Return a state update to the client (board, rack, score, movelist, etc.)
    return jsonify(game.client_state(player_index))


def _userlist(range_from, range_to):
    """ Return a list of users matching the filter criteria """
    result = []
    cuser = User.current()
    cuid = None if cuser is None else cuser.id()

    if range_from == u"robots" and not range_to:
        # Return the list of available autoplayers
        for r in Game.AUTOPLAYERS:
            result.append({
                "userid": u"robot-" + str(r[2]),
                "nick": r[0],
                "fullname": r[1],
                "fav": False,
                "chall": False,
                "fairplay": False, # The robots don't play fair ;-)
                "ready": True, # The robots are always ready for a challenge
                "ready_timed": False # Timed games are not available for robots
            })
        # That's it; we're done (no sorting required)
        return result

    # We will be returning a list of human players

    # Generate a list of challenges issued by this user
    challenges = set()
    if cuid:
        challenges.update([ch[0] # Identifier of challenged user
            for ch in iter(ChallengeModel.list_issued(cuid, max_len = 20))])

    # Get the list of online users

    # Start by looking in the cache
    online = memcache.get("live", namespace="userlist")
    if online is None:
        # Not found: do a query
        online = set(iter(ChannelModel.list_connected())) # Eliminate duplicates by using a set
        # Store the result in the cache with a lifetime of 2 minutes
        memcache.set("live", online, time=2 * 60, namespace="userlist")

    if range_from == u"live" and not range_to:
        # Return all online (live) users

        for uid in online:
            if uid == cuid:
                # Do not include the current user, if any, in the list
                continue
            lu = User.load(uid)
            if lu and lu.is_displayable():
                chall = uid in challenges
                result.append({
                    "userid": uid,
                    "nick": lu.nickname(),
                    "fullname": lu.full_name(),
                    "fav": False if cuser is None else cuser.has_favorite(uid),
                    "chall": chall,
                    "fairplay": lu.fairplay(),
                    "ready": lu.is_ready() and not chall,
                    "ready_timed": lu.is_ready_timed() and not chall
                })

    elif range_from == u"fav" and not range_to:
        # Return favorites of the current user
        if cuid is not None:
            i = iter(FavoriteModel.list_favorites(cuid))
            for favid in i:
                fu = User.load(favid)
                if fu and fu.is_displayable():
                    chall = favid in challenges
                    result.append({
                        "userid": favid,
                        "nick": fu.nickname(),
                        "fullname": fu.full_name(),
                        "fav": True,
                        "chall": chall,
                        "fairplay": fu.fairplay(),
                        "ready": fu.is_ready() and favid in online and not chall,
                        "ready_timed": fu.is_ready_timed() and favid in online and not chall
                    })

    else:
        # Return users within a particular nickname range

        # The "N:" prefix is a version header
        cache_range = "2:" + ("" if range_from is None else range_from) + \
            "-" + ("" if range_to is None else range_to)

        # Start by looking in the cache
        i = memcache.get(cache_range, namespace="userlist")
        if i is None:
            # Not found: do an unlimited query
            i = list(UserModel.list(range_from, range_to, max_len = 0))
            # Store the result in the cache with a lifetime of 5 minutes
            memcache.set(cache_range, i, time=5 * 60, namespace="userlist")

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
                    "fav": False if cuser is None else cuser.has_favorite(uid),
                    "chall": chall,
                    "fairplay": User.fairplay_from_prefs(ud["prefs"]),
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


def _gamelist():
    """ Return a list of active and zombie games for the current user """
    result = []
    cuid = User.current_id()
    if not cuid:
        return result
    now = datetime.utcnow()
    # Place zombie games (recently finished games that this player
    # has not seen) at the top of the list
    for g in ZombieModel.list_games(cuid):
        opp = g["opp"] # User id of opponent
        u = User.load(opp)
        nick = u.nickname()
        result.append({
            "uuid": g["uuid"],
            "url": url_for('board', game = g["uuid"], zombie = "1"), # Mark zombie state
            "oppid": opp,
            "opp": nick,
            "fullname": u.full_name(),
            "sc0": g["sc0"],
            "sc1": g["sc1"],
            "ts": Alphabet.format_timestamp(g["ts"]),
            "my_turn": False,
            "overdue": False,
            "zombie": True,
            "fairplay": u.fairplay(),
            "tile_count" : Alphabet.BAG_SIZE # All tiles accounted for
        })
    # Sort zombies in decreasing order by last move, i.e. most recently completed games first
    result.sort(key = lambda x: x["ts"], reverse = True)
    # Obtain up to 50 live games where this user is a player
    i = list(GameModel.list_live_games(cuid, max_len = 50))
    # Sort in reverse order by turn and then by timestamp of the last move,
    # i.e. games with newest moves first
    i.sort(key = lambda x: (x["my_turn"], x["ts"]), reverse = True)
    # Iterate through the game list
    for g in i:
        opp = g["opp"] # User id of opponent
        ts = g["ts"]
        overdue = False
        fairplay = False
        fullname = ""
        if opp is None:
            # Autoplayer opponent
            nick = Game.autoplayer_name(g["robot_level"])
        else:
            # Human opponent
            u = User.load(opp)
            nick = u.nickname()
            fullname = u.full_name()
            fairplay = u.fairplay()
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
            "ts": Alphabet.format_timestamp(ts),
            "my_turn": g["my_turn"],
            "overdue": overdue,
            "zombie": False,
            "fairplay": fairplay,
            "tile_count" : g["tile_count"]
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
        is_robot = False
        usr = None
        inactive = False
        if uid.startswith(u"robot-"):
            is_robot = True
            nick = Game.autoplayer_name(int(uid[6:]))
            fullname = nick
            chall = False
            fairplay = False
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
    temp = list(GameModel.list_finished_games(cuid, versus = versus, max_len = max_len))
    # Temp may be up to 2 * max_len as it is composed of two queries
    # Sort it and bring it down to size before processing it further
    temp.sort(key = lambda x: x["ts_last_move"], reverse = True)
    for g in temp[0:max_len]:
        opp = g["opp"]
        if opp is None:
            # Autoplayer opponent
            nick = Game.autoplayer_name(g["robot_level"])
        else:
            # Human opponent
            u = User.load(opp)
            nick = u.nickname()

        # Calculate the duration of the game in days, hours, minutes
        ts_start = g["ts"]
        ts_end = g["ts_last_move"]

        if (ts_start is None) or (ts_end is None):
            days, hours, minutes = (0, 0, 0)
        else:
            td = ts_end - ts_start # Timedelta
            tsec = td.total_seconds()
            days, tsec = divmod(tsec, 24 * 60 * 60)
            hours, tsec = divmod(tsec, 60 * 60)
            minutes, tsec = divmod(tsec, 60) # Ignore the remaining seconds

        result.append({
            "url": url_for('board', game = g["uuid"]), # Was 'review'
            "opp": nick,
            "opp_is_robot": opp is None,
            "sc0": g["sc0"],
            "sc1": g["sc1"],
            "elo_adj": g["elo_adj"],
            "human_elo_adj": g["human_elo_adj"],
            "ts_last_move": Alphabet.format_timestamp(ts_end),
            "days": int(days),
            "hours": int(hours),
            "minutes": int(minutes),
            "duration": Game.get_duration_from_prefs(g["prefs"])
        })
    return result


def _opponent_waiting(user_id, opp_id):
    """ Return True if the given opponent is waiting on this user's challenge """
    return ChannelModel.exists(u"wait", user_id, opp_id)


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
        # Timed challenge: see if there is a valid wait channel connection
        # where the opponent is waiting for this user
        return _opponent_waiting(cuid, c[0])

    if cuid is not None:

        # List received challenges
        i = iter(ChallengeModel.list_received(cuid, max_len = 20))
        for c in i:
            u = User.load(c[0]) # User id
            nick = u.nickname()
            result.append({
                "received": True,
                "userid": c[0],
                "opp": nick,
                "fullname": u.full_name(),
                "prefs": c[1],
                "ts": Alphabet.format_timestamp(c[2]),
                "opp_ready" : False
            })
        # List issued challenges
        i = iter(ChallengeModel.list_issued(cuid, max_len = 20))
        for c in i:
            u = User.load(c[0]) # User id
            nick = u.nickname()
            result.append({
                "received": False,
                "userid": c[0],
                "opp": nick,
                "fullname": u.full_name(),
                "prefs": c[1],
                "ts": Alphabet.format_timestamp(c[2]),
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
    return jsonify(ok = ok)


@app.route("/_ah/warmup")
def warmup():
    """ App Engine is starting a fresh instance - warm it up by loading word database """
    return start()


@app.route("/_ah/channel/connected/", methods=['POST'])
def channel_connected():
    """ A client channel has been connected """
    chid = request.form.get('from', None)
    # logging.info(u"Channel connect from id {0}".format(chid).encode('latin-1'))
    # Mark the entity as being connected
    ChannelModel.connect(chid)
    return jsonify(ok = True)


@app.route("/_ah/channel/disconnected/", methods=['POST'])
def channel_disconnected():
    """ A client channel has been disconnected """

    chid = request.form.get('from', None)
    # logging.info(u"Channel disconnect from id {0}".format(chid).encode('latin-1'))
    # Mark the entity as being disconnected
    ChannelModel.disconnect(chid)
    return jsonify(ok = True)


@app.route("/submitmove", methods=['POST'])
def submitmove():
    """ Handle a move that is being submitted from the client """

    if User.current_id() is None:
        return jsonify(result = Error.LOGIN_REQUIRED)

    movelist = []
    movecount = 0
    uuid = None
    if request.method == 'POST':
        # This URL should only receive Ajax POSTs from the client
        try:
            # The new move (as a list of covers)
            movelist = request.form.getlist('moves[]')
            # The client's move count, to verify synchronization
            movecount = int(request.form.get('mcount', 0))
            # The game's UUID
            uuid = request.form.get('uuid', None)
        except:
            pass

    game = None if uuid is None else Game.load(uuid)

    if game is None:
        return jsonify(result = Error.GAME_NOT_FOUND)

    # Make sure the client is in sync with the server:
    # check the move count
    if movecount != game.num_moves():
        return jsonify(result = Error.OUT_OF_SYNC)

    if game.player_id_to_move() != User.current_id():
        return jsonify(result = Error.WRONG_USER)

    # Process the movestring
    return _process_move(game, movelist)


@app.route("/forceresign", methods=['POST'])
def forceresign():
    """ Forces a tardy user to resign, if the game is overdue """

    user_id = User.current_id()
    if user_id is None:
        # We must have a logged-in user
        return jsonify(result = Error.LOGIN_REQUIRED)

    uuid = request.form.get('game', None)

    game = None if uuid is None else Game.load(uuid)

    if game is None:
        return jsonify(result = Error.GAME_NOT_FOUND)

    # Only the user who is the opponent of the tardy user can force a resign
    if game.player_id(1 - game.player_to_move()) != User.current_id():
        return jsonify(result = Error.WRONG_USER)

    try:
        movecount = int(request.form.get('mcount', "0"))
    except:
        movecount = -1

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

    words = []
    word = u""
    if request.method == 'POST':
        # This URL should only receive Ajax POSTs from the client
        try:
            # The words to check
            words = request.form.getlist('words[]')
            # The original word laid down (used as a sync token)
            word = request.form.get('word', u"")
        except:
            pass

    if not User.current_id():
        # If no user is logged in, we always return False
        return jsonify(word = word, ok = False)

    # Check the words against the dictionary
    wdb = Wordbase.dawg()
    ok = all([w in wdb for w in words])
    return jsonify(word = word, ok = ok)


@app.route("/gamestats", methods=['POST'])
def gamestats():
    """ Calculate and return statistics on a given finished game """

    uuid = request.form.get('game', None)
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

    uid = request.form.get('user', cid) # Current user is implicit
    user = None

    if uid is not None:
        user = User.load(uid)

    if user is None:
        return jsonify(result = Error.WRONG_USER)

    stats = user.statistics()
    # Include info on whether this user is a favorite of the current user
    fav = False
    cuser = User.current()
    if uid != cuser.id():
        fav = cuser.has_favorite(uid)
    stats["favorite"] = fav

    return jsonify(stats)


@app.route("/userlist", methods=['POST'])
def userlist():
    """ Return user lists with particular criteria """

    if not User.current_id():
        return jsonify(result = Error.LOGIN_REQUIRED)

    range_from = request.form.get('from', None)
    range_to = request.form.get('to', None)

    # Disable the in-context cache to save memory
    # (it doesn't give any speed advantage for user lists anyway)
    Context.disable_cache()

    return jsonify(result = Error.LEGAL, userlist = _userlist(range_from, range_to))


@app.route("/gamelist", methods=['POST'])
def gamelist():
    """ Return a list of active games for the current user """

    # _gamelist() returns an empty list if no user is logged in

    return jsonify(result = Error.LEGAL, gamelist = _gamelist())


@app.route("/rating", methods=['POST'])
def rating():
    """ Return the newest Elo ratings table (top 100) of a given kind ('all' or 'human') """

    if not User.current_id():
        return jsonify(result = Error.LOGIN_REQUIRED)

    kind = request.form.get('kind', 'all')

    return jsonify(result = Error.LEGAL, rating = _rating(kind))


@app.route("/recentlist", methods=['POST'])
def recentlist():
    """ Return a list of recently completed games for the indicated user """

    # _recentlist() returns an empty list for a nonexistent user

    user_id = request.form.get('user', None)
    versus = request.form.get('versus', None)
    count = 14 # Default number of recent games to return
    try:
        count = int(request.form.get('count', str(count)))
    except:
        pass

    # Limit count to 50 games
    if count > 50:
        count = 50
    elif count < 1:
        count = 1

    if user_id is None:
        user_id = User.current_id()

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

    destuser = request.form.get('destuser', None)
    action = request.form.get('action', u"add")

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

    destuser = request.form.get('destuser', None)
    action = request.form.get('action', u"issue")
    duration = 0
    try:
        duration = int(request.form.get('duration', "0"))
    except:
        pass
    fairplay = False
    try:
        fp = request.form.get('fairplay', None)
        fairplay = True if fp is not None and fp == u"true" else False
    except:
        fairplay = False

    # Ensure that the duration is reasonable
    if duration < 0:
        duration = 0
    elif duration > 90:
        duration = 90

    if destuser is not None:
        if action == u"issue":
            user.issue_challenge(destuser, { "duration" : duration, "fairplay" : fairplay })
        elif action == u"retract":
            user.retract_challenge(destuser)
        elif action == u"decline":
            # Decline challenge previously made by the destuser (really srcuser)
            user.decline_challenge(destuser)
        elif action == u"accept":
            # Accept a challenge previously made by the destuser (really srcuser)
            user.accept_challenge(destuser)
        # Notify the destination user, if he has one or more active channels
        ChannelModel.send_message(u"user", destuser, u'{ "kind": "challenge" }');

    return jsonify(result = Error.LEGAL)


@app.route("/setuserpref", methods=['POST'])
def setuserpref():
    """ Set a user preference """

    user = User.current()
    if user is None:
        # We must have a logged-in user
        return jsonify(result = Error.LOGIN_REQUIRED)

    # Check for the beginner preference and convert it to bool if we can
    beginner = request.form.get('beginner', None)
    if beginner is not None:
        if beginner == u"false":
            beginner = False
        elif beginner == u"true":
            beginner = True

    if beginner is not None and isinstance(beginner, bool):
        # Setting a new state for the beginner preference
        user.set_beginner(beginner)

    # Check for the ready state and convert it to bool if we can
    ready = request.form.get('ready', None)
    if ready is not None:
        if ready == u"false":
            ready = False
        elif ready == u"true":
            ready = True

    if ready is not None and isinstance(ready, bool):
        # Setting a new state for the ready preference
        user.set_ready(ready)

    # Check for the ready_timed state and convert it to bool if we can
    ready_timed = request.form.get('ready_timed', None)
    if ready_timed is not None:
        if ready_timed == u"false":
            ready_timed = False
        elif ready_timed == u"true":
            ready_timed = True

    if ready_timed is not None and isinstance(ready_timed, bool):
        # Setting a new state for the ready_timed preference
        user.set_ready_timed(ready_timed)

    user.update()

    return jsonify(result = Error.LEGAL)


@app.route("/onlinecheck", methods=['POST'])
def onlinecheck():
    """ Check whether a particular user is online """

    if not User.current_id():
        # We must have a logged-in user
        return jsonify(online = False)

    user_id = request.form.get('user', None)
    online = False

    if user_id is not None:
        online = ChannelModel.is_connected(user_id)

    return jsonify(online = online)


@app.route("/waitcheck", methods=['POST'])
def waitcheck():
    """ Check whether a particular opponent is waiting on a challenge """

    if not User.current_id():
        # We must have a logged-in user
        return jsonify(waiting = False)

    opp_id = request.form.get('user', None)
    waiting = False

    if opp_id is not None:
        waiting = _opponent_waiting(User.current_id(), opp_id)

    return jsonify(userid = opp_id, waiting = waiting)


@app.route("/chatmsg", methods=['POST'])
def chatmsg():
    """ Send a chat message on a conversation channel """

    channel = request.form.get('channel', u"")
    msg = request.form.get('msg', u"")

    if not User.current_id() or not channel:
        # We must have a logged-in user and a valid channel
        return jsonify(ok = False)

    # Add a message entity to the data store and remember its timestamp
    ts = ChatModel.add_msg(channel, User.current_id(), msg)

    if channel.startswith(u"game:") and msg:
        # Send notifications to both players on the game channel
        # No need to send empty messages, which are to be interpreted
        # as read confirmations
        uuid = channel[5:] # The game id
        # The message to be sent in JSON form on the channel
        md = dict(from_userid = User.current_id(), msg = msg, ts = Alphabet.format_timestamp(ts))
        for p in range(0, 2):
            ChannelModel.send_message(u"game",
                uuid + u":" + str(p),
                json.dumps(md)
            )

    return jsonify(ok = True)


@app.route("/chatload", methods=['POST'])
def chatload():
    """ Load all chat messages on a conversation channel """

    if not User.current_id():
        # We must have a logged-in user
        return jsonify(ok = False)

    channel = request.form.get('channel', u"")
    messages = []

    if channel:
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

    # This page does not require - and should not require - a logged-in user

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
    user = User.current()
    if user and game.has_player(user.id()):
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


@app.route("/userprefs", methods=['GET', 'POST'])
def userprefs():
    """ Handler for the user preferences page """

    user = User.current()
    if user is None:
        # User hasn't logged in yet: redirect to login page
        return redirect(users.create_login_url(url_for("userprefs")))

    class UserForm:
        """ Encapsulates the data in the user preferences form """

        def __init__(self):
            self.full_name = u''
            self.nickname = u''
            self.email = u''
            self.audio = True
            self.fanfare = True
            self.beginner = True
            self.fairplay = False # Defaults to False, must be explicitly set to True
            self.logout_url = User.logout_url()

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
            usr.update()

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


@app.route("/wait")
def wait():
    """ Show page to wait for a timed game to start """

    user = User.current()
    if user is None:
        # User hasn't logged in yet: redirect to login page
        return redirect(url_for('login'))

    # Get the opponent id
    opp = request.args.get("opp", None)
    if opp is None:
        return redirect(url_for("main", tab = "2")) # Go directly to opponents tab

    if opp[0:6] == u"robot-":
        # Start a new game against an autoplayer (robot)
        robot_level = int(opp[6:])
        game = Game.new(user.id(), None, robot_level)
        return redirect(url_for("board", game = game.id()))

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
    ChannelModel.send_message(u"user", opp, u'{ "kind": "challenge" }')

    # Create a Google App Engine Channel API token
    # to enable notification when the original challenger
    # is ready and we can start the game. The channel has
    # a short lifetime to reduce the risk of false positives.
    channel_token = ChannelModel.create_new(u"wait", opp, user.id(),
        timedelta(minutes = 1))

    # Go to the wait page
    return render_template("wait.html", user = user, opp = opp_user,
        prefs = prefs, channel_token = channel_token)


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

    if opp[0:6] == u"robot-":
        # Start a new game against an autoplayer (robot)
        robot_level = int(opp[6:])
        game = Game.new(user.id(), None, robot_level)
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
    ChannelModel.send_message(u"user", opp, u'{ "kind": "game" }')

    # If this is a timed game, notify the waiting party
    if prefs and prefs.get("duration", 0) > 0:
        ChannelModel.send_message(u"wait", user.id(), u'{ "kind": "ready", "game": "' + game.id() + u'" }')

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

    # Create a Google App Engine Channel API token
    # to enable refreshing of the board when the
    # opponent makes a move. We do this even if the
    # opponent is an autoplayer as we do want the
    # presence detection functionality for the human
    # user.
    channel_token = None
    if player_index is not None and not game.is_autoplayer(1 - player_index):
        # If one of the players is looking at the game, we create a channel
        # even if the game is over - as the players can continue chatting
        # in that case.
        channel_token = ChannelModel.create_new(u"game",
            game.id() + u":" + str(player_index), user.id())
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

    return render_template("board.html",
        game = game, user = user, opp = opp,
        player_index = player_index, zombie = bool(zombie),
        time_info = game.time_info(), og = ogd, # OpenGraph data
        channel_token = channel_token)


@app.route("/gameover", methods=['POST'])
def gameover():
    """ A player has seen a game finish: remove it from the zombie list, if it is there """

    cuid = User.current_id()
    if not cuid:
        # We must have a logged-in user
        return jsonify(result = Error.LOGIN_REQUIRED)

    game_id = request.form.get('game', None)
    user_id = request.form.get('player', None)

    if not game_id or cuid != user_id:
        # A user can only remove her own games from the zombie list
        return jsonify(result = Error.GAME_NOT_FOUND)

    ZombieModel.del_game(game_id, user_id)

    return jsonify(result = Error.LEGAL)


@app.route("/newchannel", methods=['POST'])
def newchannel():
    """ Issue a new channel token for an expired client session """

    user = User.current()
    if user is None:
        # No user: no channel token
        return jsonify(result = Error.LOGIN_REQUIRED)

    channel_token = None
    uuid = request.form.get("game", None)

    if uuid is None:
        # This is probably a user channel request
        uuid = request.form.get("user", None)
        if uuid == None:
            uuid = request.form.get("wait", None)
            if uuid is not None:
                # logging.info(u"Renewing channel token for wait channel with opponent id {0}".format(uuid))
                channel_token = ChannelModel.create_new(u"wait", uuid,
                    user.id(), timedelta(minutes = 1))

        elif uuid == user.id():
            # Create a Google App Engine Channel API token
            # for user notification
            channel_token = ChannelModel.create_new(u"user", uuid, uuid)
        if channel_token is None:
            # logging.info(u"newchannel() returning Error.WRONG_USER")
            return jsonify(result = Error.WRONG_USER)

    else:
        # Game channel request
        # Attempt to load the game whose id is in the URL query string
        game = Game.load(uuid)

        if game is not None:
            # !!! Strictly speaking the users may continue to chat after
            # the game is over, so the game.is_over() check below may
            # be too stringent
            if game.is_over() or not game.has_player(user.id()):
                game = None

        if game is None:
            # No associated game: return error
            # logging.info(u"newchannel() returning Error.WRONG_USER")
            return jsonify(result = Error.WRONG_USER)

        player_index = game.player_index(user.id())

        # Create a Google App Engine Channel API token
        # to enable refreshing of the board when the
        # opponent makes a move
        channel_token = ChannelModel.create_new(u"game",
            game.id() + u":" + str(player_index), user.id())

    return jsonify(result = Error.LEGAL, token = channel_token)


@app.route("/")
def main():
    """ Handler for the main (index) page """

    user = User.current()
    if user is None:
        # User hasn't logged in yet: redirect to login page
        return redirect(url_for('login'))

    # Initial tab to show, if any
    tab = request.args.get("tab", None)

    # Create a Google App Engine Channel API token
    # to enable refreshing of the client page when
    # the user state changes (game moves made, challenges
    # issued or accepted, etc.)
    channel_token = ChannelModel.create_new(u"user", user.id(), user.id())

    return render_template("main.html", user = user,
        channel_token = channel_token, tab = tab)


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

    return render_template("nshelp.html", user = user,
        show_twoletter = False, show_faq = False)


@app.route("/twoletter")
def twoletter():
    """ Show help page """

    user = User.current()
    # We tolerate a null (not logged in) user here

    return render_template("nshelp.html", user = user,
        show_twoletter = True, show_faq = False)


@app.route("/faq")
def faq():
    """ Show help page """

    user = User.current()
    # We tolerate a null (not logged in) user here

    return render_template("nshelp.html", user = user,
        show_twoletter = False, show_faq = True)


@app.errorhandler(404)
def page_not_found(e):
    """ Return a custom 404 error """
    return u'Þessi vefslóð er ekki rétt', 404


@app.errorhandler(500)
def server_error(e):
    """ Return a custom 500 error """
    return u'Eftirfarandi villa kom upp: {}'.format(e), 500

# Continue to add handlers for the admin web

import admin

# Run a default Flask web server for testing if invoked directly as a main program

if __name__ == "__main__":
    app.run(debug=True)
