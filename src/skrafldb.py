"""

    Skrafldb - persistent data management for the Netskrafl application

    Copyright (C) 2021 Miðeind ehf.
    Author: Vilhjálmur Þorsteinsson

    The GNU Affero General Public License, version 3, applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This module stores data in the Google App Engine NDB
    (see https://developers.google.com/appengine/docs/python/ndb/).

    The data model is as follows:

    UserModel:
        nickname : string
        inactive : boolean
        prefs : dict
        timestamp : timestamp

    MoveModel:
        coord : string
        tiles : string # Blanks are denoted by '?' followed by meaning
        score : integer
        rack : string # Contents of rack after move
        timestamp : timestamp

    GameModel:
        player0 : key into UserModel
        player1 : key into UserModel
        irack0 : string # Initial rack
        irack1 : string
        rack0 : string # Current rack
        rack1 : string
        score0 : integer
        score1 : integer
        to_move : integer # Whose move is it, 0 or 1
        over : boolean # Is the game over?
        timestamp : timestamp # Start time of game
        ts_last_move : timestamp # Time of last move
        moves : array of MoveModel

    FavoriteModel:
        parent = key into UserModel
        destuser: key into UserModel

    ChallengeModel:
        parent = key into UserModel
        destuser : key into UserModel
        timestamp : timestamp
        prefs : dict

    According to the NDB documentation, an ideal index for a query
    should contain - in the order given:
    1) Properties used in equality filters
    2) Property used in an inequality filter (only one allowed)
    3) Properties used for ordering

"""

# pylint: disable=too-many-lines

from __future__ import annotations

from typing import (
    Dict,
    Generic,
    Literal,
    Sequence,
    Set,
    Tuple,
    Optional,
    Iterator,
    Iterable,
    List,
    Any,
    Type,
    TypeVar,
    TypedDict,
    Union,
    Callable,
    cast,
    overload,
)

import logging
import uuid

from datetime import datetime

from google.cloud import ndb  # type: ignore

from cache import memcache


# Type definitions
_T = TypeVar("_T")

PrefItem = Union[str, int, bool]
PrefsDict = Dict[str, PrefItem]
ChallengeTuple = Tuple[Optional[str], Optional[PrefsDict], datetime]


class StatsDict(TypedDict):
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


StatsResults = List[StatsDict]


class Query(Generic[_T], ndb.Query):

    """A type-safer wrapper around ndb.Query"""

    def order(self, *args: Any, **kwargs: Any) -> Query[_T]:
        f: Callable[..., Query[_T]] = cast(Any, super()).order
        return f(*args, **kwargs)

    def filter(self, *args: Any, **kwargs: Any) -> Query[_T]:
        f: Callable[..., Query[_T]] = cast(Any, super()).filter
        return f(*args, **kwargs)

    def fetch(self, *args: Any, **kwargs: Any) -> List[_T]:
        f: Callable[..., List[_T]] = cast(Any, super()).fetch
        return f(*args, **kwargs)

    def fetch_async(self, *args: Any, **kwargs: Any) -> Future[_T]:
        f: Callable[..., Future[_T]] = cast(Any, super()).fetch_async
        return f(*args, **kwargs)

    def fetch_page(self, *args: Any, **kwargs: Any) -> Tuple[Iterable[_T], int, bool]:
        f: Callable[..., Tuple[Iterable[_T], int, bool]] = cast(Any, super()).fetch_page
        return f(*args, **kwargs)

    @overload
    def get(self, keys_only: Literal[True]) -> Optional[Key]:
        ...

    @overload
    def get(self, *args: Any, **kwargs: Any) -> Optional[_T]:
        ...

    def get(self, *args: Any, **kwargs: Any) -> Union[None, Key, _T]:
        f: Callable[..., Union[None, Key, _T]] = cast(Any, super()).get
        return f(*args, **kwargs)

    def count(self, *args: Any, **kwargs: Any) -> int:
        return cast(Any, super()).count(*args, **kwargs)

    @overload
    def iter(self, keys_only: Literal[True]) -> Iterable[Key]:
        ...

    @overload
    def iter(self, *args: Any, **kwargs: Any) -> Iterable[_T]:
        ...

    def iter(self, *args: Any, **kwargs: Any) -> Union[Iterable[Key], Iterable[_T]]:
        f: Callable[..., Union[Iterable[Key], Iterable[_T]]] = cast(Any, super()).iter
        return f(*args, **kwargs)


class Future(Generic[_T], ndb.Future):

    """A type-safer wrapper around ndb.Future"""

    def get_result(self) -> List[_T]:
        f: Callable[[], List[_T]] = cast(Any, super()).get_result
        return f()

    @staticmethod
    def wait_all(futures: Sequence[Future[_T]]) -> None:
        cast(Any, ndb.Future).wait_all(futures)


class Key(ndb.Key):

    """A type-safer wrapper around ndb.Key"""

    def id(self) -> str:
        return cast(str, super().id())

    def parent(self) -> Optional[Key]:
        return cast(Optional[Key], super().parent())

    def delete(self, *args: Any, **kwargs: Any) -> None:
        cast(Any, super()).delete(*args, **kwargs)


_T_Model = TypeVar("_T_Model", bound="Model")


class Model(ndb.Model):

    """A type-safer wrapper around ndb.Model"""

    @property
    def key(self) -> Key:
        return cast(Key, cast(Any, super()).key)

    def put(self, **kwargs: Any) -> Key:
        return cast(Any, super()).put(**kwargs)

    @classmethod
    def put_multi(cls: Type[_T_Model], recs: Iterable[_T_Model]) -> None:
        put_multi(recs)

    @classmethod
    def get_by_id(
        cls: Type[_T_Model], identifier: str, **kwargs: Any
    ) -> Optional[_T_Model]:
        return cast(Any, super()).get_by_id(identifier, **kwargs)

    @classmethod
    def query(cls: Type[_T_Model], *args: Any, **kwargs: Any) -> Query[_T_Model]:
        return cast(Query[_T_Model], cast(Any, super()).query(*args, **kwargs))

    @staticmethod
    def DbKey(kind: Type[_T_Model], indexed: bool = True) -> Key:
        return cast(Key, ndb.KeyProperty(kind=kind, required=True, indexed=indexed))

    @staticmethod
    def OptionalDbKey(kind: Type[_T_Model], indexed: bool = True) -> Optional[Key]:
        return cast(
            Optional[Key],
            ndb.KeyProperty(kind=kind, required=False, indexed=indexed, default=None),
        )

    @staticmethod
    def Str() -> str:
        return cast(str, ndb.StringProperty(required=True))

    @staticmethod
    def OptionalStr(default: Optional[str] = None) -> Optional[str]:
        return cast(Optional[str], ndb.StringProperty(required=False, default=default))

    @staticmethod
    def Bool() -> bool:
        return cast(bool, ndb.BooleanProperty(required=True))

    @staticmethod
    def OptionalBool(default: Optional[bool] = None) -> Optional[bool]:
        return cast(
            Optional[bool], ndb.BooleanProperty(required=False, default=default)
        )

    @staticmethod
    def Int(default: Optional[int] = None, indexed: bool = False) -> int:
        return cast(
            int,
            ndb.IntegerProperty(
                required=(default is None), default=default, indexed=indexed
            ),
        )

    @staticmethod
    def OptionalInt(
        default: Optional[int] = None, indexed: bool = False
    ) -> Optional[int]:
        return cast(
            Optional[int],
            ndb.IntegerProperty(required=False, default=default, indexed=indexed),
        )

    @staticmethod
    def Datetime(
        default: Optional[datetime] = None,
        indexed: bool = False,
        auto_now_add: bool = False,
    ) -> datetime:
        return cast(
            datetime,
            ndb.DateTimeProperty(
                required=True,
                default=default,
                indexed=indexed,
                auto_now_add=auto_now_add,
            ),
        )

    @staticmethod
    def OptionalDatetime(
        default: Optional[datetime] = None, indexed: bool = False
    ) -> Optional[datetime]:
        return cast(
            Optional[datetime],
            ndb.DateTimeProperty(required=False, default=default, indexed=indexed),
        )


