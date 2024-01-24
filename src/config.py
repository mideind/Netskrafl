"""

    Configuration data

    Copyright (C) 2023 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl


    This module reads a number of configuration parameters
    from environment variables and config files.

"""

from __future__ import annotations

from typing import Dict, Literal, Mapping, NotRequired, Optional, TypedDict
from datetime import timedelta
import os
from flask import json


class FlaskConfig(TypedDict):
    """The Flask configuration dictionary"""
    DEBUG: bool
    SESSION_COOKIE_DOMAIN: Optional[str]
    SESSION_COOKIE_SECURE: bool
    SESSION_COOKIE_HTTPONLY: bool
    SESSION_COOKIE_SAMESITE: Literal["Strict", "Lax", "None"]
    PERMANENT_SESSION_LIFETIME: timedelta
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    JSON_AS_ASCII: bool
    TESTING: NotRequired[bool]


# Are we running in a local development environment or on a GAE server?
running_local: bool = os.environ.get("SERVER_SOFTWARE", "").startswith("Development")
# Set SERVER_HOST to 0.0.0.0 to accept HTTP connections from the outside
host: str = os.environ.get("SERVER_HOST", "127.0.0.1")
port: str = os.environ.get("SERVER_PORT", "8080")

# App Engine (and Firebase) project id
PROJECT_ID = os.environ.get("PROJECT_ID", "")
assert PROJECT_ID, "PROJECT_ID environment variable not set"

DEV_SERVER = PROJECT_ID == "explo-dev"

DEFAULT_LOCALE = "is_IS" if PROJECT_ID == "netskrafl" else "en_US"

DEFAULT_OAUTH_CONF_URL = "https://accounts.google.com/.well-known/openid-configuration"

# Obtain the domain to use for HTTP session cookies
COOKIE_DOMAIN = {
    "netskrafl": ".netskrafl.is",
    "explo-dev": ".explo-dev.appspot.com",
    "explo-live": ".explo-live.appspot.com",
}.get(PROJECT_ID, ".netskrafl.is")

# Open the correct client_secret file for the project (Explo/Netskrafl)
CLIENT_SECRET_FILE = {
    "netskrafl": "client_secret_netskrafl.json",
    "explo-dev": "client_secret_explo.json",
    "explo-live": "client_secret_explo_live.json",
}.get(PROJECT_ID, "client_secret.json")

# Read client secrets (some of which aren't really that secret) from JSON file
with open(os.path.join("resources", CLIENT_SECRET_FILE), "r") as f:
    j = json.loads(f.read())
    assert j is not None

    # Client types and their ids (and secrets, as applicable)
    CLIENT: Dict[str, Dict[str, str]] = j.get("CLIENT", {})
    WEB_CLIENT: Mapping[str, str] = CLIENT.get("web", {})

    CLIENT_ID = WEB_CLIENT.get("id", "")
    CLIENT_SECRET = WEB_CLIENT.get("secret", "")
    assert CLIENT_ID, f"CLIENT.web.id not set correctly in {CLIENT_SECRET_FILE}"
    assert CLIENT_SECRET, f"CLIENT.web.secret not set correctly in {CLIENT_SECRET_FILE}"

    # Explo client secret, used as a key for signing our own JWTs
    # that are used to extend the validity of third party auth tokens
    EXPLO_CLIENT: Mapping[str, str] = CLIENT.get("explo", {})
    EXPLO_CLIENT_SECRET = EXPLO_CLIENT.get("secret", "")

    OAUTH_CONF_URL = WEB_CLIENT.get("auth_uri", DEFAULT_OAUTH_CONF_URL)

    # Analytics measurement id
    MEASUREMENT_ID: str = j.get("MEASUREMENT_ID", "")
    assert MEASUREMENT_ID, "MEASUREMENT_ID environment variable not set"

    # Facebook app token, for login verification calls to the graph API
    FACEBOOK_APP_ID: Mapping[str, str] = j.get("FACEBOOK_APP_ID", {})
    FACEBOOK_APP_SECRET: Mapping[str, str] = j.get("FACEBOOK_APP_SECRET", {})
    assert FACEBOOK_APP_SECRET, f"FACEBOOK_APP_SECRET not set correctly in {CLIENT_SECRET_FILE}"
    assert FACEBOOK_APP_ID, f"FACEBOOK_APP_ID not set correctly in {CLIENT_SECRET_FILE}"

    # Firebase configuration
    FIREBASE_API_KEY: str = j.get("FIREBASE_API_KEY", "")
    FIREBASE_SENDER_ID: str = j.get("FIREBASE_SENDER_ID", "")
    FIREBASE_DB_URL: str = j.get("FIREBASE_DB_URL", "")
    FIREBASE_APP_ID: str = j.get("FIREBASE_APP_ID", "")
    assert FIREBASE_API_KEY, f"FIREBASE_API_KEY not set correctly in {CLIENT_SECRET_FILE}"
    assert FIREBASE_SENDER_ID, f"FIREBASE_SENDER_ID not set correctly in {CLIENT_SECRET_FILE}"
    assert FIREBASE_DB_URL, f"FIREBASE_DB_URL not set correctly in {CLIENT_SECRET_FILE}"
    assert FIREBASE_APP_ID, f"FIREBASE_APP_ID not set correctly in {CLIENT_SECRET_FILE}"

    # Apple ID configuration
    APPLE_KEY_ID: str = j.get("APPLE_KEY_ID", "")
    APPLE_TEAM_ID: str = j.get("APPLE_TEAM_ID", "")
    APPLE_CLIENT_ID: str = j.get("APPLE_CLIENT_ID", "")
    assert APPLE_KEY_ID, f"APPLE_KEY_ID not set correctly in {CLIENT_SECRET_FILE}"
    assert APPLE_TEAM_ID, f"APPLE_TEAM_ID not set correctly in {CLIENT_SECRET_FILE}"
    assert APPLE_CLIENT_ID, f"APPLE_CLIENT_ID not set correctly in {CLIENT_SECRET_FILE}"

    # RevenueCat bearer token
    RC_WEBHOOK_AUTH: str = j.get("RC_WEBHOOK_AUTH", "")


# Read the Flask secret session key from file
with open(os.path.join("resources", "secret_key.bin"), "rb") as f:
    FLASK_SESSION_KEY = f.read()
    assert len(FLASK_SESSION_KEY) == 64, "Flask session key is expected to be 64 bytes"


# Valid token issuers for OAuth2 login
VALID_ISSUERS = frozenset(("accounts.google.com", "https://accounts.google.com"))

# How many games a player plays as a provisional player
# before becoming an established one
ESTABLISHED_MARK: int = 10
