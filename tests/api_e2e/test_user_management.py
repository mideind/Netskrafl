"""
User management end-to-end tests.

Tests user profile, stats, and preferences.
"""

from __future__ import annotations

import pytest
from flask.testing import FlaskClient

from tests.api_e2e.conftest import AuthHelper


@pytest.mark.api_e2e
class TestUserStats:
    """Test user stats retrieval."""

    def test_get_own_stats(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Get stats for the logged-in user."""
        login_response = auth.login_user(
            sub="stats-user-001",
            name="Stats User",
            email="stats@example.com",
        )
        login_response["user_id"]

        # Request own stats (no user parameter)
        response = client.post("/userstats", json={})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        # Should return stats structure
        # The exact fields depend on implementation
        assert "result" not in data or data.get("result") == 0

        auth.logout()

    def test_get_other_user_stats(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Get stats for another user."""
        # Create first user
        auth.login_user(
            sub="other-stats-user-001",
            name="Other User",
            email="other@example.com",
        )
        auth.logout()

        # Login as second user
        auth.login_user(
            sub="viewer-user-001",
            name="Viewer",
            email="viewer@example.com",
        )

        # Request other user's stats by specifying user parameter
        # The exact parameter name may vary (uid, user, etc.)
        response = client.post("/userstats", json={"uid": "other-stats-user-001"})
        assert response.status_code == 200

        auth.logout()


@pytest.mark.api_e2e
class TestUserPreferences:
    """Test user preference management."""

    def test_set_user_preference(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Set a user preference."""
        auth.login_user(
            sub="pref-user-001",
            name="Pref User",
            email="pref@example.com",
        )

        # Set a preference
        response = client.post(
            "/setuserpref",
            json={
                "pref": "beginner",
                "val": True,
            },
        )
        assert response.status_code == 200

        auth.logout()

    def test_set_fairplay_preference(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Set fairplay preference."""
        auth.login_user(
            sub="fairplay-user-001",
            name="Fair Player",
            email="fairplay@example.com",
        )

        response = client.post(
            "/setuserpref",
            json={
                "pref": "fairplay",
                "val": True,
            },
        )
        assert response.status_code == 200

        auth.logout()

    def test_load_user_preferences(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Load saved user preferences."""
        auth.login_user(
            sub="load-pref-user-001",
            name="Load Pref User",
            email="loadpref@example.com",
        )

        # Set a preference first
        client.post(
            "/setuserpref",
            json={
                "pref": "beginner",
                "val": True,
            },
        )

        # Load preferences
        response = client.post("/loaduserprefs", json={})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        auth.logout()

    def test_save_user_preferences(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Save multiple user preferences at once."""
        auth.login_user(
            sub="save-pref-user-001",
            name="Save Pref User",
            email="savepref@example.com",
        )

        # Save multiple preferences
        response = client.post(
            "/saveuserprefs",
            json={
                "prefs": {
                    "beginner": True,
                    "fairplay": False,
                },
            },
        )
        assert response.status_code == 200

        auth.logout()


@pytest.mark.api_e2e
class TestUserInit:
    """Test user initialization."""

    def test_init_user(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Initialize user session data."""
        auth.login_user(
            sub="init-user-001",
            name="Init User",
            email="init@example.com",
        )

        # inituser returns user info and prefs
        response = client.post("/inituser", json={})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        assert data.get("ok") is True

        # Should include user information in userprefs or userstats
        # The inituser response contains userprefs, userstats, and firebase_token
        assert "userprefs" in data or "userstats" in data

        auth.logout()


@pytest.mark.api_e2e
class TestUserLists:
    """Test user list/search functionality."""

    def test_search_users_by_prefix(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Search for users by nickname prefix."""
        # Create some users with searchable names
        auth.login_user(
            sub="search-alice-001",
            name="Alice",
            email="alice.search@example.com",
        )
        auth.logout()

        auth.login_user(
            sub="search-albert-001",
            name="Albert",
            email="albert.search@example.com",
        )
        auth.logout()

        # Login and search
        auth.login_user(
            sub="searcher-001",
            name="Searcher",
            email="searcher@example.com",
        )

        # Search for users starting with "Al"
        response = client.post("/userlist", json={"prefix": "Al"})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        # Should return list of matching users
        # The response structure may include 'result' or 'users'

        auth.logout()

    def test_userlist_with_spec(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Get user list with specific parameters."""
        auth.login_user(
            sub="userlist-spec-001",
            name="Spec User",
            email="spec@example.com",
        )

        # Request userlist with various spec options
        response = client.post(
            "/userlist",
            json={
                "spec": "robots",  # Get robot opponents
            },
        )
        assert response.status_code == 200

        auth.logout()


@pytest.mark.api_e2e
class TestRatings:
    """Test rating functionality."""

    def test_get_rating(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Get user's rating."""
        auth.login_user(
            sub="rating-user-001",
            name="Rated User",
            email="rated@example.com",
        )

        response = client.post("/rating", json={})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        auth.logout()

    def test_get_rating_by_locale(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Get rating leaderboard by locale."""
        auth.login_user(
            sub="locale-rating-user-001",
            name="Locale Rating",
            email="localerating@example.com",
        )

        # Get rating for a specific locale
        response = client.post(
            "/rating_locale",
            json={"locale": "en_US"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        auth.logout()


@pytest.mark.api_e2e
class TestFavorites:
    """Test favorite user functionality."""

    def test_add_favorite(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Add a user to favorites."""
        # Create target user first
        auth.login_user(
            sub="fav-target-001",
            name="Fav Target",
            email="favtarget@example.com",
        )
        target_response = auth.login_user(
            sub="fav-target-001",
            name="Fav Target",
            email="favtarget@example.com",
        )
        target_id = target_response["user_id"]
        auth.logout()

        # Login as another user and add favorite
        auth.login_user(
            sub="fav-user-001",
            name="Fav User",
            email="favuser@example.com",
        )

        response = client.post(
            "/favorite",
            json={
                "destuser": target_id,
                "action": "add",
            },
        )
        assert response.status_code == 200

        auth.logout()

    def test_remove_favorite(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Remove a user from favorites."""
        # Create and add favorite first
        auth.login_user(
            sub="fav-remove-target-001",
            name="Remove Target",
            email="removetarget@example.com",
        )
        target_response = auth.login_user(
            sub="fav-remove-target-001",
            name="Remove Target",
            email="removetarget@example.com",
        )
        target_id = target_response["user_id"]
        auth.logout()

        auth.login_user(
            sub="fav-remover-001",
            name="Fav Remover",
            email="favremover@example.com",
        )

        # Add first
        client.post(
            "/favorite",
            json={
                "destuser": target_id,
                "action": "add",
            },
        )

        # Then remove
        response = client.post(
            "/favorite",
            json={
                "destuser": target_id,
                "action": "delete",
            },
        )
        assert response.status_code == 200

        auth.logout()


@pytest.mark.api_e2e
class TestBlockUser:
    """Test user blocking functionality."""

    def test_block_user(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Block another user."""
        # Create target user
        auth.login_user(
            sub="block-target-001",
            name="Block Target",
            email="blocktarget@example.com",
        )
        target_response = auth.login_user(
            sub="block-target-001",
            name="Block Target",
            email="blocktarget@example.com",
        )
        target_id = target_response["user_id"]
        auth.logout()

        # Login and block
        auth.login_user(
            sub="blocker-001",
            name="Blocker",
            email="blocker@example.com",
        )

        response = client.post(
            "/blockuser",
            json={
                "destuser": target_id,
                "action": "add",
            },
        )
        assert response.status_code == 200

        auth.logout()

    def test_unblock_user(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Unblock a blocked user."""
        # Create target user
        auth.login_user(
            sub="unblock-target-001",
            name="Unblock Target",
            email="unblocktarget@example.com",
        )
        target_response = auth.login_user(
            sub="unblock-target-001",
            name="Unblock Target",
            email="unblocktarget@example.com",
        )
        target_id = target_response["user_id"]
        auth.logout()

        # Login, block, then unblock
        auth.login_user(
            sub="unblocker-001",
            name="Unblocker",
            email="unblocker@example.com",
        )

        # Block first
        client.post(
            "/blockuser",
            json={
                "destuser": target_id,
                "action": "add",
            },
        )

        # Then unblock
        response = client.post(
            "/blockuser",
            json={
                "destuser": target_id,
                "action": "delete",
            },
        )
        assert response.status_code == 200

        auth.logout()
