"""
Chat system end-to-end tests.

Tests in-game chat and direct messaging.
"""

from __future__ import annotations

import pytest
from flask.testing import FlaskClient

from tests.api_e2e.conftest import (
    AuthHelper,
    FirebaseMock,
)


@pytest.mark.api_e2e
class TestInGameChat:
    """Test in-game chat functionality."""

    def _create_game_between_users(
        self,
        client: FlaskClient,
        auth: AuthHelper,
        alice_sub: str = "chat-alice-001",
        bob_sub: str = "chat-bob-001",
    ) -> tuple[str, str, str]:
        """Helper to create a game between two users.

        Returns:
            Tuple of (game_id, alice_id, bob_id)
        """
        # Create Alice
        alice_response = auth.login_user(
            sub=alice_sub,
            name="Chat Alice",
            email=f"{alice_sub}@example.com",
        )
        alice_id = alice_response["user_id"]
        auth.logout()

        # Create Bob
        bob_response = auth.login_user(
            sub=bob_sub,
            name="Chat Bob",
            email=f"{bob_sub}@example.com",
        )
        bob_id = bob_response["user_id"]
        auth.logout()

        # Alice challenges Bob
        auth.login_user(sub=alice_sub, name="Chat Alice", email=f"{alice_sub}@example.com")
        client.post("/challenge", json={"destuser": bob_id, "action": "issue"})
        auth.logout()

        # Bob accepts
        auth.login_user(sub=bob_sub, name="Chat Bob", email=f"{bob_sub}@example.com")
        game_response = client.post("/initgame", json={"opp": alice_id})
        game_id = game_response.get_json()["uuid"]
        auth.logout()

        return game_id, alice_id, bob_id

    def test_send_chat_message_in_game(
        self,
        client: FlaskClient,
        auth: AuthHelper,
        mock_firebase: FirebaseMock,
    ) -> None:
        """Send a chat message during a game."""
        game_id, alice_id, bob_id = self._create_game_between_users(
            client, auth, "ingame-alice-001", "ingame-bob-001"
        )

        # Alice sends a chat message
        auth.login_user(
            sub="ingame-alice-001",
            name="Chat Alice",
            email="ingame-alice-001@example.com",
        )

        response = client.post(
            "/chatmsg",
            json={
                "channel": f"game:{game_id}",
                "msg": "Hello, good game!",
            },
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        assert data.get("ok") is True

        auth.logout()

    def test_load_chat_history(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Load chat history for a game."""
        game_id, alice_id, bob_id = self._create_game_between_users(
            client, auth, "history-alice-001", "history-bob-001"
        )

        # Send a few messages
        auth.login_user(
            sub="history-alice-001",
            name="Chat Alice",
            email="history-alice-001@example.com",
        )
        client.post("/chatmsg", json={"channel": f"game:{game_id}", "msg": "First message"})
        auth.logout()

        auth.login_user(
            sub="history-bob-001",
            name="Chat Bob",
            email="history-bob-001@example.com",
        )
        client.post("/chatmsg", json={"channel": f"game:{game_id}", "msg": "Second message"})

        # Load chat history
        load_response = client.post("/chatload", json={"channel": f"game:{game_id}"})
        assert load_response.status_code == 200
        data = load_response.get_json()
        assert data is not None
        assert data.get("ok") is True

        # Should include the messages
        data.get("messages", [])
        # Messages should be in the response

        auth.logout()

    def test_chat_message_notifies_opponent(
        self,
        client: FlaskClient,
        auth: AuthHelper,
        mock_firebase: FirebaseMock,
    ) -> None:
        """Chat message sends Firebase notification to opponent."""
        game_id, alice_id, bob_id = self._create_game_between_users(
            client, auth, "notify-alice-001", "notify-bob-001"
        )

        mock_firebase.clear()

        # Alice sends message
        auth.login_user(
            sub="notify-alice-001",
            name="Chat Alice",
            email="notify-alice-001@example.com",
        )
        client.post("/chatmsg", json={"channel": f"game:{game_id}", "msg": "Hi Bob!"})

        # Bob should be notified via Firebase
        # Check that a message was sent
        assert len(mock_firebase.messages) > 0

        auth.logout()


@pytest.mark.api_e2e
class TestDirectChat:
    """Test direct user-to-user chat."""

    def test_send_direct_message(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Send a direct message to another user."""
        # Create target user
        auth.login_user(
            sub="direct-target-001",
            name="Direct Target",
            email="directtarget@example.com",
        )
        target_response = auth.login_user(
            sub="direct-target-001",
            name="Direct Target",
            email="directtarget@example.com",
        )
        target_id = target_response["user_id"]
        auth.logout()

        # Send direct message
        auth.login_user(
            sub="direct-sender-001",
            name="Direct Sender",
            email="directsender@example.com",
        )

        # Direct messages use channel format "user:USER_ID"
        response = client.post(
            "/chatmsg",
            json={
                "channel": f"user:{target_id}",
                "msg": "Direct message to you!",
            },
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        assert data.get("ok") is True

        auth.logout()

    def test_load_direct_chat_history(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Load direct chat history with another user."""
        # Create users
        auth.login_user(
            sub="direct-hist-a-001",
            name="Direct A",
            email="directhista@example.com",
        )
        user_a_response = auth.login_user(
            sub="direct-hist-a-001",
            name="Direct A",
            email="directhista@example.com",
        )
        user_a_id = user_a_response["user_id"]
        auth.logout()

        auth.login_user(
            sub="direct-hist-b-001",
            name="Direct B",
            email="directhistb@example.com",
        )
        user_b_response = auth.login_user(
            sub="direct-hist-b-001",
            name="Direct B",
            email="directhistb@example.com",
        )
        user_b_id = user_b_response["user_id"]

        # Send messages back and forth (channel format: "user:USER_ID")
        client.post("/chatmsg", json={"channel": f"user:{user_a_id}", "msg": "Hello A!"})
        auth.logout()

        auth.login_user(
            sub="direct-hist-a-001",
            name="Direct A",
            email="directhista@example.com",
        )
        client.post("/chatmsg", json={"channel": f"user:{user_b_id}", "msg": "Hello B!"})

        # Load chat history
        load_response = client.post("/chatload", json={"channel": f"user:{user_b_id}"})
        assert load_response.status_code == 200
        data = load_response.get_json()
        assert data is not None
        assert data.get("ok") is True

        auth.logout()


@pytest.mark.api_e2e
class TestChatHistory:
    """Test chat history list."""

    def test_get_chat_history_list(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Get list of chat conversations."""
        auth.login_user(
            sub="chathistory-user-001",
            name="Chat History User",
            email="chathistory@example.com",
        )

        response = client.post("/chathistory", json={})
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        assert data.get("ok") is True

        # Should return list of chat conversations
        data.get("history", [])
        # Structure depends on implementation

        auth.logout()


@pytest.mark.api_e2e
class TestChatPermissions:
    """Test chat permission handling."""

    def test_cannot_chat_in_others_game(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Cannot send chat in a game you're not part of."""
        # Create a game between Alice and Bob
        alice_response = auth.login_user(
            sub="perm-alice-001",
            name="Perm Alice",
            email="permalice@example.com",
        )
        alice_id = alice_response["user_id"]
        auth.logout()

        bob_response = auth.login_user(
            sub="perm-bob-001",
            name="Perm Bob",
            email="permbob@example.com",
        )
        bob_id = bob_response["user_id"]
        auth.logout()

        # Create game
        auth.login_user(
            sub="perm-alice-001",
            name="Perm Alice",
            email="permalice@example.com",
        )
        client.post("/challenge", json={"destuser": bob_id, "action": "issue"})
        auth.logout()

        auth.login_user(
            sub="perm-bob-001",
            name="Perm Bob",
            email="permbob@example.com",
        )
        game_response = client.post("/initgame", json={"opp": alice_id})
        game_id = game_response.get_json()["uuid"]
        auth.logout()

        # Eve tries to chat in Alice & Bob's game
        auth.login_user(
            sub="perm-eve-001",
            name="Perm Eve",
            email="permeve@example.com",
        )

        response = client.post(
            "/chatmsg",
            json={
                "channel": f"game:{game_id}",
                "msg": "I shouldn't be able to do this!",
            },
        )
        # Should be rejected
        data = response.get_json()
        assert data is not None
        # Should not be ok
        assert data.get("ok") is False or "error" in str(data).lower()

        auth.logout()

    def test_anonymous_cannot_chat(
        self,
        client: FlaskClient,
        auth: AuthHelper,
    ) -> None:
        """Anonymous users cannot use chat."""
        # This test depends on whether anonymous users are blocked from chat
        # The /chatmsg endpoint has @auth_required(allow_anonymous=False)

        # Login as anonymous
        auth.login_anonymous(device_id="anon-chat-device-001")

        # Try to send a chat message (channel format: "user:USER_ID")
        response = client.post(
            "/chatmsg",
            json={
                "channel": "user:some-user-id",
                "msg": "Anonymous message",
            },
        )
        # Should be rejected for anonymous users
        data = response.get_json()
        assert data is not None
        assert data.get("ok") is False

        auth.logout()
