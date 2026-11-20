---
name: deploy
description: Deploy a new version of this project's backend. All three backends (Netskrafl production, Explo production, and the Explo dev backend, which is also the staging app) run as containers on Digital Ocean App Platform, on PostgreSQL. A production release goes to the staging app first, as a canary with a standard test, and then to production by a push to the app's deploy branch, watched through log samples with a rollback kept ready. Use when the user asks to deploy, ship, release, promote or roll back a build. Defaults to netskrafl.
user-invocable: true
allowed-tools:
  - Read
  - Bash(date *)
  - Bash(git *)
  - Bash(gcloud app describe *)
  - Bash(gcloud logging read *)
  - Bash(doctl apps list*)
  - Bash(doctl apps get*)
  - Bash(doctl apps logs *)
  - Bash(doctl apps spec get *)
  - Bash(venv/bin/python utils/staging-check.py *)
  - Bash(venv/bin/python utils/datadog-setup.py --service * --mute-starts *)
  - AskUserQuestion
---

# /deploy — release a new backend version

All three backends run the same container image on Digital Ocean App Platform,
each with its own PostgreSQL database, and each deploys from its own branch:

| Target | What it is | Deploy branch | Release name / tag |
|---|---|---|---|
| `netskrafl` (default) | Netskrafl production | `do-netskrafl`, fast-forwarded to a commit of master | `nYYYYMMDD[a-z]` |
| `explo-live` | Explo production | `do-explo`, fast-forwarded to a commit of master | `eYYYYMMDD[a-z]` |
| `explo-dev` | The Explo dev backend, which is also **the staging app**: the canary for both production apps | `do-deploy`, a merge-commit branch that master is merged into | not tagged |

**This is a production action.** Only act on an explicit deploy request typed by
the user. Stop and get a clear "yes" before the step that starts a deploy and
before a rollback.

`$ARGUMENTS` may contain a target (default `netskrafl`) and an explicit release
name (e.g. `n20261116b`). If no name is given, compute it (step 1).

## The route of a production release

1. **The canary.** The commit is deployed to the staging app, and the standard
   test is run on it (step 3). This shows that the image builds, that the new
   container starts, applies its migrations and passes its health check, that
   the scheduled jobs run, and that the key operations work. The staging app has
   few users, so it shows **nothing about how the release behaves under real
   traffic**, with production's data volume, or over time.
2. **Production**, only if the canary was clean: the same commit goes to the
   production app (step 4). There is no gradual rollout, so what protects the
   users from here on is the watch: log samples from the moment the new
   container serves (step 6), compared with a baseline taken before the deploy,
   and **a rollback target recorded in advance**, so that a bad sample leads to
   a rollback within minutes and not to debugging in production.

Straight to production, without the canary, happens only when the user asks for
exactly that, in words ("straight to production", "skip staging"). Do not
propose it, and do not read it into a request: that a fix is urgent is not by
itself such a request.

One canary run serves both production apps, if both are to get the same commit.
Deploy them one at a time: finish the watch of the first before starting the
second.

## How a container deploy behaves

- A push to the deploy branch starts a build and then a new container. The new
  container must pass the health check on `/health/ready` (database and cache
  reachable) before it gets traffic. If the build fails or the health check never
  passes, **the old container keeps serving** and nothing has changed for users.
- **There is no gradual rollout.** With one instance, all users are on the old
  version and then all on the new one.
- The container applies database schema migrations when it starts
  (`alembic upgrade head` in `docker-entrypoint.sh`), so the schema changes
  *before* the old container stops, and stays changed after a rollback.
- Scheduled jobs run inside the container (supercronic). A deploy stops the old
  container, and a job running in it with it.
- A container's log is gone when a deploy replaces the container. What is needed
  from the old one (the baseline of step 2) must be read before the deploy.

## Finding the app

The apps belong to two Digital Ocean teams: Netskrafl production and the staging
app to one, Explo production to another. `doctl` only sees the apps of the team
whose API token it runs with, and the rollback calls need the same token. Set it
per app, and find the app from the branch it deploys, not from memory:

