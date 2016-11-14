# -*- coding: utf-8 -*-

""" Billing manager for netskrafl.appspot.com

    Author: Vilhjalmur Thorsteinsson, 2016

    This module interfaces with web commerce services
    from SalesCloud to manage subscriptions for
    'friends of Netskrafl'.

"""

import logging
import json

from datetime import datetime, timedelta

import hashlib
import hmac

from flask import render_template, redirect, jsonify
from flask import request, url_for

import google.appengine.api.urlfetch as urlfetch

from skraflgame import User


class _Secret:

    """ A wrapper for private and public key data used
        in communications with SalesCloud """

    _SC_SECRET_KEY = None
    _SC_CLIENT_UUID = None
    _SC_PUBLIC_KEY = "Netskrafl-Friend-Access"

    def __init__(self):
        pass

    @classmethod
    def load(cls):
        """ Fetch secret key and client UUID from a file """
        try:
            with open("resources/salescloud_key.bin", "r") as f:
                cls._SC_SECRET_KEY = f.readline().strip()
                cls._SC_CLIENT_UUID = f.readline().strip()
        except:
            logging.error(u"Unable to read file resources/salescloud_key.bin")
            cls._SC_SECRET_KEY = ""
            cls._SC_CLIENT_UUID = ""

    @property
    def key(self):
        if not self._SC_SECRET_KEY:
            _Secret.load()
        return self._SC_SECRET_KEY

    @property
    def uuid(self):
        if not self._SC_CLIENT_UUID:
            _Secret.load()
        return self._SC_CLIENT_UUID

    @property
    def public_key(self):
        return self._SC_PUBLIC_KEY


_SECRET = _Secret()


def request_valid(method, url, payload, xsc_date, xsc_key, xsc_digest):
    """ Validate an incoming request against our secret key """

    # Sanity check
    if not all((method, url, xsc_date, xsc_key, xsc_digest)):
        return False

    if payload is None:
        logging.error("Payload is None in request_valid")
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
    if not (-2.0 < delta < 60.0):
        # The request must be made in a time window ranging from 2 seconds in
        # the future (allowing for a slightly wrong clock) to 60 seconds in
        # the past (allowing time for the HTTP request to arrive and be
        # processed). Anything outside this will be rejected. This makes a
        # brute force attack on the SHA256 hash harder.
        logging.warning("Billing request outside timestamp window")
        return False
    # Reconstruct the signature
    xsc_signature = xsc_date + xsc_key + method + url + payload
    # Hash it using the secret key
    my_digest = hmac.new(_SECRET.key, xsc_signature, hashlib.sha256).hexdigest()
    # Compare with the signature from the client and return True if they match
    return hmac.compare_digest(xsc_digest, my_digest)


def cancel_friend(user):
    """ Cancel a friendship subscription by posting a HTTPS request to SalesCloud """
    try:
        url = 'https://api.salescloud.is/webhooks/messenger/pull/' + _SECRET.uuid
        payload = json.dumps(dict(label = user.id()))
        ts = datetime.utcnow().isoformat()
        ts = ts[0:10] + " " + ts[11:19] # Example: '2016-10-26 16:10:84'
        method = "POST"
        signature = ts + _SECRET.public_key + method + url # + payload
        # Hash the signature using the secret key
        digest = hmac.new(_SECRET.key, signature, hashlib.sha256).hexdigest()
        headers = {
            'Content-Type': 'application/json',
            'X-SalesCloud-Date' : ts,
            'X-SalesCloud-Access-Key' : _SECRET.public_key,
            'X-SalesCloud-Signature' : digest
        }
        result = urlfetch.fetch(
            url = url,
            follow_redirects = False,
            deadline = 30,
            payload = payload,
            method = urlfetch.POST,
            headers = headers,
            validate_certificate = True)
        if result.status_code != 200:
            # Not OK
            logging.error('Cancel friend request to SalesCloud failed with status {1} for user {0}'.format(user.id(), result.status_code))
            return False
        response = json.loads(result.content)
        if response.get("success") != True:
            logging.error('Cancel friend request to SalesCloud failed for user {0}'.format(user.id()))
            return False
        # Disable subscription, remove friend status
        user.set_friend(False)
        user.set_has_paid(False)
        user.update()
        logging.info("Removed user {0} as friend".format(user.id()))
    except urlfetch.Error as ex:
        logging.error('Exception when cancelling friend for user {1}: {0}'.format(ex, user.id()))
        return False
    # Success
    return True


