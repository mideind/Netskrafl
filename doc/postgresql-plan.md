# PostgreSQL Migration Plan for Netskrafl/Explo

## Executive Summary

This document details the migration path from Google Cloud Datastore (NDB) to PostgreSQL with SQLAlchemy ORM. The migration aims to:

1. **Eliminate vendor lock-in** - Remove dependency on Google Cloud Datastore
2. **Enable SQL features** - Leverage relational database capabilities for complex queries
3. **Improve hosting flexibility** - Deploy on any platform supporting PostgreSQL
4. **Simplify operations** - Use standard database tooling and practices

### Key Constraints

- Minimal changes to API surface - business logic layer should be largely unchanged
- Data migration must be done with minimal downtime
- Must support the same functionality across Netskrafl (Icelandic) and Explo (multi-locale)
- Existing Redis caching infrastructure will be preserved and enhanced
- **All timestamps must be stored in UTC** - consistent with current NDB practice

### Assessment: Migration Complexity

**The migration is surprisingly straightforward** because:

1. **Simple transaction model** - Only one `@ndb.transactional` usage in the entire codebase
2. **Clean model structure** - All 18 NDB models map directly to relational tables
3. **Standard query patterns** - All NDB queries translate cleanly to SQLAlchemy
4. **JSONB for complex data** - Moves list (LocalStructuredProperty) maps naturally to JSONB
5. **Foreign keys are natural** - Parent-child relationships become FK constraints
6. **No explicit caching needed** - PostgreSQL's buffer pool replaces NDB's Redis cache

**Potential complications:**

- Data volume - Migration script must handle potentially large datasets efficiently
- Composite keys - Need careful handling of `{user_id}:{locale}` patterns
- Index optimization - May need PostgreSQL-specific index tuning after migration
- Connection pooling - Need proper pool sizing for production load

---

## Implementation Status

*Updated: February 2026*

Phase 1 of the migration (creating the PostgreSQL backend parallel to NDB) is
substantially complete. The implementation evolved beyond the original plan into
a more robust protocol-based repository architecture. This section describes what
was built and how it differs from the plan's proposals.

### What Has Been Built

The core infrastructure for running either NDB or PostgreSQL is operational:

- **Protocol layer** (`src/db/protocols.py`, ~1,420 lines) — Interface contracts
  defining 7 entity protocols, 18 repository protocols, and ~30 shared data types
  (dataclasses and TypedDicts). Both backends implement these protocols via
  structural subtyping (duck typing).

- **PostgreSQL backend** (`src/db/postgresql/`, ~2,500 lines) — Complete
  SQLAlchemy 2.0 ORM implementation with backend class, connection management,
  ORM models (which directly satisfy entity protocols), and 18 repository
  implementations. The entity wrapper layer (`entities.py`) was eliminated —
  repositories return ORM model instances directly.

- **NDB backend adapter** (`src/db/ndb/`, ~1,700 lines) — Wraps the existing
  `skrafldb_ndb.py` code to implement the same repository protocols, enabling
  both backends to be used interchangeably via `get_db()`.

- **Session management** (`src/db/session.py`, ~290 lines) — `SessionManager`
  class providing request-scoped backends via thread-local storage, with WSGI
  middleware for automatic transaction lifecycle (commit on success, rollback
  on exception).

- **Old API facade** (`skrafldb_pg.py`, ~2,100 lines) — NDB-compatible API
  (`UserModel`, `GameModel`, etc.) delegating to the PostgreSQL repositories,
  so that existing application code using `from skrafldb import UserModel`
  works unchanged with either backend.

- **Comprehensive test suite** (`tests/db/`, ~5,000 lines) — 16 test files
  (one per repository) with multi-backend parametrization via `--backend=ndb`,
  `--backend=postgresql`, or `--backend=both` CLI flags. Tests verify that
  both backends produce identical results for all operations.

### Key Architectural Differences from the Plan

| Aspect | Plan | Actual |
|--------|------|--------|
| **Architecture** | Facade + NDB-compat wrappers | Protocol/Repository pattern with entity wrappers |
| **Shared types** | Defined per-backend | Centralized in `protocols.py` |
| **Session management** | `SessionLocal = sessionmaker()` | `SessionManager` with thread-local request scoping |
| **Facades** | One (`skrafldb.py` → `db/__init__.py`) | Two: old API (`skrafldb.py` → `skrafldb_pg.py`) + new API (`get_db()`) |
| **NDB code location** | Moved to `src/db/ndb/models.py` | Stays at `skrafldb_ndb.py`; `src/db/ndb/` wraps it |
| **Transactions** | Simple context manager | Savepoint-based nested transactions |
| **Composite keys** | UUID PK + unique constraint | Composite primary keys directly |
| **SQLAlchemy style** | 1.x (`Column`, `declarative_base`) | 2.0 (`Mapped`, `mapped_column`, `DeclarativeBase`) |
| **Entity access** | Direct ORM model exposure | ORM models satisfy entity protocols directly (entity wrappers eliminated) |

### Actual Directory Structure

```
src/
  skrafldb.py              # Facade selector: imports from skrafldb_ndb or skrafldb_pg
  skrafldb_ndb.py          # Original NDB implementation (~3,000 lines, unchanged)
  skrafldb_pg.py           # PostgreSQL NDB-compatible facade (~2,100 lines)

  db/
    __init__.py            # Exports: init_session_manager, get_db, db_wsgi_middleware
    config.py              # DatabaseConfig dataclass, get_config()
    session.py             # SessionManager, request-scoped lifecycle, WSGI middleware
    protocols.py           # All protocols, entity contracts, shared data types
    testing.py             # Test infrastructure helpers

    postgresql/
      __init__.py          # Exports PostgreSQLBackend
      backend.py           # PostgreSQLBackend class (implements DatabaseBackendProtocol)
      connection.py        # create_db_engine() with UTC timezone and connection pooling
      models.py            # SQLAlchemy 2.0 ORM models (satisfy entity protocols directly)
      repositories.py      # Repository implementations (18 repositories)

    ndb/
      __init__.py          # Exports NDBBackend
      backend.py           # NDBBackend class (implements DatabaseBackendProtocol)
      entities.py          # Entity wrappers adapting NDB models to entity protocols
      repositories.py      # Repository implementations wrapping skrafldb_ndb

tests/
  db/
    conftest.py            # Multi-backend test fixtures and CLI flags
    test_user_repository.py
    test_game_repository.py
    test_elo_repository.py
    ... (16 test files total)
```

### Dual API Design

The implementation provides two APIs for database access:

**Old API** (for existing application code, zero changes required):
```python
from skrafldb import UserModel, GameModel, Client
um = UserModel.fetch("user-123")
```
`skrafldb.py` selects between `skrafldb_ndb` and `skrafldb_pg` based on
`DATABASE_BACKEND`. The `skrafldb_pg` module delegates all operations to the
PostgreSQL repositories via `get_db()`.

**New API** (for new or refactored code):
```python
from src.db import get_db
db = get_db()
user = db.users.get_by_id("user-123")
db.users.update(user, elo=1500)
# Changes committed at request end by SessionManager
```

### What Remains To Be Done

- **Integration testing** with the full application stack (Phase 2).
- **Data migration scripts** — `scripts/migrate_to_postgres.py` (Phase 3 of
  the plan). The migration procedure described later in this document is still
  the intended approach.
- **Production database creation** with ICU collation (Phase 3).
- **Cutover** — Setting `DATABASE_BACKEND=postgresql` in production (Phase 4).
- **NDB code removal** — Deleting `skrafldb_ndb.py`, `src/db/ndb/`, and
  Google Cloud NDB dependencies (Phase 5).

### Deployment Variants

Dependencies are split to support both App Engine (NDB) and Docker (PostgreSQL)
deployments from the same codebase:

- **`requirements.txt`** — Base dependencies only (no SQLAlchemy or psycopg2).
  Used by App Engine, which reads `requirements.txt` directly.
- **`requirements-pg.txt`** — Includes `requirements.txt` via `-r` plus
  SQLAlchemy and psycopg2-binary. Used by the Dockerfile and for local
  development with `DATABASE_BACKEND=postgresql`.

This means App Engine deployments avoid installing ~20MB of unused PostgreSQL
packages. The PostgreSQL libraries are never imported on the NDB code path,
so they are safe to include but unnecessary.

### Containerized Deployment

A multi-stage `Dockerfile` and `docker-compose.yml` provide containerized
deployment for the PostgreSQL backend:

- **`docker-compose.yml`** — Standard deployment with app + Redis containers.
  Uses NDB by default (no `DATABASE_BACKEND` set). Suitable for deploying the
  current App Engine codebase in a container.
- **`docker-compose.local.yml`** — Local development variant using host
  networking to connect to PostgreSQL and Redis on localhost. Sets
  `DATABASE_BACKEND=postgresql`.

---

## Current Architecture Analysis

### NDB Model Inventory (18 Models)