```bash
BRANCH=do-netskrafl        # do-explo for explo-live, do-deploy for explo-dev (the staging app)

# The API token of the team that owns the app. doctl uses the environment
# variable in place of its configured token.
TOKEN=$(awk '/access-token:/ {print $2; exit}' ~/.config/doctl/config.yaml)     # netskrafl, explo-dev
# TOKEN=$(tr -d '[:space:]' < "$EXPLO_TEAM_TOKEN_FILE")                         # explo-live
export DIGITALOCEAN_ACCESS_TOKEN="$TOKEN"

APP=$(doctl apps list -o json | jq -r --arg b "$BRANCH" \
  '.[] | select(.spec.services[0].github.branch == $b) | .id')
[ -n "$APP" ] || echo "No app deploys $BRANCH for this token: is it the right team's?"
INFO=$(doctl apps get "$APP" -o json)
COMPONENT=$(jq -r '.[0].spec.services[0].name' <<<"$INFO")
HOST=$(jq -r '.[0] | .spec.domains[0].domain
              // (.default_ingress | sub("^https://"; "") | sub("/$"; ""))' <<<"$INFO")
DEPLOYED=$(jq -r '.[0].active_deployment.services[0].source_commit_hash' <<<"$INFO")
PREVIOUS_DEPLOYMENT=$(jq -r '.[0].active_deployment.id' <<<"$INFO")
```

- The file that holds the Explo production team's token is named in the
  machine's private notes, not here. A release to `explo-live` uses both teams:
  the staging app with one token, production with the other. Set `TOKEN` anew
  whenever you turn from one app to the other.
- `DEPLOYED` is the commit that is serving now. `PREVIOUS_DEPLOYMENT` is the
  rollback target: **record both before deploying** (shell variables do not
  survive from one command to the next; keep the values).
- `HOST` is the app's own address: its custom domain if it has one, otherwise
  the address the platform gave it.
- **Never print the output of `doctl apps get -o json` or `doctl apps spec get`
  whole, or leave a copy of it behind.** The spec in it holds the log service's
  API key in plain text (the platform encrypts the `SECRET` environment
  variables, but not the key of a log destination).

**Explo production is reached through a forwarder.** The Explo apps call the old
App Engine address, where a forwarding app passes every request on to the
container (`appspot-forward/`). So for `explo-live` there are two addresses to
probe, the container's own (`HOST`) and the one the users use:

```bash
FORWARD_HOST=$(gcloud app describe --project=explo-live --format='value(defaultHostname)')
```

and App Engine's request log shows what the users got (step 6). The forwarder
is not part of a release: it stays as it is, and a deploy never touches App
Engine (see "What is left on App Engine").

## 1. Confirm scope and name the release

- `git fetch origin --tags`, then `git status -s` and `git log --oneline -1`. The
  commit to release (`COMMIT`) must be on GitHub, normally `origin/master`. Warn
  if the working tree is dirty or `HEAD` is not the intended commit.
- Release name (production targets): `BASE="n$(date -u +%Y%m%d)"` for netskrafl,
  `e...` for explo-live. If the tag `BASE` exists (`git tag -l "$BASE*"`), append
  the first free lowercase letter.
- Show the user what the release contains: `git log --oneline $DEPLOYED..$COMMIT`,
  with `DEPLOYED` of the target app.

## 2. Look at what the release changes

Check each of these and tell the user what you found, before asking to deploy.
`DEPLOYED` is the production app's commit; run the deployment-in-progress check
for the staging app as well:

