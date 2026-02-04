"""
Tests for Chat repository operations.

These tests run against any backend implementing the DatabaseBackendProtocol.
Use --backend option to select which backend(s) to test.

The chat system uses "read markers" - empty messages sent by a user to indicate
they have read the conversation up to that point. The check_conversation method
uses these markers to determine if there are unread messages.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import time

import pytest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol

UTC = timezone.utc


class TestChatMessages:
    """Test basic Chat message operations."""

    @pytest.fixture(autouse=True)
    def setup_chat_users(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test users for Chat tests."""
        test_users = [
            ("chat-user-1", "test:chat1", "ChatUser1"),
            ("chat-user-2", "test:chat2", "ChatUser2"),
            ("chat-user-3", "test:chat3", "ChatUser3"),
        ]
        for user_id, account, nickname in test_users:
            existing = backend.users.get_by_id(user_id)
            if existing is None:
                backend.users.create(
                    user_id=user_id,
                    account=account,
                    email=None,
                    nickname=nickname,
                    locale="is_IS",
                )

    def test_add_msg_in_game(self, backend: "DatabaseBackendProtocol") -> None:
        """Can add a message in a game channel."""
        game_uuid = "test-game-chat-001"
        ts = backend.chat.add_msg_in_game(
            game_uuid=game_uuid,
            from_user="chat-user-1",
            to_user="chat-user-2",
            msg="Hello in game!",
        )

        assert ts is not None
        assert isinstance(ts, datetime)

    def test_add_msg_between_users(self, backend: "DatabaseBackendProtocol") -> None:
        """Can add a direct message between users."""
        ts = backend.chat.add_msg_between_users(
            from_user="chat-user-1",
            to_user="chat-user-2",
            msg="Hello directly!",
        )

        assert ts is not None
        assert isinstance(ts, datetime)

    def test_add_msg_to_channel(self, backend: "DatabaseBackendProtocol") -> None:
        """Can add a message to a channel."""
        ts = backend.chat.add_msg(
            channel="test-channel-001",
            from_user="chat-user-1",
            to_user="chat-user-3",
            msg="Hello channel!",
        )

        assert ts is not None
        assert isinstance(ts, datetime)


