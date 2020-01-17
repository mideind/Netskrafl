# -*- coding: utf-8 -*-

"""

    Users - User management shim for the Netskrafl application

    Copyright (C) 2020 Miðeind ehf.
    Author: Vilhjálmur Þorsteinsson

    This module wraps user management in a thin wrapper object,
    roughly emulating the original GAE users module.

"""

from flask import session


class UserShim:

    def __init__(self, user_id):
        self._user_id = user_id
        self._nickname = ""
        self._email = ""

    def user_id(self):
        return self._user_id

    def nickname(self):
        return self._nickname

    def email(self):
        return self._email


def get_current_user():
    user = session.get("user")
    if user is None:
        return None
    # !!! Check the expiration
    return UserShim(user["id"])


def create_logout_url(url):
    return url


def create_login_url(url):
    return url
