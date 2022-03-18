"""

    Authentication module for netskrafl.is

    Copyright (C) 2022 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl


    This module contains functions for various types of user authentication,
    originating in web or app clients.

"""

from __future__ import annotations

from typing import Union, cast, Any, Optional, Dict

from datetime import datetime, timedelta

import requests
import cachecontrol  # type: ignore
import jwt

from flask.wrappers import Request
from flask.globals import current_app

from google.oauth2 import id_token  # type: ignore
from google.auth.transport import requests as google_requests  # type: ignore
from google.auth.exceptions import GoogleAuthError  # type: ignore

from config import (
    CLIENT,
    DEFAULT_LOCALE,
    FACEBOOK_APP_SECRET,
    FACEBOOK_APP_ID,
    APPLE_KEY_ID,
    APPLE_TEAM_ID,
    APPLE_CLIENT_ID,
    APPLE_PRIVATE_KEY,
)
from basics import jsonify, UserIdDict, ResponseType, set_session_userid, RequestData

from skrafluser import User, UserLoginDict

# URL to validate Facebook login token, in /oauth_fb endpoint
FACEBOOK_TOKEN_VALIDATION_URL = (
    "https://graph.facebook.com/debug_token?input_token={0}&access_token={1}|{2}"
)

APPLE_TOKEN_VALIDATION_URL = "https://appleid.apple.com/auth/token"

# Establish a cached session to communicate with the Google API
session = requests.session()
cached_session: Any = cast(Any, cachecontrol).CacheControl(session)
google_request = google_requests.Request(session=cached_session)


def oauth2callback(request: Request) -> ResponseType:
    # Note that HTTP GETs to the /oauth2callback URL are handled in web.py,
    # this route is only for HTTP POSTs

    if not CLIENT:
        # Something is wrong in the internal setup of the server
        # (missing setting in client_secret_*.json)
        # 500 - Internal server error
        return jsonify({"status": "invalid", "msg": "Missing CLIENT"}), 500

    # !!! TODO: Add CSRF token mechanism
    # csrf_token = request.form.get("csrfToken", "") or request.json['csrfToken']
    token: str
    config = cast(Any, current_app).config
    testing: bool = config.get("TESTING", False)
    client_type: str = "web"  # Default client type

    if testing:
        # Testing only: there is no token in the request
        token = ""
    else:
        token = request.form.get("idToken", "") or cast(Any, request).json.get(
            "idToken", ""
        )
        if not token:
            # No authentication token included in the request
            # 400 - Bad Request
            return jsonify({"status": "invalid", "msg": "Missing token"}), 400
        client_type = (
            request.form.get("clientType", "")
            or cast(Any, request).json.get("clientType", "")
            or "web"
        )

    client_id = CLIENT.get(client_type, {}).get("id", "")
    if not client_id:
        # Unknown client type (should be one of 'web', 'ios', 'android')
        # 400 - Bad Request
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
            # Get the idinfo dictionary directly from the request
            f = cast(Dict[str, str], request.form)
            idinfo = UserIdDict(
                iss="accounts.google.com",
                sub=f["sub"],
                name=f["name"],
                picture=f["picture"],
                email=f["email"],
                method="Test",
                account=f["sub"],
                locale=DEFAULT_LOCALE,
                new=False,
                client_type=client_type,
            )
        else:
            # Verify the token and extract its claims
            idinfo = id_token.verify_oauth2_token(  # type: ignore
                token, google_request, client_id
            )
            assert idinfo is not None
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
            # Attempt to find an associated user record in the datastore,
            # or create a fresh user record if not found
            # !!! TODO: Assign locale
            locale = DEFAULT_LOCALE
            uld = User.login_by_account(
                account, name or "", email or "", image or "", locale=locale
            )
            # Store login data where we'll find it again, and return
            # some of it back to the client
            userid = uld["user_id"]
            uld["method"] = idinfo["method"] = "Google"
            idinfo["account"] = uld["account"]
            idinfo["locale"] = uld["locale"]
            idinfo["new"] = uld["new"]
            idinfo["client_type"] = client_type

    except (KeyError, ValueError) as e:
        # Invalid token
        # 401 - Unauthorized
        return jsonify({"status": "invalid", "msg": str(e)}), 401

    except GoogleAuthError as e:
        return jsonify({"status": "invalid", "msg": str(e)}), 401

    if not userid or uld is None:
        # Unable to obtain the user id for some reason
        # 401 - Unauthorized
        return jsonify({"status": "invalid", "msg": "Unable to obtain user id"}), 401

    # Authentication complete; user id obtained
    # Set a session cookie
    set_session_userid(userid, idinfo)
    # Send a bunch of login data back to the client via the UserLoginDict instance
    return jsonify(dict(status="success", **uld))


