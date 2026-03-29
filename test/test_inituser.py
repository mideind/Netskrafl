"""

    Tests for the /inituser API endpoint
    Copyright © 2025 Miðeind ehf.

    This module tests the /inituser API endpoint, including
    the app_version field behavior.

"""

from utils import (
    CustomClient,
    client,
    create_user,
    login_user,
    u1,
)
from skrafldb import AppVersionModel, Client


def test_inituser_no_app_version(client: CustomClient, u1: str) -> None:
    """Test that inituser returns app_version as null when no entity exists."""
    # Log in as user 1
    client.set_authorization(True)
    resp = login_user(client, 1, client_type="explo")
    assert resp.status_code == 200

    # Call /inituser
    resp = client.post("/inituser")
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json.get("ok") is True
    assert "userprefs" in resp.json
    assert "userstats" in resp.json
    assert "firebase_token" in resp.json
    # No AppVersionModel entity exists, so app_version should be null
    assert resp.json.get("app_version") is None


def test_inituser_with_app_version(client: CustomClient, u1: str) -> None:
    """Test that inituser returns app_version when the entity is configured."""
    # Create an AppVersionModel entity
    with Client.get_context():
        av = AppVersionModel(
            id="app_version",
            min_supported_version="1.2.0",
            latest_version="1.5.0",
            update_message="Please update for new features!",
        )
        av.put()

    try:
        # Log in as user 1
        client.set_authorization(True)
        resp = login_user(client, 1, client_type="explo")
        assert resp.status_code == 200

        # Call /inituser
        resp = client.post("/inituser")
        assert resp.status_code == 200
        assert resp.json is not None
        assert resp.json.get("ok") is True
        app_version = resp.json.get("app_version")
        assert app_version is not None
        assert app_version["min_supported_version"] == "1.2.0"
        assert app_version["latest_version"] == "1.5.0"
        assert app_version["update_message"] == "Please update for new features!"
    finally:
        # Clean up the AppVersionModel entity
        with Client.get_context():
            av = AppVersionModel.get_versions()
            if av is not None:
                av.key.delete()


def test_inituser_app_version_no_message(client: CustomClient, u1: str) -> None:
    """Test that update_message is omitted when not set."""
    with Client.get_context():
        av = AppVersionModel(
            id="app_version",
            min_supported_version="2.0.0",
            latest_version="2.1.0",
        )
        av.put()

    try:
        client.set_authorization(True)
        resp = login_user(client, 1, client_type="explo")
        assert resp.status_code == 200

        resp = client.post("/inituser")
        assert resp.status_code == 200
        assert resp.json is not None
        assert resp.json.get("ok") is True
        app_version = resp.json.get("app_version")
        assert app_version is not None
        assert app_version["min_supported_version"] == "2.0.0"
        assert app_version["latest_version"] == "2.1.0"
        assert "update_message" not in app_version
    finally:
        with Client.get_context():
            av = AppVersionModel.get_versions()
            if av is not None:
                av.key.delete()
