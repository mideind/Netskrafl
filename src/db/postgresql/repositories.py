"""
Repository implementations for PostgreSQL backend.

These classes implement the repository protocols using SQLAlchemy ORM.
"""

from __future__ import annotations

from typing import (
    Optional,
    List,
    Dict,
    Iterator,
    Sequence,
    Set,
    Tuple,
    Any,
    TYPE_CHECKING,
    TypeVar,
    Generic,
    Type,
    cast,
)
from datetime import datetime, timezone
import uuid

from sqlalchemy import select, delete, and_, or_, func, desc, asc
from sqlalchemy.orm import Session, aliased

from config import DEFAULT_LOCALE

from .models import (
    User,
    Game,
    EloRating,
    Robot,
    Stats,
    Favorite,
    Challenge,
    Chat,
    Zombie,
    Block,
    Report,
    Image,
    Promo,
    Transaction,
    Submission,
    Completion,
    Rating,
    RatingArchive,
    Riddle,
)

from ..protocols import (
    PrefsDict,
    EloDict,
    UserPrefixInfo,
    LiveGameInfo,
    FinishedGameInfo,
    ZombieGameInfo,
    ChallengeInfo,
    ChatMessage,
    ChatHistoryEntry,
    RatingInfo,
    RatingForLocale,
    StatsInfo,
)

if TYPE_CHECKING:
    from ..protocols import UserEntityProtocol, GameEntityProtocol, EloEntityProtocol

UTC = timezone.utc


def _generate_id() -> str:
    """Generate a new UUID for entity IDs."""
    return str(uuid.uuid1())


class UserRepository:
    """PostgreSQL implementation of UserRepositoryProtocol."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, user_id: str) -> Optional[User]:
        """Fetch a user by their ID."""
        return self._session.get(User, user_id)

    def get_by_account(self, account: str) -> Optional[User]:
        """Fetch a user by their OAuth2 account identifier."""
        if not account:
            return None
        stmt = select(User).where(User.account == account)
        return self._session.execute(stmt).scalar_one_or_none()

    def get_by_nickname(
        self, nickname: str, ignore_case: bool = False
    ) -> Optional[User]:
        """Fetch a user by their nickname."""
        if ignore_case:
            # Try lowercase first
            stmt = select(User).where(User.nick_lc == nickname.lower())
            user = self._session.execute(stmt).scalar_one_or_none()
            if user:
                return user
        # Try exact match
        stmt = select(User).where(User.nickname == nickname)
        return self._session.execute(stmt).scalar_one_or_none()

    def get_by_email(self, email: str) -> Optional[User]:
        """Fetch a user by their email address."""
        if not email:
            return None
        # Find active users with this email, ordered by elo > 0 desc, timestamp desc
        stmt = (
            select(User)
            .where(and_(User.email == email.lower(), User.inactive == False))  # noqa: E712
            .order_by(desc(User.elo > 0), desc(User.timestamp))
        )
        return self._session.execute(stmt).scalars().first()

    def get_multi(self, user_ids: List[str]) -> List[Optional[User]]:
        """Fetch multiple users by their IDs."""
        if not user_ids:
            return []
        # Fetch all at once
        stmt = select(User).where(User.id.in_(user_ids))
        users_by_id = {u.id: u for u in self._session.execute(stmt).scalars()}
        # Return in same order as requested, with None for missing
        return [
            users_by_id.get(uid)
            for uid in user_ids
        ]

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
        """Create a new user."""
        prefs = preferences or {}
        user = User(
            id=user_id,
            account=account,
            email=email or "",  # NDB stores "" not NULL
            nickname=nickname,
            nick_lc=nickname.lower(),
            name_lc=prefs.get("full_name", "").lower() if prefs else "",
            image=image or "",  # NDB stores "" not NULL
            inactive=False,
            prefs=prefs,
            plan="friend" if prefs.get("friend", False) else None,
            locale=locale or "is_IS",
            ready=True,
            ready_timed=True,
            last_login=datetime.now(UTC),
            games=0,
        )
        self._session.add(user)
        self._session.flush()

        # Return full preferences with defaults
        all_prefs: PrefsDict = {
            "beginner": True,
            "ready": True,
            "ready_timed": True,
            "fanfare": False,
            "audio": False,
            "fairplay": False,
        }
        all_prefs.update(prefs)
        return user_id, all_prefs

    def update(self, user: "UserEntityProtocol", **kwargs: Any) -> None:
        """Update a user's attributes."""
        if not isinstance(user, User):
            raise TypeError("Expected User model from PostgreSQL backend")

        for key, value in kwargs.items():
            if hasattr(user, key):
                setattr(user, key, value)
            else:
                raise AttributeError(f"User has no attribute '{key}'")

        # Special handling for nick_lc when nickname changes
        if "nickname" in kwargs:
            setattr(user, "nick_lc", kwargs["nickname"].lower())

        # Special handling for name_lc when prefs changes
        if "prefs" in kwargs:
            prefs = kwargs["prefs"]
            if isinstance(prefs, dict) and "full_name" in prefs:
                setattr(user, "name_lc", prefs["full_name"].lower())

        self._session.flush()

    def delete(self, user_id: str) -> None:
        """Delete a user and their related entities."""
        # CASCADE will handle related entities
        stmt = delete(User).where(User.id == user_id)
        self._session.execute(stmt)
        self._session.flush()

    def count(self) -> int:
        """Return the total number of users."""
        stmt = select(func.count()).select_from(User)
        return self._session.execute(stmt).scalar_one()

    def list_prefix(
        self, prefix: str, max_len: int = 50, locale: Optional[str] = None
    ) -> Iterator[UserPrefixInfo]:
        """List users whose nickname OR full name starts with the prefix.
        Matches NDB list_prefix: nickname matches first (ordered by nick_lc),
        then full-name matches (ordered by name_lc), de-duplicated by id, with
        max_len applied across the combined stream."""
        if not prefix:
            return

        prefix_lc = prefix.lower()

        def make(u: User) -> UserPrefixInfo:
            return UserPrefixInfo(
                id=u.id,
                nickname=u.nickname,
                prefs=cast(PrefsDict, u.prefs),
                timestamp=u.timestamp,
                ready=u.ready,
                ready_timed=u.ready_timed,
                elo=u.elo,
                human_elo=u.human_elo,
                manual_elo=u.manual_elo,
                image=u.image,
                has_image_blob=u.image_blob is not None,
            )

        def build_stmt(col: Any):
            s = select(User).where(
                and_(col.startswith(prefix_lc), User.inactive == False)  # noqa: E712
            )
            if locale:
                s = s.where(User.locale == locale)
            s = s.order_by(col)
            # max_len <= 0 means "no limit" (matches NDB's `0 < max_len`)
            if max_len > 0:
                s = s.limit(max_len)
            return s

        seen: Set[str] = set()
        count = 0
        # Nickname matches first, then full-name matches
        for col in (User.nick_lc, User.name_lc):
            if max_len > 0 and count >= max_len:
                break
            for user in self._session.execute(build_stmt(col)).scalars():
                if user.id in seen:
                    continue
                seen.add(user.id)
                yield make(user)
                count += 1
                if max_len > 0 and count >= max_len:
                    break

    def list_similar_elo(
        self, elo: int, max_len: int = 40, locale: Optional[str] = None
    ) -> List[Tuple[str, EloDict]]:
        """List users with similar Elo ratings."""
        half = max_len // 2

        # Get users with lower Elo (only users who have played: highest_score > 0,
        # matching NDB list_similar_elo)
        stmt_lower = (
            select(User)
            .where(
                and_(
                    User.human_elo < elo,
                    User.inactive == False,  # noqa: E712
                    User.highest_score > 0,
                )
            )
            .order_by(desc(User.human_elo))
            .limit(half)
        )
        if locale:
            stmt_lower = stmt_lower.where(User.locale == locale)

        # Get users with higher or equal Elo
        stmt_higher = (
            select(User)
            .where(
                and_(
                    User.human_elo >= elo,
                    User.inactive == False,  # noqa: E712
                    User.highest_score > 0,
                )
            )
            .order_by(asc(User.human_elo))
            .limit(half)
        )
        if locale:
            stmt_higher = stmt_higher.where(User.locale == locale)

        lower = list(self._session.execute(stmt_lower).scalars())
        higher = list(self._session.execute(stmt_higher).scalars())

        # Combine: lower (reversed) + higher
        lower.reverse()
        combined = lower + higher

        return [
            (u.id, EloDict(u.elo, u.human_elo, u.manual_elo))
            for u in combined[:max_len]
        ]

    def list_top_elo(self, kind: str, limit: int) -> List[str]:
        """List the ids of the users with the highest current 'old style'
        (locale-independent) Elo rating of the given kind ('all', 'human'
        or 'manual'), in descending order. These fields are maintained
        canonically by the nightly stats run."""
        if kind == "human":
            col = User.human_elo
        elif kind == "manual":
            col = User.manual_elo
        else:
            # Default, kind == 'all'
            col = User.elo
        stmt = select(User.id).order_by(desc(col)).limit(limit)
        return [row[0] for row in self._session.execute(stmt)]

    def query(self) -> "PostgreSQLQueryWrapper[User]":
        """Return a query object for users."""
        return PostgreSQLQueryWrapper(self._session, User)


