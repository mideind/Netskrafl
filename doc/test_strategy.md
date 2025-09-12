# Test Strategy and Plan for Netskrafl / Explo

This document defines a comprehensive testing strategy and phased approach to strengthen confidence in the Netskrafl/Explo backend and related client-facing behavior prior to releases. It is the base reference for ongoing test hardening, guiding what to test, how to test it, and how to measure readiness.

## Preface

The current test suite validates several high-value paths (login, chat, blocking, images, Elo basics, account deletion) but leaves material gaps across API endpoints, engine rules, time-dependent flows, and negative/authorization cases. This plan lays out pragmatic, high-impact improvements that align with how the system is used in production, while keeping tests deterministic, fast, and maintainable.

## Goals and Principles

- Assurance before deploy: detect regressions and risky changes early.
- Deterministic and fast: minimize flakes with seeded randomness and frozen time.
- Focus where failures hurt: prioritize critical flows and invariants.
- Clear ownership and readability: small, isolated tests with shared fixtures.
- Defense in depth: unit tests for rules, API tests for contracts, and integration for lifecycles.
- Measurable progress: coverage visibility and thresholds for core domains.

## Scope

In scope
- Python backend in `src/` (Flask blueprints: `api`, `web`, `stats`, `firebase`, `riddle`).
- Core game engine and data layers (`skrafl*`, `dawg*`, `languages`, `skrafldb`).
- Test-time stubs for external services (Firebase messaging/presence, billing, GAE specifics) and local filesystem interactions (thumbnails).

Out of scope (this plan)
- React Native client (Explo) repository tests.
- Browser UI E2E for Netskrafl; smoke tests may be added later in separate harness.

## System Under Test Overview (condensed)

- API blueprint in `src/api.py` provides JSON endpoints for auth, gameplay, social features, chat, images, ratings, and utilities.
- Game engine handles board rules, move validation, scoring, resignation, and statistics.
- Persistence in Google Cloud NDB models (`skrafldb`); tests run with local settings and explicit cleanup.
- Real-time notifications via Firebase; presence queries impact matchmaking and chat status.

## Test Objectives

- Validate API contracts: inputs, outputs, status codes, and error semantics.
- Verify authorization barriers and cross-user protections.
- Assert game rules and scoring correctness with targeted unit tests.
- Validate time-based flows (overdue games, wait flows, Elo histories) deterministically.
- Ensure data integrity for create/update/delete operations and list consistency.
- Guard non-functional constraints: caching headers, size limits, normalization, and locale behaviors.

## Test Types and Approach

1) Unit tests (engine/data)
- Board and rack mechanics: placement legality, adjacency/connectivity, center opening move, overlap consistency.
- Scoring: letter/word multipliers, bingo bonuses, endgame tile penalties, reuse of premiums.
- DAWG/dictionary: membership checks, locale-specific acceptance, fallback behaviors using a small injected dictionary.
- Utility functions: timestamp formatting, locale normalization, rating calculations.

2) API contract tests (Flask)
- Positive and negative paths per endpoint; input validation and boundary conditions.
- Authorization matrix: anonymous vs authenticated, cross-user actions, spectator constraints.
- Idempotency where applicable; proper error codes and payloads.

3) Integration tests (lifecycles)
- Challenge → initgame → submitmove(s) → resignation → gamestate → gamestats.
- Timed challenge flows: initwait, waitcheck, cancelwait with presence stubs.
- Zombie management: gamestate with `delete_zombie`, `clear_zombie` and list updates.
- Ratings evolution: per-locale Elo updates across sequences of games.

4) Non-functional and robustness tests
- Caching/ETag for thumbnails; lifetime adherence; 304 responses.
- Size limits (image URL length, image payload sanity), invalid MIME handling.
- Security hygiene: blocked-user effects across chat/challenge/favorite; attempts to access or modify other users’ data.

## Environment and Tooling

