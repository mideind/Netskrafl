# PostgreSQL Migration: Test-First Strategy

## Philosophy

**The migration is not complete until tests prove behavioral equivalence.**

This document describes a test-driven approach where:
1. Tests define the expected behavior (contract)
2. The NDB backend is the reference implementation
3. The PostgreSQL backend must pass the same tests
4. Comparison testing catches any divergence

## Architecture: Backend-Agnostic Testing

### 1. Abstract Repository Protocol

Define Python protocols (structural typing) that describe the database operations.
Both backends implement these protocols, enabling polymorphic testing.

```python
# src/db/protocols.py
from __future__ import annotations
from typing import Protocol, Optional, List, Any, Iterator, TypeVar, Generic
from datetime import datetime

T = TypeVar('T', covariant=True)


class EntityProtocol(Protocol):
    """Protocol for database entities."""

    @property
    def id(self) -> str: ...


class UserProtocol(EntityProtocol, Protocol):
    """Protocol for User entities."""

    @property
    def nickname(self) -> str: ...

    @property
    def email(self) -> Optional[str]: ...

    @property
    def locale(self) -> str: ...

    @property
    def elo(self) -> int: ...

    @property
    def human_elo(self) -> int: ...

    @property
    def inactive(self) -> bool: ...

    # ... other properties


class GameProtocol(EntityProtocol, Protocol):
    """Protocol for Game entities."""

    @property
    def player0_id(self) -> Optional[str]: ...

    @property
    def player1_id(self) -> Optional[str]: ...

    @property
    def over(self) -> bool: ...

    @property
    def moves(self) -> List[dict]: ...

    # ... other properties


class QueryProtocol(Protocol, Generic[T]):
    """Protocol for query objects."""

    def filter(self, *conditions: Any) -> QueryProtocol[T]: ...

    def order(self, *columns: Any) -> QueryProtocol[T]: ...

    def fetch(self, limit: Optional[int] = None) -> List[T]: ...

    def get(self) -> Optional[T]: ...

    def count(self) -> int: ...


class UserRepositoryProtocol(Protocol):
    """Protocol for User repository operations."""

    def get_by_id(self, user_id: str) -> Optional[UserProtocol]: ...

    def get_by_account(self, account: str) -> Optional[UserProtocol]: ...

    def create(self, **kwargs: Any) -> UserProtocol: ...

    def update(self, user: UserProtocol, **kwargs: Any) -> UserProtocol: ...

    def delete(self, user_id: str) -> bool: ...

    def query(self) -> QueryProtocol[UserProtocol]: ...

    def find_by_locale(self, locale: str, limit: int = 100) -> List[UserProtocol]: ...

    def find_by_nickname_prefix(
        self, prefix: str, locale: Optional[str] = None, limit: int = 20
    ) -> List[UserProtocol]: ...


class GameRepositoryProtocol(Protocol):
    """Protocol for Game repository operations."""

    def get_by_id(self, game_id: str) -> Optional[GameProtocol]: ...

    def create(self, **kwargs: Any) -> GameProtocol: ...

    def update(self, game: GameProtocol, **kwargs: Any) -> GameProtocol: ...

    def delete(self, game_id: str) -> bool: ...

    def find_by_player(
        self, player_id: str, over: Optional[bool] = None, limit: int = 50
    ) -> List[GameProtocol]: ...

    def find_active_games(self, limit: int = 100) -> List[GameProtocol]: ...


class DatabaseBackendProtocol(Protocol):
    """Protocol for the complete database backend."""

    @property
    def users(self) -> UserRepositoryProtocol: ...

    @property
    def games(self) -> GameRepositoryProtocol: ...

    # ... other repositories

    def begin_transaction(self) -> Any: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...
```

### 2. Test Fixtures with Backend Injection

Use pytest fixtures to inject backends. Tests run twice: once per backend.

