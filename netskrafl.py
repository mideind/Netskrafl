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
import time
import collections
import threading

from random import randint
from datetime import datetime

from flask import Flask
from flask import render_template, redirect, jsonify
from flask import request, session, url_for

from google.appengine.api import users, memcache

from skraflmechanics import Manager, State, Board, Rack, Move, PassMove, ExchangeMove, ResignMove, Error
from skraflplayer import AutoPlayer
from languages import Alphabet
from skrafldb import Unique, UserModel, GameModel, MoveModel, FavoriteModel, ChallengeModel


# Standard Flask initialization

app = Flask(__name__)
app.config['DEBUG'] = False

# !!! TODO: Change this to read the secret key from a config file at run-time
app.secret_key = '\x03\\_,i\xfc\xaf=:L\xce\x9b\xc8z\xf8l\x000\x84\x11\xe1\xe6\xb4M'

manager = Manager()


class User:

    """ Information about a human user including nickname and preferences """

    _lock = threading.Lock()

    def __init__(self, uid = None):
        self._nickname = u""
        if uid is None:
            # Obtain information from the currently logged in user
            u = users.get_current_user()
            if u is None:
                self._user_id = None
            else:
                self._user_id = u.user_id()
                self._nickname = u.nickname() # Default
        else:
            self._user_id = uid
        self._inactive = False
        self._preferences = { }

    def _fetch(self):
        """ Fetch the user's record from the database """
        u = UserModel.fetch(self._user_id)
        if u is None:
            # Use the default properties for a newly created user
            UserModel.create(self._user_id, self.nickname()) # This updates the database
            return
        self._nickname = u.nickname
        self._inactive = u.inactive
        self._preferences = u.prefs

    def update(self):
        """ Update the user's record in the database and in the memcache """
        with User._lock:
            UserModel.update(self._user_id, self._nickname, self._inactive, self._preferences)
            memcache.set(self._user_id, self, namespace='user')

    def id(self):
        """ Returns the id (database key) of the user """
        return self._user_id

    def nickname(self):
        """ Returns the human-readable nickname of a user, or userid if a nick is not available """
        return self._nickname or self._user_id

    def set_nickname(self, nickname):
        """ Sets the human-readable nickname of a user """
        self._nickname = nickname

    def get_pref(self, pref):
        """ Retrieve a preference, or None if not found """
        if self._preferences is None:
            return None
        return self._preferences.get(pref)

    def set_pref(self, pref, value):
        """ Set a preference to a value """
        if self._preferences is None:
            self._preferences = { }
        self._preferences[pref] = value

    def full_name(self):
        """ Returns the full name of a user """
        fn = self.get_pref(u"full_name")
        return u"" if fn is None else fn

    def set_full_name(self, full_name):
        """ Sets the full name of a user """
        self.set_pref(u"full_name", full_name)

    def email(self):
        """ Returns the e-mail address of a user """
        em = self.get_pref(u"email")
        return u"" if em is None else em

    def set_email(self, email):
        """ Sets the e-mail address of a user """
        self.set_pref(u"email", email)

    def add_favorite(self, destuser_id):
        """ Add an A-favors-B relation between this user and the destuser """
        FavoriteModel.add_relation(self.id(), destuser_id)

    def del_favorite(self, destuser_id):
        """ Delete an A-favors-B relation between this user and the destuser """
        FavoriteModel.del_relation(self.id(), destuser_id)

    def has_favorite(self, destuser_id):
        """ Returns True if there is an A-favors-B relation between this user and the destuser """
        return FavoriteModel.has_relation(self.id(), destuser_id)

    def has_challenge(self, destuser_id):
        """ Returns True if this user has challenged destuser """
        return ChallengeModel.has_relation(self.id(), destuser_id)

    def issue_challenge(self, destuser_id, prefs):
        """ Issue a challenge to the destuser """
        ChallengeModel.add_relation(self.id(), destuser_id, prefs)

    def retract_challenge(self, destuser_id):
        """ Retract a challenge previously issued to the destuser """
        ChallengeModel.del_relation(self.id(), destuser_id)

    def decline_challenge(self, srcuser_id):
        """ Decline a challenge previously issued by the srcuser """
        ChallengeModel.del_relation(srcuser_id, self.id())

    def accept_challenge(self, srcuser_id):
        """ Decline a challenge previously issued by the srcuser """
        # !!! TBD: Create a new Game between the users
        # Delete the accepted challenge
        ChallengeModel.del_relation(srcuser_id, self.id())

    def logout_url(self):
        return users.create_logout_url("/")

    @classmethod
    def load(cls, uid):
        """ Load a user from persistent storage given his/her user id """
        with User._lock:
            u = memcache.get(uid, namespace='user')
            if u is None:
                u = User(uid)
                u._fetch()
                memcache.add(uid, u, namespace='user')
            return u

    @classmethod
    def current(cls):
        """ Return the currently logged in user """
        with User._lock:
            user = users.get_current_user()
            if user is None:
                return None
            u = memcache.get(user.user_id(), namespace='user')
            if u is not None:
                return u
            # This might be a user that is not yet in the database
            u = cls()
            u._fetch() # Creates a database record if this is a fresh user
            memcache.add(u.id(), u, namespace='user')
            return u

    @classmethod
    def current_id(cls):
        """ Return the id of the currently logged in user """
        user = users.get_current_user()
        return None if user is None else user.user_id()

    @classmethod
    def current_nickname(cls):
        """ Return the nickname of the current user """
        u = cls.current()
        if u is None:
            return None
        return u.nickname()

