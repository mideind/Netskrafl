"""

    Tests for Netskrafl / Explo Word Game
    Copyright © 2025 Miðeind ehf.

    This module tests several APIs by submitting HTTP requests
    to the Netskrafl / Explo server.

"""

from utils import CustomClient, login_user
from utils import client, u1, u2, u3_gb  # type: ignore  # noqa: F401


def test_block(client: CustomClient, u1: str, u2: str) -> None:
    resp = login_user(client, 1)

    # User u1 blocks user u2
    resp = client.post("/blockuser", data=dict(blocked=u2))
    assert resp.status_code == 200
    assert resp.json is not None
    assert "ok" in resp.json
    assert resp.json["ok"] == True

    # User u1 queries the user stats (profile) of user u2
    resp = client.post("/userstats", data=dict(user=u2))
    assert resp.status_code == 200
    assert resp.json is not None
    assert "result" in resp.json
    assert resp.json["result"] == 0
    assert "blocked" in resp.json
    # The 'blocked' attribute should be True
    assert resp.json["blocked"]

    # There should be an entry in the list_blocked list
    # of user u1's profile
    resp = client.post("/userstats", data=dict(user=u1))
    assert resp.status_code == 200
    assert resp.json is not None
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
    assert resp.json is not None
    assert "ok" in resp.json
    assert resp.json["ok"] == True

    # User u1 queries the user stats (profile) of user u2
    resp = client.post("/userstats", data=dict(user=u2))
    assert resp.status_code == 200
    assert resp.json is not None
    assert "result" in resp.json
    assert resp.json["result"] == 0
    assert "blocked" in resp.json
    # The 'blocked' attribute should now be False
    assert not resp.json["blocked"]
    # There should be no entry in the list_blocked list
    # of user u1's profile
    resp = client.post("/userstats", data=dict(user=u1))
    assert resp.status_code == 200
    assert resp.json is not None
    assert "result" in resp.json
    assert resp.json["result"] == 0
    assert "list_blocked" in resp.json
    b = resp.json["list_blocked"]
    assert len(b) == 0

    # User u1 blocks user u2 twice
    resp = client.post("/blockuser", data=dict(blocked=u2))
    assert resp.status_code == 200
    assert resp.json is not None
    assert "ok" in resp.json
    assert resp.json["ok"] == True
    resp = client.post("/blockuser", data=dict(blocked=u2))
    assert resp.status_code == 200
    assert resp.json is not None
    assert "ok" in resp.json
    assert resp.json["ok"] == True

    # User u1 queries the user stats (profile) of user u2
    resp = client.post("/userstats", data=dict(user=u2))
    assert resp.status_code == 200
    assert resp.json is not None
    assert "result" in resp.json
    assert resp.json["result"] == 0
    assert "blocked" in resp.json
    # The 'blocked' attribute should be True
    assert resp.json["blocked"]
    # There should be a single entry in the list_blocked list
    resp = client.post("/userstats", data=dict(user=u1))
    assert resp.status_code == 200
    assert resp.json is not None
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
    assert resp.json is not None
    assert "ok" in resp.json
    assert resp.json["ok"] == True

    # User u1 queries the user stats (profile) of user u2
    resp = client.post("/userstats", data=dict(user=u2))
    assert resp.status_code == 200
    assert resp.json is not None
    assert "result" in resp.json
    assert resp.json["result"] == 0
    assert "blocked" in resp.json
    # The 'blocked' attribute should now be False
    assert not resp.json["blocked"]
    # There should be no entry in the list_blocked list
    resp = client.post("/userstats", data=dict(user=u1))
    assert resp.status_code == 200
    assert resp.json is not None
    assert "result" in resp.json
    assert resp.json["result"] == 0
    assert "list_blocked" in resp.json
    b = resp.json["list_blocked"]
    assert len(b) == 0

    resp = client.post("/logout")
    assert resp.status_code == 200


def test_report(client: CustomClient, u1: str, u2: str) -> None:
    resp = login_user(client, 1)

    # User u1 reports user u2
    resp = client.post(
        "/reportuser", data=dict(reported=u2, code=0, text="Genuine a**hole!")
    )
    assert resp.status_code == 200
    assert resp.json is not None
    assert "ok" in resp.json
    assert resp.json["ok"] == True

    resp = client.post("/logout")

    resp = login_user(client, 2)

    # User u2 reports user u1
    resp = client.post("/reportuser", data=dict(reported=u1, code=1))
    assert resp.status_code == 200
    assert resp.json is not None
    assert "ok" in resp.json
    assert resp.json["ok"] == True

    # User u2 reports nonexisting user (which should return ok=False)
    resp = client.post("/reportuser", data=dict(reported="xxx", code=1))
    assert resp.status_code == 200
    assert resp.json is not None
    assert "ok" in resp.json
    assert resp.json["ok"] == False

    resp = client.post("/logout")
    assert resp.status_code == 200
