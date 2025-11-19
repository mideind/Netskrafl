"""

Web server for netskrafl.is

Copyright © 2025 Miðeind ehf.
Original author: Vilhjálmur Þorsteinsson

The Creative Commons Attribution-NonCommercial 4.0
International Public License (CC-BY-NC 4.0) applies to this software.
For further information, see https://github.com/mideind/Netskrafl


This module implements web routes, i.e. URLs that return
responsive HTML/CSS/JScript content.

JSON-based client API entrypoints are implemented in api.py.

"""

from __future__ import annotations

from typing import (
    Mapping,
    Optional,
    Dict,
    TypedDict,
    Union,
    List,
    Any,
    Callable,
    cast,
)

import os
import sys
import logging
from urllib.parse import urlparse
import uuid
from datetime import UTC, datetime

from flask import (
    Blueprint,
    render_template,
    send_from_directory,  # type: ignore
    redirect,
    url_for,
    request,
)
from flask.globals import current_app
from authlib.integrations.base_client.errors import OAuthError  # type: ignore

from auth import firebase_key
from config import (
    DEFAULT_LOCALE,
    PROJECT_ID,
    running_local,
    VALID_ISSUERS,
    ResponseType,
    Error,
)
from basics import (
    SessionDict,
    UserIdDict,
    current_user,
    auth_required,
    current_user_id,
    get_google_auth,
    jsonify,
    session_data,
    session_user,
    set_session_cookie,
    clear_session_userid,
    RequestData,
    max_age,
)
from logic import UserForm, promo_to_show_to_user, autoplayer_lock
from skrafldb import PrefsDict, ZombieModel
from skraflgame import Game, BingoList
from autoplayers import COMMON, autoplayer_create
from skrafluser import User, UserLoginDict, verify_malstadur_token
import firebase
import billing
from cache import memcache
from languages import current_board_type, set_game_locale


# Type definitions
RouteType = Callable[..., ResponseType]
UserPrefsType = Dict[str, Union[str, bool]]
GameList = List[Dict[str, Union[str, int, bool, Dict[str, bool]]]]


class OpenGraphDict(TypedDict):
    """TypedDict for OpenGraph metadata used in game board pages"""
    og: int  # -1 for third party view, 0 or 1 for player index
    player0: str  # Nickname of player from pix perspective
    player1: str  # Nickname of opponent from pix perspective
    winner: int  # -1 for draw, 0 or 1 for winning player
    win: bool  # True if the player at perspective 'og' won
    draw: bool  # True if the game was a draw
    score0: str  # Score of player0
    score1: str  # Score of player1
    bingo0: BingoList  # List of bingoes for player0
    bingo1: BingoList  # List of bingoes for player1


# Promotion parameters
# A promo check is done randomly, but on average every 1 out of N times
# _PROMO_FREQUENCY = 8
# _PROMO_COUNT = 2  # Max number of times that the same promo is displayed
# _PROMO_INTERVAL = timedelta(days=4)  # Min interval between promo displays

BASE_PATH = os.path.join(os.path.dirname(__file__), "..")
STATIC_FOLDER = os.path.join(BASE_PATH, "static")
TEMPLATE_FOLDER = os.path.join(BASE_PATH, "templates")

# Set to True to make the single-page UI the default
SINGLE_PAGE_UI = os.environ.get("SINGLE_PAGE", "FALSE").upper() == "TRUE"

# Register the Flask blueprint for the web routes
web = web_blueprint = Blueprint(
    "web", __name__, static_folder=STATIC_FOLDER, template_folder=TEMPLATE_FOLDER
)


