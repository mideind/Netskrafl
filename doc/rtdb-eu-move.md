# Runbook: moving Netskrafl's Realtime Database to the EU

*Written 2026-11-03, for a switch planned for 2026-11-04. Part of the GDPR
review of hosting regions (see "Background" at the end).*

The netskrafl project's Firebase Realtime Database moves from the US default
instance to a new instance in europe-west1:

| | URL |
|---|---|
| Old (us-central1, 1.1 GB) | `https://netskrafl.firebaseio.com` |
| New (europe-west1) | `https://netskrafl-eu.europe-west1.firebasedatabase.app` |

## Status

- [x] 1. Instance `netskrafl-eu` created (USER_DATABASE, europe-west1), 2026-11-03.
- [x] 2. Security rules copied from the old instance, verified byte-identical.
      They are not in the repo; read them with REST `/.settings/rules.json`.
- [x] Copy script `scripts/rtdb-move-gatadagsins.sh` written. `export`, `verify`
      and `diff` tested against the live instances; `import` not yet run.
- [x] 2026-11-04: all three SDKs connect to the new instance, tested live:
      Admin SDK 6.7.0 (server) and web SDKs 8.6.2 (Netskrafl pages) and 13.x
      (Málstaður). `.info/connected` came back true and unauthenticated reads
      were refused. The WebSocket goes to `wss://netskrafl-eu.europe-west1.firebasedatabase.app`.
- [x] 2026-11-04: **found that Málstaður's CSP blocks the new host.**
      `next.config.ts` (enforced, not report-only) allows only
      `*.firebaseio.com`, so P2 and P3 now include a CSP change
      (`*.firebasedatabase.app` in script-src, connect-src and frame-src).
      Netskrafl's own pages send no CSP.
- [x] 2026-11-04: browser test of the #2840 preview (villi): no CSP errors, the
      WebSocket to the new host is open (status 101), and the session's presence
      entry `connection/<uid>` appeared on the new instance. So custom-token sign-in
      and the rules work there, which covers most of S2.
