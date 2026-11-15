"""
End-to-end tests of what a login saves in the user's preferences.

A login changes preferences of an existing user in two cases: a login from
Málstaður sets the subscription status (the friend and haspaid preferences)
from the plan in the host's token, and an account login fills in a missing
full name. Each test reads the result back in a later request, i.e. in
another database session, so that only what was really saved counts: on
PostgreSQL, a change made inside the preferences dict of a user entity is
not noticed, and was silently dropped at the end of the request.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import uuid

import pytest
from flask.testing import FlaskClient

from tests.api_e2e.conftest import AuthHelper


def malstadur_login(
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
    email: str,
    plan: str,
) -> Dict[str, Any]:
    """Log in from Málstaður with the given subscription plan in the
    host's token (whose verification is stubbed)"""
    import web

    claims = {"sub": f"sub-{email}", "email": email, "plan": plan}
    verdict: Tuple[bool, Optional[Dict[str, Any]]] = (False, claims)
    monkeypatch.setattr(web, "verify_malstadur_token", lambda token: verdict)
    response = client.post(
        "/login_malstadur",
        json=dict(email=email, token="a-token", bearer_auth=True),
    )
    assert response.status_code == 200, f"Login failed: {response.data!r}"
    data = response.get_json()
    assert data is not None and data.get("status") == "success"
    return data


def load_user(client: FlaskClient, user_id: str) -> Dict[str, Any]:
    """Read a user back from the database, in a request of its own"""
    data = client.post("/admin/loaduser", data={"id": user_id}).get_json()
    assert data is not None and data["user"] is not None
    return data["user"]


@pytest.mark.api_e2e
class TestMalstadurSubscription:
    """A subscription bought in Málstaður must reach the Netskrafl user."""

    def test_new_user_with_subscription(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A user who is a subscriber at the first login is created as one."""
        email = f"sub-new-{uuid.uuid4().hex[:8]}@example.com"
        login = malstadur_login(client, monkeypatch, email, "friend")
        assert login["new"] is True

        user = load_user(client, login["user_id"])
        assert user["plan"] == "friend"
        assert user["friend"] is True
        assert user["has_paid"] is True

    def test_free_user_who_subscribes(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A free user who subscribes is a paying user from the next login:
        the status is saved, and the premium robots open up."""
        email = f"sub-later-{uuid.uuid4().hex[:8]}@example.com"

        # First login, without a subscription: a free user is created
        login = malstadur_login(client, monkeypatch, email, "")
        user_id = login["user_id"]
        headers = {"Authorization": f"Bearer {login['token']}"}
        assert login["prefs"].get("haspaid", False) is False
        user = load_user(client, user_id)
        assert user["plan"] == ""
        assert user["friend"] is False
        assert user["has_paid"] is False
        # The strongest robot is behind the paywall
        response = client.post("/initgame", json={"opp": "robot-0"}, headers=headers)
        data = response.get_json()
        assert data is not None
        assert data.get("ok") is False
        assert data.get("err") == "premium_required"

        # The user subscribes in Málstaður and logs in again
        login = malstadur_login(client, monkeypatch, email, "friend")
        assert login["user_id"] == user_id
        assert login["new"] is False
        headers = {"Authorization": f"Bearer {login['token']}"}
        # The login reply tells the client that the user has paid...
        assert login["prefs"].get("friend") is True
        assert login["prefs"].get("haspaid") is True
        # ...and so does the database, in later requests
        user = load_user(client, user_id)
        assert user["plan"] == "friend"
        assert user["friend"] is True
        assert user["has_paid"] is True
        # The strongest robot is now available
        response = client.post("/initgame", json={"opp": "robot-0"}, headers=headers)
        data = response.get_json()
        assert data is not None
        assert data.get("ok") is True, f"Premium robot refused: {data}"

    def test_subscription_is_kept_without_plan_in_token(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """For now, a login without a plan does not take the status away
        (it may stem from the legacy Netskrafl subscription)."""
        email = f"sub-kept-{uuid.uuid4().hex[:8]}@example.com"
        login = malstadur_login(client, monkeypatch, email, "friend")
        user_id = login["user_id"]

        login = malstadur_login(client, monkeypatch, email, "")
        assert login["user_id"] == user_id
        user = load_user(client, user_id)
        assert user["plan"] == "friend"
        assert user["friend"] is True
        assert user["has_paid"] is True


@pytest.mark.api_e2e
class TestAccountLoginFullName:
    """An account login fills in the full name if there is none."""

    def test_full_name_is_saved_on_upgrade(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """An anonymous user has no full name; the one given when the
        account is upgraded must be saved."""
        unique_id = uuid.uuid4().hex[:8]
        anon = auth.login_anonymous(device_id=f"fullname-device-{unique_id}")
        assert load_user(client, anon["user_id"])["full_name"] == ""

        # Log in with an account, without logging out first: this upgrades
        # the anonymous user
        upgraded = auth.login_user(
            sub=f"fullname-{unique_id}",
            name="Fullname Tester",
            email=f"fullname-{unique_id}@example.com",
        )
        assert upgraded["user_id"] == anon["user_id"]
        assert load_user(client, upgraded["user_id"])["full_name"] == "Fullname Tester"

        auth.logout()