| Model | Key Type | Parent/FK Relationships | Primary Use |
|-------|----------|------------------------|-------------|
| `UserModel` | String (`user_id`) | - | Main user entity, ~25 properties |
| `EloModel` | Composite `{uid}:{locale}` | Parent: UserModel | Locale-specific Elo ratings |
| `RobotModel` | String `robot-{level}:{locale}` | - | Robot Elo ratings per locale |
| `GameModel` | UUID string | FK: player0, player1 → UserModel | Game state + moves as JSON |
| `MoveModel` | Embedded | Part of GameModel | LocalStructuredProperty |
| `ImageModel` | Auto ID | FK: user → UserModel | User avatars/thumbnails |
| `FavoriteModel` | Auto ID | Parent: UserModel, FK: destuser | Favorite user relations |
| `ChallengeModel` | Auto ID | Parent: UserModel, FK: destuser | Game challenges |
| `StatsModel` | Auto ID | FK: user → UserModel | Daily statistics snapshots |
| `RatingModel` | Composite `{kind}:{rank}` | FK: user → UserModel | Precomputed rating tables |
| `ChatModel` | Auto ID | FK: user, recipient → UserModel | Chat messages |
| `ZombieModel` | Auto ID | FK: game → GameModel, player → UserModel | Unseen finished games |
| `PromoModel` | Auto ID | FK: player → UserModel | Promotion display tracking |
| `CompletionModel` | Auto ID | - | Batch process tracking |
| `BlockModel` | Auto ID | FK: blocker, blocked → UserModel | User blocking relations |
| `ReportModel` | Auto ID | FK: reporter, reported → UserModel | User reports |
| `TransactionModel` | UUID string | FK: user → UserModel | Subscription transactions |
| `SubmissionModel` | Auto ID | FK: user → UserModel | Word submissions |
| `RiddleModel` | Composite `{date}:{locale}` | - | Daily riddle data |

### Key Patterns in Current System

#### 1. String IDs (User-provided or UUID)
```python
# UserModel - user_id as string key
user = UserModel(id=user_id)

# GameModel - UUID as string key
game = GameModel(id=Unique.id())  # UUID v1

# TransactionModel - UUID as string key
tm = TransactionModel(id=Unique.id())
```

#### 2. Composite Keys
```python
# EloModel: {user_id}:{locale}
key_id = f"{uid}:{locale}"
em = EloModel(id=key_id, parent=Key(UserModel, uid), ...)

# RobotModel: robot-{level}:{locale}
key_id = f"robot-{level}:{locale}"
rm = RobotModel(id=key_id, ...)

# RatingModel: {kind}:{rank}
key_id = f"{kind}:{rank}"
rm = RatingModel(id=key_id, ...)

# RiddleModel: {date}:{locale}
key_id = f"{date_str}:{locale}"
riddle = RiddleModel(id=key_id, ...)
```

#### 3. Parent-Child (Ancestor) Relationships
```python
# EloModel has UserModel as ancestor
em = EloModel(id=elo_id, parent=Key(UserModel, uid), ...)

# FavoriteModel has UserModel as ancestor
fm = FavoriteModel(parent=Key(UserModel, src_id))

# ChallengeModel has UserModel as ancestor
cm = ChallengeModel(parent=Key(UserModel, src_id))
```

#### 4. KeyProperty References (Foreign Keys)
```python
# GameModel references UserModel
player0 = ndb.KeyProperty(kind=UserModel)
player1 = ndb.KeyProperty(kind=UserModel)

# ChatModel references UserModel for both sender and recipient
user = ndb.KeyProperty(kind=UserModel, required=True)
recipient = ndb.KeyProperty(kind=UserModel, required=False)
```

#### 5. Embedded Structured Data
```python
# MoveModel is embedded in GameModel
moves = ndb.LocalStructuredProperty(MoveModel, repeated=True, indexed=False)
```

### Query Patterns Used

| Pattern | NDB Code | Frequency |
|---------|----------|-----------|
| Get by ID | `Model.get_by_id(id)` | Very common |
| Simple equality filter | `Model.query(Model.prop == val)` | Very common |
| Multiple filters (AND) | `query.filter(ndb.AND(...))` | Common |
| Ancestor queries | `Model.query(ancestor=key)` | Common |
| Ordering | `query.order(-Model.prop)` | Common |
| Limit | `query.fetch(limit=N)` | Common |
| Keys-only queries | `query.fetch(keys_only=True)` | Common |
| Projection queries | `query.fetch(projection=[...])` | Occasional |
| Cursor-based pagination | `query.fetch_page(...)` | Occasional |
| Async queries | `query.fetch_async(...)` | Occasional |
| OR queries | `ndb.OR(...)` | Rare |
| Range queries | `Model.prop >= val` | Rare |

### Transaction Usage

**Only ONE transactional function exists in the codebase:**

```python
# src/logic.py:712
@ndb.transactional()
def submit_move(uuid: str, movelist: List[Any], movecount: int, validate: bool) -> ResponseType:
    """Idempotent, transactional function to process an incoming move"""
    game = Game.load(uuid, use_cache=False, set_locale=True) if uuid else None
    if game is None:
        return jsonify(result=Error.GAME_NOT_FOUND)
    # Make sure the client is in sync with the server
    if movecount != game.num_moves():
        return jsonify(result=Error.OUT_OF_SYNC)
    if game.player_id_to_move() != current_user_id():
        return jsonify(result=Error.WRONG_USER)
    return process_move(game, movelist, validate=validate)
```

This transaction:
- Loads a game (read)
- Validates the move count and current player
- Processes the move (read-modify-write of GameModel)
- Is designed to be idempotent

### Current Caching Architecture

NDB uses Redis for global caching via `ndb.RedisCache`:

```python
# src/skrafldb.py
_global_cache = ndb.RedisCache(memcache.get_redis_client())

@classmethod
def get_context(cls) -> ContextManager[ndb.Context]:
    return cls._client.context(global_cache=cls._global_cache)
```

The `cache.py` module provides a `RedisWrapper` class that:
- Wraps Redis client with memcache-like API
- Handles JSON serialization/deserialization
- Supports custom object serialization via `to_serializable`/`from_serializable`
- Provides namespace support, set operations, retry logic

---

## Target Architecture

### Database: PostgreSQL with SQLAlchemy ORM

#### Connection Configuration

> **Implementation note:** The actual connection management is in
> `src/db/postgresql/connection.py`. It uses `DatabaseConfig` for all settings
> and sets UTC timezone both via `connect_args` and an event listener.
> Session management is handled by `SessionManager` in `src/db/session.py`
> (see Source File Architecture section).

```python
# src/db/postgresql/connection.py (actual implementation)
from sqlalchemy import create_engine, event
from ..config import get_config

def create_db_engine(database_url=None, ...):
    config = get_config()
    engine = create_engine(
        database_url or config.database_url,
        pool_size=config.pool_size,
        max_overflow=config.max_overflow,
        pool_timeout=config.pool_timeout,
        pool_recycle=config.pool_recycle,
        echo=config.echo_sql,
        connect_args={"options": "-c timezone=utc"},
    )

    @event.listens_for(engine, "connect")
    def set_timezone(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("SET TIME ZONE 'UTC'")
        cursor.close()

    return engine
```

#### Collation for Multilingual Text

The application supports multiple locales (Icelandic, English, Polish, Norwegian) with mixed-language
user nicknames and text. PostgreSQL's ICU collations provide the best solution for universal text sorting.

**Unicode Root Collation (`und-x-icu`)**:
- Based on Unicode Collation Algorithm (UCA) / CLDR root
- Language-neutral, handles all Unicode characters sensibly
- Accented characters sort near their base letters (á near a, ö near o)
- Consistent behavior across all languages

The database should be created with ICU collation as the default.

**Requires PostgreSQL 15+** for `LOCALE_PROVIDER` / `ICU_LOCALE` syntax. Digital Ocean
managed PostgreSQL supports versions 13-16, so 15+ is available.

```sql
-- Verify ICU support is available
SELECT collname FROM pg_collation WHERE collprovider = 'i' LIMIT 5;

-- Create database with Unicode root collation
CREATE DATABASE netskrafl
    TEMPLATE template0
    ENCODING 'UTF8'
    LOCALE_PROVIDER icu
    ICU_LOCALE 'und'
    LC_COLLATE 'C'      -- Required placeholder when using ICU
    LC_CTYPE 'C';       -- Required placeholder when using ICU
```

**Language-Specific Sorting**: When strict Icelandic alphabetical order is needed (þ, æ, ö as
separate letters at the end), use explicit collation in queries:

```sql
-- Icelandic-specific ordering for leaderboards
SELECT nickname FROM users
WHERE locale = 'is_IS'
ORDER BY nickname COLLATE "is-IS-x-icu";

-- Or create an Icelandic-collated index for frequently used queries
CREATE INDEX ix_users_nickname_is ON users (nickname COLLATE "is-IS-x-icu");
```

### SQLAlchemy Model Definitions

#### UTC Timezone Handling

**Principle: All timestamps in the database are stored in UTC.**

PostgreSQL's `TIMESTAMP WITH TIME ZONE` type stores timestamps in UTC internally and converts to/from the session timezone on input/output. To ensure consistent UTC storage and retrieval:

1. **Database level**: Set the PostgreSQL timezone to UTC
2. **Connection level**: Set session timezone to UTC
3. **Application level**: Always use timezone-aware datetime objects with UTC

```python
# src/db/postgresql/connection.py - Connection with UTC timezone
engine = create_engine(
    url,
    connect_args={"options": "-c timezone=utc"},
    ...
)

@event.listens_for(engine, "connect")
def set_timezone(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("SET TIME ZONE 'UTC'")
    cursor.close()
```

#### Base Model and Patterns

> **Implementation note:** The actual implementation uses SQLAlchemy 2.0's
> `DeclarativeBase` with `Mapped` type annotations and `mapped_column()`
> instead of the 1.x-style `Column()` and `declarative_base()` shown in
> the original plan. The `UUIDMixin` and `TimestampMixin` were not used;
> instead, tables use the primary key strategy most natural for each entity:
> composite PKs for relationship/locale tables, string PKs for users and
> games (preserving NDB key formats), and `gen_random_uuid()` server defaults
> for entities that need auto-generated UUIDs.
>
> See `src/db/postgresql/models.py` for the actual definitions.

