"""
Repository implementations for NDB backend.

These classes implement the repository protocols by wrapping
the class methods of the existing NDB models.
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Optional,
    List,
    Dict,
    Iterator,
    Sequence,
    Set,
    Tuple,
    Any,
    cast,
)
from datetime import datetime

# Import the NDB models directly from skrafldb_ndb to avoid circular
# imports when DATABASE_BACKEND=postgresql (skrafldb would try to
# import skrafldb_pg which doesn't need NDB)
import skrafldb_ndb as skrafldb

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

from .entities import (
    UserEntity,
    GameEntity,
    EloEntity,
    StatsEntity,
    RiddleEntity,
)

if TYPE_CHECKING:
    from ..protocols import (
        UserEntityProtocol,
        GameEntityProtocol,
        EloEntityProtocol,
        QueryProtocol,
    )


class UserRepository:
    """NDB implementation of UserRepositoryProtocol."""

    def get_by_id(self, user_id: str) -> Optional[UserEntity]:
        """Fetch a user by their ID."""
        model = skrafldb.UserModel.fetch(user_id)
        return UserEntity(model) if model else None

    def get_by_account(self, account: str) -> Optional[UserEntity]:
        """Fetch a user by their OAuth2 account identifier."""
        model = skrafldb.UserModel.fetch_account(account)
        return UserEntity(model) if model else None

    def get_by_nickname(
        self, nickname: str, ignore_case: bool = False
    ) -> Optional[UserEntity]:
        """Fetch a user by their nickname."""
        model = skrafldb.UserModel.fetch_nickname(nickname, ignore_case)
        return UserEntity(model) if model else None

    def get_by_email(self, email: str) -> Optional[UserEntity]:
        """Fetch a user by their email address."""
        model = skrafldb.UserModel.fetch_email(email)
        return UserEntity(model) if model else None

    def get_multi(self, user_ids: List[str]) -> List[Optional[UserEntity]]:
        """Fetch multiple users by their IDs."""
        models = skrafldb.UserModel.fetch_multi(user_ids)
        return [UserEntity(m) if m else None for m in models]

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
        result = skrafldb.UserModel.create(
            user_id=user_id,
            account=account,
            email=email or "",
            nickname=nickname,
            image=image or "",
            preferences=cast(Any, preferences),
            locale=locale,
        )
        # Cast the PrefsDict from skrafldb's TypedDict to our Dict[str, Any]
        return result[0], cast(PrefsDict, result[1])

    def update(self, user: "UserEntityProtocol", **kwargs: Any) -> None:
        """Update a user's attributes."""
        # Get the underlying NDB model
        if not isinstance(user, UserEntity):
            raise TypeError("Expected UserEntity from NDB backend")
        model = user._ndb_model

        # Update fields
        for key, value in kwargs.items():
            if hasattr(model, key):
                setattr(model, key, value)
            else:
                raise AttributeError(f"UserModel has no attribute '{key}'")

        # Special handling for nick_lc when nickname changes
        if "nickname" in kwargs:
            model.nick_lc = kwargs["nickname"].lower()

        # Special handling for name_lc when prefs changes
        if "prefs" in kwargs:
            prefs = kwargs["prefs"]
            if isinstance(prefs, dict) and "full_name" in prefs:
                model.name_lc = prefs["full_name"].lower()

        model.put()

    def delete(self, user_id: str) -> None:
        """Delete a user and their related entities."""
        skrafldb.UserModel.delete(user_id)

    def count(self) -> int:
        """Return the total number of users."""
        return skrafldb.UserModel.count()

    def list_prefix(
        self, prefix: str, max_len: int = 50, locale: Optional[str] = None
    ) -> Iterator[UserPrefixInfo]:
        """List users whose nicknames start with the given prefix."""
        for item in skrafldb.UserModel.list_prefix(prefix, max_len, locale):
            yield UserPrefixInfo(
                id=item["id"],
                nickname=item["nickname"],
                prefs=cast(PrefsDict, item["prefs"]),
                timestamp=item["timestamp"],
                ready=item.get("ready") or False,
                ready_timed=item.get("ready_timed") or False,
                elo=item["elo"],
                human_elo=item["human_elo"],
                manual_elo=item["manual_elo"],
                image=item.get("image"),
                has_image_blob=item["has_image_blob"],
            )

    def list_similar_elo(
        self, elo: int, max_len: int = 40, locale: Optional[str] = None
    ) -> List[Tuple[str, EloDict]]:
        """List users with similar Elo ratings."""
        result = skrafldb.UserModel.list_similar_elo(elo, max_len, locale)
        return [(uid, EloDict(e.elo, e.human_elo, e.manual_elo)) for uid, e in result]

    def query(self) -> "QueryProtocol[UserEntity]":
        """Return a query object for users."""
        # Return a wrapper that converts NDB query results to UserEntity
        return NDBQueryWrapper(skrafldb.UserModel.query(), UserEntity)


