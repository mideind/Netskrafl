"""
Protocol definitions for database backends.

This module defines the interface contracts that both NDB and PostgreSQL
backends must implement. Using Protocol classes enables structural subtyping,
so backends don't need to explicitly inherit from these classes.

The protocols mirror the existing NDB model API to minimize changes to
application code during migration.
"""

from __future__ import annotations

from typing import (
    Protocol,
    Optional,
    List,
    Dict,
    Any,
    Iterator,
    TypeVar,
    Generic,
    Sequence,
    Set,
    Tuple,
    runtime_checkable,
)
from datetime import datetime
from dataclasses import dataclass


# =============================================================================
# Data Transfer Objects (shared across backends)
# =============================================================================


@dataclass
class EloDict:
    """Elo ratings for a user in a specific locale."""

    elo: int
    human_elo: int
    manual_elo: int


@dataclass
class MoveDict:
    """A single move in a game."""

    coord: str
    tiles: str
    score: int
    rack: Optional[str] = None
    timestamp: Optional[datetime] = None

    def is_resignation(self) -> bool:
        """Check if this move is a resignation."""
        return self.coord == "resign"


# TypedDict-style preferences (using regular dict for compatibility)
PrefsDict = Dict[str, Any]


@dataclass
class LiveGameInfo:
    """Information about an active (live) game."""

    uuid: str
    ts: datetime
    opp: Optional[str]
    robot_level: int
    my_turn: bool
    sc0: int
    sc1: int
    prefs: Optional[PrefsDict]
    tile_count: int
    locale: Optional[str]


@dataclass
class FinishedGameInfo:
    """Information about a completed game."""

    uuid: str
    ts: datetime
    ts_last_move: Optional[datetime]
    opp: Optional[str]
    robot_level: int
    sc0: int
    sc1: int
    elo_adj: int
    human_elo_adj: int
    manual_elo_adj: int
    prefs: Optional[PrefsDict]
    locale: Optional[str]


@dataclass
class ZombieGameInfo:
    """Information about a zombie game (unfinished but abandoned)."""

    uuid: str
    ts: datetime
    opp: Optional[str]
    robot_level: int
    sc0: int
    sc1: int
    locale: Optional[str]


@dataclass
class UserPrefixInfo:
    """User information returned from prefix searches."""

    id: str
    nickname: str
    prefs: Optional[PrefsDict]
    timestamp: Optional[datetime]
    ready: bool
    ready_timed: bool
    elo: int
    human_elo: int
    manual_elo: int
    image: Optional[str]
    has_image_blob: bool


@dataclass
class ChallengeInfo:
    """Information about a challenge between users."""

    opp: Optional[str]
    prefs: Optional[PrefsDict]
    ts: datetime
    key: str


@dataclass
class ChatMessage:
    """A chat message."""

    user: str
    name: str
    ts: datetime
    msg: str


@dataclass
class ChatHistoryEntry:
    """An entry in the chat history."""

    user: str
    ts: datetime
    last_msg: str
    unread: bool


@dataclass
class RatingInfo:
    """Rating table entry with historical data."""

    rank: int
    userid: Optional[str]
    robot_level: int
    games: int
    elo: int
    score: int
    score_against: int
    wins: int
    losses: int
    # Yesterday's values
    rank_yesterday: int
    games_yesterday: int
    elo_yesterday: int
    score_yesterday: int
    score_against_yesterday: int
    wins_yesterday: int
    losses_yesterday: int
    # Week ago values
    rank_week_ago: int
    games_week_ago: int
    elo_week_ago: int
    score_week_ago: int
    score_against_week_ago: int
    wins_week_ago: int
    losses_week_ago: int
    # Month ago values
    rank_month_ago: int
    games_month_ago: int
    elo_month_ago: int
    score_month_ago: int
    score_against_month_ago: int
    wins_month_ago: int
    losses_month_ago: int


@dataclass
class RatingForLocale:
    """Locale-specific rating entry."""

    rank: int
    userid: str
    elo: int


