# type: ignore
"""

    Tests for Netskrafl
    Copyright (C) 2023 Miðeind ehf.

    This module tests several APIs by submitting HTTP requests
    to the Netskrafl server.

"""

from typing import Any, Dict

import sys
import os
from datetime import datetime, timedelta
import base64

import pytest

from flask import Response


# Make sure that we can run this test from the ${workspaceFolder}/test directory
SRC_PATH = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.append(SRC_PATH)

# Set up the environment for Explo-dev testing
os.environ["PROJECT_ID"] = "explo-dev"
os.environ[
    "GOOGLE_APPLICATION_CREDENTIALS"
] = "resources/Explo Development-414318fa79b8.json"
os.environ["SERVER_SOFTWARE"] = "Development"
os.environ["REDISHOST"] = "127.0.0.1"
os.environ["REDISPORT"] = "6379"


@pytest.fixture
def client():
    """ Flask client fixture """
    import main

    main.app.config["TESTING"] = True
    main.app.testing = True

    with main.app.test_client() as client:
        yield client


def create_user(idx: int, locale: str = "en_US") -> str:
    """ Create a user instance for testing, if it doesn't already exist """
    from skrafldb import UserModel, ChatModel, Client
    from skraflgame import PrefsDict

    with Client.get_context():
        nickname = f"testuser{idx}"
        email = f"test{idx}@user.explo"
        name = f"Test user {idx}"
        account = f"999999{idx}"
        image = ""
        prefs: PrefsDict = {"newbag": True, "email": email, "full_name": name}
        # Delete chat messages for this user
        ChatModel.delete_for_user(account)
        # Create a new user, if required
        return UserModel.create(
            user_id=account,
            account=account,
            email=email,
            nickname=nickname,
            image=image,
            preferences=prefs,
            locale=locale,
        )


@pytest.fixture
def u1() -> str:
    """ Create a test user with no chat messages """
    return create_user(1)


@pytest.fixture
def u2() -> str:
    """ Create a test user with no chat messages """
    return create_user(2)


@pytest.fixture
def u3_gb() -> str:
    """ Create a test user in the en_GB locale """
    return create_user(3, "en_GB")


def login_user(client, idx: int, client_type: str = "web") -> Response:
    rq: Dict[str, Any] = dict(
        sub=f"999999{idx}",
        # Full name of user
        name=f"Test user {idx}",
        # User image
        picture="",
        # Make sure that the e-mail address is in lowercase
        email=f"test{idx}@user.explo",
        # Client type
        clientType=client_type,
    )
    return client.post("/oauth2callback", data=rq)


def test_chat(client, u1, u2) -> None:
    """ Test the chat functionality """

    # Chat messages from user 1 to user 2

    resp = login_user(client, 1)
    resp = client.post(
        "/chatmsg", data=dict(channel="user:" + u2, msg="First chat message")
    )
    resp = client.post(
        "/chatmsg", data=dict(channel="user:" + u2, msg="Second chat message")
    )

    resp = client.post("/chatload", data=dict(channel="user:" + u2))
    assert resp.json["ok"]
    assert "messages" in resp.json
    messages = resp.json["messages"]
    len_1 = len(messages)
    assert len_1 == 2
    resp = client.post("/logout")

    # Chat messages from user 2 to user 1

    resp = login_user(client, 2)
    resp = client.post(
        "/chatmsg", data=dict(channel="user:" + u1, msg="First chat message")
    )
    resp = client.post(
        "/chatmsg", data=dict(channel="user:" + u1, msg="Second chat message")
    )

    resp = client.post("/chatload", data=dict(channel="user:" + u1))
    assert resp.json["ok"]
    assert "messages" in resp.json
    messages = resp.json["messages"]
    len_2 = len(messages)
    assert len_2 == len_1 + 2

    for m in messages:
        assert "from_userid" in m
        assert "name" in m
        assert "msg" in m
        assert "ts" in m
        assert "image" in m
        if m["from_userid"] == u1:
            assert m["name"] == "Test user 1"
        else:
            assert m["name"] == "Test user 2"

    resp = client.post("/chathistory")

    assert resp.json["ok"]
    assert "history" in resp.json
    history = resp.json["history"]

    for h in history:
        assert "user" in h
        assert "name" in h
        assert "image" in h
        assert "ts" in h
        assert "unread" in h
    assert history[-1]["user"] == u1
    assert not history[-1]["unread"]

    resp = client.post("/logout")

    # Go back to user 1

    resp = login_user(client, 1)

    resp = client.post("/chathistory")

    assert resp.json["ok"]
    assert "history" in resp.json
    history = resp.json["history"]

    for h in history:
        assert "user" in h
        assert "name" in h
        assert "image" in h
        assert "ts" in h
        assert "unread" in h
    assert history[-1]["user"] == u2
    # Last message should be unread
    assert history[-1]["unread"]

    # Send a read marker
    resp = client.post("/chatmsg", data=dict(channel="user:" + u2, msg=""))

    # Check the chat history again
    resp = client.post("/chathistory")

    assert resp.json["ok"]
    assert "history" in resp.json
    history = resp.json["history"]

    for h in history:
        assert "user" in h
        assert "name" in h
        assert "image" in h
        assert "ts" in h
        assert "unread" in h
    assert history[-1]["user"] == u2
    # Last message should no longer be unread
    assert not history[-1]["unread"]