```python
# src/db/postgresql/models.py (actual implementation)
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

UTC = timezone.utc

def utcnow() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(UTC)

class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass
```

#### UserModel → User

> **Implementation note:** The actual User model uses `Mapped` type annotations,
> stores `email` and `image` as non-nullable (empty string instead of NULL,
> matching NDB behavior), uses `String(64)` for game FK references (not native
> UUID), and uses JSONB for `prefs`. A `relationship()` to `elo_ratings` was
> added for cascade deletion. See `src/db/postgresql/models.py`.

```python
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    nickname: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    inactive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email: Mapped[str] = mapped_column(String(256), nullable=False, default="", index=True)
    image: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    image_blob: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    account: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    plan: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    nick_lc: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    name_lc: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    locale: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, default="is_IS")
    location: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, default="")
    prefs: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ready_timed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    chat_disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    elo: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    human_elo: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    manual_elo: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    highest_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    highest_score_game: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    best_word: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    best_word_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    best_word_game: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    games: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    elo_ratings: Mapped[List["EloRating"]] = relationship(
        "EloRating", back_populates="user", cascade="all, delete-orphan"
    )
```

#### EloModel → EloRating

> **Implementation note:** Uses composite primary key `(user_id, locale)` instead
> of the plan's UUID PK + unique constraint. This is simpler and more natural
> for a table that is always looked up by user+locale. Includes a back-reference
> `relationship()` to `User`.

```python
class EloRating(Base):
    __tablename__ = "elo_ratings"

    # Composite primary key: user_id + locale
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    locale: Mapped[str] = mapped_column(String(10), primary_key=True)
    elo: Mapped[int] = mapped_column(Integer, nullable=False, default=1200, index=True)
    human_elo: Mapped[int] = mapped_column(Integer, nullable=False, default=1200, index=True)
    manual_elo: Mapped[int] = mapped_column(Integer, nullable=False, default=1200, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    user: Mapped["User"] = relationship("User", back_populates="elo_ratings")

    __table_args__ = (
        Index("ix_elo_ratings_locale_elo", "locale", "elo"),
        Index("ix_elo_ratings_locale_human_elo", "locale", "human_elo"),
        Index("ix_elo_ratings_locale_manual_elo", "locale", "manual_elo"),
    )
```

#### RobotModel → Robot

> **Implementation note:** Uses composite PK `(locale, level)` instead of UUID +
> unique constraint. Table named `robots` (not `robot_ratings`).

```python
class Robot(Base):
    __tablename__ = "robots"

    locale: Mapped[str] = mapped_column(String(10), primary_key=True)
    level: Mapped[int] = mapped_column(Integer, primary_key=True)
    elo: Mapped[int] = mapped_column(Integer, nullable=False, default=1200)
```

#### GameModel → Game (with JSONB moves)

> **Implementation note:** Game `id` is `String(64)` (not native UUID type),
> preserving compatibility with NDB's string-based UUIDs. The model includes
> `relationship()` definitions to `User` for `player0` and `player1`. Indexes
> are per-player composites rather than the combined four-column index.

```python
class Game(Base):
    __tablename__ = "games"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    player0_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    player1_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    locale: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    rack0: Mapped[str] = mapped_column(String(16), nullable=False)
    rack1: Mapped[str] = mapped_column(String(16), nullable=False)
    irack0: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    irack1: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    score0: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score1: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    to_move: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    robot_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    over: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    ts_last_move: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    moves: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    prefs: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    tile_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # ... Elo fields (elo0, elo1, elo0_adj, etc.) - same as plan

    player0: Mapped[Optional["User"]] = relationship("User", foreign_keys=[player0_id])
    player1: Mapped[Optional["User"]] = relationship("User", foreign_keys=[player1_id])

    __table_args__ = (
        Index("ix_games_player0_over", "player0_id", "over"),
        Index("ix_games_player1_over", "player1_id", "over"),
    )
```

#### ImageModel → Image

> **Implementation note:** Uses auto-generated UUID PK (`gen_random_uuid()`).
> Column named `fmt` (not `format`) to avoid shadowing the Python builtin.
> Unique index on `(user_id, fmt)`.

```python
class Image(Base):
    __tablename__ = "images"

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    fmt: Mapped[str] = mapped_column(String(32), nullable=False)
    image: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    __table_args__ = (
        Index("ix_images_user_fmt", "user_id", "fmt", unique=True),
    )
```

#### FavoriteModel → Favorite

> **Implementation note:** Uses composite PK `(src_user_id, dest_user_id)` —
> no UUID PK needed for a pure relationship table.

```python
class Favorite(Base):
    __tablename__ = "favorites"

    src_user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    dest_user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
```

#### ChallengeModel → Challenge

> **Implementation note:** Uses auto-generated UUID PK. Column names are
> `src_user_id`/`dest_user_id` (not `user_id`/`dest_user_id`).

```python
class Challenge(Base):
    __tablename__ = "challenges"

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    src_user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dest_user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prefs: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
```

#### StatsModel → Stats

> **Implementation note:** Uses auto-generated UUID PK. Same field structure
> as planned. See `src/db/postgresql/models.py` for actual definitions.

#### RatingModel → Rating

> **Implementation note:** Uses composite PK `(kind, rank)` instead of UUID +
> unique constraint. Includes full historical snapshot fields (yesterday, week
> ago, month ago). See `src/db/postgresql/models.py` for actual definitions.

#### ChatModel → Chat

> **Implementation note:** Table named `chats` (not `chat_messages`), class
> named `Chat`. Column named `msg` (not `message`). Uses auto-generated UUID PK.
> See `src/db/postgresql/models.py` for actual definitions.

#### ZombieModel → Zombie

> **Implementation note:** Table named `zombies`, class named `Zombie`. Uses
> composite PK `(game_id, user_id)` instead of UUID + unique constraint.
> `game_id` is `String(64)` (matching Game.id type), `user_id` (not `player_id`).

```python
class Zombie(Base):
    __tablename__ = "zombies"

    game_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("games.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
```

#### PromoModel → Promo

> **Implementation note:** Table named `promos`, class named `Promo`. Uses
> auto-generated UUID PK. Column named `user_id` (not `player_id`).
> See `src/db/postgresql/models.py` for actual definitions.

#### Remaining Models

> **Implementation note:** The following models all use auto-generated UUID PKs
> or composite PKs as appropriate. See `src/db/postgresql/models.py` for the
> actual definitions. Key naming differences from the plan:
>
> - **Completion** — Uses auto-generated UUID PK. `reason` is `Text` (not `String(256)`).
> - **Block** — Uses composite PK `(blocker_id, blocked_id)` instead of UUID + unique constraint.
> - **Report** — Uses auto-generated UUID PK. Same structure as planned.
> - **Transaction** — Uses auto-generated UUID PK. Timestamp column named `ts` (not `timestamp`).
> - **Submission** — Uses auto-generated UUID PK. Timestamp column named `ts` (not `timestamp`).
> - **Riddle** — Uses composite PK `(date, locale)` instead of UUID + unique constraint.

---

## Query Translation Patterns

### CRUD Operations

| Operation | NDB | SQLAlchemy |
|-----------|-----|------------|
| Get by ID | `Model.get_by_id(id)` | `session.get(Model, id)` |
| Create | `Model(id=id, ...); entity.put()` | `session.add(entity); session.commit()` |
| Update | `entity.prop = val; entity.put()` | `entity.prop = val; session.commit()` |
| Delete | `entity.key.delete()` | `session.delete(entity); session.commit()` |
| Bulk create | `ndb.put_multi(entities)` | `session.add_all(entities); session.commit()` |
| Bulk delete | `ndb.delete_multi(keys)` | `session.query(M).filter(M.id.in_(ids)).delete()` |

### Query Patterns

#### Simple Equality Filter
```python
# NDB
q = UserModel.query(UserModel.account == account)
user = q.get()

# SQLAlchemy
user = session.query(User).filter(User.account == account).first()
```

#### Multiple Filters (AND)
```python
# NDB
q = cls.query(ndb.AND(
    ImageModel.user == k,
    ImageModel.fmt == fmt,
))

# SQLAlchemy
from sqlalchemy import and_
image = session.query(Image).filter(
    and_(Image.user_id == uid, Image.format == fmt)
).first()
```

#### OR Filter
```python
# NDB
q = cls.query(
    ndb.OR(UserModel.locale == DEFAULT_LOCALE, UserModel.locale is None)
)

# SQLAlchemy
from sqlalchemy import or_
users = session.query(User).filter(
    or_(User.locale == DEFAULT_LOCALE, User.locale.is_(None))
).all()
```

#### Ordering
```python
# NDB
q = cls.query().order(-GameModel.ts_last_move)

# SQLAlchemy
games = session.query(Game).order_by(Game.ts_last_move.desc()).all()
```

#### Limit and Offset
```python
# NDB
results = q.fetch(limit=max_len)

# SQLAlchemy
results = q.limit(max_len).all()
```

#### Ancestor Queries → Foreign Key Filter
```python
# NDB (ancestor query)
q = FavoriteModel.query(ancestor=Key(UserModel, user_id))

# SQLAlchemy (foreign key filter)
favorites = session.query(Favorite).filter(Favorite.user_id == user_id).all()
```

#### Keys-Only Queries
```python
# NDB
keys = q.fetch(keys_only=True)

# SQLAlchemy (load only primary key)
from sqlalchemy.orm import load_only
ids = session.query(Game.id).filter(...).all()
```

