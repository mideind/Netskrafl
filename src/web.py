"""

    Web server for netskrafl.is

    Copyright (C) 2021 Miðeind ehf.
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

import logging

from flask import (
    Blueprint,
    render_template,
    send_from_directory,
    redirect,
    url_for,
    request,
    session,
)
from flask.wrappers import Response
from flask.globals import current_app
from werkzeug.wrappers import Response as WerkzeugResponse
from authlib.integrations.base_client.errors import MismatchingStateError  # type: ignore

from config import running_local, VALID_ISSUERS
from basics import (
    UserIdDict,
    current_user,
    auth_required,
    get_google_auth,
    session_idinfo,
    session_user,
    set_session_userid,
    clear_session_userid,
    RequestData,
    max_age,
)
from skrafluser import User, UserLoginDict

# from skrafldb import PromoModel
import firebase
import billing
from cache import memcache
import skraflstats


# Type definitions
ResponseType = Union[str, Response, WerkzeugResponse, Tuple[str, int]]
RouteType = Callable[..., ResponseType]
UserPrefsType = Dict[str, Union[str, bool]]
GameList = List[Dict[str, Union[str, int, bool, Dict[str, bool]]]]

# Promotion parameters
# A promo check is done randomly, but on average every 1 out of N times
# _PROMO_FREQUENCY = 8
# _PROMO_COUNT = 2  # Max number of times that the same promo is displayed
# _PROMO_INTERVAL = timedelta(days=4)  # Min interval between promo displays

STATIC_FOLDER = "../static"
TEMPLATE_FOLDER = "../templates"

# Register the Flask blueprint for the web routes
web_blueprint = Blueprint(
    "web", __name__, static_folder=STATIC_FOLDER, template_folder=TEMPLATE_FOLDER
)
# The following cast can be removed once Flask's typing becomes
# more robust and/or compatible with Pylance
web = cast(Any, web_blueprint)


def login_user() -> bool:
    """ Log in a user after she is authenticated via OAuth """
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
        token: Dict[str, Union[str, int]] = g.authorize_access_token()
        if "id_token" in token:
            idinfo = g.parse_id_token(token)
            if idinfo is None:
                return False
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
        else:
            pass
            # account = g.userinfo()
        if idinfo and account:
            # Attempt to find an associated user record in the datastore,
            # or create a fresh user record if not found
            uld = User.login_by_account(account, name or "", email or "", image or "")
            userid = uld["user_id"]
            # Save the stuff we want to keep around
            # in the user session
            idinfo["method"] = "Google"
            idinfo["account"] = uld["account"]
            idinfo["new"] = uld["new"]
            idinfo["locale"] = uld["locale"]
    except (KeyError, ValueError, MismatchingStateError) as e:
        # Something is wrong: we're not getting the same (random) state string back
        # that we originally sent to the OAuth2 provider
        logging.warning(f"login_user(): {e}")
        userid = None

    if not userid or idinfo is None or uld is None:
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


def render_locale_template(template: str, locale: str, **kwargs: Any) -> ResponseType:
    """ Render a template for a given locale. The template file name should contain
        a {0} format placeholder for the locale. """
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
    """ HTML content of a friend (subscription) promotion dialog """
    locale = request.args.get("locale", "is_IS")
    return render_locale_template("promo-friend-{0}", locale)


@web.route("/board")
def board() -> ResponseType:
    """ The main game page """
    # This is an artifact, needed only to allow url_for("web.board") to work.
    return ""


@web.route("/promo", methods=["POST"])
def promo() -> ResponseType:
    """ Return promotional HTML corresponding to a given key (category) """
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
    """ Sign up as a friend, enter card info, etc. """
    return render_template("signup.html", user=current_user())


@web.route("/skilmalar", methods=["GET"])
def skilmalar() -> ResponseType:
    """ Terms & conditions """
    return render_template("skilmalar.html")


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
    """ Return raw help page HTML. Authentication is not required. """

    locale = request.args.get("locale", "is_IS")

    def override_url_for(endpoint: str, **values: Any) -> str:
        """ Convert URLs from old-format plain ones to single-page fancy ones """
        if endpoint in {"web.twoletter", "web.newbag", "web.userprefs"}:
            # Insert special token that will be caught by client-side
            # code and converted to an action in the single-page UI
            return "$$" + endpoint.split(".")[-1] + "$$"
        return url_for(endpoint, **values)

    return render_locale_template("rawhelp-{0}.html", locale, url_for=override_url_for)


@web.route("/page")
@auth_required()
def page() -> ResponseType:
    """ Show single-page UI """
    user = current_user()
    assert user is not None
    uid = user.id() or ""
    idinfo = session_idinfo()
    firebase_token = firebase.create_custom_token(uid)
    # We return information about the login method to the client,
    # as well as whether this is a new user signing in for the first time
    return render_template(
        "page.html",
        user=user,
        firebase_token=firebase_token,
        method="" if idinfo is None else idinfo.get("method", ""),
        new=False if idinfo is None else idinfo.get("new", False),
    )


@web.route("/greet")
def greet() -> ResponseType:
    """ Handler for the greeting page """
    return render_template("login-explo.html")


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
    return redirect(url_for("web.page"))


@web.route("/service-worker.js")
@max_age(seconds=1 * 60 * 60)  # Cache file for 1 hour
def service_worker() -> ResponseType:
    return send_from_directory(STATIC_FOLDER, "service-worker.js")


@web.route("/")
@auth_required()
def main() -> ResponseType:
    """ Handler for the main (index) page """
    # Redirect to the single page UI
    return redirect(url_for("web.page"))


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


@web.route("/cache/flush", methods=["GET", "POST"])
def cache_flush() -> ResponseType:
    """ Flush the Redis cache """
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
    lang = request.accept_languages.best_match(("is", "en"), "en")
    if lang == "is":
        return "Þessi vefslóð er ekki rétt", 404
    return "This URL is not recognized", 404

