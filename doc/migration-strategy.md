# Migration Strategy: GAE + NDB → DO Containers + PostgreSQL

*Status as of 2026-11-10. The history of the earlier phases (containerization,
the PostgreSQL backend, the parity audit, the blind-spot review) is in the
git history of this file; only the decisions and notes that still matter are
kept here. Related documents: `data-migration-design.md` (the Datastore →
PostgreSQL migrator and its rehearsals), `client-switchover-plan.md` (moving
the Explo app clients to the new hosts), `rtdb-eu-move.md` (the Firebase
Realtime Database move to the EU).*

## Goal

Move Netskrafl and Explo off Google App Engine and Cloud Datastore (NDB) onto
Digital Ocean: the containerized Flask app on App Platform, managed
PostgreSQL, managed Valkey (Redis-compatible) for caching, supercronic for
scheduled jobs, and the GoSkrafl engine as a sidecar process in the same
container. Firebase (Realtime Database, Cloud Messaging, custom auth tokens)
stays with Google. The total running cost on DO should be well below the
current Google Cloud cost.

## Order of the cutovers

1. **explo-dev — done.** The Explo development backend has run on the DO
   staging app with the PostgreSQL backend since 2026-08-18.
2. **netskrafl — next** (decided 2026-11-06). Its only real client is
   Málstaður, which embeds the Netskrafl web client and talks to the backend
   through a single hostname; the original web UI is used only for testing by
   the development team. That makes it the simpler production cutover, with
   no app-store client to drain.
3. **explo-live — after netskrafl.** It needs the client switchover (app
   releases with configurable endpoints, then a long drain of old app
   versions); see `client-switchover-plan.md`.

Each production project gets its own PostgreSQL cluster. For netskrafl the
hosting and the database must flip together: the DO app runs in Europe, and
reaching the US-hosted netskrafl Datastore from there would add a
transatlantic round trip to every database call.

## Where we stand

| Area | Status |
|------|--------|
| Container | Done and running in staging: multi-stage `Dockerfile` (kaniko-compatible, see the build gotcha in `CLAUDE.md`), health endpoints, supercronic, GoSkrafl sidecar. |
| PostgreSQL backend | Done. All repositories implemented on both backends behind typed protocols (`src/db/protocols.py`); Alembic owns the schema; parity is maintained as features land. |
| Tests | `tests/db` (both backends), `tests/api_e2e` (the real Flask app on PostgreSQL), `test/` (legacy suite, including the engine-equivalence tests against GoSkrafl), the replay harness (95 sampled production games replayed move by move, `-m slow`) and the concurrency tests. |
| Data migrator | Done: `scripts/migrate_to_postgres.py`, bulk and delta modes, idempotent, resumable. Design and rehearsal results in `data-migration-design.md`. |
| netskrafl database | Production PostgreSQL cluster provisioned 2026-11-06 (single node, 2 vCPU, 4 GB RAM, 60 GiB). Holds the rehearsal copy, verified clean (below). |
| netskrafl app on DO | **Not yet created.** Next step. |
| Valkey | Miðeind's shared staging and production Valkey clusters, one logical database per tenant (`/N` URL suffix); `cache.py`'s `flush()` deletes only the app's own key patterns, so it is safe on a shared database. |
| Firebase RTDB | Netskrafl's Realtime Database moved to an EU instance on 2026-11-04 (`rtdb-eu-move.md`); a nightly cleanup job (`/connect/cleanup`) keeps it from growing without limit. It stays in use after the migration. |
| GoSkrafl | Runs as a loopback sidecar in the container, built from a pinned commit (`GOSKRAFL_COMMIT` in the `Dockerfile`). The App Engine `moves` services on explo-dev and explo-live keep running until their direct traffic is gone (below). |
| Production today | netskrafl and explo-live run on App Engine with Datastore. |

### The netskrafl rehearsal (2026-11-07 and 2026-11-09)

A full bulk copy of the netskrafl Datastore (10.4M games, 3.7M chats, 3.6M
stats rows, 52k users) into the production cluster took **238 minutes**,
during the night, with a watchdog that would have stopped the copy if App
Engine production degraded; production was unaffected. A delta pass two days
later took **7.5 minutes**, which bounds the write freeze at cutover. The copy
passed every verification layer: field-level spot checks against Datastore,
the API end-to-end tests and the replay harness on a local copy of the
database, and a decode sweep that loaded all 52k users and 10.4M games
through the app's own loaders without a single failure. Details in
`data-migration-design.md`.

