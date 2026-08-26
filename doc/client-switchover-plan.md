# Client/server switch-over plan

**Status:** server side implemented and on master (PR #143, merged
2026-08-25); client side partially implemented (force-update only).
Companion to `migration-strategy.md`, which owns the hosting and database
cutover; this document owns the *mobile client* side of the same migration:
how the installed base of Explo app clients is moved from the current Google
App Engine backends to the unified Digital Ocean-hosted backend **without
requiring a client release at switch-over time**, and how the cohort of older
clients that cannot be redirected is drained.

## The problem

Every Explo client bakes three backend addresses into its build
(`app.config.js` → `extra` → `apiUrl`, `movesApiUrl`, `movesAccessKey`):

- the main API host (the GAE `explo-live` default service),
- the GoSkrafl `moves` service host (a separate GAE service, called
  directly by the client with a bearer key),
- the bearer key for the moves service.

Clients released before the mechanism described here (≤ 1.4.7) will keep
talking to those addresses for as long as they are installed. Clients released
with it (≥ 1.4.8) can be told to go elsewhere, and can be told to update.
The plan therefore has two halves: a **redirect** path for new clients and a
**drain** path for old ones.

## Server side (implemented)

### Client configuration singleton

A generic JSON config store (`ConfigModel` in `skrafldb_ndb.py` /
`skrafldb_pg.py`; NDB `JsonProperty`, PostgreSQL `configs` table with a
`JSONB` column, Alembic revision `7c3a9e1d4f02`) holds singleton documents
keyed by id. The document with id `app_version` is the client configuration.
Its schema lives in exactly two places — `AppVersionDict` in
`src/db/protocols.py` and `validate_config()` in `src/appversion.py` — so
adding a field is a two-line change with no schema migration.

Fields (all strings, all optional except the first two):

| Field | Meaning |
|---|---|
| `min_supported_version` | Clients below this must update before they can play (**required**) |
| `latest_version` | Latest released client version (**required**) |
| `update_message` | Optional custom text for the update prompt (≤ 1000 chars) |
| `ios_min_supported_version`, `android_min_supported_version` | Per-platform override of `min_supported_version` |
| `ios_latest_version`, `android_latest_version` | Per-platform override of `latest_version` |
| `api_url` | Override of the main API base URL |
| `moves_url` | Override of the moves service base URL |

Validation: versions must match `^\d+(\.\d+){0,3}$`; URLs must start with
`https://` and be ≤ 256 chars; unknown fields are rejected.

### Delivery to the client: `/inituser`

`/inituser` — the bootstrap call every client makes at start-up — returns
two extra keys, both `null` when no configuration record exists:

```json
{
  "app_version": {
    "min_supported_version": "1.4.8",
    "latest_version": "1.4.8",
    "update_message": null
  },
  "endpoints": { "api_url": "...", "moves_url": "..." }
}
```

