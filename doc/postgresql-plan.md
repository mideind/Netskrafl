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

```python
# src/database.py (new file)
import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://user:pass@localhost:5432/netskrafl"
)

engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=5,           # Base connections
    max_overflow=10,       # Additional connections under load
    pool_timeout=30,       # Wait time for connection
    pool_recycle=1800,     # Recycle connections after 30 min
    pool_pre_ping=True,    # Check connection health
)

# Ensure all connections use UTC timezone
@event.listens_for(engine, "connect")
def set_timezone(dbapi_connection, connection_record):
    """Set session timezone to UTC for consistent timestamp handling"""
    cursor = dbapi_connection.cursor()
    cursor.execute("SET TIME ZONE 'UTC'")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db() -> Session:
    """Dependency for Flask request context"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
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
# src/database.py - Connection with UTC timezone
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

engine = create_engine(DATABASE_URL, ...)

@event.listens_for(engine, "connect")
def set_timezone(dbapi_connection, connection_record):
    """Ensure all connections use UTC timezone"""
    cursor = dbapi_connection.cursor()
    cursor.execute("SET TIME ZONE 'UTC'")
    cursor.close()
```

#### Base Model with Common Patterns

```python
# src/models/base.py
import uuid
from datetime import UTC, datetime
from sqlalchemy import Column, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()

def new_uuid() -> uuid.UUID:
    """Generate a new UUID v7 (time-ordered) for use as primary key.

    UUID v7 is preferred over UUID v4 for database primary keys because:
    - Time-ordered: better B-tree index locality and performance
    - Sortable: naturally orders by creation time
    - Unique: same guarantees as UUID v4

    Note: Existing data migrated from NDB uses UUID v1. Both UUID v1 and v7
    are compatible and coexist in the same tables - they're all valid 128-bit UUIDs.

    Requires Python 3.11+ for uuid.uuid7(), or use uuid7 package for earlier versions.
    """
    # Python 3.11+ has native uuid7 support
    # For earlier versions, use: from uuid_extensions import uuid7
    try:
        return uuid.uuid7()
    except AttributeError:
        # Fallback for Python < 3.11: use uuid4 or install uuid7 package
        # pip install uuid7
        from uuid_extensions import uuid7
        return uuid7()

class TimestampMixin:
    """Mixin for auto-managed UTC timestamps"""
    # server_default uses database's now() which will be in UTC due to session timezone
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        onupdate=lambda: datetime.now(UTC)
    )

class UUIDMixin:
    """Mixin for UUID primary key using UUID v7 (time-ordered)"""
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=new_uuid,
        nullable=False
    )

# Helper for application-level timestamp creation
def utc_now() -> datetime:
    """Return current UTC timestamp for use in application code"""
    return datetime.now(UTC)
```

#### UserModel → User

```python
# src/models/user.py
from sqlalchemy import Column, String, Boolean, Integer, DateTime, Text, LargeBinary, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

class User(Base, TimestampMixin):
    __tablename__ = "users"

    # User IDs remain VARCHAR as they come from OAuth providers (Google, Apple, Facebook)
    id = Column(String(64), primary_key=True)  # OAuth provider user ID, not a UUID
    nickname = Column(String(128), nullable=False, index=True)
    email = Column(String(256), index=True)
    image = Column(String(512))  # URL
    image_blob = Column(LargeBinary)  # JPEG data
    account = Column(String(256), index=True)  # OAuth2 account
    plan = Column(String(32))  # Subscription plan
    nick_lc = Column(String(128), index=True)  # Lowercase nickname
    name_lc = Column(String(128), index=True)  # Lowercase full name
    inactive = Column(Boolean, nullable=False, default=False)
    locale = Column(String(10), default="is_IS")
    location = Column(String(10), default="")
    prefs = Column(JSON)  # PrefsDict
    last_login = Column(DateTime(timezone=True))
    ready = Column(Boolean, default=True)
    ready_timed = Column(Boolean, default=True)
    chat_disabled = Column(Boolean, default=False)

    # Legacy Elo scores (locale-independent, for backward compatibility)
    # Real locale-specific Elo data is in the EloRating table
    elo = Column(Integer, default=0, index=True)
    human_elo = Column(Integer, default=0, index=True)
    manual_elo = Column(Integer, default=0, index=True)

    # Best scores
    highest_score = Column(Integer, default=0, index=True)
    highest_score_game = Column(
        UUID(as_uuid=True),
        ForeignKey("games.id", ondelete="SET NULL")
    )
    best_word = Column(String(32))
    best_word_score = Column(Integer, default=0, index=True)
    best_word_game = Column(
        UUID(as_uuid=True),
        ForeignKey("games.id", ondelete="SET NULL")
    )
    games = Column(Integer, default=0)  # Human game count

    # Note: No SQLAlchemy relationship() definitions. The existing codebase uses
    # explicit fetches (e.g., EloModel.load(user_id)) rather than ORM navigation.
    # This keeps the migration simpler. Deletion cascades are handled by the
    # ForeignKey ON DELETE clauses at the database level.

    # Composite indexes from index.yaml
    __table_args__ = (
        # NDB: (locale, nick_lc) - for locale-filtered user search by nickname
        Index("ix_users_locale_nick", "locale", "nick_lc"),
        # NDB: (locale, name_lc) - for locale-filtered user search by name
        Index("ix_users_locale_name", "locale", "name_lc"),
        # NDB: (locale, human_elo, highest_score) - for leaderboard queries
        # Note: NDB has two indexes with human_elo ASC and DESC. In PostgreSQL,
        # a single B-tree index supports bidirectional scans, but only if ALL
        # columns reverse together. The NDB indexes suggest mixed ordering
        # (human_elo DESC with highest_score ASC), which requires a separate index.
        # We define the DESC index via raw SQL after table creation - see Appendix.
        Index("ix_users_locale_elo_score", "locale", "human_elo", "highest_score"),
    )
```