#### Projection Queries
```python
# NDB
results = q.fetch(projection=["human_elo", "highest_score"])

# SQLAlchemy
from sqlalchemy.orm import load_only
results = session.query(User).options(
    load_only(User.human_elo, User.highest_score)
).filter(...).all()
```

#### Range Queries
```python
# NDB
q = cls.query(UserModel.nick_lc >= prefix).order(UserModel.nick_lc)

# SQLAlchemy
users = session.query(User).filter(
    User.nick_lc >= prefix
).order_by(User.nick_lc).all()
```

### Cursor-Based Pagination → Keyset Pagination

NDB uses opaque cursors for pagination. SQLAlchemy with PostgreSQL uses keyset pagination:

```python
# NDB
items, next_cursor, more = q.fetch_page(chunk_size, start_cursor=cursor)

# SQLAlchemy - Keyset pagination using last seen ID
def fetch_page(session, last_id=None, page_size=50):
    query = session.query(Game).order_by(Game.ts_last_move.desc(), Game.id)
    if last_id:
        # Get the timestamp of the last seen item
        last_item = session.get(Game, last_id)
        if last_item:
            query = query.filter(
                or_(
                    Game.ts_last_move < last_item.ts_last_move,
                    and_(
                        Game.ts_last_move == last_item.ts_last_move,
                        Game.id > last_id
                    )
                )
            )
    items = query.limit(page_size + 1).all()
    has_more = len(items) > page_size
    items = items[:page_size]
    next_id = items[-1].id if items and has_more else None
    return items, next_id, has_more
```

### Async Queries → Sequential Queries

```python
# NDB - Async queries (parallel execution to hide Datastore latency)
q0_future = q0.fetch_async(limit=max_len)
q1_future = q1.fetch_async(limit=max_len)
GameModelFuture.wait_all([q0_future, q1_future])
results0 = q0_future.get_result()
results1 = q1_future.get_result()

# SQLAlchemy - Sequential queries (PostgreSQL is fast, no need for parallelism)
results0 = session.query(Game).filter(Game.player0_id == uid).limit(max_len).all()
results1 = session.query(Game).filter(Game.player1_id == uid).limit(max_len).all()
```

**Why sequential is fine**: NDB's `fetch_async` was valuable because Google Cloud Datastore
has significant network latency per request. With PostgreSQL running nearby (same datacenter
or managed service), individual queries are fast enough that parallelizing them within a
single request provides little benefit. Request-level concurrency is handled by Gunicorn's
multiple workers.

**Note**: SQLAlchemy 1.4+ does support native async via `sqlalchemy.ext.asyncio`, but this
requires an async framework. With synchronous Flask, the standard sync API is appropriate.

---

## Transaction Handling

### The Single Transaction: `submit_move()`

The only NDB transaction in the codebase can be converted to SQLAlchemy session management.
The key principle: **use exceptions for control flow** so the session context manager can
reliably commit or rollback.

```python
# NDB version (current)
@ndb.transactional()
def submit_move(uuid: str, movelist: List[Any], movecount: int, validate: bool) -> ResponseType:
    game = Game.load(uuid, use_cache=False, set_locale=True)
    # ... validation ...
    return process_move(game, movelist, validate=validate)
```

### Actual Transaction Architecture

> **Implementation note:** The actual implementation uses a request-scoped
> session managed by `SessionManager` (in `src/db/session.py`) rather than
> the simple `db_transaction()` context manager proposed in the plan.

The transaction lifecycle is:

1. **Request-level transaction** — The WSGI middleware (`db_wsgi_middleware`)
   wraps each HTTP request in a `SessionManager.request_context()`. This
   creates a session, commits on success, and rolls back on exception.

2. **Nested transactions (savepoints)** — For operations that need explicit
   transaction boundaries within a request, `db.transaction()` creates a
   PostgreSQL savepoint:

```python
# PostgreSQL: savepoint-based nested transaction
class PostgreSQLTransactionContext:
    def __enter__(self):
        self._savepoint = self._backend._session.begin_nested()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self._savepoint.commit()   # Commit savepoint only
        else:
            self._savepoint.rollback() # Rollback to savepoint
```

3. **Usage in application code** — Business logic uses the request-scoped
   backend via `get_db()`. Changes accumulate in the session and are
   committed at request end:

```python
# In application code
db = get_db()
game = db.games.get_by_id(uuid)
db.games.update(game, moves=new_moves, score0=new_score)
# Commit happens at request end via WSGI middleware
```

For the `submit_move()` transaction specifically, the existing `@ndb.transactional()`
decorator becomes a `with db.transaction():` block when using the PostgreSQL backend.

**Key principles (unchanged from plan):**
1. **Exceptions for control flow** — validation failures raise exceptions, ensuring rollback
2. **Context manager owns the transaction** — always commits or rolls back
3. **Business logic is transaction-agnostic** — doesn't call commit/rollback

**Key principles:**
1. **Exceptions for control flow** - GameError for validation failures ensures rollback
2. **Context manager owns the transaction** - always commits or rolls back, never leaves session dangling
3. **Business logic is transaction-agnostic** - doesn't call commit/rollback, just raises on error
4. **Route handles response formatting** - converts results/errors to JSON

---

## Caching Strategy

### Why NDB Needed Redis Caching

Google Cloud Datastore (NDB) used Redis as an integral caching layer because:
- **High latency**: Datastore is a remote service requiring network round-trips
- **Query costs**: Datastore queries can be expensive (both in latency and billing)
- **No local buffer**: Unlike a traditional database, there's no local data cache

### Why PostgreSQL Doesn't Need Explicit Entity Caching

PostgreSQL with SQLAlchemy provides multiple layers of efficient caching out of the box:

1. **PostgreSQL Buffer Pool**: Frequently accessed data pages are cached in shared memory
2. **OS Page Cache**: The operating system caches database files
3. **SQLAlchemy Identity Map**: Within a session, loaded objects are cached automatically
4. **Connection Pooling**: Reuses connections, avoiding connection overhead
5. **Query Plan Caching**: PostgreSQL caches query execution plans

**Recommendation: Do not implement explicit Redis entity caching for PostgreSQL.**

The complexity of maintaining cache consistency (invalidation, TTL, etc.) is not
justified when PostgreSQL already handles this efficiently. Adding a Redis caching
layer would:
- Add latency (Redis round-trip) for cache misses
- Create cache invalidation complexity
- Risk serving stale data
- Add operational overhead

### When Redis is Still Useful

Redis remains valuable for other purposes in the application:

1. **Session storage**: User sessions (if not using database sessions)
2. **Rate limiting**: Request throttling
3. **Pub/sub**: Real-time notifications (though Firebase handles this currently)
4. **Expensive computations**: Caching aggregated data that's costly to compute
5. **Live user sets**: The existing `init_set`/`query_set` functionality for tracking online users

### Simplified Data Access Pattern

Without explicit caching, the data access layer becomes simpler. The actual
implementation uses typed repository protocols (see `src/db/protocols.py`) with
entity wrappers that hide ORM internals:

```python
# src/db/postgresql/repositories.py (simplified from actual implementation)

class UserRepository:
    """Repository for User entities - implements UserRepositoryProtocol."""

    def __init__(self, session: Session):
        self._session = session

    def get_by_id(self, user_id: str) -> Optional[UserEntity]:
        model = self._session.get(User, user_id)
        return UserEntity(model) if model else None

    def get_by_account(self, account: str) -> Optional[UserEntity]:
        model = self._session.query(User).filter(User.account == account).first()
        return UserEntity(model) if model else None

    def update(self, user: UserEntityProtocol, **kwargs: Any) -> None:
        model = self._session.get(User, user.key_id)
        for key, value in kwargs.items():
            setattr(model, key, value)

    def delete(self, user_id: str) -> None:
        self._session.query(User).filter(User.id == user_id).delete()
```

### Performance Optimization (If Needed Later)

If performance profiling reveals specific bottlenecks, targeted optimizations can be added:

1. **Eager loading**: Use `joinedload()` or `selectinload()` for relationships
2. **Query optimization**: Add database indexes for slow queries
3. **Read replicas**: Route read-heavy queries to replicas
4. **Selective caching**: Cache only specific expensive computations in Redis

```python
# Example: Eager loading to avoid N+1 queries
users_with_elo = session.query(User).options(
    selectinload(User.elo_ratings)
).filter(User.inactive == False).all()
```

---

## Data Migration Procedure

### Phase 1: Schema Creation

1. Create PostgreSQL database and user
2. Run SQLAlchemy `Base.metadata.create_all(engine)` to create tables
3. Create additional indexes as needed
4. Verify schema matches NDB model capabilities

```bash
# Create database with ICU collation for multilingual text sorting
psql -U postgres -c "CREATE DATABASE netskrafl
    TEMPLATE template0
    ENCODING 'UTF8'
    LOCALE_PROVIDER icu
    ICU_LOCALE 'und'
    LC_COLLATE 'C'
    LC_CTYPE 'C';"
psql -U postgres -c "CREATE USER netskrafl WITH PASSWORD 'xxx';"
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE netskrafl TO netskrafl;"
psql -U postgres -c "ALTER DATABASE netskrafl SET timezone TO 'UTC';"
```

### Phase 2: Dual-Write Period (Optional)

For zero-downtime migration:

1. Deploy code that writes to both NDB and PostgreSQL
2. Reads continue from NDB
3. Monitor for write failures
4. Duration: 1-2 weeks

```python
# Dual-write wrapper
class DualWriteRepository:
    def save(self, entity):
        # Write to NDB (primary)
        ndb_entity = self._ndb_repo.save(entity)
        # Write to PostgreSQL (shadow)
        try:
            self._pg_repo.save(entity)
        except Exception as e:
            logging.error(f"PostgreSQL shadow write failed: {e}")
        return ndb_entity
```

