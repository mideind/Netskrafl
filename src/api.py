"""

    Web server for netskrafl.is

    Copyright (C) 2021 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl


    This module contains the API entry points into the Netskrafl server.
    These APIs are used both by the web front-end and by the app client.

"""

from __future__ import annotations

from typing import (
    Optional,
    Dict,
    TypedDict,
    Union,
    List,
    Iterable,
    Any,
    TypeVar,
    Tuple,
    Callable,
    Set,
    cast,
)

import os
import re
import logging
import threading
import random
from datetime import datetime, timedelta

from flask import (
    Blueprint,
    request,
    url_for,
)
from flask.wrappers import Response
from flask.globals import current_app

from werkzeug.utils import redirect

from config import (
    running_local,
    PROJECT_ID,
    DEFAULT_LOCALE,
)
from basics import (
    is_mobile_client,
    jsonify,
    auth_required,
    ResponseType,
    RequestData,
    current_user,
    current_user_id,
    clear_session_userid,
)
from cache import memcache
from languages import (
    Alphabet,
    current_board_type,
    set_game_locale,
    current_lc,
    current_alphabet,
    current_language,
    to_supported_locale,
    SUPPORTED_LOCALES,
)
from dawgdictionary import Wordbase
from skraflmechanics import (
    Board,
    MoveBase,
    Move,
    PassMove,
    ExchangeMove,
    ResignMove,
    ChallengeMove,
    Error,
)
from skrafluser import MAX_NICKNAME_LENGTH, User
from skraflgame import BestMoveList, Game
from skraflplayer import AutoPlayer
from skrafldb import (
    ChatModel,
    ListPrefixDict,
    ZombieModel,
    PrefsDict,
    ChallengeModel,
    ChallengeTuple,
    UserModel,
    FavoriteModel,
    GameModel,
    RatingModel,
)
import firebase
from billing import cancel_plan
import auth

# Type definitions
T = TypeVar("T")
UserPrefsType = Dict[str, Union[str, bool]]


class GameListDict(TypedDict):

    """The dictionary returned from gamelist()"""

    uuid: str
    locale: str
    url: str
    oppid: Optional[str]
    opp: str
    fullname: str
    sc0: int
    sc1: int
    ts: str
    my_turn: bool
    overdue: bool
    zombie: bool
    prefs: Dict[str, bool]
    timed: int
    tile_count: int
    live: bool
    image: str
    fav: bool
    robot_level: int
    elo: int
    human_elo: int


GameList = List[GameListDict]


class RecentListDict(TypedDict):

    """The dictionary returned from recentlist()"""

    uuid: str
    locale: str
    url: str
    oppid: Optional[str]
    opp: str
    opp_is_robot: bool
    robot_level: int
    sc0: int
    sc1: int
    elo_adj: Optional[int]
    human_elo_adj: Optional[int]
    ts_last_move: str
    days: int
    hours: int
    minutes: int
    prefs: Dict[str, Union[int, bool]]
    live: bool
    image: str
    fav: bool
    elo: int
    human_elo: int


RecentList = List[RecentListDict]


class ChallengeListDict(TypedDict):

    """The dictionary returned from _challengelist()"""

    key: str
    received: bool
    userid: str
    opp: str
    fullname: str
    prefs: Optional[PrefsDict]
    ts: str
    opp_ready: bool
    live: bool
    image: str
    fav: bool
    elo: int
    human_elo: int


ChallengeList = List[ChallengeListDict]


class UserListDict(TypedDict):

    """The dictionary returned from _userlist()"""

    userid: str
    robot_level: int
    nick: str
    fullname: str
    elo: str  # Elo score or hyphen
    human_elo: str  # Elo score or hyphen
    fav: bool
    chall: bool
    fairplay: bool
    newbag: bool
    ready: bool
    ready_timed: bool
    live: bool
    image: str


UserList = List[UserListDict]


class ChatMessageDict(TypedDict):

    """A chat message as returned by the /chatload endpoint"""

    from_userid: str
    name: str
    image: str
    msg: str
    ts: str  # An ISO-formatted time stamp


class ChatHistoryDict(TypedDict):

    """A chat history entry as returned by the /chathistory endpoint"""

    user: str  # User id
    name: str  # Full name
    nick: str  # Nickname
    image: str
    last_msg: str
    ts: str  # An ISO-formatted time stamp
    unread: bool
    live: bool
    fav: bool
    disabled: bool  # Chat disabled?


class MoveNotifyDict(TypedDict):

    """A notification sent via Firebase to clients when a move has been
    processed"""

    game: str
    timestamp: str
    players: Tuple[Optional[str], Optional[str]]  # None if robot
    over: bool
    to_move: int
    scores: Tuple[int, int]
    progress: Tuple[int, int]


# Maximum number of online users to display
MAX_ONLINE = 80

# Default number of best moves to return from /bestmoves.
# This is set to 19 moves because that number is what fits
# in the move list of the fullscreen web version.
DEFAULT_BEST_MOVES = 19
# Maximum number of best moves to return from /bestmoves
MAX_BEST_MOVES = 20

# To try to finish requests as soon as possible and avoid GAE DeadlineExceeded
# exceptions, run the AutoPlayer move generators serially and exclusively
# within an instance
autoplayer_lock = threading.Lock()

# Register the Flask blueprint for the APIs
api_blueprint = Blueprint("api", __name__)
# The cast to Any can be removed when Flask typing becomes more robust
# and/or compatible with Pylance
api = cast(Any, api_blueprint)

VALIDATION_ERRORS: Dict[str, Dict[str, str]] = {
    "is": {
        "NICK_MISSING": "Notandi verður að hafa einkenni",
        "NICK_NOT_ALPHANUMERIC": "Einkenni má aðeins innihalda bók- og tölustafi",
        "NICK_TOO_LONG": f"Einkenni má ekki vera lengra en {MAX_NICKNAME_LENGTH} stafir",
        "EMAIL_NO_AT": "Tölvupóstfang verður að innihalda @-merki",
        "LOCALE_UNKNOWN": "Óþekkt staðfang (locale)",
    },
    "en_US": {
        "NICK_MISSING": "Nickname missing",
        "NICK_NOT_ALPHANUMERIC": "Nickname can only contain letters and numbers",
        "NICK_TOO_LONG": f"Nickname must not be longer than {MAX_NICKNAME_LENGTH} characters",
        "EMAIL_NO_AT": "E-mail address must contain @ sign",
        "LOCALE_UNKNOWN": "Unknown locale",
    },
    # !!! TODO: Add en_GB and Polish here
}