#### EloModel → EloRating

```python
# src/models/elo.py
from sqlalchemy import Column, String, Integer, ForeignKey, UniqueConstraint

class EloRating(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "elo_ratings"

    # id is UUID from UUIDMixin
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    locale = Column(String(10), nullable=False)
    elo = Column(Integer, default=1200)
    human_elo = Column(Integer, default=1200)
    manual_elo = Column(Integer, default=1200)

    # Indexes from index.yaml
    __table_args__ = (
        # Unique constraint replaces NDB composite key (ancestor + locale)
        UniqueConstraint("user_id", "locale", name="uq_user_locale"),
        # NDB: (locale, elo DESC) - for locale-specific leaderboards
        Index("ix_elo_locale_elo", "locale", "elo"),
        # NDB: (locale, human_elo DESC) and (locale, human_elo ASC)
        Index("ix_elo_locale_human_elo", "locale", "human_elo"),
        # NDB: (locale, manual_elo DESC)
        Index("ix_elo_locale_manual_elo", "locale", "manual_elo"),
    )
```

#### RobotModel → RobotRating

```python
class RobotRating(Base, UUIDMixin):
    __tablename__ = "robot_ratings"

    # id is UUID from UUIDMixin
    level = Column(Integer, nullable=False)
    locale = Column(String(10), nullable=False)
    elo = Column(Integer, default=1200)

    __table_args__ = (
        UniqueConstraint("level", "locale", name="uq_robot_level_locale"),
    )
```

#### GameModel → Game (with JSONB moves)

```python
# src/models/game.py
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

class Game(Base, UUIDMixin):
    __tablename__ = "games"

    # id is UUID from UUIDMixin
    # Existing games preserve their UUID v1 from NDB; new games use UUID v7
    player0_id = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"))
    player1_id = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"))
    locale = Column(String(10))

    # Racks (current state) - not indexed, only used for game state
    rack0 = Column(String(16), nullable=False)
    rack1 = Column(String(16), nullable=False)

    # Initial racks (for game replay) - not indexed
    irack0 = Column(String(16))
    irack1 = Column(String(16))

    # Scores
    score0 = Column(Integer, default=0)
    score1 = Column(Integer, default=0)

    # Game state
    to_move = Column(Integer, default=0)  # 0 or 1
    robot_level = Column(Integer, default=0)
    over = Column(Boolean, nullable=False, default=False, index=True)
    tile_count = Column(Integer)

    # Timestamps
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    ts_last_move = Column(DateTime(timezone=True), index=True)

    # Moves stored as JSONB array
    # Each move: {"coord": "H8", "tiles": "HELLO", "score": 24, "rack": "ABC", "timestamp": "..."}
    moves = Column(JSONB, default=list)

    # Game preferences
    prefs = Column(JSONB)  # PrefsDict

    # Elo statistics (populated when game ends)
    elo0 = Column(Integer)
    elo1 = Column(Integer)
    elo0_adj = Column(Integer)
    elo1_adj = Column(Integer)
    human_elo0 = Column(Integer)
    human_elo1 = Column(Integer)
    human_elo0_adj = Column(Integer)
    human_elo1_adj = Column(Integer)
    manual_elo0 = Column(Integer)
    manual_elo1 = Column(Integer)
    manual_elo0_adj = Column(Integer)
    manual_elo1_adj = Column(Integer)

    # Note: No relationship() definitions needed - the existing code pattern
    # fetches users explicitly via UserModel.fetch(player0_id) rather than
    # using ORM-style navigation. This keeps the migration simpler.

    # Indexes for common queries (derived from index.yaml)
    # Note: For DESC ordering in indexes, we define them after the class or use raw SQL
    __table_args__ = (
        # Primary game list query: find active/finished games for both players, ordered by last move
        # NDB: (over, player0, player1, ts_last_move DESC)
        Index("ix_games_over_players_ts", "over", "player0_id", "player1_id", "ts_last_move"),
        # Game list filtered by over status, ordered by last move
        # NDB: (over, ts_last_move)
        Index("ix_games_over_ts", "over", "ts_last_move"),
    )
```

