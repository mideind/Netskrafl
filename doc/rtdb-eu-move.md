# Moving Netskrafl's Realtime Database to the EU

In November 2026 the Firebase Realtime Database of the Netskrafl project was
moved from its original US instance to a new instance in an EU region
(europe-west1). This note records how it was done, so the method can be reused,
and what remains to be done. Operational specifics (URLs, versions, accounts)
are kept out of this public repository on purpose.

## Background

A review of hosting regions for GDPR purposes found the Netskrafl project
hosted entirely in the US, while the Explo projects are in the EU. App Engine
and Datastore regions are fixed per project, so those move with the container
migration (`doc/migration-strategy.md`). The Realtime Database can move on its
own, and its `gatadagsins/` subtree holds lasting personal data (user stats,
streaks, achievements). Strict EU hosting is not required (transfers to Google
rely on the EU-US Data Privacy Framework and standard contractual clauses), so
the move reduces risk rather than fixing a violation.

## What was copied, and why so little

Only `gatadagsins/` (about 10 MB) was copied. `game/` (over 1 GB of move and chat
notifications going back years), `user/` and `connection/` were not:

- Both web clients (Netskrafl's `static/src` and Málstaður's `netskrafl-react`)
  ignore the value they receive on first attach to `game/{id}/{uid}/move`,
  `game/{id}/{uid}/chat` and `user/{uid}`; they act only on later changes.
  Games, chat and subscriptions live in the database of record.
- Presence (`connection/`) re-registers on connect.
- The server reads back only `user/{uid}/wait/{opp}`, a short-lived marker for a
  pending timed-game challenge. Anyone waiting at the switch re-issues it.

Gáta dagsins is different: clients use the stored values (leaderboards, best
scores, stats, achievements) and the server updates them in transactions.
`scripts/rtdb-move-gatadagsins.sh` copies that subtree (`export`, `import`,
`verify`) and afterwards lists anything written to the old instance since the
export (`diff`).

The security rules were copied to the new instance unchanged before any data.

## How the URL reaches each consumer

| Consumer | Source of the URL | Takes effect |
|---|---|---|
| Netskrafl server (Firebase Admin SDK, `src/firebase.py`) | the environment variable `FIREBASE_DB_URL` if set (`app-netskrafl.yaml`), otherwise `FIREBASE_DB_URL` in the client secret, read once at import (`src/config.py`) | per App Engine version (environment variable), or when an instance starts (secret) |
| Netskrafl web pages (`templates/firebase.html`) | the same value, passed into the template | pages served by that version |
| Málstaður (Netskrafl and Gáta dagsins) | `NEXT_PUBLIC_FIREBASE_DB_URL` at build time, else a constant in its Netskrafl auth hook | the next build |

## The approach

**The server switches by moving traffic to a new App Engine version.** The
environment variable overrides the secret, and the new version sets it to the
new instance while the secret keeps the old URL. Each version is therefore
self-consistent whenever its instances start: moving traffic is the switch, and
moving it back is the rollback. An alternative was rejected: changing the
secret and restarting instances leaves a window in which a newly started
instance of the old version picks up the new URL, and it relied on instance
deletion behaving as expected under basic scaling.

**Málstaður switches by promoting a staged production build.** Its URL is fixed
at build time, so a production build was made from the exact commit already in
production, with the new URL given as a build-time variable and without
assigning the domain (`vercel deploy --prod --skip-domain --build-env ...`). At
the switch it was promoted (`vercel promote`), which takes seconds and needs no
rebuild. The code constant was then changed through the normal PR flow, so the
next regular release keeps the new URL.

## Preparation

1. Create the new instance and copy the security rules.
2. Check that every client can reach it: the Admin SDK used by the server and
   the web SDK versions used by the Netskrafl pages and by Málstaður.
   `.info/connected` must come back true and unauthenticated reads must be
   refused.