class UserForm:

    """Encapsulates the data in the user preferences form"""

    def __init__(self, usr: Optional[User] = None) -> None:
        # We store the URL that the client will redirect to after
        # doing an auth2.disconnect() call, clearing client-side
        # credentials. The login() handler clears the server-side
        # user cookie, so there is no need for an intervening redirect
        # to logout().
        self.logout_url: str = url_for("web.logout")
        self.nickname: str = ""
        self.full_name: str = ""
        self.id: str = ""
        self.email: str = ""
        self.image: str = ""
        self.audio: bool = True
        self.fanfare: bool = True
        self.beginner: bool = True
        self.fairplay: bool = False  # Defaults to False, must be explicitly set to True
        self.friend: bool = False
        self.has_paid: bool = False
        self.chat_disabled: bool = False
        self.locale: str = current_lc()
        if usr:
            self.init_from_user(usr)

    def init_from_form(self, form: Dict[str, str]) -> None:
        """The form has been submitted after editing: retrieve the entered data"""
        try:
            self.nickname = form["nickname"].strip()[0:MAX_NICKNAME_LENGTH]
        except (TypeError, ValueError, KeyError):
            pass
        try:
            self.full_name = form["full_name"].strip()
        except (TypeError, ValueError, KeyError):
            pass
        try:
            self.email = form["email"].strip()
        except (TypeError, ValueError, KeyError):
            pass
        self.locale = to_supported_locale(form.get("locale", "").strip()) or DEFAULT_LOCALE
        try:
            self.image = form["image"].strip()
        except (TypeError, ValueError, KeyError):
            pass
        try:
            self.audio = "audio" in form  # State of the checkbox
            self.fanfare = "fanfare" in form
            self.beginner = "beginner" in form
            self.fairplay = "fairplay" in form
            self.chat_disabled = "chat_disabled" in form
        except (TypeError, ValueError, KeyError):
            pass

    def init_from_dict(self, d: Dict[str, str]) -> None:
        """The form has been submitted after editing: retrieve the entered data"""
        try:
            self.nickname = d.get("nickname", "").strip()[0:MAX_NICKNAME_LENGTH]
        except (TypeError, ValueError):
            pass
        try:
            self.full_name = d.get("full_name", "").strip()
        except (TypeError, ValueError):
            pass
        try:
            self.email = d.get("email", "").strip()
        except (TypeError, ValueError):
            pass
        self.locale = to_supported_locale(d.get("locale", "").strip()) or DEFAULT_LOCALE
        try:
            self.image = d.get("image", "").strip()
        except (TypeError, ValueError, KeyError):
            pass
        try:
            self.audio = bool(d.get("audio", False))
            self.fanfare = bool(d.get("fanfare", False))
            self.beginner = bool(d.get("beginner", False))
            self.fairplay = bool(d.get("fairplay", False))
            self.chat_disabled = bool(d.get("chat_disabled", False))
        except (TypeError, ValueError, KeyError):
            pass

    def init_from_user(self, usr: User) -> None:
        """Load the data to be edited upon initial display of the form"""
        self.nickname = usr.nickname()
        self.full_name = usr.full_name()
        # Note that the email property of a User is fetched from the user
        # preferences, not from the email field in the database.
        self.email = usr.email()
        self.audio = usr.audio()
        self.fanfare = usr.fanfare()
        self.beginner = usr.beginner()
        self.fairplay = usr.fairplay()
        # Eventually, we will edit a plan identifier, not just a boolean
        self.friend = usr.plan() != ""
        self.has_paid = usr.has_paid()
        self.chat_disabled = usr.chat_disabled()
        self.locale = usr.locale
        self.id = current_user_id() or ""
        self.image = usr.image()

    @staticmethod
    def error_msg(key: str) -> str:
        """Return a validation error message, in the appropriate language"""
        lang = current_language()
        if lang not in VALIDATION_ERRORS:
            # Default to U.S. English
            lang = "en_US"
        return VALIDATION_ERRORS[lang].get(key, "")

    def validate(self) -> Dict[str, str]:
        """Check the current form data for validity
        and return a dict of errors, if any"""
        errors: Dict[str, str] = dict()
        # pylint: disable=bad-continuation
        if not self.nickname:
            errors["nickname"] = self.error_msg("NICK_MISSING")
        elif len(self.nickname) > MAX_NICKNAME_LENGTH:
            errors["nickname"] = self.error_msg("NICK_TOO_LONG")
        elif not re.match(r"^\w+$", self.nickname):
            errors["nickname"] = self.error_msg("NICK_NOT_ALPHANUMERIC")
        if self.email and "@" not in self.email:
            errors["email"] = self.error_msg("EMAIL_NO_AT")
        if self.locale not in SUPPORTED_LOCALES:
            errors["locale"] = self.error_msg("LOCALE_UNKNOWN")
        return errors

    def store(self, usr: User) -> None:
        """Store validated form data back into the user entity"""
        usr.set_nickname(self.nickname)
        usr.set_full_name(self.full_name)
        # Note that the User.set_email() call sets the email in the user preferences,
        # not the email property in the database. This is intentional and by design.
        usr.set_email(self.email)
        usr.set_audio(self.audio)
        usr.set_fanfare(self.fanfare)
        usr.set_beginner(self.beginner)
        usr.set_fairplay(self.fairplay)
        usr.disable_chat(self.chat_disabled)
        usr.set_locale(self.locale)
        # usr.set_image(self.image)  # The user image cannot and must not be set like this
        usr.update()

    def as_dict(self) -> UserPrefsType:
        """Return the user preferences as a dictionary"""
        return self.__dict__


@api.route("/oauth2callback", methods=["POST"])
def oauth2callback() -> ResponseType:
    """The OAuth2 login flow POSTs to this callback when a user has
    signed in using a Google Account"""
    return auth.oauth2callback(request)


@api.route("/oauth_fb", methods=["POST"])
def oauth_fb() -> ResponseType:
    """Facebook authentication"""
    return auth.oauth_fb(request)


@api.route("/oauth_apple", methods=["POST"])
def oauth_apple() -> ResponseType:
    """Apple authentication"""
    return auth.oauth_apple(request)


@api.route("/logout", methods=["POST"])
def logout() -> ResponseType:
    """Log the current user out"""
    clear_session_userid()
    return jsonify({"status": "success"})


@api.route("/firebase_token", methods=["POST"])
@auth_required(ok=False)
def firebase_token() -> ResponseType:
    """Obtain a custom Firebase token for the current logged-in user"""
    cuid = current_user_id()
    if not cuid:
        return jsonify(ok=False)
    try:
        token = firebase.create_custom_token(cuid)
        return jsonify(ok=True, token=token)
    except:
        return jsonify(ok=False)


def _notify_opponent_about_move(opponent_id: str, move: MoveBase) -> None:
    firebase.send_push_notification(
        user_id=opponent_id,
        title="Your opponent has made a move",
        body=str(move)
    )


def _process_move(
    game: Game, movelist: Iterable[str], *, force_resign: bool = False
) -> ResponseType:
    """Process a move coming in from the client.
    If force_resign is True, it is actually the opponent of the
    tardy player who is initiating the move, so we send the
    Firebase notification to the opposite (tardy) player in that case."""

    assert game is not None

    game_id = game.id()

    if game_id is None or game.is_over() or game.is_erroneous():
        # This game is already completed, or cannot be correctly
        # serialized from the datastore
        return jsonify(result=Error.GAME_NOT_FOUND)

    # Note that in the case of a forced resignation,
    # player_index is the index of the tardy opponent of the player
    # that is initiating the resignation
    player_index = game.player_to_move()
    opponent_index = 1 - player_index

    # Parse the move from the movestring we got back
    m: MoveBase = Move("", 0, 0)
    # pylint: disable=broad-except
    try:
        for mstr in movelist:
            if mstr == "pass":
                # Pass move (or accepting the last move in the game
                # without challenging it)
                m = PassMove()
                break
            if mstr.startswith("exch="):
                # Exchange move
                m = ExchangeMove(mstr[5:])
                break
            if mstr == "rsgn":
                # Resign from game, forfeiting all points
                assert game.state is not None
                m = ResignMove(game.state.scores()[player_index])
                break
            if mstr == "chall":
                # Challenging the last move
                m = ChallengeMove()
                break
            sq, tile = mstr.split("=")
            row = "ABCDEFGHIJKLMNO".index(sq[0])
            col = int(sq[1:]) - 1
            if tile[0] == "?":
                # If the blank tile is played, the next character contains
                # its meaning, i.e. the letter it stands for
                letter = tile[1]
                tile = tile[0]
            else:
                letter = tile
            assert isinstance(m, Move)
            m.add_cover(row, col, tile, letter)
    except Exception as e:
        logging.info("Exception in _process_move(): {0}".format(e))

    # Process the move string here
    # Unpack the error code and message
    err = game.check_legality(m)
    msg = ""
    if isinstance(err, tuple):
        err, msg = err

    if err != Error.LEGAL:
        # Something was wrong with the move:
        # show the user a corresponding error message
        return jsonify(result=err, msg=msg)

    opponent: Optional[str] = None

    # Serialize access to the following code section
    with autoplayer_lock:

        # Move is OK: register it and update the state
        game.register_move(m)

        # If it's the autoplayer's move, respond immediately
        # (can be a bit time consuming if rack has one or two blank tiles)
        # Note that if force_resign is True, opponent is the id
        # of the player who initiates the resignation (not the tardy player)
        opponent = game.player_id_to_move()

        is_over = game.is_over()

        if not is_over:

            if opponent is None:
                # Generate an autoplayer move in response
                game.autoplayer_move()
                is_over = game.is_over()  # State may change during autoplayer_move()
            elif m.needs_response_move:
                # Challenge move: generate a response move
                game.response_move()
                is_over = game.is_over()  # State may change during response_move()

        if is_over:
            # If the game is now over, tally the final score
            game.finalize_score()

        # Make sure the new game state is persistently recorded
        game.store(calc_elo_points=is_over)

        if force_resign:
            # Reverse the opponent and the player_index, since we want
            # to notify the tardy opponent, not the player who forced the resignation
            # Make sure that opponent is the tardy player
            opponent_index = player_index
            opponent = game.player_id(opponent_index)

        # If the game is now over, and the opponent is human, add it to the
        # zombie game list so that the opponent has a better chance to notice
        # the result
        if is_over and opponent is not None:
            ZombieModel.add_game(game_id, opponent)

    # Prepare the messages/notifications to be sent via Firebase
    now = datetime.utcnow().isoformat()
    msg_dict: Dict[str, Any] = dict()
    # Prepare a summary dict of the state of the game after the move
    assert game.state is not None
    move_dict: MoveNotifyDict = {
        "game": game_id,
        "timestamp": now,
        "players": tuple(game.player_ids),
        "over": game.state.is_game_over(),
        "to_move": game.player_to_move(),
        "scores": game.state.scores(),
        "progress": game.state.progress(),
    }

    if opponent:
        # Send a game update to the opponent, if human, including
        # the full client state. board.html and main.html listen to this.
        # Also update the user/[opp_id]/move branch with the current timestamp.
        client_state = game.client_state(opponent_index, m)
        msg_dict = {
            f"game/{game_id}/{opponent}/move": client_state,
            f"user/{opponent}/move": move_dict,
        }

    if player := game.player_id(1 - opponent_index):
        # Add a move notification to the original player as well,
        # since she may have multiple clients and we want to update'em all
        msg_dict[f"user/{player}/move"] = move_dict

    if msg_dict:
        firebase.send_message(msg_dict)
        _notify_opponent_about_move(opponent, m)

    # Return a state update to the client (board, rack, score, movelist, etc.)
    return jsonify(game.client_state(1 - opponent_index))


