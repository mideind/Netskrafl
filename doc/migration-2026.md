# The 2026 migration: what was done and what it taught us

In 2026 the backend moved from Google App Engine and Cloud Datastore (NDB)
to containers with managed PostgreSQL. This note keeps the outline and the
lessons; the plans, designs and rehearsal logs that led up to it are in the
git history of `doc/` (up to November 2026). How things run now is in
`operations.md`. Operational specifics were never kept in this repository.

## Outline

| When | What |
|---|---|
| January 2026 | The backend first runs in a container, still on Datastore: hosting can move independently of the database |
| Spring and summer | A PostgreSQL backend is built next to the NDB one, behind shared protocols (`src/db/`), with tests that run on both |
| 2026-08-18 | The Explo development backend (the staging app) switches to PostgreSQL |
| 2026-09 | Rehearsal copy of Explo's production data; the Explo app gets its endpoint-override mechanism (`operations.md`) |
| 2026-11-04 | Netskrafl's Firebase Realtime Database moves to an EU instance |
| 2026-11-13 | Netskrafl production switches: hosting and database together |
| 2026-11-20 | Explo production switches |
| 2026-11-26 | First clean-up: Datastore archived, Netskrafl's old App Engine backend deleted, the old Realtime Database instance emptied, Explo's public API hostname pointed straight at the container |

Netskrafl went before Explo because its only client is one web application
that reaches the backend through a single hostname, with no app-store
clients to wait for. For Netskrafl the hosting and the database had to
switch together: its Datastore was on another continent than the new
hosting, and a database call per request across the ocean was not an
option.

## The method, in short

1. **Two backends behind one contract.** Application code kept importing
   `skrafldb`; a facade selected NDB or PostgreSQL. Repository tests ran on
   both backends and had to agree.
2. **A migrator that reads through the application's own model layer**
   (`scripts/migrate_to_postgres.py`): a bulk copy days ahead with no
   freeze, then a short delta pass inside the freeze.
3. **Verification on a copy** of the migrated database: the API tests, a
   replay of sampled production games move by move, and a sweep that loaded
   every user and every game through the app's own loaders
   (`scripts/decode_sweep.py`).
4. **The freeze as a traffic switch.** A version of the old backend built
   with `MAINTENANCE` set (`src/maintenance.py`), deployed ahead of time
   without traffic, answers 503 to everything; routing traffic to it freezes
   writes, and routing it back unfreezes.
5. **The opening.** For Netskrafl: the hostname added to the new app, then
   its DNS record changed. For Explo, whose apps have the App Engine address
   built in: App Engine's traffic routed to a small reverse proxy
   (`appspot-forward/`) that passes every request on to the new backend.
6. **A script for the night.** Each production switch ran unattended from a
   script that had been rehearsed against a temporary hostname, including
   runs with forced failures to exercise its own undo steps. Each took
   under a quarter of an hour of freeze.

## Lessons

### Migrating the data

- **Decode with the code that wrote the data.** The migrator fetched
  entities over Datastore's REST API and handed them to the NDB model
  classes, so compressed properties, embedded move lists and a decade of
  schema drift were handled by the code production used. A managed export
  was taken only as an archive, never parsed.
