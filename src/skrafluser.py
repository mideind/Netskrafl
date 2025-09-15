"""

    User class for netskrafl.is

    Copyright © 2025 Miðeind ehf.
    Author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This module implements the User class for the Netskrafl application.

"""

from __future__ import annotations

from typing import (
    Callable,
    Dict,
    FrozenSet,
    Mapping,
    NotRequired,
    Required,
    TypeVar,
    TypedDict,
    Any,
    Optional,
    List,
    Set,
    Tuple,
    Iterable,
    Union,
    cast,
)

import threading
import functools
import logging
from datetime import UTC, datetime, timedelta
import re
import uuid
import jwt

from flask.helpers import url_for

from config import (
    ANONYMOUS_PREFIX,
    EXPLO_CLIENT_SECRET,
    MALSTADUR_JWT_SECRET,
    DEFAULT_LOCALE,
    NETSKRAFL,
    PROJECT_ID,
    DEFAULT_ELO,
)
from languages import Alphabet, alphabet_for_locale, to_supported_locale
from firebase import OnlineStatus, online_status, set_online_status
from skrafldb import (
    DEFAULT_ELO_DICT,
    PrefsDict,
    TransactionModel,
    UserModel,
    FavoriteModel,
    ChallengeModel,
    StatsModel,
    BlockModel,
    ReportModel,
    EloModel,
    EloDict,
    SubmissionModel,
)
from skraflmechanics import Error


# Type definitions

T = TypeVar("T")

PrefItem = Union[str, int, bool]

class UserSummaryDict(TypedDict):
    """Summary data about a user"""

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
    new_board: bool


UserSummaryList = List[UserSummaryDict]


class UserLoginDict(TypedDict):
    """Summary data about a login event"""

    user_id: str
    account: str
    method: NotRequired[str]
    nickname: str
    locale: str
    new: bool
    # Our own token, which the client can pass back later to authenticate
    # without using the third party authentication providers
    token: str
    # If we just generated a new Explo token, this is its expiration time,
    # as an ISO format date and time string
    expires: Optional[str]


class UserDetailDict(TypedDict):
    """Additional data about a user, returned when logging in by user id"""

    name: str
    picture: str
    email: str


class UserProfileDict(TypedDict, total=False):
    """User profile, returned as a part of the /userstats response"""

    result: int
    uid: str
    inactive: bool
    nickname: str
    fullname: str
    image: str
    plan: str
    friend: bool
    has_paid: bool
    locale: str
    location: str
    timestamp: str
    accepts_challenges: bool
    accepts_timed: bool
    chat_disabled: bool
    highest_score: int
    highest_score_game: Optional[str]
    best_word: Optional[str]
    best_word_score: int
    best_word_game: Optional[str]
    favorite: bool
    live: bool
    challenge: bool
    blocked: bool
    blocking: bool
    list_favorites: List[UserSummaryDict]
    list_blocked: List[UserSummaryDict]
    locale_elo: EloDict


class StatsSummaryDict(TypedDict):
    """A summary of statistics for a player at a given point in time"""

    ts: str  # An ISO-formatted time stamp
    elo: int
    human_elo: int
    manual_elo: int


class JWTClaims(TypedDict, total=False):
    """Type definition for JSON Web Tokens (JWT) claims used in the application"""

    iss: str  # Issuer (PROJECT_ID)
    sub: str  # Subject (user_id)
    email: str  # User E-mail address
    plan: str  # Subscription plan
    exp: Required[float | datetime]  # Expiration time (Unix timestamp)
    iat: Required[float | datetime]  # Issued at time (Unix timestamp)
    nbf: float | datetime  # Not before time (Unix timestamp)
    jti: str  # JWT ID (unique identifier)
    aud: str | List[str]  # Audience (JWT_AUDIENCE)


# Maximum length of player nickname
MAX_NICKNAME_LENGTH = 15

# Default login token lifetime
DEFAULT_TOKEN_LIFETIME = timedelta(days=30)

# Key ID for the client secret key used to sign our own tokens
# Change this if the key is rotated or the token structure is updated
EXPLO_KID_1 = "2022-02-08:1"
EXPLO_KID_2 = "2025-02-21:1"

# All potentially valid KIDs
EXPLO_KIDS = frozenset((EXPLO_KID_1, EXPLO_KID_2))

# This is the currently issued KID
EXPLO_KID = EXPLO_KID_2

# Remember to change Málstaður:src/app/api/netskrafl/token/route.tsx if this changes!
MALSTADUR_KID = "2025-02-27:1"

# All potentially valid KIDs
MALSTADUR_KIDS = frozenset((MALSTADUR_KID,))

# Algorithm: HMAC using SHA-256
JWT_ALGORITHM = "HS256"

# JWT audience
JWT_AUDIENCE = "explo-client"

# Nickname character replacement pattern
NICKNAME_STRIP = re.compile(r"[\W_]+", re.UNICODE)

# Use a partial function to set the online status within user summaries
set_online_status_for_summaries = functools.partial(set_online_status, "uid")


