"""

    Realtime Database cleanup utility for Netskrafl and Explo

    Copyright © 2026 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    Runs the cleanup of src/rtdb_cleanup.py (which the app runs daily via
    /connect/cleanup) from the command line, against any Realtime Database
    instance: for a dry run before the cron job is enabled, for working off
    a large backlog in one go, and, with --wipe, for emptying an instance
    that no longer has any clients.

    The cleanup only touches the Realtime Database, which has no Redis cache
    in front of it, so no cache flush is needed afterwards.

    Usage, from the repository root:
        venv/bin/python utils/rtdb-cleanup.py --project PROJECT --url URL [--dry-run]
            [--game-days N] [--presence-days N] [--session-days N]
            [--budget SECONDS] [--batch-size N]
        venv/bin/python utils/rtdb-cleanup.py --project PROJECT --url URL
            --wipe PATH [--wipe PATH ...] [--dry-run]

    PROJECT selects the service account key in credentials/PROJECT/ (override
    with --credentials). URL is the database instance URL; it is not kept in
    this repository.

    --wipe deletes EVERY child of each given path, regardless of age, and asks
    for the instance's host name as confirmation. Never use it on an instance
    that is still in use.

"""

from __future__ import annotations

from typing import List, Optional

import argparse
import os
import sys
from urllib.parse import urlparse

# Make the modules in src/ importable
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

import firebase_admin  # type: ignore  # noqa: E402
from firebase_admin import credentials  # type: ignore  # noqa: E402

import rtdb_cleanup  # noqa: E402


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete Realtime Database entries that no client will read again"
    )
    parser.add_argument(
        "--project",
        required=True,
        choices=["netskrafl", "explo-live", "explo-dev"],
        help="Google Cloud project (selects the service account key)",
    )
    parser.add_argument("--url", required=True, help="Database instance URL")
    parser.add_argument(
        "--credentials",
        help="Service account key file (default: credentials/PROJECT/service-account.json)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Only count, delete nothing"
    )
    parser.add_argument(
        "--game-days",
        type=float,
        default=rtdb_cleanup.GAME_RETENTION_DAYS,
        help="Retention of game/ nodes, in days (default: %(default)s)",
    )
    parser.add_argument(
        "--presence-days",
        type=float,
        default=rtdb_cleanup.PRESENCE_RETENTION_DAYS,
        help="Retention of connection/ entries, in days (default: %(default)s)",
    )
    parser.add_argument(
        "--session-days",
        type=float,
        default=rtdb_cleanup.SESSION_RETENTION_DAYS,
        help="Retention of session/ tokens, in days (default: %(default)s)",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=None,
        help="Time budget in seconds (default: no limit)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=rtdb_cleanup.BATCH_SIZE,
        help="Paths deleted per request (default: %(default)s)",
    )
    parser.add_argument(
        "--wipe",
        action="append",
        metavar="PATH",
        help="Delete every child of PATH, regardless of age (repeatable)",
    )
    args = parser.parse_args(argv)
    if any(d < 0 for d in (args.game_days, args.presence_days, args.session_days)):
        parser.error("Retention periods cannot be negative")
    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")
    return args


def confirm_wipe(url: str, paths: List[str]) -> bool:
    """Ask the user to type the instance's host name"""
    host = urlparse(url).hostname or url
    print(f"This deletes EVERY child of {', '.join(p + '/' for p in paths)} on {host}.")
    answer = input("Type the host name to confirm: ").strip()
    return answer == host


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    key_file = args.credentials or os.path.join(
        "credentials", args.project, "service-account.json"
    )
    if not os.path.exists(key_file):
        print(f"Service account key not found: {key_file}", file=sys.stderr)
        return 1
    app = firebase_admin.initialize_app(
        credentials.Certificate(key_file),
        {"databaseURL": args.url},
        name="rtdb-cleanup",
    )
    access = rtdb_cleanup.FirebaseAdminAccess(app)

    if args.wipe:
        paths = [p.strip("/") for p in args.wipe]
        if any(not p for p in paths):
            print("--wipe needs a path below the root", file=sys.stderr)
            return 1
        if not args.dry_run and not confirm_wipe(args.url, paths):
            print("Not confirmed, nothing deleted")
            return 1
        for path in paths:
            stats = rtdb_cleanup.wipe_children(
                access,
                path,
                dry_run=args.dry_run,
                time_budget=args.budget,
                batch_size=args.batch_size,
            )
            print(f"{path}/: {stats}")
        return 0

    result = rtdb_cleanup.cleanup(
        access,
        dry_run=args.dry_run,
        game_days=args.game_days,
        presence_days=args.presence_days,
        session_days=args.session_days,
        time_budget=args.budget,
        batch_size=args.batch_size,
    )
    print(result.summary())
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())

