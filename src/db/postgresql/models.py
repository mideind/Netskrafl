"""
SQLAlchemy ORM models for PostgreSQL backend.

These models mirror the NDB models in skrafldb.py but use PostgreSQL-native
features like JSONB, proper foreign keys, and UUID primary keys.
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from uuid import UUID as PyUUID

from sqlalchemy import (
    String,
    Text,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

# UTC timezone constant
UTC = timezone.utc


def utcnow() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


class User(Base):
    """User model - mirrors NDB UserModel."""

    __tablename__ = "users"

    # Primary key - UUID string (compatible with existing NDB keys)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Required fields
    nickname: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    inactive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # These fields are never NULL - empty string is used instead (matching NDB behavior)
    email: Mapped[str] = mapped_column(String(256), nullable=False, default="", index=True)
    image: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    image_blob: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    account: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    plan: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Lowercase versions for case-insensitive search
    nick_lc: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    name_lc: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)

    # Locale and location
    locale: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, default="is_IS")
    location: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, default="")

    # Preferences stored as JSONB
    prefs: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # Timestamps
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_login: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Ready status
    ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ready_timed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    chat_disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Elo ratings (denormalized for quick access)
    elo: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    human_elo: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    manual_elo: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)

    # Best scores
    highest_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    highest_score_game: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    best_word: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    best_word_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    best_word_game: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Game count
    games: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    elo_ratings: Mapped[List["EloRating"]] = relationship(
        "EloRating", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id!r}, nickname={self.nickname!r})>"


class EloRating(Base):
    """Elo ratings per user per locale - mirrors NDB EloModel."""

    __tablename__ = "elo_ratings"

    # Composite primary key: user_id + locale
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    locale: Mapped[str] = mapped_column(String(10), primary_key=True)

    # Ratings
    elo: Mapped[int] = mapped_column(Integer, nullable=False, default=1200, index=True)
    human_elo: Mapped[int] = mapped_column(Integer, nullable=False, default=1200, index=True)
    manual_elo: Mapped[int] = mapped_column(Integer, nullable=False, default=1200, index=True)

    # Timestamp
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="elo_ratings")

    __table_args__ = (
        Index("ix_elo_ratings_locale_elo", "locale", "elo"),
        Index("ix_elo_ratings_locale_human_elo", "locale", "human_elo"),
        Index("ix_elo_ratings_locale_manual_elo", "locale", "manual_elo"),
    )

    def __repr__(self) -> str:
        return f"<EloRating(user_id={self.user_id!r}, locale={self.locale!r}, elo={self.elo})>"


class Robot(Base):
    """Robot Elo ratings - mirrors NDB RobotModel."""

    __tablename__ = "robots"

    # Composite primary key: locale + level
    locale: Mapped[str] = mapped_column(String(10), primary_key=True)
    level: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Elo rating
    elo: Mapped[int] = mapped_column(Integer, nullable=False, default=1200)

    def __repr__(self) -> str:
        return f"<Robot(locale={self.locale!r}, level={self.level}, elo={self.elo})>"


class Game(Base):
    """Game model - mirrors NDB GameModel."""

    __tablename__ = "games"

    # Primary key - UUID string
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Players (nullable for robot games)
    player0_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    player1_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Game locale
    locale: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # Racks (current state)
    rack0: Mapped[str] = mapped_column(String(16), nullable=False)
    rack1: Mapped[str] = mapped_column(String(16), nullable=False)

    # Initial racks
    irack0: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    irack1: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    # Scores
    score0: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score1: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Game state
    to_move: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    robot_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    over: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    # Timestamps
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    ts_last_move: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Moves stored as JSONB array
    moves: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )

    # Preferences
    prefs: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    # Tile count on board
    tile_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Elo ratings at game end
    elo0: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    elo1: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    elo0_adj: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    elo1_adj: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    human_elo0: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    human_elo1: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    human_elo0_adj: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    human_elo1_adj: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    manual_elo0: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    manual_elo1: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    manual_elo0_adj: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    manual_elo1_adj: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationships
    player0: Mapped[Optional["User"]] = relationship("User", foreign_keys=[player0_id])
    player1: Mapped[Optional["User"]] = relationship("User", foreign_keys=[player1_id])

    __table_args__ = (
        Index("ix_games_player0_over", "player0_id", "over"),
        Index("ix_games_player1_over", "player1_id", "over"),
    )

    def __repr__(self) -> str:
        return f"<Game(id={self.id!r}, over={self.over})>"


class Favorite(Base):
    """Favorite (friend) relationships - mirrors NDB FavoriteModel."""

    __tablename__ = "favorites"

    # Composite primary key
    src_user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    dest_user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )

    __table_args__ = (
        Index("ix_favorites_dest", "dest_user_id"),
    )


class Challenge(Base):
    """Challenge between users - mirrors NDB ChallengeModel."""

    __tablename__ = "challenges"

    # Primary key - native UUID with auto-generation
    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    # Users involved
    src_user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dest_user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Challenge parameters
    prefs: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    # Timestamp
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )

    __table_args__ = (
        Index("ix_challenges_src_dest", "src_user_id", "dest_user_id"),
    )


class Stats(Base):
    """Statistics snapshots - mirrors NDB StatsModel."""

    __tablename__ = "stats"

    # Primary key - native UUID with auto-generation
    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    # User (nullable for robot stats)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    robot_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)

    # Timestamp
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )

    # Game counts
    games: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    human_games: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manual_games: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Elo ratings
    elo: Mapped[int] = mapped_column(Integer, nullable=False, default=1200, index=True)
    human_elo: Mapped[int] = mapped_column(Integer, nullable=False, default=1200, index=True)
    manual_elo: Mapped[int] = mapped_column(Integer, nullable=False, default=1200, index=True)

    # Scores
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    human_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manual_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    score_against: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    human_score_against: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manual_score_against: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Win/loss counts
    wins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    losses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    human_wins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    human_losses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manual_wins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manual_losses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Chat(Base):
    """Chat messages - mirrors NDB ChatModel."""

    __tablename__ = "chats"

    # Primary key - native UUID with auto-generation
    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    # Channel (game:uuid or user:id1:id2)
    channel: Mapped[str] = mapped_column(String(256), nullable=False, index=True)

    # Users
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recipient_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Message content
    msg: Mapped[str] = mapped_column(Text, nullable=False)

    # Timestamp
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )


class Zombie(Base):
    """Zombie games (unfinished but abandoned) - mirrors NDB ZombieModel."""

    __tablename__ = "zombies"

    # Composite primary key
    game_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("games.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )


class Block(Base):
    """User blocking - mirrors NDB BlockModel."""

    __tablename__ = "blocks"

    # Composite primary key
    blocker_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    blocked_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )

    # Timestamp
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        Index("ix_blocks_blocked", "blocked_id"),
    )


class Report(Base):
    """User reports - mirrors NDB ReportModel."""

    __tablename__ = "reports"

    # Primary key - native UUID with auto-generation
    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    # Users
    reporter_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reported_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Report details
    code: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Timestamp
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class Image(Base):
    """User images and thumbnails - mirrors NDB ImageModel."""

    __tablename__ = "images"

    # Primary key - native UUID with auto-generation
    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    # User reference
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Format (jpeg, thumb384, thumb512, etc.)
    fmt: Mapped[str] = mapped_column(String(32), nullable=False)

    # Image data
    image: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    __table_args__ = (
        Index("ix_images_user_fmt", "user_id", "fmt", unique=True),
    )


class Promo(Base):
    """Promotion tracking - mirrors NDB PromoModel."""

    __tablename__ = "promos"

    # Primary key - native UUID with auto-generation
    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    # User
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Promotion identifier
    promotion: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Timestamp
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )


class Transaction(Base):
    """Transaction log - mirrors NDB TransactionModel."""

    __tablename__ = "transactions"

    # Primary key - native UUID with auto-generation
    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    # User
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Transaction details
    plan: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    op: Mapped[str] = mapped_column(String(64), nullable=False)

    # Timestamp
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )


class Submission(Base):
    """Word submissions - mirrors NDB SubmissionModel."""

    __tablename__ = "submissions"

    # Primary key - native UUID with auto-generation
    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    # User
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Submission details
    locale: Mapped[str] = mapped_column(String(10), nullable=False)
    word: Mapped[str] = mapped_column(String(64), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Timestamp
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )


class Completion(Base):
    """Completion log for batch processes - mirrors NDB CompletionModel."""

    __tablename__ = "completions"

    # Primary key - native UUID with auto-generation
    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    # Process type (stats, ratings, etc.)
    proctype: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Time range
    ts_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ts_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Status
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Timestamp
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )


class Rating(Base):
    """Rating table entries - mirrors NDB RatingModel."""

    __tablename__ = "ratings"

    # Composite primary key: kind + rank
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)  # all, human, manual
    rank: Mapped[int] = mapped_column(Integer, primary_key=True)

    # User (nullable for robot)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    robot_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Current stats
    games: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    elo: Mapped[int] = mapped_column(Integer, nullable=False, default=1200)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score_against: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    losses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Yesterday's stats
    rank_yesterday: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    games_yesterday: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    elo_yesterday: Mapped[int] = mapped_column(Integer, nullable=False, default=1200)
    score_yesterday: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score_against_yesterday: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wins_yesterday: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    losses_yesterday: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Week ago stats
    rank_week_ago: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    games_week_ago: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    elo_week_ago: Mapped[int] = mapped_column(Integer, nullable=False, default=1200)
    score_week_ago: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score_against_week_ago: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wins_week_ago: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    losses_week_ago: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Month ago stats
    rank_month_ago: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    games_month_ago: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    elo_month_ago: Mapped[int] = mapped_column(Integer, nullable=False, default=1200)
    score_month_ago: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score_against_month_ago: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wins_month_ago: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    losses_month_ago: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Riddle(Base):
    """Daily riddles - mirrors NDB RiddleModel."""

    __tablename__ = "riddles"

    # Composite primary key: date + locale
    date: Mapped[str] = mapped_column(String(16), primary_key=True)
    locale: Mapped[str] = mapped_column(String(10), primary_key=True)

    # Riddle data as JSON
    riddle_json: Mapped[str] = mapped_column(Text, nullable=False)

    # Metadata
    created: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