`app_version` is already resolved for the caller's platform (the session's
`client_type`, `ios`/`android`/`web`), i.e. the per-platform overrides are
applied server-side and the client never sees them. `endpoints` is `null`
unless at least one URL override is set. Results are cached in Redis for
60 seconds (`appversion.load_config()`), so an edit takes effect within a
minute; lookups fail open (a cache or database error yields "no
configuration"), so a backend hiccup can never force-update or redirect
anyone.

### Administration: `/appversion`

Gated by `is_cron_request()`, i.e. the `X-Cron-Secret` header (same secret
as the scheduled jobs; `running_local` bypasses the check in development).

```
GET  /appversion                       → {"ok": true, "config": {...} | null}
POST /appversion  {<full document>}    → validates, replaces the document
POST /appversion  {"delete": true}     → removes it (clients see null again)
```

A POST is a **full replacement**, not a patch: GET first, edit, POST back.
There is no UI; the endpoint is meant to be driven with `curl` by an
operator. The record is per backend project (netskrafl, explo-dev,
explo-live each have their own), and there is no need for one on netskrafl.

## Client side

### Implemented (explo_app ≥ 1.4.8)

`src/context/userContext.tsx` reads `app_version` from `/inituser`: if the
native app version (`react-native-device-info` `getVersion()`) is below
`min_supported_version` — compared with `src/utils/version.ts`, which fails
open on unparsable input — the app shows a blocking update screen with
`update_message` if given. `latest_version` is currently informational.

### Not yet implemented — `endpoints` handling

The client should, on receiving a non-null `endpoints` object:

1. **Validate** each URL: `https://` only, host on a compiled-in allow-list
   of domains the team controls (never accept an arbitrary host from the
   network, even over TLS — the server is trusted, but the allow-list keeps
   a compromised or misconfigured record from hijacking clients).
2. **Persist** the accepted URLs in AsyncStorage and use them for all
   subsequent requests, *including the next cold start before `/inituser`
   has answered*. Baked-in URLs remain the fallback when nothing is stored.
3. **Retry through the fallback**: if the stored override fails at start-up
   (connection refused, TLS error, non-2xx on `/inituser`), fall back to the
   baked-in URLs for that session and re-fetch the configuration from there.
   This makes a wrong record recoverable without a client release.
4. Switch the moves calls to the main API host's `/moves` route, which is
   session-authenticated (the `movesAccessKey` bearer key is then no longer
   needed by the client). A `moves_url` override remains useful only while
   some clients still call a bearer-keyed moves service directly; whatever
   host it points at must accept the baked-in key.

A **second, independent channel** for the same override — a Firebase RTDB
node the client already subscribes to — is worth adding as belt-and-braces:
`/inituser` cannot deliver a redirect if the old API host is *already*
unreachable. The RTDB project and credentials are baked into the client and
are unaffected by the hosting move. Same allow-list and persistence rules
apply.

## The switch-over itself

Three levers, used in this order:

1. **Vanity hostname (primary).** Release the ≥ 1.4.8 clients with the
   baked-in API and moves URLs pointing at a hostname on a domain the team
   controls, initially resolving/proxying to the GAE services. The DO
   cutover is then a DNS or proxy flip that no client notices. Prerequisites
   on the server side: the same Flask `SECRET_KEY` and cookie domain on both
   backends so sessions survive the flip, the same moves bearer key on
   whichever host serves the legacy direct moves calls, and TLS on the new
   host before the flip.
2. **In-app override (fallback).** If, for any reason, the vanity hostname
   cannot carry the switch (certificate problems, a domain that has to
   change), set `api_url`/`moves_url` via `POST /appversion` (and/or the
   RTDB node). Clients pick it up on their next start within ~1 minute of
   the cache expiring.
3. **`min_supported_version` (drain lever).** Once the new backend is the
   only one that should be used, raise `min_supported_version` past the
   last version that still has hardcoded appspot.com URLs. Anyone on an
   older client gets the update screen instead of a silently degrading app.
   Use `update_message` to explain why.

### Draining the pre-1.4.8 cohort

Clients that predate the mechanism cannot be redirected at all — they will
hit the GAE `explo-live` default service and the GAE moves service at their
appspot.com URLs until they are updated or abandoned. Therefore:

- Both GAE endpoints stay up **as thin proxies** to the DO backend for the
  duration of the drain (expected: several months; watch the GAE request
  logs by user-agent/version to decide when it is over). The proxy keeps
  those users on live data rather than a frozen copy of the database.
- The pre-1.4.8 cohort also does not honour `min_supported_version`, so the
  only way to move them is the app stores' own update pressure (and, at the
  end, switching the proxies off). Prioritise getting 1.4.8 into users'
  hands, because every install after it is drainable.
- Decommissioning order at the end: GAE moves service → GAE default service
  (the same milestone as Phase F in `migration-strategy.md`).

## Operating recipe

Replace `<host>` with the backend being configured and `<secret>` with its
`CRON_SECRET` (never commit either).

```bash
# Read
curl -s https://<host>/appversion -H "X-Cron-Secret: <secret>"

# Set (full replacement)
curl -s -X POST https://<host>/appversion \
  -H "X-Cron-Secret: <secret>" -H "Content-Type: application/json" \
  -d '{"min_supported_version": "1.4.8", "latest_version": "1.4.8"}'

# Redirect clients (same call, add the URL overrides)
#   ... "api_url": "https://<new-api-host>", "moves_url": "https://<new-api-host>" ...

# Remove the record entirely
curl -s -X POST https://<host>/appversion \
  -H "X-Cron-Secret: <secret>" -H "Content-Type: application/json" \
  -d '{"delete": true}'
```

Current values: the DO staging backend (explo-dev project) has
`min_supported_version = latest_version = 1.4.8`, no URL overrides
(set 2026-08-25, matching the unreleased explo_app 1.4.8). explo-live and
netskrafl have no record.

## Tests

- `test/test_inituser.py` — `/inituser` output with and without a record,
  per-platform resolution, `endpoints`, and `/appversion` auth/validation/
  update/delete.
- `tests/db/test_config_repository.py` — the generic config store on both
  backends (`--backend=both --import-mode=importlib`).

## Open items

- [ ] `endpoints` handling in `explo_app` (allow-list, AsyncStorage,
      fallback-on-failure) — must ship in 1.4.8 or the next release for
      lever 2 to exist at all.
- [ ] RTDB override node (schema + client subscription).
- [ ] Choose and provision the vanity hostname; point 1.4.8's baked-in URLs
      at it before release; align `SECRET_KEY`/cookie domain across backends.
- [ ] Proxy configuration on the GAE default and moves services for the
      drain period.
- [ ] Decide on a per-version request-log metric to declare the drain over.
