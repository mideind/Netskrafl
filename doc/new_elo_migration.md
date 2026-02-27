# Plan: Eliminate Batch Elo Processing, Move to Real-Time Model

## Context

The nightly `/stats/run` cron job (03:00 UTC) is the main pain point. It iterates
ALL finished games from the previous day, rebuilding cumulative StatsModel snapshots
for every player from scratch. On NDB this is expensive: hundreds of `newest_before()`
queries, 250-game chunks, and batched writes of both StatsModel and UserModel. The
companion `/stats/ratings` cron (03:45 UTC) then queries StatsModel at 4 timestamps
x 3 kinds = 12 queries (with false-positive correction) to build top-100 leaderboards
in RatingModel.

**Goal:** Eliminate the expensive StatsModel batch job entirely. Move to a pure
real-time model where Elo ratings AND cumulative game stats are updated after each
game. Keep only a very lightweight daily cron for historical leaderboard snapshots.

**Scope:** PostgreSQL only. NDB continues using the existing batch jobs until the
full PostgreSQL migration is complete. Historical leaderboard comparisons
(yesterday/week/month) are preserved.

## Current StatsModel Consumers (what we must replace)

1. **`_create_ratings()`** (`skraflstats.py:330-481`) - builds RatingModel (top 100
   with historical rank/elo/games comparisons at yesterday/week/month)
2. **`User.stats()`** (`skrafluser.py:1528-1572`) - 30-day Elo history chart for
   user profiles, via `StatsModel.last_for_user(uid, days=30)`
3. **`User.profile()`** (`skrafluser.py:~1464`) - cumulative game stats (games,
   wins, losses, scores) via `StatsModel.newest_for_user(uid)`

## Architecture: Three Changes

### A. Extend EloRating with Cumulative Game Stats

Currently the PostgreSQL `elo_ratings` table (`EloRating` model at
`src/db/postgresql/models.py:136`) stores only `elo, human_elo, manual_elo`. Add 15
cumulative stats fields (games, wins, losses, scores - mirroring what StatsModel
tracks). Update them incrementally in `compute_locale_elo_for_game()` alongside Elo.

After each game, EloRating has everything StatsModel had for current stats - no
batch recomputation needed.

**PostgreSQL optimization:** Use SQL-level increments (`games = games + 1`) rather
than read-modify-write, avoiding race conditions if two games finish simultaneously.

### B. EloSnapshot Table for Historical Data

A new `elo_snapshots` table (user_id, locale, date, elo, human_elo, manual_elo)
captures daily Elo values for two purposes:

- **30-day user profile chart** (replaces `StatsModel.last_for_user`)
- **Historical leaderboard comparisons** (yesterday/week/month rank + Elo)

Populated two ways:
- **On game completion:** upsert today's snapshot for both players (2 upserts, cheap)
- **Lightweight daily cron:** a single `INSERT INTO elo_snapshots SELECT ... FROM
  elo_ratings ON CONFLICT DO UPDATE` ensures snapshots exist for ALL users with
  EloRating entries who didn't play today. Takes milliseconds. Also captures
  cumulative stats (games, wins, score, score_against) for leaderboard display.

### C. Rewrite Leaderboard Generation

- **Current rankings:** Query `elo_ratings` directly, ordered by Elo DESC (the
  `/rating_locale` endpoint already does this via `EloModel.list_rating()`)
- **Historical comparisons:** Query `elo_snapshots` at yesterday/week/month dates,
  ordered by Elo DESC, to get historical rank + Elo for comparison
- Replaces both `/stats/run` AND the heavy `/stats/ratings`

### Redis Sorted Sets?

**Not recommended.** PostgreSQL with the existing `(locale, elo)` composite index
handles `ORDER BY elo DESC LIMIT 100` in sub-millisecond time. The existing Redis
cache (5-min TTL for locale leaderboards, 1-hour for global) is already the right
approach. Adding Redis sorted sets would create a second source of truth with
divergence risk and initialization-on-restart complexity, for negligible latency gain.

## Files to Modify

### Phase 1: Extend EloRating with cumulative stats (PostgreSQL)

| File | Change |
|------|--------|
| `src/db/postgresql/models.py:136-171` | Add 15 stats columns to `EloRating` class |
| `src/db/protocols.py:584-603` | Extend `EloEntityProtocol` with stats properties |
| `src/db/protocols.py:40-45` | Create `GameStatsUpdate` dataclass |
| `src/db/postgresql/repositories.py:468-488` | Extend `EloRepository.upsert()` with atomic SQL-level increments |
| `src/skrafldb_pg.py:673-800` | Add stats properties to PG facade `EloModel` |
| `src/skraflelo.py:196-414` | Update `compute_locale_elo_for_game()` to construct `GameStatsUpdate` and pass it to upsert |

### Phase 2: EloSnapshot table (PostgreSQL)

| File | Change |
|------|--------|
| `src/db/postgresql/models.py` | New `EloSnapshot` ORM model (user_id+locale+date PK, Elo values, games, wins, score, score_against) |
| `src/db/postgresql/repositories.py` | New `EloSnapshotRepository`: `upsert_today()`, `last_for_user(uid, locale, days)`, `snapshot_all()` |
| `src/db/protocols.py` | New `EloSnapshotRepositoryProtocol` |
| `src/skraflelo.py` | After EloModel.upsert(), call snapshot `upsert_today()` for each player |

