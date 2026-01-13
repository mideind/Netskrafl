"""

    Riddle User Reset Utility for Netskrafl

    Copyright © 2025 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This utility resets a test user's state in today's Riddle of the Day,
    allowing fresh testing from a clean state.

    IMPORTANT: This script modifies PRODUCTION Firebase data when run against
    the production database. Use with caution and only for designated test users.

    Configuration:
        Create resources/test_config.json with:
        {
            "test_user_email": "your-test-user@example.com",
            "default_locale": "is"
        }

    Usage:
        python utils/reset_riddle_user.py [--locale LOCALE] [--date DATE] [--dry-run]

    Options:
        --locale LOCALE    Override the default locale from config
        --date DATE        Reset for a specific date (YYYY-MM-DD), defaults to today
        --dry-run          Show what would be done without making changes

"""

from __future__ import annotations

from typing import Any, Callable, Optional, Dict, cast

import argparse
import json
import logging
import os
import sys
from datetime import datetime, UTC
from pathlib import Path

# Configure Google Cloud gRPC to use native client OS DNS resolution.
os.environ["GRPC_DNS_RESOLVER"] = "native"

# Path to the test configuration file
CONFIG_PATH = Path(__file__).parent.parent / "resources" / "test_config.json"


def load_config_early() -> Dict[str, str]:
    """Load test configuration before other imports (needed for PROJECT_ID)"""
    if not CONFIG_PATH.exists():
        print(f"Error: Configuration file not found: {CONFIG_PATH}")
        print(f"Please copy resources/test_config.template.json to {CONFIG_PATH}")
        print("and fill in the required values.")
        sys.exit(1)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    return config


# Load config early to set environment variables before imports that require them
_early_config = load_config_early()
if "project_id" in _early_config:
    os.environ["PROJECT_ID"] = _early_config["project_id"]

# Set Google Cloud credentials if specified in config
if "credentials_file" in _early_config:
    creds_path = Path(__file__).parent.parent / _early_config["credentials_file"]
    if creds_path.exists():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(creds_path)
    else:
        print(f"Warning: Credentials file not found: {creds_path}")
        print("You may need to run 'gcloud auth application-default login'")
elif "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ:
    print("Warning: No credentials_file in config and GOOGLE_APPLICATION_CREDENTIALS not set")
    print("You may need to run 'gcloud auth application-default login'")

# Add the src directory to the Python path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

try:
    from google.cloud import ndb
    from skrafldb import UserModel
    from config import FIREBASE_DB_URL
    from firebase_admin import initialize_app, db  # type: ignore[import-untyped]
