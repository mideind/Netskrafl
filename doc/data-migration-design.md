# Data Migration Design: Datastore → PostgreSQL

*Written 2026-08-14. Design for `scripts/migrate_to_postgres.py` (Phase D
steps 2–3 of `migration-strategy.md`). Supersedes the sketch in
`postgresql-plan.md` where they differ.*

## Decisions already made

- **Transport/topology (decided 2026-08-14):** the migrator runs locally on
  the development box, reading Datastore over the **REST API**
  and writing to DO managed PostgreSQL (ams3). Measured throughput from
  this box against the real netskrafl Datastore (us-central):
  ~295 entities/s single-stream (Datastore caps responses at 300
  entities), **~2,140 entities/s with 8 key-range shards** (near-linear),
  i.e. **≈2 h for all 17.6M netskrafl entities** — an overestimate, since
  it weighs everything at GameModel size. Fallback if a full rehearsal
  disappoints: run the same script unchanged on a GCE VM in us-central
  (read-local, write to ams3). Full-run cost ≈ $10–20 (egress is
  gzip-compressed JSON, plus ~$11 of entity reads).
- **Do not use the gRPC client library for bulk reads.** On this box it
  was ~3× slower single-stream and did not scale with parallel workers at
  all (cf. the analogous gRPC note in `src/secret_manager.py`). REST via
  `requests` is fast and parallelizes cleanly.
- **Two-phase bulk + delta** (see below): the write-freeze window is
  minutes, independent of database size.
- **A managed Datastore export is taken before cutover as the rollback
  backup artifact, but is never parsed** — decoding its LevelDB/EntityProto
  format by hand would bypass the tested NDB model layer.

## Data shape (from Datastore `__Stat_Kind__`, 2026-08-14)

| Project | Location | Entities | Entity bytes | Heavy kinds |
|---|---|---|---|---|
| netskrafl | us-central | 17.6M | ~40 GB | GameModel 10.28M (~3.7 KB avg), StatsModel 3.5M, ChatModel 3.6M |
| explo-dev | europe-west | 19k | 59 MB | — |
| explo-live | europe-west (assumed) | TBD | TBD | check when credentials available |

Moves are embedded in GameModel (`LocalStructuredProperty(MoveModel,
repeated=True)`); there is **no separate move kind**. google-cloud-ndb
stores these in legacy serialized-EntityProto blob form — one of several
reasons decoding must go through the NDB model layer (below).

## Pipeline architecture

```
 REST runQuery ──► JSON → Entity proto ──► ndb model instance ──► row dict ──► COPY / upsert
 (sharded,          (json_format.          (google.cloud.ndb        (transform      (psycopg,
  cursors,           ParseDict)             _entity_from_protobuf,   layer)          batched)
  checkpointed)                             skrafldb_ndb classes)
```

1. **Reader** — REST `projects/{id}:runQuery` with `requests.Session`,
   continuous `endCursor` paging, N parallel shards (thread pool; work is
   I/O-bound). Per-kind shard strategy:
   - `GameModel` (UUID string keys): shard by key hex prefix
     (`__key__ >= 'a' AND __key__ < 'b'`), verified working.
   - `StatsModel`, `ChatModel` (numeric auto-IDs, scattered): sample
     min/max id, split the range uniformly into N `__key__` ranges.
   - All other kinds (≤50k entities): single stream, no sharding.
2. **Decoder** — parse the REST JSON entity into a `datastore.v1.Entity`
   proto (`json_format.ParseDict`), then hand it to
   `google.cloud.ndb`'s `model._entity_from_protobuf()` with the
   `skrafldb_ndb` model classes imported (kind registry populated). This
   yields real NDB model instances via the exact deserialization code the
   production app uses — legacy `LocalStructuredProperty` blobs,
   compressed properties, tz handling and all — without the gRPC
   transport. **Spike required** (first implementation task): validate
   this on a handful of real GameModel entities, including games with
   long move lists and both very old (2015-era) and recent games.
3. **Transformer** — per-kind pure functions: NDB model instance → row
   dict for the corresponding `src/db/postgresql/models.py` table.
   Explicit invariants:
   - Keys/UUIDs preserved as-is (string PKs).
   - Timestamps written tz-aware UTC (NDB returns naive UTC → attach
     `UTC`; never localtime).
   - `GameModel.moves` → `games.moves` JSONB using the **same dict shape
     as `skrafldb_pg.MoveModel`** (`coord`/`tiles`/`score`/`rack`/`ts` —
     reuse or import that conversion, do not duplicate it).
   - Unset/None optionals stay NULL (no default-filling beyond what the
     PG schema itself declares).
4. **Writer** — psycopg3 against `DATABASE_URL`:
   - **Bulk mode:** `COPY` into the target tables, in FK order
     (`users` → `elo_ratings`/`games`/`favorites`/… → `chats` → the rest),
     after `TRUNCATE ... CASCADE` of the target set. Fastest path, no
     conflict handling needed.
   - **Delta mode:** batched `INSERT ... ON CONFLICT (id) DO UPDATE`
     (~1,000 rows/statement). Idempotent by construction.
   - Schema is owned by Alembic: the tool **refuses to run** unless
     `alembic_version` in the target DB equals the repo's head revision.

## Two-phase migration

- **Phase 1 — bulk (no freeze), days before cutover:** full copy as of
  start time `T0` (recorded in the checkpoint file). All verification
  (below) runs against this copy at leisure.
- **Phase 2 — delta (inside the freeze):** `--since T0` re-copies only
  what may have changed, in delta mode:

