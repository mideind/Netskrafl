"""

    Tests for Netskrafl / Explo Word Game
    Copyright (C) 2024 Miðeind ehf.

    This module tests several APIs by submitting HTTP requests
    to the Netskrafl / Explo server.

"""

from utils import CustomClient, login_user
from utils import client, u1, u2, u3_gb  # type: ignore


def test_delete_user_1(client: CustomClient, u1: str) -> None:
    """Delete a user using the /delete_account endpoint"""
    # Try to delete an account without being logged in
    resp = client.post("/delete_account")
    assert resp.status_code == 401  # Unauthorized

    resp = login_user(client, 1)
    assert resp.status_code == 200

    # Delete the account
    resp = client.post("/delete_account")
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json["ok"] == True

    # Now the session cookie should be expired
    resp = client.post("/delete_account")
    assert resp.status_code == 401  # Unauthorized


def test_delete_user_2(client: CustomClient, u1: str, u2: str) -> None:
    """Delete a user using the /delete_account endpoint"""
    resp = login_user(client, 1)
    assert resp.status_code == 200

    # Add challenges and favorites
    resp = client.post("/challenge", data=dict(destuser=u2, duration=10))
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json["result"] == 0
    resp = client.post("/challenge", data=dict(destuser=u2, duration=20))
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json["result"] == 0

    # Add a favorite (u1 favors u2)
    resp = client.post("/favorite", data=dict(destuser=u2))
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json["result"] == 0

    # Log in the second user
    resp = client.post("/logout")
    assert resp.status_code == 200
    resp = login_user(client, 2)
    assert resp.status_code == 200

    # Verify that the challenges exist
    resp = client.post("/challengelist")
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json["result"] == 0
    assert len(resp.json["challengelist"]) == 2

    # Add a favorite (u2 favors u1)
    resp = client.post("/favorite", data=dict(destuser=u1))
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json["result"] == 0

    # Logout and log in the first user again
    resp = client.post("/logout")
    assert resp.status_code == 200
    resp = login_user(client, 1)
    assert resp.status_code == 200

    # Delete the user account
    resp = client.post("/delete_account")
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json["ok"] == True

    # Logout and log in the second user again
    resp = client.post("/logout")
    assert resp.status_code == 200
    resp = login_user(client, 2)
    assert resp.status_code == 200

    # Now there should be no challenges
    resp = client.post("/challengelist")
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json["result"] == 0
    assert len(resp.json["challengelist"]) == 0

    # Load user stats for the current user (u2)
    resp = client.post("/userstats")
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json["result"] == 0
    assert len(resp.json["list_favorites"]) == 0

    # Load user stats for the other (deleted) user (u1)
    resp = client.post("/userstats", data=dict(user=u1))
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json["result"] == 0
    assert resp.json["favorite"] == False
    assert "list_favorites" not in resp.json
    assert resp.json["fullname"] == ""
    # assert resp.json["image"] == ""
    assert resp.json["chat_disabled"] == True

    resp = client.post("/logout")
    assert resp.status_code == 200
