---
name: deploy
description: Deploy a new version of this project's backend. Netskrafl production and the Explo dev backend run as containers on Digital Ocean App Platform (deploy by pushing to a deploy branch, verify, roll back if needed); explo-live still runs on App Engine (gradual canary rollout). Use when the user asks to deploy, ship, release, promote or roll back a build. Defaults to netskrafl.
user-invocable: true
allowed-tools:
  - Read
  - Bash(date *)
  - Bash(git *)
  - Bash(grunt *)
  - Bash(gcloud app *)
  - Bash(gcloud scheduler *)
  - Bash(gcloud logging *)
  - Bash(doctl apps list*)
  - Bash(doctl apps get*)
  - Bash(doctl apps logs *)
  - Bash(doctl apps spec get *)
  - AskUserQuestion
---

# /deploy — release a new backend version

The three backends run on two platforms, and a release works differently on each:

| Target             | Platform                    | A release is                                           | Release name / tag |
|--------------------|-----------------------------|--------------------------------------------------------|--------------------|
| `netskrafl` (default) | Digital Ocean App Platform, PostgreSQL | a push to the branch `do-netskrafl`        | `nYYYYMMDD[a-z]`   |
| `explo-dev`        | Digital Ocean App Platform, PostgreSQL (the staging app) | a merge of master into the branch `do-deploy`, pushed | not tagged |
| `explo-live`       | Google App Engine, Datastore | an App Engine version, given traffic in stages        | `eYYYYMMDD[a-z]`   |

**This is a production action.** Only act on an explicit deploy request typed by
the user. Stop and get a clear "yes" before the step that starts a deploy, before
every traffic increase on App Engine, and before a rollback. Never delete or stop
old versions unless the user asks.

`$ARGUMENTS` may contain a target (default `netskrafl`) and an explicit release
name (e.g. `n20261116b`). If no name is given, compute it (step A1 / B1).

Follow **Part A** for `netskrafl` and `explo-dev`, **Part B** for `explo-live`.

---

# Part A — container targets (Digital Ocean App Platform)

## How a container deploy behaves

- A push to the deploy branch starts a build and then a new container. The new
  container must pass the health check on `/health/ready` (database and cache
  reachable) before it gets traffic. If the build fails or the health check never
  passes, **the old container keeps serving** and nothing has changed for users.
- **There is no gradual rollout.** With one instance, all users are on the old
  version and then all on the new one. The safety net is: the staging app first,
  the health gate, close watching afterwards, and a quick rollback.
- The container applies database schema migrations when it starts
  (`alembic upgrade head` in `docker-entrypoint.sh`), so the schema changes
  *before* the old container stops, and stays changed after a rollback.
- Scheduled jobs run inside the container (supercronic). A deploy stops the old
  container, and a job running in it with it.

Find the app and its details from the branch it deploys, not from memory:

```bash
BRANCH=do-netskrafl        # do-deploy for explo-dev
APP=$(doctl apps list -o json | jq -r --arg b "$BRANCH" \
  '.[] | select(.spec.services[0].github.branch == $b) | .id')
COMPONENT=$(doctl apps get "$APP" -o json | jq -r '.[0].spec.services[0].name')
HOST=$(doctl apps get "$APP" -o json | jq -r '.[0].spec.domains[0].domain')
DEPLOYED=$(doctl apps get "$APP" -o json | jq -r '.[0].active_deployment.services[0].source_commit_hash')
PREVIOUS_DEPLOYMENT=$(doctl apps get "$APP" -o json | jq -r '.[0].active_deployment.id')
```

`DEPLOYED` is the commit that is serving now. `PREVIOUS_DEPLOYMENT` is the
rollback target: record it before deploying.

## A1. Confirm scope and name the release

- `git fetch origin --tags`, then `git status -s` and `git log --oneline -1`. The
  commit to release (`COMMIT`) must be on GitHub, normally `origin/master`. Warn
  if the working tree is dirty or `HEAD` is not the intended commit.