| Kind | Delta predicate |
|---|---|
| GameModel | `ts_last_move >= T0` (also catches games created since) |
| ChatModel | `timestamp >= T0` |
| StatsModel | `timestamp >= T0` (append-mostly) |
| UserModel, EloModel, ChallengeModel, FavoriteModel, BlockModel, ZombieModel, and every other small kind | full re-copy (all are ≤50k entities, seconds each) |

Take `T0` with generous overlap (e.g. re-run the delta with
`T0 - 1 hour`); upserts make overlap harmless.

## Checkpointing and resume

A JSON state file per run (`--state <file>`): for each (kind, shard) —
last committed cursor, entity count, byte count, done flag. The writer
commits per batch; the cursor is persisted only after its batch commits,
so resume (`--resume`) re-reads at most one in-flight batch (bulk COPY
restarts the interrupted shard's table segment via upsert catch-up, or
simply re-runs that shard in delta mode). Ctrl-C-safe by design: every
run is resumable and every mode is idempotent or restartable.

## Verification (Phase D step 3)

Layered, cheapest first:

1. **Migrator parity unit test** (in `tests/`): for synthetic and sampled
   entities, write once through the migrator transform and once through
   the `skrafldb_pg` facade (`put()` path); assert identical rows. Guards
   the transform against drift from the tested facade.
2. **Counts:** per kind vs per table, printed at end of every run; delta
   runs print upserted-row counts.
3. **Deep sample:** `--verify N` re-fetches N random entities per kind
   from Datastore and field-compares against the PG rows (via the
   protocol repositories, not raw SQL, so comparison happens in
   application types).
4. **The heavy artillery:** run the **replay harness**
   (`test/replay_fixtures/`) and `tests/api_e2e/` against the migrated
   database.

## CLI

```
venv/bin/python scripts/migrate_to_postgres.py \
    --project netskrafl \
    --credentials credentials/netskrafl/service-account.json \
    --database-url postgresql://... \
    --state migration-state.json \
    [--kinds GameModel,UserModel,...]   # default: all
    [--shards 8]                        # heavy kinds only
    [--mode bulk|delta]                 # default bulk; delta implies upsert
    [--since 2026-09-01T00:00:00Z]      # delta lower bound
    [--resume]
    [--verify 200]
    [--dry-run]                         # read+decode+transform, no writes
```

Environment: needs only the service-account file and the PG URL — no
Flask app, no Redis, no `PROJECT_ID` config machinery. Import surface is
`skrafldb_ndb` model classes (+ `google.cloud.ndb` for decoding),
`src/db/postgresql/models.py`, and the move-dict conversion from
`skrafldb_pg` — nothing that touches caches or live services.
**Housekeeping:** add `scripts/` to `.dockerignore` and `.gcloudignore`
(like `utils/`); the migrator never ships in the image.

## Rehearsal sequence (Phase D steps 4–5)

1. explo-dev (19k entities, minutes) — shakes out the tool end-to-end;
   point the DO staging app at the result (`DATABASE_BACKEND=postgresql`)
   and click around.
2. explo-live (size TBD) — first realistic dress rehearsal.
3. netskrafl (17.6M) — **resize the staging PG cluster first** (the
   initial `db-s-1vcpu-2gb`/30 GB is too small for ~40 GB of entity
   data); measure wall-clock for the bulk pass and, separately, a delta
   pass — the delta number bounds the production freeze window.

## Decode spike — ✅ PASSED (2026-08-14)

The pipeline's riskiest joint is validated. 32 real netskrafl production
entities were fetched via REST, decoded via `json_format.ParseDict` →
`datastore_v1.types.Entity.wrap()` → `ndb.model._entity_from_protobuf()`
(google-cloud-ndb **2.3.2** — pin it; the API is private), and compared
field-by-field against ground truth fetched through the normal ndb
client. **Zero mismatches**, and `Model.__eq__` agreed in every case.
Coverage: games from 2014-10-20 (the oldest in the database) through
games being played live during the spike; robot and human games; 0- to
39-move games (legacy `LocalStructuredProperty` blobs decode correctly);
oldest/newest UserModel (Google-account numeric-string keys, full schema
evolution); ChatModel, StatsModel, EloModel (composite `uid:locale`
keys), ChallengeModel.

Findings that adjust the design:

- **`GameModel.timestamp` is `indexed=False`** (index-write reduction,
  effective ~Oct 2025): any query ordering or filtering on `timestamp`
  silently misses modern games. The migrator must never use it —
  key-order scans for bulk, `ts_last_move` for delta (as designed).
- **The delta predicate is confirmed safe**: `ts_last_move` is indexed,
  is set (= `timestamp`) at game creation (`skraflgame.py:260`), and an
  aggregation count found **0** GameModel entities with a null
  `ts_last_move` — so `ts_last_move >= T0` catches every game created
  or touched after T0, with no null-catching side query needed.
- UserModel keys are numeric-string Google account ids, not UUIDs —
  irrelevant to sharding (UserModel is a single-stream kind) but worth
  knowing when reading checkpoint files.

The spike scripts become the seed of the migrator's decoder unit test.

## Open items

1. **Numeric-ID shard sampling**: confirm StatsModel/ChatModel auto-IDs
   are scattered enough for uniform range splits (else fall back to more
   shards or `__scatter__`-style splitting).
2. **explo-live stats**: pull `__Stat_Kind__` when a service-account
   credential is available; expected modest.
3. **Memory:** streaming end-to-end (batch in, batch out); no kind is
   ever held fully in memory.