def fetch_users(
    ulist: Iterable[T], uid_func: Callable[[T], Optional[str]]
) -> Dict[str, User]:
    """Return a dictionary of users found in the ulist"""
    # Make a set of user ids by applying the uid_func
    # to ulist entries (!= None)
    uids: Set[str] = set(uid for u in ulist if (uid := (u is not None) and uid_func(u)))
    # No need for a special case for an empty list
    user_objects = User.load_multi(uids)
    # Return a dictionary mapping user ids to users
    return {uid: user for uid, user in zip(uids, user_objects)}


def _userlist(query: str, spec: str) -> UserList:
    """Return a list of users matching the filter criteria"""

    result: UserList = []

    def elo_str(elo: Union[None, int, str]) -> str:
        """Return a string representation of an Elo score, or a hyphen if none"""
        return str(elo) if elo else "-"

    cuser = current_user()
    cuid = None if cuser is None else cuser.id()
    locale = cuser.locale if cuser and cuser.locale else DEFAULT_LOCALE

    if query == "robots":
        # Return the list of available autoplayers for the user's locale
        aplist = AutoPlayer.for_locale(locale)
        for r in aplist:
            result.append(
                UserListDict(
                    userid="robot-" + str(r.level),
                    robot_level=r.level,
                    nick=r.name,
                    fullname=r.description,
                    elo=elo_str(None),
                    human_elo=elo_str(None),
                    fav=False,
                    chall=False,
                    fairplay=False,  # The robots don't play fair ;-)
                    newbag=True,
                    ready=True,  # The robots are always ready for a challenge
                    ready_timed=False,  # Timed games are not available for robots
                    live=True,  # robots are always online
                    image="",
                )
            )
        # That's it; we're done (no sorting required)
        return result

    # Generate a list of challenges issued by this user
    challenges: Set[str] = set()
    if cuid:
        challenges.update(
            # ch[0] is the identifier of the challenged user
            [
                cid
                for ch in ChallengeModel.list_issued(cuid, max_len=20)
                if (cid := ch[0]) is not None
            ]
        )

    # Note that we only consider online users in the same locale
    # as the requesting user
    online = firebase.online_users(locale)

    if query == "live":
        # Return a sample (no larger than MAX_ONLINE items) of online (live) users

        iter_online: Iterable[str]
        if len(online) > MAX_ONLINE:
            iter_online = random.sample(list(online), MAX_ONLINE)
        else:
            iter_online = online

        ousers = User.load_multi(iter_online)
        for lu in ousers:
            if lu and lu.is_displayable() and (uid := lu.id()) and uid != cuid:
                # Don't display the current user in the online list
                chall = uid in challenges
                result.append(
                    UserListDict(
                        userid=uid,
                        robot_level=0,
                        nick=lu.nickname(),
                        fullname=lu.full_name(),
                        elo=elo_str(lu.elo()),
                        human_elo=elo_str(lu.human_elo()),
                        fav=False if cuser is None else cuser.has_favorite(uid),
                        chall=chall,
                        fairplay=lu.fairplay(),
                        newbag=True,
                        ready=lu.is_ready(),
                        ready_timed=lu.is_ready_timed(),
                        live=True,
                        image=lu.image(),
                    )
                )

    elif query == "fav":
        # Return favorites of the current user
        # Note: this is currently not locale-constrained,
        # which may well turn out to be a bug
        if cuid is not None:
            i = set(FavoriteModel.list_favorites(cuid))
            # Do a multi-get of the entire favorites list
            fusers = User.load_multi(i)
            for fu in fusers:
                if fu and fu.is_displayable() and (favid := fu.id()):
                    chall = favid in challenges
                    result.append(
                        UserListDict(
                            userid=favid,
                            robot_level=0,
                            nick=fu.nickname(),
                            fullname=fu.full_name(),
                            elo=elo_str(fu.elo()),
                            human_elo=elo_str(fu.human_elo()),
                            fav=True,
                            chall=chall,
                            fairplay=fu.fairplay(),
                            newbag=True,
                            live=favid in online,
                            ready=fu.is_ready(),
                            ready_timed=fu.is_ready_timed(),
                            image=fu.image(),
                        )
                    )

    elif query == "alike":
        # Return users with similar Elo ratings, in the same locale
        # as the requesting user
        if cuid is not None:
            assert cuser is not None
            ui = UserModel.list_similar_elo(
                cuser.human_elo(), max_len=40, locale=locale
            )
            ausers = User.load_multi(ui)
            for au in ausers:
                if au and au.is_displayable() and (uid := au.id()) and uid != cuid:
                    chall = uid in challenges
                    result.append(
                        UserListDict(
                            userid=uid,
                            robot_level=0,
                            nick=au.nickname(),
                            fullname=au.full_name(),
                            elo=elo_str(au.elo()),
                            human_elo=elo_str(au.human_elo()),
                            fav=False if cuser is None else cuser.has_favorite(uid),
                            chall=chall,
                            fairplay=au.fairplay(),
                            live=uid in online,
                            newbag=True,
                            ready=au.is_ready(),
                            ready_timed=au.is_ready_timed(),
                            image=au.image(),
                        )
                    )

    elif query == "ready_timed":
        # Display users who are online and ready for a timed game.
        # Note that the online list is already filtered by locale,
        # so the result is also filtered by locale.
        if len(online) > MAX_ONLINE:
            iter_online = random.sample(list(online), MAX_ONLINE)
        else:
            iter_online = online

        online_users = User.load_multi(iter_online)

        for user in online_users:

            if not user or not user.is_ready_timed() or not user.is_displayable():
                # Only return users that are ready to play timed games
                continue
            if (user_id := user.id()) == cuid or not user_id:
                # Don't include the current user in the list
                continue
            result.append(
                UserListDict(
                    userid=user_id,
                    robot_level=0,
                    nick=user.nickname(),
                    fullname=user.full_name(),
                    elo=elo_str(user.elo()),
                    human_elo=elo_str(user.human_elo()),
                    fav=False if cuser is None else cuser.has_favorite(user_id),
                    chall=user_id in challenges,
                    fairplay=user.fairplay(),
                    newbag=True,
                    ready=user.is_ready(),
                    ready_timed=True,
                    live=True,
                    image=user.image(),
                )
            )

    elif query == "search":
        # Return users with nicknames matching a pattern
        si: List[ListPrefixDict] = []
        if spec:
            # Limit the spec to 16 characters
            spec = spec[0:16]

            # The "N:" prefix is a version header; the locale is also a cache key
            cache_range = "6:" + spec.lower() + ":" + locale  # Case is not significant

            # Start by looking in the cache
            si = memcache.get(cache_range, namespace="userlist")
            if si is None:
                # Not found: do a query, returning max 25 users
                si = list(UserModel.list_prefix(spec, max_len=25, locale=locale))
                # Store the result in the cache with a lifetime of 2 minutes
                memcache.set(cache_range, si, time=2 * 60, namespace="userlist")

        for ud in si:
            if not (uid := ud.get("id")) or uid == cuid:
                continue
            chall = uid in challenges
            result.append(
                UserListDict(
                    userid=uid,
                    robot_level=0,
                    nick=ud["nickname"],
                    fullname=User.full_name_from_prefs(ud["prefs"]),
                    elo=elo_str(ud["elo"] or str(User.DEFAULT_ELO)),
                    human_elo=elo_str(ud["human_elo"] or str(User.DEFAULT_ELO)),
                    fav=False if cuser is None else cuser.has_favorite(uid),
                    chall=chall,
                    live=uid in online,
                    fairplay=User.fairplay_from_prefs(ud["prefs"]),
                    newbag=True,
                    ready=ud["ready"] or False,
                    ready_timed=ud["ready_timed"] or False,
                    image=User.image_url(uid, ud["image"], ud["has_image_blob"]),
                )
            )

    # Sort the user list. The result is approximately like so:
    # 1) Users who are online and ready for timed games.
    # 2) Users who are online and ready to accept challenges.
    # 3) Users who are online.
    # 4) Users who are ready to accept challenges.
    # 5) All other users.
    # Each category is sorted by nickname, case-insensitive.
    readiness: Callable[[UserListDict], int] = lambda x: (
        4 if x["ready_timed"] else 2 if x["ready"] else 0
    ) + (1 if x["live"] else 0)
    result.sort(
        key=lambda x: (
            # First by readiness (most ready first)
            -readiness(x),
            # Then by nickname
            current_alphabet().sortkey_nocase(x["nick"]),
        )
    )
    return result


