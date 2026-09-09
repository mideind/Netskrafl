# Coordinated dictionary updates across Netskrafl, Explo, GoSkrafl and Skrafl

The Icelandic vocabulary lives in this repository and is consumed by four
products. A fix to a word list is not done until all four have been rebuilt and
deployed. This runbook records the dependencies and the exact procedure, as
verified on 2026-09-08 (removal of the bogus `tæknifrj*` paradigm).

## Where the vocabulary lives and who consumes it

| Consumer | What it uses | How it gets it | Deployed how |
|---|---|---|---|
| Netskrafl / Explo on GAE (`netskrafl`, `explo-live`, `explo-dev`) | `resources/*.bin.dawg` (18 files, see `_ALL_DAWGS` in `src/wordbase.py`) | Whatever `.bin.dawg` files exist in `resources/` at deploy time are uploaded (`.gcloudignore` does not exclude them). Explo loads all 18 at startup, so all must be present. | `/deploy` skill (canary rollout) |
| Netskrafl container (Digital Ocean, branch `do-deploy`) | same `.bin.dawg` files | Downloaded at build time from the CDN `https://netskrafl-cdn.ams3.digitaloceanspaces.com/dawg/` | push to `do-deploy` |
| GoSkrafl `moves` service (GAE service `moves` on `explo-dev` and `explo-live`; also the loopback sidecar in the container) | `dicts/*.bin.dawg` committed in the GoSkrafl repo, `go:embed`-ded | Copied by hand from `resources/` here | `go-app/deploy.sh <ver>` (explo-dev), `go-app/deploy-live.sh <ver>` (explo-live); the container pins `GOSKRAFL_COMMIT` in `Dockerfile` |
| Skrafl (`skraflhjalp.appspot.com`, repo `vthorsteinsson/Skrafl`) | its own copies of `ordalisti.full.sorted.txt`, `ordalisti.add.txt`, `ordalisti.remove.txt`, built into `resources/ordalisti.dawg.pickle` by its own stdlib-only `dawgbuilder.py` | Copied by hand from `resources/` here. **Rule: Skrafl's dictionary must always be identical to Netskrafl's full Icelandic dictionary.** | `gcloud app deploy --no-cache --no-promote --project=skraflhjalp --version=<ver> app.yaml` |

Icelandic source lists in `resources/`:

- `ordalisti.full.sorted.txt` — BÍN-derived full list (→ `ordalisti.bin.dawg`)
- `ordalisti.mid.sorted.txt` — Miðlungur robot list (→ `midlungur.bin.dawg`)
- `ordalisti.aml.sorted.txt` → filtered by `run_icelandic_filter` into
  `ordalisti.aml.filtered.txt` (→ `amlodi.bin.dawg`)
- `ordalisti.add.txt` — additions, applied to the full and mid builds
- `ordalisti.remove.txt` — known errors, applied to the full and mid builds
  (not to Amlóði). Entries only need to exist; forms absent from the lists are
  harmlessly ignored, so adding a whole paradigm is fine.

A recurring class of error is a phantom BÍN lemma that produces a whole
compound paradigm (`allfrj*` in 2021, `tæknifrj*` in 2026: the lemma "frj").
When one turns up, grep the full list for the paradigm suffixes to catch
sibling compounds before adding to the remove list.

## Procedure

Prerequisites on the build machine: Python 3.11 (the builder is stdlib-only,
no venv needed), Go (for GoSkrafl tests), `gcloud` logged in as an owner of
the four projects, Node deps (`npm install`) for the GAE frontend build.
Service-account JSON files are **not** needed for deploying; gcloud uses the
logged-in account. GoSkrafl's gitignored `go-app/env.yaml` (`ACCESS_KEY`,
`ALLOWED_ORIGINS`) can be recreated from the live service:
`gcloud app versions describe <ver> --service=moves --project=explo-live --format=yaml(envVariables)`.

1. **Edit the lists** in `resources/` (usually `ordalisti.remove.txt` or
   `ordalisti.add.txt`).
