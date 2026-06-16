---
name: deploy
description: Deploy a new App Engine version of this project and roll traffic out gradually (canary). Use when the user asks to deploy, ship, release, or promote a build to GAE (netskrafl, explo-live, or explo-dev). Defaults to the netskrafl project.
user-invocable: true
allowed-tools:
  - Read
  - Bash(date *)
  - Bash(git *)
  - Bash(grunt *)
  - Bash(gcloud app *)
  - Bash(gcloud scheduler *)
  - Bash(gcloud logging *)
  - AskUserQuestion
---

# /deploy — App Engine deployment with gradual traffic rollout

Deploys a new version of the default service to Google App Engine **without
promoting it**, then shifts traffic to it in stages (10% → 25% → 50% → 100%),
pausing to check logs at each step. Old versions are **never deleted** so a
deploy can be reverted instantly.

**This is a production action.** Only act on an explicit deploy request typed by
the user. Stop and get a clear "yes" before the initial deploy and before every
traffic increase. Never delete or stop old versions unless the user asks.

## Arguments

`$ARGUMENTS` may contain:
- A target project: `netskrafl` (default if omitted), `explo-live`, or `explo-dev`.
- An optional explicit version id (e.g. `n20260616b`). If omitted, compute it.

## Target configuration

| Target      | app.yaml              | credentials                                 | project     | prefix | scheduler update |
|-------------|-----------------------|---------------------------------------------|-------------|--------|------------------|
| netskrafl   | `app-netskrafl.yaml`  | `credentials/netskrafl/service-account.json`| `netskrafl` | `n`    | yes (`update_online_status`, location `us-central1`) |
| explo-live  | `app-explo-live.yaml` | `credentials/explo-live/service-account.json`| `explo-live`| `e`    | none |
| explo-dev   | `app-explo.yaml`      | `credentials/explo-dev/service-account.json`| `explo-dev` | `e`    | none |

The default service name is `default`.

## Procedure

### 1. Confirm scope and compute the version

- Determine the target from `$ARGUMENTS` (default `netskrafl`).
- Confirm what is being deployed: run `git status -s` and `git log --oneline -1`.
  Warn if the working tree is dirty or `HEAD` is not the merged/intended commit.
- Compute the version id unless one was given:
  - `BASE="<prefix>$(date +%Y%m%d)"` (e.g. `n20260616`).
  - List existing ids: `gcloud app versions list --project=<project> --service=default --format="value(version.id)"`.
  - If `BASE` is free, use it. Otherwise append the first free lowercase letter:
    `BASE` taken → try `${BASE}a`, `${BASE}b`, … (matches the convention: add
    `a`,`b`,`c`… for multiple releases on the same day).
- **Tell the user the exact target project and version id, and get explicit
  confirmation before deploying.**

### 2. Build and deploy (no promote)

Run from the repo root. Build the frontend, then upload the version with **zero
traffic** (`--no-promote`):

```bash
grunt make
GOOGLE_APPLICATION_CREDENTIALS=<creds> PROJECT_ID=<project> \
  gcloud app deploy --no-cache --version=<VERSION> --no-promote \
  --project=<project> <app.yaml> --quiet
```

(This mirrors `./deploy-<target>.sh default <VERSION>` but keeps the traffic
rollout and scheduler update under this skill's control.)

`grunt make` needs Node deps (`npm install` if `grunt` is missing). The
`gcloud app deploy` step can take several minutes — allow a long timeout
(up to ~10 minutes) so it isn't cut off mid-upload.

### 3. Verify the upload

```bash
gcloud app versions list --project=<project> --service=default \
  --filter="version.id=<VERSION>" \
  --format="table(version.id, traffic_split, version.servingStatus)"
```

Confirm the new version exists, is `SERVING`, and has `traffic_split = 0.00`.
Record the **current** version (the one at `traffic_split = 1.00`) as `CURRENT` —
this is the rollback target.

### 4. Gradual traffic rollout (human-gated)

Use cookie-based splitting for `netskrafl` (sticky sessions for the web game);
`--split-by=random` is acceptable for the Explo API backends.

For each stage in **10% → 25% → 50% → 100%**:

1. **Ask the user to confirm** advancing to this stage. Do not proceed without it.
2. Set the split (replace `<P>` with the percentage as a fraction):

   ```bash
   # intermediate stages keep CURRENT serving the remainder
   gcloud app services set-traffic default \
     --splits=<VERSION>=<P>,<CURRENT>=<1-P> \
     --split-by=cookie --project=<project> --quiet
   ```
   At the final stage send 100% to the new version:
   ```bash
   gcloud app services set-traffic default \
     --splits=<VERSION>=1 --split-by=cookie --project=<project> --quiet
   ```
3. **Monitor** for a few minutes before offering the next stage. Run all three
   checks and report what each shows — **empty output means clean**:
   ```bash
   # a) recent request stream — confirm core endpoints return 200
   gcloud app logs read --project=<project> --service=default \
     --version=<VERSION> --limit=50

   # b) WARNING-or-above app logs (captures warnings AND errors in one pass)
   gcloud logging read \
     'resource.type=gae_app AND resource.labels.version_id=<VERSION> AND severity>=WARNING' \
     --project=<project> --freshness=10m --limit=30 --format="value(severity)"

   # c) failed requests — any 4xx/5xx HTTP statuses
   gcloud logging read \
     'resource.type=gae_app AND resource.labels.version_id=<VERSION> AND httpRequest.status>=400' \
     --project=<project> --freshness=10m --limit=20 \
     --format="table(timestamp, httpRequest.status, httpRequest.requestUrl)"
   ```
   Use `severity>=WARNING` (not just `ERROR`) so significant warnings are
   surfaced too. A rise in warnings or non-200 statuses on the new version is a
   signal even without hard errors. If anything looks abnormal, **stop and
   recommend rollback** (step 6) rather than advancing.

### 5. Post-promote (netskrafl only)

Once the new version is at 100% and healthy, repoint the online-status scheduler
job (it is pinned to a specific version):

```bash
gcloud scheduler jobs update app-engine update_online_status \
  --version=<VERSION> --project=netskrafl --location=us-central1
```

(`Clear-Redis` is yearly and does not need updating. explo-live/explo-dev have no
such job.)

### 6. Finish

- **Do not delete or stop old versions** — leave them for rollback. Mention to
  the user that older versions remain and can be cleaned up later.
- Report the final state: `gcloud app versions list --project=<project> --service=default --format="table(version.id, traffic_split, version.servingStatus)"`.

## Rollback

To instantly route all traffic back to the previous version:

```bash
gcloud app services set-traffic default --splits=<CURRENT>=1 \
  --split-by=cookie --project=<project> --quiet
# netskrafl: also repoint the scheduler back
gcloud scheduler jobs update app-engine update_online_status \
  --version=<CURRENT> --project=netskrafl --location=us-central1
```

## Notes

- All environments currently run the **NDB** backend (no `DATABASE_BACKEND` set
  in the app.yaml files), so PostgreSQL-only changes are inert in production
  until that migration flips.
- `gcloud app deploy --no-promote` is safe (no traffic); the **traffic stages**
  are the sensitive steps — gate each one on explicit user confirmation.
- If `gcloud` is not authenticated for the target project, ask the user to run
  the login themselves (e.g. `! gcloud auth login`) since it is interactive.