class GameRepository:
    """PostgreSQL implementation of GameRepositoryProtocol."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, game_id: str) -> Optional[Game]:
        """Fetch a game by its UUID."""
        return self._session.get(Game, game_id)

    def create(self, **kwargs: Any) -> Game:
        """Create a new game."""
        game_id = kwargs.pop("id", None) or _generate_id()
        # Map "moves" kwarg to the "moves_json" column attribute
        if "moves" in kwargs:
            kwargs["moves_json"] = kwargs.pop("moves")
        game = Game(id=game_id, **kwargs)
        self._session.add(game)
        self._session.flush()
        return game

    def update(self, game: "GameEntityProtocol", **kwargs: Any) -> None:
        """Update a game's attributes."""
        if not isinstance(game, Game):
            raise TypeError("Expected Game model from PostgreSQL backend")

        for key, value in kwargs.items():
            # Map "moves" to the "moves_json" column attribute
            attr = "moves_json" if key == "moves" else key
            if hasattr(game, attr):
                setattr(game, attr, value)

        self._session.flush()

    def delete(self, game_id: str) -> None:
        """Delete a game."""
        stmt = delete(Game).where(Game.id == game_id)
        self._session.execute(stmt)
        self._session.flush()

    def list_finished_games(
        self, user_id: str, versus: Optional[str] = None, max_len: int = 10
    ) -> List[FinishedGameInfo]:
        """List finished games for a user."""
        stmt = (
            select(Game)
            .where(
                and_(
                    Game.over == True,  # noqa: E712
                    or_(Game.player0_id == user_id, Game.player1_id == user_id),
                )
            )
            .order_by(desc(Game.ts_last_move))
            .limit(max_len)
        )

        if versus:
            stmt = stmt.where(
                or_(
                    and_(Game.player0_id == user_id, Game.player1_id == versus),
                    and_(Game.player1_id == user_id, Game.player0_id == versus),
                )
            )

        results = []
        for game in self._session.execute(stmt).scalars():
            # Determine opponent and orient scores/elo to the querying user.
            # sc0/elo_adj are always the querying user's; sc1 the opponent's
            # (matches NDB GameModel.list_finished_games).
            if game.player0_id == user_id:
                opp = game.player1_id
                sc0, sc1 = game.score0, game.score1
                elo_adj = game.elo0_adj
                human_elo_adj = game.human_elo0_adj
                manual_elo_adj = game.manual_elo0_adj
            else:
                opp = game.player0_id
                sc0, sc1 = game.score1, game.score0
                elo_adj = game.elo1_adj
                human_elo_adj = game.human_elo1_adj
                manual_elo_adj = game.manual_elo1_adj

            prefs = cast(Optional[PrefsDict], game.prefs)
            locale = game.locale or (prefs or {}).get("locale") or DEFAULT_LOCALE
            results.append(
                FinishedGameInfo(
                    uuid=game.id,
                    ts=game.timestamp,
                    ts_last_move=game.ts_last_move,
                    opp=opp,
                    robot_level=game.robot_level,
                    sc0=sc0,
                    sc1=sc1,
                    elo_adj=elo_adj or 0,
                    human_elo_adj=human_elo_adj or 0,
                    manual_elo_adj=manual_elo_adj or 0,
                    prefs=prefs,
                    locale=locale,
                )
            )

        return results

    def iter_live_games(
        self, user_id: str, max_len: int = 10
    ) -> Iterator[LiveGameInfo]:
        """Iterate over live (active) games for a user."""
        stmt = (
            select(Game)
            .where(
                and_(
                    Game.over == False,  # noqa: E712
                    or_(Game.player0_id == user_id, Game.player1_id == user_id),
                )
            )
            .order_by(desc(Game.ts_last_move))
            .limit(max_len)
        )

        for game in self._session.execute(stmt).scalars():
            # Determine opponent and whose turn, orienting scores to the
            # querying user (sc0 = user's score). Matches NDB.
            if game.player0_id == user_id:
                opp = game.player1_id
                sc0, sc1 = game.score0, game.score1
                my_turn = game.to_move == 0
            else:
                opp = game.player0_id
                sc0, sc1 = game.score1, game.score0
                my_turn = game.to_move == 1

            prefs = cast(Optional[PrefsDict], game.prefs)
            locale = game.locale or (prefs or {}).get("locale") or DEFAULT_LOCALE
            yield LiveGameInfo(
                uuid=game.id,
                ts=game.ts_last_move or game.timestamp,
                opp=opp,
                robot_level=game.robot_level,
                my_turn=my_turn,
                sc0=sc0,
                sc1=sc1,
                prefs=prefs,
                tile_count=game.tile_count or 0,
                locale=locale,
            )

    def count_live_games(self, user_id: str, max_count: int = 0) -> int:
        """Return the number of live (active) games for a user.
        If max_count > 0, stop counting once that threshold is reached."""
        base = (
            select(Game.id)
            .where(
                and_(
                    Game.over == False,  # noqa: E712
                    or_(Game.player0_id == user_id, Game.player1_id == user_id),
                )
            )
        )
        if max_count > 0:
            base = base.limit(max_count)
        stmt = select(func.count()).select_from(base.subquery())
        return self._session.execute(stmt).scalar_one()

    def delete_for_user(self, user_id: str) -> None:
        """Delete all games for a user."""
        stmt = delete(Game).where(
            or_(Game.player0_id == user_id, Game.player1_id == user_id)
        )
        self._session.execute(stmt)
        self._session.flush()

    def query(self) -> "PostgreSQLQueryWrapper[Game]":
        """Return a query object for games."""
        return PostgreSQLQueryWrapper(self._session, Game)


