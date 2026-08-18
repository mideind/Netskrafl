"""

    Datastore -> PostgreSQL data migration tool

    Copyright © 2026 Miðeind ehf.

    Migrates all Netskrafl/Explo entities from Google Cloud Datastore
    to a PostgreSQL database with the schema owned by Alembic
    (src/db/postgresql/models.py). Design: doc/data-migration-design.md.

    Key properties:

    * Reads Datastore over the REST API (the gRPC client library is
      pathologically slow on the development box - see the design doc),
      with parallel key-range shards for the heavy kinds.
    * Decodes entities through google-cloud-ndb's own deserialization
      (model._entity_from_protobuf) with the real skrafldb_ndb model
      classes, so legacy LocalStructuredProperty blobs, timestamps etc.
      are interpreted by the exact code the production app uses.
    * All writes are idempotent upserts (INSERT ... ON CONFLICT);
      progress is checkpointed in a _migration_state table in the target
      database, in the same transaction as each batch, so an interrupted
      run can be resumed with --resume without double-writing.
    * Two-phase operation: --mode bulk copies everything (optionally
      after --truncate); --mode delta --since T0 re-copies only what may
      have changed - the heavy kinds via indexed timestamp filters, the
      small kinds via full delete-and-reload (which also removes rows
      deleted in Datastore since T0).

    Usage example (bulk rehearsal for explo-dev into a local database):

      venv/bin/python scripts/migrate_to_postgres.py \\
          --project explo-dev \\
          --database-url postgresql://test:test@localhost:5432/migrate_smoke \\
          --mode bulk --truncate --shards 8 --verify 50

    Then, inside the cutover write freeze:

      venv/bin/python scripts/migrate_to_postgres.py \\
          --project explo-dev --database-url ... \\
          --mode delta --since 2026-09-01T00:00:00+00:00

    The tool never runs inside the container image (scripts/ is
    docker/gcloud-ignored) and must run against a schema at Alembic
    head (checked at startup; --skip-schema-check to override).

    NOTE: importing the NDB model layer pulls in src/config.py, which
    needs project credentials and (in local mode) a local Redis at
    REDISHOST:REDISPORT. The tool sets the standard local-dev
    environment variables itself, derived from --project/--credentials.

"""

from __future__ import annotations

from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
)

import argparse
import logging
import os
import random
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"

# Fixed namespace for deriving deterministic PostgreSQL UUID primary keys
# from Datastore keys. Never change this: the uuid5(kind + key path)
# mapping is what makes delta-pass upserts idempotent across runs.
MIGRATION_NS = uuid5(NAMESPACE_URL, "https://github.com/mideind/Netskrafl/data-migration")

# Sentinel for required timestamps that are missing at the source
SENTINEL_TS = datetime(2000, 1, 1, tzinfo=UTC)

Row = Tuple[Any, ...]
EntityJson = Dict[str, Any]

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger("migrate")


# ---------------------------------------------------------------------------
# Small coercion helpers (NDB was schemaless; ten years of entities include
# properties that are None where the PG schema says NOT NULL)


def utc_ts(v: Optional[datetime]) -> Optional[datetime]:
    """NDB returns naive UTC datetimes; PG columns are timestamptz."""
    if v is None:
        return None
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


def iso_z(dt: datetime) -> str:
    """RFC3339 UTC timestamp for Datastore REST filters."""
    dt = dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    return dt.replace(tzinfo=None).isoformat() + "Z"


def move_to_dict(m: Any) -> Dict[str, Any]:
    """Convert an NDB MoveModel to the games.moves JSONB element shape.
    Must match skrafldb_pg.MoveModel.to_dict() exactly - that is the
    canonical shape the PG backend reads and writes."""
    d: Dict[str, Any] = {"coord": m.coord or "", "tiles": m.tiles or "", "score": m.score or 0}
    if m.rack is not None:
        d["rack"] = m.rack
    ts = utc_ts(m.timestamp)
    if ts is not None:
        d["timestamp"] = ts.isoformat()
    return d


def ent_uuid(key: Any) -> UUID:
    """Deterministic UUID for an entity, derived from its full key path."""
    flat = ":".join(str(p) for p in key.flat())
    return uuid5(MIGRATION_NS, flat)


# ---------------------------------------------------------------------------
# Datastore REST reader