class Client:

    """Wrapper for the ndb client instance singleton"""

    _client = ndb.Client()
    _global_cache = ndb.RedisCache(memcache.get_redis_client())

    def __init__(self) -> None:
        pass

    @classmethod
    def get_context(cls):
        """Return the ndb client instance singleton"""
        return cls._client.context(global_cache=cls._global_cache)


class Context:

    """Wrapper for NDB context operations"""

    def __init__(self) -> None:
        pass

    @staticmethod
    def disable_cache() -> None:
        """Disable the NDB in-context cache"""
        ctx = cast(Any, ndb).get_context()
        assert ctx is not None
        ctx.set_cache_policy(False)


class Unique:

    """Utility class for generation of unique id strings for keys"""

    def __init__(self) -> None:
        pass

    @staticmethod
    def id() -> str:
        """Generates unique id strings"""
        return str(uuid.uuid1())  # Random UUID


def iter_q(
    q: Query[_T],
    chunk_size: int = 50,
    limit: int = 0,
    projection: Optional[List[str]] = None,
) -> Iterator[_T]:
    """Generator for iterating through a query using a cursor"""
    if 0 < limit < chunk_size:
        # Don't fetch more than we want
        chunk_size = limit
    items, next_cursor, more = q.fetch_page(chunk_size, projection=projection)
    count = 0
    while items:
        for item in items:
            yield item
            count += 1
            if limit and count >= limit:
                # A limit was set and we'we reached it: stop
                return
        if not more or not next_cursor:
            # The query is exhausted: stop
            return
        # Get the next chunk
        items, next_cursor, more = q.fetch_page(
            chunk_size, start_cursor=next_cursor, projection=projection
        )


def put_multi(recs: Iterable[Model]) -> None:
    """Type-safer call to ndb.put_multi()"""
    cast(Any, ndb).put_multi(recs)


def delete_multi(keys: Iterable[Key]) -> None:
    """Type-safer call to ndb.delete_multi()"""
    cast(Any, ndb).delete_multi(keys)


class UserModel(Model):

    """Models an individual user"""

    nickname = Model.Str()

    email = Model.OptionalStr()

    image = Model.OptionalStr()

    # OAuth2 account identifier (unfortunately different from GAE user id)
    # optionally prefixed by the authentication provider id (default: 'google:')
    account = Model.OptionalStr()

    # Lower case nickname and full name of user - used for search
    nick_lc = Model.OptionalStr()
    name_lc = Model.OptionalStr()

    # Is the user no longer active/enabled?
    inactive = Model.Bool()
    # The user's preferred locale, i.e. language and other settings
    locale = Model.OptionalStr(default="is_IS")
    # Preferences dictionary
    prefs = cast(PrefsDict, ndb.JsonProperty())
    # Creation time of the user entity
    timestamp = Model.Datetime(auto_now_add=True)
    # Last login for the user
    last_login = Model.OptionalDatetime()
    # Ready for challenges?
    ready = Model.OptionalBool(default=False)
    # Ready for timed challenges?
    ready_timed = Model.OptionalBool(default=False)
    # Elo points
    elo = Model.Int(default=0, indexed=True)
    # Elo points for human-only games
    human_elo = Model.Int(default=0, indexed=True)
    # Elo points for manual (competition) games
    manual_elo = Model.Int(default=0, indexed=True)
    # Best total score in a game
    highest_score = Model.Int(default=0, indexed=True)
    # Note: indexing of string properties is mandatory
    highest_score_game = Model.OptionalStr()
    # Best word laid down
    # Note: indexing of string properties is mandatory
    best_word = Model.OptionalStr()
    best_word_score = Model.Int(default=0, indexed=True)
    # Note: indexing of string properties is mandatory
    best_word_game = Model.OptionalStr()

    @classmethod
    def create(
        cls,
        user_id: str,
        account: str,
        email: str,
        nickname: str,
        image: str,
        preferences: Optional[PrefsDict] = None,
        locale: Optional[str] = None,
    ) -> str:
        """Create a new user"""
        user: UserModel = cls(id=user_id)
        user.account = account
        user.email = email
        user.image = image
        user.nickname = nickname  # Default to the same nickname
        user.nick_lc = nickname.lower()
        user.inactive = False  # A new user is always active
        user.prefs = preferences or {}  # Default to no preferences
        user.ready = False  # Not ready for new challenges unless explicitly set
        user.ready_timed = False  # Not ready for timed games unless explicitly set
        user.locale = locale or "is_IS"
        user.last_login = datetime.utcnow()
        return user.put().id()

    @classmethod
    def fetch(cls, user_id: str) -> Optional[UserModel]:
        """Fetch a user entity by id"""
        return cls.get_by_id(user_id, use_cache=False, use_global_cache=False)

    @classmethod
    def fetch_account(cls, account: str) -> Optional[UserModel]:
        """Attempt to fetch a user by OAuth2 account id,
        prefixed by the authentication provider"""
        q = cls.query(UserModel.account == account)
        return q.get()

    @classmethod
    def fetch_email(cls, email: str) -> Optional[UserModel]:
        """Attempt to fetch a user by email."""
        if not email:
            return None
        # Note that multiple records with the same e-mail may occur
        # Do not return inactive accounts
        q = cls.query(UserModel.email == email.lower()).filter(
            UserModel.inactive == False
        )
        result = q.fetch()
        if not result:
            return None
        # If multiple user records have the same email, return the newest one
        # - but try to keep user records with elo==0 out of the picture
        return sorted(result, key=lambda u: (u.elo > 0, u.timestamp), reverse=True)[0]

    @classmethod
    def fetch_multi(cls, user_ids: Iterable[str]) -> List[UserModel]:
        """Fetch multiple user entities by id list"""
        # Google NDB/RPC doesn't allow more than 1000 entities per get_multi() call
        MAX_CHUNK = 1000
        result: List[UserModel] = []
        ix = 0
        user_ids = list(user_ids)
        end = len(user_ids)
        while ix < end:
            keys = [Key(UserModel, uid) for uid in user_ids[ix : ix + MAX_CHUNK]]
            len_keys = len(keys)
            if ix == 0 and len_keys == end:
                # Most common case: just a single, complete read
                return cast(Any, ndb).get_multi(keys)
            # Otherwise, accumulate chunks
            result.extend(cast(Any, ndb).get_multi(keys))
            ix += len_keys
        return result

    def user_id(self) -> str:
        """Return the ndb key of a user as a string"""
        return self.key.id()

    @classmethod
    def count(cls) -> int:
        """Return a count of user entities"""
        # Beware: this seems to be EXTREMELY slow on Google Cloud Datastore
        return cls.query().count()

    @classmethod
    def filter_locale(
        cls, q: Query[UserModel], locale: Optional[str]
    ) -> Query[UserModel]:
        """Filter the query by locale, if given, otherwise stay
        with the is_IS default"""
        # FIXME: To be modified once locale support is fully in place
        return q
        # if locale is None:
        #     return q.filter(
        #         ndb.OR(UserModel.locale == "is_IS", UserModel.locale == None)
        #     )
        # return q.filter(UserModel.locale == locale)

    @classmethod
    def list_prefix(
        cls, prefix: str, max_len: int = 50, locale: Optional[str] = None
    ) -> Iterator[Dict[str, Any]]:
        """Query for a list of users having a name or nick with the given prefix"""

        if not prefix:
            # No prefix means nothing is returned
            return

        prefix = prefix.lower()
        id_set: Set[str] = set()

        def list_q(
            q: Query[UserModel], f: Callable[[UserModel], str]
        ) -> Iterator[Dict[str, Any]]:
            """Yield the results of a user query"""
            CHUNK_SIZE = 50
            for um in iter_q(q, chunk_size=CHUNK_SIZE):
                if not f(um).startswith(prefix):
                    # Iterated past the prefix
                    return
                if not um.inactive and not um.key.id() in id_set:
                    # This entity matches and has not already been
                    # returned: yield a dict describing it
                    yield dict(
                        id=um.key.id(),
                        nickname=um.nickname,
                        prefs=um.prefs,
                        timestamp=um.timestamp,
                        ready=um.ready,
                        ready_timed=um.ready_timed,
                        human_elo=um.human_elo,
                        manual_elo=um.manual_elo,
                        image=um.image,
                    )
                    id_set.add(um.key.id())

        counter = 0

        # Return users with nicknames matching the prefix
        q: Query[UserModel]
        q = cls.query(cast(str, UserModel.nick_lc) >= prefix).order(UserModel.nick_lc)
        q = cls.filter_locale(q, locale)

        for ud in list_q(q, lambda um: um.nick_lc or ""):
            yield ud
            counter += 1
            if 0 < max_len <= counter:
                # Hit limit on returned users: stop iterating
                return

        # Return users with full names matching the prefix
        q = cls.query(cast(str, UserModel.name_lc) >= prefix).order(UserModel.name_lc)
        q = cls.filter_locale(q, locale)

        um_func: Callable[[UserModel], str] = lambda um: um.name_lc or ""
        for ud in list_q(q, um_func):
            yield ud
            counter += 1
            if 0 < max_len <= counter:
                # Hit limit on returned users: stop iterating
                return

    @classmethod
    def list_similar_elo(
        cls, elo: int, max_len: int = 40, locale: Optional[str] = None
    ) -> List[str]:
        """List users with a similar (human) Elo rating"""
        # Start with max_len users with a lower Elo rating

        def fetch(q: Query[UserModel], max_len: int) -> Iterator[str]:
            """Generator for returning query result keys"""
            assert max_len > 0
            counter = 0  # Number of results already returned
            for k in iter_q(q, chunk_size=max_len, projection=["highest_score"]):
                if k.highest_score > 0:
                    # Has played at least one game: Yield the key value
                    # Note that inactive users will be filtered out at a later stage
                    yield k.key.id()
                    counter += 1
                    if counter >= max_len:
                        # Returned the requested number of records: done
                        return

        # Descending order
        q: Query[UserModel]
        q = cls.query(UserModel.human_elo < elo).order(-UserModel.human_elo)
        q = cls.filter_locale(q, locale)
        lower = list(fetch(q, max_len))
        # Convert to an ascending list
        lower.reverse()
        # Repeat the query for same or higher rating
        # Ascending order
        q = cls.query(UserModel.human_elo >= elo).order(UserModel.human_elo)
        q = cls.filter_locale(q, locale)
        higher = list(fetch(q, max_len))
        # Concatenate the upper part of the lower range with the
        # lower part of the higher range in the most balanced way
        # available (considering that either of the lower or upper
        # ranges may be empty or have fewer than max_len//2 entries)
        len_lower = len(lower)
        len_higher = len(higher)
        # Ideal balanced length from each range
        half_len = max_len // 2
        ix = 0  # Default starting index in the lower range
        if len_lower >= half_len:
            # We have enough entries in the lower range for a balanced result,
            # if the higher range allows
            # Move the start index
            ix = len_lower - half_len
            if len_higher < half_len:
                # We don't have enough entries in the upper range
                # to balance the result: move the beginning index down
                if ix >= half_len - len_higher:
                    # Shift the entire missing balance to the lower range
                    ix -= half_len - len_higher
                else:
                    # Take as much slack as possible
                    ix = 0
        # Concatenate the two slices into one result and return it
        assert max_len >= (len_lower - ix)
        result = lower[ix:] + higher[0 : max_len - (len_lower - ix)]
        return result


