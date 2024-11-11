"""

    Configuration data

    Copyright (C) 2024 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl


    This module reads a number of configuration parameters
    from environment variables and config files.

"""

from __future__ import annotations

from typing import (
    Any,
    Dict,
    Literal,
    Mapping,
    NotRequired,
    Optional,
    TypedDict,
    Union,
    Tuple,
    Callable,
)
from datetime import UTC, datetime, timedelta
import os
from secret_manager import SecretManager
from werkzeug.wrappers import Response as WerkzeugResponse
from flask.wrappers import Response


# Universal type definitions
ResponseType = Union[
    str, bytes, Response, WerkzeugResponse, Tuple[str, int], Tuple[Response, int]
]
RouteType = Callable[..., ResponseType]


class FlaskConfig(TypedDict):
    """The Flask configuration dictionary"""

    DEBUG: bool
    SESSION_COOKIE_DOMAIN: Optional[str]
    SESSION_COOKIE_SECURE: bool
    SESSION_COOKIE_HTTPONLY: bool
    SESSION_COOKIE_SAMESITE: Literal["Strict", "Lax", "None"]
    PERMANENT_SESSION_LIFETIME: timedelta
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    AUTH_SECRET: str
    # JSON_AS_ASCII: bool  # No longer supported in Flask >= 2.3
    TESTING: NotRequired[bool]


# Are we running in a local development environment or on a GAE server?
running_local: bool = os.environ.get("SERVER_SOFTWARE", "").startswith("Development")
# Set SERVER_HOST to 0.0.0.0 to accept HTTP connections from the outside
host: str = os.environ.get("SERVER_HOST", "127.0.0.1")
port: str = os.environ.get("SERVER_PORT", "8080")

# App Engine (and Firebase) project id
PROJECT_ID = os.environ.get("PROJECT_ID", "")
assert PROJECT_ID, "PROJECT_ID environment variable not set"

DEV_SERVER = PROJECT_ID == "explo-dev"

DEFAULT_LOCALE = "is_IS" if PROJECT_ID == "netskrafl" else "en_US"

DEFAULT_OAUTH_CONF_URL = "https://accounts.google.com/.well-known/openid-configuration"

DEFAULT_THUMBNAIL_SIZE = 384  # Thumbnails are 384x384 pixels by default

DEFAULT_ELO = 1200  # Elo rating for new players

# Initialize the SecretManager with your Google Cloud project ID
sm = SecretManager(PROJECT_ID)

# Should we constrain the domain for HTTP session cookies?
# Currently we don't do this as we would like to be able to access
# particular versions of the backend by using VERSION-dot-PROJECT.appspot.com
# URLs, and we want to allow cookies for such domains also.
# (This is not ideal but follows from the peculiar GAE convention of
# using "-dot-" to separate the version and project id in HTTPS URLs.
# Ideally, we would want to share cookies across version subdomains of
# PROJECT.appspot.com, but this is not currently possible with GAE.)
CONSTRAIN_COOKIE_DOMAIN = False

# Obtain the domain to use for HTTP session cookies
COOKIE_DOMAIN: Optional[str] = (
    {
        "netskrafl": ".netskrafl.is",
        "explo-dev": ".explo-dev.appspot.com",
        "explo-live": ".explo-live.appspot.com",
    }.get(PROJECT_ID, ".netskrafl.is")
    if CONSTRAIN_COOKIE_DOMAIN
    else None
)

# Load the correct client secret for the project (Explo/Netskrafl)
CLIENT_SECRET_IDS: Mapping[str, str] = {
    "netskrafl": "CLIENT_SECRET_NETSKRAFL",
    "explo-dev": "CLIENT_SECRET_EXPLO",
    "explo-live": "CLIENT_SECRET_EXPLO_LIVE",
}
CLIENT_SECRET_ID = CLIENT_SECRET_IDS.get(PROJECT_ID, "DEFAULT_CLIENT_SECRET")

# Read client secrets (some of which aren't really that secret) from the CLIENT_SECRET_FILE
j = sm.get_json_secret(CLIENT_SECRET_ID)

# Client types and their ids (and secrets, as applicable)
CLIENT: Dict[str, Dict[str, str]] = j.get("CLIENT", {})
WEB_CLIENT: Mapping[str, str] = CLIENT.get("web", {})

CLIENT_ID = WEB_CLIENT.get("id", "")
CLIENT_SECRET = WEB_CLIENT.get("secret", "")
assert CLIENT_ID, f"CLIENT.web.id not set correctly in {CLIENT_SECRET_ID}"
assert CLIENT_SECRET, f"CLIENT.web.secret not set correctly in {CLIENT_SECRET_ID}"

