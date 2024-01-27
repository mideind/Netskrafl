"""

    Firebase wrapper for Netskrafl

    Copyright (C) 2023 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This module implements a thin wrapper around the Google Firebase
    functionality used to send push notifications to clients.

"""

from __future__ import annotations

from typing import (
    Any,
    Callable,
    Mapping,
    NotRequired,
    Optional,
    List,
    TypedDict,
    Union,
    Set,
    Dict,
    cast,
)

import threading
import logging
from datetime import datetime, timedelta

from firebase_admin import App, initialize_app, auth, messaging, db  # type: ignore
from firebase_admin.exceptions import FirebaseError  # type: ignore
from firebase_admin.messaging import UnregisteredError  # type: ignore

from config import PROJECT_ID, FIREBASE_DB_URL
from cache import memcache


PushMessageCallable = Callable[[str], str]
PushDataDict = Mapping[str, Any]


class PushMessageDict(TypedDict):

    """A message to be sent to a device via a push notification"""

    title: PushMessageCallable
    body: PushMessageCallable
    image: NotRequired[PushMessageCallable]  # Image URL


_LIFETIME_MEMORY_CACHE = 1  # Minutes
_LIFETIME_REDIS_CACHE = 5  # Minutes

# We don't send push notification messages to sessions
# that are older than the following constant indicates
_PUSH_NOTIFICATION_CUTOFF = 14  # Days

_USERLIST_LOCK = threading.Lock()

_firebase_app: Optional[App] = None
_firebase_app_lock = threading.Lock()


def init_firebase_app():
    """Initialize a global Firebase app instance"""
    global _firebase_app
    with _firebase_app_lock:
        if _firebase_app is None:
            _firebase_app = initialize_app(
                options=dict(projectId=PROJECT_ID, databaseURL=FIREBASE_DB_URL)
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
        ref = cast(Any, db).reference(path, app=_firebase_app)
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
        ref = cast(Any, db).reference(path, app=_firebase_app)
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
    value = {endpoint: datetime.utcnow().isoformat()}
    return send_message(value, *args[:-1])


def check_wait(user_id: str, opp_id: str, key: Optional[str]) -> bool:
    """Return True if the user user_id is waiting for the opponent opponent_id,
    on the challenge key, if given."""
    try:
        path = f"/user/{user_id}/wait/{opp_id}"
        ref = cast(Any, db).reference(path, app=_firebase_app)
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


def check_presence(user_id: str, locale: str) -> bool:
    """Check whether the given user has at least one active connection"""
    try:
        path = f"/connection/{locale}/{user_id}"
        ref = cast(Any, db).reference(path, app=_firebase_app)
        msg = ref.get(shallow=True)
        return bool(msg)
    except Exception as e:
        logging.warning(f"Exception [{repr(e)}] raised in firebase.check_presence()")
    return False


def get_connected_users(locale: str) -> Set[str]:
    """Return a set of all presently connected users"""
    try:
        path = f"/connection/{locale}"
        ref = cast(Any, db).reference(path, app=_firebase_app)
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
            return cast(Any, auth).create_custom_token(uid).decode()
        except:
            # It appears that ConnectionResetError exceptions can
            # propagate (wrapped in an obscure Firebase object) from
            # the call to create_custom_token()
            if attempts == MAX_ATTEMPTS - 1:
                raise
        attempts += 1
    assert False, "Unexpected fall out of loop in firebase.create_custom_token()"


_online_cache: Dict[str, Set[str]] = dict()
_online_ts: Dict[str, datetime] = dict()
_online_counter: int = 0


def online_users(locale: str) -> Set[str]:
    """Obtain a set of online users, by their user ids"""

    global _online_cache, _online_ts, _online_counter

    # First, use a per-process in-memory cache, having a lifetime of 1 minute
    now = datetime.utcnow()
    if (
        locale in _online_ts
        and locale in _online_cache
        and _online_ts[locale] > now - timedelta(minutes=_LIFETIME_MEMORY_CACHE)
    ):
        return _online_cache[locale]

    # Serialize access to the connected user list
    # !!! TBD: Convert this to a background task that periodically
    # updates the Redis cache from the Firebase database
    with _USERLIST_LOCK:

        # Use the distributed Redis cache, having a lifetime of 5 minutes
        online: Union[None, Set[str], List[str]] = memcache.get(
            "live:" + locale, namespace="userlist"
        )

        if online is None:
            # Not found: do a Firebase query, which returns a set
            online = get_connected_users(locale)
            # Store the result as a list in the Redis cache, with a timeout
            memcache.set(
                "live:" + locale,
                list(online),
                time=_LIFETIME_REDIS_CACHE * 60,  # Currently 5 minutes
                namespace="userlist",
            )
            _online_counter += 1
            if _online_counter >= 6:
                # Approximately once per half hour (6 * 5 minutes),
                # log number of connected users
                logging.info(f"Connected users in locale {locale} are {len(online)}")
                _online_counter = 0
        else:
            # Convert the cached list back into a set
            online = set(online)

        _online_cache[locale] = online
        _online_ts[locale] = now

    return online


def push_notification(
    device_token: str, message: Mapping[str, str], data: Optional[PushDataDict]
) -> bool:
    """Send a Firebase push notification to a particular device,
    identified by device token. The message is a dictionary that
    contains a title and a body."""
    if not device_token:
        return False

    # Construct the message
    msg = messaging.Message(
        notification=messaging.Notification(**message),
        token=device_token,
        data=data,
        apns=messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(content_available=True),
            ),
        ),
    )

    # Send the message
    try:
        message_id: str = cast(Any, messaging).send(msg, app=_firebase_app)
        # The response is a message ID string
        return bool(message_id)
    except UnregisteredError as e:
        logging.info(
            f"Unregistered device token ('{device_token}') in firebase.push_notification()"
        )
    except (FirebaseError, ValueError) as e:
        logging.warning(f"Exception [{repr(e)}] raised in firebase.push_notification()")

    return False