```python
# tests/conftest.py
from __future__ import annotations
import pytest
import os
from typing import Iterator, TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol


def pytest_addoption(parser):
    """Add command-line options for backend selection."""
    parser.addoption(
        "--backend",
        action="store",
        default="both",
        choices=["ndb", "postgresql", "both"],
        help="Database backend to test: ndb, postgresql, or both"
    )
    parser.addoption(
        "--compare",
        action="store_true",
        default=False,
        help="Run comparison tests (execute on both backends and compare results)"
    )


def get_backends(request) -> list[str]:
    """Get list of backends to test based on command-line option."""
    backend = request.config.getoption("--backend")
    if backend == "both":
        return ["ndb", "postgresql"]
    return [backend]


@pytest.fixture(params=["ndb", "postgresql"])
def backend(request) -> Iterator[DatabaseBackendProtocol]:
    """Fixture that provides each database backend.

    Tests using this fixture run twice: once with NDB, once with PostgreSQL.
    """
    backend_name = request.param

    # Skip if not requested
    backends_to_test = get_backends(request)
    if backend_name not in backends_to_test:
        pytest.skip(f"Skipping {backend_name} backend")

    # Create backend instance
    if backend_name == "ndb":
        from src.db.ndb import NDBBackend
        db = NDBBackend()
    else:
        from src.db.postgresql import PostgreSQLBackend
        # Use test database
        test_url = os.environ.get(
            "TEST_DATABASE_URL",
            "postgresql://test:test@localhost:5432/netskrafl_test"
        )
        db = PostgreSQLBackend(database_url=test_url)

    yield db

    # Cleanup
    db.close()


@pytest.fixture
def clean_backend(backend: DatabaseBackendProtocol) -> Iterator[DatabaseBackendProtocol]:
    """Fixture that provides a clean database state for each test."""
    # Begin transaction that will be rolled back
    backend.begin_transaction()

    yield backend

    # Rollback to restore clean state
    backend.rollback()


@pytest.fixture
def both_backends(request) -> Iterator[tuple[DatabaseBackendProtocol, DatabaseBackendProtocol]]:
    """Fixture for comparison tests - provides both backends simultaneously."""
    if not request.config.getoption("--compare"):
        pytest.skip("Comparison tests require --compare flag")

    from src.db.ndb import NDBBackend
    from src.db.postgresql import PostgreSQLBackend

    ndb = NDBBackend()
    test_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql://test:test@localhost:5432/netskrafl_test"
    )
    pg = PostgreSQLBackend(database_url=test_url)

    yield (ndb, pg)

    ndb.close()
    pg.close()
```

### 3. Backend-Agnostic Test Cases

Write tests that work with any backend implementing the protocol.