- Python 3.11; pytest; mypy for type checks; pytest-cov for coverage.
- Test settings via environment variables as in `test/utils.py` (local project id, dev creds, Redis host/port, server software).
- Stubs/mocks
  - Firebase: stub `create_custom_token`, `send_message`, `push_to_user`, `check_presence`, `online_status` to in-memory collectors; assert call shapes without network.
  - Billing (if required in some endpoints): stub paid/friend checks.
  - Time: use `freezegun` to freeze `datetime.now(UTC)` where needed.
- Randomness: seed RNG for engine and any tests relying on randomness.
- Data isolation: fixtures delete/recreate user, game, chat, elo, stats entities per test or module, with finalizers.

## Datastore Testing Strategy (NDB)

Recommendation
- Use the Google Cloud Datastore Emulator for all automated tests.
- Isolate data with unique namespaces per test or per pytest worker.
- Never write automated tests against a shared dev or prod project; reserve a staging project/namespace for occasional smoke checks only.

Why
- Safety: no pollution of real data, no IAM/quota surprises.
- Speed and determinism: local, network-free, fully controllable lifecycle.
- Isolation: namespaces allow clean state without broad deletes and enable parallelism.

Namespace strategy
- Per-test namespace gives strongest isolation; per-worker namespace balances speed and isolation for xdist.
- Generate a short random suffix, e.g. `test-${worker}-${uuid8}`.

Pytest fixtures (examples)
```python
# Option A: using google-cloud-ndb directly
import os, uuid, pytest
from google.cloud import ndb

@pytest.fixture(scope="function")
def ndb_context():
    ns = f"test-{os.getenv('PYTEST_XDIST_WORKER','gw0')}-{uuid.uuid4().hex[:8]}"
    project = os.getenv("DATASTORE_PROJECT_ID") or os.getenv("PROJECT_ID", "explo-dev")
    client = ndb.Client(project=project, namespace=ns)
    with client.context():
        yield

# Option B: through skrafldb wrapper if available
from skrafldb import Client as DSClient

@pytest.fixture(scope="function")
def ds_context():
    ns = f"test-{os.getenv('PYTEST_XDIST_WORKER','gw0')}-{uuid.uuid4().hex[:8]}"
    with DSClient.get_context(namespace=ns):
        yield
```

Cleanup and caches
- Prefer throwaway namespaces over bulk entity deletion.
- Keep targeted model cleanup helpers (e.g., `delete_for_user`) when assertions need it.
- Isolate or disable caches:
  - Memcache/Redis: namespace keys with the same test namespace or point to a local ephemeral instance.
  - In-process caches (e.g., user/profile caches): add and call `clear()` in a fixture.

CI and local setup
- Start emulator per CI job (ephemeral, in-memory):
  - `gcloud beta emulators datastore start --no-store-on-disk --host-port=127.0.0.1:0 &`
  - `eval "$(gcloud beta emulators datastore env-init)"`
- Or run via Docker using the Cloud SDK image.
- Environment for tests:
  - Set `DATASTORE_EMULATOR_HOST`, `DATASTORE_PROJECT_ID` (or `PROJECT_ID`).
  - Unset/ignore real credentials; the emulator does not require auth.
- Parallel runs: include `PYTEST_XDIST_WORKER` in the namespace string to avoid collisions.

Indexes and consistency
- The emulator is generally strongly consistent and tolerant of missing composite indexes; production enforces indexes and may be eventually consistent for some queries.
- Keep `index.yaml` updated in the repo and validated in deploy pipeline.
- Add a minimal staging smoke test suite (non-blocking) to catch index/IAM issues pre-prod.

When to use a separate namespace without emulator
- Only for manual exploratory tests in a dedicated staging project. Not recommended for automated CI due to speed, flakiness, and risk of data drift.

Action items
- Add per-test/per-worker namespace fixture, thread it through `Client.get_context()`.
- Ensure caches are isolated/cleared between tests.
- Update CI to start the emulator and export env vars before running pytest.
- Optionally wire a tiny staging smoke job for index/IAM validation.

