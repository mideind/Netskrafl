"""
Pytest configuration and fixtures for API end-to-end tests.

This module provides fixtures for testing the Netskrafl API endpoints with a
Flask test client, deterministic mocking, authentication helpers, and database
verification.

These tests use PostgreSQL only.

Usage:
    # Run all API e2e tests
    pytest tests/api_e2e/ -v

    # Run specific test file
    pytest tests/api_e2e/test_game_vs_robot.py -v
"""

from __future__ import annotations

# IMPORTANT: Set environment variables BEFORE any app imports happen
# This must be done at module load time because main.py initializes
# the database session manager on import.
import os

# Import the test database URL constant early (src/db/config.py has no side effects)
from src.db.config import DEFAULT_TEST_DATABASE_URL

# Set database backend to PostgreSQL for API e2e tests
os.environ["DATABASE_BACKEND"] = "postgresql"
# Set default test database URL if not already set in environment
os.environ.setdefault("DATABASE_URL", DEFAULT_TEST_DATABASE_URL)

import random
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import (
    Any,
    Dict,
    Iterator,
    List,
    Mapping,
    Optional,
    Tuple,
    TYPE_CHECKING,
)

import pytest
from flask import Flask
from flask.testing import FlaskClient

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol

# UTC timezone constant
UTC = timezone.utc