def login_user() -> bool:
    """Log in a user after she is authenticated via OAuth"""
    # This function is called from web.oauth2callback()
    # Note that a similar function is found in api.py
    uld: Optional[UserLoginDict] = None
    account: Optional[str] = None
    userid: Optional[str] = None
    idinfo: Optional[UserIdDict] = None
    email: Optional[str] = None
    image: Optional[str] = None
    name: Optional[str] = None
    g = get_google_auth()
    try:
        token: Optional[Dict[str, UserIdDict]] = g.authorize_access_token()
        if not token:
            return False
        idinfo = token.get("userinfo")
        if idinfo is None:
            return False
        issuer = idinfo.get("iss", "")
        if issuer not in VALID_ISSUERS:
            logging.error(f"Unknown OAuth2 token issuer: {issuer or '[None]'}")
            return False
        # ID token is valid; extract the claims
        # Get the user's Google Account ID
        account = idinfo.get("sub")
        if account:
            # Full name of user
            name = idinfo.get("name", "")
            # User image
            image = idinfo.get("picture", "")
            # Make sure that the e-mail address is in lowercase
            email = idinfo.get("email", "").lower()
        if idinfo and account:
            # Attempt to find an associated user record in the datastore,
            # or create a fresh user record if not found
            uld = User.login_by_account(account, name or "", email or "", image or "")
            userid = uld["user_id"]
            # Save the stuff we want to keep around
            # in the user session
            idinfo["method"] = "Google"
            idinfo["new"] = uld.get("new", False)
            idinfo["client_type"] = "web"
    except (KeyError, ValueError, OAuthError) as e:
        # Something is wrong: we're not getting the same (random) state string back
        # that we originally sent to the OAuth2 provider
        logging.warning(f"login_user(): {e}")
        userid = None

    if not userid or idinfo is None or uld is None:
        # Unable to obtain a properly authenticated user id for some reason
        return False

    # Authentication complete; user id obtained
    set_session_cookie(userid, idinfo=idinfo)

    if running_local:
        logging.info(
            "login_user() successfully recognized "
            "account {0} userid {1} email {2} name '{3}'".format(
                account, userid, email, name
            )
        )
    return True


def render_locale_template(template: str, locale: str, **kwargs: Any) -> ResponseType:
    """Render a template for a given locale. The template file name should contain
    a {0} format placeholder for the locale."""
    parts = locale.split("_")
    if not (1 <= len(parts) <= 2) or not all(len(p) == 2 for p in parts):
        # Funky locale requested: default to 'en'
        parts = ["en"]
    # Obtain the Flask template folder
    template_folder: str = cast(Any, current_app).template_folder or TEMPLATE_FOLDER
    # Try en_US first, then en, then nothing
    for ix in range(len(parts), -1, -1):
        lc = "_".join(parts[0:ix])
        t = template.format(lc)
        if os.path.isfile(os.path.join(template_folder, t)):
            # Found a template corresponding to the locale: render it
            return render_template(t, **kwargs)
    # The locale is not found: return a default template rendering
    return render_template(template.format("en"), **kwargs)


@web.route("/friend")
@auth_required()
def friend() -> ResponseType:
    """Page for users to register or unregister themselves
    as friends of Netskrafl"""
    user = current_user()
    assert user is not None
    try:
        action = int(request.args.get("action", "0"))
    except (TypeError, ValueError):
        action = 0
    if action == 0:
        # Launch the actual payment procedure
        # render_template displays a thank-you note in this case
        pass
    elif action == 1:
        # Display a friendship promotion
        pass
    elif action == 2:
        # Request to cancel a friendship
        if not user.friend():
            # Not a friend: nothing to cancel
            return redirect(url_for("web.main"))
    elif action == 3:
        # Actually cancel a friendship
        if not user.friend():
            # Not a friend: nothing to cancel
            return redirect(url_for("web.main"))
        billing.cancel_plan(user)
    return render_template("friend.html", user=user, action=action)