except ImportError as e:
    print(f"Error importing required modules: {e}")
    print("Make sure you're running this from the Netskrafl project directory")
    print("and that all dependencies are installed.")
    sys.exit(1)


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the reset process"""
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logging.basicConfig(level=level, handlers=[handler], force=True)
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore


def load_config() -> Dict[str, str]:
    """Return the test configuration (already loaded early for PROJECT_ID)"""
    if not _early_config.get("test_user_email"):
        print("Error: test_user_email not set in configuration file")
        sys.exit(1)

    if not _early_config.get("project_id"):
        print("Error: project_id not set in configuration file")
        sys.exit(1)

    return _early_config


_firebase_app: Any = None


def init_firebase(project_id: str) -> None:
    """Initialize Firebase app for the given project"""
    global _firebase_app
    if _firebase_app is None:
        _firebase_app = initialize_app(
            options={"projectId": project_id, "databaseURL": FIREBASE_DB_URL}
        )


def firebase_get(path: str) -> Optional[Any]:
    """Get data from Firebase at the given path"""
    try:
        ref = cast(Any, db).reference(path, app=_firebase_app)
        return ref.get()
    except Exception as e:
        logging.warning(f"Exception in firebase_get({path}): {repr(e)}")
        return None


def firebase_set(path: str, value: Optional[Any]) -> bool:
    """Set data at Firebase path (None to delete)"""
    try:
        ref = cast(Any, db).reference(path, app=_firebase_app)
        if value is None:
            ref.delete()
        else:
            ref.set(value)
        return True
    except Exception as e:
        logging.warning(f"Exception in firebase_set({path}): {repr(e)}")
        return False


def firebase_transaction(
    path: str, update_fn: Callable[[Optional[int]], int]
) -> bool:
    """Run a transaction at the given Firebase path"""
    try:
        ref = cast(Any, db).reference(path, app=_firebase_app)
        ref.transaction(update_fn)
        return True
    except Exception as e:
        logging.warning(f"Exception in firebase_transaction({path}): {repr(e)}")
        return False


def get_user_id(email: str) -> Optional[str]:
    """Look up user ID from email using NDB context"""
    client = ndb.Client()
    with client.context():
        user = UserModel.fetch_email(email)
        if user is None:
            return None
        return user.user_id()


def reset_riddle_user(
    user_id: str,
    riddle_date: str,
    locale: str,
    dry_run: bool = False,
) -> bool:
    """Reset a user's state for a specific riddle date.

    Returns True if any changes were made (or would be made in dry-run mode).
    """
    logging.info(f"Resetting riddle state for user {user_id}")
    logging.info(f"Date: {riddle_date}, Locale: {locale}")

    changes_made = False

    # Paths in Firebase
    achievement_path = f"gatadagsins/{riddle_date}/{locale}/achievements/{user_id}"
    leaders_path = f"gatadagsins/{riddle_date}/{locale}/leaders"
    best_path = f"gatadagsins/{riddle_date}/{locale}/best"
    count_path = f"gatadagsins/{riddle_date}/{locale}/count"

    # Check if user has an achievement
    achievement: Optional[Dict[str, Any]] = firebase_get(achievement_path)
    if achievement:
        logging.info(f"Found achievement: score={achievement.get('score')}, "
                     f"word='{achievement.get('word')}', isTopScore={achievement.get('isTopScore')}")
        had_top_score = achievement.get("isTopScore", False)
        changes_made = True

        if not dry_run:
            # Delete the achievement
            firebase_set(achievement_path, None)
            logging.info("Deleted user achievement")

            # Decrement count if user had top score and count exists
            if had_top_score:
                current_count = firebase_get(count_path)
                if current_count is not None and current_count > 0:
                    def decrement_count(current: Optional[int]) -> int:
                        return max(0, (current or 0) - 1)
                    firebase_transaction(count_path, decrement_count)
                    logging.info("Decremented top score count")
                else:
                    logging.info("Top score count doesn't exist or is zero, skipping decrement")
        else:
            logging.info("[DRY RUN] Would delete user achievement")
            if had_top_score:
                current_count = firebase_get(count_path)
                if current_count is not None and current_count > 0:
                    logging.info("[DRY RUN] Would decrement top score count")
                else:
                    logging.info("[DRY RUN] Top score count doesn't exist or is zero, would skip decrement")
    else:
        logging.info("No achievement found for this user/date/locale")

    # Check if user is in the leaderboard
    leaderboard: Optional[Dict[str, Any]] = firebase_get(leaders_path)
    if leaderboard and user_id in leaderboard:
        logging.info(f"Found leaderboard entry: score={leaderboard[user_id].get('score')}")
        changes_made = True

        if not dry_run:
            # Remove user from leaderboard
            del leaderboard[user_id]
            firebase_set(leaders_path, leaderboard)
            logging.info("Removed user from leaderboard")
        else:
            logging.info("[DRY RUN] Would remove user from leaderboard")
    else:
        logging.info("User not found in leaderboard")

    # Check if user holds the global best
    best: Optional[Dict[str, Any]] = firebase_get(best_path)
    if best and best.get("player") == user_id:
        logging.warning("WARNING: This user holds the global best score!")
        logging.warning(f"Best score: {best.get('score')}, word: '{best.get('word')}'")
        logging.warning("The global best will NOT be automatically recalculated.")
        logging.warning("You may need to manually update or clear the global best.")
        # We don't automatically clear the global best as it requires
        # recalculating from remaining leaderboard entries

    if not changes_made:
        logging.info("No changes needed - user has no riddle state for this date")

    return changes_made


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reset a test user's riddle state for testing purposes"
    )
    parser.add_argument(
        "--locale",
        type=str,
        help="Locale to reset (overrides config default)",
    )
    parser.add_argument(
        "--date",
        type=str,
        help="Date to reset (YYYY-MM-DD format, defaults to today)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    setup_logging(args.verbose)

    # Load configuration
    config = load_config()
    project_id = config["project_id"]
    email = config["test_user_email"]
    locale = args.locale or config.get("default_locale", "is")

    # Determine the date
    if args.date:
        try:
            datetime.strptime(args.date, "%Y-%m-%d")
            riddle_date = args.date
        except ValueError:
            print(f"Error: Invalid date format '{args.date}'. Use YYYY-MM-DD.")
            sys.exit(1)
    else:
        riddle_date = datetime.now(UTC).strftime("%Y-%m-%d")

    logging.info(f"Test user email: {email}")
    logging.info(f"Locale: {locale}")
    logging.info(f"Date: {riddle_date}")

    if args.dry_run:
        logging.info("DRY RUN MODE - no changes will be made")

    # Look up the user ID
    logging.info("Looking up user ID from email...")
    user_id = get_user_id(email)
    if not user_id:
        print(f"Error: User not found with email: {email}")
        sys.exit(1)

    logging.info(f"Found user ID: {user_id}")

    # Initialize Firebase
    logging.info("Initializing Firebase...")
    init_firebase(project_id)

    # Perform the reset
    changes_made = reset_riddle_user(
        user_id=user_id,
        riddle_date=riddle_date,
        locale=locale,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        if changes_made:
            logging.info("DRY RUN complete - run without --dry-run to apply changes")
        else:
            logging.info("DRY RUN complete - no changes would be made")
    else:
        if changes_made:
            logging.info("Reset complete")
        else:
            logging.info("No changes were necessary")


if __name__ == "__main__":
    main()
