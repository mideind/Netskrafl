"""

    Tests for the /inituser and /appversion API endpoints
    Copyright © 2026 Miðeind ehf.

    This module tests the app_version and endpoints fields returned
    by /inituser, and the /appversion configuration endpoint.

"""

from typing import Any, Dict, Iterator, Optional

import pytest

from utils import (
    CustomClient,
    client,
    create_user,
    login_user,
    u1,
)
from skrafldb import Client
import appversion
import basics

# Re-export fixtures so that pytest finds them
__all__ = ["client", "create_user", "u1"]

CRON_SECRET = "test-cron-secret"


def _set_config(**kwargs: Optional[str]) -> None:
    with Client.get_context():
        config, err = appversion.validate_config(kwargs)
        assert config is not None, err
        appversion.save_config(config)


def _clear_config() -> None:
    with Client.get_context():
        appversion.delete_config()


@pytest.fixture(autouse=True)
def clean_config() -> Iterator[None]:
    """Ensure that no app version record exists before and after each test"""
    _clear_config()
    yield
    _clear_config()


def _inituser(client: CustomClient, client_type: str = "ios") -> Dict[str, Any]:
    client.set_authorization(True)
    resp = login_user(client, 1, client_type=client_type)
    assert resp.status_code == 200
    resp = client.post("/inituser")
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json.get("ok") is True
    return resp.json


def test_inituser_no_app_version(client: CustomClient, u1: str) -> None:
    """With no record configured, app_version and endpoints are null"""
    j = _inituser(client)
    assert "userprefs" in j
    assert "userstats" in j
    assert "firebase_token" in j
    assert j.get("app_version") is None
    assert j.get("endpoints") is None


def test_inituser_with_app_version(client: CustomClient, u1: str) -> None:
    """A configured record is reported, including the update message"""
    _set_config(
        min_supported_version="1.2.0",
        latest_version="1.5.0",
        update_message="Please update for new features!",
    )
    j = _inituser(client)
    app_version = j.get("app_version")
    assert app_version == {
        "min_supported_version": "1.2.0",
        "latest_version": "1.5.0",
        "update_message": "Please update for new features!",
    }
    assert j.get("endpoints") is None


def test_inituser_app_version_no_message(client: CustomClient, u1: str) -> None:
    """update_message is omitted when not set"""
    _set_config(min_supported_version="2.0.0", latest_version="2.1.0")
    j = _inituser(client)
    app_version = j.get("app_version")
    assert app_version == {
        "min_supported_version": "2.0.0",
        "latest_version": "2.1.0",
    }


def test_inituser_platform_override(client: CustomClient, u1: str) -> None:
    """Per-platform overrides apply to the matching client type only"""
    _set_config(
        min_supported_version="1.0.0",
        latest_version="1.5.0",
        ios_min_supported_version="1.3.0",
        android_latest_version="1.6.0",
    )
    j = _inituser(client, client_type="ios")
    assert j["app_version"] == {
        "min_supported_version": "1.3.0",
        "latest_version": "1.5.0",
    }
    j = _inituser(client, client_type="android")
    assert j["app_version"] == {
        "min_supported_version": "1.0.0",
        "latest_version": "1.6.0",
    }
    j = _inituser(client, client_type="web")
    assert j["app_version"] == {
        "min_supported_version": "1.0.0",
        "latest_version": "1.5.0",
    }


def test_inituser_endpoints(client: CustomClient, u1: str) -> None:
    """Endpoint overrides are reported when configured"""
    _set_config(
        min_supported_version="1.0.0",
        latest_version="1.0.0",
        api_url="https://api.example.com",
    )
    j = _inituser(client)
    assert j["endpoints"] == {"api_url": "https://api.example.com"}


def test_appversion_endpoint(
    client: CustomClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The /appversion endpoint reads, validates, updates and deletes the record"""
    monkeypatch.setattr(basics, "CRON_SECRET", CRON_SECRET)
    # Local development allows all scheduler requests; disable that
    # shortcut so that the secret is actually checked
    monkeypatch.setattr(basics, "running_local", False)
    headers = {"X-Cron-Secret": CRON_SECRET}

    # Unauthorized
    resp = client.get("/appversion")
    assert resp.status_code == 403
    resp = client.post("/appversion", json={"min_supported_version": "1.0.0"})
    assert resp.status_code == 403

    # Nothing configured
    resp = client.get("/appversion", headers=headers)
    assert resp.status_code == 200
    assert resp.json == {"ok": True, "config": None}

    # Validation failures
    for body in (
        {"latest_version": "1.0.0"},  # missing min_supported_version
        {"min_supported_version": "1.0", "latest_version": "one"},
        {"min_supported_version": "1.0", "latest_version": "1.1", "foo": "x"},
        {
            "min_supported_version": "1.0",
            "latest_version": "1.1",
            "api_url": "http://insecure.example.com",
        },
    ):
        resp = client.post("/appversion", json=body, headers=headers)
        assert resp.status_code == 400, body
        assert resp.json is not None and resp.json["ok"] is False

    # Successful update
    body = {
        "min_supported_version": "1.4.0",
        "latest_version": "1.6.0",
        "android_min_supported_version": "1.5.0",
        "moves_url": "https://moves.example.com/",
        "update_message": "",  # empty means not set
    }
    resp = client.post("/appversion", json=body, headers=headers)
    assert resp.status_code == 200
    assert resp.json is not None and resp.json["ok"] is True
    config = resp.json["config"]
    assert config["min_supported_version"] == "1.4.0"
    assert config["latest_version"] == "1.6.0"
    assert config["android_min_supported_version"] == "1.5.0"
    assert config["moves_url"] == "https://moves.example.com/"
    assert config.get("update_message") is None
    assert config.get("ios_min_supported_version") is None

    # Reading it back
    resp = client.get("/appversion", headers=headers)
    assert resp.status_code == 200
    assert resp.json is not None and resp.json["config"] == config

    # Deletion
    resp = client.post("/appversion", json={"delete": True}, headers=headers)
    assert resp.status_code == 200
    assert resp.json == {"ok": True, "config": None}
    resp = client.get("/appversion", headers=headers)
    assert resp.json == {"ok": True, "config": None}

