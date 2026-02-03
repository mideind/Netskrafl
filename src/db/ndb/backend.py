"""
NDB Backend implementation.

This module provides the main NDBBackend class that implements
DatabaseBackendProtocol by wrapping the existing skrafldb.py models.
"""

from __future__ import annotations

from typing import Any
from contextlib import contextmanager

import skrafldb

from .repositories import (
    UserRepository,
    GameRepository,
    EloRepository,
    StatsRepository,
    FavoriteRepository,
    ChallengeRepository,
    ChatRepository,
    BlockRepository,
    ZombieRepository,
    RatingRepository,
    RiddleRepository,
    ImageRepository,
    ReportRepository,
    PromoRepository,
    TransactionRepository,
    SubmissionRepository,
    CompletionRepository,
    RobotRepository,
)


class NDBTransactionContext:
    """Transaction context manager for NDB.

    Note: NDB transactions work differently from SQL transactions.
    They use optimistic concurrency with automatic retries.
    This wrapper provides a compatible interface.
    """

    def __init__(self) -> None:
        self._in_transaction = False

    def __enter__(self) -> "NDBTransactionContext":
        """Enter the transaction context.

        Note: NDB doesn't have explicit BEGIN TRANSACTION.
        Transactions are started implicitly with @ndb.transactional.
        This context manager is mainly for API compatibility.
        """
        self._in_transaction = True
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        """Exit the transaction context.

        Note: NDB transactions auto-commit on success and auto-rollback
        on exception. We don't suppress exceptions.
        """
        self._in_transaction = False
        return False  # Don't suppress exceptions


class NDBBackend:
    """NDB implementation of DatabaseBackendProtocol.

    This class wraps the existing skrafldb.py NDB models to provide
    a backend-agnostic interface for database operations.

    Usage:
        from src.db.ndb import NDBBackend

        db = NDBBackend()
        user = db.users.get_by_id("user-123")
        games = list(db.games.iter_live_games("user-123"))
    """

    def __init__(self) -> None:
        """Initialize the NDB backend.

        Note: The NDB client is a singleton managed by skrafldb.Client.
        This backend doesn't create new connections.
        """
        # Initialize repositories (lazy - no DB calls here)
        self._users = UserRepository()
        self._games = GameRepository()
        self._elo = EloRepository()
        self._stats = StatsRepository()
        self._favorites = FavoriteRepository()
        self._challenges = ChallengeRepository()
        self._chat = ChatRepository()
        self._blocks = BlockRepository()
        self._zombies = ZombieRepository()
        self._ratings = RatingRepository()
        self._riddles = RiddleRepository()
        self._images = ImageRepository()
        self._reports = ReportRepository()
        self._promos = PromoRepository()
        self._transactions = TransactionRepository()
        self._submissions = SubmissionRepository()
        self._completions = CompletionRepository()
        self._robots = RobotRepository()

    @property
    def users(self) -> UserRepository:
        """Access the User repository."""
        return self._users

    @property
    def games(self) -> GameRepository:
        """Access the Game repository."""
        return self._games

    @property
    def elo(self) -> EloRepository:
        """Access the Elo repository."""
        return self._elo

    @property
    def stats(self) -> StatsRepository:
        """Access the Stats repository."""
        return self._stats

    @property
    def favorites(self) -> FavoriteRepository:
        """Access the Favorite repository."""
        return self._favorites

    @property
    def challenges(self) -> ChallengeRepository:
        """Access the Challenge repository."""
        return self._challenges

    @property
    def chat(self) -> ChatRepository:
        """Access the Chat repository."""
        return self._chat

    @property
    def blocks(self) -> BlockRepository:
        """Access the Block repository."""
        return self._blocks

    @property
    def zombies(self) -> ZombieRepository:
        """Access the Zombie repository."""
        return self._zombies

    @property
    def ratings(self) -> RatingRepository:
        """Access the Rating repository."""
        return self._ratings

    @property
    def riddles(self) -> RiddleRepository:
        """Access the Riddle repository."""
        return self._riddles

    @property
    def images(self) -> ImageRepository:
        """Access the Image repository."""
        return self._images

    @property
    def reports(self) -> ReportRepository:
        """Access the Report repository."""
        return self._reports

    @property
    def promos(self) -> PromoRepository:
        """Access the Promo repository."""
        return self._promos

    @property
    def transactions(self) -> TransactionRepository:
        """Access the Transaction repository."""
        return self._transactions

    @property
    def submissions(self) -> SubmissionRepository:
        """Access the Submission repository."""
        return self._submissions

    @property
    def completions(self) -> CompletionRepository:
        """Access the Completion repository."""
        return self._completions

    @property
    def robots(self) -> RobotRepository:
        """Access the Robot repository."""
        return self._robots

    def transaction(self) -> NDBTransactionContext:
        """Begin a database transaction.

        Note: NDB transactions work differently from SQL transactions.
        For true transactional behavior, use @ndb.transactional decorator
        on functions that need atomic operations.

        This method provides a compatible context manager interface.

        Usage:
            with db.transaction():
                db.users.update(user, elo=new_elo)
                db.games.update(game, over=True)
        """
        return NDBTransactionContext()

    def close(self) -> None:
        """Close database connections and clean up resources.

        Note: The NDB client is a singleton and is not closed here.
        This method is provided for API compatibility.
        """
        pass  # NDB client lifecycle is managed by skrafldb

    def generate_id(self) -> str:
        """Generate a new unique ID for entities."""
        return skrafldb.Unique.id()

    @contextmanager
    def context(self):
        """Get an NDB context for database operations.

        This wraps skrafldb.Client.get_context() for use cases that
        need explicit context management.

        Usage:
            with db.context():
                user = db.users.get_by_id("user-123")
        """
        with skrafldb.Client.get_context():
            yield