```python
# tests/db/test_user_repository.py
from __future__ import annotations
import pytest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol


class TestUserCRUD:
    """Test basic User CRUD operations on any backend."""

    def test_create_and_retrieve_user(self, clean_backend: DatabaseBackendProtocol):
        """Creating a user and retrieving it returns the same data."""
        db = clean_backend

        # Create
        user = db.users.create(
            id="test-user-001",
            nickname="TestNick",
            email="test@example.com",
            locale="is_IS",
            inactive=False,
        )

        # Retrieve
        loaded = db.users.get_by_id("test-user-001")

        assert loaded is not None
        assert loaded.id == "test-user-001"
        assert loaded.nickname == "TestNick"
        assert loaded.email == "test@example.com"
        assert loaded.locale == "is_IS"
        assert loaded.inactive is False

    def test_update_user(self, clean_backend: DatabaseBackendProtocol):
        """Updating a user persists the changes."""
        db = clean_backend

        # Create
        user = db.users.create(
            id="test-user-002",
            nickname="Original",
            locale="is_IS",
            inactive=False,
        )

        # Update
        db.users.update(user, nickname="Updated", elo=1500)

        # Retrieve and verify
        loaded = db.users.get_by_id("test-user-002")
        assert loaded is not None
        assert loaded.nickname == "Updated"
        assert loaded.elo == 1500

    def test_delete_user(self, clean_backend: DatabaseBackendProtocol):
        """Deleting a user removes it from the database."""
        db = clean_backend

        # Create
        db.users.create(
            id="test-user-003",
            nickname="ToDelete",
            locale="is_IS",
            inactive=False,
        )

        # Delete
        result = db.users.delete("test-user-003")
        assert result is True

        # Verify gone
        loaded = db.users.get_by_id("test-user-003")
        assert loaded is None

    def test_get_nonexistent_user_returns_none(self, clean_backend: DatabaseBackendProtocol):
        """Getting a non-existent user returns None, not an error."""
        db = clean_backend

        loaded = db.users.get_by_id("nonexistent-user-id")
        assert loaded is None


class TestUserQueries:
    """Test User query operations on any backend."""

    @pytest.fixture(autouse=True)
    def setup_test_users(self, clean_backend: DatabaseBackendProtocol):
        """Create test users for query tests."""
        db = clean_backend

        # Create users with different locales and Elo ratings
        test_users = [
            {"id": "user-is-1", "nickname": "Jón", "locale": "is_IS", "elo": 1200, "human_elo": 1200},
            {"id": "user-is-2", "nickname": "Sigga", "locale": "is_IS", "elo": 1500, "human_elo": 1500},
            {"id": "user-is-3", "nickname": "Jónatan", "locale": "is_IS", "elo": 1300, "human_elo": 1300},
            {"id": "user-en-1", "nickname": "John", "locale": "en_US", "elo": 1400, "human_elo": 1400},
            {"id": "user-en-2", "nickname": "Jane", "locale": "en_US", "elo": 1600, "human_elo": 1600},
        ]

        for user_data in test_users:
            db.users.create(inactive=False, **user_data)

    def test_find_by_locale(self, clean_backend: DatabaseBackendProtocol):
        """Finding users by locale returns only users in that locale."""
        db = clean_backend

        is_users = db.users.find_by_locale("is_IS")
        en_users = db.users.find_by_locale("en_US")

        assert len(is_users) == 3
        assert len(en_users) == 2
        assert all(u.locale == "is_IS" for u in is_users)
        assert all(u.locale == "en_US" for u in en_users)

    def test_find_by_nickname_prefix(self, clean_backend: DatabaseBackendProtocol):
        """Finding users by nickname prefix returns matching users."""
        db = clean_backend

        # Should match "Jón" and "Jónatan"
        matches = db.users.find_by_nickname_prefix("Jón", locale="is_IS")

        assert len(matches) == 2
        nicknames = {u.nickname for u in matches}
        assert nicknames == {"Jón", "Jónatan"}

    def test_query_with_ordering(self, clean_backend: DatabaseBackendProtocol):
        """Query results respect ordering."""
        db = clean_backend

        # Get Icelandic users ordered by Elo descending
        from src.db.protocols import UserProtocol

        users = (
            db.users.query()
            .filter(lambda u: u.locale == "is_IS")
            .order(lambda u: -u.elo)  # Descending
            .fetch(limit=10)
        )

        elos = [u.elo for u in users]
        assert elos == sorted(elos, reverse=True)

    def test_query_with_limit(self, clean_backend: DatabaseBackendProtocol):
        """Query respects limit parameter."""
        db = clean_backend

        users = db.users.find_by_locale("is_IS", limit=2)

        assert len(users) == 2


class TestUserQueryEquivalence:
    """Test that complex queries return equivalent results on both backends."""

    def test_leaderboard_query_equivalence(
        self,
        both_backends: tuple[DatabaseBackendProtocol, DatabaseBackendProtocol]
    ):
        """Leaderboard query returns same results on both backends."""
        ndb, pg = both_backends

        # Setup identical test data on both
        test_users = [
            {"id": "lb-user-1", "nickname": "Alice", "locale": "is_IS", "human_elo": 1800},
            {"id": "lb-user-2", "nickname": "Bob", "locale": "is_IS", "human_elo": 1600},
            {"id": "lb-user-3", "nickname": "Charlie", "locale": "is_IS", "human_elo": 1900},
        ]

        for user_data in test_users:
            ndb.users.create(inactive=False, **user_data)
            pg.users.create(inactive=False, **user_data)

        # Run leaderboard query on both
        ndb_results = (
            ndb.users.query()
            .filter(lambda u: u.locale == "is_IS")
            .filter(lambda u: not u.inactive)
            .order(lambda u: -u.human_elo)
            .fetch(limit=10)
        )

        pg_results = (
            pg.users.query()
            .filter(lambda u: u.locale == "is_IS")
            .filter(lambda u: not u.inactive)
            .order(lambda u: -u.human_elo)
            .fetch(limit=10)
        )

        # Compare
        assert len(ndb_results) == len(pg_results)
        for ndb_user, pg_user in zip(ndb_results, pg_results):
            assert ndb_user.id == pg_user.id
            assert ndb_user.nickname == pg_user.nickname
            assert ndb_user.human_elo == pg_user.human_elo
```