class EloRepository:
    """PostgreSQL implementation of EloRepositoryProtocol."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_user(self, locale: str, user_id: str) -> Optional[EloRating]:
        """Get Elo ratings for a user in a specific locale."""
        return self._session.get(EloRating, (user_id, locale))

    def create(
        self, locale: str, user_id: str, ratings: EloDict
    ) -> Optional[EloRating]:
        """Create Elo ratings for a user in a locale."""
        if not locale or not user_id:
            return None
        elo = EloRating(
            user_id=user_id,
            locale=locale,
            elo=ratings.elo,
            human_elo=ratings.human_elo,
            manual_elo=ratings.manual_elo,
        )
        self._session.add(elo)
        self._session.flush()
        return elo

    def upsert(
        self,
        existing: Optional["EloEntityProtocol"],
        locale: str,
        user_id: str,
        ratings: EloDict,
    ) -> bool:
        """Create or update Elo ratings."""
        if existing is None:
            return self.create(locale, user_id, ratings) is not None

        if not isinstance(existing, EloRating):
            raise TypeError("Expected EloRating model from PostgreSQL backend")
        model = cast(EloRating, existing)

        model.elo = ratings.elo
        model.human_elo = ratings.human_elo
        model.manual_elo = ratings.manual_elo
        model.timestamp = datetime.now(UTC)
        self._session.flush()
        return True

    def delete_for_user(self, user_id: str) -> None:
        """Delete all Elo ratings for a user."""
        stmt = delete(EloRating).where(EloRating.user_id == user_id)
        self._session.execute(stmt)
        self._session.flush()

    def list_rating(
        self, kind: str, locale: str, limit: int = 100
    ) -> Iterator[RatingForLocale]:
        """List ratings by kind (human, manual, all) for a locale."""
        if kind == "human":
            order_col = EloRating.human_elo
        elif kind == "manual":
            order_col = EloRating.manual_elo
        else:
            order_col = EloRating.elo

        stmt = (
            select(EloRating)
            .where(EloRating.locale == locale)
            .order_by(desc(order_col))
            .limit(limit)
        )

        for rank, elo in enumerate(self._session.execute(stmt).scalars(), 1):
            yield RatingForLocale(
                rank=rank,
                userid=elo.user_id,
                elo=getattr(elo, order_col.key),
            )

    def list_similar(
        self, locale: str, elo: int, max_len: int = 40
    ) -> Iterator[Tuple[str, EloDict]]:
        """List users with similar Elo in a locale."""
        half = max_len // 2

        # Lower Elo
        stmt_lower = (
            select(EloRating)
            .where(and_(EloRating.locale == locale, EloRating.human_elo < elo))
            .order_by(desc(EloRating.human_elo))
            .limit(half)
        )

        # Higher or equal Elo
        stmt_higher = (
            select(EloRating)
            .where(and_(EloRating.locale == locale, EloRating.human_elo >= elo))
            .order_by(asc(EloRating.human_elo))
            .limit(half)
        )

        lower = list(self._session.execute(stmt_lower).scalars())
        higher = list(self._session.execute(stmt_higher).scalars())

        lower.reverse()
        combined = lower + higher

        for e in combined[:max_len]:
            yield e.user_id, EloDict(e.elo, e.human_elo, e.manual_elo)

    def load_multi(self, locale: str, user_ids: List[str]) -> Dict[str, EloDict]:
        """Load Elo ratings for multiple users."""
        if not user_ids:
            return {}

        stmt = select(EloRating).where(
            and_(EloRating.locale == locale, EloRating.user_id.in_(user_ids))
        )

        return {
            e.user_id: EloDict(e.elo, e.human_elo, e.manual_elo)
            for e in self._session.execute(stmt).scalars()
        }


class StatsRepository:
    """PostgreSQL implementation of StatsRepositoryProtocol."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self, user_id: Optional[str] = None, robot_level: int = 0
    ) -> Stats:
        """Create a new stats entry."""
        stats = Stats(user_id=user_id, robot_level=robot_level)
        self._session.add(stats)
        self._session.flush()
        return stats

    def _default_stats(
        self, user_id: Optional[str], robot_level: int = 0
    ) -> Stats:
        """Build an in-memory default Stats entity WITHOUT persisting it.
        Mirrors NDB StatsModel.create / newest_before, which returns an
        unpersisted default (Elo 1200, zero counters) when no record exists.
        Note: SQLAlchemy column defaults are only applied at flush, so we set
        the fields explicitly here since this object is never flushed."""
        return Stats(
            user_id=user_id,
            robot_level=robot_level,
            timestamp=datetime.now(UTC),
            games=0,
            human_games=0,
            manual_games=0,
            elo=1200,
            human_elo=1200,
            manual_elo=1200,
            score=0,
            human_score=0,
            manual_score=0,
            score_against=0,
            human_score_against=0,
            manual_score_against=0,
            wins=0,
            losses=0,
            human_wins=0,
            human_losses=0,
            manual_wins=0,
            manual_losses=0,
        )

    def newest_for_user(self, user_id: str) -> Optional[Stats]:
        """Get the most recent stats for a user."""
        stmt = (
            select(Stats)
            .where(Stats.user_id == user_id)
            .order_by(desc(Stats.timestamp))
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def newest_before(
        self, ts: datetime, user_id: Optional[str], robot_level: int = 0
    ) -> Stats:
        """Get the most recent stats at or before a timestamp.
        A user_id of None denotes a robot, further identified by its
        robot_level, mirroring NDB where robot stats rows have user=None."""
        # Inclusive bound (<=) to match NDB StatsModel.newest_before; the
        # leaderboard false-positive correction relies on the record AT `ts`.
        user_filter = (
            Stats.user_id.is_(None) if user_id is None else Stats.user_id == user_id
        )
        stmt = (
            select(Stats)
            .where(
                and_(
                    user_filter,
                    Stats.robot_level == robot_level,
                    Stats.timestamp <= ts,
                )
            )
            .order_by(desc(Stats.timestamp))
            .limit(1)
        )
        stats = self._session.execute(stmt).scalar_one_or_none()
        if stats:
            return stats
        # No record: return an unpersisted default (NDB does not write here)
        return self._default_stats(user_id, robot_level)

    def newest_before_multi(
        self, ts: datetime, keys: Sequence[Tuple[Optional[str], int]]
    ) -> List[Stats]:
        """Get the most recent stats at or before a timestamp for multiple
        (user_id, robot_level) keys at once. The result is aligned with the
        keys sequence; keys without a stored record yield an unpersisted
        default entity. This mirrors NDB StatsModel.newest_before_multi,
        which issues the same per-key queries asynchronously."""
        return [
            self.newest_before(ts, user_id, robot_level)
            for user_id, robot_level in keys
        ]

    def last_for_user(self, user_id: str, days: int) -> List[Stats]:
        """Get the newest `days` human (robot_level == 0) stats rows for a
        user, newest first. Matches NDB StatsModel.last_for_user, where `days`
        is a ROW COUNT limit (not a calendar window) and robot stats are
        excluded."""
        if not user_id or days <= 0:
            return []
        stmt = (
            select(Stats)
            .where(
                and_(
                    Stats.user_id == user_id,
                    Stats.robot_level == 0,
                    Stats.timestamp <= datetime.now(UTC),
                )
            )
            .order_by(desc(Stats.timestamp))
            .limit(days)
        )
        return list(self._session.execute(stmt).scalars())

    def list_elo(
        self, timestamp: Optional[datetime] = None, max_len: int = 100
    ) -> Tuple[List[StatsInfo], Optional[datetime]]:
        """List stats ordered by Elo."""
        return self._list_by_elo("elo", timestamp, max_len)

    def list_human_elo(
        self, timestamp: Optional[datetime] = None, max_len: int = 100
    ) -> Tuple[List[StatsInfo], Optional[datetime]]:
        """List stats ordered by human Elo."""
        return self._list_by_elo("human_elo", timestamp, max_len)

    def list_manual_elo(
        self, timestamp: Optional[datetime] = None, max_len: int = 100
    ) -> Tuple[List[StatsInfo], Optional[datetime]]:
        """List stats ordered by manual Elo."""
        return self._list_by_elo("manual_elo", timestamp, max_len)

    def _list_by_elo(
        self, elo_field: str, timestamp: Optional[datetime], max_len: int
    ) -> Tuple[List[StatsInfo], Optional[datetime]]:
        """List stats ordered by the specified Elo field, newest snapshot per
        user. The stats table holds periodic snapshots per user, so we must
        first reduce to the latest snapshot per (user, robot_level) at or
        before `timestamp` (None => now), then rank by Elo. This matches NDB
        _list_by, which dedups to one (newest) record per user. Postgres can do
        the dedup exactly via DISTINCT ON, so the NDB false-positive safety
        buffer is unnecessary here."""
        # DISTINCT ON (user_id, robot_level) keeps the newest snapshot per user
        latest = (
            select(Stats)
            .order_by(Stats.user_id, Stats.robot_level, desc(Stats.timestamp))
            .distinct(Stats.user_id, Stats.robot_level)
        )
        if timestamp:
            latest = latest.where(Stats.timestamp <= timestamp)
        subq = latest.subquery()
        s_alias = aliased(Stats, subq)

        stmt = (
            select(s_alias)
            .order_by(desc(getattr(s_alias, elo_field)))
            .limit(max_len)
        )

        results = []
        for rank, s in enumerate(self._session.execute(stmt).scalars(), 1):
            # Extract the fields of the requested kind into the generic
            # StatsInfo slots, mirroring the NDB _makedict variants in
            # StatsModel.list_elo / list_human_elo / list_manual_elo
            if elo_field == "human_elo":
                games, elo = s.human_games, s.human_elo
                score, score_against = s.human_score, s.human_score_against
                wins, losses = s.human_wins, s.human_losses
            elif elo_field == "manual_elo":
                games, elo = s.manual_games, s.manual_elo
                score, score_against = s.manual_score, s.manual_score_against
                wins, losses = s.manual_wins, s.manual_losses
            else:
                games, elo = s.games, s.elo
                score, score_against = s.score, s.score_against
                wins, losses = s.wins, s.losses
            results.append(
                StatsInfo(
                    user=s.user_id,
                    robot_level=s.robot_level,
                    timestamp=s.timestamp,
                    games=games,
                    elo=elo,
                    score=score,
                    score_against=score_against,
                    wins=wins,
                    losses=losses,
                    rank=rank,
                )
            )

        return results, None

    def delete_for_user(self, user_id: str) -> None:
        """Delete all stats for a user."""
        stmt = delete(Stats).where(Stats.user_id == user_id)
        self._session.execute(stmt)
        self._session.flush()

    def delete_at_timestamp(self, timestamp: datetime) -> None:
        """Delete stats at a specific timestamp."""
        stmt = delete(Stats).where(Stats.timestamp == timestamp)
        self._session.execute(stmt)
        self._session.flush()


class FavoriteRepository:
    """PostgreSQL implementation of FavoriteRepositoryProtocol."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_favorites(self, user_id: str, max_len: int = 100) -> Iterator[str]:
        """List favorite user IDs for a user."""
        stmt = (
            select(Favorite.dest_user_id)
            .where(Favorite.src_user_id == user_id)
            .limit(max_len)
        )
        for row in self._session.execute(stmt):
            yield row[0]

    def has_relation(self, src_user_id: str, dest_user_id: str) -> bool:
        """Check if a favorite relationship exists."""
        fav = self._session.get(Favorite, (src_user_id, dest_user_id))
        return fav is not None

    def add_relation(self, src_user_id: str, dest_user_id: str) -> None:
        """Add a favorite relationship."""
        if not self.has_relation(src_user_id, dest_user_id):
            fav = Favorite(src_user_id=src_user_id, dest_user_id=dest_user_id)
            self._session.add(fav)
            self._session.flush()

    def delete_relation(self, src_user_id: str, dest_user_id: str) -> None:
        """Delete a favorite relationship."""
        stmt = delete(Favorite).where(
            and_(
                Favorite.src_user_id == src_user_id,
                Favorite.dest_user_id == dest_user_id,
            )
        )
        self._session.execute(stmt)
        self._session.flush()

    def delete_for_user(self, user_id: str) -> None:
        """Delete all favorites for a user."""
        stmt = delete(Favorite).where(
            or_(Favorite.src_user_id == user_id, Favorite.dest_user_id == user_id)
        )
        self._session.execute(stmt)
        self._session.flush()


class ChallengeRepository:
    """PostgreSQL implementation of ChallengeRepositoryProtocol."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def has_relation(self, src_user_id: str, dest_user_id: str) -> bool:
        """Check if a challenge exists between users."""
        stmt = select(Challenge).where(
            and_(
                Challenge.src_user_id == src_user_id,
                Challenge.dest_user_id == dest_user_id,
            )
        )
        return self._session.execute(stmt).scalars().first() is not None

    def find_relation(
        self, src_user_id: str, dest_user_id: str, key: Optional[str] = None
    ) -> Tuple[bool, Optional[PrefsDict]]:
        """Find a challenge relationship and its preferences."""
        from uuid import UUID as PyUUID

        stmt = select(Challenge).where(
            and_(
                Challenge.src_user_id == src_user_id,
                Challenge.dest_user_id == dest_user_id,
            )
        )
        if key:
            stmt = stmt.where(Challenge.id == PyUUID(key))

        challenge = self._session.execute(stmt).scalars().first()
        if challenge:
            return True, cast(Optional[PrefsDict], challenge.prefs)
        return False, None

    def add_relation(
        self, src_user_id: str, dest_user_id: str, prefs: Optional[PrefsDict] = None
    ) -> None:
        """Add a challenge."""
        challenge = Challenge(
            src_user_id=src_user_id,
            dest_user_id=dest_user_id,
            prefs=prefs,
        )
        self._session.add(challenge)
        self._session.flush()

    def delete_relation(
        self, src_user_id: str, dest_user_id: str, key: Optional[str] = None
    ) -> Tuple[bool, Optional[PrefsDict]]:
        """Delete a challenge and return its preferences."""
        from uuid import UUID as PyUUID

        # First find to get prefs
        found, prefs = self.find_relation(src_user_id, dest_user_id, key)
        if not found:
            return False, None

        stmt = delete(Challenge).where(
            and_(
                Challenge.src_user_id == src_user_id,
                Challenge.dest_user_id == dest_user_id,
            )
        )
        if key:
            stmt = stmt.where(Challenge.id == PyUUID(key))

        self._session.execute(stmt)
        self._session.flush()
        return True, prefs

    def delete_for_user(self, user_id: str) -> None:
        """Delete all challenges for a user."""
        stmt = delete(Challenge).where(
            or_(Challenge.src_user_id == user_id, Challenge.dest_user_id == user_id)
        )
        self._session.execute(stmt)
        self._session.flush()

    def list_issued(self, user_id: str, max_len: int = 20) -> Iterator[ChallengeInfo]:
        """List challenges issued by a user."""
        stmt = (
            select(Challenge)
            .where(Challenge.src_user_id == user_id)
            .order_by(desc(Challenge.timestamp))
            .limit(max_len)
        )
        for c in self._session.execute(stmt).scalars():
            yield ChallengeInfo(
                opp=c.dest_user_id,
                prefs=cast(Optional[PrefsDict], c.prefs),
                ts=c.timestamp,
                key=str(c.id),
            )

    def list_received(self, user_id: str, max_len: int = 20) -> Iterator[ChallengeInfo]:
        """List challenges received by a user."""
        stmt = (
            select(Challenge)
            .where(Challenge.dest_user_id == user_id)
            .order_by(desc(Challenge.timestamp))
            .limit(max_len)
        )
        for c in self._session.execute(stmt).scalars():
            yield ChallengeInfo(
                opp=c.src_user_id,
                prefs=cast(Optional[PrefsDict], c.prefs),
                ts=c.timestamp,
                key=str(c.id),
            )


class ChatRepository:
    """PostgreSQL implementation of ChatRepositoryProtocol."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_conversation(
        self, channel: str, max_len: int = 250
    ) -> Iterator[ChatMessage]:
        """List messages in a conversation channel.

        Note: Read markers (empty messages) are returned but don't count
        toward the max_len limit, matching NDB behavior.
        """
        stmt = (
            select(Chat)
            .where(Chat.channel == channel)
            .order_by(desc(Chat.timestamp))
        )
        count = 0
        for msg in self._session.execute(stmt).scalars():
            yield ChatMessage(
                user=msg.user_id,
                name="",  # NDB also returns empty string for name
                ts=msg.timestamp,
                msg=msg.msg,
            )
            if msg.msg:
                # Don't count read markers (empty messages) toward the limit
                count += 1
                if count >= max_len:
                    break

    def check_conversation(self, channel: str, user_id: str) -> bool:
        """Check if there are unread messages for a user in a channel.

        Returns True if there are unseen messages in the conversation.
        Uses the same algorithm as NDB: looks for messages from other users,
        or read markers (empty messages) from the current user.
        """
        stmt = (
            select(Chat)
            .where(Chat.channel == channel)
            .order_by(desc(Chat.timestamp))
        )
        for msg in self._session.execute(stmt).scalars():
            if msg.user_id != user_id and msg.msg:
                # Found a message from another user
                return True
            if msg.user_id == user_id and not msg.msg:
                # Found a read marker (empty message) from the querying user
                return False
        # Gone through the whole thread without finding an unseen message
        return False

    def add_msg(
        self,
        channel: str,
        from_user: str,
        to_user: Optional[str],
        msg: str,
        timestamp: Optional[datetime] = None,
    ) -> datetime:
        """Add a message to a channel."""
        ts = timestamp or datetime.now(UTC)
        chat = Chat(
            channel=channel,
            user_id=from_user,
            recipient_id=to_user or None,
            msg=msg,
            timestamp=ts,
        )
        self._session.add(chat)
        self._session.flush()
        return ts

    def add_msg_in_game(
        self,
        game_uuid: str,
        from_user: str,
        to_user: Optional[str],
        msg: str,
        timestamp: Optional[datetime] = None,
    ) -> datetime:
        """Add a message in a game channel."""
        channel = f"game:{game_uuid}"
        return self.add_msg(channel, from_user, to_user, msg, timestamp)

    def add_msg_between_users(
        self,
        from_user: str,
        to_user: str,
        msg: str,
        timestamp: Optional[datetime] = None,
    ) -> datetime:
        """Add a direct message between users."""
        # Convention: lower user ID comes first in channel name
        if from_user < to_user:
            channel = f"user:{from_user}:{to_user}"
        else:
            channel = f"user:{to_user}:{from_user}"
        return self.add_msg(channel, from_user, to_user, msg, timestamp)

    def chat_history(
        self, for_user: str, max_len: int = 20, blocked_users: Optional[Set[str]] = None
    ) -> Sequence[ChatHistoryEntry]:
        """Get the chat history (newest message per counterparty) for a user,
        excluding blocked counterparties. Faithfully mirrors NDB
        ChatModel.chat_history, including read-marker (empty-message) handling:
        an empty message is a 'read marker' that marks a conversation as read
        without itself showing as a history entry."""
        blocked = blocked_users or set()
        # Going far back is expensive; cap the scan per direction (matches NDB)
        HISTORY_LIMIT = 500

        # Messages where this user is the originator, newest first
        q_sent = (
            select(Chat)
            .where(Chat.user_id == for_user)
            .order_by(desc(Chat.timestamp))
            .limit(HISTORY_LIMIT)
        )
        # Messages where this user is the recipient, newest first
        q_recv = (
            select(Chat)
            .where(Chat.recipient_id == for_user)
            .order_by(desc(Chat.timestamp))
            .limit(HISTORY_LIMIT)
        )
        sent = list(self._session.execute(q_sent).scalars())
        recv = list(self._session.execute(q_recv).scalars())
        # Merge both streams newest-first
        merged = sorted(sent + recv, key=lambda c: c.timestamp, reverse=True)

        result: Dict[str, ChatHistoryEntry] = {}

        def consider(cm: Chat, counterparty: str) -> int:
            """Maybe add/upgrade a history entry for `counterparty`. Returns 1
            if a proper (non-empty) entry was added, else 0."""
            ch = result.get(counterparty)
            if ch is None:
                if counterparty in blocked:
                    # Don't include blocked counterparties
                    return 0
                result[counterparty] = ChatHistoryEntry(
                    user=counterparty,
                    ts=cm.timestamp,
                    last_msg=cm.msg,
                    # Messages originated by this user are never unread
                    unread=cm.user_id != for_user,
                )
                # An empty message is a read marker: don't count it yet
                return 1 if cm.msg else 0
            # Already seen this counterparty. Only act if the stored entry is a
            # read marker (empty) and this older message is a real message.
            if not ch.last_msg and cm.msg:
                ch.last_msg = cm.msg
                ch.ts = cm.timestamp
                # A newer read marker existed, so the conversation is read
                ch.unread = False
                return 1
            return 0

        count = 0
        for cm in merged:
            if count >= max_len:
                break
            if cm.user_id == for_user:
                # This user is the originator; counterparty is the recipient
                if cm.recipient_id is not None:
                    count += consider(cm, cm.recipient_id)
            else:
                # This user is the recipient; counterparty is the originator
                count += consider(cm, cm.user_id)

        # Keep only entries that have an actual message, newest first
        rlist = [r for r in result.values() if r.last_msg]
        rlist.sort(key=lambda r: r.ts, reverse=True)
        return rlist


class BlockRepository:
    """PostgreSQL implementation of BlockRepositoryProtocol."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_blocked_users(self, user_id: str, max_len: int = 100) -> Iterator[str]:
        """List users blocked by a user."""
        stmt = (
            select(Block.blocked_id)
            .where(Block.blocker_id == user_id)
            .limit(max_len)
        )
        for row in self._session.execute(stmt):
            yield row[0]

    def list_blocked_by(self, user_id: str, max_len: int = 100) -> Iterator[str]:
        """List users who have blocked a user."""
        stmt = (
            select(Block.blocker_id)
            .where(Block.blocked_id == user_id)
            .limit(max_len)
        )
        for row in self._session.execute(stmt):
            yield row[0]

    def block_user(self, blocker_id: str, blocked_id: str) -> bool:
        """Block a user. Returns True if newly blocked."""
        if self.is_blocking(blocker_id, blocked_id):
            return False
        block = Block(blocker_id=blocker_id, blocked_id=blocked_id)
        self._session.add(block)
        self._session.flush()
        return True

    def unblock_user(self, blocker_id: str, blocked_id: str) -> bool:
        """Unblock a user. Returns True if was blocked."""
        if not self.is_blocking(blocker_id, blocked_id):
            return False
        stmt = delete(Block).where(
            and_(Block.blocker_id == blocker_id, Block.blocked_id == blocked_id)
        )
        self._session.execute(stmt)
        self._session.flush()
        return True

    def is_blocking(self, blocker_id: str, blocked_id: str) -> bool:
        """Check if one user is blocking another."""
        block = self._session.get(Block, (blocker_id, blocked_id))
        return block is not None


class ZombieRepository:
    """PostgreSQL implementation of ZombieRepositoryProtocol."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_game(self, game_id: str, user_id: str) -> None:
        """Mark a game as zombie for a user."""
        zombie = Zombie(game_id=game_id, user_id=user_id)
        self._session.merge(zombie)
        self._session.flush()

    def delete_game(self, game_id: str, user_id: str) -> None:
        """Remove zombie marking for a game/user."""
        stmt = delete(Zombie).where(
            and_(Zombie.game_id == game_id, Zombie.user_id == user_id)
        )
        self._session.execute(stmt)
        self._session.flush()

    def delete_for_user(self, user_id: str) -> None:
        """Delete all zombie entries for a user."""
        stmt = delete(Zombie).where(Zombie.user_id == user_id)
        self._session.execute(stmt)
        self._session.flush()

    def list_games(self, user_id: str) -> Iterator[ZombieGameInfo]:
        """List zombie games for a user."""
        stmt = (
            select(Zombie, Game)
            .join(Game, Zombie.game_id == Game.id)
            .where(Zombie.user_id == user_id)
        )
        for zombie, game in self._session.execute(stmt):
            # Determine opponent and orient scores to the querying user
            # (sc0 = user's score), with last-move time and locale fallback.
            # Matches NDB ZombieModel.list_games.
            if game.player0_id == user_id:
                opp = game.player1_id
                sc0, sc1 = game.score0, game.score1
            else:
                opp = game.player0_id
                sc0, sc1 = game.score1, game.score0
            prefs = cast(Optional[PrefsDict], game.prefs)
            locale = game.locale or (prefs or {}).get("locale") or DEFAULT_LOCALE
            yield ZombieGameInfo(
                uuid=game.id,
                ts=game.ts_last_move or game.timestamp,
                opp=opp,
                robot_level=game.robot_level,
                sc0=sc0,
                sc1=sc1,
                locale=locale,
            )


class RatingRepository:
    """PostgreSQL implementation of RatingRepositoryProtocol."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_or_create(self, kind: str, rank: int) -> Rating:
        """Get or create a rating entry."""
        rating = self._session.get(Rating, (kind, rank))
        if rating is None:
            rating = Rating(kind=kind, rank=rank)
            self._session.add(rating)
            self._session.flush()
        return rating

    def list_rating(self, kind: str) -> Iterator[RatingInfo]:
        """List the top ratings of a kind, ascending by rank, capped at 100
        (matches NDB RatingModel.list_rating)."""
        stmt = (
            select(Rating)
            .where(Rating.kind == kind)
            .order_by(Rating.rank)
            .limit(100)
        )
        for r in self._session.execute(stmt).scalars():
            # Encode the user id the way clients expect: a real user id, else
            # "robot-N" for a robot (robot_level >= 0), else "" (matches NDB).
            if r.user_id is None:
                userid = "" if r.robot_level < 0 else f"robot-{r.robot_level}"
            else:
                userid = r.user_id
            yield RatingInfo(
                rank=r.rank,
                userid=userid,
                robot_level=r.robot_level,
                games=r.games,
                elo=r.elo,
                score=r.score,
                score_against=r.score_against,
                wins=r.wins,
                losses=r.losses,
                rank_yesterday=r.rank_yesterday,
                games_yesterday=r.games_yesterday,
                elo_yesterday=r.elo_yesterday,
                score_yesterday=r.score_yesterday,
                score_against_yesterday=r.score_against_yesterday,
                wins_yesterday=r.wins_yesterday,
                losses_yesterday=r.losses_yesterday,
                rank_week_ago=r.rank_week_ago,
                games_week_ago=r.games_week_ago,
                elo_week_ago=r.elo_week_ago,
                score_week_ago=r.score_week_ago,
                score_against_week_ago=r.score_against_week_ago,
                wins_week_ago=r.wins_week_ago,
                losses_week_ago=r.losses_week_ago,
                rank_month_ago=r.rank_month_ago,
                games_month_ago=r.games_month_ago,
                elo_month_ago=r.elo_month_ago,
                score_month_ago=r.score_month_ago,
                score_against_month_ago=r.score_against_month_ago,
                wins_month_ago=r.wins_month_ago,
                losses_month_ago=r.losses_month_ago,
            )

    def delete_all(self) -> None:
        """Delete all rating entries."""
        stmt = delete(Rating)
        self._session.execute(stmt)
        self._session.flush()


class RatingArchiveRepository:
    """PostgreSQL implementation of RatingArchiveRepositoryProtocol."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def put_archive(self, kind: str, key_date: str, table_json: str) -> None:
        """Store or overwrite the archived table for a kind and ISO date."""
        ra = self._session.get(RatingArchive, (kind, key_date))
        if ra is None:
            ra = RatingArchive(kind=kind, key_date=key_date, table_json=table_json)
            self._session.add(ra)
        else:
            ra.table_json = table_json
            ra.timestamp = datetime.now(UTC)
        self._session.flush()

    def get_archive(self, kind: str, key_date: str) -> Optional[str]:
        """Fetch the archived table for a kind and ISO date, or None."""
        ra = self._session.get(RatingArchive, (kind, key_date))
        return None if ra is None else ra.table_json

    def delete_archive(self, kind: str, key_date: str) -> None:
        """Delete the archived table for a kind and ISO date, if present."""
        ra = self._session.get(RatingArchive, (kind, key_date))
        if ra is not None:
            self._session.delete(ra)
            self._session.flush()


class RiddleRepository:
    """PostgreSQL implementation of RiddleRepositoryProtocol."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_riddle(self, date_str: str, locale: str) -> Optional[Riddle]:
        """Get a riddle by date and locale."""
        return self._session.get(Riddle, (date_str, locale))

    def get_riddles_for_date(self, date_str: str) -> Sequence[Riddle]:
        """Get all riddles for a date."""
        stmt = select(Riddle).where(Riddle.date == date_str)
        return list(self._session.execute(stmt).scalars())

    def save_riddle(
        self, date_str: str, locale: str, riddle_json: str, version: int = 1
    ) -> Riddle:
        """Save a riddle."""
        riddle = self._session.get(Riddle, (date_str, locale))
        if riddle is None:
            riddle = Riddle(date=date_str, locale=locale)
            self._session.add(riddle)
        riddle.riddle_json = riddle_json
        riddle.version = version
        riddle.created = datetime.now(UTC)
        self._session.flush()
        return riddle


class ImageRepository:
    """PostgreSQL implementation of ImageRepositoryProtocol."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_thumbnail(self, user_id: str, size: int = 384) -> Optional[bytes]:
        """Get a user's thumbnail image."""
        fmt = f"thumb{size}"
        stmt = select(Image).where(
            and_(Image.user_id == user_id, Image.fmt == fmt)
        )
        img = self._session.execute(stmt).scalar_one_or_none()
        return img.image if img else None

    def set_thumbnail(self, user_id: str, image: bytes, size: int = 384) -> None:
        """Set a user's thumbnail image."""
        fmt = f"thumb{size}"
        stmt = select(Image).where(
            and_(Image.user_id == user_id, Image.fmt == fmt)
        )
        img = self._session.execute(stmt).scalar_one_or_none()
        if img:
            img.image = image
        else:
            img = Image(user_id=user_id, fmt=fmt, image=image)
            self._session.add(img)
        self._session.flush()


class ReportRepository:
    """PostgreSQL implementation of ReportRepositoryProtocol."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def report_user(
        self, reporter_id: str, reported_id: str, code: int, text: str
    ) -> bool:
        """Report a user. Returns True if successful, False if either id is
        empty or the reported user does not exist (matches the NDB backend,
        see ReportModel.report_user in skrafldb_ndb.py)."""
        if not reporter_id or not reported_id:
            return False
        # The reported user must exist
        if self._session.get(User, reported_id) is None:
            return False
        report = Report(
            reporter_id=reporter_id,
            reported_id=reported_id,
            code=code,
            text=text,
        )
        self._session.add(report)
        self._session.flush()
        return True

    def list_reported_by(self, user_id: str, max_len: int = 100) -> Iterator[str]:
        """List users who have reported the given user."""
        stmt = (
            select(Report.reporter_id)
            .where(Report.reported_id == user_id)
            .distinct()
            .limit(max_len)
        )
        for row in self._session.execute(stmt):
            yield row[0]


class PromoRepository:
    """PostgreSQL implementation of PromoRepositoryProtocol."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_promotion(self, user_id: str, promotion: str) -> None:
        """Record that a user has seen a promotion."""
        promo = Promo(user_id=user_id, promotion=promotion)
        self._session.add(promo)
        self._session.flush()

    def list_promotions(self, user_id: str, promotion: str) -> Iterator[datetime]:
        """List when a user has seen a promotion."""
        stmt = (
            select(Promo.timestamp)
            .where(and_(Promo.user_id == user_id, Promo.promotion == promotion))
            .order_by(Promo.timestamp)
        )
        for row in self._session.execute(stmt):
            yield row[0]


class TransactionRepository:
    """PostgreSQL implementation of TransactionRepositoryProtocol."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_transaction(self, user_id: str, plan: str, kind: str, op: str) -> None:
        """Log a transaction."""
        txn = Transaction(user_id=user_id, plan=plan, kind=kind, op=op)
        self._session.add(txn)
        self._session.flush()

    def count_for_user(self, user_id: str) -> int:
        """Count transactions for a user."""
        stmt = select(func.count()).select_from(Transaction).where(
            Transaction.user_id == user_id
        )
        return self._session.execute(stmt).scalar() or 0


class SubmissionRepository:
    """PostgreSQL implementation of SubmissionRepositoryProtocol."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def submit_word(
        self, user_id: str, locale: str, word: str, comment: str
    ) -> None:
        """Submit a word for review."""
        sub = Submission(user_id=user_id, locale=locale, word=word, comment=comment)
        self._session.add(sub)
        self._session.flush()

    def count_for_user(self, user_id: str) -> int:
        """Count submissions for a user."""
        stmt = select(func.count()).select_from(Submission).where(
            Submission.user_id == user_id
        )
        return self._session.execute(stmt).scalar() or 0