def make_login_dict(
    user_id: str,
    nickname: str,
    account: str,
    locale: str,
    new: bool,
    lifetime: timedelta = DEFAULT_TOKEN_LIFETIME,
    previous_token: Optional[str] = None,
) -> UserLoginDict:
    """Create a login credential object that is returned to the client"""
    now = datetime.now(UTC)
    expires = now + lifetime
    token = previous_token
    if not token:
        # If asked, we create our own client token,
        # which the client can pass back later
        # instead of using the third party
        # authentication providers
        claims: JWTClaims = {
            "iss": PROJECT_ID,
            "sub": user_id,
            "exp": expires,
            "iat": now,
            "nbf": now,
            "jti": str(uuid.uuid4()),
            "aud": JWT_AUDIENCE,
        }
        token = jwt.encode(
            cast(Dict[str, Any], claims),
            EXPLO_CLIENT_SECRET,
            algorithm=JWT_ALGORITHM,
            headers={"kid": EXPLO_KID},
        )
    return {
        "user_id": user_id,
        "nickname": nickname,
        "account": account,
        "locale": locale,
        "new": new,
        "token": token,
        "expires": expires.isoformat() if previous_token is None else None,
    }


def is_token_blacklisted(jti: str) -> bool:
    """Check whether a token has been blacklisted"""
    # TBD
    return False


def verify_explo_token(token: str) -> Optional[JWTClaims]:
    """Verify a JWT-encoded Explo token and return its claims,
    or None if verification fails"""
    try:
        headers: Mapping[str, str] = cast(Any, jwt).get_unverified_header(token)
        if (typ := headers.get("typ")) != "JWT":
            raise ValueError(f"Unexpected token type: {typ}")
        if (alg := headers.get("alg")) != JWT_ALGORITHM:
            raise ValueError(f"Unexpected algorithm: {alg}")
        kid = headers.get("kid", "")
        if kid not in EXPLO_KIDS:
            raise ValueError(f"Unexpected key id: {kid}")
        # So far, so good. Now verify the JWT and its claims.
        # This will raise an exception if the token is invalid.
        claims: JWTClaims
        if kid == EXPLO_KID:
            # Current key identifier and token format, with a specified audience
            claims = jwt.decode(
                token,
                EXPLO_CLIENT_SECRET,
                algorithms=[JWT_ALGORITHM],
                issuer=PROJECT_ID,
                audience=JWT_AUDIENCE,
            )
            # Check the token unique ID against a blacklist
            jti = claims.get("jti", "")
            if is_token_blacklisted(jti):
                return None
        elif kid == EXPLO_KID_1:
            # The older KID_1 tokens are still accepted without an audience check,
            # but no longer issued for new logins
            claims = jwt.decode(
                token,
                EXPLO_CLIENT_SECRET,
                algorithms=[JWT_ALGORITHM],
                issuer=PROJECT_ID,
            )
        else:
            return None
        return claims
    except (jwt.InvalidTokenError, ValueError):
        return None


def verify_malstadur_token(token: str) -> Tuple[bool, Optional[JWTClaims]]:
    """Verify a JWT-encoded Málstaður token and return its claims,
    or None if verification fails. The first return value is True if
    the JWT has expired but False otherwise."""
    try:
        headers: Mapping[str, str] = cast(Any, jwt).get_unverified_header(token)
        if (typ := headers.get("typ")) != "JWT":
            raise ValueError(f"Unexpected token type: {typ}")
        if (alg := headers.get("alg")) != JWT_ALGORITHM:
            raise ValueError(f"Unexpected algorithm: {alg}")
        kid = headers.get("kid", "")
        if kid not in MALSTADUR_KIDS:
            raise ValueError(f"Unexpected key id: {kid}")
        # So far, so good. Now verify the JWT and its claims.
        # This will raise an exception if the token is invalid.
        claims: JWTClaims
        if kid == MALSTADUR_KID:
            # Current key identifier and token format
            claims = jwt.decode(
                token,
                MALSTADUR_JWT_SECRET,
                algorithms=[JWT_ALGORITHM],
                issuer="malstadur",
                audience="netskrafl",
            )
        else:
            return False, None
        return False, claims
    except jwt.ExpiredSignatureError:
        # Token is expired
        return True, None
    except (jwt.InvalidTokenError, ValueError):
        return False, None


