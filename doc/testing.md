# Testing

What test suites exist, what each one needs and what it shows. The commands
and their environment variables are in `CLAUDE.md` ("Testing").

## The suites

| Suite | What it tests | Database | Needs |
|---|---|---|---|
| `test/` | The API through Flask's test client: logins, chat, blocking, favourites, images, Elo, account deletion, `/inituser`, maintenance mode, the Málstaður login, riddle validation, the Realtime Database clean-up, and the built-in web UI's routes | Whichever backend `DATABASE_BACKEND` selects. Without it: the development project's Datastore | Credentials of a Google Cloud project, a local Redis |
| `tests/db` | Every repository of the database layer (`src/db/`), one module per repository, plus the parity regressions and `on_commit` | `--backend=ndb` (the default), `postgresql` or `both`; `--compare` runs an operation on both and compares the results | For PostgreSQL: a local throwaway database (`DATABASE_URL`, default in `src/db/config.py`). Run with `--import-mode=importlib` |
| `tests/api_e2e` | Whole flows through the real Flask app: login and preferences, a game against a robot and against a human, challenges, chat, lists and ratings, the paywall, game review, user management, the admin operations, the log entries | PostgreSQL only; the suite resets the tables of its database at the start | The same local database. `E2E_KEEP_TABLES=1` skips the reset, to run against a copy of real data |
| `test/test_replay.py` | Replays sampled production games (the JSON fixtures in `test/replay_fixtures/`, made by `utils/sample_replay_games.py`) move by move through `/initgame` and `/submitmove`, and requires the same legality, scores, challenge verdicts and final result as the original | The selected backend | Marked `slow` and deselected by default: run with `-m slow` |
| `utils/staging-check.py` | The standard test of a release on the staging app, over HTTPS as a client would: see the `/deploy` skill | The staging app's own | It only works against the development backend and refuses any other |

Type checking is part of the routine: `venv/bin/pyright src/`.

## Things to know

- **Not every test stubs out Firebase.** `tests/api_e2e` has a mock
  (`mock_firebase`) that the tests of notifications use, but a test without
  it, and the `test/` suite, send real notifications to the Realtime
  Database of the project they run as. Run the suites with the development
  project's configuration only. Run as a production project, they would
  notify that product's production Realtime Database and, on the NDB
  backend, write into the Datastore that is kept as the archive of the data
  before the move.
- **`test/test_moves.py` goes over the network** to the GoSkrafl `moves`
  service, because no sidecar runs in the test environment. It also checks
  that the Python engine and GoSkrafl generate the same moves.
- **`test/test_concurrency.py`** races conflicting `/submitmove` requests
  for one game (a retried move, two moves under the same move count, a move
  out of turn): exactly one may be applied. On PostgreSQL this exercises the
  row lock in `submit_move()`.
- **Multi-locale tests need the development project's configuration**; with
  the Netskrafl configuration only Icelandic exists and they fail.
- **Tests that write run on a throwaway database or on a copy**, never on a
  deployed database.
- **The parity tests in `tests/db` only find what they seed.** When adding a
  repository method, seed the conditions under which two implementations
  could differ: the user as second player, several rows per user, more rows
  than a limit, long texts, malformed keys.
- **A new query on a hot path** should be checked with `EXPLAIN` on a
  production-size copy of the database; the test database is too small to
  show a bad plan.
- There is no continuous integration: the suites are run by hand, and the
  staging app is the gate before production.

## When the NDB backend is retired

`tests/db` loses its `--backend` and `--compare` options and the comparison
tests; `test/` runs on PostgreSQL only and no longer needs Datastore
access. Until then, `--backend=both` is how a change to the database layer
is shown to behave the same on both.
