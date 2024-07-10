"""

    Game class for netskrafl.is

    Copyright (C) 2023 Miðeind ehf.
    Author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This module implements the Game class for the
    Netskrafl application. This class form an intermediary
    layer between the web server frontend in netskrafl.py and the
    actual game logic in skraflplayer.py, skraflmechanics.py et al.

"""

# pylint: disable=too-many-lines

from __future__ import annotations

from typing import (
    Dict,
    Type,
    Optional,
    List,
    TypedDict,
    Union,
    Tuple,
    NamedTuple,
    Iterator,
    cast,
)

import threading

# import logging

from random import randint
from datetime import UTC, datetime, timedelta
from itertools import groupby

from config import DEFAULT_LOCALE, running_local

from languages import (
    Alphabet,
    OldTileSet,
    NewTileSet,
    TileSet,
    tileset_for_locale,
    vocabulary_for_locale,
    set_game_locale,
)
from skrafldb import (
    PrefsDict,
    Unique,
    GameModel,
    MoveModel,
)
from dawgdictionary import Wordbase
from skraflmechanics import (
    DetailTuple,
    RackDetails,
    State,
    Board,
    Rack,
    Error,
    MoveBase,
    Move,
    PassMove,
    ExchangeMove,
    ChallengeMove,
    ResponseMove,
    ResignMove,
    MoveSummaryTuple,
    SummaryTuple,
)
from skraflplayer import AutoPlayer
from skrafluser import User
from skraflelo import compute_elo_for_game, compute_locale_elo_for_game


# Type definitions
StatsDict = Dict[str, Union[str, int, float, Tuple[int, int]]]


# Tuple for storing move data within a Game
class MoveTuple(NamedTuple):
    player: int
    move: MoveBase
    rack: str
    ts: Optional[datetime]


TwoLetterGroupList = List[Tuple[str, List[str]]]
TwoLetterGroupTuple = Tuple[TwoLetterGroupList, TwoLetterGroupList]

MoveSummaryTuple = Tuple[int, SummaryTuple]
MoveList = List[MoveSummaryTuple]
BestMove = MoveSummaryTuple
BestMoveList = List[BestMove]


class TimeInfo(TypedDict):

    """Information about the state of a timed game"""

    duration: int
    elapsed: Tuple[float, float]


class EloDeltaDict(TypedDict, total=False):
    """Elo point deltas (differences) for both players"""

    elo: Tuple[int, int]
    human: Tuple[int, int]
    manual: Tuple[int, int]


class EloNowDict(TypedDict, total=False):
    """Current Elo points for the requesting player"""

    elo: Tuple[int, int]
    human: Tuple[int, int]
    manual: Tuple[int, int]


class ClientStateDict(TypedDict, total=False):

    """The game state that is sent to the client"""

    alphabet: str
    autoplayer: List[bool]
    bag: str
    board_type: str  # 'explo' | 'standard'
    chall: bool
    elo_delta: EloDeltaDict
    elo_now: EloNowDict
    fairplay: bool
    fullname: List[str]
    last_chall: bool
    lastmove: List[DetailTuple]
    locale: str
    manual: bool
    moves: MoveList
    racks: Optional[List[str]]
    newbag: bool
    newmoves: MoveList
    nickname: List[str]
    num_moves: int
    overdue: bool
    player: Optional[int]
    progress: Tuple[int, int]
    rack: RackDetails
    result: int
    scores: Tuple[int, int]
    succ_chall: bool
    tile_scores: Dict[str, int]
    time_info: TimeInfo
    two_letter_words: TwoLetterGroupTuple
    userid: List[Optional[str]]
    xchg: bool


# The default nickname to display if a player has an unreadable nick
# (for instance a default Google nick with a https:// prefix)
UNDEFINED_NAME: Dict[str, str] = {
    "is": "[Ónefndur]",
    "en": "[Unknown]",
    "pl": "[Nieznany]",
    "nb": "[Ukjent]",
    "ga": "[Anaithnid]",
}