### Phase 3: Data Migration Script

**Note on timestamps**: NDB stores all timestamps in UTC (via `tzinfo=UTC` parameter).
These are migrated directly to PostgreSQL `TIMESTAMP WITH TIME ZONE` columns, which
also store in UTC. No timezone conversion is needed during migration.

**Note on UUIDs**: The existing NDB data uses UUID v1 (time-based) for Game and Transaction
primary keys. In the PostgreSQL schema, Game and Transaction IDs are stored as `VARCHAR(64)`
(not native UUID type), so the UUID v1 strings are preserved as-is during migration.

```python
# scripts/migrate_to_postgres.py

import logging
from datetime import UTC
from google.cloud import ndb
from sqlalchemy.orm import Session
from src.database import SessionLocal, engine
from src.models import Base, User, Game, EloRating, ...
from src.skrafldb import UserModel, GameModel, EloModel, ...

BATCH_SIZE = 500

def ensure_utc(dt):
    """Ensure a datetime is timezone-aware UTC (NDB should already provide this)"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Unlikely, but handle naive datetimes by assuming UTC
        return dt.replace(tzinfo=UTC)
    return dt

def migrate_users(ndb_client, pg_session: Session):
    """Migrate all users from NDB to PostgreSQL"""
    with ndb_client.context():
        count = 0
        for um in iter_q(UserModel.query(), chunk_size=BATCH_SIZE):
            user = User(
                id=um.key.id(),
                nickname=um.nickname,
                email=um.email,
                # Timestamps are already UTC from NDB
                created_at=ensure_utc(um.timestamp),
                last_login=ensure_utc(um.last_login),
                # ... map all fields
            )
            pg_session.add(user)
            count += 1
            if count % BATCH_SIZE == 0:
                pg_session.commit()
                logging.info(f"Migrated {count} users")
        pg_session.commit()
        logging.info(f"Total users migrated: {count}")

def migrate_games(ndb_client, pg_session: Session):
    """Migrate all games from NDB to PostgreSQL"""
    with ndb_client.context():
        count = 0
        for gm in iter_q(GameModel.query(), chunk_size=BATCH_SIZE):
            # Convert moves from LocalStructuredProperty to JSONB
            moves_json = [
                {
                    "coord": m.coord,
                    "tiles": m.tiles,
                    "score": m.score,
                    "rack": m.rack,
                    "timestamp": m.timestamp.isoformat() if m.timestamp else None,
                }
                for m in (gm.moves or [])
            ]
            game = Game(
                id=gm.key.id(),
                player0_id=gm.player0.id() if gm.player0 else None,
                player1_id=gm.player1.id() if gm.player1 else None,
                moves=moves_json,
                # ... map all fields
            )
            pg_session.add(game)
            count += 1
            if count % BATCH_SIZE == 0:
                pg_session.commit()
                logging.info(f"Migrated {count} games")
        pg_session.commit()
        logging.info(f"Total games migrated: {count}")

def main():
    # Create tables
    Base.metadata.create_all(engine)

    ndb_client = ndb.Client()
    pg_session = SessionLocal()

    try:
        # Order matters due to foreign key constraints
        migrate_users(ndb_client, pg_session)
        migrate_games(ndb_client, pg_session)
        migrate_elo_ratings(ndb_client, pg_session)
        # ... migrate remaining models
    finally:
        pg_session.close()

if __name__ == "__main__":
    main()
```

### Phase 4: Verification

```python
# scripts/verify_migration.py

def verify_counts():
    """Compare entity counts between NDB and PostgreSQL"""
    with ndb_client.context():
        ndb_users = UserModel.query().count()
    pg_users = pg_session.query(func.count(User.id)).scalar()
    assert ndb_users == pg_users, f"User count mismatch: {ndb_users} vs {pg_users}"
    # ... verify all models

def verify_sample_data():
    """Spot-check random entities for data integrity"""
    with ndb_client.context():
        # Get random user IDs
        sample_ids = random.sample([u.key.id() for u in UserModel.query()], 100)
        for uid in sample_ids:
            ndb_user = UserModel.get_by_id(uid)
            pg_user = pg_session.get(User, uid)
            assert ndb_user.nickname == pg_user.nickname
            assert ndb_user.elo == pg_user.elo
            # ... verify all fields
```

### Phase 5: Cutover

1. Set NDB to read-only (if possible) or schedule maintenance window
2. Run final migration delta (if dual-write was used)
3. Deploy new code that reads/writes only to PostgreSQL
4. Verify application functionality
5. Keep NDB data for rollback window (30 days recommended)

---

## Problem Areas and Solutions

### 1. Composite Keys

**Problem**: NDB uses composite string keys like `{user_id}:{locale}`

**Solution**: Use composite primary keys directly on the natural key columns.

> **Implementation note:** The original plan proposed UUID v7 PKs with unique
> constraints, but the implementation uses composite PKs instead. This is
> simpler, avoids a surrogate key, and is more natural for tables that are
> always looked up by their composite key.

```python
# Composite primary key (what was actually implemented)
class EloRating(Base):
    user_id: Mapped[str] = mapped_column(String(64), ..., primary_key=True)
    locale: Mapped[str] = mapped_column(String(10), primary_key=True)

# Similarly for: Favorite (src_user_id, dest_user_id),
# Robot (locale, level), Zombie (game_id, user_id),
# Block (blocker_id, blocked_id), Rating (kind, rank),
# Riddle (date, locale)
```

### 2. Parent-Child Relationships (Ancestor Keys)

**Problem**: NDB uses ancestor keys for entity groups and strong consistency

**Solution**: Convert to foreign keys; PostgreSQL provides strong consistency by default

```python
# NDB: FavoriteModel with ancestor
fm = FavoriteModel(parent=Key(UserModel, src_id))

# PostgreSQL: Foreign key
class Favorite(Base):
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"))
```

### 3. LocalStructuredProperty → JSONB

**Problem**: `MoveModel` is embedded in `GameModel` as `LocalStructuredProperty`

**Solution**: Store as JSONB array

```python
# NDB
moves = ndb.LocalStructuredProperty(MoveModel, repeated=True, indexed=False)

# PostgreSQL
moves = Column(JSONB, default=list)

# Access pattern change:
# NDB: game.moves[0].coord
# PostgreSQL: game.moves[0]["coord"]
```

### 4. Auto Timestamps (UTC)

**Problem**: NDB has `auto_now_add` for creation timestamps, always stored in UTC

**Solution**: Use SQLAlchemy `server_default` with UTC session timezone

```python
# NDB (always UTC via tzinfo=UTC parameter)
timestamp = ndb.DateTimeProperty(auto_now_add=True, tzinfo=UTC)

# SQLAlchemy - server_default uses database NOW() which is UTC due to session timezone
timestamp = Column(DateTime(timezone=True), server_default=func.now())

# For application-level timestamp assignment, always use UTC:
from datetime import UTC, datetime
entity.timestamp = datetime.now(UTC)
```

**Important**: The connection event handler (`SET TIME ZONE 'UTC'`) ensures that:
- `func.now()` returns UTC time
- Timestamps are stored and retrieved consistently in UTC
- No timezone conversion surprises occur

### 5. Index Requirements

**Problem**: NDB requires explicit index definitions in `index.yaml`

**Solution**: Define indexes in SQLAlchemy models using `Index` objects

```python
__table_args__ = (
    Index("ix_games_player0_over", "player0_id", "over"),
    Index("ix_games_player0_ts", "player0_id", "ts_last_move"),
)
```

### 6. Keys-Only Queries

**Problem**: NDB allows fetching only entity keys without loading full entities

**Solution**: Query for primary key column only

```python
# NDB
keys = q.fetch(keys_only=True)
ids = [k.id() for k in keys]

# SQLAlchemy
ids = [id for (id,) in session.query(Model.id).filter(...).all()]
```

### 7. OR Queries

**Problem**: NDB `ndb.OR()` for disjunctive queries

**Solution**: SQLAlchemy `or_()` function

```python
# NDB
q = cls.query(ndb.OR(UserModel.locale == DEFAULT_LOCALE, UserModel.locale is None))

# SQLAlchemy
from sqlalchemy import or_
q = session.query(User).filter(or_(User.locale == DEFAULT_LOCALE, User.locale.is_(None)))
```

---

## Testing Strategy

> **Implementation note:** The actual test infrastructure is significantly more
> comprehensive than originally planned. See `tests/db/conftest.py` for the
> full fixture setup.

### Multi-Backend Test Framework

The test suite supports running against either or both backends via CLI flags:

```bash
# Run against NDB only
venv/bin/pytest tests/db/ --backend=ndb

# Run against PostgreSQL only
venv/bin/pytest tests/db/ --backend=postgresql

# Run against both backends (default)
venv/bin/pytest tests/db/ --backend=both
```

Tests are parametrized to run against each backend, verifying that both
produce identical results for all repository operations.

### Test Database

PostgreSQL tests use a local test database:

```
postgresql://test:test@localhost:5432/netskrafl_test
```

Tables are dropped and recreated at the start of each test session. Each
test gets a clean backend via the `clean_backend` fixture, which rolls back
changes after each test.

### Test Coverage

16 test files covering all 18 repositories (~5,000 lines total):

- `test_user_repository.py` — CRUD, prefix search, similar Elo, multi-fetch
- `test_game_repository.py` — CRUD, live/finished game listing, move management
- `test_elo_repository.py` — Create, upsert, locale-specific ratings
- `test_stats_repository.py` — Stats history, Elo-ordered listing
- `test_chat_repository.py` — Messages, channels, history
- `test_favorite_repository.py`, `test_challenge_repository.py`,
  `test_block_repository.py`, `test_zombie_repository.py` — Relationship CRUD