@web.route("/board")
def board() -> ResponseType:
    """ The main game page """

    # Note that authentication is not required to access this page

    uuid = request.args.get("game", None)
    # Requesting a look at a newly finished game
    zombie = request.args.get("zombie", None)
    og: int | None = None
    try:
        # If the og argument is present, it indicates that OpenGraph data
        # should be included in the page header, from the point of view of
        # the player that the argument represents (i.e. og=0 or og=1).
        # If og=-1, OpenGraph data should be included but from a neutral
        # (third party) point of view.
        og_str = request.args.get("og", None)
        if og_str is not None:
            # This should be a player index: -1 (third party), 0 or 1
            og = int(og_str)  # May throw an exception
            if og < -1:
                og = -1
            elif og > 1:
                og = 1
    except (TypeError, ValueError):
        og = None

    game = None
    if uuid:
        # Attempt to load the game whose id is in the URL query string
        game = Game.load(uuid, use_cache=False)

    if game is None:
        # No active game to display: go back to main screen
        return redirect(url_for("web.main"))

    user = session_user()
    uid = "" if user is None else (user.id() or "")
    is_over = game.is_over()
    opp = None  # The opponent

    if not is_over:
        # Game still in progress
        if not uid:
            # User hasn't logged in yet: redirect to login page
            return redirect(url_for("web.login"))
        if not game.has_player(uid):
            # This user is not a party to the game: redirect to main page
            return redirect(url_for("web.main"))

    # Switch the current thread to the game's locale (i.e. not the
    # user's locale, except for the language setting)
    set_game_locale(game.locale)

    # user can be None if the game is over - we do not require a login in that case
    player_index = None if user is None else game.player_index(uid)

    # If a logged-in user is looking at the board, we create a Firebase
    # token in order to maintain presence info
    firebase_token = None if user is None else firebase.create_custom_token(uid)

    if player_index is not None and not game.is_autoplayer(1 - player_index):
        # Load information about the opponent
        opp = User.load_if_exists(game.player_id(1 - player_index))

    if zombie and player_index is not None and user is not None:
        # This is a newly finished game that is now being viewed by clicking
        # on it from a zombie list: remove it from the list
        ZombieModel.del_game(game.id(), uid)

    ogd: Optional[OpenGraphDict] = None  # OpenGraph data
    if og is not None and is_over:
        # This game is a valid and visible OpenGraph object
        # Calculate the OpenGraph stuff to be included in the page header
        pix = 0 if og < 0 else og  # Player indexing
        sc = game.final_scores()
        winner = game.winning_player()  # -1 if draw
        bingoes = game.bingoes()
        ogd = OpenGraphDict(
            og=og,
            player0=game.player_nickname(pix),
            player1=game.player_nickname(1 - pix),
            winner=winner,
            win=False if og == -1 else (og == winner),
            draw=(winner == -1),
            score0=str(sc[pix]),
            score1=str(sc[1 - pix]),
            bingo0=bingoes[pix],
            bingo1=bingoes[1 - pix],
        )

    # Delete the Firebase subtree for this game,
    # to get earlier move and chat notifications out of the way
    if firebase_token is not None and user is not None:
        game_id = game.id()
        if game_id is not None:
            msg = {
                "game/" + game_id + "/" + uid: None,
                "user/" + uid + "/wait": None,
            }
            firebase.send_message(msg)
        # No need to clear other stuff on the /user/[user_id]/ path,
        # since we're not listening to it in board.html

    return render_template(
        "board.html",
        game=game,
        user=user,
        opp=opp,
        player_index=player_index,
        zombie=bool(zombie),
        time_info=game.time_info(),
        og=ogd,  # OpenGraph data
        firebase_token=firebase_token,
    )


@web.route("/gameover", methods=["POST"])
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


@web.route("/wait")
@auth_required()
def wait() -> ResponseType:
    """ Show page to wait for a timed game to start """

    # !!! FIXME: Update wait logic for singlepage
    user = current_user()
    assert user is not None

    # Get the opponent id
    opp = request.args.get("opp", None)
    if opp is None or opp.startswith("robot-"):
        return redirect(url_for("web.main", tab="2"))  # Go directly to opponents tab

    # Find the challenge being accepted
    found, prefs = user.find_challenge(opp)
    if not found:
        # No challenge existed between the users: redirect to main page
        return redirect(url_for("web.main"))

    opp_user = User.load_if_exists(opp)
    if opp_user is None:
        # Opponent id not found
        return redirect(url_for("web.main"))

    # Notify the opponent of a change in the challenge list
    # via a Firebase notification to /user/[user_id]/challenge
    now = datetime.now(UTC).isoformat()
    uid = user.id() or ""
    msg: Mapping[str, Any] = {
        "user/" + opp: {"challenge": now},
        "user/" + uid + "/wait/" + opp: True,
    }
    firebase.send_message(msg)

    # Create a Firebase token for the logged-in user
    # to enable refreshing of the client page when
    # the user state changes (game moves made, challenges
    # issued or accepted, etc.)
    firebase_token = firebase.create_custom_token(uid)

    # Go to the wait page
    return render_template(
        "wait.html", user=user, opp=opp_user, prefs=prefs, firebase_token=firebase_token
    )


