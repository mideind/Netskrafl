# -*- coding: utf-8 -*-

""" Game and User classes for Netskrafl

    Author: Vilhjalmur Thorsteinsson, 2014

    This module implements the User and Game classes for the
    Netskrafl application. These classes form an intermediary
    layer between the web server frontend in netskrafl.py and the
    actual game logic in skraflplayer.py, skraflmechanics.py et al.

    Note: SCRABBLE is a registered trademark. This software or its author
    are in no way affiliated with or endorsed by the owners or licensees
    of the SCRABBLE trademark.

"""

import logging
import time
import collections
import threading

from random import randint
from datetime import datetime, timedelta

from google.appengine.api import users, memcache

from skraflmechanics import State, Board, Rack, Error, \
    Move, PassMove, ExchangeMove, ResignMove
from skraflplayer import AutoPlayer
from languages import Alphabet
from skrafldb import Unique, UserModel, GameModel, MoveModel, \
    FavoriteModel, ChallengeModel, StatsModel, ChatModel


class User:

    """ Information about a human user including nickname and preferences """

    # Use a lock to avoid potential race conditions between the memcache and the database
    _lock = threading.Lock()

    # User object expiration in memcache
    _CACHE_EXPIRY = 15 * 60 # 15 minutes

    def __init__(self, uid = None):
        """ Initialize a fresh User instance """
        self._nickname = u""
        self._inactive = False
        self._preferences = { }
        self._ready = False
        self._ready_timed = False
        # Set of favorite users, only loaded upon demand
        self._favorites = None

        # NOTE: When new properties are added, the memcache namespace version id
        # should be incremented!

        if uid is None:
            # Obtain information from the currently logged in user
            u = users.get_current_user()
            if u is None:
                self._user_id = None
            else:
                self._user_id = u.user_id()
                self._nickname = u.nickname() # Default
                # Use the user's email address, if available
                email = u.email()
                if email:
                    self.set_email(email)
        else:
            self._user_id = uid

    def _fetch(self):
        """ Fetch the user's record from the database """
        um = UserModel.fetch(self._user_id)
        if um is None:
            # Use the default properties for a newly created user
            UserModel.create(self._user_id, self.nickname()) # This updates the database
        else:
            # Obtain the properties from the database entity
            self._nickname = um.nickname
            self._inactive = um.inactive
            self._preferences = um.prefs
            self._ready = um.ready
            self._ready_timed = um.ready_timed

    def update(self):
        """ Update the user's record in the database and in the memcache """
        with User._lock:
            # Use a lock to avoid the scenaro where a user is fetched by another
            # request in the interval between a database update and a memcache update
            UserModel.update(self._user_id, self._nickname,
                self._inactive, self._preferences,
                self._ready, self._ready_timed)
            # Note: the namespace version should be incremented each time
            # that the class properties change
            memcache.set(self._user_id, self, time=User._CACHE_EXPIRY, namespace='user:1')

    def id(self):
        """ Returns the id (database key) of the user """
        return self._user_id

    def nickname(self):
        """ Returns the human-readable nickname of a user, or userid if a nick is not available """
        return self._nickname or self._user_id

    def set_nickname(self, nickname):
        """ Sets the human-readable nickname of a user """
        self._nickname = nickname

    @staticmethod
    def is_valid_nick(nick):
        """ Check whether a nickname is valid and displayable """
        if not nick:
            return False
        return nick[0:8] != u"https://" and nick[0:7] != u"http://"

    def is_displayable(self):
        """ Returns True if this user should appear in user lists """
        if self._inactive:
            # Inactive users are hidden
            return False
        # Nicknames that haven't been properly set aren't displayed
        return User.is_valid_nick(self._nickname)

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

    @staticmethod
    def full_name_from_prefs(prefs):
        """ Returns the full name of a user from a dict of preferences """
        if prefs is None:
            return u""
        fn = prefs.get(u"full_name")
        return u"" if fn is None else fn

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

    def audio(self):
        """ Returns True if the user wants audible signals """
        em = self.get_pref(u"audio")
        # True by default
        return True if em is None else em

    def set_audio(self, audio):
        """ Sets the audio preference of a user to True or False """
        assert isinstance(audio, bool)
        self.set_pref(u"audio", audio)

    def beginner(self):
        """ Returns True if the user is a beginner so we show help panels, etc. """
        em = self.get_pref(u"beginner")
        # True by default
        return True if em is None else em

    def set_beginner(self, beginner):
        """ Sets the beginner state of a user to True or False """
        assert isinstance(beginner, bool)
        self.set_pref(u"beginner", beginner)

    def is_ready(self):
        """ Returns True if the user is ready to accept challenges """
        return self._ready

    def set_ready(self, ready):
        """ Sets the ready state of a user to True or False """
        assert isinstance(ready, bool)
        self._ready = ready

    def is_ready_timed(self):
        """ Returns True if the user is ready for timed games """
        return self._ready_timed

    def set_ready_timed(self, ready):
        """ Sets the whether a user is ready for timed games """
        assert isinstance(ready, bool)
        self._ready_timed = ready

    def _load_favorites(self):
        """ Loads favorites of this user from the database into a set in memory """
        if hasattr(self, "_favorites") and self._favorites:
            # Already have the favorites in memory
            return
        self._favorites = set()
        i = iter(FavoriteModel.list_favorites(self.id()))
        self._favorites.update(i)

    def add_favorite(self, destuser_id):
        """ Add an A-favors-B relation between this user and the destuser """
        self._load_favorites()
        self._favorites.add(destuser_id)
        FavoriteModel.add_relation(self.id(), destuser_id)

    def del_favorite(self, destuser_id):
        """ Delete an A-favors-B relation between this user and the destuser """
        self._load_favorites()
        self._favorites.discard(destuser_id)
        FavoriteModel.del_relation(self.id(), destuser_id)

    def has_favorite(self, destuser_id):
        """ Returns True if there is an A-favors-B relation between this user and the destuser """
        self._load_favorites()
        return destuser_id in self._favorites

    def has_challenge(self, destuser_id):
        """ Returns True if this user has challenged destuser """
        # !!! TODO: Cache this in the user object to save NDB reads
        return ChallengeModel.has_relation(self.id(), destuser_id)

    def find_challenge(self, srcuser_id):
        """ Returns (found, prefs) """
        return ChallengeModel.find_relation(srcuser_id, self.id())

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
        # Delete the accepted challenge and return the associated preferences
        return ChallengeModel.del_relation(srcuser_id, self.id())

    @staticmethod
    def logout_url():
        return users.create_logout_url("/")

    @classmethod
    def load(cls, uid):
        """ Load a user from persistent storage given his/her user id """
        with User._lock:
            u = memcache.get(uid, namespace='user:1')
            if u is None:
                # Not found in the memcache: create a user object and
                # populate it from a database entity (or initialize
                # a fresh one if no entity exists).
                u = cls(uid)
                u._fetch()
                memcache.add(uid, u, time=User._CACHE_EXPIRY, namespace='user:1')
            return u

    @classmethod
    def current(cls):
        """ Return the currently logged in user """
        with User._lock:
            user = users.get_current_user()
            if user is None or user.user_id() is None:
                return None
            u = memcache.get(user.user_id(), namespace='user:1')
            if u is not None:
                return u
            # This might be a user that is not yet in the database
            u = cls()
            u._fetch() # Creates a database entity if this is a fresh user
            memcache.add(u.id(), u, time=User._CACHE_EXPIRY, namespace='user:1')
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

    def statistics(self):
        """ Return a set of key statistics on the user """
        reply = dict()
        sm = StatsModel.newest_for_user(self.id())
        reply["result"] = Error.LEGAL
        reply["nickname"] = self.nickname()
        reply["fullname"] = self.full_name()
        sm.populate_dict(reply)
        return reply