- `test_image_repository.py` — Binary data storage and retrieval
- `test_rating_repository.py`, `test_riddle_repository.py` — Specialized queries
- `test_misc_repositories.py` — Report, Promo, Transaction, Submission, Completion
- `test_robot_repository.py` — Robot rating management

### Migration Verification Tests (Future)

```python
def test_migration_data_integrity():
    """Verify migrated data matches source"""
    # Compare random samples from both databases
    # Check field-by-field equality
    # Verify relationship integrity
```

---

## Source File Architecture

> **Implementation note:** This section has been updated to reflect the actual
> architecture. The original plan proposed a simple facade + `compat.py`
> NDB-wrapper approach. The implementation uses a protocol-based repository
> architecture. On the PostgreSQL side, ORM models satisfy entity protocols
> directly (the original entity wrapper layer was eliminated). On the NDB side,
> lightweight entity wrappers adapt NDB model instances to the same protocols.

### Design Goals

1. **Drop-in replacement** - Existing imports (`from skrafldb import UserModel`) continue to work
2. **Side-by-side operation** - Both NDB and PostgreSQL backends available during migration
3. **Same API** - PostgreSQL backend exposes NDB-compatible methods via `skrafldb_pg.py`
4. **Backend switching** - Environment variable selects active backend
5. **Clean separation** - Each backend in its own package
6. **Protocol contracts** - Both backends implement the same typed interfaces
7. **Dual API** - Old NDB API for existing code, new repository API for new/refactored code

### Directory Structure

```
src/
  skrafldb.py              # Facade: imports from skrafldb_ndb or skrafldb_pg
  skrafldb_ndb.py          # Original NDB implementation (unchanged)
  skrafldb_pg.py           # PostgreSQL NDB-compatible facade (~2,100 lines)
                           # Delegates to PG repositories via get_db()

  db/
    __init__.py            # Exports: init_session_manager, get_db, db_wsgi_middleware
    config.py              # DatabaseConfig dataclass with from_env()
    session.py             # SessionManager: request-scoped backends, WSGI middleware
    protocols.py           # All protocols, entity contracts, shared data types (~1,420 lines)
    testing.py             # Test infrastructure helpers

    postgresql/
      __init__.py          # Exports PostgreSQLBackend
      backend.py           # PostgreSQLBackend (implements DatabaseBackendProtocol)
      connection.py        # create_db_engine() with UTC timezone
      models.py            # SQLAlchemy 2.0 ORM models (satisfy entity protocols directly)
      repositories.py      # 18 repository implementations

    ndb/
      __init__.py          # Exports NDBBackend
      backend.py           # NDBBackend (implements DatabaseBackendProtocol)
      entities.py          # Entity wrappers adapting NDB models to entity protocols
      repositories.py      # Repository implementations wrapping skrafldb_ndb
```

### Key Files

#### `db/config.py` — Backend Configuration

A `DatabaseConfig` dataclass that reads from environment variables with defaults:

```python
@dataclass
class DatabaseConfig:
    backend: str              # "ndb" or "postgresql"
    database_url: Optional[str]
    pool_size: int            # Default: 5
    max_overflow: int         # Default: 10
    pool_timeout: int         # Default: 30
    pool_recycle: int         # Default: 1800
    echo_sql: bool            # For debugging

    @classmethod
    def from_env(cls) -> DatabaseConfig:
        """Create configuration from environment variables."""
        ...
```

#### `db/session.py` — Session Management

The `SessionManager` class provides request-scoped database backends using
thread-local storage:

```python
class SessionManager:
    """Manages database sessions and backend lifecycle."""

    def __init__(self, backend_type=None, database_url=None): ...

    def get_backend(self) -> DatabaseBackendProtocol:
        """Get or create the request-scoped backend instance."""
        ...

    @contextmanager
    def request_context(self) -> Iterator[DatabaseBackendProtocol]:
        """Context manager: creates backend, yields it, commits/rolls back, cleans up."""
        ...
```

Module-level functions for convenience:

```python
def init_session_manager(backend_type=None, database_url=None) -> SessionManager: ...
def get_db() -> DatabaseBackendProtocol: ...
def db_wsgi_middleware(wsgi_app) -> wsgi_app: ...
```

The WSGI middleware wraps each request with `request_context()`. For NDB, it
also establishes the NDB client context. For PostgreSQL, the session is committed
on success and rolled back on exception.

#### `db/protocols.py` — Interface Contracts

Defines all shared types and protocols:

- **~30 data types**: `EloDict`, `MoveDict`, `PrefsDict`, `LiveGameInfo`,
  `FinishedGameInfo`, `ZombieGameInfo`, `ChallengeInfo`, `ChatMessage`,
  `RatingInfo`, `StatsInfo`, etc. (as dataclasses and TypedDicts)
- **7 entity protocols**: `UserEntityProtocol`, `GameEntityProtocol`,
  `EloEntityProtocol`, `StatsEntityProtocol`, `ChatEntityProtocol`,
  `RiddleEntityProtocol`, plus base `EntityProtocol`
- **18 repository protocols**: `UserRepositoryProtocol`,
  `GameRepositoryProtocol`, `EloRepositoryProtocol`, etc.
- **`DatabaseBackendProtocol`**: Top-level interface with properties for
  each repository, plus `commit()`, `rollback()`, `close()`,
  `transaction()` methods

#### `skrafldb.py` — Old API Facade

```python
from src.db.config import get_config
_config = get_config()
if _config.backend == "postgresql":
    from skrafldb_pg import *
else:
    from skrafldb_ndb import *
```

#### `skrafldb_pg.py` — PostgreSQL NDB-Compatible API

This ~2,100-line module provides the same `UserModel`, `GameModel`, etc. classes
as `skrafldb_ndb.py`, but delegates all operations to the PostgreSQL repositories
via `get_db()`. Each model class method calls the appropriate repository method:

```python
class UserModel:
    @staticmethod
    def fetch(user_id: str) -> Optional[UserModel]:
        db = _get_db()
        entity = db.users.get_by_id(user_id)
        return UserModel._from_entity(entity) if entity else None

    @staticmethod
    def list_prefix(prefix, max_len=50, locale=None):
        db = _get_db()
        return list(db.users.list_prefix(prefix, max_len, locale))
    # ... etc.
```

#### `db/postgresql/backend.py` — PostgreSQL Backend

The `PostgreSQLBackend` class implements `DatabaseBackendProtocol`. It creates
a SQLAlchemy session and exposes repository instances as properties:

```python
class PostgreSQLBackend:
    def __init__(self, database_url=None):
        self._session = Session(bind=engine)
        self._users = UserRepository(self._session)
        self._games = GameRepository(self._session)
        # ...

    @property
    def users(self) -> UserRepositoryProtocol: return self._users
    @property
    def games(self) -> GameRepositoryProtocol: return self._games

    def transaction(self) -> PostgreSQLTransactionContext:
        """Create a savepoint (nested transaction)."""
        return PostgreSQLTransactionContext(self)

    def commit(self): self._session.commit()
    def rollback(self): self._session.rollback()
    def close(self): self._session.close()
```

#### `db/postgresql/models.py` — ORM Models as Entity Implementations

The SQLAlchemy ORM models directly satisfy the entity protocols defined in
`protocols.py`, eliminating the need for a separate entity wrapper layer.
This was achieved by adding `key_id` properties and a few computed properties
to the ORM model classes:

```python
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    nickname: Mapped[str] = mapped_column(String(128), nullable=False)
    # ... all columns as Mapped[T] descriptors

    @property
    def key_id(self) -> str:
        return self.id
```

For models with richer protocol requirements (e.g., `Game` with its `moves`
property that converts JSONB dicts to `MoveDict` objects, or `Riddle` with
its parsed `riddle` property), the computed properties and lazy caching are
built into the ORM model class itself.

Repositories return ORM model instances directly (e.g., `Optional[User]`
instead of `Optional[UserEntity]`). The `backend.py` uses `cast()` for
repository properties where pyright cannot statically verify that
`Mapped[T]` descriptors satisfy `@property` protocol members (they do
at runtime).

**Benefits of this simplification:**
- Eliminated ~540 lines of boilerplate wrapper code
- Reduced the number of files to update per new column from 5 to 3
- Removed an indirection layer, making debugging more straightforward

### Migration Path with This Structure

| Phase | DATABASE_BACKEND | Behavior |
|-------|------------------|----------|
| Development | `ndb` | Current behavior, no changes |
| Testing | `postgresql` | Test PostgreSQL backend locally |
| Dual-write | `ndb` | NDB primary, PostgreSQL shadow writes |
| Cutover | `postgresql` | PostgreSQL primary |
| Cleanup | `postgresql` | Remove NDB code |

### Benefits

1. **Zero changes to business logic** - `from skrafldb import UserModel` works with either backend
2. **Gradual migration** - Switch backends with an environment variable
3. **Easy rollback** - Set `DATABASE_BACKEND=ndb` to revert
4. **Testable in isolation** - Test PostgreSQL backend without affecting production
5. **Clear code organization** - Each backend is self-contained

---

## Implementation Phases

### Phase 1: Create PostgreSQL Backend (Parallel to NDB) — COMPLETE

The PostgreSQL backend infrastructure is fully implemented. What was actually
built differs from the original plan in architecture (see Implementation Status
section above), but achieves all the same goals.

**What was done:**

1. Created `src/db/` package with protocol-based repository architecture
2. Created `src/db/protocols.py` with all shared types, entity protocols,
   and repository protocols (~1,420 lines)
