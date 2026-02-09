"""

    Authentication module for netskrafl.is

    Copyright © 2025 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl


    This module contains functions for various types of user authentication,
    originating in web or app clients.

"""

from __future__ import annotations
from functools import lru_cache

from typing import Mapping, cast, Any, Optional, Dict

from datetime import UTC, datetime
import logging

import requests
import cachecontrol  # type: ignore
import jwt

from flask.wrappers import Request
from flask.globals import current_app

from google.oauth2 import id_token  # type: ignore
from google.auth.transport import requests as google_requests  # type: ignore
from google.auth.exceptions import GoogleAuthError  # type: ignore

from config import (
    ANONYMOUS_PREFIX,
    CLIENT,
    DEFAULT_LOCALE,
    FACEBOOK_APP_SECRET,
    FACEBOOK_APP_ID,
    FACEBOOK_NONCE,
    APPLE_CLIENT_ID,
    DEV_SERVER,
    FlaskConfig,
)
from basics import (
    SessionDict,
    jsonify,
    UserIdDict,
    ResponseType,
    session_data,
    set_session_cookie,
    RequestData,
)

from skrafluser import User, UserLoginDict, verify_explo_token

# URL to validate Facebook login token, in /oauth_fb endpoint
FACEBOOK_TOKEN_VALIDATION_URL = (
    "https://graph.facebook.com/debug_token?input_token={0}&access_token={1}|{2}"
)

# Facebook public key endpoint
FACEBOOK_JWT_ENDPOINT = "https://www.facebook.com/.well-known/oauth/openid/jwks/"

# Apple public key and JWT stuff
APPLE_TOKEN_VALIDATION_URL = "https://appleid.apple.com/auth/token"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"

# Establish a cached session to communicate with the Google API
google_api_session = requests.session()
cached_session: Any = cast(Any, cachecontrol).CacheControl(google_api_session)
google_request = google_requests.Request(session=cached_session)

# For testing purposes only: a hard-coded user image URL
TEST_USER_IMAGE = "https://lh3.googleusercontent.com/a/ALm5wu31WJ1zJ_P-NZzvdADdaFE9Pk1NobKf2veK6Hvt=s96-c"

# Map characters that are forbidden in Firebase paths to underscores
FIREBASE_FORBIDDEN_CHARS = ".#$[]/"
FIREBASE_TRANSLATE: Mapping[int, int] = str.maketrans(
    FIREBASE_FORBIDDEN_CHARS, "_" * len(FIREBASE_FORBIDDEN_CHARS)
)

FACEBOOK_PUBLIC_KEY: Optional[str] = None


# Utility function for making account IDs compatible with Firebase
# key restrictions
def firebase_key(s: str) -> str:
    return s.translate(FIREBASE_TRANSLATE)


def authorized_as_anonymous(request: Request) -> bool:
    """Check whether the request contains the required authorization header
    that identifies it as legitimately anonymous."""
    config: FlaskConfig = cast(Any, current_app).config
    AUTH_SECRET = config.get("AUTH_SECRET", "")
    if not AUTH_SECRET or not request.json:
        return False
    # Check for our secret bearer token AUTH_SECRET
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {AUTH_SECRET}"


def rq_get(request: Request, key: str) -> str:
    """Get a value from the request by key, either from the form data or JSON"""
    if val := request.form.get(key):
        return val
    if j := request.json:
        return j.get(key, "")
    return ""


def get_facebook_public_key() -> Optional[str]:
    """Get the public key from Facebook's JWKS endpoint"""
    global FACEBOOK_PUBLIC_KEY
    if FACEBOOK_PUBLIC_KEY:
        # Already fetched successfully: re-use cached value
        return FACEBOOK_PUBLIC_KEY
    try:
        response = requests.get(FACEBOOK_JWT_ENDPOINT)
        response.raise_for_status()  # Raise an error for bad status codes
        jwks = response.json()
        # Extract the public key in PEM format
        key_data = jwks["keys"][0]
        FACEBOOK_PUBLIC_KEY = cast(  # type: ignore
            Optional[str],
            jwt.algorithms.RSAAlgorithm.from_jwk(key_data),  # type: ignore
        )
        return FACEBOOK_PUBLIC_KEY
    except requests.exceptions.RequestException as e:
        logging.error(f"An error occurred while fetching the public key: {e}")
        return None  # Return None and failure status
    except KeyError as e:
        logging.error(f"Key error: {e}")
        return None  # Return None and failure status