class MoveModel(Model):

    """Models a single move in a Game"""

    coord = Model.Str()
    tiles = Model.Str()
    score = Model.Int(default=0)
    rack = Model.OptionalStr()
    timestamp = Model.OptionalDatetime()


class GameModel(Model):

    """Models a game between two users"""

    # The players
    player0 = Model.OptionalDbKey(kind=UserModel)
    player1 = Model.OptionalDbKey(kind=UserModel)

    rack0 = Model.Str()  # Must be indexed
    rack1 = Model.Str()  # Must be indexed

    # The scores
    score0 = Model.Int(indexed=False)
    score1 = Model.Int(indexed=False)

    # Whose turn is it next, 0 or 1?
    to_move = Model.Int(indexed=False)

    # How difficult should the robot player be (if the opponent is a robot)?
    # None or 0 = most difficult
    robot_level = Model.Int(indexed=False, default=0)

    # Is this game over?
    over = Model.Bool()

    # When was the game started?
    timestamp = Model.Datetime(auto_now_add=True)

    # The timestamp of the last move in the game
    ts_last_move = Model.OptionalDatetime()

    # The moves so far
    moves = cast(
        Iterable[MoveModel],
        ndb.LocalStructuredProperty(MoveModel, repeated=True, indexed=False),
    )

    # The initial racks
    irack0 = Model.OptionalStr()  # Must be indexed
    irack1 = Model.OptionalStr()  # Must be indexed

    # Game preferences, such as duration, alternative bags or boards, etc.
    prefs = cast(PrefsDict, ndb.JsonProperty(required=False, default=None))

    # Count of tiles that have been laid on the board
    tile_count = Model.OptionalInt()

    # Elo statistics properties - only defined for finished games
    # Elo points of both players when game finished, before adjustment
    elo0 = Model.OptionalInt()
    elo1 = Model.OptionalInt()
    # Adjustment of Elo points of both players as a result of this game
    elo0_adj = Model.OptionalInt()
    elo1_adj = Model.OptionalInt()
    # Human-only Elo points of both players when game finished
    # (not defined if robot game)
    human_elo0 = Model.OptionalInt()
    human_elo1 = Model.OptionalInt()
    # Human-only Elo point adjustment as a result of this game
    human_elo0_adj = Model.OptionalInt()
    human_elo1_adj = Model.OptionalInt()
    # Manual-only Elo points of both players when game finished
    # (not defined unless this is a manual (competition) game)
    manual_elo0 = Model.OptionalInt()
    manual_elo1 = Model.OptionalInt()
    # Manual-only Elo point adjustment as a result of this game
    manual_elo0_adj = Model.OptionalInt()
    manual_elo1_adj = Model.OptionalInt()

    def set_player(self, ix: int, user_id: Optional[str]) -> None:
        """Set a player key property to point to a given user, or None"""
        k = None if user_id is None else Key(UserModel, user_id)
        if ix == 0:
            self.player0 = k
        elif ix == 1:
            self.player1 = k

    def player0_id(self) -> Optional[str]:
        """Return the user id of player 0, if any"""
        if (p := self.player0) is None:
            return None
        return p.id()

    def player1_id(self) -> Optional[str]:
        """Return the user id of player 1, if any"""
        if (p := self.player1) is None:
            return None
        return p.id()

    @classmethod
    def fetch(cls, game_uuid: str, use_cache: bool = True) -> Optional[GameModel]:
        """Fetch a game entity given its uuid"""
        if not use_cache:
            return cls.get_by_id(game_uuid, use_cache=False, use_global_cache=False)
        # Default caching policy if caching is not explictly prohibited
        return cls.get_by_id(game_uuid)

    @classmethod
    def list_finished_games(
        cls, user_id: str, versus: Optional[str] = None, max_len: int = 10
    ) -> List[Dict[str, Any]]:
        """Query for a list of recently finished games for the given user"""
        assert user_id is not None
        if user_id is None:
            return []

        def game_callback(gm: GameModel) -> Dict[str, Any]:
            """Map a game entity to a result dictionary with useful info about the game"""
            game_uuid = gm.key.id()
            u0: Optional[str] = None if gm.player0 is None else gm.player0.id()
            u1: Optional[str] = None if gm.player1 is None else gm.player1.id()
            if u0 == user_id:
                # Player 0 is the source player, 1 is the opponent
                opp = u1
                sc0, sc1 = gm.score0, gm.score1
                elo_adj = gm.elo0_adj
                human_elo_adj = gm.human_elo0_adj
                manual_elo_adj = gm.manual_elo0_adj
            else:
                # Player 1 is the source player, 0 is the opponent
                assert u1 == user_id
                opp = u0
                sc1, sc0 = gm.score0, gm.score1
                elo_adj = gm.elo1_adj
                human_elo_adj = gm.human_elo1_adj
                manual_elo_adj = gm.manual_elo1_adj
            return dict(
                uuid=game_uuid,
                ts=gm.timestamp,
                ts_last_move=gm.ts_last_move or gm.timestamp,
                opp=opp,
                robot_level=gm.robot_level,
                sc0=sc0,
                sc1=sc1,
                elo_adj=elo_adj,
                human_elo_adj=human_elo_adj,
                manual_elo_adj=manual_elo_adj,
                prefs=gm.prefs,
            )

        k = Key(UserModel, user_id)

        q0: Query[GameModel]
        q1: Query[GameModel]

        if versus:
            # Add a filter on the opponent
            v = Key(UserModel, versus)
            q0 = cls.query(ndb.AND(GameModel.player1 == k, GameModel.player0 == v))
            q1 = cls.query(ndb.AND(GameModel.player0 == k, GameModel.player1 == v))
        else:
            # Plain filter on the player
            q0 = cls.query(GameModel.player0 == k)
            q1 = cls.query(GameModel.player1 == k)

        # pylint: disable=singleton-comparison
        # The cast to int below is a hack for type checking
        # (it has no effect at run-time)
        q0 = q0.filter(GameModel.over == True).order(-cast(int, GameModel.ts_last_move))
        q1 = q1.filter(GameModel.over == True).order(-cast(int, GameModel.ts_last_move))

        # Issue two asynchronous queries in parallel
        qf = (q0.fetch_async(max_len), q1.fetch_async(max_len))
        # Wait for both of them to finish
        Future.wait_all(qf)

        # Combine the two query result lists and call game_callback() on each item
        rlist = map(game_callback, qf[0].get_result() + qf[1].get_result())

        # Return the newest max_len games
        return sorted(rlist, key=lambda x: x["ts_last_move"], reverse=True)[0:max_len]

    @classmethod
    def iter_live_games(
        cls, user_id: Optional[str], max_len: int = 10
    ) -> Iterator[Dict[str, Any]]:
        """Query for a list of active games for the given user"""
        if user_id is None:
            return
        k = Key(UserModel, user_id)
        # pylint: disable=singleton-comparison
        q: Query[GameModel] = (
            cls.query(ndb.OR(GameModel.player0 == k, GameModel.player1 == k))
            .filter(GameModel.over == False)
            .order(-cast(int, GameModel.ts_last_move))
        )

        def game_callback(gm: GameModel) -> Dict[str, Any]:
            """Map a game entity to a result tuple with useful info about the game"""
            game_uuid = gm.key.id()
            u0: Optional[str] = None if gm.player0 is None else gm.player0.id()
            u1: Optional[str] = None if gm.player1 is None else gm.player1.id()
            if u0 == user_id:
                # Player 0 is the source player, 1 is the opponent
                opp = u1
                sc0, sc1 = gm.score0, gm.score1
                my_turn = gm.to_move == 0
            else:
                # Player 1 is the source player, 0 is the opponent
                assert u1 == user_id
                opp = u0
                sc1, sc0 = gm.score0, gm.score1
                my_turn = gm.to_move == 1
            # Obtain a count of the tiles that have been laid down
            tc = gm.tile_count
            if tc is None:
                # Not stored: we must count the tiles manually
                # This will not be 100% accurate as tiles will be double-counted
                # if they are a part of two words
                tc = 0
                for m in gm.moves:
                    if m.coord:
                        # Normal tile move
                        tc += len(m.tiles.replace("?", ""))
            return dict(
                uuid=game_uuid,
                ts=gm.ts_last_move or gm.timestamp,
                opp=opp,
                robot_level=gm.robot_level,
                my_turn=my_turn,
                sc0=sc0,
                sc1=sc1,
                prefs=gm.prefs,
                tile_count=tc,
            )

        for gm in q.fetch(max_len):
            yield game_callback(gm)