def test_locale_assets(client, u1, u3_gb):

    # Test default en_US user
    resp = login_user(client, 1)
    resp = client.post("/locale_asset", data=dict(asset="test_english.html"))
    assert resp.status_code == 200
    assert resp.content_type == "text/html; charset=utf-8"
    assert "American English" in resp.data.decode("utf-8")
    resp = client.post("/logout")

    # Test en_GB user
    resp = login_user(client, 3)
    resp = client.post("/locale_asset", data=dict(asset="test_english.html"))
    assert resp.status_code == 200
    assert resp.content_type == "text/html; charset=utf-8"
    assert "generic English" in resp.data.decode("utf-8")
    resp = client.post("/logout")


def test_block(client, u1, u2):
    resp = login_user(client, 1)

    # User u1 blocks user u2
    resp = client.post("/blockuser", data=dict(blocked=u2))
    assert resp.status_code == 200
    assert "ok" in resp.json
    assert resp.json["ok"] == True

    # User u1 queries the user stats (profile) of user u2
    resp = client.post("/userstats", data=dict(user=u2))
    assert resp.status_code == 200
    assert "result" in resp.json
    assert resp.json["result"] == 0
    assert "blocked" in resp.json
    # The 'blocked' attribute should be True
    assert resp.json["blocked"]

    # There should be an entry in the list_blocked list
    # of user u1's profile
    resp = client.post("/userstats", data=dict(user=u1))
    assert resp.status_code == 200
    assert "result" in resp.json
    assert resp.json["result"] == 0
    assert "list_blocked" in resp.json
    b = resp.json["list_blocked"]
    assert len(b) == 1
    assert b[0]["uid"] == u2
    assert b[0]["nick"] == "testuser2"
    assert b[0]["name"] == "Test user 2"

    # User u1 unblocks user u2
    resp = client.post("/blockuser", data=dict(blocked=u2, action="delete"))
    assert resp.status_code == 200
    assert "ok" in resp.json
    assert resp.json["ok"] == True

    # User u1 queries the user stats (profile) of user u2
    resp = client.post("/userstats", data=dict(user=u2))
    assert resp.status_code == 200
    assert "result" in resp.json
    assert resp.json["result"] == 0
    assert "blocked" in resp.json
    # The 'blocked' attribute should now be False
    assert not resp.json["blocked"]
    # There should be no entry in the list_blocked list
    # of user u1's profile
    resp = client.post("/userstats", data=dict(user=u1))
    assert resp.status_code == 200
    assert "result" in resp.json
    assert resp.json["result"] == 0
    assert "list_blocked" in resp.json
    b = resp.json["list_blocked"]
    assert len(b) == 0

    # User u1 blocks user u2 twice
    resp = client.post("/blockuser", data=dict(blocked=u2))
    assert resp.status_code == 200
    assert "ok" in resp.json
    assert resp.json["ok"] == True
    resp = client.post("/blockuser", data=dict(blocked=u2))
    assert resp.status_code == 200
    assert "ok" in resp.json
    assert resp.json["ok"] == True

    # User u1 queries the user stats (profile) of user u2
    resp = client.post("/userstats", data=dict(user=u2))
    assert resp.status_code == 200
    assert "result" in resp.json
    assert resp.json["result"] == 0
    assert "blocked" in resp.json
    # The 'blocked' attribute should be True
    assert resp.json["blocked"]
    # There should be a single entry in the list_blocked list
    resp = client.post("/userstats", data=dict(user=u1))
    assert resp.status_code == 200
    assert "result" in resp.json
    assert resp.json["result"] == 0
    assert "list_blocked" in resp.json
    b = resp.json["list_blocked"]
    assert len(b) == 1
    assert b[0]["uid"] == u2
    assert b[0]["nick"] == "testuser2"
    assert b[0]["name"] == "Test user 2"

    # User u1 unblocks user u2
    resp = client.post("/blockuser", data=dict(blocked=u2, action="delete"))
    assert resp.status_code == 200
    assert "ok" in resp.json
    assert resp.json["ok"] == True

    # User u1 queries the user stats (profile) of user u2
    resp = client.post("/userstats", data=dict(user=u2))
    assert resp.status_code == 200
    assert "result" in resp.json
    assert resp.json["result"] == 0
    assert "blocked" in resp.json
    # The 'blocked' attribute should now be False
    assert not resp.json["blocked"]
    # There should be no entry in the list_blocked list
    resp = client.post("/userstats", data=dict(user=u1))
    assert resp.status_code == 200
    assert "result" in resp.json
    assert resp.json["result"] == 0
    assert "list_blocked" in resp.json
    b = resp.json["list_blocked"]
    assert len(b) == 0

    resp = client.post("/logout")