class CompletionRepository:
    """PostgreSQL implementation of CompletionRepositoryProtocol."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_completion(
        self, proctype: str, ts_from: datetime, ts_to: datetime
    ) -> None:
        """Log a successful completion."""
        comp = Completion(
            proctype=proctype,
            ts_from=ts_from,
            ts_to=ts_to,
            success=True,
        )
        self._session.add(comp)
        self._session.flush()

    def add_failure(
        self, proctype: str, ts_from: datetime, ts_to: datetime, reason: str
    ) -> None:
        """Log a failed completion."""
        comp = Completion(
            proctype=proctype,
            ts_from=ts_from,
            ts_to=ts_to,
            success=False,
            reason=reason,
        )
        self._session.add(comp)
        self._session.flush()

    def count_for_proctype(self, proctype: str) -> int:
        """Count completions for a process type."""
        stmt = select(func.count()).select_from(Completion).where(
            Completion.proctype == proctype
        )
        return self._session.execute(stmt).scalar() or 0


class RobotRepository:
    """PostgreSQL implementation of RobotRepositoryProtocol."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_elo(self, locale: str, level: int) -> Optional[int]:
        """Get the Elo rating for a robot at a level."""
        # Reject invalid keys up front (matches NDB robot_elo)
        if not locale or level < 0:
            return None
        robot = self._session.get(Robot, (locale, level))
        return robot.elo if robot else None

    def upsert_elo(self, locale: str, level: int, elo: int) -> bool:
        """Create or update robot Elo. Returns True if successful."""
        # A robot Elo entry requires a non-empty locale (matches NDB, which
        # asserts locale; we return False rather than raise)
        if not locale or level < 0:
            return False
        robot = self._session.get(Robot, (locale, level))
        if robot:
            robot.elo = elo
        else:
            robot = Robot(locale=locale, level=level, elo=elo)
            self._session.add(robot)
        self._session.flush()
        return True


