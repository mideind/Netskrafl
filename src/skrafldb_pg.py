"""
Skrafldb PostgreSQL implementation - facade over protocol repositories

Copyright © 2025 Miðeind ehf.

This module implements the skrafldb API (the same interface as skrafldb_ndb.py)
by delegating to the PostgreSQL repositories in src/db/postgresql/. No database
logic is duplicated; all operations flow through the same repositories that
the test harness uses.

Architecture:
    Application code
      └─ from skrafldb import UserModel, GameModel, ...
           └─ skrafldb.py (facade selector)
                └─ DATABASE_BACKEND=postgresql → this module
                     └─ get_db() → PostgreSQLBackend
                          └─ PG repositories (already implemented)
                               └─ SQLAlchemy → PostgreSQL
"""

from __future__ import annotations

from typing import (
    Any,
    Dict,
    Generic,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    TYPE_CHECKING,
    TypeVar,
    cast,
)

import logging
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import wraps
from itertools import zip_longest

from config import (
    DEFAULT_LOCALE,
    DEFAULT_THUMBNAIL_SIZE,
    ESTABLISHED_MARK,
)

# Re-export all shared type definitions from the NDB module.
# These TypedDicts and dataclasses are backend-agnostic data shapes.
from skrafldb_ndb import (
    # Type definitions (shared across backends)
    PrefsDict,
    ChallengeTuple,
    StatsDict,
    StatsResults,
    LiveGameDict,
    FinishedGameDict,
    ZombieGameDict,
    ChatModelHistoryDict,
    ListPrefixDict,
    RatingDict,
    RatingForLocaleDict,
    EloDict,
    DEFAULT_ELO_DICT,  # noqa: F401 - re-exported via skrafldb.py
)


if TYPE_CHECKING:
    from src.db.protocols import (
        UserEntityProtocol,
        GameEntityProtocol,
        EloEntityProtocol,
        StatsEntityProtocol,
        RiddleEntityProtocol,
    )

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Transaction decorator (no-op for PostgreSQL)
# ---------------------------------------------------------------------------

def transactional(**_kw: Any) -> Any:
    """No-op replacement for ndb.transactional() on the PostgreSQL backend.

    The PostgreSQL WSGI middleware already wraps each request in a transaction,
    so there is no need for an additional transactional wrapper here."""

    def decorator(fn: Any) -> Any:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)
        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Database access helper
# ---------------------------------------------------------------------------

def _get_db():
    """Get the current request-scoped PostgreSQL backend."""
    from src.db import get_db
    return get_db()


# ---------------------------------------------------------------------------
# Key adapter
# ---------------------------------------------------------------------------

class Key:
    """Lightweight NDB Key-compatible adapter for PostgreSQL.

    Supports the NDB Key API patterns used by application code:
        Key(ModelClass, id)
        Key(M1, id1, M2, id2)  -- ancestor keys
        key.id() -> str
        key.parent() -> Optional[Key]
        key.kind() -> str
    """

    def __init__(self, *path_args: Any) -> None:
        # Normalise path: [(kind_name, id), ...]
        self._pairs: List[Tuple[str, str]] = []
        i = 0
        args = list(path_args)
        while i < len(args):
            kind = args[i]
            if isinstance(kind, type):
                kind = kind.__name__
            i += 1
            if i < len(args):
                self._pairs.append((kind, str(args[i])))
                i += 1
            else:
                # Kind without id (shouldn't normally happen)
                self._pairs.append((kind, ""))

    def id(self) -> str:
        """Return the id component of the key."""
        if self._pairs:
            return self._pairs[-1][1]
        return ""

    def kind(self) -> str:
        """Return the kind (model name) of the key."""
        if self._pairs:
            return self._pairs[-1][0]
        return ""

    def parent(self) -> Optional[Key]:
        """Return the parent key, if any."""
        if len(self._pairs) > 1:
            k = Key.__new__(Key)
            k._pairs = self._pairs[:-1]
            return k
        return None

    def get(self, *args: Any, **kwargs: Any) -> Any:
        """Fetch the entity referenced by this key."""
        # Not all code paths use this; provide minimal support
        kind = self.kind()
        key_id = self.id()
        db = _get_db()
        if kind == "UserModel":
            return db.users.get_by_id(key_id)
        if kind == "GameModel":
            return db.games.get_by_id(key_id)
        return None

    def delete(self, *args: Any, **kwargs: Any) -> None:
        """Delete the entity referenced by this key."""
        kind = self.kind()
        key_id = self.id()
        db = _get_db()
        if kind == "UserModel":
            db.users.delete(key_id)
        elif kind == "GameModel":
            db.games.delete(key_id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Key):
            return self._pairs == other._pairs
        return NotImplemented

    def __hash__(self) -> int:
        return hash(tuple(self._pairs))

    def __repr__(self) -> str:
        return f"Key({self._pairs!r})"


# ---------------------------------------------------------------------------
# Client / Context / Unique stubs
# ---------------------------------------------------------------------------

class Client:
    """No-op NDB Client replacement for PostgreSQL.

    PostgreSQL session management is handled by the WSGI middleware
    (db_wsgi_middleware) rather than explicit client contexts.
    """

    def __init__(self) -> None:
        pass

    @classmethod
    @contextmanager
    def get_context(cls) -> Iterator[None]:
        """No-op context manager (PG uses WSGI middleware)."""
        yield


class Context:
    """No-op NDB Context replacement for PostgreSQL."""

    def __init__(self) -> None:
        pass

    @staticmethod
    def disable_cache() -> None:
        """No-op: PostgreSQL doesn't use NDB caching."""
        pass

    @staticmethod
    def disable_global_cache() -> None:
        """No-op: PostgreSQL doesn't use NDB caching."""
        pass


class Unique:
    """Unique ID generator, compatible with the NDB version."""

    def __init__(self) -> None:
        pass

    @staticmethod
    def id() -> str:
        """Generate a unique id string."""
        return str(uuid.uuid1())


# ---------------------------------------------------------------------------
# NDB compatibility shim
# ---------------------------------------------------------------------------

class _NdbCompat:
    """Minimal shim for code that imports `ndb` from skrafldb and uses
    ndb.AND(...), ndb.OR(...), ndb.Key(...) etc."""

    @staticmethod
    def AND(*conditions: Any) -> Tuple[str, Tuple[Any, ...]]:
        return ("AND", conditions)

    @staticmethod
    def OR(*conditions: Any) -> Tuple[str, Tuple[Any, ...]]:
        return ("OR", conditions)

    @staticmethod
    def Key(*args: Any) -> Key:
        return Key(*args)


ndb = _NdbCompat()


# ---------------------------------------------------------------------------
# interleave helper (also re-exported from skrafldb_ndb, but defined here
# for completeness)
# ---------------------------------------------------------------------------

_T = TypeVar("_T")


def interleave(iter1: Iterable[_T], iter2: Iterable[_T]) -> Iterator[_T]:
    """Interleave two iterables, returning elements from each until both
    are exhausted."""
    for item1, item2 in zip_longest(iter1, iter2, fillvalue=None):
        if item1 is not None:
            yield item1
        if item2 is not None:
            yield item2


# ---------------------------------------------------------------------------
# Query / Future / Model base stubs
# ---------------------------------------------------------------------------

_T_Model = TypeVar("_T_Model")