class DatastoreReader:
    """Reads entities of a kind over the Datastore REST API with
    continuous cursor paging, retry/backoff and token refresh."""

    RETRY_STATUS = {429, 500, 502, 503, 504}

    def __init__(self, project: str, creds_path: str) -> None:
        # Imported lazily so the module can be inspected without deps
        import requests
        from google.oauth2 import service_account

        self.project = project
        self.url = f"https://datastore.googleapis.com/v1/projects/{project}:runQuery"
        self.creds = service_account.Credentials.from_service_account_file(
            creds_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        self.session = requests.Session()

    def _headers(self) -> Dict[str, str]:
        from google.auth.transport.requests import Request as AuthRequest

        if not self.creds.valid:
            self.creds.refresh(AuthRequest())
        return {"Authorization": f"Bearer {self.creds.token}"}

    def run_query(self, query: Dict[str, Any]) -> Dict[str, Any]:
        delay = 1.0
        for attempt in range(6):
            r = self.session.post(
                self.url, json={"query": query}, headers=self._headers(), timeout=120
            )
            if r.status_code == 401 and attempt == 0:
                self.creds.token = None  # force refresh
                continue
            if r.status_code in self.RETRY_STATUS and attempt < 5:
                log.warning("Datastore %s; retrying in %.0fs", r.status_code, delay)
                time.sleep(delay)
                delay *= 2
                continue
            r.raise_for_status()
            return r.json()["batch"]
        raise RuntimeError("unreachable")

    def _key_value(self, kind: str, ident: str | int) -> Dict[str, Any]:
        path: Dict[str, Any] = {"kind": kind}
        if isinstance(ident, int):
            path["id"] = str(ident)
        else:
            path["name"] = ident
        return {
            "keyValue": {
                "partitionId": {"projectId": self.project},
                "path": [path],
            }
        }

    def iter_batches(
        self,
        kind: str,
        key_start: Optional[str | int] = None,
        key_end: Optional[str | int] = None,
        since: Optional[Tuple[str, datetime]] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Tuple[List[EntityJson], str]]:
        """Yield (entities, end_cursor) batches for a kind, optionally
        bounded by a __key__ range or a timestamp-property filter.
        Note: Datastore allows inequality filters on only one property,
        so key ranges and `since` are mutually exclusive."""
        assert not (since and (key_start is not None or key_end is not None))
        filters: List[Dict[str, Any]] = []
        if key_start is not None:
            filters.append({"propertyFilter": {
                "property": {"name": "__key__"},
                "op": "GREATER_THAN_OR_EQUAL",
                "value": self._key_value(kind, key_start)}})
        if key_end is not None:
            filters.append({"propertyFilter": {
                "property": {"name": "__key__"},
                "op": "LESS_THAN",
                "value": self._key_value(kind, key_end)}})
        if since is not None:
            prop, dt = since
            filters.append({"propertyFilter": {
                "property": {"name": prop},
                "op": "GREATER_THAN_OR_EQUAL",
                "value": {"timestampValue": iso_z(dt)}}})
        query: Dict[str, Any] = {"kind": [{"name": kind}]}
        if len(filters) == 1:
            query["filter"] = filters[0]
        elif filters:
            query["filter"] = {"compositeFilter": {"op": "AND", "filters": filters}}
        while True:
            if cursor:
                query["startCursor"] = cursor
            batch = self.run_query(query)
            ents = [er["entity"] for er in batch.get("entityResults", [])]
            cursor = str(batch.get("endCursor") or "")
            if ents:
                yield ents, cursor
            if batch.get("moreResults") != "NOT_FINISHED":
                return

    def _first_id_at_or_above(self, kind: str, lower: Optional[int]) -> Optional[int]:
        """Smallest numeric key id >= lower (ascending key order is the
        only built-in index; descending would need a composite)."""
        q: Dict[str, Any] = {
            "kind": [{"name": kind}],
            "projection": [{"property": {"name": "__key__"}}],
            "limit": 1,
        }
        if lower is not None:
            q["filter"] = {"propertyFilter": {
                "property": {"name": "__key__"},
                "op": "GREATER_THAN_OR_EQUAL",
                "value": self._key_value(kind, lower)}}
        ents = self.run_query(q).get("entityResults", [])
        if not ents:
            return None
        elem = ents[0]["entity"]["key"]["path"][-1]
        return int(elem["id"]) if "id" in elem else None

    def key_bounds(self, kind: str) -> Optional[Tuple[int, int]]:
        """Smallest and largest numeric key id of a kind, or None if the
        kind uses string key names. The maximum is found by binary
        search over exists-above probes, since only ascending __key__
        order has a built-in index."""
        lo = self._first_id_at_or_above(kind, None)
        if lo is None:
            return None
        hi = 2**62
        lo_known = lo
        while lo_known < hi:
            mid = (lo_known + hi + 1) // 2
            r = self._first_id_at_or_above(kind, mid)
            if r is not None:
                lo_known = r
            else:
                hi = mid - 1
        return lo, lo_known


def uuid_shard_bounds(n: int) -> List[Tuple[Optional[str], Optional[str]]]:
    """Split the hex-named (UUID) key space into n contiguous ranges."""
    edges = [format(i * 256 // n, "02x") for i in range(n + 1)]
    bounds: List[Tuple[Optional[str], Optional[str]]] = []
    for i in range(n):
        start: Optional[str] = None if i == 0 else edges[i]
        end: Optional[str] = None if i == n - 1 else edges[i + 1]
        bounds.append((start, end))
    return bounds


def numeric_shard_bounds(
    lo: int, hi: int, n: int
) -> List[Tuple[Optional[int], Optional[int]]]:
    """Split a numeric key id range into n contiguous ranges."""
    if n <= 1 or hi <= lo:
        return [(None, None)]
    step = (hi - lo) // n + 1
    bounds: List[Tuple[Optional[int], Optional[int]]] = []
    for i in range(n):
        start: Optional[int] = None if i == 0 else lo + i * step
        end: Optional[int] = None if i == n - 1 else lo + (i + 1) * step
        bounds.append((start, end))
    return bounds


# ---------------------------------------------------------------------------
# Kind specifications

TransformFn = Callable[[Any], Optional[Row]]


@dataclass
class KindSpec:
    """Everything the pipeline needs to know about one Datastore kind."""

    kind: str
    table: str
    columns: Tuple[str, ...]
    conflict: Tuple[str, ...]
    # "update": upsert all non-conflict columns; "nothing": ignore dupes
    # (required when the source may contain duplicates on the conflict key)
    conflict_action: str = "update"
    # "uuid" (hex-named keys) or "numeric" (auto ids) enables sharding
    shard: Optional[str] = None
    # Indexed timestamp property used for --mode delta filtering
    delta_prop: Optional[str] = None
    # In delta mode, wipe and fully reload this (small) kind, so rows
    # deleted in Datastore since T0 disappear from PG as well
    delta_replace: bool = False


KIND_SPECS: List[KindSpec] = [
    KindSpec("UserModel", "users",
             ("id", "nickname", "inactive", "email", "image", "image_blob",
              "account", "plan", "nick_lc", "name_lc", "locale", "location",
              "prefs", "timestamp", "last_login", "ready", "ready_timed",
              "chat_disabled", "elo", "human_elo", "manual_elo",
              "highest_score", "highest_score_game", "best_word",
              "best_word_score", "best_word_game", "games"),
             conflict=("id",)),
    KindSpec("RobotModel", "robots", ("locale", "level", "elo"),
             conflict=("locale", "level"), delta_replace=True),
    KindSpec("GameModel", "games",
             ("id", "player0_id", "player1_id", "locale", "rack0", "rack1",
              "irack0", "irack1", "score0", "score1", "to_move", "robot_level",
              "over", "timestamp", "ts_last_move", "moves", "prefs",
              "tile_count", "elo0", "elo1", "elo0_adj", "elo1_adj",
              "human_elo0", "human_elo1", "human_elo0_adj", "human_elo1_adj",
              "manual_elo0", "manual_elo1", "manual_elo0_adj", "manual_elo1_adj"),
             conflict=("id",), shard="uuid", delta_prop="ts_last_move"),
    KindSpec("EloModel", "elo_ratings",
             ("user_id", "locale", "elo", "human_elo", "manual_elo", "timestamp"),
             conflict=("user_id", "locale"), delta_replace=True),
    KindSpec("FavoriteModel", "favorites", ("src_user_id", "dest_user_id"),
             conflict=("src_user_id", "dest_user_id"),
             conflict_action="nothing", delta_replace=True),
    KindSpec("ChallengeModel", "challenges",
             ("id", "src_user_id", "dest_user_id", "prefs", "timestamp"),
             conflict=("id",), delta_replace=True),
    KindSpec("StatsModel", "stats",
             ("id", "user_id", "robot_level", "timestamp", "games",
              "human_games", "manual_games", "elo", "human_elo", "manual_elo",
              "score", "human_score", "manual_score", "score_against",
              "human_score_against", "manual_score_against", "wins", "losses",
              "human_wins", "human_losses", "manual_wins", "manual_losses"),
             conflict=("id",), shard="numeric", delta_prop="timestamp"),
    KindSpec("ChatModel", "chats",
             ("id", "channel", "user_id", "recipient_id", "msg", "timestamp"),
             conflict=("id",), shard="numeric", delta_prop="timestamp"),
    KindSpec("ZombieModel", "zombies", ("game_id", "user_id"),
             conflict=("game_id", "user_id"),
             conflict_action="nothing", delta_replace=True),
    KindSpec("BlockModel", "blocks", ("blocker_id", "blocked_id", "timestamp"),
             conflict=("blocker_id", "blocked_id"),
             conflict_action="nothing", delta_replace=True),
    KindSpec("ReportModel", "reports",
             ("id", "reporter_id", "reported_id", "code", "text", "timestamp"),
             conflict=("id",), delta_replace=True),
    KindSpec("ImageModel", "images", ("id", "user_id", "fmt", "image"),
             conflict=("user_id", "fmt"), delta_replace=True),
    KindSpec("PromoModel", "promos", ("id", "user_id", "promotion", "timestamp"),
             conflict=("id",), delta_replace=True),
    KindSpec("TransactionModel", "transactions",
             ("id", "user_id", "plan", "kind", "op", "ts"),
             conflict=("id",), delta_replace=True),
    KindSpec("SubmissionModel", "submissions",
             ("id", "user_id", "locale", "word", "comment", "ts"),
             conflict=("id",), delta_replace=True),
    KindSpec("CompletionModel", "completions",
             ("id", "proctype", "ts_from", "ts_to", "success", "reason",
              "timestamp"),
             conflict=("id",), delta_replace=True),
    KindSpec("RatingModel", "ratings",
             ("kind", "rank", "user_id", "robot_level", "games", "elo",
              "score", "score_against", "wins", "losses",
              "rank_yesterday", "games_yesterday", "elo_yesterday",
              "score_yesterday", "score_against_yesterday", "wins_yesterday",
              "losses_yesterday",
              "rank_week_ago", "games_week_ago", "elo_week_ago",
              "score_week_ago", "score_against_week_ago", "wins_week_ago",
              "losses_week_ago",
              "rank_month_ago", "games_month_ago", "elo_month_ago",
              "score_month_ago", "score_against_month_ago", "wins_month_ago",
              "losses_month_ago"),
             conflict=("kind", "rank"), delta_replace=True),
    KindSpec("RatingArchiveModel", "rating_archive",
             ("kind", "key_date", "table_json", "timestamp"),
             conflict=("kind", "key_date"), delta_replace=True),
    KindSpec("RiddleModel", "riddles",
             ("date", "locale", "riddle_json", "created", "version"),
             conflict=("date", "locale"), delta_replace=True),
]

SPEC_BY_KIND = {s.kind: s for s in KIND_SPECS}


# ---------------------------------------------------------------------------
# The migrator


class Migrator:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.project: str = args.project
        self.creds_path: str = args.credentials or str(
            REPO_ROOT / "credentials" / args.project / "service-account.json"
        )
        self.database_url: str = args.database_url
        self.mode: str = args.mode
        self.since: Optional[datetime] = None
        if args.since:
            self.since = datetime.fromisoformat(args.since)
            if self.since.tzinfo is None:
                self.since = self.since.replace(tzinfo=UTC)
        self.run_id: str = args.run_id or f"{self.project}:{self.mode}"
        self.dry_run: bool = args.dry_run
        self.batch_size: int = 500
        self.verify_n: int = args.verify

        self.lock = threading.Lock()
        self.counters: Dict[str, int] = {}
        self.user_ids: Set[str] = set()
        # Reservoir samples per kind for --verify: (row, seen-count state)
        self.samples: Dict[str, List[Row]] = {}
        self.sample_seen: Dict[str, int] = {}

        self._bootstrap_env()
        # These imports need the environment above
        import skrafldb_ndb  # noqa: F401  - registers all NDB kinds

        from google.cloud import ndb

        self.ndb_client = ndb.Client(project=self.project)
        self.t0 = datetime.now(UTC)

    # -- setup ---------------------------------------------------------------

    def _bootstrap_env(self) -> None:
        """Set the standard local-dev environment expected by src/config.py
        before importing the NDB model layer."""
        os.environ["PROJECT_ID"] = self.project
        os.environ["GOOGLE_CLOUD_PROJECT"] = self.project
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.creds_path
        os.environ.setdefault("RUNNING_LOCAL", "true")
        os.environ.setdefault("REDISHOST", "127.0.0.1")
        os.environ.setdefault("REDISPORT", "6379")
        sys.path.insert(0, str(SRC_DIR))

    def connect(self) -> Any:
        import psycopg2
        from psycopg2.extras import register_uuid

        register_uuid()  # adapt uuid.UUID values (idempotent, global)
        conn = psycopg2.connect(self.database_url)
        conn.autocommit = False
        return conn

    def check_schema(self) -> None:
        """Refuse to run unless the target schema is at Alembic head."""
        from alembic.config import Config as AlembicConfig
        from alembic.script import ScriptDirectory

        cfg = AlembicConfig(str(REPO_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
        head = ScriptDirectory.from_config(cfg).get_current_head()
        with self.connect() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute("SELECT version_num FROM alembic_version")
                    row = cur.fetchone()
                except Exception:
                    row = None
        current = row[0] if row else None
        if current != head:
            sys.exit(
                f"Target schema is at Alembic revision {current!r}, repo head "
                f"is {head!r}. Run 'alembic upgrade head' against the target "
                f"database first (or pass --skip-schema-check)."
            )
        log.info("Schema check OK (Alembic head %s)", head)

    def ensure_state_table(self, conn: Any) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS _migration_state (
                       run_id text NOT NULL,
                       kind text NOT NULL,
                       shard text NOT NULL,
                       cursor text,
                       count bigint NOT NULL DEFAULT 0,
                       done boolean NOT NULL DEFAULT false,
                       updated timestamptz NOT NULL,
                       PRIMARY KEY (run_id, kind, shard)
                   )"""
            )
        conn.commit()

    def load_state(self, conn: Any, kind: str) -> Dict[str, Tuple[Optional[str], int, bool]]:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT shard, cursor, count, done FROM _migration_state "
                "WHERE run_id = %s AND kind = %s",
                (self.run_id, kind),
            )
            return {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}

    # -- counters / samples ---------------------------------------------------

    def bump(self, what: str, n: int = 1) -> None:
        with self.lock:
            self.counters[what] = self.counters.get(what, 0) + n

    def maybe_sample(self, kind: str, row: Row) -> None:
        if not self.verify_n:
            return
        with self.lock:
            seen = self.sample_seen.get(kind, 0) + 1
            self.sample_seen[kind] = seen
            bucket = self.samples.setdefault(kind, [])
            if len(bucket) < self.verify_n:
                bucket.append(row)
            else:
                j = random.randrange(seen)
                if j < self.verify_n:
                    bucket[j] = row

    # -- decode ---------------------------------------------------------------

    @staticmethod
    def decode(entity_json: EntityJson) -> Any:
        from google.cloud.datastore_v1.types import entity as entity_types
        from google.cloud.ndb import model as ndb_model
        from google.protobuf import json_format

        pb = entity_types.Entity.pb(entity_types.Entity())
        json_format.ParseDict(entity_json, pb)
        # Private but stable API (validated by the decode spike against
        # google-cloud-ndb 2.3.2 - keep that version pinned)
        decode_fn = getattr(ndb_model, "_entity_from_protobuf")
        return decode_fn(entity_types.Entity.wrap(pb))

    # -- transforms -----------------------------------------------------------
    # Each returns a Row matching the KindSpec.columns, or None to skip
    # (the reason is counted and reported).

    def _uid(self, key_prop: Any) -> Optional[str]:
        return None if key_prop is None else str(key_prop.id())

    def _known_user(self, uid: Optional[str]) -> bool:
        return uid is not None and uid in self.user_ids

    def tf_UserModel(self, e: Any) -> Optional[Row]:
        from psycopg2.extras import Json

        uid = str(e.key.id())
        with self.lock:
            self.user_ids.add(uid)
        return (
            uid, e.nickname or "", bool(e.inactive), e.email or "",
            e.image or "", e.image_blob, e.account, e.plan, e.nick_lc,
            e.name_lc, e.locale, e.location, Json(e.prefs or {}),
            utc_ts(e.timestamp) or SENTINEL_TS, utc_ts(e.last_login),
            True if e.ready is None else bool(e.ready),
            True if e.ready_timed is None else bool(e.ready_timed),
            False if e.chat_disabled is None else bool(e.chat_disabled),
            e.elo or 0, e.human_elo or 0, e.manual_elo or 0,
            e.highest_score or 0, e.highest_score_game, e.best_word,
            e.best_word_score or 0, e.best_word_game, e.games or 0,
        )

    def tf_RobotModel(self, e: Any) -> Optional[Row]:
        # Key form: "robot-{level}:{locale}"
        ident = str(e.key.id())
        try:
            level_part, locale = ident.split(":", 1)
            level = int(level_part.removeprefix("robot-"))
        except ValueError:
            self.bump("robots.bad_key")
            return None
        return (locale, level, e.elo or 0)

    def tf_GameModel(self, e: Any) -> Optional[Row]:
        from psycopg2.extras import Json

        p0, p1 = self._uid(e.player0), self._uid(e.player1)
        if p0 is not None and not self._known_user(p0):
            self.bump("games.orphan_player0_nulled")
            p0 = None
        if p1 is not None and not self._known_user(p1):
            self.bump("games.orphan_player1_nulled")
            p1 = None
        if e.rack0 is None or e.rack1 is None:
            self.bump("games.null_rack_coerced")
        return (
            str(e.key.id()), p0, p1, e.locale, e.rack0 or "", e.rack1 or "",
            e.irack0, e.irack1, e.score0 or 0, e.score1 or 0, e.to_move or 0,
            e.robot_level or 0, bool(e.over),
            utc_ts(e.timestamp) or SENTINEL_TS, utc_ts(e.ts_last_move),
            Json([move_to_dict(m) for m in e.moves]),
            None if e.prefs is None else Json(e.prefs), e.tile_count,
            e.elo0, e.elo1, e.elo0_adj, e.elo1_adj,
            e.human_elo0, e.human_elo1, e.human_elo0_adj, e.human_elo1_adj,
            e.manual_elo0, e.manual_elo1, e.manual_elo0_adj, e.manual_elo1_adj,
        )

    def tf_EloModel(self, e: Any) -> Optional[Row]:
        parent = e.key.parent()
        uid = str(parent.id()) if parent else str(e.key.id()).rsplit(":", 1)[0]
        locale = e.locale or str(e.key.id()).rsplit(":", 1)[-1]
        if not self._known_user(uid):
            self.bump("elo_ratings.orphan_user_skipped")
            return None
        return (uid, locale, e.elo or 1200, e.human_elo or 1200,
                e.manual_elo or 1200, utc_ts(e.timestamp) or SENTINEL_TS)

    def tf_FavoriteModel(self, e: Any) -> Optional[Row]:
        parent = e.key.parent()
        src = str(parent.id()) if parent else None
        dest = self._uid(e.destuser)
        if not (self._known_user(src) and self._known_user(dest)):
            self.bump("favorites.orphan_skipped")
            return None
        return (src, dest)

    def tf_ChallengeModel(self, e: Any) -> Optional[Row]:
        from psycopg2.extras import Json

        parent = e.key.parent()
        src = str(parent.id()) if parent else None
        dest = self._uid(e.destuser)
        if not (self._known_user(src) and self._known_user(dest)):
            self.bump("challenges.orphan_skipped")
            return None
        return (ent_uuid(e.key), src, dest,
                None if e.prefs is None else Json(e.prefs),
                utc_ts(e.timestamp) or SENTINEL_TS)

    def tf_StatsModel(self, e: Any) -> Optional[Row]:
        uid = self._uid(e.user)
        if uid is not None and not self._known_user(uid):
            self.bump("stats.orphan_user_skipped")
            return None
        z = lambda v: v or 0  # noqa: E731
        return (
            ent_uuid(e.key), uid, e.robot_level or 0,
            utc_ts(e.timestamp) or SENTINEL_TS,
            z(e.games), z(e.human_games), z(e.manual_games),
            e.elo or 1200, e.human_elo or 1200, e.manual_elo or 1200,
            z(e.score), z(e.human_score), z(e.manual_score),
            z(e.score_against), z(e.human_score_against),
            z(e.manual_score_against),
            z(e.wins), z(e.losses), z(e.human_wins), z(e.human_losses),
            z(e.manual_wins), z(e.manual_losses),
        )

    def tf_ChatModel(self, e: Any) -> Optional[Row]:
        uid = self._uid(e.user)
        if not self._known_user(uid):
            self.bump("chats.orphan_user_skipped")
            return None
        rcpt = self._uid(e.recipient)
        if rcpt is not None and not self._known_user(rcpt):
            self.bump("chats.orphan_recipient_nulled")
            rcpt = None
        return (ent_uuid(e.key), e.channel or "", uid, rcpt, e.msg or "",
                utc_ts(e.timestamp) or SENTINEL_TS)

    def tf_ZombieModel(self, e: Any) -> Optional[Row]:
        gid, uid = self._uid(e.game), self._uid(e.player)
        if gid is None or not self._known_user(uid):
            self.bump("zombies.orphan_skipped")
            return None
        return (gid, uid)

    def tf_BlockModel(self, e: Any) -> Optional[Row]:
        blocker, blocked = self._uid(e.blocker), self._uid(e.blocked)
        if not (self._known_user(blocker) and self._known_user(blocked)):
            self.bump("blocks.orphan_skipped")
            return None
        return (blocker, blocked, utc_ts(e.timestamp) or SENTINEL_TS)

    def tf_ReportModel(self, e: Any) -> Optional[Row]:
        reporter, reported = self._uid(e.reporter), self._uid(e.reported)
        if not (self._known_user(reporter) and self._known_user(reported)):
            self.bump("reports.orphan_skipped")
            return None
        return (ent_uuid(e.key), reporter, reported, e.code or 0,
                e.text or "", utc_ts(e.timestamp) or SENTINEL_TS)

    def tf_ImageModel(self, e: Any) -> Optional[Row]:
        uid = self._uid(e.user)
        if not self._known_user(uid):
            self.bump("images.orphan_skipped")
            return None
        if e.image is None:
            self.bump("images.null_image_skipped")
            return None
        return (ent_uuid(e.key), uid, e.fmt or "", e.image)

    def tf_PromoModel(self, e: Any) -> Optional[Row]:
        uid = self._uid(e.player)
        if not self._known_user(uid):
            self.bump("promos.orphan_skipped")
            return None
        return (ent_uuid(e.key), uid, e.promotion or "",
                utc_ts(e.timestamp) or SENTINEL_TS)

    def tf_TransactionModel(self, e: Any) -> Optional[Row]:
        uid = self._uid(e.user)
        if not self._known_user(uid):
            self.bump("transactions.orphan_skipped")
            return None
        return (ent_uuid(e.key), uid, e.plan or "", e.kind or "", e.op or "",
                utc_ts(e.ts) or SENTINEL_TS)

    def tf_SubmissionModel(self, e: Any) -> Optional[Row]:
        uid = self._uid(e.user)
        if not self._known_user(uid):
            self.bump("submissions.orphan_skipped")
            return None
        return (ent_uuid(e.key), uid, e.locale or "", e.word or "",
                e.comment or "", utc_ts(e.ts) or SENTINEL_TS)

    def tf_CompletionModel(self, e: Any) -> Optional[Row]:
        return (ent_uuid(e.key), e.proctype or "",
                utc_ts(e.ts_from) or SENTINEL_TS, utc_ts(e.ts_to) or SENTINEL_TS,
                True if e.success is None else bool(e.success), e.reason or "",
                utc_ts(e.timestamp) or SENTINEL_TS)

    def tf_RatingModel(self, e: Any) -> Optional[Row]:
        uid = self._uid(e.user)
        if uid is not None and not self._known_user(uid):
            self.bump("ratings.orphan_user_nulled")
            uid = None
        z = lambda v: v or 0  # noqa: E731
        r = lambda v: 1200 if v is None else v  # noqa: E731
        return (
            e.kind or "", z(e.rank), uid, z(e.robot_level),
            z(e.games), r(e.elo), z(e.score), z(e.score_against),
            z(e.wins), z(e.losses),
            z(e.rank_yesterday), z(e.games_yesterday), r(e.elo_yesterday),
            z(e.score_yesterday), z(e.score_against_yesterday),
            z(e.wins_yesterday), z(e.losses_yesterday),
            z(e.rank_week_ago), z(e.games_week_ago), r(e.elo_week_ago),
            z(e.score_week_ago), z(e.score_against_week_ago),
            z(e.wins_week_ago), z(e.losses_week_ago),
            z(e.rank_month_ago), z(e.games_month_ago), r(e.elo_month_ago),
            z(e.score_month_ago), z(e.score_against_month_ago),
            z(e.wins_month_ago), z(e.losses_month_ago),
        )

    def tf_RatingArchiveModel(self, e: Any) -> Optional[Row]:
        if e.table_json is None:
            self.bump("rating_archive.null_json_skipped")
            return None
        return (e.kind or "", e.key_date or "", e.table_json,
                utc_ts(e.timestamp) or SENTINEL_TS)

    def tf_RiddleModel(self, e: Any) -> Optional[Row]:
        if e.riddle_json is None:
            self.bump("riddles.null_json_skipped")
            return None
        created = utc_ts(e.created)
        if created is None:
            self.bump("riddles.null_created_coerced")
            created = SENTINEL_TS
        return (e.date or "", e.locale or "", e.riddle_json, created,
                1 if e.version is None else e.version)

    def transform(self, spec: KindSpec, e: Any) -> Optional[Row]:
        fn: TransformFn = getattr(self, f"tf_{spec.kind}")
        return fn(e)

    # -- writing --------------------------------------------------------------

    def upsert_sql(self, spec: KindSpec) -> str:
        cols = ", ".join(f'"{c}"' for c in spec.columns)
        conflict = ", ".join(f'"{c}"' for c in spec.conflict)
        if spec.conflict_action == "nothing":
            action = "DO NOTHING"
        else:
            updates = ", ".join(
                f'"{c}" = EXCLUDED."{c}"'
                for c in spec.columns
                if c not in spec.conflict
            )
            action = f"DO UPDATE SET {updates}" if updates else "DO NOTHING"
        return (
            f'INSERT INTO "{spec.table}" ({cols}) VALUES %s '
            f"ON CONFLICT ({conflict}) {action}"
        )

    def post_filter(self, spec: KindSpec, cur: Any, rows: List[Row]) -> List[Row]:
        """Kind-specific filtering that needs the target database."""
        if spec.kind == "ZombieModel" and rows:
            # Drop zombies whose game no longer exists (FK to games)
            gids = list({r[0] for r in rows})
            cur.execute("SELECT id FROM games WHERE id = ANY(%s)", (gids,))
            existing = {r[0] for r in cur.fetchall()}
            kept = [r for r in rows if r[0] in existing]
            if len(kept) < len(rows):
                self.bump("zombies.orphan_game_skipped", len(rows) - len(kept))
            return kept
        if spec.kind == "ImageModel" and rows:
            # Unique (user_id, fmt): keep the last occurrence per pair so a
            # single INSERT ... ON CONFLICT DO UPDATE cannot hit the same
            # row twice within one statement
            dedup: Dict[Tuple[Any, Any], Row] = {(r[1], r[2]): r for r in rows}
            if len(dedup) < len(rows):
                self.bump("images.dup_user_fmt_dropped", len(rows) - len(dedup))
            return list(dedup.values())
        return rows

    def save_state(
        self, cur: Any, kind: str, shard: str, cursor: Optional[str],
        count: int, done: bool,
    ) -> None:
        cur.execute(
            """INSERT INTO _migration_state
                   (run_id, kind, shard, cursor, count, done, updated)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (run_id, kind, shard) DO UPDATE SET
                   cursor = EXCLUDED.cursor, count = EXCLUDED.count,
                   done = EXCLUDED.done, updated = EXCLUDED.updated""",
            (self.run_id, kind, shard, cursor, count, done, datetime.now(UTC)),
        )

    # -- per-shard pipeline ---------------------------------------------------

    def run_shard(
        self,
        spec: KindSpec,
        shard_label: str,
        key_start: Optional[str | int],
        key_end: Optional[str | int],
        since: Optional[Tuple[str, datetime]],
        start_cursor: Optional[str],
        start_count: int,
        single_txn: bool = False,
    ) -> int:
        """Read one key range of one kind and upsert it into PG.
        Runs in its own thread with its own connections."""
        from psycopg2.extras import execute_values

        reader = DatastoreReader(self.project, self.creds_path)
        conn = None if self.dry_run else self.connect()
        sql = self.upsert_sql(spec)
        count = start_count
        pending: List[Row] = []
        cursor: Optional[str] = start_cursor
        last_log = time.time()

        def flush(end_cursor: Optional[str], done: bool) -> None:
            nonlocal pending
            if self.dry_run:
                pending = []
                return
            assert conn is not None
            with conn.cursor() as cur:
                rows = self.post_filter(spec, cur, pending)
                for row in rows:
                    self.maybe_sample(spec.kind, row)
                if rows:
                    execute_values(cur, sql, rows, page_size=self.batch_size)
                self.save_state(cur, spec.kind, shard_label, end_cursor, count, done)
            if not single_txn or done:
                conn.commit()
            pending = []

        with self.ndb_client.context(cache_policy=lambda key: False):
            try:
                for ents, end_cursor in reader.iter_batches(
                    spec.kind, key_start, key_end, since, cursor
                ):
                    for ej in ents:
                        entity = self.decode(ej)
                        row = self.transform(spec, entity)
                        if row is None:
                            continue
                        pending.append(row)
                        count += 1
                    cursor = end_cursor
                    if len(pending) >= self.batch_size:
                        flush(end_cursor, done=False)
                    if time.time() - last_log > 15:
                        log.info("%s[%s]: %s rows", spec.kind, shard_label, f"{count:,}")
                        last_log = time.time()
                flush(cursor, done=True)
            finally:
                if conn is not None:
                    conn.close()
        return count

    # -- per-kind driver --------------------------------------------------------

    def run_kind(self, spec: KindSpec) -> None:
        delta = self.mode == "delta"
        since: Optional[Tuple[str, datetime]] = None
        if delta and spec.delta_prop and self.since:
            since = (spec.delta_prop, self.since)

        state_conn = None if self.dry_run else self.connect()
        prior: Dict[str, Tuple[Optional[str], int, bool]] = {}
        if state_conn is not None:
            if self.args.resume:
                prior = self.load_state(state_conn, spec.kind)
            if delta and spec.delta_replace:
                # Full replace: wipe the table so rows deleted at the
                # source since T0 disappear here too. Committed together
                # with the reload's final batch? No - kept simple: the
                # delete commits first, and the reload is idempotent, so
                # a crash in between is fixed by re-running the delta.
                with state_conn.cursor() as cur:
                    cur.execute(f'DELETE FROM "{spec.table}"')
                state_conn.commit()
                log.info("%s: delta replace - table %s cleared", spec.kind, spec.table)

        # Shard planning (bulk mode only: Datastore allows an inequality
        # filter on just one property, so `since` excludes key ranges)
        shards: List[Tuple[str, Optional[str | int], Optional[str | int]]] = []
        n = self.args.shards if (spec.shard and not since and not delta) else 1
        if n > 1 and spec.shard == "uuid":
            for i, (a, b) in enumerate(uuid_shard_bounds(n)):
                shards.append((f"s{i:02d}", a, b))
        elif n > 1 and spec.shard == "numeric":
            reader = DatastoreReader(self.project, self.creds_path)
            bounds = reader.key_bounds(spec.kind)
            if bounds is None:
                log.warning("%s: non-numeric keys; falling back to 1 shard", spec.kind)
                shards.append(("s00", None, None))
            else:
                for i, (a, b) in enumerate(numeric_shard_bounds(*bounds, n)):
                    shards.append((f"s{i:02d}", a, b))
        else:
            shards.append(("s00", None, None))

        # Apply prior state (resume)
        todo: List[Tuple[str, Optional[str | int], Optional[str | int], Optional[str], int]] = []
        for label, a, b in shards:
            cur0, cnt0, done0 = prior.get(label, (None, 0, False))
            if done0:
                self.bump(f"{spec.table}.rows", cnt0)
                continue
            todo.append((label, a, b, cur0, cnt0))
        if not todo:
            log.info("%s: all shards already done (resume)", spec.kind)
            if state_conn is not None:
                state_conn.close()
            return

        log.info(
            "%s -> %s: %d shard(s)%s%s",
            spec.kind, spec.table, len(todo),
            " [delta filter]" if since else "",
            " [dry run]" if self.dry_run else "",
        )
        results: List[int] = []
        errors: List[BaseException] = []

        def work(item: Tuple[str, Optional[str | int], Optional[str | int], Optional[str], int]) -> None:
            label, a, b, cur0, cnt0 = item
            try:
                results.append(
                    self.run_shard(spec, label, a, b, since, cur0, cnt0)
                )
            except BaseException as ex:  # noqa: BLE001 - reported below
                log.error("%s[%s] failed: %r", spec.kind, label, ex)
                errors.append(ex)

        if len(todo) == 1:
            work(todo[0])
        else:
            threads = [threading.Thread(target=work, args=(t,)) for t in todo]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        if errors:
            raise errors[0]
        total = sum(results)
        self.bump(f"{spec.table}.rows", total)
        log.info("%s: %s rows migrated", spec.kind, f"{total:,}")
        if state_conn is not None:
            state_conn.close()

    # -- verification -----------------------------------------------------------

    @staticmethod
    def normalize(v: Any) -> Any:
        from psycopg2.extras import Json

        if isinstance(v, Json):
            return v.adapted
        if isinstance(v, memoryview):
            return bytes(v)
        if isinstance(v, UUID):
            return str(v)
        if isinstance(v, datetime):
            return v.astimezone(UTC).isoformat() if v.tzinfo else v.replace(tzinfo=UTC).isoformat()
        return v

    def verify(self) -> int:
        """Re-read sampled rows from PG and compare with what we wrote."""
        mismatches = 0
        conn = self.connect()
        try:
            for kind, rows in sorted(self.samples.items()):
                spec = SPEC_BY_KIND[kind]
                cols = ", ".join(f'"{c}"' for c in spec.columns)
                cond = " AND ".join(f'"{c}" = %s' for c in spec.conflict)
                pk_idx = [spec.columns.index(c) for c in spec.conflict]
                checked = 0
                for row in rows:
                    pk = tuple(self.normalize(row[i]) for i in pk_idx)
                    with conn.cursor() as cur:
                        cur.execute(
                            f'SELECT {cols} FROM "{spec.table}" WHERE {cond}', pk
                        )
                        got = cur.fetchone()
                    if got is None:
                        log.error("VERIFY %s: row %s missing", spec.table, pk)
                        mismatches += 1
                        continue
                    if spec.conflict_action == "nothing":
                        # Duplicate source entities collapse onto one row
                        # (first write wins), so only existence is
                        # well-defined for these kinds
                        checked += 1
                        continue
                    want_n = [self.normalize(v) for v in row]
                    got_n = [self.normalize(v) for v in got]
                    for c, w, g in zip(spec.columns, want_n, got_n):
                        if w != g:
                            log.error(
                                "VERIFY %s %s col %s: wrote %r, read %r",
                                spec.table, pk, c, w, g,
                            )
                            mismatches += 1
                    checked += 1
                log.info("verify %s: %d rows checked", spec.table, checked)
        finally:
            conn.close()
        return mismatches

    def report(self) -> None:
        log.info("=== migration report (run_id=%s, mode=%s) ===", self.run_id, self.mode)
        for k in sorted(self.counters):
            log.info("  %-42s %10s", k, f"{self.counters[k]:,}")
        if not self.dry_run:
            conn = self.connect()
            try:
                with conn.cursor() as cur:
                    for spec in KIND_SPECS:
                        cur.execute(f'SELECT count(*) FROM "{spec.table}"')
                        n = cur.fetchone()[0]
                        log.info("  table %-28s %10s rows", spec.table, f"{n:,}")
            finally:
                conn.close()

    # -- main -----------------------------------------------------------------

    def run(self) -> int:
        if not self.args.skip_schema_check and not self.dry_run:
            self.check_schema()
        if not self.dry_run:
            conn = self.connect()
            self.ensure_state_table(conn)
            if self.args.truncate:
                if self.mode != "bulk":
                    sys.exit("--truncate is only valid with --mode bulk")
                tables = ", ".join(f'"{s.table}"' for s in KIND_SPECS)
                log.warning("TRUNCATING target tables: %s", tables)
                with conn.cursor() as cur:
                    cur.execute(f"TRUNCATE {tables} CASCADE")
                    cur.execute(
                        "DELETE FROM _migration_state WHERE run_id = %s",
                        (self.run_id,),
                    )
                conn.commit()
            conn.close()
        if self.mode == "delta" and self.since is None:
            sys.exit("--mode delta requires --since")

        selected = [s for s in KIND_SPECS if not self.args.kinds or s.kind in self.args.kinds]
        if self.args.kinds:
            unknown = set(self.args.kinds) - {s.kind for s in KIND_SPECS}
            if unknown:
                sys.exit(f"Unknown kind(s): {', '.join(sorted(unknown))}")

        # The user id set drives FK repair for every dependent kind
        if not self.dry_run and (not selected or selected[0].kind != "UserModel"):
            conn = self.connect()
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM users")
                self.user_ids = {r[0] for r in cur.fetchall()}
            conn.close()
            log.info("Loaded %s existing user ids from target", f"{len(self.user_ids):,}")

        started = time.time()
        for spec in selected:
            self.run_kind(spec)
            if spec.kind == "UserModel" and not self.dry_run:
                # Authoritative set after the users pass (covers resume)
                conn = self.connect()
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM users")
                    self.user_ids = {r[0] for r in cur.fetchall()}
                conn.close()
        elapsed = time.time() - started
        log.info("All kinds done in %.1f min", elapsed / 60)

        mismatches = 0
        if self.verify_n and not self.dry_run:
            mismatches = self.verify()
        self.report()
        if mismatches:
            log.error("%d verification mismatches", mismatches)
            return 1
        log.info("T0 for a subsequent delta pass: --since %s", self.t0.isoformat())
        return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", required=True,
                   help="Source project id (netskrafl, explo-dev, explo-live)")
    p.add_argument("--credentials",
                   help="Service account JSON (default: credentials/<project>/service-account.json)")
    p.add_argument("--database-url", required=True,
                   help="Target PostgreSQL URL")
    p.add_argument("--mode", choices=("bulk", "delta"), default="bulk")
    p.add_argument("--since", help="Delta lower bound (ISO timestamp, UTC assumed)")
    p.add_argument("--kinds", nargs="*",
                   help="Restrict to these Datastore kinds (default: all)")
    p.add_argument("--shards", type=int, default=8,
                   help="Parallel key-range shards for heavy kinds (bulk mode)")
    p.add_argument("--truncate", action="store_true",
                   help="TRUNCATE all target tables first (bulk mode only)")
    p.add_argument("--resume", action="store_true",
                   help="Continue from checkpoints in _migration_state")
    p.add_argument("--run-id", help="Checkpoint namespace (default: <project>:<mode>)")
    p.add_argument("--verify", type=int, default=0, metavar="N",
                   help="Sample N rows per kind and re-read them from PG")
    p.add_argument("--dry-run", action="store_true",
                   help="Read, decode and transform only; no writes")
    p.add_argument("--skip-schema-check", action="store_true")
    args = p.parse_args()
    return Migrator(args).run()


if __name__ == "__main__":
    sys.exit(main())

