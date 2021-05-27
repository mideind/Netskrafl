"""

    Web server for netskrafl.is

    Copyright (C) 2021 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The GNU Affero General Public License, version 3, applies to this software.
    For further information, see https://github.com/mideind/Netskrafl


    This module contains the API entry points into the Netskrafl server.
    These APIs are used both by the web front-end and by the app client.

"""

from __future__ import annotations
import os

from typing import (
    Optional,
    Dict,
    Mapping,
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

import logging
import threading
import random
from datetime import datetime, timedelta

from flask import (
    Blueprint,
    request,
    url_for,
)
from flask.globals import current_app

from google.oauth2 import id_token  # type: ignore
from google.auth.transport import requests as google_requests  # type: ignore

from basics import (
    jsonify,
    auth_required,
    ResponseType,
    RequestData,
    current_user,
    current_user_id,
    set_session_userid,
    clear_session_userid,
    running_local,
    CLIENT_ID,
    VALID_ISSUERS,
)
from cache import memcache
from languages import (
    Alphabet,
    current_board_type,
    set_game_locale,
    current_lc,
    current_alphabet,
    SUPPORTED_LOCALES,
)
from dawgdictionary import Wordbase
from skraflmechanics import (
    MoveBase,
    Move,
    PassMove,
    ExchangeMove,
    ResignMove,
    ChallengeMove,
    Error,
    SummaryTuple,
)
from skraflplayer import AutoPlayer
from skraflgame import User, Game
from skrafldb import (
    ChatModel,
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

# Type definitions
T = TypeVar("T")
UserPrefsType = Dict[str, Union[str, bool]]
GameList = List[Dict[str, Union[str, int, bool, Dict[str, bool]]]]

# Maximum number of online users to display
MAX_ONLINE = 80

# To try to finish requests as soon as possible and avoid DeadlineExceeded
# exceptions, run the AutoPlayer move generator serially and exclusively
# within an instance
autoplayer_lock = threading.Lock()

# Register the Flask blueprint for the APIs
api = Blueprint('api', __name__)


class UserForm:

    """ Encapsulates the data in the user preferences form """

    def __init__(self, usr: Optional[User] = None) -> None:
        # We store the URL that the client will redirect to after
        # doing an auth2.disconnect() call, clearing client-side
        # credentials. The login() handler clears the server-side
        # user cookie, so there is no need for an intervening redirect
        # to logout().
        self.logout_url: str = url_for("web.logout")
        self.unfriend_url: str = url_for("web.friend", action=2)
        self.nickname: str = ""
        self.full_name: str = ""
        self.id: str = ""
        self.email: str = ""
        self.image: str = ""
        self.audio: bool = True
        self.fanfare: bool = True
        self.beginner: bool = True
        self.fairplay: bool = False  # Defaults to False, must be explicitly set to True
        self.newbag: bool = False  # Defaults to False, must be explicitly set to True
        self.friend: bool = False
        self.locale: str = current_lc()
        if usr:
            self.init_from_user(usr)

    def init_from_form(self, form: Dict[str, str]) -> None:
        """ The form has been submitted after editing: retrieve the entered data """
        try:
            self.nickname = form["nickname"].strip()
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
        self.locale = form.get("locale", "").strip() or "is_IS"
        try:
            self.image = form["image"].strip()
        except (TypeError, ValueError, KeyError):
            pass
        try:
            self.audio = "audio" in form  # State of the checkbox
            self.fanfare = "fanfare" in form
            self.beginner = "beginner" in form
            self.fairplay = "fairplay" in form
            self.newbag = "newbag" in form
        except (TypeError, ValueError, KeyError):
            pass

    def init_from_dict(self, d: Dict[str, str]) -> None:
        """ The form has been submitted after editing: retrieve the entered data """
        try:
            self.nickname = d.get("nickname", "").strip()
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
        self.locale = d.get("locale", "").strip() or "is_IS"
        try:
            self.image = d.get("image", "").strip()
        except (TypeError, ValueError, KeyError):
            pass
        try:
            self.audio = bool(d.get("audio", False))
            self.fanfare = bool(d.get("fanfare", False))
            self.beginner = bool(d.get("beginner", False))
            self.fairplay = bool(d.get("fairplay", False))
            self.newbag = bool(d.get("newbag", False))
        except (TypeError, ValueError, KeyError):
            pass

    def init_from_user(self, usr: User) -> None:
        """ Load the data to be edited upon initial display of the form """
        self.nickname = usr.nickname()
        self.full_name = usr.full_name()
        self.email = usr.email()
        self.audio = usr.audio()
        self.fanfare = usr.fanfare()
        self.beginner = usr.beginner()
        self.fairplay = usr.fairplay()
        self.newbag = usr.new_bag()
        self.friend = usr.friend()
        self.locale = usr.locale
        self.id = current_user_id() or ""
        self.image = usr.image()

    def validate(self) -> Dict[str, str]:
        """Check the current form data for validity
        and return a dict of errors, if any"""
        errors: Dict[str, str] = dict()
        # pylint: disable=bad-continuation
        alphabet = current_alphabet()
        if not self.nickname:
            errors["nickname"] = "Notandi verður að hafa einkenni"
        elif (
            self.nickname[0] not in alphabet.full_order
            and self.nickname[0] not in alphabet.full_upper
        ):
            errors["nickname"] = "Einkenni verður að byrja á bókstaf"
        elif len(self.nickname) > 15:
            errors["nickname"] = "Einkenni má ekki vera lengra en 15 stafir"
        elif '"' in self.nickname:
            errors["nickname"] = "Einkenni má ekki innihalda gæsalappir"
        if '"' in self.full_name:
            errors["full_name"] = "Nafn má ekki innihalda gæsalappir"
        if self.email and "@" not in self.email:
            errors["email"] = "Tölvupóstfang verður að innihalda @-merki"
        if self.locale not in SUPPORTED_LOCALES:
            errors["locale"] = "Óþekkt staðfang (locale)"
        return errors

    def store(self, usr: User) -> None:
        """ Store validated form data back into the user entity """
        usr.set_nickname(self.nickname)
        usr.set_full_name(self.full_name)
        usr.set_email(self.email)
        usr.set_audio(self.audio)
        usr.set_fanfare(self.fanfare)
        usr.set_beginner(self.beginner)
        usr.set_fairplay(self.fairplay)
        usr.set_new_bag(self.newbag)
        usr.set_locale(self.locale)
        usr.set_image(self.image)
        usr.update()

    def as_dict(self) -> UserPrefsType:
        """ Return the user preferences as a dictionary """
        return self.__dict__


@api.route("/oauth2callback", methods=["POST"])
def oauth2callback():
    """ The OAuth2 login flow POSTs to this callback when a user has
        signed in using a Google Account """

    # Note that HTTP GETs to the /oauth2callback URL are handled in web.py,
    # this route is only for HTTP POSTs

    if not CLIENT_ID:
        # Something is wrong in the internal setup of the server
        # (environment variable probably missing)
        # 500 - Internal server error
        return jsonify({"status": "invalid", "msg": "Missing CLIENT_ID"}), 500

    # !!! TODO: Add CSRF token mechanism
    # csrf_token = request.form.get("csrfToken", "") or request.json['csrfToken']
    token: str
    testing: bool = current_app.config.get("TESTING", False)
    
    if testing:
        # Testing only: there is no token in the request
        token = ""
    else:
        token = request.form.get("idToken", "") or cast(Any, request).json.get("idToken", "")
        if not token:
            # No authentication token included in the request
            # 400 - Bad Request
            return jsonify({"status": "invalid", "msg": "Missing token"}), 400

    account: Optional[str] = None
    userid: Optional[str] = None
    idinfo: Dict[str, Any] = dict()
    email: Optional[str] = None
    image: Optional[str] = None
    name: Optional[str] = None
    try:
        if testing:
            # Get the idinfo dictionary directly from the request
            f = cast(Dict[str, str], request.form)
            idinfo = dict(sub=f["sub"], name=f["name"], picture=f["picture"], email=f["email"])
        else:
            # Verify the token and extract its claims
            idinfo = id_token.verify_oauth2_token(  # type: ignore
                token, google_requests.Request(), CLIENT_ID
            )
            if idinfo["iss"] not in VALID_ISSUERS:
                raise ValueError("Unknown OAuth2 token issuer: " + idinfo["iss"])
        # ID token is valid; extract the claims
        # Get the user's Google Account ID
        account = idinfo.get("sub")
        if account:
            # Full name of user
            name = idinfo.get("name")
            # User image
            image = idinfo.get("picture")
            # Make sure that the e-mail address is in lowercase
            email = idinfo.get("email", "").lower()
            # Attempt to find an associated user record in the datastore,
            # or create a fresh user record if not found
            userid = User.login_by_account(
                account, name or "", email or "", image or ""
            )

    except (KeyError, ValueError) as e:
        # Invalid token
        # 401 - Unauthorized
        return jsonify({"status": "invalid", "msg": str(e)}), 401

    if not userid:
        # Unable to obtain the user id for some reason
        # 401 - Unauthorized
        return jsonify({"status": "invalid", "msg": "Unable to obtain user id"}), 401

    # Authentication complete; user id obtained
    # Set a session cookie
    set_session_userid(userid, idinfo)
    return jsonify({"status": "success"})


@api.route("/logout", methods=["POST"])
def logout() -> ResponseType:
    """ Log the current user out """
    clear_session_userid()
    return jsonify({"status": "success"})


def _process_move(game: Game, movelist: Iterable[str]) -> ResponseType:
    """ Process a move coming in from the client """

    assert game is not None

    game_id = game.id()

    if game_id is None or game.is_over() or game.is_erroneous():
        # This game is already completed, or cannot be correctly
        # serialized from the datastore
        return jsonify(result=Error.GAME_NOT_FOUND)

    player_index = game.player_to_move()

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

    # Serialize access to the following code section
    with autoplayer_lock:

        # Move is OK: register it and update the state
        game.register_move(m)

        # If it's the autoplayer's move, respond immediately
        # (can be a bit time consuming if rack has one or two blank tiles)
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
        game.store()

        # If the game is now over, and the opponent is human, add it to the
        # zombie game list so that the opponent has a better chance to notice
        # the result
        if is_over and opponent is not None:
            ZombieModel.add_game(game_id, opponent)

    if opponent is not None:
        # Send Firebase notifications
        # Send a game update to the opponent, if human, including
        # the full client state. board.html and main.html listen to this.
        # Also update the user/[opp_id]/move branch with the current timestamp.
        client_state = game.client_state(1 - player_index, m)
        msg_dict: Dict[str, Any] = {
            "game/" + game_id + "/" + opponent + "/move": client_state,
            "user/" + opponent: {"move": datetime.utcnow().isoformat()},
        }
        firebase.send_message(msg_dict)

    # Return a state update to the client (board, rack, score, movelist, etc.)
    return jsonify(game.client_state(player_index))


def fetch_users(
    ulist: Iterable[T], uid_func: Callable[[T], Optional[str]]
) -> Dict[str, User]:
    """ Return a dictionary of users found in the ulist """
    # Make a list of user ids by applying the uid_func to ulist entries (!= None)
    uids: List[str] = []
    for u in ulist:
        uid = None if u is None else uid_func(u)
        if uid:
            uids.append(uid)
    # No need for a special case for an empty list
    user_objects = User.load_multi(uids)
    # Return a dictionary mapping user ids to users
    return {uid: user for uid, user in zip(uids, user_objects)}


def _get_online() -> Set[str]:
    # Get the list of online users

    # Start by looking in the cache
    # !!! TODO: Cache the entire list including the user information,
    # !!! only updating the favorite state (fav field) for the requesting user
    online: Union[Set[str], List[str]] = memcache.get("live", namespace="userlist")

    if not online:
        # Not found: do a query, which returns a set
        online = firebase.get_connected_users()

        # Store the result as a list in the cache with a lifetime of 10 minutes
        memcache.set("live", list(online), time=10 * 60, namespace="userlist")
    else:
        # Convert the cached list back into a set
        online = set(online)
    return online


def _userlist(query: str, spec: str) -> List[Dict[str, Any]]:
    """ Return a list of users matching the filter criteria """

    result: List[Dict[str, Any]] = []

    def elo_str(elo: Union[None, int, str]) -> str:
        """ Return a string representation of an Elo score, or a hyphen if none """
        return str(elo) if elo else "-"

    # We will be returning a list of human players
    cuser = current_user()
    cuid = None if cuser is None else cuser.id()

    if query == "robots":
        # Return the list of available autoplayers
        for r in Game.AUTOPLAYERS:
            result.append(
                {
                    "userid": "robot-" + str(r[2]),
                    "nick": r[0],
                    "fullname": r[1],
                    "human_elo": elo_str(None),
                    "fav": False,
                    "chall": False,
                    "fairplay": False,  # The robots don't play fair ;-)
                    "newbag": cuser is not None and cuser.new_bag(),
                    "ready": True,  # The robots are always ready for a challenge
                    "ready_timed": False,  # Timed games are not available for robots
                    "live": True,  # robots are always online
                }
            )
        # That's it; we're done (no sorting required)
        return result

    # Generate a list of challenges issued by this user
    challenges: Set[str] = set()
    if cuid:
        challenges.update(
            # ch[0] is the identifier of the challenged user
            [ch[0] for ch in ChallengeModel.list_issued(cuid, max_len=20) if ch[0]]
        )

    online = _get_online()
    if query == "live":
        # Return a sample (no larger than MAX_ONLINE items) of online (live) users

        if len(online) > MAX_ONLINE:
            iter_online = random.sample(list(online), MAX_ONLINE)
        else:
            iter_online = online

        ousers = User.load_multi(iter_online)
        for lu in ousers:
            if lu and lu.is_displayable() and lu.id() != cuid:
                # Don't display the current user in the online list
                uid = lu.id()
                if uid is None:
                    continue
                chall = uid in challenges
                result.append(
                    {
                        "userid": uid,
                        "nick": lu.nickname(),
                        "fullname": lu.full_name(),
                        "human_elo": elo_str(lu.human_elo()),
                        "fav": False if cuser is None else cuser.has_favorite(uid),
                        "chall": chall,
                        "fairplay": lu.fairplay(),
                        "newbag": lu.new_bag(),
                        "ready": lu.is_ready() and not chall,
                        "ready_timed": lu.is_ready_timed() and not chall,
                        "live": True,
                        "image": lu.image(),
                    }
                )

    elif query == "fav":
        # Return favorites of the current user
        if cuid is not None:
            i = FavoriteModel.list_favorites(cuid)
            # Do a multi-get of the entire favorites list
            fusers = User.load_multi(i)
            for fu in fusers:
                if fu and fu.is_displayable():
                    favid = fu.id()
                    chall = favid in challenges
                    result.append(
                        {
                            "userid": favid,
                            "nick": fu.nickname(),
                            "fullname": fu.full_name(),
                            "human_elo": elo_str(fu.human_elo()),
                            "fav": True,
                            "chall": chall,
                            "fairplay": fu.fairplay(),
                            "newbag": fu.new_bag(),
                            "live": favid in online,
                            "ready": (fu.is_ready() and favid in online and not chall),
                            "ready_timed": (
                                fu.is_ready_timed() and favid in online and not chall
                            ),
                            "image": fu.image(),
                        }
                    )

    elif query == "alike":
        # Return users with similar Elo ratings
        if cuid is not None:
            assert cuser is not None
            ui = UserModel.list_similar_elo(
                cuser.human_elo(), max_len=40, locale=current_lc()
            )
            ausers = User.load_multi(ui)
            for au in ausers:
                if au and au.is_displayable() and au.id() != cuid:
                    uid = au.id()
                    if uid is None:
                        continue
                    chall = uid in challenges
                    result.append(
                        {
                            "userid": uid,
                            "nick": au.nickname(),
                            "fullname": au.full_name(),
                            "human_elo": elo_str(au.human_elo()),
                            "fav": False if cuser is None else cuser.has_favorite(uid),
                            "chall": chall,
                            "fairplay": au.fairplay(),
                            "live": uid in online,
                            "newbag": au.new_bag(),
                            "ready": (au.is_ready() and uid in online and not chall),
                            "ready_timed": (
                                au.is_ready_timed() and uid in online and not chall
                            ),
                            "image": au.image(),
                        }
                    )

    elif query == "search":
        # Return users with nicknames matching a pattern

        if not spec:
            si = []
        else:
            # Limit the spec to 16 characters
            spec = spec[0:16]

            # The "N:" prefix is a version header
            cache_range = "4:" + spec.lower()  # Case is not significant

            # Start by looking in the cache
            si = memcache.get(cache_range, namespace="userlist")
            if si is None:
                # Not found: do an query, returning max 25 users
                si = list(UserModel.list_prefix(spec, max_len=25, locale=current_lc()))
                # Store the result in the cache with a lifetime of 2 minutes
                memcache.set(cache_range, si, time=2 * 60, namespace="userlist")

        def displayable(ud: Mapping[str, str]) -> bool:
            """ Determine whether a user entity is displayable in a list """
            return User.is_valid_nick(ud["nickname"])

        for ud in si:
            uid = ud["id"]
            if uid is None:
                continue
            if uid == cuid:
                # Do not include the current user, if any, in the list
                continue
            if displayable(ud):
                chall = uid in challenges
                result.append(
                    {
                        "userid": uid,
                        "nick": ud["nickname"],
                        "fullname": User.full_name_from_prefs(ud["prefs"]),
                        "human_elo": elo_str(ud["human_elo"] or str(User.DEFAULT_ELO)),
                        "fav": False if cuser is None else cuser.has_favorite(uid),
                        "chall": chall,
                        "live": uid in online,
                        "fairplay": User.fairplay_from_prefs(ud["prefs"]),
                        "newbag": User.new_bag_from_prefs(ud["prefs"]),
                        "ready": (ud["ready"] and uid in online and not chall),
                        "ready_timed": (
                            ud["ready_timed"] and uid in online and not chall
                        ),
                        "image": ud["image"],
                    }
                )

    # Sort the user list. The list is ordered so that users who are
    # ready for any kind of challenge come first, then users who are ready for
    # a timed game, and finally all other users. Each category is sorted
    # by nickname, case-insensitive.
    result.sort(
        key=lambda x: (
            # First by readiness
            0 if x["ready"] else 1 if x["ready_timed"] else 2,
            # Then by nickname
            current_alphabet().sortkey_nocase(x["nick"]),
        )
    )
    return result


def _gamelist(cuid: str, include_zombies: bool = True) -> GameList:
    """ Return a list of active and zombie games for the current user """
    result: GameList = []
    if not cuid:
        return result

    now = datetime.utcnow()
    online = _get_online()
    cuser = current_user()
    u: Optional[User] = None

    # Place zombie games (recently finished games that this player
    # has not seen) at the top of the list
    if include_zombies:
        for g in ZombieModel.list_games(cuid):
            opp = g["opp"]  # User id of opponent
            u = User.load_if_exists(opp)
            if u is None:
                continue
            nick = u.nickname()
            prefs: Optional[PrefsDict] = g.get("prefs", None)
            fairplay = Game.fairplay_from_prefs(prefs)
            new_bag = Game.new_bag_from_prefs(prefs)
            manual = Game.manual_wordcheck_from_prefs(prefs)
            # Time per player in minutes
            timed = Game.get_duration_from_prefs(prefs)
            result.append(
                {
                    "uuid": g["uuid"],
                    # Mark zombie state
                    "url": url_for("web.board", game=g["uuid"], zombie="1"),
                    "oppid": opp,
                    "opp": nick,
                    "fullname": u.full_name(),
                    "sc0": g["sc0"],
                    "sc1": g["sc1"],
                    "ts": Alphabet.format_timestamp_short(g["ts"]),
                    "my_turn": False,
                    "overdue": False,
                    "zombie": True,
                    "prefs": {
                        "fairplay": fairplay,
                        "newbag": new_bag,
                        "manual": manual,
                    },
                    "timed": timed,
                    "live": opp in online,
                    "image": u.image(),
                    "fav": False if cuser is None else cuser.has_favorite(opp),
                    "tile_count": 100,  # All tiles (100%) accounted for
                }
            )
        # Sort zombies in decreasing order by last move,
        # i.e. most recently completed games first
        result.sort(key=lambda x: cast(str, x["ts"]), reverse=True)

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
        opp = g["opp"]  # User id of opponent
        ts = g["ts"]
        overdue = False
        prefs = g.get("prefs", None)
        tileset = Game.tileset_from_prefs(prefs)
        fairplay = Game.fairplay_from_prefs(prefs)
        new_bag = Game.new_bag_from_prefs(prefs)
        manual = Game.manual_wordcheck_from_prefs(prefs)
        # Time per player in minutes
        timed = Game.get_duration_from_prefs(prefs)
        fullname = ""
        if opp is None:
            # Autoplayer opponent
            nick = Game.autoplayer_name(g["robot_level"])
        else:
            # Human opponent
            u = opponents[opp]  # Was User.load(opp)
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
            {
                "uuid": g["uuid"],
                "url": url_for("web.board", game=g["uuid"]),
                "oppid": opp,
                "opp": nick,
                "fullname": fullname,
                "sc0": g["sc0"],
                "sc1": g["sc1"],
                "ts": Alphabet.format_timestamp_short(ts),
                "my_turn": g["my_turn"],
                "overdue": overdue,
                "zombie": False,
                "prefs": {"fairplay": fairplay, "newbag": new_bag, "manual": manual,},
                "timed": timed,
                "tile_count": int(g["tile_count"] * 100 / tileset.num_tiles()),
                "live": opp in online,
                "image": "" if u is None else u.image(),
                "fav": False if cuser is None else cuser.has_favorite(opp),
            }
        )
    return result


def _rating(kind: str) -> List[Dict[str, Any]]:
    """ Return a list of Elo ratings of the given kind ('all' or 'human') """
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
            nick = Game.autoplayer_name(int(uid[6:]))
            fullname = nick
            chall = False
            fairplay = False
            # Robots have the same new bag preference as the user
            new_bag = cuser and cuser.new_bag()
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
            new_bag = usr.new_bag()
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
                "newbag": new_bag,
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


def _recentlist(cuid: Optional[str], versus: str, max_len: int) -> List[Dict[str, Any]]:
    """Return a list of recent games for the indicated user, eventually
    filtered by the opponent id (versus)"""
    result: List[Dict[str, Any]] = []
    if cuid is None:
        return result

    cuser = current_user()
    # Obtain a list of recently finished games where the indicated user was a player
    rlist = GameModel.list_finished_games(cuid, versus=versus, max_len=max_len)
    # Multi-fetch the opponents in the list into a dictionary
    opponents = fetch_users(rlist, lambda g: g["opp"])

    online = _get_online()

    u: Optional[User] = None

    for g in rlist:
        opp = g["opp"]
        if opp is None:
            # Autoplayer opponent
            u = None
            nick = Game.autoplayer_name(g["robot_level"])
        else:
            # Human opponent
            u = opponents[opp]  # Was User.load(opp)
            nick = u.nickname()

        # Calculate the duration of the game in days, hours, minutes
        ts_start = g["ts"]
        ts_end = g["ts_last_move"]

        prefs = g["prefs"]

        if (ts_start is None) or (ts_end is None):
            days, hours, minutes = (0, 0, 0)
        else:
            td = ts_end - ts_start  # Timedelta
            tsec = td.total_seconds()
            days, tsec = divmod(tsec, 24 * 60 * 60)
            hours, tsec = divmod(tsec, 60 * 60)
            minutes, tsec = divmod(tsec, 60)  # Ignore the remaining seconds

        result.append(
            {
                "url": url_for("web.board", game=g["uuid"]),
                "opp": nick,
                "opp_is_robot": opp is None,
                "sc0": g["sc0"],
                "sc1": g["sc1"],
                "elo_adj": g["elo_adj"],
                "human_elo_adj": g["human_elo_adj"],
                "ts_last_move": Alphabet.format_timestamp_short(ts_end),
                "days": int(days),
                "hours": int(hours),
                "minutes": int(minutes),
                "prefs": {
                    "duration": Game.get_duration_from_prefs(prefs),
                    "manual": Game.manual_wordcheck_from_prefs(prefs),
                },
                "live": opp in online,
                "image": "" if u is None else u.image(),
                "fav": False if cuser is None else cuser.has_favorite(opp),
            }
        )
    return result


def _opponent_waiting(user_id: str, opp_id: str) -> bool:
    """ Return True if the given opponent is waiting on this user's challenge """
    return firebase.check_wait(opp_id, user_id)


def _challengelist() -> List[Dict[str, Any]]:
    """ Return a list of challenges issued or received by the current user """

    result: List[Dict[str, Any]] = []
    cuser = current_user()
    assert cuser is not None
    cuid = cuser.id()
    assert cuid is not None

    def is_timed(prefs: Optional[Dict[str, Any]]) -> bool:
        """ Return True if the challenge is for a timed game """
        if prefs is None:
            return False
        return prefs.get("duration", 0) > 0

    def opp_ready(c: ChallengeTuple):
        """Returns True if this is a timed challenge
        and the opponent is ready to play"""
        if not is_timed(c[1]):
            return False
        # Timed challenge: see if there is a Firebase path indicating
        # that the opponent is waiting for this user
        assert cuid is not None
        assert c[0] is not None
        return _opponent_waiting(cuid, c[0])

    online = _get_online()
    # List received challenges
    received = list(ChallengeModel.list_received(cuid, max_len=20))
    # List issued challenges
    issued = list(ChallengeModel.list_issued(cuid, max_len=20))
    # Multi-fetch all opponents involved
    opponents = fetch_users(received + issued, lambda c: c[0])
    # List the received challenges
    for c in received:
        if not c[0]:
            continue
        u = opponents[c[0]]  # User id
        nick = u.nickname()
        result.append(
            {
                "received": True,
                "userid": c[0],
                "opp": nick,
                "fullname": u.full_name(),
                "prefs": c[1],
                "ts": Alphabet.format_timestamp_short(c[2]),
                "opp_ready": False,
                "live": c[0] in online,
                "image": u.image(),
                "fav": False if cuser is None else cuser.has_favorite(c[0]),
            }
        )
    # List the issued challenges
    for c in issued:
        if not c[0]:
            continue
        u = opponents[c[0]]  # User id
        nick = u.nickname()
        result.append(
            {
                "received": False,
                "userid": c[0],
                "opp": nick,
                "fullname": u.full_name(),
                "prefs": c[1],
                "ts": Alphabet.format_timestamp_short(c[2]),
                "opp_ready": opp_ready(c),
                "live": c[0] in online,
                "image": u.image(),
                "fav": False if cuser is None else cuser.has_favorite(c[0]),
            }
        )
    return result


@api.route("/submitmove", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def submitmove() -> ResponseType:
    """ Handle a move that is being submitted from the client """
    # This URL should only receive Ajax POSTs from the client
    rq = RequestData(request)
    movelist = rq.get_list("moves")
    movecount = rq.get_int("mcount")
    uuid = rq.get("uuid")

    game = None if uuid is None else Game.load(uuid, use_cache=False)

    if game is None:
        return jsonify(result=Error.GAME_NOT_FOUND)

    # Make sure the client is in sync with the server:
    # check the move count
    if movecount != game.num_moves():
        return jsonify(result=Error.OUT_OF_SYNC)

    if game.player_id_to_move() != current_user_id():
        return jsonify(result=Error.WRONG_USER)

    # Switch to the game's locale before processing the move
    set_game_locale(game.locale)

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
    """ Returns the current state of a game """

    rq = RequestData(request)
    uuid = rq.get("game")

    user_id = current_user_id()
    assert user_id is not None

    game = Game.load(uuid) if uuid else None

    if game is None:
        # We must have a logged-in user and a valid game
        return jsonify(ok=False)

    player_index = game.player_index(user_id)
    if player_index is None and not game.is_over:
        # The game is still ongoing and this user is not one of the players:
        # refuse the request
        return jsonify(ok=False)

    # Switch to the game's locale for the client state info
    set_game_locale(game.locale)

    return jsonify(ok=True, game=game.client_state(player_index, deep=True))


@api.route("/forceresign", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def forceresign() -> ResponseType:
    """ Forces a tardy user to resign, if the game is overdue """

    user_id = current_user_id()
    rq = RequestData(request)
    uuid = rq.get("game")
    movecount = rq.get_int("mcount", -1)

    game = None if uuid is None else Game.load(uuid, use_cache=False)

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
    return _process_move(game, ["rsgn"])


@api.route("/wordcheck", methods=["POST"])
@auth_required(ok=False)
def wordcheck() -> str:
    """ Check a list of words for validity """

    rq = RequestData(request)
    # If a locale is included in the request,
    # use it within the current thread for the vocabulary lookup
    locale: Optional[str] = rq.get("locale")
    words = rq.get_list("words")
    word = rq["word"]

    if locale:
        set_game_locale(locale)

    # Check the words against the dictionary
    wdb = Wordbase.dawg()
    ok = all([w in wdb for w in words])
    return jsonify(word=word, ok=ok)


@api.route("/gamestats", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def gamestats() -> str:
    """ Calculate and return statistics on a given finished game """

    rq = RequestData(request)
    uuid = rq.get("game")
    game = None

    if uuid is not None:
        game = Game.load(uuid)
        # Check whether the game is still in progress
        if (game is not None) and not game.is_over():
            # Don't allow looking at the stats in this case
            game = None

    if game is None:
        return jsonify(result=Error.GAME_NOT_FOUND)

    # Switch to the game's locale
    set_game_locale(game.locale)

    return jsonify(game.statistics())


@api.route("/userstats", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def userstats() -> str:
    """ Calculate and return statistics on a given user """

    cid = current_user_id()
    rq = RequestData(request)
    uid = rq.get("user", cid)  # Current user is implicit
    user = User.load_if_exists(uid)

    if user is None:
        return jsonify(result=Error.WRONG_USER)

    cuser = current_user()
    assert cuser is not None

    profile = user.profile()

    # Include info on whether this user is a favorite of the current user
    fav = False
    if uid != cuser.id():
        fav = cuser.has_favorite(uid)
    profile["favorite"] = fav

    # Include info on whether the current user has challenged this user
    chall = False
    if uid != cuser.id():
        chall = cuser.has_challenge(uid)
    profile["challenge"] = chall

    # Include info on whether the current user has blocked this user
    blocked = False
    if uid != cuser.id():
        blocked = cuser.has_blocked(uid)
    profile["blocked"] = blocked

    return jsonify(profile)


@api.route("/userlist", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def userlist() -> ResponseType:
    """ Return user lists with particular criteria """

    rq = RequestData(request)
    query = rq.get("query")
    spec = rq.get("spec")
    return jsonify(result=Error.LEGAL, spec=spec, userlist=_userlist(query, spec))


@api.route("/gamelist", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def gamelist() -> ResponseType:
    """ Return a list of active games for the current user """

    # Specify "zombies":false to omit zombie games from the returned list
    rq = RequestData(request)
    include_zombies = rq.get_bool("zombies", True)
    cuid = current_user_id()
    assert cuid is not None
    return jsonify(result=Error.LEGAL, gamelist=_gamelist(cuid, include_zombies))


@api.route("/rating", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def rating() -> ResponseType:
    """Return the newest Elo ratings table (top 100)
    of a given kind ('all' or 'human')"""
    rq = RequestData(request)
    kind = rq.get("kind", "all")
    if kind not in ("all", "human"):
        kind = "all"
    return jsonify(result=Error.LEGAL, rating=_rating(kind))


@api.route("/recentlist", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def recentlist() -> ResponseType:
    """ Return a list of recently completed games for the indicated user """

    rq = RequestData(request)
    user_id = rq.get("user")
    versus = rq.get("versus")
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
    """ Return a list of challenges issued or received by the current user """
    return jsonify(result=Error.LEGAL, challengelist=_challengelist())


@api.route("/favorite", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def favorite() -> ResponseType:
    """ Create or delete an A-favors-B relation """

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
    """ Create or delete an A-challenges-B relation """

    user = current_user()
    assert user is not None

    rq = RequestData(request)
    destuser = rq.get("destuser")
    if not destuser:
        return jsonify(result=Error.WRONG_USER)
    action = rq.get("action", "issue")
    duration = rq.get_int("duration")
    fairplay = rq.get_bool("fairplay")
    new_bag = rq.get_bool("newbag")
    manual = rq.get_bool("manual")

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
                "newbag": new_bag,
                "manual": manual,
            },
        )
    elif action == "retract":
        user.retract_challenge(destuser)
    elif action == "decline":
        # Decline challenge previously made by the destuser (really srcuser)
        user.decline_challenge(destuser)
    elif action == "accept":
        # Accept a challenge previously made by the destuser (really srcuser)
        user.accept_challenge(destuser)
    # Notify the destination user via a
    # Firebase notification to /user/[user_id]/challenge
    # main.html listens to this
    firebase.send_update("user", destuser, "challenge")

    return jsonify(result=Error.LEGAL)


@api.route("/setuserpref", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def setuserpref() -> ResponseType:
    """ Set a user preference """

    user = current_user()
    assert user is not None

    rq = RequestData(request)

    # Loop through the various preference booleans and set them
    # by calling the associated function on the User instance
    prefs: List[Tuple[str, Callable[[bool], None]]] = [
        ("beginner", user.set_beginner),
        ("ready", user.set_ready),
        ("ready_timed", user.set_ready_timed),
        ("chat_disabled", user.disable_chat),
    ]

    update = False
    for s, func in prefs:
        val = rq.get_bool(s, None)
        if val is not None:
            func(val)
            update = True

    if update:
        user.update()

    return jsonify(result=Error.LEGAL)


@api.route("/onlinecheck", methods=["POST"])
@auth_required(online=False)
def onlinecheck() -> ResponseType:
    """ Check whether a particular user is online """
    rq = RequestData(request)
    if (user_id := rq.get("user")) :
        online = firebase.check_presence(user_id)
    else:
        online = False
    return jsonify(online=online)


@api.route("/waitcheck", methods=["POST"])
@auth_required(waiting=False)
def waitcheck() -> ResponseType:
    """ Check whether a particular opponent is waiting on a challenge """
    rq = RequestData(request)
    opp_id = rq.get("user")
    waiting = False
    if opp_id:
        cuid = current_user_id()
        assert cuid is not None
        waiting = _opponent_waiting(cuid, opp_id)
    return jsonify(userid=opp_id, waiting=waiting)


@api.route("/cancelwait", methods=["POST"])
@auth_required(ok=False)
def cancelwait() -> ResponseType:
    """ A wait on a challenge has been cancelled """
    rq = RequestData(request)
    user_id = rq.get("user")
    opp_id = rq.get("opp")

    if not user_id or not opp_id:
        return jsonify(ok=False)

    # Delete the current wait and force update of the opponent's challenge list
    msg = {
        "user/" + user_id + "/wait/" + opp_id: None,
        "user/" + opp_id: {"challenge": datetime.utcnow().isoformat()},
    }
    firebase.send_message(msg)

    return jsonify(ok=True)


@api.route("/chatmsg", methods=["POST"])
@auth_required(ok=False)
def chatmsg() -> ResponseType:
    """ Send a chat message on a conversation channel """

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
            game = Game.load(uuid)
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
                pid = game.player_id(p)
                if pid is not None:
                    send_msg["game/" + uuid + "/" + pid + "/chat"] = md
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
            send_msg["user/" + user_id + "/chat"] = md
            send_msg["user/" + opp_id + "/chat"] = md
            firebase.send_message(send_msg)

    else:
        # Invalid channel prefix
        return jsonify(ok=False)

    return jsonify(ok=True)


class UserCache:

    """ A temporary cache for user lookups """

    def __init__(self) -> None:
        self._cache: Dict[str, Optional[User]] = {}

    def full_name(self, user_id: str) -> str:
        """ Return the full name of a user """
        if (u := self._cache.get(user_id)) is None:
            u = self._cache[user_id] = User.load_if_exists(user_id)
        return "" if u is None else u.full_name()

    def image(self, user_id: str) -> str:
        """ Return the image for a user """
        if (u := self._cache.get(user_id)) is None:
            u = self._cache[user_id] = User.load_if_exists(user_id)
        return "" if u is None else u.image()


@api.route("/chatload", methods=["POST"])
@auth_required(ok=False)
def chatload() -> ResponseType:
    """ Load all chat messages on a conversation channel """

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
            game = Game.load(uuid)
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
    messages: List[Dict[str, str]] = [
        dict(
            from_userid=(uid := cm["user"]),
            name=uc.full_name(uid),
            image=uc.image(uid),
            msg=cm["msg"],
            ts=Alphabet.format_timestamp(cm["ts"]),
        )
        for cm in ChatModel.list_conversation(channel)
    ]

    return jsonify(ok=True, messages=messages)


@api.route("/chathistory", methods=["POST"])
@auth_required(ok=False)
def chathistory() -> ResponseType:
    """ Return the chat history, i.e. the set of recent,
        distinct chat conversations for the logged-in user """

    user_id = current_user_id()
    if not user_id:
        # Unknown current user
        return jsonify(ok=False)

    # Return the messages sorted in ascending timestamp order.
    # ChatModel.list_conversations returns them in descending
    # order since its maxlen limit cuts off the oldest messages.
    uc = UserCache()
    history: List[Dict[str, Any]] = [
        dict(
            user=(uid := cm["user"]),
            name=uc.full_name(uid),
            image=uc.image(uid),
            last_msg=cm["last_msg"],
            ts=Alphabet.format_timestamp(cm["ts"]),
            unread=cm["unread"],
        )
        for cm in ChatModel.chat_history(user_id)
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
    game: Optional[Game] = None if uuid is None else Game.load(uuid)

    if game is None or not game.is_over():
        # The game is not found or still in progress: abort
        return jsonify(result=Error.GAME_NOT_FOUND)

    # Switch to the game's locale
    set_game_locale(game.locale)

    move_number = rq.get_int("move")
    if move_number > game.num_moves():
        move_number = game.num_moves()
    elif move_number < 0:
        move_number = 0

    state = game.state_after_move(move_number if move_number == 0 else move_number - 1)
    player_index = state.player_to_move()

    best_moves: Optional[List[Tuple[int, SummaryTuple]]] = None
    if game.allows_best_moves():

        # Serialize access to the following section
        with autoplayer_lock:

            # Show best moves if available and it is proper to do so (i.e. the game is finished)
            apl = AutoPlayer(state)
            # Ask for max 19 moves because that is what fits on screen
            best_moves = [
                (player_index, m.summary(state)) for m, _ in apl.generate_best_moves(19)
            ]

    uid = user.id()
    if uid is not None and game.has_player(uid):
        # Look at the game from the point of view of this player
        user_index = game.player_index(uid)
    else:
        # This is an outside spectator: look at it from the point of view of
        # player 0, or the human player if player 0 is an autoplayer
        user_index = 1 if game.is_autoplayer(0) else 0

    return jsonify(
        result=Error.LEGAL,
        move_number=move_number,
        player_index=player_index,
        user_index=user_index,
        player_rack=state.rack_details(player_index),
        best_moves=best_moves,
    )


@api.route("/blockuser", methods=["POST"])
@auth_required(ok = False)
def blockuser() -> ResponseType:
    """ Block or unblock another user """
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
@auth_required(ok = False)
def reportuser() -> ResponseType:
    """ Report another user """
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


@api.route("/loaduserprefs", methods=["POST"])
@auth_required(ok=False)
def loaduserprefs() -> ResponseType:
    """ Fetch the preferences of the current user in JSON form """
    # Return the user preferences in JSON form
    uf = UserForm(current_user())
    return jsonify(ok=True, userprefs=uf.as_dict())


@api.route("/saveuserprefs", methods=["POST"])
@auth_required(ok=False)
def saveuserprefs() -> ResponseType:
    """ Fetch the preferences of the current user in JSON form """

    user = current_user()
    assert user is not None
    j: Dict[str, str] = cast(Any, request).get_json(silent=True)

    # Return the user preferences in JSON form
    uf = UserForm()
    uf.init_from_dict(j)
    err = uf.validate()
    if err:
        return jsonify(ok=False, err=err)
    uf.store(user)
    return jsonify(ok=True)


@api.route("/initgame", methods=["POST"])
@auth_required(ok=False)
def initgame() -> ResponseType:
    """ Create a new game and return its UUID """

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

    board_type = rq.get("board_type", current_board_type())

    # Is this a reverse action, i.e. the challenger initiating a timed game,
    # instead of the challenged player initiating a normal one?
    rev = rq.get_bool("rev")

    prefs: Optional[PrefsDict]

    if opp.startswith("robot-"):
        # Start a new game against an autoplayer (robot)
        robot_level = int(opp[6:])
        # Play the game with the new bag if the user prefers it
        prefs = dict(newbag=user.new_bag(), locale=user.locale,)
        if board_type != "standard":
            prefs["board_type"] = board_type
        game = Game.new(uid, None, robot_level, prefs=prefs)
        # Return the uuid of the new game
        return jsonify(ok=True, uuid=game.id())

    # Start a new game between two human users
    if rev:
        # Timed game: load the opponent
        opp_user = User.load_if_exists(opp)
        if opp_user is None:
            return jsonify(ok=False)
        # In this case, the opponent accepts the challenge
        found, prefs = opp_user.accept_challenge(uid)
    else:
        # The current user accepts the challenge
        found, prefs = user.accept_challenge(opp)

    if not found:
        # No challenge existed between the users
        return jsonify(ok=False)

    # Create a fresh game object
    game = Game.new(uid, opp, 0, prefs)

    # Notify the opponent's client that there is a new game
    msg: Dict[str, Any] = {"user/" + opp + "/move": datetime.utcnow().isoformat()}

    # If this is a timed game, notify the waiting party
    if prefs and cast(int, prefs.get("duration", 0)) > 0:
        msg["user/" + opp + "/wait/" + uid] = {"game": game.id()}

    firebase.send_message(msg)

    # Return the uuid of the new game
    return jsonify(ok=True, uuid=game.id())


@api.route("/gameover", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def gameover() -> ResponseType:
    """A player has seen a game finish: remove it from
    the zombie list, if it is there"""
    cuid = current_user_id()
    rq = RequestData(request)
    game_id = rq.get("game")
    user_id = rq.get("player")
    if not game_id or cuid != user_id:
        # A user can only remove her own games from the zombie list
        return jsonify(result=Error.GAME_NOT_FOUND)
    ZombieModel.del_game(game_id, user_id)
    return jsonify(result=Error.LEGAL)


@api.route("/locale_asset", methods=["POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def locale_asset() -> ResponseType:
    """ Return static content, for the user's locale """
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
    locale = u.locale or "en_US"
    parts = locale.split("_")
    static_folder = current_app.static_folder or "../static"
    # Try en_US first, then en, then nothing
    for ix in range(len(parts), -1, -1):
        lc = "_".join(parts[0:ix])
        fname = os.path.join(static_folder, "assets", lc, asset)
        if os.path.isfile(fname):
            # Found the static asset file: return it
            return current_app.send_static_file(os.path.join("assets", lc, asset))
    return "", 404  # Not found
