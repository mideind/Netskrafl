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

from datetime import timedelta

from flask import Flask
from flask import render_template, redirect, jsonify
from flask import request, session, url_for

from google.appengine.api import users, memcache

from languages import Alphabet
from dawgdictionary import Wordbase
from skraflmechanics import Move, PassMove, ExchangeMove, ResignMove, Error
from skraflplayer import AutoPlayer
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


def _process_move(movecount, movelist, uuid):
    """ Process a move from the client (the local player)
        Returns True if OK or False if the move was illegal
    """

    game = None if uuid is None else Game.load(uuid)

    if game is None:
        return jsonify(result = Error.LOGIN_REQUIRED)

    # Make sure the client is in sync with the server:
    # check the move count
    if movecount != game.num_moves():
        return jsonify(result = Error.OUT_OF_SYNC)

    if game.player_id_to_move() != User.current_id():
        return jsonify(result = Error.WRONG_USER)

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

    # Notify the opponent, if he is not a robot and has one or more active channels
    if opponent is not None:
        # Send a game update to the opponent channel, if any, including
        # the full client state. board.html listens to this.
        ChannelModel.send_message(u"game", game.id() + u":" + str(1 - player_index),
            json.dumps(game.client_state(1 - player_index, m)))
        # Notify the opponent that it's his turn to move. main.html listens to this.
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
                "chall": False
            })
        # That's it; we're done
        return result

    # We will be returning a list of human players

    # Generate a list of challenges issued by this user
    challenges = set()
    if cuid:
        challenges.update([ch[0] # Identifier of challenged user
            for ch in iter(ChallengeModel.list_issued(cuid, max_len = 20))])

    if range_from == u"live" and not range_to:
        # Return all connected (live) users

        # Start by looking in the cache
        i = memcache.get("live", namespace="userlist")
        if i is None:
            # Not found: do a query
            i = set(iter(ChannelModel.list_connected())) # Eliminate duplicates by using a set
            # Store the result in the cache with a lifetime of 1 minute
            memcache.set("live", i, time=60, namespace="userlist")

        for uid in i:
            if uid == cuid:
                # Do not include the current user, if any, in the list
                continue
            lu = User.load(uid)
            if lu and lu.is_displayable():
                result.append({
                    "userid": uid,
                    "nick": lu.nickname(),
                    "fullname": lu.full_name(),
                    "fav": False if cuser is None else cuser.has_favorite(uid),
                    "chall": uid in challenges
                })

    elif range_from == u"fav" and not range_to:
        # Return favorites of the current user
        if cuid is not None:
            i = iter(FavoriteModel.list_favorites(cuid))
            for favid in i:
                fu = User.load(favid)
                if fu and fu.is_displayable():
                    result.append({
                        "userid": favid,
                        "nick": fu.nickname(),
                        "fullname": fu.full_name(),
                        "fav": True,
                        "chall": favid in challenges
                    })

    else:
        # Return users within a particular nickname range
        i = iter(UserModel.list(range_from, range_to, max_len = 200))
        for uid in i:
            if uid == cuid:
                # Do not include the current user, if any, in the list
                continue
            u = User.load(uid)
            if u and u.is_displayable():
                result.append({
                    "userid": uid,
                    "nick": u.nickname(),
                    "fullname": u.full_name(),
                    "fav": False if cuser is None else cuser.has_favorite(uid),
                    "chall": uid in challenges
                })

    # Sort the user list in ascending order by nickname, case-insensitive
    result.sort(key = lambda x: Alphabet.sortkey_nocase(x["nick"]))
    return result


def _gamelist():
    """ Return a list of active games for the current user """
    result = []
    cuid = User.current_id()
    if cuid is not None:
        # Obtain up to 50 live games where this user is a player
        i = list(GameModel.list_live_games(cuid, max_len = 50))
        # Sort in reverse order by turn and then by timestamp of the last move,
        # i.e. games with newest moves first
        i.sort(key = lambda x: (x["my_turn"], x["ts"]), reverse = True)
        # Iterate through the game list
        for g in i:
            opp = g["opp"] # User id of opponent
            if opp is None:
                # Autoplayer opponent
                nick = Game.autoplayer_name(g["robot_level"])
            else:
                # Human opponent
                u = User.load(opp)
                nick = u.nickname()
            result.append({
                "url": url_for('board', game = g["uuid"]),
                "opp": nick,
                "opp_is_robot": opp is None,
                "sc0": g["sc0"],
                "sc1": g["sc1"],
                "ts": Alphabet.format_timestamp(g["ts"]),
                "my_turn": g["my_turn"]
            })
    return result


def _recentlist(cuid, max_len):
    """ Return a list of recent games for the indicated user """
    result = []
    if cuid is not None:
        # Obtain a list of recently finished games where the indicated user was a player
        i = iter(GameModel.list_finished_games(cuid, max_len = max_len))
        for g in i:
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
                "ts_last_move": Alphabet.format_timestamp(g["ts_last_move"]),
                "days": int(days),
                "hours": int(hours),
                "minutes": int(minutes)
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
    # Process the movestring
    return _process_move(movecount, movelist, uuid)


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
        return jsonify(result = Error.LOGIN_REQUIRED) # Strictly speaking: game not found

    return jsonify(game.statistics())


