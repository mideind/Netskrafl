# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## This repository is public

Everything committed here (docs, this file, comments, commit messages, PR descriptions) is
world-readable. Describe procedures and decisions, but keep low-level operational details
out: concrete URLs and hostnames of infrastructure, deployment names, account emails, user
and account IDs, secret names and versions, service accounts, IP addresses, key IDs and
dashboard paths. Write "the EU database instance" or "the previous App Engine version"
instead, and keep the specifics in private notes.

## Project Overview

Netskrafl is the backend server of an Icelandic crossword game, built with:
- **Backend**: Python 3.11 + Flask, run by gunicorn in a container
- **Frontend**: the players' clients live in other repositories (see below); this
  one keeps a single-page TypeScript web client as a development client
- **Database**: PostgreSQL (SQLAlchemy 2.0, Alembic). The original Google Cloud
  Datastore (NDB) backend is still in the code and is what runs when
  `DATABASE_BACKEND` is not set, but no deployment uses it
- **Real-time**: Firebase (Realtime Database, Cloud Messaging), on Google Cloud
- **Build System**: Grunt for TypeScript/JavaScript/CSS compilation
- **Testing**: pytest framework

It supports (1) Netskrafl, a web-based game currently offered in Icelandic only,
and (2) is the backend for Explo, a multilingual mobile app client
(React Native app, in a separate repository).

Since November 2026 all three deployments (Netskrafl production, Explo
production, and the Explo development backend, which is also the staging app)
run as containers on Digital Ocean App Platform with managed PostgreSQL. How
they run, what is left on Google Cloud and what is still to do is in
`doc/operations.md`; what the move taught us is in `doc/migration-2026.md`.

## Common Development Commands

### Development Setup
```bash
# Create the venv (CPython 3.11, as in the container image) and install
# everything: runtime deps (requirements.txt), PostgreSQL backend deps
# (requirements-pg.txt, which includes the former and is what the image
# gets) and dev tooling (icegrams, pytest, pyright, type stubs). There is no
# pyproject.toml: the layered requirements files are the single source of
# truth.
uv venv --python 3.11 venv
uv pip install --python venv/bin/python -r requirements-dev.txt

# Install Node.js dependencies
npm install

# Generate DAWG vocabulary files (takes a few minutes)
python utils/dawgbuilder.py all

# Build frontend assets
grunt make

# Start development server (explo-dev configuration; on the NDB backend
# unless DATABASE_BACKEND=postgresql and DATABASE_URL are set)
./runserver.sh  # or runserver.bat on Windows

# Watch for file changes during development
grunt  # runs grunt watch by default
```

### Testing

Tests require Google Cloud credentials (for Firebase and, on the NDB backend,
Datastore) and environment variables. The suites and what each one shows are
described in `doc/testing.md`. Use the explo-dev configuration:

```bash
# Run tests for explo-dev (multi-locale, full test coverage)
PROJECT_ID=explo-dev \
GOOGLE_APPLICATION_CREDENTIALS="credentials/explo-dev/service-account.json" \
GOOGLE_CLOUD_PROJECT=explo-dev \
RUNNING_LOCAL=true \
REDISHOST=127.0.0.1 \
REDISPORT=6379 \
SINGLE_PAGE=TRUE \
venv/bin/pytest test/ -v

# Run specific test file
venv/bin/pytest test/test_elo.py

# Repository tests on both backends, and the end-to-end API tests on the
# PostgreSQL backend (same environment variables as above; both use the local
# throwaway database postgresql://test:test@localhost:5432/netskrafl_test,
# override with DATABASE_URL)
venv/bin/pytest tests/db --backend=both --import-mode=importlib
venv/bin/pytest tests/api_e2e

# Type checking with pyright (preferred)
venv/bin/pyright src/

```

