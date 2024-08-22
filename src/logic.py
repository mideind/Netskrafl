"""

    Application logic layer for netskrafl.is / Explo Word Game

    Copyright (C) 2024 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl


    This module contains a middle layer between the server APIs
    (found in apy.py) and the various game functions in modules
    such as skrafluser.py, skraflmechanics.py and skraflgame.py.

"""

from __future__ import annotations

from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Set,
    Tuple,
    TypeVar,
    TypedDict,
    Union,
)

import logging
import threading
import re
import functools
from datetime import UTC, datetime, timedelta

from google.cloud import ndb  # type: ignore
from flask import url_for
import firebase

from basics import current_user, current_user_id, jsonify
from config import DEFAULT_LOCALE, DEFAULT_ELO, PROJECT_ID, ResponseType
from languages import (
    Alphabet,
    to_supported_locale,
    current_lc,
    current_language,
    current_alphabet,
    RECOGNIZED_LOCALES,
)
from skraflgame import Game
from skraflmechanics import (
    ChallengeMove,
    Error,
    ExchangeMove,
    Move,
    MoveBase,
    PassMove,
    ResignMove,
)
from skrafluser import MAX_NICKNAME_LENGTH, User, fetch_users
from skraflplayer import AutoPlayer
from skrafldb import (
    EloDict,
    EloModel,
    ListPrefixDict,
    RatingDict,
    RatingForLocaleDict,
    ZombieModel,
    PrefsDict,
    ChallengeModel,
    ChallengeTuple,
    UserModel,
    FavoriteModel,
    GameModel,
    RatingModel,
)
from cache import memcache

# Type definitions
T = TypeVar("T")
UserPrefsType = Dict[str, Union[str, bool]]

# To try to finish requests as soon as possible and avoid GAE DeadlineExceeded
# exceptions, run the AutoPlayer move generators serially and exclusively
# within an instance
autoplayer_lock = threading.Lock()

# Maximum number of online users to display
MAX_ONLINE = 80

EXPLO_LOGO_URL = "https://explo-live.appspot.com/static/icon-explo-192.png"

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
    "en_GB": {
        "NICK_MISSING": "Nickname missing",
        "NICK_NOT_ALPHANUMERIC": "Nickname can only contain letters and numbers",
        "NICK_TOO_LONG": f"Nickname must not be longer than {MAX_NICKNAME_LENGTH} characters",
        "EMAIL_NO_AT": "E-mail address must contain @ sign",
        "LOCALE_UNKNOWN": "Unknown locale",
    },
    "pl": {
        "NICK_MISSING": "Brak nazwy użytkownika",
        "NICK_NOT_ALPHANUMERIC": "Nazwa użytkownika może zawierać tylko litery i cyfry",
        "NICK_TOO_LONG": f"Nazwa użytkownika nie może mieć więcej niż {MAX_NICKNAME_LENGTH} znaków",
        "EMAIL_NO_AT": "Adres e-mail musi zawierać znak @",
        "LOCALE_UNKNOWN": "Nieznana lokalizacja",
    },
    "nb": {
        "NICK_MISSING": "Mangler kallenavn",
        "NICK_NOT_ALPHANUMERIC": "Kallenavn kan bare inneholde bokstaver og tall",
        "NICK_TOO_LONG": f"Kallenavn kan ikke være lengre enn {MAX_NICKNAME_LENGTH} tegn",
        "EMAIL_NO_AT": "E-postadressen må inneholde @-tegn",
        "LOCALE_UNKNOWN": "Ukjent lokalitet",
    },
    "ga": {
        "NICK_MISSING": "Ainm cleite in easnamh",
        "NICK_NOT_ALPHANUMERIC": "Ní féidir le hainm cleite ach litreacha agus uimhreacha a áireamh",
        "NICK_TOO_LONG": "Ní mór d'ainm cleite a bheith níos lú ná {MAX_NICKNAME_LENGTH} carachtair",
        "EMAIL_NO_AT": "Caithfidh seoladh ríomhphoist comhartha @ a áireamh",
        "LOCALE_UNKNOWN": "Locale anaithnid",
    },
}