#### ImageModel → Image

```python
class Image(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "images"

    # id is UUID from UUIDMixin
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    format = Column(String(16), nullable=False)  # 'jpeg', 'thumb384', 'thumb512'
    image = Column(LargeBinary, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "format", name="uq_user_format"),
    )
```

#### FavoriteModel → Favorite

```python
class Favorite(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "favorites"

    # id is UUID from UUIDMixin
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    dest_user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "dest_user_id", name="uq_favorite_pair"),
        Index("ix_favorites_user", "user_id"),
        Index("ix_favorites_dest", "dest_user_id"),
    )
```

#### ChallengeModel → Challenge

```python
class Challenge(Base, UUIDMixin):
    __tablename__ = "challenges"

    # id is UUID from UUIDMixin
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    dest_user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"))
    prefs = Column(JSONB)  # PrefsDict
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    # Indexes from index.yaml (timestamp only queried via these composites)
    __table_args__ = (
        # NDB: (destuser, timestamp)
        Index("ix_challenges_dest_ts", "dest_user_id", "timestamp"),
        # NDB: ancestor + (timestamp) → user_id is the ancestor
        Index("ix_challenges_user_ts", "user_id", "timestamp"),
    )
```

#### StatsModel → Stats

```python
class Stats(Base, UUIDMixin):
    __tablename__ = "stats"

    # id is UUID from UUIDMixin
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"))
    robot_level = Column(Integer, default=0)  # Indexed via composite index only
    timestamp = Column(DateTime(timezone=True), server_default=func.now())  # Leading column in composites

    games = Column(Integer, default=0)
    human_games = Column(Integer, default=0)
    manual_games = Column(Integer, default=0)

    elo = Column(Integer, default=1200, index=True)
    human_elo = Column(Integer, default=1200, index=True)
    manual_elo = Column(Integer, default=1200, index=True)

    score = Column(Integer, default=0)
    human_score = Column(Integer, default=0)
    manual_score = Column(Integer, default=0)

    score_against = Column(Integer, default=0)
    human_score_against = Column(Integer, default=0)
    manual_score_against = Column(Integer, default=0)

    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    human_wins = Column(Integer, default=0)
    human_losses = Column(Integer, default=0)
    manual_wins = Column(Integer, default=0)
    manual_losses = Column(Integer, default=0)

    # Indexes from index.yaml
    __table_args__ = (
        # NDB: (robot_level, user, timestamp DESC) - for user stats history
        Index("ix_stats_robot_user_ts", "robot_level", "user_id", "timestamp"),
        # NDB: (timestamp, elo DESC) - for leaderboards at a point in time
        Index("ix_stats_ts_elo", "timestamp", "elo"),
        # NDB: (timestamp, human_elo DESC)
        Index("ix_stats_ts_human_elo", "timestamp", "human_elo"),
        # NDB: (timestamp, manual_elo DESC)
        Index("ix_stats_ts_manual_elo", "timestamp", "manual_elo"),
    )
```

#### RatingModel → Rating

