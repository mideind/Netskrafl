# Coordinated dictionary updates across Netskrafl, Explo, GoSkrafl and Skrafl

The Icelandic vocabulary lives in this repository and is consumed in several
places. A fix to a word list is not done until all of them have been rebuilt
and deployed. This runbook records the dependencies and the procedure. It was
first verified on 2026-09-08 (removal of the bogus `tæknifrj*` paradigm) and
revised in November 2026, when the backends moved from App Engine to
containers (`operations.md`); the steps that changed then are marked.

## Where the vocabulary lives and who consumes it

| Consumer | What it uses | How it gets it | Deployed how |
|---|---|---|---|
| The backend containers (Netskrafl production, Explo production, the staging app) | `*.bin.dawg` (all files in `_ALL_DAWGS` in `src/wordbase.py`; Netskrafl loads the Icelandic ones only) | Downloaded **from the CDN when the image is built** (`DAWG_BASE_URL` in the `Dockerfile`). The files in `resources/` of a checkout do not reach an image | `/deploy` skill: the staging app first, then the production apps |
| GoSkrafl as the sidecar in those containers | `dicts/*.bin.dawg` committed in the GoSkrafl repo, `go:embed`-ded | Copied by hand from `resources/` here | Built into the image from the commit pinned as `GOSKRAFL_COMMIT` in the `Dockerfile` |
| GoSkrafl as the App Engine `moves` service, in the development project (Málstaður's word checks for Netskrafl) and in Explo's production project (the Explo apps' word checks) | the same embedded files | the same | GoSkrafl's own deploy scripts, one per project |
| Skrafl (the word-helper site, repo `vthorsteinsson/Skrafl`, on App Engine in a project of its own) | its own copies of `ordalisti.full.sorted.txt`, `ordalisti.add.txt`, `ordalisti.remove.txt`, built into a pickled DAWG by its own stdlib-only `dawgbuilder.py` | Copied by hand from `resources/` here. **Rule: Skrafl's dictionary must always be identical to Netskrafl's full Icelandic dictionary.** | `gcloud app deploy --no-promote` from its repository, then move the traffic |

Icelandic source lists in `resources/`:

- `ordalisti.full.sorted.txt` — BÍN-derived full list (→ `ordalisti.bin.dawg`)
- `ordalisti.mid.sorted.txt` — Miðlungur robot list (→ `midlungur.bin.dawg`)
- `ordalisti.aml.sorted.txt` → filtered by `run_icelandic_filter` into
  `ordalisti.aml.filtered.txt` (→ `amlodi.bin.dawg`)
- `ordalisti.add.txt` — additions, applied to the full and mid builds
- `ordalisti.remove.txt` — known errors, applied to the full and mid builds
  (not to Amlóði). Entries only need to exist; forms absent from the lists are
  harmlessly ignored, so adding a whole paradigm is fine.
- `ordalisti.variants.txt` — headwords (`stofn;ordfl`) that BÍN grades as
  incorrect (grade 4) but that are kept in the full list as widely used
  variant spellings (*pítsa*, *partý*, *prótein*), curated by hand. Read only by the SQL
  recipe in `README.md`, which bakes them into `ordalisti.full.sorted.txt`;
  the DAWG builders and Skrafl never see this file. After editing it, reload
  the `ordalisti_variants` table (the README block truncates it first) and
  regenerate the full list; editing the file alone changes nothing.

The full and Miðlungur lists are generated from BÍN's *Kristínarsnið* by the
SQL recipe in `README.md` (section "Generating a new vocabulary file"). The
full list excludes headwords and forms that BÍN grades 4 or higher (incorrect
spellings such as *svasi*, which is correctly *Svasi*, or *allskonar*, correctly
*alls konar*) except the variants above. The robot lists err on the side of
removal, because players object to robots playing questionable words: Miðlungur
takes only grade 1 headwords and forms (plus singular question forms, which BÍN
grades 2), without marked registers or subordinate variant forms; Amlóði is a
subset of Miðlungur; neither has words longer than 10 letters (added
2026-09-23 after a player complaint about *svasi*).

Do not re-run `run_icelandic_filter` with the current venv without first
raising `MIN_ICELANDIC_FREQUENCY`: the icegrams 2.0 model is built from a much
larger corpus and lets about 72,000 more words into Amlóði at the old
threshold. The 2026-09-23 Amlóði list was produced by restricting the previous
filtered list, not by re-running the frequency filter.

A recurring class of error is a phantom BÍN lemma that produces a whole
compound paradigm (`allfrj*` in 2021, `tæknifrj*` in 2026: the lemma "frj").
When one turns up, grep the full list for the paradigm suffixes to catch
sibling compounds before adding to the remove list.

## Procedure

Prerequisites on the build machine: Python 3.11 (the builder is stdlib-only,
no venv needed), Go (for GoSkrafl's tests), `gcloud` logged in with rights to
deploy GoSkrafl's and Skrafl's App Engine services, and the access key of the
CDN's storage (step 5). GoSkrafl's gitignored `go-app/env.yaml` (`ACCESS_KEY`,
`ALLOWED_ORIGINS`) can be recreated from the live service's environment
(`gcloud app versions describe ... --format=yaml(envVariables)`).

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
4. **Mind what else is in `resources/`.** The uploader of the next step
   sends every `.bin.dawg` file it finds there, so the directory should hold
   the files just rebuilt and otherwise files identical to the CDN's. The
   non-Icelandic ones rebuild identically from the repo
   (`osps37 nsf2023 nynorsk2024 otcwl2014 sowpods english_robot_vocabs
   polish_robot_vocabs`), **except the four Norwegian robot vocabularies**
   (`nsf2023.aml/.mid`, `nynorsk2024.aml/.mid`), whose filters need the
   gitignored Leipzig corpora `nob-no_web_2020_300K-words.txt` and
   `nno-no_web_2020_300K-words.txt`. Without them, copy the CDN files.
5. **Upload to the CDN:** needs the storage's access key ID in
   `DO_SPACES_KEY` and the secret in `DO_SPACES_SECRET` or in the key file
   that `utils/dawgbuilder.py` names. The uploader needs boto3, so without a
   venv run
   `DO_SPACES_KEY=... uv run --no-project --python 3.11 --with boto3 python utils/dawgbuilder.py --upload-only`.
   Verify by fetching every file back from the CDN and `cmp`-ing it against
   `resources/`. *(Changed in November 2026: every backend now takes its
   vocabulary from the CDN at build time.)* The CDN must be refreshed
   **before** any backend is deployed, or the container's Python engine and
   its GoSkrafl sidecar will disagree.
6. **GoSkrafl:** copy `ordalisti.bin.dawg` and `amlodi.bin.dawg` into
   `dicts/`, run `go test ./...`, commit, push. Then set `GOSKRAFL_COMMIT` in
   this repo's `Dockerfile` to the new hash.
7. **Skrafl:** copy all three `ordalisti.*.txt` lists into its `resources/`,
   run `python3.11 dawgbuilder.py` there (about 30 s, writes the gitignored
   `ordalisti.text.dawg` and `ordalisti.dawg.pickle`; only the pickle is
   uploaded). Verify its word set equals `ordalisti.bin.dawg`'s. Commit the
   lists, push (remote must be SSH).
8. **Commit and push this repo** (lists + Dockerfile pin).
9. **Deploy, lowest impact first** *(changed in November 2026)*: Skrafl
   (`--no-promote`, check `/?rack=<word>` on the version's own address, then
   move the traffic); GoSkrafl's `moves` service in the development project,
   then in Explo's production project; then the backends with the `/deploy`
   skill: the staging app, Netskrafl production, Explo production. A backend
   release picks up both the CDN files and the pinned GoSkrafl commit when
   its image is built, so a release is needed even if no Python code
   changed. An App Engine version stays available after a deploy, so the
   `moves` and Skrafl steps can be reverted by moving traffic back; a backend
   release is rolled back as the skill describes.

## Verification cheat-sheet

- Skrafl: `/?rack=<word>` on the new version's address; the removed word
  must not appear as a `resultword`.
- GoSkrafl: `go test ./...` plus a `/wordcheck` call against the new
  version of the `moves` service.
- Backends: `utils/staging-check.py` on the staging app checks one valid and
  one invalid word per locale; for the word that was changed, a word check
  through the game API, and the `/deploy` skill's log checks.
