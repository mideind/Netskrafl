"""

    Tests for Netskrafl / Explo Word Game
    Copyright © 2025 Miðeind ehf.

    This module tests several APIs by submitting HTTP requests
    to the Netskrafl / Explo server.

"""

from utils import CustomClient, login_user
from utils import client, u1, u2, u3_gb  # type: ignore


def test_chat(client: CustomClient, u1: str, u2: str) -> None:
    """Test the chat functionality"""

    # Chat messages from user 1 to user 2

    resp = login_user(client, 1)
    resp = client.post(
        "/chatmsg", data=dict(channel="user:" + u2, msg="First chat message")
    )
    assert resp.status_code == 200
    resp = client.post(
        "/chatmsg", data=dict(channel="user:" + u2, msg="Second chat message")
    )
    assert resp.status_code == 200

    resp = client.post("/chatload", data=dict(channel="user:" + u2))
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json["ok"]
    assert "messages" in resp.json
    messages = resp.json["messages"]
    len_1 = len(messages)
    assert len_1 == 2
    resp = client.post("/logout")
    assert resp.status_code == 200

    # Chat messages from user 2 to user 1

    resp = login_user(client, 2)
    resp = client.post(
        "/chatmsg", data=dict(channel="user:" + u1, msg="First chat message")
    )
    assert resp.status_code == 200
    resp = client.post(
        "/chatmsg", data=dict(channel="user:" + u1, msg="Second chat message")
    )
    assert resp.status_code == 200

    resp = client.post("/chatload", data=dict(channel="user:" + u1))
    assert resp.status_code == 200
    assert resp.json is not None
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
    assert resp.status_code == 200

    assert resp.json is not None
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
    assert resp.status_code == 200

    # Go back to user 1

    resp = login_user(client, 1)

    resp = client.post("/chathistory")
    assert resp.status_code == 200

    assert resp.json is not None
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
    assert resp.status_code == 200

    # Check the chat history again
    resp = client.post("/chathistory")
    assert resp.status_code == 200

    assert resp.json is not None
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


def test_disable_chat(client: CustomClient, u1: str, u2: str) -> None:
    resp = login_user(client, 1)

    # User u1 disables chat
    resp = client.post("/setuserpref", data=dict(chat_disabled=True))
    assert resp.status_code == 200
    assert resp.json is not None
    assert "result" in resp.json
    assert resp.json["result"] == 0

    resp = client.post("/userstats", data=dict(user=u1))
    assert resp.status_code == 200
    assert resp.json is not None
    assert "result" in resp.json
    assert resp.json["result"] == 0
    assert "chat_disabled" in resp.json
    assert resp.json["chat_disabled"]

    # User u1 enables chat
    resp = client.post("/setuserpref", data=dict(chat_disabled=False))
    assert resp.status_code == 200
    assert resp.json is not None
    assert "result" in resp.json
    assert resp.json["result"] == 0

    resp = client.post("/userstats", data=dict(user=u1))
    assert resp.status_code == 200
    assert resp.json is not None
    assert "result" in resp.json
    assert resp.json["result"] == 0
    assert "chat_disabled" in resp.json
    assert not resp.json["chat_disabled"]

    resp = client.post("/logout")
    assert resp.status_code == 200