def oauth2callback(request: Request) -> ResponseType:
    # Note that HTTP GETs to the /oauth2callback URL are handled in web.py,
    # this route is only for HTTP POSTs

    if not CLIENT:
        # Something is wrong in the internal setup of the server
        # (missing CLIENT setting in Secret Manager)
        # 500 - Internal server error
        return jsonify({"status": "invalid", "msg": "Missing CLIENT"}), 500

    if DEV_SERVER:
        # The 'fail' parameter is used for testing purposes only.
        # If sent by the client, we respond with the error code requested.
        try:
            fail = rq_get(request, "fail")
            if fail:
                fail_code = int(fail) if len(fail) <= 3 else 0
                if fail_code:
                    return (
                        jsonify({"status": "invalid", "msg": "Testing failure"}),
                        fail_code,
                    )
        except Exception:
            # Never mind (this can happen if the request is not a form and does not contain JSON)
            pass

    token = ""
    config: FlaskConfig = cast(Any, current_app).config
    testing = config.get("TESTING", False)
    client_type = "web"  # Default client type
    locale = ""

    if not testing:
        token = rq_get(request, "idToken")
        if not token:
            # No authentication token included in the request
            # 400 - Bad Request
            logging.warning("Missing token")
            return jsonify({"status": "invalid", "msg": "Missing token"}), 400
        client_type = rq_get(request, "clientType") or "web"
        locale = rq_get(request, "locale")

    client_type = client_type[:64]  # Defensive programming
    client_id = CLIENT.get(client_type, {}).get("id", "")
    if not client_id:
        # Unknown client type (should be one of 'web', 'ios', 'android')
        # 400 - Bad Request
        logging.warning(f"Unknown client type: {client_type}")
        return jsonify({"status": "invalid", "msg": "Unknown client type"}), 400

    uld: Optional[UserLoginDict] = None
    account: Optional[str] = None
    userid: Optional[str] = None
    idinfo: Optional[UserIdDict] = None
    email: Optional[str] = None
    image: Optional[str] = None
    name: Optional[str] = None

    try:
        if testing:
            # Probably a Python unit test
            # Get the idinfo dictionary directly from the request
            f = cast(Dict[str, str], request.form)
            idinfo = UserIdDict(
                iss="accounts.google.com",
                sub=f["sub"],
                name=f["name"],
                picture=TEST_USER_IMAGE,
                email=f["email"],
                method="Test",
                account=f["sub"],
                locale=DEFAULT_LOCALE,
                new=False,
                client_type=client_type,
            )
        elif DEV_SERVER and token == "[TESTING]":
            # Probably a client-side (Detox/Jest) test
            # Use a hard-coded user id dictionary
            idinfo = UserIdDict(
                iss="accounts.google.com",
                sub=token,
                name="Test User",
                picture=TEST_USER_IMAGE,
                email="test@explowordgame.com",
                method="Test",
                account=token,
                locale=DEFAULT_LOCALE,
                new=False,
                client_type=client_type,
            )
        else:
            # Verify the token and extract its claims
            idinfo = id_token.verify_oauth2_token(  # type: ignore
                token, google_request, client_id
            )
            if idinfo is None:
                raise ValueError(
                    f"Invalid Google token: {token}, client_id {client_id}"
                )
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
            # We prioritize the locale given in the request, if any,
            # then the one returned from the Google auth, if any,
            # and finally we resort to the default locale (en_US).
            locale = (locale or idinfo.get("locale") or DEFAULT_LOCALE).replace(
                "-", "_"
            )
            # Check whether this is an upgrade of an anonymous user
            # to a fully authenticated user
            upgrade_from: Optional[str] = None
            sd = session_data()
            if sd and sd.get("method") == "Anonymous":
                # We already have a valid anonymous user session:
                # upgrade the user to a fully authenticated user
                upgrade_from = sd.get("userid")
            # Attempt to find an associated user record in the datastore,
            # or create a fresh user record if not found
            uld = User.login_by_account(
                account,
                name or "",
                email or "",
                image or "",
                locale=locale,
                upgrade_from=upgrade_from,
            )
            # Store login data where we'll find it again, and return
            # some of it back to the client
            userid = uld["user_id"]
            uld["method"] = idinfo["method"] = "Google"
            idinfo["new"] = uld["new"]
            idinfo["client_type"] = client_type

    except (KeyError, ValueError) as e:
        # Invalid token (most likely expired, which is an expected condition)
        # 401 - Unauthorized
        logging.info(f"Invalid Google token: {e}")
        return jsonify({"status": "invalid", "msg": str(e)}), 401

    except GoogleAuthError as e:
        logging.error(f"Google auth error: {e}", exc_info=True)
        return jsonify({"status": "invalid", "msg": str(e)}), 401

    if not userid or uld is None:
        # Unable to obtain the user id for some reason
        # 401 - Unauthorized
        msg = "Unable to obtain user id in Google sign-in"
        logging.error(msg)
        return jsonify({"status": "invalid", "msg": msg}), 401

    # Authentication complete; user id obtained
    # Set the Flask session cookie
    set_session_cookie(userid, idinfo=idinfo)
    # Send a bunch of login data back to the client via the UserLoginDict instance
    return jsonify(dict(status="success", **uld))