- Release name (netskrafl only): `BASE="n$(date -u +%Y%m%d)"`. If the tag `BASE`
  exists (`git tag -l "n*"`), append the first free lowercase letter.
- Show the user what the release contains: `git log --oneline $DEPLOYED..$COMMIT`.

## A2. Look at what the release changes

Check each of these and tell the user what you found, before asking to deploy:

| Check | Command | Why it matters |
|---|---|---|
| Schema migrations | `git diff --stat $DEPLOYED..$COMMIT -- migrations/` | **A release with a migration cannot be rolled back** by redeploying the old version: the old container does not know the new schema revision and fails to start. The migration must also work with the *old* code, which keeps serving while the new container starts. Say so explicitly and ask whether to go to the staging app first. |
| Container build | `git diff --stat $DEPLOYED..$COMMIT -- Dockerfile docker-entrypoint.sh crontab requirements*.txt .dockerignore` | App Platform builds with kaniko, which differs from a local `docker build` (see `CLAUDE.md`). Build changes should have gone through the staging app. |
| Deployment in progress | `doctl apps list-deployments "$APP"` | Starting a deployment while another is in progress cancels the first. Wait for it. |
| Time of day | `date -u` | Do not deploy between 02:55 and 04:30 UTC: the nightly jobs run then, and the deploy would stop one halfway. Prefer a quiet time of day for anything risky. |
| Staging | `git log --oneline -1 origin/do-deploy` | For netskrafl: has this code been on the staging app? It runs the same container with the Explo configuration, so it proves the build, the start-up and the migrations, but not Netskrafl-specific behaviour. Recommend staging first for migrations, build changes and large releases. |

**Then tell the user the target, the release name, the commit and the findings
above, and get an explicit "yes".**

## A3. Deploy

`netskrafl` — `do-netskrafl` only ever points at a commit of master, so the push
is a fast-forward (never force it):

```bash
git push origin $COMMIT:do-netskrafl
```

Then set the version label, right away, while the build is still running. The app
reads it from the environment variable `APP_VERSION` in its spec (it is the
cache-busting suffix of static files). Round-trip the live spec; never apply the
checked-in `.do/app.yaml`, which has placeholders for the secrets:

```bash
doctl apps spec get "$APP" --format json > "$SPEC"      # $SPEC: a file in a private temp directory
# set the value of the service env var APP_VERSION to the release name, then:
doctl apps update "$APP" --spec "$SPEC" && rm "$SPEC"
```

The spec update cancels the build that the push started and starts a new one
from the same commit with the new label, so users see one switch, not two.
Step A5 checks that the commit serving in the end is indeed `COMMIT`.

`explo-dev` — `do-deploy` is a merge-commit branch: check it out, `git merge
origin/master`, push it, and return to the previous branch. It has no version
label.

## A4. Watch the build and the switch

```bash
doctl apps list-deployments "$APP" --format ID,Cause,Progress,Phase,Updated | head -4
```

Phases go `PENDING_BUILD` → `BUILDING` → `PENDING_DEPLOY` → `DEPLOYING` → `ACTIVE`
(the previous one becomes `SUPERSEDED`); `ERROR` or `CANCELED` means the old
container is still serving. A build takes several minutes. If it fails:

```bash
doctl apps logs "$APP" "$COMPONENT" --type build --tail 100
doctl apps logs "$APP" "$COMPONENT" --type deploy --tail 100
```

While the deployment is `DEPLOYING`, probe the public hostname every few seconds
and count the answers that are not 200, to see whether the switch dropped
requests:

```bash
curl -s -o /dev/null -m 10 -w "%{http_code} %{time_total}\n" "https://$HOST/health/ready"
```

## A5. Verify the new version

1. It is the right code and it is active:
   ```bash
   doctl apps get "$APP" -o json | jq -r '.[0].active_deployment | .phase, .services[0].source_commit_hash'
   ```
   The commit must equal `COMMIT`.
