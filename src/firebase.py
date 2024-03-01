"""

    Firebase wrapper for Netskrafl

    Copyright (C) 2024 Miðeind ehf.
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
    Iterable,
    Mapping,
    NotRequired,
    Optional,
    List,
    Required,
    Sequence,
    TypedDict,
    Set,
    Dict,
    cast,
)

import threading
import logging
from datetime import datetime, timedelta
from flask import Blueprint, request

from firebase_admin import App, initialize_app, auth, messaging, db  # type: ignore
from firebase_admin.exceptions import FirebaseError  # type: ignore
from firebase_admin.messaging import UnregisteredError  # type: ignore

from config import PROJECT_ID, FIREBASE_DB_URL, running_local, ResponseType, ttl_cache
from languages import SUPPORTED_LOCALES
from cache import memcache


OnlineStatusFunc = Callable[[Iterable[str]], Iterable[bool]]

PushMessageCallable = Callable[[str], str]
PushDataDict = Mapping[str, Any]


class PushMessageDict(TypedDict):
    """A message to be sent to a device via a push notification"""

    title: PushMessageCallable
    body: PushMessageCallable
    image: NotRequired[PushMessageCallable]  # Image URL


# Expiration of user online status, in seconds
_CONNECTED_EXPIRY = 2 * 60  # 2 minutes

# We don't send push notification messages to sessions
# that are older than the following constant indicates
_PUSH_NOTIFICATION_CUTOFF = 14  # Days

_firebase_app: Optional[App] = None
_firebase_app_lock = threading.Lock()

# Create a blueprint for the connect module, which is used to
# update the Redis cache from Firebase presence information
# using a cron job that calls /connect/update
connect_blueprint = connect = Blueprint("connect", __name__, url_prefix="/connect")


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
    assert (
        len(locale) == 5 and "_" in locale
    ), "Locale string is expected to have format 'xx_XX'"
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


class OnlineStatus:
    """This class implements a wrapper for queries about the
    online status of users by locale. The wrapper talks to the
    Redis cache, which is updated from Firebase by a cron job."""

    def __init__(self, locale: str) -> None:
        # Assign the Redis key used for the set of online users
        # for this locale
        self._key = "live:" + locale

    def users_online(self, user_ids: Iterable[str]) -> List[bool]:
        """Return a list of booleans, one for each passed user_id"""
        return memcache.query_set(self._key, list(user_ids))

    def user_online(self, user_id: str) -> bool:
        """Return True if a user is online"""
        return self.users_online([user_id])[0]

    @ttl_cache(seconds=30)  # Cache this data for 30 seconds
    @staticmethod
    def _get_random_sample(key: str, n: int) -> List[str]:
        """Return a cached random sample of <= n online users"""
        return memcache.random_sample_from_set(key, n)

    def random_sample(self, n: int) -> List[str]:
        """Return a random sample of <= n online users"""
        return OnlineStatus._get_random_sample(self._key, n)


# Collection of OnlineStatus instances, one for each game locale
_online_status: Dict[str, OnlineStatus] = dict()


def online_status(locale: str) -> OnlineStatus:
    """Obtain an user online status wrapper for a particular locale"""
    global _online_status
    if (oc := _online_status.get(locale)) is None:
        oc = OnlineStatus(locale)
        _online_status[locale] = oc
    return oc


class UserLiveDict(TypedDict):
    """A dictionary that has at least a 'live' property, of type bool"""

    live: Required[bool]


def set_online_status(
    user_id_prop: str,
    users: Sequence[UserLiveDict],
    func_online_status: OnlineStatusFunc,
) -> None:
    """Set the live (online) status of the users in the list"""
    # Call the function to get the online status of the users
    # TODO: We are passing in empty strings for robot players, which is a
    # fairly common occurrence. The robots are never marked as online, so
    # the Redis roundtrip is unnecessary. We should optimize this.
    online = func_online_status(cast(str, u.get(user_id_prop) or "") for u in users)
    # Set the live status of the users in the list
    for u, o in zip(users, online):
        u["live"] = bool(o)


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


@connect.route("/update", methods=["GET"])
def update() -> ResponseType:
    """Update the Redis cache from Firebase presence information.
    This method is invoked from a cron job that fetches /connect/update."""
    # Check that we are actually being called internally by
    # a GAE cron job or a cloud scheduler
    headers = request.headers
    task_queue = headers.get("X-AppEngine-QueueName", "") != ""
    cron_job = headers.get("X-Appengine-Cron", "") == "true"
    cloud_scheduler = request.environ.get("HTTP_X_CLOUDSCHEDULER", "") == "true"
    if not any((running_local, task_queue, cloud_scheduler, cron_job)):
        # Not called internally, by a cron job or a cloud scheduler
        return "Error", 403  # Forbidden
    try:
        # Get the list of all connected users from Firebase,
        # for each supported game locale
        for locale in SUPPORTED_LOCALES:
            online = get_connected_users(locale)
            # Store the result in a Redis set, with an expiry
            if not memcache.init_set("live:" + locale, online, time=_CONNECTED_EXPIRY):
                logging.warning(
                    f"Unable to update Redis connection cache for locale {locale}"
                )
        return "OK", 200
    except Exception as e:
        logging.warning(f"Exception [{repr(e)}] raised in firebase.update()")
    return "Error", 500
