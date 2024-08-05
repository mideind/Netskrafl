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

from typing import (
    Any,
    Mapping,
    Optional,
    Set,
    cast,
)

import os
import threading
import logging

from firebase_admin import App, initialize_app, auth, db

from skrafldb import utcnow


_PROJECT_ID: str = os.environ.get("PROJECT_ID", "")

assert _PROJECT_ID, "PROJECT_ID environment variable not defined"

# Select Firebase database URL depending on project ID
_FIREBASE_DB: Mapping[str, str] = {
    "netskrafl": "https://netskrafl.firebaseio.com",
    "explo-dev": "https://explo-dev-default-rtdb.europe-west1.firebasedatabase.app/",
}
_FIREBASE_DB_URL: str = _FIREBASE_DB[_PROJECT_ID]

_firebase_app: Optional[App] = None
_firebase_app_lock = threading.Lock()


def init_firebase_app():
    """Initialize a global Firebase app instance"""
    global _firebase_app
    with _firebase_app_lock:
        if _firebase_app is None:
            _firebase_app = initialize_app(
                options=dict(projectId=_PROJECT_ID, databaseURL=_FIREBASE_DB_URL)
            )


def send_message(message: Optional[Mapping[str, Any]], *args: str) -> bool:
    """Updates data in Firebase. If a message object is provided, then it updates
    the data at the given location (whose path is built as a concatenation
    of the *args list) with the message using the PATCH http method.
    If no message is provided, the data at this location is deleted
    using the DELETE http method.
    """
    try:
        path = "/".join(args)
        ref = db.reference(path, app=_firebase_app)
        if message is None:
            ref.delete()
        else:
            ref.update(message)
        return True
    except Exception as e:
        logging.warning(f"Exception [{repr(e)}] in firebase.send_message()")
    return False


def put_message(message: Optional[Mapping[str, Any]], *args: str) -> bool:
    """Updates data in Firebase. If a message object is provided, then it sets
    the data at the given location (whose path is built as a concatenation
    of the *args list) with the message using the PUT http method.
    If no message is provided, the data at this location is deleted
    using the DELETE http method.
    """
    try:
        path = "/".join(args)
        ref = db.reference(path, app=_firebase_app)
        if message is None:
            ref.delete()
        else:
            ref.set(message)
        return True
    except Exception as e:
        logging.warning(f"Exception [{repr(e)}] in firebase.put_message()")
    return False


def send_update(*args: str) -> bool:
    """Updates the path endpoint to contain the current UTC timestamp"""
    if not args:
        return False
    endpoint = args[-1]
    value = {endpoint: utcnow().isoformat()}
    return send_message(value, *args[:-1])


def check_wait(user_id: str, opp_id: str, key: Optional[str] = None) -> bool:
    """Return True if the user user_id is waiting for the opponent opponent_id,
    on the challenge key, if given."""
    try:
        path = f"/user/{user_id}/wait/{opp_id}"
        ref = db.reference(path, app=_firebase_app)
        msg = ref.get()
        if msg is True:
            # The Firebase endpoint is set to True, meaning the user is waiting
            return True
        # Alternatively, the firebase endpoint may contain a key of the original challenge.
        # However, if it also contains a game id, the game has already been started
        # and the user is no longer waiting.
        if key is not None and isinstance(msg, dict):
            msg_dict = cast(Mapping[str, str], msg)
            if "game" not in msg_dict and key == msg_dict.get("key"):
                return True
    except Exception as e:
        logging.warning(f"Exception [{repr(e)}] raised in firebase.check_wait()")
    return False


def check_presence(user_id: str) -> bool:
    """Check whether the given user has at least one active connection"""
    try:
        path = f"/connection/{user_id}"
        ref = db.reference(path, app=_firebase_app)
        msg = ref.get(shallow=True)
        return bool(msg)
    except Exception as e:
        logging.warning(f"Exception [{repr(e)}] raised in firebase.check_presence()")
    return False


def get_connected_users() -> Set[str]:
    """Return a set of all presently connected users"""
    try:
        path = "/connection"
        ref = db.reference(path, app=_firebase_app)
        msg = cast(Mapping[str, str], ref.get(shallow=True))
    except Exception as e:
        logging.warning(
            f"Exception [{repr(e)}] raised in firebase.get_connected_users()"
        )
        return set()
    if not msg:
        return set()
    return set(msg.keys())


def create_custom_token(uid: str, valid_minutes: int = 60) -> str:
    """Create a secure token for the given id.
    This method is used to create secure custom JWT tokens to be passed to
    clients. It takes a unique id that will be used by Firebase's
    security rules to prevent unauthorized access."""
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