def oauth_fb(request: Request) -> ResponseType:
    """Facebook authentication"""
    # The 'fail' parameter is used for testing purposes only.
    # If sent by the client, we always respond with a 401 Not Authorized.
    if DEV_SERVER:
        # The 'fail' parameter is used for testing purposes only.
        # If sent by the client, we respond with the error code requested.
        fail = request.form.get("fail", "") or cast(Any, request).json.get("fail", "")
        if fail:
            try:
                fail_code = int(fail) if len(fail) <= 3 else 0
            except ValueError:
                fail_code = 0
            if fail_code:
                return (
                    jsonify({"status": "invalid", "msg": "Testing failure"}),
                    fail_code,
                )

    rq = RequestData(request)
    user: Optional[Dict[str, str]] = rq.get("user")
    if user is None or not (account := user.get("id", "")):
        return (
            jsonify(
                {
                    "status": "invalid",
                    "msg": "Unable to obtain user id in Facebook sign-in",
                }
            ),
            401,
        )

    # Obtain the provider that is being requested for Facebook token validation
    # These are presently either "stokkur" (default) or "mideind"
    provider = rq.get("provider", "stokkur")
    facebook_app_id = FACEBOOK_APP_ID.get(provider, "")
    facebook_app_secret = FACEBOOK_APP_SECRET.get(provider, "")
    if not facebook_app_id or not facebook_app_secret:
        return (
            jsonify(
                {
                    "status": "invalid",
                    "msg": "Unknown Facebook auth provider",
                }
            ),
            401,
        )

    token = user.get("token", "")

    # Check whether this is a limited login (used by iOS clients only)
    is_limited_login = rq.get_bool("isLimitedLogin", False)
    if is_limited_login:
        if not token or len(token) > 4096:
            return (
                jsonify(
                    {"status": "invalid", "msg": "Invalid Facebook limited login token"}
                ),
                401,
            )
        # Validate Limited Login token
        try:
            # Get the (cached) public key from Facebook's JWKS endpoint
            public_key = get_facebook_public_key()
            if not public_key:
                return (
                    jsonify(
                        {
                            "status": "invalid",
                            "msg": "Missing Facebook public key",
                        }
                    ),
                    401,
                )
            decoded_token = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                audience=facebook_app_id,
                options={"verify_exp": True},
            )
            if decoded_token.get("nonce") != FACEBOOK_NONCE:
                return (
                    jsonify(
                        {
                            "status": "invalid",
                            "msg": "Invalid Facebook nonce in token",
                        }
                    ),
                    401,
                )
            account_in_token = decoded_token.get("sub", "")
            if account != account_in_token:
                return (
                    jsonify(
                        {
                            "status": "invalid",
                            "msg": "Wrong user id in Facebook token",
                        }
                    ),
                    401,
                )
        except jwt.ExpiredSignatureError:
            return (
                jsonify(
                    {
                        "status": "invalid",
                        "msg": "Token has expired",
                    }
                ),
                401,
            )
        except jwt.InvalidTokenError:
            return (
                jsonify(
                    {
                        "status": "invalid",
                        "msg": "Invalid Facebook token",
                    }
                ),
                401,
            )
    else:
        # Perform basic validation
        if not token or len(token) > 1024 or not token.isalnum():
            return jsonify({"status": "invalid", "msg": "Invalid Facebook token"}), 401
        # Validate regular Facebook token
        r = requests.get(
            FACEBOOK_TOKEN_VALIDATION_URL.format(
                token, facebook_app_id, facebook_app_secret
            )
        )
        if r.status_code != 200:
            # Error from the Facebook API: communicate it back to the client
            msg = ""
            try:
                msg = cast(Any, r).json()["error"]["message"]
                msg = f": {msg}"
            except (KeyError, ValueError):
                pass
            return (
                jsonify(
                    {
                        "status": "invalid",
                        "msg": f"Unable to verify Facebook token{msg}",  # Lack of space intentional
                    }
                ),
                401,
            )
        response: Dict[str, Any] = cast(Any, r).json()
        if not response or not (rd := response.get("data")):
            return (
                jsonify(
                    {
                        "status": "invalid",
                        "msg": "Invalid format of Facebook token data",
                    }
                ),
                401,
            )
        if (
            facebook_app_id != rd.get("app_id")
            or "USER" != rd.get("type")
            or not rd.get("is_valid")
        ):
            return (
                jsonify({"status": "invalid", "msg": "Facebook token data mismatch"}),
                401,
            )
        if account != rd.get("user_id"):
            return (
                jsonify(
                    {"status": "invalid", "msg": "Wrong user id in Facebook token"}
                ),
                401,
            )
    # So far, so good: double check that token data are as expected
    name = user.get("full_name", "")
    image = user.get("image", "")
    email = user.get("email", "").lower()
    # Make sure that Facebook account ids are different from Google/OAuth ones
    # by prefixing them with 'fb:'
    account = "fb:" + account
    # Login or create the user in the Explo user model
    locale = (rq.get("locale") or DEFAULT_LOCALE).replace("-", "_")
    # Check whether this is an upgrade of an anonymous user
    # to a fully authenticated user
    upgrade_from: Optional[str] = None
    sd = session_data()
    if sd and sd.get("method") == "Anonymous":
        # We already have a valid anonymous user session:
        # upgrade the user to a fully authenticated user
        upgrade_from = sd.get("userid")
    uld = User.login_by_account(
        account, name, email, image, locale=locale, upgrade_from=upgrade_from
    )
    userid = uld.get("user_id") or ""
    uld["method"] = "Facebook"
    # Create the session dictionary that will be set as a cookie
    sd = SessionDict(
        userid=userid,
        method="Facebook",
        new=uld.get("new") or False,
        client_type=rq.get("clientType") or "web",
    )
    # Set the Flask session cookie
    set_session_cookie(userid, sd=sd)
    # Send a bunch of login data back to the client via the UserLoginDict instance
    return jsonify(dict(status="success", **uld))