### 4. Comparison Test Harness

For critical operations, run both backends and compare results automatically.

```python
# tests/db/test_comparison.py
from __future__ import annotations
import pytest
from typing import Any, Callable, TypeVar
from dataclasses import dataclass

T = TypeVar('T')


@dataclass
class ComparisonResult:
    """Result of comparing operations across backends."""
    operation: str
    ndb_result: Any
    pg_result: Any
    match: bool
    difference: str | None = None


def compare_results(ndb_result: Any, pg_result: Any) -> tuple[bool, str | None]:
    """Compare results from two backends, handling common differences."""

    # Handle None
    if ndb_result is None and pg_result is None:
        return True, None
    if ndb_result is None or pg_result is None:
        return False, f"One is None: NDB={ndb_result}, PG={pg_result}"

    # Handle entities (compare by ID and key properties)
    if hasattr(ndb_result, 'id') and hasattr(pg_result, 'id'):
        if ndb_result.id != pg_result.id:
            return False, f"ID mismatch: {ndb_result.id} vs {pg_result.id}"
        # Compare other properties...
        return True, None

    # Handle lists
    if isinstance(ndb_result, list) and isinstance(pg_result, list):
        if len(ndb_result) != len(pg_result):
            return False, f"Length mismatch: {len(ndb_result)} vs {len(pg_result)}"
        for i, (n, p) in enumerate(zip(ndb_result, pg_result)):
            match, diff = compare_results(n, p)
            if not match:
                return False, f"Item {i}: {diff}"
        return True, None

    # Handle primitives
    if ndb_result == pg_result:
        return True, None
    return False, f"Value mismatch: {ndb_result} vs {pg_result}"


class DualBackendRunner:
    """Runs operations on both backends and compares results."""

    def __init__(self, ndb_backend, pg_backend):
        self.ndb = ndb_backend
        self.pg = pg_backend
        self.results: list[ComparisonResult] = []

    def run(
        self,
        operation_name: str,
        ndb_op: Callable[[], T],
        pg_op: Callable[[], T],
    ) -> T:
        """Run an operation on both backends and compare results."""
        ndb_result = ndb_op()
        pg_result = pg_op()

        match, difference = compare_results(ndb_result, pg_result)

        self.results.append(ComparisonResult(
            operation=operation_name,
            ndb_result=ndb_result,
            pg_result=pg_result,
            match=match,
            difference=difference,
        ))

        if not match:
            raise AssertionError(
                f"Backend mismatch in '{operation_name}': {difference}"
            )

        return ndb_result  # Return NDB result as reference

    def report(self) -> str:
        """Generate a report of all comparisons."""
        lines = ["Comparison Report", "=" * 50]

        passed = sum(1 for r in self.results if r.match)
        failed = len(self.results) - passed

        lines.append(f"Total: {len(self.results)}, Passed: {passed}, Failed: {failed}")
        lines.append("")

        for r in self.results:
            status = "✓" if r.match else "✗"
            lines.append(f"{status} {r.operation}")
            if not r.match:
                lines.append(f"  Difference: {r.difference}")

        return "\n".join(lines)


class TestGameOperationsComparison:
    """Compare game operations across both backends."""

    def test_game_lifecycle_comparison(
        self,
        both_backends: tuple[DatabaseBackendProtocol, DatabaseBackendProtocol]
    ):
        """Full game lifecycle produces identical results on both backends."""
        ndb, pg = both_backends
        runner = DualBackendRunner(ndb, pg)

        # Create users on both
        for db in [ndb, pg]:
            db.users.create(id="player-0", nickname="Player0", locale="is_IS", inactive=False)
            db.users.create(id="player-1", nickname="Player1", locale="is_IS", inactive=False)

        game_id = "test-game-001"

        # Create game
        runner.run(
            "create_game",
            lambda: ndb.games.create(
                id=game_id,
                player0_id="player-0",
                player1_id="player-1",
                locale="is_IS",
                rack0="AEIOU??",
                rack1="RSTLNE?",
            ),
            lambda: pg.games.create(
                id=game_id,
                player0_id="player-0",
                player1_id="player-1",
                locale="is_IS",
                rack0="AEIOU??",
                rack1="RSTLNE?",
            ),
        )

        # Retrieve game
        runner.run(
            "get_game",
            lambda: ndb.games.get_by_id(game_id),
            lambda: pg.games.get_by_id(game_id),
        )

        # Add a move
        move = {"coord": "H8", "tiles": "HELLO", "score": 24}
        runner.run(
            "add_move",
            lambda: ndb.games.add_move(game_id, move),
            lambda: pg.games.add_move(game_id, move),
        )

        # Verify move was added
        runner.run(
            "get_game_after_move",
            lambda: ndb.games.get_by_id(game_id),
            lambda: pg.games.get_by_id(game_id),
        )

        # Find games for player
        runner.run(
            "find_games_for_player",
            lambda: ndb.games.find_by_player("player-0"),
            lambda: pg.games.find_by_player("player-0"),
        )

        print(runner.report())
```

