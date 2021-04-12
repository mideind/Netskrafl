"""

    Firebase wrapper for Netskrafl

    Copyright (C) 2021 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The GNU General Public License, version 3, applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This module implements a thin wrapper around the Google Firebase
    functionality used to send push notifications to clients.

"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence, Tuple, Set, Dict

import os
import json
import threading
import logging
import socket
from datetime import datetime

import httplib2  # type: ignore

from oauth2client.client import GoogleCredentials  # type: ignore

from firebase_admin import App, initialize_app, auth  # type: ignore


_PROJECT_ID: str = os.environ.get("PROJECT_ID", "")

assert _PROJECT_ID, "PROJECT_ID environment variable not defined"

# Select Firebase database URL depending on project ID
_FIREBASE_DB: Mapping[str, str] = {
    "netskrafl": "https://netskrafl.firebaseio.com",
    "explo-dev": "https://explo-dev-default-rtdb.europe-west1.firebasedatabase.app/",
}
_FIREBASE_DB_URL: str = _FIREBASE_DB[_PROJECT_ID]

_FIREBASE_SCOPES: Sequence[str] = [
    "https://www.googleapis.com/auth/firebase.database",
    "https://www.googleapis.com/auth/userinfo.email",
]
_TIMEOUT: int = 15  # Seconds

_HEADERS: Mapping[str, str] = {"Connection": "keep-alive"}

# Initialize thread-local storage
_tls = threading.local()


def _get_http() -> httplib2.Http:
    """ Provides an authorized HTTP object, one per thread """
    if not hasattr(_tls, "_HTTP") or _tls._HTTP is None:
        http = httplib2.Http(timeout=_TIMEOUT)
        # Use application default credentials to make the Firebase calls
        # https://firebase.google.com/docs/reference/rest/database/user-auth
        creds = GoogleCredentials.get_application_default().create_scoped(
            _FIREBASE_SCOPES
        )
        creds.authorize(http)
        creds.refresh(http)
        _tls._HTTP = http
    return _tls._HTTP


def _request(*args: Any, **kwargs: Any) -> Tuple[httplib2.Response, bytes]:
    """ Attempt to post a Firebase request, with recovery on a ConnectionError """
    MAX_ATTEMPTS = 2
    attempts = 0
    while attempts < MAX_ATTEMPTS:
        try:
            kw: Dict[str, Any] = kwargs.copy()
            kw["headers"] = _HEADERS
            response, content = _get_http().request(*args, **kw)
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


def _firebase_put(
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
            url = "/".join((_FIREBASE_DB_URL,) + args) + ".json"
        else:
            url = _FIREBASE_DB_URL + "/.json"
        if message is None:
            response, _ = _firebase_delete(path=url)
        else:
            response, _ = _firebase_patch(
                path=url + "?print=silent", message=json.dumps(message)
            )
        # If all is well and good, "200" (OK) or "204" (No Content)
        # is returned in the status field
        return response["status"] in ("200", "204")
    except httplib2.HttpLib2Error as e:
        logging.warning("Exception [{}] in firebase.send_message()".format(repr(e)))
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
        url = "{}/user/{}/wait/{}.json".format(_FIREBASE_DB_URL, user_id, opp_id)
        response, body = _firebase_get(path=url)
        if response["status"] != "200":
            return False
        msg = json.loads(body) if body else None
        return msg is True  # Return False if msg is dict, None or False
    except httplib2.HttpLib2Error as e:
        logging.warning(
            "Exception [{}] raised in firebase.check_wait()".format(repr(e))
        )
        return False


def check_presence(user_id: str) -> bool:
    """ Check whether the given user has at least one active connection """
    try:
        url = "{}/connection/{}.json".format(_FIREBASE_DB_URL, user_id)
        response, body = _firebase_get(path=url)
        if response["status"] != "200":
            return False
        msg = json.loads(body) if body else None
        return bool(msg)
    except httplib2.HttpLib2Error as e:
        logging.warning(
            "Exception [{}] raised in firebase.check_presence()".format(repr(e))
        )
        return False


_USERLIST_LOCK = threading.Lock()


def get_connected_users() -> Set[str]:
    """ Return a set of all presently connected users """
    with _USERLIST_LOCK:
        # Serialize access to the connected user list
        url = "{}/connection.json?shallow=true".format(_FIREBASE_DB_URL)
        try:
            response, body = _firebase_get(path=url)
        except httplib2.HttpLib2Error as e:
            logging.warning(
                "Exception [{}] raised in firebase.get_connected_users()".format(
                    repr(e)
                )
            )
            return set()
        if response["status"] != "200":
            return set()
        msg = json.loads(body) if body else None
        if not msg:
            return set()
        return set(msg.keys())


_firebase_app: Optional[App] = None


def create_custom_token(uid: str, valid_minutes: int = 60) -> bytes:
    """ Create a secure token for the given id.

        This method is used to create secure custom JWT tokens to be passed to
        clients. It takes a unique id that will be used by Firebase's
        security rules to prevent unauthorized access. In this case, the uid will
        be the channel id which is a combination of a user id and a game id.
    """
    global _firebase_app
    if _firebase_app is None:
        _firebase_app = initialize_app()
    attempts = 0
    MAX_ATTEMPTS = 2
    while attempts < MAX_ATTEMPTS:
        try:
            return auth.create_custom_token(uid).decode()
        except:
            # It appears that ConnectionResetError exceptions can
            # propagate (wrapped in an obscure Firebase object) from
            # the call to create_custom_token()
            if attempts == MAX_ATTEMPTS - 1:
                raise
        attempts += 1
    assert False, "Unexpected fall out of loop in firebase.create_custom_token()"