@dataclass
class StatsInfo:
    """Statistics for a user or robot."""

    user: Optional[str]
    robot_level: int
    timestamp: datetime
    games: int
    elo: int
    score: int
    score_against: int
    wins: int
    losses: int
    rank: int


# =============================================================================
# Entity Protocols
# =============================================================================

T = TypeVar("T", covariant=True)
T_co = TypeVar("T_co", covariant=True)
# Covariant type variable for QueryProtocol - T only appears in return positions
T_Query = TypeVar("T_Query", covariant=True)


@runtime_checkable
class EntityProtocol(Protocol):
    """Base protocol for all database entities."""

    @property
    def key_id(self) -> str:
        """The entity's unique identifier."""
        ...


@runtime_checkable
class UserEntityProtocol(EntityProtocol, Protocol):
    """Protocol for User entities."""

    @property
    def nickname(self) -> str: ...

    @property
    def email(self) -> Optional[str]: ...

    @property
    def image(self) -> Optional[str]: ...

    @property
    def account(self) -> Optional[str]: ...

    @property
    def plan(self) -> Optional[str]: ...

    @property
    def nick_lc(self) -> Optional[str]: ...

    @property
    def name_lc(self) -> Optional[str]: ...

    @property
    def inactive(self) -> bool: ...

    @property
    def locale(self) -> Optional[str]: ...

    @property
    def location(self) -> Optional[str]: ...

    @property
    def prefs(self) -> PrefsDict: ...

    @property
    def timestamp(self) -> datetime: ...

    @property
    def last_login(self) -> Optional[datetime]: ...

    @property
    def ready(self) -> bool: ...

    @property
    def ready_timed(self) -> bool: ...

    @property
    def chat_disabled(self) -> bool: ...

    @property
    def elo(self) -> int: ...

    @property
    def human_elo(self) -> int: ...

    @property
    def manual_elo(self) -> int: ...

    @property
    def highest_score(self) -> int: ...

    @property
    def highest_score_game(self) -> Optional[str]: ...

    @property
    def best_word(self) -> Optional[str]: ...

    @property
    def best_word_score(self) -> int: ...

    @property
    def best_word_game(self) -> Optional[str]: ...

    @property
    def games(self) -> int: ...


@runtime_checkable
class GameEntityProtocol(EntityProtocol, Protocol):
    """Protocol for Game entities."""

    @property
    def player0_id(self) -> Optional[str]: ...

    @property
    def player1_id(self) -> Optional[str]: ...

    @property
    def locale(self) -> Optional[str]: ...

    @property
    def rack0(self) -> str: ...

    @property
    def rack1(self) -> str: ...

    @property
    def score0(self) -> int: ...

    @property
    def score1(self) -> int: ...

    @property
    def to_move(self) -> int: ...

    @property
    def robot_level(self) -> int: ...

    @property
    def over(self) -> bool: ...

    @property
    def timestamp(self) -> datetime: ...

    @property
    def ts_last_move(self) -> Optional[datetime]: ...

    @property
    def moves(self) -> List[MoveDict]: ...

    @property
    def irack0(self) -> Optional[str]: ...

    @property
    def irack1(self) -> Optional[str]: ...

    @property
    def prefs(self) -> Optional[PrefsDict]: ...

    @property
    def tile_count(self) -> Optional[int]: ...

    # Elo fields at game end
    @property
    def elo0(self) -> Optional[int]: ...

    @property
    def elo1(self) -> Optional[int]: ...

    @property
    def elo0_adj(self) -> Optional[int]: ...

    @property
    def elo1_adj(self) -> Optional[int]: ...

    @property
    def human_elo0(self) -> Optional[int]: ...

    @property
    def human_elo1(self) -> Optional[int]: ...

    @property
    def human_elo0_adj(self) -> Optional[int]: ...

    @property
    def human_elo1_adj(self) -> Optional[int]: ...

    @property
    def manual_elo0(self) -> Optional[int]: ...

    @property
    def manual_elo1(self) -> Optional[int]: ...

    @property
    def manual_elo0_adj(self) -> Optional[int]: ...

    @property
    def manual_elo1_adj(self) -> Optional[int]: ...

    def manual_wordcheck(self) -> bool:
        """Check if manual wordcheck is enabled for this game."""
        ...


