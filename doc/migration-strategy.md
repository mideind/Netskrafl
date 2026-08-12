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
- **The Explo mobile client** (`explo-front`) calls `/moves` directly,
  configured via `movesApiUrl` / `movesAccessKey` in its Expo config, with
  CORS handled by the service (`ALLOWED_ORIGINS`).

Porting needs: GoSkrafl has **no Dockerfile** and no DO deployment. The
service is a good container citizen (static Go binary + embedded DAWGs,
`PORT` env, bearer-token auth via `ACCESS_KEY` env) — containerizing it is
straightforward. The consuming side needs the endpoint URLs made
configurable (env var in `src/riddle.py`; Expo config change in
`explo-front` at cutover).

### Missing or not yet done

| Area | State |
|------|-------|
| Data migration (Datastore→PG) | **Absent** — `scripts/migrate_to_postgres.py` was never written; there is no `scripts/` directory. Note `.dockerignore`/`.gcloudignore` exclude `utils/`, so migration tooling runs outside the image. |
| Managed PostgreSQL cluster | **Not provisioned.** Must be PG 15+ and created with the neutral ICU root collation (`und`) — see the collation note in `CLAUDE.md`. |
| Managed Valkey | **Decision made (2026-08-12): reuse Miðeind's existing shared clusters** `db-redis-gsapi-staging` and `db-redis-gsapi-prod` (Valkey 8, ams3) instead of provisioning new ones. Tenant separation via *logical databases* selected with a `/N` URL suffix — verified working on the staging cluster (URL-based selection, `SELECT`, and `FLUSHDB` scoped to the selected database). Assignment: db 0 = gsapi; staging db 1 = explo-dev; prod db 1 = netskrafl, prod db 2 = explo-live. `cache.py`'s `flush()` additionally deletes only the app's own key patterns (no `FLUSHDB`), so `/cacheflush` is shared-tenant-safe even within one logical database. Remaining: attach to the staging app and smoke-test. |
| Scheduled jobs on DO | **Off** (`CRON_SECRET` unset). The `crontab` + supercronic + `X-Cron-Secret` machinery is ready and e2e-tested. |
| GoSkrafl on DO | **Not started** (no Dockerfile; hardcoded consumer URLs). |
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
2. **Point the app at the shared Valkey** (`db-redis-gsapi-staging`,
   logical db 1): set `REDIS_URL` to the cluster URI with a `/1` suffix
   (an attached-database binding would yield db 0, so the URL is explicit),
   make sure the app is in the cluster's trusted sources, then enable the
   `health_check` on `/health/ready`. See the Redis/Valkey notes in
   `.do/app.yaml`.
3. **Enable scheduled jobs**: set `CRON_SECRET`, verify supercronic runs
   `/connect/update` (every 2 min) and the nightly `/stats/run` +
   `/stats/ratings` against explo-dev. (These write real aggregate data to
   the explo-dev project — that is the point, but never point staging at a
   production project.)
4. **Port GoSkrafl** (parallel-friendly, independent of everything else):
   - Add a Dockerfile to `../GoSkrafl` (multi-stage Go build; `PORT`,
     `ACCESS_KEY`, `ALLOWED_ORIGINS` env vars already supported). Mind the
     kaniko heredoc gotcha.
   - Deploy it as a second service/component on App Platform.
   - Make the consumer URLs configurable: replace the hardcoded
     `RIDDLE_ENDPOINT_*` appspot URLs in `src/riddle.py` with
     project-aware config/env; plan the `movesApiUrl` change in
     `explo-front` for cutover.
5. **Production-parity sizing**: move to an instance size with ≥2 GB RAM
   (GAE `B4_1G` equivalent) before drawing any load-testing conclusions;
   then load-test against staging.

### Phase D — Database track: provision, migrate, rehearse

1. **Provision managed PostgreSQL** (15+, ICU `und` collation on the app
   database — DO's stock `defaultdb` does not qualify), private VPC,
   trusted-sources allowlist for local admin access.
2. **Write `scripts/migrate_to_postgres.py`** per `postgresql-plan.md`:
   batched, UTC-preserving, moves→JSONB, UUID strings preserved as-is.
   Runs outside the container image (`utils/` is dockerignored).
3. **Write the verification tooling**: entity counts and row samples per
   table, plus — the strongest instrument we now have — run the
   **replay harness** and `tests/api_e2e/` against a database populated by
   a real migration.
4. **Rehearse** against a production Datastore export into a staging PG
   database. Measure wall-clock time — this bounds the cutover window.
5. **Deploy the PG backend to staging** (`DATABASE_BACKEND=postgresql` +
   `DATABASE_URL` binding) against the rehearsal database — the first
   App-Platform deployment of the PG path, and the convergence point of
   the two tracks.

### Phase E — Cutover, per project, smallest first

Order: **explo-dev → explo-live → netskrafl.**

1. Brief write freeze; final migration + verification (Phase D tooling).
2. Flip `DATABASE_BACKEND=postgresql`; monitor.
3. Move DNS/domains to the DO app; switch GoSkrafl consumer URLs
   (`src/riddle.py` config, `explo-front` release for `movesApiUrl`).
4. Keep NDB warm for a ~30-day rollback window. Rollback after real writes
   means data loss back to the freeze point, so the Phase D verification
   gate matters.

### Phase F — Cleanup

1. Delete `skrafldb_ndb.py`, `src/db/ndb/`, and the Google Datastore
   dependencies; fold `requirements-pg.txt` into `requirements.txt`.
2. Retire `cron.yaml`, `index.yaml`, `dispatch.yaml`, `app-*.yaml` and the
   GAE deploy tooling once GAE is decommissioned; likewise GoSkrafl's
   `go-app/app.yaml` + deploy scripts and the GAE `moves` services.
3. Delete the remaining Cloud Scheduler jobs (`Clear-Redis` on netskrafl,
   `clear-cache` on explo-dev) or replace them with supercronic entries.

---

## Open Decisions

1. **Is GCP-for-secrets-and-Firebase acceptable long-term?**
   - If **yes**: the plan above is mostly mechanical from here.
   - If **no**: still execute the plan unchanged; a Firebase replacement
     (presence, realtime push, FCM, custom auth tokens, plus `explo-front`
     client changes) is a separate follow-on project. Env-var secrets are
     already done (`SECRETS_PROVIDER=env`).
2. **Riddle endpoint for production netskrafl** — it currently uses the
   explo-dev `moves` service (TODO in `src/riddle.py`). The GoSkrafl port
   is the natural moment to decide which instance each project should use.
3. **Locale-strict collation rollout** — deferred post-cutover (see
   Standing decisions).