# Tuple for storing move data within a Game (must be at outermost scope for pickling to work)
MoveTuple = collections.namedtuple("MoveTuple", ["player", "move", "rack", "ts"])

class Game:

    """ A wrapper class for a particular game that is in process
        or completed. Contains inter alia a State instance.
    """

    # The available autoplayers (robots)
    AUTOPLAYERS = [
        (u"Fullsterkur", u"Velur stigahæsta leik í hverri stöðu", 0),
        (u"Miðlungur", u"Velur af handahófi einn af átta stigahæstu leikjum í hverri stöðu", 8),
        (u"Amlóði", u"Velur af handahófi einn af fimmtán stigahæstu leikjum í hverri stöðu", 15)
        ]

    UNDEFINED_NAME = u"[Ónefndur]"

    _lock = threading.Lock()

    def __init__(self, uuid = None):
        # Unique id of the game
        self.uuid = uuid
        # The start time of the game
        self.timestamp = None
        # The user ids of the players (None if autoplayer)
        # Player 0 is the one that begins the game
        self.player_ids = [None, None]
        # The current game state
        self.state = None
        # The ability level of the autoplayer (0 = strongest)
        self.robot_level = 0
        # The last move made by the remote player
        self.last_move = None
        # The timestamp of the last move made in the game
        self.ts_last_move = None
        # Was the game finished by resigning?
        self.resigned = False
        # History of moves in this game so far, as a list of MoveTuple namedtuples
        self.moves = []
        # Initial rack contents
        self.initial_racks = [None, None]

    def _make_new(self, player0_id, player1_id, robot_level = 0):
        """ Initialize a new, fresh game """
        # If either player0_id or player1_id is None, this is a human-vs-autoplayer game
        self.player_ids = [player0_id, player1_id]
        self.state = State(drawtiles = True)
        self.initial_racks[0] = self.state.rack(0)
        self.initial_racks[1] = self.state.rack(1)
        self.robot_level = robot_level
        self.timestamp = self.ts_last_move = datetime.utcnow()

    @classmethod
    def new(cls, player0_id, player1_id, robot_level = 0):
        """ Start and initialize a new game """
        game = cls(Unique.id()) # Assign a new unique id to the game
        if randint(0, 1) == 1:
            # Randomize which player starts the game
            player0_id, player1_id = player1_id, player0_id
        game._make_new(player0_id, player1_id, robot_level)
        # If AutoPlayer is first to move, generate the first move
        if game.player_id_to_move() is None:
            game.autoplayer_move()
        # Store the new game in persistent storage and add to the memcache
        game.store()
        return game

    @classmethod
    def load(cls, uuid):
        """ Load an already existing game from cache or persistent storage """
        with Game._lock:
            return cls._load_locked(uuid)

    @classmethod
    def _load_locked(cls, uuid):
        """ Load an existing game from cache or persistent storage under lock """

        # Try the memcache first
        game = memcache.get(uuid, namespace="game")
        if game is not None:
            return game

        gm = GameModel.fetch(uuid)
        if gm is None:
            # A game with this uuid is not found in the database: give up
            return None

        # Initialize a new Game instance with a pre-existing uuid
        game = cls(uuid)

        game.timestamp = gm.timestamp
        game.ts_last_move = gm.ts_last_move
        if game.ts_last_move is None:
            game.ts_last_move = game.timestamp

        game.state = State(drawtiles = False)

        game.player_ids[0] = None if gm.player0 is None else gm.player0.id()
        game.player_ids[1] = None if gm.player1 is None else gm.player1.id()

        game.robot_level = gm.robot_level

        # Load the initial racks
        game.initial_racks[0] = gm.irack0
        game.initial_racks[1] = gm.irack1

        # Load the current racks
        game.state.set_rack(0, gm.rack0)
        game.state.set_rack(1, gm.rack1)

        # Process the moves
        player = 0
        mx = 0
        for mm in gm.moves:

            mx += 1
            # logging.info(u"Game move {0} tiles '{3}' score is {1}:{2}".format(mx, game.state._scores[0], game.state._scores[1], mm.tiles).encode("latin-1"))

            m = None
            if mm.coord:

                # Normal tile move
                # Decode the coordinate: A15 = horizontal, 15A = vertical
                if mm.coord[0] in Board.ROWIDS:
                    row = Board.ROWIDS.index(mm.coord[0])
                    col = int(mm.coord[1:]) - 1
                    horiz = True
                else:
                    row = Board.ROWIDS.index(mm.coord[-1])
                    col = int(mm.coord[0:-1]) - 1
                    horiz = False
                # The tiles string may contain wildcards followed by their meaning
                # Remove the ? marks to get the "plain" word formed
                if mm.tiles is not None:
                    m = Move(mm.tiles.replace(u'?', u''), row, col, horiz)
                    m.make_covers(game.state.board(), mm.tiles)

            elif mm.tiles[0:4] == u"EXCH":

                # Exchange move
                m = ExchangeMove(mm.tiles[5:])

            elif mm.tiles == u"PASS":

                # Pass move
                m = PassMove()

            elif mm.tiles == u"RSGN":

                # Game resigned
                m = ResignMove(- mm.score)

            assert m is not None
            if m:
                # Do a "shallow apply" of the move, which updates
                # the board and internal state variables but does
                # not modify the bag or the racks
                game.state.apply_move(m, True)
                # Append to the move history
                game.moves.append(MoveTuple(player, m, mm.rack, mm.timestamp))
                player = 1 - player

        # Account for the final tiles in the rack
        # logging.info(u"Game move load completed after move {0}, score is {1}:{2}".format(mx, game.state._scores[0], game.state._scores[1]).encode("latin-1"))
        if game.is_over():
            game.state.finalize_score()
        # If the moves were correctly applied, the scores should match
        if game.state._scores[0] != gm.score0:
            logging.info(u"Game state score0 is {0} while gm.score0 is {1}'".format(game.state._scores[0], gm.score0).encode("latin-1"))
        if game.state._scores[1] != gm.score1:
            logging.info(u"Game state score1 is {0} while gm.score1 is {1}'".format(game.state._scores[1], gm.score1).encode("latin-1"))
        assert game.state._scores[0] == gm.score0
        assert game.state._scores[1] == gm.score1

        # Find out what tiles are now in the bag
        game.state.recalc_bag()

        # Cache the game
        memcache.add(uuid, game, namespace='game')
        return game

    def store(self):
        """ Store the game state in persistent storage """
        assert self.uuid is not None
        with Game._lock:
            gm = GameModel(id = self.uuid)
            gm.timestamp = self.timestamp
            gm.ts_last_move = self.ts_last_move
            gm.set_player(0, self.player_ids[0])
            gm.set_player(1, self.player_ids[1])
            gm.irack0 = self.initial_racks[0]
            gm.irack1 = self.initial_racks[1]
            gm.rack0 = self.state.rack(0)
            gm.rack1 = self.state.rack(1)
            gm.score0 = self.state.scores()[0]
            gm.score1 = self.state.scores()[1]
            gm.to_move = len(self.moves) % 2
            gm.robot_level = self.robot_level
            gm.over = self.is_over()
            movelist = []
            for m in self.moves:
                mm = MoveModel()
                coord, tiles, score = m.move.summary(self.state.board())
                mm.coord = coord
                mm.tiles = tiles
                mm.score = score
                mm.rack = m.rack
                mm.timestamp = m.ts
                movelist.append(mm)
            gm.moves = movelist
            gm.put()
            # Update the memcache as well as the persistent store
            memcache.set(self.uuid, self, namespace='game')

    def id(self):
        """ Returns the unique id of this game """
        return self.uuid

    @classmethod
    def autoplayer_name(cls, level):
        """ Return the autoplayer name for a given level """
        i = len(Game.AUTOPLAYERS)
        while i > 0:
            i -= 1
            if level >= Game.AUTOPLAYERS[i][2]:
                return Game.AUTOPLAYERS[i][0]
        return Game.AUTOPLAYERS[0][0] # Strongest player by default

    def player_nickname(self, index):
        """ Returns the nickname of a player """
        u = None if self.player_ids[index] is None else User.load(self.player_ids[index])
        if u is None:
            # This is an autoplayer
            nick = Game.autoplayer_name(self.robot_level)
        else:
            # This is a human user
            nick = u.nickname()
            if nick[0:8] == u"https://":
                # Raw name (path) from Google Accounts: use a more readable version
                nick = Game.UNDEFINED_NAME
        return nick

    def resign(self):
        """ The local player is resigning the game """
        self.resigned = True

    def is_over(self):
        """ Return True if the game is over """
        return self.state.is_game_over()

    def allows_best_moves(self):
        """ Returns True if this game supports full review (has stored racks, etc.) """
        if self.initial_racks[0] is None or self.initial_racks[1] is None:
            # This is an old game stored without rack information: can't display best moves
            return False
        if not self.is_over():
            # Never show best moves for games that are still being played
            return False
        return True

    def autoplayer_move(self):
        """ Let the AutoPlayer make its move """
        player_index = self.player_to_move()
        apl = AutoPlayer(self.state, self.robot_level)
        move = apl.generate_move()
        self.state.apply_move(move)
        self.moves.append(MoveTuple(player_index, move,
            self.state.rack(player_index), datetime.utcnow()))
        self.ts_last_move = datetime.utcnow()
        self.last_move = move

    def local_move(self, move):
        """ Register the local player's move, update the score and move list """
        player_index = self.player_to_move()
        self.state.apply_move(move)
        self.moves.append(MoveTuple(player_index, move, self.state.rack(player_index), datetime.utcnow()))
        self.ts_last_move = datetime.utcnow()
        self.last_move = None # No autoplayer move yet

    def enum_tiles(self, state = None):
        """ Enumerate all tiles on the board in a convenient form """
        if state is None:
            state = self.state
        for x, y, tile, letter in state.board().enum_tiles():
            yield (Board.ROWIDS[x] + str(y + 1), tile, letter,
                0 if tile == u'?' else Alphabet.scores[tile])

    def state_after_move(self, move_number):
        """ Return a game state after the indicated move, 0=beginning state """
        s = State(drawtiles = False)
        for ix in range(2):
            s.set_player_name(ix, self.state.player_name(ix))
            if self.initial_racks[ix] is None:
                # Load the current rack rather than nothing
                s.set_rack(ix, self.state.rack(ix))
            else:
                # Load the initial rack
                s.set_rack(ix, self.initial_racks[ix])
        # Apply the moves
        for m in self.moves[0 : move_number]:
            s.apply_move(m.move, True)
            if m.rack is not None:
                s.set_rack(m.player, m.rack)
        s.recalc_bag()
        return s

    def display_bag(self, player_index):
        """ Returns the bag as it should be displayed to the indicated player,
            including the opponent's rack and sorted """
        return self.state.display_bag(player_index)

    def num_moves(self):
        """ Returns the number of moves in the game so far """
        return len(self.moves)

    def player_to_move(self):
        """ Returns the index (0 or 1) of the player whose move it is """
        return self.state.player_to_move()

    def player_id_to_move(self):
        """ Return the userid of the player whose turn it is, or None if autoplayer """
        return self.player_ids[self.player_to_move()]

    def is_autoplayer(self, player_index):
        """ Return True if the player in question is an autoplayer """
        return self.player_ids[player_index] is None

    def player_index(self, user_id):
        """ Return the player index (0 or 1) of the given user, or throw ValueError if not a player """
        if self.player_ids[0] == user_id:
            return 0
        if self.player_ids[1] == user_id:
            return 1
        raise ValueError(u"User_id {0} is not a player of this game".format(user_id))

    def has_player(self, user_id):
        """ Return True if the indicated user is a player of this game """
        try:
            pix = self.player_index(user_id)
        except ValueError:
            # Nope
            return False
        # player_index was obtained: the user is a player
        return True

    def start_time(self):
        """ Returns the timestamp of the game in a readable format """
        return u"" if self.timestamp is None else Alphabet.format_timestamp(self.timestamp)

    def client_state(self):
        """ Create a package of information for the client about the current state """
        reply = dict()
        if self.is_over():
            # The game is now over - one of the players finished it
            reply["result"] = Error.GAME_OVER # Not really an error
            num_moves = 1
            if self.last_move is not None:
                # Show the autoplayer move if it was the last move in the game
                reply["lastmove"] = self.last_move.details()
                num_moves = 2 # One new move to be added to move list
            newmoves = [(m.player, m.move.summary(self.state.board())) for m in self.moves[-num_moves:]]
            # Lastplayer is the player who finished the game
            lastplayer = self.moves[-1].player
            if not self.resigned:
                # If the game did not end by resignation,
                # account for the losing rack
                rack = self.state.rack(1 - lastplayer)
                # Subtract the score of the losing rack from the losing player
                newmoves.append((1 - lastplayer, (u"", rack, -1 * Alphabet.score(rack))))
                # Add the score of the losing rack to the winning player
                newmoves.append((lastplayer, (u"", rack, 1 * Alphabet.score(rack))))
            # Add a synthetic "game over" move
            newmoves.append((1 - lastplayer, (u"", u"OVER", 0)))
            reply["newmoves"] = newmoves
            reply["bag"] = "" # Bag is now empty, by definition
            reply["xchg"] = False # Exchange move not allowed
        else:
            # Game is still in progress
            reply["result"] = 0 # Indicate no error
            reply["rack"] = self.state.player_rack().details()
            reply["lastmove"] = self.last_move.details()
            reply["newmoves"] = [(m.player, m.move.summary(self.state.board())) for m in self.moves[-2:]]
            reply["bag"] = self.display_bag(self.player_to_move())
            reply["xchg"] = self.state.is_exchange_allowed()
        reply["scores"] = self.state.scores()
        return reply

    def statistics(self):
        """ Return a set of statistics on the game to be displayed by the client """
        reply = dict()
        if self.is_over():
            reply["result"] = Error.GAME_OVER # Indicate that the game is over (not really an error)
        else:
            reply["result"] = 0 # Game still in progress
        reply["gamestart"] = self.start_time()
        reply["scores"] = sc = self.state.scores()
        # Number of moves made
        reply["moves0"] = m0 = (len(self.moves) + 1) // 2 # Floor division
        reply["moves1"] = m1 = (len(self.moves) + 0) // 2 # Floor division
        ncovers = [(m.player, m.move.num_covers()) for m in self.moves]
        bingoes = [(p, nc == Rack.MAX_TILES) for p, nc in ncovers]
        # Number of bingoes
        reply["bingoes0"] = sum([1 if p == 0 and bingo else 0 for p, bingo in bingoes])
        reply["bingoes1"] = sum([1 if p == 1 and bingo else 0 for p, bingo in bingoes])
        # Number of tiles laid down
        reply["tiles0"] = t0 = sum([nc if p == 0 else 0 for p, nc in ncovers])
        reply["tiles1"] = t1 = sum([nc if p == 1 else 0 for p, nc in ncovers])
        blanks = [0, 0]
        letterscore = [0, 0]
        cleanscore = [0, 0]
        # Loop through the moves, collecting stats
        for m in self.moves:
            coord, wrd, msc = m.move.summary(self.state.board())
            if wrd != u'RSGN':
                # Don't include a resignation penalty in the clean score
                cleanscore[m.player] += msc
            if m.move.num_covers() == 0:
                # Exchange, pass or resign move
                continue
            for coord, tile, letter, score in m.move.details():
                if tile == u'?':
                    blanks[m.player] += 1
                letterscore[m.player] += score
        # Number of blanks laid down
        reply["blanks0"] = b0 = blanks[0]
        reply["blanks1"] = b1 = blanks[1]
        # Sum of straight letter scores
        reply["letterscore0"] = lsc0 = letterscore[0]
        reply["letterscore1"] = lsc1 = letterscore[1]
        # Calculate average straight score of tiles laid down (excluding blanks)
        reply["average0"] = (float(lsc0) / (t0 - b0)) if (t0 > b0) else 0.0
        reply["average1"] = (float(lsc1) / (t1 - b1)) if (t1 > b1) else 0.0
        # Calculate point multiple of tiles laid down (score / nominal points)
        reply["multiple0"] = (float(cleanscore[0]) / lsc0) if (lsc0 > 0) else 0.0
        reply["multiple1"] = (float(cleanscore[1]) / lsc1) if (lsc1 > 0) else 0.0
        # Calculate average score of each move
        reply["avgmove0"] = (float(cleanscore[0]) / m0) if (m0 > 0) else 0.0
        reply["avgmove1"] = (float(cleanscore[1]) / m1) if (m1 > 0) else 0.0
        # Plain sum of move scores
        reply["cleantotal0"] = cleanscore[0]
        reply["cleantotal1"] = cleanscore[1]
        # Contribution of remaining tiles at the end of the game
        reply["remaining0"] = sc[0] - cleanscore[0]
        reply["remaining1"] = sc[1] - cleanscore[1]
        # Score ratios (percentages)
        totalsc = sc[0] + sc[1]
        reply["ratio0"] = (float(sc[0]) / totalsc * 100.0) if totalsc > 0 else 0.0
        reply["ratio1"] = (float(sc[1]) / totalsc * 100.0) if totalsc > 0 else 0.0
        return reply


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
    game.local_move(m)

    # If it's the autoplayer's move, respond immediately
    # (can be a bit time consuming if rack has one or two blank tiles)
    if not game.is_over() and game.player_id_to_move() is None:
        game.autoplayer_move()

    if game.is_over():
        # If the game is now over, tally the final score
        game.state.finalize_score()

    # Make sure the new game state is persistently recorded
    game.store()

    # Return a state update to the client (board, rack, score, movelist, etc.)
    return jsonify(game.client_state())