@runtime_checkable
class EloEntityProtocol(EntityProtocol, Protocol):
    """Protocol for Elo rating entities (per user per locale)."""

    @property
    def locale(self) -> str: ...

    @property
    def user_id(self) -> str: ...

    @property
    def timestamp(self) -> datetime: ...

    @property
    def elo(self) -> int: ...

    @property
    def human_elo(self) -> int: ...

    @property
    def manual_elo(self) -> int: ...


@runtime_checkable
class StatsEntityProtocol(EntityProtocol, Protocol):
    """Protocol for Stats entities."""

    @property
    def user_id(self) -> Optional[str]: ...

    @property
    def robot_level(self) -> int: ...

    @property
    def timestamp(self) -> datetime: ...

    @property
    def games(self) -> int: ...

    @property
    def human_games(self) -> int: ...

    @property
    def manual_games(self) -> int: ...

    @property
    def elo(self) -> int: ...

    @property
    def human_elo(self) -> int: ...

    @property
    def manual_elo(self) -> int: ...

    @property
    def score(self) -> int: ...

    @property
    def human_score(self) -> int: ...

    @property
    def manual_score(self) -> int: ...

    @property
    def score_against(self) -> int: ...

    @property
    def human_score_against(self) -> int: ...

    @property
    def manual_score_against(self) -> int: ...

    @property
    def wins(self) -> int: ...

    @property
    def losses(self) -> int: ...

    @property
    def human_wins(self) -> int: ...

    @property
    def human_losses(self) -> int: ...

    @property
    def manual_wins(self) -> int: ...

    @property
    def manual_losses(self) -> int: ...


@runtime_checkable
class ChatEntityProtocol(EntityProtocol, Protocol):
    """Protocol for Chat message entities."""

    @property
    def channel(self) -> str: ...

    @property
    def user_id(self) -> str: ...

    @property
    def recipient_id(self) -> Optional[str]: ...

    @property
    def timestamp(self) -> datetime: ...

    @property
    def msg(self) -> str: ...


@runtime_checkable
class RiddleEntityProtocol(EntityProtocol, Protocol):
    """Protocol for Riddle entities."""

    @property
    def date(self) -> str: ...

    @property
    def locale(self) -> str: ...

    @property
    def riddle_json(self) -> str: ...

    @property
    def riddle(self) -> Optional[Dict[str, Any]]: ...

    @property
    def created(self) -> datetime: ...

    @property
    def version(self) -> int: ...


# =============================================================================
# Query Protocol
# =============================================================================


class QueryProtocol(Protocol, Generic[T_Query]):
    """Protocol for query objects supporting filtering, ordering, and fetching."""

    def filter(self, *conditions: Any) -> QueryProtocol[T_Query]:
        """Add filter conditions to the query."""
        ...

    def order(self, *columns: Any) -> QueryProtocol[T_Query]:
        """Add ordering to the query."""
        ...

    def fetch(self, limit: Optional[int] = None) -> Sequence[T_Query]:
        """Execute the query and return results."""
        ...

    def get(self) -> Optional[T_Query]:
        """Execute the query and return the first result."""
        ...

    def count(self) -> int:
        """Return the count of matching entities."""
        ...

    def iter(self, limit: int = 0) -> Iterator[T_Query]:
        """Iterate over query results."""
        ...


# =============================================================================
# Repository Protocols
# =============================================================================