class GameRepository:
    """NDB implementation of GameRepositoryProtocol."""

    def get_by_id(self, game_id: str) -> Optional[GameEntity]:
        """Fetch a game by its UUID."""
        model = skrafldb.GameModel.fetch(game_id)
        return GameEntity(model) if model else None

    def create(self, **kwargs: Any) -> GameEntity:
        """Create a new game."""
        # Extract known fields
        game_id = kwargs.pop("id", None) or skrafldb.Unique.id()

        model = skrafldb.GameModel(id=game_id)

        # Set player references
        if "player0_id" in kwargs:
            model.set_player(0, kwargs.pop("player0_id"))
        if "player1_id" in kwargs:
            model.set_player(1, kwargs.pop("player1_id"))

        # Set other fields
        for key, value in kwargs.items():
            if hasattr(model, key):
                setattr(model, key, value)

        model.put()
        return GameEntity(model)

    def update(self, game: "GameEntityProtocol", **kwargs: Any) -> None:
        """Update a game's attributes."""
        if not isinstance(game, GameEntity):
            raise TypeError("Expected GameEntity from NDB backend")
        model = game._ndb_model

        # Handle player ID updates specially
        if "player0_id" in kwargs:
            model.set_player(0, kwargs.pop("player0_id"))
        if "player1_id" in kwargs:
            model.set_player(1, kwargs.pop("player1_id"))

        for key, value in kwargs.items():
            if hasattr(model, key):
                setattr(model, key, value)

        model.put()

    def delete(self, game_id: str) -> None:
        """Delete a game."""
        model = skrafldb.GameModel.fetch(game_id)
        if model:
            model.key.delete()

    def list_finished_games(
        self, user_id: str, versus: Optional[str] = None, max_len: int = 10
    ) -> List[FinishedGameInfo]:
        """List finished games for a user."""
        results = skrafldb.GameModel.list_finished_games(user_id, versus, max_len)
        return [
            FinishedGameInfo(
                uuid=r["uuid"],
                ts=r["ts"],
                ts_last_move=r.get("ts_last_move"),
                opp=r.get("opp"),
                robot_level=r["robot_level"],
                sc0=r["sc0"],
                sc1=r["sc1"],
                elo_adj=r.get("elo_adj") or 0,
                human_elo_adj=r.get("human_elo_adj") or 0,
                manual_elo_adj=r.get("manual_elo_adj") or 0,
                prefs=cast(Optional[PrefsDict], r.get("prefs")),
                locale=r.get("locale"),
            )
            for r in results
        ]

    def iter_live_games(
        self, user_id: str, max_len: int = 10
    ) -> Iterator[LiveGameInfo]:
        """Iterate over live (active) games for a user."""
        for r in skrafldb.GameModel.iter_live_games(user_id, max_len):
            yield LiveGameInfo(
                uuid=r["uuid"],
                ts=r["ts"],
                opp=r.get("opp"),
                robot_level=r["robot_level"],
                my_turn=r["my_turn"],
                sc0=r["sc0"],
                sc1=r["sc1"],
                prefs=cast(Optional[PrefsDict], r.get("prefs")),
                tile_count=r["tile_count"],
                locale=r.get("locale") or "",
            )

    def delete_for_user(self, user_id: str) -> None:
        """Delete all games for a user."""
        skrafldb.GameModel.delete_for_user(user_id)

    def query(self) -> "QueryProtocol[GameEntity]":
        """Return a query object for games."""
        return NDBQueryWrapper(skrafldb.GameModel.query(), GameEntity)