3. **Check Málstaður's Content Security Policy.** It is enforced and allowed
   only the legacy `*.firebaseio.com` hosts; regional instances live under
   `*.firebasedatabase.app`, which had to be added to script-src, connect-src
   and frame-src and released before the switch. Netskrafl's own pages send no
   CSP.
4. Deploy the new App Engine version without traffic (`--no-promote`) and check
   its environment and startup logs.
5. Build the staged Málstaður deployment shortly before the switch, and test it
   in a browser: the WebSocket must go to the new instance. Creating and
   promoting production deployments needs an Owner role in the Vercel team, and
   logging in on a staged production deployment needs its hostname temporarily
   on the production auth provider's redirect allowlist (previews use the
   staging one, which accepts preview hostnames). Remove that entry afterwards.
6. Agree on a short **release freeze** for Málstaður: no merges to main from
   building the staged deployment until the URL change is merged into staging.
   After that, every release carries the new URL, because release PRs have the
   staging branch itself as their head.

## The switch

Steps 1 to 3 back to back, at a quiet hour:

1. Copy Gáta dagsins: `scripts/rtdb-move-gatadagsins.sh export`, `import`,
   `verify` (must report a match).
2. Move all App Engine traffic to the new version in one step
   (`gcloud app services set-traffic default --splits <new version>=1`).
3. Check that Málstaður production is still at the commit the staged build was
   made from, and that no production deployment is building or queued (a build
   that finishes after the promote takes the domain and brings back the old
   URL). Then `vercel promote <staged deployment>` with the team as scope.
4. Verify: no errors on the new version, the Málstaður WebSocket goes to the new
   instance, `connection`, `game` and `user` writes appear on it, Gáta dagsins
   shows leaderboards and personal stats, and moves and chat update live.
5. `scripts/rtdb-move-gatadagsins.sh diff`: merge any Gáta dagsins writes made on
   the old instance since the export.
6. Merge the Málstaður URL change into staging, which ends the freeze; the next
   release takes it to main.

The switch itself took about four minutes. The App Engine and Málstaður sides
were out of step for about half a minute, longer than planned because the first
promote ran under the wrong Vercel scope. Open tabs keep listening to the old
instance until they are reloaded.

## Rollback

1. Move App Engine traffic back to the previous version. It reads the URL from
   the secret, which still names the old instance.
2. Roll Málstaður back to the previous production deployment, and revert the URL
   change in staging. **A Vercel rollback turns off automatic promotion of
   production deployments**, so later releases stay staged until one is
   promoted again; tell whoever releases Málstaður.
3. Copy Gáta dagsins written on the new instance back to the old one (the same
   export and diff method, in the other direction).

The old instance is left intact until follow-up F1, so a rollback loses nothing
else.

## Follow-ups

- F1. After about two weeks, make the old instance read-only (`.write: false`),
  then delete its data in chunks (`firebase database:remove`, never one delete of
  `game/`, which would lock the database for a long time) and set deny-all rules.
  The default instance itself cannot be deleted. Delete the local exports and
  secret copies at the same time.
- F2. Add a nightly purge of `game/{id}` nodes for finished games (game IDs are
  version 1 UUIDs, so a node's age is in its key), so the new instance does not
  build up years of notifications again.
- F3. Find out why presence entries go stale (very old entries under
  `connection/`), since `get_connected_users()` counts every key.
- F4. Check the rules file into the repo.
- F5. Configure the new URL for the planned container deployment
  (`doc/migration-strategy.md`).
- F6. Once a rollback is no longer wanted (about a week): set the new URL in the
  client secret too, so deployments without the override get it, then delete the
  previous App Engine version. The override in `app-netskrafl.yaml` can stay or go.
- [x] F7. Remove the temporary redirect allowlist entry (done at the switch).

A backend-supplied database URL for Málstaður was considered and set aside:
`netskrafl-react` can start Firebase from cached session settings without a fresh
login response, so it would not avoid stale tabs without further design work,
and the URL is not expected to change again.
