"""

    Server module for Netskrafl statistics and other background tasks

    Copyright © 2025 Miðeind ehf.
    Author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This module implements three endpoints, /stats/run, /stats/ratings
    and /stats/ratings_backfill. The first one is normally called by the
    Google Cloud Scheduler at 02:00 UTC each night, and the second one
    at 02:20 UTC. The endpoints cannot be invoked manually via HTTP
    except when running on a local development server.

    /stats/run looks at the games played during the preceding day (UTC time)
    and calculates Elo scores and high scores for each game and player.

    /stats/ratings creates the top 100 Elo scoreboard, for human-only
    games and for all games (including human-vs-robot). The tables are
    computed from current canonical Elo data and then archived by date
    (in RatingArchiveModel entities), so that historical comparisons
    (yesterday/week/month ago) are simple keyed lookups instead of
    expensive recomputations over the entire StatsModel history.

    /stats/ratings_backfill fills in missing archived tables for past
    dates, one date per invocation, chaining itself via a Cloud Tasks
    task until done. Kick it off after deployment with:

        gcloud tasks create-app-engine-task --project <project> \\
            --queue default --location <region> --method GET \\
            --relative-uri /stats/ratings_backfill

"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple, Any, cast

import calendar
import json
import logging
import os
import time
import gc

from datetime import UTC, date, datetime, timedelta
from threading import Thread

from flask import request, Blueprint
from flask.wrappers import Request

from config import running_local, ResponseType, DEFAULT_ELO, PROJECT_ID
from cache import memcache
from skrafldb import (
    Context,
    ndb,
    Client,
    UserModel,
    GameModel,
    StatsModel,
    RatingModel,
    RatingArchiveModel,
    CompletionModel,
    iter_q,
    put_multi,
    StatsDict,
    StatsResults,
)
from skraflgame import Game
from skraflelo import ESTABLISHED_MARK, compute_elo
from autoplayers import AUTOPLAYERS

# Register the Flask blueprint for the stats routes
stats = stats_blueprint = Blueprint("stats", __name__, url_prefix="/stats")

# The kinds of rating tables that we maintain
RATING_KINDS = ("all", "human", "manual")

# The length of the rating tables
MAX_RATINGS = 100

# Number of extra users fetched beyond the table length when computing
# a current table, to absorb minor ordering drift between the current
# UserModel Elo values and the newest StatsModel snapshots
RATINGS_OVERSAMPLE = 50

# How many days further back we search for an archived rating table
# if the target date is missing (e.g. because the ratings task
# did not run on that date)
ARCHIVE_MAX_LOOKBACK = 4

# The default and maximum number of past days that the ratings
# backfill process looks at; must comfortably cover the month-ago
# lookback of the ratings task
BACKFILL_DEFAULT_DAYS = 36
BACKFILL_MAX_DAYS = 366

# The robot levels that can appear in the 'all' rating table
ROBOT_LEVELS: List[int] = sorted({apt.level for apl in AUTOPLAYERS.values() for apt in apl})

# The Cloud Tasks queue used for backfill continuation tasks.
# Every App Engine application has a "default" push queue.
CLOUD_TASKS_QUEUE = "default"
CLOUD_TASKS_LOCATION = os.environ.get("CLOUD_TASKS_LOCATION") or (
    "us-central1" if PROJECT_ID == "netskrafl" else "europe-west1"
)


def monthdelta(date: datetime, delta: int) -> datetime:
    """Calculate a date x months from now, in the past or in the future"""
    m, y = (date.month + delta) % 12, date.year + (date.month + delta - 1) // 12
    if not m:
        m = 12
    d = min(date.day, calendar.monthrange(y, m)[1])
    return date.replace(day=d, month=m, year=y)


def _write_stats(timestamp: datetime, urecs: Dict[str, StatsModel]) -> None:
    """Writes the freshly calculated statistics records to the database"""
    # Delete all previous stats with the same timestamp, if any
    StatsModel.delete_ts(timestamp=timestamp)
    um_list: List[UserModel] = []
    sm_list: List[StatsModel] = []
    # Note: we need a limit on the put_multi() size
    # since user entites can be quite large (due to the embedded images)
    # and the maximum size of a single RPC call is 10 MB
    MAX_STATS_PUT = 200
    MAX_USERS_PUT = 50
    for sm in urecs.values():
        # Set the reference timestamp for the entire stats series
        sm.timestamp = timestamp
        # Fetch user information to update Elo statistics
        um = sm.fetch_user()
        if um:
            # Not robot
            um.elo = sm.elo
            um.human_elo = sm.human_elo
            um.manual_elo = sm.manual_elo
            # Make sure that the human game counts agree
            um.games = sm.human_games
            um_list.append(um)
            if len(um_list) >= MAX_USERS_PUT:
                # At limit: Update the entities that we've gathered so far
                put_multi(um_list)
                um_list = []
        # Collect the updated StatsModel entities
        sm_list.append(sm)
        if len(sm_list) >= MAX_STATS_PUT:
            # At limit: Update the entities that we've gathered so far
            put_multi(sm_list)
            sm_list = []
    # Update the remaining StatsModel entities
    if sm_list:
        put_multi(sm_list)
    # Update the remaining UserModel entities
    if um_list:
        put_multi(um_list)


def _run_stats(from_time: datetime, to_time: datetime) -> bool:
    """Runs a process to update user statistics and Elo ratings"""
    logging.info("Generating stats from {0} to {1}".format(from_time, to_time))

    if from_time >= to_time:
        # Null time range
        return False

    # Collect any stray garbage before we start
    gc.collect()

    # Clear previous cache contents, if any
    StatsModel.clear_cache()

    # Iterate over all finished games within the time span in temporal order
    # pylint: disable=singleton-comparison
    q = (
        GameModel.query(
            ndb.AND(
                cast(datetime, GameModel.ts_last_move) > from_time,
                cast(datetime, GameModel.ts_last_move) <= to_time,
            )
        )
        .order(GameModel.ts_last_move)
        .filter(GameModel.over == True)  # noqa: E712
    )

    # The accumulated cache of user statistics
    users: Dict[str, StatsModel] = dict()

    def init_stat(user_id: Optional[str], robot_level: int) -> StatsModel:
        """Returns the newest StatsModel instance available for the given user"""
        return StatsModel.newest_before(from_time, user_id, robot_level)

    cnt = 0
    p0: Optional[str]
    p1: Optional[str]

    try:
        # Use i as a progress counter
        i = 0
        for gm in iter_q(q, chunk_size=250):
            i += 1

            s0 = gm.score0
            s1 = gm.score1

            if (s0 == 0) and (s1 == 0):
                # When a game ends by resigning immediately,
                # make sure that the weaker player
                # doesn't get Elo points for a draw; in fact,
                # ignore such a game altogether in the statistics
                continue

            # lm = Alphabet.format_timestamp(gm.ts_last_move or gm.timestamp)
            p0 = None if gm.player0 is None else gm.player0.id()
            p1 = None if gm.player1 is None else gm.player1.id()
            robot_game = (p0 is None) or (p1 is None)
            manual_game = False
            if robot_game:
                rl = gm.robot_level
            else:
                rl = 0
                manual_game = Game.manual_wordcheck_from_prefs(gm.prefs)

            if p0 is None:
                k0 = "robot-" + str(rl)
            else:
                k0 = p0
            if p1 is None:
                k1 = "robot-" + str(rl)
            else:
                k1 = p1

            if k0 in users:
                urec0 = users[k0]
            else:
                users[k0] = urec0 = init_stat(p0, rl if p0 is None else 0)
            if k1 in users:
                urec1 = users[k1]
            else:
                users[k1] = urec1 = init_stat(p1, rl if p1 is None else 0)

            # Number of games played
            urec0.games += 1
            urec1.games += 1
            if not robot_game:
                urec0.human_games += 1
                urec1.human_games += 1
                if manual_game:
                    urec0.manual_games += 1
                    urec1.manual_games += 1

            # Total scores
            urec0.score += s0
            urec1.score += s1
            urec0.score_against += s1
            urec1.score_against += s0
            if not robot_game:
                urec0.human_score += s0
                urec1.human_score += s1
                urec0.human_score_against += s1
                urec1.human_score_against += s0
                if manual_game:
                    urec0.manual_score += s0
                    urec1.manual_score += s1
                    urec0.manual_score_against += s1
                    urec1.manual_score_against += s0

            # Wins and losses
            if s0 > s1:
                urec0.wins += 1
                urec1.losses += 1
            elif s1 > s0:
                urec1.wins += 1
                urec0.losses += 1
            if not robot_game:
                if s0 > s1:
                    urec0.human_wins += 1
                    urec1.human_losses += 1
                elif s1 > s0:
                    urec1.human_wins += 1
                    urec0.human_losses += 1
                if manual_game:
                    if s0 > s1:
                        urec0.manual_wins += 1
                        urec1.manual_losses += 1
                    elif s1 > s0:
                        urec1.manual_wins += 1
                        urec0.manual_losses += 1

            # Find out whether players are established or beginners
            est0 = urec0.games > ESTABLISHED_MARK
            est1 = urec1.games > ESTABLISHED_MARK

            # Save the Elo point state used in the calculation
            gm.elo0, gm.elo1 = urec0.elo, urec1.elo

            # Compute the Elo points of both players
            adj = compute_elo((urec0.elo, urec1.elo), s0, s1, est0, est1)

            # When an established player is playing a beginning (provisional) player,
            # leave the Elo score of the established player unchanged
            # Adjust player 0
            if est0 and not est1:
                adj = (0, adj[1])
            gm.elo0_adj = adj[0]
            urec0.elo += adj[0]
            # Adjust player 1
            if est1 and not est0:
                adj = (adj[0], 0)
            gm.elo1_adj = adj[1]
            urec1.elo += adj[1]
            # If not a robot game, compute the human-only Elo
            if not robot_game:
                # Find out whether players are established or beginners,
                # counting human games only
                est0 = urec0.human_games > ESTABLISHED_MARK
                est1 = urec1.human_games > ESTABLISHED_MARK

                uelo0 = urec0.human_elo or DEFAULT_ELO
                uelo1 = urec1.human_elo or DEFAULT_ELO
                gm.human_elo0, gm.human_elo1 = uelo0, uelo1
                adj = compute_elo((uelo0, uelo1), s0, s1, est0, est1)
                # Adjust player 0
                if est0 and not est1:
                    adj = (0, adj[1])
                gm.human_elo0_adj = adj[0]
                urec0.human_elo = uelo0 + adj[0]
                # Adjust player 1
                if est1 and not est0:
                    adj = (adj[0], 0)
                gm.human_elo1_adj = adj[1]
                urec1.human_elo = uelo1 + adj[1]
                # If manual game, compute the manual-only Elo
                if manual_game:
                    uelo0 = urec0.manual_elo or DEFAULT_ELO
                    uelo1 = urec1.manual_elo or DEFAULT_ELO
                    gm.manual_elo0, gm.manual_elo1 = uelo0, uelo1
                    adj = compute_elo((uelo0, uelo1), s0, s1, est0, est1)
                    # Adjust player 0
                    if est0 and not est1:
                        adj = (0, adj[1])
                    gm.manual_elo0_adj = adj[0]
                    urec0.manual_elo = uelo0 + adj[0]
                    # Adjust player 1
                    if est1 and not est0:
                        adj = (adj[0], 0)
                    gm.manual_elo1_adj = adj[1]
                    urec1.manual_elo = uelo1 + adj[1]

            # Save the game object with the new Elo adjustment statistics
            gm.put()

            # Report on our progress
            cnt += 1
            if i % 500 == 0:
                logging.info("Stats processed {0} games".format(i))

    except Exception as ex:
        logging.error(
            "Exception in _run_stats(from={0}, to={1}) after {2} games and {3} users: {4!r}".format(
                from_time, to_time, cnt, len(users), ex
            )
        )
        return False

    # Completed without incident
    logging.info(
        "Normal completion of stats from {0} to {1}; {2} games and {3} users".format(
            from_time, to_time, cnt, len(users)
        )
    )
    _write_stats(to_time, users)
    return True


def _table_to_json(table: StatsResults) -> str:
    """Serialize a ratings table to JSON for archival"""
    return json.dumps([dict(d, timestamp=d["timestamp"].isoformat()) for d in table])


def _table_from_json(table_json: str) -> StatsResults:
    """Deserialize a ratings table from its archived JSON form"""
    rows: List[Dict[str, Any]] = json.loads(table_json)
    return [
        cast(StatsDict, dict(d, timestamp=datetime.fromisoformat(d["timestamp"])))
        for d in rows
    ]


def _fetch_archived_table(kind: str, target: date) -> Dict[str, StatsDict]:
    """Fetch the archived ratings table of the given kind that is closest
    to (at or before) the target date, searching up to ARCHIVE_MAX_LOOKBACK
    days back. Returns a dict keyed by user key (or robot key); empty if
    no archive is found."""
    _key = StatsModel.dict_key
    for back in range(ARCHIVE_MAX_LOOKBACK + 1):
        d = target - timedelta(days=back)
        table_json = RatingArchiveModel.fetch_json(kind, d.isoformat())
        if table_json is not None:
            return {_key(sd): sd for sd in _table_from_json(table_json)}
    return {}


def _stats_dict(
    sm: StatsModel, user_id: Optional[str], robot_level: int, kind: str
) -> StatsDict:
    """Extract the fields relevant to the given rating kind from a
    StatsModel entity into a StatsDict"""
    if kind == "human":
        games, elo = sm.human_games, sm.human_elo
        score, score_against = sm.human_score, sm.human_score_against
        wins, losses = sm.human_wins, sm.human_losses
    elif kind == "manual":
        games, elo = sm.manual_games, sm.manual_elo
        score, score_against = sm.manual_score, sm.manual_score_against
        wins, losses = sm.manual_wins, sm.manual_losses
    else:
        # Default, kind == 'all'
        games, elo = sm.games, sm.elo
        score, score_against = sm.score, sm.score_against
        wins, losses = sm.wins, sm.losses
    return StatsDict(
        user=user_id,
        robot_level=robot_level,
        timestamp=sm.timestamp,
        games=games,
        elo=elo,
        score=score,
        score_against=score_against,
        wins=wins,
        losses=losses,
        rank=0,
    )


def _current_ratings_table(
    kind: str, sticky_keys: Iterable[str], max_len: int = MAX_RATINGS
) -> StatsResults:
    """Compute the current top-Elo ratings table of the given kind.
    Candidates are the users with the highest current Elo ratings (as
    maintained canonically by the nightly stats run), the robot players
    (for the 'all' table), and any users present in the most recent
    archived table (so that entries cannot silently vanish between runs).
    The stats fields for each candidate come from the candidate's newest
    StatsModel snapshot, fetched in parallel. Since each candidate maps
    to exactly one snapshot, this is exact - no false positives can
    occur, in contrast to the previous global descending-Elo scan over
    the entire snapshot history."""
    now = datetime.now(UTC)
    key_set: Set[str] = set()
    candidates: List[Tuple[Optional[str], int]] = []

    def add_candidate(user_id: Optional[str], robot_level: int) -> None:
        k = f"robot-{robot_level}" if user_id is None else user_id
        if k not in key_set:
            key_set.add(k)
            candidates.append((user_id, robot_level))

    for uid in UserModel.list_top_elo(kind, max_len + RATINGS_OVERSAMPLE):
        add_candidate(uid, 0)
    if kind == "all":
        # The 'all' table includes robot players
        for level in ROBOT_LEVELS:
            add_candidate(None, level)
    for k in sticky_keys:
        add_candidate(*StatsModel.user_id_from_key(k))

    sms = StatsModel.newest_before_multi(now, candidates)
    table = [
        _stats_dict(sm, user_id, robot_level, kind)
        for (user_id, robot_level), sm in zip(candidates, sms)
    ]
    # Drop robot entries for levels that have no games recorded
    table = [d for d in table if d["user"] is not None or d["games"] > 0]
    # Sort in descending order by Elo, rank and truncate
    table.sort(key=lambda d: -d["elo"])
    del table[max_len:]
    for ix, d in enumerate(table):
        d["rank"] = ix + 1
    return table


def _create_ratings() -> None:
    """Create the Top 100 ratings tables"""
    logging.info("Starting _create_ratings")

    timestamp = datetime.now(UTC)
    today = timestamp.date()
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)
    month_ago = monthdelta(timestamp, -1).date()

    # Collect any stray garbage before we start
    gc.collect()

    def _augment_table(
        t: Iterable[StatsDict],
        t_yesterday: Dict[str, StatsDict],
        t_week_ago: Dict[str, StatsDict],
        t_month_ago: Dict[str, StatsDict],
    ) -> None:
        """Go through a table of top scoring users and augment it
        with data from previous time points"""

        for sm in t:
            # Augment the rating with info about progress
            key = StatsModel.dict_key(sm)

            # pylint: disable=cell-var-from-loop
            def _augment(prop: str) -> None:
                asm = cast(Any, sm)  # Type checking hack
                asm[prop + "_yesterday"] = (
                    t_yesterday[key][prop] if key in t_yesterday else 0  # type: ignore[literal-required]
                )
                asm[prop + "_week_ago"] = (
                    t_week_ago[key][prop] if key in t_week_ago else 0  # type: ignore[literal-required]
                )
                asm[prop + "_month_ago"] = (
                    t_month_ago[key][prop] if key in t_month_ago else 0  # type: ignore[literal-required]
                )

            _augment("rank")
            _augment("games")
            _augment("elo")
            _augment("wins")
            _augment("losses")
            _augment("score")
            _augment("score_against")

    t0 = time.time()
    rlist: List[RatingModel] = []

    for kind in RATING_KINDS:

        # Fetch the archived tables for the historical comparison points
        t_yesterday = _fetch_archived_table(kind, yesterday)
        t_week_ago = _fetch_archived_table(kind, week_ago)
        t_month_ago = _fetch_archived_table(kind, month_ago)

        # Compute the current table; users in the most recent archived
        # table are included as candidates ("sticky") so that they are
        # re-evaluated even if their current Elo rating has dropped
        table = _current_ratings_table(kind, t_yesterday.keys())

        # Archive today's table (before augmenting it) so that future
        # runs can use it for their historical comparisons
        RatingArchiveModel.store(kind, today.isoformat(), _table_to_json(table))

        # Augment the table with data from the historical time points
        _augment_table(table, t_yesterday, t_week_ago, t_month_ago)

        # Assemble the RatingModel rows for this kind
        for rank in range(0, MAX_RATINGS):
            rm = RatingModel.get_or_create(kind, rank + 1)
            if rank < len(table):
                rm.assign(table[rank])
            else:
                # Sentinel empty records
                rm.user = None
                rm.robot_level = -1
                rm.games = -1
            rlist.append(rm)

    logging.info("Writing top 100 tables to the database")
    # Put the entire top 100 table in one RPC call
    put_multi(rlist)

    t1 = time.time()
    logging.info("Finishing _create_ratings in {0:.1f} seconds".format(t1 - t0))


def _backfill_ratings_for_date(d: date) -> None:
    """Compute and archive the ratings tables for a past date, as they
    would have been computed by the ratings task early on that day.
    This uses the historical StatsModel snapshots via the (slow) legacy
    descending-Elo scan and is intended for one-time backfill only."""
    # Stats snapshots are stamped at (UTC) midnight, so any cutoff time
    # during day d captures exactly the set of snapshots that the
    # ratings task saw when it ran in the early hours of day d
    ts = datetime(d.year, d.month, d.day, 12, 0, tzinfo=UTC)
    listers: List[Tuple[str, Callable[[datetime, int], StatsResults]]] = [
        ("all", StatsModel.list_elo),
        ("human", StatsModel.list_human_elo),
        ("manual", StatsModel.list_manual_elo),
    ]
    for kind, lister in listers:
        if RatingArchiveModel.fetch_json(kind, d.isoformat()) is not None:
            # Already archived: skip (this makes the backfill idempotent)
            continue
        table = lister(ts, MAX_RATINGS)
        RatingArchiveModel.store(kind, d.isoformat(), _table_to_json(table))
    # The legacy scan accumulates a large in-memory cache; drop it
    StatsModel.clear_cache()


def _missing_archive_dates(days: int) -> List[date]:
    """Return the dates within the lookback window that are missing
    one or more archived rating tables, most recent date first"""
    today = datetime.now(UTC).date()
    missing: List[date] = []
    for delta in range(1, days + 1):
        d = today - timedelta(days=delta)
        if any(
            RatingArchiveModel.fetch_json(kind, d.isoformat()) is None
            for kind in RATING_KINDS
        ):
            missing.append(d)
    return missing


def _enqueue_backfill_task(days: int) -> bool:
    """Enqueue a Cloud Tasks task to continue the ratings backfill.
    Returns False if the task could not be enqueued."""
    try:
        import google.cloud.tasks_v2 as tasks_v2

        client = tasks_v2.CloudTasksClient()
        parent = client.queue_path(PROJECT_ID, CLOUD_TASKS_LOCATION, CLOUD_TASKS_QUEUE)
        task = tasks_v2.Task(
            app_engine_http_request=tasks_v2.AppEngineHttpRequest(
                http_method=tasks_v2.HttpMethod.GET,
                relative_uri=f"/stats/ratings_backfill?days={days}",
            )
        )
        client.create_task(request=tasks_v2.CreateTaskRequest(parent=parent, task=task))
        return True
    except Exception as ex:
        logging.warning(f"Could not enqueue a backfill continuation task: {ex!r}")
        return False


def deferred_stats(from_time: datetime, to_time: datetime, wait: bool) -> bool:
    """This is the deferred stats collection process"""

    def _deferred_stats() -> bool:
        success = False
        t0 = time.time()
        error = "Gave up after two retries"
        try:
            # Try up to two times to execute _run_stats()
            attempts = 0
            while attempts < 2:
                if _run_stats(from_time, to_time):
                    # Success: we're done
                    success = True
                    break
                attempts += 1
                logging.warning("Retrying _run_stats()")

        except Exception as ex:
            logging.error("Exception in deferred_stats: {0!r}".format(ex))
            success = False
            error = str(ex)

        t1 = time.time()
        if success:
            logging.info(
                "Stats calculation successfully finished in {0:.2f} seconds".format(
                    t1 - t0
                )
            )
            CompletionModel.add_completion("stats", from_time, to_time)
        else:
            logging.error(
                "Stats calculation did not complete, after running for {0:.2f} seconds".format(
                    t1 - t0
                )
            )
            CompletionModel.add_failure("stats", from_time, to_time, error)
        return success

    if wait:
        # Synchronous
        return _deferred_stats()

    # Asynchronous: we need a new context for this thread
    with Client.get_context():
        # Disable the in-memory cache for this thread
        Context.disable_cache()
        return _deferred_stats()


def deferred_ratings(wait: bool) -> bool:
    """This is the deferred ratings table calculation process"""

    def _deferred_ratings() -> bool:

        t0 = time.time()

        try:
            _create_ratings()
        except Exception as ex:
            logging.error("Exception in deferred_ratings: {0!r}".format(ex))
            now = datetime.now(UTC)
            CompletionModel.add_failure("ratings", now, now, str(ex))
            return False

        t1 = time.time()

        StatsModel.log_cache_stats()
        # Do not maintain the cache in memory between runs
        StatsModel.clear_cache()

        logging.info("Ratings calculation finished in {0:.2f} seconds".format(t1 - t0))
        now = datetime.now(UTC)
        CompletionModel.add_completion("ratings", now, now)

        return True

    if wait:
        # Synchronous: we don't need a client context
        return _deferred_ratings()

    # Asynchronous: this thread needs a fresh client context
    with Client.get_context():
        # Disable the in-memory cache for this thread
        Context.disable_cache()
        return _deferred_ratings()


def run(request: Request, *, wait: bool) -> Tuple[str, int]:
    """Calculate a new set of statistics"""
    logging.info("Starting stats calculation")

    # If invoked without parameters (such as from a cron job),
    # this will calculate yesterday's statistics.
    # If invoked with a year=YYYY&month=MM&day=DD parameter,
    # the parameter is the starting date (from_time) for the calculation.
    now = datetime.now(UTC)
    yesterday = now - timedelta(days=1)

    year = int(request.args.get("year", str(yesterday.year)))
    month = int(request.args.get("month", str(yesterday.month)))
    day = int(request.args.get("day", str(yesterday.day)))

    from_time = datetime(year=year, month=month, day=day, tzinfo=UTC)
    to_time = from_time + timedelta(days=1)

    kwargs: Dict[str, Any] = dict(from_time=from_time, to_time=to_time, wait=wait)

    if not wait:
        # Asynchronous execution
        Thread(target=deferred_stats, kwargs=kwargs).start()
        # All is well so far and the calculation has been started
        # on a separate thread
        return "Stats calculation has been started", 200

    # Synchronous execution
    success = deferred_stats(**kwargs)
    if not success:
        return "Stats calculation failed", 500

    return "Stats calculation has been completed", 200


def ratings(request: Request, *, wait: bool) -> Tuple[str, int]:
    """Calculate new ratings tables"""
    logging.info("Starting ratings calculation")
    kwargs: Dict[str, Any] = dict(wait=wait)
    if not wait:
        Thread(target=deferred_ratings, kwargs=kwargs).start()
        return "Ratings calculation has been started", 200

    success = deferred_ratings(**kwargs)
    if not success:
        return "Ratings calculation failed", 500

    return "Ratings calculation completed", 200


# Cloud Scheduler routes - requests are only accepted when originated
# by the Google Cloud Scheduler


def _scheduler_wait_mode(task_name: str) -> Optional[bool]:
    """Check that the current request originates from the Google Cloud
    Scheduler, a Cloud Tasks queue or a cron job (or from a local
    development server). Returns None if the request is not authorized;
    otherwise False if the task should be run asynchronously (Cloud
    Scheduler requests), or True to run it synchronously."""
    headers: Dict[str, str] = cast(Any, request).headers
    task_queue_name = headers.get("X-AppEngine-QueueName", "")
    task_queue = task_queue_name != ""
    cloud_scheduler = request.environ.get("HTTP_X_CLOUDSCHEDULER", "") == "true"
    cron_job = headers.get("X-Appengine-Cron", "") == "true"
    if not any((task_queue, cloud_scheduler, cron_job, running_local)):
        # Only allow bona fide Google Cloud Scheduler or Task Queue requests
        return None
    if cloud_scheduler:
        logging.info(f"Running {task_name} from cloud scheduler")
        # Run Cloud Scheduler tasks asynchronously
        return False
    if task_queue:
        logging.info(f"Running {task_name} from queue {task_queue_name}")
    elif cron_job:
        logging.info(f"Running {task_name} from cron job")
    return True


@stats.route("/run", methods=["GET", "POST"])
def stats_run() -> ResponseType:
    """Start a task to calculate Elo points for games"""
    wait = _scheduler_wait_mode("stats")
    if wait is None:
        return "Restricted URL", 403
    return run(request, wait=wait)


@stats.route("/ratings", methods=["GET", "POST"])
def stats_ratings() -> ResponseType:
    """Start a task to calculate top Elo rankings"""
    wait = _scheduler_wait_mode("ratings")
    if wait is None:
        return "Restricted URL", 403
    result, status = ratings(request, wait=wait)
    if status == 200:
        # New ratings: ensure that old ones are deleted from cache
        memcache.delete("all", namespace="rating")
        memcache.delete("human", namespace="rating")
        memcache.delete("manual", namespace="rating")
    return result, status


@stats.route("/ratings_backfill", methods=["GET", "POST"])
def stats_ratings_backfill() -> ResponseType:
    """Backfill missing archived ratings tables, one date per invocation,
    chaining via a Cloud Tasks task until no dates are missing"""
    if _scheduler_wait_mode("ratings_backfill") is None:
        return "Restricted URL", 403
    try:
        days = int(request.args.get("days", str(BACKFILL_DEFAULT_DAYS)))
    except ValueError:
        return "Invalid days parameter", 400
    days = max(1, min(days, BACKFILL_MAX_DAYS))
    missing = _missing_archive_dates(days)
    if not missing:
        logging.info("Ratings backfill is complete; no dates are missing")
        return "Backfill complete", 200
    d = missing[0]
    t0 = time.time()
    _backfill_ratings_for_date(d)
    t1 = time.time()
    remaining = len(missing) - 1
    logging.info(
        f"Backfilled ratings for {d.isoformat()} in {t1 - t0:.1f} seconds; "
        f"{remaining} date(s) remaining"
    )
    if remaining > 0 and not _enqueue_backfill_task(days):
        logging.warning(
            "Backfill continuation could not be enqueued; "
            "re-invoke /stats/ratings_backfill to continue"
        )
    return f"Backfilled {d.isoformat()}; {remaining} date(s) remaining", 200
