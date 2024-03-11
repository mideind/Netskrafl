"""

    Tests for Netskrafl / Explo Word Game
    Copyright (C) 2024 Miðeind ehf.

    This module tests several APIs by submitting HTTP requests
    to the Netskrafl / Explo server.

"""

import json

from utils import CustomClient, decode_cookie, login_anonymous_user
from utils import client, u1, u2, u3_gb  # type: ignore


def test_anonymous_login(client: CustomClient) -> None:
    """Test the anonymous login functionality"""
    # Should fail if the proper authorization header was not provided
    resp = login_anonymous_user(client, 1)
    assert resp.status_code == 401  # Unauthorized
    # Try again with the proper authorization header
    client.set_authorization(True)
    resp = login_anonymous_user(client, 1, locale="en_US")
    client.set_authorization(False)
    assert resp.status_code == 200
    assert resp.json is not None
    assert "status" in resp.json
    assert resp.json["status"] == "success"
    assert "account" in resp.json
    assert resp.json.get("locale", "") == "en_US"
    assert "token" in resp.json
    assert "expires" in resp.json
    assert resp.json.get("method", "") == "Anonymous"
    # Obtain a Firebase token (this should work for anonymous users)
    resp = client.post("/firebase_token")
    assert resp.status_code == 200
    assert resp.json is not None
    assert len(resp.json.get("token", "")) > 0
    assert resp.json.get("ok", False) == True
    # Obtain the current user's profile
    resp = client.post("/userstats")
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json.get("result", -1) == 0
    # Check that the Flask session cookie contains expected values
    cookie = client.get_cookie("session")
    assert cookie is not None
    session = decode_cookie(cookie.decoded_value)
    # Obtain the session dictionary from the decoded cookie
    sd = json.loads(session).get("s", {})
    assert sd.get("userid", "") == "anon:device9999991"
    assert sd.get("method", "") == "Anonymous"
    # Attempt to challenge another user, which should fail with a 401 status (Unauthorized)
    resp = client.post("/challenge", json=dict(destuser="9999992", duration=0))
    assert resp.status_code == 401  # Unauthorized
    # Attempt an online check, which should fail with a 401 status (Unauthorized)
    resp = client.post("/onlinecheck", json=dict(user="9999992"))
    assert resp.status_code == 401  # Unauthorized
    # Log out
    resp = client.post("/logout")
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json.get("status", "") == "success"
    # Try again to obtain a Firebase token, which should now fail
    resp = client.post("/firebase_token")
    assert resp.status_code == 401  # Unauthorized