class UserRepositoryProtocol(Protocol):
    """Protocol for User repository operations."""

    def get_by_id(self, user_id: str) -> Optional[UserEntityProtocol]:
        """Fetch a user by their ID."""
        ...

    def get_by_account(self, account: str) -> Optional[UserEntityProtocol]:
        """Fetch a user by their OAuth2 account identifier."""
        ...

    def get_by_nickname(
        self, nickname: str, ignore_case: bool = False
    ) -> Optional[UserEntityProtocol]:
        """Fetch a user by their nickname."""
        ...

    def get_by_email(self, email: str) -> Optional[UserEntityProtocol]:
        """Fetch a user by their email address."""
        ...

    def get_multi(self, user_ids: List[str]) -> Sequence[Optional[UserEntityProtocol]]:
        """Fetch multiple users by their IDs."""
        ...

    def create(
        self,
        user_id: str,
        account: str,
        email: Optional[str],
        nickname: str,
        image: Optional[str] = None,
        preferences: Optional[PrefsDict] = None,
        locale: Optional[str] = None,
    ) -> Tuple[str, PrefsDict]:
        """Create a new user.

        Returns:
            Tuple of (user_id, preferences dict)
        """
        ...

    def update(self, user: UserEntityProtocol, **kwargs: Any) -> None:
        """Update a user's attributes."""
        ...

    def delete(self, user_id: str) -> None:
        """Delete a user and their related entities."""
        ...

    def count(self) -> int:
        """Return the total number of users."""
        ...

    def list_prefix(
        self, prefix: str, max_len: int = 50, locale: Optional[str] = None
    ) -> Iterator[UserPrefixInfo]:
        """List users whose nicknames start with the given prefix."""
        ...

    def list_similar_elo(
        self, elo: int, max_len: int = 40, locale: Optional[str] = None
    ) -> Sequence[Tuple[str, EloDict]]:
        """List users with similar Elo ratings."""
        ...

    def query(self) -> QueryProtocol[UserEntityProtocol]:
        """Return a query object for users."""
        ...


class GameRepositoryProtocol(Protocol):
    """Protocol for Game repository operations."""

    def get_by_id(self, game_id: str) -> Optional[GameEntityProtocol]:
        """Fetch a game by its UUID."""
        ...

    def create(self, **kwargs: Any) -> GameEntityProtocol:
        """Create a new game."""
        ...

    def update(self, game: GameEntityProtocol, **kwargs: Any) -> None:
        """Update a game's attributes."""
        ...

    def delete(self, game_id: str) -> None:
        """Delete a game."""
        ...

    def list_finished_games(
        self, user_id: str, versus: Optional[str] = None, max_len: int = 10
    ) -> List[FinishedGameInfo]:
        """List finished games for a user."""
        ...

    def iter_live_games(self, user_id: str, max_len: int = 10) -> Iterator[LiveGameInfo]:
        """Iterate over live (active) games for a user."""
        ...

    def delete_for_user(self, user_id: str) -> None:
        """Delete all games for a user."""
        ...

    def query(self) -> QueryProtocol[GameEntityProtocol]:
        """Return a query object for games."""
        ...


class EloRepositoryProtocol(Protocol):
    """Protocol for Elo rating repository operations."""

    def get_for_user(self, locale: str, user_id: str) -> Optional[EloEntityProtocol]:
        """Get Elo ratings for a user in a specific locale."""
        ...

    def create(
        self, locale: str, user_id: str, ratings: EloDict
    ) -> Optional[EloEntityProtocol]:
        """Create Elo ratings for a user in a locale."""
        ...

    def upsert(
        self,
        existing: Optional[EloEntityProtocol],
        locale: str,
        user_id: str,
        ratings: EloDict,
    ) -> bool:
        """Create or update Elo ratings.

        Returns:
            True if created/updated successfully
        """
        ...

    def delete_for_user(self, user_id: str) -> None:
        """Delete all Elo ratings for a user."""
        ...

    def list_rating(
        self, kind: str, locale: str, limit: int = 100
    ) -> Iterator[RatingForLocale]:
        """List ratings by kind (human, manual, all) for a locale."""
        ...

    def list_similar(
        self, locale: str, elo: int, max_len: int = 40
    ) -> Iterator[Tuple[str, EloDict]]:
        """List users with similar Elo in a locale."""
        ...

    def load_multi(self, locale: str, user_ids: List[str]) -> Dict[str, EloDict]:
        """Load Elo ratings for multiple users."""
        ...


