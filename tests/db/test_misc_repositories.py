"""
Tests for miscellaneous repository operations.

These tests cover smaller repositories:
- ReportRepository
- PromoRepository
- TransactionRepository
- SubmissionRepository
- CompletionRepository

Use --backend option to select which backend(s) to test.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol

UTC = timezone.utc


class TestReportRepository:
    """Test Report repository operations."""

    @pytest.fixture(autouse=True)
    def setup_report_users(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test users for Report tests."""
        for user_id, account, nickname in [
            ("report-user-1", "test:report1", "ReportUser1"),
            ("report-user-2", "test:report2", "ReportUser2"),
        ]:
            existing = backend.users.get_by_id(user_id)
            if existing is None:
                backend.users.create(
                    user_id=user_id,
                    account=account,
                    email=None,
                    nickname=nickname,
                    locale="is_IS",
                )

    def test_report_user(self, backend: "DatabaseBackendProtocol") -> None:
        """Can report a user."""
        result = backend.reports.report_user(
            reporter_id="report-user-1",
            reported_id="report-user-2",
            code=1,
            text="Test report",
        )

        assert result is True

    def test_list_reported_by(self, backend: "DatabaseBackendProtocol") -> None:
        """Can list users who have reported a user."""
        # user-1 reports user-2
        backend.reports.report_user(
            reporter_id="report-user-1",
            reported_id="report-user-2",
            code=2,
            text="Another report",
        )

        # list_reported_by returns users who have reported user-2
        reporters = list(backend.reports.list_reported_by("report-user-2"))

        assert "report-user-1" in reporters


class TestPromoRepository:
    """Test Promo repository operations."""

    @pytest.fixture(autouse=True)
    def setup_promo_user(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test user for Promo tests."""
        existing = backend.users.get_by_id("promo-user")
        if existing is None:
            backend.users.create(
                user_id="promo-user",
                account="test:promo",
                email=None,
                nickname="PromoUser",
                locale="is_IS",
            )

    def test_add_promotion(self, backend: "DatabaseBackendProtocol") -> None:
        """Can record that a user has seen a promotion."""
        # Should not raise
        backend.promos.add_promotion("promo-user", "test_promo_001")

    def test_list_promotions(self, backend: "DatabaseBackendProtocol") -> None:
        """Can list when a user has seen a promotion."""
        # Add some promotions
        backend.promos.add_promotion("promo-user", "test_promo_002")
        backend.promos.add_promotion("promo-user", "test_promo_002")

        times = list(backend.promos.list_promotions("promo-user", "test_promo_002"))

        # Should have at least two entries
        assert len(times) >= 2
        # Each should be a datetime
        for t in times:
            assert isinstance(t, datetime)


class TestTransactionRepository:
    """Test Transaction repository operations."""

    @pytest.fixture(autouse=True)
    def setup_transaction_user(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test user for Transaction tests."""
        existing = backend.users.get_by_id("transaction-user")
        if existing is None:
            backend.users.create(
                user_id="transaction-user",
                account="test:transaction",
                email=None,
                nickname="TransactionUser",
                locale="is_IS",
            )

    def test_add_transaction(self, backend: "DatabaseBackendProtocol") -> None:
        """Can log a transaction and verify it was persisted."""
        # Get initial count
        initial_count = backend.transactions.count_for_user("transaction-user")

        # Add a transaction
        backend.transactions.add_transaction(
            user_id="transaction-user",
            plan="premium",
            kind="subscription",
            op="purchase",
        )

        # Verify count increased
        new_count = backend.transactions.count_for_user("transaction-user")
        assert new_count == initial_count + 1


class TestSubmissionRepository:
    """Test Submission repository operations."""

    @pytest.fixture(autouse=True)
    def setup_submission_user(self, backend: "DatabaseBackendProtocol") -> None:
        """Create test user for Submission tests."""
        existing = backend.users.get_by_id("submission-user")
        if existing is None:
            backend.users.create(
                user_id="submission-user",
                account="test:submission",
                email=None,
                nickname="SubmissionUser",
                locale="is_IS",
            )

    def test_submit_word(self, backend: "DatabaseBackendProtocol") -> None:
        """Can submit a word and verify it was persisted."""
        # Get initial count
        initial_count = backend.submissions.count_for_user("submission-user")

        # Submit a word
        backend.submissions.submit_word(
            user_id="submission-user",
            locale="is_IS",
            word="nýttorð",
            comment="Ég held þetta ætti að vera í orðabókinni",
        )

        # Verify count increased
        new_count = backend.submissions.count_for_user("submission-user")
        assert new_count == initial_count + 1


class TestCompletionRepository:
    """Test Completion repository operations."""

    def test_add_completion(self, backend: "DatabaseBackendProtocol") -> None:
        """Can log a successful completion and verify it was persisted."""
        proctype = "test_daily_stats"
        now = datetime.now(UTC)

        # Get initial count
        initial_count = backend.completions.count_for_proctype(proctype)

        # Add a completion
        backend.completions.add_completion(
            proctype=proctype,
            ts_from=now,
            ts_to=now,
        )

        # Verify count increased
        new_count = backend.completions.count_for_proctype(proctype)
        assert new_count == initial_count + 1

    def test_add_failure(self, backend: "DatabaseBackendProtocol") -> None:
        """Can log a failed completion and verify it was persisted."""
        proctype = "test_weekly_rating"
        now = datetime.now(UTC)

        # Get initial count
        initial_count = backend.completions.count_for_proctype(proctype)

        # Add a failure
        backend.completions.add_failure(
            proctype=proctype,
            ts_from=now,
            ts_to=now,
            reason="Test failure reason",
        )

        # Verify count increased
        new_count = backend.completions.count_for_proctype(proctype)
        assert new_count == initial_count + 1