### 5. Property-Based Testing with Hypothesis

Use property-based testing to generate edge cases automatically.

```python
# tests/db/test_properties.py
from __future__ import annotations
import pytest
from hypothesis import given, strategies as st, settings, assume
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol


# Strategies for generating test data
user_id_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N', 'P')),
    min_size=1,
    max_size=64
).filter(lambda x: x.strip() == x)  # No leading/trailing whitespace

nickname_strategy = st.text(min_size=1, max_size=128).filter(
    lambda x: x.strip() == x and '\x00' not in x
)

locale_strategy = st.sampled_from(["is_IS", "en_US", "en_GB", "pl_PL", "nb_NO"])

elo_strategy = st.integers(min_value=0, max_value=3000)


class TestUserProperties:
    """Property-based tests for User operations."""

    @given(
        user_id=user_id_strategy,
        nickname=nickname_strategy,
        locale=locale_strategy,
        elo=elo_strategy,
    )
    @settings(max_examples=50)
    def test_create_retrieve_roundtrip(
        self,
        clean_backend: DatabaseBackendProtocol,
        user_id: str,
        nickname: str,
        locale: str,
        elo: int,
    ):
        """Property: Creating and retrieving a user preserves all data."""
        db = clean_backend

        # Skip if user_id already exists (hypothesis might generate duplicates)
        assume(db.users.get_by_id(user_id) is None)

        # Create
        db.users.create(
            id=user_id,
            nickname=nickname,
            locale=locale,
            elo=elo,
            inactive=False,
        )

        # Retrieve
        loaded = db.users.get_by_id(user_id)

        # Verify
        assert loaded is not None
        assert loaded.id == user_id
        assert loaded.nickname == nickname
        assert loaded.locale == locale
        assert loaded.elo == elo

    @given(
        original_nick=nickname_strategy,
        new_nick=nickname_strategy,
    )
    @settings(max_examples=30)
    def test_update_preserves_other_fields(
        self,
        clean_backend: DatabaseBackendProtocol,
        original_nick: str,
        new_nick: str,
    ):
        """Property: Updating one field doesn't affect others."""
        db = clean_backend
        user_id = "prop-test-user"

        # Ensure clean state
        db.users.delete(user_id)

        # Create with original nickname
        db.users.create(
            id=user_id,
            nickname=original_nick,
            locale="is_IS",
            elo=1500,
            human_elo=1400,
            inactive=False,
        )

        # Update nickname only
        user = db.users.get_by_id(user_id)
        db.users.update(user, nickname=new_nick)

        # Verify other fields unchanged
        loaded = db.users.get_by_id(user_id)
        assert loaded.nickname == new_nick  # Changed
        assert loaded.locale == "is_IS"     # Unchanged
        assert loaded.elo == 1500           # Unchanged
        assert loaded.human_elo == 1400     # Unchanged


class TestQueryProperties:
    """Property-based tests for query operations."""

    @given(
        limit=st.integers(min_value=1, max_value=100),
    )
    def test_limit_respected(
        self,
        clean_backend: DatabaseBackendProtocol,
        limit: int,
    ):
        """Property: Query limit is always respected."""
        db = clean_backend

        # Create more users than the limit
        for i in range(limit + 10):
            try:
                db.users.create(
                    id=f"limit-test-{i}",
                    nickname=f"User{i}",
                    locale="is_IS",
                    inactive=False,
                )
            except Exception:
                pass  # Ignore if already exists

        # Query with limit
        results = db.users.find_by_locale("is_IS", limit=limit)

        # Verify limit respected
        assert len(results) <= limit

    @given(
        elos=st.lists(st.integers(min_value=800, max_value=2500), min_size=5, max_size=20),
    )
    def test_ordering_consistent(
        self,
        clean_backend: DatabaseBackendProtocol,
        elos: list[int],
    ):
        """Property: Ordering is consistent and correct."""
        db = clean_backend

        # Create users with given Elos
        for i, elo in enumerate(elos):
            try:
                db.users.create(
                    id=f"order-test-{i}",
                    nickname=f"OrderUser{i}",
                    locale="is_IS",
                    elo=elo,
                    inactive=False,
                )
            except Exception:
                pass

        # Query with descending Elo order
        results = (
            db.users.query()
            .filter(lambda u: u.locale == "is_IS")
            .order(lambda u: -u.elo)
            .fetch()
        )

        # Verify ordering
        result_elos = [u.elo for u in results]
        assert result_elos == sorted(result_elos, reverse=True)
```

