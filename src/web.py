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
import os

import sys
from typing import (
    Optional,
    Dict,
    Union,
    List,
    Any,
    Callable,
    cast,
)

import logging
import uuid

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
)
from basics import (
    SessionDict,
    UserIdDict,
    current_user,
    auth_required,
    get_google_auth,
    jsonify,
    session_data,
    session_user,
    set_session_cookie,
    clear_session_userid,
    RequestData,
    max_age,
)
from logic import promo_to_show_to_user
from skrafluser import User, UserLoginDict, verify_malstadur_token
import firebase
import billing
from cache import memcache


# Type definitions
RouteType = Callable[..., ResponseType]
UserPrefsType = Dict[str, Union[str, bool]]
GameList = List[Dict[str, Union[str, int, bool, Dict[str, bool]]]]

# Promotion parameters
# A promo check is done randomly, but on average every 1 out of N times
# _PROMO_FREQUENCY = 8
# _PROMO_COUNT = 2  # Max number of times that the same promo is displayed
# _PROMO_INTERVAL = timedelta(days=4)  # Min interval between promo displays

BASE_PATH = os.path.join(os.path.dirname(__file__), "..")
STATIC_FOLDER = os.path.join(BASE_PATH, "static")
TEMPLATE_FOLDER = os.path.join(BASE_PATH, "templates")

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
def friend() -> ResponseType:
    """HTML content of a friend (subscription) promotion dialog"""
    short_default_locale = DEFAULT_LOCALE.split("_")[0]  # Normally 'en' or 'is'
    locale = request.args.get("locale", short_default_locale)
    # !!! TODO: Make this work for all locales and screen sizes
    return render_locale_template("promo-friend-{0}.html", locale)


@web.route("/board")
def board() -> ResponseType:
    """The main game page"""
    # This is an artifact, needed only to allow url_for("web.board") to work.
    return ""


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
    VALID_PROMOS = {"friend", "krafla"}
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


@web.route("/rawhelp")
def rawhelp() -> ResponseType:
    """Return raw help page HTML. Authentication is not required."""

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
    )


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
        emailClaim = claims.get("email", "")
        if not emailClaim or emailClaim != email:
            return jsonify(status="invalid", message="Mismatched email"), 401
        # Extract information about the user's subscription plan
        # and set the user's friendship status accordingly
        plan = claims.get("plan", "")
        is_friend = plan == "friend"
        sub = claims.get("sub", "")
        if not sub:
            return jsonify(status="invalid", message="No sub identifier provided"), 401
        # Create a unique account id for the user, from the sub claim.
        # We're careful to sanitize the user id so that it is Firebase-compatible.
        account = f"malstadur:{firebase_key(sub)}"
    # Find the user record by email, or create a new user if it doesn't exist
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
    return redirect(url_for("web.page"))


@web.route("/service-worker.js")
@max_age(seconds=1 * 60 * 60)  # Cache file for 1 hour
def service_worker() -> ResponseType:
    return send_from_directory(STATIC_FOLDER, "service-worker.js")


@web.route("/")
@auth_required()
def main() -> ResponseType:
    """Handler for the main (index) page"""
    # Redirect to the single page UI
    return redirect(url_for("web.page"))


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