# Explo client secret, used as a key for signing our own JWTs
# that are used to extend the validity of third party auth tokens
EXPLO_CLIENT: Mapping[str, str] = CLIENT.get("explo", {})
EXPLO_CLIENT_SECRET = EXPLO_CLIENT.get("secret", "")

OAUTH_CONF_URL = WEB_CLIENT.get("auth_uri", DEFAULT_OAUTH_CONF_URL)

# Analytics measurement id
MEASUREMENT_ID: str = j.get("MEASUREMENT_ID", "")
if PROJECT_ID != "netskrafl":
    assert MEASUREMENT_ID, "MEASUREMENT_ID environment variable not set"

# Facebook app token, for login verification calls to the graph API
FACEBOOK_APP_ID: Mapping[str, str] = j.get("FACEBOOK_APP_ID", {})
FACEBOOK_APP_SECRET: Mapping[str, str] = j.get("FACEBOOK_APP_SECRET", {})
if PROJECT_ID != "netskrafl":
    assert (
        FACEBOOK_APP_SECRET
    ), f"FACEBOOK_APP_SECRET not set correctly in {CLIENT_SECRET_ID}"
    assert FACEBOOK_APP_ID, f"FACEBOOK_APP_ID not set correctly in {CLIENT_SECRET_ID}"

# Firebase configuration
FIREBASE_API_KEY: str = j.get("FIREBASE_API_KEY", "")
FIREBASE_SENDER_ID: str = j.get("FIREBASE_SENDER_ID", "")
FIREBASE_DB_URL: str = j.get("FIREBASE_DB_URL", "")
FIREBASE_APP_ID: str = j.get("FIREBASE_APP_ID", "")
assert (
    FIREBASE_API_KEY
), f"FIREBASE_API_KEY not set correctly in {CLIENT_SECRET_ID}"
assert (
    FIREBASE_SENDER_ID
), f"FIREBASE_SENDER_ID not set correctly in {CLIENT_SECRET_ID}"
assert FIREBASE_DB_URL, f"FIREBASE_DB_URL not set correctly in {CLIENT_SECRET_ID}"
assert FIREBASE_APP_ID, f"FIREBASE_APP_ID not set correctly in {CLIENT_SECRET_ID}"

# Apple ID configuration
APPLE_KEY_ID: str = j.get("APPLE_KEY_ID", "")
APPLE_TEAM_ID: str = j.get("APPLE_TEAM_ID", "")
APPLE_CLIENT_ID: str = j.get("APPLE_CLIENT_ID", "")
if PROJECT_ID != "netskrafl":
    assert APPLE_KEY_ID, f"APPLE_KEY_ID not set correctly in {CLIENT_SECRET_ID}"
    assert APPLE_TEAM_ID, f"APPLE_TEAM_ID not set correctly in {CLIENT_SECRET_ID}"
    assert APPLE_CLIENT_ID, f"APPLE_CLIENT_ID not set correctly in {CLIENT_SECRET_ID}"

# RevenueCat bearer token
RC_WEBHOOK_AUTH: str = j.get("RC_WEBHOOK_AUTH", "")

# Anonymous user session token
AUTH_SECRET: str = j.get("AUTH_SECRET", "")
if PROJECT_ID != "netskrafl":
    assert AUTH_SECRET, f"AUTH_SECRET not set correctly in {CLIENT_SECRET_ID}"

# Read the Flask secret session key from Google secret manager
FLASK_SESSION_KEY = sm.get_secret("SECRET_KEY_BIN")
assert len(FLASK_SESSION_KEY) == 64, "Flask session key is expected to be 64 bytes"

# Valid token issuers for OAuth2 login
VALID_ISSUERS = frozenset(("accounts.google.com", "https://accounts.google.com"))

# How many games a player plays as a provisional player
# before becoming an established one
ESTABLISHED_MARK: int = 10

# Prefix of anonymous account identifiers
ANONYMOUS_PREFIX = "anon:"


class CacheEntryDict(TypedDict):
    value: Any
    time: datetime


def ttl_cache(seconds: int) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """A simple time-to-live (TTL) caching decorator"""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        cache: Dict[Tuple[Any, ...], CacheEntryDict] = {}
        delta = timedelta(seconds=seconds)

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            current_time = datetime.now(UTC)
            # Check if the value is in the cache and if it has not expired
            key = (*args, *kwargs.items())
            val = cache.get(key)
            if val is not None and current_time - val["time"] < delta:
                return val["value"]
            # Call the function and store the result in the cache with the current time
            result = func(*args, **kwargs)
            cache[key] = {"value": result, "time": current_time}
            return result

        return wrapped

    return decorator