### 6. Deterministic Testing Infrastructure

Handle non-deterministic elements (timestamps, UUIDs) via dependency injection.

```python
# src/db/testing.py
from __future__ import annotations
from datetime import datetime, UTC
from typing import Callable, Iterator
from contextlib import contextmanager
import uuid

# Global overrides for testing
_time_override: Callable[[], datetime] | None = None
_uuid_override: Callable[[], uuid.UUID] | None = None


def get_current_time() -> datetime:
    """Get current time, using override if set."""
    if _time_override is not None:
        return _time_override()
    return datetime.now(UTC)


def generate_uuid() -> uuid.UUID:
    """Generate UUID, using override if set."""
    if _uuid_override is not None:
        return _uuid_override()
    try:
        return uuid.uuid7()
    except AttributeError:
        return uuid.uuid4()


@contextmanager
def freeze_time(frozen_time: datetime) -> Iterator[None]:
    """Context manager to freeze time for testing."""
    global _time_override
    _time_override = lambda: frozen_time
    try:
        yield
    finally:
        _time_override = None


@contextmanager
def deterministic_uuids(seed: int = 42) -> Iterator[None]:
    """Context manager for deterministic UUID generation."""
    global _uuid_override
    import random
    rng = random.Random(seed)

    def generate():
        # Generate deterministic but valid UUIDs
        return uuid.UUID(int=rng.getrandbits(128), version=4)

    _uuid_override = generate
    try:
        yield
    finally:
        _uuid_override = None


# Usage in tests:
#
# def test_with_frozen_time(clean_backend):
#     with freeze_time(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)):
#         user = db.users.create(...)
#         assert user.created_at == datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
#
# def test_with_deterministic_ids(clean_backend):
#     with deterministic_uuids(seed=123):
#         game1 = db.games.create(...)
#         game2 = db.games.create(...)
#         # UUIDs are reproducible with same seed
```

### 7. Migration Data Verification Tests

Tests that verify migrated data integrity.