class EloRepository:
    """NDB implementation of EloRepositoryProtocol."""

    def get_for_user(self, locale: str, user_id: str) -> Optional[EloEntity]:
        """Get Elo ratings for a user in a specific locale."""
        model = skrafldb.EloModel.user_elo(locale, user_id)
        return EloEntity(model) if model else None

    def create(
        self, locale: str, user_id: str, ratings: EloDict
    ) -> Optional[EloEntity]:
        """Create Elo ratings for a user in a locale."""
        ndb_ratings = skrafldb.EloDict(
            elo=ratings.elo,
            human_elo=ratings.human_elo,
            manual_elo=ratings.manual_elo,
        )
        model = skrafldb.EloModel.create(locale, user_id, ndb_ratings)
        if model is None:
            return None
        # EloModel.create() returns an entity but doesn't persist it
        # We need to call put() to save it to NDB
        model.put()
        return EloEntity(model)

    def upsert(
        self,
        existing: Optional["EloEntityProtocol"],
        locale: str,
        user_id: str,
        ratings: EloDict,
    ) -> bool:
        """Create or update Elo ratings."""
        ndb_model = None
        if existing is not None:
            if not isinstance(existing, EloEntity):
                raise TypeError("Expected EloEntity from NDB backend")
            ndb_model = existing._ndb_model

        ndb_ratings = skrafldb.EloDict(
            elo=ratings.elo,
            human_elo=ratings.human_elo,
            manual_elo=ratings.manual_elo,
        )
        return skrafldb.EloModel.upsert(ndb_model, locale, user_id, ndb_ratings)

    def delete_for_user(self, user_id: str) -> None:
        """Delete all Elo ratings for a user."""
        skrafldb.EloModel.delete_for_user(user_id)

    def list_rating(
        self, kind: str, locale: str, limit: int = 100
    ) -> Iterator[RatingForLocale]:
        """List ratings by kind (human, manual, all) for a locale."""
        for r in skrafldb.EloModel.list_rating(kind, locale, limit=limit):
            yield RatingForLocale(
                rank=r["rank"],
                userid=r["userid"],
                elo=r["elo"],
            )

    def list_similar(
        self, locale: str, elo: int, max_len: int = 40
    ) -> Iterator[Tuple[str, EloDict]]:
        """List users with similar Elo in a locale."""
        for uid, e in skrafldb.EloModel.list_similar(locale, elo, max_len):
            yield uid, EloDict(e.elo, e.human_elo, e.manual_elo)

    def load_multi(self, locale: str, user_ids: List[str]) -> Dict[str, EloDict]:
        """Load Elo ratings for multiple users."""
        result = skrafldb.EloModel.load_multi(locale, user_ids)
        return {
            uid: EloDict(e.elo, e.human_elo, e.manual_elo) for uid, e in result.items()
        }


