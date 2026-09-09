# Client/server switch-over plan

**Status:** server side implemented and on master (PR #143, merged
2026-08-25); client side implemented on the `explo_app` branch
`feat/server-endpoints` (first written 2026-09-01, lost unpushed in the
2026-09-05 disk failure, re-implemented from this document 2026-09-09;
see the client repo's `doc/server-endpoints.md`), pending review/merge
and release; vanity domain chosen and provisioned 2026-09-09 (see
"Vanity hostnames: decision and state" below).
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

### Implemented — `endpoints` handling (2026-09-01, branch `feat/server-endpoints`)

Implemented in `src/api/endpoints.ts` (stateful manager; `API_URL` /
`MOVES_API_URL` are live bindings) and `src/api/endpointConfig.ts` (pure
validation logic, unit-tested); documented in the client repo's
`doc/server-endpoints.md`. Behavior, refining the original sketch:

1. **Validation**: URLs must be plain `https://` origins (no path, query,
   fragment or credentials; stricter than the server-side validator), and
   the host must be one of the baked-in hosts or equal to / a subdomain of
   a suffix in `ENDPOINT_ALLOWLIST`, an optional array in the (untracked)
   `appsIds.json` — so the allow-list ships inside the build without the
   domains appearing in either source tree. The server is trusted, but the
   allow-list keeps a compromised or misconfigured record from hijacking
   clients. Rejections are reported via analytics (see Monitoring below),
   so a missing allow-list entry is visible, not silent.
2. **Persistence**: accepted overrides are stored in AsyncStorage and
   re-validated on every load; all requests await the load, so an override
   applies from the first request of the next cold start.
3. **Fallback**: after 3 consecutive *network-level* failures (no HTTP
   response at all — any status code counts as reachable) while an
   override is active, the client reverts to the baked-in URLs and clears
   the stored override. If the override was actually fine (device merely
   offline), the next successful `/inituser` re-applies it — a
   self-healing loop that makes a wrong record recoverable without a
   client release. A successful `/inituser` *without* `endpoints` also
   clears any active override: that is the mechanism's built-in
   retirement path once the vanity hostname points at the new backend.
4. **Moves routing**: the moves-on-main-host decision (`moves_url` empty
   or equal to the API URL ⇒ session-authenticated `/moves` on the main
   host, no bearer key) is evaluated per request, so the two services can
   be moved independently. A `moves_url` override pointing at a dedicated
   moves host must accept the baked-in bearer key.

The **second, independent channel** — needed because `/inituser` cannot
deliver a redirect if the old API host is *already* unreachable — is a
Firebase RTDB node, `client_config/endpoints`, holding the same JSON shape
as the `/inituser` `endpoints` field and subject to the same allow-list
and persistence rules. The client reads it at most once per session, only
after the baked-in host has also failed at the network level. The RTDB
project and credentials are baked into the client and unaffected by the
hosting move. **Server-side prerequisite, not yet done:** the node must be
world-readable in the Firebase security rules — a client that cannot
reach the backend cannot obtain a Firebase custom token — and an operator
procedure for writing it is needed. Until then the read fails harmlessly.

### Monitoring

The client emits Mixpanel + Firebase Analytics events sized for migration
dashboards (host names only, never full URLs): `endpoints_in_use` (once
per sign-in: `api_host`, `moves_host`, `override`, version, OS — the
primary fleet-population-by-backend metric), `endpoint_applied`,
`endpoint_rejected` (misconfiguration alarm), `endpoint_fallback`
(new-backend health), `endpoint_rescue` (should stay at zero), plus
`force_update_shown` (drain-lever effect) and `update_available`
(upgrade lag).

## Vanity hostnames: decision and state (2026-09-09)

**Domain: `explowordgame.com`.** It is the product domain, and every Explo
binary ever shipped already depends on it (website, help and policy
pages, share links: ~50 references in the client source), so hosting the
API there adds no new long-term liability. DNS moved from Namecheap's
registrar DNS to Cloudflare (same account as `mideind.is`) on
2026-09-09; the registration stays at Namecheap. All records are DNS-only
(unproxied).

| Host | Target | State |
|---|---|---|
| `api.explowordgame.com` | GAE explo-live (custom-domain mapping, managed cert; CNAME `ghs.googlehosted.com`) | **live 2026-09-09**: certificate issued and served, `/health/ready` OK over HTTPS |
| `api-dev2.explowordgame.com` | DO staging app (`ALIAS` domain) | live 2026-09-09; exists only as a redirect target for rehearsals of lever 2 |
| `api-dev.explowordgame.com` | DO staging app (`PRIMARY` domain in the app spec; CNAME to the app's default ingress) | **live 2026-09-09**: `/health/ready` OK over HTTPS, certificate auto-renewed by App Platform |

Client side: `ENDPOINT_ALLOWLIST = ["explowordgame.com", "mideind.is"]`
in both ID files; the dev file's baked-in `API_URL` is now the `api-dev`
host and the live file's `API_URL` is the `api` host (both set 2026-09-09). Leave `moves.explowordgame.com` unregistered until
a dedicated moves host is ever needed again.

## Vanity hostname strategy (2026-09-01)

The vanity hostname is the name that eventually gets baked into clients as
the *baseline* URL, so it must outlive every hosting (and branding)
decision. The principles and mechanics are:

### Naming

- **Product domain over company domain.** Hostnames inside years-old
  installed clients are the same kind of liability as `appspot.com` today
  if the product is ever rebranded, spun out or sold. The team owns
  several product domains; pick the one it would be happiest still owning
  in ten years, and host it at the same DNS provider as the company
  domain (moving a domain there is about an hour of work and free).
- **Service-descriptive, implementation-free names**: `api.<domain>` for
  the main backend, `moves.<domain>` for a dedicated moves host if ever
  needed again, `api-dev.<domain>` for the dev-project backend. Nothing
  that encodes the provider, generation or migration (`gae-`, `do-`,
  `v2`, `new-`) — those are the names one migrates away from next time.
- **Single-level subdomains only.** The DNS provider's free universal
  wildcard certificate covers one label (`*.<domain>`), not two
  (`a.b.<domain>`); deeper names require a paid certificate tier. If the
  company domain were used instead, the equivalent single-level pattern
  would be `<product>-api.<company-domain>`.
- **The web game needs no vanity host.** Browsers follow DNS; its
  user-facing domain *is* the vanity domain, and its cutover is a plain
  DNS repoint of the apex (lower the TTL beforehand). The vanity-hostname
  machinery exists for the mobile app because its URLs are baked into
  binaries.
- **Allow-list both domain families** in the client's
  `ENDPOINT_ALLOWLIST` (product domain and company domain) — costs
  nothing and preserves the option to redirect clients to either later
  without a release.

### Implementation phases

1. **Now (GAE as origin):** create the hostname as a **DNS-only
   (unproxied) CNAME** to the GAE app, with a GAE custom-domain mapping
   so Google provisions and renews the certificate. Unproxied matters:
   GAE-managed certificates fail issuance/renewal behind a CDN proxy
   (Google must see its own IPs). Set the TTL to 60 s. Ship the next
   client release with this hostname as the baked-in `API_URL` (and the
   allow-list populated); from that release on, clients have no
   dependency on `appspot.com`.
2. **At cutover:** add the custom domain to the DO app (App Platform
   issues its own certificate), then flip the CNAME. With a 60 s TTL the
   flip lands in minutes, with two independent safety nets underneath:
   the `/inituser` `endpoints` override (lever 2) and
   `min_supported_version` (lever 3). Watch `endpoints_in_use` segmented
   by `api_host` to see the flip propagate across the fleet.
3. **Post-cutover (optional):** turn the record proxied ("orange-cloud")
   for origin hiding, HTTP/3 and instant future flips. Two API-breaking
   proxy defaults must be handled first: a cache rule that bypasses the
   API hostname entirely (a cached `/inituser` would be poisonous), and
   bot-challenge features disabled for it (a challenge page served to
   the app's HTTP client bricks the app).

**Rejected: proxy-level gradual traffic splitting** (worker/load-balancer
percentage canary between GAE and DO). It would require both fleets to
serve the *same* database — i.e. DO running `DATABASE_BACKEND=ndb` —
and would create two incoherent NDB caches (GAE's Redis vs. DO's Valkey)
over one Datastore, a genuine correctness hazard. The dev-project
rehearsal (publish the DO URL via `/appversion` on explo-dev first,
against dev builds) is the canary instead.

**Session-cookie nuance.** Cookies are host-scoped. A pure DNS flip keeps
the hostname, so sessions survive provided both backends share the Flask
`SECRET_KEY`. An `endpoints` *override* changes the hostname, so the
first request 401s and the app re-authenticates automatically (401s are
the expected-and-handled case in the client's request layer) — expect a
brief blip of 401s and sign-in events when publishing an override, and
do not mistake it for breakage.

## Rehearsal on explo-dev (done 2026-09-09)

Run with a `developmentRelease` build of the client (branch
`feat/server-endpoints`, baked-in `api-dev.explowordgame.com`) on a
headless emulator on the dev box, driving the record through
`/appversion` on the DO staging backend:

- **Baseline:** guest sign-in and `/inituser` succeed on the vanity host;
  no override applied.
- **Lever 2 (redirect):** `api_url = https://api-dev2.explowordgame.com`
  (a second alias of the staging app, provisioned for this). `/inituser`
  delivered it; the device persisted it (`@server-endpoints` in
  AsyncStorage); a packet capture of the next cold start showed every TLS
  connection going to `api-dev2` and none to `api-dev`.
- **Retirement:** removing `api_url` from the record cleared the stored
  override on the next cold start.
- **Fallback:** `api_url = https://nowhere.explowordgame.com` (allow-listed,
  unresolvable): the override was applied, the next three requests failed
  at the network level, the override was dropped and removed from storage,
  and the fourth request succeeded on the baked-in host.
- Not exercised on a device: the Firebase rescue read (covered by unit
  tests; the node's anonymous readability is verified separately).

The staging `CRON_SECRET` was regenerated for this (the old value was
lost with the dev box's disk); it lives in `~/.config/netskrafl-staging.env`
on the dev box.

## The switch-over itself

Three levers, used in this order:

1. **Vanity hostname (primary).** Release the ≥ 1.4.8 clients with the
   baked-in API and moves URLs pointing at a hostname on a domain the team
   controls (see the strategy section above), initially resolving to the
   GAE services. The DO cutover is then a DNS flip that no client notices.
   Prerequisites on the server side: the same Flask `SECRET_KEY` on both
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

- [x] `endpoints` handling in `explo_app` (allow-list, AsyncStorage,
      fallback-on-failure) — on branch `feat/server-endpoints`
      (re-implemented 2026-09-09 after the original was lost); must ship
      in 1.4.8 or the next release for lever 2 to exist at all. Remaining:
      push the branch, review/merge, and put the `ENDPOINT_ALLOWLIST`
      values into `appsIds.json`/`live-appsIds.json` (both files also
      need recreating on the rebuilt dev box).
- [x] RTDB override node `client_config/endpoints` — client read side
      implemented; security rules published on explo-live and explo-dev
      2026-09-09 (`.read: true` on that node only; verified: anonymous
      read of the node returns the value, the parent, other nodes and
      writes are denied). **Node values written 2026-09-09:** explo-dev
      `{"api_url": "https://api-dev.explowordgame.com"}`, explo-live
      `{"api_url": "https://api.explowordgame.com"}` (no `moves_url`, so
      the baked-in moves routing stays in force). Operator procedure
      (owner token bypasses the rules; `$DB` is the project's RTDB URL):

      ```bash
      TOKEN=$(gcloud auth print-access-token)
      curl -X PUT "$DB/client_config/endpoints.json?access_token=$TOKEN" \
        -d '{"api_url": "https://<new-api-host>"}'
      curl "$DB/client_config/endpoints.json"     # anonymous read-back
      curl -X DELETE "$DB/client_config/endpoints.json?access_token=$TOKEN"
      ```
- [x] Choose and provision the vanity domain/hostnames — done
      2026-09-09, see "Vanity hostnames: decision and state" above.
      Both hosts live and baked into the ID files. Remaining: align
      `SECRET_KEY` across backends before the DNS flip.
- [ ] Proxy configuration on the GAE default and moves services for the
      drain period.
- [ ] Decide on a per-version request-log metric to declare the drain
      over (the `endpoints_in_use` analytics event provides the
      complementary fleet-side view).
