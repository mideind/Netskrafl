"""

    Game and User classes for netskrafl.is

    Copyright (C) 2021 Miðeind ehf.
    Author: Vilhjálmur Þorsteinsson

    The GNU Affero General Public License, version 3, applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This module implements the User and Game classes for the
    Netskrafl application. These classes form an intermediary
    layer between the web server frontend in netskrafl.py and the
    actual game logic in skraflplayer.py, skraflmechanics.py et al.

"""

# pylint: disable=too-many-lines

from __future__ import annotations

from typing import (
    Dict,
    TypedDict,
    Any,
    Optional,
    List,
    Union,
    Set,
    Tuple,
    NamedTuple,
    Iterable,
    Iterator,
    cast,
)

import threading

# import logging

from random import randint
from datetime import datetime, timedelta
from itertools import groupby
from functools import cached_property

from flask.helpers import url_for

from cache import memcache

from languages import Alphabet, OldTileSet, NewTileSet, vocabulary_for_locale
from skrafldb import (
    PrefItem,
    PrefsDict,
    Unique,
    UserModel,
    GameModel,
    MoveModel,
    FavoriteModel,
    ChallengeModel,
    StatsModel,
    ChatModel,
    BlockModel,
    ReportModel,
)
from dawgdictionary import Wordbase
from skraflmechanics import (
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
)
from skraflplayer import AutoPlayer

# Type definitions
StatsDict = Dict[str, Union[str, int, float, Tuple[int, int]]]
# Tuple for storing move data within a Game
MoveTuple = NamedTuple(
    "MoveTuple",
    [("player", int), ("move", MoveBase), ("rack", str), ("ts", datetime),],
)
TwoLetterGroupList = List[Tuple[str, List[str]]]
TwoLetterGroupTuple = Tuple[TwoLetterGroupList, TwoLetterGroupList]


class UserSummaryDict(TypedDict):

    """ Summary data about a user """

    uid: str
    nick: str
    name: str
    image: str