def _userlist(range_from, range_to):
    """ Return a list of users matching the filter criteria """
    result = []
    cuser = User.current()
    cuid = None if cuser is None else cuser.id()
    if range_from == u"fav" and not range_to:
        # Return favorites of the current user
        logging.info(u"_userlist: iterating favorites".encode("latin-1"))
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
        logging.info(u"_userlist: iterating from {0} to {1}".format(range_from, range_to).encode("latin-1"))
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
    cuser = User.current()
    cuid = None if cuser is None else cuser.id()
    logging.info(u"_gamelist: iterating games".encode("latin-1"))
    if cuid is not None:
        i = list(GameModel.list_live_games(cuid, max_len = 50))
        i.sort(key = lambda x: x["ts"], reverse = True)
        for g in i:
            if g["opp"] is None:
                # Autoplayer opponent
                nick = Game.autoplayer_name(g["robot_level"])
            else:
                # Human opponent
                u = User.load(g["opp"])
                nick = u.nickname()
            result.append({
                "url": url_for('board', game = g["uuid"]),
                "opp": nick,
                "opp_is_robot": g["opp"] is None,
                "sc0": g["sc0"],
                "sc1": g["sc1"],
                "ts": Alphabet.format_timestamp(g["ts"]),
                "my_turn": g["my_turn"]
            })
    return result


