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

Netskrafl is an Icelandic crossword game website and backend server built with:
- **Backend**: Python 3.11 + Flask web server for Google App Engine
- **Frontend**: the players' clients live in other repositories (see below); this
  one keeps a single-page TypeScript web client as a development client
- **Database**: Google Cloud NDB (schemaless NoSQL), but being migrated to PostgreSQL
- **Build System**: Grunt for TypeScript/JavaScript/CSS compilation
- **Testing**: pytest framework

It supports (1) Netskrafl, a web-based game currently offered in Icelandic only,
and (2) is the backend for Explo, a multilingual mobile app client
(React Native app, in a separate repository).

## Common Development Commands

### Development Setup
```bash
# Create the venv (CPython 3.11, the GAE runtime) and install everything:
# runtime deps (requirements.txt, what GAE gets), PostgreSQL backend deps
# (requirements-pg.txt, what the container gets) and dev tooling
# (icegrams, pytest, pyright, type stubs). No pyproject.toml: GAE needs
# requirements.txt and nothing consumes a pyproject, so the layered
# requirements files are the single source of truth.
uv venv --python 3.11 venv
uv pip install --python venv/bin/python -r requirements-dev.txt

# Install Node.js dependencies
npm install

# Generate DAWG vocabulary files (takes a few minutes)
python utils/dawgbuilder.py all

# Build frontend assets
grunt make

# Start development server
./runserver.sh  # or runserver.bat on Windows

# Watch for file changes during development
grunt  # runs grunt watch by default
```

### Testing

Tests require Google Cloud credentials and environment variables. Use the appropriate
configuration for each project:

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

# Run tests for netskrafl (Icelandic only - some multi-locale tests will fail)
PROJECT_ID=netskrafl \
GOOGLE_APPLICATION_CREDENTIALS="credentials/netskrafl/service-account.json" \
GOOGLE_CLOUD_PROJECT=netskrafl \
RUNNING_LOCAL=true \
REDISHOST=127.0.0.1 \
REDISPORT=6379 \
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

Note: The explo-dev configuration should be used for full test coverage as it supports
multiple locales. The netskrafl configuration only supports Icelandic (`is_IS`) and
some tests that require other locales will fail. `FIREBASE_DB_URL` does not need to
be set: it is read from the project's client secret at startup.
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
- **skrafldb.py**: Database persistence layer using Google Cloud NDB
- **auth.py/authmanager.py**: Authentication and user session management
- **secret_manager.py**: Google Cloud Secret Manager integration

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
- Explo has a mobile app client (React Native app, implemented in the explo-front repository)
  that communicates with a separate instance of the Netskrafl/Explo game server
- Real-time gameplay uses WebSocket-like communication via Firebase
- Firebase notifications (and any other side effect that makes a client re-read
  the database) must be registered with `skrafldb.on_commit()` rather than sent
  directly: inside an `@transactional()` function on NDB, and anywhere in a
  request on PostgreSQL, the writes are not committed until the function or
  request returns, and a client reacting to an early notification reads the old
  state (the 2026-09-11 stale-game-list bug in the Explo app)
- Elo rating system tracks player performance
- Logging in the container is structured: one JSON entry per line, one entry
  per request with the user's id, and entries for refusals, logins and the
  results of scheduled jobs (`src/applog.py`; the entries, their fields and
  the forwarding to the log service are described in `doc/logging.md`). Attach
  fields to a log call with `log_fields()`, and end a scheduled job with
  `log_job()`. An API refusal is answered with HTTP 200, so it is only visible
  in the log if it is noted there
- Maintenance mode: with the `MAINTENANCE` environment variable set, the server
  answers every request except the health endpoints with HTTP 503
  (`src/maintenance.py`). A version built that way and deployed without traffic
  is how the backend is frozen (by routing traffic to it) during a data migration
- Game list queries on PostgreSQL (`GameRepository._newest_games_stmt`) use one
  ordered, limited branch per player column, merged; an `OR` across the two
  player columns cannot use the per-player indexes and took seconds on the
  production-size database. Check new hot queries with `EXPLAIN` at that size
