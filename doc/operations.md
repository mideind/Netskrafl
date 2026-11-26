# Hosting and operations

How the Netskrafl / Explo backend runs since the move away from Google App
Engine and Cloud Datastore in November 2026, what is left on Google Cloud,
and what is still to do. Releases are described in the `/deploy` skill
(`.claude/skills/deploy/SKILL.md`), the log in `logging.md`, the tests in
`testing.md`, and what the move itself taught us in `migration-2026.md`.

This repository is public: names, addresses, sizes and the whereabouts of
secrets are kept in private notes, not here.

## The three backends

One code base and one container image serve three deployments, told apart by
the `PROJECT_ID` environment variable:

| `PROJECT_ID` | What it is | Clients |
|---|---|---|
| `netskrafl` | Netskrafl production (Icelandic only) | The Netskrafl web client, which is embedded in Málstaður |
| `explo-live` | Explo production (all locales) | The Explo mobile apps |
| `explo-dev` | The Explo development backend, which is also **the staging app**: the canary for both production apps | Development builds of the Explo app, and the built-in web UI |

Each runs as a single container on a managed container platform, with its
own managed PostgreSQL database, and deploys from its own git branch. The
production apps moved from App Engine and Datastore in November 2026
(Netskrafl on the 13th, Explo on the 20th); the staging app has run on
PostgreSQL since August 2026.

What stays on Google Cloud for all three is **Firebase**: the Realtime
Database (notifications of moves and chat, presence, and the data of Gáta
dagsins, see `firebase-tree.md`), Cloud Messaging for push notifications,
and custom auth tokens. The container therefore still carries a Google
service-account credential, which the Firebase Admin SDK uses.

## The container

`Dockerfile` builds the image in stages: Python packages
(`requirements-pg.txt`), the vocabulary files (downloaded from a CDN, see
`dictionary-update.md`), the front-end assets of the built-in web UI, the
GoSkrafl engine (from a pinned commit, `GOSKRAFL_COMMIT`), and the runtime.
The platform builds it with kaniko, which differs from a local
`docker build`; the gotchas are in `CLAUDE.md`.

`docker-entrypoint.sh` starts, in this order:

1. **Schema migrations**: `alembic upgrade head`, when
   `DATABASE_BACKEND=postgresql`. So the schema changes before the previous
   container stops serving, and a release that contains a migration cannot
   be rolled back by redeploying the previous one.
2. **The scheduler** (supercronic, running `crontab`), only if `CRON_SECRET`
   is set.
3. **The GoSkrafl sidecar**, only if `MOVES_SIDECAR_PORT` is set: a second
   process bound to the loopback address, restarted by the entrypoint if it
   exits.
4. **gunicorn**, in the foreground, with the Flask app.

`/health/live` answers when the process is up. `/health/ready` answers 200
when the vocabularies are loaded and the cache is reachable; the platform
gives a new container traffic only after that, and keeps the old one serving
if it never does.

**One instance only.** The scheduler runs in every container, so two
instances would run every scheduled job twice, and each would run Alembic at
its start. Scale by the size of the instance, not by the number.

## Configuration and secrets

Everything is configured through environment variables in the app's spec.
`.do/app.yaml` is a reference copy of the staging app's spec, with every
setting explained; `.do/app-netskrafl.yaml` and `.do/app-explo.yaml` are the
production apps', commenting only on what differs. They hold placeholders
for all secrets and must never be applied to a live app: change a live app
by fetching its own spec, editing it and sending it back. A copy of a live
spec is itself a secret (see `logging.md`).

| Variable | Meaning |
|---|---|
| `PROJECT_ID` | Which product the backend is (table above). It selects the locales, the login methods, the rating tables and the client secret |
| `DATABASE_BACKEND` | `postgresql` on all deployments. **The default in the code is still `ndb`**, see "The database layer" |
| `DATABASE_URL` | The PostgreSQL connection |
| `REDIS_URL` | The cache (below) |
| `SECRETS_PROVIDER` | `env` on all deployments: each secret is read from the variable named after it, or base64-decoded from that name with `_BASE64` appended. The default, `google`, reads Google Secret Manager and is what a local server uses |
| `GOOGLE_CREDENTIALS_BASE64` | The service-account credential for Firebase |
| `CRON_SECRET` | Starts the scheduler and authenticates its calls; also guards `/appversion` and `/cacheflush` |
| `MOVES_SIDECAR_PORT` | Starts the GoSkrafl sidecar and points the app at it |
| `APP_VERSION` | The release name: the `version` of every log entry and the cache-busting suffix of static files |
| `HOME_REDIRECT_URL` | Where a browser that opens `/` or `/greet` is sent (the production apps serve no web UI) |
| `SINGLE_PAGE` | `TRUE` serves the built-in web UI, a development client: on the staging app and local servers only |
| `MAINTENANCE` | Set, the server answers every request except the health endpoints with HTTP 503 (`src/maintenance.py`) |
| `ENABLE_RATINGS` | Opts a project other than `netskrafl` into the old-style rating tables |
| `FIREBASE_DB_URL` | Overrides the Realtime Database address in the client secret |
| `LOG_FORMAT` | `text` for plain-text log lines in a container (default: JSON) |