# Global sequence number for Apple JWK cache invalidation
_apple_jwk_seq = 0


@lru_cache(maxsize=1)
def _apple_key_client(day: datetime, seq: int) -> jwt.PyJWKClient:
    """Return a cached Apple client secret. The secret is calculated
    once per day and is valid for 180 days (6 months),
    which is the maximum allowed."""
    return jwt.PyJWKClient(APPLE_JWKS_URL)


def apple_key_client() -> jwt.PyJWKClient:
    """Return the currently cached Apple client secret"""
    now = datetime.now(UTC)
    today = datetime(now.year, now.month, now.day, tzinfo=UTC)
    return _apple_key_client(today, _apple_jwk_seq)


def fresh_apple_key_client() -> jwt.PyJWKClient:
    """Return a freshly recalculated Apple client secret"""
    global _apple_jwk_seq
    _apple_jwk_seq += 1
    return apple_key_client()


def oauth_apple(request: Request) -> ResponseType:
    """Apple ID token validation"""

    if DEV_SERVER:
        # The 'fail' parameter is used for testing purposes only.
        # If sent by the client, we respond with the error code requested.
        fail = request.form.get("fail", "") or cast(Any, request).json.get("fail", "")
        if fail:
            try:
                fail_code = int(fail) if len(fail) <= 3 else 0
            except ValueError:
                fail_code = 0
            if fail_code:
                return (
                    jsonify({"status": "invalid", "msg": "Testing failure"}),
                    fail_code,
                )

    rq = RequestData(request)
    token = rq.get("token", "")
    if not token:
        return (
            jsonify({"status": "invalid", "msg": "Missing token in Apple sign-in"}),
            401,
        )
    try:
        jwt_client = apple_key_client()
        try:
            signing_key = jwt_client.get_signing_key_from_jwt(token)
        except jwt.exceptions.PyJWKClientError:
            # Unable to obtain the signing key from the Apple JWKs;
            # it may simply need to be refreshed
            jwt_client = fresh_apple_key_client()
            signing_key = jwt_client.get_signing_key_from_jwt(token)
        # The decode() function raises an exception if the token
        # is incorrectly signed or does not contain the required claims
        payload = jwt.decode(  # type: ignore
            token,
            cast(Any, signing_key).key,
            algorithms=["RS256"],  # Apple only supports RS256
            issuer=APPLE_ISSUER,
            audience=APPLE_CLIENT_ID,
            options={"require": ["iss", "sub", "email"]},
        )
    except jwt.exceptions.PyJWKClientError as e:
        logging.error(f"Unable to obtain Apple signing key: {e}", exc_info=True)
        return (
            jsonify(
                {
                    "status": "invalid",
                    "msg": "Unable to obtain Apple signing key",
                    "error": str(e),
                }
            ),
            401,
        )
    except jwt.exceptions.ExpiredSignatureError as e:
        # Expired token (which is an expected condition):
        # return 401 - Unauthorized
        logging.info(f"Expired Apple token: {e}")
        return (
            jsonify(
                {
                    "status": "invalid",
                    "msg": "Invalid token in Apple sign-in",
                    "error": str(e),
                }
            ),
            401,
        )
    except Exception as e:
        # Invalid token (something is probably wrong):
        # return 401 - Unauthorized
        logging.error(f"Invalid Apple token: {e}", exc_info=True)
        return (
            jsonify(
                {
                    "status": "invalid",
                    "msg": "Invalid token in Apple sign-in",
                    "error": str(e),
                }
            ),
            401,
        )

    email: str = payload.get("email", "")
    uid: str = payload.get("sub", "")
    name: str = rq.get("fullName", "")  # This is populated on first sign-in
    image = ""  # !!! Not available from Apple token
    locale = (rq.get("locale") or DEFAULT_LOCALE).replace("-", "_")

    # Make sure that Apple account ids are different from Google/OAuth ones
    # by prefixing them with 'apple:'. Note that Firebase paths cannot contain
    # periods, so we replace those with underscores, enabling the account
    # id to be used as a part of a Firebase path.
    account = "apple:" + firebase_key(uid)
    # Check whether this is an upgrade of an anonymous user
    # to a fully authenticated user
    upgrade_from: Optional[str] = None
    sd = session_data()
    if sd and sd.get("method") == "Anonymous":
        # We already have a valid anonymous user session:
        # upgrade the user to a fully authenticated user
        upgrade_from = sd.get("userid")
    # Login or create the user in the Explo user model
    uld = User.login_by_account(
        account, name, email, image, locale=locale, upgrade_from=upgrade_from
    )
    userid = uld.get("user_id") or ""
    uld["method"] = "Apple"
    # Populate the session dictionary that will be set as a cookie
    sd = SessionDict(
        userid=userid,
        method="Apple",
        new=uld.get("new") or False,
        client_type="ios",  # Assume that Apple login is always from iOS
    )
    # Set the Flask session cookie
    set_session_cookie(userid, sd=sd)
    # Send a bunch of login data back to the client via the UserLoginDict instance
    return jsonify(dict(status="success", **uld))


