# Logging

This document describes what the backend writes to its log in the container
deployment, how to read it, and how it reaches the log service. On App Engine
(explo-live, until it moves) the platform's own request log and Cloud Logging
apply instead; the application's log calls are the same.

## Why it looks the way it does

Three things were missing when the backend first ran in a container:

- **History.** The platform keeps the log only briefly: about two hours at
  busy times, and a container's log is gone when a deploy replaces it. A
  problem reported the next day could not be looked up.
- **The user.** The web server's access log knew neither the user nor the
  client's address (it saw the platform's proxy), so one user's session could
  not be followed.
- **Refusals.** The API answers a refused request with HTTP 200 and an error
  code in the body. A subscriber who was wrongly refused the premium robots
  left no trace at all.

So the log is now forwarded to a log service, every entry is structured, each
request is logged by the application itself with the user's id, and refusals
are logged with the reason.

## The format

In a container, every line is one JSON object (`src/applog.py`). Set
`LOG_FORMAT=text` to get plain text instead, for instance when reading the
log of a local container by eye. Local development (`RUNNING_LOCAL`) logs
plain text as before.

Every entry has:

| Key | Content |
|---|---|
| `timestamp` | UTC, ISO 8601 with milliseconds |
| `status` | `info`, `warning`, `error`, `critical` |
| `message` | The text, readable on its own |
| `logger.name` | The module that logged it; `request`, `job` and `gunicorn` for the entries below |
| `service` | The deployment's `PROJECT_ID` (override with `DD_SERVICE`) |
| `version` | The release, from `APP_VERSION` (override with `DD_VERSION`) |
| `env` | Only if `DD_ENV` is set |

An entry logged while a request is being handled also has `request_id` and,
if the user is known by then, `usr.id`. An entry for an exception has
`error.kind`, `error.message` and `error.stack`.

The attribute names follow the log service's standard attributes (`http.*`,
`network.client.ip`, `duration`, `usr.id`, `error.*`), so no parsing rules are
needed there.

A log call attaches its own fields with `log_fields()`:

```python
logging.info(
    f"Málstaður login: user {userid} logged in",
    extra=log_fields("malstadur_login", outcome="success", user_id=userid),
)
```

The first argument becomes the `event` field, which is what queries and
monitors select on. Write the message so that it can be read without the
fields: locally they are not shown.

## Entries worth knowing

### `event: request`: one per request

Written by `RequestLogMiddleware` when a request has been answered. It
replaces the web server's access log.

```
POST /initgame 200 23 ms user 0a1b2c refused: premium_required
```

| Field | Content |
|---|---|
| `http.method`, `http.url_details.path`, `http.status_code`, `http.useragent` | The request. The path only: a query string can hold secrets |
| `usr.id` | The user, if the request was authenticated (or logged a user in) |
| `network.client.ip` | The client's address, from the header that the platform's proxy sets |
| `duration` (nanoseconds), `duration_ms` | Time in the application, including the database commit |
| `request_id` | Also sent to the client in the `X-Request-Id` header |
| `api.ok`, `api.err`, `api.result`, `api.reason`, `api.status` | Present if the answer was a refusal: `ok: false` with its `err`; a result code other than a legal move or a move that ends the game, with its name as `reason` (`LOGIN_REQUIRED`, `WORD_NOT_IN_DICTIONARY`, ...); or a login status of `invalid` or `expired` |

Not logged, unless they fail: CORS preflights (`OPTIONS`), the platform's
health probes (`/health/`) and static files. A request answered with 5xx is
logged with status `error`.

To follow one user: filter on `@usr.id`. To see everything that was logged
during one request: filter on `@request_id`.

### `event: paywall`: a refusal that needs a subscription

```
Paywall: premium_required for user 0a1b2c (plan 'none', friend False, has paid False)
```

Fields: `reason` (`premium_required`, `game_limit_reached`, `best_moves`,
`review`), `user_id`, `plan`, `friend`, `has_paid`, `inconsistent`. A user
whose plan says subscriber but who is refused as unpaid is logged as a
**warning** with `inconsistent: true`: that state should not exist. It is what
the PostgreSQL login bug of November 2026 left behind, invisibly at the time.

### `event: malstadur_login`: a login from the host

`outcome` is `success`, `expired`, `invalid`, `email_mismatch`, `no_sub`,
`error` or `no_firebase_token`. A successful login also says what the host's
token claimed (`token_plan`) and what the user ended up with (`friend`,
`has_paid`), so that a subscription that does not take effect shows here.

### `event: job`: the result of a scheduled job

Each job ends with one entry, from `log_job()`:

```
Job stats: OK in 38.4 s; 1213 games and 584 users, played on 2026-11-14
Job ratings: OK in 4.2 s; all 100/100, human 100/100, manual 100/100
Job cleanup: OK in 0.5 s; connection/ 0 deleted of 0 expired; session/ 0 deleted of 0 expired; game/ 42 deleted of 42 expired
```

