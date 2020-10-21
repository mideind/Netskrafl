"""

    Billing manager for netskrafl.appspot.com

    Copyright (C) 2020 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The GNU General Public License, version 3, applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This module interfaces with web commerce services
    from SalesCloud to manage subscriptions for
    'friends of Netskrafl'.

"""

from typing import Optional

import os
import logging
import json

from datetime import datetime

import hashlib
import hmac

from flask import redirect, jsonify, url_for

import requests

from skraflgame import User


class _Secret:

    """ A wrapper for private and public key data used
        in communications with SalesCloud """

    _SC_SECRET_KEY: Optional[bytes] = None
    _SC_CLIENT_UUID: Optional[str] = None
    _SC_PUBLIC_KEY = "Netskrafl-Friend-Access"

    def __init__(self):
        pass

    @classmethod
    def load(cls):
        """ Fetch secret key and client UUID from a file """
        fname = os.path.join("resources", "salescloud_key.bin")
        try:
            with open(fname, "r", encoding="utf-8") as f:
                cls._SC_SECRET_KEY = f.readline().strip().encode("ascii")
                cls._SC_CLIENT_UUID = f.readline().strip()
        except Exception:
            logging.error("Unable to read file '{0}'".format(fname))
            cls._SC_SECRET_KEY = b""
            cls._SC_CLIENT_UUID = ""

    @property
    def key(self):
        """ Return the secret key value, which is a bytes object """
        if not self._SC_SECRET_KEY:
            _Secret.load()
        return self._SC_SECRET_KEY

    @property
    def uuid(self):
        """ Return the client UUID """
        if not self._SC_CLIENT_UUID:
            _Secret.load()
        return self._SC_CLIENT_UUID

    @property
    def public_key(self):
        """ Return Netskrafl's public key """
        return self._SC_PUBLIC_KEY


_SECRET = _Secret()