PUSH_MESSAGES: Mapping[str, Mapping[str, str]] = {
    "title": {
        "is": "Þú átt leik í Explo 💥",
        "en": "Your turn in Explo 💥",
        "pl": "Twoja kolej w Explo 💥",
        "nb": "Din tur i Explo 💥",
        "ga": "Do sheal i Explo 💥",
    },
    "body": {
        "is": "{player} hefur leikið í viðureign ykkar.",
        "en": "{player} made a move in your game.",
        "pl": "{player} wykonał ruch w Twojej grze.",
        "nb": "{player} har gjort et trekk i spillet ditt.",
        "ga": "Rinne {player} gluaiseacht i do chluiche.",
    },
    "chall_title": {
        "is": "Þú fékkst áskorun í Explo 💥",
        "en": "You've been challenged in Explo 💥",
        "pl": "Zostałeś wyzwany w Explo 💥",
        "nb": "Du har blitt utfordret i Explo 💥",
        "ga": "Tá dúshlán curtha ort i Explo 💥",
    },
    "chall_body": {
        "is": "{player} hefur skorað á þig í viðureign!",
        "en": "{player} has challenged you to a game!",
        "pl": "{player} wyzwał cię na pojedynek!",
        "nb": "{player} har utfordret deg til en kamp!",
        "ga": "Tá {player} tar éis dúshlán a thabhairt duit i gcluiche!",
    },
}


class UserListDict(TypedDict):
    """The dictionary returned from userlist()"""

    userid: str
    robot_level: int
    nick: str
    fullname: str
    locale: str
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


class UserRatingForLocaleDict(TypedDict):
    """The dictionary returned from the rating_for_locale() function"""

    rank: int
    userid: str
    nick: str
    fullname: str
    locale: str
    fairplay: bool
    inactive: bool
    fav: bool
    ready: bool
    ready_timed: bool
    live: bool
    image: str
    elo: int


class UserRatingDict(TypedDict):
    """The dictionary returned from the rating() function"""

    rank: int
    rank_yesterday: int
    rank_week_ago: int
    rank_month_ago: int
    userid: str
    nick: str
    fullname: str
    chall: bool
    fairplay: bool
    newbag: bool
    inactive: bool
    fav: bool
    ready: bool
    ready_timed: bool
    live: bool
    image: str
    elo: int
    elo_yesterday: int
    elo_week_ago: int
    elo_month_ago: int
    games: int
    games_yesterday: int
    games_week_ago: int
    games_month_ago: int
    ratio: float
    avgpts: float


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
        self.account: str = ""
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
        # An empty locale is mapped to DEFAULT_LOCALE
        self.locale = to_supported_locale(form.get("locale", "").strip())
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
        # An empty locale is mapped to DEFAULT_LOCALE
        self.locale = to_supported_locale(d.get("locale", "").strip())
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
        self.account = usr.account()
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
        if self.locale not in RECOGNIZED_LOCALES:
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
        usr.set_chat_disabled(self.chat_disabled)
        usr.set_locale(self.locale)
        # usr.set_image(self.image)  # The user image cannot and must not be set like this
        usr.update()

    def as_dict(self) -> UserPrefsType:
        """Return the user preferences as a dictionary"""
        return self.__dict__


def localize_push_message(key: str, locale: str) -> str:
    """Return a localized push message for the given key and locale"""
    pm = PUSH_MESSAGES.get(key)
    if pm is None:
        return ""
    txt = pm.get(locale)
    if txt is None and len(locale) > 2:
        # Try to find a message for the language only
        txt = pm.get(locale[0:2])
    if txt is None:
        # Default to English
        txt = pm.get("en")
    return txt or ""