class Query(Generic[_T_Model]):
    """Minimal query stub.

    Complex NDB-style query building (used in skraflstats.py/admin.py)
    is not yet supported for Phase 1. The Model facade classes provide
    direct static methods that delegate to the PG repositories instead.
    """

    def order(self, *args: Any, **kwargs: Any) -> Query[_T_Model]:
        return self

    def filter(self, *args: Any, **kwargs: Any) -> Query[_T_Model]:
        return self

    def fetch(self, *args: Any, **kwargs: Any) -> Sequence[_T_Model]:
        return []

    def fetch_async(self, *args: Any, **kwargs: Any) -> Future[_T_Model]:
        return Future([])

    def fetch_page(
        self, *args: Any, **kwargs: Any
    ) -> Tuple[Sequence[_T_Model], Any, bool]:
        return ([], None, False)

    def get(self, *args: Any, **kwargs: Any) -> Optional[_T_Model]:
        return None

    def count(self, *args: Any, **kwargs: Any) -> int:
        return 0

    def iter(self, *args: Any, **kwargs: Any) -> Iterator[_T_Model]:
        return iter([])


class Future(Generic[_T]):
    """Minimal Future stub for API compatibility."""

    def __init__(self, result: Any = None) -> None:
        self._result = result if result is not None else []

    def get_result(self) -> List[_T]:
        return self._result

    @staticmethod
    def wait_all(futures: Sequence[Future[_T]]) -> None:
        pass


class Model:
    """Base Model stub for PostgreSQL.

    Provides the type helper statics (Str, Int, Bool, etc.) that are
    used as class-level declarations in skrafldb_ndb.py. Since the PG
    facade classes don't use NDB property descriptors, these are no-ops.
    """

    @property
    def key(self) -> Key:
        """Return the key of this entity."""
        return Key(type(self).__name__, getattr(self, "_id", ""))

    def put(self, **kwargs: Any) -> Key:
        """Persist this entity. Subclasses override."""
        return self.key

    @classmethod
    def get_by_id(
        cls, id: Any, *args: Any, **kwargs: Any
    ) -> Optional[Any]:
        return None

    @classmethod
    def query(cls, *args: Any, **kwargs: Any) -> Query[Any]:
        return Query()


def iter_q(
    q: Query[_T_Model],
    chunk_size: int = 50,
    limit: int = 0,
    projection: Optional[List[str]] = None,
) -> Iterator[_T_Model]:
    """Iterate through a query. For PG this is a simple delegation."""
    count = 0
    for item in q.iter():
        yield item
        count += 1
        if limit and count >= limit:
            return


def put_multi(recs: Iterable[Any]) -> None:
    """Persist multiple entities."""
    for rec in recs:
        if hasattr(rec, "put"):
            rec.put()


def delete_multi(keys: Iterable[Key]) -> None:
    """Delete multiple entities by key."""
    for k in keys:
        k.delete()


# ---------------------------------------------------------------------------
# _model_property descriptor
# ---------------------------------------------------------------------------

def _model_property(name: str, default: Any = None) -> property:
    """Descriptor for Model facade properties.

    Reads from the mutation dict (_attrs) first, then falls back to the
    wrapped protocol entity, then to the default.
    """
    def getter(self: Any) -> Any:
        if name in self._attrs:
            return self._attrs[name]
        if self._entity is not None:
            return getattr(self._entity, name, default)
        return default

    def setter(self: Any, value: Any) -> None:
        self._attrs[name] = value

    return property(getter, setter)


# ===========================================================================
# Model Facades
# ===========================================================================


class UserModel:
    """PostgreSQL facade for UserModel, delegating to UserRepository."""

    # Provide the same class-level attribute names so that code doing
    # UserModel.nickname, UserModel.elo, etc. for query filters gets
    # a string sentinel rather than raising AttributeError.
    # (Full query-builder support is deferred to Phase 2.)

    def __init__(self, id: Optional[str] = None, **kwargs: Any) -> None:
        self._id = id or ""
        self._entity: Optional[UserEntityProtocol] = None
        self._attrs: Dict[str, Any] = dict(kwargs)

    @classmethod
    def _from_entity(cls, entity: UserEntityProtocol) -> UserModel:
        """Wrap a PG User model as a UserModel facade."""
        um = cls.__new__(cls)
        um._id = entity.key_id
        um._entity = entity
        um._attrs = {}
        return um

    @property
    def key(self) -> Key:
        return Key(UserModel, self._id)

    def user_id(self) -> str:
        return self._id

    # --- Properties ---
    nickname = _model_property("nickname", "")
    email = _model_property("email", "")
    image: Any = _model_property("image", "")
    image_blob = _model_property("image_blob", None)
    account = _model_property("account", None)
    plan = _model_property("plan", None)
    nick_lc = _model_property("nick_lc", None)
    name_lc = _model_property("name_lc", None)
    inactive = _model_property("inactive", False)
    locale = _model_property("locale", DEFAULT_LOCALE)
    location = _model_property("location", "")
    prefs = _model_property("prefs", {})
    timestamp = _model_property("timestamp", None)
    last_login = _model_property("last_login", None)
    ready = _model_property("ready", True)
    ready_timed = _model_property("ready_timed", True)
    chat_disabled = _model_property("chat_disabled", False)
    elo = _model_property("elo", 0)
    human_elo = _model_property("human_elo", 0)
    manual_elo = _model_property("manual_elo", 0)
    highest_score = _model_property("highest_score", 0)
    highest_score_game = _model_property("highest_score_game", None)
    best_word = _model_property("best_word", None)
    best_word_score = _model_property("best_word_score", 0)
    best_word_game = _model_property("best_word_game", None)
    games = _model_property("games", 0)

    def put(self, **kwargs: Any) -> Key:
        """Persist changes to the database."""
        db = _get_db()
        if self._entity is not None:
            # Update existing entity
            if self._attrs:
                db.users.update(self._entity, **self._attrs)
                self._attrs.clear()
        else:
            # Create new entity - this shouldn't normally be called
            # directly; use UserModel.create() instead
            db.users.create(
                user_id=self._id,
                account=self._attrs.get("account", ""),
                email=self._attrs.get("email", ""),
                nickname=self._attrs.get("nickname", ""),
                image=self._attrs.get("image", ""),
                preferences=self._attrs.get("prefs"),
                locale=self._attrs.get("locale"),
            )
        return self.key

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
    ) -> Tuple[str, PrefsDict]:
        """Create a new user."""
        db = _get_db()
        return db.users.create(
            user_id=user_id,
            account=account,
            email=email,
            nickname=nickname,
            image=image,
            preferences=preferences,
            locale=locale,
        )

    @classmethod
    def fetch(cls, user_id: str) -> Optional[UserModel]:
        """Fetch a user entity by id."""
        db = _get_db()
        entity = db.users.get_by_id(user_id)
        if entity is None:
            return None
        return cls._from_entity(entity)

    @classmethod
    def fetch_account(cls, account: str) -> Optional[UserModel]:
        """Fetch a user by OAuth2 account id."""
        if not account:
            return None
        db = _get_db()
        entity = db.users.get_by_account(account)
        if entity is None:
            return None
        return cls._from_entity(entity)

    @classmethod
    def fetch_nickname(cls, nickname: str, ignore_case: bool) -> Optional[UserModel]:
        """Fetch a user by nickname."""
        db = _get_db()
        entity = db.users.get_by_nickname(nickname, ignore_case)
        if entity is None:
            return None
        return cls._from_entity(entity)

    @classmethod
    def fetch_email(cls, email: str) -> Optional[UserModel]:
        """Fetch a user by email."""
        if not email:
            return None
        db = _get_db()
        entity = db.users.get_by_email(email)
        if entity is None:
            return None
        return cls._from_entity(entity)

    @classmethod
    def fetch_multi(cls, user_ids: Iterable[str]) -> List[Optional[UserModel]]:
        """Fetch multiple user entities by id list."""
        db = _get_db()
        entities = db.users.get_multi(list(user_ids))
        return [
            cls._from_entity(e) if e is not None else None
            for e in entities
        ]

    def get_image(self) -> Tuple[str, Optional[bytes]]:
        """Get image data for the user."""
        img = self.image
        if img and img.startswith("/image?"):
            img = ""
        return img, self.image_blob

    def set_image(self, image: str, image_blob: Optional[bytes]) -> None:
        """Set image data for the user."""
        if image and image.startswith("/image?"):
            image = ""
        self.image = image
        self.image_blob = image_blob
        self.put()

    @classmethod
    def count(cls) -> int:
        """Return a count of user entities."""
        db = _get_db()
        return db.users.count()

    @classmethod
    def filter_locale(cls, q: Any, locale: Optional[str]) -> Any:
        """Filter by locale (stub - query builder deferred to Phase 2)."""
        return q

    @classmethod
    def list_prefix(
        cls, prefix: str, max_len: int = 50, locale: Optional[str] = None
    ) -> Iterator[ListPrefixDict]:
        """Query for users with a name or nick matching the given prefix."""
        if not prefix:
            return
        db = _get_db()
        for info in db.users.list_prefix(prefix, max_len, locale):
            yield ListPrefixDict(
                id=info.id,
                nickname=info.nickname,
                prefs=info.prefs if info.prefs is not None else cast(PrefsDict, {}),
                timestamp=info.timestamp or datetime.now(UTC),
                ready=info.ready,
                ready_timed=info.ready_timed,
                elo=info.elo,
                human_elo=info.human_elo,
                manual_elo=info.manual_elo,
                image=info.image,
                has_image_blob=info.has_image_blob,
            )

    @classmethod
    def list_similar_elo(
        cls, elo: int, max_len: int = 40, locale: Optional[str] = None
    ) -> List[Tuple[str, EloDict]]:
        """List users with a similar Elo rating."""
        db = _get_db()
        result = db.users.list_similar_elo(elo, max_len, locale)
        # Convert protocol EloDict to skrafldb_ndb EloDict
        return [
            (uid, EloDict(ed.elo, ed.human_elo, ed.manual_elo))
            for uid, ed in result
        ]

    @classmethod
    def delete_related_entities(cls, user_id: str) -> None:
        """Delete entities related to a user."""
        if not user_id:
            return
        db = _get_db()
        db.favorites.delete_for_user(user_id)
        db.challenges.delete_for_user(user_id)
        db.elo.delete_for_user(user_id)

    @classmethod
    def delete(cls, user_id: str) -> None:
        """Delete a user entity."""
        if not user_id:
            return
        cls.delete_related_entities(user_id)
        db = _get_db()
        db.users.delete(user_id)