The secrets have the same values as before the move, so sessions and login
tokens survived it.

## The database layer

- `src/db/protocols.py` defines the contracts: entity protocols, one
  repository protocol per kind of data, and the shared data types.
- `src/db/postgresql/` implements them with SQLAlchemy 2.0 (the ORM models
  satisfy the entity protocols directly); `src/db/ndb/` implements them by
  wrapping the original Datastore code in `src/skrafldb_ndb.py`.
- `src/skrafldb.py` is the facade that application code imports
  (`UserModel`, `GameModel`, ...). It selects `skrafldb_ndb` or
  `skrafldb_pg` by `DATABASE_BACKEND`; the latter delegates to the
  PostgreSQL repositories. New code can use the repositories directly
  through `get_db()`.
- On PostgreSQL there is one session per request, committed when the request
  returns (`src/db/session.py`). That is why side effects that make a client
  re-read the database must be registered with `skrafldb.on_commit()` (see
  `CLAUDE.md`).
- Alembic owns the schema (`migrations/`). The database's default collation
  is the neutral ICU root collation; see `CLAUDE.md` for what that leaves
  open.

**The Datastore (NDB) backend is still in the code, and no deployment uses
it.** It is what runs when `DATABASE_BACKEND` is not set, so a local server
started with `runserver.sh` and the `test/` suite work against the
development project's Datastore unless told otherwise. Removing it is on the
list below.

## The cache