```python
# tests/migration/test_data_integrity.py
from __future__ import annotations
import pytest
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol


class TestMigrationIntegrity:
    """Tests that verify data integrity after migration."""

    @pytest.fixture
    def sample_user_ids(self, ndb_backend: DatabaseBackendProtocol) -> list[str]:
        """Get a sample of user IDs from NDB for verification."""
        # Get all user IDs (or a large sample)
        all_users = ndb_backend.users.query().fetch(limit=10000)
        all_ids = [u.id for u in all_users]

        # Return random sample
        sample_size = min(100, len(all_ids))
        return random.sample(all_ids, sample_size)

    def test_user_count_matches(
        self,
        both_backends: tuple[DatabaseBackendProtocol, DatabaseBackendProtocol]
    ):
        """Total user count matches between backends."""
        ndb, pg = both_backends

        ndb_count = ndb.users.query().count()
        pg_count = pg.users.query().count()

        assert ndb_count == pg_count, f"User count mismatch: NDB={ndb_count}, PG={pg_count}"

    def test_user_data_matches(
        self,
        both_backends: tuple[DatabaseBackendProtocol, DatabaseBackendProtocol],
        sample_user_ids: list[str],
    ):
        """User data matches for sampled users."""
        ndb, pg = both_backends

        mismatches = []

        for user_id in sample_user_ids:
            ndb_user = ndb.users.get_by_id(user_id)
            pg_user = pg.users.get_by_id(user_id)

            if ndb_user is None and pg_user is None:
                continue

            if ndb_user is None or pg_user is None:
                mismatches.append(f"{user_id}: exists in only one backend")
                continue

            # Compare key fields
            fields_to_check = [
                'nickname', 'email', 'locale', 'elo', 'human_elo',
                'inactive', 'highest_score', 'best_word_score'
            ]

            for field in fields_to_check:
                ndb_val = getattr(ndb_user, field, None)
                pg_val = getattr(pg_user, field, None)
                if ndb_val != pg_val:
                    mismatches.append(
                        f"{user_id}.{field}: NDB={ndb_val}, PG={pg_val}"
                    )

        if mismatches:
            pytest.fail(f"Data mismatches found:\n" + "\n".join(mismatches[:20]))

    def test_game_moves_preserved(
        self,
        both_backends: tuple[DatabaseBackendProtocol, DatabaseBackendProtocol],
    ):
        """Game moves are preserved correctly during migration."""
        ndb, pg = both_backends

        # Get sample of games with moves
        ndb_games = ndb.games.query().filter(lambda g: g.over).fetch(limit=100)
        games_with_moves = [g for g in ndb_games if g.moves][:20]

        for ndb_game in games_with_moves:
            pg_game = pg.games.get_by_id(ndb_game.id)

            assert pg_game is not None, f"Game {ndb_game.id} not found in PostgreSQL"
            assert len(ndb_game.moves) == len(pg_game.moves), (
                f"Game {ndb_game.id}: move count mismatch"
            )

            for i, (ndb_move, pg_move) in enumerate(zip(ndb_game.moves, pg_game.moves)):
                assert ndb_move.get('coord') == pg_move.get('coord'), (
                    f"Game {ndb_game.id}, move {i}: coord mismatch"
                )
                assert ndb_move.get('tiles') == pg_move.get('tiles'), (
                    f"Game {ndb_game.id}, move {i}: tiles mismatch"
                )
                assert ndb_move.get('score') == pg_move.get('score'), (
                    f"Game {ndb_game.id}, move {i}: score mismatch"
                )

    def test_foreign_key_integrity(
        self,
        pg_backend: DatabaseBackendProtocol,
    ):
        """Foreign key relationships are valid in PostgreSQL."""
        pg = pg_backend

        # Check games reference valid users
        games = pg.games.query().fetch(limit=1000)

        for game in games:
            if game.player0_id:
                user = pg.users.get_by_id(game.player0_id)
                assert user is not None or game.player0_id.startswith("robot-"), (
                    f"Game {game.id}: player0 {game.player0_id} not found"
                )

            if game.player1_id:
                user = pg.users.get_by_id(game.player1_id)
                assert user is not None or game.player1_id.startswith("robot-"), (
                    f"Game {game.id}: player1 {game.player1_id} not found"
                )
```