Note: Always test with the explo-dev configuration. It supports all locales, and it is
the only one that is safe: with a production project's configuration, test games would
send notifications to that product's production Realtime Database and, on the NDB
backend, write into its Datastore, which is kept as the archive of the data before the
move. `FIREBASE_DB_URL` does not need to be set: it is read from the project's client
secret at startup.
The `test/` suite runs on the backend that `DATABASE_BACKEND` selects, which
without it is NDB, i.e. the project's Datastore.
If port 8080 is taken on the machine, add `SERVER_PORT=<free port>`: with
`RUNNING_LOCAL=true` the app checks that its port is free at import time.

## Architecture Overview

### Backend Structure (src/)
- **main.py**: Flask app entry point and configuration
- **web.py**: the web routes: the built-in web UI and the login sequences
- **api.py**: JSON API endpoints for client communication
- **skraflgame.py**: Core Game class and game state management
- **skrafluser.py**: User class and user management
- **skraflmechanics.py**: Game mechanics and move validation
- **skraflplayer.py**: Robot player AI implementation using Appel & Jacobson algorithm
- **dawgdictionary.py**: DAWG (Directed Acyclic Word Graph) navigation for word validation
- **languages.py**: Language-specific tile sets, bags, and vocabularies
- **skrafldb.py**: The persistence facade that application code imports; it
  selects `skrafldb_pg.py` (PostgreSQL) or `skrafldb_ndb.py` (Datastore) by
  `DATABASE_BACKEND`
