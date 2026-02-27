"""
Testing utilities for database backends.

This module provides infrastructure for deterministic testing, including
frozen time, deterministic UUID generation, and comparison utilities.
"""

from __future__ import annotations

from typing import (
    Any,
    Callable,
    Iterator,
    Optional,
    TypeVar,
    List,
    Tuple,
    Protocol,
)
from datetime import datetime, timezone
from contextlib import contextmanager
from dataclasses import dataclass, field
import uuid
import random

# UTC timezone constant
UTC = timezone.utc

T = TypeVar("T")


# =============================================================================
# Time and UUID Override Infrastructure
# =============================================================================

# Global overrides for testing
_time_override: Optional[Callable[[], datetime]] = None
_uuid_override: Optional[Callable[[], str]] = None


def get_current_time() -> datetime:
    """Get current time, using override if set.

    Always returns a timezone-aware datetime in UTC.
    """
    if _time_override is not None:
        return _time_override()
    return datetime.now(UTC)


def generate_id() -> str:
    """Generate a unique ID, using override if set.

    Returns a UUID string suitable for entity IDs.
    """
    if _uuid_override is not None:
        return _uuid_override()
    # Use UUID v1 for compatibility with existing NDB IDs
    return str(uuid.uuid1())


@contextmanager
def freeze_time(frozen_time: datetime) -> Iterator[None]:
    """Context manager to freeze time for testing.

    Args:
        frozen_time: The datetime to return for all get_current_time() calls.

    Example:
        with freeze_time(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)):
            user = db.users.create(...)
            assert user.timestamp == datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
    """
    global _time_override
    old_override = _time_override

    def _frozen() -> datetime:
        return frozen_time

    _time_override = _frozen
    try:
        yield
    finally:
        _time_override = old_override


@contextmanager
def advancing_time(
    start_time: datetime, increment_seconds: float = 1.0
) -> Iterator[Callable[[], datetime]]:
    """Context manager for time that advances with each call.

    Args:
        start_time: The starting datetime.
        increment_seconds: How many seconds to advance per call.

    Yields:
        A function that returns the current (advancing) time.

    Example:
        with advancing_time(datetime(2024, 1, 1, tzinfo=UTC), 60.0) as get_time:
            time1 = get_time()  # 2024-01-01 00:00:00
            time2 = get_time()  # 2024-01-01 00:01:00
    """
    global _time_override
    old_override = _time_override

    from datetime import timedelta

    current = [start_time]

    def advance() -> datetime:
        result = current[0]
        current[0] = current[0] + timedelta(seconds=increment_seconds)
        return result

    _time_override = advance
    try:
        yield advance
    finally:
        _time_override = old_override


@contextmanager
def deterministic_ids(seed: int = 42) -> Iterator[None]:
    """Context manager for deterministic ID generation.

    Args:
        seed: Random seed for reproducible IDs.

    Example:
        with deterministic_ids(seed=123):
            id1 = generate_id()  # Always same with seed=123
            id2 = generate_id()
    """
    global _uuid_override
    old_override = _uuid_override
    rng = random.Random(seed)
    counter = [0]

    def generate() -> str:
        # Generate deterministic but valid UUID-like strings
        counter[0] += 1
        bits = rng.getrandbits(128)
        return str(uuid.UUID(int=bits, version=4))

    _uuid_override = generate
    try:
        yield
    finally:
        _uuid_override = old_override


@contextmanager
def sequential_ids(prefix: str = "test") -> Iterator[None]:
    """Context manager for sequential ID generation.

    Useful for tests where you want predictable, readable IDs.

    Args:
        prefix: Prefix for generated IDs.

    Example:
        with sequential_ids("user"):
            id1 = generate_id()  # "user-0001"
            id2 = generate_id()  # "user-0002"
    """
    global _uuid_override
    old_override = _uuid_override
    counter = [0]

    def generate() -> str:
        counter[0] += 1
        return f"{prefix}-{counter[0]:04d}"

    _uuid_override = generate
    try:
        yield
    finally:
        _uuid_override = old_override


# =============================================================================
# Comparison Utilities
# =============================================================================


@dataclass
class ComparisonResult:
    """Result of comparing operations across backends."""

    operation: str
    ndb_result: Any
    pg_result: Any
    match: bool
    difference: Optional[str] = None