# =============================================================================
# Query Wrapper
# =============================================================================

T = TypeVar("T")


class PostgreSQLQueryWrapper(Generic[T]):
    """Wrapper to provide QueryProtocol interface for SQLAlchemy queries.

    Returns ORM model instances directly (they satisfy the entity protocols).
    """

    def __init__(
        self,
        session: Session,
        model_class: Type[T],
    ) -> None:
        self._session = session
        self._model_class = model_class
        self._stmt = select(model_class)

    def filter(self, *conditions: Any) -> "PostgreSQLQueryWrapper[T]":
        """Add filter conditions to the query."""
        wrapper: PostgreSQLQueryWrapper[T] = PostgreSQLQueryWrapper(
            self._session, self._model_class
        )
        wrapper._stmt = self._stmt.where(*conditions)
        return wrapper

    def order(self, *columns: Any) -> "PostgreSQLQueryWrapper[T]":
        """Add ordering to the query."""
        wrapper: PostgreSQLQueryWrapper[T] = PostgreSQLQueryWrapper(
            self._session, self._model_class
        )
        wrapper._stmt = self._stmt.order_by(*columns)
        return wrapper

    def fetch(self, limit: Optional[int] = None) -> List[T]:
        """Execute the query and return results."""
        stmt = self._stmt
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self._session.execute(stmt).scalars())

    def get(self) -> Optional[T]:
        """Execute the query and return the first result."""
        stmt = self._stmt.limit(1)
        return self._session.execute(stmt).scalar_one_or_none()

    def count(self) -> int:
        """Return the count of matching entities."""
        # Extract the WHERE clause and apply to count
        count_stmt = select(func.count()).select_from(self._model_class)
        # This is simplified - full implementation would need to copy filters
        return self._session.execute(count_stmt).scalar_one()

    def iter(self, limit: int = 0) -> Iterator[T]:
        """Iterate over query results."""
        stmt = self._stmt
        if limit > 0:
            stmt = stmt.limit(limit)
        yield from self._session.execute(stmt).scalars()
