"""

    Server API for netskrafl.is / Explo Word Game

    Copyright (C) 2024 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl


    This module contains the API entry points into the Netskrafl server.
    These APIs are used both by the web front-end and by the app client.

"""

from __future__ import annotations
from functools import wraps

from typing import (
    Optional,
    Dict,
    Sequence,
    TypedDict,
    List,
    Any,
    Tuple,
    Callable,
    cast,
)

import os
import logging
from datetime import UTC, datetime
import base64
import io
from zlib import adler32

from flask import (
    Blueprint,
    request,
    send_file,  # type: ignore
)
from flask.globals import current_app
from werkzeug.utils import redirect
from PIL import Image

from config import (
    RC_WEBHOOK_AUTH,
    RouteType,
    running_local,
    PROJECT_ID,
    DEFAULT_LOCALE,
    ResponseType,
)
from basics import (
    RouteFunc,
    is_mobile_client,
    jsonify,
    auth_required,
    RequestData,
    current_user,
    current_user_id,
    clear_session_userid,
)
from languages import (
    Alphabet,
    current_board_type,
    set_game_locale,
    to_supported_locale,
)
from dawgdictionary import Wordbase
from skraflmechanics import (
    Board,
    Error,
)
from skrafluser import User
from skraflgame import BestMoveList, Game
from skrafldb import (
    ChatModel,
    ZombieModel,
    PrefsDict,
    UserModel,
)
import firebase
from billing import cancel_plan
import auth
from logic import (
    EXPLO_LOGO_URL,
    MoveNotifyDict,
    UserForm,
    opponent_waiting,
    localize_push_message,
    process_move,
    set_online_status_for_chats,
    autoplayer_lock,
    userlist,
    gamelist,
    recentlist,
    challengelist,
    rating,
)


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


ChatHistoryList = List[ChatHistoryDict]


class RevenueCatEvent(TypedDict, total=False):
    """A JSON object describing a subscription event from RevenueCat"""

    type: str
    app_user_id: str
    transferred_from: Sequence[str]
    transferred_to: Sequence[str]


# Default number of best moves to return from /bestmoves.
# This is set to 19 moves because that number is what fits
# in the move list of the fullscreen web version.
DEFAULT_BEST_MOVES = 19
# Maximum number of best moves to return from /bestmoves
MAX_BEST_MOVES = 20
# Only allow POST requests to the API endpoints
_ONLY_POST: Sequence[str] = ["POST"]

# Register the Flask blueprint for the APIs
api = api_blueprint = Blueprint("api", __name__)


def api_route(route: str, methods: Sequence[str] = _ONLY_POST) -> RouteFunc:
    """Decorator for API routes; checks that the name of the route function ends with '_api'"""

    def decorator(f: RouteType) -> RouteType:

        assert f.__name__.endswith("_api"), f"Name of API function '{f.__name__}' must end with '_api'"

        @api.route(route, methods=methods)
        @wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> ResponseType:
            return f(*args, **kwargs)

        return wrapper

    return decorator


@api_route("/oauth2callback")
def oauth2callback_api() -> ResponseType:
    """The OAuth2 login flow POSTs to this callback when a user has
    signed in using a Google Account"""
    return auth.oauth2callback(request)


@api_route("/oauth_fb")
def oauth_fb_api() -> ResponseType:
    """Facebook authentication"""
    return auth.oauth_fb(request)


@api_route("/oauth_apple")
def oauth_apple_api() -> ResponseType:
    """Apple authentication"""
    return auth.oauth_apple(request)


@api_route("/oauth_explo")
def oauth_explo_api() -> ResponseType:
    """Explo authentication"""
    return auth.oauth_explo(request)


@api_route("/oauth_anon")
def oauth_anon_api() -> ResponseType:
    """Anonymous authentication"""
    return auth.oauth_anonymous(request)


@api_route("/logout")
def logout_api() -> ResponseType:
    """Log the current user out"""
    clear_session_userid()
    return jsonify({"status": "success"})


@api_route("/delete_account")
@auth_required(allow_anonymous=False, ok=False)
def delete_account_api() -> ResponseType:
    """Delete the account of the current user"""
    # This marks the account as inactive and erases personally identifiable data
    # such as the full name, the email address and the profile picture.
    # Challenges and favorites associated with the account are also deleted.
    u = current_user()
    if not u or not u.delete_account():
        return jsonify(ok=False)
    # Successfully deleted: also delete the session cookie
    clear_session_userid()
    return jsonify(ok=True)