Fields: `job`, `ok`, `seconds`, and the job's own figures (`games`, `users`
and `period` for stats; `rows` per table and `tables_ok` for ratings;
`scanned`, `expired`, `deleted` per path, `complete` and `dry_run` for the
cleanup). A failed job is logged with status `error` and says why.

The stats, ratings and cleanup jobs also record each run in the completions
table of the database (`proctype` `stats`, `ratings`, `cleanup`), which
answers "did it run last night?" without the log.

The scheduler (supercronic) logs the start and the end of each job as JSON
too; its entries have the command line in `job.command`.

### `event: ratings_table`: what the ratings job found

The ratings job logs one entry per table (`all`, `human`, `manual`) before its
job entry:

```
Ratings table 'human': 100 of 100 rows, Elo 1784 to 1564, 152 candidates, weakest 1498
```

Fields: `kind`, `rows`, `max_rows`, `robots`, `elo_top`, `elo_cutoff`,
`candidates`, `weakest_candidate`, `all_users`, `full`, `complete`.

This is the nightly evidence that the tables are what they should be:

- **Full:** `rows` equals `max_rows`. The former computation on App Engine
  scanned all statistics snapshots in descending order of Elo and discarded
  those that were not a player's newest ("false positives"); with enough of
  them, a table came out short.
- **Complete:** the weakest candidate is at or below the table's cutoff, so
  nobody outside the candidates could belong in the table.

An entry that is not full or not complete is logged as a warning, with
`NOT FULL` or `POSSIBLY INCOMPLETE` in the message, and the job entry marks
the table with `(CHECK)`.

`utils/ratings-check.sql` checks the tables independently against the
snapshots: that every row is the player's newest snapshot, and that no player
whose newest Elo is above the cutoff is missing. It also counts the false
positives that the former scan had to discard.

### gunicorn

The web server's own entries (start-up, a worker booting, `WORKER TIMEOUT`)
are JSON as well, with `logger.name: gunicorn`.

## Getting the log to the log service

App Platform forwards everything a container writes to a log destination that
is named in the app's spec (`log_destinations`, see the reference specs in
`.do/`). The destination is the log intake of the log service's EU site, the
same site that Málstaður uses; the API key is entered into the live spec. No
agent runs in the container.

The platform's forwarder tags each line with the name of the app as its
`source`. A JSON entry's own `service` (the deployment's `PROJECT_ID`) takes
precedence over the service name that the forwarder gives, so the staging
and the production app, whose component has the same name, are told apart by
`service`. Lines that are not JSON get the component's name as their service
and can only be told apart by `source`.

The platform does not encrypt that API key: unlike the environment variables
of type `SECRET`, it comes back in plain text whenever the spec is read. So
every copy of a live spec is a secret. Keep one only in a private temporary
directory while round-tripping, delete it afterwards, and never paste a live
spec anywhere. The key is one that was made for this purpose alone, so that
it can be revoked without touching anything else.

Change the live spec by round-tripping it (`doctl apps spec get`, edit,
`doctl apps update`), never by applying a reference spec. A spec update
starts a new deployment. Do it on the staging app first.

### Metrics and monitors

`utils/datadog-setup.py` creates, or updates, what is built on the entries:

- **Log-based metrics:** request count by status code, request duration by
  path (served requests only), and paywall refusals by reason. They keep
  aggregates for longer than the entries themselves are kept.
- **Monitors:** errors in the log; requests answered with 5xx; a scheduled
  job that failed; a nightly job that did not report success within a day; a
  rating table that is not full or may be incomplete; a subscriber refused at
  the paywall; a worker timeout; restarting workers; slow requests.

Run it without `--apply` to see the definitions, with `--validate` to have
the service check the monitor definitions without creating anything, and with
`--apply` to send them (the last two need the organization's keys in the
environment). Thresholds are changed
in that file, not in the service's UI, so that they are not lost. The
ratings job only runs for Netskrafl: for an Explo backend, give
`--jobs stats,cleanup`, or its absence is reported every day.

Lines that are not JSON also reach the log service, as plain messages: the
entrypoint's start-up lines, the output of the schema migration, and the
moves sidecar.

## Personal data

The entries hold user ids, client addresses, user agents and, for a login
that fails, the e-mail address that was given. They hold no names, no tokens
and no query strings. The log service's EU site is used, and the retention
period there is the one set for its index.

## Adding to the log

- Log through `logging` as elsewhere; attach fields with `log_fields()` when
  somebody may want to search or count the entry.
- A refusal that the client sees as HTTP 200 is noted on the request's entry
  automatically, if it follows the API's conventions (`ok: false` with `err`,
  or a nonzero `result`). Add an entry of its own, as for the paywall, when
  the reason needs the state it was decided on.
- A new scheduled job should end with `log_job()`, and record its run in the
  completions table if it matters whether it ran.
