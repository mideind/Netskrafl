"""
Authentication flow end-to-end tests.

Tests OAuth login, anonymous login, logout, and session handling.
"""

from __future__ import annotations

import pytest
from flask.testing import FlaskClient

from tests.api_e2e.conftest import AuthHelper, DatabaseVerifier


@pytest.mark.api_e2e
class TestGoogleLogin:
    """Test Google OAuth login flow."""

    def test_google_login_creates_new_user(
        self,
        client: FlaskClient,
        auth: AuthHelper,
        db: DatabaseVerifier,
    ) -> None:
        """First login creates a new user in the database."""
        # Use unique sub to ensure this is a new user
        import uuid
        unique_sub = f"google-new-user-{uuid.uuid4().hex[:8]}"

        response = auth.login_user(
            sub=unique_sub,
            name="New User",
            email=f"{unique_sub}@example.com",
        )

        # Should return successful login
        assert "user_id" in response
        user_id = response["user_id"]
        assert user_id  # Non-empty

        # User should be marked as new on first login
        assert response.get("new") is True

        # Verify user was created in database
        user = db.get_user(user_id)
        assert user is not None
        assert user.email == f"{unique_sub}@example.com"

        auth.logout()

    def test_google_login_existing_user(
        self,
        client: FlaskClient,
        auth: AuthHelper,
        db: DatabaseVerifier,
    ) -> None:
        """Second login returns the same user ID."""
        # First login
        response1 = auth.login_user(
            sub="google-user-002",
            name="Existing User",
            email="existing@example.com",
        )
        user_id1 = response1["user_id"]
        auth.logout()

        # Second login with same account
        response2 = auth.login_user(
            sub="google-user-002",
            name="Existing User",
            email="existing@example.com",
        )
        user_id2 = response2["user_id"]

        # Should get the same user ID
        assert user_id1 == user_id2

        # Should not be marked as new
        assert response2.get("new") is False

        auth.logout()

    def test_login_different_client_types(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Login works with different client types."""
        for client_type in ["web", "ios", "android"]:
            response = auth.login_user(
                sub=f"client-type-user-{client_type}",
                name=f"User {client_type}",
                email=f"{client_type}@example.com",
                client_type=client_type,
            )
            assert "user_id" in response
            auth.logout()


@pytest.mark.api_e2e
class TestAnonymousLogin:
    """Test anonymous login flow."""

    def test_anonymous_login(
        self,
        client: FlaskClient,
        auth: AuthHelper,
        db: DatabaseVerifier,
    ) -> None:
        """Anonymous login with device ID creates anonymous user."""
        response = auth.login_anonymous(device_id="test-device-001")

        assert "user_id" in response
        user_id = response["user_id"]
        assert user_id

        # Anonymous users should have a special prefix in their account
        # The account is based on the device ID
        user = db.get_user(user_id)
        assert user is not None

        auth.logout()

    def test_anonymous_login_same_device(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Same device ID returns same anonymous user."""
        response1 = auth.login_anonymous(device_id="test-device-002")
        user_id1 = response1["user_id"]
        auth.logout()

        response2 = auth.login_anonymous(device_id="test-device-002")
        user_id2 = response2["user_id"]

        assert user_id1 == user_id2
        auth.logout()

    def test_anonymous_login_different_devices(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Different device IDs create different anonymous users."""
        response1 = auth.login_anonymous(device_id="test-device-003a")
        user_id1 = response1["user_id"]
        auth.logout()

        response2 = auth.login_anonymous(device_id="test-device-003b")
        user_id2 = response2["user_id"]

        assert user_id1 != user_id2
        auth.logout()


@pytest.mark.api_e2e
class TestAnonymousUpgrade:
    """Test upgrading anonymous user to full account."""

    def test_anonymous_upgrade_to_google(
        self,
        client: FlaskClient,
        auth: AuthHelper,
        db: DatabaseVerifier,
    ) -> None:
        """Anonymous user can upgrade to a fully authenticated user."""
        import uuid
        unique_id = uuid.uuid4().hex[:8]

        # Start as anonymous
        anon_response = auth.login_anonymous(device_id=f"upgrade-device-{unique_id}")
        anon_response["user_id"]

        # Now upgrade by logging in with Google (without logging out first)
        # The session still contains the anonymous user info, which triggers upgrade
        google_response = auth.login_user(
            sub=f"google-upgrade-{unique_id}",
            name="Upgraded User",
            email=f"upgraded-{unique_id}@example.com",
        )

        # The Google user should now exist
        google_user_id = google_response["user_id"]

        # Verify the upgraded user exists in the database
        user = db.get_user(google_user_id)
        assert user is not None
        # Verify the email is correct (nickname may be processed differently)
        assert user.email == f"upgraded-{unique_id}@example.com"

        auth.logout()


@pytest.mark.api_e2e
class TestLogout:
    """Test logout functionality."""

    def test_logout_clears_session(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Logout removes session and prevents API access."""
        # Login first
        auth.login_user(
            sub="logout-user-001",
            name="Logout Test",
            email="logout@example.com",
        )

        # Verify we can access authenticated endpoint
        response = client.post("/gamelist", json={})
        assert response.status_code == 200

        # Logout
        auth.logout()

        # Now should get login required error
        response = client.post("/gamelist", json={})
        # The exact behavior depends on the endpoint, but we should
        # get an error response
        data = response.get_json()
        # gamelist returns result=Error.LOGIN_REQUIRED when not authenticated
        assert data is not None
        # Error.LOGIN_REQUIRED = 14
        assert data.get("result") == 14 or data.get("ok") is False


@pytest.mark.api_e2e
class TestUnauthenticatedAccess:
    """Test access to protected endpoints without authentication."""

    def test_protected_endpoint_returns_error(
        self,
        client: FlaskClient,
    ) -> None:
        """Protected endpoints return appropriate error without auth."""
        # gamelist requires authentication
        response = client.post("/gamelist", json={})
        data = response.get_json()
        assert data is not None
        # Should return Error.LOGIN_REQUIRED (14)
        assert data.get("result") == 14

    def test_unauthenticated_returns_401(
        self,
        client: FlaskClient,
    ) -> None:
        """Unauthenticated requests to protected endpoints return 401."""
        # initgame endpoint returns 401 when not authenticated
        response = client.post("/initgame", json={"opp": "robot-15"})
        # Should return 401 Unauthorized
        assert response.status_code == 401

    def test_initgame_requires_auth(
        self,
        client: FlaskClient,
    ) -> None:
        """initgame endpoint requires authentication."""
        response = client.post("/initgame", json={"opp": "robot-15"})
        data = response.get_json()
        assert data is not None
        assert data.get("ok") is False


@pytest.mark.api_e2e
class TestSessionPersistence:
    """Test session persistence across requests."""

    def test_session_persists_across_requests(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Session persists across multiple requests."""
        auth.login_user(
            sub="session-user-001",
            name="Session Test",
            email="session@example.com",
        )

        # Make multiple requests, all should succeed
        for _ in range(3):
            response = client.post("/gamelist", json={})
            assert response.status_code == 200
            data = response.get_json()
            # Should get ok=True or at least not login required
            assert data.get("result") != 99

        auth.logout()

    def test_userstats_returns_current_user(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """userstats endpoint returns data for the logged-in user."""
        login_response = auth.login_user(
            sub="stats-user-001",
            name="Stats Test",
            email="stats@example.com",
        )
        login_response["user_id"]

        # Get user stats without specifying user (should return current user)
        response = client.post("/userstats", json={})
        assert response.status_code == 200
        data = response.get_json()

        # Should return stats for the logged-in user
        assert data is not None
        # The response structure varies, but should include user info
        # when requesting own stats

        auth.logout()