class User:

    """Information about a human user including nickname and preferences"""

    # Use a lock to avoid potential race conditions between
    # the memcache and the database
    _lock = threading.Lock()

    # User object expiration in memcache/Redis, measured in seconds
    _CACHE_EXPIRY = 15 * 60  # 15 minutes

    # Current namespace (schema) for memcached User objects
    # Upgraded from 4 to 5 after adding locale attribute
    # Upgraded from 5 to 6 after adding location attribute
    # Upgraded from 6 to 7 after adding timestamp with conversion to/from isoformat
    _NAMESPACE = "user:7"

    # Default Elo points if not explicitly assigned
    DEFAULT_ELO = 1200

    def __init__(
        self,
        uid: Optional[str] = None,
        account: Optional[str] = None,
        locale: Optional[str] = None,
    ) -> None:
        """Initialize a fresh User instance"""
        self._user_id = uid
        self._account = account
        self._email: Optional[str] = None
        self._nickname = ""
        self._inactive: bool = False
        self._locale = locale or "is_IS"
        self._preferences: PrefsDict = {}
        self._ready: bool = False
        self._ready_timed: bool = False
        self._chat_disabled: bool = False
        self._elo = 0
        self._human_elo = 0
        self._manual_elo = 0
        self._highest_score = 0
        self._highest_score_game: Optional[str] = None
        self._best_word: Optional[str] = None
        self._best_word_score = 0
        self._best_word_game: Optional[str] = None
        # Set of favorite users, only loaded upon demand
        self._favorites: Optional[Set[str]] = None
        # Set of blocked users, only loaded upon demand
        self._blocks: Optional[Set[str]] = None
        self._image: str = ""
        self._has_image_blob: bool = False
        self._timestamp = datetime.utcnow()
        # The user location is typically an ISO country code
        self._location: str = ""

        # NOTE: When new properties are added, the memcache namespace version id
        # (User._NAMESPACE, above) should be incremented!

    def _init(self, um: UserModel) -> None:
        """Obtain the properties from the database entity"""
        self._account = um.account
        self._email = um.email
        self._nickname = um.nickname
        self._inactive = um.inactive
        self._locale = um.locale or "is_IS"
        self._preferences = um.prefs
        self._ready = False if um.ready is None else um.ready
        self._ready_timed = False if um.ready_timed is None else um.ready_timed
        self._chat_disabled = False if um.chat_disabled is None else um.chat_disabled
        self._elo = um.elo
        self._human_elo = um.human_elo
        self._manual_elo = um.manual_elo
        self._highest_score = um.highest_score
        self._highest_score_game = um.highest_score_game
        self._best_word = um.best_word
        self._best_word_score = um.best_word_score
        self._best_word_game = um.best_word_game
        self._image = um.image or ""
        self._has_image_blob = bool(um.image_blob)
        self._timestamp = um.timestamp
        self._location = um.location or ""

    def update(self) -> None:
        """Update the user's record in the database and in the memcache"""
        with User._lock:
            # Use a lock to avoid the scenaro where a user
            # is fetched by another request in the interval
            # between a database update and a memcache update
            assert self._user_id is not None
            um = UserModel.fetch(self._user_id)
            assert um is not None
            um.account = self._account
            um.email = self._email
            um.nickname = self._nickname
            um.nick_lc = self._nickname.lower()
            um.name_lc = self.full_name().lower()
            um.inactive = self._inactive
            um.locale = self._locale or "is_IS"
            um.prefs = self._preferences
            um.ready = self._ready
            um.ready_timed = self._ready_timed
            um.chat_disabled = self._chat_disabled
            um.elo = self._elo
            um.human_elo = self._human_elo
            um.manual_elo = self._manual_elo
            um.highest_score = self._highest_score
            um.highest_score_game = self._highest_score_game
            um.best_word = self._best_word
            um.best_word_score = self._best_word_score
            um.best_word_game = self._best_word_game
            um.image = self._image
            if not self._has_image_blob:
                um.image_blob = None
            um.location = self._location
            # um.timestamp should not be set or updated
            um.put()

            # Note: the namespace version should be incremented each time
            # that the class properties change
            memcache.set(
                self._user_id, self, time=User._CACHE_EXPIRY, namespace=User._NAMESPACE
            )

    def id(self) -> Optional[str]:
        """Returns the id (database key) of the user"""
        return self._user_id

    def nickname(self) -> str:
        """Returns the human-readable nickname of a user,
        or userid if a nick is not available"""
        return self._nickname or self._user_id or ""

    def set_nickname(self, nickname: str) -> None:
        """Sets the human-readable nickname of a user"""
        self._nickname = nickname

    def timestamp(self) -> datetime:
        """ Creation date and time for this user """
        return self._timestamp

    @staticmethod
    def is_valid_nick(nick: str) -> bool:
        """Check whether a nickname is valid and displayable"""
        if not nick:
            return False
        return nick[0:8] != "https://" and nick[0:7] != "http://"

    def human_elo(self) -> int:
        """Return the human-only Elo points of the user"""
        return self._human_elo or User.DEFAULT_ELO

    def manual_elo(self) -> int:
        """Return the human-only, manual-game-only Elo points of the user"""
        return self._manual_elo or User.DEFAULT_ELO

    def is_inactive(self) -> bool:
        """Return True if the user is marked as inactive"""
        return self._inactive

    def is_displayable(self) -> bool:
        """Returns True if this user should appear in user lists"""
        if self._inactive:
            # Inactive users are hidden
            return False
        # Nicknames that haven't been properly set aren't displayed
        return User.is_valid_nick(self._nickname)

    @property
    def preferences(self) -> PrefsDict:
        """Return the game preferences as a dictionary"""
        return self._preferences

    @property
    def locale(self) -> str:
        """Get the locale code for this user"""
        return self._locale or "is_IS"

    def set_locale(self, locale: str) -> None:
        """Set the locale code for this user"""
        self._locale = locale

    @property
    def location(self) -> str:
        """Get the location code for this user"""
        return self._location or ""

    def set_location(self, location: str) -> None:
        """Set the location code for this user"""
        self._location = location

    def get_pref(
        self, pref: str, default: Optional[PrefItem] = None
    ) -> Optional[PrefItem]:
        """Retrieve a preference, or None if not found"""
        if self._preferences is None:
            return None
        return self._preferences.get(pref, default)

    def get_string_pref(self, pref: str, default: str = "") -> str:
        """Retrieve a string preference, or "" if not found"""
        if self._preferences is None:
            return default
        val = self._preferences.get(pref, default)
        return val if isinstance(val, str) else default

    def get_bool_pref(self, pref: str, default: bool = False) -> bool:
        """Retrieve a string preference, or "" if not found"""
        if self._preferences is None:
            return default
        val = self._preferences.get(pref, default)
        return val if isinstance(val, bool) else default

    def set_pref(self, pref: str, value: PrefItem) -> None:
        """Set a preference to a value"""
        if self._preferences is None:
            self._preferences = {}
        self._preferences[pref] = value

    @staticmethod
    def full_name_from_prefs(prefs: Optional[PrefsDict]) -> str:
        """Returns the full name of a user from a dict of preferences"""
        if prefs is None:
            return ""
        fn = prefs.get("full_name")
        return fn if fn is not None and isinstance(fn, str) else ""

    def full_name(self) -> str:
        """Returns the full name of a user"""
        return self.get_string_pref("full_name")

    def set_full_name(self, full_name: str) -> None:
        """Sets the full name of a user"""
        self.set_pref("full_name", full_name)

    def email(self) -> str:
        """Returns the e-mail address of a user"""
        return self.get_string_pref("email", self._email or "")

    def set_email(self, email: str) -> None:
        """Sets the e-mail address of a user"""
        self.set_pref("email", email)

    def audio(self) -> bool:
        """Returns True if the user wants audible signals"""
        # True by default
        return self.get_bool_pref("audio", True)

    def set_audio(self, audio: bool) -> None:
        """Sets the audio preference of a user to True or False"""
        assert isinstance(audio, bool)
        self.set_pref("audio", audio)

    def image(self) -> str:
        """Returns the URL of an image (photo/avatar) of a user"""
        if not self._user_id:
            return ""
        if self._has_image_blob:
            # We have a stored BLOB for this user: return a URL to it
            return url_for("api.image", uid=self._user_id)
        # We have a stored URL: return it
        return self._image or ""

    def set_image(self, image: str) -> None:
        """Sets the URL of an image (photo/avatar) of a user"""
        # Note: For associating a user with an image BLOB,
        # refer to the /image endpoint in api.py.
        # This call erases any BLOB already associated with the user!
        self._image = image
        self._has_image_blob = False

    def fanfare(self) -> bool:
        """Returns True if the user wants a fanfare sound when winning"""
        return self.get_bool_pref("fanfare", True)

    def set_fanfare(self, fanfare: bool) -> None:
        """Sets the fanfare preference of a user to True or False"""
        self.set_pref("fanfare", fanfare)

    def beginner(self) -> bool:
        """Returns True if the user is a beginner so we show help panels, etc."""
        # True by default
        return self.get_bool_pref("beginner", True)

    def set_beginner(self, beginner: bool) -> None:
        """Sets the beginner state of a user to True or False"""
        self.set_pref("beginner", beginner)

    @staticmethod
    def fairplay_from_prefs(prefs: Optional[PrefsDict]) -> bool:
        """Returns the fairplay preference of a user"""
        if prefs is None:
            return False
        fp = prefs.get("fairplay")
        return isinstance(fp, bool) and fp

    def fairplay(self) -> bool:
        """Returns True if the user has committed to a fair play statement"""
        # False by default
        return self.get_bool_pref("fairplay", False)

    def set_fairplay(self, state: bool) -> None:
        """Sets the fairplay state of a user to True or False"""
        self.set_pref("fairplay", state)

    @staticmethod
    def new_bag_from_prefs(prefs: Optional[PrefsDict]) -> bool:
        """Returns the new bag preference of a user"""
        if prefs is None:
            return False
        newbag = prefs.get("newbag")
        # True by default
        return newbag if isinstance(newbag, bool) else True

    def new_bag(self) -> bool:
        """Returns True if the user would like to play with the new bag"""
        # True by default
        return self.get_bool_pref("newbag", True)

    def set_new_bag(self, state: bool) -> None:
        """Sets the new bag preference of a user to True or False"""
        self.set_pref("newbag", state)

    @staticmethod
    def friend_from_prefs(prefs: Optional[PrefsDict]) -> bool:
        """Returns True if the user is a friend of Netskrafl"""
        if prefs is None:
            return False
        friend = prefs.get("friend")
        return isinstance(friend, bool) and friend

    def friend(self) -> bool:
        """Returns True if the user is a friend of Netskrafl"""
        # False by default
        return self.get_bool_pref("friend", False)

    def set_friend(self, state: bool) -> None:
        """Sets the friend status of a user to True or False"""
        self.set_pref("friend", state)

    @staticmethod
    def has_paid_from_prefs(prefs: Optional[PrefsDict]) -> bool:
        """Returns True if the user is a paying friend of Netskrafl"""
        if prefs is None:
            return False
        if not User.friend_from_prefs(prefs):
            # Must be a friend before being a paying friend
            return False
        has_paid = prefs.get("haspaid")
        return isinstance(has_paid, bool) and has_paid

    def has_paid(self) -> bool:
        """Returns True if the user is a paying friend of Netskrafl"""
        if not self.friend():
            # Must be a friend before being a paying friend
            return False
        # False by default
        return self.get_bool_pref("haspaid", False)

    def set_has_paid(self, state: bool) -> None:
        """Sets the payment status of a user to True or False"""
        self.set_pref("haspaid", state)

    def is_ready(self) -> bool:
        """Returns True if the user is ready to accept challenges"""
        return self._ready

    def set_ready(self, ready: bool) -> None:
        """Sets the ready state of a user to True or False"""
        self._ready = ready

    def is_ready_timed(self) -> bool:
        """Returns True if the user is ready for timed games"""
        return self._ready_timed

    def set_ready_timed(self, ready: bool) -> None:
        """Sets the whether a user is ready for timed games"""
        self._ready_timed = ready

    def chat_disabled(self) -> bool:
        """Returns True if the user has disabled chat"""
        return self._chat_disabled

    def disable_chat(self, disabled: bool) -> None:
        """Sets the ready state of a user to True or False"""
        self._chat_disabled = disabled

    def _load_favorites(self) -> None:
        """Loads favorites of this user from the database into a set in memory"""
        if hasattr(self, "_favorites") and self._favorites:
            # Already have the favorites in memory
            return
        sid = self.id()
        assert sid is not None
        self._favorites = set(FavoriteModel.list_favorites(sid))

    def add_favorite(self, destuser_id: str) -> None:
        """Add an A-favors-B relation between this user and the destuser"""
        sid = self.id()
        assert sid is not None
        self._load_favorites()
        assert self._favorites is not None
        self._favorites.add(destuser_id)
        FavoriteModel.add_relation(sid, destuser_id)

    def del_favorite(self, destuser_id: str) -> None:
        """Delete an A-favors-B relation between this user and the destuser"""
        sid = self.id()
        assert sid is not None
        self._load_favorites()
        assert self._favorites is not None
        self._favorites.discard(destuser_id)
        FavoriteModel.del_relation(sid, destuser_id)

    def has_favorite(self, destuser_id: str) -> bool:
        """Returns True if there is an A-favors-B relation between this user and the destuser"""
        self._load_favorites()
        assert self._favorites is not None
        return destuser_id in self._favorites

    def _load_blocks(self) -> None:
        """Loads blocked users into a set in memory"""
        if hasattr(self, "_blocks") and self._blocks:
            # Already have the blocks in memory
            return
        sid = self.id()
        assert sid is not None
        self._blocks = set(BlockModel.list_blocked_users(sid))

    def block(self, destuser_id: str) -> bool:
        """Add an A-blocks-B relation between this user and the destuser"""
        if not destuser_id:
            return False
        sid = self.id()
        assert sid is not None
        self._load_blocks()
        assert self._blocks is not None
        if not BlockModel.block_user(sid, destuser_id):
            return False
        self._blocks.add(destuser_id)
        return True

    def unblock(self, destuser_id: str) -> bool:
        """Delete an A-favors-B relation between this user and the destuser"""
        if not destuser_id:
            return False
        sid = self.id()
        assert sid is not None
        self._load_blocks()
        assert self._blocks is not None
        if not BlockModel.unblock_user(sid, destuser_id):
            return False
        self._blocks.discard(destuser_id)
        return True

    def has_blocked(self, destuser_id: str) -> bool:
        """Returns True if there is an A-favors-B relation between this user and the destuser"""
        if not destuser_id:
            return False
        self._load_blocks()
        assert self._blocks is not None
        return destuser_id in self._blocks

    def list_blocked(self) -> List[UserSummaryDict]:
        """Returns a list of users blocked by this user"""
        self._load_blocks()
        assert self._blocks is not None
        result: List[UserSummaryDict] = []
        for uid in self._blocks:
            u = User.load_if_exists(uid)
            if u is not None:
                result.append(
                    UserSummaryDict(
                        uid=uid, nick=u.nickname(), name=u.full_name(), image=u.image()
                    )
                )
        return result

    def report(self, destuser_id: str, code: int, text: str) -> bool:
        """The current user is reporting another user"""
        if not destuser_id:
            return False
        sid = self.id()
        assert sid is not None
        return ReportModel.report_user(sid, destuser_id, code, text)

    def has_challenge(self, destuser_id: str) -> bool:
        """Returns True if this user has challenged destuser"""
        # TBD: Cache this in the user object to save NDB reads
        return ChallengeModel.has_relation(self.id(), destuser_id)

    def find_challenge(self, srcuser_id: str) -> Tuple[bool, Optional[PrefsDict]]:
        """Returns (found, prefs)"""
        return ChallengeModel.find_relation(srcuser_id, self.id())

    def issue_challenge(self, destuser_id: str, prefs: Optional[PrefsDict]) -> None:
        """Issue a challenge to the destuser"""
        sid = self.id()
        assert sid is not None
        ChallengeModel.add_relation(sid, destuser_id, prefs)

    def retract_challenge(self, destuser_id: str, *, key: Optional[str] = None) -> None:
        """Retract a challenge previously issued to the destuser"""
        sid = self.id()
        assert sid is not None
        ChallengeModel.del_relation(sid, destuser_id, key)

    def decline_challenge(self, srcuser_id: str, *, key: Optional[str] = None) -> None:
        """Decline a challenge previously issued by the srcuser"""
        sid = self.id()
        assert sid is not None
        ChallengeModel.del_relation(srcuser_id, sid, key)

    def accept_challenge(self, srcuser_id: str, *, key: Optional[str] = None) -> Tuple[bool, Optional[PrefsDict]]:
        """Decline a challenge previously issued by the srcuser"""
        # Delete the accepted challenge and return the associated preferences
        sid = self.id()
        assert sid is not None
        return ChallengeModel.del_relation(srcuser_id, sid, key)

    def adjust_highest_score(self, score: int, game_uuid: str) -> bool:
        """If this is the highest score of the player, modify it"""
        if self._highest_score and self._highest_score >= score:
            # Not a new record
            return False
        # New record
        self._highest_score = score
        self._highest_score_game = game_uuid
        return True

    def adjust_best_word(self, word: str, score: int, game_uuid: str) -> bool:
        """If this is the highest scoring word of the player, modify it"""
        if self._best_word_score and self._best_word_score >= score:
            # Not a new record
            return False
        # New record
        self._best_word = word
        self._best_word_score = score
        self._best_word_game = game_uuid
        return True

    @classmethod
    def load_if_exists(cls, uid: Optional[str]) -> Optional[User]:
        """Load a user by id if she exists, otherwise return None"""
        if not uid:
            return None
        with User._lock:
            u = memcache.get(uid, namespace=User._NAMESPACE)
            if u is not None:
                return u
            um = UserModel.fetch(uid)
            if um is None:
                return None
            u = cls(uid=uid)
            u._init(um)
            memcache.add(uid, u, time=User._CACHE_EXPIRY, namespace=User._NAMESPACE)
            return u

    @classmethod
    def load_multi(cls, uids: Iterable[str]) -> List[User]:
        """Load multiple users from persistent storage, given their user id"""
        user_list: List[User] = []
        with User._lock:
            for um in UserModel.fetch_multi(uids):
                if um is not None:
                    u = cls(uid=um.user_id())
                    u._init(um)
                    user_list.append(u)
        return user_list

    @classmethod
    def login_by_account(
        cls,
        account: str,
        name: str,
        email: str,
        image: str,
        *,
        locale: Optional[str] = None
    ):
        """Log in a user via the given Google Account and return her user id"""
        # First, see if the user account already exists under the Google account id
        um = UserModel.fetch_account(account)
        if um is not None:
            # We've seen this user account before
            if image and image != um.image:
                # Use the opportunity to update the image, if different
                um.image = image
            if email and email != um.email:
                # Use the opportunity to update the email, if different
                # (This should probably not happen very often)
                um.email = email
            # Note the login timestamp
            um.last_login = datetime.utcnow()
            um.put()
            # Note that the user id might not be the Google account id!
            # Instead, it could be the old GAE user id.
            return um.user_id()
        # We haven't seen this Google Account before: try to match by email
        if email:
            um = UserModel.fetch_email(email)
            if um is not None:
                # We probably have an older (GAE) user for this email:
                # Associate the account with it from now on (but keep the old id)
                # logging.info("Login: Unknown account {0}, but email {1} matched existing account of '{2}'"
                #     .format(account, email, name)
                # )
                um.account = account
                if image and image != um.image:
                    # Use the opportunity to update the image, if different
                    um.image = image
                # Note the last login
                um.last_login = datetime.utcnow()
                return um.put().id()
        # No match by account id or email: create a new user,
        # with the account id as user id.
        # New users are created with the new bag as default,
        # and we also capture the email and the full name.
        # logging.info("Login: Unknown account {0} and email {1}; creating new user for '{2}'"
        #     .format(account, email, name)
        # )
        nickname = email.split("@")[0] or name.split()[0]
        prefs: PrefsDict = {"newbag": True, "email": email, "full_name": name}
        return UserModel.create(
            user_id=account,
            account=account,
            email=email,
            nickname=nickname,
            image=image,
            preferences=prefs,
            locale=locale,
        )

    def to_serializable(self) -> Dict[str, Any]:
        """Convert to JSON-serializable format"""
        d: Dict[str, Any] = dict(**self.__dict__)
        del d["_favorites"]
        del d["_blocks"]
        d["_timestamp"] = self._timestamp.isoformat()
        return d

    @classmethod
    def from_serializable(cls, j: Dict[str, Any]) -> User:
        """Create a fresh instance from a JSON-serialized object"""
        u = cls(uid=j["_user_id"])
        u.__dict__ = j
        u._favorites = None
        u._blocks = None
        u._timestamp = datetime.fromisoformat(j["_timestamp"])
        return u

    def profile(self) -> Dict[str, Any]:
        """Return a set of key statistics on the user"""
        reply: Dict[str, Any] = dict()
        user_id = self.id()
        assert user_id is not None
        reply["result"] = Error.LEGAL
        reply["nickname"] = self.nickname()
        reply["fullname"] = self.full_name()
        reply["image"] = self.image()
        reply["friend"] = self.friend()
        reply["has_paid"] = self.has_paid()
        reply["locale"] = self.locale
        reply["location"] = self.location
        # Format the user timestamp as YYYY-MM-DD HH:MM:SS
        reply["timestamp"] = Alphabet.format_timestamp(self.timestamp())
        reply["accepts_challenges"] = self.is_ready()
        reply["accepts_timed"] = self.is_ready_timed()
        reply["chat_disabled"] = self.chat_disabled()
        # Add statistics from the user entity
        reply["highest_score"] = self._highest_score
        reply["highest_score_game"] = self._highest_score_game
        reply["best_word"] = self._best_word
        reply["best_word_score"] = self._best_word_score
        reply["best_word_game"] = self._best_word_game
        # Add Elo statistics
        sm = StatsModel.newest_for_user(user_id)
        if sm is not None:
            sm.populate_dict(reply)
        return reply


