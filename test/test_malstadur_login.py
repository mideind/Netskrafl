"""

    Tests for the /login_malstadur route in web.py
    Copyright © 2026 Miðeind ehf.

    Verifies that the outcome of a login attempt is logged with the
    identity it was made for, and that a failure to create a Firebase
    custom token does not fail the login.

    The token verification, the user lookup and Firebase are stubbed,
    so these tests do not touch the database.

"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest
from werkzeug.test import TestResponse

import web
from skrafluser import JWTClaims, UserLoginDict
from utils import CustomClient

EMAIL = "player@example.com"
USER_ID = "test-user-id-42"

ULD: UserLoginDict = {
    "user_id": USER_ID,
    "nickname": "player",
    "account": "malstadur:1234567890",
    "locale": "is_IS",
    "new": False,
    "token": "session-token",
    "expires": None,
    "firebase_api_key": "",
}


def stub_login(
    monkeypatch: pytest.MonkeyPatch,
    verdict: Tuple[bool, Optional[JWTClaims]],
) -> None:
    """Stub the token verification with the given verdict,
    and the user lookup with a fixed login dictionary"""
    monkeypatch.setattr(web, "verify_malstadur_token", lambda token: verdict)
    monkeypatch.setattr(web.User, "login_by_email", lambda *args, **kwargs: ULD)


def login_events(caplog: pytest.LogCaptureFixture) -> List[Dict[str, Any]]:
    """Return the structured fields of the logged login events"""
    fields = [getattr(r, "json_fields", None) for r in caplog.records]
    return [f for f in fields if f and f.get("event") == "malstadur_login"]


def post_login(client: CustomClient) -> TestResponse:
    return client.post(
        "/login_malstadur",
        json=dict(email=EMAIL, token="a-token", bearer_auth=True),
    )


VALID_CLAIMS: JWTClaims = {
    "sub": "1234567890",
    "email": EMAIL,
    "plan": "friend",
    "exp": 0.0,  # Not looked at: the token verification is stubbed
    "iat": 0.0,
}
VALID: Tuple[bool, Optional[JWTClaims]] = (False, VALID_CLAIMS)


def test_successful_login_is_logged_with_the_user_id(
    client: CustomClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    stub_login(monkeypatch, VALID)
    monkeypatch.setattr(web.firebase, "create_custom_token", lambda uid: "fb-token")
    with caplog.at_level("INFO"):
        resp = post_login(client)
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json["status"] == "success"
    assert resp.json["firebase_token"] == "fb-token"
    assert USER_ID in caplog.text
    assert login_events(caplog) == [
        dict(
            event="malstadur_login",
            outcome="success",
            user_id=USER_ID,
            new_user=False,
            firebase_token=True,
        )
    ]


def test_login_survives_a_firebase_token_failure(
    client: CustomClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The client can play without Firebase, and asks for a token
    # again later via /firebase_token
    def fail(uid: str) -> str:
        raise ConnectionResetError("Firebase unreachable")

    stub_login(monkeypatch, VALID)
    monkeypatch.setattr(web.firebase, "create_custom_token", fail)
    with caplog.at_level("INFO"):
        resp = post_login(client)
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json["status"] == "success"
    assert resp.json["token"] == "session-token"
    assert resp.json["firebase_token"] == ""
    assert "no Firebase token" in caplog.text
    assert USER_ID in caplog.text
    outcomes = [(e["outcome"], e.get("user_id")) for e in login_events(caplog)]
    assert outcomes == [("no_firebase_token", USER_ID), ("success", USER_ID)]


@pytest.mark.parametrize(
    "verdict,status_code,status",
    [((True, None), 200, "expired"), ((False, None), 401, "invalid")],
)
def test_rejected_login_is_logged_with_the_email(
    client: CustomClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    verdict: Tuple[bool, Optional[JWTClaims]],
    status_code: int,
    status: str,
) -> None:
    stub_login(monkeypatch, verdict)
    with caplog.at_level("INFO"):
        resp = post_login(client)
    assert resp.status_code == status_code
    assert resp.json is not None
    assert resp.json["status"] == status
    assert EMAIL in caplog.text
    assert login_events(caplog) == [
        dict(event="malstadur_login", outcome=status, email=EMAIL)
    ]