def request_valid(method, url, payload, xsc_date, xsc_key, xsc_digest, max_time=100.0):
    """ Validate an incoming request against our secret key. All parameters
        are assumed to be strings (str) except payload, which is bytes. """

    # Sanity check
    if not all((method, url, payload, xsc_date, xsc_key, xsc_digest)):
        return False

    # The public key must of course be correct
    if xsc_key != _SECRET.public_key:
        return False

    # Check the time stamp
    try:
        dt = datetime.strptime(xsc_date, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        # Invalid date/time
        return False
    delta = (datetime.utcnow() - dt).total_seconds()
    if not -2.0 < delta < max_time:
        # The request must be made in a time window ranging from 2 seconds in
        # the future (allowing for a slightly wrong clock) to 100 seconds in
        # the past (allowing time for the HTTP request to arrive and be
        # processed). Anything outside this will be rejected. This makes a
        # brute force attack on the SHA256 hash harder.
        logging.warning(
            "Billing request outside timestamp window, delta is {0:.1f}".format(delta)
        )
        return False
    # Reconstruct the signature, which is a bytes object
    xsc_signature = (xsc_date + xsc_key + method + url).encode("ascii") + payload
    # Hash it using the secret key
    my_digest = hmac.new(_SECRET.key, xsc_signature, hashlib.sha256).hexdigest()
    # Compare with the signature from the client and return True if they match
    if hasattr(hmac, "compare_digest"):
        # Better to use the compare_digest function, if available
        return hmac.compare_digest(xsc_digest, my_digest)
    return xsc_digest == my_digest


def cancel_friend(user):
    """ Cancel a friendship subscription by posting a HTTPS request to SalesCloud """
    try:
        url = "https://api.salescloud.is/webhooks/messenger/pull/" + _SECRET.uuid
        payload = dict(label=user.id())
        ts = datetime.utcnow().isoformat()
        ts = ts[0:10] + " " + ts[11:19]  # Example: '2016-10-26 16:10:84'
        method = "POST"
        signature = (ts + _SECRET.public_key + method + url).encode("ascii")
        # Hash the signature using the secret key
        digest = hmac.new(_SECRET.key, signature, hashlib.sha256)
        headers = {
            "Content-Type": "application/json",
            "X-SalesCloud-Date": ts,
            "X-SalesCloud-Access-Key": _SECRET.public_key,
            "X-SalesCloud-Signature": digest.hexdigest(),
        }
        result = requests.post(
            url, json=payload, headers=headers, timeout=30.0, allow_redirects=False
        )
        if result.status_code != 200:
            # Not OK
            logging.error(
                "Cancel friend request to SalesCloud failed with status {1} for user {0}".format(
                    user.id(), result.status_code
                )
            )
            return False
        response = result.json()
        # noinspection PySimplifyBooleanCheck,PyPep8
        if response.get("success") != True:
            logging.error(
                "Cancel friend request to SalesCloud failed for user {0}".format(
                    user.id()
                )
            )
            return False
        # Disable subscription, remove friend status
        user.set_friend(False)
        user.set_has_paid(False)
        user.update()
        logging.info("Removed user {0} as friend".format(user.id()))
    except requests.RequestException as ex:
        logging.error(
            "Exception when cancelling friend for user {1}: {0}".format(ex, user.id())
        )
        return False
    # Success
    return True


def handle(request, uid):
    """ Handle an incoming request to the /billing URL path """

    if request.method != "POST":
        # This is probably an incoming redirect from the SalesCloud IFRAME
        # after completing a payment form
        xsc_key = request.args.get("salescloud_access_key", "")[0:256]
        xsc_date = request.args.get("salescloud_date", "")[0:256]
        xsc_digest = request.args.get("salescloud_signature", "")[0:256]
        # pylint: disable=bad-continuation
        if not uid:
            logging.warning("uid is empty in billing.handle()")
        if not request_valid(
            request.method,
            request.base_url,
            uid.encode("ascii"),  # Payload
            xsc_date,
            xsc_key,
            xsc_digest,
            max_time=300.0,
        ):
            # Wrong signature: probably not coming from SalesCloud
            logging.warning(
                "Invalid signature in incoming redirect GET - url {0}".format(
                    request.base_url
                )
            )
            # !!! The signature from SalesCloud in this case does
            # !!! not agree with our calculation, so we leave it at that
            # return "<html><body>Invalid signature</body></html>", 403 # Forbidden
        return redirect(url_for("friend", action=0))  # Redirect to a thank-you page

    # Begin by validating the request by checking its signature
    xsc_key = request.headers.get("X-SalesCloud-Access-Key", "")[0:256]
    xsc_date = request.headers.get("X-SalesCloud-Date", "")[0:256]
    xsc_digest = request.headers.get("X-SalesCloud-Signature", "")[0:256]
    payload = b""
    try:
        # Do not accept request bodies larger than 2K
        if int(request.headers.get("Content-length", 0)) < 2048:
            payload = request.get_data(cache=False, as_text=False)
    except Exception as ex:
        # Something wrong with the Content-length header or the request body
        logging.error("Exception when obtaining payload: {0}".format(ex))
    # pylint: disable=bad-continuation
    if not request_valid(
        request.method, request.url, payload, xsc_date, xsc_key, xsc_digest
    ):
        logging.error("Invalid signature received")
        return jsonify(ok=False, reason="Invalid signature"), 403  # Forbidden

    # The request looks legit
    # Note: We can't use request.get_json() because we already read the data stream
    # using get_data() above
    j = json.loads(payload.decode("utf-8")) if payload else None
    # logging.info("/billing json is {0}".format(j))
    # Example billing POST:
    # {u'customer_label': u'', u'subscription_status': u'true', u'customer_id': u'34724',
    # u'after_renewal': u'2017-01-14T18:34:42+00:00',
    # u'before_renewal': u'2016-12-14T18:34:42+00:00',
    # u'product_id': u'479', u'type': u'subscription_updated'}
    if j is None:
        logging.error("Empty or illegal JSON")
        return jsonify(ok=False, reason="Empty or illegal JSON"), 400  # Bad request
    handled = False
    _FRIEND_OF_NETSKRAFL = "479"  # Product id for friend subscription
    # pylint: disable=bad-continuation
    if (
        j.get("type") in ("subscription_updated", "subscription_created")
        and j.get("product_id") == _FRIEND_OF_NETSKRAFL
    ):
        # Updating the subscription status of a user
        uid = j.get("customer_label")
        if uid and not isinstance(uid, str):
            uid = None
        if uid:
            uid = uid[0:32]  # Sanity cut-off
        user = User.load_if_exists(uid) if uid else None
        if user is None:
            logging.error(
                "Unknown or illegal user id: '{0}'".format(
                    "[None]" if uid is None else uid
                )
            )
            logging.info(
                "Original JSON from SalesCloud was:\n{0}"
                .format(payload.decode("utf-8"))
            )
            # We no longer return HTTP code 400, since this simply
            # makes SalesCloud repeat the request indefinitely
            return jsonify(
                ok=False,
                reason="Unknown or illegal user id (customer_label)"
            )
        status = j.get("subscription_status")
        if status == "true":
            # Enable subscription, mark as friend
            user.set_friend(True)
            user.set_has_paid(True)
            user.update()
            logging.info("Set user {0} as friend".format(uid))
            handled = True
        elif status == "false":
            # Disable subscription, remove friend status
            user.set_friend(False)
            user.set_has_paid(False)
            user.update()
            logging.info("Removed user {0} as friend".format(uid))
            handled = True
    if not handled:
        logging.warning(
            "/billing unknown request '{0}', did not handle".format(j.get("type"))
        )
    return jsonify(ok=True, handled=handled)