class Game:

    """A wrapper class for a particular game that is in process
    or completed. Contains inter alia a State instance."""

    # The available autoplayers (robots)
    AUTOPLAYERS = [
        ("Fullsterkur", "Velur stigahæsta leik í hverri stöðu", 0,),
        (
            "Miðlungur",
            "Forðast allra sjaldgæfustu orðin; velur úr 10 stigahæstu leikjum",
            8,
        ),
        (
            "Amlóði",
            "Forðast sjaldgæf orð og velur úr 20 leikjum sem koma til álita",
            15,
        ),
    ]

    # The default nickname to display if a player has an unreadable nick
    # (for instance a default Google nick with a https:// prefix)
    UNDEFINED_NAME = "[Ónefndur]"

    # The maximum overtime in a game, after which a player automatically loses
    MAX_OVERTIME = 10 * 60.0  # 10 minutes, in seconds

    # After this number of days the game becomes overdue and the
    # waiting player can force the tardy opponent to resign
    OVERDUE_DAYS = 14

    _lock = threading.Lock()

    def __init__(self, uuid: Optional[str] = None) -> None:
        # Unique id of the game
        self.uuid = uuid
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
        self.timestamp = self.ts_last_move = datetime.utcnow()

    @classmethod
    def new(
        cls,
        player0_id: Optional[str],
        player1_id: Optional[str],
        robot_level: int = 0,
        prefs: Optional[PrefsDict] = None,
    ) -> Game:
        """Start and initialize a new game"""
        game = cls(Unique.id())  # Assign a new unique id to the game
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
    def load(cls, uuid: str, use_cache: bool = True) -> Optional[Game]:
        """Load an already existing game from persistent storage"""
        with Game._lock:
            # Ensure that the game load does not introduce race conditions
            return cls._load_locked(uuid, use_cache)

    def store(self) -> None:
        """Store the game state in persistent storage"""
        # Avoid race conditions by securing the lock before storing
        with Game._lock:
            self._store_locked()

    @classmethod
    def _load_locked(cls, uuid: str, use_cache: bool = True) -> Optional[Game]:
        """Load an existing game from cache or persistent storage under lock"""

        gm = GameModel.fetch(uuid, use_cache)
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

        # A player_id of None means that the player is an autoplayer (robot)
        game.player_ids[0] = gm.player0_id()
        game.player_ids[1] = gm.player1_id()

        game.robot_level = gm.robot_level

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
        now = datetime.utcnow()

        for mm in gm.moves:

            # logging.info("Game move {0} tiles '{3}' score is {1}:{2}"
            # .format(mx, game.state._scores[0], game.state._scores[1], mm.tiles))

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
                if mm.tiles is not None:
                    m = Move(mm.tiles.replace("?", ""), row, col, horiz)
                    m.make_covers(game.state.board(), mm.tiles)

            elif mm.tiles is None:

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
                game._store_locked()

        return game

    def _store_locked(self) -> None:
        """Store the game after having acquired the object lock"""

        assert self.uuid is not None

        gm = GameModel(id=self.uuid)
        gm.timestamp = cast(datetime, self.timestamp)
        gm.ts_last_move = cast(datetime, self.ts_last_move)
        gm.set_player(0, self.player_ids[0])
        gm.set_player(1, self.player_ids[1])
        gm.irack0 = cast(str, self.initial_racks[0])
        gm.irack1 = cast(str, self.initial_racks[1])
        assert self.state is not None
        gm.rack0 = self.state.rack(0)
        gm.rack1 = self.state.rack(1)
        gm.over = self.is_over()
        sc = self.final_scores()  # Includes adjustments if game is over
        gm.score0 = sc[0]
        gm.score1 = sc[1]
        gm.to_move = len(self.moves) % 2
        gm.robot_level = self.robot_level
        gm.prefs = cast(PrefsDict, self._preferences)
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
        # Update the database entity
        gm.put()

        # Storing a game that is now over: update the player statistics as well
        if self.is_over():
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
            if u0:
                mod_0 = u0.adjust_highest_score(sc[0], self.uuid)
                if bw0:
                    mod_0 |= u0.adjust_best_word(bw0, best_word_score[0], self.uuid)
                if mod_0:
                    # Modified: store the updated user entity
                    u0.update()
            if u1:
                mod_1 = u1.adjust_highest_score(sc[1], self.uuid)
                if bw1:
                    mod_1 |= u1.adjust_best_word(bw1, best_word_score[1], self.uuid)
                if mod_1:
                    # Modified: store the updated user entity
                    u1.update()

    def id(self) -> Optional[str]:
        """Returns the unique id of this game"""
        return self.uuid

    @property
    def preferences(self) -> Optional[PrefsDict]:
        """Return the game preferences, as a dictionary"""
        return self._preferences

    @staticmethod
    def autoplayer_name(level: int) -> str:
        """Return the autoplayer name for a given level"""
        i = len(Game.AUTOPLAYERS)
        while i > 0:
            i -= 1
            if level >= Game.AUTOPLAYERS[i][2]:
                return Game.AUTOPLAYERS[i][0]
        return Game.AUTOPLAYERS[0][0]  # Strongest player by default

    def player_nickname(self, index: int) -> str:
        """Returns the nickname of a player"""
        u = (
            None
            if self.player_ids[index] is None
            else User.load_if_exists(self.player_ids[index])
        )
        if u is None:
            # This is an autoplayer
            nick = Game.autoplayer_name(self.robot_level)
        else:
            # This is a human user
            nick = u.nickname()
            if nick[0:8] == "https://":
                # Raw name (path) from Google Accounts:
                # use a more readable version
                nick = Game.UNDEFINED_NAME
        return nick

    def player_fullname(self, index: int) -> str:
        """Returns the full name of a player"""
        u = (
            None
            if self.player_ids[index] is None
            else User.load_if_exists(self.player_ids[index])
        )
        if u is None:
            # This is an autoplayer
            name = Game.autoplayer_name(self.robot_level)
        else:
            # This is a human user
            name = u.full_name().strip()
            if not name:
                name = u.nickname()
                if name[0:8] == "https://":
                    # Raw name (path) from Google Accounts:
                    # use a more readable version
                    name = Game.UNDEFINED_NAME
        return name

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
        return prefs is not None and cast(bool, prefs.get("fairplay", False))

    def get_fairplay(self) -> bool:
        """True if this was originated as a fairplay game"""
        return cast(bool, self.get_pref("fairplay")) or False

    def set_fairplay(self, state: bool) -> None:
        """Set the fairplay commitment of this game"""
        self.set_pref("fairplay", state)

    @staticmethod
    def new_bag_from_prefs(prefs: Optional[PrefsDict]) -> bool:
        """Returns true if the game preferences specify a new bag"""
        return prefs is not None and cast(bool, prefs.get("newbag", False))

    def new_bag(self) -> bool:
        """True if this game uses the new bag"""
        return cast(bool, self.get_pref("newbag")) or False

    def set_new_bag(self, state: bool) -> None:
        """Configures the game as using the new bag"""
        self.set_pref("newbag", state)

    @staticmethod
    def manual_wordcheck_from_prefs(prefs: Optional[PrefsDict]) -> bool:
        """Returns true if the game preferences specify a manual wordcheck"""
        return prefs is not None and cast(bool, prefs.get("manual", False))

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

    @property
    def locale(self) -> str:
        """Return the locale of this game"""
        return cast(str, self.get_pref("locale")) or "is_IS"

    @staticmethod
    def tileset_from_prefs(prefs: Optional[PrefsDict]):
        """Returns the tileset specified by the given game preferences"""
        if prefs is None:
            # Stay backwards compatible with old version
            return OldTileSet
        lc = cast(str, prefs.get("locale", "is_IS"))
        if lc == "is_IS":
            # For Icelandic, there are two bags:
            # select one by preference setting
            new_bag = Game.new_bag_from_prefs(prefs)
            return NewTileSet if new_bag else OldTileSet
        # For other locales, use the Alphabet mapping found in languages.py
        return Alphabet.tileset_for_locale(lc)

    @property
    def tileset(self):
        """Return the tile set used in this game"""
        return Game.tileset_from_prefs(self._preferences)

    @cached_property
    def two_letter_words(self) -> TwoLetterGroupTuple:
        """Return the two-letter list that applies to this game,
        as a tuple of two lists, one grouped by first letter, and
        the other grouped by the second (last) letter"""
        vocab = vocabulary_for_locale(self.locale)
        tw0, tw1 = Wordbase.two_letter_words(vocab)
        gr0, gr1 = groupby(tw0, lambda w: w[0]), groupby(tw1, lambda w: w[1])
        return (
            [(key, list(grp)) for key, grp in gr0],
            [(key, list(grp)) for key, grp in gr1],
        )

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
        return 0 if prefs is None else cast(int, prefs.get("duration", 0))

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
        ts_last_move = self.ts_last_move or self.timestamp or datetime.utcnow()
        delta = datetime.utcnow() - ts_last_move
        return delta >= timedelta(days=Game.OVERDUE_DAYS)

    def get_elapsed(self) -> Tuple[float, float]:
        """Return the elapsed time for both players,
        in seconds, as a tuple"""
        elapsed = [0.0, 0.0]
        last_ts = self.timestamp or datetime.utcnow()
        for m in self.moves:
            if m.ts is not None:
                delta = m.ts - last_ts
                last_ts = m.ts
                elapsed[m.player] += delta.total_seconds()
        if self.state is not None and not self.state.is_game_over():
            # Game still going on: Add the time from the last move until now
            delta = datetime.utcnow() - last_ts
            elapsed[self.player_to_move()] += delta.total_seconds()
        return cast(Tuple[float, float], tuple(elapsed))

    def time_info(self) -> Dict[str, Union[int, Tuple[float, float]]]:
        """Returns a dict with timing information about this game"""
        return dict(duration=self.get_duration(), elapsed=self.get_elapsed())

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

    def check_legality(self, move: MoveBase) -> Union[int, Tuple[int, str]]:
        """Check whether an incoming move from a client is legal and valid"""
        assert self.state is not None
        return self.state.check_legality(move)

    def register_move(self, move: MoveBase) -> None:
        """Register a new move, updating the score
        and appending to the move list"""
        player_index = self.player_to_move()
        assert self.state is not None
        self.state.apply_move(move)
        self.ts_last_move = datetime.utcnow()
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
            if m.rack is not None:
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

    def has_new_chat_msg(self, user_id: str) -> bool:
        """Return True if there is a new chat message
        that the given user hasn't seen"""
        p = self.player_index(user_id)
        if p is None or self.is_autoplayer(1 - p):
            # The user is not a player of this game, or robot opponent: no chat
            return False
        # Check the database
        # TBD: consider memcaching this
        uuid = self.id()
        if not uuid:
            return False
        return ChatModel.check_conversation("game:" + uuid, user_id)

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
    ) -> Dict[str, Any]:
        """Create a package of information for the client
        about the current state"""
        assert self.state is not None
        reply: Dict[str, Any] = dict()
        num_moves = 1
        lm: Optional[MoveBase] = None
        succ_chall = False
        if self.last_move is not None:
            # Show the autoplayer or response move that was made
            lm = self.last_move
            num_moves = 2  # One new move to be added to move list
        elif lastmove is not None:
            # The indicated move should be included in the client state
            # (used when notifying an opponent of a new move through a channel)
            lm = lastmove
        if lm is not None:
            reply["lastmove"] = lm.details(self.state)
            # Successful challenge?
            succ_chall = lm.is_successful_challenge(self.state)
        newmoves = [
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
        else:
            # Game is still in progress
            assert player_index is not None
            # ...but in a last-challenge state
            last_chall = self.state.is_last_challenge()
            reply["result"] = 0  # Indicate no error
            reply["xchg"] = False if last_chall else self.state.is_exchange_allowed()
            reply["chall"] = self.state.is_challengeable()
            reply["last_chall"] = last_chall
            reply["bag"] = self.display_bag(player_index)

        if player_index is None:
            reply["rack"] = ""
        else:
            reply["rack"] = self.state.rack_details(player_index)
        reply["num_moves"] = len(self.moves)
        reply["newmoves"] = newmoves
        reply["scores"] = self.final_scores()
        reply["succ_chall"] = succ_chall
        reply["player"] = player_index  # Can be None if the game is over
        reply["newbag"] = self.new_bag()
        reply["manual"] = self.manual_wordcheck()
        reply["locale"] = self.locale
        reply["alphabet"] = self.tileset.alphabet.order
        reply["tile_scores"] = self.tileset.scores
        reply["board_type"] = self.board_type
        reply["two_letter_words"] = self.two_letter_words
        if self.get_duration():
            # Timed game: send information about elapsed time
            reply["time_info"] = self.time_info()
        if deep:
            # Send all moves
            reply["moves"] = [
                (m.player, m.move.summary(self.state)) for m in self.moves[0:-num_moves]
            ]
            reply["fairplay"] = self.get_fairplay()
            reply["autoplayer"] = [self.is_autoplayer(0), self.is_autoplayer(1)]
            reply["nickname"] = [self.player_nickname(0), self.player_nickname(1)]
            reply["userid"] = [self.player_id(0), self.player_id(1)]
            reply["fullname"] = [self.player_fullname(0), self.player_fullname(1)]
            reply["overdue"] = self.is_overdue()

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
