# Data Migration Design: Datastore → PostgreSQL

*Written 2026-08-14, updated 2026-11-09 after the netskrafl rehearsal.
Design, implementation notes and rehearsal results for
`scripts/migrate_to_postgres.py`; `migration-strategy.md` has the overall
plan. Supersedes the sketch in `postgresql-plan.md` where they differ.*

## Decisions already made

- **Transport/topology (decided 2026-08-14):** the migrator runs locally on
  the development box, reading Datastore over the **REST API**
  and writing to DO managed PostgreSQL (ams3). Measured throughput from
  this box against the real netskrafl Datastore (us-central):
  ~295 entities/s single-stream (Datastore caps responses at 300
  entities), **~2,140 entities/s with 8 key-range shards** (near-linear),
  for reading alone. Decoding turned out to be the real bound: the full
  netskrafl bulk copy took 238 minutes (see the rehearsal below), which is
  fine for a copy that runs a day or two before the switch. Full-run cost
  ≈ $10–20 (egress is gzip-compressed JSON, plus ~$11 of entity reads).
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
| netskrafl | us-central | 17.7M | ~40 GB | GameModel 10.41M (~3.7 KB avg), ChatModel 3.66M, StatsModel 3.56M, UserModel 52k; stats as of 2026-11-01 |
| explo-dev | europe-west | 19k | 59 MB | — |
| explo-live | europe-west | 2.41M | ~13.3 GB | GameModel 1.46M (~7.2 KB avg), StatsModel 625k, ChatModel 230k, UserModel 36k (~22 KB avg, image blobs); stats as of 2026-09-09 |

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
   continuous `endCursor` paging, N parallel shards, **one worker process
   per shard** (the work is CPU-bound, not I/O-bound as first assumed —
   see the 2026-09-10 implementation notes). Per-kind shard strategy:
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
   transport. Validated by the decode spike (below) and, at full scale,
   by the decode sweeps of the rehearsals.
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
4. **Writer** — psycopg2 against `DATABASE_URL`, batched
   `INSERT ... ON CONFLICT` upserts in FK order (`users` first) for bulk
   and delta alike, so every run is idempotent; `--truncate` empties the
   target tables first for a clean-slate bulk copy. Schema is owned by
   Alembic: the tool **refuses to run** unless `alembic_version` in the
   target database equals the repo's head revision.

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

Checkpoints live in a `_migration_state` table in the target database:
for each (kind, shard), the last committed cursor and the row count,
updated in the same transaction as each batch. `--resume` continues from
there and re-reads at most the batch that was in flight. Ctrl-C (SIGINT)
is safe: every run is resumable and every mode is idempotent.

## Verification

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
venv/bin/python -W ignore scripts/migrate_to_postgres.py \
    --project netskrafl \
    --credentials credentials/netskrafl/service-account.json \
    --database-url postgresql://... \
    [--mode bulk|delta]                 # default bulk
    [--truncate]                        # bulk: empty the target tables first
    [--since 2026-09-01T00:00:00Z]      # delta: lower bound (T0 minus overlap)
    [--kinds GameModel UserModel ...]   # default: all
    [--shards 8]                        # parallel shards for the heavy kinds
    [--resume] [--run-id ID]            # continue from the checkpoints
    [--verify 200]                      # spot-check N rows per kind
    [--dry-run]                         # read, decode, transform; no writes