@api_route("/firebase_token")
@auth_required(ok=False)
def firebase_token_api() -> ResponseType:
    """Obtain a custom Firebase token for the current logged-in user"""
    cuid = current_user_id()
    if not cuid:
        return jsonify(ok=False)
    try:
        token = firebase.create_custom_token(cuid)
        return jsonify(ok=True, token=token)
    except:
        return jsonify(ok=False)


@api_route("/submitmove")
@auth_required(result=Error.LOGIN_REQUIRED)
def submitmove_api() -> ResponseType:
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
            result = process_move(game, movelist)
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


@api_route("/gamestate")
@auth_required(ok=False)
def gamestate_api() -> ResponseType:
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


@api_route("/clear_zombie")
@auth_required(allow_anonymous=False, ok=False)
def clear_zombie_api() -> ResponseType:
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


@api_route("/forceresign")
@auth_required(allow_anonymous=False, result=Error.LOGIN_REQUIRED)
def forceresign_api() -> ResponseType:
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
    return process_move(game, ["rsgn"], force_resign=True)


@api_route("/wordcheck")
@auth_required(ok=False)
def wordcheck_api() -> ResponseType:
    """Check a list of words for validity"""
    # Note: The Explo app calls the /wordcheck endpoint on the 'moves' service,
    # not this endpoint (which is on the 'default' service)
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
    # use it for the vocabulary lookup
    locale = to_supported_locale(rq.get("locale", ""))

    # Check the words against the dictionary
    wdb = Wordbase.dawg_for_locale(locale)
    valid = [(w, w in wdb) for w in words]
    ok = all(v[1] for v in valid)
    return jsonify(word=word, ok=ok, valid=valid)


@api_route("/gamestats")
@auth_required(allow_anonymous=False, result=Error.LOGIN_REQUIRED)
def gamestats_api() -> ResponseType:
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


@api_route("/userstats")
@auth_required(result=Error.LOGIN_REQUIRED)
def userstats_api() -> ResponseType:
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


@api_route("/image", methods=["GET", "POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def image_api() -> ResponseType:
    """Set (POST) or get (GET) the image of a user"""
    rq = RequestData(request, use_args=True)
    method: str = cast(Any, request).method
    cuid = current_user_id()
    uid = rq.get("uid") or cuid or ""
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
            if not image or image.startswith(("https:", "http:")):
                # Accommodate strange scenarios
                mimetype = "image/jpeg"
            else:
                mimetype = image
            try:
                decoded_image = base64.b64decode(image_blob)
                # Convert the decoded image to a BytesIO object
                image_bytes = io.BytesIO(decoded_image)
                checksum = adler32(decoded_image) & 0xFFFFFFFF
                # Serve the image using flask.send_file(),
                # with a cache time of 10 minutes
                return send_file(
                    image_bytes,
                    mimetype=mimetype,
                    etag=f"img:{checksum:08x}",
                    max_age=10 * 60,
                )
            except Exception:
                # Something wrong in the image_blob: give up
                pass
        if not image or not image.startswith(("https:", "http:")):
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


@api_route("/thumbnail", methods=["GET", "POST"])
@auth_required(result=Error.LOGIN_REQUIRED)
def thumbnail_api() -> ResponseType:
    """Get (GET) a profile image thumbnail for a user"""
    rq = RequestData(request, use_args=True)
    uid = rq.get("uid", "") or current_user_id() or ""
    um = UserModel.fetch(uid) if uid else None
    if not um:
        # User not found
        return jsonify({ "ok": False })
    # Get image for user
    image, image_blob = um.get_image()
    if image_blob:
        # We have the image as a bytes object: return it
        try:
            decoded_image = base64.b64decode(image_blob)
            # Convert the decoded image to a BytesIO object
            image_bytes = io.BytesIO(decoded_image)
            # Create a thumbnail using PIL
            img = Image.open(image_bytes)  # type: ignore
            img.thumbnail((512, 512))  # type: ignore
            thumb_bytes = io.BytesIO()
            img.save(thumb_bytes, "JPEG")  # type: ignore
            thumb_bytes.seek(0)
            # Serve the image using flask.send_file()
            return send_file(
                thumb_bytes, mimetype="image/jpeg", max_age=10 * 60
            )  # 10 minutes
        except Exception:
            # Something wrong in the image_blob: give up
            pass
    if not image or not image.startswith(("https:", "http:")):
        return "Image not found", 404  # Not found
    # Assume that this is a URL: redirect to it
    return redirect(image)


@api_route("/userlist")
@auth_required(result=Error.LOGIN_REQUIRED)
def userlist_api() -> ResponseType:
    """Return user lists with particular criteria"""
    rq = RequestData(request)
    query = rq.get("query")
    spec = rq.get("spec")
    return jsonify(result=Error.LEGAL, spec=spec, userlist=userlist(query, spec))


@api_route("/gamelist")
@auth_required(result=Error.LOGIN_REQUIRED)
def gamelist_api() -> ResponseType:
    """Return a list of active games for the current user"""
    # Specify "zombies":false to omit zombie games from the returned list
    rq = RequestData(request)
    include_zombies = rq.get_bool("zombies", True)
    cuid = current_user_id()
    if cuid is None:
        return jsonify(result=Error.WRONG_USER)
    return jsonify(result=Error.LEGAL, gamelist=gamelist(cuid, include_zombies))


@api_route("/recentlist")
@auth_required(result=Error.LOGIN_REQUIRED)
def recentlist_api() -> ResponseType:
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
        recentlist=recentlist(user_id, versus=versus, max_len=count),
    )


@api_route("/challengelist")
@auth_required(result=Error.LOGIN_REQUIRED)
def challengelist_api() -> ResponseType:
    """Return a list of challenges issued or received by the current user"""
    return jsonify(result=Error.LEGAL, challengelist=challengelist())


@api_route("/allgamelists")
@auth_required(result=Error.LOGIN_REQUIRED)
def allgamelists_api() -> ResponseType:
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
        gamelist=gamelist(cuid, include_zombies),
        challengelist=challengelist(),
        recentlist=recentlist(cuid, versus=None, max_len=count),
    )