2. **Rebuild the Icelandic DAWGs:**
   `PROJECT_ID=netskrafl python3.11 utils/dawgbuilder.py skrafl`
   (about 1 minute; writes `ordalisti`, `midlungur`, `amlodi` `.bin.dawg`).
3. **Verify by word set, not by checksum.** The packed layout is not
   byte-deterministic between builds. Enumerate the words of the new file and
   of the CDN copy and diff them; the diff must be exactly the intended change.
   A small enumerator over `PackedDawgDictionary` (walk the edges from offset 0,
   emitting on node-final bits and on `c|` final markers inside collapsed
   prefixes) does this in under a minute.
4. **Make sure all 18 DAWGs exist in `resources/`** before a GAE deploy. The
   non-Icelandic ones rebuild identically from the repo
   (`osps37 nsf2023 nynorsk2024 otcwl2014 sowpods english_robot_vocabs
   polish_robot_vocabs`), **except the four Norwegian robot vocabularies**
   (`nsf2023.aml/.mid`, `nynorsk2024.aml/.mid`), whose filters need the
   gitignored Leipzig corpora `nob-no_web_2020_300K-words.txt` and
   `nno-no_web_2020_300K-words.txt`. Without them, copy the CDN files.
5. **Upload to the CDN:** needs the Spaces access key ID in `DO_SPACES_KEY`
   and the secret in `DO_SPACES_SECRET` or `credentials/netskrafl/cdn.key`
   (keys are generated in the DO control panel under API → Spaces Keys). The
   uploader needs boto3, so without a venv run
   `DO_SPACES_KEY=... uv run --no-project --python 3.11 --with boto3 python utils/dawgbuilder.py --upload-only`.
   Verify by fetching every file back from
   `https://netskrafl-cdn.ams3.digitaloceanspaces.com/dawg/` and `cmp`-ing it
   against `resources/`. Only the container build reads the CDN, but it must
   be refreshed **before** pushing `do-deploy`, or the container's Python
   engine and its GoSkrafl sidecar will disagree.
6. **GoSkrafl:** copy `ordalisti.bin.dawg` and `amlodi.bin.dawg` into
   `dicts/`, run `go test ./...`, commit, push. Then set `GOSKRAFL_COMMIT` in
   this repo's `Dockerfile` to the new hash.
7. **Skrafl:** copy all three `ordalisti.*.txt` lists into its `resources/`,
   run `python3.11 dawgbuilder.py` there (about 30 s, writes the gitignored
   `ordalisti.text.dawg` and `ordalisti.dawg.pickle`; only the pickle is
   uploaded). Verify its word set equals `ordalisti.bin.dawg`'s. Commit the
   lists, push (remote must be SSH).
8. **Commit and push this repo** (lists + Dockerfile pin).
9. **Deploy, lowest impact first:** Skrafl (`--no-promote`, check
   `/?rack=<word>` on the versioned URL, then migrate traffic), GoSkrafl
   `moves` to explo-dev then explo-live, then Netskrafl to `netskrafl` and
   `explo-live` via `/deploy`, then the Digital Ocean container (merge master
   into `do-deploy`, push, watch `doctl apps list-deployments`). GAE versions
   are never deleted, so each step can be reverted by moving traffic back.

   Which explo-dev surfaces matter (as of 2026-09-08): the Explo dev app is
   routed to the Digital Ocean container, so the GAE `default` service on
   `explo-dev` is dormant and need not be deployed. The GAE `moves` service on
   `explo-dev` is **not** dormant: Netskrafl production resolves its moves URL
   there (see `MOVES_SERVICE_URL` in `src/config.py`), so it must be updated.

## Verification cheat-sheet

- Skrafl: `https://<ver>-dot-skraflhjalp.appspot.com/?rack=<word>`; the removed
  word must not appear as a `resultword`.
- GoSkrafl: `go test ./...` plus a `/wordcheck` call against the versioned
  `moves` URL.
- Netskrafl/Explo: word check through the game API on the versioned URL, and
  the `/deploy` skill's log checks.