```python
class Rating(Base, UUIDMixin):
    __tablename__ = "ratings"

    # id is UUID from UUIDMixin
    kind = Column(String(16), nullable=False, index=True)  # 'all', 'human', 'manual'
    rank = Column(Integer, nullable=False, index=True)
    user_id = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"))
    robot_level = Column(Integer, default=0)

    # Current values
    games = Column(Integer, default=0)
    elo = Column(Integer, default=1200)
    score = Column(Integer, default=0)
    score_against = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)

    # Historical snapshots (yesterday, week ago, month ago)
    # ... (same pattern as RatingModel)

    __table_args__ = (
        UniqueConstraint("kind", "rank", name="uq_rating_kind_rank"),
    )
```

#### ChatModel → ChatMessage

```python
class ChatMessage(Base, UUIDMixin):
    __tablename__ = "chat_messages"

    # id is UUID from UUIDMixin
    channel = Column(String(128), nullable=False)  # Leading column in composite
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    recipient_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"))
    message = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    # Indexes from index.yaml (standalone indexes not needed - composites cover all queries)
    __table_args__ = (
        # NDB: (channel, timestamp DESC)
        Index("ix_chat_channel_ts", "channel", "timestamp"),
        # NDB: (user, timestamp DESC)
        Index("ix_chat_user_ts", "user_id", "timestamp"),
        # NDB: (recipient, timestamp DESC)
        Index("ix_chat_recipient_ts", "recipient_id", "timestamp"),
    )
```

#### ZombieModel → ZombieGame

```python
from sqlalchemy.dialects.postgresql import UUID

class ZombieGame(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "zombie_games"

    # id is UUID from UUIDMixin
    game_id = Column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    player_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        UniqueConstraint("game_id", "player_id", name="uq_zombie_game_player"),
        Index("ix_zombie_player", "player_id"),
    )
```

#### PromoModel → Promotion

```python
class Promotion(Base, UUIDMixin):
    __tablename__ = "promotions"

    # id is UUID from UUIDMixin
    player_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    promotion = Column(String(64), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    # Index from index.yaml: (player, promotion, timestamp) - no standalone indexes needed
    __table_args__ = (
        Index("ix_promo_player_type_ts", "player_id", "promotion", "timestamp"),
    )
```

#### CompletionModel → Completion

```python
class Completion(Base, UUIDMixin):
    __tablename__ = "completions"

    # id is UUID from UUIDMixin
    proctype = Column(String(32), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    ts_from = Column(DateTime(timezone=True), nullable=False)
    ts_to = Column(DateTime(timezone=True), nullable=False)
    success = Column(Boolean, nullable=False, default=True)
    reason = Column(String(256), default="")

    # Indexes for log viewing (ordered by timestamp, optionally filtered by success)
    __table_args__ = (
        Index("ix_completions_success_ts", "success", "timestamp"),
    )
```

#### BlockModel → Block

```python
class Block(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "blocks"

    # id is UUID from UUIDMixin
    blocker_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    blocked_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        UniqueConstraint("blocker_id", "blocked_id", name="uq_block_pair"),
        Index("ix_blocks_blocker", "blocker_id"),
        Index("ix_blocks_blocked", "blocked_id"),
    )
```

#### ReportModel → Report

```python
class Report(Base, UUIDMixin):
    __tablename__ = "reports"

    # id is UUID from UUIDMixin
    reporter_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reported_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    code = Column(Integer, nullable=False)
    text = Column(Text, nullable=False, default="")
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_reports_reported", "reported_id"),
    )
```

#### TransactionModel → Transaction

```python
class Transaction(Base, UUIDMixin):
    __tablename__ = "transactions"

    # id is UUID from UUIDMixin
    # Existing transactions preserve their UUID v1 from NDB; new ones use UUID v7
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    plan = Column(String(32), nullable=False)
    kind = Column(String(32), nullable=False)
    op = Column(String(32), nullable=False)

    # Index from index.yaml: (user, ts DESC) - for user transaction history
    __table_args__ = (
        Index("ix_transactions_user_ts", "user_id", "timestamp"),
    )
```

#### SubmissionModel → Submission

```python
class Submission(Base, UUIDMixin):
    __tablename__ = "submissions"

    # id is UUID from UUIDMixin
    # Note: This is a write-only table for word submissions; no indexes needed beyond PK and FK
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    locale = Column(String(10), nullable=False)
    word = Column(String(64), nullable=False)
    comment = Column(Text, default="")
```

#### RiddleModel → Riddle