def process_move(
    game: Game,
    movelist: Iterable[str],
    *,
    force_resign: bool = False,
    validate: bool = True,
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
    err = game.check_legality(m, validate)
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
    now = datetime.now(UTC).isoformat()
    msg_dict: Dict[str, Any] = dict()
    # Prepare a summary dict of the state of the game after the move
    assert game.state is not None
    move_dict: MoveNotifyDict = {
        "game": game_id,
        "timestamp": now,
        "players": (game.player_ids[0], game.player_ids[1]),
        "over": game.state.is_game_over(),
        "to_move": game.player_to_move(),
        "scores": game.state.scores(),
        "progress": game.state.progress(),
    }

    if opponent:
        # Send a game update to the opponent, if human, including
        # the full client state. board.html and main.html listen to this.
        # Also update the user/[opp_id]/move branch with the newest move data.
        client_state = game.client_state(opponent_index, m)
        msg_dict = {
            f"game/{game_id}/{opponent}/move": client_state,
            f"user/{opponent}/move": move_dict,
        }
        # Push a Firebase notification message to the opponent,
        # in the correct language for each client session
        opp_nick = game.player_nickname(1 - opponent_index)
        firebase.push_to_user(
            opponent,
            {
                "title": lambda locale: localize_push_message("title", locale),
                "body": lambda locale: localize_push_message("body", locale).format(
                    player=opp_nick
                ),
                "image": lambda locale: EXPLO_LOGO_URL,
            },
            {
                "type": "notify-move",
                "game": game_id,
            },
        )

    if player := game.player_id(1 - opponent_index):
        # Add a move notification to the original player as well,
        # since she may have multiple clients and we want to update'em all
        msg_dict[f"user/{player}/move"] = move_dict

    if msg_dict:
        firebase.send_message(msg_dict)

    # Return a state update to the client (board, rack, score, movelist, etc.)
    return jsonify(game.client_state(1 - opponent_index))


@ndb.transactional()  # type: ignore
def submit_move(uuid: str, movelist: List[Any], movecount: int, validate: bool) -> ResponseType:
    """Idempotent, transactional function to process an incoming move"""
    game = Game.load(uuid, use_cache=False, set_locale=True) if uuid else None
    if game is None:
        return jsonify(result=Error.GAME_NOT_FOUND)
    # Make sure the client is in sync with the server:
    # check the move count
    if movecount != game.num_moves():
        return jsonify(result=Error.OUT_OF_SYNC)
    if game.player_id_to_move() != current_user_id():
        return jsonify(result=Error.WRONG_USER)
    # Parameters look superficially OK: process the move
    return process_move(game, movelist, validate=validate)


# Kludge to create reasonably type-safe functions for each type of
# dictionary that contains some kind of user id and has a 'live' property
set_online_status_for_users = functools.partial(firebase.set_online_status, "userid")
set_online_status_for_games = functools.partial(firebase.set_online_status, "oppid")
set_online_status_for_chats = functools.partial(firebase.set_online_status, "user")


def userlist(query: str, spec: str) -> UserList:
    """Return a list of users matching the filter criteria"""
    # The query string can be 'robots', 'live', 'fav', 'alike',
    # 'ready_timed' or 'search', for a list of robots, live users,
    # favorite users, users with similar Elo ratings, users ready
    # to play timed games, or a search pattern match, respectively.

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
                    locale=locale,
                    elo=elo_str(None),
                    human_elo=elo_str(None),
                    fav=False,
                    chall=False,
                    fairplay=False,  # The robots don't play fair ;-)
                    newbag=True,
                    ready=True,  # The robots are always ready for a challenge
                    ready_timed=False,  # Timed games are not available for robots
                    live=True,  # Robots are always online
                    image="",
                )
            )
        # That's it; we're done (no sorting required)
        return result

    # Generate a list of challenges issued by this user
    challenges: Set[str] = set()
    # Explo presently doesn't use this information, so we
    # only include it for Netskrafl
    if cuid and PROJECT_ID == "netskrafl":
        challenges.update(
            # ch[0] is the identifier of the challenged user
            [
                cid
                for ch in ChallengeModel.list_issued(cuid, max_len=20)
                if (cid := ch[0]) is not None
            ]
        )

    # Note that we only consider online users in the same locale
    # as the requesting user. However, the Firebase connection
    # information is occasionally stale, so we still need to
    # filter the returned users by locale.
    online = firebase.online_status(locale)

    # Set of users blocked by the current user
    blocked: Set[str] = cuser.blocked() if cuser else set()

    func_online_status: Optional[firebase.OnlineStatusFunc] = None

    if query == "live":
        # Return a sample (no larger than MAX_ONLINE items)
        # of online (live) users. Note that these are always
        # grouped by locale, so all returned users will be in
        # the same locale as the current user.

        list_online = online.random_sample(MAX_ONLINE)
        ousers = User.load_multi(list_online)
        oelos = EloModel.load_multi(locale, list_online)

        for lu in ousers:
            if lu is None or not lu.is_displayable():
                continue
            if lu.locale != locale:
                # The online user list may on occasion contain users
                # from other locales, so we need to filter them out
                continue
            if not (uid := lu.id()) or uid == cuid or uid in blocked:
                # Don't display the current user in the online list
                continue
            rating = oelos.get(uid, lu.elo_for_locale())
            chall = uid in challenges
            result.append(
                UserListDict(
                    userid=uid,
                    robot_level=0,
                    nick=lu.nickname(),
                    fullname=lu.full_name(),
                    locale=lu.locale,
                    elo=elo_str(rating.elo),
                    human_elo=elo_str(rating.human_elo),
                    fav=False if cuser is None else cuser.has_favorite(uid),
                    chall=chall,
                    fairplay=lu.fairplay(),
                    newbag=True,
                    ready=lu.is_ready(),
                    ready_timed=lu.is_ready_timed(),
                    live=True,
                    image=lu.thumbnail(),
                )
            )

    elif query == "fav":
        # Return favorites of the current user, filtered by
        # the user's current locale
        if cuid is not None:
            i = set(FavoriteModel.list_favorites(cuid))
            # Do a multi-get of the entire favorites list
            fusers = User.load_multi(i)
            felos = EloModel.load_multi(locale, i)
            # Look up users' online status later
            func_online_status = online.users_online
            for fu in fusers:
                if not fu or not fu.is_displayable():
                    continue
                if not (favid := fu.id()) or favid in blocked:
                    continue
                rating = felos.get(favid, fu.elo_for_locale())
                chall = favid in challenges
                result.append(
                    UserListDict(
                        userid=favid,
                        robot_level=0,
                        nick=fu.nickname(),
                        fullname=fu.full_name(),
                        locale=fu.locale,  # Note: This might not be the current user's locale
                        elo=elo_str(rating.elo),
                        human_elo=elo_str(rating.human_elo),
                        fav=True,
                        chall=chall,
                        fairplay=fu.fairplay(),
                        newbag=True,
                        live=False,  # Will be filled in later
                        ready=fu.is_ready(),
                        ready_timed=fu.is_ready_timed(),
                        image=fu.thumbnail(),
                    )
                )

    elif query == "alike":
        # Return users with similar human Elo ratings,
        # in the same locale as the requesting user
        if cuid is not None:
            assert cuser is not None
            # Obtain the current user's human Elo rating
            ed = cuser.elo_for_locale(locale)
            # Look up users with similar Elo ratings
            ei = list(EloModel.list_similar(locale, ed.human_elo, max_len=40))
            # Load the user entities and zip them with the corresponding EloDict
            ausers = zip(User.load_multi(e[0] for e in ei), (e[1] for e in ei))
            # Look up users' online status later
            func_online_status = online.users_online
            for au, ed in ausers:
                if not au or not au.is_displayable():
                    continue
                if au.locale != locale:
                    # Better safe than sorry
                    continue
                if not (uid := au.id()) or uid == cuid or uid in blocked:
                    continue
                chall = uid in challenges
                result.append(
                    UserListDict(
                        userid=uid,
                        robot_level=0,
                        nick=au.nickname(),
                        fullname=au.full_name(),
                        locale=au.locale,
                        elo=elo_str(ed.elo),
                        human_elo=elo_str(ed.human_elo),
                        # manual_elo=elo_str(ed.manual_elo),
                        fav=cuser.has_favorite(uid),
                        chall=chall,
                        fairplay=au.fairplay(),
                        live=False,  # Will be filled in later
                        newbag=True,
                        ready=au.is_ready(),
                        ready_timed=au.is_ready_timed(),
                        image=au.thumbnail(),
                    )
                )

    elif query == "ready_timed":
        # Display users who are online and ready for a timed game.
        # Note that the online list is already filtered by locale,
        # so the result is also filtered by locale.
        iter_online = online.random_sample(MAX_ONLINE)
        online_users = User.load_multi(iter_online)
        elos = EloModel.load_multi(locale, iter_online)

        for user in online_users:
            if not user or not user.is_ready_timed() or not user.is_displayable():
                # Only return users that are ready to play timed games
                continue
            if user.locale != locale:
                # The online user list may on occasion contain users
                # from other locales, so we need to filter them out
                continue
            if not (user_id := user.id()) or user_id == cuid or user_id in blocked:
                # Don't include the current user in the list;
                # also don't include users that are blocked by the current user
                continue
            rating = elos.get(user_id, user.elo_for_locale())
            result.append(
                UserListDict(
                    userid=user_id,
                    robot_level=0,
                    nick=user.nickname(),
                    fullname=user.full_name(),
                    locale=user.locale,
                    elo=elo_str(rating.elo),
                    human_elo=elo_str(rating.human_elo),
                    fav=False if cuser is None else cuser.has_favorite(user_id),
                    chall=user_id in challenges,
                    fairplay=user.fairplay(),
                    newbag=True,
                    ready=user.is_ready(),
                    ready_timed=True,
                    live=True,
                    image=user.thumbnail(),
                )
            )

    elif query == "search":
        # Return users with nicknames matching a pattern
        si: Optional[List[ListPrefixDict]] = []
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

        func_online_status = online.users_online
        elos = EloModel.load_multi(locale, (uid for ud in si if (uid := ud.get("id"))))

        for ud in si:
            if not (uid := ud.get("id")) or uid == cuid or uid in blocked:
                continue
            rating = elos.get(
                uid,
                EloDict(
                    ud.get("elo", DEFAULT_ELO),
                    ud.get("human_elo", DEFAULT_ELO),
                    DEFAULT_ELO,
                ),
            )
            chall = uid in challenges
            result.append(
                UserListDict(
                    userid=uid,
                    robot_level=0,
                    nick=ud["nickname"],
                    fullname=User.full_name_from_prefs(ud["prefs"]),
                    locale=locale,
                    elo=elo_str(rating.elo),
                    human_elo=elo_str(rating.human_elo),
                    fav=False if cuser is None else cuser.has_favorite(uid),
                    chall=chall,
                    live=False,  # Will be filled in later
                    fairplay=User.fairplay_from_prefs(ud["prefs"]),
                    newbag=True,
                    ready=ud["ready"] or False,
                    ready_timed=ud["ready_timed"] or False,
                    image=User.thumbnail_url(uid, ud["image"], ud["has_image_blob"]),
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
    # Assign the online status of the users in the list,
    # if this assignment was postponed
    if func_online_status is not None:
        set_online_status_for_users(result, func_online_status)
    return result


def rating(kind: str) -> List[UserRatingDict]:
    """Return a list of top players by Elo rating
    of the given kind ('all', 'human', 'manual')"""
    result: List[UserRatingDict] = []
    cuser = current_user()
    cuid = None if cuser is None else cuser.id()
    user_locale = cuser.locale if cuser and cuser.locale else DEFAULT_LOCALE
    online = firebase.online_status(user_locale)

    # Generate a list of challenges issued by this user
    challenges: Set[Optional[str]] = set()
    if cuid:
        challenges.update(
            # ch[0] is the identifier of the challenged user
            [ch[0] for ch in ChallengeModel.list_issued(cuid, max_len=20)]
        )

    rating_list: Optional[List[RatingDict]] = memcache.get(kind, namespace="rating")
    if rating_list is None:
        # Not found: do a query
        rating_list = list(RatingModel.list_rating(kind))
        # Store the result in the cache with a lifetime of 1 hour
        memcache.set(kind, rating_list, time=1 * 60 * 60, namespace="rating")

    # Prefetch the users in the rating list
    users = fetch_users(rating_list, lambda x: x["userid"])

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
            nick = AutoPlayer.name(lc, int(a[1]))
            fullname = nick
            chall = False
            fairplay = False
            fav = False
            ready = True
            ready_timed = False
            image = ""
        else:
            usr = users.get(uid)
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
            fav = False if cuser is None else cuser.has_favorite(uid)
            ready = usr.is_ready()
            ready_timed = usr.is_ready_timed()
            image = usr.thumbnail()

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
                "fav": fav,
                "ready": ready,
                "ready_timed": ready_timed,
                "live": False,  # Will be filled in later
                "image": image,
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

    set_online_status_for_users(result, online.users_online)
    return result


def rating_for_locale(kind: str, locale: str) -> List[UserRatingForLocaleDict]:
    """Return a list of top 100 players by Elo rating
    of the given kind ('all', 'human', 'manual')"""
    NUM_RETURNED = 100  # We return at most 100 users
    NUM_FETCHED = 120  # Fetch 120 users to allow for some filtering
    result: List[UserRatingForLocaleDict] = []
    cuser = current_user()
    user_locale = cuser.locale if cuser and cuser.locale else DEFAULT_LOCALE
    online = firebase.online_status(user_locale)
    # If the locale is not explicitly given, use the current user's locale
    locale = locale or user_locale

    cache_key = f"{kind}:{locale}"
    rating_list: Optional[List[RatingForLocaleDict]] = memcache.get(
        cache_key, namespace="rating-locale"
    )
    if rating_list is None:
        # Not found: do a query. We fetch 120 users to allow for
        # some filtering out inactive or anonymous users.
        rating_list = list(EloModel.list_rating(kind, locale, limit=NUM_FETCHED))
        # Store the result in the cache with a lifetime of 1 hour
        memcache.set(cache_key, rating_list, time=1 * 60 * 60, namespace="rating-locale")

    # Prefetch the users in the rating list
    # TODO: Consider caching the user information that is actually
    # returned in the rating list, to avoid re-fetching it for every call
    # (which can get pretty expensive)
    users = fetch_users(rating_list, lambda x: x["userid"])

    rank = 0
    for ru in rating_list:

        uid = ru["userid"]
        if uid.startswith("robot-"):
            a = uid.split("-")
            try:
                nick = AutoPlayer.name(locale, int(a[1]))
            except ValueError:
                nick = "--"
            fullname = nick
            fairplay = False
            inactive = False
            fav = False
            ready = True
            ready_timed = False
            image = ""
            list_locale = locale
        else:
            usr = users.get(uid)
            if usr is None or not usr.is_displayable():
                # Something wrong, or this is an inactive or
                # anonymous user, which we don't display
                continue
            nick = usr.nickname()
            if not User.is_valid_nick(nick):
                # Require a valid nickname for display
                continue
            fullname = usr.full_name()
            fairplay = usr.fairplay()
            inactive = False  # All displayable users are active
            fav = False if cuser is None else cuser.has_favorite(uid)
            ready = usr.is_ready()
            ready_timed = usr.is_ready_timed()
            image = usr.thumbnail()
            list_locale = usr.locale  # The user's current locale

        rank += 1
        result.append(
            {
                "rank": rank,
                "userid": uid,
                "nick": nick,
                "fullname": fullname,
                "locale": list_locale,
                "fairplay": fairplay,
                "inactive": inactive,
                "fav": fav,
                "ready": ready,
                "ready_timed": ready_timed,
                "live": False,  # Will be filled in later
                "image": image,
                "elo": ru["elo"],
            }
        )
        if rank >= NUM_RETURNED:
            # We're done already
            break

    set_online_status_for_users(result, online.users_online)
    return result


def gamelist(cuid: str, include_zombies: bool = True) -> GameList:
    """Return a list of active and zombie games for the current user"""
    result: GameList = []
    if not cuid:
        return result

    now = datetime.now(UTC)
    cuser = current_user()
    locale = cuser.locale if cuser and cuser.locale else DEFAULT_LOCALE
    online = firebase.online_status(locale)
    u: Optional[User] = None

    # Place zombie games (recently finished games that this player
    # has not seen) at the top of the list
    if include_zombies:
        for g in ZombieModel.list_games(cuid):
            opp = g["opp"]  # User id of opponent
            u = User.load_if_exists(opp)
            if u is None:
                continue
            # Fetch the Elo rating of the opponent in his own locale
            rating = u.elo_for_locale()
            uuid = g["uuid"]
            game_locale = g["locale"]
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
                    locale=game_locale,
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
                    live=False,  # Will be filled in later
                    image=u.thumbnail(),
                    fav=False if cuser is None else cuser.has_favorite(opp),
                    tile_count=100,  # All tiles (100%) accounted for
                    robot_level=0,  # Should not be used; zombie games are human-only
                    elo=rating.elo,
                    human_elo=rating.human_elo,
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
    # Multi-fetch the opponents' Elo ratings, in the current player's locale
    elos = EloModel.load_multi(locale, opponents.keys())
    # Iterate through the game list
    for g in i:
        u = None
        uuid = g["uuid"]
        opp = g["opp"]  # User id of opponent
        ts = g["ts"]
        game_locale = g["locale"]
        overdue = False
        prefs = g.get("prefs", None)
        tileset = Game.tileset_from_prefs(game_locale, prefs)
        fairplay = Game.fairplay_from_prefs(prefs)
        new_bag = Game.new_bag_from_prefs(prefs)
        manual = Game.manual_wordcheck_from_prefs(prefs)
        # Time per player in minutes
        timed = Game.get_duration_from_prefs(prefs)
        fullname = ""
        robot_level: int = 0
        rating: Optional[EloDict] = None
        if opp is None:
            # Autoplayer opponent
            robot_level = g["robot_level"]
            nick = AutoPlayer.name(game_locale, robot_level)
        else:
            # Human opponent
            u = opponents.get(opp)
            if u is None:
                # This should not happen, but try to cope nevertheless
                u = User.load_if_exists(opp)
            if u is None:
                continue
            nick = u.nickname()
            fullname = u.full_name()
            # If the opponent is in the same locale as the current user,
            # use the Elo rating that we previously multi-fetched;
            # otherwise, use the Elo rating in the opponent's own locale
            rating = elos.get(opp) if u.locale == locale else u.elo_for_locale()
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
                locale=game_locale,
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
                live=False,
                image="" if u is None else u.thumbnail(),
                fav=False if cuser is None else cuser.has_favorite(opp),
                robot_level=robot_level,
                elo=0 if rating is None else rating.elo,
                human_elo=0 if rating is None else rating.human_elo,
            )
        )
    # Set the live status of the opponents in the list
    set_online_status_for_games(result, online.users_online)
    return result


