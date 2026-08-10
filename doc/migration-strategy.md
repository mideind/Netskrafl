# Migration Strategy: GAE + NDB → Containers + PostgreSQL

*Written: August 2026. Synthesizes and updates `dockerization-plan.md`,
`postgresql-plan.md`, `postgresql-testing-strategy.md`, and `DB_PARITY_AUDIT.md`
against the actual state of the repository.*

*Updated August 2026: Phase A (container-mode blockers) was implemented on
the `prepare-migration` branch — see the ✅ RESOLVED markers on Blind Spots
3–8 below. Blind Spot 9 (Cloud Tasks backfill chaining) is declared moot:
the ratings backfill has been completed in production and no comparable
operation on this data is anticipated.*

## Executive Summary

The two big engineering workstreams — **containerization** and the
**PostgreSQL backend** — are genuinely complete and well-tested. What is
missing is the connective tissue that turns them into a production migration:
schema migration tooling, Datastore→PostgreSQL data migration tooling, and a
handful of container-mode blockers. Production today is still 100% NDB on GAE
across all three projects (netskrafl, explo-dev, explo-live).

A key strategic advantage: **hosting and database can be migrated
independently**, because the container runs the NDB backend fine (and has
already done so successfully on Digital Ocean App Platform). The plan below
exploits that to isolate risk.

**On Vercel:** there is no Vercel configuration or mention anywhere in the
repo, and that is the right call. This app is a poor fit for a serverless
model: it is a long-lived gunicorn process that loads ~13 MB of DAWG
vocabularies into memory at warmup, needs persistent Redis, in-container cron,
and 30s+ batch jobs. Digital Ocean (or any container host) is the target of
record; Vercel is dropped from consideration.

---

## Where We Stand

### Complete and verified

- **Containerization is done and field-proven.** The 5-stage `Dockerfile`
  (uv, DAWG download from DO Spaces CDN, frontend build, supercronic,
  non-root runtime), `docker-compose.yml`, health endpoints
  (`/health/live`, `/health/ready`), `ProxyFix`, platform-aware logging, and
  the `CRON_SECRET` machinery all exist. A deployment on Digital Ocean App
  Platform with Valkey (Redis-compatible) succeeded — running the **NDB**
  backend in a container (see `dockerization-plan.md`).

- **The PostgreSQL backend is complete.** All 19 repositories are implemented
  on both backends behind typed protocols (`src/db/protocols.py`), with
  symbol-level parity: every name that application code imports from
  `skrafldb` exists in both `skrafldb_ndb.py` and `skrafldb_pg.py`. All 19
  PG tables exist in `src/db/postgresql/models.py`; the only NDB model with
  no PG table is `MoveModel`, by design (denormalized into `games.moves`
  JSONB).

- **Correctness has been audited.** `DB_PARITY_AUDIT.md` found eight real PG
  bugs (including high-severity ones: swapped scores for player1, stats-table
  pollution on read) — all fixed and regression-tested in
  `tests/db/test_backend_parity.py`.

