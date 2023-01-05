"""

    Configuration data

    Copyright (C) 2021 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl


    This module reads a number of configuration parameters
    from environment variables and config files.

"""

from __future__ import annotations

from typing import Dict

import os
from flask import json

# Are we running in a local development environment or on a GAE server?
running_local: bool = os.environ.get("SERVER_SOFTWARE", "").startswith("Development")
# Set SERVER_HOST to 0.0.0.0 to accept HTTP connections from the outside
host: str = os.environ.get("SERVER_HOST", "127.0.0.1")
port: str = os.environ.get("SERVER_PORT", "8080")

# App Engine (and Firebase) project id
PROJECT_ID = os.environ.get("PROJECT_ID", "")
assert PROJECT_ID, "PROJECT_ID environment variable not set"

DEFAULT_LOCALE = "is_IS" if PROJECT_ID == "netskrafl" else "en_US"

DEFAULT_OAUTH_CONF_URL = "https://accounts.google.com/.well-known/openid-configuration"

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
    WEB_CLIENT = CLIENT.get("web", {})

    CLIENT_ID = WEB_CLIENT.get("id", "")
    CLIENT_SECRET = WEB_CLIENT.get("secret", "")
    assert CLIENT_ID, f"CLIENT.web.id not set correctly in {CLIENT_SECRET_FILE}"
    assert CLIENT_SECRET, f"CLIENT.web.secret not set correctly in {CLIENT_SECRET_FILE}"

    OAUTH_CONF_URL = WEB_CLIENT.get("auth_uri", DEFAULT_OAUTH_CONF_URL)

    # Analytics measurement id
    MEASUREMENT_ID = j.get("MEASUREMENT_ID", "")
    assert MEASUREMENT_ID, "MEASUREMENT_ID environment variable not set"

    # Facebook app token, for login verification calls to the graph API
    FACEBOOK_APP_ID = j.get("FACEBOOK_APP_ID", "")
    FACEBOOK_APP_SECRET = j.get("FACEBOOK_APP_SECRET", "")
    assert FACEBOOK_APP_SECRET, "FACEBOOK_APP_SECRET environment variable not set"
    assert FACEBOOK_APP_ID, "FACEBOOK_APP_ID environment variable not set"

    # Firebase configuration
    FIREBASE_API_KEY = j.get("FIREBASE_API_KEY", "")
    FIREBASE_SENDER_ID = j.get("FIREBASE_SENDER_ID", "")
    FIREBASE_DB_URL = j.get("FIREBASE_DB_URL", "")
    FIREBASE_APP_ID = j.get("FIREBASE_APP_ID", "")
    assert FIREBASE_API_KEY, "FIREBASE_API_KEY environment variable not set"
    assert FIREBASE_SENDER_ID, "FIREBASE_SENDER_ID environment variable not set"
    assert FIREBASE_DB_URL, "FIREBASE_DB_URL environment variable not set"
    assert FIREBASE_APP_ID, "FIREBASE_APP_ID environment variable not set"

    # Apple ID configuration
    APPLE_KEY_ID = j.get("APPLE_KEY_ID", "")
    APPLE_TEAM_ID = j.get("APPLE_TEAM_ID", "")
    APPLE_CLIENT_ID = j.get("APPLE_CLIENT_ID", "")
    assert APPLE_KEY_ID, "APPLE_KEY_ID environment variable not set"
    assert APPLE_TEAM_ID, "APPLE_TEAM_ID environment variable not set"
    assert APPLE_CLIENT_ID, "APPLE_CLIENT_ID environment variable not set"


# Valid token issuers for OAuth2 login
VALID_ISSUERS = frozenset(("accounts.google.com", "https://accounts.google.com"))

# How many games a player plays as a provisional player
# before becoming an established one
ESTABLISHED_MARK: int = 10