def _recentlist():
    """ Return a list of recent games for the current user """
    result = []
    cuser = User.current()
    cuid = None if cuser is None else cuser.id()
    logging.info(u"_recentlist: iterating games".encode("latin-1"))
    if cuid is not None:
        i = iter(GameModel.list_finished_games(cuid, max_len = 14))
        for g in i:
            if g["opp"] is None:
                # Autoplayer opponent
                nick = Game.autoplayer_name(g["robot_level"])
            else:
                # Human opponent
                u = User.load(g["opp"])
                nick = u.nickname()
            result.append({
                "url": url_for('review', game = g["uuid"]),
                "opp": nick,
                "opp_is_robot": g["opp"] is None,
                "sc0": g["sc0"],
                "sc1": g["sc1"],
                "ts": Alphabet.format_timestamp(g["ts"])
            })
    return result


def _challengelist():
    """ Return a list of challenges issued or received by the current user """
    result = []
    cuser = User.current()
    cuid = None if cuser is None else cuser.id()
    logging.info(u"_challengelist: iterating challenges".encode("latin-1"))
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


@app.route("/gamestats", methods=['POST'])
def gamestats():
    """ Calculate and return statistics on the current game """

    user = User.current()
    if not user:
        # We must have a logged-in user
        return jsonify(result = Error.LOGIN_REQUIRED)

    uuid = request.form.get('game', None)
    if uuid is not None:
        game = Game.load(uuid)
        # Check whether the user was a player in this game
        if not game.has_player(user.id ()):
            # Nope: don't allow looking at the stats
            game = None

    if game is None:
       return jsonify(result = Error.LOGIN_REQUIRED) # Strictly speaking: game not found

    return jsonify(game.statistics())