@dataclass
class ComparisonReport:
    """Report of all comparisons performed."""

    results: List[ComparisonResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        """Number of comparisons that passed."""
        return sum(1 for r in self.results if r.match)

    @property
    def failed(self) -> int:
        """Number of comparisons that failed."""
        return len(self.results) - self.passed

    @property
    def all_passed(self) -> bool:
        """Whether all comparisons passed."""
        return self.failed == 0

    def add(self, result: ComparisonResult) -> None:
        """Add a comparison result."""
        self.results.append(result)

    def format(self) -> str:
        """Format the report as a string."""
        lines = [
            "Comparison Report",
            "=" * 50,
            f"Total: {len(self.results)}, Passed: {self.passed}, Failed: {self.failed}",
            "",
        ]

        for r in self.results:
            status = "PASS" if r.match else "FAIL"
            lines.append(f"[{status}] {r.operation}")
            if not r.match and r.difference:
                lines.append(f"       {r.difference}")

        return "\n".join(lines)


class EntityComparable(Protocol):
    """Protocol for entities that can be compared."""

    @property
    def key_id(self) -> str: ...


def compare_entities(
    entity1: Optional[EntityComparable],
    entity2: Optional[EntityComparable],
    fields: List[str],
) -> Tuple[bool, Optional[str]]:
    """Compare two entities field by field.

    Args:
        entity1: First entity (usually NDB).
        entity2: Second entity (usually PostgreSQL).
        fields: List of field names to compare.

    Returns:
        Tuple of (match, difference_description).
    """
    # Handle None cases
    if entity1 is None and entity2 is None:
        return True, None
    if entity1 is None:
        return False, "First entity is None, second is not"
    if entity2 is None:
        return False, "Second entity is None, first is not"

    # Compare key_id
    if entity1.key_id != entity2.key_id:
        return False, f"ID mismatch: {entity1.key_id} vs {entity2.key_id}"

    # Compare specified fields
    for field_name in fields:
        val1 = getattr(entity1, field_name, None)
        val2 = getattr(entity2, field_name, None)
        if val1 != val2:
            return False, f"Field '{field_name}' mismatch: {val1!r} vs {val2!r}"

    return True, None


def compare_lists(
    list1: List[Any],
    list2: List[Any],
    item_comparator: Optional[Callable[[Any, Any], Tuple[bool, Optional[str]]]] = None,
) -> Tuple[bool, Optional[str]]:
    """Compare two lists element by element.

    Args:
        list1: First list.
        list2: Second list.
        item_comparator: Optional function to compare items. If None, uses ==.

    Returns:
        Tuple of (match, difference_description).
    """
    if len(list1) != len(list2):
        return False, f"Length mismatch: {len(list1)} vs {len(list2)}"

    for i, (item1, item2) in enumerate(zip(list1, list2)):
        if item_comparator:
            match, diff = item_comparator(item1, item2)
            if not match:
                return False, f"Item {i}: {diff}"
        elif item1 != item2:
            return False, f"Item {i} mismatch: {item1!r} vs {item2!r}"

    return True, None


class DualBackendRunner:
    """Runs operations on both backends and compares results.

    This is the core utility for comparison testing. It executes the same
    operation on both backends and verifies the results match.

    Example:
        runner = DualBackendRunner(ndb_backend, pg_backend)

        runner.run(
            "create_user",
            lambda: ndb.users.create(id="test", ...),
            lambda: pg.users.create(id="test", ...),
        )

        runner.run(
            "get_user",
            lambda: ndb.users.get_by_id("test"),
            lambda: pg.users.get_by_id("test"),
            comparator=lambda a, b: compare_entities(a, b, ["nickname", "email"])
        )

        if not runner.report.all_passed:
            print(runner.report.format())
    """

    def __init__(self, ndb_backend: Any, pg_backend: Any):
        """Initialize with both backends.

        Args:
            ndb_backend: The NDB backend instance.
            pg_backend: The PostgreSQL backend instance.
        """
        self.ndb = ndb_backend
        self.pg = pg_backend
        self.report = ComparisonReport()

    def run(
        self,
        operation_name: str,
        ndb_op: Callable[[], T],
        pg_op: Callable[[], T],
        comparator: Optional[Callable[[T, T], Tuple[bool, Optional[str]]]] = None,
    ) -> T:
        """Run an operation on both backends and compare results.

        Args:
            operation_name: Name for logging/reporting.
            ndb_op: Function to call on NDB backend.
            pg_op: Function to call on PostgreSQL backend.
            comparator: Optional custom comparison function.

        Returns:
            The NDB result (used as reference).

        Raises:
            AssertionError: If results don't match.
        """
        ndb_result = ndb_op()
        pg_result = pg_op()

        if comparator:
            match, difference = comparator(ndb_result, pg_result)
        else:
            match = ndb_result == pg_result
            difference = (
                None if match else f"Values differ: {ndb_result!r} vs {pg_result!r}"
            )

        result = ComparisonResult(
            operation=operation_name,
            ndb_result=ndb_result,
            pg_result=pg_result,
            match=match,
            difference=difference,
        )
        self.report.add(result)

        if not match:
            raise AssertionError(
                f"Backend mismatch in '{operation_name}': {difference}"
            )

        return ndb_result

    def run_both(
        self,
        operation_name: str,
        operation: Callable[[Any], T],
        comparator: Optional[Callable[[T, T], Tuple[bool, Optional[str]]]] = None,
    ) -> T:
        """Run the same operation on both backends.

        This is a convenience method when the operation signature is identical
        for both backends.

        Args:
            operation_name: Name for logging/reporting.
            operation: Function that takes a backend and returns a result.
            comparator: Optional custom comparison function.

        Returns:
            The NDB result (used as reference).
        """
        return self.run(
            operation_name,
            lambda: operation(self.ndb),
            lambda: operation(self.pg),
            comparator,
        )