3. Created `src/db/session.py` with `SessionManager` and WSGI middleware
4. Created `src/db/postgresql/` with SQLAlchemy 2.0 models, repositories,
   backend class, and connection management
5. Created `src/db/ndb/` with backend class, entity wrappers, and
   repositories wrapping `skrafldb_ndb.py`
6. Created `skrafldb_pg.py` — NDB-compatible API delegating to PG repositories
7. Refactored `skrafldb.py` into a facade selecting between `skrafldb_ndb`
   and `skrafldb_pg`
8. Created comprehensive test suite (`tests/db/`, ~5,000 lines, 16 test files)
   with multi-backend parametrization
9. Eliminated the PostgreSQL entity wrapper layer (`entities.py`) — ORM
   models now satisfy entity protocols directly, reducing boilerplate
10. Split `requirements.txt` into base (App Engine) and PostgreSQL (Docker)
    variants to avoid unnecessary dependencies per deployment target
11. Created `Dockerfile` and `docker-compose.yml` for containerized deployment

**Key decision: NDB code stayed in place.** Rather than moving `skrafldb.py`
to `src/db/ndb/models.py`, the original file was renamed to `skrafldb_ndb.py`
and the `src/db/ndb/` package wraps it via the repository pattern. This
minimized risk and kept the original code untouched.

**Key simplification: No entity wrappers on the PostgreSQL side.** Initially,
`__slots__`-based entity wrappers were created to insulate application code
from SQLAlchemy internals. In practice, these wrappers were pure boilerplate
— every property simply delegated to the underlying ORM model. By adding
`key_id` properties and a few computed properties directly to the ORM models,
the wrapper layer was eliminated entirely (~540 lines removed).

### Phase 2: Testing and Integration — IN PROGRESS

1. Repository-level tests pass against both backends (`--backend=both`)
2. Containerized deployment tested via `docker-compose.local.yml` with
   `DATABASE_BACKEND=postgresql` against local PostgreSQL and Redis
3. Full application integration testing with the production-like stack
   still to be done
4. Dual-write mode not yet needed — direct cutover may be sufficient given
   the test coverage

### Phase 3: Migrate Data — NOT STARTED

1. Create migration scripts (`scripts/migrate_to_postgres.py`)
2. Run migration in batches
3. Verify data integrity
4. Document any data issues found

### Phase 4: Switch to PostgreSQL — NOT STARTED

1. Set `DATABASE_BACKEND=postgresql` in production environment
2. Monitor application logs and performance
3. Keep NDB code available for quick rollback (`DATABASE_BACKEND=ndb`)
4. Run for 1-2 weeks to build confidence

**No code changes required** — the backend switch is purely configuration:

```bash
DATABASE_BACKEND=postgresql
```

**Rollback procedure** (if needed):
```bash
DATABASE_BACKEND=ndb  # Instantly reverts to NDB
```

### Phase 5: Remove NDB Code — NOT STARTED

After PostgreSQL has been stable in production:

1. Remove `src/db/ndb/` directory
2. Remove `skrafldb_ndb.py`
3. Simplify `src/db/session.py` to always use PostgreSQL
4. Remove `google-cloud-ndb` from `requirements.txt`
5. Move SQLAlchemy and psycopg2-binary from `requirements-pg.txt` to
   `requirements.txt` (no longer need separate variants)
6. Remove `requirements-pg.txt`
7. Remove NDB client initialization from `src/main.py`
8. Simplify `skrafldb.py` to import directly from `skrafldb_pg`
9. Remove `DATABASE_BACKEND` configuration (no longer needed)

---

## Appendix: Environment Variables

```bash
# Database backend selection: "ndb" (default) or "postgresql"
DATABASE_BACKEND=postgresql

# PostgreSQL connection (required when DATABASE_BACKEND=postgresql)
DATABASE_URL=postgresql://user:password@host:5432/netskrafl

# Connection pool settings (optional, have defaults)
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=1800

# SQL statement logging (optional, for debugging)
DB_ECHO_SQL=false

# Redis (unchanged from current setup)
REDIS_URL=redis://localhost:6379
# or legacy:
REDISHOST=localhost
REDISPORT=6379
```

---

## Appendix: Database Schema SQL

> **Implementation note:** This SQL schema was written as part of the original plan
> and has not yet been updated to match the actual SQLAlchemy models. The actual
> schema is defined by `src/db/postgresql/models.py` and created via
> `Base.metadata.create_all(engine)`. Key differences from this SQL include:
> different table names (e.g., `robots` not `robot_ratings`, `chats` not
> `chat_messages`, `zombies` not `zombie_games`), composite primary keys
> instead of UUID PKs for several tables, and `VARCHAR(64)` instead of native
> `UUID` type for Game IDs. The SQL below is retained for reference but should
> not be used directly; use the SQLAlchemy models as the source of truth.

For reference, here is the original planned PostgreSQL schema as raw SQL.

**Important notes**:
- All `TIMESTAMP WITH TIME ZONE` columns store values in UTC
- The database uses ICU Unicode root collation (`und`) for multilingual text sorting
- Use `COLLATE "is-IS-x-icu"` in queries when strict Icelandic alphabetical order is needed

