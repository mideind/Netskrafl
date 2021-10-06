"""

    User class for netskrafl.is

    Copyright (C) 2021 Miðeind ehf.
    Author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This module implements the User class for the Netskrafl application.

"""

from __future__ import annotations

from typing import (
    Dict,
    TypedDict,
    Any,
    Optional,
    List,
    Set,
    Tuple,
    Iterable,
)

import threading

from datetime import datetime

from flask.helpers import url_for

from cache import memcache

from config import DEFAULT_LOCALE
from languages import Alphabet
from firebase import online_users
from skrafldb import (
    PrefItem,
    PrefsDict,
    UserModel,
    FavoriteModel,
    ChallengeModel,
    StatsModel,
    BlockModel,
    ReportModel,
)
from skraflmechanics import Error


# Type definitions


class UserSummaryDict(TypedDict):

    """ Summary data about a user """

    uid: str
    nick: str
    name: str
    image: str
    locale: str
    location: str
    elo: int
    human_elo: int
    manual_elo: int
    ready: bool
    ready_timed: bool
    fairplay: bool
    favorite: bool
    live: bool


class UserLoginDict(TypedDict, total=False):

    """ Summary data about a login event """

    user_id: str
    account: str
    method: str
    locale: str
    new: bool


# Should we use memcache (in practice Redis) to cache user data?
USE_MEMCACHE = False