def _gamelist(cuid: str, include_zombies: bool = True) -> GameList:
    """Return a list of active and zombie games for the current user"""
    result: GameList = []
    if not cuid:
        return result

    now = datetime.utcnow()
    cuser = current_user()
    online = firebase.online_users(
        cuser.locale if cuser and cuser.locale else DEFAULT_LOCALE
    )
    u: Optional[User] = None

    # Place zombie games (recently finished games that this player
    # has not seen) at the top of the list
    if include_zombies:
        for g in ZombieModel.list_games(cuid):
            opp = g["opp"]  # User id of opponent
            u = User.load_if_exists(opp)
            if u is None:
                continue
            uuid = g["uuid"]
            locale = g["locale"]
            nick = u.nickname()
            prefs: Optional[PrefsDict] = g.get("prefs", None)
            fairplay = Game.fairplay_from_prefs(prefs)
            new_bag = Game.new_bag_from_prefs(prefs)
            manual = Game.manual_wordcheck_from_prefs(prefs)
            # Time per player in minutes
            timed = Game.get_duration_from_prefs(prefs)
            result.append(
                GameListDict(
                    uuid=uuid,
                    locale=locale,
                    # Mark zombie state
                    url=url_for("web.board", game=uuid, zombie="1"),
                    oppid=opp,
                    opp=nick,
                    fullname=u.full_name(),
                    sc0=g["sc0"],
                    sc1=g["sc1"],
                    ts=Alphabet.format_timestamp_short(g["ts"]),
                    my_turn=False,
                    overdue=False,
                    zombie=True,
                    prefs={
                        "fairplay": fairplay,
                        "newbag": new_bag,
                        "manual": manual,
                    },
                    timed=timed,
                    live=opp in online,
                    image=u.image(),
                    fav=False if cuser is None else cuser.has_favorite(opp),
                    tile_count=100,  # All tiles (100%) accounted for
                    robot_level=0,  # Should not be used; zombie games are human-only
                    elo=u.elo(),
                    human_elo=u.human_elo(),
                )
            )
        # Sort zombies in decreasing order by last move,
        # i.e. most recently completed games first
        result.sort(key=lambda x: x["ts"], reverse=True)

    # Obtain up to 50 live games where this user is a player
    i = list(GameModel.iter_live_games(cuid, max_len=50))
    # Sort in reverse order by turn and then by timestamp of the last move,
    # i.e. games with newest moves first
    i.sort(key=lambda x: (x["my_turn"], x["ts"]), reverse=True)
    # Multi-fetch the opponents in the game list
    opponents = fetch_users(i, lambda g: g["opp"])
    # Iterate through the game list
    for g in i:
        if g is None:
            continue
        u = None
        uuid = g["uuid"]
        opp = g["opp"]  # User id of opponent
        ts = g["ts"]
        locale = g["locale"]
        overdue = False
        prefs = g.get("prefs", None)
        tileset = Game.tileset_from_prefs(locale, prefs)
        fairplay = Game.fairplay_from_prefs(prefs)
        new_bag = Game.new_bag_from_prefs(prefs)
        manual = Game.manual_wordcheck_from_prefs(prefs)
        # Time per player in minutes
        timed = Game.get_duration_from_prefs(prefs)
        fullname = ""
        robot_level: int = 0
        if opp is None:
            # Autoplayer opponent
            robot_level = g["robot_level"]
            nick = AutoPlayer.name(locale, robot_level)
        else:
            # Human opponent
            try:
                u = opponents[opp]
            except KeyError:
                # This should not happen, but try to cope nevertheless
                u = User.load_if_exists(opp)
                if u is None:
                    continue
            nick = u.nickname()
            fullname = u.full_name()
            delta = now - ts
            if g["my_turn"]:
                # Start to show warning after 12 days
                overdue = delta >= timedelta(days=Game.OVERDUE_DAYS - 2)
            else:
                # Show mark after 14 days
                overdue = delta >= timedelta(days=Game.OVERDUE_DAYS)
        result.append(
            GameListDict(
                uuid=uuid,
                locale=locale,
                url=url_for("web.board", game=uuid),
                oppid=opp,
                opp=nick,
                fullname=fullname,
                sc0=g["sc0"],
                sc1=g["sc1"],
                ts=Alphabet.format_timestamp_short(ts),
                my_turn=g["my_turn"],
                overdue=overdue,
                zombie=False,
                prefs={
                    "fairplay": fairplay,
                    "newbag": new_bag,
                    "manual": manual,
                },
                timed=timed,
                tile_count=int(g["tile_count"] * 100 / tileset.num_tiles()),
                live=opp in online,
                image="" if u is None else u.image(),
                fav=False if cuser is None else cuser.has_favorite(opp),
                robot_level=robot_level,
                elo=0 if u is None else u.elo(),
                human_elo=0 if u is None else u.human_elo(),
            )
        )
    return result


def _rating(kind: str) -> List[Dict[str, Any]]:
    """Return a list of Elo ratings of the given kind ('all' or 'human')"""
    result: List[Dict[str, Any]] = []
    cuser = current_user()
    cuid = None if cuser is None else cuser.id()

    # Generate a list of challenges issued by this user
    challenges: Set[Optional[str]] = set()
    if cuid:
        challenges.update(
            # ch[0] is the identifier of the challenged user
            [ch[0] for ch in ChallengeModel.list_issued(cuid, max_len=20)]
        )

    rating_list = memcache.get(kind, namespace="rating")
    if rating_list is None:
        # Not found: do a query
        rating_list = list(RatingModel.list_rating(kind))
        # Store the result in the cache with a lifetime of 1 hour
        memcache.set(kind, rating_list, time=1 * 60 * 60, namespace="rating")

    for ru in rating_list:

        uid = ru["userid"]
        if not uid:
            # Hit the end of the list
            break
        inactive = False
        if uid.startswith("robot-"):
            # Assume that the user id has the format robot-level-locale,
            # for instance robot-15-en. If the locale is missing, use "is".
            a = uid.split("-")
            lc = a[2] if len(a) >= 3 else "is"
            nick = AutoPlayer.name(lc, int(uid[6:]))
            fullname = nick
            chall = False
            fairplay = False
        else:
            usr = User.load_if_exists(uid)
            if usr is None:
                # Something wrong with this one: don't bother
                continue
            nick = usr.nickname()
            if not User.is_valid_nick(nick):
                nick = "--"
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

        result.append(
            {
                "rank": ru["rank"],
                "rank_yesterday": ru["rank_yesterday"],
                "rank_week_ago": ru["rank_week_ago"],
                "rank_month_ago": ru["rank_month_ago"],
                "userid": uid,
                "nick": nick,
                "fullname": fullname,
                "chall": chall,
                "fairplay": fairplay,
                "newbag": True,
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
                "avgpts": avgpts,
            }
        )

    return result


def _recentlist(cuid: Optional[str], versus: Optional[str], max_len: int) -> RecentList:
    """Return a list of recent games for the indicated user, eventually
    filtered by the opponent id (versus)"""
    result: RecentList = []
    if not cuid:
        return result

    cuser = current_user()
    # Obtain a list of recently finished games where the indicated user was a player
    rlist = GameModel.list_finished_games(cuid, versus=versus, max_len=max_len)
    # Multi-fetch the opponents in the list into a dictionary
    opponents = fetch_users(rlist, lambda g: g["opp"])

    online = firebase.online_users(cuser.locale if cuser else DEFAULT_LOCALE)

    u: Optional[User] = None

    for g in rlist:

        uuid = g["uuid"]

        prefs = g["prefs"]
        locale = g["locale"]

        opp: Optional[str] = g["opp"]
        if opp is None:
            # Autoplayer opponent
            u = None
            nick = AutoPlayer.name(locale, g["robot_level"])
        else:
            # Human opponent
            try:
                u = opponents[opp]
            except KeyError:
                u = User.load_if_exists(opp)
                if u is None:
                    continue
            nick = u.nickname()

        # Calculate the duration of the game in days, hours, minutes
        ts_start = g["ts"]
        ts_end = g["ts_last_move"]

        if (ts_start is None) or (ts_end is None):
            days, hours, minutes = (0, 0, 0)
        else:
            td = ts_end - ts_start  # Timedelta
            tsec = td.total_seconds()
            days, tsec = divmod(tsec, 24 * 60 * 60)
            hours, tsec = divmod(tsec, 60 * 60)
            minutes, tsec = divmod(tsec, 60)  # Ignore the remaining seconds

        result.append(
            RecentListDict(
                uuid=uuid,
                locale=locale,
                url=url_for("web.board", game=uuid),
                oppid=opp,
                opp=nick,
                opp_is_robot=opp is None,
                robot_level=g["robot_level"],
                sc0=g["sc0"],
                sc1=g["sc1"],
                elo_adj=g["elo_adj"],
                human_elo_adj=g["human_elo_adj"],
                ts_last_move=Alphabet.format_timestamp_short(ts_end),
                days=int(days),
                hours=int(hours),
                minutes=int(minutes),
                prefs={
                    "duration": Game.get_duration_from_prefs(prefs),
                    "manual": Game.manual_wordcheck_from_prefs(prefs),
                },
                live=False if opp is None else opp in online,
                image="" if u is None else u.image(),
                elo=0 if u is None else u.elo(),
                human_elo=0 if u is None else u.human_elo(),
                fav=False if cuser is None or opp is None else cuser.has_favorite(opp),
            )
        )
    return result


def _opponent_waiting(user_id: str, opp_id: str, *, key: Optional[str]) -> bool:
    """Return True if the given opponent is waiting on this user's challenge"""
    return firebase.check_wait(opp_id, user_id, key)