class StatsRepository:
    """NDB implementation of StatsRepositoryProtocol."""

    def create(
        self, user_id: Optional[str] = None, robot_level: int = 0
    ) -> StatsEntity:
        """Create a new stats entry."""
        model = skrafldb.StatsModel.create(user_id, robot_level)
        # StatsModel.create() returns an entity but doesn't persist it
        # We need to call put() to save it to NDB
        model.put()
        return StatsEntity(model)

    def newest_for_user(self, user_id: str) -> Optional[StatsEntity]:
        """Get the most recent stats for a user."""
        model = skrafldb.StatsModel.newest_for_user(user_id)
        # NDB's newest_for_user creates a new (unpersisted) entity if none exists.
        # Check if the model has a key to determine if it was actually found in DB.
        if model is None or model.key is None:
            return None
        return StatsEntity(model)

    def newest_before(
        self, ts: datetime, user_id: str, robot_level: int = 0
    ) -> StatsEntity:
        """Get the most recent stats before a timestamp."""
        model = skrafldb.StatsModel.newest_before(ts, user_id, robot_level)
        return StatsEntity(model)

    def last_for_user(self, user_id: str, days: int) -> List[StatsEntity]:
        """Get stats entries for a user over the last N days."""
        models = skrafldb.StatsModel.last_for_user(user_id, days)
        return [StatsEntity(m) for m in models]

    def list_elo(
        self, timestamp: Optional[datetime] = None, max_len: int = 100
    ) -> Tuple[List[StatsInfo], Optional[datetime]]:
        """List stats ordered by Elo."""
        results = skrafldb.StatsModel.list_elo(timestamp, max_len)
        return self._convert_stats_results(results)

    def list_human_elo(
        self, timestamp: Optional[datetime] = None, max_len: int = 100
    ) -> Tuple[List[StatsInfo], Optional[datetime]]:
        """List stats ordered by human Elo."""
        results = skrafldb.StatsModel.list_human_elo(timestamp, max_len)
        return self._convert_stats_results(results)

    def list_manual_elo(
        self, timestamp: Optional[datetime] = None, max_len: int = 100
    ) -> Tuple[List[StatsInfo], Optional[datetime]]:
        """List stats ordered by manual Elo."""
        results = skrafldb.StatsModel.list_manual_elo(timestamp, max_len)
        return self._convert_stats_results(results)

    def _convert_stats_results(
        self, results: Sequence[Any]
    ) -> Tuple[List[StatsInfo], Optional[datetime]]:
        """Convert NDB stats results to StatsInfo list."""
        stats = [
            StatsInfo(
                user=r.get("user"),
                robot_level=r["robot_level"],
                timestamp=r["timestamp"],
                games=r["games"],
                elo=r["elo"],
                score=r["score"],
                score_against=r["score_against"],
                wins=r["wins"],
                losses=r["losses"],
                rank=r["rank"],
            )
            for r in results
        ]
        # The NDB implementation doesn't return a timestamp, so we return None
        return stats, None

    def delete_for_user(self, user_id: str) -> None:
        """Delete all stats for a user."""
        skrafldb.StatsModel.delete_user(user_id)

    def delete_at_timestamp(self, timestamp: datetime) -> None:
        """Delete stats at a specific timestamp."""
        skrafldb.StatsModel.delete_ts(timestamp)


class FavoriteRepository:
    """NDB implementation of FavoriteRepositoryProtocol."""

    def list_favorites(self, user_id: str, max_len: int = 100) -> Iterator[str]:
        """List favorite user IDs for a user."""
        return skrafldb.FavoriteModel.list_favorites(user_id, max_len)

    def has_relation(self, src_user_id: str, dest_user_id: str) -> bool:
        """Check if a favorite relationship exists."""
        return skrafldb.FavoriteModel.has_relation(src_user_id, dest_user_id)

    def add_relation(self, src_user_id: str, dest_user_id: str) -> None:
        """Add a favorite relationship."""
        skrafldb.FavoriteModel.add_relation(src_user_id, dest_user_id)

    def delete_relation(self, src_user_id: str, dest_user_id: str) -> None:
        """Delete a favorite relationship."""
        skrafldb.FavoriteModel.del_relation(src_user_id, dest_user_id)

    def delete_for_user(self, user_id: str) -> None:
        """Delete all favorites for a user."""
        skrafldb.FavoriteModel.delete_user(user_id)