class FavoriteModel(Model):

    """Models the fact that a user has marked another user as a favorite"""

    MAX_FAVORITES = 100  # The maximum number of favorites that a user can have

    # The originating (source) user is the parent/ancestor of the relation
    destuser = Model.DbKey(kind=UserModel)

    def set_dest(self, user_id: str) -> None:
        """Set a destination user key property"""
        k = None if user_id is None else Key(UserModel, user_id)
        self.destuser = k

    @classmethod
    def list_favorites(
        cls, user_id: str, max_len: int = MAX_FAVORITES
    ) -> Iterator[str]:
        """Query for a list of favorite users for the given user"""
        assert user_id is not None
        if user_id is None:
            return
        k = Key(UserModel, user_id)
        q: Query[FavoriteModel] = cls.query(ancestor=k)
        for fm in q.fetch(max_len, read_consistency=cast(Any, ndb).EVENTUAL):
            if fm.destuser is not None:
                yield fm.destuser.id()

    @classmethod
    def has_relation(
        cls, srcuser_id: Optional[str], destuser_id: Optional[str]
    ) -> bool:
        """Return True if destuser is a favorite of user"""
        if srcuser_id is None or destuser_id is None:
            return False
        ks = Key(UserModel, srcuser_id)
        kd = Key(UserModel, destuser_id)
        q: Query[FavoriteModel] = cls.query(ancestor=ks).filter(
            FavoriteModel.destuser == kd
        )
        return q.get(keys_only=True) is not None

    @classmethod
    def add_relation(cls, src_id: str, dest_id: str) -> None:
        """Add a favorite relation between the two users"""
        fm = FavoriteModel(parent=Key(UserModel, src_id))
        fm.set_dest(dest_id)
        fm.put()

    @classmethod
    def del_relation(cls, src_id: str, dest_id: str) -> None:
        """Delete a favorite relation between a source user and a destination user"""
        ks = Key(UserModel, src_id)
        kd = Key(UserModel, dest_id)
        while True:
            # There might conceivably be more than one relation,
            # so repeat the query/delete cycle until we don't find any more
            q: Query[FavoriteModel] = cls.query(ancestor=ks).filter(
                FavoriteModel.destuser == kd
            )
            fmk = q.get(keys_only=True)
            if fmk is None:
                return
            fmk.delete()


