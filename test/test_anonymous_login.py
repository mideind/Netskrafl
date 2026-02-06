"""

    Tests for Netskrafl / Explo Word Game
    Copyright © 2025 Miðeind ehf.

    This module tests several APIs by submitting HTTP requests
    to the Netskrafl / Explo server.

"""

import random

from utils import CustomClient, get_session_dict, login_anonymous_user


def test_anonymous_login(client: CustomClient, u1: str) -> None:
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
    assert resp.json.get("ok", False)
    # Obtain the current user's profile
    resp = client.post("/userstats")
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json.get("result", -1) == 0
    # Check that the Flask session cookie contains expected values
    sd = get_session_dict(client)
    assert sd.get("userid", "") == "anon:device9999991"
    assert sd.get("method", "") == "Anonymous"
    # Attempt to challenge another user, which should fail with a 401 status (Unauthorized)
    resp = client.post("/challenge", json=dict(destuser=u1, duration=0))
    assert resp.status_code == 401  # Unauthorized
    # Attempt an online check, which should fail with a 401 status (Unauthorized)
    resp = client.post("/onlinecheck", json=dict(user=u1))
    assert resp.status_code == 401  # Unauthorized
    # Log out
    resp = client.post("/logout")
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json.get("status", "") == "success"
    # Try again to obtain a Firebase token, which should now fail
    resp = client.post("/firebase_token")
    assert resp.status_code == 401  # Unauthorized


def test_anonymous_upgrade(client: CustomClient, u1: str) -> None:
    """Test upgrading of an anonymous account to a regular account"""
    # Start by logging in as an anonymous user
    client.set_authorization(True)
    resp = login_anonymous_user(client, 1, locale="en_US")
    client.set_authorization(False)
    assert resp.status_code == 200
    # Verify that the session is an anonymous session
    sd = get_session_dict(client)
    assert sd.get("userid", "") == "anon:device9999991"
    assert sd.get("method", "") == "Anonymous"
    # Attempt an online check, which should fail (not allowed for anonymous users)
    resp = client.post("/onlinecheck", json=dict(user=u1))
    assert resp.status_code == 401
    # Upgrade the anonymous account to a regular account
    # Generate a string from a 12-digit random number as the user's 'sub' value
    sub = "".join(str(random.randint(0, 9)) for _ in range(12))
    # Do a synthetic POST to the /oauth2callback endpoint
    # (this will simulate the Google OAuth2 callback with the user's profile data)
    resp = client.post(
        "/oauth2callback",
        data=dict(sub=sub, name=f"Test user {sub}", email=f"u{sub}@explowordgame.com"),
    )
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json.get("status") == "success"
    # Verify that the session is now a regular session
    sd = get_session_dict(client)
    assert sd.get("userid", "") == "anon:device9999991"
    assert sd.get("method", "") == "Google"
    # Verify that the returned login dictionary is as expected
    assert resp.json.get("status", "") == "success"
    assert resp.json.get("token", "") > ""
    assert resp.json.get("expires", "") != ""
    assert resp.json.get("user_id", "") == "anon:device9999991"
    assert resp.json.get("account", "") == sub
    assert resp.json.get("method", "") == "Google"
    assert resp.json.get("locale", "") == "en_US"
    # Attempt an online check, which should succeed since the user is now authenticated
    resp = client.post("/onlinecheck", json=dict(user=u1))
    assert resp.status_code == 200
    # Log out
    resp = client.post("/logout")
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json.get("status", "") == "success"
