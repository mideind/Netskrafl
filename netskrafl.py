# -*- coding: utf-8 -*-

""" Web server for netskrafl.appspot.com

    Author: Vilhjalmur Thorsteinsson, 2014

    This web server module uses the Flask framework to implement
    a crossword game similar to SCRABBLE(tm).

    The actual game logic is found in skraflplayer.py and
    skraflmechanics.py. The web client code is found in netskrafl.js

    The server is compatible with Python 2.7 and 3.x, CPython and PyPy.
    (To get it to run under PyPy 2.7.6 the author had to patch
    \pypy\lib-python\2.7\mimetypes.py to fix a bug that was not
    present in the CPython 2.7 distribution of the same file.)

    Note: SCRABBLE is a registered trademark. This software or its author
    are in no way affiliated with or endorsed by the owners or licensees
    of the SCRABBLE trademark.

"""

import logging
import json

from flask import Flask
from flask import render_template, redirect, jsonify
from flask import request, session, url_for

from google.appengine.api import users

from languages import Alphabet
from skraflmechanics import Move, PassMove, ExchangeMove, ResignMove, Error
from skraflplayer import AutoPlayer
from skraflgame import User, Game
from skrafldb import Unique, UserModel, GameModel, MoveModel,\
    FavoriteModel, ChallengeModel, ChannelModel


# Standard Flask initialization

app = Flask(__name__)
app.config['DEBUG'] = False

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
                game.resign()
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
    if not game.is_over() and opponent is None:
        game.autoplayer_move()

    if game.is_over():
        # If the game is now over, tally the final score
        game.state.finalize_score()

    # Make sure the new game state is persistently recorded
    game.store()

    # Notify the opponent, if he has one or more active channels
    if opponent is not None:
        # Human opponent
        ChannelModel.send_message(u"user", opponent, u'{ "kind": "game" }')
        # Send a game update to the opponent channel, if any, including
        # the full client state
        ChannelModel.send_message(u"game", game.id() + u":" + str(1 - player_index),
            json.dumps(game.client_state(1 - player_index, m)))

    # Return a state update to the client (board, rack, score, movelist, etc.)
    return jsonify(game.client_state(player_index))


def _userlist(range_from, range_to):
    """ Return a list of users matching the filter criteria """
    result = []
    cuser = User.current()
    cuid = None if cuser is None else cuser.id()
    if range_from == u"fav" and not range_to:
        # Return favorites of the current user
        if cuid is not None:
            i = iter(FavoriteModel.list_favorites(cuid, max_len = 50))
            for favid in i:
                fu = User.load(favid)
                result.append({
                    "userid": favid,
                    "nick": fu.nickname(),
                    "fullname": fu.full_name(),
                    "fav": True,
                    "chall": False if cuser is None else cuser.has_challenge(favid)
                })
    elif range_from == u"robots" and not range_to:
        # Return the list of available autoplayers
        for r in Game.AUTOPLAYERS:
            result.append({
                "userid": u"robot-" + str(r[2]),
                "nick": r[0],
                "fullname": r[1],
                "fav": False,
                "chall": False
            })
    else:
        # Return users within a particular nickname range
        i = iter(UserModel.list(range_from, range_to, max_len = 50))
        for uid in i:
            if uid == cuid:
                # Do not include the current user, if any, in the list
                continue
            u = User.load(uid)
            result.append({
                "userid": uid,
                "nick": u.nickname(),
                "fullname": u.full_name(),
                "fav": False if cuser is None else cuser.has_favorite(uid),
                "chall": False if cuser is None else cuser.has_challenge(uid)
            })
    return result


def _gamelist():
    """ Return a list of active games for the current user """
    result = []
    cuid = User.current_id()
    if cuid is not None:
        # Obtain up to 50 live games where this user is a player
        i = list(GameModel.list_live_games(cuid, max_len = 50))
        # Sort in reverse order by timestamp of last move,
        # i.e. games with newest moves first
        i.sort(key = lambda x: x["ts"], reverse = True)
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