- Google App Engine deployment across three projects: netskrafl, explo-live and
  explo-dev (the explo-dev GAE default service was retired on 2026-10-15: its cron
  jobs are gone and the version, which App Engine cannot stop under automatic
  scaling, idles at zero instances; the Explo dev app runs on the Digital Ocean
  container, and the explo-dev `moves` service still serves Netskrafl production
  and Málstaður). The former netskrafl `demo` service was deleted on
  2026-09-08 for lack of traffic; `app-demo.yaml` remains in case it is ever needed
- Netskrafl's backend moved to the Digital Ocean container and PostgreSQL on
  2026-11-13. What is left on App Engine in the netskrafl project is
  `appspot-redirect/`, a dependency-free app that redirects browsers opening the
  old App Engine address to Netskrafl's home within Málstaður and answers 503 to
  everything else (`./deploy-netskrafl.sh redirect <version>`, then route the
  traffic to that version). It stays until the App Engine project is closed
- Every production release (netskrafl or explo-live) gets a git tag named
  `nYYYYMMDD` or `eYYYYMMDD` (plus a letter for further releases on the same day),
  on the deployed commit, pushed to GitHub once the release serves all users. The
  tag equals the `APP_VERSION` label in the spec of the app's container. The
  tag is also published as a GitHub release ("Version <tag>") with release notes
  that cover everything since the previous release tag. The `/deploy` skill does
  both as its last step; tag and publish by hand after any deploy made outside it
- Deploying is done with the `/deploy` skill, and works the same way for all three
  backends, which are containers on Digital Ocean (netskrafl since 2026-11-13,
  explo-live since 2026-11-20): a production release goes to the staging app first
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
- A project is underway to migrate from Google Cloud to a containerized deployment,
  probably on Digital Ocean, with PostgreSQL replacing Google NDB; the plan and
  current status are tracked in `doc/migration-strategy.md`
- Vocabulary fixes must be propagated to four consumers (GAE, container/CDN,
  GoSkrafl, Skrafl); the dependency map and runbook are in `doc/dictionary-update.md`

### PostgreSQL collation (detail to attend to later)

The PostgreSQL database uses the neutral ICU root collation (`und`) as its
default - the only coherent choice, since users of all locales share the same
tables. PostgreSQL simultaneously provides per-locale ICU collations
(`is-x-icu`, `pl-x-icu`, `nb-x-icu`, `nn-x-icu`, `ga-x-icu`, `gd-x-icu`, ...)
that produce correct national alphabetical order (e.g. Icelandic þ/æ/ö at the
end; Norwegian æ/ø/å after z), applied per query with
`ORDER BY col COLLATE "is-x-icu"` (plus a collated index if the query is hot;
app locale codes map trivially: `is_IS` → `is-IS`). **Deferred decision:**
which server-side-sorted list/leaderboard endpoints should switch from neutral
to locale-strict ordering after the PG cutover - a product-visible change, so
it deserves a deliberate pass rather than a blanket swap. Note that NDB sorts
strings by UTF-8 bytes (code-point order), so root ICU is already an
improvement; parts of the app also sort client-side via `Alphabet` in
`languages.py`. Ops note: after a managed-PG engine/ICU upgrade, watch for
"collation version mismatch" warnings and `REINDEX` affected text indexes.

### Scheduled jobs (GAE)

- `cron.yaml` defines four jobs: `/stats/run` (03:00), `/stats/ratings` (03:45),
  `/connect/cleanup` (04:15, see below) and `/connect/update` ("Online users",
  every 2 minutes). `cron.yaml` is deployed separately from the app
  (`./deploy-<target>.sh cron`), so deploy it only once a version that serves
  every listed URL has all the traffic. It is deployed on
  explo-live, where the jobs run via
  legacy App Engine cron, always targeting the promoted version. explo-dev
  (since 2026-10-15) and netskrafl (since 2026-11-13) have an empty cron
  configuration: their jobs run in the DO containers' supercronic, and
  `deploy-explo.sh cron` and `deploy-netskrafl.sh cron` refuse to redeploy them. No per-version
  scheduler updates are needed after deploys. (Consolidated 2026-08-07; before
  that, netskrafl triggered `/connect/update` via a version-pinned Cloud
  Scheduler job that had to be re-pinned after every promotion.)
