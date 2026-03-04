"""
Paywall enforcement end-to-end tests.

Tests premium robot access restrictions, game count limits,
autoplayer definitions, and the /userlist premium field.
"""

from __future__ import annotations

import pytest
from flask.testing import FlaskClient

from tests.api_e2e.conftest import AuthHelper


def _set_user_paid(user_id: str, paid: bool) -> None:
    """Set the has_paid and friend status of a test user via the User model."""
    from skrafluser import User

    user = User.load_if_exists(user_id)
    assert user is not None, f"User {user_id} not found"
    user.set_has_paid(paid)
    user.set_friend(paid)
    user.update()


# =============================================================================
# Autoplayer definition tests (no Flask client needed)
# =============================================================================


class TestAutoplayerDefinitions:
    """Verify autoplayer lists have correct premium flags."""

    def test_icelandic_robots_count_and_premium(self) -> None:
        """Icelandic locale should have 4 robots with correct premium flags."""
        from autoplayers import autoplayer_for_locale

        robots = autoplayer_for_locale("is")
        assert len(robots) == 4

        by_name = {r.name: r for r in robots}
        assert by_name["Fullsterkur"].premium is True
        assert by_name["Miðlungur"].premium is True
        assert by_name["Hálfdrættingur"].premium is False
        assert by_name["Amlóði"].premium is False

    def test_english_robots_premium(self) -> None:
        """English locale should have 4 robots with correct premium flags."""
        from autoplayers import autoplayer_for_locale

        robots = autoplayer_for_locale("en")
        assert len(robots) == 4

        by_name = {r.name: r for r in robots}
        assert by_name["Freyja"].premium is True
        assert by_name["Idun"].premium is True
        assert by_name["Frigg"].premium is False
        assert by_name["Sif"].premium is False

    def test_autoplayer_is_premium_helper(self) -> None:
        """The autoplayer_is_premium helper should return correct values."""
        from autoplayers import autoplayer_is_premium

        # Icelandic: level 0 (Fullsterkur) and 8 (Miðlungur) are premium
        assert autoplayer_is_premium("is", 0) is True
        assert autoplayer_is_premium("is", 8) is True
        # Level 15 (Hálfdrættingur) and 20 (Amlóði) are free
        assert autoplayer_is_premium("is", 15) is False
        assert autoplayer_is_premium("is", 20) is False

    def test_all_locales_have_four_robots(self) -> None:
        """Every locale should have exactly 4 robots."""
        from autoplayers import autoplayer_for_locale

        for locale in ["is", "en", "en_US", "nb", "nn", "pl"]:
            robots = autoplayer_for_locale(locale)
            assert len(robots) == 4, f"Locale {locale} has {len(robots)} robots"

    def test_all_locales_premium_pattern(self) -> None:
        """Every locale should have 2 premium and 2 free robots."""
        from autoplayers import autoplayer_for_locale

        for locale in ["is", "en", "en_US", "nb", "nn", "pl"]:
            robots = autoplayer_for_locale(locale)
            premium_count = sum(1 for r in robots if r.premium)
            assert premium_count == 2, (
                f"Locale {locale}: expected 2 premium robots, got {premium_count}"
            )


# =============================================================================
# /userlist premium field tests
# =============================================================================