def oauth_explo(request: Request) -> ResponseType:
    """Login via a previously issued Explo token. The token is generated
    in any of the other login methods and is returned to the client in the
    UserLoginDict instance. The client can then use that token for subsequent
    logins, without having to go through the third party OAuth flow again.
    The token is by default valid for 30 days."""
    if DEV_SERVER:
        # The 'fail' parameter is used for testing purposes only.
        # If sent by the client, we respond with the error code requested.
        fail = request.form.get("fail", "") or cast(Any, request).json.get("fail", "")
        if fail:
            try:
                fail_code = int(fail) if len(fail) <= 3 else 0
            except ValueError:
                fail_code = 0
            if fail_code:
                return (
                    jsonify({"status": "invalid", "msg": "Testing failure"}),
                    fail_code,
                )

    token: Optional[str] = None
    config: FlaskConfig = cast(Any, current_app).config
    testing = config.get("TESTING", False)
    client_type: str = "web"  # Default client type

    if not testing:
        token = request.form.get("token", "") or cast(Any, request).json.get(
            "token", ""
        )
        if not token:
            # No authentication token included in the request
            # 400 - Bad Request
            return jsonify({"status": "invalid", "msg": "Missing token"}), 400
        client_type = (
            request.form.get("clientType", "")
            or (
                request.json is not None
                and cast(Dict[str, str], request.json).get("clientType", "")
            )
            or "web"
        )

    client_id = CLIENT.get(client_type, {}).get("id", "")
    if not client_id:
        # Unknown client type (should be one of 'web', 'ios', 'android')
        # 400 - Bad Request
        return jsonify({"status": "invalid", "msg": "Unknown client type"}), 400

    uld: Optional[UserLoginDict] = None
    userid: Optional[str] = None

    try:
        if testing:
            # Get the idinfo dictionary directly from the request
            f = cast(Dict[str, str], request.form)
            sub = f.get("sub", "")
        else:
            # Verify the basics of the JWT-compliant token
            claims = verify_explo_token(token) if token else None
            if claims is None:
                raise ValueError("Unable to verify token")
            # Claims successfully extracted, which means that the token
            # is valid and not expired
            sub = claims.get("sub", "")
        if not sub:
            raise ValueError("Missing user id")
        # Note that we return the original token to the client,
        # as we want to re-use it until it expires
        uld = User.login_by_id(sub, previous_token=token)
        if uld is None:
            raise ValueError("User id not found")
        userid = uld["user_id"]
        uld["method"] = "Explo"
        sd = SessionDict(
            userid=userid,
            method="Explo",
            # By definition, the user must already have existed
            # in order for Explo auth to be available
            new=False,
            client_type=client_type,
        )

    except (KeyError, ValueError) as e:
        # Invalid token: return 401 - Unauthorized
        msg = f"Invalid Explo token: {e}"
        logging.error(msg)
        return jsonify({"status": "invalid", "msg": msg}), 401

    # Authentication complete; token was valid and user id was found
    # Set the Flask session cookie
    set_session_cookie(userid, sd=sd)
    # Send a bunch of login data back to the client via the UserLoginDict instance
    return jsonify(dict(status="success", **uld))


