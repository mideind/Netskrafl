"""

    Web server for netskrafl.is

    Copyright (C) 2021 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl


    This module defines a number of basic entities that are used and shared
    by the main.py, api.py and web.py modules.

"""

from __future__ import annotations

from typing import (
    Literal,
    Optional,
    Dict,
    TypedDict,
    Union,
    List,
    Any,
    TypeVar,
    Callable,
    Tuple,
    cast,
    overload,
)

import os
from functools import wraps

from flask import (
    Flask,
    redirect,
    jsonify as flask_jsonify,
    url_for,
    request,
    make_response,
    g,
    session,
)
from flask.wrappers import Request, Response
from werkzeug.wrappers import Response as WerkzeugResponse
from authlib.integrations.flask_client import OAuth  # type: ignore

from languages import set_locale
from skrafluser import User
from skrafldb import Client

# Type definitions
T = TypeVar("T")
ResponseType = Union[str, Response, WerkzeugResponse, Tuple[str, int]]
RouteType = Callable[..., ResponseType]

class UserIdDict(TypedDict):
    iss: str
    sub: str
    name: str
    picture: str
    email: str

# Are we running in a local development environment or on a GAE server?
running_local: bool = os.environ.get("SERVER_SOFTWARE", "").startswith("Development")
# Set SERVER_HOST to 0.0.0.0 to accept HTTP connections from the outside
host: str = os.environ.get("SERVER_HOST", "127.0.0.1")
port: str = os.environ.get("SERVER_PORT", "8080")

# App Engine (and Firebase) project id
PROJECT_ID = os.environ.get("PROJECT_ID", "")
assert PROJECT_ID, "PROJECT_ID environment variable not set"

# client_id and client_secret for Google Sign-In
CLIENT_ID = os.environ.get("CLIENT_ID", "")
CLIENT_SECRET_FILE = {
    "netskrafl": "client_secret.txt",
    "explo-dev": "client_secret_explo.txt",
}.get(PROJECT_ID, "client_secret.txt")

# Read client secret key from file
with open(os.path.abspath(os.path.join("resources", CLIENT_SECRET_FILE)), "r") as f_txt:
    CLIENT_SECRET = f_txt.read().strip()

assert CLIENT_ID, "CLIENT_ID environment variable not set"
assert CLIENT_SECRET, "CLIENT_SECRET environment variable not set"

# Facebook app token, for login verification calls to the graph API
FACEBOOK_APP_SECRET = os.environ.get("FACEBOOK_APP_SECRET", "")
FACEBOOK_APP_ID = os.environ.get("FACEBOOK_APP_ID", "")
assert FACEBOOK_APP_SECRET, "FACEBOOK_APP_SECRET environment variable not set"
assert FACEBOOK_APP_ID, "FACEBOOK_APP_ID environment variable not set"

# Firebase configuration
FIREBASE_API_KEY = os.environ.get("FIREBASE_API_KEY", "")
FIREBASE_SENDER_ID = os.environ.get("FIREBASE_SENDER_ID", "")
FIREBASE_DB_URL = os.environ.get("FIREBASE_DB_URL", "")
FIREBASE_APP_ID = os.environ.get("FIREBASE_APP_ID", "")

assert FIREBASE_DB_URL, "FIREBASE_DB_URL environment variable not set"
assert FIREBASE_API_KEY, "FIREBASE_API_KEY environment variable not set"
assert FIREBASE_SENDER_ID, "FIREBASE_SENDER_ID environment variable not set"
assert FIREBASE_APP_ID, "FIREBASE_APP_ID environment variable not set"

# Valid token issuers for OAuth2 login
VALID_ISSUERS = frozenset(("accounts.google.com", "https://accounts.google.com"))


# Type annotation wrapper for flask.jsonify()
def jsonify(*args: Any, **kwargs: Any) -> str:
    return cast(str, flask_jsonify(*args, **kwargs))


def ndb_wsgi_middleware(wsgi_app: Any) -> Callable[[Any, Any], Any]:
    """ Returns a wrapper for the original WSGI app """

    def middleware(environ: Any, start_response: Any) -> Any:
        """ Wraps the original WSGI app """
        with Client.get_context():
            return wsgi_app(environ, start_response)

    return middleware


def max_age(seconds: int) -> Callable[[RouteType], RouteType]:
    """ Caching decorator for Flask - augments response
        with a max-age cache header """

    def decorator(f: RouteType) -> RouteType:
        @wraps(f)
        def decorated_function(*args: Any, **kwargs: Any) -> ResponseType:
            resp = f(*args, **kwargs)
            if not isinstance(resp, Response):
                resp = make_response(resp)
            cast(Any, resp).cache_control.max_age = seconds
            return resp

        return decorated_function

    return decorator


# Module-scope OAuth instance,
# only used by init_oauth() and get_google_auth()
_oauth: Optional[OAuth] = None


def init_oauth(app: Flask) -> None:
    """ Initialize the OAuth wrapper """
    OAUTH_CONF_URL = "https://accounts.google.com/.well-known/openid-configuration"
    global _oauth
    _oauth = OAuth(app)
    cast(Any, _oauth).register(
        name="google",
        server_metadata_url=OAUTH_CONF_URL,
        client_kwargs={"scope": "openid email profile"},
    )


