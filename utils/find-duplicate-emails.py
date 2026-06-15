"""

    Duplicate-email diagnostic utility for Netskrafl

    Copyright © 2025 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This utility scans the UserModel entities in Google Cloud Datastore,
    groups them by (normalized) e-mail address, and reports the cases where
    more than one *active* user entity shares the same e-mail. This is the
    situation that the Málstaður login flow (and any other email-based login)
    has to disambiguate via UserModel.fetch_email().

    For every duplicated e-mail it also compares two disambiguation strategies:
      * "current":  the record fetch_email() currently returns
                    -> sorted(rs, key=lambda u: (u.elo > 0, u.timestamp),
                              reverse=True)[0]   (i.e. the *newest* played one)
      * "proposed": most completed human games, then human Elo, then overall
                    Elo, then the *oldest* (most original) account.
    The number of e-mails where the two strategies disagree is the practical
    measure of how often the current behavior picks the "wrong" account.

    Usage:
        python utils/find-duplicate-emails.py [--include-inactive]
                                              [--min-count N]
                                              [--csv FILE] [--limit N] [-v]

"""

from __future__ import annotations

from typing import DefaultDict, List, Optional, Tuple

import argparse
import csv as csvlib
import logging
import sys
import os
from collections import defaultdict
from datetime import datetime, UTC

# Configure Google Cloud gRPC to use native client OS DNS resolution.
# This saves ~20 seconds of blocking calls/timeouts upon first use of gRPC
# when running locally.
os.environ["GRPC_DNS_RESOLVER"] = "native"

# Add the src directory to the Python path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

try:
    from google.cloud import ndb
    from skrafldb import UserModel, iter_q