### Phase 3: Replace StatsModel consumers (PostgreSQL path only)

| File | Change |
|------|--------|
| `src/skrafluser.py:~1464` | `User.profile()`: on PG backend, read cumulative stats from EloModel instead of StatsModel |
| `src/skrafluser.py:1528-1572` | `User.stats()`: on PG backend, read 30-day chart from EloSnapshot |
| `src/logic.py:1070-1174` | `rating()`: on PG backend, query EloModel (current) + EloSnapshot (historical) instead of RatingModel |
| `src/skraflstats.py` | New `/stats/snapshot` endpoint: call `EloSnapshotRepository.snapshot_all()` |
| `cron.yaml` | For PG deployment: remove `/stats/run`; replace `/stats/ratings` with `/stats/snapshot` |

### Phase 4: Cleanup (after validation period, future)

Remove StatsModel-related code from PostgreSQL backend. Drop `stats` table.
Remove `_run_stats()` from `skraflstats.py`. Keep NDB code unchanged until NDB
is fully retired.

## Transition Strategy

1. **Backfill EloRating stats** - One-time SQL migration populates the new stats
   columns from the most recent StatsModel entries per user:
   ```sql
   UPDATE elo_ratings er SET
       games = s.games, wins = s.wins, losses = s.losses,
       score = s.score, score_against = s.score_against, ...
   FROM (
       SELECT DISTINCT ON (user_id) user_id, games, wins, losses, score, ...
       FROM stats WHERE robot_level = 0
       ORDER BY user_id, timestamp DESC
   ) s WHERE er.user_id = s.user_id;
   ```
2. **Backfill EloSnapshot** - Populate from existing StatsModel daily entries:
   ```sql
   INSERT INTO elo_snapshots (user_id, locale, date, elo, human_elo, manual_elo, ...)
   SELECT user_id, 'is_IS', date_trunc('day', timestamp), elo, human_elo, manual_elo, ...
   FROM stats WHERE robot_level = 0
   ON CONFLICT DO NOTHING;
   ```
3. **Dual-write** (1-2 weeks) - Real-time path writes EloRating stats + EloSnapshot
   alongside existing batch job. Validation script compares daily.
4. **Switch readers** - Profile, chart, and leaderboard read from new sources
5. **Disable batch** - Remove `/stats/run` from cron.yaml for PG deployment
6. **Cleanup** - Remove StatsModel code from PG backend

## Key Design Details

### GameStatsUpdate dataclass (passed to EloModel.upsert)
```python
@dataclass
class GameStatsUpdate:
    is_robot_game: bool
    is_manual_game: bool
    player_score: int
    opponent_score: int
    player_won: bool    # True if this player won
    player_lost: bool   # True if this player lost (False for draws)
```

### EloSnapshot model
```
elo_snapshots (user_id, locale, date) PK
  elo, human_elo, manual_elo          -- for 30-day chart + historical rank
  games, wins, score, score_against   -- for leaderboard stats display
  Index: (locale, date, elo DESC)     -- for historical top-100 queries
```

### Lightweight cron job (replaces _run_stats + _create_ratings)
```sql
-- Single query, takes milliseconds
INSERT INTO elo_snapshots (user_id, locale, date, elo, human_elo, manual_elo,
                           games, wins, score, score_against)
SELECT user_id, locale, CURRENT_DATE, elo, human_elo, manual_elo,
       games, wins, score, score_against
FROM elo_ratings
ON CONFLICT (user_id, locale, date) DO UPDATE SET
  elo = EXCLUDED.elo, human_elo = EXCLUDED.human_elo,
  manual_elo = EXCLUDED.manual_elo, games = EXCLUDED.games,
  wins = EXCLUDED.wins, score = EXCLUDED.score,
  score_against = EXCLUDED.score_against;
```

### Historical leaderboard query
```sql
-- Get top 100 at a historical date (e.g., yesterday)
SELECT user_id, elo, games, wins, score, score_against,
       ROW_NUMBER() OVER (ORDER BY elo DESC) as rank
FROM elo_snapshots
WHERE locale = :locale AND date = :target_date
ORDER BY elo DESC LIMIT 100;
```

### rating() rewrite sketch (logic.py)
Current top-100 from `elo_ratings`, then join with `elo_snapshots` at 3 historical
dates (yesterday, 7 days ago, 30 days ago) to get historical rank/elo/games.
Result format stays the same (`UserRatingDict`). Redis cache (1-hour TTL) unchanged.

## Verification

- Existing `test/test_elo.py` verifies Elo calculation correctness
- New tests: `upsert_with_stats()` atomic increment correctness (wins, losses, draws,
  robot vs human, manual vs normal)
- Integration test: play several games via API, verify EloRating cumulative stats
  match expected totals
- Regression test: 30-day chart from EloSnapshot matches chart from StatsModel for
  the same user and period
- Regression test: leaderboard from EloModel+EloSnapshot produces same rankings as
  the current RatingModel-based leaderboard
- Validation script during dual-write period: compare EloRating.games/wins/elo vs
  StatsModel for all active users