class ChallengeModel(Model):

    """Models a challenge issued by a user to another user"""

    # The challenging (source) user is the parent/ancestor of the relation

    # The challenged user
    destuser = Model.DbKey(kind=UserModel)

    # The parameters of the challenge (time, bag type, etc.)
    prefs = cast(PrefsDict, ndb.JsonProperty())

    # The time of issuance
    timestamp = cast(datetime, ndb.DateTimeProperty(auto_now_add=True))

    def set_dest(self, user_id: Optional[str]) -> None:
        """Set a destination user key property"""
        k = None if user_id is None else Key(UserModel, user_id)
        self.destuser = k

    @classmethod
    def has_relation(
        cls, srcuser_id: Optional[str], destuser_id: Optional[str]
    ) -> bool:
        """Return True if srcuser has issued a challenge to destuser"""
        if srcuser_id is None or destuser_id is None:
            return False
        ks = Key(UserModel, srcuser_id)
        kd = Key(UserModel, destuser_id)
        q: Query[ChallengeModel] = cls.query(ancestor=ks).filter(
            ChallengeModel.destuser == kd
        )
        return q.get(keys_only=True) is not None

    @classmethod
    def find_relation(
        cls, srcuser_id: Optional[str], destuser_id: Optional[str]
    ) -> Tuple[bool, Optional[PrefsDict]]:
        """Return (found, prefs) where found is True if srcuser has challenged destuser"""
        if srcuser_id is None or destuser_id is None:
            # noinspection PyRedundantParentheses
            return (False, None)
        ks = Key(UserModel, srcuser_id)
        kd = Key(UserModel, destuser_id)
        q: Query[ChallengeModel] = cls.query(ancestor=ks).filter(
            ChallengeModel.destuser == kd
        )
        cm = q.get()
        if cm is None:
            # Not found
            # noinspection PyRedundantParentheses
            return (False, None)
        # Found: return the preferences associated with the challenge (if any)
        return (True, cm.prefs)

    @classmethod
    def add_relation(
        cls, src_id: str, dest_id: str, prefs: Optional[PrefsDict]
    ) -> None:
        """Add a challenge relation between the two users"""
        cm = ChallengeModel(parent=Key(UserModel, src_id))
        cm.set_dest(dest_id)
        cm.prefs = {} if prefs is None else prefs
        cm.put()

    @classmethod
    def del_relation(
        cls, src_id: str, dest_id: str
    ) -> Tuple[bool, Optional[PrefsDict]]:
        """Delete a challenge relation between a source user and a destination user"""
        ks = Key(UserModel, src_id)
        kd = Key(UserModel, dest_id)
        prefs: Optional[PrefsDict] = None
        found = False
        while True:
            # There might conceivably be more than one relation,
            # so repeat the query/delete cycle until we don't find any more
            q: Query[ChallengeModel] = cls.query(ancestor=ks).filter(
                ChallengeModel.destuser == kd
            )
            cm = q.get()
            if cm is None:
                # Return the preferences of the challenge, if any
                return (found, prefs)
            # Found the relation in question: store the associated preferences
            found = True
            if prefs is None:
                prefs = cm.prefs
            cm.key.delete()

    @classmethod
    def list_issued(cls, user_id: str, max_len: int = 20) -> Iterator[ChallengeTuple]:
        """Query for a list of challenges issued by a particular user"""
        assert user_id is not None
        if user_id is None:
            return
        k = Key(UserModel, user_id)
        # List issued challenges in ascending order by timestamp (oldest first)
        q: Query[ChallengeModel] = cls.query(ancestor=k).order(ChallengeModel.timestamp)

        def ch_callback(cm: ChallengeModel) -> ChallengeTuple:
            """Map an issued challenge to a tuple of useful info"""
            id0: Optional[str] = None if cm.destuser is None else cm.destuser.id()
            return (id0, cm.prefs, cm.timestamp)

        for cm in q.fetch(max_len):
            yield ch_callback(cm)

    @classmethod
    def list_received(
        cls, user_id: Optional[str], max_len: int = 20
    ) -> Iterator[ChallengeTuple]:
        """Query for a list of challenges issued to a particular user"""
        assert user_id is not None
        if user_id is None:
            return
        k = Key(UserModel, user_id)
        # List received challenges in ascending order by timestamp (oldest first)
        q: Query[ChallengeModel] = cls.query(ChallengeModel.destuser == k).order(
            ChallengeModel.timestamp
        )

        def ch_callback(cm: ChallengeModel) -> ChallengeTuple:
            """Map a received challenge to a tuple of useful info"""
            p0 = cm.key.parent()
            id0: Optional[str] = None if p0 is None else p0.id()
            return (id0, cm.prefs, cm.timestamp)

        for cm in q.fetch(max_len):
            yield ch_callback(cm)