## Organization and Conventions

- Keep shared fixtures/utilities in `test/utils.py` (CustomClient, login helpers, env setup, user creation, cookie/session decoding, firebase stubs).
- One test module per feature cluster (e.g., `test_auth.py`, `test_gameplay.py`, `test_bestmoves.py`, `test_wordcheck.py`, `test_thumbnails.py`, `test_waitflows.py`).
- Use descriptive test names; prefer table-driven parametrization for endpoint matrices and boundary conditions.
- Mark slow tests with `@pytest.mark.slow` and exclude from default CI; run nightly.

## Coverage Targets and Quality Gates

- Overall coverage initial target 70% with a focus on:
  - 85%+ for engine modules (`skrafl*`, `dawg*`, `languages`).
  - 80%+ for `src/api.py` control-flow branches, especially error paths.
- Enforce thresholds in CI; report top uncovered files and functions.
- Type checking: mypy pass for changed files; no introduction of untyped public functions.

## Endpoint Coverage Plan (initial inventory)

Covered today (representative):
- Auth/login/logout: `/oauth2callback`, `/oauth_anon`, `/logout`, `/firebase_token`.
- Profiles/prefs: `/userstats`, `/setuserpref`.
- Social: `/blockuser`, `/reportuser`, `/favorite`, `/challenge` (issue), listing endpoints (`/challengelist`).
- Chat: `/chatmsg`, `/chatload`, `/chathistory`.
- Images: `/image` (blob/URL), profile image retrieval.
- Games: `/initgame`, `/submitmove`, `/gamestate`, `/delete_account`, Elo history and `/rating_locale` basics.

High-priority gaps to add:
- Validation and safety: `/wordcheck`, `/bestmoves` (count limits, paywall semantics), `/image` cross-user POST 403, `/thumbnail` (ETag/lifetime/304), `/gamestats` (finished-only), `/clear_zombie`, `/forceresign` (mcount, overdue rules), `/gamelist`, `/recentlist`, `/allgamelists`, `/userlist`.
- Challenge lifecycle: `/challenge` (retract/decline/accept), timed flows: `/initwait`, `/waitcheck`, `/cancelwait`.
- Ratings: `/rating` (non-locale table variants), manual/human kinds.
- OAuth alternates: `/oauth_fb`, `/oauth_apple`, `/oauth_explo` (mocked success/failure paths).
- `/submitword`, `/rchook`, `/cancelplan`, `/loaduserprefs`, `/saveuserprefs`, `/inituser` (where applicable and stable).

## Representative Test Design (examples)

- Authorization matrix (parameterized)
  - For each endpoint and method, assert 401/403 when anonymous or cross-user access is attempted; assert 200 and correct payload when properly authenticated.
- `submitmove` error semantics
  - Wrong `mcount` → `Error.OUT_OF_SYNC`; unknown `uuid` → `Error.GAME_NOT_FOUND`; invalid move shapes → rejection without side effects.
- `bestmoves`
  - Enforce `DEFAULT_BEST_MOVES` and `MAX_BEST_MOVES`; paywall behavior: deny for unpaid web users (not local), allow for mobile; validate descending scores and move legality on a fixed snapshot.
- `wordcheck`
  - Too many/too long words → `ok=False`; per-locale checks return expected validity; mix-case normalization behavior (if applicable).
- Thumbnails
  - Posting image blob creates thumbnail; GET `/thumbnail?uid=...` sets cache headers; subsequent request with `If-None-Match` returns 304; lifetime equals configured value for foreign uid and 0 for current user.
- Timed flows
  - With frozen time, `initwait` produces a waiting state and Firebase message; `waitcheck` reports waiting; `cancelwait` clears it; `forceresign` succeeds only when overdue and opponent calls it with matching `mcount`.
- Block effects
  - Blocked user cannot chat/challenge/favorite; history filters exclude blocked users; list reflect updates.