class StatsRepositoryProtocol(Protocol):
    """Protocol for Stats repository operations."""

    def create(
        self, user_id: Optional[str] = None, robot_level: int = 0
    ) -> StatsEntityProtocol:
        """Create a new stats entry."""
        ...

    def newest_for_user(self, user_id: str) -> Optional[StatsEntityProtocol]:
        """Get the most recent stats for a user."""
        ...

    def newest_before(
        self, ts: datetime, user_id: str, robot_level: int = 0
    ) -> StatsEntityProtocol:
        """Get the most recent stats before a timestamp."""
        ...

    def last_for_user(self, user_id: str, days: int) -> Sequence[StatsEntityProtocol]:
        """Get stats entries for a user over the last N days."""
        ...

    def list_elo(
        self, timestamp: Optional[datetime] = None, max_len: int = 100
    ) -> Tuple[List[StatsInfo], Optional[datetime]]:
        """List stats ordered by Elo."""
        ...

    def list_human_elo(
        self, timestamp: Optional[datetime] = None, max_len: int = 100
    ) -> Tuple[List[StatsInfo], Optional[datetime]]:
        """List stats ordered by human Elo."""
        ...

    def list_manual_elo(
        self, timestamp: Optional[datetime] = None, max_len: int = 100
    ) -> Tuple[List[StatsInfo], Optional[datetime]]:
        """List stats ordered by manual Elo."""
        ...

    def delete_for_user(self, user_id: str) -> None:
        """Delete all stats for a user."""
        ...

    def delete_at_timestamp(self, timestamp: datetime) -> None:
        """Delete stats at a specific timestamp."""
        ...


class FavoriteRepositoryProtocol(Protocol):
    """Protocol for Favorite (friend) repository operations."""

    def list_favorites(self, user_id: str, max_len: int = 100) -> Iterator[str]:
        """List favorite user IDs for a user."""
        ...

    def has_relation(self, src_user_id: str, dest_user_id: str) -> bool:
        """Check if a favorite relationship exists."""
        ...

    def add_relation(self, src_user_id: str, dest_user_id: str) -> None:
        """Add a favorite relationship."""
        ...

    def delete_relation(self, src_user_id: str, dest_user_id: str) -> None:
        """Delete a favorite relationship."""
        ...

    def delete_for_user(self, user_id: str) -> None:
        """Delete all favorites for a user."""
        ...


class ChallengeRepositoryProtocol(Protocol):
    """Protocol for Challenge repository operations."""

    def has_relation(self, src_user_id: str, dest_user_id: str) -> bool:
        """Check if a challenge exists between users."""
        ...

    def find_relation(
        self, src_user_id: str, dest_user_id: str, key: Optional[str] = None
    ) -> Tuple[bool, Optional[PrefsDict]]:
        """Find a challenge relationship and its preferences."""
        ...

    def add_relation(
        self, src_user_id: str, dest_user_id: str, prefs: Optional[PrefsDict] = None
    ) -> None:
        """Add a challenge."""
        ...

    def delete_relation(
        self, src_user_id: str, dest_user_id: str, key: Optional[str] = None
    ) -> Tuple[bool, Optional[PrefsDict]]:
        """Delete a challenge and return its preferences."""
        ...

    def delete_for_user(self, user_id: str) -> None:
        """Delete all challenges for a user."""
        ...

    def list_issued(self, user_id: str, max_len: int = 20) -> Iterator[ChallengeInfo]:
        """List challenges issued by a user."""
        ...

    def list_received(self, user_id: str, max_len: int = 20) -> Iterator[ChallengeInfo]:
        """List challenges received by a user."""
        ...


class ChatRepositoryProtocol(Protocol):
    """Protocol for Chat repository operations."""

    def list_conversation(
        self, channel: str, max_len: int = 250
    ) -> Iterator[ChatMessage]:
        """List messages in a conversation channel."""
        ...

    def check_conversation(self, channel: str, user_id: str) -> bool:
        """Check if there are unread messages for a user in a channel."""
        ...

    def add_msg(
        self,
        channel: str,
        from_user: str,
        to_user: Optional[str],
        msg: str,
        timestamp: Optional[datetime] = None,
    ) -> datetime:
        """Add a message to a channel."""
        ...

    def add_msg_in_game(
        self,
        game_uuid: str,
        from_user: str,
        to_user: Optional[str],
        msg: str,
        timestamp: Optional[datetime] = None,
    ) -> datetime:
        """Add a message in a game channel."""
        ...

    def add_msg_between_users(
        self,
        from_user: str,
        to_user: str,
        msg: str,
        timestamp: Optional[datetime] = None,
    ) -> datetime:
        """Add a direct message between users."""
        ...

    def chat_history(
        self, for_user: str, max_len: int = 20, blocked_users: Optional[Set[str]] = None
    ) -> Sequence[ChatHistoryEntry]:
        """Get chat history for a user."""
        ...


