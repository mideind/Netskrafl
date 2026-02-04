"""
Tests for Riddle repository operations.

These tests run against any backend implementing the DatabaseBackendProtocol.
Use --backend option to select which backend(s) to test.

The Riddle repository manages daily riddles ("Gáta dagsins") that are
stored per date and locale.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol


class TestRiddleRepository:
    """Test Riddle repository operations."""

    def test_save_and_get_riddle(self, backend: "DatabaseBackendProtocol") -> None:
        """Can save and retrieve a riddle."""
        date_str = "2025-01-15"
        locale = "is_IS"
        riddle_data = {
            "question": "Hvað er hvítt og kemur úr himnum?",
            "answer": "Snjór",
            "difficulty": 1,
        }
        riddle_json = json.dumps(riddle_data)

        # Save riddle
        saved = backend.riddles.save_riddle(
            date_str=date_str,
            locale=locale,
            riddle_json=riddle_json,
            version=1,
        )

        assert saved is not None
        assert saved.date == date_str
        assert saved.locale == locale
        assert saved.riddle_json == riddle_json
        assert saved.version == 1

        # Retrieve riddle
        loaded = backend.riddles.get_riddle(date_str, locale)

        assert loaded is not None
        assert loaded.date == date_str
        assert loaded.locale == locale
        assert loaded.riddle_json == riddle_json

    def test_get_nonexistent_riddle(self, backend: "DatabaseBackendProtocol") -> None:
        """Getting a non-existent riddle returns None."""
        loaded = backend.riddles.get_riddle("1999-12-31", "xx_XX")

        assert loaded is None

    def test_save_riddle_updates_existing(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Saving a riddle for existing date/locale updates it."""
        date_str = "2025-02-20"
        locale = "en_US"

        # Save initial riddle
        riddle_v1 = {"question": "What is white?", "answer": "Snow"}
        backend.riddles.save_riddle(
            date_str=date_str,
            locale=locale,
            riddle_json=json.dumps(riddle_v1),
            version=1,
        )

        # Save updated riddle with same date/locale
        riddle_v2 = {"question": "What falls from the sky?", "answer": "Rain"}
        backend.riddles.save_riddle(
            date_str=date_str,
            locale=locale,
            riddle_json=json.dumps(riddle_v2),
            version=2,
        )

        # Should get the updated version
        loaded = backend.riddles.get_riddle(date_str, locale)

        assert loaded is not None
        assert loaded.version == 2
        assert json.loads(loaded.riddle_json) == riddle_v2

    def test_get_riddles_for_date(self, backend: "DatabaseBackendProtocol") -> None:
        """Can get all riddles for a specific date across locales."""
        date_str = "2025-03-10"

        # Save riddles for different locales
        locales_and_riddles = [
            ("is_IS", {"question": "Íslenski gátan", "answer": "Svar"}),
            ("en_US", {"question": "English riddle", "answer": "Answer"}),
            ("pl_PL", {"question": "Polska zagadka", "answer": "Odpowiedź"}),
        ]

        for locale, riddle in locales_and_riddles:
            backend.riddles.save_riddle(
                date_str=date_str,
                locale=locale,
                riddle_json=json.dumps(riddle),
                version=1,
            )

        # Get all riddles for that date
        riddles = backend.riddles.get_riddles_for_date(date_str)

        assert len(riddles) >= 3

        # All should have the same date
        for riddle in riddles:
            assert riddle.date == date_str

        # Check we have all locales
        locales_found = {r.locale for r in riddles}
        assert "is_IS" in locales_found
        assert "en_US" in locales_found
        assert "pl_PL" in locales_found

    def test_get_riddles_for_date_empty(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Getting riddles for a date with none returns empty list."""
        riddles = backend.riddles.get_riddles_for_date("1990-01-01")

        assert len(riddles) == 0

    def test_riddle_has_created_timestamp(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """Saved riddles have a created timestamp."""
        date_str = "2025-04-01"
        locale = "nb_NO"
        riddle_json = json.dumps({"question": "Norsk gåte", "answer": "Svar"})

        saved = backend.riddles.save_riddle(
            date_str=date_str,
            locale=locale,
            riddle_json=riddle_json,
            version=1,
        )

        assert saved.created is not None

    def test_riddle_property_returns_parsed_json(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """The riddle property returns parsed JSON dict."""
        date_str = "2025-05-15"
        locale = "is_IS"
        riddle_data = {
            "question": "Test",
            "answer": "Svar",
            "hints": ["hint1", "hint2"],
        }
        riddle_json = json.dumps(riddle_data)

        saved = backend.riddles.save_riddle(
            date_str=date_str,
            locale=locale,
            riddle_json=riddle_json,
            version=1,
        )

        # The riddle property should return parsed dict
        if saved.riddle is not None:
            assert saved.riddle == riddle_data