def test_disable_chat(client, u1, u2):
    resp = login_user(client, 1)

    # User u1 disables chat
    resp = client.post("/setuserpref", data=dict(chat_disabled=True))
    assert resp.status_code == 200
    assert "result" in resp.json
    assert resp.json["result"] == 0

    resp = client.post("/userstats", data=dict(user=u1))
    assert resp.status_code == 200
    assert "result" in resp.json
    assert resp.json["result"] == 0
    assert "chat_disabled" in resp.json
    assert resp.json["chat_disabled"]

    # User u1 enables chat
    resp = client.post("/setuserpref", data=dict(chat_disabled=False))
    assert resp.status_code == 200
    assert "result" in resp.json
    assert resp.json["result"] == 0

    resp = client.post("/userstats", data=dict(user=u1))
    assert resp.status_code == 200
    assert "result" in resp.json
    assert resp.json["result"] == 0
    assert "chat_disabled" in resp.json
    assert not resp.json["chat_disabled"]

    resp = client.post("/logout")


def test_report(client, u1, u2):
    resp = login_user(client, 1)

    # User u1 reports user u2
    resp = client.post("/reportuser", data=dict(reported=u2, code=0, text="Genuine a**hole!"))
    assert resp.status_code == 200
    assert "ok" in resp.json
    assert resp.json["ok"] == True

    resp = client.post("/logout")

    resp = login_user(client, 2)

    # User u2 reports user u1
    resp = client.post("/reportuser", data=dict(reported=u1, code=1))
    assert resp.status_code == 200
    assert "ok" in resp.json
    assert resp.json["ok"] == True

    # User u2 reports nonexisting user (which should return ok=False)
    resp = client.post("/reportuser", data=dict(reported="xxx", code=1))
    assert resp.status_code == 200
    assert "ok" in resp.json
    assert resp.json["ok"] == False

    resp = client.post("/logout")


def test_elo_history(client, u1):
    resp = login_user(client, 1)

    # Insert some stats
    from skrafldb import StatsModel, Client

    with Client.get_context():
        StatsModel.delete_user(u1)

    resp = client.post("/userstats", data=dict(user=u1))
    assert resp.status_code == 200
    assert "result" in resp.json
    assert resp.json["result"] == 0

    assert "elo_30_days" in resp.json
    assert len(resp.json["elo_30_days"]) == 30
    now = datetime.utcnow()
    now = datetime(year=now.year, month=now.month, day=now.day)

    for ix, sm in enumerate(resp.json["elo_30_days"]):
        ts = datetime.fromisoformat(sm["ts"])
        assert (now - ts).days == ix
        assert sm["elo"] == 1200
        assert sm["human_elo"] == 1200
        assert sm["manual_elo"] == 1200

    with Client.get_context():

        sm = StatsModel.create(u1)
        sm.timestamp = now - timedelta(days=35)
        sm.elo = 1210
        sm.human_elo = 1220
        sm.manual_elo = 1230
        sm.put()
        sm = StatsModel.create(u1)
        sm.timestamp = now - timedelta(days=15)
        sm.elo = 1240
        sm.human_elo = 1250
        sm.manual_elo = 1260
        sm.put()
        sm = StatsModel.create(u1)
        sm.timestamp = now - timedelta(days=5)
        sm.elo = 1270
        sm.human_elo = 1280
        sm.manual_elo = 1290
        sm.put()

    resp = client.post("/userstats", data=dict(user=u1))
    assert resp.status_code == 200
    assert "result" in resp.json
    assert resp.json["result"] == 0

    assert "elo_30_days" in resp.json
    slist = resp.json["elo_30_days"]
    assert len(slist) == 30

    for ix in reversed(range(16, 30)):
        sm = slist[ix]
        ts = datetime.fromisoformat(sm["ts"])
        assert (now - ts).days == ix
        assert sm["elo"] == 1210
        assert sm["human_elo"] == 1220
        assert sm["manual_elo"] == 1230

    for ix in reversed(range(6, 16)):
        sm = slist[ix]
        ts = datetime.fromisoformat(sm["ts"])
        assert (now - ts).days == ix
        assert sm["elo"] == 1240
        assert sm["human_elo"] == 1250
        assert sm["manual_elo"] == 1260

    for ix in reversed(range(0, 6)):
        sm = slist[ix]
        ts = datetime.fromisoformat(sm["ts"])
        assert (now - ts).days == ix
        assert sm["elo"] == 1270
        assert sm["human_elo"] == 1280
        assert sm["manual_elo"] == 1290

    resp = client.post("/logout")