except ImportError as e:
    print(f"Error importing required modules: {e}")
    print("Make sure you're running this from the Netskrafl project directory")
    print("and that all dependencies are installed.")
    sys.exit(1)


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the scan"""
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logging.basicConfig(level=level, handlers=[handler], force=True)
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore


def uid(u: UserModel) -> str:
    """Return the entity id of a user, robustly"""
    try:
        return u.user_id()
    except Exception:
        return u.key.id()  # type: ignore


def epoch(ts: Optional[datetime]) -> float:
    """Epoch seconds for a (possibly missing) timestamp"""
    return ts.timestamp() if ts is not None else 0.0


def current_pick(rs: List[UserModel]) -> UserModel:
    """Replicate the existing UserModel.fetch_email() disambiguator:
    prefer elo>0, then the newest creation timestamp."""
    # Guard against None timestamps (the live code would raise on those)
    return sorted(rs, key=lambda u: ((u.elo or 0) > 0, epoch(u.timestamp)), reverse=True)[0]


def proposed_pick(rs: List[UserModel]) -> UserModel:
    """Proposed disambiguator: most completed human games, then human Elo,
    then overall Elo, then the oldest (most original) account."""
    return max(
        rs,
        key=lambda u: (u.games or 0, u.human_elo or 0, u.elo or 0, -epoch(u.timestamp)),
    )


def describe(u: UserModel) -> str:
    """One-line description of a candidate user record"""
    ts = u.timestamp.date().isoformat() if u.timestamp else "????-??-??"
    ll = u.last_login.date().isoformat() if u.last_login else "-"
    plan = u.plan or ""
    return (
        f"{uid(u):<24} created={ts} last_login={ll} "
        f"games={u.games or 0:<4} elo={u.elo or 0:<4} human_elo={u.human_elo or 0:<4} "
        f"plan={plan:<6} account={u.account or '-'}"
    )


def scan(
    include_inactive: bool,
    min_count: int,
    csv_path: Optional[str],
    limit: int,
) -> None:
    """Scan UserModel, group by email, report duplicates"""
    # email -> list of UserModel
    by_email: DefaultDict[str, List[UserModel]] = defaultdict(list)

    total = 0
    skipped_inactive = 0
    skipped_no_email = 0

    logging.info("Scanning UserModel entities...")
    for u in iter_q(UserModel.query(), chunk_size=200):
        total += 1
        if total % 5000 == 0:
            logging.info(f"Progress: {total} users scanned...")
        if u.inactive and not include_inactive:
            skipped_inactive += 1
            continue
        email = (u.email or "").lower().strip()
        if not email:
            skipped_no_email += 1
            continue
        by_email[email].append(u)

    # Keep only the genuinely duplicated groups
    dups: List[Tuple[str, List[UserModel]]] = sorted(
        ((e, rs) for e, rs in by_email.items() if len(rs) >= min_count),
        key=lambda kv: len(kv[1]),
        reverse=True,
    )

    n_emails = len(by_email)
    n_dup_emails = len(dups)
    n_dup_records = sum(len(rs) for _, rs in dups)
    n_excess = sum(len(rs) - 1 for _, rs in dups)
    n_disagree = sum(
        1 for _, rs in dups if uid(current_pick(rs)) != uid(proposed_pick(rs))
    )
    size_hist: DefaultDict[int, int] = defaultdict(int)
    for _, rs in dups:
        size_hist[len(rs)] += 1

    logging.info("")
    logging.info("=" * 64)
    logging.info("DUPLICATE-EMAIL SUMMARY")
    logging.info("=" * 64)
    logging.info(f"Total user entities scanned : {total}")
    logging.info(f"  inactive skipped          : {skipped_inactive}")
    logging.info(f"  no-email skipped          : {skipped_no_email}")
    logging.info(f"Distinct e-mails            : {n_emails}")
    logging.info(f"E-mails with >= {min_count} records  : {n_dup_emails}")
    logging.info(f"  user records involved     : {n_dup_records}")
    logging.info(f"  'excess' duplicate records: {n_excess}")
    logging.info(
        f"E-mails where current != proposed pick: {n_disagree} "
        f"({(100.0 * n_disagree / n_dup_emails):.1f}% of duplicates)"
        if n_dup_emails
        else "E-mails where current != proposed pick: 0"
    )
    logging.info("Group-size distribution (records per email):")
    for size in sorted(size_hist):
        logging.info(f"  {size} records: {size_hist[size]} e-mails")
    logging.info("=" * 64)

    # Detailed listing (capped by --limit)
    shown = dups if limit <= 0 else dups[:limit]
    for email, rs in shown:
        cur = uid(current_pick(rs))
        prop = uid(proposed_pick(rs))
        flag = "  <-- DIFFERS" if cur != prop else ""
        logging.info("")
        logging.info(f"{email}  ({len(rs)} records){flag}")
        for u in sorted(rs, key=lambda u: epoch(u.timestamp)):
            marks = []
            if uid(u) == cur:
                marks.append("CURRENT")
            if uid(u) == prop:
                marks.append("PROPOSED")
            tag = (" [" + ",".join(marks) + "]") if marks else ""
            logging.info(f"    {describe(u)}{tag}")

    if limit > 0 and len(dups) > limit:
        logging.info("")
        logging.info(f"... {len(dups) - limit} more duplicated e-mails not shown "
                     f"(use --limit 0 to list all)")

    # Optional CSV export of all duplicate records
    if csv_path:
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            w = csvlib.writer(f)
            w.writerow([
                "email", "group_size", "user_id", "created", "last_login",
                "games", "elo", "human_elo", "plan", "account",
                "is_current_pick", "is_proposed_pick",
            ])
            for email, rs in dups:
                cur = uid(current_pick(rs))
                prop = uid(proposed_pick(rs))
                for u in rs:
                    w.writerow([
                        email, len(rs), uid(u),
                        u.timestamp.isoformat() if u.timestamp else "",
                        u.last_login.isoformat() if u.last_login else "",
                        u.games or 0, u.elo or 0, u.human_elo or 0,
                        u.plan or "", u.account or "",
                        uid(u) == cur, uid(u) == prop,
                    ])
        logging.info("")
        logging.info(f"Wrote per-record CSV to {csv_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find UserModel entities with duplicated e-mail addresses",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include inactive accounts (default: active only, matching fetch_email)",
    )
    parser.add_argument(
        "--min-count",
        type=int,
        default=2,
        help="Minimum records per e-mail to report (default: 2)",
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="Optional path to write a per-record CSV of all duplicates",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max number of duplicated e-mails to list in detail (0 = all)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)

    logging.info("=" * 64)
    logging.info("Netskrafl Duplicate-Email Diagnostic")
    logging.info(f"Started at: {datetime.now(UTC).isoformat()}")
    logging.info("=" * 64)

    try:
        client = ndb.Client()
        with client.context():
            scan(
                include_inactive=args.include_inactive,
                min_count=args.min_count,
                csv_path=args.csv,
                limit=args.limit,
            )
        logging.info("")
        logging.info("Scan completed successfully!")
        return 0
    except KeyboardInterrupt:
        logging.info("\nScan interrupted by user")
        return 1
    except Exception as e:
        logging.error(f"Fatal error during scan: {e}")
        logging.exception("Full error details:")
        return 1


if __name__ == "__main__":
    sys.exit(main())