@app.route("/userlist", methods=['POST'])
def userlist():
    """ Return user lists with particular criteria """

    range_from = request.form.get('from', None)
    range_to = request.form.get('to', None)

    logging.info(u"userlist(): range_from is {0}, range_to is {1}".format(range_from, range_to).encode("latin-1"))

    return jsonify(result = 0, userlist = _userlist(range_from, range_to))


@app.route("/gamelist", methods=['POST'])
def gamelist():
    """ Return a list of active games for the current user """

    return jsonify(result = 0, gamelist = _gamelist())


@app.route("/recentlist", methods=['POST'])
def recentlist():
    """ Return a list of recently completed games for the current user """

    return jsonify(result = 0, recentlist = _recentlist())


@app.route("/challengelist", methods=['POST'])
def challengelist():
    """ Return a list of challenges issued or received by the current user """

    return jsonify(result = 0, challengelist = _challengelist())


@app.route("/favorite", methods=['POST'])
def favorite():
    """ Create or delete an A-favors-B relation """

    user = User.current()
    if user is None:
        # We must have a logged-in user
        return jsonify(result = Error.LOGIN_REQUIRED)

    destuser = request.form.get('destuser', None)
    action = request.form.get('action', u"add")

    logging.info(u"favorite(): destuser is {0}, action is {1}".format(destuser, action).encode("latin-1"))

    if destuser is not None:
        if action == u"add":
            user.add_favorite(destuser)
        elif action == u"delete":
            user.del_favorite(destuser)

    return jsonify(result = 0)


