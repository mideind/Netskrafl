"""

    Email Collection Utility for Netskrafl

    Copyright © 2025 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This utility collects email addresses from UserModel entities in Google
    Cloud Datastore and writes them to text files for use with SendGrid.

    Usage:
        python utils/collect-emails.py [--output-dir DIR] [--dry-run]

    Options:
        --output-dir DIR    Directory to write output files (default: current directory)
        --dry-run           Show statistics without writing files

    Output files:
        - regular-emails.txt: Email addresses of regular (non-friend) users
        - friend-emails.txt: Email addresses of friends (plan='friend' or has_paid=True)

"""

from __future__ import annotations

from typing import Set, Optional

import argparse
import logging
import sys
import os
from datetime import datetime, UTC

# Configure Google Cloud gRPC to use native client OS DNS resolution.
# This saves ~20 seconds of blocking calls/timeouts upon first use of gRPC
# when running locally.
os.environ["GRPC_DNS_RESOLVER"] = "native"

# Add the src directory to the Python path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

try:
    from google.cloud import ndb
    from skrafldb import UserModel, iter_q, PrefsDict
except ImportError as e:
    print(f"Error importing required modules: {e}")
    print("Make sure you're running this from the Netskrafl project directory")
    print("and that all dependencies are installed.")
    sys.exit(1)


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the collection process"""
    level = logging.DEBUG if verbose else logging.INFO
    # Create a handler that writes to stdout with immediate flushing
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    # Use force=True to override any logging config set by imported libraries
    logging.basicConfig(level=level, handlers=[handler], force=True)
    # Ensure stdout is unbuffered for real-time output
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore


def is_valid_email(email: str) -> bool:
    """Basic email validation - checks for @ and at least one dot after @"""
    if not email or "@" not in email:
        return False
    local, _, domain = email.partition("@")
    return bool(local) and "." in domain


def has_paid_from_prefs(prefs: Optional[PrefsDict]) -> bool:
    """Returns True if the user is a paying friend of Netskrafl"""
    if prefs is None:
        return False
    if not prefs.get("friend"):
        # Must be a friend before being a paying friend
        return False
    has_paid = prefs.get("haspaid")
    return isinstance(has_paid, bool) and has_paid


def is_friend_user(user: UserModel) -> bool:
    """Check if user is a friend (has plan='friend' or has_paid=True)"""
    # Check plan field
    if user.plan and user.plan != "":
        return True
    # Check has_paid in prefs
    prefs = getattr(user, "prefs", None)
    if has_paid_from_prefs(prefs):
        return True
    return False


def collect_emails(
    output_dir: str, dry_run: bool = False
) -> tuple[int, int, int, int]:
    """
    Collect emails from UserModel entities and write to files.

    Args:
        output_dir: Directory to write output files
        dry_run: If True, don't write files, just show statistics

    Returns:
        Tuple of (total_users, users_with_email, regular_count, friend_count)
    """
    regular_emails: Set[str] = set()
    friend_emails: Set[str] = set()

    total_users = 0
    users_with_email = 0
    invalid_emails = 0
    inactive_users = 0

    logging.info("Scanning UserModel entities...")

    for user in iter_q(UserModel.query(), chunk_size=200):
        total_users += 1

        if total_users % 1000 == 0:
            logging.info(f"Progress: {total_users} users scanned...")

        # Skip inactive users
        if user.inactive:
            inactive_users += 1
            continue

        # Get email
        email = user.email
        if not email:
            continue

        # Normalize email (lowercase, strip whitespace)
        email = email.lower().strip()

        # Validate email
        if not is_valid_email(email):
            invalid_emails += 1
            logging.debug(f"Invalid email skipped: {email}")
            continue

        users_with_email += 1

        # Categorize by friend status
        if is_friend_user(user):
            friend_emails.add(email)
        else:
            regular_emails.add(email)

    # Remove any friend emails from regular list (in case of duplicates
    # where same email appears as both friend and non-friend)
    regular_emails -= friend_emails

    logging.info("")
    logging.info("=" * 60)
    logging.info("COLLECTION SUMMARY")
    logging.info("=" * 60)
    logging.info(f"Total users scanned: {total_users}")
    logging.info(f"Inactive users skipped: {inactive_users}")
    logging.info(f"Users with valid email: {users_with_email}")
    logging.info(f"Invalid emails skipped: {invalid_emails}")
    logging.info(f"Unique regular emails: {len(regular_emails)}")
    logging.info(f"Unique friend emails: {len(friend_emails)}")
    logging.info("=" * 60)

    if dry_run:
        logging.info("")
        logging.info("DRY RUN - No files written")
        logging.info("Run without --dry-run to write output files")
    else:
        # Write output files
        regular_file = os.path.join(output_dir, "regular-emails.txt")
        friend_file = os.path.join(output_dir, "friend-emails.txt")

        # Sort emails for consistent output
        sorted_regular = sorted(regular_emails)
        sorted_friends = sorted(friend_emails)

        with open(regular_file, "w", encoding="utf-8") as f:
            for email in sorted_regular:
                f.write(email + "\n")
        logging.info(f"Wrote {len(sorted_regular)} emails to {regular_file}")

        with open(friend_file, "w", encoding="utf-8") as f:
            for email in sorted_friends:
                f.write(email + "\n")
        logging.info(f"Wrote {len(sorted_friends)} emails to {friend_file}")

    return total_users, users_with_email, len(regular_emails), len(friend_emails)


def main() -> int:
    """
    Main entry point for the email collection script.

    Returns:
        int: 0 if collection succeeds, 1 if it fails
    """
    parser = argparse.ArgumentParser(
        description="Collect email addresses from Netskrafl users",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python utils/collect-emails.py --dry-run           # Preview collection
  python utils/collect-emails.py                     # Collect to current directory
  python utils/collect-emails.py --output-dir /tmp   # Collect to specific directory
        """,
    )

    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory to write output files (default: current directory)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show statistics without writing files",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    setup_logging(args.verbose)

    # Validate output directory
    if not args.dry_run:
        if not os.path.isdir(args.output_dir):
            logging.error(f"Output directory does not exist: {args.output_dir}")
            return 1

    logging.info("=" * 60)
    logging.info("Netskrafl Email Collection Utility")
    logging.info(f"Started at: {datetime.now(UTC).isoformat()}")
    logging.info("=" * 60)

    try:
        # Initialize NDB client (required for Google Cloud NDB)
        client = ndb.Client()

        with client.context():
            collect_emails(
                output_dir=args.output_dir,
                dry_run=args.dry_run,
            )

        logging.info("")
        logging.info("Collection completed successfully!")
        return 0

    except KeyboardInterrupt:
        logging.info("\nCollection interrupted by user")
        return 1

    except Exception as e:
        logging.error(f"Fatal error during collection: {e}")
        logging.exception("Full error details:")
        return 1


if __name__ == "__main__":
    sys.exit(main())
