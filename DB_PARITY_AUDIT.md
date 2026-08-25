# NDB ↔ PostgreSQL backend parity audit

Audit of behavioral parity between the two DB backends:
- NDB logic: `src/skrafldb_ndb.py` (model classmethods), wrapped by `src/db/ndb/repositories.py`
- PG logic: `src/db/postgresql/repositories.py`
- Contracts: `src/db/protocols.py`

NDB is the production reference for Netskrafl, so unless noted, "PG is wrong" means PG
should be changed to match NDB. ✅ = I verified the finding by reading both sides.

## Status: ALL items below are now FIXED (verified on both backends)
- `ChallengeRepository.list_issued` / `list_received` — NDB now newest-first (was oldest-first + 20 cap).
- `ReportRepository.report_user` — PG now rejects nonexistent reported user (returned True before).
- All "Confirmed correctness bugs" (#1–#8) fixed in PG.
- All "Needs a product decision" items resolved (NDB-as-reference, except where NDB was the
  buggy side — see notes below).
- Leaderboard dedup fixed in PG via DISTINCT ON (latest snapshot per user).
- Regression + compare tests added in `tests/db/test_backend_parity.py`.

### Decision-item resolutions
- `last_for_user(days)` → PG now matches NDB: newest `days` ROWS, robot_level==0 only.
- `RatingRepository.list_rating` userid → PG now encodes `"robot-N"`/`""` like NDB (consumer keys
  on this; `robot_level` field is unused by callers so left as-is). Also capped at 100.
- `FavoriteRepository.add_relation` → idempotency guard added at the real call site
  `User.add_favorite` (skrafluser.py), NOT the repository wrapper. The production path is
  `api /favorite → User.add_favorite → FavoriteModel.add_relation` (the NDB repository wrapper
  is only reached via the PG facade), and `add_favorite` already loads the favorites set, so the
  guard there fixes both backends with no extra read. Tested in `test/test_favorite.py`.
- `ReportRepository.list_reported_by` → NDB now de-dups (NDB was the buggy side; PG already did).
- `UserRepository.list_prefix` → PG now nick-block-then-name-block, deduped (matches NDB).
- `RobotRepository.get_elo`/`upsert_elo` → PG now validates empty locale / negative level.

## Confirmed correctness bugs (PG is wrong; clear fix)

| # | Method | Sev | Bug | Fix |
|---|--------|-----|-----|-----|
| 1 | ✅ `GameRepository.list_finished_games`, `iter_live_games`, `ZombieRepository.list_games` | HIGH | PG returns `sc0=score0, sc1=score1` unconditionally; NDB swaps so `sc0`=querying user's score when they are player1. `opp`/`elo_adj` ARE oriented in PG → internally inconsistent. Wrong scores shown for half of all games. | Swap `sc0`/`sc1` in the player1 branch (PG repos ~371-382, 416-422, 1101-1102). |
| 2 | ✅ `iter_live_games`, `ZombieRepository.list_games` | HIGH | PG `ts=game.timestamp` (creation); NDB `ts=ts_last_move or timestamp`. Consumer sorts by `ts` → live/zombie lists ordered by creation vs last-move time. | PG `ts=game.ts_last_move or game.timestamp`. |
| 3 | ✅ `StatsRepository.newest_before` | HIGH | PG `timestamp < ts` vs NDB `timestamp <= ts`. Off-by-boundary at exact timestamps; feeds leaderboard false-positive correction. | PG `<` → `<=`. |
| 4 | ✅ `StatsRepository.newest_before` / `create` | HIGH | PG `create()` does `add()+flush()`, so `newest_before` PERSISTS an empty Stats row on every not-found. NDB returns an in-memory default. Pollutes stats table. | `newest_before` should build an in-memory `Stats(...)` default without add/flush. |
| 5 | `UserRepository.list_similar_elo` | MED | NDB filters to users with `highest_score > 0` (played ≥1 game); PG has no such filter → includes never-played users in "similar Elo" lists. | Add `highest_score > 0` to both PG subqueries. |
| 6 | `ChatRepository.chat_history` | HIGH | PG truncates `last_msg` to 100 chars AND lacks NDB's read-marker/empty-message handling → blank conversation entries + wrong `unread` flags. | Port NDB read-marker algorithm; reconcile truncation. |
| 7 | `RatingRepository.list_rating` | MED | NDB caps at 100; PG unbounded. | Add `.limit(100)` to PG. |
| 8 | `GameRepository.list_finished_games` / `iter_live_games` / zombie | LOW-MED | PG `locale=game.locale` can be None; NDB falls back `locale or prefs['locale'] or DEFAULT_LOCALE`. | PG apply same fallback. |

## Needs a product decision (semantics genuinely differ — which is canonical?)

| Method | NDB | PG |
|--------|-----|-----|
| `StatsRepository.last_for_user(days)` | newest `days` **rows** (count) | rows within last `days` **days** (time window) |
| `RatingRepository.list_rating` userid | `"robot-N"` / `""` for robots | raw `user_id` (None for robots) |
| `FavoriteRepository.add_relation` | NDB can create **duplicate** favorite rows (no guard) | idempotent (composite PK + guard) |
| `ReportRepository.list_reported_by` | no dedup (reporter repeated) | `.distinct()` |
| `UserRepository.list_prefix` | nick-prefix block first, then name-prefix, deduped, then cap | single query ordered by `nick_lc` only |
| `RobotRepository.upsert_elo`/`get_elo` | rejects empty locale / `level<0` | no validation |

## Needs verification (potentially HIGH — leaderboard)
- `StatsRepository._list_by_elo` (list_elo/list_human_elo/list_manual_elo): NDB dedupes to the
  newest stats row **per user** (2-pass, with false-positive re-check + possible truncation);
  PG does a plain `ORDER BY elo DESC LIMIT` with **no per-user dedup**. If the stats table holds
  multiple snapshots per user (it does — that's why `newest_before` exists), PG may return
  **duplicate users** and rank by raw rows, esp. for historical `timestamp` queries. Tie-break
  also differs (NDB stable secondary order vs PG DB-defined).

## Low / edge
- `count_live_games`: NDB double-counts a self-game (player0==player1); PG counts once.
- `get_by_nickname`: divergence only when `nick_lc` is NULL/inconsistent with `nickname`.
- `delete_relation` malformed `key`: NDB catches ValueError → (False,None); PG raises (UUID parse).
- `PromoRepository.list_promotions`: NDB unordered vs PG ordered (current caller sorts anyway).

## Root cause / process
The existing `tests/db/` parity tests didn't catch these because they never seed the divergent
conditions: a user as **player1**, **multiple stats snapshots** per user, **long** chat messages,
read markers, or >cap result sets. Strengthening these (and/or the `--compare` mode) is the
durable fix so parity regressions are caught automatically.