class ChallengeRepository:
    """NDB implementation of ChallengeRepositoryProtocol."""

    def has_relation(self, src_user_id: str, dest_user_id: str) -> bool:
        """Check if a challenge exists between users."""
        return skrafldb.ChallengeModel.has_relation(src_user_id, dest_user_id)

    def find_relation(
        self, src_user_id: str, dest_user_id: str, key: Optional[str] = None
    ) -> Tuple[bool, Optional[PrefsDict]]:
        """Find a challenge relationship and its preferences."""
        found, prefs = skrafldb.ChallengeModel.find_relation(
            src_user_id, dest_user_id, key
        )
        return found, cast(Optional[PrefsDict], prefs)

    def add_relation(
        self, src_user_id: str, dest_user_id: str, prefs: Optional[PrefsDict] = None
    ) -> None:
        """Add a challenge."""
        skrafldb.ChallengeModel.add_relation(
            src_user_id, dest_user_id, cast(Any, prefs)
        )

    def delete_relation(
        self, src_user_id: str, dest_user_id: str, key: Optional[str] = None
    ) -> Tuple[bool, Optional[PrefsDict]]:
        """Delete a challenge and return its preferences."""
        found, prefs = skrafldb.ChallengeModel.del_relation(
            src_user_id, dest_user_id, key
        )
        return found, cast(Optional[PrefsDict], prefs)

    def delete_for_user(self, user_id: str) -> None:
        """Delete all challenges for a user."""
        skrafldb.ChallengeModel.delete_user(user_id)

    def list_issued(self, user_id: str, max_len: int = 20) -> Iterator[ChallengeInfo]:
        """List challenges issued by a user."""
        for c in skrafldb.ChallengeModel.list_issued(user_id, max_len):
            yield ChallengeInfo(
                opp=c.opp,
                prefs=cast(Optional[PrefsDict], c.prefs),
                ts=c.ts,
                key=c.key,
            )

    def list_received(self, user_id: str, max_len: int = 20) -> Iterator[ChallengeInfo]:
        """List challenges received by a user."""
        for c in skrafldb.ChallengeModel.list_received(user_id, max_len):
            yield ChallengeInfo(
                opp=c.opp,
                prefs=cast(Optional[PrefsDict], c.prefs),
                ts=c.ts,
                key=c.key,
            )


class ChatRepository:
    """NDB implementation of ChatRepositoryProtocol."""

    def list_conversation(
        self, channel: str, max_len: int = 250
    ) -> Iterator[ChatMessage]:
        """List messages in a conversation channel."""
        for msg in skrafldb.ChatModel.list_conversation(channel, max_len):
            yield ChatMessage(
                user=msg["user"],
                name=msg.get("name", ""),
                ts=msg["ts"],
                msg=msg["msg"],
            )

    def check_conversation(self, channel: str, user_id: str) -> bool:
        """Check if there are unread messages for a user in a channel."""
        return skrafldb.ChatModel.check_conversation(channel, user_id)

    def add_msg(
        self,
        channel: str,
        from_user: str,
        to_user: Optional[str],
        msg: str,
        timestamp: Optional[datetime] = None,
    ) -> datetime:
        """Add a message to a channel."""
        # skrafldb requires to_user as str, use empty string if None
        return skrafldb.ChatModel.add_msg(
            channel, from_user, to_user or "", msg, timestamp
        )

    def add_msg_in_game(
        self,
        game_uuid: str,
        from_user: str,
        to_user: Optional[str],
        msg: str,
        timestamp: Optional[datetime] = None,
    ) -> datetime:
        """Add a message in a game channel."""
        # skrafldb requires to_user as str, use empty string if None
        return skrafldb.ChatModel.add_msg_in_game(
            game_uuid, from_user, to_user or "", msg, timestamp
        )

    def add_msg_between_users(
        self,
        from_user: str,
        to_user: str,
        msg: str,
        timestamp: Optional[datetime] = None,
    ) -> datetime:
        """Add a direct message between users."""
        return skrafldb.ChatModel.add_msg_between_users(
            from_user, to_user, msg, timestamp
        )

    def chat_history(
        self, for_user: str, max_len: int = 20, blocked_users: Optional[Set[str]] = None
    ) -> Sequence[ChatHistoryEntry]:
        """Get chat history for a user."""
        # skrafldb.ChatModel.chat_history uses keyword-only args after for_user
        results = skrafldb.ChatModel.chat_history(
            for_user, maxlen=max_len, blocked_users=blocked_users or set()
        )
        return [
            ChatHistoryEntry(
                user=r["user"],
                ts=r["ts"],
                last_msg=r["last_msg"],
                unread=r["unread"],
            )
            for r in results
        ]


