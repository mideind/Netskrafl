# Elo ratings

How ratings are computed and stored, how the two products differ, and two
changes that have been designed but not made.

## Three ratings

Each player has three Elo ratings (`EloDict`):

- `elo`: all games, against humans and robots;
- `human_elo`: games between humans only;
- `manual_elo`: games between humans in the manual word-check ("pro") mode.

The adjustment after a game is the usual Elo formula (`compute_elo()` in
`src/skraflelo.py`), with a larger K for beginners (32) than for established
players (20), and never below zero.

## Two stores

When a game ends (`src/skraflgame.py`), two computations run:

1. **Ratings kept with the user** ("old style": `compute_elo_for_game()`),
   for games between two humans. One set of ratings per user, with no
   notion of locale. These are provisional: the nightly statistics job
   (`/stats/run`) goes through the previous day's finished games,
   recalculates the ratings in order, and writes them back to the users and
   into one statistics snapshot per player and day.
2. **Ratings per user and locale** ("new style":
   `compute_locale_elo_for_game()`), for every game, robots included: one
   row per user and locale in the Elo table (`EloModel`), and one per robot
   level and locale (`RobotModel`). These are final when written.

Which of them a player sees depends on the product
(`User.elo_for_locale()`):

| | Netskrafl | Explo |
|---|---|---|
| Rating shown | The one kept with the user | The one for the game's locale; a user without one starts from the rating kept with the user, if the locale is the user's own |
| Rating lists | The old-style tables of the top players (all games, human games, manual games), with their standing a day, a week and a month ago: built by the nightly `/stats/ratings` job from the statistics snapshots, served by `/rating` | Per locale, read live from the Elo table by `/rating_locale` |
| Nightly jobs | `/stats/run` and `/stats/ratings` | `/stats/run` only (`/stats/ratings` does nothing there) |

`/stats/run` is needed in both: the statistics snapshots also feed the
profile page (games, wins, scores) and the 30-day Elo history chart.

## Designed, not done

**1. Netskrafl on the per-locale model.** Netskrafl would read its ratings
from the Elo table like Explo (every Netskrafl game is in the one locale),
which removes the `NETSKRAFL` branches in `User.elo_for_locale()` and
`locale_elos()`. It needs a one-time copy of each user's ratings into the
Elo table (`utils/migrate_netskrafl_elo.py`, checked with
`utils/verify_elo_migration.py`), and rating lists that read from there.

**2. No nightly recalculation (PostgreSQL).** The statistics job rebuilds
cumulative snapshots for every player who played the day before. The design
replaces it with:

- cumulative game statistics kept in the Elo row and incremented in SQL when
  a game ends (`games = games + 1`, not read-modify-write);
- a table of daily Elo snapshots (user, locale, date), written for both
  players when a game ends and completed for everyone else by one
  `INSERT ... SELECT ... ON CONFLICT` a day, serving the 30-day chart and
  the "a day, a week, a month ago" columns of the rating lists;
- rating lists read from the Elo table (current) and the snapshots
  (historical);
- a transition with a backfill from the existing snapshots, a period of
  writing both, a comparison, and then switching the readers.

Redis sorted sets were considered for the lists and rejected: an index on
locale and Elo answers "top 100" at once, and a second source of truth
would only add ways to disagree.

The pressure behind the second design is lower than when it was written:
on PostgreSQL the nightly statistics job takes well under a minute. It
remains the cleaner model.