# ---------------------------------------------------------------------------
# EloModel
# ---------------------------------------------------------------------------

class EloModelFuture(Future["EloModel"]):
    pass


class EloModel:
    """PostgreSQL facade for EloModel, delegating to EloRepository."""

    def __init__(self, **kwargs: Any) -> None:
        self._entity: Optional[EloEntityProtocol] = None
        self._attrs: Dict[str, Any] = dict(kwargs)
        self._id = kwargs.get("id", "")

    @classmethod
    def _from_entity(cls, entity: EloEntityProtocol) -> EloModel:
        em = cls.__new__(cls)
        em._entity = entity
        em._attrs = {}
        em._id = entity.key_id
        return em

    @property
    def key(self) -> Key:
        # EloModel keys in NDB are Key(UserModel, uid, EloModel, elo_id)
        if self._entity is not None:
            uid = self._entity.user_id
            return Key(UserModel, uid, EloModel, self._id)
        return Key(EloModel, self._id)

    locale = _model_property("locale", "")
    timestamp = _model_property("timestamp", None)
    elo = _model_property("elo", 0)
    human_elo = _model_property("human_elo", 0)
    manual_elo = _model_property("manual_elo", 0)

    def put(self, **kwargs: Any) -> Key:
        """Persist to database."""
        db = _get_db()
        if self._entity is not None:
            # Update via upsert
            ratings = EloDict(
                elo=self.elo,
                human_elo=self.human_elo,
                manual_elo=self.manual_elo,
            )
            db.elo.upsert(self._entity, self._entity.locale, self._entity.user_id, ratings)
        return self.key

    @staticmethod
    def id(locale: str, uid: str) -> str:
        """Return the id of an EloModel entity."""
        return f"{uid}:{locale}"

    @classmethod
    def user_elo(cls, locale: str, uid: str) -> Optional[EloModel]:
        """Retrieve the EloModel for a user in the given locale."""
        if not locale or not uid:
            return None
        db = _get_db()
        entity = db.elo.get_for_user(locale, uid)
        if entity is None:
            return None
        return cls._from_entity(entity)

    @classmethod
    def create(cls, locale: str, uid: str, ratings: EloDict) -> Optional[EloModel]:
        """Create a new EloModel entity and return it."""
        if not locale or not uid:
            return None
        db = _get_db()
        entity = db.elo.create(locale, uid, ratings)
        if entity is None:
            return None
        return cls._from_entity(entity)

    @classmethod
    def upsert(
        cls,
        em: Optional[EloModel],
        locale: str,
        uid: str,
        ratings: EloDict,
    ) -> bool:
        """Update the Elo ratings for a user in the given locale."""
        assert locale
        assert uid
        db = _get_db()
        existing = em._entity if em is not None else None
        return db.elo.upsert(existing, locale, uid, ratings)

    @classmethod
    def delete_for_user(cls, uid: str) -> None:
        """Delete all Elo ratings for a user."""
        if not uid:
            return
        db = _get_db()
        db.elo.delete_for_user(uid)

    @classmethod
    def list_rating(
        cls, kind: str, locale: str, *, limit: int = 100
    ) -> Iterator[RatingForLocaleDict]:
        """Return the top Elo ratings of a specified kind in the given locale."""
        db = _get_db()
        for info in db.elo.list_rating(kind, locale, limit):
            yield RatingForLocaleDict(
                rank=info.rank,
                userid=info.userid,
                elo=info.elo,
            )

    @classmethod
    def list_similar(
        cls,
        locale: str,
        elo: int,
        max_len: int = 40,
    ) -> Iterator[Tuple[str, EloDict]]:
        """Return users with a similar human Elo rating in the specified locale."""
        db = _get_db()
        for uid, ed in db.elo.list_similar(locale, elo, max_len):
            yield uid, EloDict(ed.elo, ed.human_elo, ed.manual_elo)

    @classmethod
    def load_multi(cls, locale: str, user_ids: Iterable[str]) -> Dict[str, EloDict]:
        """Return the Elo ratings of multiple users."""
        db = _get_db()
        result = db.elo.load_multi(locale, list(user_ids))
        return {
            uid: EloDict(ed.elo, ed.human_elo, ed.manual_elo)
            for uid, ed in result.items()
        }


# ---------------------------------------------------------------------------
# RobotModel
# ---------------------------------------------------------------------------

class RobotModel:
    """PostgreSQL facade for RobotModel."""

    def __init__(self, **kwargs: Any) -> None:
        self._attrs: Dict[str, Any] = dict(kwargs)
        self._id = kwargs.get("id", "")

    @property
    def key(self) -> Key:
        return Key(RobotModel, self._id)

    elo = _model_property("elo", 0)

    def put(self, **kwargs: Any) -> Key:
        return self.key

    @staticmethod
    def id(locale: str, level: int) -> str:
        return f"robot-{level}:{locale}"

    @classmethod
    def robot_elo(cls, locale: str, level: int) -> Optional[RobotModel]:
        if not locale or level < 0:
            return None
        db = _get_db()
        elo_val = db.robots.get_elo(locale, level)
        if elo_val is None:
            return None
        rm = cls(id=cls.id(locale, level), elo=elo_val)
        return rm

    @classmethod
    def upsert(
        cls,
        rm: Optional[RobotModel],
        locale: str,
        level: int,
        elo: int,
    ) -> bool:
        assert locale
        db = _get_db()
        return db.robots.upsert_elo(locale, level, elo)