## Plan ahead: the netskrafl cutover

### 1. A production-shaped netskrafl app on DO

The reference spec is `.do/app-netskrafl.yaml` (placeholders only).

- `PROJECT_ID=netskrafl`, `DATABASE_BACKEND=postgresql` against the production
  cluster (the app is added to the cluster's trusted sources), the production
  Valkey database for netskrafl, the GoSkrafl sidecar on
  (`MOVES_SIDECAR_PORT`), secrets as encrypted environment variables
  (`SECRETS_PROVIDER=env`, values equal to the current ones so that sessions
  and tokens survive the switch).
- **One instance**, sized generously at first (App Engine serves production
  with two 2 GB instances that use about 300 MB each) and lowered once
  metrics are in. The app cannot scale out as it is: supercronic runs in
  every container, so two instances would run every scheduled job twice.
- **Scheduled jobs off** until the cutover (`CRON_SECRET` unset): App Engine
  cron still runs the same jobs against Datastore. A stats run on DO for a
  day that App Engine also processes would leave two sets of stats rows for
  that day once the delta pass copies App Engine's over.
- **No custom domain** until the cutover; the app is reached at its default
  hostname.
- Test against the rehearsal copy with **test accounts only**: Málstaður
  login, the legacy Google login, game play against humans and robots, Gáta
  dagsins. The app shares the live Firebase Realtime Database with
  production, so it must not touch real users' games.

### 2. Before the switch

- **Riddle generation.** GoSkrafl's riddle generator writes Gáta dagsins
  riddles straight into the Datastore. The current stock lasts until
  mid-January 2027; before that, generation must target PostgreSQL (or an
  importer must carry riddles over).
- **The robot engine (done, 2026-11-10).** On DO, robots take their
  candidate moves from the sidecar (about 0.1 s per move even with two
  blanks on the rack), with the in-process Python engine as the fallback;
  on App Engine they keep using the Python engine, where a rack with two
  blanks takes a few seconds. The Python engine now produces the same moves
  as GoSkrafl, and every move request carries the game's tile set. Deployed
  to both App Engine production apps and the DO staging app; all GoSkrafl
  instances (the App Engine `moves` services and the sidecar) run the same
  commit.
- **Other hostnames.** Besides the main backend hostname, which is the one
  that flips, App Engine still answers on its own default hostnames (cron,
  a few legacy logins, an uptime check). Those need a redirect or retirement
  plan and a replacement uptime check on the DO app.
- **A cutover runbook**, with the operational specifics kept in private
  notes and a trimmed version here.

### 3. The switch

1. **The copy.** The rehearsal copy is the starting point: nothing has
   written to it since its delta pass, and a delta pass sees every change
   made on App Engine (games are only written when created or moved in,
   which moves `ts_last_move`, and by the nightly stats job; chats and stats
   rows are never edited; users and the small kinds are re-read in full).
   So anything written through the DO app before the switch stays in the
   production data: test with the team's own accounts only. A catch-up
   delta pass the day before keeps the final one short. (The alternative, a
   fresh `--truncate` bulk copy a day or two before the switch, costs a
   night and wipes any test residue.)
2. **Write freeze** on App Engine: all traffic is routed to a version built
   with the `MAINTENANCE` environment variable set, which answers every
   request with HTTP 503 (`src/maintenance.py`; the web client treats that
   as "server unreachable" and offers a retry). Then a **delta pass** with
   `--since` the start of the previous pass minus 2 days (the nightly stats job writes Elo results into
   games without moving `ts_last_move`, so a generous overlap is needed;
   upserts make it harmless). About 8 minutes, as rehearsed.
   Run this delta pass without the watchdog: it stops the migrator when
   App Engine returns errors, which is all App Engine does while frozen.
   Afterwards, compare row counts per table with Datastore.
3. **Flip the backend hostname.** The order matters, because App Platform
   can only obtain the certificate for the hostname once its DNS record
   points at the app, and clients get a TLS error until it has one:
   - point the DNS record at the DO app right after the freeze (lower its
     TTL to 60 seconds some days ahead), so the change propagates while the
     delta pass runs;
   - when the data is copied and checked (through the app's default
     hostname), enable the scheduled jobs, flush the cache and add the
     hostname to the app as its domain; the certificate follows within
     minutes;
   - remove the jobs from App Engine cron.

   Until the certificate is issued no user can have reached the new
   backend, so everything up to that point can be abandoned without loss:
   point the DNS record back and route traffic back to the serving version.
4. **Monitor**, with App Engine and the Datastore kept intact (read-only)
   for a rollback window of about 30 days. A rollback after real writes on
   PostgreSQL loses those writes, which is why the verification gate before
   the switch matters.

### 4. After netskrafl

- **explo-live**: production app, client switchover and drain per
  `client-switchover-plan.md`, a fresh rehearsal with the same tooling,
  then the same switch sequence. (The staging copy of explo-live from the
  September rehearsal is one Alembic revision behind; refresh or upgrade it
  before reuse.)
- **Málstaður's word checks** go straight to the explo-dev App Engine
  `moves` service; repointing them at a DO host is needed before that
  service can be retired.
- **Cleanup** (once App Engine is no longer serving a project): delete
  `skrafldb_ndb.py`, `src/db/ndb/` and the Datastore dependencies; fold
  `requirements-pg.txt` into `requirements.txt`; retire `cron.yaml`,
  `index.yaml`, `dispatch.yaml`, `app-*.yaml` and the GAE deploy tooling;
  delete or replace the remaining Cloud Scheduler jobs. GoSkrafl's App
  Engine `moves` services go last, when their request logs show that old
  Explo app versions no longer call them directly (several months after the
  client switchover).

## Decisions that still apply

- **GoSkrafl as a loopback sidecar** (2026-08-13). It runs as a second
  process in the Netskrafl container, bound to `127.0.0.1` and supervised by
  `docker-entrypoint.sh`. Flask owns the public routes and forwards to it
  (`src/movesservice.py`; the target is `MOVES_SERVICE_URL`, the sidecar when
  `MOVES_SIDECAR_PORT` is set, otherwise the App Engine service). The
  sidecar keeps process isolation (a Go crash restarts one process, slow
  riddle generation stays out of the web workers) and loads its
  dictionaries once for all workers. `/wordcheck` stays local in Flask.
  Changes reach the container by bumping the pinned commit in a Netskrafl PR.
- **Secrets as environment variables** on DO (`SECRETS_PROVIDER=env`,
  `<SECRET_ID>` or `<SECRET_ID>_BASE64`); the Google service-account
  credential stays in the container for the Firebase Admin SDK.
- **No dual writes.** A short write freeze and a delta pass are simpler and
  safer, given the test coverage.
- **Admin operations** run on a locally started instance connected to the
  production database (routes gated on `running_local`).
- **Locale-strict collation is deferred** until after the cutovers; the
  database default is the neutral ICU root collation (see `CLAUDE.md`).
- **App Platform, not serverless.** A long-lived gunicorn process with a
  large dictionary warm-up, in-container cron and long batch jobs is a poor
  fit for serverless hosting.

## Operational notes

- A database whose schema predates Alembic needs a one-time
  `alembic stamp head`; `docker-entrypoint.sh` runs `alembic upgrade head`
  in PostgreSQL mode.
- Scheduled-job requests are authenticated by `basics.cron_request_source()`
  (App Engine headers, `X-Cron-Secret`, local development); jobs triggered
  from outside App Engine run asynchronously.
- The staging app deploys from the `do-deploy` branch, a merge-commit
  branch: merge master into it to deploy. Edit its spec by round-tripping
  `doctl apps spec get` → edit → `doctl apps update`; `.do/app.yaml` is a
  reference copy with placeholders and must never be applied as is.
- Release tags: every production deploy is tagged with its App Engine
  version name (see `CLAUDE.md`); the DO apps should follow the same rule.

## Open items

1. **Riddle generation into PostgreSQL** (deadline: mid-January 2027).
2. **Locale-strict collation** (deferred, see above).
3. **A score-bounded search** (generating only moves that can reach the top
   of the candidate list) would speed up robots without a sidecar. Not
   planned while the sidecar covers DO.