class User:
    """Information about a human user including nickname and preferences"""

    # Use a lock to avoid potential race conditions between
    # the memcache and the database
    _lock = threading.Lock()

    # Current namespace (schema) for memcached User objects
    # Upgraded from 4 to 5 after adding locale attribute
    # Upgraded from 5 to 6 after adding location attribute
    # Upgraded from 6 to 7 after adding timestamp with conversion to/from isoformat
    # Upgraded from 7 to 8 after adding plan attribute
    _NAMESPACE = "user:8"

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
        self._plan: Optional[str] = None
        self._locale = locale or DEFAULT_LOCALE
        self._preferences: PrefsDict = {}
        self._ready: bool = True
        self._ready_timed: bool = True
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
        self._timestamp = datetime.now(UTC)
        # The user location is typically an ISO country code
        self._location: str = ""
        # Number of completed human games
        # (used for on-the-fly Elo calculations at game end)
        self._human_games = 0

        # NOTE: When new properties are added, the memcache namespace version id
        # (User._NAMESPACE, above) should be incremented!

    def _init(self, um: UserModel) -> None:
        """Obtain the properties from the database entity"""
        self._account = um.account
        self._email = um.email
        self._nickname = um.nickname
        self._inactive = um.inactive
        self._locale = um.locale or DEFAULT_LOCALE
        self._plan = um.plan
        self._preferences = um.prefs or {}
        self._ready = True if um.ready is None else um.ready
        self._ready_timed = True if um.ready_timed is None else um.ready_timed
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
        self._human_games = um.games or 0

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
            um.locale = self._locale or DEFAULT_LOCALE
            um.plan = self._plan
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
            um.location = self._location
            um.games = self._human_games
            # Don't mess with the image data (the image URL or the BLOB),
            # those are set with separate APIs
            um.put()
            # um.timestamp should not be set or updated

    def id(self) -> Optional[str]:
        """Returns the id (database key) of the user"""
        return self._user_id

    def account(self) -> str:
        """Returns the OAuth account identifier (including a potential
        provider prefix, i.e. "fb:" or "apple:") of the user"""
        return self._account or ""

    def is_anonymous(self) -> bool:
        """Returns True if the account is anonymous"""
        return self.account().startswith(ANONYMOUS_PREFIX)

    def nickname(self) -> str:
        """Returns the human-readable nickname of a user,
        or userid if a nick is not available"""
        return self._nickname or self._user_id or ""

    def set_nickname(self, nickname: str) -> None:
        """Sets the human-readable nickname of a user"""
        self._nickname = nickname.strip()[0:MAX_NICKNAME_LENGTH]

    def timestamp(self) -> datetime:
        """Creation date and time for this user"""
        return self._timestamp

    @staticmethod
    def is_valid_nick(nick: str) -> bool:
        """Check whether a nickname is valid and displayable"""
        nick = nick.strip()
        if not nick:
            return False
        if len(nick) > MAX_NICKNAME_LENGTH:
            return False
        return not nick.startswith(("https://", "http://", "robot-"))

    def elo_dict(self) -> EloDict:
        """Return the Elo ratings of the user as a dictionary"""
        # These are the 'old-style' Elo ratings, which are not strictly locale-aware
        return EloDict(
            self._elo or DEFAULT_ELO,
            self._human_elo or DEFAULT_ELO,
            self._manual_elo or DEFAULT_ELO,
        )

    def set_elo(self, ratings: EloDict) -> None:
        """Set the Elo points for the user"""
        # Note: This is the 'old-style' Elo rating, which is not
        # locale-specific. The new-style Elo ratings are stored
        # in EloModel entities, one for each (user, locale) combination.
        self._elo = ratings.elo
        self._human_elo = ratings.human_elo
        self._manual_elo = ratings.manual_elo

    def elo_for_locale(self, locale: Optional[str] = None) -> EloDict:
        """Return the Elo ratings of the user for the given locale,
        or for the user's current locale if None"""
        if NETSKRAFL:
            # In Netskrafl, we don't support locale-specific Elo ratings,
            # so we always return the Elo ratings stored with the user entity
            assert (
                locale is None or locale == DEFAULT_LOCALE
            ), f"Invalid locale: {locale}"
            return self.elo_dict()
        locale = locale or self.locale or DEFAULT_LOCALE
        if uid := self.id():
            if (em := EloModel.user_elo(locale, uid)) is not None:
                return EloDict(em.elo, em.human_elo, em.manual_elo)
        # Default to the 'old-style' Elo ratings if the locales match
        if locale == self.locale:
            return self.elo_dict()
        # No Elo data already available; go back to defaults
        return DEFAULT_ELO_DICT

    def num_human_games(self) -> int:
        """Return the number of completed human games for this user"""
        return self._human_games

    def increment_human_games(self) -> None:
        """Add to the number of completed human games for this user"""
        self._human_games += 1

    def is_inactive(self) -> bool:
        """Return True if the user is marked as inactive"""
        return self._inactive

    def set_inactive(self, state: bool) -> None:
        """Set the inactive state of a user"""
        self._inactive = state

    def is_displayable(self) -> bool:
        """Returns True if this user should appear in user lists"""
        if self._inactive:
            # Inactive users are hidden
            return False
        # Anonymous users are hidden from user lists
        return not self.is_anonymous()

    @property
    def preferences(self) -> PrefsDict:
        """Return the game preferences as a dictionary"""
        return self._preferences

    @property
    def locale(self) -> str:
        """Get the locale code for this user"""
        return self._locale or DEFAULT_LOCALE

    def set_locale(self, locale: str) -> None:
        """Set the locale code for this user"""
        if self._locale == locale:
            return  # Nothing to do
        # Note: the following two statements much occur in this order!
        # Update the 'old-style' Elo ratings to reflect the new locale
        self.set_elo(self.elo_for_locale(locale))
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
        return self._preferences.get(pref, default)

    def get_string_pref(self, pref: str, default: str = "") -> str:
        """Retrieve a string preference, or "" if not found"""
        val = self._preferences.get(pref, default)
        return val if isinstance(val, str) else default

    def get_bool_pref(self, pref: str, default: bool = False) -> bool:
        """Retrieve a string preference, or "" if not found"""
        val = self._preferences.get(pref, default)
        return val if isinstance(val, bool) else default

    def set_pref(self, pref: str, value: PrefItem) -> None:
        """Set a preference to a value"""
        self._preferences[pref] = value

    @staticmethod
    def full_name_from_prefs(prefs: Optional[PrefsDict]) -> str:
        """Returns the full name of a user from a dict of preferences"""
        if prefs is None:
            return ""
        return prefs.get("full_name", "")

    def full_name(self) -> str:
        """Returns the full name of a user"""
        return self.get_string_pref("full_name")

    def set_full_name(self, full_name: str) -> None:
        """Sets the full name of a user"""
        self.set_pref("full_name", full_name)

    def email(self) -> str:
        """Returns the e-mail address of a user from the user preferences,
        or the e-mail address of the user entity"""
        email = self.get_string_pref("email")
        return email or self._email or ""

    def set_email(self, email: str) -> None:
        """Sets the e-mail address of a user in the user preferences"""
        self.set_pref("email", email)

    def audio(self) -> bool:
        """Returns True if the user wants audible signals"""
        # True by default
        return self.get_bool_pref("audio", True)

    def set_audio(self, audio: bool) -> None:
        """Sets the audio preference of a user to True or False"""
        assert isinstance(audio, bool)
        self.set_pref("audio", audio)

    @staticmethod
    def _url_for_image(
        user_id: Optional[str], image: Optional[str], has_image_blob: bool, api: str
    ) -> str:
        """Converts a user_id and image info to an image URL"""
        if not user_id:
            return ""
        if has_image_blob:
            # We have a stored BLOB for this user: return a URL to it
            return url_for(f"api.{api}", uid=user_id)
        # We have a stored URL: return it
        return image or ""

    @staticmethod
    def image_url(
        user_id: Optional[str], image: Optional[str], has_image_blob: bool
    ) -> str:
        """Converts a user_id and image info to an image URL"""
        return User._url_for_image(user_id, image, has_image_blob, "image_api")

    @staticmethod
    def thumbnail_url(
        user_id: Optional[str], image: Optional[str], has_image_blob: bool
    ) -> str:
        """Converts a user_id and image info to a thumbnail URL"""
        return User._url_for_image(user_id, image, has_image_blob, "thumbnail_api")

    def image(self) -> str:
        """Returns the URL of an image (photo/avatar) of a user"""
        return self.image_url(self._user_id, self._image, self._has_image_blob)

    def thumbnail(self) -> str:
        """Returns the URL of a thumbnail (photo/avatar) of a user"""
        return self.thumbnail_url(self._user_id, self._image, self._has_image_blob)

    def set_image(self, image: str) -> None:
        """Sets the URL of an image (photo/avatar) of a user"""
        # Note: For associating a user with an image BLOB,
        # refer to the /image endpoint in api.py.
        # This erases any BLOB already associated with the user,
        # when the user entity is saved in the database!
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
    def new_board_from_prefs(prefs: Optional[PrefsDict]) -> bool:
        """Returns the new_board preference of a user"""
        if prefs is None:
            return False
        fp = prefs.get("new_board")
        return isinstance(fp, bool) and fp

    def new_board(self) -> bool:
        """Returns True if the user prefers to play on the new board"""
        # False by default
        return self.get_bool_pref("new_board", False)

    def set_new_board(self, state: bool) -> None:
        """Sets the new_board state of a user to True or False"""
        self.set_pref("new_board", state)

    @staticmethod
    def new_bag_from_prefs(prefs: Optional[PrefsDict]) -> bool:
        """Returns the new bag preference of a user"""
        # Now always True
        return True

    def new_bag(self) -> bool:
        """Returns True if the user would like to play with the new bag"""
        # Now always True
        return True

    def set_new_bag(self, state: bool) -> None:
        """Sets the new bag preference of a user to True or False"""
        # Now always True; no action needed
        pass

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
        if not self.plan():
            # Must be a friend of some kind before being a paying friend
            return False
        # False by default
        return self.get_bool_pref("haspaid", False)

    def set_has_paid(self, state: bool) -> None:
        """Sets the payment status of a user to True or False"""
        self.set_pref("haspaid", state)

    def plan(self) -> str:
        """Return a subscription plan identifier"""
        p = self._plan or ""
        if not p and self.friend():
            p = "friend"
        return p

    def add_transaction(self, plan: str, kind: str, op: str = "") -> None:
        """Start or finish a subscription plan"""
        if not (user_id := self.id()):
            logging.warning("Attempted to add transaction for user with no id")
            return
        self._plan = plan
        self.set_has_paid(plan != "")
        self.set_friend(plan != "")
        self.update()
        # Add a transaction record to the datastore
        TransactionModel.add_transaction(user_id, plan, kind, op)

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

    def set_chat_disabled(self, disabled: bool) -> None:
        """Sets the chat disabled state for a user to True or False"""
        self._chat_disabled = disabled

    def _load_favorites(self) -> None:
        """Loads favorites of this user from the database into a set in memory"""
        if hasattr(self, "_favorites") and (self._favorites is not None):
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

    def has_favorite(self, destuser_id: Optional[str]) -> bool:
        """Returns True if there is an A-favors-B relation
        between this user and the destuser"""
        if destuser_id is None:
            return False
        self._load_favorites()
        assert self._favorites is not None
        return destuser_id in self._favorites

    def _load_blocks(self) -> None:
        """Loads blocked users into a set in memory"""
        if getattr(self, "_blocks", None) is not None:
            # Already have the blocks in memory
            return
        sid = self.id()
        assert sid is not None
        self._blocks = set(BlockModel.list_blocked_users(sid))

    def blocked_by(self) -> Set[str]:
        """Return a set of user ids who block this user"""
        if not (sid := self.id()):
            return set()
        return set(BlockModel.list_blocked_by(sid))

    def reported_by(self) -> Set[str]:
        """Return a set of user ids who have reported this user"""
        if not (sid := self.id()):
            return set()
        return set(ReportModel.list_reported_by(sid))

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
        """Delete an A-blocks-B relation between this user and the destuser"""
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
        """Returns True if there is an A-blocks-B relation between
        this user and the destuser"""
        if not destuser_id:
            return False
        self._load_blocks()
        assert self._blocks is not None
        return destuser_id in self._blocks

    def blocked(self) -> Set[str]:
        """Returns a set of ids of all users blocked by this user"""
        self._load_blocks()
        assert self._blocks is not None
        return self._blocks

    def _summary_list(
        self,
        uids: Iterable[str],
        locale: str,
        online: OnlineStatus,
        *,
        is_favorite: bool = False,
    ) -> UserSummaryList:
        """Return a list of summary data about a set of users"""
        result: UserSummaryList = []
        users = fetch_users(uids, lambda uid: uid)
        elos = EloModel.load_multi(locale, users.keys())
        for uid, u in users.items():
            rating = elos.get(uid) or u.elo_for_locale(locale)
            result.append(
                UserSummaryDict(
                    uid=uid,
                    nick=u.nickname(),
                    name=u.full_name(),
                    image=u.thumbnail(),
                    locale=u.locale,
                    location=u.location,
                    elo=rating.elo,
                    human_elo=rating.human_elo,
                    manual_elo=rating.manual_elo,
                    ready=u.is_ready(),
                    ready_timed=u.is_ready_timed(),
                    fairplay=u.fairplay(),
                    favorite=is_favorite or self.has_favorite(uid),
                    live=False,  # Will be filled in later
                    new_board=u.new_board(),
                )
            )
        set_online_status_for_summaries(result, online.users_online)
        return result

    def list_blocked(self, locale: str, online: OnlineStatus) -> List[UserSummaryDict]:
        """Returns a list of users blocked by this user"""
        self._load_blocks()
        assert self._blocks is not None
        return self._summary_list(self._blocks, locale, online)

    def list_favorites(
        self, locale: str, online: OnlineStatus
    ) -> List[UserSummaryDict]:
        """Returns a list of users that this user favors"""
        self._load_favorites()
        assert self._favorites is not None
        return self._summary_list(self._favorites, locale, online, is_favorite=True)

    def report(self, destuser_id: str, code: int, text: str) -> bool:
        """The current user is reporting another user"""
        if not destuser_id:
            return False
        sid = self.id()
        assert sid is not None
        return ReportModel.report_user(sid, destuser_id, code, text)

    def submit_word(self, word: str, locale: str, comment: str) -> bool:
        """Submit a word for consideration as missing word"""
        word = word.strip().lower()
        if not word or not locale:
            return False
        sid = self.id()
        if not sid:
            return False  # Should not happen
        locale = to_supported_locale(locale)
        alphabet = alphabet_for_locale(locale)
        valid_chars = set(alphabet.order)
        # Validate the word; it must not contain illegal characters
        if any(c not in valid_chars for c in word):
            return False
        # Add the submission to the database
        SubmissionModel.submit_word(sid, locale, word, comment)
        return True

    def has_challenge(self, destuser_id: str) -> bool:
        """Returns True if this user has challenged destuser"""
        # TBD: Cache this in the user object to save NDB reads
        return ChallengeModel.has_relation(self.id(), destuser_id)

    def find_challenge(
        self, srcuser_id: str, *, key: Optional[str] = None
    ) -> Tuple[bool, Optional[PrefsDict]]:
        """Returns (found, prefs)"""
        return ChallengeModel.find_relation(srcuser_id, self.id(), key)

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

    def accept_challenge(
        self, srcuser_id: str, *, key: Optional[str] = None
    ) -> Tuple[bool, Optional[PrefsDict]]:
        """Accept a challenge previously issued by the srcuser"""
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
            um = UserModel.fetch(uid)
            if um is None:
                return None
            u = cls(uid=uid)
            u._init(um)
            return u

    @classmethod
    def load_by_email(cls, email: str) -> Optional[User]:
        """Load a user by email if she exists, otherwise return None"""
        if not email:
            return None
        with User._lock:
            um = UserModel.fetch_email(email)
            if um is None:
                return None
            u = cls(uid=um.user_id())
            u._init(um)
            return u

    @classmethod
    def load_by_account(cls, account: str) -> Optional[User]:
        """Load a user by account id if she exists, otherwise return None"""
        if not account:
            return None
        with User._lock:
            um = UserModel.fetch_account(account)
            if um is None:
                return None
            u = cls(uid=um.user_id())
            u._init(um)
            return u

    @classmethod
    def load_by_nickname(
        cls, nickname: str, *, ignore_case: bool = False
    ) -> Optional[User]:
        """Load a user by account id if she exists, otherwise return None"""
        if not nickname:
            return None
        with User._lock:
            um = UserModel.fetch_nickname(nickname, ignore_case)
            if um is None:
                return None
            u = cls(uid=um.user_id())
            u._init(um)
            return u

    @classmethod
    def load_multi(cls, uids: Iterable[str]) -> List[Optional[User]]:
        """Load multiple users from persistent storage, given their user id"""
        user_list: List[Optional[User]] = []
        with User._lock:
            for um in UserModel.fetch_multi(uids):
                if um is None:
                    user_list.append(None)
                else:
                    u = cls(uid=um.user_id())
                    u._init(um)
                    user_list.append(u)
        return user_list

    @classmethod
    def make_nickname(
        cls, nickname: str, name: str, email: str
    ) -> str:
        """Create a nickname for a user"""
        nickname = NICKNAME_STRIP.sub("", nickname)
        if not nickname:
            # Obtain a candidate nickname from the email
            candidate1 = email.split("@")[0] if email else ""
            # Strip candidate to only contain alphanumeric characters
            strip1 = NICKNAME_STRIP.sub("", candidate1)
            # Obtain a candidate nickname from the full name
            candidate2 = name.split()[0] if name else ""
            # Strip candidate to only contain alphanumeric characters
            strip2 = NICKNAME_STRIP.sub("", candidate2)
            # If candidate1 originally contained non-alphanumeric characters,
            # but candidate2 did not, prefer candidate2
            if strip1 != candidate1 and candidate2 and strip2 == candidate2:
                strip1 = ""
            nickname = strip1 or candidate2 or ""
        return nickname[0:MAX_NICKNAME_LENGTH]

    @classmethod
    def create_user(
        cls,
        account: str,
        email: str,
        nickname: str,
        name: str,
        image: str,
        locale: str,
        is_friend: bool = False,
    ) -> str:
        """Create a new user object"""
        # Create a new user, with the account id as user id.
        # New users are created with the new bag as default,
        # and we also capture the email and the full name.
        prefs: PrefsDict = {
            "newbag": True,
            "email": email,
            "full_name": name or nickname,
            "friend": is_friend,
            "haspaid": is_friend,
        }
        # Make sure that the locale is a valid, supported locale
        locale = to_supported_locale(locale)  # Maps an empty locale to DEFAULT_LOCALE
        # Return the id of the freshly created user
        return UserModel.create(
            user_id=account,
            account=account,
            email=email,
            nickname=nickname,
            image=image,
            preferences=prefs,
            locale=locale,
        )

    @classmethod
    def login_by_account(
        cls,
        account: str,
        name: str,
        email: str,
        image: str,
        *,
        locale: Optional[str] = None,
        upgrade_from: Optional[str] = None,
    ) -> UserLoginDict:
        """Log in a user via the given account identifier and return her user id"""
        name = name.strip()
        # First, see if the user account already exists under the account id
        um = UserModel.fetch_account(account)
        if um is None and upgrade_from:
            # The user probably exists as an anonymous user with the upgrade_from id
            um = UserModel.fetch(upgrade_from)
        if um is not None:
            # We've seen this user account before
            # If this was an anonymous user, we need to assign a new account id
            # (i.e. replace anon:XYZ with [google:]XYZ, fb:XYZ or apple:XYZ)
            um.account = account
            if image and image != um.image:
                # Use the opportunity to update the image, if different
                um.image = image
            if email and email != um.email:
                # Use the opportunity to update the email, if different
                um.email = email
            full_name = um.prefs.get("full_name", "") if um.prefs else ""
            if name and not full_name:
                # Use the opportunity to update the name, if not already set
                um.prefs["full_name"] = name
            # Note the login timestamp
            um.last_login = datetime.now(UTC)
            # If the account was disabled, enable it again
            um.inactive = False
            um.put()
            # Note that the user id might not be the Google account id!
            # Instead, it could be the old GAE user id.
            uld = make_login_dict(
                user_id=um.user_id(),
                account=um.account,
                nickname=um.nickname,
                locale=um.locale or DEFAULT_LOCALE,
                new=False,
            )
            return uld
        # We haven't seen this Google Account before: try to match by email
        if email and (um := UserModel.fetch_email(email)) is not None:
            # We probably have an older (Python2 GAE) user for this email:
            # Associate the account with it from now on (but keep the old id)
            if account:
                um.account = account
            elif not um.account:
                # Should not happen, but anyway: if there was no
                # account id, copy the user id into it
                um.account = um.user_id()
            if image and image != um.image:
                # Use the opportunity to update the image, if different
                um.image = image
            full_name = um.prefs.get("full_name", "") if um.prefs else ""
            if name and not full_name:
                # Use the opportunity to update the name, if not already set
                um.prefs["full_name"] = name
            # Note the last login
            um.last_login = datetime.now(UTC)
            # If the account was disabled, enable it again
            um.inactive = False
            user_id = um.put().id()
            uld = make_login_dict(
                user_id=user_id,
                account=um.account,
                nickname=um.nickname,
                locale=um.locale or DEFAULT_LOCALE,
                new=False,
            )
            return uld
        # User does not exist already: create a new user entity
        nickname = cls.make_nickname("", name, email)
        user_id = cls.create_user(
            account, email, nickname, name, image, locale or DEFAULT_LOCALE
        )
        # Create a user login event object and return it
        uld = make_login_dict(
            user_id=user_id,
            account=account,
            nickname=nickname,
            locale=locale or DEFAULT_LOCALE,
            new=True,
        )
        return uld

    @classmethod
    def login_by_email(
        cls,
        email: str,
        account: str,
        nickname: str,
        fullname: str,
        is_friend: bool,
    ) -> UserLoginDict:
        """Log in a user given an e-mail address; return a login dictionary and some
        additional user details. This is used by the Málstaður login flow."""
        if (um := UserModel.fetch_email(email)) is not None:
            # User exists: Note the login timestamp
            um.last_login = datetime.now(UTC)
            # Force the friend state to the one coming from Málstaður
            um.plan = "friend" if is_friend else ""
            um.prefs["friend"] = is_friend
            um.prefs["haspaid"] = is_friend
            um.put()
            user_id = um.user_id()
            uld = make_login_dict(
                user_id=user_id,
                nickname=um.nickname or nickname,
                account=um.account or user_id,
                locale=um.locale or DEFAULT_LOCALE,
                new=False,
                # We don't need to create a fresh Explo token, so we
                # pass in a dummy placeholder value here
                previous_token="*",
            )
            return uld
        # User does not exist already: create a new user entity
        nickname = User.make_nickname(nickname, fullname, email)
        user_id = cls.create_user(
            account, email, nickname, fullname, "", DEFAULT_LOCALE, is_friend
        )
        # Return a user login event object
        uld = make_login_dict(
            user_id=user_id,
            account=account,
            nickname=nickname,
            locale=DEFAULT_LOCALE,
            new=True,
            # We don't need to create a fresh Explo token, so we
            # pass in a dummy placeholder value here
            previous_token="*",
        )
        return uld

    @classmethod
    def login_by_id(
        cls,
        user_id: str,
        previous_token: Optional[str] = None,
    ) -> Optional[UserLoginDict]:
        """Log in a user given a user id; return a login dictionary
        and some additional user details, or None"""
        if (um := UserModel.fetch(user_id)) is None:
            return None
        # Note the login timestamp
        um.last_login = datetime.now(UTC)
        um.put()
        uld = make_login_dict(
            user_id=user_id,
            account=um.account or user_id,
            nickname=um.nickname,
            locale=um.locale or DEFAULT_LOCALE,
            new=False,
            previous_token=previous_token,
        )
        return uld

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
        u._timestamp = datetime.fromisoformat(j["_timestamp"]).replace(tzinfo=UTC)
        return u

    def delete_account(self) -> bool:
        """Delete the user account"""
        # We can't actually delete the user entity in the database,
        # since it is referenced by other entities, such as GameModel.
        # Instead, we remove all personally identifiable
        # information from the user object, and delete associated entities
        # such as favorites and challenges.
        if not (uid := self.id()):
            return False
        self.set_inactive(True)
        self.set_email("")
        self.set_full_name("")
        self.set_image("")
        self.set_location("")
        self.set_ready(False)
        self.set_ready_timed(False)
        self.set_chat_disabled(True)
        # Remove favorites
        # Retract issued challenges
        # Reject received challenges
        UserModel.delete_related_entities(uid)
        # Save the updated user record and delete subscriptions/plans
        self.add_transaction("", "api", "ACCOUNT_DELETED")
        return True

    def profile(self) -> UserProfileDict:
        """Return a set of static attributes and key statistics on the user"""
        reply = UserProfileDict()
        user_id = self.id()
        assert user_id is not None
        reply["result"] = Error.LEGAL
        reply["inactive"] = self.is_inactive()
        reply["nickname"] = self.nickname()
        reply["fullname"] = self.full_name()
        reply["image"] = self.image()  # Full size image (not thumbnail)
        reply["plan"] = self.plan()
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
            sm.populate_dict(cast(Dict[str, Any], reply))  # Typing hack
        # Add locale-specific Elo ratings
        reply["locale_elo"] = self.elo_for_locale()
        return reply

    @staticmethod
    def stats(uid: Optional[str], cuser: User) -> Tuple[int, Optional[UserProfileDict]]:
        """Return the profile of a given user along with key statistics,
        as a dictionary as well as an error code"""
        cuid = cuser.id()
        if cuid == uid:
            # Current user: no need to load the user object
            user = cuser
        else:
            user = User.load_if_exists(uid) if uid else None
            if user is None:
                return Error.WRONG_USER, None
        assert uid is not None

        # Read static attributes of the user into a profile object
        profile = user.profile()

        # Add dynamic attributes to the returned object

        online = online_status(cuser.locale or DEFAULT_LOCALE)
        # Is the user online in the current user's locale?
        if uid == cuid:
            live = True  # The current user is always live
        else:
            live = online.user_online(uid)
        profile["live"] = live

        # Include info on whether this user is a favorite of the current user
        fav = False  # The current user is never a favorite of themselves
        if uid != cuid:
            fav = cuser.has_favorite(uid)
        profile["favorite"] = fav

        # Include info on whether the current user has challenged this user
        chall = False  # The current user cannot challenge themselves
        if uid != cuid:
            chall = cuser.has_challenge(uid)
        profile["challenge"] = chall

        # Include info on whether the current user has blocked this user
        blocked = False  # The current user cannot be blocking themselves
        if uid != cuid:
            blocked = cuser.has_blocked(uid)
        profile["blocked"] = blocked

        # Include info on whether this user has blocked the current user
        blocking = False  # The current user cannot block themselves
        if cuid and uid != cuid:
            blocking = user.has_blocked(cuid)
        profile["blocking"] = blocking

        if uid == cuid:
            # If current user, include a list of favorite users
            profile["list_favorites"] = cuser.list_favorites(cuser.locale, online)
            # Also, include a list of blocked users
            profile["list_blocked"] = cuser.list_blocked(cuser.locale, online)
            # Also, include a 30-day history of Elo scores
            now = datetime.now(UTC)
            # Time at midnight, i.e. start of the current day
            now = datetime(year=now.year, month=now.month, day=now.day, tzinfo=UTC)
            # We will return a 30-day history
            PERIOD = 30
            # Initialize the list of day slots
            result: List[Optional[StatsSummaryDict]] = [None] * PERIOD
            # The enumeration is youngest-first
            for sm in StatsModel.last_for_user(uid, days=PERIOD):
                age = (now - sm.timestamp).days
                ts_iso = sm.timestamp.isoformat()
                if age >= PERIOD:
                    # It's an entry older than we need
                    if result[PERIOD - 1] is not None:
                        # We've already filled our list
                        break
                    # Assign the oldest entry, if we don't yet have a value for it
                    age = PERIOD - 1
                    ts_iso = (now - timedelta(days=age)).isoformat()
                result[age] = StatsSummaryDict(
                    ts=ts_iso,
                    elo=sm.elo,
                    human_elo=sm.human_elo,
                    manual_elo=sm.manual_elo,
                )
            # Fill all day slots in the result list
            # Create a beginning sentinel entry to fill empty day slots
            prev = StatsSummaryDict(
                ts=(now - timedelta(days=31)).isoformat(),
                elo=1200,
                human_elo=1200,
                manual_elo=1200,
            )
            # Enumerate in reverse order (oldest first)
            for ix in reversed(range(PERIOD)):
                r = result[ix]
                if r is None:
                    # No entry for this day: duplicate the previous entry
                    p = prev.copy()
                    p["ts"] = (now - timedelta(days=ix)).isoformat()
                    result[ix] = p
                else:
                    prev = r
            profile[f"elo_{PERIOD}_days"] = result

        return Error.LEGAL, profile


def fetch_users(
    ulist: Iterable[T], uid_func: Callable[[T], Optional[str]]
) -> Dict[str, User]:
    """Return a dictionary of users found in the ulist"""
    # Make a set of user ids by applying the uid_func
    # to ulist entries (!= None)
    uids: FrozenSet[str] = frozenset(
        uid for u in ulist if (uid := (u is not None) and uid_func(u))
    )
    # No need for a special case for an empty list
    user_objects = User.load_multi(uids)
    # Return a dictionary mapping user ids to users
    return {uid: user for uid, user in zip(uids, user_objects) if user is not None}