def oauth_fb(request: Request) -> ResponseType:
    """Facebook authentication"""
    rq = RequestData(request)
    user: Optional[Dict[str, str]] = rq.get("user")
    if user is None or not (account := user.get("id", "")):
        return jsonify({"status": "invalid", "msg": "Unable to obtain user id"}), 401
    token = user.get("token", "")
    # Validate the Facebook token
    if not token or len(token) > 1024 or not token.isalnum():
        return jsonify({"status": "invalid", "msg": "Invalid Facebook token"}), 401
    r = requests.get(
        FACEBOOK_TOKEN_VALIDATION_URL.format(
            token, FACEBOOK_APP_ID, FACEBOOK_APP_SECRET
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
                {"status": "invalid", "msg": f"Unable to verify Facebook token{msg}"}
            ),
            401,
        )
    # So far, so good: double check that token data are as expected
    name = user.get("full_name", "")
    image = user.get("image", "")
    email = user.get("email", "").lower()
    response: Dict[str, Any] = cast(Any, r).json()
    if not response or not (rd := response.get("data")):
        return (
            jsonify(
                {"status": "invalid", "msg": "Invalid format of Facebook token data"}
            ),
            401,
        )
    if (
        FACEBOOK_APP_ID != rd.get("app_id")
        or "USER" != rd.get("type")
        or not rd.get("is_valid")
    ):
        return (
            jsonify({"status": "invalid", "msg": "Facebook token data mismatch"}),
            401,
        )
    if account != rd.get("user_id"):
        return (
            jsonify({"status": "invalid", "msg": "Wrong user id in Facebook token"}),
            401,
        )
    # Make sure that Facebook account ids are different from Google/OAuth ones
    # by prefixing them with 'fb:'
    account = "fb:" + account
    # Login or create the user in the Explo user model
    # !!! TODO: send locale from client in request
    locale = rq.get("locale") or DEFAULT_LOCALE
    uld = User.login_by_account(account, name, email, image, locale=None)
    userid = uld.get("user_id") or ""
    uld["method"] = "Facebook"
    # Emulate the OAuth idinfo
    idinfo = UserIdDict(
        iss="accounts.facebook.com",
        sub=account,
        name=name,
        picture=image,
        email=email,
        method="Facebook",
        account=account,
        locale=locale,
        new=uld.get("new") or False,
        # !!! TODO: Send clientType from client
        client_type=rq.get("clientType") or "web",
    )
    # Set the Flask session token
    set_session_userid(userid, idinfo)
    # Send a bunch of login data back to the client via the UserLoginDict instance
    return jsonify(dict(status="success", **uld))


def oauth_apple(request: Request) -> ResponseType:
    """Apple ID authentication"""

    rq = RequestData(request)
    token = rq.get("token", "")
    if not token:
        return jsonify({"status": "invalid", "msg": "Missing token"}), 401

    headers: Dict[str, str] = {"kid": APPLE_KEY_ID}
    now = datetime.utcnow()
    payload: Dict[str, Union[str, datetime]] = {
        "iss": APPLE_TEAM_ID,
        "iat": now,
        "exp": now + timedelta(days=180),
        "aud": "https://appleid.apple.com",
        "sub": APPLE_CLIENT_ID,
    }
    client_secret = jwt.encode(
        payload,
        APPLE_PRIVATE_KEY,
        algorithm="ES256",
        headers=headers,
    ).decode("utf-8")

    headers = {"content-type": "application/x-www-form-urlencoded"}
    data: Dict[str, str] = {
        "client_id": APPLE_CLIENT_ID,
        "client_secret": client_secret,
        "code": token,
        "grant_type": "authorization_code",
        "redirect_uri": "https://explowordgame.com/redirect",  # Dummy URL
    }

    res = requests.post(APPLE_TOKEN_VALIDATION_URL, data=data, headers=headers)
    response_dict = res.json()
    id_token = response_dict.get("id_token", None)

    email: str = ""
    uid: str = ""
    name: str = ""
    image: str = ""

    if id_token:
        decoded = jwt.decode(id_token, "", verify=False)
        email = decoded.get("email", "")
        uid = decoded.get("sub", "")
        name = decoded.get("name", "")  # !!! TODO
        image = decoded.get("image", "")  # !!! TODO

    if not uid:
        return jsonify({"status": "invalid", "msg": "Invalid token"}), 401

    # Make sure that Apple account ids are different from Google/OAuth ones
    # by prefixing them with 'apple:'
    account = "apple:" + uid
    # Login or create the user in the Explo user model
    # !!! TODO: send locale from client in request
    locale = rq.get("locale") or DEFAULT_LOCALE
    uld = User.login_by_account(account, name, email, image, locale=locale)
    userid = uld.get("user_id") or ""
    uld["method"] = "Apple"
    # Emulate the OAuth idinfo
    idinfo = UserIdDict(
        iss="appleid.apple.com",
        sub=account,
        name=name,
        picture=image,
        email=email,
        method="Apple",
        account=account,
        locale=locale,
        new=uld.get("new") or False,
        client_type="ios",  # Assume that Apple login is always from iOS
    )
    # Set the Flask session token
    set_session_userid(userid, idinfo)
    # Send a bunch of login data back to the client via the UserLoginDict instance
    return jsonify(dict(status="success", **uld))