@web.route("/newgame")
@auth_required()
def newgame() -> ResponseType:
    """ Show page to initiate a new game """

    # Note: this code is not used in the single page UI

    user = current_user()
    assert user is not None
    uid = user.id()
    assert uid is not None

    # Get the opponent id
    opp = request.args.get("opp", None)

    if opp is None:
        return redirect(url_for("web.main", tab="2"))  # Go directly to opponents tab

    # Get the board type
    board_type = request.args.get("board_type", current_board_type())

    # Is this a reverse action, i.e. the challenger initiating a timed game,
    # instead of the challenged player initiating a normal one?
    rev = request.args.get("rev", None) is not None

    prefs: Optional[PrefsDict]

    if opp.startswith("robot-"):
        # Start a new game against an autoplayer (robot)
        try:
            robot_level = int(opp[6:])
        except ValueError:
            robot_level = COMMON
        # Play the game with the new bag if the user prefers it
        prefs = PrefsDict(
            newbag=user.new_bag(),
            locale=user.locale,
        )
        if board_type != "standard":
            prefs["board_type"] = board_type
        game = Game.new(uid, None, robot_level, prefs=prefs)
        return redirect(url_for("web.board", game=game.id()))

    # Start a new game between two human users
    if rev:
        # Timed game: load the opponent
        opp_user = User.load_if_exists(opp)
        if opp_user is None:
            return redirect(url_for("web.main"))
        # In this case, the opponent accepts the challenge
        found, prefs = opp_user.accept_challenge(uid)
    else:
        # The current user accepts the challenge
        found, prefs = user.accept_challenge(opp)

    if not found:
        # No challenge existed between the users: redirect to main page
        return redirect(url_for("web.main"))

    # Create a fresh game object
    game = Game.new(uid, opp, 0, prefs)

    # Notify the opponent's main.html that there is a new game
    # !!! board.html eventually needs to listen to this as well
    now = datetime.now(UTC).isoformat()
    msg: Dict[str, Any] = {"user/" + opp + "/move": now}

    # If this is a timed game, notify the waiting party
    if prefs and prefs.get("duration", 0) > 0:
        msg["user/" + opp + "/wait/" + uid] = {"game": game.id()}

    firebase.send_message(msg)

    # Go to the game page
    return redirect(url_for("web.board", game=game.id()))


@web.route("/initgame", methods=["POST"])
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
        prefs = PrefsDict(
            newbag=user.new_bag(),
            locale=user.locale,
        )
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
    now = datetime.now(UTC).isoformat()
    msg: Dict[str, Any] = {"user/" + opp + "/move": now}

    # If this is a timed game, notify the waiting party
    if prefs and prefs.get("duration", 0) > 0:
        msg["user/" + opp + "/wait/" + uid] = {"game": game.id()}

    firebase.send_message(msg)

    # Return the uuid of the new game
    return jsonify(ok=True, uuid=game.id())


@web.route("/promo", methods=["POST"])
def promo() -> ResponseType:
    """Return promotional HTML corresponding to a given key (category)"""
    user = session_user()
    if user is None:
        lang = request.accept_languages.best_match(("is", "en"), "en")
        if lang == "is":
            return "<p>Notandi er ekki innskráður</p>"  # Unauthorized
        return "<p>User not logged in</p>"
    rq = RequestData(request)
    key = rq.get("key", "")
    VALID_PROMOS = {"friend", "krafla", "explo"}
    if key not in VALID_PROMOS:
        key = "error"
    return render_template("promo-" + key + ".html", user=user)


@web.route("/signup", methods=["GET"])
@auth_required()
def signup() -> ResponseType:
    """Sign up as a friend, enter card info, etc."""
    return render_template("signup.html", user=current_user())


@web.route("/skilmalar", methods=["GET"])
def skilmalar() -> ResponseType:
    """Terms & conditions"""
    return render_template("skilmalar.html", user=session_user())


@web.route("/billing", methods=["GET", "POST"])
def handle_billing() -> ResponseType:
    """Receive signup and billing confirmations.
    Authentication not necessarily required."""
    uid = ""
    u = session_user()
    if u is not None:
        # This is called within a session: pass the user id to the billing module
        uid = u.id() or ""
    return billing.handle(request, uid)