class StatsModel(Model):

    """Models statistics about users"""

    # The user associated with this statistic or None if robot
    user = Model.OptionalDbKey(kind=UserModel)
    robot_level = Model.Int(default=0, indexed=True)

    # The timestamp of this statistic
    timestamp = Model.Datetime(indexed=True, auto_now_add=True)

    games = Model.Int()
    human_games = Model.Int()
    manual_games = Model.Int(default=0)

    elo = Model.Int(indexed=True, default=1200)
    human_elo = Model.Int(indexed=True, default=1200)
    manual_elo = Model.Int(indexed=True, default=1200)

    score = Model.Int()
    human_score = Model.Int()
    manual_score = Model.Int(default=0)

    score_against = Model.Int()
    human_score_against = Model.Int()
    manual_score_against = Model.Int(default=0)

    wins = Model.Int()
    losses = Model.Int()

    human_wins = Model.Int()
    human_losses = Model.Int()

    manual_wins = Model.Int(default=0)
    manual_losses = Model.Int(default=0)

    MAX_STATS = 100

    def set_user(self, user_id: Optional[str], robot_level: int = 0) -> None:
        """Set the user key property"""
        k = None if user_id is None else Key(UserModel, user_id)
        self.user = k
        self.robot_level = robot_level

    @classmethod
    def create(cls, user_id: Optional[str], robot_level: int = 0) -> StatsModel:
        """Create a fresh instance with default values"""
        sm = cls()
        sm.set_user(user_id, robot_level)
        sm.timestamp = None
        sm.elo = 1200
        sm.human_elo = 1200
        sm.manual_elo = 1200
        sm.games = 0
        sm.human_games = 0
        sm.manual_games = 0
        sm.score = 0
        sm.human_score = 0
        sm.manual_score = 0
        sm.score_against = 0
        sm.human_score_against = 0
        sm.manual_score_against = 0
        sm.wins = 0
        sm.losses = 0
        sm.human_wins = 0
        sm.human_losses = 0
        sm.manual_wins = 0
        sm.manual_losses = 0
        return sm

    def copy_from(self, src: StatsModel) -> None:
        """Copy data from the src instance"""
        # user and robot_level are assumed to be in place already
        assert hasattr(self, "user")
        assert hasattr(self, "robot_level")
        self.timestamp = src.timestamp
        self.elo = src.elo
        self.human_elo = src.human_elo
        self.manual_elo = src.manual_elo
        self.games = src.games
        self.human_games = src.human_games
        self.manual_games = src.manual_games
        self.score = src.score
        self.human_score = src.human_score
        self.manual_score = src.manual_score
        self.score_against = src.score_against
        self.human_score_against = src.human_score_against
        self.manual_score_against = src.manual_score_against
        self.wins = src.wins
        self.losses = src.losses
        self.human_wins = src.human_wins
        self.human_losses = src.human_losses
        self.manual_wins = src.manual_wins
        self.manual_losses = src.manual_losses

    def populate_dict(self, d: Dict[str, int]) -> None:
        """Copy statistics data to the given dict"""
        d["elo"] = self.elo
        d["human_elo"] = self.human_elo
        d["manual_elo"] = self.manual_elo
        d["games"] = self.games
        d["human_games"] = self.human_games
        d["manual_games"] = self.manual_games
        d["score"] = self.score
        d["human_score"] = self.human_score
        d["manual_score"] = self.manual_score
        d["score_against"] = self.score_against
        d["human_score_against"] = self.human_score_against
        d["manual_score_against"] = self.manual_score_against
        d["wins"] = self.wins
        d["losses"] = self.losses
        d["human_wins"] = self.human_wins
        d["human_losses"] = self.human_losses
        d["manual_wins"] = self.manual_wins
        d["manual_losses"] = self.manual_losses

    @staticmethod
    def dict_key(d: StatsDict) -> str:
        """Return a dictionary key that works for human users and robots"""
        if d["user"] is None:
            return "robot-" + str(d["robot_level"])
        return cast(str, d["user"])

    @staticmethod
    def user_id_from_key(k: Optional[str]) -> Tuple[Optional[str], int]:
        """Decompose a dictionary key into a (user_id, robot_level) tuple"""
        if k is not None and k.startswith("robot-"):
            return (None, int(k[6:]))
        return (k, 0)

    def fetch_user(self) -> Optional[UserModel]:
        """Fetch the user associated with a StatsModel instance"""
        if (user := self.user) is None:
            # Probably a robot
            return None
        return UserModel.fetch(user.id())

    @classmethod
    def _list_by(
        cls,
        prop: ndb.Property,
        makedict: Callable[[StatsModel], StatsDict],
        timestamp: Optional[datetime] = None,
        max_len: int = MAX_STATS,
    ) -> StatsResults:
        """Returns the Elo ratings at the indicated time point (None = now),
        in descending order"""

        # Currently this means a safety_buffer of 160
        max_fetch = int(max_len * 2.6)
        safety_buffer = max_fetch - max_len
        check_false_positives = True

        if timestamp is None:
            timestamp = datetime.utcnow()
            max_fetch = max_len
            # No need to check false positives if querying newest records
            check_false_positives = False

        # Use descending Elo order
        # Ndb doesn't allow us to put an inequality filter on the timestamp here
        # so we need to fetch irrespective of timestamp and manually filter
        q: Query[StatsModel] = cls.query().order(-prop)

        result: Dict[str, StatsDict] = dict()
        CHUNK_SIZE = 100
        lowest_elo: Optional[int] = None

        # The following loop may yield an incorrect result since there may
        # be newer stats records for individual users with lower Elo scores
        # than those scanned to create the list. In other words, there may
        # be false positives on the list (but not false negatives, i.e.
        # there can't be higher Elo scores somewhere that didn't make it
        # to the list). We attempt to address this by fetching 2.5 times the
        # number of requested users, then separately checking each of them for
        # false positives. If we have too many false positives, we don't return
        # the full requested number of result records.

        for sm in iter_q(q, CHUNK_SIZE):
            if sm.timestamp <= timestamp:
                # Within our time range
                d = makedict(sm)
                ukey = cls.dict_key(d)
                if (ukey not in result) or (d["timestamp"] > result[ukey]["timestamp"]):
                    # Fresh entry or newer (and also lower) than the previous one
                    result[ukey] = d
                    if (lowest_elo is None) or d["elo"] < lowest_elo:
                        lowest_elo = d["elo"]
                    if len(result) >= max_fetch:
                        # We have all the requested entries: done
                        break  # From for loop

        false_pos = 0
        # Do another loop through the result to check for false positives
        if check_false_positives:
            for ukey, d in result.items():
                sm = cls.newest_before(timestamp, d["user"], d["robot_level"])
                assert sm is not None  # We should always have an entity here
                nd = makedict(sm)
                # This may be None if a default record was created
                nd_ts = nd["timestamp"]
                if (nd_ts is not None) and nd_ts > d["timestamp"]:
                    # This is a newer one than we have already
                    # It must be a lower Elo score, or we would already have it
                    assert nd["elo"] <= d["elo"]
                    assert lowest_elo is not None
                    if nd["elo"] < lowest_elo:
                        # The entry didn't belong on the list at all
                        false_pos += 1
                    # Replace the entry with the newer one (which will lower it)
                    result[ukey] = nd
            logging.info(
                "False positives are {0}, safety buffer is {1}".format(
                    false_pos, safety_buffer
                )
            )

        if false_pos > safety_buffer:
            # Houston, we have a problem: the original list was way off
            # and the corrections are not sufficient;
            # truncate the result accordingly
            logging.error("False positives caused ratings list to be truncated")
            max_len -= false_pos - safety_buffer
            if max_len < 0:
                max_len = 0

        # Sort in descending order by Elo, and finally rank and return the result
        result_list = sorted(result.values(), key=lambda x: -x["elo"])[0:max_len]
        for ix, d in enumerate(result_list):
            d["rank"] = ix + 1

        return result_list

    @classmethod
    def list_elo(
        cls, timestamp: Optional[datetime] = None, max_len: int = MAX_STATS
    ) -> StatsResults:
        """Return the top Elo-rated users for all games (including robots)"""

        def _makedict(sm: StatsModel) -> StatsDict:
            return StatsDict(
                user=None if sm.user is None else sm.user.id(),
                robot_level=sm.robot_level or 0,
                timestamp=sm.timestamp,
                games=sm.games,
                elo=sm.elo,
                score=sm.score,
                score_against=sm.score_against,
                wins=sm.wins,
                losses=sm.losses,
                rank=0,
            )

        return cls._list_by(
            cast(ndb.Property, StatsModel.elo), _makedict, timestamp, max_len
        )

    @classmethod
    def list_human_elo(
        cls, timestamp: Optional[datetime] = None, max_len: int = MAX_STATS
    ) -> StatsResults:
        """Return the top Elo-rated users for human-only games"""

        def _makedict(sm: StatsModel) -> StatsDict:
            return StatsDict(
                user=None if sm.user is None else sm.user.id(),
                robot_level=sm.robot_level or 0,
                timestamp=sm.timestamp,
                games=sm.human_games,
                elo=sm.human_elo,
                score=sm.human_score,
                score_against=sm.human_score_against,
                wins=sm.human_wins,
                losses=sm.human_losses,
                rank=0,
            )

        return cls._list_by(
            cast(ndb.Property, StatsModel.human_elo), _makedict, timestamp, max_len
        )

    @classmethod
    def list_manual_elo(
        cls, timestamp: Optional[datetime] = None, max_len: int = MAX_STATS
    ) -> StatsResults:
        """Return the top Elo-rated users for manual-only games"""

        def _makedict(sm: StatsModel) -> StatsDict:
            return StatsDict(
                user=None if sm.user is None else sm.user.id(),
                robot_level=sm.robot_level or 0,
                timestamp=sm.timestamp,
                games=sm.manual_games,
                elo=sm.manual_elo,
                score=sm.manual_score,
                score_against=sm.manual_score_against,
                wins=sm.manual_wins,
                losses=sm.manual_losses,
                rank=0,
            )

        return cls._list_by(
            cast(ndb.Property, StatsModel.manual_elo), _makedict, timestamp, max_len
        )

    _NB_CACHE: Dict[Tuple[Optional[str], int], Dict[datetime, StatsModel]] = dict()
    _NB_CACHE_STATS: Dict[str, int] = dict(hits=0, misses=0)

    @classmethod
    def clear_cache(cls) -> None:
        """Reset the cache"""
        cls._NB_CACHE = dict()
        cls._NB_CACHE_STATS = dict(hits=0, misses=0)

    @classmethod
    def log_cache_stats(cls) -> None:
        """Show cache statistics in the log"""
        hits = cls._NB_CACHE_STATS["hits"]
        misses = cls._NB_CACHE_STATS["misses"]
        total = hits + misses
        logging.info(
            "Cache hits {0} or {1:.2f}%".format(
                hits, 100.0 * hits / total if total != 0 else 0.0
            )
        )
        logging.info(
            "Cache misses {0} or {1:.2f}%".format(
                misses, 100.0 * misses / total if total != 0 else 0.0
            )
        )

    @classmethod
    def newest_before(
        cls, ts: datetime, user_id: Optional[str], robot_level: int = 0
    ) -> StatsModel:
        """Returns the newest available stats record for the user at or before the given time"""
        cache = cls._NB_CACHE
        key = (user_id, robot_level)
        if ts:
            if key in cache:
                for c_ts, c_val in cache[key].items():
                    if c_ts >= ts >= c_val.timestamp:
                        cls._NB_CACHE_STATS["hits"] += 1
                        sm = cls.create(user_id, robot_level)
                        sm.copy_from(c_val)
                        return sm
            else:
                d: Dict[datetime, StatsModel] = dict()
                cache[key] = d
        cls._NB_CACHE_STATS["misses"] += 1
        sm = cls.create(user_id, robot_level)
        if ts:
            # Try to query using the timestamp
            if user_id is None:
                k = None
            else:
                k = Key(UserModel, user_id)
            # Use a common query structure and index for humans and robots
            q = cls.query(
                ndb.AND(StatsModel.user == k, StatsModel.robot_level == robot_level)
            )
            q = q.filter(StatsModel.timestamp <= ts).order(
                -cast(int, StatsModel.timestamp)
            )
            sm_before = q.get()
            if sm_before is not None:
                # Found: copy the stats
                sm.copy_from(sm_before)
            cache[key][ts] = sm
        return sm

    @classmethod
    def newest_for_user(cls, user_id: str) -> Optional[StatsModel]:
        """Returns the newest available stats record for the user"""
        if user_id is None:
            return None
        k = Key(UserModel, user_id)
        # Use a common query structure and index for humans and robots
        q = cls.query(ndb.AND(StatsModel.user == k, StatsModel.robot_level == 0)).order(
            -cast(int, StatsModel.timestamp)
        )
        sm = q.get()
        if sm is None:
            # No record in the database: return a default entity
            sm = cls.create(user_id)
        return sm

    @classmethod
    def delete_ts(cls, timestamp: datetime) -> None:
        """Delete all stats records at a particular timestamp"""
        delete_multi(cls.query(StatsModel.timestamp == timestamp).iter(keys_only=True))