```python
class Riddle(Base, UUIDMixin):
    __tablename__ = "riddles"

    # id is UUID from UUIDMixin
    date = Column(String(10), nullable=False)  # YYYY-MM-DD
    locale = Column(String(10), nullable=False)
    riddle_json = Column(Text, nullable=False)
    created = Column(DateTime(timezone=True), server_default=func.now())
    version = Column(Integer, default=1)

    __table_args__ = (
        UniqueConstraint("date", "locale", name="uq_riddle_date_locale"),
        Index("ix_riddle_date", "date"),
    )
```

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

The only NDB transaction in the codebase can be converted to SQLAlchemy session management:

```python
# NDB version (current)
@ndb.transactional()
def submit_move(uuid: str, movelist: List[Any], movecount: int, validate: bool) -> ResponseType:
    game = Game.load(uuid, use_cache=False, set_locale=True)
    # ... validation ...
    return process_move(game, movelist, validate=validate)

# SQLAlchemy version
def submit_move(session: Session, uuid: str, movelist: List[Any], movecount: int, validate: bool) -> ResponseType:
    try:
        # Load game with row-level lock for update
        game = session.query(Game).filter(Game.id == uuid).with_for_update().first()
        if game is None:
            return jsonify(result=Error.GAME_NOT_FOUND)

        # Validation
        if movecount != len(game.moves):
            return jsonify(result=Error.OUT_OF_SYNC)
        if game_player_id_to_move(game) != current_user_id():
            return jsonify(result=Error.WRONG_USER)

        # Process move (modifies game object)
        result = process_move(session, game, movelist, validate=validate)

        # Commit transaction
        session.commit()
        return result

    except Exception:
        session.rollback()
        raise
```

Key changes:
1. Pass session as parameter (dependency injection)
2. Use `with_for_update()` for row-level locking (SELECT FOR UPDATE)
3. Explicit `commit()` and `rollback()`
4. The function is no longer decorated - transaction boundary is explicit

### Session Management Pattern

```python
# Flask request context manager
from contextlib import contextmanager

@contextmanager
def db_session():
    """Provide a transactional scope around a series of operations."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

# Usage in Flask route
@app.route("/api/submitmove", methods=["POST"])
def submitmove():
    with db_session() as session:
        return submit_move(session, uuid, movelist, movecount, validate)
```

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

Without explicit caching, the data access layer becomes simpler:

```python
# src/repositories/user.py - Simple repository without caching

class UserRepository:
    """Repository for User entities"""

    def __init__(self, session: Session):
        self._session = session

    def get_by_id(self, user_id: str) -> Optional[User]:
        """Get a user by ID"""
        return self._session.get(User, user_id)

    def get_by_account(self, account: str) -> Optional[User]:
        """Get a user by OAuth account ID"""
        return self._session.query(User).filter(User.account == account).first()

    def save(self, user: User) -> None:
        """Save a user"""
        self._session.add(user)

    def delete(self, user: User) -> None:
        """Delete a user"""
        self._session.delete(user)
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
primary keys. These are fully compatible with PostgreSQL's native `UUID` type and will be
preserved as-is during migration. After migration, new records will be created with UUID v7
(also time-ordered, but with improved randomness). Both UUID versions coexist without issues
in the same table - they are all valid 128-bit UUIDs.

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

**Solution**: Use UUID v7 primary keys with unique constraints on the composite columns

```python
# Preferred: UUID primary key + unique constraint
class EloRating(Base, UUIDMixin):
    # id is UUID v7 from UUIDMixin - time-ordered for good index performance
    user_id = Column(String(64), nullable=False)
    locale = Column(String(10), nullable=False)
    __table_args__ = (UniqueConstraint("user_id", "locale"),)

# Alternative: Keep composite string key (not recommended)
class EloRating(Base):
    id = Column(String(128), primary_key=True)  # "{uid}:{locale}"

    @classmethod
    def make_id(cls, user_id: str, locale: str) -> str:
        return f"{user_id}:{locale}"
```

**Why UUID v7 is preferred:**
- Time-ordered: maintains B-tree index locality (unlike random UUID v4)
- No coordination needed: can generate IDs in application without database round-trip
- Globally unique: safe for distributed systems and data migration
- PostgreSQL native: efficient 16-byte storage with native `UUID` type

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

### Unit Tests with Test Database

```python
# tests/conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.models import Base

TEST_DATABASE_URL = "postgresql://test:test@localhost:5432/netskrafl_test"

@pytest.fixture(scope="session")
def engine():
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)