2. It answers: `/health/ready` gives 200; an API call without a login (for
   instance `POST /gamelist`) gives 401, not 5xx.
3. Watch the log for at least 10 minutes, longer for a risky release. Report what
   each check shows; empty output means clean:
   ```bash
   doctl apps logs "$APP" "$COMPONENT" --type run --tail 3000 > "$LOG"
   grep -E "ERROR|WARNING|CRITICAL|Traceback" "$LOG"          # application problems
   grep -E '" 5[0-9]{2} ' "$LOG"                              # failed requests
   grep -c 'job succeeded' "$LOG"; grep 'job failed' "$LOG"   # scheduled jobs (every 2 minutes)
   grep -E "Booting worker|Starting gunicorn" "$LOG"          # more than one start = restarts
   ```
   The access log ends each request with its duration in microseconds; compare
   the slow tail with what is normal (median API call around 30 ms, nearly all
   under 300 ms).
4. Ask the user to try the change itself, and one ordinary thing: log in, open a
   game, make a move.

If anything looks abnormal, **stop and go to "When a container deploy goes
wrong"** rather than waiting for it to clear up.

## A6. Finish

- **Tag the release** (netskrafl only), on the commit that is serving:
  ```bash
  git tag -a <NAME> $COMMIT -m "netskrafl production release <NAME> $(date -u +%F)"
  git push origin <NAME>
  ```
  This is part of the deploy the user approved. Do not tag a release that was
  rolled back. Never move or delete an existing release tag.
- Report: release name, commit, when the switch happened, whether any probe
  failed during it, and what the log checks showed.

## When a container deploy goes wrong

| What you see | What it means | What to do |
|---|---|---|
| Build `ERROR` | The image could not be built. The old version is serving. | Nothing is broken. Read the build log, fix on master, deploy again. |
| Deployment `ERROR` after the build; health check never passed | The new container did not start or could not reach the database or the cache. The old version is serving. | Nothing is broken for users. Read the deploy and run logs. **If the release had a migration, check whether it was applied** (`select version_num from alembic_version`): if so, the old code is now running on the new schema; watch it and fix forward quickly. |
| New version `ACTIVE`, but errors, 5xx answers, restarts or slow answers | A bad release is serving everyone. | Decide within minutes: recommend a **rollback** to the user (below), unless the release had a migration. Do not debug in production while users are affected. |
| New version `ACTIVE`, one feature misbehaves, the rest is fine | A contained bug. | Tell the user what is affected and offer both: roll back now, or fix forward. The user chooses. |
| The release had a migration and the new version is bad | Rollback by redeploying is not available. | **Fix forward**: the fastest safe fix or revert of the *code* on master, keeping the migration, then deploy again. A schema downgrade is a decision for the user, never a reflex. |
| Data was damaged | A rollback does not repair data. | Stop the damage first (roll back or fix forward), then tell the user exactly what was written wrongly and since when. Restoring from the managed database's backups is the user's decision. |
| The platform itself is failing (no deployments, app unreachable, old and new alike) | Not caused by the release. | Do not push more changes. Report it and check the provider's status page. App Engine is **not** a fallback for netskrafl: its data stopped at the move. |

### Rollback

A rollback creates a new deployment from an earlier one, without a rebuild. The
command-line client has no command for it; it is done through the API, with the
client's own token:

```bash
TOKEN=$(awk '/access-token:/ {print $2; exit}' ~/.config/doctl/config.yaml)
API="https://api.digitalocean.com/v2/apps/$APP"
ROLLBACK='{"deployment_id": "'$PREVIOUS_DEPLOYMENT'"}'

# 1. Is it possible? Changes nothing. Expect {"valid": true}; read any warnings.
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "$ROLLBACK" "$API/rollback/validate"

# 2. Roll back (after the user's "yes")
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "$ROLLBACK" "$API/rollback"
```

Then watch it as in A4 and verify as in A5 (the serving commit is `DEPLOYED`
again). What to know:

