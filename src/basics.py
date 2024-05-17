"""

    Basic utility functions and classes

    Copyright (C) 2024 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl


    This module defines a number of basic entities that are used and shared
    by the main.py, api.py and web.py modules.

"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import io
from typing import (
    Literal,
    Mapping,
    Optional,
    Dict,
    TypedDict,
    Union,
    List,
    Any,
    TypeVar,
    Callable,
    cast,
    overload,
)

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
from werkzeug.utils import send_file  # type: ignore
from authlib.integrations.flask_client import OAuth  # type: ignore
from PIL import Image

from config import OAUTH_CONF_URL, DEFAULT_THUMBNAIL_SIZE, RouteType, ResponseType
from languages import set_locale
from skrafluser import User
from skrafldb import Client


# Generic placeholder type
T = TypeVar("T")

# A Flask route function decorator
RouteFunc = Callable[[RouteType], RouteType]


class UserIdDict(TypedDict):
    """Old-style auxiliary user data dictionary, previously
    stored in the Flask session cookie. Has been replaced by
    the simpler and smaller SessionDict (see below)."""

    iss: str
    sub: str
    name: str
    picture: str
    email: str
    # Login method ('Google', 'Facebook', 'Apple', 'Explo')
    method: str
    # Account identifier
    account: str
    # User locale
    locale: str
    # True if new user, signing in for the first time
    new: bool
    # Client type ('web', 'ios', 'android')
    client_type: str


class SessionDict(TypedDict):
    """The contents of the Flask session cookie"""

    userid: str
    # Login method ('Google', 'Facebook', 'Apple', 'Explo')
    method: str
    # True if new user, signing in for the first time
    new: bool
    # Client type ('web', 'ios', 'android')
    client_type: str


MOBILE_CLIENT_TYPES = frozenset(("ios", "android"))


# Type annotation wrapper for flask.jsonify()
def jsonify(*args: Any, **kwargs: Any) -> Response:
    response = flask_jsonify(*args, **kwargs)
    response.headers["Content-Type"] = "application/json; charset=UTF-8"
    return response


def ndb_wsgi_middleware(wsgi_app: Any) -> Callable[[Any, Any], Any]:
    """Returns a wrapper for the original WSGI app"""

    def middleware(environ: Any, start_response: Any) -> Any:
        """Wraps the original WSGI app"""
        with Client.get_context():
            return wsgi_app(environ, start_response)

    return middleware


def max_age(seconds: int) -> RouteFunc:
    """Caching decorator for Flask - augments response
    with a max-age cache header"""

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


class CachedResponse(Response):

    """A subclass of Flask's Response class that causes
    the requisite cache headers to be added to the response
    and deletes the Vary: header which Flask adds by
    default to all responses that use the current
    session."""

    pass


class FlaskWithCaching(Flask):

    """Subclass Flask to inject our custom process_response() method"""

    def process_response(self, response: Response) -> Response:
        """Process the response before returning it to the client"""
        r = super().process_response(response)
        if isinstance(r, CachedResponse):
            # Remove the Set-Cookie header, as the client
            # may not cache responses that set cookies
            r.headers.pop("Set-Cookie", None)
            # ...and remove Flask's default Vary: Cookie header
            r.headers.pop("Vary", None)
            r.vary.clear()
        return r


def send_cached_file(
    content: io.BytesIO, *, lifetime_seconds: int, mimetype: str = "image/jpeg"
) -> Response:
    """Create a response with a JPEG image and a cache header, if lifetime_seconds > 0"""
    now = datetime.now(UTC)
    response = send_file(
        content,
        environ=request.environ,
        mimetype=mimetype,
        last_modified=now,
        max_age=lifetime_seconds,
        response_class=CachedResponse if lifetime_seconds > 0 else Response,
    )
    assert isinstance(response, Response)
    if lifetime_seconds > 0:
        expires = now + timedelta(seconds=lifetime_seconds)
        response.headers["Expires"] = expires.strftime("%a, %d %b %Y %H:%M:%S GMT")
    return response


# Module-scope OAuth instance,
# only used by init_oauth() and get_google_auth()
_oauth: Optional[OAuth] = None


def init_oauth(app: Flask) -> None:
    """Initialize the OAuth wrapper"""
    global _oauth
    _oauth = OAuth(app)
    cast(Any, _oauth).register(
        name="google",
        server_metadata_url=OAUTH_CONF_URL,
        client_kwargs={"scope": "openid email profile"},
    )


def get_google_auth() -> Any:
    """Return a Google authentication provider interface"""
    assert _oauth is not None
    return cast(Any, _oauth).google


def set_session_cookie(
    userid: str,
    *,
    sd: Optional[SessionDict] = None,
    idinfo: Optional[UserIdDict] = None,
) -> None:
    """Set the Flask session cookie attributes"""
    sess = cast(Dict[str, Any], session)
    if sd is None:
        if idinfo is None:
            raise ValueError("Either sd or idinfo must be specified")
        # Create a SessionDict from the UserIdDict
        sd = SessionDict(
            userid=userid,
            method=idinfo.get("method", "Google"),
            new=idinfo.get("new", False),
            client_type=idinfo.get("client_type", "web"),
        )
    # Set the new-style session attribute
    sess["s"] = sd
    # Pop deprecated session attributes
    sess.pop("userid", None)
    sess.pop("user", None)
    session.permanent = True


def clear_session_userid() -> None:
    """Clears the Flask session userid and idinfo attributes"""
    sess = cast(Dict[str, Any], session)
    # Pop deprecated session attributes
    sess.pop("userid", None)
    sess.pop("user", None)
    # Pop the current session attribute
    sess.pop("s", None)


def session_user() -> Optional[User]:
    """Return the user who is authenticated in the current session, if any.
    This can be called within any Flask request."""
    userid = ""
    sess = cast(Mapping[str, Any], session)
    if (s := cast(Optional[SessionDict], sess.get("s"))) is not None:
        # New-style session: single user id
        userid = s.get("userid", "")
    elif (u := sess.get("userid")) is not None:
        # Old-style session: nested user id dictionary
        userid = u.get("id", "")
    return User.load_if_exists(userid)  # Returns None if userid is None or empty


def session_data() -> Optional[SessionDict]:
    """Return auxiliary data associated with the current session, if any.
    This can be called within any Flask request."""
    if (sess := cast(Optional[Dict[str, Any]], session)) is None:
        return None
    # Check for new-style session and return it directly if found
    if (sd := sess.get("s")) is not None:
        return sd
    # Check for old-style (deprecated) session
    if (u := cast(Optional[UserIdDict], sess.get("user"))) is None:
        return None
    userid = ""
    if (uid := sess.get("userid")) is not None:
        # Old-style session: nested user id dictionary
        userid = uid.get("id", "")
    return SessionDict(
        userid=userid,
        method=u.get("method", "Google"),
        new=u.get("new", False),
        client_type=u.get("client_type", "web"),
    )


def anonymous_user() -> bool:
    """Return True if the current user signed in anoymously."""
    if (sd := session_data()) is None:
        return False
    return sd.get("method", "") == "Anonymous"


def is_mobile_client() -> bool:
    """Return True if the currently logged in client is a mobile client"""
    if (s := session_data()) is None:
        return False
    return s.get("client_type", "web") in MOBILE_CLIENT_TYPES


def current_user() -> Optional[User]:
    """Return the currently logged in user. Only valid within route functions
    decorated with @auth_required."""
    return g.get("user")


def current_user_id() -> Optional[str]:
    """Return the id of the currently logged in user. Only valid within route
    functions decorated with @auth_required."""
    return None if (u := g.get("user")) is None else u.id()


def auth_required(*, allow_anonymous: bool = True, **error_kwargs: Any) -> RouteFunc:
    """Decorator for routes that require an authenticated user.
    Call with no parameters to redirect unauthenticated requests
    to url_for("web.login"), or login_url="..." to redirect to that URL,
    or any other kwargs to return a JSON reply to unauthenticated
    requests, containing those kwargs (via jsonify())."""

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
            # We have an authenticated user: check whether they're anonymous
            # and this route forbids anonymous users
            if not allow_anonymous and u.is_anonymous():
                # Reply with 401 - Unauthorized
                # (We are safe to assume that this is a JSON API route)
                return jsonify(ok=False, msg="Anonymous user not allowed"), 401
            # All is OK: store in g.user and call the route function
            g.user = u
            # Set the locale for this thread to the user's locale
            set_locale(u.locale)
            return func()

        return route

    return wrap


def make_thumbnail(image: bytes, size: int=DEFAULT_THUMBNAIL_SIZE) -> io.BytesIO:
    """Create a thumbnail from a JPEG image"""
    # Convert the image bytes to a BytesIO object
    image_bytes = io.BytesIO(image)
    # Create a thumbnail using PIL
    img = Image.open(image_bytes, formats=["JPEG"])  # type: ignore
    img.thumbnail((size, size))  # type: ignore
    thumb_bytes = io.BytesIO()
    img.save(thumb_bytes, format="JPEG")  # type: ignore
    thumb_bytes.seek(0)
    return thumb_bytes


class RequestData:
    """Wraps the Flask request object to allow error-checked retrieval of query
    parameters either from JSON or from form-encoded POST data"""

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

    def __repr__(self) -> str:
        return f"<RequestData {self.q!r}>"

    @overload
    def get(self, key: str) -> Any: ...

    @overload
    def get(self, key: str, default: T) -> T: ...

    def get(self, key: str, default: Any = None) -> Any:
        """Obtain an arbitrary data item from the request"""
        return self.q.get(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        """Obtain an integer data item from the request"""
        try:
            return int(self.q.get(key, default))
        except (TypeError, ValueError):
            return default

    @overload
    def get_bool(self, key: str) -> bool: ...

    @overload
    def get_bool(self, key: str, default: bool) -> bool: ...

    @overload
    def get_bool(self, key: str, default: Literal[None]) -> Union[bool, None]: ...

    def get_bool(self, key: str, default: Optional[bool] = None) -> Union[bool, None]:
        """Obtain a boolean data item from the request"""
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
        """Obtain a list data item from the request"""
        if self.using_json:
            # Normal get from a JSON dictionary
            r = self.q.get(key, [])
        else:
            # Use special getlist() call on request.form object
            r = cast(Any, self.q).getlist(key + "[]")
        return cast(List[Any], r) if isinstance(r, list) else []

    def __getitem__(self, key: str) -> Any:
        """Shortcut: allow indexing syntax with an empty string default"""
        return self.q.get(key, "")