- **REST, not gRPC, and processes, not threads.** The gRPC client was
  several times slower and did not scale with parallel workers. Decoding
  turned out to be CPU-bound (protobuf's JSON layer and timestamp parsing),
  so threads gave one busy core; one worker process per key-range shard gave
  a fifteen-fold speed-up.
- **Make every run idempotent and resumable.** Upserts everywhere,
  checkpoints stored in the target database in the same transaction as each
  batch, deterministic UUIDs (version 5, from the Datastore key path) for
  kinds whose tables have UUID keys, so that a delta pass lands on the rows
  of the bulk copy. Persist the start time of the first bulk attempt: a
  resumed run must not report its own start as the baseline for the delta.
- **The delta pass needs a field that really moves.** Games were selected by
  their last-move timestamp, which is indexed and set at creation; but the
  nightly statistics job writes Elo results into finished games without
  touching it, so the delta took a window two days wider than the gap.
  Users had no last-modified field at all and were re-read in full. A
  property that is not indexed is silently absent from queries that filter
  or sort on it.
- **Decide what a missing reference means before repairing it.** A null
  player means "the robot", so nulling a player whose user had been deleted
  turned a human game into a robot game. Such games were skipped and
  logged instead.
- **Datastore's implicit behaviour has to be made explicit.** An ordered
  Datastore query leaves out entities that lack the property; in SQL, rows
  with NULL sort first unless excluded, and a few thousand ancient games
  would have headed every player's list. Datastore also sorts strings by
  code point, and it held duplicates (the same favourite or block stored
  twice) that a unique key refuses.
- **Bulk takes hours, the delta minutes.** Ten million games took a night;
  the delta pass took under ten minutes, which is what bounded the freeze.
  Reading Datastore at that rate did not disturb production (a watchdog
  that compared production with a baseline never fired).
- **Run the write-heavy verification on a copy,** and with a development
  project's configuration: not every API test stubs out Firebase, and a
  test game would otherwise send notifications to a production Realtime
  Database.
- **An export can only go to storage in the database's own location.**

### Keeping two backends the same

- **Parity tests only find what they seed.** An audit by reading both
  implementations side by side found a dozen divergences that the shared
  tests had passed, because no test had a user as the second player,
  several statistics snapshots per user, long chat messages, or more rows
  than a limit. `tests/db/test_backend_parity.py` now seeds those.
- **Query plans differ at production size.** An `OR` across the two player
  columns could not use the per-player indexes and took seconds for busy
  users; one ordered, limited branch per column, merged, takes
  milliseconds. Check new hot queries with `EXPLAIN` on a production-size
  copy.
- **Re-run a batch job on a copy and compare.** The nightly statistics job
  was re-run on PostgreSQL for a day that App Engine had processed, and its
  rows compared one by one.
- **Managed databases restart.** A maintenance update dropped every pooled
  connection; the pool now checks a connection before use, and a failed
  connect is retried for a while (`ConnectRetry`).

### The switch

- **Clients must see the freeze as "server unreachable".** They treat a
  status of 500 and above that way and offer a retry; a 404 they treat as
  an error. So the freeze answers 503, and the order of steps was chosen
  so that no 404 phase could occur.
- **Never let a scheduled job run on both sides for the same day.** The new
  app's scheduler was switched on (by setting `CRON_SECRET`) only after the
  old side's nightly jobs had run, shortly before the freeze.
- **Hostname first, DNS second.** With the hostname already in the app's
  spec, the app answered within seconds of the DNS change. In the other
  order the platform answers 404 for the hostname for most of a minute.
  The platform's edge network also hosts the DNS zone and serves the zone's
  wildcard certificate until the app's own arrives, so there is no
  certificate gap, provided the hostname is a single level below the zone.
- **The new path cannot be tested under the real name beforehand.** A
  request for the hostname sent straight to the new app's address is
  routed by the zone's current DNS record, that is, to the old backend. The
  DNS change itself is the first real test; keep the TTL short and the old
  side answering.
- **One spec update at a time.** After a hostname's DNS points at the app,
  the platform finishes its own work on the domain, which took between one
  and six minutes on different occasions and may include a deployment of
  its own. A spec update sent meanwhile cancelled that deployment and left
  routing out of step with the spec. Wait until no deployment is in
  progress and the domain is active.
- **Attaching a database to an app in its spec does not open the database's
  firewall to it.** The app must be added to the database's trusted sources
  separately.
- **A reverse proxy is a calm way to move clients that cannot be told
  anything.** The forwarder is stateless and depends on nothing but an HTTP
  client; a request through it costs a few tens of milliseconds. Session
  cookies without a domain bind to the address the client used, so they
  kept working. It stays until the request log says nothing uses it.
- **Freeze at night for apps that punish a failed login.** The Explo app
  discards its stored login when a login fails, so a user who starts the
  app cold during a freeze is signed out.
- **Clients hold keys from before the switch.** An app with a list of
  challenges loaded before the switch sent Datastore's keys back
  afterwards; the new backend expected UUIDs and failed. A key that cannot
  be parsed now means "not found", as it did on Datastore.
- **A notification must not overtake its transaction.** With a session
  committed at the end of the request, a Firebase notification sent in the
  middle reached the client before the data did, and the client re-read the
  old state. Hence `skrafldb.on_commit()`. Notifications also moved off the
  request's own thread, after a slow Firebase call had held one for
  seconds.
- **The rollback window closes with the first writes.** Going back to the
  old backend would have lost everything written since the switch, so
  after the first day the old side was a fallback in name only. Decide
  early when it is deleted; until then it costs money and invites mistakes.

### Moving a Realtime Database instance

Netskrafl's instance was moved to another region ahead of the main switch:

- **Copy only what clients read back.** Notification nodes and presence are
  write-and-forget (clients ignore the value they get on first attach), so
  only the Gáta dagsins subtree, whose stored values clients display, was
  copied (`scripts/rtdb-move-gatadagsins.sh`: export, import, verify, and a
  diff that lists what was written to the old instance afterwards).
- **Make each server version self-consistent.** The address came from an
  environment variable of the new version while the stored secret kept the
  old one, so moving traffic was the switch and moving it back the
  rollback.
- **A web client with the address compiled in switches by promoting a build
  prepared in advance,** from the commit already in production. Check its
  Content Security Policy first: regional instances live under another
  domain than the original ones.
- **Old pages keep listening to the old instance.** Three weeks later a few
  clients still attached to it. They get no live updates; nothing else
  breaks.
- **Empty the old instance in batches** (`utils/rtdb-cleanup.py --wipe`),
  never with one delete of a large subtree, which locks the database; then
  set rules that deny everything. A project's default instance cannot be
  deleted.

### Running in a container

- **The platform keeps little log, and none of a replaced container.** The
  log is forwarded to a log service, structured, with the user's id on
  every request and a reason on every refusal (`logging.md`).
- **The platform delivers some log lines more than once.** Monitors must
  not count entries where one entry would do.
- **A deploy is normal operation and must not raise an alert.** The monitor
  on server starts is muted for the duration of each deploy.
- **The builder is not the one on the developer's machine** (see the build
  gotcha in `CLAUDE.md`).

## What is left of the tooling

`scripts/migrate_to_postgres.py`, `scripts/decode_sweep.py` and
`scripts/rtdb-move-gatadagsins.sh` did their work and stay only until the
NDB backend is removed (`operations.md`, "Still to do"). The maintenance
mode, the forwarder and the redirect app are still in use or may be needed
again.