def _challengelist() -> ChallengeList:
    """Return a list of challenges issued or received by the current user"""

    result: ChallengeList = []
    cuser = current_user()
    assert cuser is not None
    cuid = cuser.id()
    assert cuid is not None

    def is_timed(prefs: Optional[Dict[str, Any]]) -> bool:
        """Return True if the challenge is for a timed game"""
        if prefs is None:
            return False
        return int(prefs.get("duration", 0)) > 0

    def opp_ready(c: ChallengeTuple):
        """Returns True if this is a timed challenge
        and the opponent is ready to play"""
        if not is_timed(c.prefs):
            return False
        # Timed challenge: see if there is a Firebase path indicating
        # that the opponent is waiting for this user
        assert cuid is not None
        assert c.opp is not None
        return _opponent_waiting(cuid, c.opp, key=c.key)

    online = firebase.online_users(
        cuser.locale if cuser and cuser.locale else DEFAULT_LOCALE
    )
    # List received challenges
    received = list(ChallengeModel.list_received(cuid, max_len=20))
    # List issued challenges
    issued = list(ChallengeModel.list_issued(cuid, max_len=20))
    # Multi-fetch all opponents involved
    opponents = fetch_users(received + issued, lambda c: c[0])
    # List the received challenges
    for c in received:
        if not (oppid := c.opp):
            continue
        if (u := opponents.get(oppid)) is None:  # User id
            continue
        nick = u.nickname()
        result.append(
            ChallengeListDict(
                key=c.key,  # ChallengeModel entity key
                received=True,
                userid=oppid,
                opp=nick,
                fullname=u.full_name(),
                prefs=c.prefs,
                ts=Alphabet.format_timestamp_short(c.ts),
                opp_ready=False,
                live=oppid in online,
                image=u.image(),
                fav=False if cuser is None else cuser.has_favorite(oppid),
                elo=0 if u is None else u.elo(),
                human_elo=0 if u is None else u.human_elo(),
            )
        )
    # List the issued challenges
    for c in issued:
        if not (oppid := c.opp):
            continue
        if (u := opponents.get(oppid)) is None:  # User id
            continue
        nick = u.nickname()
        result.append(
            ChallengeListDict(
                key=c.key,  # ChallengeModel entity key
                received=False,
                userid=oppid,
                opp=nick,
                fullname=u.full_name(),
                prefs=c.prefs,
                ts=Alphabet.format_timestamp_short(c.ts),
                opp_ready=opp_ready(c),
                live=oppid in online,
                image=u.image(),
                fav=False if cuser is None else cuser.has_favorite(oppid),
                elo=0 if u is None else u.elo(),
                human_elo=0 if u is None else u.human_elo(),
            )
        )
    return result