def oauth_anonymous(request: Request) -> ResponseType:
    """Anonymous login, i.e. one where the user hasn't (yet) signed in
    via any of the regular OAuth2 methods. This typically relies on a device id
    to identify the user."""
    if not authorized_as_anonymous(request):
        return (
            jsonify({"status": "invalid", "msg": "Not authorized as anonymous"}),
            401,
        )

    # Get the device id from the "sub" field in the request JSON
    f = cast(Optional[Mapping[str, str]], request.json)
    if f is None or not (sub := f.get("sub", "")):
        # 401 - Unauthorized
        return (
            jsonify(
                {"status": "invalid", "msg": "Missing device id in anonymous sign-in"}
            ),
            401,
        )

    # This appears to be our client and the request is authorized;
    # proceed with the anonymous login
    client_type = f.get("clientType", "web")  # Default client type
    locale = (f.get("locale", "") or DEFAULT_LOCALE).replace("-", "_")

    # Prefix the incoming device id with 'anon:' to distinguish
    # it from properly authenticated ids
    sub = ANONYMOUS_PREFIX + firebase_key(sub)

    # Attempt to find an associated user record in the datastore,
    # or create a fresh user record if not found.
    # Note that we have no name, e-mail or image for an anonymous user.
    uld = User.login_by_account(sub, "", "", "", locale=locale)

    # Obtain the unique user id (key), under which this account is stored
    # in the UserModel table in the datastore
    userid = uld["user_id"]

    if not userid:
        # Unable to obtain the user id for some reason
        # 401 - Unauthorized
        msg = "Unable to obtain user id in anonymous sign-in"
        logging.error(msg)
        return (
            jsonify({"status": "invalid", "msg": msg}),
            401,
        )

    sd = SessionDict(
        userid=userid,
        method="Anonymous",
        new=uld.get("new") or False,
        client_type=client_type,
    )
    uld["method"] = "Anonymous"

    # Authentication complete; user id obtained
    # Set the Flask session cookie
    set_session_cookie(userid, sd=sd)
    # Send a bunch of login data back to the client
    # via the UserLoginDict instance
    return jsonify(dict(status="success", **uld))
