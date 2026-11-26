"""

Web server for netskrafl.is

Copyright © 2025 Miðeind ehf.
Original author: Vilhjálmur Þorsteinsson

The Creative Commons Attribution-NonCommercial 4.0
International Public License (CC-BY-NC 4.0) applies to this software.
For further information, see https://github.com/mideind/Netskrafl


This module implements the web routes: the built-in web UI and the
login sequences, along with a few JSON entry points that have their
home here for historical reasons.

The users' clients are the Explo app and the Netskrafl client that is
embedded in Málstaður. The built-in web UI (the single-page client in
static/src) is a development client, served only where the SINGLE_PAGE
environment variable is set to TRUE (the staging app and local
development servers). Elsewhere its routes answer HTTP 404, and the
root and greeting pages redirect to HOME_REDIRECT_URL, if that is set.

Most JSON-based client API entrypoints are implemented in api.py.

"""

from __future__ import annotations

from typing import (
    Optional,
    Dict,
    Union,
    Any,
    cast,
)

import os
import sys
import logging
import uuid
from datetime import UTC, datetime
from functools import wraps

from flask import (
    Blueprint,
    abort,
    render_template,
    redirect,
    url_for,
    request,
)
from flask.globals import current_app
from flask.typing import ResponseReturnValue
from authlib.integrations.base_client.errors import OAuthError

from auth import firebase_key
from config import (
    DEFAULT_LOCALE,
    running_local,
    VALID_ISSUERS,
    ResponseType,
    RouteType,
    Error,
)
from basics import (
    SessionDict,
    UserIdDict,
    current_user,
    auth_required,
    current_user_id,
    get_google_auth,
    is_cron_request,
    jsonify,
    session_data,
    session_user,
    set_session_cookie,
    clear_session_userid,
    RequestData,
)
from logic import promo_to_show_to_user
from skrafldb import PrefsDict, ZombieModel, on_commit
from skraflgame import Game
from applog import note_request
from skrafluser import (
    User,
    UserLoginDict,
    log_fields,
    verify_malstadur_token,
)
import firebase
import billing
from cache import memcache
from languages import current_board_type


BASE_PATH = os.path.join(os.path.dirname(__file__), "..")
STATIC_FOLDER = os.path.join(BASE_PATH, "static")
TEMPLATE_FOLDER = os.path.join(BASE_PATH, "templates")

# True if this deployment serves the built-in web UI. It is a development
# client, so this is set on the staging app and on local development
# servers only, never on the production backends.
SINGLE_PAGE_UI = os.environ.get("SINGLE_PAGE", "FALSE").upper() == "TRUE"

# Where a browser that opens the root or the greeting page is sent when
# the web UI is not served (for Netskrafl, its home within Málstaður).
# If this is not set, those pages answer HTTP 404.
HOME_REDIRECT_URL = os.environ.get("HOME_REDIRECT_URL", "").strip()

# Register the Flask blueprint for the web routes
web = web_blueprint = Blueprint(
    "web", __name__, static_folder=STATIC_FOLDER, template_folder=TEMPLATE_FOLDER
)


def web_ui_route(func: RouteType) -> RouteType:
    """Decorator for the routes of the built-in web UI: they exist
    only in a deployment that serves the UI, and are unknown URLs
    (HTTP 404) elsewhere. Apply it below @web.route() and above
    @auth_required(), so that the check comes before the login check."""

    @wraps(func)
    def route(*args: Any, **kwargs: Any) -> ResponseReturnValue:
        if not SINGLE_PAGE_UI:
            abort(404)
        return func(*args, **kwargs)

    return route


def home_redirect() -> ResponseType:
    """Answer a request for the root or the greeting page in a deployment
    that does not serve the web UI: send the browser to the product's
    home, if there is one"""
    if HOME_REDIRECT_URL:
        return redirect(HOME_REDIRECT_URL)
    abort(404)


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
@web_ui_route
def friend() -> ResponseType:
    """Return the HTML content of the friend (subscription) promotion dialog"""
    locale = request.args.get("locale", DEFAULT_LOCALE)
    return render_locale_template("promo-friend-{0}.html", locale)


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

    # Deferred until the new game is committed; see skrafldb.on_commit()
    on_commit(lambda: firebase.send_message(msg))

    # Return the uuid of the new game
    return jsonify(ok=True, uuid=game.id())


@web.route("/promo", methods=["POST"])
@web_ui_route
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


@web.route("/rawhelp")
@web_ui_route
@auth_required()
def rawhelp() -> ResponseType:
    """Return raw help page HTML."""

    user = session_user()
    locale = request.args.get("locale", DEFAULT_LOCALE)
    version = request.args.get("version", "")

    def override_url_for(endpoint: str, **values: Any) -> str:
        """Convert the links in the help text to actions in the web UI"""
        # The help templates link to these three names, which were pages
        # of the former server-rendered UI and are not routes any more
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


@web.route("/page")
@web_ui_route
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
        running_local=running_local,
        promo=promo_to_show,
    )


@web.route("/greet")
def greet() -> ResponseType:
    """Handler for the greeting page, which is the web UI's login page"""
    if not SINGLE_PAGE_UI:
        return home_redirect()
    return render_template("login.html", user=None)