The app uses Redis (a managed, Redis-compatible service): one logical
database of a cluster that it shares with other services, which is why
`cache.py`'s `flush()` deletes the app's own key patterns and never uses
`FLUSHDB`. On PostgreSQL the cache holds the sets of online users (written
by the `/connect/update` job), a few result caches (user search, rating
lists) and the client configuration record; on NDB it also cached Datastore
entities. `/cacheflush` (with the scheduler's secret) empties it.

## Scheduled jobs

`crontab`, run by supercronic in the container, calls the app on its own
port with the `X-Cron-Secret` header (`basics.cron_request_source()`
authenticates it):

| Job | When (UTC) | What |
|---|---|---|
| `/connect/update` | every 2 minutes | Reads presence from Firebase and refreshes the sets of online users |
| `/stats/run` | 03:00 | Statistics of the previous day's games: profile statistics, the 30-day Elo history, the Elo fields kept with each user. Needed in all three projects |
| `/stats/ratings` | 03:45 | The old-style, locale-ignorant rating tables. A no-op outside Netskrafl (`RATINGS_ENABLED` in `src/config.py`): Explo serves per-locale ratings live from the Elo table |
| `/connect/cleanup` | 04:15 | Keeps the Realtime Database from growing without limit (below) |

The nightly jobs answer at once and work in the background; each ends with
a log entry of its result (`logging.md`) and records its run in the
completions table. Do not deploy between 02:55 and 04:30 UTC: a deploy stops
the container and a job running in it.

`/connect/cleanup` (`src/rtdb_cleanup.py`) exists because the Realtime
Database has no time-to-live of its own. It deletes `game/{id}` notification
nodes 30 days after the game was created (the age is in the version 1 UUID
of the game id), presence entries under `connection/` older than 14 days (by
their push id) or set to `false` (left by older clients), and Explo push
tokens under `session/` not refreshed for 60 days. `gatadagsins/` and
`user/` are never touched. It deletes in batches, oldest first, within a
3-minute budget per run, so a backlog carries over to the next night.
`utils/rtdb-cleanup.py` runs the same code from the command line
(`--dry-run`, other retention periods, no time budget, and `--wipe` to empty
an instance that no longer has clients).

## The moves service (GoSkrafl)

GoSkrafl, the engine written in Go (its own repository), generates moves for
the robots, the best moves shown in game reviews, and the riddles of Gáta
dagsins. In the container it runs as the loopback sidecar: Flask owns the
public routes and forwards to it (`src/movesservice.py`), robots take their
candidate moves from it (about a tenth of a second per move, where the
Python engine needs seconds for a rack with two blanks), and the Python
engine is the fallback. A change in GoSkrafl reaches the backends by
changing the pinned commit in the `Dockerfile`.

GoSkrafl also still runs as a service of its own on App Engine, see the next
section.

## What is left on Google Cloud

Besides Firebase, which stays:

- **Netskrafl's project** serves only `appspot-redirect/`: a dependency-free
  app that redirects a browser opening the old App Engine address to
  Netskrafl's home within Málstaður and answers 503 to everything else
  (`./deploy-netskrafl.sh redirect <version>`, then route the traffic to
  that version). The old backend versions and the services they needed were
  deleted on 2026-11-26, so `app-netskrafl.yaml` can no longer be deployed
  as it stands.
- **Explo's production project** serves `appspot-forward/`, a small reverse
  proxy: Explo apps released before version 1.5.1 have the App Engine
  address built in, and the forwarder passes their requests on to the
  container (`./deploy-explo-live.sh forward <version>` with `FORWARD_TO`
  set). The project also runs the GoSkrafl `moves` service, which **every**
  released app version calls directly for word checks. The old backend
  versions still exist there, without traffic; nothing may ever be routed to
  them, since their data stopped at the move.
- **The development project** runs a GoSkrafl `moves` service as well, which
  Málstaður calls for Netskrafl's word checks. Its old backend version is
  dormant and cannot start.
- **Datastore** still holds the data as it was at each move, in both
  production projects. Managed exports were taken as an archive on
  2026-11-26; the data itself has not been deleted.
- The App Engine cron configuration is empty in all three projects. Do not
  deploy `cron.yaml`.

Files in this repository that belong to the App Engine era and are no longer
used by any deployment: `app-netskrafl.yaml`, `app-explo.yaml`,
`app-explo-live.yaml`, `app-demo.yaml`, `cron.yaml`, `dispatch.yaml`,
`index.yaml`, `index-netskrafl.yaml`, and the `default` targets of the
`deploy-*.sh` scripts. The scripts' `redirect` and `forward` targets are
still the way to deploy the two small apps above.

## Explo apps and the backend's address

An Explo app has its backend addresses built in: the API host, and the host
of the `moves` service, which it calls directly with a bearer key. Whatever
a released version has built in, it keeps calling for as long as it is
installed. Two levers exist for moving the installed base without a
release: telling an app to update, and telling it to use another address.
Neither has been used on a production backend yet.

**What the versions can do**

| App version | API address built in | Can be told to update (`min_supported_version`) | Can be redirected (`endpoints`) |
|---|---|---|---|
| older than 1.4.7 | the App Engine address | no | no |
| 1.4.7 | the App Engine address | yes | no |
| 1.4.8 to 1.5.0 | the App Engine address | yes | yes |
| 1.5.1 and later | the backend's public API hostname | yes | yes |

Since 2026-11-26 the public API hostname is a domain of the production
container itself, so apps from 1.5.1 reach it directly, and everything older
goes through the forwarder. All versions still have the App Engine `moves`
address built in.

**The client configuration record.** A generic JSON store (`ConfigModel`;
the `configs` table) holds singleton documents; the one with id
`app_version` is the client configuration. Its schema lives in two places,
`AppVersionDict` in `src/db/protocols.py` and `validate_config()` in
`src/appversion.py`, so a new field needs no schema migration.

| Field | Meaning |
|---|---|
| `min_supported_version` | Clients below this must update before they can play (required) |
| `latest_version` | The latest released client version (required; informational in the app so far) |
| `update_message` | Optional text for the update screen |
| `ios_min_supported_version`, `android_min_supported_version`, `ios_latest_version`, `android_latest_version` | Per-platform overrides, resolved by the server |
| `api_url` | Override of the API base URL |
| `moves_url` | Override of the moves service base URL |

Versions must look like `1.2.3`; URLs must start with `https://`; unknown
fields are refused. `/inituser`, the call every client makes at start-up,
returns the record as `app_version` (already resolved for the caller's
platform) and `endpoints` (`null` unless a URL override is set). The lookup
is cached for 60 seconds and **fails open**: a cache or database error
yields "no configuration", so a backend hiccup can neither force an update
nor redirect anyone.

`/appversion` reads and writes the record, authenticated like a scheduled
job. A POST replaces the whole document, so read it first. There is one
record per backend; check what a backend has before assuming anything.

```bash
# <host>: the backend; <secret>: its CRON_SECRET (never commit either)
curl -s https://<host>/appversion -H "X-Cron-Secret: <secret>"
curl -s -X POST https://<host>/appversion \
  -H "X-Cron-Secret: <secret>" -H "Content-Type: application/json" \
  -d '{"min_supported_version": "1.4.8", "latest_version": "1.5.1"}'
#   to redirect clients, add "api_url" and/or "moves_url" to the document
curl -s -X POST https://<host>/appversion \
  -H "X-Cron-Secret: <secret>" -H "Content-Type: application/json" \
  -d '{"delete": true}'
```

**How the app treats an override** (the app repository documents it in its
`doc/server-endpoints.md`):

- A URL must be a plain `https://` origin on a host that is built into the
  app or on its allow-list of domains, so that a wrong or hostile record
  cannot take clients anywhere else. A refusal is reported through the
  app's analytics.
- An accepted override is stored on the device and applies from the next
  cold start.
- After three consecutive failures at the network level (no HTTP answer at
  all; any status code counts as reachable) the app goes back to its
  built-in addresses and forgets the override. A later `/inituser` that
  still carries it applies it again, so a wrong record can be repaired
  without a release. A successful `/inituser` without `endpoints` also
  clears a stored override: that is how an override is retired.
- `moves_url` empty or equal to the API URL means that the app calls
  `/moves` on the API host with its session, without the bearer key. A
  `moves_url` that names a dedicated moves host must accept the built-in
  key.
- A second channel exists for the case where the built-in API host cannot be
  reached at all, so that `/inituser` cannot deliver anything: the node
  `client_config/endpoints` in the Realtime Database, world-readable by its
  security rule, with the same content and the same checks. The app reads it
  at most once per session, and only after the built-in host has failed at
  the network level.

**Things to know before using the levers**

- Cookies belong to a host. A change of DNS keeps the host name, so sessions
  survive it. An override changes the host name: the first request is
  answered 401 and the app logs in again by itself, so expect a short burst
  of 401s and logins when an override is published.
- Clients older than 1.4.7 honour neither lever. They keep working through
  the forwarder until it is switched off, which is therefore a decision to
  be taken from the request log, not an event.
- The app reports the hosts it uses once per login (the analytics event
  `endpoints_in_use`, with the app version), which shows how the installed
  base is distributed; the forwarder's request log shows the same from the
  server's side.
- The public API hostname must stay unproxied at the DNS provider unless
  caching is switched off for it and bot challenges are disabled: a cached
  `/inituser` or a challenge page served to the app's HTTP client would
  break the app.

## Still to do

1. **Riddle generation into PostgreSQL.** GoSkrafl's riddle generator writes
   the riddles of Gáta dagsins into Datastore, and the backends now read
   them from PostgreSQL. The stock that was copied lasts until 2027-01-15.
2. **Move the remaining Explo traffic off App Engine**: publish `api_url`
   for the apps that still call the App Engine address, and `moves_url` (or
   a corrected build configuration) for the word checks; raise
   `min_supported_version` for 1.4.7; point the subscription provider's
   webhook at the public API hostname. Then retire the forwarder and the
   `moves` service when their request logs show that nothing calls them.
3. **Málstaður's word checks** go to the development project's `moves`
   service; they need another target before that service can go.
4. **Remove Redis from the PostgreSQL backend** (online users into a table,
   result caches dropped or kept in the process), so that the apps no longer
   depend on a shared cache cluster.
5. **Retire the NDB backend**: `skrafldb_ndb.py`, `src/db/ndb/`, the
   Datastore dependencies, the App Engine files listed above, and
   `requirements-pg.txt` folded into `requirements.txt`. The tests that
   compare the two backends go with it.
6. **Delete the Datastore data** once the archives are no longer needed as
   anything but archives, and close what remains of App Engine.
7. **Locale-strict collation** for server-sorted lists (see `CLAUDE.md`).
8. **Rehearse a rollback** on the staging app; none has been carried out yet
   (see the `/deploy` skill).