@pytest.fixture
def session(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.rollback()
    session.close()
```

### Integration Tests

```python
# tests/test_user_repository.py

def test_user_crud(session):
    repo = UserRepository(session, entity_cache)

    # Create
    user = User(id="test123", nickname="TestUser", inactive=False)
    repo.save(user)

    # Read
    loaded = repo.get_by_id("test123")
    assert loaded.nickname == "TestUser"

    # Update
    loaded.nickname = "UpdatedUser"
    repo.save(loaded)
    reloaded = repo.get_by_id("test123")
    assert reloaded.nickname == "UpdatedUser"

    # Delete
    repo.delete(loaded)
    assert repo.get_by_id("test123") is None
```

### Migration Verification Tests

```python
def test_migration_data_integrity():
    """Verify migrated data matches source"""
    # Compare random samples from both databases
    # Check field-by-field equality
    # Verify relationship integrity
```

### Performance Tests

```python
def test_query_performance():
    """Ensure critical queries meet performance requirements"""
    import time

    start = time.time()
    # Run the query being tested
    games = session.query(Game).filter(
        Game.player0_id == test_user_id,
        Game.over == False
    ).order_by(Game.ts_last_move.desc()).limit(20).all()
    elapsed = time.time() - start

    assert elapsed < 0.5, f"Query too slow: {elapsed}s"
```

---

## Implementation Phases

### Phase 1: Add SQLAlchemy Models (Parallel to NDB)

**Duration**: 1-2 weeks

1. Create `src/models/` directory with all model definitions
2. Create `src/database.py` for connection management
3. Create `src/repositories/` for data access layer
4. Add unit tests for new models
5. No changes to production code paths

**Files to create:**
- `src/database.py`
- `src/models/__init__.py`
- `src/models/base.py`
- `src/models/user.py`
- `src/models/game.py`
- `src/models/elo.py`
- `src/models/...` (one file per model or grouped logically)
- `src/repositories/__init__.py`
- `src/repositories/user.py`
- `src/repositories/game.py`
- `src/repositories/...`

### Phase 2: Implement Dual-Write (Optional)

**Duration**: 1-2 weeks

1. Create dual-write wrappers for repositories
2. Add PostgreSQL writes as shadow operations
3. Monitor for errors and performance
4. Build confidence in PostgreSQL data

**Files to modify:**
- `src/skrafldb.py` - Add dual-write hooks
- `src/cache.py` - Enhance for PostgreSQL caching

### Phase 3: Migrate Data

**Duration**: 1 week (depending on data volume)

1. Create migration scripts
2. Run migration in batches
3. Verify data integrity
4. Document any data issues found

**Files to create:**
- `scripts/migrate_to_postgres.py`
- `scripts/verify_migration.py`

### Phase 4: Switch Reads to PostgreSQL

**Duration**: 1 week

1. Update repositories to read from PostgreSQL
2. Keep NDB writes as backup
3. Monitor for consistency issues
4. Gradual rollout (feature flags)

**Files to modify:**
- `src/repositories/*.py` - Switch to PostgreSQL reads
- `src/skraflgame.py` - Use new repositories
- `src/skrafluser.py` - Use new repositories
- `src/logic.py` - Use new repositories
- `src/api.py` - Use new session management

### Phase 5: Remove NDB Code

**Duration**: 1 week

1. Remove NDB dependencies
2. Clean up dual-write code
3. Remove NDB model definitions
4. Update tests
5. Update deployment configuration

**Files to modify/delete:**
- `src/skrafldb.py` - Remove or archive
- `requirements.txt` - Remove `google-cloud-ndb`
- `src/main.py` - Remove NDB client initialization

---

## Appendix: Environment Variables

```bash
# PostgreSQL connection
DATABASE_URL=postgresql://user:password@host:5432/netskrafl

# Connection pool settings (optional, have defaults)
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=1800

# Redis (unchanged from current setup)
REDIS_URL=redis://localhost:6379
# or legacy:
REDISHOST=localhost
REDISPORT=6379
```

---

## Appendix: Database Schema SQL

For reference, here is the complete PostgreSQL schema as raw SQL.

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
-- - Existing data from NDB uses UUID v1 (preserved during migration)
-- - New records use UUID v7 (time-ordered, better index performance than UUID v4)
-- - Both UUID versions are compatible and coexist in the same tables
-- - Application generates UUIDs using Python's uuid.uuid7() (Python 3.11+)
--   or the uuid7 package for earlier versions

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
