"""
PostgreSQL Backend implementation.

This module provides the main PostgreSQLBackend class that implements
DatabaseBackendProtocol using SQLAlchemy ORM.
"""

from __future__ import annotations

from typing import Optional, Any, TYPE_CHECKING
import uuid

from sqlalchemy.orm import Session

from .connection import DatabaseSession, create_db_engine
from .models import Base
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

if TYPE_CHECKING:
    from ..protocols import (
        UserRepositoryProtocol,
        GameRepositoryProtocol,
        EloRepositoryProtocol,
        StatsRepositoryProtocol,
        FavoriteRepositoryProtocol,
        ChallengeRepositoryProtocol,
        ChatRepositoryProtocol,
        BlockRepositoryProtocol,
        ZombieRepositoryProtocol,
        RatingRepositoryProtocol,
        RiddleRepositoryProtocol,
        ImageRepositoryProtocol,
        ReportRepositoryProtocol,
        PromoRepositoryProtocol,
        TransactionRepositoryProtocol,
        SubmissionRepositoryProtocol,
        CompletionRepositoryProtocol,
        RobotRepositoryProtocol,
    )


class PostgreSQLTransactionContext:
    """Transaction context manager for PostgreSQL.

    This wraps a SQLAlchemy session with automatic commit/rollback.
    """

    def __init__(self, backend: "PostgreSQLBackend") -> None:
        self._backend = backend
        self._session: Optional[Session] = None

    def __enter__(self) -> "PostgreSQLTransactionContext":
        """Begin a new transaction."""
        self._session = self._backend._db_session._session_factory()
        # Update backend's current session
        self._backend._current_session = self._session
        # Reinitialize repositories with new session
        self._backend._init_repositories(self._session)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        """End the transaction - commit or rollback."""
        if self._session is None:
            return False

        try:
            if exc_type is None:
                self._session.commit()
            else:
                self._session.rollback()
        finally:
            self._session.close()
            self._session = None
            # Reset to default session
            self._backend._current_session = None
            self._backend._init_repositories(None)

        return False  # Don't suppress exceptions


class PostgreSQLBackend:
    """PostgreSQL implementation of DatabaseBackendProtocol.

    This class provides a PostgreSQL backend using SQLAlchemy ORM.

    Usage:
        from src.db.postgresql import PostgreSQLBackend

        db = PostgreSQLBackend(database_url="postgresql://...")

        # Simple operations (auto-commit per operation)
        user = db.users.get_by_id("user-123")

        # Transactional operations
        with db.transaction():
            db.users.update(user, elo=new_elo)
            db.games.update(game, over=True)
    """

    def __init__(self, database_url: Optional[str] = None) -> None:
        """Initialize the PostgreSQL backend.

        Args:
            database_url: PostgreSQL connection URL. If not provided, reads from
                          DATABASE_URL environment variable.
        """
        # Create engine and session manager
        engine = create_db_engine(database_url)
        self._db_session = DatabaseSession(engine)

        # Track current session for transaction management
        self._current_session: Optional[Session] = None

        # Initialize repositories with None session (will use auto-session)
        self._init_repositories(None)

    def _init_repositories(self, session: Optional[Session]) -> None:
        """Initialize or reinitialize repositories with a session."""
        # If no explicit session, create one that auto-commits
        if session is None:
            session = self._get_auto_session()

        self._users = UserRepository(session)
        self._games = GameRepository(session)
        self._elo = EloRepository(session)
        self._stats = StatsRepository(session)
        self._favorites = FavoriteRepository(session)
        self._challenges = ChallengeRepository(session)
        self._chat = ChatRepository(session)
        self._blocks = BlockRepository(session)
        self._zombies = ZombieRepository(session)
        self._ratings = RatingRepository(session)
        self._riddles = RiddleRepository(session)
        self._images = ImageRepository(session)
        self._reports = ReportRepository(session)
        self._promos = PromoRepository(session)
        self._transactions = TransactionRepository(session)
        self._submissions = SubmissionRepository(session)
        self._completions = CompletionRepository(session)
        self._robots = RobotRepository(session)

    def _get_auto_session(self) -> Session:
        """Get a session for auto-commit operations."""
        # For simplicity, create a new session
        # In production, you might want connection pooling
        return self._db_session._session_factory()

    @property
    def users(self) -> "UserRepositoryProtocol":
        """Access the User repository."""
        return self._users

    @property
    def games(self) -> "GameRepositoryProtocol":
        """Access the Game repository."""
        return self._games

    @property
    def elo(self) -> "EloRepositoryProtocol":
        """Access the Elo repository."""
        return self._elo

    @property
    def stats(self) -> "StatsRepositoryProtocol":
        """Access the Stats repository."""
        return self._stats

    @property
    def favorites(self) -> "FavoriteRepositoryProtocol":
        """Access the Favorite repository."""
        return self._favorites

    @property
    def challenges(self) -> "ChallengeRepositoryProtocol":
        """Access the Challenge repository."""
        return self._challenges

    @property
    def chat(self) -> "ChatRepositoryProtocol":
        """Access the Chat repository."""
        return self._chat

    @property
    def blocks(self) -> "BlockRepositoryProtocol":
        """Access the Block repository."""
        return self._blocks

    @property
    def zombies(self) -> "ZombieRepositoryProtocol":
        """Access the Zombie repository."""
        return self._zombies

    @property
    def ratings(self) -> "RatingRepositoryProtocol":
        """Access the Rating repository."""
        return self._ratings

    @property
    def riddles(self) -> "RiddleRepositoryProtocol":
        """Access the Riddle repository."""
        return self._riddles

    @property
    def images(self) -> "ImageRepositoryProtocol":
        """Access the Image repository."""
        return self._images

    @property
    def reports(self) -> "ReportRepositoryProtocol":
        """Access the Report repository."""
        return self._reports

    @property
    def promos(self) -> "PromoRepositoryProtocol":
        """Access the Promo repository."""
        return self._promos

    @property
    def transactions(self) -> "TransactionRepositoryProtocol":
        """Access the Transaction repository."""
        return self._transactions

    @property
    def submissions(self) -> "SubmissionRepositoryProtocol":
        """Access the Submission repository."""
        return self._submissions

    @property
    def completions(self) -> "CompletionRepositoryProtocol":
        """Access the Completion repository."""
        return self._completions

    @property
    def robots(self) -> "RobotRepositoryProtocol":
        """Access the Robot repository."""
        return self._robots

    def transaction(self) -> PostgreSQLTransactionContext:
        """Begin a database transaction.

        Usage:
            with db.transaction():
                db.users.update(user, elo=new_elo)
                db.games.update(game, over=True)
                # Commits on success, rolls back on exception
        """
        return PostgreSQLTransactionContext(self)

    def close(self) -> None:
        """Close database connections and clean up resources."""
        self._db_session.close()

    def generate_id(self) -> str:
        """Generate a new unique ID for entities."""
        return str(uuid.uuid1())

    def create_tables(self) -> None:
        """Create all database tables.

        This should only be called during initial setup or testing.
        For production, use proper migrations (e.g., Alembic).
        """
        Base.metadata.create_all(self._db_session.engine)

    def drop_tables(self) -> None:
        """Drop all database tables.

        WARNING: This deletes all data! Only use for testing.
        """
        Base.metadata.drop_all(self._db_session.engine)
