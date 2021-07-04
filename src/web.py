"""

    Web server for netskrafl.is

    Copyright (C) 2021 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The GNU Affero General Public License, version 3, applies to this software.
    For further information, see https://github.com/mideind/Netskrafl


    This module implements web routes, i.e. URLs that return
    responsive HTML/CSS/JScript content.

    JSON-based client API entrypoints are implemented in api.py.

"""

from __future__ import annotations

from typing import (
    Optional,
    Dict,
    Union,
    List,
    Any,
    Callable,
    Tuple,
    cast,
)

import os
import logging
import random

from datetime import datetime, timedelta

from flask import (
    Blueprint,
    render_template,
    send_from_directory,
    redirect,
    url_for,
    request,
    Response,
    session,
)
from werkzeug.urls import url_parse
from werkzeug.wrappers import Response as WerkzeugResponse
from authlib.integrations.base_client.errors import MismatchingStateError  # type: ignore

from basics import (
    current_user,
    auth_required,
    get_google_auth,
    session_user,
    set_session_userid,
    clear_session_userid,
    RequestData,
    max_age,
    running_local,
    VALID_ISSUERS,
)
from api import UserForm, autoplayer_lock
from languages import (
    current_board_type,
    set_game_locale,
)
from skraflplayer import AutoPlayer, MoveList
from skraflgame import User, Game
from skrafldb import (
    ZombieModel,
    PromoModel,
    PrefsDict,
)
import billing
import firebase
from cache import memcache
import skraflstats


# Type definitions
ResponseType = Union[str, Response, WerkzeugResponse, Tuple[str, int]]
RouteType = Callable[..., ResponseType]
UserPrefsType = Dict[str, Union[str, bool]]
GameList = List[Dict[str, Union[str, int, bool, Dict[str, bool]]]]

# Promotion parameters
# A promo check is done randomly, but on average every 1 out of N times
_PROMO_FREQUENCY = 8
_PROMO_COUNT = 2  # Max number of times that the same promo is displayed
_PROMO_INTERVAL = timedelta(days=4)  # Min interval between promo displays

# Set to True to make the single-page UI the default
_SINGLE_PAGE_UI = os.environ.get("SINGLE_PAGE", "false").lower() in {
    "true",
    "yes",
    "on",
    "1",
}

# Register the Flask blueprint for the web routes
web_blueprint = Blueprint(
    'web', __name__, static_folder="../static", template_folder="../templates"
)
# The following cast can be removed once Flask's typing becomes
# more robust and/or compatible with Pylance
web = cast(Any, web_blueprint)


def login_user() -> bool:
    """ Log in a user after she is authenticated via OAuth """
    # This function is called from web.oauth2callback()
    # Note that a similar function is found in api.py
    account: Optional[str] = None
    userid: Optional[str] = None
    idinfo: Dict[str, Any] = dict()
    email: Optional[str] = None
    image: Optional[str] = None
    name: Optional[str] = None
    g = get_google_auth()
    try:
        token: str = g.authorize_access_token()
        idinfo = g.parse_id_token(token)
        issuer = idinfo.get("iss", "")
        if issuer not in VALID_ISSUERS:
            logging.error("Unknown OAuth2 token issuer: " + (issuer or "[None]"))
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
            # Attempt to find an associated user record in the datastore,
            # or create a fresh user record if not found
            userid = User.login_by_account(
                account, name or "", email or "", image or ""
            )
    except (KeyError, ValueError, MismatchingStateError) as e:
        # Something is wrong: we're not getting the same (random) state string back
        # that we originally sent to the OAuth2 provider
        logging.warning(f"login_user(): {e}")
        userid = None

    if not userid:
        # Unable to obtain a properly authenticated user id for some reason
        return False

    # Authentication complete; user id obtained
    set_session_userid(userid, idinfo)

    if running_local:
        logging.info(
            "login_user() successfully recognized "
            "account {0} userid {1} email {2} name '{3}'".format(
                account, userid, email, name
            )
        )
    return True


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

    game: Optional[Game] = None
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

    best_moves: Optional[MoveList] = None
    if game.allows_best_moves():

        # Serialize access to the following section
        with autoplayer_lock:

            # Show best moves if available and it is proper to do so (i.e. the game is finished)
            apl = AutoPlayer(state)
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


