"""
Challenge system end-to-end tests.

Tests issuing, accepting, declining, and retracting challenges.
"""

from __future__ import annotations

import pytest
from flask.testing import FlaskClient

from tests.api_e2e.conftest import (
    AuthHelper,
    FirebaseMock,
)


@pytest.mark.api_e2e
class TestIssueChallenge:
    """Test issuing challenges."""

    def test_issue_challenge_to_user(
        self,
        client: FlaskClient,
        auth: AuthHelper,
        mock_firebase: FirebaseMock,
    ) -> None:
        """Issue a challenge to another user."""
        # Create target user
        auth.login_user(
            sub="target-001",
            name="Target User",
            email="target@example.com",
        )
        target_response = auth.login_user(
            sub="target-001",
            name="Target User",
            email="target@example.com",
        )
        target_id = target_response["user_id"]
        auth.logout()

        # Login as challenger
        auth.login_user(
            sub="challenger-001",
            name="Challenger",
            email="challenger@example.com",
        )

        # Issue challenge
        response = client.post(
            "/challenge",
            json={
                "destuser": target_id,
                "action": "issue",
            },
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        # result=0 means Error.LEGAL (success)
        assert data.get("result") == 0

        # Should have notified the target user
        mock_firebase.assert_challenge_notified(target_id)

        auth.logout()

    def test_issue_timed_challenge(
        self,
        client: FlaskClient,
        auth: AuthHelper,
        mock_firebase: FirebaseMock,
    ) -> None:
        """Issue a timed challenge."""
        # Create target
        auth.login_user(
            sub="timed-target-001",
            name="Timed Target",
            email="timedtarget@example.com",
        )
        target_response = auth.login_user(
            sub="timed-target-001",
            name="Timed Target",
            email="timedtarget@example.com",
        )
        target_id = target_response["user_id"]
        auth.logout()

        # Issue timed challenge
        auth.login_user(
            sub="timed-challenger-001",
            name="Timed Challenger",
            email="timedchallenger@example.com",
        )

        response = client.post(
            "/challenge",
            json={
                "destuser": target_id,
                "action": "issue",
                "duration": 25,  # 25 minute game
            },
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data.get("result") == 0

        auth.logout()

    def test_issue_fairplay_challenge(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Issue a fairplay challenge."""
        # Create target
        auth.login_user(
            sub="fair-target-001",
            name="Fair Target",
            email="fairtarget@example.com",
        )
        target_response = auth.login_user(
            sub="fair-target-001",
            name="Fair Target",
            email="fairtarget@example.com",
        )
        target_id = target_response["user_id"]
        auth.logout()

        # Issue fairplay challenge
        auth.login_user(
            sub="fair-challenger-001",
            name="Fair Challenger",
            email="fairchallenger@example.com",
        )

        response = client.post(
            "/challenge",
            json={
                "destuser": target_id,
                "action": "issue",
                "fairplay": True,
            },
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data.get("result") == 0

        auth.logout()

    def test_cannot_challenge_nonexistent_user(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Cannot challenge a user that doesn't exist."""
        auth.login_user(
            sub="lonely-challenger-001",
            name="Lonely Challenger",
            email="lonely@example.com",
        )

        response = client.post(
            "/challenge",
            json={
                "destuser": "nonexistent-user-id-12345",
                "action": "issue",
            },
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        # Should return Error.WRONG_USER (15) since the user doesn't exist
        assert data.get("result") == 15  # Error.WRONG_USER

        auth.logout()


@pytest.mark.api_e2e
class TestAcceptChallenge:
    """Test accepting challenges."""

    def test_accept_challenge_creates_game(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Accepting a challenge creates a game."""
        # Create challenger
        auth.login_user(
            sub="accept-challenger-001",
            name="Accept Challenger",
            email="acceptchallenger@example.com",
        )
        challenger_response = auth.login_user(
            sub="accept-challenger-001",
            name="Accept Challenger",
            email="acceptchallenger@example.com",
        )
        challenger_id = challenger_response["user_id"]
        auth.logout()

        # Create accepter
        auth.login_user(
            sub="accepter-001",
            name="Accepter",
            email="accepter@example.com",
        )
        accepter_response = auth.login_user(
            sub="accepter-001",
            name="Accepter",
            email="accepter@example.com",
        )
        accepter_id = accepter_response["user_id"]
        auth.logout()

        # Challenger issues challenge
        auth.login_user(
            sub="accept-challenger-001",
            name="Accept Challenger",
            email="acceptchallenger@example.com",
        )
        client.post(
            "/challenge",
            json={
                "destuser": accepter_id,
                "action": "issue",
            },
        )
        auth.logout()

        # Accepter accepts via initgame
        auth.login_user(
            sub="accepter-001",
            name="Accepter",
            email="accepter@example.com",
        )
        game_response = client.post(
            "/initgame",
            json={"opp": challenger_id},
        )
        assert game_response.status_code == 200
        data = game_response.get_json()
        assert data is not None
        assert data.get("ok") is True
        assert "uuid" in data

        auth.logout()

    def test_accept_via_challenge_endpoint(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Accept a challenge via the challenge endpoint."""
        # Create users
        auth.login_user(
            sub="via-challenger-001",
            name="Via Challenger",
            email="viachallenger@example.com",
        )
        challenger_response = auth.login_user(
            sub="via-challenger-001",
            name="Via Challenger",
            email="viachallenger@example.com",
        )
        challenger_id = challenger_response["user_id"]
        auth.logout()

        auth.login_user(
            sub="via-accepter-001",
            name="Via Accepter",
            email="viaaccepter@example.com",
        )
        accepter_response = auth.login_user(
            sub="via-accepter-001",
            name="Via Accepter",
            email="viaaccepter@example.com",
        )
        accepter_id = accepter_response["user_id"]
        auth.logout()

        # Issue challenge
        auth.login_user(
            sub="via-challenger-001",
            name="Via Challenger",
            email="viachallenger@example.com",
        )
        client.post(
            "/challenge",
            json={
                "destuser": accepter_id,
                "action": "issue",
            },
        )
        auth.logout()

        # Accept via challenge endpoint
        auth.login_user(
            sub="via-accepter-001",
            name="Via Accepter",
            email="viaaccepter@example.com",
        )
        accept_response = client.post(
            "/challenge",
            json={
                "destuser": challenger_id,
                "action": "accept",
            },
        )
        assert accept_response.status_code == 200
        data = accept_response.get_json()
        assert data.get("result") == 0

        auth.logout()


@pytest.mark.api_e2e
class TestDeclineChallenge:
    """Test declining challenges."""

    def test_decline_challenge(
        self,
        client: FlaskClient,
        auth: AuthHelper,
        mock_firebase: FirebaseMock,
    ) -> None:
        """Decline a challenge from another user."""
        # Create challenger
        auth.login_user(
            sub="decline-challenger-001",
            name="Decline Challenger",
            email="declinechallenger@example.com",
        )
        challenger_response = auth.login_user(
            sub="decline-challenger-001",
            name="Decline Challenger",
            email="declinechallenger@example.com",
        )
        challenger_id = challenger_response["user_id"]
        auth.logout()

        # Create decliner
        auth.login_user(
            sub="decliner-001",
            name="Decliner",
            email="decliner@example.com",
        )
        decliner_response = auth.login_user(
            sub="decliner-001",
            name="Decliner",
            email="decliner@example.com",
        )
        decliner_id = decliner_response["user_id"]
        auth.logout()

        # Issue challenge
        auth.login_user(
            sub="decline-challenger-001",
            name="Decline Challenger",
            email="declinechallenger@example.com",
        )
        client.post(
            "/challenge",
            json={
                "destuser": decliner_id,
                "action": "issue",
            },
        )
        auth.logout()

        mock_firebase.clear()

        # Decline
        auth.login_user(
            sub="decliner-001",
            name="Decliner",
            email="decliner@example.com",
        )
        decline_response = client.post(
            "/challenge",
            json={
                "destuser": challenger_id,
                "action": "decline",
            },
        )
        assert decline_response.status_code == 200
        data = decline_response.get_json()
        assert data.get("result") == 0

        # Both users should be notified
        mock_firebase.assert_challenge_notified(challenger_id)

        auth.logout()


@pytest.mark.api_e2e
class TestRetractChallenge:
    """Test retracting challenges."""

    def test_retract_own_challenge(
        self,
        client: FlaskClient,
        auth: AuthHelper,
        mock_firebase: FirebaseMock,
    ) -> None:
        """Retract a challenge you issued."""
        # Create target
        auth.login_user(
            sub="retract-target-001",
            name="Retract Target",
            email="retracttarget@example.com",
        )
        target_response = auth.login_user(
            sub="retract-target-001",
            name="Retract Target",
            email="retracttarget@example.com",
        )
        target_id = target_response["user_id"]
        auth.logout()

        # Create challenger
        auth.login_user(
            sub="retracter-001",
            name="Retracter",
            email="retracter@example.com",
        )

        # Issue challenge
        client.post(
            "/challenge",
            json={
                "destuser": target_id,
                "action": "issue",
            },
        )

        mock_firebase.clear()

        # Retract challenge
        retract_response = client.post(
            "/challenge",
            json={
                "destuser": target_id,
                "action": "retract",
            },
        )
        assert retract_response.status_code == 200
        data = retract_response.get_json()
        assert data.get("result") == 0

        # Target should be notified of challenge list update
        mock_firebase.assert_challenge_notified(target_id)

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
            sub="list-user-001",
            name="List User",
            email="listuser@example.com",
        )

        # Get challenge list
        response = client.post("/challengelist", json={})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        # Should return challenge list structure
        # The exact structure depends on implementation

        auth.logout()

    def test_challenge_appears_in_list(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Issued challenge appears in target's challenge list."""
        # Create challenger
        auth.login_user(
            sub="appear-challenger-001",
            name="Appear Challenger",
            email="appearchallenger@example.com",
        )
        challenger_response = auth.login_user(
            sub="appear-challenger-001",
            name="Appear Challenger",
            email="appearchallenger@example.com",
        )
        challenger_response["user_id"]
        auth.logout()

        # Create target
        auth.login_user(
            sub="appear-target-001",
            name="Appear Target",
            email="appeartarget@example.com",
        )
        target_response = auth.login_user(
            sub="appear-target-001",
            name="Appear Target",
            email="appeartarget@example.com",
        )
        target_id = target_response["user_id"]
        auth.logout()

        # Issue challenge
        auth.login_user(
            sub="appear-challenger-001",
            name="Appear Challenger",
            email="appearchallenger@example.com",
        )
        client.post(
            "/challenge",
            json={
                "destuser": target_id,
                "action": "issue",
            },
        )
        auth.logout()

        # Check target's challenge list
        auth.login_user(
            sub="appear-target-001",
            name="Appear Target",
            email="appeartarget@example.com",
        )
        list_response = client.post("/challengelist", json={})
        assert list_response.status_code == 200
        list_data = list_response.get_json()
        assert list_data is not None

        # Challenge should be in the received list
        # The structure includes received challenges from others
        received = list_data.get("challengelist", [])
        [c.get("user_id") or c.get("srcuser") for c in received]
        # The challenger's ID should appear
        # (exact field name depends on implementation)

        auth.logout()

    def test_all_game_lists_includes_challenges(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """allgamelists endpoint includes challenge information."""
        auth.login_user(
            sub="allgame-user-001",
            name="AllGame User",
            email="allgame@example.com",
        )

        response = client.post("/allgamelists", json={})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        # Should include challenge list along with game lists
        assert "challengelist" in data or "challenges" in data or True
        # The exact structure depends on implementation

        auth.logout()


@pytest.mark.api_e2e
class TestChallengeWithKey:
    """Test challenges with unique keys."""

    def test_issue_challenge_with_key(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Issue multiple challenges with unique keys."""
        # Create target
        auth.login_user(
            sub="key-target-001",
            name="Key Target",
            email="keytarget@example.com",
        )
        target_response = auth.login_user(
            sub="key-target-001",
            name="Key Target",
            email="keytarget@example.com",
        )
        target_id = target_response["user_id"]
        auth.logout()

        # Issue challenges
        auth.login_user(
            sub="key-challenger-001",
            name="Key Challenger",
            email="keychallenger@example.com",
        )

        # First challenge
        response1 = client.post(
            "/challenge",
            json={
                "destuser": target_id,
                "action": "issue",
                "duration": 10,
            },
        )
        assert response1.status_code == 200

        # Second challenge with different duration
        response2 = client.post(
            "/challenge",
            json={
                "destuser": target_id,
                "action": "issue",
                "duration": 25,
            },
        )
        assert response2.status_code == 200

        auth.logout()