- Gamestats
  - Only for finished games; invariants on totals and resignation handling; deny for in-progress.

## Engine Unit Tests (focused)

- Placement legality and adjacency rules; center opening; islands detection; overlay mismatch rejected.
- Scoring correctness on canonical scenarios; multi-word cross scoring and premium squares; bingo bonus and endgame penalties.
- DAWG membership with injected tiny dictionary; locale-specific acceptance; fallback mechanics.
- Best move ordering on a seeded board+rack; returns consistent top choice and non-increasing scores.

## Test Data and Fixtures

- Users: `create_user(idx, locale)` helper; fixtures for `u1`, `u2`, `u3_gb` with teardown that wipes chats, zombies, elo, stats, favorites, challenges, and games.
- Clients: `CustomClient` with optional Authorization header injection; `client1`, `client2` for two-user interactions.
- Firebase stub: in-memory collector with assertions on messages and presence checks; no network.
- Time: `freezegun` fixture to freeze time per test; helpers to advance time.
- Images: minimal valid JPEG and small PNG payloads as hex to test blob and URL modes.
- RNG: global seed fixture to ensure repeatability.

## Phased Delivery Plan

Phase 1 — API contract gaps and auth hardening (fast wins)
- Add tests for `/wordcheck`, `/thumbnail`, `/favorite` delete, `/challenge` retract/decline/accept, `/gamelist`/`/recentlist`/`/allgamelists`, `/rating` (non-locale), `/gamestats`, `/clear_zombie`.
- Add authorization matrix tests across selected endpoints; cross-user POST `/image` 403.
- Introduce firebase stub, time freezer, deterministic seeding; unify fixtures.

Phase 2 — Engine rigor and bestmoves
- Unit tests for scoring and validation; DAWG tiny-dict injection; bestmoves snapshot tests and result invariants.
- Extend Elo tests: K-factor for beginners vs established; per-locale isolation; manual/human vs all.

Phase 3 — Timed flows and overdue resign
- Tests for `initwait`/`waitcheck`/`cancelwait`; `forceresign` success and failure cases with frozen time and controlled `mcount`.

Phase 4 — Web routes, robustness, and security edges
- Locale template fallback tests for selected web routes.
- Block effects across features; payload limits and invalid MIME handling; caching and header correctness.

## CI Integration and Execution Model

- Pytest with `-q` and coverage: `pytest --cov=src --cov=skrafl* --cov-report=term-missing`.
- Gates: fail build if coverage drops below thresholds for changed files and core modules.
- Mypy in CI for `src/` and changed files; forbid new untyped defs.
- Split jobs: fast tests on PR; slow marker suite nightly/weekly; artifact coverage report.

## Risks and Mitigations

- Heavy DAWG resources: use tiny dictionaries for engine tests; keep DAWG generation out of unit tests.
- Flaky time-dependent tests: require time freezing; avoid sleeps.
- External services: require mocks; tests must not rely on network or external credentials beyond local dev settings already used in tests.

## Release Readiness Checklist (tests)

- All PR checks green (pytest, coverage, mypy) with thresholds met.
- API matrix green for critical endpoints; negative/authorization tests pass.
- Engine unit suite green across scoring/validation core scenarios.
- Timed/overdue flows verified where changes touch gameplay timing.
- Manual smoke run on dev instance for critical scenarios (optional but recommended).

## Future Enhancements

- Add contract tests for additional blueprints (`web`, `stats`, `firebase`) where stable and useful.
- Incorporate property-based tests for move generation correctness and rack/bag invariants (e.g., Hypothesis) once stable.
- Lightweight browser-based smoke tests for Netskrafl web routes using Playwright in CI (separate job, non-blocking initially).

---

This strategy is intended to evolve with the codebase. As new endpoints or behaviors are introduced, extend the inventory and adjust coverage priorities accordingly. Keep tests fast, focused, and reliable to maintain trust in the release pipeline.