@web.route("/userprefs", methods=["GET", "POST"])
@auth_required()
def userprefs():
    """ Handler for the user preferences page """

    user = current_user()
    assert user is not None

    uf = UserForm()
    err: Dict[str, str] = dict()

    # The URL to go back to, if not main.html
    from_url = request.args.get("from", None)

    # Validate that 'from_url' does not redirect to an external site.
    # If 'url_parse(from_url).netloc' is empty, that means from_url is a relative
    # link and is safe. If .netloc is populated, it might be external.
    if from_url and cast(Any, url_parse(from_url)).netloc != "":
        from_url = None

    method: str = cast(Any, request).method
    if method == "GET":
        # Entering the form for the first time: load the user data
        uf.init_from_user(user)
    elif method == "POST":
        # Attempting to submit modified data: retrieve it and validate
        uf.init_from_form(request.form)
        err = uf.validate()
        if not err:
            # All is fine: store the data back in the user entity
            uf.store(user)
            return redirect(from_url or url_for("web.main"))

    # Render the form with the current data and error messages, if any
    return render_template("userprefs.html", uf=uf, err=err, from_url=from_url)


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
        # !!! TODO: Update for singlepage
        # Go directly to opponents tab
        return redirect(url_for("web.main", tab="2"))

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
    uid = user.id() or ""
    msg = {
        "user/" + opp: {"challenge": datetime.utcnow().isoformat()},
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

    prefs: Optional[PrefsDict] = None

    if opp.startswith("robot-"):
        # Start a new game against an autoplayer (robot)
        robot_level = int(opp[6:])
        # Play the game with the new bag if the user prefers it
        prefs = dict(newbag=user.new_bag(), locale=user.locale,)
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
    msg: Dict[str, Any] = {"user/" + opp + "/move": datetime.utcnow().isoformat()}

    # If this is a timed game, notify the waiting party
    if prefs and cast(int, prefs.get("duration", 0)) > 0:
        msg["user/" + opp + "/wait/" + uid] = {"game": game.id()}

    firebase.send_message(msg)

    # Go to the game page
    return redirect(url_for("web.board", game=game.id()))


@web.route("/board")
def board() -> ResponseType:
    """ The main game page """

    # Note that authentication is not required to access this page

    uuid = request.args.get("game", None)
    # Requesting a look at a newly finished game
    zombie = request.args.get("zombie", None)
    og: Optional[int] = None
    try:
        # If the og argument is present, it indicates that OpenGraph data
        # should be included in the page header, from the point of view of
        # the player that the argument represents (i.e. og=0 or og=1).
        # If og=-1, OpenGraph data should be included but from a neutral
        # (third party) point of view.
        ogstr = request.args.get("og", None)
        if ogstr is not None:
            # This should be a player index: -1 (third party), 0 or 1
            og = int(ogstr)  # May throw an exception
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

    ogd = None  # OpenGraph data
    if og is not None and is_over:
        # This game is a valid and visible OpenGraph object
        # Calculate the OpenGraph stuff to be included in the page header
        pix = 0 if og < 0 else og  # Player indexing
        sc = game.final_scores()
        winner = game.winning_player()  # -1 if draw
        bingoes = game.bingoes()
        ogd = dict(
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
        billing.cancel_friend(user)
    return render_template("friend.html", user=user, action=action)


@web.route("/promo", methods=["POST"])
def promo() -> ResponseType:
    """ Return promotional HTML corresponding to a given key (category) """
    user = session_user()
    if user is None:
        return "<p>Notandi er ekki innskráður</p>"  # Unauthorized
    rq = RequestData(request)
    key = rq.get("key", "")
    VALID_PROMOS = {"friend", "krafla"}
    if key not in VALID_PROMOS:
        key = "error"
    return render_template("promo-" + key + ".html", user=user)


@web.route("/signup", methods=["GET"])
@auth_required()
def signup() -> ResponseType:
    """ Sign up as a friend, enter card info, etc. """
    return render_template("signup.html", user=current_user())


@web.route("/skilmalar", methods=["GET"])
@auth_required()
def skilmalar() -> ResponseType:
    """ Conditions """
    return render_template("skilmalar.html", user=current_user())


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
def rawhelp() -> ResponseType:
    """ Return raw help page HTML. Authentication is not required. """

    def override_url_for(endpoint: str, **values: Any) -> str:
        """ Convert URLs from old-format plain ones to single-page fancy ones """
        if endpoint in {"web.twoletter", "web.newbag", "web.userprefs"}:
            # Insert special token that will be caught by client-side
            # code and converted to an action in the single-page UI
            return "$$" + endpoint.split(".")[-1] + "$$"
        return url_for(endpoint, **values)

    return render_template("rawhelp.html", url_for=override_url_for)


@web.route("/twoletter")
def twoletter() -> ResponseType:
    """ Show help page. Authentication is not required. """
    user = session_user()
    return render_template("nshelp.html", user=user, tab="twoletter")


@web.route("/faq")
def faq() -> ResponseType:
    """ Show help page. Authentication is not required. """
    user = session_user()
    # We tolerate a null (not logged in) user here
    return render_template("nshelp.html", user=user, tab="faq")


@web.route("/page")
@auth_required()
def page() -> ResponseType:
    """ Show single-page UI test """
    user = current_user()
    assert user is not None
    uid = user.id() or ""
    firebase_token = firebase.create_custom_token(uid)
    return render_template("page.html", user=user, firebase_token=firebase_token)


@web.route("/newbag")
def newbag() -> ResponseType:
    """ Show help page. Authentication is not required. """
    user = session_user()
    # We tolerate a null (not logged in) user here
    return render_template("nshelp.html", user=user, tab="newbag")


@web.route("/greet")
def greet() -> ResponseType:
    """ Handler for the greeting page """
    return render_template("login.html", single_page=_SINGLE_PAGE_UI)


@web.route("/login")
def login() -> ResponseType:
    """ Handler for the login sequence """
    cast(Any, session).pop("userid", None)
    cast(Any, session).pop("user", None)
    redirect_uri = url_for("web.oauth2callback", _external=True)
    g = get_google_auth()
    return g.authorize_redirect(redirect_uri)


@web.route("/login_error")
def login_error() -> ResponseType:
    """ An error during login: probably cookies or popups are not allowed """
    return render_template("login-error.html")


@web.route("/logout", methods=["GET"])
def logout() -> ResponseType:
    """ Log the user out """
    clear_session_userid()
    return redirect(url_for("web.greet"))


@web.route("/oauth2callback", methods=["GET"])
def oauth2callback() -> ResponseType:
    """The OAuth2 login flow GETs this callback when a user has
    signed in using a Google Account"""

    # Note that HTTP POSTs to /oauth2callback are handled in api.py

    if not login_user():
        return redirect(url_for("web.login_error"))
    main_url = url_for("web.page") if _SINGLE_PAGE_UI else url_for("web.main")
    return redirect(main_url)


@web.route("/service-worker.js")
@max_age(seconds=1 * 60 * 60)  # Cache file for 1 hour
def service_worker() -> ResponseType:
    return send_from_directory("../static", "service-worker.js")


@web.route("/")
@auth_required()
def main() -> ResponseType:
    """ Handler for the main (index) page """

    if _SINGLE_PAGE_UI:
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

    # Promotion display logic
    promo_to_show = None
    promos: List[datetime] = []
    if random.randint(1, _PROMO_FREQUENCY) == 1:
        # Once every N times, check whether this user may be due for
        # a promotion display

        # promo = 'krafla' # Un-comment this to enable promo

        # The list_promotions call yields a list of timestamps
        if promo_to_show:
            promos = sorted(list(PromoModel.list_promotions(uid, promo_to_show)))
            now = datetime.utcnow()
            if len(promos) >= _PROMO_COUNT:
                # Already seen too many of these
                promo_to_show = None
            elif promos and (now - promos[-1] < _PROMO_INTERVAL):
                # Less than one interval since last promo was displayed:
                # don't display this one
                promo_to_show = None

    if promo_to_show:
        # Note the fact that we have displayed this promotion to this user
        logging.info(
            "Displaying promo {1} to user {0} who has already seen it {2} times".format(
                uid, promo_to_show, len(promos)
            )
        )
        PromoModel.add_promotion(uid, promo_to_show)

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


# Cloud Scheduler routes - requests are only accepted when originated
# by the Google Cloud Scheduler


@web.route("/stats/run", methods=["GET", "POST"])
def stats_run() -> ResponseType:
    """ Start a task to calculate Elo points for games """
    headers: Dict[str, str] = cast(Any, request).headers
    task_queue_name = headers.get("X-AppEngine-QueueName", "")
    task_queue = task_queue_name != ""
    cloud_scheduler = request.environ.get("HTTP_X_CLOUDSCHEDULER", "") == "true"
    cron_job = headers.get("X-Appengine-Cron", "") == "true"
    if not any((task_queue, cloud_scheduler, cron_job, running_local)):
        # Only allow bona fide Google Cloud Scheduler or Task Queue requests
        return "Restricted URL", 403
    wait = True
    if cloud_scheduler:
        logging.info("Running stats from cloud scheduler")
        # Run Cloud Scheduler tasks asynchronously
        wait = False
    elif task_queue:
        logging.info(f"Running stats from queue {task_queue_name}")
    elif cron_job:
        logging.info("Running stats from cron job")
    return skraflstats.run(request, wait=wait)


@web.route("/stats/ratings", methods=["GET", "POST"])
def stats_ratings() -> ResponseType:
    """ Start a task to calculate top Elo rankings """
    headers: Dict[str, str] = cast(Any, request).headers
    task_queue_name = headers.get("X-AppEngine-QueueName", "")
    task_queue = task_queue_name != ""
    cloud_scheduler = request.environ.get("HTTP_X_CLOUDSCHEDULER", "") == "true"
    cron_job = headers.get("X-Appengine-Cron", "") == "true"
    if not any((task_queue, cloud_scheduler, cron_job, running_local)):
        # Only allow bona fide Google Cloud Scheduler or Task Queue requests
        return "Restricted URL", 403
    wait = True
    if cloud_scheduler:
        logging.info("Running ratings from cloud scheduler")
        # Run Cloud Scheduler tasks asynchronously
        wait = False
    elif task_queue:
        logging.info(f"Running ratings from queue {task_queue_name}")
    elif cron_job:
        logging.info("Running ratings from cron job")
    result, status = skraflstats.ratings(request, wait=wait)
    if status == 200:
        # New ratings: ensure that old ones are deleted from cache
        memcache.delete("all", namespace="rating")
        memcache.delete("human", namespace="rating")
    return result, status


# We only enable the administration routes if running
# on a local development server, not on the production server

if running_local:

    import admin

    @web.route("/admin/usercount", methods=["POST"])
    def admin_usercount() -> ResponseType:
        # Be careful - this operation is EXTREMELY slow on Cloud Datastore
        return admin.admin_usercount()

    @web.route("/admin/userupdate", methods=["GET"])
    def admin_userupdate() -> ResponseType:
        return admin.admin_userupdate()

    @web.route("/admin/setfriend", methods=["GET"])
    def admin_setfriend() -> ResponseType:
        return admin.admin_setfriend()

    @web.route("/admin/loadgame", methods=["POST"])
    def admin_loadgame() -> ResponseType:
        return admin.admin_loadgame()

    @web.route("/admin/main")
    def admin_main() -> ResponseType:
        """ Show main administration page """
        return render_template("admin.html")


# noinspection PyUnusedLocal
# pylint: disable=unused-argument
@web.errorhandler(404)
def page_not_found(e: Union[int, Exception]) -> ResponseType:
    """ Return a custom 404 error """
    return "Þessi vefslóð er ekki rétt", 404

