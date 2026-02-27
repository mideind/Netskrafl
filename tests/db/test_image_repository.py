"""
Tests for Image repository operations.

These tests run against any backend implementing the DatabaseBackendProtocol.
Use --backend option to select which backend(s) to test.

The Image repository manages user thumbnail images stored as binary blobs.
"""

from __future__ import annotations

import pytest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol


class TestImageRepository:
    """Test Image repository operations."""

    @pytest.fixture(autouse=True)
    def setup_image_users(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test users for Image tests."""
        test_users = [
            ("image-user-1", "test:image1", "ImageUser1"),
            ("image-user-2", "test:image2", "ImageUser2"),
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

    def _create_test_image(self, size: int = 100) -> bytes:
        """Create a simple test image (fake JPEG header + data)."""
        # JPEG magic bytes + some padding to simulate an image
        jpeg_header = bytes([0xFF, 0xD8, 0xFF, 0xE0])
        padding = bytes([0x00] * (size - len(jpeg_header)))
        return jpeg_header + padding

    def test_set_and_get_thumbnail(self, backend: "DatabaseBackendProtocol") -> None:
        """Can set and retrieve a thumbnail image."""
        user_id = "image-user-1"
        test_image = self._create_test_image(200)
        size = 384

        # Set thumbnail
        backend.images.set_thumbnail(user_id, test_image, size)

        # Get thumbnail
        loaded = backend.images.get_thumbnail(user_id, size)

        assert loaded is not None
        assert loaded == test_image

    def test_get_nonexistent_thumbnail(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Getting a non-existent thumbnail returns None."""
        loaded = backend.images.get_thumbnail("nonexistent-user-xyz", 384)

        assert loaded is None

    def test_set_thumbnail_different_sizes(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Can store different sized thumbnails for same user."""
        user_id = "image-user-2"
        image_384 = self._create_test_image(150)
        image_512 = self._create_test_image(250)

        # Set thumbnails of different sizes
        backend.images.set_thumbnail(user_id, image_384, 384)
        backend.images.set_thumbnail(user_id, image_512, 512)

        # Retrieve each size
        loaded_384 = backend.images.get_thumbnail(user_id, 384)
        loaded_512 = backend.images.get_thumbnail(user_id, 512)

        assert loaded_384 == image_384
        assert loaded_512 == image_512

    def test_set_thumbnail_overwrites_existing(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Setting a thumbnail overwrites the existing one."""
        user_id = "image-user-1"
        size = 384

        # Set initial thumbnail
        image_v1 = self._create_test_image(100)
        backend.images.set_thumbnail(user_id, image_v1, size)

        # Verify it was set
        loaded_v1 = backend.images.get_thumbnail(user_id, size)
        assert loaded_v1 == image_v1

        # Set new thumbnail
        image_v2 = self._create_test_image(200)
        backend.images.set_thumbnail(user_id, image_v2, size)

        # Should get the new one
        loaded_v2 = backend.images.get_thumbnail(user_id, size)
        assert loaded_v2 == image_v2
        assert loaded_v2 != image_v1

    def test_thumbnail_preserves_binary_data(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Thumbnail binary data is preserved exactly."""
        user_id = "image-user-1"
        size = 384

        # Create image with specific byte patterns
        test_bytes = bytes(range(256)) * 4  # All byte values repeated

        backend.images.set_thumbnail(user_id, test_bytes, size)
        loaded = backend.images.get_thumbnail(user_id, size)

        assert loaded is not None
        assert loaded == test_bytes
        assert len(loaded) == len(test_bytes)

    def test_default_thumbnail_size(self, backend: "DatabaseBackendProtocol") -> None:
        """Default thumbnail size is 384."""
        user_id = "image-user-2"
        test_image = self._create_test_image(100)

        # Set with explicit size
        backend.images.set_thumbnail(user_id, test_image, 384)

        # Get with default size (should be 384)
        loaded = backend.images.get_thumbnail(user_id)

        assert loaded == test_image