@api_route("/rating")
@auth_required(result=Error.LOGIN_REQUIRED)
def rating_api() -> ResponseType:
    """Return the newest Elo ratings table (top 100)
    of a given kind ('all' or 'human')"""
    rq = RequestData(request)
    kind = rq.get("kind", "all")
    if kind not in ("all", "human", "manual"):
        kind = "all"
    return jsonify(result=Error.LEGAL, rating=rating(kind))


@api_route("/favorite")
@auth_required(allow_anonymous=False, result=Error.LOGIN_REQUIRED)
def favorite_api() -> ResponseType:
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


@api_route("/challenge")
@auth_required(allow_anonymous=False, result=Error.LOGIN_REQUIRED)
def challenge_api() -> ResponseType:
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
        # Notify the challenged user via a push notification
        firebase.push_to_user(
            destuser,
            {
                "title": lambda locale: localize_push_message("chall_title", locale),
                "body": lambda locale: localize_push_message(
                    "chall_body", locale
                ).format(player=user.nickname()),
                "image": lambda locale: EXPLO_LOGO_URL,
            },
            {
                "type": "notify-challenge",
                "uid": uid,
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
    now = datetime.now(UTC).isoformat()
    msg[f"user/{destuser}/challenge"] = now
    msg[f"user/{uid}/challenge"] = now
    firebase.send_message(msg)

    return jsonify(result=Error.LEGAL)


@api_route("/setuserpref")
@auth_required(result=Error.LOGIN_REQUIRED)
def setuserpref_api() -> ResponseType:
    """Set a user preference"""
    user = current_user()
    assert user is not None

    rq = RequestData(request)

    # Loop through the various preference booleans and set them
    # by calling the associated function on the User instance.
    # The last bool parameter is True if the setting is only
    # available for mobile clients.
    prefs: List[Tuple[str, Callable[[bool], None]]] = [
        ("beginner", user.set_beginner),
        ("ready", user.set_ready),
        ("ready_timed", user.set_ready_timed),
        ("chat_disabled", user.disable_chat),
    ]

    update = False
    # We don't allow anonymous users to set the above preferences
    if not user.is_anonymous():
        for s, func in prefs:
            val = rq.get_bool(s, None)
            if val is not None:
                func(val)
                update = True

    # We allow the locale to be set as a preference,
    # even for anonymous users.
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


@api_route("/onlinecheck")
@auth_required(allow_anonymous=False, online=False)
def onlinecheck_api() -> ResponseType:
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


@api_route("/initwait")
@auth_required(allow_anonymous=False, online=False, waiting=False)
def initwait_api() -> ResponseType:
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
    now = datetime.now(UTC).isoformat()
    msg = {
        f"user/{opp}/challenge": now,
        f"user/{uid}/wait/{opp}": {"key": key} if key else True,
    }
    firebase.send_message(msg)
    online = firebase.check_presence(uid, user.locale)
    return jsonify(online=online, waiting=True)


@api_route("/waitcheck")
@auth_required(allow_anonymous=False, waiting=False)
def waitcheck_api() -> ResponseType:
    """Check whether a particular opponent is waiting on a challenge"""
    rq = RequestData(request)
    opp_id = rq.get("user")
    key: Optional[str] = rq.get("key")  # Can be omitted
    waiting = False
    if opp_id:
        cuid = current_user_id()
        assert cuid is not None
        waiting = opponent_waiting(cuid, opp_id, key=key)
    return jsonify(userid=opp_id, waiting=waiting)


@api_route("/cancelwait")
@auth_required(allow_anonymous=False, ok=False)
def cancelwait_api() -> ResponseType:
    """A wait on a challenge has been cancelled"""
    rq = RequestData(request)
    opp_id = rq.get("opp")
    cuid = current_user_id()

    if not opp_id or not cuid:
        return jsonify(ok=False)

    # Delete the current wait and force update of the opponent's challenge list
    now = datetime.now(UTC).isoformat()
    msg = {
        f"user/{cuid}/wait/{opp_id}": None,
        f"user/{opp_id}/challenge": now,
    }
    firebase.send_message(msg)

    return jsonify(ok=True)


@api_route("/chatmsg")
@auth_required(allow_anonymous=False, ok=False)
def chatmsg_api() -> ResponseType:
    """Send a chat message on a conversation channel"""
    if not (user_id := current_user_id()):
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
        uuid = channel[5:][:36]  # The game id; UUIDs are 36 chars long
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
        opp_id = channel[5:][
            :64
        ]  # The opponent id is e.g. 50 characters in the case of Apple
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


@api_route("/chatload")
@auth_required(allow_anonymous=False, ok=False)
def chatload_api() -> ResponseType:
    """Load all chat messages on a conversation channel"""

    # The channel can be either 'game:' + game uuid or
    # 'user:' + user id
    user_id = current_user_id()
    if not user_id:
        # Unknown current user
        return jsonify(ok=False)

    rq = RequestData(request)
    channel = rq.get("channel", "")
    maxlen = rq.get_int("count", 50)

    if not channel:
        # We must have a valid channel
        return jsonify(ok=False)

    if channel.startswith("game:"):
        # In-game conversation
        game: Optional[Game] = None
        uuid = channel[5:][:36]  # The game id (UUIDs are 36 chars long)
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
        opp_id = channel[5:][:64]  # The opponent id, e.g. 50 chars in the case of Apple
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
        for cm in ChatModel.list_conversation(channel, maxlen=maxlen)
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


@api_route("/chathistory")
@auth_required(allow_anonymous=False, ok=False)
def chathistory_api() -> ResponseType:
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

    online = firebase.online_status(user.locale or DEFAULT_LOCALE)
    # We don't return chat conversations with users
    # that this user has blocked
    blocked = user.blocked()
    uc = UserCache()
    # The chat history is ordered in reverse timestamp
    # order, i.e. the newest entry comes first
    history: ChatHistoryList = [
        ChatHistoryDict(
            user=(uid := cm["user"]),
            name=uc.full_name(uid),
            nick=uc.nickname(uid),
            image=uc.image(uid),
            last_msg=cm["last_msg"],
            ts=Alphabet.format_timestamp(cm["ts"]),
            unread=cm["unread"],
            live=False,  # Will be filled in later
            fav=user.has_favorite(uid),
            disabled=uc.chat_disabled(uid),
        )
        for cm in ChatModel.chat_history(user_id, blocked_users=blocked, maxlen=count)
    ]

    set_online_status_for_chats(history, online.users_online)
    return jsonify(ok=True, history=history)


@api_route("/bestmoves")
@auth_required(allow_anonymous=False, result=Error.LOGIN_REQUIRED)
def bestmoves_api() -> ResponseType:
    """Return a list of the best possible moves in a game
    at a given point"""
    user = current_user()
    assert user is not None

    if not user.has_paid() and not is_mobile_client() and not running_local:
        # For this to succeed, the user must be a paying friend,
        # or the request is coming from a mobile client
        # (where the paywall gating is reliably performed in the UI)
        # or we're on a development server
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


@api_route("/blockuser")
@auth_required(allow_anonymous=False, ok=False)
def blockuser_api() -> ResponseType:
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


@api_route("/reportuser")
@auth_required(allow_anonymous=False, ok=False)
def reportuser_api() -> ResponseType:
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


@api_route("/cancelplan")
@auth_required(allow_anonymous=False, result=Error.LOGIN_REQUIRED)
def cancelplan_api() -> ResponseType:
    """Cancel a user friendship"""
    user = current_user()
    if user is None:
        return jsonify(ok=False)
    result = cancel_plan(user)
    return jsonify(ok=result)


# RevenueCat event types that start or continue a subscription
SUBSCRIPTION_START_TYPES = frozenset(
    [
        "INITIAL_PURCHASE",
        "NON_RENEWING_PURCHASE",
        "RENEWAL",
        "UNCANCELLATION",
    ]
)

# RevenueCat event types that end a subscription
SUBSCRIPTION_END_TYPES = frozenset(
    [
        "CANCELLATION",
        "SUBSCRIPTION_PAUSED",
        "EXPIRATION",
    ]
)

# Assert if there is overlap between the two sets
assert not SUBSCRIPTION_START_TYPES.intersection(
    SUBSCRIPTION_END_TYPES
), "SUBSCRIPTION_START_TYPES and SUBSCRIPTION_END_TYPES must be disjoint"


@api_route("/rchook")
def rchook_api() -> ResponseType:
    """Receive a webhook call from the RevenueCat server"""
    # First, validate whether the request has the correct
    # bearer token (RC_WEBHOOK_AUTH)
    if not RC_WEBHOOK_AUTH:
        return "Not supported", 200
    if request.headers.get("Authorization", "") != "Bearer " + RC_WEBHOOK_AUTH:
        return "Not authorized", 401
    # OK: Process the request
    rq = RequestData(request)
    # logging.info(f"Received webhook from RevenueCat: {rq!r}")
    event: RevenueCatEvent = rq.get("event", RevenueCatEvent())
    rq_type = event.get("type", "")
    if rq_type in SUBSCRIPTION_START_TYPES:
        # A subscription has been purchased or renewed
        user_id = event.get("app_user_id", "")
        if user_id:
            user = User.load_if_exists(user_id)
            if user is not None:
                user.add_transaction("friend", "rchook", rq_type)
        return "OK", 200

    elif rq_type in SUBSCRIPTION_END_TYPES:
        # A subscription has expired or been cancelled
        user_id = event.get("app_user_id", "")
        if user_id:
            user = User.load_if_exists(user_id)
            if user is not None:
                user.add_transaction("", "rchook", rq_type)
        return "OK", 200

    elif rq_type == "TRANSFER":
        # A subscription has been transferred between users,
        # from the one in transferred_from[0] to the one in
        # transferred_to[0]. Load both users and add the appropriate
        # transactions.
        from_list = event.get("transferred_from") or [""]
        to_list = event.get("transferred_to") or [""]
        user_from_id = from_list[0]
        user_to_id = to_list[0]
        if user_from_id:
            user = User.load_if_exists(user_from_id)
            if user is not None:
                user.add_transaction("", "rchook", rq_type)
        if user_to_id:
            user = User.load_if_exists(user_to_id)
            if user is not None:
                user.add_transaction("friend", "rchook", rq_type)
        return "OK", 200

    # Return 200 OK for all other event types, since RevenueCat
    # will retry the request if we return an error
    logging.info(f"Ignoring RevenueCat event type '{rq_type}'")
    return "OK", 200


@api_route("/loaduserprefs")
@auth_required(ok=False)
def loaduserprefs_api() -> ResponseType:
    """Fetch the preferences of the current user in JSON form"""
    # Return the user preferences in JSON form
    uf = UserForm(current_user())
    return jsonify(ok=True, userprefs=uf.as_dict())


@api_route("/saveuserprefs")
@auth_required(ok=False)
def saveuserprefs_api() -> ResponseType:
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


@api_route("/inituser")
@auth_required(ok=False)
def inituser_api() -> ResponseType:
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


@api_route("/initgame")
@auth_required(ok=False)
def initgame_api() -> ResponseType:
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
        prefs = PrefsDict(newbag=True, locale=user.locale)
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
        prefs = PrefsDict(locale=user.locale)
    prefs["board_type"] = board_type
    set_game_locale(cast(str, prefs.get("locale")) or user.locale)
    game = Game.new(uid, opp, 0, prefs)
    game_id = game.id()
    if not game_id or game.state is None:
        # Something weird is preventing the proper creation of the game
        return jsonify(ok=False)

    # Notify both players' clients that there is a new game
    now = datetime.now(UTC).isoformat()
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
    if prefs and prefs.get("duration", 0) > 0:
        msg[f"user/{opp}/wait/{uid}"] = {"game": game_id, "key": key}

    firebase.send_message(msg)

    # Return the uuid of the new game
    return jsonify(ok=True, uuid=game_id)


@api_route("/locale_asset")
@auth_required(result=Error.LOGIN_REQUIRED)
def locale_asset_api() -> ResponseType:
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
            return send_file(fname)
    return "", 404  # Not found