class BlockRepository:
    """NDB implementation of BlockRepositoryProtocol."""

    def list_blocked_users(self, user_id: str, max_len: int = 100) -> Iterator[str]:
        """List users blocked by a user."""
        return skrafldb.BlockModel.list_blocked_users(user_id, max_len)

    def list_blocked_by(self, user_id: str, max_len: int = 100) -> Iterator[str]:
        """List users who have blocked a user."""
        return skrafldb.BlockModel.list_blocked_by(user_id, max_len)

    def block_user(self, blocker_id: str, blocked_id: str) -> bool:
        """Block a user. Returns True if newly blocked."""
        # Check if already blocked to return correct value
        if self.is_blocking(blocker_id, blocked_id):
            return False
        return skrafldb.BlockModel.block_user(blocker_id, blocked_id)

    def unblock_user(self, blocker_id: str, blocked_id: str) -> bool:
        """Unblock a user. Returns True if was blocked."""
        return skrafldb.BlockModel.unblock_user(blocker_id, blocked_id)

    def is_blocking(self, blocker_id: str, blocked_id: str) -> bool:
        """Check if one user is blocking another."""
        return skrafldb.BlockModel.is_blocking(blocker_id, blocked_id)


class ZombieRepository:
    """NDB implementation of ZombieRepositoryProtocol."""

    def add_game(self, game_id: str, user_id: str) -> None:
        """Mark a game as zombie for a user."""
        skrafldb.ZombieModel.add_game(game_id, user_id)

    def delete_game(self, game_id: str, user_id: str) -> None:
        """Remove zombie marking for a game/user."""
        skrafldb.ZombieModel.del_game(game_id, user_id)

    def delete_for_user(self, user_id: str) -> None:
        """Delete all zombie entries for a user."""
        skrafldb.ZombieModel.delete_for_user(user_id)

    def list_games(self, user_id: str) -> Iterator[ZombieGameInfo]:
        """List zombie games for a user."""
        for z in skrafldb.ZombieModel.list_games(user_id):
            yield ZombieGameInfo(
                uuid=z["uuid"],
                ts=z["ts"],
                opp=z.get("opp"),
                robot_level=z["robot_level"],
                sc0=z["sc0"],
                sc1=z["sc1"],
                locale=z.get("locale"),
            )