# pylint: disable=redefined-builtin
@web.route("/help")
def help() -> ResponseType:
    """ Show help page, which does not require authentication """
    user = session_user()
    # We tolerate a null (not logged in) user here
    return render_template("nshelp.html", user=user, tab=None)


@web.route("/rawhelp")
@auth_required()
def rawhelp() -> ResponseType:
    """Return raw help page HTML."""

    user = session_user()
    locale = request.args.get("locale", DEFAULT_LOCALE)
    version = request.args.get("version", "")

    def override_url_for(endpoint: str, **values: Any) -> str:
        """Convert URLs from old-format plain ones to single-page fancy ones"""
        if endpoint in {"web.twoletter", "web.newbag", "web.userprefs"}:
            # Insert special token that will be caught by client-side
            # code and converted to an action in the single-page UI
            return "$$" + endpoint.split(".")[-1] + "$$"
        return url_for(endpoint, **values)

    return render_locale_template(
        "rawhelp-{0}.html",
        locale,
        url_for=override_url_for,
        version=version,
        user=user,
    )


@web.route("/twoletter")
def twoletter() -> ResponseType:
    """ Show help page. Authentication is not required. """
    user = session_user()
    return render_template("nshelp.html", user=user, tab="twoletter")


@web.route("/newbag")
def newbag() -> ResponseType:
    """ Show help page. Authentication is not required. """
    user = session_user()
    # We tolerate a null (not logged in) user here
    return render_template("nshelp.html", user=user, tab="newbag")


@web.route("/userprefs", methods=["GET", "POST"])
@auth_required()
def userprefs() -> ResponseType:
    """ Handler for the user preferences page """

    user = current_user()
    assert user is not None

    uf = UserForm()
    err: Dict[str, str] = dict()

    # The URL to go back to, if not main.html
    from_url = request.args.get("from", None)

    # Validate that 'from_url' does not redirect to an external site.
    # If 'urlparse(from_url).netloc' is empty, that means from_url is a relative
    # link and is safe. If .netloc is populated, it might be external.
    if from_url and urlparse(from_url).netloc != "":
        from_url = None

    if request.method == "GET":
        # Entering the form for the first time: load the user data
        uf.init_from_user(user)
    elif request.method == "POST":
        # Attempting to submit modified data: retrieve it and validate
        uf.init_from_form(request.form)
        err = uf.validate()
        if not err:
            # All is fine: store the data back in the user entity
            uf.store(user)
            return redirect(from_url or url_for("web.main"))

    # Render the form with the current data and error messages, if any
    return render_template("userprefs.html", uf=uf, err=err, user=user, from_url=from_url)


@web.route("/page")
@auth_required()
def page() -> ResponseType:
    """Show single-page UI"""
    user = current_user()
    assert user is not None
    uid = user.id() or ""
    s = session_data()
    firebase_token = firebase.create_custom_token(uid)
    promo_to_show = promo_to_show_to_user(uid)
    # We return information about the login method to the client,
    # as well as whether this is a new user signing in for the first time
    return render_template(
        "page.html",
        user=user,
        firebase_token=firebase_token,
        method="" if s is None else s.get("method", ""),
        new=False if s is None else s.get("new", False),
        project_id=PROJECT_ID,
        running_local=running_local,
        promo=promo_to_show,
    )