class RatingModel(Model):

    """Models tables of user ratings"""

    # Typically "all" or "human"
    kind = Model.Str()

    # The ordinal rank
    rank = Model.Int()

    user = Model.OptionalDbKey(kind=UserModel, indexed=False)

    robot_level = Model.Int(default=0, indexed=False)

    games = Model.Int(default=0)
    elo = Model.Int(default=1200)
    score = Model.Int(default=0)
    score_against = Model.Int(default=0)
    wins = Model.Int(default=0)
    losses = Model.Int(default=0)

    rank_yesterday = Model.Int(default=0)
    games_yesterday = Model.Int(default=0)
    elo_yesterday = Model.Int(default=1200)
    score_yesterday = Model.Int(default=0)
    score_against_yesterday = Model.Int(default=0)
    wins_yesterday = Model.OptionalInt(default=0)
    losses_yesterday = Model.Int(default=0)

    rank_week_ago = Model.Int(default=0)
    games_week_ago = Model.Int(default=0)
    elo_week_ago = Model.Int(default=1200)
    score_week_ago = Model.Int(default=0)
    score_against_week_ago = Model.Int(default=0)
    wins_week_ago = Model.Int(default=0)
    losses_week_ago = Model.Int(default=0)

    rank_month_ago = Model.Int(default=0)
    games_month_ago = Model.Int(default=0)
    elo_month_ago = Model.Int(default=1200)
    score_month_ago = Model.Int(default=0)
    score_against_month_ago = Model.Int(default=0)
    wins_month_ago = Model.Int(default=0)
    losses_month_ago = Model.Int(default=0)

    @classmethod
    def get_or_create(cls, kind: str, rank: int) -> RatingModel:
        """Get an existing entity or create a new one if it doesn't exist"""
        k = Key(cls, kind + ":" + str(rank))
        rm = k.get()
        if rm is None:
            # Did not already exist in the database:
            # create a fresh instance
            rm = cls(id=kind + ":" + str(rank))
        rm.kind = kind
        rm.rank = rank
        return rm

    def assign(self, dict_args: StatsDict) -> None:
        """Populate attributes from a dict"""
        for key, val in dict_args.items():
            if key == "user":
                # Re-pack the user id into a key
                setattr(self, key, None if val is None else Key(UserModel, val))
            else:
                setattr(self, key, val)

    @classmethod
    def list_rating(cls, kind: str) -> Iterator[Dict[str, Any]]:
        """Iterate through the rating table of a given kind, in ascending order by rank"""
        CHUNK_SIZE = 100
        q: Query[RatingModel] = cls.query(RatingModel.kind == kind).order(
            RatingModel.rank
        )
        for rm in iter_q(q, CHUNK_SIZE, limit=100):
            v: Dict[str, Union[str, Optional[int]]] = dict(
                rank=rm.rank,
                games=rm.games,
                elo=rm.elo,
                score=rm.score,
                score_against=rm.score_against,
                wins=rm.wins,
                losses=rm.losses,
                rank_yesterday=rm.rank_yesterday,
                games_yesterday=rm.games_yesterday,
                elo_yesterday=rm.elo_yesterday,
                score_yesterday=rm.score_yesterday,
                score_against_yesterday=rm.score_against_yesterday,
                wins_yesterday=rm.wins_yesterday,
                losses_yesterday=rm.losses_yesterday,
                rank_week_ago=rm.rank_week_ago,
                games_week_ago=rm.games_week_ago,
                elo_week_ago=rm.elo_week_ago,
                score_week_ago=rm.score_week_ago,
                score_against_week_ago=rm.score_against_week_ago,
                wins_week_ago=rm.wins_week_ago,
                losses_week_ago=rm.losses_week_ago,
                rank_month_ago=rm.rank_month_ago,
                games_month_ago=rm.games_month_ago,
                elo_month_ago=rm.elo_month_ago,
                score_month_ago=rm.score_month_ago,
                score_against_month_ago=rm.score_against_month_ago,
                wins_month_ago=rm.wins_month_ago,
                losses_month_ago=rm.losses_month_ago,
            )

            # Stringify a user id
            if rm.user is None:
                if rm.robot_level < 0:
                    v["userid"] = ""
                else:
                    v["userid"] = "robot-" + str(rm.robot_level)
            else:
                v["userid"] = rm.user.id()

            yield v

    @classmethod
    def delete_all(cls) -> None:
        """Delete all ratings records"""
        delete_multi(cls.query().iter(keys_only=True))