def _recentlist():
    """ Return a list of recent games for the current user """
    result = []
    cuid = User.current_id()
    if cuid is not None:
        # Obtain a list of recently finished games where this user was a player
        i = iter(GameModel.list_finished_games(cuid, max_len = 14))
        for g in i:
            opp = g["opp"]
            if opp is None:
                # Autoplayer opponent
                nick = Game.autoplayer_name(g["robot_level"])
            else:
                # Human opponent
                u = User.load(opp)
                nick = u.nickname()
            result.append({
                "url": url_for('review', game = g["uuid"]),
                "opp": nick,
                "opp_is_robot": opp is None,
                "sc0": g["sc0"],
                "sc1": g["sc1"],
                "ts": Alphabet.format_timestamp(g["ts"])
            })
    return result


def _challengelist():
    """ Return a list of challenges issued or received by the current user """
    result = []
    cuid = User.current_id()
    if cuid is not None:

        def preftext(pd):
            # Translate the challenge preferences to a descriptive text
            # !!! TBD
            return u"Venjuleg ótímabundin viðureign"

        # List received challenges
        i = iter(ChallengeModel.list_received(cuid, max_len = 20))
        for c in i:
            u = User.load(c[0]) # User id
            nick = u.nickname()
            prefs = preftext(c[1])
            result.append({
                "received": True,
                "userid": c[0],
                "opp": nick,
                "prefs": prefs,
                "ts": Alphabet.format_timestamp(c[2])
            })
        # List issued challenges
        i = iter(ChallengeModel.list_issued(cuid, max_len = 20))
        for c in i:
            u = User.load(c[0]) # User id
            nick = u.nickname()
            prefs = preftext(c[1])
            result.append({
                "received": False,
                "userid": c[0],
                "opp": nick,
                "prefs": prefs,
                "ts": Alphabet.format_timestamp(c[2])
            })
    return result


@app.route("/_ah/warmup")
def warmup():
    """ App Engine is starting a fresh instance - warm it up by loading word database """

    wdb = Game.manager.word_db()
    ok = u"upphitun" in wdb # Use a random word to check ('upphitun' means warm-up)
    logging.info(u"Warmup, ok is {0}".format(ok).encode("latin-1"))
    return jsonify(ok = ok)


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
    wdb = Game.manager.word_db()
    ok = all([w in wdb for w in words])
    return jsonify(word = word, ok = ok)


@app.route("/gamestats", methods=['POST'])
def gamestats():
    """ Calculate and return statistics on the current game """

    cuid = User.current_id()
    if not cuid:
        # We must have a logged-in user
        return jsonify(result = Error.LOGIN_REQUIRED)

    uuid = request.form.get('game', None)
    if uuid is not None:
        game = Game.load(uuid)
        # Check whether the user was a player in this game
        if not game.has_player(cuid):
            # Nope: don't allow looking at the stats
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
    """ Return a list of recently completed games for the current user """

    # _recentlist() returns an empty list if no user is logged in

    return jsonify(result = Error.LEGAL, recentlist = _recentlist())


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

    if destuser is not None:
        if action == u"issue":
            user.issue_challenge(destuser, { }) # !!! No preference parameters yet
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