class TestChatReadMarkers:
    """Test Chat read marker functionality.

    Read markers are empty messages that indicate a user has read the
    conversation up to that point. The check_conversation method uses
    these to determine if there are unread messages.
    """

    @pytest.fixture(autouse=True)
    def setup_read_marker_users(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test users for read marker tests."""
        test_users = [
            ("rm-alice", "test:rmalice", "Alice"),
            ("rm-bob", "test:rmbob", "Bob"),
            ("rm-carol", "test:rmcarol", "Carol"),
        ]
        for user_id, account, nickname in test_users:
            existing = backend.users.get_by_id(user_id)
            if existing is None:
                backend.users.create(
                    user_id=user_id,
                    account=account,
                    email=None,
                    nickname=nickname,
                    locale="is_IS",
                )

    def test_check_conversation_no_messages(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Empty conversation has no unread messages."""
        result = backend.chat.check_conversation(
            "empty-channel-xyz", "rm-alice"
        )
        assert result is False

    def test_check_conversation_unread_from_other(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Conversation with message from other user shows as unread."""
        channel = "unread-test-channel"

        # Bob sends a message to Alice
        backend.chat.add_msg(
            channel=channel,
            from_user="rm-bob",
            to_user="rm-alice",
            msg="Hello Alice!",
        )

        # Alice checks - should see unread message
        result = backend.chat.check_conversation(channel, "rm-alice")
        assert result is True

        # Bob checks - should NOT see unread (he sent the message)
        result = backend.chat.check_conversation(channel, "rm-bob")
        assert result is False

    def test_check_conversation_with_read_marker(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Read marker indicates messages have been read."""
        channel = "read-marker-test-channel"
        base_time = datetime.now(UTC)

        # Bob sends a message to Alice (oldest)
        backend.chat.add_msg(
            channel=channel,
            from_user="rm-bob",
            to_user="rm-alice",
            msg="Hello Alice!",
            timestamp=base_time,
        )

        # Small delay to ensure ordering
        time.sleep(0.01)

        # Alice sends a read marker (empty message) - indicates she read Bob's message
        backend.chat.add_msg(
            channel=channel,
            from_user="rm-alice",
            to_user="rm-bob",
            msg="",  # Empty message = read marker
            timestamp=base_time + timedelta(milliseconds=100),
        )

        # Alice checks - should NOT see unread (she marked as read)
        result = backend.chat.check_conversation(channel, "rm-alice")
        assert result is False

    def test_check_conversation_new_message_after_read_marker(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """New message after read marker shows as unread."""
        channel = "new-after-read-channel"
        base_time = datetime.now(UTC)

        # Bob sends first message
        backend.chat.add_msg(
            channel=channel,
            from_user="rm-bob",
            to_user="rm-alice",
            msg="First message",
            timestamp=base_time,
        )

        # Alice reads it (sends read marker)
        backend.chat.add_msg(
            channel=channel,
            from_user="rm-alice",
            to_user="rm-bob",
            msg="",  # Read marker
            timestamp=base_time + timedelta(milliseconds=100),
        )

        # Bob sends another message after the read marker
        backend.chat.add_msg(
            channel=channel,
            from_user="rm-bob",
            to_user="rm-alice",
            msg="Second message",
            timestamp=base_time + timedelta(milliseconds=200),
        )

        # Alice checks - should see unread (new message after her read marker)
        result = backend.chat.check_conversation(channel, "rm-alice")
        assert result is True

    def test_check_conversation_interleaved_messages(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Complex conversation with interleaved messages and read markers."""
        channel = "interleaved-channel"
        base_time = datetime.now(UTC)

        # Simulate a conversation:
        # 1. Bob: "Hi Alice" (t=0)
        # 2. Alice: "Hi Bob" (t=100)
        # 3. Bob: read marker (t=150) - Bob has read Alice's message
        # 4. Bob: "How are you?" (t=200)
        # 5. Alice: read marker (t=300) - Alice has read up to here
        # 6. Bob: "Are you there?" (t=400)

        backend.chat.add_msg(
            channel=channel,
            from_user="rm-bob",
            to_user="rm-alice",
            msg="Hi Alice",
            timestamp=base_time,
        )
        backend.chat.add_msg(
            channel=channel,
            from_user="rm-alice",
            to_user="rm-bob",
            msg="Hi Bob",
            timestamp=base_time + timedelta(milliseconds=100),
        )
        backend.chat.add_msg(
            channel=channel,
            from_user="rm-bob",
            to_user="rm-alice",
            msg="",  # Bob's read marker - he read Alice's "Hi Bob"
            timestamp=base_time + timedelta(milliseconds=150),
        )
        backend.chat.add_msg(
            channel=channel,
            from_user="rm-bob",
            to_user="rm-alice",
            msg="How are you?",
            timestamp=base_time + timedelta(milliseconds=200),
        )
        backend.chat.add_msg(
            channel=channel,
            from_user="rm-alice",
            to_user="rm-bob",
            msg="",  # Alice's read marker
            timestamp=base_time + timedelta(milliseconds=300),
        )
        backend.chat.add_msg(
            channel=channel,
            from_user="rm-bob",
            to_user="rm-alice",
            msg="Are you there?",
            timestamp=base_time + timedelta(milliseconds=400),
        )

        # Alice checks - should see unread (Bob's message at t=400 is after her read marker at t=300)
        result = backend.chat.check_conversation(channel, "rm-alice")
        assert result is True

        # Bob checks - should NOT see unread because:
        # - Scanning from newest: t=400 (his msg), t=300 (Alice's read marker - not his),
        #   t=200 (his msg), t=150 (his read marker) → returns False
        # His read marker at t=150 is encountered before Alice's "Hi Bob" at t=100
        result = backend.chat.check_conversation(channel, "rm-bob")
        assert result is False

    def test_check_conversation_all_read(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Conversation where all messages have been read."""
        channel = "all-read-channel"
        base_time = datetime.now(UTC)

        # Bob sends message
        backend.chat.add_msg(
            channel=channel,
            from_user="rm-bob",
            to_user="rm-alice",
            msg="Hello!",
            timestamp=base_time,
        )

        # Alice replies
        backend.chat.add_msg(
            channel=channel,
            from_user="rm-alice",
            to_user="rm-bob",
            msg="Hi there!",
            timestamp=base_time + timedelta(milliseconds=100),
        )

        # Bob sends read marker (he read Alice's reply)
        backend.chat.add_msg(
            channel=channel,
            from_user="rm-bob",
            to_user="rm-alice",
            msg="",  # Read marker
            timestamp=base_time + timedelta(milliseconds=200),
        )

        # Alice sends read marker (she read... well, nothing new, but marking anyway)
        backend.chat.add_msg(
            channel=channel,
            from_user="rm-alice",
            to_user="rm-bob",
            msg="",  # Read marker
            timestamp=base_time + timedelta(milliseconds=300),
        )

        # Both should see no unread messages
        assert backend.chat.check_conversation(channel, "rm-alice") is False
        assert backend.chat.check_conversation(channel, "rm-bob") is False


class TestChatListConversation:
    """Test listing conversation messages with read markers."""

    @pytest.fixture(autouse=True)
    def setup_list_users(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test users for list conversation tests."""
        test_users = [
            ("list-user-1", "test:listuser1", "ListUser1"),
            ("list-user-2", "test:listuser2", "ListUser2"),
        ]
        for user_id, account, nickname in test_users:
            existing = backend.users.get_by_id(user_id)
            if existing is None:
                backend.users.create(
                    user_id=user_id,
                    account=account,
                    email=None,
                    nickname=nickname,
                    locale="is_IS",
                )

    def test_list_conversation_includes_read_markers(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Read markers (empty messages) are included in conversation listing."""
        channel = "list-with-markers-channel"
        base_time = datetime.now(UTC)

        # Add a real message
        backend.chat.add_msg(
            channel=channel,
            from_user="list-user-1",
            to_user="list-user-2",
            msg="Hello!",
            timestamp=base_time,
        )

        # Add a read marker
        backend.chat.add_msg(
            channel=channel,
            from_user="list-user-2",
            to_user="list-user-1",
            msg="",  # Read marker
            timestamp=base_time + timedelta(milliseconds=100),
        )

        messages = list(backend.chat.list_conversation(channel))

        # Should have both messages (including read marker)
        assert len(messages) >= 2

        # Check that we have both types
        non_empty = [m for m in messages if m.msg]
        empty = [m for m in messages if not m.msg]

        assert len(non_empty) >= 1
        assert len(empty) >= 1

    def test_list_conversation_max_len_excludes_read_markers(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """max_len counts only real messages, not read markers."""
        channel = "maxlen-test-channel"
        base_time = datetime.now(UTC)

        # Add 3 real messages interspersed with read markers
        for i in range(3):
            # Real message
            backend.chat.add_msg(
                channel=channel,
                from_user="list-user-1",
                to_user="list-user-2",
                msg=f"Message {i+1}",
                timestamp=base_time + timedelta(milliseconds=i * 100),
            )
            # Read marker after each message
            backend.chat.add_msg(
                channel=channel,
                from_user="list-user-2",
                to_user="list-user-1",
                msg="",  # Read marker
                timestamp=base_time + timedelta(milliseconds=i * 100 + 50),
            )

        # Request max_len=2 - should get 2 real messages but also read markers
        messages = list(backend.chat.list_conversation(channel, max_len=2))

        # Count real messages
        real_messages = [m for m in messages if m.msg]

        # Should have exactly 2 real messages (max_len limit)
        assert len(real_messages) == 2


class TestChatHistory:
    """Test Chat history operations."""

    @pytest.fixture(autouse=True)
    def setup_history(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test users and messages for history tests."""
        test_users = [
            ("chat-hist-user", "test:chathist", "ChatHistUser"),
            ("chat-hist-other", "test:chathistother", "ChatHistOther"),
        ]
        for user_id, account, nickname in test_users:
            existing = backend.users.get_by_id(user_id)
            if existing is None:
                backend.users.create(
                    user_id=user_id,
                    account=account,
                    email=None,
                    nickname=nickname,
                    locale="is_IS",
                )

        # Add a message between users
        backend.chat.add_msg_between_users(
            from_user="chat-hist-other",
            to_user="chat-hist-user",
            msg="Hello from other!",
        )

    def test_chat_history(self, backend: "DatabaseBackendProtocol") -> None:
        """Can get chat history for a user."""
        history = backend.chat.chat_history("chat-hist-user")

        # Should have at least one conversation
        assert len(history) >= 1

        # Each entry should have expected fields
        for entry in history:
            assert entry.user is not None
            assert entry.ts is not None
            assert entry.last_msg is not None
