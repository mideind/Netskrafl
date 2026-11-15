-- Independent check of a rating table against the statistics snapshots
-- (PostgreSQL). Read-only; takes well under a second per table on the
-- production-size database, since it is driven by the indexes on the Elo
-- columns and on (user_id, robot_level, timestamp).
--
-- The nightly ratings job reports on its own tables in the log (see
-- doc/logging.md, "ratings_table"). This query is the check from outside:
--
--   A. Exact: is every row of the table the player's newest snapshot?
--   B. Complete: is anyone whose newest Elo is above the table's cutoff
--      missing from it?
--
-- B also counts the players who have EVER had a snapshot at or above the
-- cutoff but are below it now. Those are the "false positives" that the
-- former computation, a descending scan of all snapshots, had to discard,
-- and that could leave a table short.
--
-- Usage, once per kind (the Elo column and the cutoff belong to the kind;
-- the cutoff is the lowest Elo in the table, which the first query prints):
--
--   psql "$DATABASE_URL" -X -At -v kind=all    -v col=elo        -f utils/ratings-check.sql
--   psql "$DATABASE_URL" -X -At -v kind=human  -v col=human_elo  -f utils/ratings-check.sql
--   psql "$DATABASE_URL" -X -At -v kind=manual -v col=manual_elo -f utils/ratings-check.sql
--
-- Expected: "differing 0" in A and "MISSING from the table 0" in B. The
-- 'all' table also holds robots, which A and B leave out; players exactly
-- at the cutoff may be in the table or not (ties). A user who has no snapshot
-- at all (as in a test database) counts as differing in A.

set default_transaction_read_only = on;
set statement_timeout = '60s';

select min(elo) as cutoff from ratings where kind = :'kind' and games >= 0 \gset

select :'kind' || ' table: ' || count(*) filter (where games >= 0) || ' rows of ' || count(*)
       || ', robots ' || count(*) filter (where games >= 0 and user_id is null)
       || ', cutoff Elo ' || :cutoff
  from ratings where kind = :'kind';

-- A. Exactness
select :'kind' || ' A: user rows ' || count(*)
       || ', equal to the newest snapshot ' || count(*) filter (where n.elo = t.elo)
       || ', differing ' || count(*) filter (where n.elo is distinct from t.elo)
  from ratings t
  left join lateral (
      select s.:col as elo from stats s
       where s.user_id = t.user_id and s.robot_level = 0
       order by s.timestamp desc limit 1) n on true
 where t.kind = :'kind' and t.user_id is not null and t.games >= 0;

-- B. Completeness
with cand as materialized (
    select user_id, count(*) as snapshots from stats
     where :col >= :cutoff and user_id is not null group by user_id
)
select :'kind' || ' B: snapshots at or above the cutoff ' || coalesce(sum(c.snapshots), 0)
       || ', users ever there ' || count(*)
       || ', now below the cutoff ' || count(*) filter (where n.elo < :cutoff)
       || ', now above and in the table ' || count(*) filter (where n.elo > :cutoff and t.user_id is not null)
       || ', now above and MISSING from the table ' || count(*) filter (where n.elo > :cutoff and t.user_id is null)
       || ', exactly at the cutoff ' || count(*) filter (where n.elo = :cutoff)
  from cand c
  cross join lateral (
      select s.:col as elo from stats s
       where s.user_id = c.user_id and s.robot_level = 0
       order by s.timestamp desc limit 1) n
  left join ratings t on t.kind = :'kind' and t.user_id = c.user_id;
