"""
Tests for Config repository operations.

These tests run against any backend implementing the DatabaseBackendProtocol.
Use --backend option to select which backend(s) to test.

The Config repository stores JSON configuration documents keyed by id,
e.g. the app version / client configuration record reported to mobile
clients via /inituser.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol


TEST_ID = "test_config"


class TestConfigRepository:
    """Test Config repository operations."""

    def test_get_nonexistent(self, backend: "DatabaseBackendProtocol") -> None:
        """Getting a document that does not exist returns None."""
        backend.configs.delete(TEST_ID)
        assert backend.configs.get(TEST_ID) is None
        # Deleting a non-existent document is a no-op
        backend.configs.delete(TEST_ID)

    def test_set_get_replace_delete(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Can create, read, replace and delete a document."""
        doc = {
            "min_supported_version": "1.2.0",
            "latest_version": "1.5.0",
            "nested": {"a": [1, 2, 3], "b": None},
        }
        backend.configs.set(TEST_ID, doc)
        c = backend.configs.get(TEST_ID)
        assert c is not None
        assert c.key_id == TEST_ID
        assert c.doc == doc

        # Replacing the document drops keys that are no longer present
        backend.configs.set(TEST_ID, {"latest_version": "2.0.0"})
        c = backend.configs.get(TEST_ID)
        assert c is not None
        assert c.doc == {"latest_version": "2.0.0"}

        backend.configs.delete(TEST_ID)
        assert backend.configs.get(TEST_ID) is None