def push_to_user(
    user_id: str, message: PushMessageDict, data: Optional[PushDataDict]
) -> bool:
    """Send a Firebase push notification to a particular user,
    identified by user id. The message is a dictionary that
    contains at least a title and a body."""
    if not user_id:
        return False
    # A user's sessions are found under the /session/<user_id> path,
    # containing 0..N sessions. Each session has a token as its key,
    # and contains a dictionary with the OS and the timestamp of the session.
    # We need to iterate over all sessions and send the message to each
    # device token, after localizing it for the UI locale of the session.
    try:
        path = f"/session/{user_id}"
        ref: db.Reference = cast(Any, db).reference(path, app=_firebase_app)
        msg: Mapping[str, Mapping[str, str]] = cast(Any, ref).get()
        if not msg:
            return False
        # We don't send notifications to sessions that are older than 14 days
        cutoff = datetime.utcnow() - timedelta(days=_PUSH_NOTIFICATION_CUTOFF)
        # msg is a dictionary of device tokens : { os, utc, locale }
        raw_message = cast(Mapping[str, PushMessageCallable], message)
        for device_token, device_info in msg.items():
            # os = device_info.get("os") or ""
            if not isinstance(device_info, dict):
                continue
            utc = device_info.get("utc") or ""
            if not utc:
                continue
            # Format the string so that Python can parse it
            # (the original string is generated in JavaScript code and
            # is not ISO 8601 compliant as far as Python is concerned)
            utc = utc[0:19]
            if datetime.fromisoformat(utc) < cutoff:
                # The session token is too old
                # logging.info("Skipping notification, session token is too old")
                continue
            # Localize the message for this session
            locale = device_info.get("locale") or "en"
            localized_message = {
                key: text_func(locale) for key, text_func in raw_message.items()
            }
            # Send the push notification via Firebase
            if not push_notification(device_token, localized_message, data):
                # The device token has become invalid:
                # delete this node from the Firebase tree to prevent
                # further attempts to send notifications to it
                path = f"/session/{user_id}/{device_token}"
                try:
                    ref = cast(Any, db).reference(path, app=_firebase_app)
                    ref.delete()
                except Exception as e:
                    logging.warning(
                        f"Failed to delete node '{path}' in firebase.push_to_user()"
                    )
        return True
    except Exception as e:
        logging.warning(f"Exception [{repr(e)}] raised in firebase.push_to_user()")
    return False