@app.route("/challenge", methods=['POST'])
def challenge():
    """ Create or delete an A-favors-B relation """

    user = User.current()
    if user is None:
        # We must have a logged-in user
        return jsonify(result = Error.LOGIN_REQUIRED)

    destuser = request.form.get('destuser', None)
    action = request.form.get('action', u"issue")

    logging.info(u"challenge(): destuser is {0}, action is {1}".format(destuser, action).encode("latin-1"))

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

    return jsonify(result = 0)


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

    if game is None or not game.has_player(user.id()):
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

    if request.method == 'POST':
        try:
            # Funny string addition below ensures that username is
            # a Unicode string under both Python 2 and 3
            nickname = u'' + request.form['nickname'].strip()
        except:
            nickname = u''
        try:
            full_name = u'' + request.form['full_name'].strip()
        except:
            full_name = u''
        try:
            email = u'' + request.form['email'].strip()
        except:
            email = u''
        if nickname:
            user.set_nickname(nickname)
            user.set_full_name(full_name)
            user.set_email(email)
            user.update()
            return redirect(url_for("main"))
    return render_template("userprefs.html", user = user)


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
        # Starting a new game against an autoplayer (robot)
        robot_level = int(opp[6:])
        logging.info(u"Starting a new game with robot level {0}".format(robot_level).encode("latin-1"))
        game = Game.new(user.id(), None, robot_level)
        return redirect(url_for("board", game = game.id()))

    # !!! TBD: Handling the start of a game against a human
    return redirect(url_for("main"))


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

    return render_template("board.html", game = game, user = user, player_index = player_index)


@app.route("/")
def main():
    """ Handler for the main (index) page """

    user = User.current()
    if user is None:
        # User hasn't logged in yet: redirect to login page
        return redirect(users.create_login_url("/"))

    return render_template("main.html", user = user)


@app.route("/help")
def help():
    """ Show help page """
    return render_template("nshelp.html")


@app.errorhandler(404)
def page_not_found(e):
    """ Return a custom 404 error """
    return u'Sorry, nothing at this URL', 404


@app.errorhandler(500)
def server_error(e):
    """ Return a custom 500 error """
    return u'Sorry, unexpected error: {}'.format(e), 500


# Run a default Flask web server for testing if invoked directly as a main program

if __name__ == "__main__":
    app.run(debug=True)