class RatingRepository:
    """NDB implementation of RatingRepositoryProtocol."""

    def get_or_create(self, kind: str, rank: int) -> Any:
        """Get or create a rating entry."""
        model = skrafldb.RatingModel.get_or_create(kind, rank)
        # RatingModel.get_or_create() returns an entity but doesn't persist it
        # if it was newly created. Call put() to ensure it's saved.
        model.put()
        return model

    def list_rating(self, kind: str) -> Iterator[RatingInfo]:
        """List all ratings of a kind."""
        for r in skrafldb.RatingModel.list_rating(kind):
            yield RatingInfo(
                rank=r["rank"],
                userid=r.get("userid"),
                robot_level=0,  # RatingModel doesn't have robot_level in dict
                games=r["games"],
                elo=r["elo"],
                score=r["score"],
                score_against=r["score_against"],
                wins=r["wins"],
                losses=r["losses"],
                rank_yesterday=r["rank_yesterday"],
                games_yesterday=r["games_yesterday"],
                elo_yesterday=r["elo_yesterday"],
                score_yesterday=r["score_yesterday"],
                score_against_yesterday=r["score_against_yesterday"],
                wins_yesterday=r["wins_yesterday"],
                losses_yesterday=r["losses_yesterday"],
                rank_week_ago=r["rank_week_ago"],
                games_week_ago=r["games_week_ago"],
                elo_week_ago=r["elo_week_ago"],
                score_week_ago=r["score_week_ago"],
                score_against_week_ago=r["score_against_week_ago"],
                wins_week_ago=r["wins_week_ago"],
                losses_week_ago=r["losses_week_ago"],
                rank_month_ago=r["rank_month_ago"],
                games_month_ago=r["games_month_ago"],
                elo_month_ago=r["elo_month_ago"],
                score_month_ago=r["score_month_ago"],
                score_against_month_ago=r["score_against_month_ago"],
                wins_month_ago=r["wins_month_ago"],
                losses_month_ago=r["losses_month_ago"],
            )

    def delete_all(self) -> None:
        """Delete all rating entries."""
        skrafldb.RatingModel.delete_all()


class RiddleRepository:
    """NDB implementation of RiddleRepositoryProtocol."""

    def get_riddle(self, date_str: str, locale: str) -> Optional[RiddleEntity]:
        """Get a riddle by date and locale."""
        model = skrafldb.RiddleModel.get_riddle(date_str, locale)
        return RiddleEntity(model) if model else None

    def get_riddles_for_date(self, date_str: str) -> Sequence[RiddleEntity]:
        """Get all riddles for a date."""
        models = skrafldb.RiddleModel.get_riddles_for_date(date_str)
        return [RiddleEntity(m) for m in models]

    def save_riddle(
        self, date_str: str, locale: str, riddle_json: str, version: int = 1
    ) -> RiddleEntity:
        """Save a riddle."""
        # RiddleModel doesn't have a save method, so we create/update manually
        key_id = f"{date_str}:{locale}"
        model = skrafldb.RiddleModel.get_by_id(key_id)
        if model is None:
            model = skrafldb.RiddleModel(id=key_id)
        model.date = date_str
        model.locale = locale
        model.riddle_json = riddle_json
        model.version = version
        from datetime import datetime, UTC

        model.created = datetime.now(UTC)
        model.put()
        return RiddleEntity(model)


class ImageRepository:
    """NDB implementation of ImageRepositoryProtocol."""

    def get_thumbnail(self, user_id: str, size: int = 384) -> Optional[bytes]:
        """Get a user's thumbnail image."""
        return skrafldb.ImageModel.get_thumbnail(user_id, size)

    def set_thumbnail(self, user_id: str, image: bytes, size: int = 384) -> None:
        """Set a user's thumbnail image."""
        skrafldb.ImageModel.set_thumbnail(user_id, image, size)


class ReportRepository:
    """NDB implementation of ReportRepositoryProtocol."""

    def report_user(
        self, reporter_id: str, reported_id: str, code: int, text: str
    ) -> bool:
        """Report a user. Returns True if successful."""
        return skrafldb.ReportModel.report_user(reporter_id, reported_id, code, text)

    def list_reported_by(self, user_id: str, max_len: int = 100) -> Iterator[str]:
        """List users reported by a user."""
        return skrafldb.ReportModel.list_reported_by(user_id, max_len)


class PromoRepository:
    """NDB implementation of PromoRepositoryProtocol."""

    def add_promotion(self, user_id: str, promotion: str) -> None:
        """Record that a user has seen a promotion."""
        skrafldb.PromoModel.add_promotion(user_id, promotion)

    def list_promotions(self, user_id: str, promotion: str) -> Iterator[datetime]:
        """List when a user has seen a promotion."""
        return skrafldb.PromoModel.list_promotions(user_id, promotion)