## Test Execution Strategy

### Running Tests

```bash
# Run all tests against NDB only (current behavior)
pytest tests/db/ --backend=ndb

# Run all tests against PostgreSQL only (verify new implementation)
pytest tests/db/ --backend=postgresql

# Run all tests against both backends (verify equivalence)
pytest tests/db/ --backend=both

# Run comparison tests (execute on both and compare results)
pytest tests/db/ --compare

# Run migration verification tests
pytest tests/migration/ --compare

# Full validation suite
pytest tests/db/ tests/migration/ --backend=both --compare -v
```

### Continuous Integration Pipeline

```yaml
# .github/workflows/migration-tests.yml
name: Database Migration Tests

on:
  push:
    paths:
      - 'src/db/**'
      - 'tests/db/**'
      - 'tests/migration/**'

jobs:
  test-ndb:
    name: Test NDB Backend
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -r requirements.txt -r requirements-test.txt
      - name: Run NDB tests
        run: pytest tests/db/ --backend=ndb -v
        env:
          GOOGLE_APPLICATION_CREDENTIALS: ${{ secrets.GCP_CREDENTIALS }}

  test-postgresql:
    name: Test PostgreSQL Backend
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
          POSTGRES_DB: netskrafl_test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -r requirements.txt -r requirements-test.txt
      - name: Run PostgreSQL tests
        run: pytest tests/db/ --backend=postgresql -v
        env:
          TEST_DATABASE_URL: postgresql://test:test@localhost:5432/netskrafl_test

  test-comparison:
    name: Backend Comparison Tests
    needs: [test-ndb, test-postgresql]
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
          POSTGRES_DB: netskrafl_test
        ports:
          - 5432:5432
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -r requirements.txt -r requirements-test.txt
      - name: Run comparison tests
        run: pytest tests/db/ --compare -v
        env:
          GOOGLE_APPLICATION_CREDENTIALS: ${{ secrets.GCP_CREDENTIALS }}
          TEST_DATABASE_URL: postgresql://test:test@localhost:5432/netskrafl_test
```

## Implementation Phases with Testing

### Phase 1: Protocol Definition and NDB Wrapper

1. Define protocols in `src/db/protocols.py`
2. Create NDB wrapper that implements protocols
3. Write initial test suite against protocols
4. Verify all tests pass with NDB backend

**Gate**: All protocol tests pass with NDB.

### Phase 2: PostgreSQL Implementation

1. Create PostgreSQL models and connection handling
2. Create PostgreSQL implementation of protocols
3. Run same test suite against PostgreSQL
4. Fix any failures until all tests pass

**Gate**: All protocol tests pass with PostgreSQL.

### Phase 3: Comparison Testing

1. Enable comparison testing mode
2. Run comparison tests with identical data
3. Investigate and fix any behavioral differences
4. Add edge case tests for discovered issues

**Gate**: All comparison tests pass (both backends produce identical results).

### Phase 4: Migration Verification

1. Migrate production data to test PostgreSQL instance
2. Run migration integrity tests
3. Verify data completeness and correctness
4. Test production query patterns against migrated data

**Gate**: Migration verification tests pass with production data sample.

### Phase 5: Production Cutover

1. Final data migration
2. Run full comparison test suite
3. Switch `DATABASE_BACKEND=postgresql`
4. Monitor for behavioral differences
5. Keep NDB available for rollback

**Gate**: Production operates correctly on PostgreSQL for 2 weeks.

## Summary

This test-first approach provides:

1. **Confidence**: Same tests pass on both backends
2. **Regression detection**: Any behavioral change is caught immediately
3. **Documentation**: Tests document expected behavior
4. **Gradual migration**: Can switch backends with confidence
5. **Easy rollback**: If issues arise, switch back to NDB
6. **Property-based coverage**: Edge cases discovered automatically

The key insight is that the NDB-compatible wrapper API allows running identical tests against both backends, making behavioral equivalence verifiable at every step.