@pytest.mark.api_e2e
class TestUserListPremiumField:
    """Verify the /userlist endpoint includes premium flags for robots."""

    def test_robot_list_includes_premium_field(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Robot list entries should include a premium boolean field."""
        auth.login_user(
            sub="paywall-robotlist-001",
            name="Robot Lister",
            email="robotlister@example.com",
        )

        response = client.post("/userlist", json={"query": "robots"})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        userlist = data.get("userlist", [])
        assert len(userlist) == 4, f"Expected 4 robots, got {len(userlist)}"

        for entry in userlist:
            assert "premium" in entry, f"Missing premium field in {entry['userid']}"
            assert isinstance(entry["premium"], bool)

        auth.logout()

    def test_robot_list_premium_flags_correct(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Robot list premium flags should match autoplayer definitions."""
        auth.login_user(
            sub="paywall-premflags-001",
            name="Premium Flag Checker",
            email="premflags@example.com",
        )

        response = client.post("/userlist", json={"query": "robots"})
        data = response.get_json()
        userlist = data.get("userlist", [])

        by_userid = {e["userid"]: e for e in userlist}
        # Level 0 and 8 are premium; 15 and 20 are free
        assert by_userid["robot-0"]["premium"] is True
        assert by_userid["robot-8"]["premium"] is True
        assert by_userid["robot-15"]["premium"] is False
        assert by_userid["robot-20"]["premium"] is False

        auth.logout()


# =============================================================================
# Premium robot enforcement tests
# =============================================================================


@pytest.mark.api_e2e
class TestPremiumRobotEnforcement:
    """Test that free users cannot start games against premium robots."""

    def test_free_user_blocked_from_premium_robot(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Free user should get premium_required when starting premium robot game."""
        login_data = auth.login_user(
            sub="paywall-free-001",
            name="Free User",
            email="freeuser@example.com",
        )
        user_id = login_data["user_id"]
        # Ensure user is not a paying user
        _set_user_paid(user_id, False)

        # Try to start a game against Fullsterkur (level 0, premium)
        response = client.post("/initgame", json={"opp": "robot-0"})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        assert data.get("ok") is False
        assert data.get("err") == "premium_required"

        auth.logout()

    def test_free_user_blocked_from_medium_robot(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Free user should get premium_required for Miðlungur (level 8)."""
        login_data = auth.login_user(
            sub="paywall-free-002",
            name="Free User 2",
            email="freeuser2@example.com",
        )
        user_id = login_data["user_id"]
        _set_user_paid(user_id, False)

        response = client.post("/initgame", json={"opp": "robot-8"})
        data = response.get_json()
        assert data.get("ok") is False
        assert data.get("err") == "premium_required"

        auth.logout()

    def test_free_user_can_play_free_robots(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Free user should be able to start games against free robots."""
        login_data = auth.login_user(
            sub="paywall-free-003",
            name="Free User 3",
            email="freeuser3@example.com",
        )
        user_id = login_data["user_id"]
        _set_user_paid(user_id, False)

        # Hálfdrættingur (level 15) is free
        response = client.post("/initgame", json={"opp": "robot-15"})
        data = response.get_json()
        assert data.get("ok") is True
        assert "uuid" in data

        auth.logout()

    def test_paid_user_can_play_premium_robots(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Paid user should be able to start games against premium robots."""
        login_data = auth.login_user(
            sub="paywall-paid-001",
            name="Paid User",
            email="paiduser@example.com",
        )
        user_id = login_data["user_id"]
        _set_user_paid(user_id, True)

        # Fullsterkur (level 0, premium) should work for paid users
        response = client.post("/initgame", json={"opp": "robot-0"})
        data = response.get_json()
        assert data.get("ok") is True
        assert "uuid" in data

        # Miðlungur (level 8, premium) should also work
        response = client.post("/initgame", json={"opp": "robot-8"})
        data = response.get_json()
        assert data.get("ok") is True
        assert "uuid" in data

        auth.logout()


# =============================================================================
# Game count limit enforcement tests
# =============================================================================


@pytest.mark.api_e2e
class TestGameCountLimit:
    """Test that free users are limited to MAX_FREE_GAMES concurrent games."""

    def test_free_user_hits_game_limit(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Free user should be blocked after reaching the game limit."""
        from config import MAX_FREE_GAMES

        login_data = auth.login_user(
            sub="paywall-limit-001",
            name="Limit User",
            email="limituser@example.com",
        )
        user_id = login_data["user_id"]
        _set_user_paid(user_id, False)

        # Start MAX_FREE_GAMES games (using free robots)
        for i in range(MAX_FREE_GAMES):
            response = client.post("/initgame", json={"opp": "robot-15"})
            data = response.get_json()
            assert data.get("ok") is True, (
                f"Game {i + 1} of {MAX_FREE_GAMES} should succeed"
            )

        # The next game should be blocked
        response = client.post("/initgame", json={"opp": "robot-15"})
        data = response.get_json()
        assert data.get("ok") is False
        assert data.get("err") == "game_limit_reached"

        auth.logout()

    def test_paid_user_no_game_limit(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Paid user should not be limited by MAX_FREE_GAMES."""
        from config import MAX_FREE_GAMES

        login_data = auth.login_user(
            sub="paywall-nolimit-001",
            name="No Limit User",
            email="nolimituser@example.com",
        )
        user_id = login_data["user_id"]
        _set_user_paid(user_id, True)

        # Start more games than the free limit allows
        for i in range(MAX_FREE_GAMES + 1):
            response = client.post("/initgame", json={"opp": "robot-15"})
            data = response.get_json()
            assert data.get("ok") is True, (
                f"Game {i + 1} should succeed for paid user"
            )

        auth.logout()

    def test_game_limit_checked_before_premium(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Game limit should be checked before premium robot check."""
        from config import MAX_FREE_GAMES

        login_data = auth.login_user(
            sub="paywall-order-001",
            name="Order User",
            email="orderuser@example.com",
        )
        user_id = login_data["user_id"]
        _set_user_paid(user_id, False)

        # Fill up the game slots with free robot games
        for _ in range(MAX_FREE_GAMES):
            client.post("/initgame", json={"opp": "robot-20"})

        # Now try a premium robot — should get game_limit_reached
        # (not premium_required), since game limit is checked first
        response = client.post("/initgame", json={"opp": "robot-0"})
        data = response.get_json()
        assert data.get("ok") is False
        assert data.get("err") == "game_limit_reached"

        auth.logout()