@web.route("/login")
@web_ui_route
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
    rq = RequestData(request)
    # Obtain email from the request
    email = rq.get("email", "")
    if not email:
        return jsonify(status="invalid", message="No email provided"), 401
    nickname = rq.get("nickname", "")
    fullname = rq.get("fullname", "")
    # Check if the client supports Bearer token authentication
    bearer_auth = rq.get_bool("bearer_auth", False)
    if not bearer_auth:
        # Legacy client: clear any existing session cookie
        clear_session_userid()
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
        # The outcome of every login attempt is logged with the identity
        # it was made for, so that an individual user's login problems
        # can be traced. (The e-mail is unverified when the token is bad.)
        expired, claims = verify_malstadur_token(jwt)
        if expired:
            logging.info(
                f"Málstaður login: token expired for {email}",
                extra=log_fields("malstadur_login", outcome="expired", email=email),
            )
            return jsonify(status="expired", message="Token expired")
        if claims is None:
            logging.warning(
                f"Málstaður login: invalid token for {email}",
                extra=log_fields("malstadur_login", outcome="invalid", email=email),
            )
            return jsonify(status="invalid", message="Invalid token"), 401
        # Claims successfully extracted, which means that the token
        # is valid and not expired
        email_claim = claims.get("email", "")
        if not email_claim or email_claim != email:
            logging.warning(
                f"Málstaður login: e-mail {email} does not match "
                f"token e-mail {email_claim or '[none]'}",
                extra=log_fields(
                    "malstadur_login",
                    outcome="email_mismatch",
                    email=email,
                    token_email=email_claim,
                ),
            )
            return jsonify(status="invalid", message="Mismatched email"), 401
        sub = claims.get("sub", "")
        if not sub:
            logging.warning(
                f"Málstaður login: no sub claim in token for {email}",
                extra=log_fields("malstadur_login", outcome="no_sub", email=email),
            )
            return jsonify(status="invalid", message="No sub identifier provided"), 401
        # Extract information about the user's subscription plan
        # and set the user's friendship status accordingly
        plan = claims.get("plan", "")
        is_friend = plan == "friend"
        # Create a unique account id for the user, from the sub claim.
        # We're careful to sanitize the user id so that it is Firebase-compatible.
        account = f"malstadur:{firebase_key(sub)}"
    # Find the user entity by email, or create a new user if it doesn't exist
    try:
        uld = User.login_by_email(email, account, nickname, fullname, is_friend)
    except Exception:
        logging.exception(
            f"Málstaður login: failed for {email}",
            extra=log_fields("malstadur_login", outcome="error", email=email),
        )
        raise
    userid = uld["user_id"]
    # Create a Firebase custom token for the user. The API works without
    # Firebase (the client only loses real-time updates, and asks for a new
    # token via /firebase_token later), so a failure here, which has been
    # seen as transient connection resets, does not fail the login.
    try:
        token = firebase.create_custom_token(userid)
    except Exception:
        logging.exception(
            f"Málstaður login: no Firebase token for user {userid}",
            extra=log_fields(
                "malstadur_login", outcome="no_firebase_token", user_id=userid
            ),
        )
        token = ""
    # The log entry says what the host's token claimed (plan) and what the
    # user ended up with (friend, has_paid), so that a subscription that
    # does not take effect can be seen here
    prefs = uld.get("prefs") or {}
    token_plan = "friend" if is_friend else "none"
    friend = bool(prefs.get("friend", False))
    has_paid = bool(prefs.get("haspaid", False))
    logging.info(
        f"Málstaður login: user {userid} logged in"
        f"{' (new user)' if uld['new'] else ''}"
        f", token plan {token_plan}, has paid {has_paid}",
        extra=log_fields(
            "malstadur_login",
            outcome="success",
            user_id=userid,
            new_user=uld["new"],
            firebase_token=bool(token),
            token_plan=token_plan,
            friend=friend,
            has_paid=has_paid,
        ),
    )
    note_request(user_id=userid)
    if not bearer_auth:
        # Legacy client: set a session cookie for backwards compatibility.
        # Note that this may not work for cross-origin requests due to
        # SameSite=Lax cookie restrictions, but we provide it anyway for
        # same-origin or older client scenarios.
        sd = SessionDict(userid=userid, method="Malstadur")
        set_session_cookie(userid, sd=sd)
    # An Explo token is returned via the UserLoginDict. Clients that set
    # bearer_auth=true are expected to pass it back in subsequent requests
    # in an Authorization: Bearer header.
    return jsonify(dict(status="success", firebase_token=token, **uld))


@web.route("/login_error")
@web_ui_route
def login_error() -> ResponseType:
    """An error during login: probably cookies or popups are not allowed"""
    return render_template("login-error.html", user=None)


@web.route("/logout", methods=["GET"])
def logout() -> ResponseType:
    """Log the user out"""
    clear_session_userid()
    return redirect(url_for("web.greet"))


@web.route("/oauth2callback", methods=["GET"])
@web_ui_route
def oauth2callback() -> ResponseType:
    """The OAuth2 login flow GETs this callback when a user has
    signed in using a Google Account"""

    # Note that HTTP POSTs to /oauth2callback are handled in api.py

    if not login_user():
        return redirect(url_for("web.login_error"))
    return redirect(url_for("web.page"))


@web.route("/")
def main() -> ResponseType:
    """Handler for the root URL"""
    if not SINGLE_PAGE_UI:
        return home_redirect()
    # Go to the single-page web UI (or to its login page,
    # if the user is not logged in)
    return redirect(url_for("web.page"))


@web.route("/cacheflush", methods=["GET", "POST"])
def cache_flush() -> ResponseType:
    """Flush the Redis cache"""
    if not is_cron_request():
        # Only allow authorized scheduler requests
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