def get_google_auth() -> Any:
    """ Return a Google authentication provider interface """
    assert _oauth is not None
    return cast(Any, _oauth).google


def set_session_userid(userid: str, idinfo: UserIdDict) -> None:
    """ Set the Flask session userid and idinfo attributes """
    session["userid"] = {
        "id": userid,
    }
    session["user"] = idinfo
    session.permanent = True


def clear_session_userid() -> None:
    """ Clears the Flask session userid and idinfo attributes """
    sess = cast(Dict[str, Any], session)
    sess.pop("userid", None)
    sess.pop("user", None)


def session_user() -> Optional[User]:
    """ Return the user who is authenticated in the current session, if any.
        This can be called within any Flask request. """
    u = None
    sess = cast(Dict[str, Any], session)
    if (user := sess.get("userid")) is not None:
        userid = user.get("id")
        u = User.load_if_exists(userid)
    return u


def auth_required(**error_kwargs: Any) -> Callable[[RouteType], RouteType]:
    """ Decorator for routes that require an authenticated user.
        Call with no parameters to redirect unauthenticated requests
        to url_for("web.login"), or login_url="..." to redirect to that URL,
        or any other kwargs to return a JSON reply to unauthenticated
        requests, containing those kwargs (via jsonify()). """

    def wrap(func: RouteType) -> RouteType:
        @wraps(func)
        def route() -> ResponseType:
            """Load the authenticated user into g.user
            before invoking the wrapped route function"""
            u = session_user()
            if u is None:
                # No authenticated user
                if error_kwargs and "login_url" not in error_kwargs:
                    # This is a JSON API: Reply with a JSON error code
                    # and an HTTP status of 401 - Unauthorized
                    return jsonify(**error_kwargs), 401
                # This is probably a web route; reply with a redirect
                # Check whether we're already coming from the
                # login page, in which case we're screwed
                # (cookies or popups are probably not allowed)
                if request.args.get("fromlogin", "") == "1":
                    return redirect(url_for("web.login_error"))
                # Not already coming from the greeting page:
                # redirect to it
                login_url = error_kwargs.get("login_url")
                return redirect(login_url or url_for("web.greet"))
            # We have an authenticated user: store in g.user
            # and call the route function
            g.user = u
            # Set the locale for this thread to the user's locale
            set_locale(u.locale)
            return func()

        return route

    return wrap


def current_user() -> Optional[User]:
    """ Return the currently logged in user. Only valid within route functions
        decorated with @auth_required. """
    return g.get("user")


def current_user_id() -> Optional[str]:
    """ Return the id of the currently logged in user. Only valid within route
        functions decorated with @auth_required. """
    u = g.get("user")
    return None if u is None else u.id()


class RequestData:

    """ Wraps the Flask request object to allow error-checked retrieval of query
        parameters either from JSON or from form-encoded POST data """

    _TRUE_SET = frozenset(("true", "True", "1", 1, True))
    _FALSE_SET = frozenset(("false", "False", "0", 0, False))

    def __init__(self, rq: Request, *, use_args: bool = False) -> None:
        # If JSON data is present, assume this is a JSON request
        self.q: Dict[str, Any] = cast(Any, rq).get_json(silent=True)
        self.using_json = True
        if not self.q:
            # No JSON data: assume this is a form-encoded request
            self.q = rq.form
            self.using_json = False
            if not self.q:
                # As a last resort, and if permitted, fall back to URL arguments
                if use_args:
                    self.q = rq.args
                else:
                    self.q = dict()

    def get(self, key: str, default: Any = None) -> Any:
        """ Obtain an arbitrary data item from the request """
        return self.q.get(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        """ Obtain an integer data item from the request """
        try:
            return int(self.q.get(key, default))
        except (TypeError, ValueError):
            return default

    @overload
    def get_bool(self, key: str) -> bool:
        ...

    @overload
    def get_bool(self, key: str, default: bool) -> bool:
        ...

    @overload
    def get_bool(self, key: str, default: Literal[None]) -> Union[bool, None]:
        ...

    def get_bool(self, key: str, default: Optional[bool] = None) -> Union[bool, None]:
        """ Obtain a boolean data item from the request """
        try:
            val = self.q.get(key, default)
            if val in self._TRUE_SET:
                # This is a truthy value
                return True
            if val in self._FALSE_SET:
                # This is a falsy value
                return False
        except (TypeError, ValueError):
            pass
        # Something else, i.e. neither truthy nor falsy: return the default
        return default

    def get_list(self, key: str) -> List[Any]:
        """ Obtain a list data item from the request """
        if self.using_json:
            # Normal get from a JSON dictionary
            r = self.q.get(key, [])
        else:
            # Use special getlist() call on request.form object
            r = cast(Any, self.q).getlist(key + "[]")
        return r if isinstance(r, list) else []

    def __getitem__(self, key: str) -> Any:
        """ Shortcut: allow indexing syntax with an empty string default """
        return self.q.get(key, "")