@web.route("/review")
@auth_required()
def review() -> ResponseType:
    """ Show game review page """

    # Only logged-in users who are paying friends can view this page
    user = current_user()
    assert user is not None

    if not user.has_paid():
        # Only paying users can see game reviews
        return redirect(url_for("web.friend", action=1))

    game = None
    uuid = request.args.get("game", None)

    if uuid is not None:
        # Attempt to load the game whose id is in the URL query string
        game = Game.load(uuid)

    if game is None or not game.is_over():
        # The game is not found: abort
        return redirect(url_for("web.main"))

    # Swith the current thread to the game's locale, overriding the
    # user's locale settings - except for the language
    set_game_locale(game.locale)

    try:
        move_number = int(request.args.get("move", "0"))
    except (TypeError, ValueError):
        move_number = 0

    if move_number > game.num_moves():
        move_number = game.num_moves()
    elif move_number < 0:
        move_number = 0

    state = game.state_after_move(move_number if move_number == 0 else move_number - 1)
    player_index = state.player_to_move()

    best_moves = None
    if game.allows_best_moves():

        # Serialize access to the following section
        with autoplayer_lock:

            # Show best moves if available and it is proper to do so (i.e. the game is finished)
            apl = autoplayer_create(state)
            # 19 is what fits on screen
            best_moves = apl.generate_best_moves(19)

    uid = user.id()
    if uid is not None and game.has_player(uid):
        # Look at the game from the point of view of this player
        user_index = game.player_index(uid)
    else:
        # This is an outside spectator: look at it from the point of view of
        # player 0, or the human player if player 0 is an autoplayer
        user_index = 1 if game.is_autoplayer(0) else 0

    return render_template(
        "review.html",
        game=game,
        state=state,
        player_index=player_index,
        user_index=user_index,
        move_number=move_number,
        best_moves=best_moves,
    )


@web.route("/greet")
def greet() -> ResponseType:
    """Handler for the greeting page"""
    return render_template("login.html", user=None)


@web.route("/login")
def login() -> ResponseType:
    """Handler for the login sequence"""
    clear_session_userid()
    redirect_uri = url_for("web.oauth2callback", _external=True)
    g = get_google_auth()
    return g.authorize_redirect(redirect_uri)


@web.route("/login_malstadur", methods=["POST"])
def login_malstadur() -> ResponseType:
    """User login from Málstaður by e-mail, using a JWT token
    to verify the user's identity"""
    # logging.info("login_malstadur invoked")
    clear_session_userid()
    rq = RequestData(request)
    # Obtain email from the request
    email = rq.get("email", "")
    if not email:
        return jsonify(status="invalid", message="No email provided"), 401
    nickname = rq.get("nickname", "")
    fullname = rq.get("fullname", "")
    # Obtain the JavaScript Web Token (JWT) from the request
    jwt = rq.get("token", "")
    if running_local and not jwt:
        # Shortcut for local development
        is_friend = True
        # Generate a default account id for the user, from a random UUID
        # This is only used if the given email doesn't exist already
        account = f"malstadur:{str(uuid.uuid4())}"
    else:
        # Normal production: must have a valid JWT
        if not jwt:
            return jsonify(status="invalid", message="No token provided"), 401
        # Decode the claims in the JWT, using the Málstaður secret
        expired, claims = verify_malstadur_token(jwt)
        if expired:
            return jsonify(status="expired", message="Token expired")
        if claims is None:
            return jsonify(status="invalid", message="Invalid token"), 401
        # Claims successfully extracted, which means that the token
        # is valid and not expired
        email_claim = claims.get("email", "")
        if not email_claim or email_claim != email:
            return jsonify(status="invalid", message="Mismatched email"), 401
        sub = claims.get("sub", "")
        if not sub:
            return jsonify(status="invalid", message="No sub identifier provided"), 401
        # Extract information about the user's subscription plan
        # and set the user's friendship status accordingly
        plan = claims.get("plan", "")
        is_friend = plan == "friend"
        # Create a unique account id for the user, from the sub claim.
        # We're careful to sanitize the user id so that it is Firebase-compatible.
        account = f"malstadur:{firebase_key(sub)}"
    # Find the user entity by email, or create a new user if it doesn't exist
    uld = User.login_by_email(email, account, nickname, fullname, is_friend)
    userid = uld["user_id"]
    # Create a Firebase custom token for the user
    token = firebase.create_custom_token(userid)
    sd = SessionDict(userid=userid, method="Malstadur")
    # Create a session cookie with the user id
    set_session_cookie(userid, sd=sd)
    return jsonify(dict(status="success", firebase_token=token, **uld))


@web.route("/login_error")
def login_error() -> ResponseType:
    """An error during login: probably cookies or popups are not allowed"""
    return render_template("login-error.html", user=None)


@web.route("/logout", methods=["GET"])
def logout() -> ResponseType:
    """Log the user out"""
    clear_session_userid()
    return redirect(url_for("web.greet"))