def handle(request):
    """ Handle an incoming request to the /billing URL path """

    if request.method != 'POST':
        # This is probably an incoming redirect from the SalesCloud IFRAME
        # after completing a payment form
        xsc_key = request.args.get("salescloud_access_key", "")[0:256]
        xsc_date = request.args.get("salescloud_date", "")[0:256]
        xsc_digest = request.args.get("salescloud_signature", "")[0:256].encode('utf-8') # Required
        uid = User.current_id() or ""
        if not request_valid(request.method, request.base_url, uid, xsc_date, xsc_key, xsc_digest):
            # Wrong signature: probably not coming from SalesCloud
            return "<html><body>Invalid signature</body></html>", 403 # Forbidden
        return redirect(url_for("friend", action=0)) # Redirect to a thank-you page

    # Begin by validating the request by checking its signature
    xsc_key = request.headers.get("X-SalesCloud-Access-Key", "")[0:256]
    xsc_date = request.headers.get("X-SalesCloud-Date", "")[0:256]
    xsc_digest = request.headers.get("X-SalesCloud-Signature", "")[0:256].encode('utf-8') # Required
    payload = ""
    try:
        # Do not accept request bodies larger than 2K
        if int(request.headers.get("Content-length", 0)) < 2048:
            payload = request.get_data(cache=False, as_text=False)
    except Exception as ex:
        # Something wrong with the Content-length header or the request body
        logging.error("Exception when obtaining payload: {0}".format(ex))
    if not request_valid(request.method, request.url, payload, xsc_date, xsc_key, xsc_digest):
        logging.error("Invalid signature received")
        return jsonify(ok = False, reason = "Invalid signature"), 403 # Forbidden

    # The request looks legit
    # Note: We can't use request.get_json() because we already read the data stream
    # using get_data() above
    j = json.loads(payload.decode('utf-8')) if payload else None
    # logging.info("/billing json is {0}".format(j))
    # Example billing POST:
    # {u'customer_label': u'', u'subscription_status': u'true', u'customer_id': u'34724', u'after_renewal': u'2017-01-14T18:34:42+00:00',
    # u'before_renewal': u'2016-12-14T18:34:42+00:00', u'product_id': u'479', u'type': u'subscription_updated'}
    if j is None:
        return jsonify(ok = False, reason = u"Empty or illegal JSON")
    handled = False
    _FRIEND_OF_NETSKRAFL = u"479" # Product id for friend subscription
    if j.get(u"type") in (u"subscription_updated", u"subscription_created") \
        and j.get(u"product_id") == _FRIEND_OF_NETSKRAFL:
        # Updating the subscription status of a user
        uid = j.get(u"customer_label")
        if uid and not isinstance(uid, basestring):
            uid = None
        if uid:
            uid = uid[0:32] # Sanity cut-off
        user = User.load_if_exists(uid) if uid else None
        if user is None:
            return jsonify(ok = False, reason = u"Unknown or illegal user id")
        if j.get(u"subscription_status") == u"true":
            # Enable subscription, mark as friend
            user.set_friend(True)
            user.set_has_paid(True)
            user.update()
            logging.info("Set user {0} as friend".format(uid))
            handled = True
        elif j.get(u"subscription_status") == u"false":
            # Disable subscription, remove friend status
            user.set_friend(False)
            user.set_has_paid(False)
            user.update()
            logging.info("Removed user {0} as friend".format(uid))
            handled = True
    if not handled:
        logging.warning("/billing unknown request '{0}', did not handle".format(j.get(u"type")))
    return jsonify(ok = True, handled = handled)