class BlockRepositoryProtocol(Protocol):
    """Protocol for Block (user blocking) repository operations."""

    def list_blocked_users(self, user_id: str, max_len: int = 100) -> Iterator[str]:
        """List users blocked by a user."""
        ...

    def list_blocked_by(self, user_id: str, max_len: int = 100) -> Iterator[str]:
        """List users who have blocked a user."""
        ...

    def block_user(self, blocker_id: str, blocked_id: str) -> bool:
        """Block a user. Returns True if newly blocked."""
        ...

    def unblock_user(self, blocker_id: str, blocked_id: str) -> bool:
        """Unblock a user. Returns True if was blocked."""
        ...

    def is_blocking(self, blocker_id: str, blocked_id: str) -> bool:
        """Check if one user is blocking another."""
        ...


class ZombieRepositoryProtocol(Protocol):
    """Protocol for Zombie game repository operations."""

    def add_game(self, game_id: str, user_id: str) -> None:
        """Mark a game as zombie for a user."""
        ...

    def delete_game(self, game_id: str, user_id: str) -> None:
        """Remove zombie marking for a game/user."""
        ...

    def delete_for_user(self, user_id: str) -> None:
        """Delete all zombie entries for a user."""
        ...

    def list_games(self, user_id: str) -> Iterator[ZombieGameInfo]:
        """List zombie games for a user."""
        ...


class RatingRepositoryProtocol(Protocol):
    """Protocol for Rating table repository operations."""

    def get_or_create(self, kind: str, rank: int) -> Any:
        """Get or create a rating entry."""
        ...

    def list_rating(self, kind: str) -> Iterator[RatingInfo]:
        """List all ratings of a kind."""
        ...

    def delete_all(self) -> None:
        """Delete all rating entries."""
        ...


class RiddleRepositoryProtocol(Protocol):
    """Protocol for Riddle repository operations."""

    def get_riddle(self, date_str: str, locale: str) -> Optional[RiddleEntityProtocol]:
        """Get a riddle by date and locale."""
        ...

    def get_riddles_for_date(self, date_str: str) -> Sequence[RiddleEntityProtocol]:
        """Get all riddles for a date."""
        ...

    def save_riddle(
        self, date_str: str, locale: str, riddle_json: str, version: int = 1
    ) -> RiddleEntityProtocol:
        """Save a riddle."""
        ...


class ImageRepositoryProtocol(Protocol):
    """Protocol for Image repository operations."""

    def get_thumbnail(
        self, user_id: str, size: int = 384
    ) -> Optional[bytes]:
        """Get a user's thumbnail image."""
        ...

    def set_thumbnail(
        self, user_id: str, image: bytes, size: int = 384
    ) -> None:
        """Set a user's thumbnail image."""
        ...


class ReportRepositoryProtocol(Protocol):
    """Protocol for Report repository operations."""

    def report_user(
        self, reporter_id: str, reported_id: str, code: int, text: str
    ) -> bool:
        """Report a user. Returns True if successful."""
        ...

    def list_reported_by(self, user_id: str, max_len: int = 100) -> Iterator[str]:
        """List users reported by a user."""
        ...


class PromoRepositoryProtocol(Protocol):
    """Protocol for Promotion tracking repository operations."""

    def add_promotion(self, user_id: str, promotion: str) -> None:
        """Record that a user has seen a promotion."""
        ...

    def list_promotions(self, user_id: str, promotion: str) -> Iterator[datetime]:
        """List when a user has seen a promotion."""
        ...


