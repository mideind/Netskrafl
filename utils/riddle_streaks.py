"""

    Riddle Streak Leaderboard Utility for Netskrafl

    Copyright © 2026 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This utility lists the users with the longest streaks of consecutive
    days played in Gáta dagsins (Riddle of the Day), per locale.

    The streak statistics are kept in the Firebase Realtime Database at
    gatadagsins/users/{locale}/{user_id}/stats and are maintained by
    update_user_streak_stats() in src/riddle.py. A day counts towards a
    streak when a submission improves the user's best score for that day's
    riddle. Note that currentStreak is only reset the next time a user plays,
    so a stored currentStreak can be stale; this utility reports a streak as
    current only if the user last played today or yesterday (UTC).

    This script is READ-ONLY. It reads PRODUCTION data (Firebase, and the
    user database for nicknames) when run against a production project.
    Nickname lookups go through the local Redis cache like the app does;
    nothing is written to the user database.

    Usage:
        python utils/riddle_streaks.py [--project PROJECT] [--locale LOCALE]
            [--top N] [--sort {longest,current}] [--no-names]

    Options:
        --project PROJECT  Firebase/GAE project (default: $PROJECT_ID or netskrafl).
                           Unless GOOGLE_APPLICATION_CREDENTIALS is set, the
                           credentials are read from
                           credentials/<project>/service-account.json
        --locale LOCALE    Only list this locale (default: all locales)
        --top N            Number of users to list per locale (default: 10)
        --sort KEY         Rank by 'longest' (default) or 'current' streak
        --no-names         Do not look up user nicknames

"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, cast

import argparse
import os
import sys
from datetime import datetime, timedelta, UTC
from pathlib import Path

# Configure Google Cloud gRPC to use native client OS DNS resolution.
os.environ["GRPC_DNS_RESOLVER"] = "native"

REPO_ROOT = Path(__file__).parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List the longest Gáta dagsins streaks per locale"
    )
    parser.add_argument(
        "--project",
        type=str,
        default=os.environ.get("PROJECT_ID") or "netskrafl",
        help="Firebase/GAE project id (default: $PROJECT_ID or netskrafl)",
    )
    parser.add_argument(
        "--locale",
        type=str,
        help="Only list this locale (default: all locales)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of users to list per locale (default: 10)",
    )
    parser.add_argument(
        "--sort",
        choices=("longest", "current"),
        default="longest",
        help="Rank by longest streak ever (default) or by current streak",
    )
    parser.add_argument(
        "--no-names",
        action="store_true",
        help="Do not look up user nicknames",
    )
    return parser.parse_args()


# Parse arguments and set up the environment before importing app modules,
# since the config module reads PROJECT_ID and the credentials at import time
_args = parse_args()
os.environ["PROJECT_ID"] = _args.project
os.environ["GOOGLE_CLOUD_PROJECT"] = _args.project
os.environ.setdefault("RUNNING_LOCAL", "true")
os.environ.setdefault("REDISHOST", "127.0.0.1")
os.environ.setdefault("REDISPORT", "6379")
if "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ:
    creds_path = REPO_ROOT / "credentials" / _args.project / "service-account.json"
    if creds_path.exists():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(creds_path)
    else:
        print(f"Warning: Credentials file not found: {creds_path}")
        print("You may need to run 'gcloud auth application-default login'")

# Add the src directory to the Python path for imports
sys.path.insert(0, str(REPO_ROOT / "src"))

try:
    from config import FIREBASE_DB_URL
    from firebase_admin import initialize_app, db  # type: ignore[import-untyped]
except ImportError as e:
    print(f"Error importing required modules: {e}")
    print("Make sure you're running this from the Netskrafl project directory")
    print("and that all dependencies are installed.")
    sys.exit(1)


StatsDict = Dict[str, Any]

_firebase_app: Any = None


def init_firebase(project_id: str) -> None:
    """Initialize Firebase app for the given project"""
    global _firebase_app
    if _firebase_app is None:
        _firebase_app = initialize_app(
            options={"projectId": project_id, "databaseURL": FIREBASE_DB_URL}
        )


def firebase_get(path: str, shallow: bool = False) -> Optional[Any]:
    """Get data from Firebase at the given path"""
    ref = cast(Any, db).reference(path, app=_firebase_app)
    return ref.get(shallow=shallow)


def fetch_locales() -> List[str]:
    """Return the locales that have riddle user statistics"""
    locales = cast(Optional[Dict[str, Any]], firebase_get("gatadagsins/users", shallow=True))
    return sorted(locales or {})


def fetch_stats(locale: str) -> Dict[str, StatsDict]:
    """Return a dict of user id -> streak statistics for the given locale"""
    users = cast(Optional[Dict[str, Any]], firebase_get(f"gatadagsins/users/{locale}"))
    result: Dict[str, StatsDict] = {}
    for user_id, node in (users or {}).items():
        stats = cast(Dict[str, Any], node or {}).get("stats")
        if stats:
            result[user_id] = cast(StatsDict, stats)
    return result


def live_streak(stats: StatsDict, today: str, yesterday: str) -> int:
    """Return the user's current streak, or 0 if it has lapsed
    (the stored currentStreak is only reset when the user plays again)"""
    if stats.get("lastPlayedDate", "") in (today, yesterday):
        return int(stats.get("currentStreak", 0))
    return 0


def fetch_nicknames(user_ids: List[str]) -> Dict[str, str]:
    """Look up nicknames for the given user ids (read-only)"""
    from skrafldb import Client, UserModel

    with Client.get_context():
        users = UserModel.fetch_multi(user_ids)
    return {uid: u.nickname for uid, u in zip(user_ids, users) if u is not None}


def main() -> None:
    init_firebase(_args.project)

    now = datetime.now(UTC).date()
    today = now.isoformat()
    yesterday = (now - timedelta(days=1)).isoformat()

    locales = [_args.locale] if _args.locale else fetch_locales()
    if not locales:
        print("No riddle user statistics found")
        return

    tables: List[Tuple[str, int, List[Tuple[str, StatsDict, int]]]] = []
    for locale in locales:
        stats = fetch_stats(locale)
        rows = [(uid, s, live_streak(s, today, yesterday)) for uid, s in stats.items()]
        if _args.sort == "current":
            rows.sort(key=lambda r: (r[2], int(r[1].get("longestStreak", 0))), reverse=True)
        else:
            rows.sort(key=lambda r: (int(r[1].get("longestStreak", 0)), r[2]), reverse=True)
        tables.append((locale, len(stats), rows[: _args.top]))

    nicknames: Dict[str, str] = {}
    if not _args.no_names:
        user_ids = sorted({uid for _, _, rows in tables for uid, _, _ in rows})
        if user_ids:
            nicknames = fetch_nicknames(user_ids)

    print(f"Gáta dagsins streaks in project {_args.project}, as of {today} (UTC)")
    for locale, num_users, rows in tables:
        print(f"\n{locale}: {num_users} users, top {len(rows)} by {_args.sort} streak")
        print(
            f"  {'#':>3} {'Longest':>7} {'Current':>7} {'Last played':<11} "
            f"{'Days':>5} {'Tops':>5}  {'Nickname':<20} User id"
        )
        for ix, (uid, s, current) in enumerate(rows, start=1):
            print(
                f"  {ix:>3} {int(s.get('longestStreak', 0)):>7} {current:>7} "
                f"{s.get('lastPlayedDate', ''):<11} {int(s.get('totalDaysPlayed', 0)):>5} "
                f"{int(s.get('totalTopScores', 0)):>5}  {nicknames.get(uid, ''):<20} {uid}"
            )


if __name__ == "__main__":
    main()