def recentlist(cuid: Optional[str], versus: Optional[str], max_len: int) -> RecentList:
    """Return a list of recent games for the indicated user, eventually
    filtered by the opponent id (versus)"""
    result: RecentList = []
    if not cuid:
        return result

    cuser = current_user()
    locale = cuser.locale if cuser and cuser.locale else DEFAULT_LOCALE
    # Obtain a list of recently finished games where the indicated user was a player
    rlist = GameModel.list_finished_games(cuid, versus=versus, max_len=max_len)
    # Multi-fetch the opponents in the list into a dictionary
    opponents = fetch_users(rlist, lambda g: g["opp"])
    # Multi-fetch their Elo ratings
    elos = EloModel.load_multi(locale, opponents.keys())

    online = firebase.online_status(locale)

    u: Optional[User] = None

    for g in rlist:

        uuid = g["uuid"]

        prefs = g["prefs"]
        locale = g["locale"]
        rating: Optional[EloDict] = None

        opp: Optional[str] = g["opp"]
        if opp is None:
            # Autoplayer opponent
            u = None
            nick = AutoPlayer.name(locale, g["robot_level"])
        else:
            # Human opponent
            u = opponents.get(opp)
            if u is None:
                # Second chance, should not happen
                u = User.load_if_exists(opp)
            if u is None:
                continue
            nick = u.nickname()
            rating = elos.get(opp, u.elo_for_locale(locale))

        # Calculate the duration of the game in days, hours, minutes
        ts_start = g["ts"]
        ts_end = g["ts_last_move"]

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
                live=False,  # Will be filled in later
                image="" if u is None else u.thumbnail(),
                elo=0 if rating is None else rating.elo,
                human_elo=0 if rating is None else rating.human_elo,
                fav=False if cuser is None or opp is None else cuser.has_favorite(opp),
            )
        )
    set_online_status_for_games(result, online.users_online)
    return result