@web.route("/oauth2callback", methods=["GET"])
def oauth2callback() -> ResponseType:
    """The OAuth2 login flow GETs this callback when a user has
    signed in using a Google Account"""

    # Note that HTTP POSTs to /oauth2callback are handled in api.py

    if not login_user():
        return redirect(url_for("web.login_error"))
    main_url = url_for("web.page") if SINGLE_PAGE_UI else url_for("web.main")
    return redirect(main_url)


@web.route("/service-worker.js")
@max_age(seconds=1 * 60 * 60)  # Cache file for 1 hour
def service_worker() -> ResponseType:
    return send_from_directory(STATIC_FOLDER, "js/service-worker.js")


@web.route("/")
@auth_required()
def main() -> ResponseType:
    """Handler for the main (index) page"""
    if SINGLE_PAGE_UI:
        # Redirect to the single page UI
        return redirect(url_for("web.page"))

    user = current_user()
    assert user is not None

    # Initial tab to show, if any
    tab = request.args.get("tab", None)

    uid = user.id() or ""

    # Create a Firebase token for the logged-in user
    # to enable refreshing of the client page when
    # the user state changes (game moves made, challenges
    # issued or accepted, etc.)
    firebase_token = firebase.create_custom_token(uid)

    # Promotion display
    promo_to_show = promo_to_show_to_user(uid)

    # Get earlier challenge, move and wait notifications out of the way
    msg = {"challenge": None, "move": None, "wait": None}
    firebase.send_message(msg, "user", uid)

    return render_template(
        "main.html",
        user=user,
        tab=tab,
        firebase_token=firebase_token,
        promo=promo_to_show,
    )


@web.route("/cacheflush", methods=["GET", "POST"])
def cache_flush() -> ResponseType:
    """Flush the Redis cache"""
    headers: Dict[str, str] = cast(Any, request).headers
    task_queue_name = headers.get("X-AppEngine-QueueName", "")
    task_queue = task_queue_name != ""
    cloud_scheduler = request.environ.get("HTTP_X_CLOUDSCHEDULER", "") == "true"
    cron_job = headers.get("X-Appengine-Cron", "") == "true"
    if not any((task_queue, cloud_scheduler, cron_job, running_local)):
        # Only allow bona fide Google Cloud Scheduler or Task Queue requests
        return "Restricted URL", 403
    # Flush the cache
    memcache.flush()
    return "<html><body><p>Cache flushed</p></body></html>", 200


# We only enable the administration routes if running
# on a local development server, not on the production server

if running_local:
    import admin

    @web.route("/admin/usercount", methods=["POST"])
    def admin_usercount() -> ResponseType:
        # Be careful - this operation is EXTREMELY slow on Cloud Datastore
        return admin.admin_usercount()

    @web.route("/admin/userupdate", methods=["POST"])
    def admin_userupdate() -> ResponseType:
        return admin.admin_userupdate()

    @web.route("/admin/eloinit", methods=["GET"])
    def admin_eloinit() -> ResponseType:
        return admin.admin_eloinit()

    @web.route("/admin/gameupdate", methods=["POST"])
    def admin_gameupdate() -> ResponseType:
        return jsonify(ok=False, result="Not implemented")
        # return admin.admin_gameupdate()

    @web.route("/admin/setfriend", methods=["GET"])
    def admin_setfriend() -> ResponseType:
        return admin.admin_setfriend()

    @web.route("/admin/loadgame", methods=["POST"])
    def admin_loadgame() -> ResponseType:
        return admin.admin_loadgame()

    @web.route("/admin/loaduser", methods=["POST"])
    def admin_loaduser() -> ResponseType:
        return admin.admin_loaduser()

    @web.route("/admin/main")
    def admin_main() -> ResponseType:
        """Show main administration page"""
        return render_template("admin.html", user=None, project_id=PROJECT_ID)

    @web.route("/admin/exit")
    def admin_exit() -> ResponseType:
        """Exit the server process"""
        sys.exit(0)
        return "Exiting", 200


# noinspection PyUnusedLocal
# pylint: disable=unused-argument
@web.errorhandler(404)
def page_not_found(e: Union[int, Exception]) -> ResponseType:
    """Return a custom 404 error"""
    lang = request.accept_languages.best_match(("is", "en"), "en")
    if lang == "is":
        return "Þessi vefslóð er ekki rétt", 404
    return "This URL is not recognized", 404