def test_image(client, u1):
    """ Test image setting and getting """
    resp = login_user(client, 1)

    # Set the image by POSTing the JPEG or PNG content (BLOB) directly
    image_blob = b"1234"
    # Encode the image_blob as base64
    image_b64 = base64.b64encode(image_blob)
    resp = client.post("/image", data=image_b64, content_type="image/jpeg; charset=utf-8")
    assert resp.status_code == 200

    # Retrieve the image of the currently logged-in user
    resp = client.get("/image")
    assert resp.status_code == 200
    assert resp.mimetype == "image/jpeg"
    assert resp.content_length == len(image_blob)
    # Retrieve the original BLOB
    assert resp.get_data(as_text=False) == image_blob

    # Set an image URL: note the text/plain MIME type
    image_url = "https://lh3.googleusercontent.com/a/AATXAJxmLaM_8c61i_EeyptXynOG1SL7b-BSt7uBz8Hg=s96-c"
    resp = client.post("/image",
        data=image_url,
        content_type="text/plain; charset=utf-8"
    )
    assert resp.status_code == 200

    # Get the image (follow_redirects specified for emphasis, it
    # is False by default)
    resp = client.get("/image", follow_redirects=False)
    assert resp.status_code == 302
    # Retrieve the URL from the Location header
    assert resp.location == image_url

    resp = client.post("/logout")


def test_delete_user_1(client, u1):
    """Delete a user using the /delete_account endpoint"""
    # Try to delete an account without being logged in
    resp = client.post("/delete_account")
    assert resp.status_code == 401  # Unauthorized

    resp = login_user(client, 1)
    assert resp.status_code == 200

    # Delete the account
    resp = client.post("/delete_account")
    assert resp.status_code == 200
    assert resp.json["ok"] == True

    # Now the session cookie should be expired
    resp = client.post("/delete_account")
    assert resp.status_code == 401  # Unauthorized


def test_delete_user_2(client, u1, u2):
    """Delete a user using the /delete_account endpoint"""
    resp = login_user(client, 1)
    assert resp.status_code == 200

    # Add challenges and favorites
    resp = client.post("/challenge", data=dict(destuser=u2, duration=10))
    assert resp.status_code == 200
    assert resp.json["result"] == 0
    resp = client.post("/challenge", data=dict(destuser=u2, duration=20))
    assert resp.status_code == 200
    assert resp.json["result"] == 0

    # Add a favorite (u1 favors u2)
    resp = client.post("/favorite", data=dict(destuser=u2))
    assert resp.status_code == 200
    assert resp.json["result"] == 0

    # Log in the second user
    resp = client.post("/logout")
    assert resp.status_code == 200
    resp = login_user(client, 2)
    assert resp.status_code == 200

    # Verify that the challenges exist
    resp = client.post("/challengelist")
    assert resp.status_code == 200
    assert resp.json["result"] == 0
    assert len(resp.json["challengelist"]) == 2

    # Add a favorite (u2 favors u1)
    resp = client.post("/favorite", data=dict(destuser=u1))
    assert resp.status_code == 200
    assert resp.json["result"] == 0

    # Logout and log in the first user again
    resp = client.post("/logout")
    assert resp.status_code == 200
    resp = login_user(client, 1)
    assert resp.status_code == 200

    # Delete the user account
    resp = client.post("/delete_account")
    assert resp.status_code == 200
    assert resp.json["ok"] == True

    # Logout and log in the second user again
    resp = client.post("/logout")
    assert resp.status_code == 200
    resp = login_user(client, 2)
    assert resp.status_code == 200

    # Now there should be no challenges
    resp = client.post("/challengelist")
    assert resp.status_code == 200
    assert resp.json["result"] == 0
    assert len(resp.json["challengelist"]) == 0

    # Load user stats for the current user (u2)
    resp = client.post("/userstats")
    assert resp.status_code == 200
    assert resp.json["result"] == 0
    assert len(resp.json["list_favorites"]) == 0

    # Load user stats for the other (deleted) user (u1)
    resp = client.post("/userstats", data=dict(user=u1))
    assert resp.status_code == 200
    assert resp.json["result"] == 0
    assert resp.json["favorite"] == False
    assert "list_favorites" not in resp.json
    assert resp.json["fullname"] == ""
    # assert resp.json["image"] == ""
    assert resp.json["chat_disabled"] == True

    resp = client.post("/logout")
    assert resp.status_code == 200