def opponent_waiting(user_id: str, opp_id: str, *, key: Optional[str]) -> bool:
    """Return True if the given opponent is waiting on this user's challenge"""
    return firebase.check_wait(opp_id, user_id, key)


def challengelist() -> ChallengeList:
    """Return a list of challenges issued or received by the current user"""

    result: ChallengeList = []
    cuser = current_user()
    if cuser is None or not (cuid := cuser.id()):
        # Current user not valid: return empty list
        return result

    def is_timed(prefs: Optional[PrefsDict]) -> bool:
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
        return opponent_waiting(cuid, c.opp, key=c.key)

    blocked = cuser.blocked()
    locale = cuser.locale if cuser and cuser.locale else DEFAULT_LOCALE
    online = firebase.online_status(locale)
    # List received challenges
    received = list(ChallengeModel.list_received(cuid, max_len=20))
    # List issued challenges
    issued = list(ChallengeModel.list_issued(cuid, max_len=20))
    # Multi-fetch all opponents involved
    opponents = fetch_users(received + issued, lambda c: c[0])
    # Multi-fetch their Elo ratings
    elos = EloModel.load_multi(locale, opponents.keys())

    # List the received challenges
    for c in received:
        if not (oppid := c.opp):
            continue
        if oppid in blocked:
            # Don't list challenges from blocked users
            continue
        if (u := opponents.get(oppid)) is None:
            continue
        rating = elos.get(oppid, u.elo_for_locale(locale))
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
                live=False,  # Will be filled in later
                image=u.thumbnail(),
                fav=cuser.has_favorite(oppid),
                elo=rating.elo,
                human_elo=rating.human_elo,
            )
        )
    # List the issued challenges
    for c in issued:
        if not (oppid := c.opp):
            continue
        # Currently, we do include challenges issued to blocked users
        # in the list of issued challenges.
        # A possible addition would be to automatically delete issued
        # challenges to a user when blocking that user.
        if (u := opponents.get(oppid)) is None:
            continue
        rating = elos.get(oppid, u.elo_for_locale(locale))
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
                live=False,  # Will be filled in later
                image=u.thumbnail(),
                fav=cuser.has_favorite(oppid),
                elo=rating.elo,
                human_elo=rating.human_elo,
            )
        )
    # Set the live status of the opponents in the list
    set_online_status_for_users(result, online.users_online)
    return result