class User:

    """ Information about a human user including nickname and preferences """

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
        """ Initialize a fresh User instance """
        self._user_id = uid
        self._account = account
        self._email: Optional[str] = None
        self._nickname = ""
        self._inactive: bool = False
        self._locale = locale or DEFAULT_LOCALE
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
        """ Obtain the properties from the database entity """
        self._account = um.account
        self._email = um.email
        self._nickname = um.nickname
        self._inactive = um.inactive
        self._locale = um.locale or DEFAULT_LOCALE
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
        """ Update the user's record in the database and in the memcache """
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
            um.locale = self._locale or DEFAULT_LOCALE
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
            if USE_MEMCACHE:
                memcache.set(
                    self._user_id,
                    self,
                    time=User._CACHE_EXPIRY,
                    namespace=User._NAMESPACE,
                )

    def id(self) -> Optional[str]:
        """ Returns the id (database key) of the user """
        return self._user_id

    def nickname(self) -> str:
        """ Returns the human-readable nickname of a user,
            or userid if a nick is not available """
        return self._nickname or self._user_id or ""

    def set_nickname(self, nickname: str) -> None:
        """ Sets the human-readable nickname of a user """
        self._nickname = nickname

    def timestamp(self) -> datetime:
        """ Creation date and time for this user """
        return self._timestamp

    @staticmethod
    def is_valid_nick(nick: str) -> bool:
        """ Check whether a nickname is valid and displayable """
        if not nick:
            return False
        return nick[0:8] != "https://" and nick[0:7] != "http://"

    def elo(self) -> int:
        """ Return the overall (human and robot) Elo points of the user """
        return self._elo or User.DEFAULT_ELO

    def human_elo(self) -> int:
        """ Return the human-only Elo points of the user """
        return self._human_elo or User.DEFAULT_ELO

    def manual_elo(self) -> int:
        """ Return the human-only, manual-game-only Elo points of the user """
        return self._manual_elo or User.DEFAULT_ELO

    def is_inactive(self) -> bool:
        """ Return True if the user is marked as inactive """
        return self._inactive

    def is_displayable(self) -> bool:
        """ Returns True if this user should appear in user lists """
        if self._inactive:
            # Inactive users are hidden
            return False
        # Nicknames that haven't been properly set aren't displayed
        return User.is_valid_nick(self._nickname)

    @property
    def preferences(self) -> PrefsDict:
        """ Return the game preferences as a dictionary """
        return self._preferences

    @property
    def locale(self) -> str:
        """ Get the locale code for this user """
        return self._locale or DEFAULT_LOCALE

    def set_locale(self, locale: str) -> None:
        """ Set the locale code for this user """
        self._locale = locale

    @property
    def location(self) -> str:
        """ Get the location code for this user """
        return self._location or ""

    def set_location(self, location: str) -> None:
        """ Set the location code for this user """
        self._location = location

    def get_pref(
        self, pref: str, default: Optional[PrefItem] = None
    ) -> Optional[PrefItem]:
        """ Retrieve a preference, or None if not found """
        if self._preferences is None:
            return None
        return self._preferences.get(pref, default)

    def get_string_pref(self, pref: str, default: str = "") -> str:
        """ Retrieve a string preference, or "" if not found """
        if self._preferences is None:
            return default
        val = self._preferences.get(pref, default)
        return val if isinstance(val, str) else default

    def get_bool_pref(self, pref: str, default: bool = False) -> bool:
        """ Retrieve a string preference, or "" if not found """
        if self._preferences is None:
            return default
        val = self._preferences.get(pref, default)
        return val if isinstance(val, bool) else default

    def set_pref(self, pref: str, value: PrefItem) -> None:
        """ Set a preference to a value """
        if self._preferences is None:
            self._preferences = {}
        self._preferences[pref] = value

    @staticmethod
    def full_name_from_prefs(prefs: Optional[PrefsDict]) -> str:
        """ Returns the full name of a user from a dict of preferences """
        if prefs is None:
            return ""
        fn = prefs.get("full_name")
        return fn if fn is not None and isinstance(fn, str) else ""

    def full_name(self) -> str:
        """ Returns the full name of a user """
        return self.get_string_pref("full_name")

    def set_full_name(self, full_name: str) -> None:
        """ Sets the full name of a user """
        self.set_pref("full_name", full_name)

    def email(self) -> str:
        """ Returns the e-mail address of a user """
        return self.get_string_pref("email", self._email or "")

    def set_email(self, email: str) -> None:
        """ Sets the e-mail address of a user """
        self.set_pref("email", email)

    def audio(self) -> bool:
        """ Returns True if the user wants audible signals """
        # True by default
        return self.get_bool_pref("audio", True)

    def set_audio(self, audio: bool) -> None:
        """ Sets the audio preference of a user to True or False """
        assert isinstance(audio, bool)
        self.set_pref("audio", audio)

    def image(self) -> str:
        """ Returns the URL of an image (photo/avatar) of a user """
        if not self._user_id:
            return ""
        if self._has_image_blob:
            # We have a stored BLOB for this user: return a URL to it
            return url_for("api.image", uid=self._user_id)
        # We have a stored URL: return it
        return self._image or ""

    def set_image(self, image: str) -> None:
        """ Sets the URL of an image (photo/avatar) of a user """
        # Note: For associating a user with an image BLOB,
        # refer to the /image endpoint in api.py.
        # This call erases any BLOB already associated with the user!
        self._image = image
        self._has_image_blob = False

    def fanfare(self) -> bool:
        """ Returns True if the user wants a fanfare sound when winning """
        return self.get_bool_pref("fanfare", True)

    def set_fanfare(self, fanfare: bool) -> None:
        """ Sets the fanfare preference of a user to True or False """
        self.set_pref("fanfare", fanfare)

    def beginner(self) -> bool:
        """ Returns True if the user is a beginner so we show help panels, etc."""
        # True by default
        return self.get_bool_pref("beginner", True)

    def set_beginner(self, beginner: bool) -> None:
        """ Sets the beginner state of a user to True or False """
        self.set_pref("beginner", beginner)

    @staticmethod
    def fairplay_from_prefs(prefs: Optional[PrefsDict]) -> bool:
        """ Returns the fairplay preference of a user """
        if prefs is None:
            return False
        fp = prefs.get("fairplay")
        return isinstance(fp, bool) and fp

    def fairplay(self) -> bool:
        """ Returns True if the user has committed to a fair play statement """
        # False by default
        return self.get_bool_pref("fairplay", False)

    def set_fairplay(self, state: bool) -> None:
        """ Sets the fairplay state of a user to True or False """
        self.set_pref("fairplay", state)

    @staticmethod
    def new_bag_from_prefs(prefs: Optional[PrefsDict]) -> bool:
        """ Returns the new bag preference of a user """
        if prefs is None:
            return False
        newbag = prefs.get("newbag")
        # True by default
        return newbag if isinstance(newbag, bool) else True

    def new_bag(self) -> bool:
        """ Returns True if the user would like to play with the new bag """
        # True by default
        return self.get_bool_pref("newbag", True)

    def set_new_bag(self, state: bool) -> None:
        """ Sets the new bag preference of a user to True or False """
        self.set_pref("newbag", state)

    @staticmethod
    def friend_from_prefs(prefs: Optional[PrefsDict]) -> bool:
        """ Returns True if the user is a friend of Netskrafl """
        if prefs is None:
            return False
        friend = prefs.get("friend")
        return isinstance(friend, bool) and friend

    def friend(self) -> bool:
        """ Returns True if the user is a friend of Netskrafl """
        # False by default
        return self.get_bool_pref("friend", False)

    def set_friend(self, state: bool) -> None:
        """ Sets the friend status of a user to True or False """
        self.set_pref("friend", state)

    @staticmethod
    def has_paid_from_prefs(prefs: Optional[PrefsDict]) -> bool:
        """ Returns True if the user is a paying friend of Netskrafl """
        if prefs is None:
            return False
        if not User.friend_from_prefs(prefs):
            # Must be a friend before being a paying friend
            return False
        has_paid = prefs.get("haspaid")
        return isinstance(has_paid, bool) and has_paid

    def has_paid(self) -> bool:
        """ Returns True if the user is a paying friend of Netskrafl """
        if not self.friend():
            # Must be a friend before being a paying friend
            return False
        # False by default
        return self.get_bool_pref("haspaid", False)

    def set_has_paid(self, state: bool) -> None:
        """ Sets the payment status of a user to True or False """
        self.set_pref("haspaid", state)

    def is_ready(self) -> bool:
        """ Returns True if the user is ready to accept challenges """
        return self._ready

    def set_ready(self, ready: bool) -> None:
        """ Sets the ready state of a user to True or False """
        self._ready = ready

    def is_ready_timed(self) -> bool:
        """ Returns True if the user is ready for timed games """
        return self._ready_timed

    def set_ready_timed(self, ready: bool) -> None:
        """ Sets the whether a user is ready for timed games """
        self._ready_timed = ready

    def chat_disabled(self) -> bool:
        """ Returns True if the user has disabled chat """
        return self._chat_disabled

    def disable_chat(self, disabled: bool) -> None:
        """ Sets the ready state of a user to True or False """
        self._chat_disabled = disabled

    def _load_favorites(self) -> None:
        """ Loads favorites of this user from the database into a set in memory """
        if hasattr(self, "_favorites") and self._favorites:
            # Already have the favorites in memory
            return
        sid = self.id()
        assert sid is not None
        self._favorites = set(FavoriteModel.list_favorites(sid))

    def add_favorite(self, destuser_id: str) -> None:
        """ Add an A-favors-B relation between this user and the destuser """
        sid = self.id()
        assert sid is not None
        self._load_favorites()
        assert self._favorites is not None
        self._favorites.add(destuser_id)
        FavoriteModel.add_relation(sid, destuser_id)

    def del_favorite(self, destuser_id: str) -> None:
        """ Delete an A-favors-B relation between this user and the destuser """
        sid = self.id()
        assert sid is not None
        self._load_favorites()
        assert self._favorites is not None
        self._favorites.discard(destuser_id)
        FavoriteModel.del_relation(sid, destuser_id)

    def has_favorite(self, destuser_id: str) -> bool:
        """ Returns True if there is an A-favors-B relation
            between this user and the destuser """
        self._load_favorites()
        assert self._favorites is not None
        return destuser_id in self._favorites

    def _load_blocks(self) -> None:
        """ Loads blocked users into a set in memory """
        if hasattr(self, "_blocks") and self._blocks:
            # Already have the blocks in memory
            return
        sid = self.id()
        assert sid is not None
        self._blocks = set(BlockModel.list_blocked_users(sid))

    def block(self, destuser_id: str) -> bool:
        """ Add an A-blocks-B relation between this user and the destuser """
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
        """ Delete an A-favors-B relation between this user and the destuser """
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
        """ Returns True if there is an A-favors-B relation between
            this user and the destuser """
        if not destuser_id:
            return False
        self._load_blocks()
        assert self._blocks is not None
        return destuser_id in self._blocks

    def _summary_list(
        self, uids: Iterable[str], *, is_favorite: bool = False
    ) -> List[UserSummaryDict]:
        """ Return a list of summary data about a set of users """
        result: List[UserSummaryDict] = []
        online = online_users()
        for uid in uids:
            u = User.load_if_exists(uid)
            if u is not None:
                result.append(
                    UserSummaryDict(
                        uid=uid,
                        nick=u.nickname(),
                        name=u.full_name(),
                        image=u.image(),
                        locale=u.locale,
                        location=u.location,
                        elo=u.elo(),
                        human_elo=u.human_elo(),
                        manual_elo=u.manual_elo(),
                        ready=u.is_ready(),
                        ready_timed=u.is_ready_timed(),
                        fairplay=u.fairplay(),
                        favorite=is_favorite or self.has_favorite(uid),
                        live=uid in online,
                    )
                )
        return result

    def list_blocked(self) -> List[UserSummaryDict]:
        """ Returns a list of users blocked by this user """
        self._load_blocks()
        assert self._blocks is not None
        return self._summary_list(self._blocks)

    def list_favorites(self) -> List[UserSummaryDict]:
        """ Returns a list of users that this user favors """
        self._load_favorites()
        assert self._favorites is not None
        return self._summary_list(self._favorites, is_favorite=True)

    def report(self, destuser_id: str, code: int, text: str) -> bool:
        """ The current user is reporting another user """
        if not destuser_id:
            return False
        sid = self.id()
        assert sid is not None
        return ReportModel.report_user(sid, destuser_id, code, text)

    def has_challenge(self, destuser_id: str) -> bool:
        """ Returns True if this user has challenged destuser """
        # TBD: Cache this in the user object to save NDB reads
        return ChallengeModel.has_relation(self.id(), destuser_id)

    def find_challenge(self, srcuser_id: str) -> Tuple[bool, Optional[PrefsDict]]:
        """ Returns (found, prefs)"""
        return ChallengeModel.find_relation(srcuser_id, self.id())

    def issue_challenge(self, destuser_id: str, prefs: Optional[PrefsDict]) -> None:
        """ Issue a challenge to the destuser """
        sid = self.id()
        assert sid is not None
        ChallengeModel.add_relation(sid, destuser_id, prefs)

    def retract_challenge(self, destuser_id: str, *, key: Optional[str] = None) -> None:
        """ Retract a challenge previously issued to the destuser """
        sid = self.id()
        assert sid is not None
        ChallengeModel.del_relation(sid, destuser_id, key)

    def decline_challenge(self, srcuser_id: str, *, key: Optional[str] = None) -> None:
        """ Decline a challenge previously issued by the srcuser """
        sid = self.id()
        assert sid is not None
        ChallengeModel.del_relation(srcuser_id, sid, key)

    def accept_challenge(
        self, srcuser_id: str, *, key: Optional[str] = None
    ) -> Tuple[bool, Optional[PrefsDict]]:
        """ Decline a challenge previously issued by the srcuser """
        # Delete the accepted challenge and return the associated preferences
        sid = self.id()
        assert sid is not None
        return ChallengeModel.del_relation(srcuser_id, sid, key)

    def adjust_highest_score(self, score: int, game_uuid: str) -> bool:
        """ If this is the highest score of the player, modify it """
        if self._highest_score and self._highest_score >= score:
            # Not a new record
            return False
        # New record
        self._highest_score = score
        self._highest_score_game = game_uuid
        return True

    def adjust_best_word(self, word: str, score: int, game_uuid: str) -> bool:
        """ If this is the highest scoring word of the player, modify it """
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
        """ Load a user by id if she exists, otherwise return None """
        if not uid:
            return None
        with User._lock:
            if USE_MEMCACHE:
                u = memcache.get(uid, namespace=User._NAMESPACE)
                if u is not None:
                    return u
            um = UserModel.fetch(uid)
            if um is None:
                return None
            u = cls(uid=uid)
            u._init(um)
            if USE_MEMCACHE:
                memcache.add(uid, u, time=User._CACHE_EXPIRY, namespace=User._NAMESPACE)
            return u

    @classmethod
    def load_multi(cls, uids: Iterable[str]) -> List[User]:
        """ Load multiple users from persistent storage, given their user id """
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
    ) -> UserLoginDict:
        """ Log in a user via the given Google Account and return her user id """
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
            # !!! TODO: Return the entire UserModel object to avoid re-loading it
            uld = UserLoginDict(
                user_id=um.user_id(),
                account=um.account or account,
                locale=um.locale or DEFAULT_LOCALE,
                new=False,
            )
            return uld
        # We haven't seen this Google Account before: try to match by email
        if email:
            um = UserModel.fetch_email(email)
            if um is not None:
                # We probably have an older (GAE) user for this email:
                # Associate the account with it from now on (but keep the old id)
                um.account = account
                if image and image != um.image:
                    # Use the opportunity to update the image, if different
                    um.image = image
                # Note the last login
                um.last_login = datetime.utcnow()
                user_id = um.put().id()
                uld = UserLoginDict(
                    user_id=user_id,
                    account=um.account,
                    locale=um.locale or DEFAULT_LOCALE,
                    new=False,
                )
                return uld
        # No match by account id or email: create a new user,
        # with the account id as user id.
        # New users are created with the new bag as default,
        # and we also capture the email and the full name.
        nickname = email.split("@")[0] or name.split()[0]
        prefs: PrefsDict = {"newbag": True, "email": email, "full_name": name}
        user_id = UserModel.create(
            user_id=account,
            account=account,
            email=email,
            nickname=nickname,
            image=image,
            preferences=prefs,
            locale=locale,
        )
        # Create a user login event object and return it
        uld = UserLoginDict(
            user_id=user_id,
            account=account,
            locale=locale or DEFAULT_LOCALE,
            new=True,
        )
        return uld

    def to_serializable(self) -> Dict[str, Any]:
        """ Convert to JSON-serializable format """
        d: Dict[str, Any] = dict(**self.__dict__)
        del d["_favorites"]
        del d["_blocks"]
        d["_timestamp"] = self._timestamp.isoformat()
        return d

    @classmethod
    def from_serializable(cls, j: Dict[str, Any]) -> User:
        """ Create a fresh instance from a JSON-serialized object """
        u = cls(uid=j["_user_id"])
        u.__dict__ = j
        u._favorites = None
        u._blocks = None
        u._timestamp = datetime.fromisoformat(j["_timestamp"])
        return u

    def profile(self) -> Dict[str, Any]:
        """ Return a set of key statistics on the user """
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

