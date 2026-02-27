"""
Tests for Robot repository operations.

These tests run against any backend implementing the DatabaseBackendProtocol.
Use --backend option to select which backend(s) to test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol


class TestRobotElo:
    """Test Robot Elo operations."""

    def test_get_elo_returns_none_for_nonexistent(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """get_elo returns None when no Elo exists for level."""
        elo = backend.robots.get_elo("xx_XX", 999)
        assert elo is None

    def test_upsert_creates_elo(self, backend: "DatabaseBackendProtocol") -> None:
        """Can create Elo for a robot level."""
        result = backend.robots.upsert_elo("is_IS", 1, 1200)

        assert result is True

        # Verify it was created
        elo = backend.robots.get_elo("is_IS", 1)
        assert elo == 1200

    def test_upsert_updates_elo(self, backend: "DatabaseBackendProtocol") -> None:
        """Can update Elo for a robot level."""
        # Create initial
        backend.robots.upsert_elo("en_US", 2, 1100)

        # Update
        backend.robots.upsert_elo("en_US", 2, 1250)

        # Verify updated
        elo = backend.robots.get_elo("en_US", 2)
        assert elo == 1250

    def test_elo_is_locale_and_level_specific(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Elo is specific to locale and level combination."""
        backend.robots.upsert_elo("is_IS", 3, 1300)
        backend.robots.upsert_elo("is_IS", 4, 1400)
        backend.robots.upsert_elo("en_US", 3, 1350)

        assert backend.robots.get_elo("is_IS", 3) == 1300
        assert backend.robots.get_elo("is_IS", 4) == 1400
        assert backend.robots.get_elo("en_US", 3) == 1350