- [x] 2026-11-04 15:42: P1b, `n20261104` (master 0dfdded, PR #169) deployed with
      `--no-promote`: SERVING, traffic 0, env `FIREBASE_DB_URL` = the EU URL, no
      warnings or failed requests at startup. Rollback target: `n20260928`.
- [x] 2026-11-04 16:02: P2, staged deployment `malstadur-q83154u9z-mideind.vercel.app`
      (CLI deploy from `e14b24765`, so the API shows no git SHA for it, source `cli`),
      READY with no domain. villi was made Vercel team Owner for this: as Developer,
      the CLI refused to create a production deployment.
- [x] 2026-11-04: staged build tested in the browser: WebSocket to
      `netskrafl-eu.europe-west1.firebasedatabase.app` with `ns=netskrafl-eu`, presence
      entry on the new instance. Logging in there needed a **temporary Redirect URL in the
      production Supabase project** (`https://malstadur-q83154u9z-mideind.vercel.app/**`,
      added by villi); without it, Google login falls back to the Site URL. Remove it
      after the switch (F7). Previews log in through the staging Supabase project, whose
      allowlist accepts `*-mideind.vercel.app`.
- [x] Preparation (P1–P3). P1b (browser test of `n20261104`) skipped: the legacy web UI
      always redirects to `/transition` or Málstaður, so S6 covered the server.
- [x] **The switch, 2026-11-04 16:26–16:30 UTC.** S1 16:26:36 (10.68 MB, verify OK);
      S3 16:27:04 (`n20261104` = 100%); S5 16:27:40 (`vercel promote` needs
      `--scope mideind`; the first attempt without it failed, which made the window of
      mixed versions 36 s); S6 OK (97 requests with 200, no errors; villi's Málstaður
      WebSocket on `ns=netskrafl-eu`; `game`/`user`/`connection` writes on the new instance);
      S7 16:28:14: no stray writes; S8: #2840 squash-merged to staging as `e142d6d1e`,
      freeze over. Main still `e14b24765`; the next release carries the constant. P1 done 2026-11-04, the P2 worktree is
      ready (deploy not yet run), and the P3 PRs are open.
- [ ] Follow-ups (F1–F5 below).

## What is copied, and why so little

Only `gatadagsins/` (10.6 MB) is copied. `game/` (~1.09 GB, 409k games since
2020), `user/` (2.9 MB) and `connection/` (1 MB) are not:

- Both web clients (Netskrafl's `static/src` and Málstaður's
  `packages/netskrafl-react`) ignore the value they receive on first attach to
  `game/{id}/{uid}/move`, `game/{id}/{uid}/chat` and `user/{uid}`; they act only
  on later changes. Games, chat and subscriptions live in Datastore.
- Presence (`connection/`) re-registers on connect.
- The server reads back only `user/{uid}/wait/{opp}`, a short-lived marker
  for a pending timed-game challenge. Anyone waiting at the switch re-issues it.

Gáta dagsins is different: clients use the stored values (leaderboards, best
scores, stats, achievements) and the server updates them in transactions.

## How the URL reaches each consumer

| Consumer | Source of the URL | Takes effect |
|---|---|---|
| Netskrafl server (Firebase Admin SDK, `src/firebase.py`) | env var `FIREBASE_DB_URL` (in `app-netskrafl.yaml`, since 2026-11-04) if set, else top-level key `FIREBASE_DB_URL` in secret `CLIENT_SECRET_NETSKRAFL`, version `latest`, read once at import (`src/config.py`) | per version (env var), or when an instance starts (secret) |
| Netskrafl web pages (`templates/firebase.html`) | the same, passed into the template | pages served by a new instance |
| Málstaður (Netskrafl and Gáta dagsins) | `NEXT_PUBLIC_FIREBASE_DB_URL`, **not set in Vercel**, so the fallback `NETSKRAFL_FIREBASE_DB_URL` in `src/hooks/useNetskraflAuth.tsx` applies | at build time |
| Málstaður-vor demo (`malstadur-demo` unit on brandur) | the same fallback, or its `.env.local` | at its next build |

**Decided 2026-11-04: the server switches with a new App Engine version, not
by restarting instances.** `src/config.py` now lets an environment variable
`FIREBASE_DB_URL` override the secret, and `app-netskrafl.yaml` sets it to the
EU URL. The secret stays at version 6, the old URL. So each version is
self-consistent: `n20260928` always uses the old instance and the new version
always the new one, whenever their instances start. Moving traffic is the
switch, and moving it back is the rollback. The earlier plan (secret v7 plus
deleting instances) had a mixed-state window and an unrehearsed instance
delete; it is kept below only as the record of P1.

A promoted Vercel build switches Málstaður.

## Shell setup (every step below assumes this)

```sh
cd ~/github/Netskrafl
NEW_URL=https://netskrafl-eu.europe-west1.firebasedatabase.app
OLD_URL=https://netskrafl.firebaseio.com
umask 077; mkdir -p ~/rtdb-move    # also the copy script's default directory
```

gcloud runs as the interactive login (`vt@extrada.com`, owner of netskrafl).
If that login has expired, prefix the commands with
`CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE=credentials/netskrafl/service-account.json`
(the service account can also add secret versions; checked 2026-11-03).
The copy script always uses the service account.

## Preparation (no production effect; the morning of the switch)

### P1. Secret version 7, as local files

```sh
gcloud secrets versions list CLIENT_SECRET_NETSKRAFL --project netskrafl
# Expect version 6 as the newest, enabled. If there is a newer one, use it below instead of 6.
gcloud secrets versions access 6 --secret CLIENT_SECRET_NETSKRAFL --project netskrafl > ~/rtdb-move/secret-v6.json
jq -r .FIREBASE_DB_URL ~/rtdb-move/secret-v6.json          # expect $OLD_URL
jq --arg u "$NEW_URL" '.FIREBASE_DB_URL = $u' ~/rtdb-move/secret-v6.json > ~/rtdb-move/secret-v7.json
diff <(jq -S . ~/rtdb-move/secret-v6.json) <(jq -S . ~/rtdb-move/secret-v7.json)
# Must show exactly one changed line: FIREBASE_DB_URL.
```

`secret-v6.json` is also the rollback file. Both files hold secrets: mode 600,
and delete them when the move is finished.

*With the version route, the switch does not need the secret.* `secret-v7.json`
is used only in follow-up F6, once `n20260928` is gone.

### P1b. Deploy the new version without traffic

Deploy master (it includes the env override and the `opp_beginner` commits
e1f202e, 8b56bd0) with the deploy skill's build steps, but **`--no-promote` and
no canary**: the traffic move in S3 is all at once.

Then test it on its own URL, `https://<version>-dot-netskrafl.appspot.com`. In
the page source, `templates/firebase.html` must show the EU `databaseURL`, and
the browser's WebSocket must go to `netskrafl-eu...`. Two test accounts in a
game see each other's moves and chat live (both on the version URL). Gáta
dagsins data written there before S1 is overwritten by the import, which is
harmless. Users are unaffected: all traffic stays on `n20260928`.

### P2. Staged Málstaður production build with the EU URL

Built from the exact commit that is in production now, plus the CSP commit of
PR #2839 if that has not been released yet. The URL is given as a build-time
variable, so the Vercel project settings stay unchanged. `--skip-domain` keeps
the domain on the current deployment until we promote.

Find the production commit (the dashboard shows it too):

```sh
VT=$(jq -r .token ~/.local/share/com.vercel.cli/auth.json)
PRJ=$(jq -r .projectId ~/github/Malstadur-vor/.vercel/project.json)
TEAM=$(jq -r .orgId ~/github/Malstadur-vor/.vercel/project.json)
curl -s -H "Authorization: Bearer $VT" "https://api.vercel.com/v9/projects/$PRJ?teamId=$TEAM" \
  | jq -r '.targets.production | .url + " " + .meta.githubCommitSha'
```

Since 2026-11-04 15:32 that is `e14b24765` (release PR #2835, which includes
the CSP change). The worktree is already there: `~/github/Malstadur-prod-eu`,
detached at `e14b24765` (no cherry-pick needed), with `.vercel` copied from
Malstadur-vor (excluded in `.git/info/exclude`). If production has moved on by
the time of the switch, recreate it:

```sh
cd ~/github/Malstadur && git fetch origin
git worktree remove ~/github/Malstadur-prod-eu
git worktree add --detach ~/github/Malstadur-prod-eu <production commit>
cd ~/github/Malstadur-prod-eu
# The CSP change (#2839, squash-merged to staging as 96eb100a4 on 2026-11-04)
# must be in the build; cherry-pick it only if production does not have it yet:
grep -q firebasedatabase.app next.config.ts || git cherry-pick 96eb100a4
cp -r ~/github/Malstadur-vor/.vercel .
```

Then deploy:

```sh
cd ~/github/Malstadur-prod-eu
grep -c firebasedatabase.app next.config.ts      # must be 4
vercel deploy --prod --skip-domain --build-env NEXT_PUBLIC_FIREBASE_DB_URL=$NEW_URL
# Note the deployment URL it prints: needed in S5.
```

**Málstaður releases from staging to main about daily** (kristofer). A release
after P2 makes the staged build older than production, and promoting it would
roll that release back. So build P2 shortly before the switch, and check the
production commit again just before S5.

Smoke-test the deployment URL: it loads, and the browser's network tab shows
the Firebase connection going to `netskrafl-eu.europe-west1.firebasedatabase.app`.
Live updates will not work there until the switch (the server still writes to
the old instance), and the Supabase login may refuse an unlisted deployment URL;
neither is a problem.

`vercel whoami` showed `vthorsteinsson` logged in on 2026-11-03. If it is logged
out: `! vercel login`.

### P3. Málstaður PRs (opened 2026-11-04)

- [#2839](https://github.com/mideind/Malstadur/pull/2839),
  `netskrafl/csp-firebasedatabase-app`: adds `*.firebasedatabase.app` to the
  CSP. Squash-merged to staging as `96eb100a4` on 2026-11-04 15:25, and on its way
  to production in release PR #2835.
- [#2840](https://github.com/mideind/Malstadur/pull/2840) (draft),
  `netskrafl/firebase-eu-url`, rebased onto staging (only the URL commit): changes
  `NETSKRAFL_FIREBASE_DB_URL` in `src/hooks/useNetskraflAuth.tsx` to `$NEW_URL`.
  Merged in S8. Until it reaches production, **every new Málstaður production
  build reverts to the US database**, because Vercel has no
  `NEXT_PUBLIC_FIREBASE_DB_URL`. The same goes for staging and preview builds.
  Its preview (`malstadur-git-netskrafl-firebase-eu-url-mideind.vercel.app`)
  is a real Málstaður with the new CSP and the EU URL, so it serves as a browser
  test before the switch. Its connection should work, but live updates and
  today's Gáta dagsins data will not, since nothing has been copied or switched yet.

## The switch (a quiet hour; about 15 minutes)

Do S1, S3 and S5 without pauses. With the version route, S2 and S4 are
replaced as marked.

### S1. Copy Gáta dagsins

```sh
scripts/rtdb-move-gatadagsins.sh export    # old instance -> ~/rtdb-move/gatadagsins-before.json
scripts/rtdb-move-gatadagsins.sh import    # -> new instance (replaces gatadagsins/ there)
scripts/rtdb-move-gatadagsins.sh verify    # must print OK
```

### S2. Optional: check rules and Auth on the new instance

Make a custom token for a test user, exchange it for a Firebase ID token
(Identity Toolkit `signInWithCustomToken`, with the web API key from the secret),
then read `$NEW_URL/gatadagsins/<today>/is_IS/leaders.json?auth=<idToken>` (must
work) and another user's `$NEW_URL/user/<other uid>.json?auth=<idToken>` (must be
refused).

### S3. Move all traffic to the new version (version route)

```sh
NEWV=<version from P1b>
gcloud app services set-traffic default --splits $NEWV=1 --project netskrafl --quiet
gcloud app versions list --project netskrafl --service default --filter="traffic_split>0"
```

The secret is **not** changed. Leave `n20260928` deployed (not stopped) until
F6: it is the rollback target.

### S3–S4, previous plan (not used): secret v7 and restarting instances

```sh
gcloud secrets versions add CLIENT_SECRET_NETSKRAFL --project netskrafl --data-file=$HOME/rtdb-move/secret-v7.json
```

```sh
V=$(gcloud app versions list --project netskrafl --service default --filter="traffic_split>0" --format="value(id)")
echo "$V"    # must be exactly one version (2026-11-03: n20260928 with all traffic)
gcloud app instances list --project netskrafl --service default --version "$V" --format="value(id,instance.startTime)"
for id in $(gcloud app instances list --project netskrafl --service default --version "$V" --format="value(id)"); do
    gcloud app instances delete "$id" --project netskrafl --service default --version "$V" --quiet
done
gcloud app instances list --project netskrafl --service default --version "$V" --format="value(id,instance.startTime)"
```

The next request starts a fresh instance (basic scaling, max 2, a cold start of a
few seconds); in-flight requests are cut off.

If instance deletion is refused: `gcloud app versions stop/start` is documented
for manual scaling only, so do not count on it. The fallback that certainly
works is to deploy the current master as a new version and move all traffic to
it at once (`gcloud app services set-traffic default --splits <new>=1 --project
netskrafl`, no canary). That takes several minutes, and needs a clean frontend
build (`node_modules/.bin/grunt make`; never deploy after a failed build, since
it empties `static/built/`). The old instance keeps the old URL until then, so
expect the mixed state described under "What users notice" for longer.

To remove this uncertainty, the instance delete can be rehearsed beforehand at a
quiet moment: with the secret still at version 6 it changes nothing except a cold
start.

### S5. Promote the staged Málstaður build

**Release freeze.** Agree with kristofer beforehand: no merges to main, and no
release PR from staging merged, from P2 until #2840 is merged into staging (S8).
That is about 20 minutes. After that, every release from staging includes #2840,
because release PRs have the `staging` branch itself as their head.

Right before promoting, check two things: production is still the commit P2 was
built from, and **no production deployment is building or queued**. A main
build that finishes after the promote is auto-assigned the domain and would put
Málstaður back on the old URL.

```sh
curl -s -H "Authorization: Bearer $VT" "https://api.vercel.com/v9/projects/$PRJ?teamId=$TEAM" \
  | jq -r '.targets.production | "current: " + .url + " " + .meta.githubCommitSha[0:9]'
curl -s -H "Authorization: Bearer $VT" "https://api.vercel.com/v6/deployments?projectId=$PRJ&teamId=$TEAM&target=production&limit=5" \
  | jq -r '.deployments[] | [.url, .state, .meta.githubCommitSha[0:9] // "cli"] | @tsv'
# Only READY entries, and the current one at the expected commit. Anything
# BUILDING/QUEUED/INITIALIZING other than our own staged build: wait.
```

If a release went out in between, do not promote: the staged build would roll
it back. Rebuild P2 from the new commit instead (a few minutes; meanwhile
Málstaður is on the old database, the "mixed state" below).

`vercel promote` keeps auto-assignment of production domains switched on (it
also re-enables it after a rollback), so normal releases keep going live
afterwards.

```sh
cd ~/github/Malstadur-prod-eu && vercel promote <deployment URL from P2> --yes
```

### S6. Verify

- `gcloud app instances list ...`: a start time after S3.
- Logs: no Firebase errors from the new instance.
- Two test accounts: a move and a chat message update live, both on
  netskrafl.mideind.is (reload first) and in Málstaður.
- Gáta dagsins in Málstaður shows today's leaderboard and your own stats.
- The new instance receives writes; `connection`, `game` and `user` appear within
  minutes:

  ```sh
  T=$(gcloud auth print-access-token)
  curl -s -H "Authorization: Bearer $T" "$NEW_URL/.json?shallow=true"
  ```

### S7. Catch stray writes on the old instance

```sh
scripts/rtdb-move-gatadagsins.sh diff
```

It lists every `gatadagsins/` leaf written on the old instance since S1 (from the
old instance before S4, or from browser tabs not yet reloaded). Merge those into
the new instance by hand. Run it again an hour or so later.

### S8. Merge the Málstaður PRs (P3)

Merge #2839 (if not already merged), then mark #2840 ready and merge it to
staging. Tell kristofer that the next release from staging to main must include
it, and that no release without it may go out. Also rebuild the Málstaður-vor demo with the new URL and restart it
(`systemctl --user restart malstadur-demo`).

## What users notice

- A cold start of a few seconds right after S4.
- Open tabs (Netskrafl and Málstaður) keep listening to the old instance and get
  no live updates until they are reloaded.
- The "online users" list empties and fills as clients reconnect. It becomes
  accurate: before the move only 98 of the 4,559 users under `connection/` had an
  entry less than 24 hours old.

## Rollback

1. `gcloud app services set-traffic default --splits n20260928=1 --project netskrafl --quiet`.
   That version reads the secret (still v6, the old URL), so it is back on the
   old instance immediately.
2. (Only if the previous plan was used: add secret version 8 = `secret-v6.json`
   and restart the instances. Never disable version 7, because `latest` would
   then point at a disabled version.)
3. Málstaður: `vercel rollback` (or Instant Rollback in the dashboard) to the
   previous production deployment, and do not merge #2840 (revert it in staging
   if it is already merged). **A rollback turns off auto-assignment of production
   domains**, so later releases from main stay staged until someone promotes one
   (`vercel promote <deployment>`, or "Undo Rollback" in the dashboard). Tell
   kristofer.
4. Gáta dagsins written on the new instance meanwhile must be copied back to the
   old one (the same export/diff method, in the other direction).

The old instance is left intact until F1, so rolling back loses nothing else.

## Follow-ups

- F1. Keep the old instance read-only for about two weeks (rules: `.write: false`
  everywhere), then delete its data in chunks (`firebase database:remove`, never one
  delete of `game/`, which would lock the database for a long time) and set
  deny-all rules. The default instance itself cannot be deleted. Delete
  `~/rtdb-move` (secrets and Gáta dagsins exports) at the same time.
- F2. Add a nightly purge of `game/{id}` nodes for finished games (game IDs are
  version 1 UUIDs, so a node's age is in its key), so the new instance does not
  build up years of move and chat notifications again.
- F3. Find out why presence entries go stale (entries back to 2017 under
  `connection/`), since `get_connected_users()` counts every key.
- F4. Check the rules file into the repo.
- F5. Put the new URL into `.do/app.yaml` and `doc/migration-strategy.md` for the
  future netskrafl app on Digital Ocean.
- [x] F7 (done by villi, 2026-11-04). Remove the temporary Redirect URL `https://malstadur-q83154u9z-mideind.vercel.app/**`
  from the production Supabase project (Authentication > URL Configuration).
- F6. Once rollback to `n20260928` is no longer wanted (say a week): add secret
  version 7 (`~/rtdb-move/secret-v7.json`, P1), so the secret matches, and the
  Digital Ocean container and any later deploy without the env override get the
  EU URL. Then delete `n20260928`. The `FIREBASE_DB_URL` line in
  `app-netskrafl.yaml` can then stay, as a harmless override, or go.

## Background

On 2026-11-03 an audit of hosting regions found the netskrafl GCP project to be
entirely in the US (App Engine `us-central`, Datastore `nam5`, Memorystore, this
database), while explo-live and explo-dev are in the EU. App Engine and Datastore
regions are fixed per project, so those move with the Digital Ocean migration
(`doc/migration-strategy.md`); the Realtime Database can move on its own, and
`gatadagsins/` holds lasting personal data (user stats, streaks, achievements).
Strict EU hosting is not required (GDPR transfers to Google rely on the EU-US
Data Privacy Framework and standard contractual clauses), so this move reduces
risk rather than fixing a violation.

A backend-supplied database URL for Málstaður was considered and set aside for
this switch: `netskrafl-react` can start Firebase from cached session settings
without a fresh login response, so it would not avoid stale tabs without further
design work, and the URL is not expected to change again.