- **A rollback restores the earlier deployment's spec too**, not only its code:
  environment variables, domains, instance size. Before rolling back, make sure
  nothing in the spec was changed on purpose since `PREVIOUS_DEPLOYMENT` (the
  version label does not matter).
- **The app is pinned after a rollback**: no deployment starts, not even from a
  push to the deploy branch, until the rollback is committed or reverted:
  ```bash
  curl -s -X POST -H "Authorization: Bearer $TOKEN" "$API/rollback/commit"   # keep it, allow deployments again
  curl -s -X POST -H "Authorization: Bearer $TOKEN" "$API/rollback/revert"   # go back to the release that was rolled back
  ```
  Leave it pinned while the fix is being made. When the fix is on master: commit
  the rollback, then deploy the fix as a new release (Part A from the top). The
  deploy branch still points at the bad commit until then, which is fine: it only
  moves forward.
- **It does not undo schema migrations or data changes**, and it fails for a
  release that contained a migration (see the table).
- As of 2026-11-13 the validation call has been used against the production app,
  but an actual rollback has not been carried out on either app. Until one has
  been rehearsed on the staging app, say so when recommending it, and watch the
  first one closely.

After any incident, tell the user plainly what happened, from when to when users
were affected, and what state the app, the deploy branch and the database schema
are in now.

---

# Part B — App Engine target (explo-live)

Deploys a new version of the default service to Google App Engine **without
promoting it**, then shifts traffic to it in stages (10% → 25% → 50% → 100%),
pausing to check logs at each step. Old versions are **never deleted** so a
deploy can be reverted instantly.

Configuration: `app-explo-live.yaml`, credentials
`credentials/explo-live/service-account.json`, project `explo-live`, service
`default`. The recurring jobs (`/stats/run`, `/stats/ratings`,
`/connect/cleanup`, `/connect/update`) run via `cron.yaml`; cron always targets
the promoted version, so no scheduler updates are needed.

Do not use this part for `netskrafl`: its App Engine project only serves a
redirect to the new home since the move (see `appspot-redirect/`), and
`explo-dev`'s App Engine service is retired.

## B1. Confirm scope and compute the version

- Confirm what is being deployed: run `git status -s` and `git log --oneline -1`.
  Warn if the working tree is dirty or `HEAD` is not the merged/intended commit.
  Record `git rev-parse HEAD` as `COMMIT`: the release tag (step B5) goes on it,
  so it must be a commit that is on GitHub (normally `origin/master`).
- Compute the version id unless one was given:
  - `BASE="e$(date +%Y%m%d)"` (e.g. `e20260616`).
  - List existing ids: `gcloud app versions list --project=explo-live --service=default --format="value(version.id)"`,
    and existing release tags: `git fetch --tags && git tag -l "e*"`.
  - If `BASE` is free in both lists, use it. Otherwise append the first free
    lowercase letter (`a`, `b`, `c`… for multiple releases on the same day).
- **Tell the user the exact target project and version id, and get explicit
  confirmation before deploying.**

## B2. Build and deploy (no promote)

Run from the repo root. Build the frontend, then upload the version with **zero
traffic** (`--no-promote`):

```bash
grunt make
GOOGLE_APPLICATION_CREDENTIALS=credentials/explo-live/service-account.json PROJECT_ID=explo-live \
  gcloud app deploy --no-cache --version=<VERSION> --no-promote \
  --project=explo-live app-explo-live.yaml --quiet
```