- `/connect/cleanup` (`src/rtdb_cleanup.py`) keeps the Firebase Realtime Database
  from growing without limit, since it has no time-to-live of its own: it deletes
  `game/{id}` notification nodes 30 days after the game was created (judged by the
  version 1 UUID of the game id), presence entries under `connection/` older than
  14 days (by their push id) or set to `false` (left by older clients), and Explo push tokens under `session/` not refreshed
  for 60 days. `gatadagsins/` and `user/` are never touched. It deletes in batches,
  oldest first, within a 3-minute budget per run, so a backlog carries over to the
  next night. `utils/rtdb-cleanup.py` runs the same code from the command line
  (`--dry-run`, other retention periods, no time budget, and `--wipe` to empty a
  decommissioned instance).
- The only remaining Cloud Scheduler job is `Clear-Redis` on netskrafl (yearly);
  explo-dev also has a daily `clear-cache` job, paused. The container migration will
  replace GAE cron with supercronic.
- `/stats/ratings` (and `/stats/ratings_backfill`) are no-ops outside the
  netskrafl project (guarded by the `NETSKRAFL` config flag): the old-style,
  locale-ignorant rating tables are only displayed on Netskrafl, while Explo
  serves per-locale ratings live from `EloModel` via `/rating_locale`.
  `/stats/run` remains essential in all projects (profile stats, 30-day Elo
  history, `UserModel` Elo fallback fields).

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

- When running locally in development, a separate local Redis instance is used for Cloud
  Datastore caching. *This may cause cache incoherency* with the production environment.
  Especially, if running local utility scripts that modify the production database,
  the production cache may need to be cleared via Google Cloud Console.
  *Please remind the user about this if you can, when you see that utility programs
  are being run locally.* Also, adding comments to utility programs to this effect is useful.
- `netskrafl_lint.py` is **not** a linter - it is a separate utility program.
  Do not invoke it for code quality checks. Only run it when specifically asked.

## The staging app on Digital Ocean

The Explo dev backend runs as a container on DO App Platform, and doubles as
the staging app: the canary for both production apps (see the `/deploy`
skill). It was first stood up in January 2026 against the **NDB** backend,
proving that hosting can be migrated independently of the database, and has
run on PostgreSQL since 2026-08-18. Its names, addresses and the whereabouts
of its secrets are kept in private notes, not here.

**The app spec.** `.do/app.yaml` is a reference copy of its spec (and
`.do/app-netskrafl.yaml` and `.do/app-explo.yaml` of the production apps').
The live spec remains the source of truth, so edit it by round-tripping
`doctl apps spec get` → edit → `doctl apps update` rather than applying a
checked-in file (which would overwrite encrypted secrets with placeholders).

**Configuration.** `PROJECT_ID=explo-dev` with that project's service account,
`DATABASE_BACKEND=postgresql` against a managed PostgreSQL cluster, one small
instance, auto-deploying on push to the dedicated `do-deploy` branch (a
merge-commit branch: merge master into it, it is not fast-forwardable).
Secrets come from encrypted env vars (`SECRETS_PROVIDER=env`); the Google
service-account credential stays for the Firebase Admin SDK. `/health/ready`
passes when the database and the cache are reachable, and a `health_check` on
it gates deployments.

**Cache.** The app uses one logical database of a Valkey cluster that it
shares with other services (the assignment is noted in `.do/app.yaml`). This
is why `cache.py`'s `flush()` deliberately avoids `FLUSHDB`.

**Scheduled jobs.** supercronic runs the crontab in the container, and
authenticates to the app with the `CRON_SECRET` environment variable, which
also guards `/appversion` and `/cacheflush`. The instance has half the memory
of a production instance with the same three gunicorn workers, so it is not a
valid load-testing baseline.

**Build gotcha - App Platform builds with kaniko, not BuildKit.** kaniko does
not support heredocs in `RUN`: it passes only the first line and silently
discards the body, so failures surface later and misleadingly. The DAWG list
derivation was affected and now lives in `utils/list_dawgs.py` instead. Related:
`.dockerignore` excludes `utils/` wholesale, so build-time helpers there need an
explicit `!utils/<file>` re-inclusion or their `COPY` fails during context
resolution, before any stage runs. Validate Dockerfile changes against a kaniko
build, not just a local `docker build`.
