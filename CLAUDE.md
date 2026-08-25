# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Project Overview

Netskrafl is an Icelandic crossword game website and backend server built with:
- **Backend**: Python 3.11 + Flask web server for Google App Engine
- **Frontend**: HTML5/JavaScript/TypeScript client with Ajax communication
- **Database**: Google Cloud NDB (schemaless NoSQL), but being migrated to PostgreSQL
- **Build System**: Grunt for TypeScript/JavaScript/CSS compilation
- **Testing**: pytest framework

It supports (1) Netskrafl, a web-based game currently offered in Icelandic only,
and (2) is the backend for Explo, a multilingual mobile app client
(React Native app, in a separate repository).

## Common Development Commands

### Development Setup
```bash
# Install Python dependencies
pip install -r requirements.txt

# For local development, also install
pip install icegrams

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
FIREBASE_DB_URL="<explo-dev-firebase-url>" \
SINGLE_PAGE=TRUE \
venv/bin/pytest test/ -v

# Run tests for netskrafl (Icelandic only - some multi-locale tests will fail)
PROJECT_ID=netskrafl \
GOOGLE_APPLICATION_CREDENTIALS="credentials/netskrafl/service-account.json" \
GOOGLE_CLOUD_PROJECT=netskrafl \
RUNNING_LOCAL=true \
REDISHOST=127.0.0.1 \
REDISPORT=6379 \
FIREBASE_DB_URL="<netskrafl-firebase-url>" \
venv/bin/pytest test/ -v

# Run specific test file
venv/bin/pytest test/test_elo.py

# Type checking with pyright (preferred)
venv/bin/pyright src/

```

Note: The explo-dev configuration should be used for full test coverage as it supports
multiple locales. The netskrafl configuration only supports Icelandic (`is_IS`) and
some tests that require other locales will fail.

The actual values for credentials paths and Firebase URLs can be found in `.vscode/launch.json`.

## Architecture Overview

### Backend Structure (src/)
- **main.py**: Flask app entry point and configuration
- **web.py**: HTML page routes and responsive web content
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
- **js/**: Legacy JavaScript files
- **built/**: Compiled JavaScript output (netskrafl.js, explo.js)
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
- Netskrafl is a web-based game with real-time multiplayer capabilities
- The Netskrafl web frontend supports responsive UIs for desktop and mobile browsers
- Explo has a mobile app client (React Native app, implemented in the explo-front repository)
  that communicates with a separate instance of the Netskrafl/Explo game server
- Real-time gameplay uses WebSocket-like communication via Firebase
- Elo rating system tracks player performance
- Google App Engine deployment with multiple environments (Netskrafl/Explo, demo/live)
- A project is underway to migrate from Google Cloud to a containerized deployment,
  probably on Digital Ocean, with PostgreSQL replacing Google NDB; the plan and
  current status are tracked in `doc/migration-strategy.md`

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

- `cron.yaml` defines three jobs: `/stats/run` (03:00), `/stats/ratings` (03:45)
  and `/connect/update` ("Online users", every 2 minutes). It is deployed on all
  three projects (netskrafl, explo-dev, explo-live), where the jobs run via
  legacy App Engine cron, always targeting the promoted version. No per-version
  scheduler updates are needed after deploys. (Consolidated 2026-08-07; before
  that, netskrafl triggered `/connect/update` via a version-pinned Cloud
  Scheduler job that had to be re-pinned after every promotion.)
- The only remaining Cloud Scheduler job is `Clear-Redis` on netskrafl (yearly);
  explo-dev also has a daily `clear-cache` job. The container migration will
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

## Digital Ocean deployment experiment (status as of 2026-08-12)

A container deployment test runs on DO App Platform as the app
`netskrafl-staging` (region ams,
`https://netskrafl-staging-fvmuj.ondigitalocean.app`). It was first stood up in
January 2026 against the **NDB** backend, proving that hosting can be migrated
independently of the database, and was revived and repointed on 2026-08-12. The
app spec is checked in at `.do/app.yaml` as a reference copy; the live spec
remains the source of truth, so edit it by round-tripping
`doctl apps spec get` → edit → `doctl apps update` rather than applying the
checked-in file (which would overwrite encrypted secrets with placeholders).

**Current configuration:** `PROJECT_ID=explo-dev` with the explo-dev service
account, `DATABASE_BACKEND=ndb`, one `apps-s-1vcpu-1gb` instance, auto-deploying
on push to the dedicated `do-deploy` branch. Firebase and other client-secret
values are *not* set as env vars - they are fetched from Secret Manager keyed by
`PROJECT_ID` (`src/config.py:166,186`), so they follow the project automatically.

**Redis/Valkey (since 2026-08-12):** the app uses Miðeind's shared Valkey
cluster `db-redis-gsapi-staging`, **logical database 1** (`REDIS_URL` set to
the cluster URI with a `/1` suffix; db 0 belongs to gsapi — see the Valkey
notes in `.do/app.yaml` for the full tenant assignment, and note that
`cache.py`'s `flush()` deliberately avoids `FLUSHDB` for this reason).
`/health/ready` passes and a `health_check` on it gates deployments.

**Not yet exercised:** `CRON_SECRET` is deliberately unset (which keeps
supercronic, and therefore all scheduled jobs, switched off - see
`docker-entrypoint.sh`). The PostgreSQL backend has never been deployed here.
Note the instance has 1 GB against GAE production's 2 GB (`B4_1G`) with the same
three gunicorn workers, so it is not a valid load-testing baseline as sized.

**Build gotcha - App Platform builds with kaniko, not BuildKit.** kaniko does
not support heredocs in `RUN`: it passes only the first line and silently
discards the body, so failures surface later and misleadingly. The DAWG list
derivation was affected and now lives in `utils/list_dawgs.py` instead. Related:
`.dockerignore` excludes `utils/` wholesale, so build-time helpers there need an
explicit `!utils/<file>` re-inclusion or their `COPY` fails during context
resolution, before any stage runs. Validate Dockerfile changes against a kaniko
build, not just a local `docker build`.