class ChatModel(Model):

    """Models chat communications between users"""

    # The channel (conversation) identifier
    # This is a string, either of the form 'game:' + uuid for an in-game chat,
    # or of the form 'user:' + user_id_1 + ':' + user_id_2
    # where user_id_1 < user_id_2.
    channel = Model.Str()

    # The user originating this chat message
    user = Model.DbKey(kind=UserModel)

    # The recipient of the message
    recipient = Model.OptionalDbKey(kind=UserModel)

    # The timestamp of this chat message
    timestamp = Model.Datetime(indexed=True, auto_now_add=True)

    # The actual message - by convention, an empty msg from a user means that
    # the user has seen all older messages
    msg = Model.Str()

    def get_recipient(self) -> Optional[str]:
        """ Return the user id of the message recipient """
        return None if self.recipient is None else self.recipient.id()

    @classmethod
    def list_conversation(
        cls, channel: str, maxlen: int = 250
    ) -> Iterator[Dict[str, Any]]:
        """Return the newest items in a conversation"""
        CHUNK_SIZE = 100
        q = cls.query(ChatModel.channel == channel).order(
            -cast(int, ChatModel.timestamp)
        )
        count = 0
        for cm in iter_q(q, CHUNK_SIZE):
            if cm.msg:
                # Don't return empty messages (read markers)
                yield dict(
                    user=cm.user.id(),
                    recipient=cm.get_recipient(),
                    ts=cm.timestamp,
                    msg=cm.msg,
                )
                count += 1
                if count >= maxlen:
                    break

    @classmethod
    def check_conversation(cls, channel: str, userid: Optional[str]) -> bool:
        """Returns True if there are unseen messages in the conversation"""
        CHUNK_SIZE = 40
        q = cls.query(ChatModel.channel == channel).order(
            -cast(int, ChatModel.timestamp)
        )
        for cm in iter_q(q, CHUNK_SIZE):
            if (cm.user.id() != userid) and cm.msg:
                # Found a message originated by the other user
                return True
            if (cm.user.id() == userid) and not cm.msg:
                # Found an 'already seen' indicator (empty message) from the querying user
                return False
        # Gone through the whole thread without finding an unseen message
        return False

    @classmethod
    def add_msg(
        cls,
        channel: str,
        from_user: str,
        to_user: str,
        msg: str,
        timestamp: Optional[datetime] = None,
    ) -> datetime:
        """Adds a message to a chat conversation on a channel"""
        cm = cls()
        cm.channel = channel
        cm.user = Key(UserModel, from_user)
        cm.recipient = Key(UserModel, to_user)
        cm.msg = msg
        cm.timestamp = timestamp or datetime.utcnow()
        cm.put()
        # Return the message timestamp
        return cm.timestamp

    @classmethod
    def add_msg_in_game(
        cls,
        game_uuid: str,
        from_user: str,
        to_user: str,
        msg: str,
        timestamp: Optional[datetime] = None,
    ) -> datetime:
        """ Adds a message to an in-game conversation """
        channel = f"game:{game_uuid}"
        return cls.add_msg(channel, from_user, to_user, msg, timestamp)

    @classmethod
    def add_msg_between_users(
        cls,
        from_user: str,
        to_user: str,
        msg: str,
        timestamp: Optional[datetime] = None,
    ) -> datetime:
        """ Adds a message to a chat conversation between two users """
        # By convention, the lower user id comes before
        # the higher one in the channel string
        if from_user < to_user:
            channel = f"user:{from_user}:{to_user}"
        else:
            channel = f"user:{to_user}:{from_user}"
        return cls.add_msg(channel, from_user, to_user, msg, timestamp)

    @classmethod
    def chat_history(
        cls,
        for_user: str,
        maxlen: int = 20,
    ) -> Iterator[Dict[str, Any]]:
        """ Return the chat history for a user """
        CHUNK_SIZE = 50

        # Create two queries, on the user and recipient fields,
        # and interleave their results by timestamp
        user = Key(UserModel, for_user)
        q1 = cls.query(ChatModel.user == user).order(
            -cast(int, ChatModel.timestamp)
        )
        q2 = cls.query(ChatModel.recipient == user).order(
            -cast(int, ChatModel.timestamp)
        )
        # Count of unique counterparties that we have already returned
        count = 0
        # Set of opponents (chat counterparties) that we have already returned
        returned: Set[str] = set()

        i1 = iter_q(q1, CHUNK_SIZE)
        i2 = iter_q(q2, CHUNK_SIZE)
        c1 = next(i1, None)
        c2 = next(i2, None)

        def d(cm: ChatModel, opp: str) -> Dict[str, Any]:
            """ Create a chat history entry to be returned """
            nonlocal count
            nonlocal returned
            count += 1
            returned.add(opp)
            return dict(
                user=opp,
                ts=cm.timestamp,
                # A chat message is unread if it was not originated by
                # this user, and it is not an empty message (read marker)
                # This function only sees the newest message in each thread,
                # so a more fancy state check is not needed
                unread=(cm.user != for_user) and cm.msg != "",
            )

        # We loop until both iterators are exhausted, or we have returned
        # maxlen unique history entries
        while (c1 or c2) and (count < maxlen):
            pick: int = 0
            if c1 and c2:
                if c1.timestamp > c2.timestamp:
                    # The first iterator has a newer message than the second
                    pick = 1
                else:
                    # The second iterator has a newer message than the first
                    pick = 2
            elif c1:
                pick = 1
            elif c2:
                pick = 2
            if pick == 1:
                assert c1 is not None
                opp = c1.recipient
                if opp and opp.id() not in returned:
                    # Haven't returned this opponent/counterparty before: do it now
                    yield d(c1, opp.id())
                # Go to the next, older message
                c1 = next(i1, None)
            elif pick == 2:
                assert c2 is not None
                opp = c2.user
                if opp.id() not in returned:
                    # Haven't returned this opponent/counterparty before: do it now
                    yield d(c2, opp.id())
                # Go to the next, older message
                c2 = next(i2, None)
            else:
                assert False


class ZombieModel(Model):

    """Models finished games that have not been seen by one of the players"""

    # The zombie game
    game = Model.DbKey(kind=GameModel)
    # The player that has not seen the result
    player = Model.DbKey(kind=UserModel)

    def set_player(self, user_id: Optional[str]) -> None:
        """Set the player's user id"""
        self.player = None if user_id is None else Key(UserModel, user_id)

    def set_game(self, game_id: Optional[str]) -> None:
        """Set the game id"""
        self.game = None if game_id is None else Key(GameModel, game_id)

    @classmethod
    def add_game(cls, game_id: Optional[str], user_id: Optional[str]) -> None:
        """Add a zombie game that has not been seen by the player in question"""
        zm = cls()
        zm.set_game(game_id)
        zm.set_player(user_id)
        zm.put()

    @classmethod
    def del_game(cls, game_id: Optional[str], user_id: Optional[str]) -> None:
        """Delete a zombie game after the player has seen it"""
        kg = Key(GameModel, game_id)
        kp = Key(UserModel, user_id)
        q = cls.query(ZombieModel.game == kg).filter(ZombieModel.player == kp)
        zmk = q.get(keys_only=True)
        if not zmk:
            # No such game in the zombie list
            return
        zmk.delete()

    @classmethod
    def list_games(cls, user_id: str) -> Iterator[Dict[str, Any]]:
        """List all zombie games for the given player"""
        assert user_id is not None
        if user_id is None:
            return
        k = Key(UserModel, user_id)
        q = cls.query(ZombieModel.player == k)

        def z_callback(zm: ZombieModel) -> Optional[Dict[str, Any]]:
            """Map a ZombieModel entity to a game descriptor"""
            if not zm.game:
                return None
            gm = GameModel.fetch(zm.game.id())
            if gm is None:
                return None
            u0 = None if gm.player0 is None else gm.player0.id()
            u1 = None if gm.player1 is None else gm.player1.id()
            if u0 == user_id:
                # Player 0 is the source player, 1 is the opponent
                opp = u1
                sc0, sc1 = gm.score0, gm.score1
            else:
                # Player 1 is the source player, 0 is the opponent
                assert u1 == user_id
                opp = u0
                sc1, sc0 = gm.score0, gm.score1
            return dict(
                uuid=zm.game.id(),
                ts=gm.ts_last_move or gm.timestamp,
                opp=opp,
                robot_level=gm.robot_level,
                sc0=sc0,
                sc1=sc1,
            )

        for zm in q.fetch():
            if (zd := z_callback(zm)) is not None:
                yield zd


class PromoModel(Model):

    """Models promotions displayed to players"""

    # The player that saw the promotion
    player = Model.DbKey(kind=UserModel)
    # The promotion id
    promotion = Model.Str()
    # The timestamp
    timestamp = Model.Datetime(auto_now_add=True)

    def set_player(self, user_id: str) -> None:
        """Set the player's user id"""
        assert user_id is not None
        self.player = Key(UserModel, user_id)

    @classmethod
    def add_promotion(cls, user_id: str, promotion: str) -> None:
        """Add a zombie game that has not been seen by the player in question"""
        pm = cls()
        pm.set_player(user_id)
        pm.promotion = promotion
        pm.put()

    @classmethod
    def list_promotions(
        cls, user_id: Optional[str], promotion: str
    ) -> Iterator[datetime]:
        """Return a list of timestamps for when the given promotion has been displayed"""
        assert user_id is not None
        if user_id is None:
            return
        k = Key(UserModel, user_id)
        q = cls.query(PromoModel.player == k).filter(PromoModel.promotion == promotion)

        for pm in q.fetch(projection=["timestamp"]):
            yield pm.timestamp


class CompletionModel(Model):

    """Models the successful completion of stats or ratings runs"""

    # The type of process that was completed, usually 'stats' or 'ratings'
    proctype = Model.Str()
    # The timestamp of the successful run
    timestamp = Model.Datetime(auto_now_add=True)

    # The from-to range of the successful process
    ts_from = Model.Datetime()
    ts_to = Model.Datetime()

    # True if successful completion (the default); included for future expansion
    success = Model.Bool()

    # The reason for failure, if any
    reason = Model.Str()

    @classmethod
    def add_completion(cls, proctype: str, ts_from: datetime, ts_to: datetime) -> None:
        """Add a zombie game that has not been seen by the player in question"""
        cm = cls()
        cm.proctype = proctype
        cm.ts_from = ts_from
        cm.ts_to = ts_to
        cm.success = True
        cm.reason = ""
        cm.put()

    @classmethod
    def add_failure(
        cls, proctype: str, ts_from: datetime, ts_to: datetime, reason: str
    ) -> None:
        """Add a zombie game that has not been seen by the player in question"""
        cm = cls()
        cm.proctype = proctype
        cm.ts_from = ts_from
        cm.ts_to = ts_to
        cm.success = False
        cm.reason = reason
        cm.put()