@app.route("/review")
def review():
    """ Show game review page """

    user = User.current()
    if user is None:
        # User hasn't logged in yet: redirect to login page
        return redirect(users.create_login_url(url_for("review")))

    game = None
    uuid = request.args.get("game", None)

    if uuid is not None:
        # Attempt to load the game whose id is in the URL query string
        game = Game.load(uuid)

    if game is None or not game.is_over() or not game.has_player(user.id()):
        # The game is not found or the current user did not play it: abort
        return redirect(url_for("main"))

    move_number = int(request.args.get("move", "0"))
    if move_number > game.num_moves():
        move_number = game.num_moves()
    state = game.state_after_move(move_number if move_number == 0 else move_number - 1)

    best_moves = None
    if game.allows_best_moves():
        # Show best moves if available and it is proper to do so (i.e. the game is finished)
        apl = AutoPlayer(state)
        best_moves = apl.generate_best_moves(20)

    player_index = state.player_to_move()
    user_index = game.player_index(user.id())

    return render_template("review.html",
        user = user, game = game, state = state,
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


@app.route("/newgame")
def newgame():
    """ Show page to initiate a new game """

    user = User.current()
    if user is None:
        # User hasn't logged in yet: redirect to login page
        return redirect(users.create_login_url("/"))

    # Get the opponent id
    opp = request.args.get("opp", None)
    if opp is None:
        return redirect(url_for("main"))

    if opp[0:6] == u"robot-":
        # Start a new game against an autoplayer (robot)
        robot_level = int(opp[6:])
        game = Game.new(user.id(), None, robot_level)
        return redirect(url_for("board", game = game.id()))

    # Start a new game between two human users
    found, prefs = user.accept_challenge(opp)
    if not found:
        # No challenge existed between the users: redirect to main page
        return redirect(url_for("main"))

    # Create a fresh game object
    game = Game.new(user.id(), opp, 0, prefs)

    # Notify the opponent that there is a new game
    ChannelModel.send_message(u"user", opp, u'{ "kind": "game" }')

    # Go to the game page
    return redirect(url_for("board", game = game.id()))


@app.route("/board")
def board():
    """ The main game page """

    user = User.current()
    if user is None:
        # User hasn't logged in yet: redirect to login page
        return redirect(users.create_login_url("/"))

    uuid = request.args.get("game", None)
    game = None

    if uuid is not None:
        # Attempt to load the game whose id is in the URL query string
        game = Game.load(uuid)

    if game is not None and (game.is_over() or not game.has_player(user.id())):
        # Go back to main screen if game is no longer active
        game = None

    if game is None:
        # No active game to display: go back to main screen
        return redirect(url_for("main"))

    player_index = game.player_index(user.id())

    if game.is_autoplayer(1 - player_index):
        # No need for a channel if the opponent is an autoplayer
        channel_token = None
    else:
        # Create a Google App Engine Channel API token
        # to enable refreshing of the board when the
        # opponent makes a move
        channel_token = ChannelModel.create_new(u"game", game.id() + u":" + str(player_index))

    return render_template("board.html", game = game, user = user,
        player_index = player_index, channel_token = channel_token)


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
        if uuid == user.id():
            # Create a Google App Engine Channel API token
            # for user notification
            channel_token = ChannelModel.create_new(u"user", uuid)
    else:
        # Game channel request
        # Attempt to load the game whose id is in the URL query string
        game = Game.load(uuid)

        if game is not None and (game.is_over() or not game.has_player(user.id())):
            game = None

        if game is None:
            # No associated game: return error
            return jsonify(result = Error.WRONG_USER)

        player_index = game.player_index(user.id())

        if game.is_autoplayer(1 - player_index):
            # No need for a channel if the opponent is an autoplayer
            return jsonify(result = Error.WRONG_USER)

        # Create a Google App Engine Channel API token
        # to enable refreshing of the board when the
        # opponent makes a move
        channel_token = ChannelModel.create_new(u"game", game.id() + u":" + str(player_index))

    return jsonify(result = Error.LEGAL, token = channel_token)


@app.route("/")
def main():
    """ Handler for the main (index) page """

    user = User.current()
    if user is None:
        # User hasn't logged in yet: redirect to login page
        return redirect(users.create_login_url("/"))

    # Create a Google App Engine Channel API token
    # to enable refreshing of the client page when
    # the user state changes (game moves made, challenges
    # issued or accepted, etc.)
    channel_token = ChannelModel.create_new(u"user", user.id())

    return render_template("main.html", user = user,
        channel_token = channel_token)


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
