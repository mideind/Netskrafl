# Migration Strategy: GAE + NDB → DO Containers + PostgreSQL

*Written: August 2026. Synthesizes and updates `dockerization-plan.md`,
`postgresql-plan.md`, `postgresql-testing-strategy.md`, and `DB_PARITY_AUDIT.md`
against the actual state of the repository.*

*Updated 2026-08-12: Phases A and B are complete and merged to master
(PR #152). The replay-based differential test harness and concurrency work
landed (PR #153). The Digital Ocean App Platform staging app was revived and
the kaniko build fixes merged. The detailed record of the thirteen original
blind spots has been compressed to a summary — see the git history of this
file for the full write-up. Scope addition: the **GoSkrafl "moves" service**
is now explicitly part of the migration (it must move to DO along with the
main backend).*

## Executive Summary

The overall project is to move Netskrafl/Explo off Google App Engine and
Google Cloud NDB onto Digital Ocean. It proceeds on **two tracks**:

1. **Database track** — migrate the production databases from Datastore/NDB
   to DO managed PostgreSQL.
2. **Hosting track** — run the backend and all auxiliary services on DO App
   Platform: the containerized Flask app, managed Valkey (Redis-compatible)
   for caching, supercronic for scheduled jobs, and the GoSkrafl Go backend
   (`/moves`, `/wordcheck`, `/riddle`).

The two tracks are deliberately independent — the container runs the NDB
backend fine, which is exactly what the current staging deployment does — so
hosting risk and data-migration risk never have to be taken at the same time.

The two big engineering workstreams — **containerization** and the
**PostgreSQL backend** — are complete and heavily tested (including a
replay-based differential harness that runs real production games through
the full API against both backends). Production today is still 100% NDB on
GAE across all three projects (netskrafl, explo-dev, explo-live).

We are roughly at **Phase C**: a staging container is live on DO App
Platform against explo-dev/NDB. The largest remaining engineering artifact
is the **Datastore→PostgreSQL data migration tooling**; the largest
remaining infrastructure work is attaching the managed services (Valkey,
PostgreSQL) and porting GoSkrafl.

**On Vercel:** dropped from consideration (long-lived gunicorn process,
~14 MB DAWG warmup, persistent Redis, in-container cron, 30s+ batch jobs —
a poor serverless fit). DO is the target of record.

---

## Where We Stand

### Complete and verified

- **Containerization is done and field-proven.** The 5-stage `Dockerfile`
  (uv, DAWG download from DO Spaces CDN, frontend build, supercronic,
  non-root runtime), `docker-compose.yml` and `docker-compose.pg.yml`,
  health endpoints (`/health/live`, `/health/ready`), `ProxyFix`,
  platform-aware logging, and the `CRON_SECRET` machinery all exist. The
  build is kaniko-compatible (App Platform does not build with BuildKit;
  see the build gotcha in `CLAUDE.md`).

- **The PostgreSQL backend is complete.** All 19 repositories are implemented
  on both backends behind typed protocols (`src/db/protocols.py`), with
  symbol-level parity between `skrafldb_ndb.py` and `skrafldb_pg.py`. The
  only NDB model with no PG table is `MoveModel`, by design (denormalized
  into `games.moves` JSONB). Alembic owns the schema; `docker-entrypoint.sh`
  runs `alembic upgrade head` in PG mode.

- **Correctness has been audited three ways.**
  - `DB_PARITY_AUDIT.md` found eight real PG bugs (including swapped
    player-1 scores and stats-table pollution on read) — all fixed and
    regression-tested in `tests/db/test_backend_parity.py`.
  - **Replay-based differential testing** (PR #153): 105 sampled production
    games (fixtures in `test/replay_fixtures/`, sampler in
    `utils/sample_replay_games.py`) are replayed move-by-move through the
    real Flask API against both backends and the results compared. This
    found and fixed a PG `create()` upsert bug.
  - **Concurrency testing** (PR #153): concurrent move-submission tests
    found and fixed a class-lock/row-lock deadlock in `Game.load`; the
    GAE-era Python thread locks around game processing were then retired in
    favor of the PG row-locking model (`SELECT ... FOR UPDATE` in
    `submit_move`; NDB keeps its transactional semantics).

- **The abstraction holds for new feature work.** The July 2026
  `/stats/ratings` rewrite (PR #149) shipped its NDB model and the full
  PostgreSQL mirror (table, repository, protocol, facade, 24 dual-backend
  tests) in the same commit. Parity is being maintained as features land.

- **Test coverage is strong.** ~315 repository tests parametrized over both
  backends (`tests/db/ --backend=both`), ~125 end-to-end API tests
  (`tests/api_e2e/`) running the real Flask app with
  `DATABASE_BACKEND=postgresql`, the legacy `test/` suite, plus the replay
  and concurrency suites above.

### Digital Ocean staging (status 2026-08-12)

The App Platform app `netskrafl-staging` (region ams,
`https://netskrafl-staging-fvmuj.ondigitalocean.app`) is live, running
`PROJECT_ID=explo-dev` with `DATABASE_BACKEND=ndb` on one
`apps-s-1vcpu-1gb` instance, auto-deploying on push to the dedicated
`do-deploy` branch. The app spec reference copy is checked in at
`.do/app.yaml` (placeholders only — round-trip the live spec via `doctl`,
never apply the file to the live app). Secrets follow `PROJECT_ID` via
Secret Manager; only `GOOGLE_CREDENTIALS_BASE64` is a platform env var.

Not yet exercised on App Platform:

- **No Valkey/Redis attached** — consequently `/health/ready` fails and no
  `health_check` is configured on the service.
- **`CRON_SECRET` deliberately unset** — supercronic, and therefore all
  scheduled jobs, are off (see `docker-entrypoint.sh`).
- **The PostgreSQL backend has never been deployed here**; no managed PG
  cluster has been provisioned.
- **Sizing is not production-parity**: 1 GB per instance vs. GAE's `B4_1G`
  (2 GB) with the same 3 gunicorn workers — not a valid load-test baseline.

### The GoSkrafl "moves" service (new in scope)

GoSkrafl (repo `../GoSkrafl`) is a Go crossword engine serving three
endpoints — `/moves` (best-move analysis), `/wordcheck`, and `/riddle`
(riddle generation, up to ~20 s per request). Today it runs as the GAE
service `moves` (runtime `go125`, F1, max 2 instances) on **explo-dev and
explo-live** (`go-app/app.yaml`, `deploy.sh`/`deploy-live.sh`); the
netskrafl project has no instance of it. Consumers:

- **This backend** calls `/riddle` from `src/riddle.py`, authenticating
  with the `MOVES_AUTH_KEY` secret (Secret Manager). The endpoint URLs are
  **hardcoded appspot.com URLs** (`RIDDLE_ENDPOINT_DEV/_PROD` in
  `src/riddle.py`); explo-live uses the prod endpoint, everything else —
  including production netskrafl — uses the dev endpoint (a standing TODO).
- **The Explo mobile client** (`explo-front`) calls `/moves` and
  `/wordcheck` directly, configured via `movesApiUrl` / `movesAccessKey` in
  its Expo config, with CORS handled by the service (`ALLOWED_ORIGINS`).
  The Go `/wordcheck` is deliberately API-identical to the Flask one, and
  current clients prefer it because it is much faster; the Flask route
  remains for the built-in web UI (session-cookie rather than bearer auth).

**Chosen architecture (decided 2026-08-13): loopback sidecar.** In the
container era, GoSkrafl runs as a second process *inside the Netskrafl
container*, bound to `127.0.0.1` and supervised by `docker-entrypoint.sh`
(alongside supercronic). Flask owns the public `/moves`, `/wordcheck` and
`/riddle` routes: it performs real session authentication and forwards
over loopback (~0.1–0.3 ms), replacing the bearer-`ACCESS_KEY` hack.
Externally there is then one backend, one hostname, one auth model; the
sidecar keeps process isolation (a Go crash restarts one process, the
20 s riddle generation stays out of the web workers) and loads its DAWGs
once, shared by all gunicorn workers. The alternative — linking Go into
the Python process via a `c-shared` library — was considered and
rejected: it saves only the loopback hop while adding gunicorn
fork-safety constraints, crash coupling, per-worker memory duplication,
and a C ABI to maintain; it remains available later behind the same
Flask routes if profiling ever justifies it.

The bridge design: the Flask routes forward to a **configurable target
URL** — the external GAE service today, `127.0.0.1` when the sidecar is
present. This also retires the hardcoded `RIDDLE_ENDPOINT_*` constants
and the netskrafl-uses-dev-endpoint TODO as a side effect.

**Drain constraint:** older Explo clients call the GAE `moves` service
directly at its hardcoded appspot.com URL. The GAE service must
therefore stay up until that direct traffic drains — expected to take
**several months** after clients switch to the main API host — and is
decommissioned only then (monitor its request logs to decide).

### Missing or not yet done

| Area | State |
|------|-------|
| Data migration (Datastore→PG) | ✅ **Implemented (2026-08-14)** — `scripts/migrate_to_postgres.py`, per `doc/data-migration-design.md` (see its implementation notes). First rehearsal done: explo-dev bulk (19k entities, 0.7 min, verify clean) + delta passes into the `explo_dev` ICU-`und` database on the staging cluster. **Staging serves it live since 2026-08-18** (`DATABASE_BACKEND=postgresql`), and the migrated data passed full verification the same day (api_e2e + replay harness + decode sweep — see Phase D step 3). Remaining: the explo-live and netskrafl rehearsals (resize cluster first). |
| Managed PostgreSQL cluster | ✅ **Provisioned (2026-08-14)**: `db-postgresql-ams3-netskrafl-staging` (PG 18, ams3, `db-s-1vcpu-2gb`, 1 node). App database `netskrafl` created from `template0` with `LOCALE_PROVIDER icu ICU_LOCALE 'und'`, owner `netskrafl_app`; per-locale ICU collations (`is-x-icu` et al.) verified. Trusted sources: the dev box and the DO staging app. **Resize before the full netskrafl rehearsal** (~40 GB of entity data vs. this plan's disk). |
| Managed Valkey | ✅ **Done (2026-08-12): reusing Miðeind's existing shared clusters** `db-redis-gsapi-staging` and `db-redis-gsapi-prod` (Valkey 8, ams3). Tenant separation via *logical databases* selected with a `/N` URL suffix (verified: URL-based selection, `SELECT`, and `FLUSHDB` scoping all work). Assignment: db 0 = gsapi; staging db 1 = explo-dev; prod db 1 = netskrafl, prod db 2 = explo-live. `cache.py`'s `flush()` deletes only the app's own key patterns (no `FLUSHDB`), so `/cacheflush` is shared-tenant-safe even within one logical database. The staging app is attached and smoke-tested (entity cache + presence sets live in db 1; gsapi's db 0 untouched). |
| Scheduled jobs on DO | ✅ **Running (2026-08-12)**: `CRON_SECRET` set, supercronic runs `/connect/update` every 2 min (verified end-to-end into Valkey db 1). The daily `/stats/run`/`/stats/ratings` lines are deliberately **commented out in `crontab`** while GAE cron still runs them for the same project; re-enable when the container is the sole scheduler. (Fixed along the way: the Dockerfile only installed supercronic when a `CRON_SECRET` build ARG was set, which DO never supplies — now installed unconditionally, runtime-gated.) |
| GoSkrafl on DO | **Implemented (2026-08-13)** as a loopback sidecar (see the GoSkrafl section above): Dockerfile stage builds the pinned GoSkrafl binary, `docker-entrypoint.sh` runs it when `MOVES_SIDECAR_PORT` is set, and the authenticated Flask `/moves` route + `riddle.py` forward to `MOVES_SERVICE_URL` (loopback when the sidecar is on, GAE service otherwise — `src/movesservice.py`). `/wordcheck` deliberately stays local: behind Flask, a local DAWG lookup beats a loopback hop. `/bestmoves` delegates its move generation to the sidecar **when one is local** (`MOVES_SIDECAR` in `config.py`); on GAE the in-process Python engine keeps running unchanged — same source, environment-selected. Engine equivalence is tested (`test_best_moves_equivalence`: identical move sets and scores; empty-board first moves may differ in orientation label only). Verified end-to-end against both a local sidecar and the GAE service (`test/test_moves.py`). Remaining: the trailing `explo-front` release, then the multi-month GAE drain. |
| Firebase RTDB / FCM | **Retained Google dependency** (realtime push, presence, notifications, custom auth tokens), no abstraction layer. Posture: "hosted anywhere, still dependent on Google for Firebase." |
| Production state | All three projects run NDB on GAE; `DATABASE_BACKEND` has never been set anywhere in production. |

---

## Resolved Blind Spots (compressed record)

Thirteen blind spots were identified when this document was first written;
all but data migration (#2, still open — see the table above) are resolved
or moot. Summary, with the operational notes that still matter:

1. **Schema migrations** — Alembic adopted; initial revision verified
   drift-free with a working downgrade path. *Operational note:* a database
   whose schema predates Alembic (created via `create_all()`) needs a
   one-time `alembic stamp head`.
2. **Container cron auth** — unified in `basics.cron_request_source()`
   (GAE headers, `X-Cron-Secret`, local dev) for `/stats/run`,
   `/stats/ratings`, `/cacheflush`.
3. **Gunicorn timeout vs. stats jobs** — externally scheduled stats jobs
   dispatch asynchronously (background thread), as under Cloud Scheduler.
4. **Secrets** — `SECRETS_PROVIDER=env` selects `EnvSecretProvider`
   (`<SECRET_ID>` or `<SECRET_ID>_BASE64` env vars); GCP Secret Manager
   remains the default.
5. **PG independence** — with `DATABASE_BACKEND=postgresql`, importing
   `skrafldb` loads neither `skrafldb_ndb` nor `google.cloud.ndb` (the
   packages can be dropped from the PG container in Phase F).
6. **PG gaps found by testing** — `ChatModel.delete_for_user()`,
   `EloModel.put_multi()`, NDB-style `Model.query()` translation
   (`FacadeQuery`), and a real `Client.get_context()` session scope for
   background threads (was silently losing writes). Residual facade stubs
   now raise `NotImplementedError` instead of returning empty results.
7. **Concurrency** — PG `submit_move` path serializes on
   `SELECT ... FOR UPDATE` of the game row; the GAE-era Python thread
   locks were removed after deadlock/concurrency testing (PR #153).
8. **Index parity** — `index.yaml` composites mirrored in the PG models
   and included in the initial Alembic revision, plus a query-driven audit
   of every filter/sort column (which caught `zombies.user_id`).
9. **Static file serving** — nginx `/static/` block in
   `docker-compose.yml` (1-day expiry, matching GAE); on App Platform a
   CDN in front is the equivalent at scale. Root-level static files stay
   with Flask deliberately.
10. **DAWG list derivation** — the Dockerfile derives the download list
    from `src/wordbase.py:_ALL_DAWGS` at build time via
    `utils/list_dawgs.py` (a real file, not a heredoc — kaniko silently
    discards heredoc bodies).
11. **Cloud Tasks backfill chaining** — moot; the ratings backfill has
    been completed in production and no comparable operation is expected.

### Standing decisions

- **Admin operations stay on a locally started instance** connected to the
  production database (routes gated on `running_local`; unregistered routes
  beat any auth check). DO managed PG is reachable locally via IP allowlist
  over TLS or an SSH tunnel; the PG backend has no Redis entity cache, so
  the old cache-incoherency snag disappears; derived Redis state can be
  invalidated remotely via `/cacheflush` with `X-Cron-Secret`. The admin
  routes and deferred admin jobs are e2e-tested on PG
  (`tests/api_e2e/test_admin.py`).
- **Locale-strict collation is deferred post-cutover.** The database
  default is neutral ICU root (`und`); per-locale ICU collations are
  available per query/index. Which server-side-sorted endpoints adopt them
  is a product-visible decision — see the collation note in `CLAUDE.md`.
- **Dual-write is not planned.** Given the test coverage, a
  maintenance-window cutover is simpler and safer.

---

## Migration Plan

### Phase A — Container-mode blockers — ✅ DONE (PR #152)

### Phase B — Alembic and deployable topology — ✅ DONE (PR #152)

Verified at merge: `tests/db/` 315 passed (`--backend=both`),
`tests/api_e2e/` 125 passed, `test/` 49 passed, pyright clean.

### Phase C — Hosting track: production-shaped staging on DO (IN PROGRESS)

Goal: the staging app exercises *everything except the database change*, so
hosting problems surface with zero data-migration risk. Rollback is DNS.

1. **Keep `do-deploy` current.** The staging app deploys from the
   `do-deploy` branch; after merging it back to master (done 2026-08-12),
   fast-forward `do-deploy` to master whenever staging should pick up new
   work. (Longer term, once staging graduates to production, the app should
   track master directly.)
2. ✅ **Shared Valkey attached** (2026-08-12): `REDIS_URL` → staging
   cluster, logical db 1; `health_check` on `/health/ready` enabled and
   gating deployments. See the Redis/Valkey notes in `.do/app.yaml`.
3. ✅ **Scheduled jobs on** (2026-08-12): supercronic verified end-to-end
   with `/connect/update`; daily stats jobs deliberately deferred until
   the container is the sole scheduler for its project.
4. **GoSkrafl sidecar** (parallel-friendly, decided 2026-08-13 — see the
   GoSkrafl section above for the architecture):
   - Add a build stage to the Netskrafl `Dockerfile` compiling the
     GoSkrafl server binary (pinned version/commit; kaniko-safe), and
     start it on `127.0.0.1` from `docker-entrypoint.sh`.
   - Add authenticated Flask routes for `/moves` and `/riddle`, and route
     the existing `/wordcheck` through the same forwarding path; the
     forward target is a configurable URL (external GAE service today,
     loopback sidecar in the container), replacing the hardcoded
     `RIDDLE_ENDPOINT_*` constants in `src/riddle.py`.
   - Plan the trailing `explo-front` release: `/moves`/`/wordcheck` move
     to the main API host with session auth; the GAE `moves` service
     stays up until its direct traffic drains (several months).
5. **Production-parity sizing**: move to an instance size with ≥2 GB RAM
   (GAE `B4_1G` equivalent) before drawing any load-testing conclusions;
   then load-test against staging.
6. ✅ **Staging secrets on env vars** (2026-08-14), per resolved Open
   Decision 1: `SECRETS_PROVIDER=env` with `SECRET_KEY_BIN_BASE64`,
   `MOVES_AUTH_KEY` and `CLIENT_SECRET_EXPLO_BASE64` as encrypted env vars
   in the app spec — the runtime Secret Manager dependency is gone.
   Deployed and verified (health gate passed, cron/Firebase exercised).
   `GOOGLE_CREDENTIALS_BASE64` stays regardless (Firebase Admin SDK).

### Phase D — Database track: provision, migrate, rehearse

1. ✅ **Provision managed PostgreSQL** (2026-08-14) — see the table above
   (`db-postgresql-ams3-netskrafl-staging`, PG 18, ICU `und` app database,
   trusted-sources allowlist covering the dev box and the staging app).
2. ✅ **`scripts/migrate_to_postgres.py`** — designed and implemented
   2026-08-14, see **`doc/data-migration-design.md`** (REST reader with
   sharded key ranges, NDB-layer decoding, bulk+delta phases,
   checkpoint/resume in a `_migration_state` table; supersedes the
   `postgresql-plan.md` sketch). Verified end-to-end with the explo-dev
   rehearsal. Runs outside the container image (`scripts/` is ignored).
3. ✅ **Verification against migrated data** (2026-08-18), run on a local
   `pg_dump` copy of the staging `explo_dev` database so the live data
   stays untouched:
   - `tests/api_e2e/`: 125 passed against the migrated copy (with the
     new `E2E_KEEP_TABLES=1` conftest flag that skips the table reset),
     identical to the clean-database baseline run the same day.
   - **Replay harness**: all 105 production-game fixtures replayed
     exactly against the migrated copy.
   - **Full decode sweep** (every migrated row through the real app
     loaders): 632/632 users, 2,416/2,419 games clean. The three
     exceptions are source-data quirks, not migration defects: one
     synthetic test entity (`test-moves-game-001`) left behind in
     explo-dev NDB, and two experimental `es_ES` games (Feb 2026) that
     `Game.load` declines identically on the NDB backend
     (parity-verified) because the locale is unsupported.
4. **Rehearse** against a production Datastore export into a staging PG
   database. Measure wall-clock time — this bounds the cutover window.
   (Remaining: explo-live, then netskrafl — resize the cluster first.)
5. ✅ **Deploy the PG backend to staging** (2026-08-18): the app runs
   `DATABASE_BACKEND=postgresql` with a `${pg.DATABASE_URL}` binding to
   the migrated `explo_dev` database — the first App-Platform deployment
   of the PG path, and the convergence point of the two tracks. Health
   gate green; nightly `/stats/run` + `/stats/ratings` cron enabled on
   the container (see the crontab), doubling as a recurring PG exercise.

### Phase E — Cutover, per project, smallest first

Order: **explo-dev → explo-live → netskrafl.**

1. Brief write freeze; final migration + verification (Phase D tooling).
2. Flip `DATABASE_BACKEND=postgresql`; monitor.
3. Move DNS/domains to the DO app. GoSkrafl needs no per-cutover URL
   switch under the sidecar architecture — the container serves
   `/moves`/`/wordcheck`/`/riddle` itself; only the trailing
   `explo-front` release (Phase C step 4) changes client behavior.
4. Keep NDB warm for a ~30-day rollback window. Rollback after real writes
   means data loss back to the freeze point, so the Phase D verification
   gate matters.

### Phase F — Cleanup

1. Delete `skrafldb_ndb.py`, `src/db/ndb/`, and the Google Datastore
   dependencies; fold `requirements-pg.txt` into `requirements.txt`.
2. Retire `cron.yaml`, `index.yaml`, `dispatch.yaml`, `app-*.yaml` and the
   GAE deploy tooling once GAE is decommissioned. GoSkrafl's GAE `moves`
   services and `go-app/` deploy tooling are retired **later and
   separately**: only after direct-client traffic to the hardcoded
   appspot.com URLs has drained (several months after the `explo-front`
   release that switches clients to the main API host — monitor the GAE
   service's request logs).
3. Delete the remaining Cloud Scheduler jobs (`Clear-Redis` on netskrafl,
   `clear-cache` on explo-dev) or replace them with supercronic entries.

---

## Open Decisions

1. **GCP for secrets and Firebase — ✅ RESOLVED (2026-08-14):**
   - **Secrets move to environment variables** on DO: set
     `SECRETS_PROVIDER=env` and supply `SECRET_KEY_BIN_BASE64`,
     `MOVES_AUTH_KEY` and the project's `CLIENT_SECRET_*` JSON as encrypted
     env vars in the app spec. The code side is already done — the
     `SecretProvider` ABC in `src/secret_manager.py` with
     `EnvSecretProvider` (`<SECRET_ID>` or `<SECRET_ID>_BASE64`).
   - **Firebase is retained** (presence, realtime push, FCM, custom auth
     tokens) and is used from the DO container. Its client-side config
     values travel inside the `CLIENT_SECRET_*` JSON, and the Firebase
     Admin SDK authenticates via the Google service-account credential
     (`GOOGLE_CREDENTIALS_BASE64`) — so that credential stays in the
     container even once Secret Manager is no longer consulted. A Firebase
     replacement, if ever, is a separate follow-on project.
2. **Riddle endpoint for production netskrafl** — it currently uses the
   explo-dev `moves` service (TODO in `src/riddle.py`). The GoSkrafl port
   is the natural moment to decide which instance each project should use.
3. **Locale-strict collation rollout** — deferred post-cutover (see
   Standing decisions).