- **db/**: The database layer: typed protocols (`protocols.py`), the
  PostgreSQL repositories and ORM models (`postgresql/`), the NDB adapter
  (`ndb/`), and the request-scoped session (`session.py`). The schema is
  owned by Alembic (`migrations/`)
- **auth.py/authmanager.py**: Authentication and user session management
- **secret_manager.py**: Secrets, from environment variables (deployments) or
  Google Secret Manager (local servers)
- **movesservice.py**: Forwarding to the GoSkrafl engine (a sidecar process in
  the container)
- **appversion.py**: The client configuration record (minimum app version,
  endpoint overrides) that `/inituser` hands to the Explo apps
- **applog.py**, **maintenance.py**, **rtdb_cleanup.py**: structured logging,
  maintenance mode, and the nightly Realtime Database clean-up

### Frontend Structure (static/)
- **src/**: TypeScript source files
  - **page.ts**: Main page logic and UI management
  - **game.ts**: Game board and gameplay interactions
  - **model.ts**: Data models and state management
- **lib/**: Vendored third-party JavaScript (credited in `README.md`)
- **built/**: Compiled JavaScript output (explo.js)
- **templates/**: Jinja2 HTML templates

### Key Data Files
- **resources/*.bin.dawg**: Compressed vocabulary files for different languages
- **resources/ordalisti.*.txt**: Source vocabulary lists
- **static/skrafl-*.less**: LESS stylesheets compiled to CSS

### Game Engine
The game uses a sophisticated robot player based on the classic Appel & Jacobson
"World's Fastest Scrabble Program" algorithm. The DAWG structure enables efficient
word validation and move generation. The engine is language-agnostic, supporting
multiple languages through separate DAWG files and tile sets.

## Development Notes

- The codebase supports two game variants (Netskrafl, Explo) with shared core logic
  but a few differences in the backend APIs, for instance in player authentication
- Currently, Netskrafl only supports Icelandic
- Explo supports Icelandic, English, Polish, and Norwegian (bokmål and nynorsk)
- Netskrafl is a web-based game with real-time multiplayer capabilities. Its web
  client is embedded in Málstaður and maintained there, not in this repository
- The built-in web UI (`static/src/`, `templates/page.html`) is a development
  client. It is served only where `SINGLE_PAGE=TRUE` is set: on the staging app
  and on local servers (`runserver.sh` and the compose files set it), never on
  the production apps. Without it the UI's routes answer 404 (`web_ui_route` in
  `src/web.py`), and `/` and `/greet` redirect to `HOME_REDIRECT_URL` if that is
  set (on Netskrafl: its home within Málstaður; on Explo: its website), else
  answer 404. The older server-rendered jQuery UI was removed on 2026-11-26,
  with the help pages, the admin page and the SalesCloud billing integration
  (`/billing`, `/cancelplan`): subscriptions come from Málstaður's login token
  and from RevenueCat (`/rchook`). The `url` field of the game lists keeps its
  `/board?game=…` form because clients read the game id from it (`game_url` in
  `src/logic.py`)
- Explo has a mobile app client (React Native app, in a separate repository)
  that communicates with a separate instance of the Netskrafl/Explo game server.
  A released app keeps calling the backend address that is built into it, so
  the server can tell an app to update or to use another address
  (`src/appversion.py`; the mechanism and its use are in `doc/operations.md`)
- Real-time gameplay uses WebSocket-like communication via Firebase
- Firebase notifications (and any other side effect that makes a client re-read
  the database) must be registered with `skrafldb.on_commit()` rather than sent
  directly: inside an `@transactional()` function on NDB, and anywhere in a
  request on PostgreSQL, the writes are not committed until the function or
  request returns, and a client reacting to an early notification reads the old
  state (the 2026-09-11 stale-game-list bug in the Explo app)
- Elo rating system tracks player performance; the two products store and
  show ratings differently (`doc/elo.md`)
- Logging in the container is structured: one JSON entry per line, one entry
  per request with the user's id, and entries for refusals, logins and the
  results of scheduled jobs (`src/applog.py`; the entries, their fields and
  the forwarding to the log service are described in `doc/logging.md`). Attach
  fields to a log call with `log_fields()`, and end a scheduled job with
  `log_job()`. An API refusal is answered with HTTP 200, so it is only visible
  in the log if it is noted there
- Maintenance mode: with the `MAINTENANCE` environment variable set, the server
  answers every request except the health endpoints with HTTP 503
  (`src/maintenance.py`). The clients treat a status of 500 or above as "the
  server could not be reached" and offer a retry, which a 404 does not get.
  This is how a backend is frozen during a data migration
- Game list queries on PostgreSQL (`GameRepository._newest_games_stmt`) use one
  ordered, limited branch per player column, merged; an `OR` across the two
  player columns cannot use the per-player indexes and took seconds on the
  production-size database. Check new hot queries with `EXPLAIN` at that size
- The three deployments are told apart by `PROJECT_ID`: `netskrafl`,
  `explo-live` (Explo production) and `explo-dev` (the Explo development
  backend and staging app). The code branches on it through the `NETSKRAFL`
  flag in `src/config.py`
- What still runs on App Engine is not this backend: a redirect app in the
  netskrafl project (`appspot-redirect/`), a forwarding app in explo-live for
  Explo apps that have the old address built in (`appspot-forward/`), and the
  GoSkrafl `moves` services. The `app-*.yaml`, `cron.yaml`, `index*.yaml` and
  `dispatch.yaml` files and the `default` targets of the `deploy-*.sh` scripts
  are leftovers that no deployment uses (`doc/operations.md`)
- Every production release (netskrafl or explo-live) gets a git tag named
  `nYYYYMMDD` or `eYYYYMMDD` (plus a letter for further releases on the same day),
  on the deployed commit, pushed to GitHub once the release serves all users. The
  tag equals the `APP_VERSION` label in the spec of the app's container. The
  tag is also published as a GitHub release ("Version <tag>") with release notes
  that cover everything since the previous release tag. The `/deploy` skill does
  both as its last step; tag and publish by hand after any deploy made outside it
- Deploying is done with the `/deploy` skill, and works the same way for all three
  backends: a production release goes to the staging app first
  (the `do-deploy` branch, i.e. the Explo dev backend), as a canary. There the
  standard test `utils/staging-check.py` plays through the key operations with
  test users that exist only on that backend. If the canary is clean, the same
  commit goes to production by a push to the app's deploy branch (`do-netskrafl`
  or `do-explo`); straight to production only when that is asked for explicitly.
  The canary shows that the container starts and works, not how it behaves under
  real traffic. There is no gradual rollout (the new container gets all the
  traffic once it passes its health check), so production is watched through log
  samples after the switch, with a rollback to the previous deployment kept
  ready; the skill describes what to do when a release goes wrong. A release
  that contains a schema migration cannot be rolled back that way and must be
  fixed forward
- The alerts of the production backends (`utils/datadog-setup.py`) go to a channel
  that is only for conditions that someone has to act on. Normal operation,
  deploys included, must not set them off: keep that in mind when adding or
  changing a monitor, and see `doc/logging.md`
- Vocabulary fixes must be propagated to every consumer (the CDN that the
  container build reads, GoSkrafl in its three places, and Skrafl); the
  dependency map and runbook are in `doc/dictionary-update.md`
- Still to do after the move (details in `doc/operations.md`): riddle
  generation into PostgreSQL (the Gáta dagsins stock ends 2027-01-15), moving
  the remaining Explo traffic off App Engine, removing Redis from the
  PostgreSQL backend, retiring the NDB backend

### PostgreSQL collation (a decision still open)

The PostgreSQL database uses the neutral ICU root collation (`und`) as its
default - the only coherent choice, since users of all locales share the same
tables. PostgreSQL simultaneously provides per-locale ICU collations
(`is-x-icu`, `pl-x-icu`, `nb-x-icu`, `nn-x-icu`, `ga-x-icu`, `gd-x-icu`, ...)
that produce correct national alphabetical order (e.g. Icelandic þ/æ/ö at the
end; Norwegian æ/ø/å after z), applied per query with
`ORDER BY col COLLATE "is-x-icu"` (plus a collated index if the query is hot;
app locale codes map trivially: `is_IS` → `is-IS`). **Deferred decision:**
which server-side-sorted list/leaderboard endpoints should switch from neutral
to locale-strict ordering - a product-visible change, so
it deserves a deliberate pass rather than a blanket swap. Note that NDB sorted
strings by UTF-8 bytes (code-point order), so root ICU is already an
improvement; parts of the app also sort client-side via `Alphabet` in
`languages.py`. Ops note: after a managed-PG engine/ICU upgrade, watch for
"collation version mismatch" warnings and `REINDEX` affected text indexes.

### Scheduled jobs

- The jobs run inside each container: supercronic runs `crontab`, which calls
  the app on its own port with the `X-Cron-Secret` header (the `CRON_SECRET`
  environment variable; without it the scheduler does not start). They are
  `/connect/update` ("online users", every 2 minutes), `/stats/run` (03:00
  UTC), `/stats/ratings` (03:45) and `/connect/cleanup` (04:15). A new
  scheduled job should end with `log_job()`
- The App Engine cron configuration is empty in all three projects; never
  deploy `cron.yaml`. A deploy stops the container and a job running in it,
  so do not deploy between 02:55 and 04:30 UTC
- `/stats/ratings` (and `/stats/ratings_backfill`) are no-ops outside the
  netskrafl project (guarded by `RATINGS_ENABLED` in `src/config.py`): the
  old-style, locale-ignorant rating tables are only displayed on Netskrafl,
  while Explo serves per-locale ratings live from `EloModel` via
  `/rating_locale`. `/stats/run` remains essential in all projects (profile
  stats, 30-day Elo history, `UserModel` Elo fallback fields)
- `/connect/cleanup` (`src/rtdb_cleanup.py`) keeps the Firebase Realtime
  Database from growing without limit, since it has no time-to-live of its
  own; what it deletes and when is in `doc/operations.md`.
  `utils/rtdb-cleanup.py` runs the same code from the command line

## Coding Standards

- The #!/usr/bin/env python3 shebang is not required and should be omitted.
- Use `from __future__ import annotations` to enable postponed evaluation of type annotations.
- Use `from typing import ...` to import type hints. Place this immediately after
  the `from __future__ import annotations` line. Other imports then follow after these two.
- Use type hints for all function parameters and return types.
- Use strict typing in all cases except where third party libraries do not support it.
  In that case, use `# type: ignore` to suppress type checking errors, but try to use
  `cast(T, ...)` liberally and immediately to limit propagation of 'Any' or 'Unknown' types.
- Otherwise, avoid casts, type ignores and `Any` types as much as possible. If you find
  yourself needing to use them, consider whether the code can be refactored to avoid them.
- Python source files should end with an empty line (i.e., two newlines at the end - `\n\n`).
- Use datetime.now(UTC) for timestamps, not datetime.now() or datetime.utcnow().
- Empty lines should only contain newlines, no spaces or tabs.

## Gotchas

- A locally run program uses a local Redis instance, not the cache of a
  deployed backend. If a local utility script modifies a production database,
  the production backend may keep serving cached results (user search, rating
  lists, the client configuration record) until they expire or until its
  cache is emptied with `/cacheflush`. *Please remind the user about this if
  you can, when you see that utility programs are being run locally.* Also,
  adding comments to utility programs to this effect is useful.
- A local server or test run without `DATABASE_BACKEND=postgresql` uses the
  NDB backend, i.e. the Datastore of the project it is configured for, which
  no deployed backend reads any more.
- `netskrafl_lint.py` is **not** a linter - it is a separate utility program.
  Do not invoke it for code quality checks. Only run it when specifically asked.

## Hosting: what to know when changing the app or its build

`doc/operations.md` describes the deployments. The rules that matter while
working on the code:

**The staging app.** The Explo dev backend doubles as the staging app: the
canary for both production apps (see the `/deploy` skill). It auto-deploys on
push to the dedicated `do-deploy` branch (a merge-commit branch: merge master
into it, it is not fast-forwardable). It serves the built-in web UI
(`SINGLE_PAGE=TRUE`), which the production apps do not. It is smaller than
the production apps and has little data, so it is neither a load-testing
baseline nor a place to judge a query plan.

**The app specs.** `.do/app.yaml` is a reference copy of the staging app's
spec, and `.do/app-netskrafl.yaml` and `.do/app-explo.yaml` of the production
apps'. The live spec remains the source of truth, so edit it by round-tripping
`doctl apps spec get` → edit → `doctl apps update` rather than applying a
checked-in file (which would overwrite encrypted secrets with placeholders).
A copy of a live spec is a secret (`doc/logging.md`). Send one spec update at
a time: an update sent while a deployment is in progress cancels it. A change
of an environment variable restarts the container; adding a domain does not.

**One instance per app.** The scheduler runs in every container and the
entrypoint runs Alembic at every start, so the apps are scaled by instance
size, never by count. A schema migration must work with the previous
release's code, which keeps serving while the new container starts.

**Health.** `/health/ready` passes when the vocabularies are loaded and the
cache is reachable, and gates every deployment.

**Cache.** Each app uses one logical database of a Redis-compatible cluster
that it shares with other services. This is why `cache.py`'s `flush()`
deliberately avoids `FLUSHDB`.

**Build gotcha - App Platform builds with kaniko, not BuildKit.** kaniko does
not support heredocs in `RUN`: it passes only the first line and silently
discards the body, so failures surface later and misleadingly. The DAWG list
derivation was affected and now lives in `utils/list_dawgs.py` instead. Related:
`.dockerignore` excludes `utils/` wholesale, so build-time helpers there need an
explicit `!utils/<file>` re-inclusion or their `COPY` fails during context
resolution, before any stage runs. Validate Dockerfile changes against a kaniko
build, not just a local `docker build`.