# Tuple for storing move data within a Game (must be at outermost scope for pickling to work)
MoveTuple = collections.namedtuple("MoveTuple", ["player", "move", "rack", "ts"])


class Game:

    """ A wrapper class for a particular game that is in process
        or completed. Contains inter alia a State instance.
    """

    # The available autoplayers (robots)
    AUTOPLAYERS = [
        (u"Fullsterkur",
            u"Velur stigahæsta leik í hverri stöðu", 0),
        (u"Miðlungur",
            u"Velur af handahófi einn af 8 stigahæstu leikjum í hverri stöðu", 8),
        (u"Amlóði",
            u"Forðast sjaldgæf orð og velur úr 20 leikjum sem koma til álita", 15)
        ]

    # The default nickname to display if a player has an unreadable nick
    # (for instance a default Google nick with a https:// prefix)
    UNDEFINED_NAME = u"[Ónefndur]"

    # The maximum overtime in a game, after which a player automatically loses
    MAX_OVERTIME = 10 * 60.0 # 10 minutes, in seconds

    # After this number of days the game becomes overdue and the
    # waiting player can force the tardy opponent to resign
    OVERDUE_DAYS = 14

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
        # History of moves in this game so far, as a list of MoveTuple namedtuples
        self.moves = []
        # Initial rack contents
        self.initial_racks = [None, None]
        # Preferences (such as time limit, alternative bag or board, etc.)
        self._preferences = None
        # Cache of game over state (becomes True when the game is definitely over)
        self._game_over = None

    def _make_new(self, player0_id, player1_id, robot_level = 0, prefs = None):
        """ Initialize a new, fresh game """
        # If either player0_id or player1_id is None, this is a human-vs-autoplayer game
        self.player_ids = [player0_id, player1_id]
        self.state = State(drawtiles = True)
        self.initial_racks[0] = self.state.rack(0)
        self.initial_racks[1] = self.state.rack(1)
        self.robot_level = robot_level
        self.timestamp = self.ts_last_move = datetime.utcnow()
        self._preferences = prefs

    @classmethod
    def new(cls, player0_id, player1_id, robot_level = 0, prefs = None):
        """ Start and initialize a new game """
        game = cls(Unique.id()) # Assign a new unique id to the game
        if randint(0, 1) == 1:
            # Randomize which player starts the game
            player0_id, player1_id = player1_id, player0_id
        game._make_new(player0_id, player1_id, robot_level, prefs)
        # If AutoPlayer is first to move, generate the first move
        if game.player_id_to_move() is None:
            game.autoplayer_move()
        # Store the new game in persistent storage
        game.store()
        return game

    @classmethod
    def load(cls, uuid):
        """ Load an already existing game from persistent storage """
        with Game._lock:
            # Ensure that the game load does not introduce race conditions
            return cls._load_locked(uuid)

    def store(self):
        """ Store the game state in persistent storage """
        # Avoid race conditions by securing the lock before storing
        with Game._lock:
            self._store_locked()

    @classmethod
    def _load_locked(cls, uuid):
        """ Load an existing game from cache or persistent storage under lock """

        gm = GameModel.fetch(uuid)
        if gm is None:
            # A game with this uuid is not found in the database: give up
            return None

        # Initialize a new Game instance with a pre-existing uuid
        game = cls(uuid)

        # Set the timestamps
        game.timestamp = gm.timestamp
        game.ts_last_move = gm.ts_last_move
        if game.ts_last_move is None:
            # If no last move timestamp, default to the start of the game
            game.ts_last_move = game.timestamp

        # Initialize the preferences
        game._preferences = gm.prefs

        # Initialize a fresh, empty state with no tiles drawn into the racks
        game.state = State(drawtiles = False)

        # A player_id of None means that the player is an autoplayer (robot)
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
        # mx = 0 # Move counter for debugging/logging
        for mm in gm.moves:

            # mx += 1
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

        # Find out what tiles are now in the bag
        game.state.recalc_bag()

        # Account for the final tiles in the rack and overtime, if any
        if game.is_over():
            game.finalize_score()
            if not gm.over:
                # The game was not marked as over when we loaded it from
                # the datastore, but it is over now. One of the players must
                # have lost on overtime. We need to update the persistent state.
                game._store_locked()

        return game

    def _store_locked(self):
        """ Store the game after having acquired the object lock """

        assert self.uuid is not None

        gm = GameModel(id = self.uuid)
        gm.timestamp = self.timestamp
        gm.ts_last_move = self.ts_last_move
        gm.set_player(0, self.player_ids[0])
        gm.set_player(1, self.player_ids[1])
        gm.irack0 = self.initial_racks[0]
        gm.irack1 = self.initial_racks[1]
        gm.rack0 = self.state.rack(0)
        gm.rack1 = self.state.rack(1)
        gm.over = self.is_over()
        sc = self.final_scores() # Includes adjustments if game is over
        gm.score0 = sc[0]
        gm.score1 = sc[1]
        gm.to_move = len(self.moves) % 2
        gm.robot_level = self.robot_level
        gm.prefs = self._preferences
        tile_count = 0
        movelist = []
        for m in self.moves:
            mm = MoveModel()
            coord, tiles, score = m.move.summary(self.state.board())
            if coord:
                # Regular move: count the tiles actually laid down
                tile_count += m.move.num_covers()
            mm.coord = coord
            mm.tiles = tiles
            mm.score = score
            mm.rack = m.rack
            mm.timestamp = m.ts
            movelist.append(mm)
        gm.moves = movelist
        gm.tile_count = tile_count
        # Update the database entity
        gm.put()

    def id(self):
        """ Returns the unique id of this game """
        return self.uuid

    @staticmethod
    def autoplayer_name(level):
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

    def get_pref(self, pref):
        """ Retrieve a preference, or None if not found """
        if self._preferences is None:
            return None
        return self._preferences.get(pref, None)

    def set_pref(self, pref, value):
        """ Set a preference to a value """
        if self._preferences is None:
            self._preferences = { }
        self._preferences[pref] = value

    @staticmethod
    def get_duration_from_prefs(prefs):
        """ Return the duration given a dict of game preferences """
        return 0 if prefs is None else prefs.get(u"duration", 0)

    def get_duration(self):
        """ Return the duration for each player in the game, e.g. 25 if 2x25 minute game """
        return self.get_pref(u"duration") or 0

    def set_duration(self, duration):
        """ Set the duration for each player in the game, e.g. 25 if 2x25 minute game """
        self.set_pref(u"duration", duration)

    def is_overdue(self):
        """ Return True if no move has been made in the game for OVERDUE_DAYS days """
        ts_last_move = self.ts_last_move or self.timestamp
        delta = datetime.utcnow() - ts_last_move
        return delta >= timedelta(days = Game.OVERDUE_DAYS)

    def get_elapsed(self):
        """ Return the elapsed time for both players, in seconds, as a tuple """
        elapsed = [0.0, 0.0]
        last_ts = self.timestamp
        for m in self.moves:
            if m.ts is not None:
                delta = m.ts - last_ts
                last_ts = m.ts
                elapsed[m.player] += delta.total_seconds()
        if not self.state.is_game_over():
            # Game still going on: Add the time from the last move until now
            delta = datetime.utcnow() - last_ts
            elapsed[self.player_to_move()] += delta.total_seconds()
        return tuple(elapsed)

    def time_info(self):
        """ Returns a dict with timing information about this game """
        return dict(duration = self.get_duration(), elapsed = self.get_elapsed())

    def overtime(self):
        """ Return overtime for both players, in seconds """
        overtime = [0, 0]
        duration = self.get_duration() * 60.0 # In seconds
        if duration > 0.0:
            # Timed game: calculate the overtime
            el = self.get_elapsed()
            for player in range(2):
                overtime[player] = max(0.0, el[player] - duration) # Never negative
        return tuple(overtime)

    def overtime_adjustment(self):
        """ Return score adjustments due to overtime, as a tuple with two deltas """
        overtime = self.overtime()
        adjustment = [0, 0]
        for player in range(2):
            if overtime[player] > 0.0:
                # 10 point subtraction for every started minute
                # The formula means that 0.1 second into a new minute
                # a 10-point loss is incurred
                # After 10 minutes, the game is lost and the adjustment maxes out at -100
                adjustment[player] = max(-100, -10 * ((int(overtime[player] + 0.9) + 59) // 60))
        return tuple(adjustment)

    def is_over(self):
        """ Return True if the game is over """
        if self._game_over:
            # Use the cached result if available and True
            return True
        if self.state.is_game_over():
            self._game_over = True
            return True
        if self.get_duration() == 0:
            # Not a timed game: it's not over
            return False
        # Timed game: might now be lost on overtime
        overtime = self.overtime()
        if any(overtime[ix] >= Game.MAX_OVERTIME for ix in range(2)):
            # The game has been lost on overtime
            self._game_over = True
            return True
        return False

    def winning_player(self):
        """ Returns index of winning player, or -1 if game is tied or not over """
        if not self.is_over():
            return -1
        sc = self.final_scores()
        if sc[0] > sc[1]:
            return 0
        if sc[1] > sc[0]:
            return 1
        return -1

    def finalize_score(self):
        """ Adjust the score at the end of the game, accounting for left tiles, overtime, etc. """
        assert self.is_over()
        # Final adjustments to score, including rack leave and overtime, if any
        overtime = self.overtime()
        # Check whether a player lost on overtime
        lost_on_overtime = None
        for player in range(2):
            if overtime[player] >= Game.MAX_OVERTIME:
                lost_on_overtime = player
                break
        self.state.finalize_score(lost_on_overtime, self.overtime_adjustment())

    def final_scores(self):
        """ Return the final score of the game after adjustments, if any """
        return self.state.final_scores()

    def allows_best_moves(self):
        """ Returns True if this game supports full review (has stored racks, etc.) """
        if self.initial_racks[0] is None or self.initial_racks[1] is None:
            # This is an old game stored without rack information: can't display best moves
            return False
        # Never show best moves for games that are still being played
        return self.is_over()

    def register_move(self, move):
        """ Register a new move, updating the score and appending to the move list """
        player_index = self.player_to_move()
        self.state.apply_move(move)
        self.ts_last_move = datetime.utcnow()
        self.moves.append(MoveTuple(player_index, move,
            self.state.rack(player_index), self.ts_last_move))
        self.last_move = None # No response move yet

    def autoplayer_move(self):
        """ Generate an AutoPlayer move and register it """
        # Create an appropriate AutoPlayer subclass instance
        # depending on the robot level in question
        apl = AutoPlayer.create(self.state, self.robot_level)
        move = apl.generate_move()
        self.register_move(move)
        self.last_move = move # Store a response move

    def enum_tiles(self, state = None):
        """ Enumerate all tiles on the board in a convenient form """
        if state is None:
            state = self.state
        for x, y, tile, letter in state.board().enum_tiles():
            yield (Board.ROWIDS[x] + str(y + 1), tile, letter, Alphabet.scores[tile])

    def state_after_move(self, move_number):
        """ Return a game state after the indicated move, 0=beginning state """
        # Initialize a fresh state object
        s = State(drawtiles = False)
        # Set up the initial state
        for ix in range(2):
            s.set_player_name(ix, self.state.player_name(ix))
            if self.initial_racks[ix] is None:
                # Load the current rack rather than nothing
                s.set_rack(ix, self.state.rack(ix))
            else:
                # Load the initial rack
                s.set_rack(ix, self.initial_racks[ix])
        # Apply the moves up to the state point
        for m in self.moves[0 : move_number]:
            s.apply_move(m.move, shallow = True) # Shallow apply
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

    def player_id(self, player_index):
        """ Return the userid of the indicated player """
        return self.player_ids[player_index]

    def my_turn(self, user_id):
        """ Return True if it is the indicated player's turn to move """
        if self.is_over():
            return False
        return self.player_id_to_move() == user_id

    def is_autoplayer(self, player_index):
        """ Return True if the player in question is an autoplayer """
        return self.player_ids[player_index] is None

    def is_robot_game(self):
        """ Return True if one of the players is an autoplayer """
        return self.is_autoplayer(0) or self.is_autoplayer(1)

    def player_index(self, user_id):
        """ Return the player index (0 or 1) of the given user, or None if not a player """
        if self.player_ids[0] == user_id:
            return 0
        if self.player_ids[1] == user_id:
            return 1
        return None

    def has_player(self, user_id):
        """ Return True if the indicated user is a player of this game """
        return self.player_index(user_id) is not None

    def start_time(self):
        """ Returns the timestamp of the game in a readable format """
        return u"" if self.timestamp is None else Alphabet.format_timestamp(self.timestamp)

    def end_time(self):
        """ Returns the time of the last move in a readable format """
        return u"" if self.ts_last_move is None else Alphabet.format_timestamp(self.ts_last_move)

    def has_new_chat_msg(self, user_id):
        """ Return True if there is a new chat message that the given user hasn't seen """
        p = self.player_index(user_id)
        if p is None or self.is_autoplayer(1 - p):
            # The user is not a player of this game, or robot opponent: no chat
            return False
        # Check the database
        # !!! TBD: consider memcaching this
        return ChatModel.check_conversation(u"game:" + self.id(), user_id)

    def _append_final_adjustments(self, movelist):
        """ Appends final score adjustment transactions to the given movelist """

        # Lastplayer is the player who finished the game
        lastplayer = self.moves[-1].player

        if not self.state.is_resigned():

            # If the game did not end by resignation, check for a timeout
            overtime = self.overtime()
            adjustment = list(self.overtime_adjustment())
            sc = self.state.scores()

            if any(overtime[ix] >= Game.MAX_OVERTIME for ix in range(2)): # 10 minutes overtime
                # Game ended with a loss on overtime
                ix = 0 if overtime[0] >= Game.MAX_OVERTIME else 1
                adjustment[1 - ix] = 0
                # Adjust score of losing player down by 100 points
                adjustment[ix] = - min(100, sc[ix])
                # If losing player is still winning on points, add points to the
                # winning player so that she leads by one point
                if sc[ix] + adjustment[ix] >= sc[1 - ix]:
                    adjustment[1 - ix] = sc[ix] + adjustment[ix] + 1 - sc[1 - ix]
            else:
                # Normal end of game
                opp_rack = self.state.rack(1 - lastplayer)
                opp_score = Alphabet.score(opp_rack)
                last_rack = self.state.rack(lastplayer)
                last_score = Alphabet.score(last_rack)
                if not last_rack:
                    # Won with an empty rack: Add double the score of the losing rack
                    movelist.append((1 - lastplayer, (u"", u"--", 0)))
                    movelist.append((lastplayer, (u"", u"2 * " + opp_rack, 2 * opp_score)))
                else:
                    # The game has ended by passes: each player gets her own rack subtracted
                    movelist.append((1 - lastplayer, (u"", opp_rack, -1 * opp_score)))
                    movelist.append((lastplayer, (u"", last_rack, -1 * last_score)))

            # If this is a timed game, add eventual overtime adjustment
            if tuple(adjustment) != (0, 0):
                movelist.append((1 - lastplayer, (u"", u"TIME", adjustment[1 - lastplayer])))
                movelist.append((lastplayer, (u"", u"TIME", adjustment[lastplayer])))

        # Add a synthetic "game over" move
        movelist.append((1 - lastplayer, (u"", u"OVER", 0)))

    def get_final_adjustments(self):
        """ Get a fresh list of the final adjustments made to the game score """
        movelist = []
        self._append_final_adjustments(movelist)
        return movelist

    def client_state(self, player_index, lastmove = None):
        """ Create a package of information for the client about the current state """

        reply = dict()
        num_moves = 1
        if self.last_move is not None:
            # Show the autoplayer move that was made in response
            reply["lastmove"] = self.last_move.details()
            num_moves = 2 # One new move to be added to move list
        elif lastmove is not None:
            # The indicated move should be included in the client state
            # (used when notifying an opponent of a new move through a channel)
            reply["lastmove"] = lastmove.details()
        newmoves = [(m.player, m.move.summary(self.state.board())) for m in self.moves[-num_moves:]]

        if self.is_over():
            # The game is now over - one of the players finished it
            self._append_final_adjustments(newmoves)
            reply["result"] = Error.GAME_OVER # Not really an error
            reply["xchg"] = False # Exchange move not allowed
            reply["bag"] = self.state.bag().contents()
        else:
            # Game is still in progress
            reply["result"] = 0 # Indicate no error
            reply["xchg"] = self.state.is_exchange_allowed()
            reply["bag"] = self.display_bag(player_index)

        reply["rack"] = self.state.rack_details(player_index)
        reply["newmoves"] = newmoves
        reply["scores"] = self.final_scores()
        if self.get_duration():
            # Timed game: send information about elapsed time
            reply["time_info"] = self.time_info()
        return reply

    def statistics(self):
        """ Return a set of statistics on the game to be displayed by the client """
        reply = dict()
        if self.is_over():
            reply["result"] = Error.GAME_OVER # Indicate that the game is over (not really an error)
        else:
            reply["result"] = 0 # Game still in progress
        reply["gamestart"] = self.start_time()
        reply["gameend"] = self.end_time()
        reply["duration"] = self.get_duration()
        reply["scores"] = sc = self.final_scores()
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
        # Contribution of overtime at the end of the game
        ov = self.overtime()
        if any(ov[ix] >= Game.MAX_OVERTIME for ix in range(2)):
            # Game was lost on overtime
            reply["remaining0"] = 0
            reply["remaining1"] = 0
            reply["overtime0"] = sc[0] - cleanscore[0]
            reply["overtime1"] = sc[1] - cleanscore[1]
        else:
            oa = self.overtime_adjustment()
            reply["overtime0"] = oa[0]
            reply["overtime1"] = oa[1]
            # Contribution of remaining tiles at the end of the game
            reply["remaining0"] = sc[0] - cleanscore[0] - oa[0]
            reply["remaining1"] = sc[1] - cleanscore[1] - oa[1]
        # Score ratios (percentages)
        totalsc = sc[0] + sc[1]
        reply["ratio0"] = (float(sc[0]) / totalsc * 100.0) if totalsc > 0 else 0.0
        reply["ratio1"] = (float(sc[1]) / totalsc * 100.0) if totalsc > 0 else 0.0
        return reply