class TransactionRepositoryProtocol(Protocol):
    """Protocol for Transaction log repository operations."""

    def add_transaction(
        self, user_id: str, plan: str, kind: str, op: str
    ) -> None:
        """Log a transaction."""
        ...


class SubmissionRepositoryProtocol(Protocol):
    """Protocol for word Submission repository operations."""

    def submit_word(
        self, user_id: str, locale: str, word: str, comment: str
    ) -> None:
        """Submit a word for review."""
        ...


class CompletionRepositoryProtocol(Protocol):
    """Protocol for Completion log repository operations."""

    def add_completion(
        self, proctype: str, ts_from: datetime, ts_to: datetime
    ) -> None:
        """Log a successful completion."""
        ...

    def add_failure(
        self, proctype: str, ts_from: datetime, ts_to: datetime, reason: str
    ) -> None:
        """Log a failed completion."""
        ...


class RobotRepositoryProtocol(Protocol):
    """Protocol for Robot Elo repository operations."""

    def get_elo(self, locale: str, level: int) -> Optional[int]:
        """Get the Elo rating for a robot at a level."""
        ...

    def upsert_elo(self, locale: str, level: int, elo: int) -> bool:
        """Create or update robot Elo. Returns True if successful."""
        ...


# =============================================================================
# Transaction Context Protocol
# =============================================================================


class TransactionContextProtocol(Protocol):
    """Protocol for transaction context managers."""

    def __enter__(self) -> TransactionContextProtocol:
        ...

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        ...


# =============================================================================
# Database Backend Protocol
# =============================================================================


class DatabaseBackendProtocol(Protocol):
    """Protocol for the complete database backend.

    This is the main entry point for database operations. Implementations
    provide access to all entity repositories and transaction management.
    """

    @property
    def users(self) -> UserRepositoryProtocol:
        """Access the User repository."""
        ...

    @property
    def games(self) -> GameRepositoryProtocol:
        """Access the Game repository."""
        ...

    @property
    def elo(self) -> EloRepositoryProtocol:
        """Access the Elo repository."""
        ...

    @property
    def stats(self) -> StatsRepositoryProtocol:
        """Access the Stats repository."""
        ...

    @property
    def favorites(self) -> FavoriteRepositoryProtocol:
        """Access the Favorite repository."""
        ...

    @property
    def challenges(self) -> ChallengeRepositoryProtocol:
        """Access the Challenge repository."""
        ...

    @property
    def chat(self) -> ChatRepositoryProtocol:
        """Access the Chat repository."""
        ...

    @property
    def blocks(self) -> BlockRepositoryProtocol:
        """Access the Block repository."""
        ...

    @property
    def zombies(self) -> ZombieRepositoryProtocol:
        """Access the Zombie repository."""
        ...

    @property
    def ratings(self) -> RatingRepositoryProtocol:
        """Access the Rating repository."""
        ...

    @property
    def riddles(self) -> RiddleRepositoryProtocol:
        """Access the Riddle repository."""
        ...

    @property
    def images(self) -> ImageRepositoryProtocol:
        """Access the Image repository."""
        ...

    @property
    def reports(self) -> ReportRepositoryProtocol:
        """Access the Report repository."""
        ...

    @property
    def promos(self) -> PromoRepositoryProtocol:
        """Access the Promo repository."""
        ...

    @property
    def transactions(self) -> TransactionRepositoryProtocol:
        """Access the Transaction repository."""
        ...

    @property
    def submissions(self) -> SubmissionRepositoryProtocol:
        """Access the Submission repository."""
        ...

    @property
    def completions(self) -> CompletionRepositoryProtocol:
        """Access the Completion repository."""
        ...

    @property
    def robots(self) -> RobotRepositoryProtocol:
        """Access the Robot repository."""
        ...

    def transaction(self) -> TransactionContextProtocol:
        """Begin a database transaction.

        Usage:
            with db.transaction():
                db.users.update(user, elo=new_elo)
                db.games.update(game, over=True)
        """
        ...

    def close(self) -> None:
        """Close database connections and clean up resources."""
        ...

    def generate_id(self) -> str:
        """Generate a new unique ID for entities."""
        ...