class Game:

    """A wrapper class for a particular game that is in process
    or completed. Contains inter alia a State instance."""

    # The maximum overtime in a game, after which a player automatically loses
    # Normally 10 minutes, but set to 1 minute if running locally (debug)
    MAX_OVERTIME = 1 * 60.0 if running_local else 10 * 60.0

    # After this number of days the game becomes overdue and the
    # waiting player can force the tardy opponent to resign
    OVERDUE_DAYS = 14

    _lock = threading.Lock()

    def __init__(self, *, locale: str, uuid: Optional[str] = None) -> None:
        # Unique id of the game
        self.uuid = uuid
        # The reference locale of the game
        self._locale = locale
        # The start time of the game
        self.timestamp: Optional[datetime] = None
        # The user ids of the players (None if autoplayer)
        # Player 0 is the one that begins the game
        self.player_ids: List[Optional[str]] = [None, None]
        # The current game state
        self.state: Optional[State] = None
        # The ability level of the autoplayer (0 = strongest)
        self.robot_level = 0
        # The last move made by the remote player
        self.last_move: Optional[MoveBase] = None
        # The timestamp of the last move made in the game
        self.ts_last_move: Optional[datetime] = None
        # History of moves in this game so far, as a list of MoveTuple namedtuples
        self.moves: List[MoveTuple] = []
        # Initial rack contents
        self.initial_racks: List[Optional[str]] = [None, None]
        # Preferences (such as time limit, alternative bag or board, etc.)
        self._preferences: Optional[PrefsDict] = None
        # Cache of game over state (becomes True when the game is definitely over)
        self._game_over = False
        # Flag for erroneous games, i.e. ones that are incorrectly stored
        # in the NDB datastore
        self._erroneous = False
        # Cached two-letter word list
        self._two_letter_words: Optional[TwoLetterGroupTuple] = None
        # Elo score deltas for both players, calculated when the game finishes
        self.elo_delta: Optional[EloDeltaDict] = None
        # Current Elo scores for both players
        self.elo_now: Optional[EloNowDict] = None

    def _make_new(
        self,
        player0_id: Optional[str],
        player1_id: Optional[str],
        robot_level: int = 0,
        prefs: Optional[PrefsDict] = None,
    ) -> None:
        """Initialize a new, fresh game"""
        self._preferences = prefs
        # If either player0_id or player1_id is None,
        # this is a human-vs-autoplayer game
        self.player_ids = [player0_id, player1_id]
        self.state = State(
            drawtiles=True,
            tileset=self.tileset,
            manual_wordcheck=self.manual_wordcheck(),
            locale=self.locale,
            board_type=self.board_type,
        )
        self.initial_racks[0] = self.state.rack(0)
        self.initial_racks[1] = self.state.rack(1)
        self.robot_level = robot_level
        self.timestamp = self.ts_last_move = datetime.now(UTC)

    @classmethod
    def new(
        cls,
        player0_id: Optional[str],
        player1_id: Optional[str],
        robot_level: int = 0,
        prefs: Optional[PrefsDict] = None,
    ) -> Game:
        """Start and initialize a new game"""
        locale = Game.locale_from_prefs(prefs) or DEFAULT_LOCALE
        game = cls(
            uuid=Unique.id(), locale=locale
        )  # Assign a new unique id to the game
        if randint(0, 1) == 1:
            # Randomize which player starts the game
            player0_id, player1_id = player1_id, player0_id
        game._make_new(player0_id, player1_id, robot_level, prefs)
        # If AutoPlayer is first to move, generate the first move
        if game.player_id_to_move() is None:
            game.autoplayer_move()
        # Store the new game in persistent storage
        game.store(calc_elo_points=False)
        return game

    @classmethod
    def load(
        cls, uuid: str, *, use_cache: bool = True, set_locale: bool = False
    ) -> Optional[Game]:
        """Load an already existing game from persistent storage.
        If set_locale is True, set the current thread's locale
        to the game locale."""
        with Game._lock:
            # Ensure that the game load does not introduce race conditions
            try:
                return cls._load_locked(
                    uuid, use_cache=use_cache, set_locale=set_locale
                )
            except KeyError:
                # Hack to handle older game objects that have no associated
                # locale. If we run Explo on such data, the default locale
                # is en_US, but the game may use the Icelandic tile set, which
                # causes KeyError to be raised upon loading. In that case,
                # we try again with the locale forced to is_IS.
                if set_locale and DEFAULT_LOCALE != "is_IS":
                    return cls._load_locked(
                        uuid, use_cache=use_cache, force_locale="is_IS"
                    )
            return None

    def store(self, *, calc_elo_points: bool) -> None:
        """Store the game state in persistent storage"""
        # Avoid race conditions by securing the lock before storing
        with Game._lock:
            self._store_locked(calc_elo_points=calc_elo_points)

    @classmethod
    def _load_locked(
        cls,
        uuid: str,
        *,
        use_cache: bool = True,
        set_locale: bool = False,
        force_locale: str = "",
    ) -> Optional[Game]:
        """Load an existing game from cache or persistent storage under lock"""

        gm = GameModel.fetch(uuid, use_cache)
        if gm is None:
            # A game with this uuid is not found in the database: give up
            return None

        # Initialize a new Game instance with a pre-existing uuid
        game = cls(uuid=uuid, locale=gm.locale or "")

        # Set the timestamps
        game.timestamp = gm.timestamp
        game.ts_last_move = gm.ts_last_move
        if game.ts_last_move is None:
            # If no last move timestamp, default to the start of the game
            game.ts_last_move = game.timestamp

        # Initialize the preferences (this sets the locale, tileset, etc.)
        game._preferences = gm.prefs

        if force_locale:
            # Hack: we force a locale if the game doesn't have one already
            if not game.has_locale():
                game.set_locale(force_locale)
            set_locale = True

        # A player_id of None means that the player is an autoplayer (robot)
        game.player_ids[0] = gm.player0_id()
        game.player_ids[1] = gm.player1_id()

        game.robot_level = gm.robot_level

        if set_locale:
            # If asked to do so, set the current thread's game locale
            # before loading the moves. This is needed because challenge
            # moves consult the dictionary from the current locale to
            # determine the validity of the challenge and hence its score.
            set_game_locale(game.locale)

        # Initialize a fresh, empty state with no tiles drawn into the racks
        game.state = State(
            drawtiles=False,
            manual_wordcheck=game.manual_wordcheck(),
            tileset=game.tileset,
            locale=game.locale,
            board_type=game.board_type,
        )

        # Load the initial racks
        game.initial_racks[0] = gm.irack0
        game.initial_racks[1] = gm.irack1

        game.state.set_rack(0, gm.irack0 or "")
        game.state.set_rack(1, gm.irack1 or "")

        # Process the moves
        player = 0
        now = datetime.now(UTC)

        for mm in gm.moves:
            m: Optional[MoveBase] = None

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
                if mm.tiles:
                    m = Move(mm.tiles.replace("?", ""), row, col, horiz)
                    m.make_covers(game.state.board(), mm.tiles)

            elif not mm.tiles:
                # Degenerate (error) case: this game is stored incorrectly
                # in the NDB datastore. Probably an artifact of the move to
                # Google Cloud NDB.
                pass

            elif mm.tiles[0:4] == "EXCH":
                # Exchange move
                m = ExchangeMove(mm.tiles[5:])

            elif mm.tiles == "PASS":
                # Pass move
                m = PassMove()

            elif mm.tiles == "RSGN":
                # Game resigned
                m = ResignMove(-mm.score)

            elif mm.tiles == "CHALL":
                # Last move challenged
                m = ChallengeMove()

            elif mm.tiles == "RESP":
                # Response to challenge
                m = ResponseMove(mm.score)

            if m is None:
                # Something is wrong: mark the game as erroneous
                game._erroneous = True
            else:
                # Do a "shallow apply" of the move, which updates
                # the board and internal state variables but does
                # not modify the bag or the racks
                game.state.apply_move(m, shallow=True)
                # Append to the move history
                game.moves.append(
                    MoveTuple(player, m, mm.rack or "", mm.timestamp or now)
                )
                game.state.set_rack(player, mm.rack or "")

            player = 1 - player

        # Load the current racks
        game.state.set_rack(0, gm.rack0)
        game.state.set_rack(1, gm.rack1)

        # Find out what tiles are now in the bag
        game.state.recalc_bag()

        # Account for the final tiles in the rack and overtime, if any
        if game.is_over():
            game.finalize_score()
            if not gm.over and not game._erroneous:
                # The game was not marked as over when we loaded it from
                # the datastore, but it is over now. One of the players must
                # have lost on overtime. We need to update the persistent state.
                # (This also calls game.set_elo_delta())
                game._store_locked(calc_elo_points=True)
            else:
                # Fill in the game.elo_delta and game.elo_now dictionaries
                game.set_elo_delta(gm)

        return game

    def _store_locked(self, *, calc_elo_points: bool) -> None:
        """Store the game after having acquired the object lock"""

        assert self.uuid is not None

        gm = GameModel(id=self.uuid)
        assert self.timestamp is not None
        gm.timestamp = self.timestamp
        assert self.ts_last_move is not None
        gm.ts_last_move = self.ts_last_move
        gm.locale = self.locale
        gm.set_player(0, self.player_ids[0])
        gm.set_player(1, self.player_ids[1])
        gm.irack0 = self.initial_racks[0] or ""
        gm.irack1 = self.initial_racks[1] or ""
        assert self.state is not None
        gm.rack0 = self.state.rack(0)
        gm.rack1 = self.state.rack(1)
        gm.over = self.is_over()
        sc = self.final_scores()  # Includes adjustments if game is over
        gm.score0 = sc[0]
        gm.score1 = sc[1]
        gm.to_move = len(self.moves) % 2
        gm.robot_level = self.robot_level
        gm.prefs = self._preferences
        tile_count = 0
        movelist: List[MoveModel] = []
        for m in self.moves:
            mm = MoveModel()
            coord, tiles, score = m.move.summary(self.state)
            # Count the tiles actually laid down
            # Can be negative for a successful challenge
            tile_count += m.move.num_covers()
            mm.coord = coord
            mm.tiles = tiles
            mm.score = score
            mm.rack = m.rack
            mm.timestamp = m.ts
            movelist.append(mm)
        gm.moves = movelist
        gm.tile_count = tile_count

        # Storing a game that is now over: update the player statistics as well
        # (with the exception that if both scores are zero, the game is
        # not included in the statistics)
        if self.is_over() and (sc[0] > 0 or sc[1] > 0):
            # Accumulate best word statistics
            best_word: List[Optional[str]] = [None, None]
            best_word_score = [0, 0]
            player = 0
            for m in self.net_moves:  # Excludes successfully challenged moves
                coord, tiles, score = m.move.summary(self.state)
                if coord:
                    # Keep track of best words laid down by each player
                    if score > best_word_score[player]:
                        best_word_score[player] = score
                        best_word[player] = tiles
                player = 1 - player
            bw0, bw1 = best_word
            pid_0, pid_1 = self.player_ids
            u0 = User.load_if_exists(pid_0) if pid_0 else None
            u1 = User.load_if_exists(pid_1) if pid_1 else None
            if u0 is not None:
                if u1 is not None:
                    # This is a two-human-player game
                    u0.increment_human_games()
                u0.adjust_highest_score(sc[0], self.uuid)
                if bw0:
                    u0.adjust_best_word(bw0, best_word_score[0], self.uuid)
            if u1 is not None:
                if u0 is not None:
                    # This is a two-human-player game
                    u1.increment_human_games()
                u1.adjust_highest_score(sc[1], self.uuid)
                if bw1:
                    u1.adjust_best_word(bw1, best_word_score[1], self.uuid)

            if calc_elo_points:
                # We want to calculate provisional Elo points for the game
                # and store them with the game and the user(s).
                if u0 is not None and u1 is not None:
                    # Human-only game: calculate 'old style' Elo points
                    compute_elo_for_game(gm, u0, u1)
                    # Transfer the Elo deltas to the game object
                    self.set_elo_delta(gm)
                # Calculate 'new style', locale-specific Elo points
                # for the game and the users
                compute_locale_elo_for_game(gm, u0, u1)

            if u0 is not None:
                # Store the updated user entity
                u0.update()
            if u1 is not None:
                # Store the updated user entity
                u1.update()

        # Update the database entity (GameModel) for the game
        gm.put()

    def id(self) -> Optional[str]:
        """Returns the unique id of this game"""
        return self.uuid

    @property
    def preferences(self) -> Optional[PrefsDict]:
        """Return the game preferences, as a dictionary"""
        return self._preferences

    def player_nickname(self, index: int) -> str:
        """Returns the nickname of a player"""
        uid = self.player_ids[index]
        u = None if uid is None else User.load_if_exists(uid)
        if u is None:
            # This is an autoplayer
            nick = AutoPlayer.name(self.locale, self.robot_level)
        else:
            # This is a human user
            nick = u.nickname()
            if nick.startswith("https://") or nick.startswith("http://"):
                # Raw name (path) from Google Accounts:
                # use a more readable version
                locale = self.locale
                nick = UNDEFINED_NAME.get(locale, "")
                if not nick:
                    if "_" in locale:
                        nick = UNDEFINED_NAME.get(locale.split("_")[0], "")
                    if not nick:
                        nick = UNDEFINED_NAME["en"]
        return nick

    def player_fullname(self, index: int) -> str:
        """Returns the full name of a player"""
        uid = self.player_ids[index]
        u = None if uid is None else User.load_if_exists(uid)
        if u is None:
            # This is an autoplayer
            name = AutoPlayer.name(self.locale, self.robot_level)
        else:
            # This is a human user
            name = u.full_name().strip()
            if not name:
                # Try the nickname instead
                name = u.nickname()
                if name.startswith("https://") or name.startswith("http://"):
                    # Raw name (path) from Google Accounts:
                    # use a more readable version
                    locale = self.locale
                    name = UNDEFINED_NAME.get(locale, "")
                    if not name:
                        if "_" in locale:
                            name = UNDEFINED_NAME.get(locale.split("_")[0], "")
                        if not name:
                            name = UNDEFINED_NAME["en"]
        return name

    def set_elo_delta(self, gm: GameModel) -> None:
        """Collect Elo delta information from the GameModel.
        Only finished games have this info."""
        delta = EloDeltaDict()
        if gm.elo0_adj is not None and gm.elo1_adj is not None:
            delta["elo"] = (gm.elo0_adj, gm.elo1_adj)
        if gm.human_elo0_adj is not None and gm.human_elo1_adj is not None:
            delta["human"] = (gm.human_elo0_adj, gm.human_elo1_adj)
        if gm.manual_elo0_adj is not None and gm.manual_elo1_adj is not None:
            delta["manual"] = (gm.manual_elo0_adj, gm.manual_elo1_adj)
        if delta:
            self.elo_delta = delta
        # Note that elo_now is the Elo rating BEFORE applying the delta!
        now = EloNowDict()
        if gm.elo0 is not None and gm.elo1 is not None:
            now["elo"] = (gm.elo0, gm.elo1)
        if gm.human_elo0 is not None and gm.human_elo1 is not None:
            now["human"] = (gm.human_elo0, gm.human_elo1)
        if gm.manual_elo0 is not None and gm.manual_elo1 is not None:
            now["manual"] = (gm.manual_elo0, gm.manual_elo1)
        if now:
            self.elo_now = now

    def get_pref(self, pref: str) -> Union[None, str, int, bool]:
        """Retrieve a preference, or None if not found"""
        if self._preferences is None:
            return None
        return self._preferences.get(pref, None)

    def set_pref(self, pref: str, value: Union[str, int, bool]) -> None:
        """Set a preference to a value"""
        if self._preferences is None:
            self._preferences = {}
        self._preferences[pref] = value

    @staticmethod
    def fairplay_from_prefs(prefs: Optional[PrefsDict]) -> bool:
        """Returns the fairplay commitment specified
        by the given game preferences"""
        return prefs is not None and prefs.get("fairplay", False)

    def get_fairplay(self) -> bool:
        """True if this was originated as a fairplay game"""
        return cast(bool, self.get_pref("fairplay")) or False

    def set_fairplay(self, state: bool) -> None:
        """Set the fairplay commitment of this game"""
        self.set_pref("fairplay", state)

    @staticmethod
    def new_bag_from_prefs(prefs: Optional[PrefsDict]) -> bool:
        """Returns true if the game preferences specify a new bag"""
        return prefs is not None and prefs.get("newbag", False)

    def new_bag(self) -> bool:
        """True if this game uses the new bag"""
        return cast(bool, self.get_pref("newbag")) or False

    def set_new_bag(self, state: bool) -> None:
        """Configures the game as using the new bag"""
        self.set_pref("newbag", state)

    @staticmethod
    def manual_wordcheck_from_prefs(prefs: Optional[PrefsDict]) -> bool:
        """Returns true if the game preferences specify a manual wordcheck"""
        return prefs is not None and prefs.get("manual", False)

    def manual_wordcheck(self) -> bool:
        """True if this game uses manual wordcheck"""
        if self.is_robot_game():
            # A robot game always uses automatic wordcheck
            return False
        return cast(bool, self.get_pref("manual")) or False

    def set_manual_wordcheck(self, state: bool) -> None:
        """Configures the game as using manual wordcheck"""
        self.set_pref("manual", state)

    @property
    def board_type(self) -> str:
        """Return the type of the board used in this game"""
        return cast(str, self.get_pref("board_type")) or "standard"

    @staticmethod
    def locale_from_prefs(prefs: Optional[PrefsDict]) -> str:
        """Return the locale specified by the given game preferences"""
        if prefs is None:
            return DEFAULT_LOCALE
        return prefs.get("locale", DEFAULT_LOCALE)

    @property
    def locale(self) -> str:
        """Return the locale of this game"""
        return self._locale or cast(str, self.get_pref("locale")) or DEFAULT_LOCALE

    def set_locale(self, locale: str) -> None:
        """Set the locale of this game"""
        self._locale = locale
        return self.set_pref("locale", locale)

    def has_locale(self) -> bool:
        """Return True if this game has an assigned locale"""
        return bool(self._locale) or bool(self.get_pref("locale"))

    @staticmethod
    def tileset_from_prefs(locale: str, prefs: Optional[PrefsDict]) -> Type[TileSet]:
        """Returns the tileset specified by the given game preferences"""
        if prefs is None:
            # Stay backwards compatible with old version
            return OldTileSet
        lc = locale or Game.locale_from_prefs(prefs)
        if lc == "is_IS":
            # For Icelandic, there are two bags:
            # select one by preference setting
            new_bag = Game.new_bag_from_prefs(prefs)
            return NewTileSet if new_bag else OldTileSet
        # For other locales, use the mapping found in languages.py
        return tileset_for_locale(lc)

    @property
    def tileset(self):
        """Return the tile set used in this game"""
        return Game.tileset_from_prefs(self.locale, self._preferences)

    @property
    def two_letter_words(self) -> TwoLetterGroupTuple:
        """Return the two-letter list that applies to this game,
        as a tuple of two lists, one grouped by first letter, and
        the other grouped by the second (last) letter"""
        if self._two_letter_words is None:
            vocab = vocabulary_for_locale(self.locale)
            tw0, tw1 = Wordbase.two_letter_words(vocab)
            gr0, gr1 = groupby(tw0, lambda w: w[0]), groupby(tw1, lambda w: w[1])
            self._two_letter_words = (
                [(key, list(grp)) for key, grp in gr0],
                [(key, list(grp)) for key, grp in gr1],
            )
        return self._two_letter_words

    @property
    def net_moves(self) -> List[MoveTuple]:
        """Return a list of net moves, i.e. those that
        weren't successfully challenged"""
        if not self.manual_wordcheck():
            # No challenges possible: just return the complete move list
            return self.moves
        assert self.state is not None
        net_m: List[MoveTuple] = []
        for m in self.moves:
            if m.move.is_successful_challenge(self.state):
                # Successful challenge: Erase the two previous moves
                # (the challenge and the illegal move)
                assert len(net_m) >= 2
                del net_m[-1]
                del net_m[-1]
            else:
                # Not a successful challenge response: add to the net move list
                net_m.append(m)
        return net_m

    @staticmethod
    def get_duration_from_prefs(prefs: Optional[PrefsDict]) -> int:
        """Return the duration given a dict of game preferences"""
        return 0 if prefs is None else prefs.get("duration", 0)

    def get_duration(self) -> int:
        """Return the duration for each player in
        the game, e.g. 25 if 2x25 minute game"""
        return cast(int, self.get_pref("duration")) or 0

    def set_duration(self, duration: int) -> None:
        """Set the duration for each player in the game,
        e.g. 25 if 2x25 minute game"""
        self.set_pref("duration", duration)

    def is_overdue(self) -> bool:
        """Return True if no move has been made
        in the game for OVERDUE_DAYS days"""
        ts_last_move = self.ts_last_move or self.timestamp or datetime.now(UTC)
        delta = datetime.now(UTC) - ts_last_move
        return delta >= timedelta(days=Game.OVERDUE_DAYS)

    def get_elapsed(self) -> Tuple[float, float]:
        """Return the elapsed time for both players,
        in seconds, as a tuple"""
        elapsed = [0.0, 0.0]
        last_ts = self.timestamp or datetime.now(UTC)
        for m in self.moves:
            if m.ts is not None:
                delta = m.ts - last_ts
                last_ts = m.ts
                elapsed[m.player] += delta.total_seconds()
        if self.state is not None and not self.state.is_game_over():
            # Game still going on: Add the time from the last move until now
            delta = datetime.now(UTC) - last_ts
            elapsed[self.player_to_move()] += delta.total_seconds()
        return cast(Tuple[float, float], tuple(elapsed))

    def time_info(self) -> TimeInfo:
        """Returns a dict with timing information about this game"""
        return TimeInfo(duration=self.get_duration(), elapsed=self.get_elapsed())

    def overtime(self) -> Tuple[float, float]:
        """Return overtime for both players, in seconds"""
        overtime: List[float] = [0.0, 0.0]
        duration = self.get_duration() * 60.0  # In seconds
        if duration > 0.0:
            # Timed game: calculate the overtime
            el = self.get_elapsed()
            for player in range(2):
                overtime[player] = max(0.0, el[player] - duration)  # Never negative
        return cast(Tuple[float, float], tuple(overtime))

    def overtime_adjustment(self) -> Tuple[int, int]:
        """Return score adjustments due to overtime,
        as a tuple with two deltas"""
        overtime = self.overtime()
        adjustment = [0, 0]
        for player in range(2):
            if overtime[player] > 0.0:
                # 10 point subtraction for every started minute
                # The formula means that 0.1 second into a new minute
                # a 10-point loss is incurred
                # After 10 minutes, the game is lost and
                # the adjustment maxes out at -100
                adjustment[player] = max(
                    -100, -10 * ((int(overtime[player] + 0.9) + 59) // 60)
                )
        return cast(Tuple[int, int], tuple(adjustment))

    def is_over(self) -> bool:
        """Return True if the game is over"""
        if self._game_over:
            # Use the cached result if available and True
            return True
        if self.state is not None and self.state.is_game_over():
            self._game_over = True
            return True
        if self.get_duration() == 0:
            # Not a timed game: it's not over
            return False
        # Timed game: might now be lost on overtime
        # (even if waiting on a challenge)
        overtime = self.overtime()
        if any(overtime[ix] >= Game.MAX_OVERTIME for ix in range(2)):
            # The game has been lost on overtime
            self._game_over = True
            return True
        return False

    def winning_player(self) -> int:
        """Returns index of winning player,
        or -1 if game is tied or not over"""
        if not self.is_over():
            return -1
        sc = self.final_scores()
        if sc[0] > sc[1]:
            return 0
        if sc[1] > sc[0]:
            return 1
        return -1

    def finalize_score(self) -> None:
        """Adjust the score at the end of the game,
        accounting for left tiles, overtime, etc."""
        assert self.is_over()
        # Final adjustments to score, including
        # rack leave and overtime, if any
        overtime = self.overtime()
        # Check whether a player lost on overtime
        lost_on_overtime = None
        for player in range(2):
            if overtime[player] >= Game.MAX_OVERTIME:
                lost_on_overtime = player
                break
        assert self.state is not None
        self.state.finalize_score(lost_on_overtime, self.overtime_adjustment())

    def final_scores(self) -> Tuple[int, int]:
        """Return the final score of the game
        after adjustments, if any"""
        assert self.state is not None
        return self.state.final_scores()

    def allows_best_moves(self) -> bool:
        """Returns True if this game supports full review
        (has stored racks, etc.)"""
        if self.initial_racks[0] is None or self.initial_racks[1] is None:
            # This is an old game stored without rack information:
            # can't display best moves
            return False
        # Never show best moves for games that are still being played
        return self.is_over()

    def check_legality(self, move: MoveBase, validate: bool) -> Union[int, Tuple[int, str]]:
        """Check whether an incoming move from a client is legal and valid"""
        assert self.state is not None
        return self.state.check_legality(move, validate)

    def register_move(self, move: MoveBase) -> None:
        """Register a new move, updating the score
        and appending to the move list"""
        player_index = self.player_to_move()
        assert self.state is not None
        self.state.apply_move(move)
        self.ts_last_move = datetime.now(UTC)
        mt = MoveTuple(
            player_index, move, self.state.rack(player_index), self.ts_last_move
        )
        self.moves.append(mt)
        self.last_move = None  # No response move yet

    def autoplayer_move(self) -> None:
        """Generate an AutoPlayer move and register it"""
        # Create an appropriate AutoPlayer subclass instance
        # depending on the robot level in question
        assert self.state is not None
        apl = AutoPlayer.create(self.state, self.robot_level)
        move = apl.generate_move()
        self.register_move(move)
        self.last_move = move  # Store a response move

    def response_move(self) -> None:
        """Generate a response to a challenge move and register it"""
        move = ResponseMove()
        self.register_move(move)
        self.last_move = move  # Store the response move

    def best_moves(self, state: State, n: int) -> BestMoveList:
        """Returns a list of the n best moves available in the game,
        at the point described by the state parameter."""
        if not self.allows_best_moves():
            # The game is probably not finished:
            # querying for best moves is prohibited
            return []
        player_index = state.player_to_move()
        # Create an AutoPlayer instance that always finds the top-scoring moves
        apl = AutoPlayer(0, state)
        return [(player_index, m.summary(state)) for m, _ in apl.generate_best_moves(n)]

    def enum_tiles(
        self, state: Optional[State] = None
    ) -> Iterator[Tuple[str, str, str, int]]:
        """Enumerate all tiles on the board in a convenient form"""
        if state is None:
            state = self.state
        assert state is not None
        scores = self.tileset.scores
        for x, y, tile, letter in state.board().enum_tiles():
            yield (
                Board.ROWIDS[x] + str(y + 1),
                tile,
                letter,
                scores[tile],
            )

    def state_after_move(self, move_number: int) -> State:
        """Return a game state after the indicated move,
        0=beginning state"""
        # Initialize a fresh state object
        s = State(
            drawtiles=False,
            manual_wordcheck=self.manual_wordcheck(),
            tileset=self.tileset,
            locale=self.locale,
            board_type=self.board_type,
        )
        # Set up the initial state
        assert self.state is not None
        for ix in range(2):
            s.set_player_name(ix, self.state.player_name(ix))
            irack = self.initial_racks[ix]
            if irack is None:
                # Load the current rack rather than nothing
                s.set_rack(ix, self.state.rack(ix))
            else:
                # Load the initial rack
                s.set_rack(ix, irack)
        # Apply the moves up to the state point
        for m in self.moves[0:move_number]:
            s.apply_move(m.move, shallow=True)  # Shallow apply
            s.set_rack(m.player, m.rack)
        s.recalc_bag()
        return s

    def display_bag(self, player_index: int) -> str:
        """Returns the bag as it should be displayed to the indicated player,
        including the opponent's rack and sorted"""
        assert self.state is not None
        return self.state.display_bag(player_index)

    def num_moves(self) -> int:
        """Returns the number of moves in the game so far"""
        return len(self.moves)

    def is_erroneous(self) -> bool:
        """Return True if this game object is incorrectly serialized"""
        return self._erroneous

    def player_to_move(self) -> int:
        """Returns the index (0 or 1) of the player whose move it is"""
        assert self.state is not None
        return self.state.player_to_move()

    def player_id_to_move(self) -> Optional[str]:
        """Return the userid of the player whose turn it is,
        or None if autoplayer"""
        return self.player_ids[self.player_to_move()]

    def player_id(self, player_index: int) -> Optional[str]:
        """Return the userid of the indicated player"""
        return self.player_ids[player_index]

    def my_turn(self, user_id: str) -> bool:
        """Return True if it is the indicated player's turn to move"""
        if self.is_over():
            return False
        return self.player_id_to_move() == user_id

    def is_autoplayer(self, player_index: int) -> bool:
        """Return True if the player in question is an autoplayer"""
        return self.player_ids[player_index] is None

    def is_robot_game(self) -> bool:
        """Return True if one of the players is an autoplayer"""
        return self.is_autoplayer(0) or self.is_autoplayer(1)

    def player_index(self, user_id: str) -> Optional[int]:
        """Return the player index (0 or 1) of the given user,
        or None if not a player"""
        if self.player_ids[0] == user_id:
            return 0
        if self.player_ids[1] == user_id:
            return 1
        return None

    def has_player(self, user_id: str) -> bool:
        """Return True if the indicated user is a player of this game"""
        return self.player_index(user_id) is not None

    def start_time(self) -> str:
        """Returns the timestamp of the game in a readable format"""
        return (
            "" if self.timestamp is None else Alphabet.format_timestamp(self.timestamp)
        )

    def end_time(self) -> str:
        """Returns the time of the last move in a readable format"""
        return (
            ""
            if self.ts_last_move is None
            else Alphabet.format_timestamp(self.ts_last_move)
        )

    def _append_final_adjustments(self, movelist: List[MoveSummaryTuple]) -> None:
        """Appends final score adjustment transactions
        to the given movelist"""

        # Lastplayer is the player who finished the game
        lastplayer = self.moves[-1].player if self.moves else 0
        assert self.state is not None

        if not self.state.is_resigned():
            # If the game did not end by resignation, check for a timeout
            overtime = self.overtime()
            adjustment = list(self.overtime_adjustment())
            sc = self.state.scores()

            if any(overtime[ix] >= Game.MAX_OVERTIME for ix in range(2)):
                # 10 minutes overtime
                # Game ended with a loss on overtime
                ix = 0 if overtime[0] >= Game.MAX_OVERTIME else 1
                adjustment[1 - ix] = 0
                # Adjust score of losing player down by 100 points
                adjustment[ix] = -min(100, sc[ix])
                # If losing player is still winning on points, add points to the
                # winning player so that she leads by one point
                if sc[ix] + adjustment[ix] >= sc[1 - ix]:
                    adjustment[1 - ix] = sc[ix] + adjustment[ix] + 1 - sc[1 - ix]
            else:
                # Normal end of game
                opp_rack = self.state.rack(1 - lastplayer)
                opp_score = self.tileset.score(opp_rack)
                last_rack = self.state.rack(lastplayer)
                last_score = self.tileset.score(last_rack)
                if not last_rack:
                    # Finished with an empty rack:
                    # Add double the score of the opponent rack
                    movelist.append((1 - lastplayer, ("", "--", 0)))
                    movelist.append(
                        (lastplayer, ("", "2 * " + opp_rack, 2 * opp_score))
                    )
                elif not opp_rack:
                    # A manual check game that ended with
                    # no challenge to a winning final move
                    movelist.append(
                        (1 - lastplayer, ("", "2 * " + last_rack, 2 * last_score))
                    )
                    movelist.append((lastplayer, ("", "--", 0)))
                else:
                    # The game has ended by passes: each player gets
                    # their own rack subtracted
                    movelist.append((1 - lastplayer, ("", opp_rack, -1 * opp_score)))
                    movelist.append((lastplayer, ("", last_rack, -1 * last_score)))

            # If this is a timed game, add eventual overtime adjustment
            if tuple(adjustment) != (0, 0):
                movelist.append(
                    (1 - lastplayer, ("", "TIME", adjustment[1 - lastplayer]))
                )
                movelist.append((lastplayer, ("", "TIME", adjustment[lastplayer])))

        # Add a synthetic "game over" move
        movelist.append((1 - lastplayer, ("", "OVER", 0)))

    def get_final_adjustments(self) -> List[MoveSummaryTuple]:
        """Get a fresh list of the final adjustments made to the game score"""
        movelist: List[MoveSummaryTuple] = []
        self._append_final_adjustments(movelist)
        return movelist

    def is_challengeable(self) -> bool:
        """Return True if the last move in the game is challengeable"""
        assert self.state is not None
        return self.state.is_challengeable()

    def is_last_challenge(self) -> bool:
        """Return True if the last tile move has been made and
        is pending a challenge or pass"""
        assert self.state is not None
        return self.state.is_last_challenge()

    def client_state(
        self,
        player_index: Union[None, int],
        lastmove: Optional[MoveBase] = None,
        deep: bool = False,
    ) -> ClientStateDict:
        """Create a package of information for the client
        about the current state"""
        assert self.state is not None
        reply: ClientStateDict = ClientStateDict()
        num_moves = 1
        lm: Optional[MoveBase] = None
        succ_chall = False
        if self.last_move is not None:
            # Show the autoplayer or response move that was made
            lm = self.last_move
            num_moves = 2  # One new move to be added to move list
        elif lastmove is not None:
            # The indicated move should be included in the client state
            # (used when notifying an opponent of a new move through Firebase)
            lm = lastmove
        if lm is not None:
            reply["lastmove"] = lm.details(self.state)
            # Successful challenge?
            succ_chall = lm.is_successful_challenge(self.state)
        newmoves: List[Tuple[int, SummaryTuple]] = [
            (m.player, m.move.summary(self.state)) for m in self.moves[-num_moves:]
        ]

        assert self.state is not None
        if self.is_over():
            # The game is now over - one of the players finished it
            self._append_final_adjustments(newmoves)
            reply["result"] = Error.GAME_OVER  # Not really an error
            reply["xchg"] = False  # Exchange move not allowed
            reply["chall"] = False  # Challenge not allowed
            reply["last_chall"] = False  # Not in last challenge state
            reply["bag"] = self.state.bag().contents()
            reply["overdue"] = False
            if self.elo_delta is not None:
                # Include the Elo deltas for the players
                reply["elo_delta"] = self.elo_delta
            if self.elo_now is not None:
                # Include the Elo base scores for the players
                reply["elo_now"] = self.elo_now
        else:
            # Game is still in progress
            assert player_index is not None
            # ...but in a last-challenge state
            last_chall = self.state.is_last_challenge()
            reply["result"] = Error.LEGAL  # No error
            reply["xchg"] = False if last_chall else self.state.is_exchange_allowed()
            reply["chall"] = self.state.is_challengeable()
            reply["last_chall"] = last_chall
            reply["bag"] = self.display_bag(player_index)
            reply["overdue"] = self.is_overdue()

        if player_index is None:
            reply["rack"] = []
        else:
            reply["rack"] = self.state.rack_details(player_index)
        reply["num_moves"] = len(self.moves)
        reply["newmoves"] = newmoves
        reply["scores"] = self.final_scores()
        reply["progress"] = self.state.progress()
        reply["succ_chall"] = succ_chall  # Successful challenge
        reply["player"] = player_index  # Can be None if the game is over
        if self.get_duration():
            # Timed game: send information about elapsed time
            reply["time_info"] = self.time_info()
        # If deep=False, only the information above this line
        # is sent to the client. This applies to /submitmove responses
        # in a robot game, and updates sent via Firebase notifications
        # in human-vs-human games.
        # The /gamestate endpoint, in contrast, uses deep=True to obtain
        # the entire state of a game.
        if deep:
            # Send all moves so far to the client
            reply["moves"] = [
                (m.player, m.move.summary(self.state)) for m in self.moves[0:-num_moves]
            ]
            if self.is_over():
                # The game is over and this may be a game review:
                # Send the racks as they were before each move
                reply["racks"] = [
                    self.initial_racks[0] or self.state.rack(0),
                    self.initial_racks[1] or self.state.rack(1),
                ] + [m.rack for m in self.moves]
            # Player information
            reply["autoplayer"] = [self.is_autoplayer(0), self.is_autoplayer(1)]
            reply["nickname"] = [self.player_nickname(0), self.player_nickname(1)]
            reply["userid"] = [self.player_id(0), self.player_id(1)]
            reply["fullname"] = [self.player_fullname(0), self.player_fullname(1)]
            # Constant state
            reply["fairplay"] = self.get_fairplay()
            reply["newbag"] = self.new_bag()
            reply["manual"] = self.manual_wordcheck()
            reply["locale"] = self.locale
            reply["alphabet"] = self.tileset.alphabet.order
            reply["tile_scores"] = self.tileset.scores
            reply["board_type"] = self.board_type
            reply["two_letter_words"] = self.two_letter_words

        return reply

    def bingoes(self) -> Tuple[List[Tuple[str, int]], List[Tuple[str, int]]]:
        """Returns a tuple of lists of bingoes for both players"""
        # List all bingoes in the game
        assert self.state is not None
        bingoes = [
            (m.player, m.move.summary(self.state))
            for m in self.net_moves
            if m.move.is_bingo
        ]

        def _stripq(s: str) -> str:
            return s.replace("?", "")

        # Populate (word, score) tuples for each bingo for each player
        bingo0 = [(_stripq(ms[1]), ms[2]) for p, ms in bingoes if p == 0]
        bingo1 = [(_stripq(ms[1]), ms[2]) for p, ms in bingoes if p == 1]
        # noinspection PyRedundantParentheses
        return (bingo0, bingo1)

    def statistics(self) -> StatsDict:
        """Return a set of statistics on the game
        to be displayed by the client"""
        assert self.state is not None
        reply: StatsDict = dict()
        if self.is_over():
            # Indicate that the game is over (not really an error)
            reply["result"] = Error.GAME_OVER
        else:
            reply["result"] = 0  # Game still in progress
        reply["gamestart"] = self.start_time()
        reply["gameend"] = self.end_time()
        reply["duration"] = self.get_duration()
        reply["scores"] = sc = self.final_scores()
        # New bag?
        reply["newbag"] = self.new_bag()
        # Manual wordcheck?
        reply["manual"] = self.manual_wordcheck()
        # Number of moves made
        reply["moves0"] = m0 = (len(self.moves) + 1) // 2  # Floor division
        reply["moves1"] = m1 = (len(self.moves) + 0) // 2  # Floor division
        # Count bingoes and covers for moves that were not successfully challenged
        net_moves = self.net_moves
        ncovers = [(m.player, m.move.num_covers()) for m in net_moves]
        bingoes = [(p, nc == Rack.MAX_TILES) for p, nc in ncovers]
        # Number of bingoes (net of successful challenges)
        reply["bingoes0"] = sum([1 if p == 0 and bingo else 0 for p, bingo in bingoes])
        reply["bingoes1"] = sum([1 if p == 1 and bingo else 0 for p, bingo in bingoes])
        # Number of tiles laid down (net of successful challenges)
        reply["tiles0"] = t0 = sum([nc if p == 0 else 0 for p, nc in ncovers])
        reply["tiles1"] = t1 = sum([nc if p == 1 else 0 for p, nc in ncovers])
        blanks = [0, 0]
        letterscore = [0, 0]
        cleanscore = [0, 0]
        wrong_chall = [0, 0]  # Points gained by wrong challenges from opponent
        # Loop through the moves, collecting stats
        for m in net_moves:  # Omit successfully challenged moves
            _, wrd, msc = m.move.summary(self.state)
            if wrd == "RESP":
                assert msc > 0
                # Wrong challenge by opponent: add 10 points
                wrong_chall[m.player] += msc
            elif wrd != "RSGN":
                # Don't include a resignation penalty in the clean score
                cleanscore[m.player] += msc
            if m.move.num_covers() == 0:
                # Exchange, pass or resign move
                continue
            for _, tile, _, score in m.move.details(self.state):
                if tile == "?":
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
        # Score from wrong challenges by opponent
        reply["wrongchall0"] = wrong_chall[0]
        reply["wrongchall1"] = wrong_chall[1]
        # Contribution of overtime at the end of the game
        ov = self.overtime()
        if any(ov[ix] >= Game.MAX_OVERTIME for ix in range(2)):
            # Game was lost on overtime
            reply["remaining0"] = 0
            reply["remaining1"] = 0
            reply["overtime0"] = sc[0] - cleanscore[0] - wrong_chall[0]
            reply["overtime1"] = sc[1] - cleanscore[1] - wrong_chall[0]
        else:
            oa = self.overtime_adjustment()
            reply["overtime0"] = oa[0]
            reply["overtime1"] = oa[1]
            # Contribution of remaining tiles at the end of the game
            reply["remaining0"] = sc[0] - cleanscore[0] - oa[0] - wrong_chall[0]
            reply["remaining1"] = sc[1] - cleanscore[1] - oa[1] - wrong_chall[1]
        # Score ratios (percentages)
        totalsc = sc[0] + sc[1]
        reply["ratio0"] = (float(sc[0]) / totalsc * 100.0) if totalsc > 0 else 0.0
        reply["ratio1"] = (float(sc[1]) / totalsc * 100.0) if totalsc > 0 else 0.0
        return reply