class TransactionRepository:
    """NDB implementation of TransactionRepositoryProtocol."""

    def add_transaction(self, user_id: str, plan: str, kind: str, op: str) -> None:
        """Log a transaction."""
        skrafldb.TransactionModel.add_transaction(user_id, plan, kind, op)

    def count_for_user(self, user_id: str) -> int:
        """Count transactions for a user."""
        from google.cloud.ndb import Key

        user_key = Key(skrafldb.UserModel, user_id)
        return skrafldb.TransactionModel.query(
            skrafldb.TransactionModel.user == user_key
        ).count()


class SubmissionRepository:
    """NDB implementation of SubmissionRepositoryProtocol."""

    def submit_word(self, user_id: str, locale: str, word: str, comment: str) -> None:
        """Submit a word for review."""
        skrafldb.SubmissionModel.submit_word(user_id, locale, word, comment)

    def count_for_user(self, user_id: str) -> int:
        """Count submissions for a user."""
        from google.cloud.ndb import Key

        user_key = Key(skrafldb.UserModel, user_id)
        return skrafldb.SubmissionModel.query(
            skrafldb.SubmissionModel.user == user_key
        ).count()


class CompletionRepository:
    """NDB implementation of CompletionRepositoryProtocol."""

    def add_completion(self, proctype: str, ts_from: datetime, ts_to: datetime) -> None:
        """Log a successful completion."""
        skrafldb.CompletionModel.add_completion(proctype, ts_from, ts_to)

    def add_failure(
        self, proctype: str, ts_from: datetime, ts_to: datetime, reason: str
    ) -> None:
        """Log a failed completion."""
        skrafldb.CompletionModel.add_failure(proctype, ts_from, ts_to, reason)

    def count_for_proctype(self, proctype: str) -> int:
        """Count completions for a process type."""
        return skrafldb.CompletionModel.query(
            skrafldb.CompletionModel.proctype == proctype
        ).count()


class RobotRepository:
    """NDB implementation of RobotRepositoryProtocol."""

    def get_elo(self, locale: str, level: int) -> Optional[int]:
        """Get the Elo rating for a robot at a level."""
        model = skrafldb.RobotModel.robot_elo(locale, level)
        return model.elo if model else None

    def upsert_elo(self, locale: str, level: int, elo: int) -> bool:
        """Create or update robot Elo. Returns True if successful."""
        model = skrafldb.RobotModel.robot_elo(locale, level)
        return skrafldb.RobotModel.upsert(model, locale, level, elo)


# =============================================================================
# Query Wrapper
# =============================================================================


class NDBQueryWrapper:
    """Wrapper around NDB Query to implement QueryProtocol."""

    def __init__(self, query: Any, entity_class: type) -> None:
        self._query = query
        self._entity_class = entity_class

    def filter(self, *conditions: Any) -> "NDBQueryWrapper":
        """Add filter conditions to the query."""
        # NDB queries use different filter syntax, so we pass through
        return NDBQueryWrapper(self._query.filter(*conditions), self._entity_class)

    def order(self, *columns: Any) -> "NDBQueryWrapper":
        """Add ordering to the query."""
        return NDBQueryWrapper(self._query.order(*columns), self._entity_class)

    def fetch(self, limit: Optional[int] = None) -> List[Any]:
        """Execute the query and return results."""
        if limit is not None:
            results = self._query.fetch(limit=limit)
        else:
            results = self._query.fetch()
        return [self._entity_class(m) for m in results]

    def get(self) -> Optional[Any]:
        """Execute the query and return the first result."""
        result = self._query.get()
        return self._entity_class(result) if result else None

    def count(self) -> int:
        """Return the count of matching entities."""
        return self._query.count()

    def iter(self, limit: int = 0) -> Iterator[Any]:
        """Iterate over query results."""
        for item in skrafldb.iter_q(self._query, limit=limit):
            yield self._entity_class(item)
