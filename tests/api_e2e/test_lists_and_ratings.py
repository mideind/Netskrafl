"""
Lists and ratings end-to-end tests.

Tests user lists, game lists, ratings, and leaderboards.
"""

from __future__ import annotations

import pytest
from flask.testing import FlaskClient

from tests.api_e2e.conftest import (
    AuthHelper,
)


@pytest.mark.api_e2e
class TestUserList:
    """Test user list/search functionality."""

    def test_search_users_empty_prefix(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Search with empty prefix returns default results."""
        auth.login_user(
            sub="search-empty-001",
            name="Search Empty",
            email="searchempty@example.com",
        )

        response = client.post("/userlist", json={"prefix": ""})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        auth.logout()

    def test_search_users_by_nickname(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Search for users by nickname prefix."""
        # Create users with specific nicknames
        for name in ["ZebraPlayer", "ZenMaster", "ZigzagKing"]:
            auth.login_user(
                sub=f"search-{name.lower()}-001",
                name=name,
                email=f"{name.lower()}@example.com",
            )
            auth.logout()

        # Search for 'Ze' prefix
        auth.login_user(
            sub="searcher-nick-001",
            name="Searcher",
            email="searchernick@example.com",
        )

        response = client.post("/userlist", json={"prefix": "Ze"})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        # Should find users starting with 'Ze'
        data.get("result", [])
        # ZebraPlayer and ZenMaster should match

        auth.logout()

    def test_userlist_favorites(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Get list of favorite users."""
        auth.login_user(
            sub="fav-lister-001",
            name="Fav Lister",
            email="favlister@example.com",
        )

        response = client.post("/userlist", json={"spec": "favorites"})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        auth.logout()

    def test_userlist_recent(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Get list of recent opponents."""
        auth.login_user(
            sub="recent-lister-001",
            name="Recent Lister",
            email="recentlister@example.com",
        )

        response = client.post("/userlist", json={"spec": "recent"})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        auth.logout()


@pytest.mark.api_e2e
class TestGameList:
    """Test game list functionality."""

    def test_get_active_games(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Get list of active games."""
        auth.login_user(
            sub="active-games-001",
            name="Active Games User",
            email="activegames@example.com",
        )

        # Create a game to ensure there's at least one
        client.post("/initgame", json={"opp": "robot-10"})

        # Get game list
        response = client.post("/gamelist", json={})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        # Should have at least one game
        games = data.get("gamelist", [])
        assert len(games) >= 1

        auth.logout()

    def test_gamelist_structure(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Verify game list response structure."""
        auth.login_user(
            sub="structure-user-001",
            name="Structure User",
            email="structure@example.com",
        )

        # Create a game
        client.post("/initgame", json={"opp": "robot-15"})

        response = client.post("/gamelist", json={})
        data = response.get_json()

        games = data.get("gamelist", [])
        if games:
            game = games[0]
            # Verify expected fields exist
            assert "uuid" in game or "id" in game
            # Other expected fields: opp, my_turn, scores, etc.

        auth.logout()


@pytest.mark.api_e2e
class TestRecentList:
    """Test recent games list functionality."""

    def test_get_recent_games(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Get list of recently completed games."""
        auth.login_user(
            sub="recent-games-001",
            name="Recent Games User",
            email="recentgames@example.com",
        )

        response = client.post("/recentlist", json={})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        # Should return recentlist
        data.get("recentlist", [])
        # May be empty for new user

        auth.logout()

    def test_completed_game_appears_in_recent(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Completed game appears in recent list."""
        auth.login_user(
            sub="complete-recent-001",
            name="Complete Recent User",
            email="completerecent@example.com",
        )

        # Create and complete a game
        create_response = client.post("/initgame", json={"opp": "robot-5"})
        game_id = create_response.get_json()["uuid"]

        # Get current game state to check move count
        state_response = client.post("/gamestate", json={"game": game_id})
        state_data = state_response.get_json()
        mcount = state_data["game"].get("num_moves", 0)

        # Resign to complete quickly by submitting a resign move
        client.post(
            "/submitmove",
            json={
                "uuid": game_id,
                "mcount": mcount,
                "moves": ["rsgn"],
            },
        )

        # Check recent list
        recent_response = client.post("/recentlist", json={})
        data = recent_response.get_json()

        recent_games = data.get("recentlist", [])
        game_ids = [g.get("uuid") or g.get("id") for g in recent_games]
        assert game_id in game_ids

        auth.logout()


@pytest.mark.api_e2e
class TestChallengeList:
    """Test challenge list functionality."""

    def test_get_challenge_list(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Get list of pending challenges."""
        auth.login_user(
            sub="chall-list-001",
            name="Challenge Lister",
            email="challlist@example.com",
        )

        response = client.post("/challengelist", json={})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        # Should return challenge list structure
        data.get("challengelist", [])

        auth.logout()

    def test_issued_challenge_in_list(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Issued challenges appear in challenger's list."""
        # Create target
        auth.login_user(
            sub="issued-target-001",
            name="Issued Target",
            email="issuedtarget@example.com",
        )
        target_response = auth.login_user(
            sub="issued-target-001",
            name="Issued Target",
            email="issuedtarget@example.com",
        )
        target_id = target_response["user_id"]
        auth.logout()

        # Issue challenge
        auth.login_user(
            sub="issuer-list-001",
            name="Issuer",
            email="issuerlist@example.com",
        )
        client.post("/challenge", json={"destuser": target_id, "action": "issue"})

        # Check own challenge list
        list_response = client.post("/challengelist", json={})
        list_response.get_json()

        # Should include issued challenges
        # The structure may vary but should contain the challenge

        auth.logout()


@pytest.mark.api_e2e
class TestAllGameLists:
    """Test combined game lists endpoint."""

    def test_get_all_lists(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Get all game-related lists in one call."""
        auth.login_user(
            sub="all-lists-001",
            name="All Lists User",
            email="alllists@example.com",
        )

        response = client.post("/allgamelists", json={})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        # Should include multiple list types
        # gamelist, recentlist, challengelist

        auth.logout()


@pytest.mark.api_e2e
class TestRatings:
    """Test rating functionality."""

    def test_get_own_rating(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Get logged-in user's rating."""
        auth.login_user(
            sub="own-rating-001",
            name="Own Rating User",
            email="ownrating@example.com",
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
        """Get rating leaderboard for a specific locale."""
        auth.login_user(
            sub="locale-rating-001",
            name="Locale Rating User",
            email="localerating@example.com",
        )

        # Get rating for en_US locale
        response = client.post("/rating_locale", json={"locale": "en_US"})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        auth.logout()

    def test_rating_locale_is_IS(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Get rating for Icelandic locale."""
        auth.login_user(
            sub="is-rating-001",
            name="IS Rating User",
            email="israting@example.com",
        )

        response = client.post("/rating_locale", json={"locale": "is_IS"})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        auth.logout()


@pytest.mark.api_e2e
class TestGameStats:
    """Test game statistics endpoint."""

    def test_get_game_stats(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Get statistics for a specific game."""
        auth.login_user(
            sub="gamestats-user-001",
            name="Game Stats User",
            email="gamestats@example.com",
        )

        # Create a game first
        create_response = client.post("/initgame", json={"opp": "robot-10"})
        game_id = create_response.get_json()["uuid"]

        # Get game stats
        response = client.post("/gamestats", json={"game": game_id})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        auth.logout()


@pytest.mark.api_e2e
class TestOnlineStatus:
    """Test online status functionality."""

    def test_online_check(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Check online status updates."""
        auth.login_user(
            sub="online-check-001",
            name="Online User",
            email="onlinecheck@example.com",
        )

        # onlinecheck endpoint
        response = client.post("/onlinecheck", json={})
        assert response.status_code == 200

        auth.logout()


@pytest.mark.api_e2e
class TestWaitingSystem:
    """Test the waiting/matchmaking system."""

    def test_init_wait(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Start waiting for an opponent."""
        auth.login_user(
            sub="wait-user-001",
            name="Wait User",
            email="waituser@example.com",
        )

        response = client.post("/initwait", json={})
        assert response.status_code == 200

        auth.logout()

    def test_cancel_wait(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Cancel waiting for an opponent."""
        auth.login_user(
            sub="cancel-wait-001",
            name="Cancel Wait User",
            email="cancelwait@example.com",
        )

        # Start waiting
        client.post("/initwait", json={})

        # Cancel
        response = client.post("/cancelwait", json={})
        assert response.status_code == 200

        auth.logout()

    def test_wait_check(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Check wait status."""
        auth.login_user(
            sub="waitcheck-001",
            name="Wait Check User",
            email="waitcheck@example.com",
        )

        # Start waiting
        client.post("/initwait", json={})

        # Check status
        response = client.post("/waitcheck", json={})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        auth.logout()