@app.route("/userlist", methods=['POST'])
def userlist():
    """ Return user lists with particular criteria """

    if not User.current_id():
        return jsonify(result = Error.LOGIN_REQUIRED)

    range_from = request.form.get('from', None)
    range_to = request.form.get('to', None)

    return jsonify(result = Error.LEGAL, userlist = _userlist(range_from, range_to))


@app.route("/gamelist", methods=['POST'])
def gamelist():
    """ Return a list of active games for the current user """

    # _gamelist() returns an empty list if no user is logged in

    return jsonify(result = Error.LEGAL, gamelist = _gamelist())


@app.route("/recentlist", methods=['POST'])
def recentlist():
    """ Return a list of recently completed games for the indicated user """

    # _recentlist() returns an empty list for a nonexistent user

    user_id = request.form.get('user', None)
    count = 14 # Default number of recent games to return
    try:
        count = int(request.form.get('count', str(count)))
    except:
        pass
    # Limit count to 50 games
    if count > 50:
        count = 50
    if user_id is None:
        user_id = User.current_id()

    return jsonify(result = Error.LEGAL, recentlist = _recentlist(user_id, max_len = count))


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
        duration = int(request.form.get('duration', 0))
    except:
        pass

    if destuser is not None:
        if action == u"issue":
            user.issue_challenge(destuser, { "duration" : duration })
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

    move_number = int(request.args.get("move", "0"))
    if move_number > game.num_moves():
        move_number = game.num_moves()
    state = game.state_after_move(move_number if move_number == 0 else move_number - 1)

    best_moves = None
    if game.allows_best_moves():
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

        def init_from_user(self, usr):
            """ Load the data to be edited upon initial display of the form """
            self.nickname = usr.nickname()
            self.full_name = usr.full_name()
            self.email = usr.email()

        def validate(self):
            """ Check the current form data for validity and return a dict of errors, if any """
            errors = dict()
            if not self.nickname:
                errors['nickname'] = u"Notandi verður að hafa einkenni"
            elif (self.nickname[0] not in Alphabet.full_order) and (self.nickname[0] not in Alphabet.full_upper):
                errors['nickname'] = u"Einkenni verður að byrja á bókstaf"
            elif len(self.nickname) > 15:
                errors['nickname'] = u"Einkenni má ekki vera lengra en 15 stafir"
            if self.email and u'@' not in self.email:
                errors['email'] = u"Tölvupóstfang verður að innihalda @-merki"
            return errors

        def store(self, usr):
            """ Store validated form data back into the user entity """
            usr.set_nickname(self.nickname)
            usr.set_full_name(self.full_name)
            usr.set_email(self.email)
            usr.update()

    uf = UserForm()
    err = dict()

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
            return redirect(url_for("main"))

    # Render the form with the current data and error messages, if any
    return render_template("userprefs.html", uf = uf, err = err)


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

    # Notify the opponent that there is a new game
    ChannelModel.send_message(u"user", opp, u'{ "kind": "game" }')

    # If this is a timed game, notify the waiting party
    if prefs and prefs.get("duration", 0) > 0:
        ChannelModel.send_message(u"wait", user.id(), u'{ "kind": "ready", "game": "' + game.id() + u'" }')

    # Go to the game page
    return redirect(url_for("board", game = game.id()))


@app.route("/board")
def board():
    """ The main game page """

    user = User.current()
    if user is None:
        # User hasn't logged in yet: redirect to login page
        return redirect(url_for('login'))

    uuid = request.args.get("game", None)
    game = None

    if uuid is not None:
        # Attempt to load the game whose id is in the URL query string
        game = Game.load(uuid)

    is_over = False

    if game is not None:
        is_over = game.is_over()
        if not (is_over or game.has_player(user.id())):
            # Non-players are only allowed to view if the game is over
            game = None

    if game is None:
        # No active game to display: go back to main screen
        return redirect(url_for("main"))

    player_index = game.player_index(user.id()) # May be None

    # Create a Google App Engine Channel API token
    # to enable refreshing of the board when the
    # opponent makes a move. We do this even if the
    # opponent is an autoplayer as we do want the
    # presence detection functionality for the human
    # user.
    if game.is_over():
        channel_token = None
    else:
        assert player_index is not None
        channel_token = ChannelModel.create_new(u"game",
            game.id() + u":" + str(player_index), user.id())

    return render_template("board.html", game = game, user = user,
        player_index = player_index,
        time_info = game.time_info(),
        channel_token = channel_token)


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

    return render_template("nshelp.html", user = user, show_twoletter = False)


@app.route("/twoletter")
def twoletter():
    """ Show help page """

    user = User.current()
    # We tolerate a null (not logged in) user here

    return render_template("nshelp.html", user = user, show_twoletter = True)


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