- **The abstraction holds for new feature work.** The July 2026 rewrite of
  `/stats/ratings` (PR #149) introduced a new NDB model
  (`RatingArchiveModel`) plus new query methods (`UserModel.list_top_elo`,
  `StatsModel.newest_before_multi`) — and shipped with the full PostgreSQL
  mirror in the same commit: `rating_archive` table, repository, protocol,
  facade methods, and 24 dual-backend tests in
  `tests/db/test_rating_archive_repository.py` (verified passing on both
  backends, August 2026). New backend features are being kept in parity as
  they land, which is exactly what the migration needs.

- **Test coverage is strong.** ~180 repository tests parametrized over both
  backends (`tests/db/`, `--backend=both`), plus ~118 end-to-end API tests in
  `tests/api_e2e/` that run the *real Flask app* with
  `DATABASE_BACKEND=postgresql`. The e2e suite is the strongest evidence that
  the PG path works through the full stack.

### Missing or broken

| Area | State |
|------|-------|
| Schema migrations | ✅ **Fixed** (prepare-migration, Phase B) — Alembic with a verified initial revision; `docker-entrypoint.sh` runs `alembic upgrade head` in PG mode. |
| Data migration (Datastore→PG) | **Absent** — `scripts/migrate_to_postgres.py` from the plan was never written; there is no `scripts/` directory. |
| Container cron auth | ✅ **Fixed** (prepare-migration) — `/stats/run`, `/stats/ratings`, and `/cacheflush` now accept `X-Cron-Secret` via the shared `cron_request_source()` helper. |
| Long-running cron jobs | ✅ **Fixed** (prepare-migration) — externally scheduled stats jobs dispatch asynchronously, out of reach of the gunicorn request timeout. |
| Secret Manager | ✅ **Fixed** (prepare-migration) — `SECRETS_PROVIDER=env` selects an environment-based provider; GCP Secret Manager remains the default. |
| Firebase RTDB / FCM | **Retained Google dependency**, no abstraction layer. |
| Deployable PG topology | ✅ **Fixed** (prepare-migration, Phase B) — `docker-compose.pg.yml`: self-contained app + PostgreSQL 16 (ICU collation) + Redis stack with schema auto-migration. |
| Production state | All three projects run NDB on GAE; `DATABASE_BACKEND` has never been set anywhere in production. |

---

## Blind Spots (Detailed)

1. ✅ **RESOLVED — No schema migration tooling.** *Fixed on
   `prepare-migration` (Phase B):* Alembic is set up (`alembic.ini`,
   `migrations/env.py` reading `DATABASE_URL` from the environment — no
   application secrets needed) with an initial revision that exactly
   reproduces the model schema (verified: empty autogenerate diff after
   upgrade, and a clean downgrade/upgrade cycle). `docker-entrypoint.sh`
   runs `alembic upgrade head` when `DATABASE_BACKEND=postgresql`, so a
   fresh container against an empty database boots to a working schema.
   For databases whose schema predates Alembic (created via
   `create_all()`), run `alembic stamp head` once. `alembic` was added to
   `requirements-pg.txt`; `alembic.ini`/`migrations/` are copied into the
   Docker image and excluded from GAE deploys.

2. **No data migration tooling.** The `utils/` scripts are all NDB-only
   one-offs. Note that `.dockerignore` and `.gcloudignore` both exclude
   `utils/`, so migration tooling must run outside the image or the ignore
   rules need adjusting.

3. ✅ **RESOLVED — Two of three cron jobs 403'd in a container.**
   `_scheduler_wait_mode()` in `src/skraflstats.py` (guarding `/stats/run`
   and `/stats/ratings`) and the copy-pasted check on `/cacheflush` in
   `src/web.py` accepted only GAE/Cloud Scheduler headers, rejecting the
   container's own `X-Cron-Secret` requests. *Fixed on `prepare-migration`:*
   cron authorization is unified in `firebase.cron_request_source()`
   (platform-gated GAE/GCP headers, `X-Cron-Secret`, local dev), used by
   `is_cron_request()`, `_scheduler_wait_mode()`, and `/cacheflush`.

4. ✅ **RESOLVED — Stats job vs. the 30-second gunicorn timeout.** Under
   supercronic, the stats batch ran *synchronously* in the request, subject
   to gunicorn's `--timeout 30`. *Fixed on `prepare-migration`:*
   `_scheduler_wait_mode()` returns the async (`wait=False`) dispatch mode
   for both Cloud Scheduler and external (`X-Cron-Secret`) schedulers, so
   the batch runs on a background thread and the HTTP request returns
   immediately — same pattern GAE used for Cloud Scheduler.

5. ✅ **RESOLVED (secrets) — Google doesn't fully go away.**
   `src/config.py` called Google Cloud Secret Manager at module import and
   could not boot without it. *Fixed on `prepare-migration`:*
   `src/secret_manager.py` now defines an abstract `SecretProvider` with two
   implementations — `GoogleSecretManager` (default, unchanged behavior) and
   `EnvSecretProvider` (`SECRETS_PROVIDER=env`), which reads `<SECRET_ID>`
   or base64-encoded `<SECRET_ID>_BASE64` environment variables and imports
   no Google libraries. Firebase RTDB + FCM (realtime game push, presence
   tracking, push notifications, custom auth tokens) remain a retained
   Google dependency with no abstraction layer; the near-term posture is
   "hosted anywhere, still dependent on Google for Firebase."

6. ✅ **RESOLVED — `ChatModel.delete_for_user()` was a `pass` in
   `skrafldb_pg.py`.** *Fixed on `prepare-migration`:* implemented across
   the stack (`ChatRepositoryProtocol.delete_for_user`, NDB and PG
   repositories, PG facade), with dual-backend tests in
   `tests/db/test_chat_repository.py`. Note: its only current callers are
   the legacy test suite's cleanup helpers; `delete_account()` does not
   delete chat messages on either backend (a separate product decision).

7. ✅ **RESOLVED — `transactional()` is a no-op under PG.** *Fixed on
   `prepare-migration`:* `submit_move()` now loads the game with
   `for_update=True`, which on PostgreSQL translates to
   `SELECT ... FOR UPDATE` on the game row
   (`GameRepository.get_by_id(for_update=True)`, with `populate_existing`
   to defeat identity-map staleness), serializing concurrent move
   submissions for the duration of the request transaction. NDB ignores the
   flag and keeps its `@ndb.transactional` semantics. Verified by a
   lock-contention test (`FOR UPDATE NOWAIT` from a second connection) in
   `tests/db/test_game_repository.py`.

8. ✅ **RESOLVED — `skrafldb_pg.py` imported `skrafldb_ndb.py`** for shared
   TypedDicts/dataclasses, making `google-cloud-ndb` a hard dependency even
   in PG mode. *Fixed on `prepare-migration`:* the shared types were already
   canonically defined in `src/db/protocols.py`; `skrafldb_pg.py` now
   imports them from there and defines its own `DEFAULT_ELO_DICT`. Verified:
   with `DATABASE_BACKEND=postgresql`, importing `skrafldb` loads neither
   `skrafldb_ndb` nor `google.cloud.ndb`. (The packages can be dropped from
   the PG container's requirements in Phase F.)

9. **MOOT — Cloud Tasks backfill chaining is GAE-only.**
   `_enqueue_backfill_task()` in `src/skraflstats.py` uses
   `AppEngineHttpRequest` routing and degrades gracefully outside GAE.
   Decision (August 2026): the ratings backfill has been completed in
   production and no comparable operation on this data is anticipated, so
   this is not a migration concern.

10. ✅ **RESOLVED — Admin routes are gated on `running_local`** (`src/web.py`),
    so they are unavailable in production containers.
    **Decision (August 2026): keep this model.** Admin operations continue
    to run on a locally started instance connected to the production
    database — the same workflow used against GAE/NDB. Rationale:
    - DO managed PostgreSQL is reachable from a local box via a
      trusted-sources IP allowlist over TLS (`sslmode=require`), or via an
      SSH tunnel through any droplet in the VPC. Set `DATABASE_URL`
      accordingly, with `RUNNING_LOCAL=true` and
      `DATABASE_BACKEND=postgresql`.
    - The old NDB/Redis cache-incoherency snag largely disappears: the PG
      backend has no Redis entity cache, so local admin writes are
      immediately visible to production instances. Derived Redis state
      (rating tables, live lists) can be invalidated remotely via
      `/cacheflush` with the `X-Cron-Secret` header.
    - Long-running admin jobs don't belong in production web requests
      (gunicorn timeout), and unregistered routes are a stronger guarantee
      than any auth check. An env-var admin flag (e.g. `ADMIN_USER_IDS`)
      remains an option later, scoped to cheap operations only.

    *Test pass (prepare-migration):* `tests/api_e2e/test_admin.py` now
    exercises the admin routes and the deferred (background-thread) admin
    jobs against PostgreSQL. This uncovered and fixed three real gaps in
    the PG facade:
    - `UserModel.query()` / `GameModel.query()` did not exist (the base
      `Query` stub silently returned empty results) — **`/stats/run` was
      broken under PG** as well as the deferred admin jobs. Fixed via
      `FacadeQuery` in `skrafldb_pg.py`, which translates NDB-style
      conditions (`UserModel.locale == x`, `ndb.AND(...)`, `.order(...)`)
      to SQLAlchemy queries; `/stats/run` is now e2e-tested on PG.
    - `Client.get_context()` was a no-op on PG, so background threads
      (deferred admin jobs, async stats dispatch) got a thread-local
      session that was **never committed or closed** — silent data loss
      plus a connection leak. It now establishes a real session scope
      (commit on success, rollback on exception, close on exit), with a
      no-op guard when already inside a WSGI request.
    - `EloModel.put_multi()` (classmethod) was missing from the PG facade.

11. ✅ **RESOLVED — Index verification.** *Done on `prepare-migration`
    (Phase B):* `index.yaml` was diffed against
    `src/db/postgresql/models.py`. Already covered: `RatingModel(kind,rank)`
    (composite PK), the `EloModel` locale composites, `ImageModel(user,fmt)`.
    Added composites mirroring the remaining Datastore indexes:
    games `(player0_id|player1_id, over, ts_last_move)` and
    `(over, ts_last_move)` (per-player lists and the `/stats/run` scan),
    stats `(user_id, robot_level, timestamp)` (`newest_before` lookups and
    leaderboard dedup), chats `(channel|user_id|recipient_id, timestamp)`,
    challenges `(src|dest, timestamp)`, users `(locale, nick_lc|name_lc)`
    and `(locale, human_elo)`, promos `(user_id, promotion, timestamp)`,
    transactions `(user_id, ts)`. Deliberately not ported: the StatsModel
    `(timestamp, *elo)` composites, which served NDB's legacy
    descending-Elo scan — the PG leaderboard uses `DISTINCT ON` served by
    the new stats composite instead. All indexes are included in the
    initial Alembic revision.

12. **Static file serving.** GAE's ~20 tuned static handlers in
    `app-netskrafl.yaml` are replaced by Flask serving everything through
    Python; the nginx static block exists but is commented out in
    `nginx.conf`. Enable it (or a CDN) to avoid regressing static-asset
    performance at scale.

13. **DAWG file list is hand-maintained.** The Dockerfile's download list
    must be kept in sync with `src/wordbase.py:_ALL_DAWGS` manually (the
    Dockerfile comment says so).

---

## Migration Plan

### Phase A — Close the container-mode blockers — ✅ DONE (prepare-migration)

1. ✅ Unified cron auth on `cron_request_source()` for `/stats/run`,
   `/stats/ratings`, and `/cacheflush` (Blind Spot #3).
2. ✅ Async dispatch for externally scheduled stats jobs (Blind Spot #4).
3. ✅ Implemented `ChatModel.delete_for_user()` for PG (Blind Spot #6).
4. ✅ Added row locking to the PG `submit_move` path (Blind Spot #7).
5. ✅ (Pulled forward from Phase F prerequisites) Env-based secrets provider
   (Blind Spot #5) and severing the `skrafldb_pg` → `skrafldb_ndb` import
   (Blind Spot #8).

Verified: `tests/db/` 315 passed (`--backend=both`), `test/` 49 passed,
`tests/api_e2e/` 118 passed, pyright clean. (20 e2e tests had been failing
since the paywall alignment: they played premium robots — `robot-0/5/10` —
with non-paying test users, and `/initgame` correctly returned
`premium_required`. Production behavior was correct; the stale tests now
mark their users as paying via `AuthHelper.login_user(..., paid=True)`.)

### Phase B — Alembic and deployable topology — ✅ DONE (prepare-migration)

1. ✅ Alembic adopted; initial revision generated from the models and
   verified drift-free with a working downgrade path (Blind Spot #1).
2. ✅ `docker-entrypoint.sh` runs `alembic upgrade head` in PG mode.
3. ✅ `docker-compose.pg.yml` added: full self-contained stack (app +
   PostgreSQL 16 + Redis) with healthchecks and named volumes; the
   postgres service initializes its cluster with ICU collation
   (`und`), matching the production recommendation. On DO App Platform,
   the postgres service is replaced by managed PostgreSQL via
   `DATABASE_URL`. Provisioning the managed production database with ICU
   collation (PostgreSQL 15+) remains a deploy-time step.
4. ✅ Index parity with `index.yaml` established (Blind Spot #11); all
   indexes are in the initial Alembic revision.

Additional hardening from the Phase B kickoff sweep: a method-level
parity comparison of the two facades found no remaining functional gaps
(the "missing" NDB methods have no callers outside `skrafldb_ndb.py`
itself), and the PG facade's residual silent stubs (`Model.query`,
`Model.get_by_id`, the leftover `Query` shell) now raise
`NotImplementedError` instead of returning empty results — future facade
gaps will fail loudly instead of masquerading as an empty database.

Verified: `tests/db/` 315 passed (`--backend=both`), `tests/api_e2e/`
125 passed, `test/` 49 passed, pyright clean.

### Phase C — Prove hosting on DO with NDB first (optional, low-risk)

The DO deployment already worked with NDB. Move traffic (or run a shadow
instance) on DO *before* touching the database. Hosting problems surface
without any data-migration risk; rollback is DNS.

### Phase D — Write and rehearse the data migration

1. Build `scripts/migrate_to_postgres.py` per `postgresql-plan.md`
   (batched, UTC-preserving, moves→JSONB, UUID strings preserved as-is).
2. Build the count/sample verification script.
3. Rehearse against a production Datastore export into a staging PG database;
   run the `tests/api_e2e/` suite against the migrated data.
4. Diff `index.yaml` against the PG index declarations (Blind Spot #11).

Given the test coverage, dual-write is probably unnecessary — a
maintenance-window cutover is simpler and safer than dual-write complexity
(this matches the note in `postgresql-plan.md` Phase 2).

### Phase E — Cutover, per project, smallest first

Order: **explo-dev → explo-live → netskrafl.**

1. Brief write freeze; final migration + verification.
2. Flip `DATABASE_BACKEND=postgresql`; monitor.
3. Keep NDB warm for a ~30-day rollback window. Note: rollback after real
   writes means data loss back to the freeze point, so the verification gate
   in Phase D matters.

### Phase F — Cleanup (postgresql-plan.md Phase 5)

1. ✅ ~~Extract the shared TypedDicts/dataclasses out of `skrafldb_ndb.py`~~
   (Blind Spot #8 — done in Phase A; `skrafldb_pg` imports from
   `db.protocols`).
2. Delete `skrafldb_ndb.py`, `src/db/ndb/`, and the Google Datastore
   dependencies; fold `requirements-pg.txt` into `requirements.txt`.
3. Retire `cron.yaml`, `index.yaml`, `dispatch.yaml`, `app-*.yaml` once GAE
   is decommissioned.

---

## Open Decision

**Is GCP-for-secrets-and-Firebase acceptable long-term?**

- If **yes**: the plan above is mostly mechanical from here.
- If **no**: still execute the plan above unchanged, and treat the follow-on
  as a separate project rather than letting it inflate this one:
  - ✅ *Env-var-based secrets* — done (Phase A): `SECRETS_PROVIDER=env`
    with `EnvSecretProvider` in `src/secret_manager.py`.
  - *Firebase replacement* — large; covers presence, realtime push, FCM
    notifications, custom auth tokens, plus client changes in the
    `explo-front` repository. Out of scope for the hosting/database
    migration.
