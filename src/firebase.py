"""

    Firebase wrapper for Netskrafl

    Copyright (C) 2021 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This module implements a thin wrapper around the Google Firebase
    functionality used to send push notifications to clients.

"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence, List, Union, Tuple, Set, Dict, cast

import json
import threading
import logging
import socket
from datetime import datetime, timedelta

import httplib2  # type: ignore

from oauth2client.client import GoogleCredentials  # type: ignore

from firebase_admin import App, initialize_app, auth  # type: ignore

from config import PROJECT_ID, FIREBASE_DB_URL
from cache import memcache


_FIREBASE_SCOPES: Sequence[str] = [
    "https://www.googleapis.com/auth/firebase.database",
    "https://www.googleapis.com/auth/userinfo.email",
]
_TIMEOUT: int = 15  # Seconds

_LIFETIME_MEMORY_CACHE = 1  # Minutes
_LIFETIME_REDIS_CACHE = 10  # Minutes

_HEADERS: Mapping[str, str] = {"Connection": "keep-alive"}

_USERLIST_LOCK = threading.Lock()

# Initialize thread-local storage
_tls = threading.local()

_firebase_app: Optional[App] = None
_firebase_app_lock = threading.Lock()


def _get_http() -> Optional[httplib2.Http]:
    """ Provides an authorized HTTP object, one per thread """
    http: Optional[httplib2.Http] = getattr(_tls, "_HTTP", None)
    if http is None:
        http = cast(Any, httplib2).Http(timeout=_TIMEOUT)
        # Use application default credentials to make the Firebase calls
        # https://firebase.google.com/docs/reference/rest/database/user-auth
        creds = (
            cast(Any, GoogleCredentials)
            .get_application_default()
            .create_scoped(_FIREBASE_SCOPES)
        )
        creds.authorize(http)
        creds.refresh(http)
        _tls._HTTP = http
    return http


def _request(*args: Any, **kwargs: Any) -> Tuple[httplib2.Response, bytes]:
    """ Attempt to post a Firebase request, with recovery on a ConnectionError """
    MAX_ATTEMPTS = 2
    attempts = 0
    response: httplib2.Response
    content: bytes
    while attempts < MAX_ATTEMPTS:
        try:
            kw: Dict[str, Any] = kwargs.copy()
            kw["headers"] = _HEADERS
            if (http := _get_http()) is None:
                raise ValueError("Unable to obtain http object")
            response, content = cast(Any, http).request(*args, **kw)
            assert isinstance(content, bytes)
            return response, content
        except ConnectionError:
            # Note that BrokenPipeError is a subclass of ConnectionError
            if attempts == MAX_ATTEMPTS - 1:
                # Give up and re-raise the original exception
                raise
            # Attempt recovery by creating a new httplib2.Http object and
            # forcing re-generation of the credentials
            _tls._HTTP = None
        except socket.timeout:
            # socket.timeout is not a subclass of ConnectionError
            # Make another attempt, then give up
            if attempts == MAX_ATTEMPTS - 1:
                # Give up and re-raise the original exception
                raise
        # Try again
        attempts += 1
    # Should not get here
    assert False, "Unexpected fall out of loop in firebase._request()"


def _init_firebase_app():
    """ Initialize a global Firebase app instance """
    global _firebase_app
    with _firebase_app_lock:
        if _firebase_app is None:
            _firebase_app = initialize_app(
                options=dict(projectId=PROJECT_ID, databaseURL=FIREBASE_DB_URL)
            )


def _firebase_put(  # type: ignore
    path: str, message: Optional[str] = None
) -> Tuple[httplib2.Response, bytes]:
    """ Writes data to Firebase.
    An HTTP PUT writes an entire object at the given database path. Updates to
    fields cannot be performed without overwriting the entire object
    Args:
        path - the url to the Firebase object to write.
        value - a json string.
    """
    return _request(path, method="PUT", body=message)


def _firebase_get(path: str) -> Tuple[httplib2.Response, bytes]:
    """ Read the data at the given path.
    An HTTP GET request allows reading of data at a particular path.
    A successful request will be indicated by a 200 OK HTTP status code.
    The response will contain the data being retrieved.
    Args:
        path - the url to the Firebase object to read.
    """
    return _request(path, method="GET")


def _firebase_patch(path: str, message: str) -> Tuple[httplib2.Response, bytes]:
    """ Update the data at the given path.
    An HTTP GET request allows reading of data at a particular path.
    A successful request will be indicated by a 200 OK HTTP status code.
    The response will contain the data being retrieved.
    Args:
        path - the url to the Firebase object to read.
    """
    return _request(path, method="PATCH", body=message)


def _firebase_delete(path: str) -> Tuple[httplib2.Response, bytes]:
    """ Delete the data at the given path.
    An HTTP DELETE request allows deleting of the data at the given path.
    A successful request will be indicated by a 200 OK HTTP status code.
    Args:
        path - the url to the Firebase object to delete.
    """
    return _request(path, method="DELETE")


def send_message(message: Optional[Mapping[str, Any]], *args: str) -> bool:
    """ Updates data in Firebase. If a message object is provided, then it updates
        the data at the given location (whose path is built as a concatenation
        of the *args list) with the message using the PATCH http method.
        If no message is provided, the data at this location is deleted
        using the DELETE http method.
    """
    try:
        if args:
            url = "/".join((FIREBASE_DB_URL,) + args) + ".json"
        else:
            url = f"{FIREBASE_DB_URL}/.json"
        if message is None:
            response, _ = _firebase_delete(path=url)
        else:
            response, _ = _firebase_patch(
                path=f"{url}?print=silent", message=json.dumps(message)
            )
        # If all is well and good, "200" (OK) or "204" (No Content)
        # is returned in the status field
        return response["status"] in ("200", "204")
    except httplib2.HttpLib2Error as e:
        logging.warning("Exception [{}] in firebase.send_message()".format(repr(e)))
        return False


def put_message(message: Optional[Mapping[str, Any]], *args: str) -> bool:
    """ Updates data in Firebase. If a message object is provided, then it sets
        the data at the given location (whose path is built as a concatenation
        of the *args list) with the message using the PUT http method.
        If no message is provided, the data at this location is deleted
        using the DELETE http method.
    """
    try:
        if args:
            url = "/".join((FIREBASE_DB_URL,) + args) + ".json"
        else:
            url = f"{FIREBASE_DB_URL}/.json"
        if message is None:
            response, _ = _firebase_delete(path=url)
        else:
            response, _ = _firebase_put(
                path=f"{url}?print=silent", message=json.dumps(message)
            )
        # If all is well and good, "200" (OK) or "204" (No Content)
        # is returned in the status field
        return response["status"] in ("200", "204")
    except httplib2.HttpLib2Error as e:
        logging.warning("Exception [{}] in firebase.put_message()".format(repr(e)))
        return False


def send_update(*args: str) -> bool:
    """ Updates the path endpoint to contain the current UTC timestamp """
    assert args, "Firebase path cannot be empty"
    endpoint = args[-1]
    value = {endpoint: datetime.utcnow().isoformat()}
    return send_message(value, *args[:-1])


def check_wait(user_id: str, opp_id: str) -> bool:
    """ Return True if the user user_id is waiting for the opponent opponent_id """
    try:
        url = f"{FIREBASE_DB_URL}/user/{user_id}/wait/{opp_id}.json"
        response, body = _firebase_get(path=url)
        if response["status"] != "200":
            return False
        msg = json.loads(body) if body else None
        return msg is True  # Return False if msg is dict, None or False
    except httplib2.HttpLib2Error as e:
        logging.warning(f"Exception [{repr(e)}] raised in firebase.check_wait()")
        return False


def check_presence(user_id: str) -> bool:
    """ Check whether the given user has at least one active connection """
    try:
        url = f"{FIREBASE_DB_URL}/connection/{user_id}.json"
        response, body = _firebase_get(path=url)
        if response["status"] != "200":
            return False
        msg = json.loads(body) if body else None
        return bool(msg)
    except httplib2.HttpLib2Error as e:
        logging.warning(f"Exception [{repr(e)}] raised in firebase.check_presence()")
        return False


def get_connected_users() -> Set[str]:
    """ Return a set of all presently connected users """
    with _USERLIST_LOCK:
        # Serialize access to the connected user list
        url = f"{FIREBASE_DB_URL}/connection.json?shallow=true"
        try:
            response, body = _firebase_get(path=url)
        except httplib2.HttpLib2Error as e:
            logging.warning(
                f"Exception [{repr(e)}] raised in firebase.get_connected_users()"
            )
            return set()
        if response["status"] != "200":
            return set()
        msg = json.loads(body) if body else None
        if not msg:
            return set()
        return set(msg.keys())


def create_custom_token(uid: str, valid_minutes: int = 60) -> str:
    """ Create a secure token for the given id.
        This method is used to create secure custom JWT tokens to be passed to
        clients. It takes a unique id that will be used by Firebase's
        security rules to prevent unauthorized access. """
    # Make sure that the Firebase app instance has been initialized
    _init_firebase_app()
    attempts = 0
    MAX_ATTEMPTS = 2
    while attempts < MAX_ATTEMPTS:
        try:
            return cast(Any, auth).create_custom_token(uid).decode()
        except:
            # It appears that ConnectionResetError exceptions can
            # propagate (wrapped in an obscure Firebase object) from
            # the call to create_custom_token()
            if attempts == MAX_ATTEMPTS - 1:
                raise
        attempts += 1
    assert False, "Unexpected fall out of loop in firebase.create_custom_token()"


_online_cache: Optional[Set[str]] = None
_online_ts: Optional[datetime] = None


def online_users() -> Set[str]:
    """Obtain a set of online users, by their user ids"""

    global _online_cache, _online_ts

    # First, use a per-process in-memory cache, having a lifetime of 1 minute
    now = datetime.utcnow()
    if (
        _online_ts is not None
        and _online_cache is not None
        and _online_ts > now - timedelta(minutes=_LIFETIME_MEMORY_CACHE)
    ):
        return _online_cache

    # Second, use the distributed Redis cache, having a lifetime of 10 minutes
    online: Union[Set[str], List[str]] = memcache.get("live", namespace="userlist")

    if not online:
        # Not found: do a Firebase query, which returns a set
        online = get_connected_users()
        # Store the result as a list in the Redis cache with a lifetime of 10 minutes
        memcache.set(
            "live", list(online), time=_LIFETIME_REDIS_CACHE * 60, namespace="userlist"
        )
    else:
        # Convert the cached list back into a set
        online = set(online)

    _online_cache = online
    _online_ts = now
    return online