# ---------------------------------------------------------------------------
# MoveModel
# ---------------------------------------------------------------------------

class MoveModel:
    """PostgreSQL facade for MoveModel - a simple data container."""

    def __init__(self, **kwargs: Any) -> None:
        self.coord: str = kwargs.get("coord", "")
        self.tiles: str = kwargs.get("tiles", "")
        self.score: int = kwargs.get("score", 0)
        self.rack: Optional[str] = kwargs.get("rack", None)
        self.timestamp: Optional[datetime] = kwargs.get("timestamp", None)

    @property
    def key(self) -> Key:
        return Key(MoveModel, "")

    def is_resignation(self) -> bool:
        return self.coord == "" and self.tiles == "RSGN"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSONB storage."""
        d: Dict[str, Any] = {
            "coord": self.coord,
            "tiles": self.tiles,
            "score": self.score,
        }
        if self.rack is not None:
            d["rack"] = self.rack
        if self.timestamp is not None:
            d["timestamp"] = self.timestamp.isoformat() if isinstance(self.timestamp, datetime) else self.timestamp
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> MoveModel:
        """Create from a dict (from JSONB)."""
        ts = d.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
        return cls(
            coord=d.get("coord", ""),
            tiles=d.get("tiles", ""),
            score=d.get("score", 0),
            rack=d.get("rack"),
            timestamp=ts,
        )

    def put(self, **kwargs: Any) -> Key:
        return self.key


# ---------------------------------------------------------------------------
# ImageModel
# ---------------------------------------------------------------------------

class ImageModel:
    """PostgreSQL facade for ImageModel."""

    @classmethod
    def get_thumbnail(
        cls, uid: str, size: int = DEFAULT_THUMBNAIL_SIZE
    ) -> Optional[bytes]:
        if not uid:
            return None
        db = _get_db()
        return db.images.get_thumbnail(uid, size)

    @classmethod
    def set_thumbnail(
        cls, uid: str, image: bytes, size: int = DEFAULT_THUMBNAIL_SIZE
    ) -> None:
        db = _get_db()
        db.images.set_thumbnail(uid, image, size)


# ---------------------------------------------------------------------------
# GameModel
# ---------------------------------------------------------------------------

class GameModelFuture(Future["GameModel"]):
    pass


class GameModel:
    """PostgreSQL facade for GameModel, delegating to GameRepository."""

    def __init__(self, id: Optional[str] = None, **kwargs: Any) -> None:
        self._id = id or Unique.id()
        self._entity: Optional[GameEntityProtocol] = None
        self._attrs: Dict[str, Any] = dict(kwargs)
        self._moves_list: Optional[List[MoveModel]] = None

    @classmethod
    def _from_entity(cls, entity: GameEntityProtocol) -> GameModel:
        gm = cls.__new__(cls)
        gm._id = entity.key_id
        gm._entity = entity
        gm._attrs = {}
        gm._moves_list = None
        return gm

    @property
    def key(self) -> Key:
        return Key(GameModel, self._id)

    # --- Player references ---

    @property
    def player0(self) -> Optional[Key]:
        """Return Key for player 0."""
        pid = self.player0_id()
        if pid is None:
            return None
        return Key(UserModel, pid)

    @player0.setter
    def player0(self, value: Optional[Key]) -> None:
        if value is None:
            self._attrs["player0_id"] = None
        else:
            self._attrs["player0_id"] = value.id()

    @property
    def player1(self) -> Optional[Key]:
        """Return Key for player 1."""
        pid = self.player1_id()
        if pid is None:
            return None
        return Key(UserModel, pid)

    @player1.setter
    def player1(self, value: Optional[Key]) -> None:
        if value is None:
            self._attrs["player1_id"] = None
        else:
            self._attrs["player1_id"] = value.id()

    def set_player(self, ix: int, user_id: Optional[str]) -> None:
        """Set a player key property."""
        if ix == 0:
            self._attrs["player0_id"] = user_id
        elif ix == 1:
            self._attrs["player1_id"] = user_id

    def player0_id(self) -> Optional[str]:
        if "player0_id" in self._attrs:
            return self._attrs["player0_id"]
        if self._entity is not None:
            return self._entity.player0_id
        return None

    def player1_id(self) -> Optional[str]:
        if "player1_id" in self._attrs:
            return self._attrs["player1_id"]
        if self._entity is not None:
            return self._entity.player1_id
        return None

    # --- Simple properties ---
    locale = _model_property("locale", None)
    rack0 = _model_property("rack0", "")
    rack1 = _model_property("rack1", "")
    score0 = _model_property("score0", 0)
    score1 = _model_property("score1", 0)
    to_move = _model_property("to_move", 0)
    robot_level = _model_property("robot_level", 0)
    over = _model_property("over", False)
    timestamp = _model_property("timestamp", None)
    ts_last_move = _model_property("ts_last_move", None)
    irack0 = _model_property("irack0", None)
    irack1 = _model_property("irack1", None)
    prefs = _model_property("prefs", None)
    tile_count = _model_property("tile_count", None)
    elo0 = _model_property("elo0", None)
    elo1 = _model_property("elo1", None)
    elo0_adj = _model_property("elo0_adj", None)
    elo1_adj = _model_property("elo1_adj", None)
    human_elo0 = _model_property("human_elo0", None)
    human_elo1 = _model_property("human_elo1", None)
    human_elo0_adj = _model_property("human_elo0_adj", None)
    human_elo1_adj = _model_property("human_elo1_adj", None)
    manual_elo0 = _model_property("manual_elo0", None)
    manual_elo1 = _model_property("manual_elo1", None)
    manual_elo0_adj = _model_property("manual_elo0_adj", None)
    manual_elo1_adj = _model_property("manual_elo1_adj", None)

    @property
    def moves(self) -> List[MoveModel]:
        """Get the moves list."""
        if "moves" in self._attrs:
            val = self._attrs["moves"]
            if val and isinstance(val[0], MoveModel):
                return val
            # Convert from dicts
            return [MoveModel.from_dict(m) if isinstance(m, dict) else m for m in val]
        if self._entity is not None:
            if self._moves_list is None:
                raw_moves = self._entity.moves  # List[MoveDict]
                self._moves_list = [
                    MoveModel(
                        coord=m.coord,
                        tiles=m.tiles,
                        score=m.score,
                        rack=m.rack,
                        timestamp=m.timestamp,
                    )
                    for m in raw_moves
                ]
            return self._moves_list
        return []

    @moves.setter
    def moves(self, value: List[Any]) -> None:
        self._attrs["moves"] = value
        self._moves_list = None

    def manual_wordcheck(self) -> bool:
        """Returns true if the game preferences specify a manual wordcheck."""
        p = self.prefs
        return p is not None and p.get("manual", False)

    def put(self, **kwargs: Any) -> Key:
        """Persist changes to the database."""
        db = _get_db()
        # Convert MoveModel list to dicts for JSONB storage
        update_attrs = dict(self._attrs)
        if "moves" in update_attrs:
            moves_val = update_attrs["moves"]
            update_attrs["moves"] = [
                m.to_dict() if isinstance(m, MoveModel) else m
                for m in moves_val
            ]

        if self._entity is not None:
            if update_attrs:
                db.games.update(self._entity, **update_attrs)
                self._attrs.clear()
                self._moves_list = None
        else:
            # No loaded entity: check whether a game with this id
            # already exists in the database (NDB put() is an upsert)
            existing = db.games.get_by_id(self._id)
            if existing is not None:
                # Update the existing game
                self._entity = existing
                if update_attrs:
                    db.games.update(existing, **update_attrs)
            else:
                # Creating a new game
                create_kwargs = dict(update_attrs)
                create_kwargs["id"] = self._id
                entity = db.games.create(**create_kwargs)
                self._entity = entity
            self._attrs.clear()
            self._moves_list = None
        return self.key

    @classmethod
    def fetch(cls, game_uuid: str, use_cache: bool = True) -> Optional[GameModel]:
        """Fetch a game entity given its uuid."""
        db = _get_db()
        entity = db.games.get_by_id(game_uuid)
        if entity is None:
            return None
        return cls._from_entity(entity)

    @classmethod
    def list_finished_games(
        cls, user_id: str, versus: Optional[str] = None, max_len: int = 10
    ) -> List[FinishedGameDict]:
        """Query for recently finished games for the given user."""
        if not user_id:
            return []
        db = _get_db()
        results = db.games.list_finished_games(user_id, versus, max_len)
        return [
            FinishedGameDict(
                uuid=r.uuid,
                ts=r.ts,
                ts_last_move=r.ts_last_move or r.ts,
                opp=r.opp,
                robot_level=r.robot_level,
                sc0=r.sc0,
                sc1=r.sc1,
                elo_adj=r.elo_adj,
                human_elo_adj=r.human_elo_adj,
                manual_elo_adj=r.manual_elo_adj,
                prefs=r.prefs,
                locale=r.locale or DEFAULT_LOCALE,
            )
            for r in results
        ]

    @classmethod
    def iter_live_games(
        cls, user_id: Optional[str], max_len: int = 10
    ) -> Iterator[LiveGameDict]:
        """Query for active games for the given user."""
        if not user_id:
            return
        db = _get_db()
        for r in db.games.iter_live_games(user_id, max_len):
            yield LiveGameDict(
                uuid=r.uuid,
                ts=r.ts,
                opp=r.opp,
                robot_level=r.robot_level,
                my_turn=r.my_turn,
                sc0=r.sc0,
                sc1=r.sc1,
                prefs=r.prefs,
                tile_count=r.tile_count,
                locale=r.locale or DEFAULT_LOCALE,
            )

    @classmethod
    def delete_for_user(cls, uid: str) -> None:
        """Delete all game entities for a user."""
        if not uid:
            return
        db = _get_db()
        db.games.delete_for_user(uid)


# ---------------------------------------------------------------------------
# FavoriteModel
# ---------------------------------------------------------------------------

class FavoriteModel:
    """PostgreSQL facade for FavoriteModel."""

    MAX_FAVORITES = 100

    @classmethod
    def list_favorites(
        cls, user_id: str, max_len: int = MAX_FAVORITES
    ) -> Iterator[str]:
        if not user_id:
            return
        db = _get_db()
        yield from db.favorites.list_favorites(user_id, max_len)

    @classmethod
    def delete_user(cls, user_id: str) -> None:
        if not user_id:
            return
        db = _get_db()
        db.favorites.delete_for_user(user_id)

    @classmethod
    def has_relation(
        cls, srcuser_id: Optional[str], destuser_id: Optional[str]
    ) -> bool:
        if not srcuser_id or not destuser_id:
            return False
        db = _get_db()
        return db.favorites.has_relation(srcuser_id, destuser_id)

    @classmethod
    def add_relation(cls, src_id: str, dest_id: str) -> None:
        db = _get_db()
        db.favorites.add_relation(src_id, dest_id)

    @classmethod
    def del_relation(cls, src_id: str, dest_id: str) -> None:
        db = _get_db()
        db.favorites.delete_relation(src_id, dest_id)


# ---------------------------------------------------------------------------
# ChallengeModel
# ---------------------------------------------------------------------------

class ChallengeModel:
    """PostgreSQL facade for ChallengeModel."""

    @classmethod
    def has_relation(
        cls, srcuser_id: Optional[str], destuser_id: Optional[str]
    ) -> bool:
        if srcuser_id is None or destuser_id is None:
            return False
        db = _get_db()
        return db.challenges.has_relation(srcuser_id, destuser_id)

    @classmethod
    def find_relation(
        cls, srcuser_id: Optional[str], destuser_id: Optional[str], key: Optional[str]
    ) -> Tuple[bool, Optional[PrefsDict]]:
        if srcuser_id is None or destuser_id is None:
            return (False, None)
        db = _get_db()
        return db.challenges.find_relation(srcuser_id, destuser_id, key)

    @classmethod
    def add_relation(
        cls, src_id: str, dest_id: str, prefs: Optional[PrefsDict]
    ) -> None:
        db = _get_db()
        db.challenges.add_relation(src_id, dest_id, prefs)

    @classmethod
    def del_relation(
        cls, src_id: str, dest_id: str, key: Optional[str]
    ) -> Tuple[bool, Optional[PrefsDict]]:
        db = _get_db()
        return db.challenges.delete_relation(src_id, dest_id, key)

    @classmethod
    def delete_user(cls, user_id: str) -> None:
        if not user_id:
            return
        db = _get_db()
        db.challenges.delete_for_user(user_id)

    @classmethod
    def list_issued(
        cls, user_id: Optional[str], max_len: int = 20
    ) -> Iterator[ChallengeTuple]:
        if not user_id:
            return
        db = _get_db()
        for info in db.challenges.list_issued(user_id, max_len):
            yield ChallengeTuple(
                opp=info.opp,
                prefs=info.prefs,
                ts=info.ts,
                key=info.key,
            )

    @classmethod
    def list_received(
        cls, user_id: Optional[str], max_len: int = 20
    ) -> Iterator[ChallengeTuple]:
        if not user_id:
            return
        db = _get_db()
        for info in db.challenges.list_received(user_id, max_len):
            yield ChallengeTuple(
                opp=info.opp,
                prefs=info.prefs,
                ts=info.ts,
                key=info.key,
            )


# ---------------------------------------------------------------------------
# StatsModel
# ---------------------------------------------------------------------------

class StatsModel:
    """PostgreSQL facade for StatsModel."""

    MAX_STATS = 100

    def __init__(self, **kwargs: Any) -> None:
        self._entity: Optional[StatsEntityProtocol] = None
        self._attrs: Dict[str, Any] = dict(kwargs)

    @classmethod
    def _from_entity(cls, entity: StatsEntityProtocol) -> StatsModel:
        sm = cls.__new__(cls)
        sm._entity = entity
        sm._attrs = {}
        return sm

    @property
    def key(self) -> Key:
        if self._entity is not None:
            return Key(StatsModel, self._entity.key_id)
        return Key(StatsModel, "")

    # Properties
    user = _model_property("user", None)
    robot_level = _model_property("robot_level", 0)
    timestamp = _model_property("timestamp", None)
    games = _model_property("games", 0)
    human_games = _model_property("human_games", 0)
    manual_games = _model_property("manual_games", 0)
    elo = _model_property("elo", 1200)
    human_elo = _model_property("human_elo", 1200)
    manual_elo = _model_property("manual_elo", 1200)
    score = _model_property("score", 0)
    human_score = _model_property("human_score", 0)
    manual_score = _model_property("manual_score", 0)
    score_against = _model_property("score_against", 0)
    human_score_against = _model_property("human_score_against", 0)
    manual_score_against = _model_property("manual_score_against", 0)
    wins = _model_property("wins", 0)
    losses = _model_property("losses", 0)
    human_wins = _model_property("human_wins", 0)
    human_losses = _model_property("human_losses", 0)
    manual_wins = _model_property("manual_wins", 0)
    manual_losses = _model_property("manual_losses", 0)

    def set_user(self, user_id: Optional[str], robot_level: int = 0) -> None:
        """Set the user (as a Key-like value) and robot_level."""
        # In the NDB version, self.user is a Key. Here we store the user_id
        # and adapt in the property accessor as needed.
        if user_id is not None:
            self._attrs["user"] = Key(UserModel, user_id)
        else:
            self._attrs["user"] = None
        self._attrs["robot_level"] = robot_level

    def put(self, **kwargs: Any) -> Key:
        """Persist to database."""
        db = _get_db()
        if self._entity is not None:
            # Update the entity (which is the ORM model directly)
            entity = self._entity
            for attr_name, value in self._attrs.items():
                if attr_name == "user":
                    # Convert Key back to user_id string
                    if value is not None:
                        entity.user_id = value.id() if isinstance(value, Key) else value  # type: ignore[union-attr]
                    else:
                        entity.user_id = None  # type: ignore[assignment]
                elif hasattr(entity, attr_name):
                    setattr(entity, attr_name, value)
                elif attr_name == "user_id" and hasattr(entity, "user_id"):
                    entity.user_id = value  # type: ignore[union-attr]
            db.flush()
            self._attrs.clear()
        else:
            # Create new entity
            user_val = self._attrs.get("user")
            user_id: Optional[str] = None
            if isinstance(user_val, Key):
                user_id = user_val.id()
            elif isinstance(user_val, str):
                user_id = user_val
            entity = db.stats.create(
                user_id=user_id,
                robot_level=self._attrs.get("robot_level", 0),
            )
            self._entity = entity
            # Now update all other attributes on the entity directly
            for attr_name, value in self._attrs.items():
                if attr_name in ("user", "robot_level"):
                    continue
                if hasattr(entity, attr_name):
                    setattr(entity, attr_name, value)
            db.flush()
            self._attrs.clear()
        return self.key

    @classmethod
    def create(cls, user_id: Optional[str], robot_level: int = 0) -> StatsModel:
        """Create a fresh instance with default values."""
        sm = cls()
        sm.set_user(user_id, robot_level)
        sm.timestamp = datetime.now(UTC)
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
        """Copy data from the src instance."""
        for attr in [
            "timestamp", "elo", "human_elo", "manual_elo",
            "games", "human_games", "manual_games",
            "score", "human_score", "manual_score",
            "score_against", "human_score_against", "manual_score_against",
            "wins", "losses", "human_wins", "human_losses",
            "manual_wins", "manual_losses",
        ]:
            setattr(self, attr, getattr(src, attr))

    def populate_dict(self, d: Dict[str, Any]) -> None:
        """Copy statistics data to the given dict."""
        d["elo"] = self.elo
        d["human_elo"] = self.human_elo
        d["manual_elo"] = self.manual_elo
        d["games"] = self.games
        d["human_games"] = self.human_games
        d["established"] = self.human_games > ESTABLISHED_MARK
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
        d_user = d.get("user")
        if d_user is None:
            return f"robot-{d.get('robot_level', 0)}"
        return d_user

    @staticmethod
    def user_id_from_key(k: Optional[str]) -> Tuple[Optional[str], int]:
        if k is not None and k.startswith("robot-"):
            return (None, int(k[6:]))
        return (k, 0)

    def fetch_user(self) -> Optional[UserModel]:
        user_val = self.user
        if user_val is None:
            return None
        if isinstance(user_val, Key):
            return UserModel.fetch(user_val.id())
        return UserModel.fetch(str(user_val))

    @classmethod
    def list_elo(
        cls, timestamp: Optional[datetime] = None, max_len: int = MAX_STATS
    ) -> StatsResults:
        db = _get_db()
        results, _ = db.stats.list_elo(timestamp, max_len)
        return [
            StatsDict(
                user=r.user,
                robot_level=r.robot_level,
                timestamp=r.timestamp,
                games=r.games,
                elo=r.elo,
                score=r.score,
                score_against=r.score_against,
                wins=r.wins,
                losses=r.losses,
                rank=r.rank,
            )
            for r in results
        ]

    @classmethod
    def list_human_elo(
        cls, timestamp: Optional[datetime] = None, max_len: int = MAX_STATS
    ) -> StatsResults:
        db = _get_db()
        results, _ = db.stats.list_human_elo(timestamp, max_len)
        return [
            StatsDict(
                user=r.user,
                robot_level=r.robot_level,
                timestamp=r.timestamp,
                games=r.games,
                elo=r.elo,
                score=r.score,
                score_against=r.score_against,
                wins=r.wins,
                losses=r.losses,
                rank=r.rank,
            )
            for r in results
        ]

    @classmethod
    def list_manual_elo(
        cls, timestamp: Optional[datetime] = None, max_len: int = MAX_STATS
    ) -> StatsResults:
        db = _get_db()
        results, _ = db.stats.list_manual_elo(timestamp, max_len)
        return [
            StatsDict(
                user=r.user,
                robot_level=r.robot_level,
                timestamp=r.timestamp,
                games=r.games,
                elo=r.elo,
                score=r.score,
                score_against=r.score_against,
                wins=r.wins,
                losses=r.losses,
                rank=r.rank,
            )
            for r in results
        ]

    # Cache stubs (used by skraflstats.py)
    _NB_CACHE: Dict[Tuple[Optional[str], int], Dict[datetime, StatsModel]] = dict()
    _NB_CACHE_STATS: Dict[str, int] = dict(hits=0, misses=0)

    @classmethod
    def clear_cache(cls) -> None:
        cls._NB_CACHE = dict()
        cls._NB_CACHE_STATS = dict(hits=0, misses=0)

    @classmethod
    def log_cache_stats(cls) -> None:
        hits = cls._NB_CACHE_STATS["hits"]
        misses = cls._NB_CACHE_STATS["misses"]
        total = hits + misses
        _log.info(f"Cache hits {hits} or {100.0 * hits / total if total else 0.0:.2f}%")
        _log.info(f"Cache misses {misses} or {100.0 * misses / total if total else 0.0:.2f}%")

    @classmethod
    def newest_before(
        cls, ts: datetime, user_id: Optional[str], robot_level: int = 0
    ) -> StatsModel:
        """Returns the newest available stats record at or before the given time."""
        cache = cls._NB_CACHE
        key = (user_id, robot_level)
        if ts and key in cache:
            for c_ts, c_val in cache[key].items():
                if c_ts >= ts >= c_val.timestamp:
                    cls._NB_CACHE_STATS["hits"] += 1
                    sm = cls.create(user_id, robot_level)
                    sm.copy_from(c_val)
                    return sm

        cls._NB_CACHE_STATS["misses"] += 1
        sm = cls.create(user_id, robot_level)

        if ts and user_id:
            db = _get_db()
            entity = db.stats.newest_before(ts, user_id, robot_level)
            if entity is not None:
                wrapped = cls._from_entity(entity)
                sm.copy_from(wrapped)

            if key not in cache:
                cache[key] = dict()
            cache[key][ts] = sm

        return sm

    @classmethod
    def newest_for_user(cls, user_id: str) -> Optional[StatsModel]:
        if not user_id:
            return None
        db = _get_db()
        entity = db.stats.newest_for_user(user_id)
        if entity is None:
            return cls.create(user_id)
        return cls._from_entity(entity)

    @classmethod
    def last_for_user(cls, user_id: str, days: int) -> List[StatsModel]:
        if not user_id or days <= 0:
            return []
        db = _get_db()
        entities = db.stats.last_for_user(user_id, days)
        return [cls._from_entity(e) for e in entities]

    @classmethod
    def delete_ts(cls, timestamp: datetime) -> None:
        db = _get_db()
        db.stats.delete_at_timestamp(timestamp)

    @classmethod
    def delete_user(cls, user_id: str) -> None:
        if not user_id:
            return
        db = _get_db()
        db.stats.delete_for_user(user_id)


# ---------------------------------------------------------------------------
# RatingModel
# ---------------------------------------------------------------------------

class RatingModel:
    """PostgreSQL facade for RatingModel."""

    def __init__(self, **kwargs: Any) -> None:
        self._pg_rating: Any = None
        self._attrs: Dict[str, Any] = dict(kwargs)

    @classmethod
    def _from_pg(cls, pg_rating: Any) -> RatingModel:
        rm = cls.__new__(cls)
        rm._pg_rating = pg_rating
        rm._attrs = {}
        return rm

    @property
    def key(self) -> Key:
        kind = self._attrs.get("kind", "")
        rank = self._attrs.get("rank", 0)
        if self._pg_rating is not None:
            kind = self._pg_rating.kind
            rank = self._pg_rating.rank
        return Key(RatingModel, f"{kind}:{rank}")

    # Properties that map to the PG Rating model
    kind = _model_property("kind", "")
    rank = _model_property("rank", 0)
    user = _model_property("user", None)
    robot_level = _model_property("robot_level", 0)
    games = _model_property("games", 0)
    elo = _model_property("elo", 1200)
    score = _model_property("score", 0)
    score_against = _model_property("score_against", 0)
    wins = _model_property("wins", 0)
    losses = _model_property("losses", 0)
    rank_yesterday = _model_property("rank_yesterday", 0)
    games_yesterday = _model_property("games_yesterday", 0)
    elo_yesterday = _model_property("elo_yesterday", 1200)
    score_yesterday = _model_property("score_yesterday", 0)
    score_against_yesterday = _model_property("score_against_yesterday", 0)
    wins_yesterday = _model_property("wins_yesterday", 0)
    losses_yesterday = _model_property("losses_yesterday", 0)
    rank_week_ago = _model_property("rank_week_ago", 0)
    games_week_ago = _model_property("games_week_ago", 0)
    elo_week_ago = _model_property("elo_week_ago", 1200)
    score_week_ago = _model_property("score_week_ago", 0)
    score_against_week_ago = _model_property("score_against_week_ago", 0)
    wins_week_ago = _model_property("wins_week_ago", 0)
    losses_week_ago = _model_property("losses_week_ago", 0)
    rank_month_ago = _model_property("rank_month_ago", 0)
    games_month_ago = _model_property("games_month_ago", 0)
    elo_month_ago = _model_property("elo_month_ago", 1200)
    score_month_ago = _model_property("score_month_ago", 0)
    score_against_month_ago = _model_property("score_against_month_ago", 0)
    wins_month_ago = _model_property("wins_month_ago", 0)
    losses_month_ago = _model_property("losses_month_ago", 0)

    def put(self, **kwargs: Any) -> Key:
        """Persist to database."""
        if self._pg_rating is not None:
            # Update existing PG Rating model
            pg = self._pg_rating
            for attr_name, value in self._attrs.items():
                if attr_name == "user":
                    # Convert Key to user_id
                    if value is None:
                        pg.user_id = None
                    elif isinstance(value, Key):
                        pg.user_id = value.id()
                    else:
                        pg.user_id = str(value)
                elif hasattr(pg, attr_name):
                    setattr(pg, attr_name, value)
            db = _get_db()
            db.flush()
            self._attrs.clear()
        return self.key

    def assign(self, dict_args: StatsDict) -> None:
        """Populate attributes from a dict."""
        for key_name, val in dict_args.items():
            if key_name == "user":
                if val is None:
                    self.user = None
                else:
                    self.user = Key(UserModel, val)
            else:
                setattr(self, key_name, val)

    @classmethod
    def get_or_create(cls, kind: str, rank: int) -> RatingModel:
        db = _get_db()
        pg_rating = db.ratings.get_or_create(kind, rank)
        rm = cls._from_pg(pg_rating)
        return rm

    @classmethod
    def list_rating(cls, kind: str) -> Iterator[RatingDict]:
        db = _get_db()
        for info in db.ratings.list_rating(kind):
            v = RatingDict(
                rank=info.rank,
                userid=info.userid or "",
                games=info.games,
                elo=info.elo,
                score=info.score,
                score_against=info.score_against,
                wins=info.wins,
                losses=info.losses,
                rank_yesterday=info.rank_yesterday,
                games_yesterday=info.games_yesterday,
                elo_yesterday=info.elo_yesterday,
                score_yesterday=info.score_yesterday,
                score_against_yesterday=info.score_against_yesterday,
                wins_yesterday=info.wins_yesterday,
                losses_yesterday=info.losses_yesterday,
                rank_week_ago=info.rank_week_ago,
                games_week_ago=info.games_week_ago,
                elo_week_ago=info.elo_week_ago,
                score_week_ago=info.score_week_ago,
                score_against_week_ago=info.score_against_week_ago,
                wins_week_ago=info.wins_week_ago,
                losses_week_ago=info.losses_week_ago,
                rank_month_ago=info.rank_month_ago,
                games_month_ago=info.games_month_ago,
                elo_month_ago=info.elo_month_ago,
                score_month_ago=info.score_month_ago,
                score_against_month_ago=info.score_against_month_ago,
                wins_month_ago=info.wins_month_ago,
                losses_month_ago=info.losses_month_ago,
            )
            # Handle robot_level from userid convention
            if info.userid and info.userid.startswith("robot-"):
                pass  # userid already contains the robot designation
            elif info.robot_level and info.robot_level > 0:
                v["userid"] = f"robot-{info.robot_level}"
            yield v

    @classmethod
    def delete_all(cls) -> None:
        db = _get_db()
        db.ratings.delete_all()


# ---------------------------------------------------------------------------
# ChatModel
# ---------------------------------------------------------------------------

class ChatModelFuture(Future["ChatModel"]):
    pass


class ChatModel:
    """PostgreSQL facade for ChatModel."""

    @classmethod
    def list_conversation(
        cls, channel: str, maxlen: int = 250
    ) -> Iterator[Dict[str, Any]]:
        db = _get_db()
        for msg in db.chat.list_conversation(channel, maxlen):
            yield dict(
                user=msg.user,
                recipient=None,  # Not typically needed
                ts=msg.ts,
                msg=msg.msg,
            )

    @classmethod
    def check_conversation(cls, channel: str, userid: Optional[str]) -> bool:
        if userid is None:
            return False
        db = _get_db()
        return db.chat.check_conversation(channel, userid)

    @classmethod
    def add_msg(
        cls,
        channel: str,
        from_user: str,
        to_user: str,
        msg: str,
        timestamp: Optional[datetime] = None,
    ) -> datetime:
        db = _get_db()
        return db.chat.add_msg(channel, from_user, to_user or None, msg, timestamp)

    @classmethod
    def add_msg_in_game(
        cls,
        game_uuid: str,
        from_user: str,
        to_user: str,
        msg: str,
        timestamp: Optional[datetime] = None,
    ) -> datetime:
        db = _get_db()
        return db.chat.add_msg_in_game(game_uuid, from_user, to_user or None, msg, timestamp)

    @classmethod
    def add_msg_between_users(
        cls,
        from_user: str,
        to_user: str,
        msg: str,
        timestamp: Optional[datetime] = None,
    ) -> datetime:
        db = _get_db()
        return db.chat.add_msg_between_users(from_user, to_user, msg, timestamp)

    @classmethod
    def chat_history(
        cls,
        for_user: str,
        *,
        maxlen: int = 20,
        blocked_users: Set[str] = set(),
    ) -> Sequence[ChatModelHistoryDict]:
        db = _get_db()
        results = db.chat.chat_history(for_user, maxlen, blocked_users or None)
        return [
            ChatModelHistoryDict(
                user=r.user,
                ts=r.ts,
                last_msg=r.last_msg,
                unread=r.unread,
            )
            for r in results
        ]

    @classmethod
    def delete_for_user(cls, user_id: str) -> None:
        # Not implemented in PG repository yet, but not commonly needed
        pass


# ---------------------------------------------------------------------------
# ZombieModel
# ---------------------------------------------------------------------------

class ZombieModel:
    """PostgreSQL facade for ZombieModel."""

    @classmethod
    def add_game(cls, game_id: Optional[str], user_id: Optional[str]) -> None:
        if not game_id or not user_id:
            return
        db = _get_db()
        db.zombies.add_game(game_id, user_id)

    @classmethod
    def del_game(cls, game_id: Optional[str], user_id: Optional[str]) -> None:
        if not game_id or not user_id:
            return
        db = _get_db()
        db.zombies.delete_game(game_id, user_id)

    @classmethod
    def delete_for_user(cls, user_id: str) -> None:
        if not user_id:
            return
        db = _get_db()
        db.zombies.delete_for_user(user_id)

    @classmethod
    def list_games(cls, user_id: Optional[str]) -> Iterator[ZombieGameDict]:
        if not user_id:
            return
        db = _get_db()
        for info in db.zombies.list_games(user_id):
            yield ZombieGameDict(
                uuid=info.uuid,
                ts=info.ts,
                opp=info.opp,
                robot_level=info.robot_level,
                sc0=info.sc0,
                sc1=info.sc1,
                locale=info.locale or DEFAULT_LOCALE,
            )


# ---------------------------------------------------------------------------
# PromoModel
# ---------------------------------------------------------------------------

class PromoModel:
    """PostgreSQL facade for PromoModel."""

    @classmethod
    def add_promotion(cls, user_id: str, promotion: str) -> None:
        db = _get_db()
        db.promos.add_promotion(user_id, promotion)

    @classmethod
    def list_promotions(
        cls, user_id: Optional[str], promotion: str
    ) -> Iterator[datetime]:
        if not user_id:
            return
        db = _get_db()
        yield from db.promos.list_promotions(user_id, promotion)


# ---------------------------------------------------------------------------
# CompletionModel
# ---------------------------------------------------------------------------

class CompletionModel:
    """PostgreSQL facade for CompletionModel."""

    @classmethod
    def add_completion(cls, proctype: str, ts_from: datetime, ts_to: datetime) -> None:
        db = _get_db()
        db.completions.add_completion(proctype, ts_from, ts_to)

    @classmethod
    def add_failure(
        cls, proctype: str, ts_from: datetime, ts_to: datetime, reason: str
    ) -> None:
        db = _get_db()
        db.completions.add_failure(proctype, ts_from, ts_to, reason)


# ---------------------------------------------------------------------------
# BlockModel
# ---------------------------------------------------------------------------

class BlockModel:
    """PostgreSQL facade for BlockModel."""

    MAX_BLOCKS = 100

    @classmethod
    def list_blocked_users(
        cls, user_id: str, max_len: int = MAX_BLOCKS
    ) -> Iterator[str]:
        if not user_id:
            return
        db = _get_db()
        yield from db.blocks.list_blocked_users(user_id, max_len)

    @classmethod
    def list_blocked_by(cls, user_id: str, max_len: int = MAX_BLOCKS) -> Iterator[str]:
        if not user_id:
            return
        db = _get_db()
        yield from db.blocks.list_blocked_by(user_id, max_len)

    @classmethod
    def block_user(cls, blocker_id: str, blocked_id: str) -> bool:
        if not blocker_id or not blocked_id:
            return False
        db = _get_db()
        return db.blocks.block_user(blocker_id, blocked_id)

    @classmethod
    def unblock_user(cls, blocker_id: str, blocked_id: str) -> bool:
        db = _get_db()
        return db.blocks.unblock_user(blocker_id, blocked_id)

    @classmethod
    def is_blocking(cls, blocker_id: str, blocked_id: str) -> bool:
        db = _get_db()
        return db.blocks.is_blocking(blocker_id, blocked_id)


# ---------------------------------------------------------------------------
# ReportModel
# ---------------------------------------------------------------------------

class ReportModel:
    """PostgreSQL facade for ReportModel."""

    MAX_REPORTS = 100

    @classmethod
    def report_user(
        cls, reporter_id: str, reported_id: str, code: int, text: str
    ) -> bool:
        if not reporter_id or not reported_id:
            return False
        db = _get_db()
        return db.reports.report_user(reporter_id, reported_id, code, text)

    @classmethod
    def list_reported_by(
        cls, user_id: str, max_len: int = MAX_REPORTS
    ) -> Iterator[str]:
        if not user_id:
            return
        db = _get_db()
        yield from db.reports.list_reported_by(user_id, max_len)


# ---------------------------------------------------------------------------
# TransactionModel
# ---------------------------------------------------------------------------

class TransactionModel:
    """PostgreSQL facade for TransactionModel."""

    @classmethod
    def add_transaction(cls, user_id: str, plan: str, kind: str, op: str) -> None:
        db = _get_db()
        db.transactions.add_transaction(user_id, plan, kind, op)


# ---------------------------------------------------------------------------
# SubmissionModel
# ---------------------------------------------------------------------------

class SubmissionModel:
    """PostgreSQL facade for SubmissionModel."""

    @classmethod
    def submit_word(cls, user_id: str, locale: str, word: str, comment: str) -> None:
        db = _get_db()
        db.submissions.submit_word(user_id, locale, word, comment)


# ---------------------------------------------------------------------------
# RiddleModel
# ---------------------------------------------------------------------------

class RiddleModel:
    """PostgreSQL facade for RiddleModel."""

    def __init__(self, **kwargs: Any) -> None:
        self._entity: Optional[RiddleEntityProtocol] = None
        self._attrs: Dict[str, Any] = dict(kwargs)

    @classmethod
    def _from_entity(cls, entity: RiddleEntityProtocol) -> RiddleModel:
        rm = cls.__new__(cls)
        rm._entity = entity
        rm._attrs = {}
        return rm

    date = _model_property("date", "")
    locale = _model_property("locale", "")
    riddle_json = _model_property("riddle_json", "")
    created = _model_property("created", None)
    version = _model_property("version", 1)

    @property
    def riddle(self) -> Any:
        import json
        rj = self.riddle_json
        if not rj:
            return None
        try:
            return json.loads(rj)
        except (ValueError, TypeError):
            return None

    @classmethod
    def get_riddle(cls, date_str: str, locale: str) -> Optional[RiddleModel]:
        db = _get_db()
        entity = db.riddles.get_riddle(date_str, locale)
        if entity is None:
            return None
        return cls._from_entity(entity)

    @classmethod
    def get_riddles_for_date(cls, date_str: str) -> Sequence[RiddleModel]:
        db = _get_db()
        entities = db.riddles.get_riddles_for_date(date_str)
        return [cls._from_entity(e) for e in entities]

    @classmethod
    def get_by_id(cls, id: Any, *args: Any, **kwargs: Any) -> Optional[RiddleModel]:
        """Fetch by composite key id (date:locale)."""
        if not id:
            return None
        parts = str(id).split(":", 1)
        if len(parts) != 2:
            return None
        return cls.get_riddle(parts[0], parts[1])
