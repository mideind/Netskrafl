"""
Tests for AppVersion repository operations.

These tests run against any backend implementing the DatabaseBackendProtocol.
Use --backend option to select which backend(s) to test.

The AppVersion repository manages the singleton app version / client
configuration record reported to mobile clients via /inituser.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.db.protocols import AppVersionDict

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol


class TestAppVersionRepository:
    """Test AppVersion repository operations."""

    def test_get_nonexistent(self, backend: "DatabaseBackendProtocol") -> None:
        """Getting the record when none exists returns None."""
        backend.app_versions.delete_versions()
        assert backend.app_versions.get_versions() is None
        # Deleting a non-existent record is a no-op
        backend.app_versions.delete_versions()

    def test_set_get_replace_delete(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Can create, read, replace and delete the singleton record."""
        backend.app_versions.set_versions(
            AppVersionDict(
                min_supported_version="1.2.0",
                latest_version="1.5.0",
                update_message="Please update",
                ios_min_supported_version="1.3.0",
                api_url="https://api.example.com",
            )
        )
        av = backend.app_versions.get_versions()
        assert av is not None
        assert av.key_id == "app_version"
        assert av.min_supported_version == "1.2.0"
        assert av.latest_version == "1.5.0"
        assert av.update_message == "Please update"
        assert av.ios_min_supported_version == "1.3.0"
        assert av.android_min_supported_version is None
        assert av.ios_latest_version is None
        assert av.android_latest_version is None
        assert av.api_url == "https://api.example.com"
        assert av.moves_url is None

        # Replacing the record clears fields that are no longer set
        backend.app_versions.set_versions(
            AppVersionDict(
                min_supported_version="2.0.0",
                latest_version="2.0.0",
                moves_url="https://moves.example.com",
            )
        )
        av = backend.app_versions.get_versions()
        assert av is not None
        assert av.min_supported_version == "2.0.0"
        assert av.latest_version == "2.0.0"
        assert av.update_message is None
        assert av.ios_min_supported_version is None
        assert av.api_url is None
        assert av.moves_url == "https://moves.example.com"

        backend.app_versions.delete_versions()
        assert backend.app_versions.get_versions() is None