```

At the end of a bulk run the migrator prints the T0 to use for the next
delta pass.

The migrator never ships in the image (`scripts/` is excluded from the
Docker and App Engine builds). Its environment needs are in the
implementation notes below.

## Implementation notes (2026-08-14, deviations from the design above)

`scripts/migrate_to_postgres.py` is implemented; differences from the
plan, all in the writer/bookkeeping layer:

- **Upserts everywhere, no COPY.** The repo uses psycopg2 (not
  psycopg3); `execute_values` batched `INSERT ... ON CONFLICT` is used
  for bulk as well as delta. The REST reader is the throughput bound,
  upserts make every path idempotent, and one code path is simpler.
  `--truncate` provides the clean-slate bulk variant.
- **Checkpoints live in the target database** (`_migration_state`
  table), updated in the same transaction as each batch — exactly-once
  semantics with no separate state file; `--resume` reads it back.
- **Deterministic UUID PKs**: kinds whose PG tables use UUID primary
  keys (stats, chats, challenges, reports, promos, transactions,
  submissions, completions, images) get `uuid5(MIGRATION_NS, full key
  path)` — stable across runs, which is what makes delta upserts land
  on the same rows. The namespace constant must never change.
- **FK repair**: the users id-set is held in memory (50k); dependent
  rows with missing users are skipped (NOT NULL FKs) or nulled
  (nullable FKs), each counted and reported. Games are the exception:
  their player FKs are nullable, but a NULL player means the robot, so a
  game with a missing player is skipped (id logged) rather than turned
  into a robot game, and so is a game with no human player at all.
  Zombies are additionally
  filtered against existing game ids in PG. Kinds where the source may
  contain duplicates on the PG key (favorites, blocks, zombies) use
  `ON CONFLICT DO NOTHING`; verification checks existence only for
  those, and full column equality elsewhere, sampled post-filter.
- **Numeric key bounds by binary search** (~60 probes): descending
  `__key__` order would need a composite index that doesn't exist.
  Numeric range shards keep open outer bounds, so stray string-named
  keys are still swept up by the first/last shard.
- **Delta-replace kinds** (all the small ones) are wiped and fully
  reloaded inside the delta pass, so rows deleted at the source since
  T0 also disappear from PG. Users are the one small kind that is
  re-copied by upsert instead (the dependent tables reference them);
  UserModel entities are never deleted in normal backend operation, so
  nothing is lost. Games/chats/stats deletions are likewise not
  propagated by a delta pass — vanishingly rare inside a freeze window.
  Note that UserModel has no last-modified property (`timestamp` is the
  creation time and `last_login` does not move when a finished game
  updates the user's Elo/stats fields), so the users delta is a full
  re-read: ~4 min for explo-live's 36k users, the dominant part of its
  delta pass.
- **Environment**: importing the NDB model layer pulls in
  `src/config.py`, so the tool needs project credentials and a local
  Redis; it sets the standard local-dev env vars itself from
  `--project`/`--credentials`. (The design's "no config machinery"
  aspiration didn't survive contact with the import graph.)

## Implementation notes (2026-09-10, from the explo-live rehearsal)

- **Shards run in worker processes, not threads.** The first explo-live
  bulk run decoded games at ~40/s with 8 threads and exactly one core
  busy: the decode path (`json_format.ParseDict`, pure Python, ~5 ms per
  game, plus the NDB model layer, ~3 ms) is CPU-bound, and the threads
  additionally convoyed on the process-wide lock inside `strptime`,
  which protobuf's timestamp parser calls 30–40 times per game (once
  per move timestamp). With one `multiprocessing` ("spawn") worker per
  shard the same copy ran at ~600 games/s. Each worker bootstraps its
  own `Migrator` and returns its count, counters and verification
  samples for the parent to merge; single-shard kinds still run in the
  main process. The "≈2,140 entities/s" read-side estimate above was
  measured without decoding and does not bound a real run; budget
  ~8 ms of CPU per game (≈1 core-hour per 450k games) and ~1 GB/hour
  of gzip-compressed JSON.
- **Verification samples cross the process boundary normalized**:
  psycopg2's `Json` wrappers keep a reference to the connection they
  were executed on and cannot be pickled; the worker unwraps them
  (`Migrator.normalize`, idempotent) before returning.
- **T0 is persisted** in `_migration_state` (pseudo-shard `_run/t0`) on
  the first bulk attempt and reused by `--resume`, so the "T0 for a
  subsequent delta pass" line printed at the end is the start of the
  first attempt, not of the resume. (Before this, a resumed run printed
  its own start time — an operator trap at cutover.)
- **Newer CPython does not help** the decode cost: measured 3.1–3.6 ms
  per game on 3.11–3.13 and 11 ms on 3.14 (all with the upb protobuf
  core; the JSON layer is pure Python). The migrator stays on the GAE
  runtime version (3.11) with the pinned google-cloud-ndb anyway.
- `scripts/decode_sweep.py` loads every migrated user and game through
  the app's own loaders (`User.load_if_exists`, `Game.load`) and reports
  any row that fails, on a copy of the database. At ~600 games/s per
  process, netskrafl's 10.4M games would take ~5 hours in one process,
  so `--jobs N` runs N hash-partitioned shards in parallel (`--shard I/N`
  runs one of them).

## Implementation notes (2026-11, from the netskrafl rehearsal)

- **Games with a missing player are skipped**, not repaired: a NULL
  player means the robot, so nulling a player whose user entity no
  longer exists turned a game into a robot game (three such games, all
  unfinished robot games whose human user had been deleted by hand). Games
  with no human player at all are skipped too. Both are counted and
  their ids logged.
- **Production safety during the bulk copy**: the copy ran at night, at
  low CPU priority in its own process group, next to a watchdog that
  compared App Engine production every two minutes with a baseline taken
  just before the start (5xx responses, application errors, median
  latency) and would have stopped the copy with SIGINT, which leaves it
  resumable. It never fired: Datastore reads at this rate did not affect
  production at all.
- **What the delta pass spends its time on** (7.5 min in all): the full
  users re-read (2 min for 52k users), games since T0 (under 2 min), and
  the wipe-and-reload of the small kinds (about 4 min, mostly challenges,
  promos and favorites at 30–50k rows each).
- **Verification on a copy**: the API tests and the replay harness write
  to the database, so they run on a local `pg_dump`/`pg_restore` copy,
  never on the migrated target. The API tests do not stub out Firebase
  either: run them with a development project's configuration, so test
  games do not send notifications to a production Realtime Database.

## Rehearsals

1. ✅ **explo-dev — 2026-08-14**, into the `explo_dev` database on the
   staging cluster: 19k entities, bulk in 0.7 min over 4 shards,
   `--verify 50` clean on all 19 tables, delta pass exercised (filters +
   replace kinds) in 0.3 min. Orphan/dedup counts all explained by
   explo-dev test-data leftovers. The staging app has served this
   database since 2026-08-18.
2. ✅ **explo-live — 2026-09-10**, into a new `explo_live` database
   (ICU `und`, Alembic head) on the staging cluster, from the dev box:
   - **Bulk:** 2.41M entities. Users 35,870 in 3.5 min (single stream,
     ~22 KB each); games 1,461,702 in ~41 min once the worker-process
     fix was in (~600/s over 8 shards; the thread version managed ~40/s);
     stats 625,673 in 2.5 min; chats 230,594 in 1.7 min; all small
     kinds under a minute. **≈50 min wall-clock for a clean run.**
     `--verify 200`: 0 mismatches (games' samples were lost to the
     pickling bug, fixed since, and are covered by the sweep instead).
     Repairs reported: 67 chats with an unknown recipient nulled, 1
     duplicate image, 2 duplicate favorites and 32 duplicate blocks
     collapsed (`ON CONFLICT DO NOTHING` kinds). Target size 4.4 GB.
   - **Delta** (`--since` T0 − 1 h, i.e. a 3-hour window): **5.4 min**,
     of which the full users re-read was 4.1 min; games 526 rows in
     6 s, chats 50, stats 0 (written only by the nightly cron), every
     replace kind in seconds. `--verify 100`: clean. So the freeze
     window for explo-live is bounded by the users pass, ~5–6 min.
   - **Verification** on a local `pg_dump`/`pg_restore` copy (2.2 GB
     dump in 3 min, restore in 3.5 min): `tests/api_e2e` 125 passed
     (`E2E_KEEP_TABLES=1`), replay harness 105/105 fixtures exact,
     decode sweep (`scripts/decode_sweep.py`): 36,025/36,025 users and
     1,461,796/1,461,796 games load through the real app loaders (~640
     games/s, 38 min); the single "bad" row reported was a transient
     game created and deleted by the concurrently running API tests,
     present in neither database afterwards. Run the sweep alone next
     time.
   - Kinds present in explo-live but not migrated on purpose:
     `AdminUser` (2 entities, unused by the app).
3. ✅ **netskrafl — 2026-11-07 (bulk) and 2026-11-09 (delta and
   verification)**, into the netskrafl production cluster:
   - **Bulk** (`--truncate --shards 8 --verify 200`), started 01:30 UTC:
     **238 minutes**. Users 52,060 in 2 min; games 10,424,753 in
     200 min (~54k per minute over 8 shards); stats 3,561,643 in 12 min;
     chats 3,666,260 in 20 min; every small kind within a minute or two.
     `--verify 200`: 0 mismatches. Repairs: 3 games with a missing player
     (since skipped, see the notes above), and duplicate favorites and
     blocks collapsed. Target size 24 GB (the Datastore holds ~40 GB of
     entity data). Production was unaffected throughout: no 5xx
     responses, no errors, median latency at its baseline.
   - **Delta** (`--since` T0 minus 2 days, i.e. a 4.5-day window):
     **7.5 minutes**, with games 9,584 rows, stats 2,347, chats 1,167,
     and every small kind reloaded; `--verify 100` clean. This bounds the
     write freeze at cutover at about 8 minutes.
   - **Verification** on a local copy (dump 13 min, 9.3 GB; restore 25
     min): `tests/api_e2e` 125 passed (`E2E_KEEP_TABLES=1`); replay
     harness 95 of 95 (10 fixtures that failed only because the
     vocabulary had changed since the games were played were removed);
     decode sweep with `--jobs 6`, about 100 minutes: all 52,249 users
     and 10,428,780 games load through the app's loaders, none bad.
   - Kinds not migrated on purpose: `ChannelModel` (4,062 entities,
     unused since 2017).

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

## Open items

None for the migrator itself. The numeric-ID range splits for StatsModel
and ChatModel proved even enough (3.6M stats rows and 3.7M chats in 12
and 20 minutes over 8 shards), and the copy streams batch by batch, well
within the development box's memory. The final runs at cutover follow the
sequence in `migration-strategy.md`.