```sql
-- =============================================================================
-- DATABASE CREATION (run as postgres superuser)
-- =============================================================================

-- Create database with ICU collation for multilingual text sorting
-- The 'und' (undetermined) locale uses Unicode CLDR root collation rules,
-- which provide sensible sorting for mixed-language text (Icelandic, English,
-- Polish, Norwegian nicknames, etc.)
--
-- NOTE: This syntax requires PostgreSQL 15+. For PostgreSQL 10-14, ICU collations
-- must be created separately and applied per-column or per-index.
CREATE DATABASE netskrafl
    TEMPLATE template0
    ENCODING 'UTF8'
    LOCALE_PROVIDER icu
    ICU_LOCALE 'und'
    LC_COLLATE 'C'
    LC_CTYPE 'C';

-- Set default timezone to UTC
ALTER DATABASE netskrafl SET timezone TO 'UTC';

-- Create application user
CREATE USER netskrafl WITH PASSWORD 'xxx';
GRANT ALL PRIVILEGES ON DATABASE netskrafl TO netskrafl;

-- =============================================================================
-- SCHEMA (run as netskrafl user, connected to netskrafl database)
-- =============================================================================

-- Enable UUID extension (required for gen_random_uuid() fallback)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Note on UUIDs:
-- - Existing data from NDB uses UUID v1 for Game and Transaction IDs
--   (preserved during migration as VARCHAR(64) strings)
-- - Tables that need auto-generated UUIDs use gen_random_uuid() server default
-- - Many tables use composite primary keys instead of surrogate UUID PKs
-- - User and Game IDs are VARCHAR(64), not native UUID type

-- Users table
-- Note: user IDs remain VARCHAR as they come from OAuth providers (Google, Apple, Facebook)
CREATE TABLE users (
    id VARCHAR(64) PRIMARY KEY,  -- OAuth provider ID, not a UUID
    nickname VARCHAR(128) NOT NULL,
    email VARCHAR(256),
    image VARCHAR(512),
    image_blob BYTEA,
    account VARCHAR(256),
    plan VARCHAR(32),
    nick_lc VARCHAR(128),
    name_lc VARCHAR(128),
    inactive BOOLEAN NOT NULL DEFAULT FALSE,
    locale VARCHAR(10) DEFAULT 'is_IS',
    location VARCHAR(10) DEFAULT '',
    prefs JSONB,
    last_login TIMESTAMP WITH TIME ZONE,
    ready BOOLEAN DEFAULT TRUE,
    ready_timed BOOLEAN DEFAULT TRUE,
    chat_disabled BOOLEAN DEFAULT FALSE,
    -- Legacy Elo scores (indexed; locale-specific data is in elo_ratings table)
    elo INTEGER DEFAULT 0,
    human_elo INTEGER DEFAULT 0,
    manual_elo INTEGER DEFAULT 0,
    highest_score INTEGER DEFAULT 0,
    highest_score_game UUID,  -- FK added after games table exists
    best_word VARCHAR(32),
    best_word_score INTEGER DEFAULT 0,
    best_word_game UUID,  -- FK added after games table exists
    games INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE
);

-- Games table
CREATE TABLE games (
    id UUID PRIMARY KEY,  -- UUID v7, generated by application
    player0_id VARCHAR(64) REFERENCES users(id) ON DELETE SET NULL,
    player1_id VARCHAR(64) REFERENCES users(id) ON DELETE SET NULL,
    locale VARCHAR(10),
    rack0 VARCHAR(16) NOT NULL,
    rack1 VARCHAR(16) NOT NULL,
    irack0 VARCHAR(16),
    irack1 VARCHAR(16),
    score0 INTEGER DEFAULT 0,
    score1 INTEGER DEFAULT 0,
    to_move INTEGER DEFAULT 0,
    robot_level INTEGER DEFAULT 0,
    over BOOLEAN NOT NULL DEFAULT FALSE,
    tile_count INTEGER,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ts_last_move TIMESTAMP WITH TIME ZONE,
    moves JSONB DEFAULT '[]',
    prefs JSONB,
    elo0 INTEGER,
    elo1 INTEGER,
    elo0_adj INTEGER,
    elo1_adj INTEGER,
    human_elo0 INTEGER,
    human_elo1 INTEGER,
    human_elo0_adj INTEGER,
    human_elo1_adj INTEGER,
    manual_elo0 INTEGER,
    manual_elo1 INTEGER,
    manual_elo0_adj INTEGER,
    manual_elo1_adj INTEGER
);

-- Add foreign keys from users to games (after games table exists)
ALTER TABLE users
    ADD CONSTRAINT fk_users_highest_game
    FOREIGN KEY (highest_score_game) REFERENCES games(id) ON DELETE SET NULL;

ALTER TABLE users
    ADD CONSTRAINT fk_users_best_game
    FOREIGN KEY (best_word_game) REFERENCES games(id) ON DELETE SET NULL;

-- Elo ratings table
CREATE TABLE elo_ratings (
    id UUID PRIMARY KEY,  -- UUID v7, generated by application
    user_id VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    locale VARCHAR(10) NOT NULL,
    elo INTEGER DEFAULT 1200,
    human_elo INTEGER DEFAULT 1200,
    manual_elo INTEGER DEFAULT 1200,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE,
    UNIQUE(user_id, locale)
);

-- Robot ratings table
CREATE TABLE robot_ratings (
    id UUID PRIMARY KEY,  -- UUID v7, generated by application
    level INTEGER NOT NULL,
    locale VARCHAR(10) NOT NULL,
    elo INTEGER DEFAULT 1200,
    UNIQUE(level, locale)
);

-- Images table
CREATE TABLE images (
    id UUID PRIMARY KEY,  -- UUID v7, generated by application
    user_id VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    format VARCHAR(16) NOT NULL,
    image BYTEA NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    UNIQUE(user_id, format)
);

-- Favorites table
CREATE TABLE favorites (
    id UUID PRIMARY KEY,  -- UUID v7, generated by application
    user_id VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    dest_user_id VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    UNIQUE(user_id, dest_user_id)
);

-- Challenges table
CREATE TABLE challenges (
    id UUID PRIMARY KEY,  -- UUID v7, generated by application
    user_id VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    dest_user_id VARCHAR(64) REFERENCES users(id) ON DELETE CASCADE,
    prefs JSONB,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Stats table
CREATE TABLE stats (
    id UUID PRIMARY KEY,  -- UUID v7, generated by application
    user_id VARCHAR(64) REFERENCES users(id) ON DELETE CASCADE,
    robot_level INTEGER DEFAULT 0,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    games INTEGER DEFAULT 0,
    human_games INTEGER DEFAULT 0,
    manual_games INTEGER DEFAULT 0,
    elo INTEGER DEFAULT 1200,
    human_elo INTEGER DEFAULT 1200,
    manual_elo INTEGER DEFAULT 1200,
    score INTEGER DEFAULT 0,
    human_score INTEGER DEFAULT 0,
    manual_score INTEGER DEFAULT 0,
    score_against INTEGER DEFAULT 0,
    human_score_against INTEGER DEFAULT 0,
    manual_score_against INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    human_wins INTEGER DEFAULT 0,
    human_losses INTEGER DEFAULT 0,
    manual_wins INTEGER DEFAULT 0,
    manual_losses INTEGER DEFAULT 0
);

-- Ratings table (precomputed rankings)
CREATE TABLE ratings (
    id UUID PRIMARY KEY,  -- UUID v7, generated by application
    kind VARCHAR(16) NOT NULL,
    rank INTEGER NOT NULL,
    user_id VARCHAR(64) REFERENCES users(id) ON DELETE SET NULL,
    robot_level INTEGER DEFAULT 0,
    games INTEGER DEFAULT 0,
    elo INTEGER DEFAULT 1200,
    score INTEGER DEFAULT 0,
    score_against INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    rank_yesterday INTEGER DEFAULT 0,
    games_yesterday INTEGER DEFAULT 0,
    elo_yesterday INTEGER DEFAULT 1200,
    -- ... additional historical fields
    UNIQUE(kind, rank)
);

-- Chat messages table
CREATE TABLE chat_messages (
    id UUID PRIMARY KEY,  -- UUID v7, generated by application
    channel VARCHAR(128) NOT NULL,
    user_id VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recipient_id VARCHAR(64) REFERENCES users(id) ON DELETE CASCADE,
    message TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Zombie games table
CREATE TABLE zombie_games (
    id UUID PRIMARY KEY,  -- UUID v7, generated by application
    game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    player_id VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    UNIQUE(game_id, player_id)
);

-- Promotions table
CREATE TABLE promotions (
    id UUID PRIMARY KEY,  -- UUID v7, generated by application
    player_id VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    promotion VARCHAR(64) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Completions table (audit log for batch processes)
CREATE TABLE completions (
    id UUID PRIMARY KEY,  -- UUID v7, generated by application
    proctype VARCHAR(32) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ts_from TIMESTAMP WITH TIME ZONE NOT NULL,
    ts_to TIMESTAMP WITH TIME ZONE NOT NULL,
    success BOOLEAN NOT NULL DEFAULT TRUE,
    reason VARCHAR(256) DEFAULT ''
);

-- Blocks table
CREATE TABLE blocks (
    id UUID PRIMARY KEY,  -- UUID v7, generated by application
    blocker_id VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    blocked_id VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    UNIQUE(blocker_id, blocked_id)
);

-- Reports table
CREATE TABLE reports (
    id UUID PRIMARY KEY,  -- UUID v7, generated by application
    reporter_id VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reported_id VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code INTEGER NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Transactions table
CREATE TABLE transactions (
    id UUID PRIMARY KEY,  -- UUID v7, generated by application
    user_id VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    plan VARCHAR(32) NOT NULL,
    kind VARCHAR(32) NOT NULL,
    op VARCHAR(32) NOT NULL
);

-- Submissions table (write-only, no indexes needed beyond PK/FK)
CREATE TABLE submissions (
    id UUID PRIMARY KEY,  -- UUID v7, generated by application
    user_id VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    locale VARCHAR(10) NOT NULL,
    word VARCHAR(64) NOT NULL,
    comment TEXT DEFAULT ''
);

-- Riddles table
CREATE TABLE riddles (
    id UUID PRIMARY KEY,  -- UUID v7, generated by application
    date VARCHAR(10) NOT NULL,
    locale VARCHAR(10) NOT NULL,
    riddle_json TEXT NOT NULL,
    created TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    version INTEGER DEFAULT 1,
    UNIQUE(date, locale)
);

-- =============================================================================
-- INDEXES (from index.yaml)
-- =============================================================================

-- Users table indexes
CREATE INDEX ix_users_nickname ON users(nickname);
CREATE INDEX ix_users_email ON users(email);
CREATE INDEX ix_users_account ON users(account);
CREATE INDEX ix_users_nick_lc ON users(nick_lc);
CREATE INDEX ix_users_name_lc ON users(name_lc);
CREATE INDEX ix_users_elo ON users(elo);
CREATE INDEX ix_users_human_elo ON users(human_elo);
CREATE INDEX ix_users_manual_elo ON users(manual_elo);
CREATE INDEX ix_users_highest_score ON users(highest_score);
CREATE INDEX ix_users_best_word_score ON users(best_word_score);
-- Composite indexes from index.yaml
CREATE INDEX ix_users_locale_nick ON users(locale, nick_lc);
CREATE INDEX ix_users_locale_name ON users(locale, name_lc);
-- Leaderboard indexes: NDB has both ASC and DESC on human_elo with highest_score ASC.
-- This mixed ordering requires two indexes in PostgreSQL (bidirectional scan only
-- works when ALL columns reverse together).
CREATE INDEX ix_users_locale_elo_score ON users(locale, human_elo, highest_score);
CREATE INDEX ix_users_locale_elo_desc_score ON users(locale, human_elo DESC, highest_score);

-- Games table indexes (from index.yaml)
CREATE INDEX ix_games_over_players_ts ON games(over, player0_id, player1_id, ts_last_move DESC);
CREATE INDEX ix_games_over_ts ON games(over, ts_last_move);

-- Elo ratings table indexes (from index.yaml)
CREATE INDEX ix_elo_locale_elo ON elo_ratings(locale, elo DESC);
CREATE INDEX ix_elo_locale_human_elo ON elo_ratings(locale, human_elo);
CREATE INDEX ix_elo_locale_manual_elo ON elo_ratings(locale, manual_elo DESC);

-- Challenges table indexes (from index.yaml)
CREATE INDEX ix_challenges_dest_ts ON challenges(dest_user_id, timestamp);
CREATE INDEX ix_challenges_user_ts ON challenges(user_id, timestamp);

-- Stats table indexes (from index.yaml)
CREATE INDEX ix_stats_robot_user_ts ON stats(robot_level, user_id, timestamp DESC);
CREATE INDEX ix_stats_ts_elo ON stats(timestamp, elo DESC);
CREATE INDEX ix_stats_ts_human_elo ON stats(timestamp, human_elo DESC);
CREATE INDEX ix_stats_ts_manual_elo ON stats(timestamp, manual_elo DESC);

-- Chat messages table indexes (from index.yaml)
CREATE INDEX ix_chat_channel_ts ON chat_messages(channel, timestamp DESC);
CREATE INDEX ix_chat_user_ts ON chat_messages(user_id, timestamp DESC);
CREATE INDEX ix_chat_recipient_ts ON chat_messages(recipient_id, timestamp DESC);

-- Promotions table indexes (from index.yaml)
CREATE INDEX ix_promo_player_type_ts ON promotions(player_id, promotion, timestamp);

-- Transactions table indexes (from index.yaml)
CREATE INDEX ix_transactions_user_ts ON transactions(user_id, timestamp DESC);

-- Completions table indexes (for log viewing)
CREATE INDEX ix_completions_timestamp ON completions(timestamp DESC);
CREATE INDEX ix_completions_success_ts ON completions(success, timestamp DESC);

-- Riddles table indexes
CREATE INDEX ix_riddle_date ON riddles(date);
```