| Check | Command | Why it matters |
|---|---|---|
| Schema migrations | `git diff --stat $DEPLOYED..$COMMIT -- migrations/` | **A release with a migration cannot be rolled back** by redeploying the old version: the old container does not know the new schema revision and fails to start. The migration must also work with the *old* code, which keeps serving while the new container starts. Say so explicitly: the fallback for such a release is a fix forward, and it stops for a second "yes" after the canary (step 3). |
| Container build | `git diff --stat $DEPLOYED..$COMMIT -- Dockerfile docker-entrypoint.sh crontab requirements*.txt .dockerignore` | App Platform builds with kaniko, which differs from a local `docker build` (see `CLAUDE.md`). The canary is what proves a build change. |
| Deployment in progress | `doctl apps list-deployments "$APP"` | Starting a deployment while another is in progress cancels the first. Wait for it. |
| Time of day | `date -u` | Do not deploy between 02:55 and 04:30 UTC: the nightly jobs run then, and the deploy would stop one halfway. Prefer a quiet time of day for anything risky. |
| Staging | `git merge-base --is-ancestor $COMMIT $STAGING_DEPLOYED && echo yes` (`STAGING_DEPLOYED`: the staging app's `DEPLOYED`) | Is the staging app already running this commit? If so, step 3 does not deploy it again, but it still runs the standard test and reads the log. |
| What the canary cannot show | read the diff | The staging app runs the Explo configuration with little data. Say which of the changes it does not exercise: Netskrafl-only behaviour (the web pages, the login from Málstaður, the old-style rating tables), queries whose cost depends on production's data volume, behaviour under load. Those are what to look at first in production. |
| Baseline | the log sample and the metrics of step 6, taken from the production app now | What the new version's samples are compared with: the usual warnings, the response times, the memory use. The old container's log is gone after the switch. |

**Then tell the user the target, the release name, the commit, the findings
above, the route (canary first and then production, or straight to production
because the user asked for that) and the fallback (a rollback to
`PREVIOUS_DEPLOYMENT`, or a fix forward if the release has a migration), and get
an explicit "yes".** For a production release that "yes" covers both steps: the
canary and, if everything there is clean, the production deploy. Say so when
asking.

## 3. The canary: the staging app

Skip this step only when the user asked for a release straight to production.
For the target `explo-dev` this step is the whole release: go on to step 7
after it.

1. **Deploy**, unless the staging app already runs `COMMIT` (the check in step
   2). `do-deploy` is a merge-commit branch: check it out, bring it up to date
   with `origin/do-deploy`, `git merge $COMMIT`, push it, and return to the
   previous branch. It has no version label.
2. **Watch the build and the switch** as in step 5, with the staging app's `APP`,
   `COMPONENT` and `HOST`. The serving commit is a merge commit of `do-deploy`;
   it must contain `COMMIT` (`git merge-base --is-ancestor`).
3. **Run the standard test**, `utils/staging-check.py`. It plays through the key
   operations as the app does, over HTTPS, with three test users that exist only
   on the dev backend: a guest login, a game against a robot with a generated
   move and the robot's answer, the vocabulary of every locale, and two
   registered users who log in, challenge each other, play, chat and resign. It
   takes a few seconds, prints one line per check, and exits with status 0 only
   if every check passed:
   ```bash
   PROJECT_ID=explo-dev GOOGLE_CLOUD_PROJECT=explo-dev RUNNING_LOCAL=true \
   GOOGLE_APPLICATION_CREDENTIALS=credentials/explo-dev/service-account.json \
     venv/bin/python utils/staging-check.py "https://$HOST"
   ```
   It only works against the dev backend, and refuses any other project. If the
   release changes something that the test does not cover and that the Explo
   configuration can exercise (an API call, a job), try that by hand as well,
   and consider adding it to the test.
4. **Read the log** as in step 6, items 1 to 3: the right commit, a log sample
   that covers the start-up, the test's own requests (they are in the log under
   the test users' ids) and at least two runs of the scheduled jobs. Five
   minutes are enough here.
5. Tell the user what the canary showed. Then:
   - **Everything clean**: go on to step 4 for production, under the "yes" from
     step 2.
   - **Anything abnormal** (a failed build, a health check that did not pass, a
     failed check in the standard test, errors, 5xx answers, restarts, slow
     answers, a failed job): stop. Production has not been touched. Report it,
     fix on master, and start again from step 1. Treat a bad staging deployment
     as in "When a deploy goes wrong": the Explo dev app has users too.
   - **The release has a schema migration**: stop even when everything is clean,
     report, and get a second "yes" before production. The step after this one
     cannot be undone.

Do not let much time pass between the canary and production, and check before
step 4 that `origin/master` has not moved past `COMMIT`: production gets
`COMMIT`, the commit that the canary ran, not whatever is newest.

## 4. Deploy to production

With the production app's `TOKEN` and `APP`, and with `DEPLOYED` and
`PREVIOUS_DEPLOYMENT` recorded.

First hold back the one alert that a deploy would set off. The alerts go to a
channel that is only for things someone has to act on, and a deploy is normal
operation; but it starts the server, which the monitor on server starts cannot
tell from a restart by the platform. Mute that monitor for the time of the
deploy (`<target>` is `netskrafl` or `explo-live`; the keys of the log service
are in the environment variables `DD_API_KEY` and `DD_APP_KEY`, from the files
named in the machine's private notes):

```bash
venv/bin/python utils/datadog-setup.py --service <target> --mute-starts 30
```

Then push. The deploy branch only ever points at a commit of master, so the push
is a fast-forward (never force it):

```bash
git push origin $COMMIT:$BRANCH        # do-netskrafl or do-explo
```

Then set the version label, right away, while the build is still running. The app
reads it from the environment variable `APP_VERSION` in its spec (it is the
cache-busting suffix of static files, and the `version` of every log entry).
Round-trip the live spec; never apply the checked-in specs in `.do/`, which have
placeholders for the secrets:

```bash
doctl apps spec get "$APP" --format json > "$SPEC"      # $SPEC: a file in a private temp directory
# set the value of the service env var APP_VERSION to the release name, check
# that nothing else differs from the live spec, then:
doctl apps update "$APP" --spec "$SPEC" && rm "$SPEC"
```

The spec update cancels the build that the push started and starts a new one
from the same commit with the new label, so users see one switch, not two.
Step 6 checks that the commit serving in the end is indeed `COMMIT`.

## 5. Watch the build and the switch

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

While the deployment is `DEPLOYING`, probe the app every few seconds and count
the answers that are not 200, to see whether the switch dropped requests. For
`explo-live`, probe `FORWARD_HOST` in the same way, at the same time:

```bash
curl -s -o /dev/null -m 10 -w "%{http_code} %{time_total}\n" "https://$HOST/health/ready"
```

## 6. Verify the new version, and watch it

1. It is the right code and it is active:
   ```bash
   doctl apps get "$APP" -o json | jq -r '.[0].active_deployment | .phase, .services[0].source_commit_hash'
   ```
   The commit must equal `COMMIT`.
2. It answers: `/health/ready` gives 200; an API call without a login (for
   instance `POST /gamelist`) gives 401, not 5xx. For `explo-live`, on both
   addresses.
3. **Take log samples**: the first as soon as the new container serves, then
   every few minutes, for at least 10 minutes in production (longer for a risky
   release, and until the changed code has demonstrably been used by real
   requests). The container writes one JSON entry per line (see
   `doc/logging.md`); `doctl` puts the component name and a timestamp in front of
   each. Report what each check shows; empty output means clean:
   ```bash
   doctl apps logs "$APP" "$COMPONENT" --type run --tail 3000 \
     | sed 's/^[^{]*//' | jq -c -R 'fromjson? // empty' > "$LOG"    # the JSON entries only
   # application problems (supercronic's entries have "level" instead of "status")
   jq -r 'select((.status // .level) | IN("warning","error","critical","fatal"))
          | "\(.timestamp // .time) \(.status // .level) \(.message // .msg)"' "$LOG"
   # failed requests
   jq -r 'select(.event == "request" and .http.status_code >= 500) | .message' "$LOG"
   # requests by path and status: the changed endpoints should be among them
   jq -r 'select(.event == "request") | "\(.http.url_details.path) \(.http.status_code)"' "$LOG" \
     | sort | uniq -c | sort -rn | head -30
   # the scheduler (a job every 2 minutes), and what the jobs reported
   jq -r 'select(.msg == "job succeeded" or .msg == "job failed") | .msg' "$LOG" | sort | uniq -c
   jq -r 'select(.event == "job") | "\(.timestamp) \(.message)"' "$LOG"
   # one start of the server and of each worker is the deploy itself;
   # anything more, or a worker timeout, is a restart
   jq -r 'select(.logger.name == "gunicorn" and (.message | test("Starting gunicorn|Booting worker|WORKER TIMEOUT")))
          | "\(.timestamp) \(.message)"' "$LOG"
   # response times of the requests, in milliseconds
   jq -s '[.[] | select(.event == "request") | .duration_ms] | sort
          | {n: length, p50: .[length * 0.5 | floor], p99: .[length * 0.99 | floor], max: .[-1]}' "$LOG"
   ```
   Lines that are not JSON (the entrypoint's start-up messages, the moves
   sidecar) are left out by the first command; read the raw log if a start-up
   problem is suspected.

   The container's CPU, memory and restart count, where the team's token may
   read them (the answer is otherwise "not authorized", and the gunicorn check
   above is what shows restarts):
   ```bash
   NOW=$(date +%s)
   for M in cpu_percentage memory_percentage restart_count; do
     curl -s -H "Authorization: Bearer $TOKEN" \
       "https://api.digitalocean.com/v2/monitoring/metrics/apps/$M?app_id=$APP&app_component=$COMPONENT&start=$((NOW-1800))&end=$NOW" \
       | jq -c --arg m "$M" '{($m): (if .data then [.data.result[]
            | {max: ([.values[][1] | tonumber] | max), last: (.values[-1][1] | tonumber)}] else .message end)}'
   done
   ```

   For `explo-live`, also what the users got, from App Engine's request log of
   the forwarder (status and latency per request; a 502 or 503 there means the
   forwarder could not reach the container):
   ```bash
   gcloud logging read 'resource.type=gae_app AND resource.labels.module_id=default
       AND logName:"request_log" AND timestamp>="<start, UTC, ISO 8601>"' \
     --project=explo-live --limit=20000 --format='value(protoPayload.status,protoPayload.latency)' \
     | cut -f1 | sort | uniq -c
   ```
4. **Judge each sample against the baseline of step 2**, not against zero: some
   warnings are normal (expired login tokens, refused requests). What counts is
   what is new or more frequent since the switch. Normal response times, as the
   backend logs them, are a median of 20 to 30 ms with nearly all requests under
   300 ms. Any of these in a sample is a bad sample:
   - a request answered with a 5xx status, or an `error` or `critical` entry,
     that the baseline does not have;
   - a restart: a second start of the server or of a worker, a worker timeout, a
     restart count above zero;
   - a scheduled job that failed;
   - response times clearly above the baseline, or memory use that keeps
     climbing from sample to sample;
   - for `explo-live`, 5xx answers in the forwarder's log.

   **On a bad sample, do not wait for the next one.** Go to "When a deploy goes
   wrong": run the rollback validation at once (it changes nothing), tell the
   user what the sample shows, recommend the rollback and ask for the "yes".
5. Ask the user to try the change itself, and one ordinary thing: log in, open a
   game, make a move.

## 7. Finish

- **Tag the release** (production targets), on the commit that is serving:
  ```bash
  git tag -a <NAME> $COMMIT -m "<target> production release <NAME> $(date -u +%F)"
  git push origin <NAME>
  ```
  This is part of the deploy the user approved. Do not tag a release that was
  rolled back. Never move or delete an existing release tag.
- **Publish a GitHub release** for the tag, with release notes:
  ```bash
  gh release create <NAME> --verify-tag --title "Version <NAME>" --notes-file "$NOTES"
  ```
  Write the notes for someone who was not there: a heading that names the main
  changes, then one short section per change that users or operators can notice
  (what was wrong or missing, what changed), with the pull request numbers, and
  smaller things in a list at the end. Cover everything since the target's
  previous release tag (`git log --merges <previous tag>..<NAME>`), and say so if
  some of it went live earlier without a tag. See an earlier release for the form
  (`gh release list`, `gh release view`). The repository is public: no
  hostnames, deployment names, accounts or other operational details.
- Report: release name, commit, when the switch happened, whether any probe
  failed during it, what the canary showed (the standard test's result, or that
  the canary was skipped at the user's request), what the log samples showed,
  and the rollback target that remains.

## When a deploy goes wrong

| What you see | What it means | What to do |
|---|---|---|
| Build `ERROR` | The image could not be built. The old version is serving. | Nothing is broken. Read the build log, fix on master, deploy again. |
| Deployment `ERROR` after the build; health check never passed | The new container did not start or could not reach the database or the cache. The old version is serving. | Nothing is broken for users. Read the deploy and run logs. **If the release had a migration, check whether it was applied** (`select version_num from alembic_version`): if so, the old code is now running on the new schema; watch it and fix forward quickly. |
| New version `ACTIVE`, and a bad log sample: errors, 5xx answers, restarts or slow answers | A bad release is serving everyone. | Decide within minutes: validate the rollback, recommend it to the user (below), unless the release had a migration. Do not debug in production while users are affected. |
| New version `ACTIVE`, one feature misbehaves, the rest is fine | A contained bug. | Tell the user what is affected and offer both: roll back now, or fix forward. The user chooses. |
| The release had a migration and the new version is bad | Rollback by redeploying is not available. | **Fix forward**: the fastest safe fix or revert of the *code* on master, keeping the migration, then deploy again. A schema downgrade is a decision for the user, never a reflex. |
| Data was damaged | A rollback does not repair data. | Stop the damage first (roll back or fix forward), then tell the user exactly what was written wrongly and since when. Restoring from the managed database's backups is the user's decision. |
| `explo-live`: the container's own address answers, the forwarder's does not | The fault is between the users and the container (the forwarder, or App Engine), not in the release. | Do not roll the release back for it. Report it, with what the forwarder's log shows. |
| The platform itself is failing (no deployments, app unreachable, old and new alike) | Not caused by the release. | Do not push more changes. Report it and check the provider's status page. **App Engine is not a fallback** for either production app: its data stopped at the move. |

### Rollback

A rollback creates a new deployment from an earlier one, without a rebuild. The
command-line client has no command for it; it is done through the API, with the
token of the team that owns the app (`TOKEN`, see "Finding the app"):

```bash
API="https://api.digitalocean.com/v2/apps/$APP"
ROLLBACK='{"deployment_id": "'$PREVIOUS_DEPLOYMENT'"}'

# 1. Is it possible? Changes nothing. Expect {"valid": true}; read any warnings.
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "$ROLLBACK" "$API/rollback/validate"

# 2. Roll back (after the user's "yes")
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "$ROLLBACK" "$API/rollback"
```

A rollback starts the server too: mute the alert on that first, as in step 4.
Then watch the rollback as in step 5 and verify as in step 6 (the serving commit
is `DEPLOYED` again). What to know:

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
  the rollback, then deploy the fix as a new release (from step 1). The deploy
  branch still points at the bad commit until then, which is fine: it only moves
  forward.
- **It does not undo schema migrations or data changes**, and it fails for a
  release that contained a migration (see the table).
- As of 2026-11-20 the validation call has been used against both production
  apps, but an actual rollback has not been carried out on any of the three.
  Until one has been rehearsed on the staging app, say so when recommending it,
  and watch the first one closely.

After any incident, tell the user plainly what happened, from when to when users
were affected, and what state the app, the deploy branch and the database schema
are in now.

## What is left on App Engine

No backend serves users from App Engine any more, and nothing in this skill
deploys there. What remains:

- In the netskrafl project, a small app that redirects browsers to Netskrafl's
  new home (`appspot-redirect/`). In the explo-live project, the forwarder that
  passes the Explo apps' requests on to the container (`appspot-forward/`). Each
  is deployed with its project's deploy script and given traffic by hand. That
  is rare, it is not a release in the sense of this skill, and each step of it
  needs the user's explicit "yes".
- The earlier backend versions, which served from Datastore, still exist in
  both projects. **Never route traffic to one of them**, for any reason: their
  data stopped at the move, so users would see an old state and what they wrote
  would be lost. Do not delete or stop them unless the user asks.
- The App Engine cron configuration is empty in all three projects: the jobs run
  in the containers. Do not deploy `cron.yaml`.

## Notes

- All three backends run on PostgreSQL. The Datastore (NDB) backend is still in
  the code, but no deployment uses it.
- The **push to a deploy branch** and the **spec update** are the sensitive
  steps: gate them on the user's confirmation as described in step 2. Production
  is pushed only after the same commit has run well on the staging app, unless
  the user asked for a release straight to production.
- The `doctl` commands for reading (`list`, `get`, `logs`, `spec get`), the
  standard test and the muting of the server-start alert are pre-approved for
  this skill. `doctl apps update`, the pushes
  and the rollback calls are not, on purpose: each one is confirmed when it is
  made.
- An alert that arrives during a deploy is information about the release:
  none is expected once the server-start alert is muted. Treat one as a bad
  sample (step 6).
- If `gcloud` is not authenticated for the explo-live project (the forwarder's
  log), use the project's service-account key:
  `CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE=<credentials file>`.