(This mirrors `./deploy-explo-live.sh default <VERSION>` but keeps the traffic
rollout under this skill's control.)

`grunt make` needs Node deps (`npm install` if `grunt` is missing). The
`gcloud app deploy` step can take several minutes — allow a long timeout
(up to ~10 minutes) so it isn't cut off mid-upload.

## B3. Verify the upload

```bash
gcloud app versions list --project=explo-live --service=default \
  --filter="version.id=<VERSION>" \
  --format="table(version.id, traffic_split, version.servingStatus)"
```

Confirm the new version exists, is `SERVING`, and has `traffic_split = 0.00`.
Record the **current** version (the one at `traffic_split = 1.00`) as `CURRENT` —
this is the rollback target.

## B4. Gradual traffic rollout (human-gated)

The commands below split by cookie; `--split-by=random` is also acceptable for
an API backend such as Explo's.

For each stage in **10% → 25% → 50% → 100%**:

1. **Ask the user to confirm** advancing to this stage. Do not proceed without it.
2. Set the split (replace `<P>` with the percentage as a fraction):

   ```bash
   # intermediate stages keep CURRENT serving the remainder
   gcloud app services set-traffic default \
     --splits=<VERSION>=<P>,<CURRENT>=<1-P> \
     --split-by=cookie --project=explo-live --quiet
   ```
   At the final stage send 100% to the new version:
   ```bash
   gcloud app services set-traffic default \
     --splits=<VERSION>=1 --split-by=cookie --project=explo-live --quiet
   ```
3. **Monitor** for a few minutes before offering the next stage. Run all three
   checks and report what each shows — **empty output means clean**:
   ```bash
   # a) recent request stream — confirm core endpoints return 200
   gcloud app logs read --project=explo-live --service=default \
     --version=<VERSION> --limit=50

   # b) WARNING-or-above app logs (captures warnings AND errors in one pass)
   gcloud logging read \
     'resource.type=gae_app AND resource.labels.version_id=<VERSION> AND severity>=WARNING' \
     --project=explo-live --freshness=10m --limit=30 --format="value(severity)"

   # c) failed requests — any 4xx/5xx HTTP statuses
   gcloud logging read \
     'resource.type=gae_app AND resource.labels.version_id=<VERSION> AND httpRequest.status>=400' \
     --project=explo-live --freshness=10m --limit=20 \
     --format="table(timestamp, httpRequest.status, httpRequest.requestUrl)"
   ```
   Use `severity>=WARNING` (not just `ERROR`) so significant warnings are
   surfaced too. A rise in warnings or non-200 statuses on the new version is a
   signal even without hard errors. If anything looks abnormal, **stop and
   recommend rollback** (see below) rather than advancing.

## B5. Finish

- **Tag the release** once the version has 100% of the traffic. The tag has the
  same name as the App Engine version and points at `COMMIT` from step B1, so a
  bug or anomaly seen in production can be traced back to the exact source:
  ```bash
  git tag -a <VERSION> <COMMIT> -m "explo-live production release <VERSION>, 100% traffic $(date -u +%F)"
  git push origin <VERSION>
  ```
  This is part of the deploy the user approved; no separate confirmation is
  needed. If the rollout is abandoned or rolled back before 100%, do not tag.
  Never move or delete an existing release tag.
- **Do not delete or stop old versions** — leave them for rollback. Mention to
  the user that older versions remain and can be cleaned up later.
- Report the final state: `gcloud app versions list --project=explo-live --service=default --format="table(version.id, traffic_split, version.servingStatus)"`.

## Rollback on App Engine

To instantly route all traffic back to the previous version:

```bash
gcloud app services set-traffic default --splits=<CURRENT>=1 \
  --split-by=cookie --project=explo-live --quiet
```

Cron jobs follow the promoted version automatically; no scheduler changes are
needed on rollback.

---

## Notes

- Backends: `netskrafl` and `explo-dev` run on **PostgreSQL**; `explo-live` runs
  on **NDB** (Datastore) until it moves too. A change must work on both.
- On App Engine, `gcloud app deploy --no-promote` is safe (no traffic); the
  **traffic stages** are the sensitive steps. On the container targets, the
  **push to the deploy branch** is the sensitive step: gate it on explicit user
  confirmation.
- If `gcloud` is not authenticated for the target project, use the project's
  service-account key: `CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE=<credentials file>`.
- The `doctl` commands for reading (`list`, `get`, `logs`, `spec get`) are
  pre-approved for this skill. `doctl apps update` and the rollback calls are
  not, on purpose: each one is confirmed when it is made.