# =============================================================================
# Pytest Configuration
# =============================================================================


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers for API tests."""
    config.addinivalue_line(
        "markers",
        "api_e2e: end-to-end API test",
    )


# =============================================================================
# Database Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def _reset_postgresql_tables() -> Iterator[None]:
    """Session-scoped fixture that resets PostgreSQL tables once per test session.

    This fixture drops and recreates all tables to ensure a clean state.
    """
    from src.db.config import get_config, DEFAULT_TEST_DATABASE_URL
    from src.db.postgresql import PostgreSQLBackend

    url = get_config().get_database_url(DEFAULT_TEST_DATABASE_URL)

    # Reset tables at session start
    db = PostgreSQLBackend(database_url=url)
    db.drop_tables()
    db.create_tables()
    db.close()

    yield


@pytest.fixture(scope="session")
def pg_backend(_reset_postgresql_tables: None) -> Iterator["DatabaseBackendProtocol"]:
    """Session-scoped PostgreSQL backend for database verification."""
    from src.db.config import get_config, DEFAULT_TEST_DATABASE_URL
    from src.db.postgresql import PostgreSQLBackend

    url = get_config().get_database_url(DEFAULT_TEST_DATABASE_URL)
    db = PostgreSQLBackend(database_url=url)
    yield db
    db.close()


# =============================================================================
# Flask App Fixture
# =============================================================================


@pytest.fixture(scope="session")
def app(_reset_postgresql_tables: None) -> Iterator[Flask]:
    """Create Flask test app with PostgreSQL backend.

    This fixture configures the Flask app for testing mode with:
    - TESTING=True (enables test authentication bypass)
    - PostgreSQL database backend
    - Session-scoped WSGI middleware

    Note: Environment variables (DATABASE_BACKEND, DATABASE_URL) are set at
    module load time above, before any imports that might trigger main.py.
    """
    # Import the Flask app - environment is already configured at module level
    from src.main import app as flask_app
    from src.db import db_wsgi_middleware

    # Configure for testing
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False

    # Wrap with database middleware if not already wrapped
    # (main.py may have already done this)
    if not hasattr(flask_app, "_test_middleware_applied"):
        flask_app.wsgi_app = db_wsgi_middleware(flask_app.wsgi_app)  # type: ignore
        flask_app._test_middleware_applied = True  # type: ignore

    yield flask_app


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """Flask test client with session support."""
    return app.test_client()


# =============================================================================
# Authentication Helper
# =============================================================================


@dataclass
class AuthHelper:
    """Helper for simulating user authentication in tests.

    This helper provides methods to simulate OAuth login, anonymous login,
    and logout operations. It works because Flask's TESTING=True triggers
    test mode in auth.py, which bypasses actual OAuth verification.
    """

    client: FlaskClient
    _current_user_id: Optional[str] = None

    def login_user(
        self,
        sub: str,
        name: str,
        email: str,
        *,
        client_type: str = "web",
    ) -> Dict[str, Any]:
        """Simulate OAuth login via POST to /oauth2callback with form data.

        In test mode (TESTING=True), auth.py accepts form data directly
        instead of validating a real OAuth token.

        Args:
            sub: Google account ID (becomes the user account identifier)
            name: User's display name
            email: User's email address
            client_type: Client type ('web', 'ios', 'android')

        Returns:
            JSON response dict with user data
        """
        response = self.client.post(
            "/oauth2callback",
            data={
                "sub": sub,
                "name": name,
                "email": email,
                "clientType": client_type,
            },
        )
        assert response.status_code == 200, f"Login failed: {response.data}"
        data = response.get_json()
        if data and data.get("user_id"):
            self._current_user_id = data["user_id"]
        return data or {}

    def login_anonymous(self, device_id: str) -> Dict[str, Any]:
        """Simulate anonymous login via /oauth_anon.

        Args:
            device_id: Device identifier for anonymous user

        Returns:
            JSON response dict with user data
        """
        # Get the AUTH_SECRET from config
        from config import AUTH_SECRET

        response = self.client.post(
            "/oauth_anon",
            json={"sub": device_id},  # The field is called "sub", not "id"
            headers={"Authorization": f"Bearer {AUTH_SECRET}"},
        )
        assert response.status_code == 200, f"Anonymous login failed: {response.data}"
        data = response.get_json()
        if data and data.get("user_id"):
            self._current_user_id = data["user_id"]
        return data or {}

    def logout(self) -> None:
        """Clear session via /logout."""
        self.client.post("/logout")
        self._current_user_id = None

    @property
    def current_user_id(self) -> Optional[str]:
        """Return the current logged-in user ID."""
        return self._current_user_id

    @contextmanager
    def as_user(
        self, sub: str, name: str, email: str
    ) -> Iterator[Dict[str, Any]]:
        """Context manager for temporary user session.

        Args:
            sub: Google account ID
            name: User's display name
            email: User's email address

        Yields:
            Login response data
        """
        data = self.login_user(sub, name, email)
        try:
            yield data
        finally:
            self.logout()


@pytest.fixture
def auth(client: FlaskClient) -> AuthHelper:
    """Helper for simulating user authentication."""
    return AuthHelper(client)


# =============================================================================
# Deterministic Game Context
# =============================================================================


@dataclass
class DeterministicGameContext:
    """Context for controlling all random elements in game creation/play.

    This class provides methods to patch various random sources to make
    game behavior deterministic and reproducible.
    """

    monkeypatch: pytest.MonkeyPatch
    _game_ids: List[str] = field(default_factory=list)
    _game_id_index: int = 0
    _tile_sequence: str = ""
    _tile_index: int = 0
    _player0_first: Optional[bool] = None
    _robot_choices: List[Any] = field(default_factory=list)
    _robot_choice_index: int = 0
    _patches_applied: bool = False

    def set_game_id(self, game_id: str) -> None:
        """Set a specific game ID to be returned by Unique.id().

        Args:
            game_id: The game ID to return
        """
        self._game_ids = [game_id]
        self._game_id_index = 0
        self._apply_game_id_patch()

    def set_game_ids(self, game_ids: List[str]) -> None:
        """Set multiple game IDs to be returned by Unique.id() in sequence.

        Args:
            game_ids: List of game IDs to return in order
        """
        self._game_ids = game_ids
        self._game_id_index = 0
        self._apply_game_id_patch()

    def _apply_game_id_patch(self) -> None:
        """Apply the game ID patch to Unique.id()."""

        def mock_unique_id() -> str:
            if self._game_id_index < len(self._game_ids):
                result = self._game_ids[self._game_id_index]
                self._game_id_index += 1
                return result
            # Fall back to UUID if we run out of predefined IDs
            import uuid
            return str(uuid.uuid1())

        # Patch both NDB and PG implementations
        self.monkeypatch.setattr("skrafldb.Unique.id", staticmethod(mock_unique_id))

    def set_tile_sequence(self, tiles: str) -> None:
        """Set the sequence of tiles to be drawn from the bag.

        The tiles string should contain all tiles in the order they will be drawn.
        For a standard game, this includes:
        - Player 0's initial rack (7 tiles)
        - Player 1's initial rack (7 tiles)
        - Subsequent draws after each move

        Args:
            tiles: String of tiles in draw order
        """
        self._tile_sequence = tiles
        self._tile_index = 0
        self._apply_tile_patch()

    def _apply_tile_patch(self) -> None:
        """Apply the tile draw patch to Bag.RNG."""

        class DeterministicRNG:
            """A fake RNG that returns predetermined indices."""

            def __init__(self, ctx: DeterministicGameContext):
                self._ctx = ctx

            def randint(self, a: int, b: int) -> int:
                """Return index 0 to always pick the first available tile.

                Since we're controlling the bag contents via the tile sequence,
                we need to ensure tiles are drawn in order. By always returning 0,
                we pick the first tile in the remaining bag.
                """
                return 0

        # Store context reference for the RNG class
        deterministic_rng = DeterministicRNG(self)
        self.monkeypatch.setattr(
            "src.skraflmechanics.Bag.RNG", deterministic_rng
        )

    def set_player_order(self, player0_first: bool) -> None:
        """Control which player goes first.

        Args:
            player0_first: If True, player 0 moves first; if False, player 1
        """
        self._player0_first = player0_first
        self._apply_player_order_patch()

    def _apply_player_order_patch(self) -> None:
        """Apply the player order patch to randint."""

        def mock_randint(a: int, b: int) -> int:
            if self._player0_first is not None:
                return 0 if self._player0_first else 1
            return random.randint(a, b)

        self.monkeypatch.setattr("src.skraflgame.randint", mock_randint)

    def set_robot_choices(self, choices: List[Any]) -> None:
        """Set predetermined choices for robot move selection.

        Args:
            choices: List of values to return from random.choice calls
        """
        self._robot_choices = choices
        self._robot_choice_index = 0
        self._apply_robot_patch()

    def set_robot_seed(self, seed: int) -> None:
        """Seed the robot's random number generator for reproducible moves.

        Args:
            seed: Random seed value
        """
        rng = random.Random(seed)
        self.monkeypatch.setattr("src.skraflplayer.random", rng)

    def _apply_robot_patch(self) -> None:
        """Apply the robot choice patch."""

        original_choice = random.choice

        def mock_choice(seq: Any) -> Any:
            if self._robot_choice_index < len(self._robot_choices):
                result = self._robot_choices[self._robot_choice_index]
                self._robot_choice_index += 1
                return result
            return original_choice(seq)

        self.monkeypatch.setattr("src.skraflplayer.random.choice", mock_choice)


@pytest.fixture
def deterministic_game(monkeypatch: pytest.MonkeyPatch) -> DeterministicGameContext:
    """Control all random elements in game creation/play."""
    return DeterministicGameContext(monkeypatch)


# =============================================================================
# Firebase Mock
# =============================================================================


@dataclass
class FirebaseMock:
    """Mock Firebase to capture notifications without external calls.

    This mock captures all Firebase send_message and push_to_user calls
    for verification in tests.
    """

    messages: List[Dict[str, Any]] = field(default_factory=list)
    push_notifications: List[Dict[str, Any]] = field(default_factory=list)
    _monkeypatch: pytest.MonkeyPatch = field(default=None)  # type: ignore

    def __post_init__(self) -> None:
        """Apply patches after initialization."""
        if self._monkeypatch:
            self._apply_patches()

    def _apply_patches(self) -> None:
        """Apply Firebase patches."""

        def mock_send_message(
            message: Optional[Mapping[str, Any]], *args: str
        ) -> bool:
            self.messages.append({
                "message": dict(message) if message else None,
                "args": args,
                "timestamp": datetime.now(UTC).isoformat(),
            })
            return True

        def mock_push_to_user(
            user_id: str, message: Any, data: Optional[Any]
        ) -> bool:
            self.push_notifications.append({
                "user_id": user_id,
                "message": message,
                "data": data,
                "timestamp": datetime.now(UTC).isoformat(),
            })
            return True

        self._monkeypatch.setattr("firebase.send_message", mock_send_message)
        self._monkeypatch.setattr("firebase.push_to_user", mock_push_to_user)

    def clear(self) -> None:
        """Clear all captured messages."""
        self.messages.clear()
        self.push_notifications.clear()

    def assert_message_sent(self, path_contains: str) -> Dict[str, Any]:
        """Assert a message was sent containing the given path.

        Args:
            path_contains: Substring to search for in message paths

        Returns:
            The matching message

        Raises:
            AssertionError: If no matching message found
        """
        for msg in self.messages:
            if msg["message"]:
                for key in msg["message"].keys():
                    if path_contains in key:
                        return msg
        raise AssertionError(
            f"No message found containing path '{path_contains}'. "
            f"Messages: {self.messages}"
        )

    def assert_move_notified(self, game_id: str, user_id: str) -> None:
        """Assert a move notification was sent for the given game and user.

        Args:
            game_id: Game UUID
            user_id: User ID to check for notification
        """
        for msg in self.messages:
            if msg["message"]:
                move_key = f"user/{user_id}/move"
                if move_key in msg["message"]:
                    move_data = msg["message"][move_key]
                    if move_data.get("game") == game_id:
                        return
        raise AssertionError(
            f"No move notification found for game {game_id}, user {user_id}. "
            f"Messages: {self.messages}"
        )

    def assert_challenge_notified(self, user_id: str) -> None:
        """Assert a challenge notification was sent to the user.

        Args:
            user_id: User ID to check for notification
        """
        for msg in self.messages:
            if msg["message"]:
                challenge_key = f"user/{user_id}/challenge"
                if challenge_key in msg["message"]:
                    return
        raise AssertionError(
            f"No challenge notification found for user {user_id}. "
            f"Messages: {self.messages}"
        )

    def assert_push_sent_to(self, user_id: str) -> Dict[str, Any]:
        """Assert a push notification was sent to the user.

        Args:
            user_id: User ID to check

        Returns:
            The matching push notification

        Raises:
            AssertionError: If no matching notification found
        """
        for notification in self.push_notifications:
            if notification["user_id"] == user_id:
                return notification
        raise AssertionError(
            f"No push notification found for user {user_id}. "
            f"Notifications: {self.push_notifications}"
        )


@pytest.fixture
def mock_firebase(monkeypatch: pytest.MonkeyPatch) -> FirebaseMock:
    """Mock Firebase to capture notifications without external calls."""
    mock = FirebaseMock(_monkeypatch=monkeypatch)
    return mock


# =============================================================================
# Database Verifier
# =============================================================================


class DatabaseVerifier:
    """Direct database access for state verification.

    This class provides methods to verify database state after API operations.
    It uses the PostgreSQL backend directly for queries.
    """

    def __init__(self, backend: "DatabaseBackendProtocol"):
        self._backend = backend

    def get_user(self, user_id: str) -> Any:
        """Get a user entity for custom assertions.

        Args:
            user_id: User ID

        Returns:
            User entity or None
        """
        return self._backend.users.get_by_id(user_id)

    def get_game(self, game_id: str) -> Any:
        """Get a game entity for custom assertions.

        Args:
            game_id: Game UUID

        Returns:
            Game entity or None
        """
        return self._backend.games.get_by_id(game_id)


@pytest.fixture
def db(pg_backend: "DatabaseBackendProtocol") -> DatabaseVerifier:
    """Direct database access for state verification."""
    return DatabaseVerifier(pg_backend)


# =============================================================================
# Convenience Fixtures
# =============================================================================


@pytest.fixture
def logged_in_user(
    client: FlaskClient, auth: AuthHelper
) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Create and login a test user.

    Yields:
        Tuple of (user_id, login_response)
    """
    response = auth.login_user(
        sub="test-user-001",
        name="Test User",
        email="test@example.com",
    )
    user_id = response.get("user_id", "")
    yield user_id, response
    auth.logout()


@pytest.fixture
def two_users(
    client: FlaskClient, auth: AuthHelper
) -> Iterator[Tuple[Tuple[str, str], Tuple[str, str]]]:
    """Create and login two test users.

    Yields:
        Tuple of ((alice_id, alice_sub), (bob_id, bob_sub))
    """
    # Create Alice
    alice_response = auth.login_user(
        sub="alice-sub-001",
        name="Alice",
        email="alice@example.com",
    )
    alice_id = alice_response.get("user_id", "")
    auth.logout()

    # Create Bob
    bob_response = auth.login_user(
        sub="bob-sub-001",
        name="Bob",
        email="bob@example.com",
    )
    bob_id = bob_response.get("user_id", "")
    auth.logout()

    yield (alice_id, "alice-sub-001"), (bob_id, "bob-sub-001")