@api.route("/submitmove", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def submitmove() -> ResponseType:
    """Handle a move that is being submitted from the client"""
    # This URL should only receive Ajax POSTs from the client
    rq = RequestData(request)
    movelist = rq.get_list("moves")
    movecount = rq.get_int("mcount")
    uuid = rq.get("uuid")

    game = None if uuid is None else Game.load(uuid, use_cache=False, set_locale=True)

    if game is None:
        return jsonify(result=Error.GAME_NOT_FOUND)

    # Make sure the client is in sync with the server:
    # check the move count
    if movecount != game.num_moves():
        return jsonify(result=Error.OUT_OF_SYNC)

    if game.player_id_to_move() != current_user_id():
        return jsonify(result=Error.WRONG_USER)

    # Process the movestring
    # Try twice in case of timeout or other exception
    result: ResponseType = jsonify(result=Error.LEGAL)
    for attempt in reversed(range(2)):
        # pylint: disable=broad-except
        try:
            result = _process_move(game, movelist)
        except Exception as e:
            logging.info(
                "Exception in submitmove(): {0} {1}".format(
                    e, "- retrying" if attempt > 0 else ""
                )
            )
            if attempt == 0:
                # Final attempt failed
                result = jsonify(result=Error.SERVER_ERROR)
        else:
            # No exception: done
            break
    assert result is not None
    return result


@api.route("/gamestate", methods=["POST"])
@auth_required(ok=False)
def gamestate() -> ResponseType:
    """Returns the current state of a game"""

    user_id = current_user_id()
    if user_id is None:
        return jsonify(ok=False)

    rq = RequestData(request)
    uuid = rq.get("game")
    delete_zombie = rq.get_bool("delete_zombie", False)

    game = Game.load(uuid, use_cache=False, set_locale=True) if uuid else None

    if game is None:
        # We must have a logged-in user and a valid game
        return jsonify(ok=False)

    player_index = game.player_index(user_id)
    if player_index is None and not game.is_over():
        # The game is still ongoing and this user is not one of the players:
        # refuse the request
        return jsonify(ok=False)

    # If we are being asked to remove the game's zombie status, do it
    if delete_zombie:
        ZombieModel.del_game(uuid, user_id)

    return jsonify(ok=True, game=game.client_state(player_index, deep=True))


@api.route("/clear_zombie", methods=["POST"])
@auth_required(ok=False)
def clear_zombie() -> ResponseType:
    """Clears the zombie status of a game"""

    user_id = current_user_id()
    if user_id is None:
        return jsonify(ok=False)

    rq = RequestData(request)
    uuid = rq.get("game")

    game = Game.load(uuid) if uuid else None

    if game is None:
        # We must have a logged-in user and a valid game
        return jsonify(ok=False)

    player_index = game.player_index(user_id)
    if player_index is None:
        # This user is not one of the players: refuse the request
        return jsonify(ok=False)

    ZombieModel.del_game(uuid, user_id)

    return jsonify(ok=True)


@api.route("/forceresign", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def forceresign() -> ResponseType:
    """Forces a tardy user to resign, if the game is overdue"""

    user_id = current_user_id()
    rq = RequestData(request)
    uuid = rq.get("game")
    movecount = rq.get_int("mcount", -1)

    game = None if uuid is None else Game.load(uuid, use_cache=False, set_locale=True)

    if game is None:
        return jsonify(result=Error.GAME_NOT_FOUND)

    # Only the user who is the opponent of the tardy user can force a resign
    if game.player_id(1 - game.player_to_move()) != user_id:
        return jsonify(result=Error.WRONG_USER)

    # Make sure the client is in sync with the server:
    # check the move count
    if movecount != game.num_moves():
        return jsonify(result=Error.OUT_OF_SYNC)

    if not game.is_overdue():
        return jsonify(result=Error.GAME_NOT_OVERDUE)

    # Send in a resign move on behalf of the opponent
    return _process_move(game, ["rsgn"], force_resign=True)


@api.route("/wordcheck", methods=["POST"])
@auth_required(ok=False)
def wordcheck() -> ResponseType:
    """Check a list of words for validity"""

    rq = RequestData(request)
    words: List[str] = rq.get_list("words")
    word: str = rq["word"]
    board_size = Board.SIZE

    # Sanity check the word list: we should never need to check more than 16 words
    # (major-axis word plus up to 15 cross-axis words)
    if (
        not words
        or len(words) > board_size + 1
        or any(len(w) > board_size for w in words)
    ):
        return jsonify(ok=False)

    # If a locale is included in the request,
    # use it within the current thread for the vocabulary lookup
    locale: Optional[str] = rq.get("locale")

    if locale:
        set_game_locale(to_supported_locale(locale))

    # Check the words against the dictionary
    wdb = Wordbase.dawg()
    valid = [(w, w in wdb) for w in words]
    ok = all(v[1] for v in valid)
    return jsonify(word=word, ok=ok, valid=valid)


@api.route("/gamestats", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def gamestats() -> ResponseType:
    """Calculate and return statistics on a given finished game"""

    rq = RequestData(request)
    uuid = rq.get("game")
    game = None

    if uuid is not None:
        game = Game.load(uuid, set_locale=True, use_cache=False)
        # Check whether the game is still in progress
        if (game is not None) and not game.is_over():
            # Don't allow looking at the stats in this case
            game = None

    if game is None:
        return jsonify(result=Error.GAME_NOT_FOUND)

    return jsonify(game.statistics())


@api.route("/userstats", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def userstats() -> ResponseType:
    """Return the profile of a given user along with key statistics"""
    cuser = current_user()
    if cuser is None:
        return jsonify(result=Error.LOGIN_REQUIRED)
    cid = cuser.id()
    rq = RequestData(request)
    uid = rq.get("user", cid or "")  # Current user is implicit
    error, us = User.stats(uid, cuser)
    if error != Error.LEGAL or us is None:
        return jsonify(result=error or Error.WRONG_USER)
    return jsonify(us)


@api.route("/image", methods=["GET", "POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def image() -> ResponseType:
    """Set (POST) or get (GET) the image of a user"""
    rq = RequestData(request, use_args=True)
    method: str = cast(Any, request).method
    cuid = current_user_id()
    assert cuid is not None
    uid = rq.get("uid") or cuid
    if method == "POST" and uid != cuid:
        # Can't update another user's image
        return "Not authorized", 403  # Forbidden
    um = UserModel.fetch(uid)
    if not um:
        return "User not found", 404  # Not found
    if method == "GET":
        # Get image for user
        image, image_blob = um.get_image()
        if image_blob:
            # We have the image as a bytes object: return it
            mimetype = image or "image/jpeg"
            return Response(
                image_blob, mimetype=mimetype, content_type="application/octet-stream"
            )
        if not image or image.startswith("/image"):
            return "Image not found", 404  # Not found
        # Assume that this is a URL: redirect to it
        return redirect(image)
    # Method is POST: update image for current user
    mimetype = request.mimetype
    if mimetype == "text/plain":
        # Assume that an image URL is being set
        if (request.content_length or 0) > 256:
            return "URL too long", 400  # Bad request
        url = request.get_data(as_text=True).strip()
        if url.startswith("https://"):
            # Looks superficially legit
            um.set_image(url, None)
            return "OK", 200
        return "Invalid URL", 400  # Bad request
    elif mimetype.startswith("image/"):
        um.set_image(mimetype, request.get_data(as_text=False))
        return "OK", 200
    return "Unrecognized MIME type", 400


@api.route("/userlist", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def userlist() -> ResponseType:
    """Return user lists with particular criteria"""

    rq = RequestData(request)
    query = rq.get("query")
    spec = rq.get("spec")
    return jsonify(result=Error.LEGAL, spec=spec, userlist=_userlist(query, spec))


@api.route("/gamelist", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def gamelist() -> ResponseType:
    """Return a list of active games for the current user"""

    # Specify "zombies":false to omit zombie games from the returned list
    rq = RequestData(request)
    include_zombies = rq.get_bool("zombies", True)
    cuid = current_user_id()
    if cuid is None:
        return jsonify(result=Error.WRONG_USER)
    return jsonify(result=Error.LEGAL, gamelist=_gamelist(cuid, include_zombies))


@api.route("/recentlist", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def recentlist() -> ResponseType:
    """Return a list of recently completed games for the indicated user"""

    rq = RequestData(request)
    user_id: Optional[str] = rq.get("user")
    versus: Optional[str] = rq.get("versus")
    count = rq.get_int("count", 14)  # Default number of recent games to return

    # Limit count to 50 games
    if count > 50:
        count = 50
    elif count < 1:
        count = 1

    if not user_id:
        user_id = current_user_id()

    # _recentlist() returns an empty list for a nonexistent user

    return jsonify(
        result=Error.LEGAL,
        recentlist=_recentlist(user_id, versus=versus, max_len=count),
    )


@api.route("/challengelist", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def challengelist() -> ResponseType:
    """Return a list of challenges issued or received by the current user"""
    return jsonify(result=Error.LEGAL, challengelist=_challengelist())


@api.route("/allgamelists", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def allgamelists() -> ResponseType:
    """Return a combined dict with the results of the gamelist,
    challengelist and recentlist calls, for the current user"""
    cuid = current_user_id()
    if cuid is None:
        return jsonify(result=Error.WRONG_USER)
    rq = RequestData(request)
    count = rq.get_int("count", 14)  # Default number of recent games to return
    # Limit count to 50 games
    if count > 50:
        count = 50
    elif count < 1:
        count = 1
    include_zombies = rq.get_bool("zombies", True)
    return jsonify(
        result=Error.LEGAL,
        gamelist=_gamelist(cuid, include_zombies),
        challengelist=_challengelist(),
        recentlist=_recentlist(cuid, versus=None, max_len=count),
    )


@api.route("/rating", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def rating() -> ResponseType:
    """Return the newest Elo ratings table (top 100)
    of a given kind ('all' or 'human')"""
    rq = RequestData(request)
    kind = rq.get("kind", "all")
    if kind not in ("all", "human", "manual"):
        kind = "all"
    return jsonify(result=Error.LEGAL, rating=_rating(kind))


@api.route("/favorite", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def favorite() -> ResponseType:
    """Create or delete an A-favors-B relation"""

    user = current_user()
    assert user is not None

    rq = RequestData(request)
    destuser = rq.get("destuser")
    action = rq.get("action", "add")

    if destuser:
        if action == "add":
            user.add_favorite(destuser)
        elif action == "delete":
            user.del_favorite(destuser)

    return jsonify(result=Error.LEGAL)


@api.route("/challenge", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def challenge() -> ResponseType:
    """Create or delete an A-challenges-B relation"""

    user = current_user()
    if user is None or not (uid := user.id()):
        return jsonify(result=Error.LOGIN_REQUIRED)

    rq = RequestData(request)
    destuser = rq.get("destuser")
    if not destuser:
        return jsonify(result=Error.WRONG_USER)
    action = rq.get("action", "issue")
    duration = rq.get_int("duration")
    fairplay = rq.get_bool("fairplay")
    manual = rq.get_bool("manual")
    # Fetch an optional key of the challenge being acted on
    key = rq.get("key")

    # Ensure that the duration is reasonable
    if duration < 0:
        duration = 0
    elif duration > 90:
        duration = 90

    if action == "issue":
        user.issue_challenge(
            destuser,
            {
                "duration": duration,
                "fairplay": fairplay,
                "newbag": True,
                "manual": manual,
                # A challenge is by default bound to the issuing user's locale
                "locale": user.locale,
            },
        )
    elif action == "retract":
        user.retract_challenge(destuser, key=key)
    elif action == "decline":
        # Decline challenge previously made by the destuser (really srcuser)
        user.decline_challenge(destuser, key=key)
    elif action == "accept":
        # Accept a challenge previously made by the destuser (really srcuser)
        user.accept_challenge(destuser, key=key)
    # Notify both users via a
    # Firebase notification to /user/[user_id]/challenge
    msg: Dict[str, str] = dict()

    # Notify both players' clients of an update to the challenge lists
    now = datetime.utcnow().isoformat()
    msg[f"user/{destuser}/challenge"] = now
    msg[f"user/{uid}/challenge"] = now
    firebase.send_message(msg)

    return jsonify(result=Error.LEGAL)


@api.route("/setuserpref", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def setuserpref() -> ResponseType:
    """Set a user preference"""

    user = current_user()
    assert user is not None

    rq = RequestData(request)
    is_mobile = is_mobile_client()

    # Loop through the various preference booleans and set them
    # by calling the associated function on the User instance.
    # The last bool parameter is True if the setting is only
    # available for mobile clients.
    prefs: List[Tuple[str, Callable[[bool], None], bool]] = [
        ("beginner", user.set_beginner, False),
        ("ready", user.set_ready, False),
        ("ready_timed", user.set_ready_timed, False),
        ("chat_disabled", user.disable_chat, False),
        ("friend", user.set_friend, True),
        ("has_paid", user.set_has_paid, True),
    ]

    update = False
    for s, func, mobile_only in prefs:
        val = rq.get_bool(s, None)
        if val is not None and (is_mobile or not mobile_only):
            func(val)
            update = True

    # We allow the locale to be set as a user preference.
    # Note that it cannot be read back as a preference!
    if lc := rq.get("locale", ""):
        # Do some rudimentary normalization and validation of the locale code
        lc = lc.replace("-", "_")
        a = lc.split("_")
        # Locales have one or two parts, separated by an underscore,
        # and each part is a two-letter code.
        if 1 <= len(a) <= 2 and all(len(x) == 2 and x.isalpha() for x in a):
            user.set_locale(to_supported_locale(lc))
            update = True

    if update:
        user.update()

    return jsonify(result=Error.LEGAL, did_update=update)


@api.route("/onlinecheck", methods=["POST"])
@auth_required(online=False)
def onlinecheck() -> ResponseType:
    """Check whether a particular user is online"""
    rq = RequestData(request)
    if user_id := rq.get("user"):
        user = User.load_if_exists(user_id)
        if not user:
            online = False
        else:
            online = firebase.check_presence(user_id, user.locale)
    else:
        online = False
    return jsonify(online=online)


@api.route("/initwait", methods=["POST"])
@auth_required(online=False, waiting=False)
def initwait() -> ResponseType:
    """Initialize a wait for a timed game to start"""

    user = current_user()

    # Get the opponent id
    rq = RequestData(request)
    opp: Optional[str] = rq.get("opp")
    if not opp or user is None or not (uid := user.id()):
        return jsonify(online=False, waiting=False)

    # Find the challenge being accepted, optionally by explicit key
    # but otherwise by the (source user, destination user) tuple
    key: Optional[str] = rq.get("key")  # Can be omitted
    found, prefs = user.find_challenge(opp, key=key)
    if not found or prefs is None or not int(prefs.get("duration", 0)) > 0:
        # No timed challenge existed between the users
        return jsonify(online=False, waiting=False)

    opp_user = User.load_if_exists(opp)
    if opp_user is None:
        # Opponent id not found
        return jsonify(online=False, waiting=False)

    # Notify the opponent of a change in the challenge list
    # via a Firebase notification to /user/[user_id]/challenge
    now = datetime.utcnow().isoformat()
    msg = {
        f"user/{opp}/challenge": now,
        f"user/{uid}/wait/{opp}": {"key": key} if key else True,
    }
    firebase.send_message(msg)
    online = firebase.check_presence(uid, user.locale)
    return jsonify(online=online, waiting=True)


@api.route("/waitcheck", methods=["POST"])
@auth_required(waiting=False)
def waitcheck() -> ResponseType:
    """Check whether a particular opponent is waiting on a challenge"""
    rq = RequestData(request)
    opp_id = rq.get("user")
    key: Optional[str] = rq.get("key")  # Can be omitted
    waiting = False
    if opp_id:
        cuid = current_user_id()
        assert cuid is not None
        waiting = _opponent_waiting(cuid, opp_id, key=key)
    return jsonify(userid=opp_id, waiting=waiting)


@api.route("/cancelwait", methods=["POST"])
@auth_required(ok=False)
def cancelwait() -> ResponseType:
    """A wait on a challenge has been cancelled"""
    rq = RequestData(request)
    opp_id = rq.get("opp")
    cuid = current_user_id()

    if not opp_id or not cuid:
        return jsonify(ok=False)

    # Delete the current wait and force update of the opponent's challenge list
    now = datetime.utcnow().isoformat()
    msg = {
        f"user/{cuid}/wait/{opp_id}": None,
        f"user/{opp_id}/challenge": now,
    }
    firebase.send_message(msg)

    return jsonify(ok=True)


@api.route("/chatmsg", methods=["POST"])
@auth_required(ok=False)
def chatmsg() -> ResponseType:
    """Send a chat message on a conversation channel"""

    user_id = current_user_id()
    if not user_id:
        return jsonify(ok=False)

    rq = RequestData(request)
    channel = rq.get("channel", "")

    if not channel:
        # We must have a valid channel
        return jsonify(ok=False)

    msg = rq.get("msg", "")
    md: Dict[str, str]
    send_msg: Dict[str, Dict[str, str]] = {}

    if channel.startswith("game:"):

        # In-game chat
        # Send notifications to both players on the game channel
        game: Optional[Game] = None
        uuid = channel[5:][:36]  # The game id
        if uuid:
            # We don't set use_cache=False here since we are only
            # accessing game data that remains constant for the
            # entire duration of a game, i.e. the player info
            game = Game.load(uuid, set_locale=True)
        if game is None or not game.has_player(user_id):
            # The logged-in user must be a player in the game
            return jsonify(ok=False)
        # Find out who the opponent is
        if (opp := game.player_id(0)) == user_id:
            opp = game.player_id(1)
        if not opp:
            return jsonify(ok=False)
        # Add a message entity to the data store and remember its timestamp
        ts = ChatModel.add_msg_in_game(uuid, user_id, opp, msg)
        if msg:
            # No need to send empty messages, which are to be interpreted
            # as read confirmations
            # The message to be sent in JSON form via Firebase
            md = dict(
                game=uuid,
                from_userid=user_id,
                to_userid=opp,
                msg=msg,
                ts=Alphabet.format_timestamp(ts),
            )
            for p in range(0, 2):
                # Send a Firebase notification to /game/[gameid]/[userid]/chat
                if pid := game.player_id(p):
                    send_msg[f"game/{uuid}/{pid}/chat"] = md
            if send_msg:
                firebase.send_message(send_msg)

    elif channel.startswith("user:"):

        # Chat between two users
        opp_id = channel[5:][:36]  # The opponent id
        if not opp_id:
            return jsonify(ok=False)
        # Add a message entity to the data store and remember its timestamp
        ts = ChatModel.add_msg_between_users(user_id, opp_id, msg)
        if msg:
            # No need to send empty messages, which are to be interpreted
            # as read confirmations
            # The message to be sent in JSON form via Firebase
            md = dict(
                from_userid=user_id,
                to_userid=opp_id,
                msg=msg,
                ts=Alphabet.format_timestamp(ts),
            )
            send_msg[f"user/{user_id}/chat"] = md
            send_msg[f"user/{opp_id}/chat"] = md
            firebase.send_message(send_msg)

    else:
        # Invalid channel prefix
        return jsonify(ok=False)

    return jsonify(ok=True)


class UserCache:

    """A temporary cache for user lookups"""

    def __init__(self) -> None:
        self._cache: Dict[str, Optional[User]] = {}

    def _load(self, user_id: str) -> Optional[User]:
        if (u := self._cache.get(user_id)) is None:
            u = User.load_if_exists(user_id)
            if u is not None:
                self._cache[user_id] = u
        return u

    def full_name(self, user_id: str) -> str:
        """Return the full name of a user"""
        return "" if (u := self._load(user_id)) is None else u.full_name()

    def nickname(self, user_id: str) -> str:
        """Return the nickname of a user"""
        return "" if (u := self._load(user_id)) is None else u.nickname()

    def image(self, user_id: str) -> str:
        """Return the image for a user"""
        return "" if (u := self._load(user_id)) is None else u.image()

    def chat_disabled(self, user_id: str) -> bool:
        """Return True if the user has disabled chat"""
        if (u := self._load(user_id)) is None:
            return True  # Chat is disabled by default
        return u.chat_disabled()


@api.route("/chatload", methods=["POST"])
@auth_required(ok=False)
def chatload() -> ResponseType:
    """Load all chat messages on a conversation channel"""

    # The channel can be either 'game:' + game uuid or
    # 'user:' + user id
    user_id = current_user_id()
    if not user_id:
        # Unknown current user
        return jsonify(ok=False)

    rq = RequestData(request)
    channel = rq.get("channel", "")

    if not channel:
        # We must have a valid channel
        return jsonify(ok=False)

    if channel.startswith("game:"):
        # In-game conversation
        game: Optional[Game] = None
        uuid = channel[5:][:36]  # The game id
        if uuid:
            # We don't set use_cache=False here since we are
            # only accessing data that remains constant over the
            # lifetime of a game object, i.e. the player information
            game = Game.load(uuid, set_locale=True)
        if game is None or not game.has_player(user_id):
            # The logged-in user must be a player in the game
            return jsonify(ok=False)
    elif channel.startswith("user:"):
        # Conversation between users
        opp_id = channel[5:][:36]  # The opponent id
        if not opp_id:
            return jsonify(ok=False)
        # By convention, the lower user id comes before
        # the higher one in the channel string
        if opp_id < user_id:
            channel = f"user:{opp_id}:{user_id}"
        else:
            channel = f"user:{user_id}:{opp_id}"
    else:
        # Unknown channel prefix
        return jsonify(ok=False)

    # Return the messages sorted in ascending timestamp order.
    # ChatModel.list_conversations returns them in descending
    # order since its maxlen limit cuts off the oldest messages.
    uc = UserCache()
    messages: List[ChatMessageDict] = [
        ChatMessageDict(
            from_userid=(uid := cm["user"]),
            name=uc.full_name(uid),
            image=uc.image(uid),
            msg=cm["msg"],
            ts=Alphabet.format_timestamp(cm["ts"]),
        )
        for cm in ChatModel.list_conversation(channel)
    ]
    # Check whether the user has already seen the newest chat message
    # (which may be a read marker, i.e. an empty message)
    seen = True
    for m in messages:
        from_userid = m["from_userid"]
        if from_userid != user_id and not m["msg"]:
            # Read marker from the other user: not significant
            continue
        # This is either a read marker from this user,
        # or a proper message from either user.
        seen = from_userid == user_id
        break
    # Return the message list in reverse order (oldest first) and
    # remove empty messages (read markers) from the list
    messages = [m for m in messages[::-1] if m["msg"]]
    return jsonify(ok=True, seen=seen, messages=messages)


@api.route("/chathistory", methods=["POST"])
@auth_required(ok=False)
def chathistory() -> ResponseType:
    """Return the chat history, i.e. the set of recent,
    distinct chat conversations for the logged-in user"""

    user = current_user()
    assert user is not None

    user_id = user.id()
    if not user_id:
        # Unknown current user
        return jsonify(ok=False)

    rq = RequestData(request)
    # By default, return a history of 20 conversations
    count = rq.get_int("count", 20)

    online = firebase.online_users(user.locale or DEFAULT_LOCALE)
    uc = UserCache()
    # The chat history is ordered in reverse timestamp
    # order, i.e. the newest entry comes first
    history: List[ChatHistoryDict] = [
        ChatHistoryDict(
            user=(uid := cm["user"]),
            name=uc.full_name(uid),
            nick=uc.nickname(uid),
            image=uc.image(uid),
            last_msg=cm["last_msg"],
            ts=Alphabet.format_timestamp(cm["ts"]),
            unread=cm["unread"],
            live=uid in online,
            fav=user.has_favorite(uid),
            disabled=uc.chat_disabled(uid),
        )
        for cm in ChatModel.chat_history(user_id, maxlen=count)
    ]

    return jsonify(ok=True, history=history)


@api.route("/bestmoves", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def bestmoves() -> ResponseType:
    """Return a list of the best possible moves in a game
    at a given point"""

    user = current_user()
    assert user is not None

    if not user.has_paid() and not running_local:
        # User must be a paying friend, or we're on a development server
        return jsonify(result=Error.USER_MUST_BE_FRIEND)

    rq = RequestData(request)

    uuid = rq.get("game")
    # Attempt to load the game whose id is in the URL query string
    game: Optional[Game] = (
        None if uuid is None else Game.load(uuid, set_locale=True, use_cache=False)
    )

    if game is None or not game.is_over():
        # The game is not found or still in progress: abort
        return jsonify(result=Error.GAME_NOT_FOUND)

    # move_number is the actual index into the game's move list
    # rq_move_number is the requested index, which can include the
    # final adjustment moves (rack leave, overtime adjustment, game over)
    move_number = rq_move_number = rq.get_int("move")
    final_adjustments = game.get_final_adjustments()
    num_moves = game.num_moves()
    max_index = num_moves + len(final_adjustments)

    if move_number > num_moves:
        move_number = num_moves
    elif move_number < 0:
        move_number = 0

    if rq_move_number > max_index:
        rq_move_number = max_index
    elif rq_move_number < 0:
        rq_move_number = 0

    best_moves: BestMoveList = []

    state = game.state_after_move(move_number if move_number == 0 else move_number - 1)
    player_index = state.player_to_move()

    if rq_move_number <= move_number:
        # How many best moves are being requested?
        num_moves = rq.get_int("num_moves", DEFAULT_BEST_MOVES)
        # Serialize access to the following section
        with autoplayer_lock:
            best_moves = game.best_moves(state, min(num_moves, MAX_BEST_MOVES))

    uid = user.id()
    if uid is not None and game.has_player(uid):
        # Look at the game from the point of view of this player
        user_index = game.player_index(uid)
    else:
        # This is an outside spectator: look at it from the point of view of
        # player 0, or the human player if player 0 is an autoplayer
        user_index = 1 if game.is_autoplayer(0) else 0

    # If we're showing an adjustment move, i.e. rack leave, overtime or 'game over',
    # return an empty player rack
    if rq_move_number > move_number:
        player_rack = []
    else:
        player_rack = state.rack_details(player_index)

    return jsonify(
        result=Error.LEGAL,
        move_number=rq_move_number,
        player_index=player_index,
        user_index=user_index,
        player_rack=player_rack,
        best_moves=best_moves,
    )


@api.route("/blockuser", methods=["POST"])
@auth_required(ok=False)
def blockuser() -> ResponseType:
    """Block or unblock another user"""
    user = current_user()
    assert user is not None

    rq = RequestData(request)
    blocked_id = rq.get("blocked")
    action = rq.get("action", "add")

    ok = False
    if blocked_id:
        if action == "add":
            ok = user.block(blocked_id)
        elif action == "delete":
            ok = user.unblock(blocked_id)

    return jsonify(ok=ok)


@api.route("/reportuser", methods=["POST"])
@auth_required(ok=False)
def reportuser() -> ResponseType:
    """Report another user"""
    user = current_user()
    assert user is not None

    rq = RequestData(request)
    reported_id = rq.get("reported")
    try:
        # Reason code 0 means that we have free-form text;
        # other reason codes have fixed meanings with no text
        code = int(rq.get("code", 0))
        text = str(rq.get("text", ""))
    except ValueError:
        return jsonify(ok=False)

    ok = False
    if reported_id:
        ok = user.report(reported_id, code, text)

    return jsonify(ok=ok)


@api.route("/cancelplan", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def cancelplan() -> ResponseType:
    """Cancel a user friendship"""
    user = current_user()
    if user is None:
        return jsonify(ok=False)
    result = cancel_plan(user)
    return jsonify(ok=result)


@api.route("/loaduserprefs", methods=["POST"])
@auth_required(ok=False)
def loaduserprefs() -> ResponseType:
    """Fetch the preferences of the current user in JSON form"""
    # Return the user preferences in JSON form
    uf = UserForm(current_user())
    return jsonify(ok=True, userprefs=uf.as_dict())


@api.route("/saveuserprefs", methods=["POST"])
@auth_required(ok=False)
def saveuserprefs() -> ResponseType:
    """Set the preferences of the current user, from a JSON dictionary"""

    user = current_user()
    assert user is not None
    j: Optional[Dict[str, str]] = request.get_json(silent=True)
    if j is None:
        return jsonify(ok=False, err={"reason": "Unable to parse JSON"})

    # Populate a UserForm object with the data from the JSON dictionary
    uf = UserForm()
    uf.init_from_dict(j)
    err = uf.validate()
    if err:
        return jsonify(ok=False, err=err)
    uf.store(user)
    return jsonify(ok=True)


@api.route("/inituser", methods=["POST"])
@auth_required(ok=False)
def inituser() -> ResponseType:
    """Combines the data returned from the /loaduserprefs, /userstats and /firebase_token
    API endpoints into a single endpoint, for efficiency. The result is a JSON dictionary
    with three fields, called userprefs, userstats and firebase_token."""
    cuser = current_user()
    if cuser is None:
        # No logged-in user
        return jsonify(ok=False)
    cuid = cuser.id()
    if cuid is None:
        # No logged-in user
        return jsonify(ok=False)
    try:
        error, us = User.stats(cuid, cuser)
        if error != Error.LEGAL or us is None:
            return jsonify(ok=False)
        token = firebase.create_custom_token(cuid)
        uf = UserForm(cuser)
    except:
        return jsonify(ok=False)

    return jsonify(
        ok=True,
        userprefs=uf.as_dict(),
        userstats=us,
        firebase_token=token,
    )


@api.route("/initgame", methods=["POST"])
@auth_required(ok=False)
def initgame() -> ResponseType:
    """Create a new game and return its UUID"""

    user = current_user()
    assert user is not None
    uid = user.id()
    assert uid is not None

    rq = RequestData(request)
    # Get the opponent id
    opp = rq.get("opp")
    if not opp:
        # Unknown opponent
        return jsonify(ok=False)

    if PROJECT_ID == "netskrafl":
        board_type = rq.get("board_type", current_board_type())
    else:
        board_type = "explo"

    # Is this a reverse action, i.e. the challenger initiating a timed game,
    # instead of the challenged player initiating a normal one?
    rev = rq.get_bool("rev")

    prefs: Optional[PrefsDict]

    if opp.startswith("robot-"):
        # Start a new game against an autoplayer (robot)
        robot_level = int(opp[6:])
        # The game is always in the user's locale
        prefs = dict(newbag=True, locale=user.locale)
        prefs["board_type"] = board_type
        set_game_locale(user.locale)
        game = Game.new(uid, None, robot_level, prefs=prefs)
        # Return the uuid of the new game
        return jsonify(ok=True, uuid=game.id())

    key: Optional[str] = rq.get("key", None)

    # Start a new game between two human users
    if rev:
        # Timed game: load the opponent
        opp_user = User.load_if_exists(opp)
        if opp_user is None:
            return jsonify(ok=False)
        # In this case, the opponent accepts the challenge
        found, prefs = opp_user.accept_challenge(uid, key=key)
    else:
        # The current user accepts the challenge
        found, prefs = user.accept_challenge(opp, key=key)

    if not found:
        # No challenge existed between the users
        return jsonify(ok=False)

    # Create a fresh game object, ensuring it has a board_type pref
    if prefs is None:
        prefs = dict(locale=user.locale)
    prefs["board_type"] = board_type
    set_game_locale(cast(str, prefs.get("locale")) or user.locale)
    game = Game.new(uid, opp, 0, prefs)
    game_id = game.id()
    if not game_id or game.state is None:
        # Something weird is preventing the proper creation of the game
        return jsonify(ok=False)

    # Notify both players' clients that there is a new game
    now = datetime.utcnow().isoformat()
    msg: Dict[str, Any] = dict()
    move_dict: MoveNotifyDict = {
        "game": game_id,
        "timestamp": now,
        "over": False,
        "players": (uid, opp),
        "to_move": game.player_to_move(),
        "scores": (0, 0),
        "progress": game.state.progress(),
    }
    msg[f"user/{uid}/move"] = move_dict
    msg[f"user/{opp}/move"] = move_dict

    # Notify both players' clients of an update to the challenge lists
    msg[f"user/{opp}/challenge"] = now
    msg[f"user/{uid}/challenge"] = now

    # If this is a timed game, notify the waiting party
    if prefs and cast(int, prefs.get("duration", 0)) > 0:
        msg[f"user/{opp}/wait/{uid}"] = {"game": game_id, "key": key}

    firebase.send_message(msg)

    # Return the uuid of the new game
    return jsonify(ok=True, uuid=game_id)


@api.route("/locale_asset", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def locale_asset() -> ResponseType:
    """Return static content, for the user's locale"""
    # For a locale such as en_US, we first try to serve from
    # base_path/static/assets/en_US/asset_name, then
    # base_path/static/assets/en/asset_name, and finally
    # base_path/static/assets/asset_name
    u = current_user()
    assert u is not None
    rq = RequestData(request)
    asset = rq.get("asset")
    if not asset:
        return "", 404  # Not found
    locale = u.locale or DEFAULT_LOCALE
    parts = locale.split("_")
    static_folder = current_app.static_folder or os.path.abspath("static")
    # Try en_US first, then en, then nothing
    for ix in range(len(parts), -1, -1):
        lc = "_".join(parts[0:ix])
        fname = os.path.join(static_folder, "assets", lc, asset)
        if os.path.isfile(fname):
            # Found the static asset file: return it
            return current_app.send_static_file(os.path.join("assets", lc, asset))
    return "", 404  # Not found
