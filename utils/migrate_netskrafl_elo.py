"""

    Elo Migration Utility for Netskrafl

    Copyright © 2025 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This utility migrates Elo ratings from UserModel entities to the new
    EloModel entity structure used by Explo, enabling real-time Elo updates
    instead of nightly batch processing.

    Usage:
        python utils/migrate_netskrafl_elo.py [--dry-run] [--force]

    Options:
        --dry-run    Show what would be migrated without making changes
        --force      Skip confirmation prompts (use with caution)

    The migration process:
    1. Creates EloModel entities for all users with Elo ratings
    2. Creates RobotModel entities for all robot difficulty levels
    3. Preserves all existing UserModel data (non-destructive)
    4. Provides detailed progress reporting and error handling

"""

from __future__ import annotations

from typing import List, Tuple, Dict, Any

import argparse
import logging
import sys
import os
from datetime import datetime, UTC

# Add the src directory to the Python path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

try:
    from google.cloud import ndb
    from skrafldb import UserModel, EloModel, RobotModel, StatsModel, iter_q
    from skraflelo import EloDict
    from config import DEFAULT_ELO, DEFAULT_LOCALE
    from autoplayers import TOP_SCORE, COMMON, ADAPTIVE
except ImportError as e:
    print(f"Error importing required modules: {e}")
    print("Make sure you're running this from the Netskrafl utils directory")
    print("and that all dependencies are installed.")
    sys.exit(1)


class MigrationStats:
    """Track migration statistics and progress"""

    def __init__(self) -> None:
        self.users_processed = 0
        self.users_migrated = 0
        self.users_skipped = 0
        self.robots_created = 0
        self.errors: List[str] = []
        self.start_time = datetime.now(UTC)

    def log_user_migrated(self, user_id: str) -> None:
        """Record successful user migration"""
        self.users_migrated += 1
        self.users_processed += 1
        if self.users_processed % 100 == 0:
            logging.info(f"Progress: {self.users_processed} users processed, {self.users_migrated} migrated")

    def log_user_skipped(self, user_id: str, reason: str) -> None:
        """Record skipped user with reason"""
        self.users_skipped += 1
        self.users_processed += 1
        logging.debug(f"Skipped user {user_id}: {reason}")
        if self.users_processed % 100 == 0:
            logging.info(f"Progress: {self.users_processed} users processed, {self.users_migrated} migrated")

    def log_error(self, error: str) -> None:
        """Record migration error"""
        self.errors.append(error)
        logging.error(error)

    def log_robot_created(self, level: int) -> None:
        """Record robot model creation"""
        self.robots_created += 1
        logging.info(f"Created RobotModel for level {level}")

    def get_summary(self) -> Dict[str, Any]:
        """Get migration summary statistics"""
        end_time = datetime.now(UTC)
        duration = end_time - self.start_time

        return {
            "duration_seconds": duration.total_seconds(),
            "users_processed": self.users_processed,
            "users_migrated": self.users_migrated,
            "users_skipped": self.users_skipped,
            "robots_created": self.robots_created,
            "errors_count": len(self.errors),
            "success_rate": (self.users_migrated / max(1, self.users_processed)) * 100
        }


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the migration process"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('elo_migration.log')
        ]
    )


def get_robot_default_elo(level: int) -> int:
    """
    Get default Elo rating for robot at given difficulty level.
    
    Args:
        level: Robot difficulty level (TOP_SCORE, COMMON, or ADAPTIVE)
        
    Returns:
        int: Default Elo rating for the robot level
    """
    # Robot Elo ratings based on difficulty level
    # Netskrafl has three robots: Fullsterkur, Miðlungur, and Amlóði
    robot_elos = {
        TOP_SCORE: 1600,  # Fullsterkur - strongest robot
        COMMON: 1200,     # Miðlungur - medium difficulty robot  
        ADAPTIVE: 1000,   # Amlóði - adaptive/beginner robot
    }
    return robot_elos.get(level, DEFAULT_ELO)


def check_prerequisites() -> bool:
    """
    Check if the system is ready for migration.

    Returns:
        bool: True if prerequisites are met, False otherwise
    """
    logging.info("Checking migration prerequisites...")

    try:
        # Test database connectivity
        _ = UserModel.query().count(limit=1)
        logging.info("✓ Database connectivity verified")

        # Check whether EloModel entities already exist
        existing_elo_count = EloModel.query().filter(EloModel.locale == DEFAULT_LOCALE).count(limit=10)

        if existing_elo_count > 0:
            logging.warning(f"Found {existing_elo_count} existing EloModel entities")
            logging.warning("This might indicate a partial or previous migration")
            return False

        logging.info("✓ No existing EloModel entities found")
        return True

    except Exception as e:
        logging.error(f"Prerequisites check failed: {e}")
        return False


def migrate_user_elo(user: UserModel, stats: MigrationStats, dry_run: bool = False) -> bool:
    """
    Migrate Elo ratings for a single user from UserModel to EloModel.
    
    Args:
        user: UserModel entity to migrate
        stats: Migration statistics tracker
        dry_run: If True, don't actually create entities
        
    Returns:
        bool: True if migration successful, False otherwise
    """
    user_id = user.user_id()

    # Skip users with no Elo data
    if not (user.elo or user.human_elo or user.manual_elo):
        stats.log_user_skipped(user_id, "no Elo data")
        return True

    # Check if EloModel already exists (shouldn't happen in fresh migration)
    existing_elo = EloModel.user_elo(DEFAULT_LOCALE, user_id)
    if existing_elo:
        stats.log_user_skipped(user_id, "EloModel already exists")
        return True

    try:
        # Create EloDict with user's current ratings
        ratings = EloDict(
            elo=user.elo or DEFAULT_ELO,
            human_elo=user.human_elo or DEFAULT_ELO,
            manual_elo=user.manual_elo or DEFAULT_ELO
        )

        if dry_run:
            logging.debug(f"[DRY RUN] Would create EloModel for user {user_id}: {ratings}")
            stats.log_user_migrated(user_id)
            return True

        # Create new EloModel entity
        success = EloModel.upsert(
            None,           # No existing entity
            DEFAULT_LOCALE, # Netskrafl locale
            user_id,        # User ID
            ratings         # Elo ratings
        )

        if success:
            stats.log_user_migrated(user_id)
            logging.debug(f"Migrated user {user_id}: elo={ratings.elo}, human_elo={ratings.human_elo}, manual_elo={ratings.manual_elo}")
            return True
        else:
            stats.log_error(f"Failed to create EloModel for user {user_id}")
            return False

    except Exception as e:
        stats.log_error(f"Error migrating user {user_id}: {e}")
        return False


def migrate_robot_elo(level: int, stats: MigrationStats, dry_run: bool = False) -> bool:
    """
    Create RobotModel entity for a robot difficulty level from existing StatsModel data.
    
    Args:
        level: Robot difficulty level (TOP_SCORE, COMMON, or ADAPTIVE)
        stats: Migration statistics tracker
        dry_run: If True, don't actually create entities
        
    Returns:
        bool: True if creation successful, False otherwise
    """
    try:
        # Check if RobotModel already exists
        existing_robot = RobotModel.robot_elo(DEFAULT_LOCALE, level)
        if existing_robot:
            logging.info(f"RobotModel for level {level} already exists, skipping")
            return True

        # Find existing robot Elo data in StatsModel  
        robot_stats = None
        for stats_entry in iter_q(StatsModel.query().filter(
            # Robot entries have user = None
            # Note: must use == (not 'is') for Datastore query filters
            StatsModel.user == None,  # noqa: E711
            StatsModel.robot_level == level
        ), limit=1):
            robot_stats = stats_entry
            break  # Take the first (most recent) entry

        if robot_stats:
            # Use existing Elo rating from StatsModel (RobotModel only has single elo field)
            robot_elo = robot_stats.elo or DEFAULT_ELO

            logging.debug(f"Found existing robot stats for level {level}: elo={robot_elo}")
        else:
            # Use default Elo if no existing stats found
            robot_elo = get_robot_default_elo(level)

            logging.warning(f"No existing StatsModel found for robot level {level}, using default: elo={robot_elo}")

        if dry_run:
            logging.info(f"[DRY RUN] Would create RobotModel for level {level}: elo={robot_elo}")
            stats.log_robot_created(level)
            return True

        # Create RobotModel entity with actual Elo ratings
        success = RobotModel.upsert(
            None,           # No existing entity
            DEFAULT_LOCALE, # Netskrafl locale
            level,          # Robot level
            robot_elo,      # Current Elo rating from StatsModel
        )

        if success:
            stats.log_robot_created(level)
            return True
        else:
            stats.log_error(f"Failed to create RobotModel for level {level}")
            return False

    except Exception as e:
        stats.log_error(f"Error creating RobotModel for level {level}: {e}")
        return False


def get_migration_preview() -> Tuple[int, int, Dict[int, bool]]:
    """
    Get preview of what will be migrated without making changes.
    
    Returns:
        Tuple[int, int, Dict[int, bool]]: (users_to_migrate, total_users, robots_found)
    """
    logging.info("Analyzing data for migration preview...")

    total_users = 0
    users_with_elo = 0
    robots_found: Dict[int, bool] = {}

    # Check users
    for user in iter_q(UserModel.query()):
        total_users += 1
        if user.elo or user.human_elo or user.manual_elo:
            users_with_elo += 1

    # Check existing robot data in StatsModel
    robot_levels = [TOP_SCORE, COMMON, ADAPTIVE]
    for level in robot_levels:
        # Note: must use == (not 'is') for Datastore query filters
        robot_stats_exist = StatsModel.query().filter(
            StatsModel.user == None,  # noqa: E711
            StatsModel.robot_level == level
        ).count(limit=1) > 0
        robots_found[level] = robot_stats_exist

    return users_with_elo, total_users, robots_found


def migrate_netskrafl_elo(dry_run: bool = False, force: bool = False) -> bool:
    """
    Main migration function that migrates all Elo data from UserModel to EloModel.
    
    Args:
        dry_run: If True, show what would be done without making changes
        force: If True, skip confirmation prompts
        
    Returns:
        bool: True if migration successful, False otherwise
    """
    stats = MigrationStats()

    logging.info("=" * 60)
    if dry_run:
        logging.info("Starting Elo migration DRY RUN...")
    else:
        logging.info("Starting Elo migration...")
    logging.info(f"Default locale: {DEFAULT_LOCALE}")
    logging.info(f"Default Elo rating: {DEFAULT_ELO}")
    logging.info("=" * 60)

    # Check prerequisites
    if not dry_run and not check_prerequisites():
        logging.error("Prerequisites check failed - aborting migration")
        return False

    # Get migration preview
    users_to_migrate, total_users, robots_found = get_migration_preview()

    robot_names = {TOP_SCORE: "Fullsterkur", COMMON: "Miðlungur", ADAPTIVE: "Amlóði"}

    logging.info("Migration scope:")
    logging.info(f"  Total users in database: {total_users}")
    logging.info(f"  Users with Elo data to migrate: {users_to_migrate}")
    logging.info("  Robot levels to create: 3 (Fullsterkur, Miðlungur, Amlóði)")

    logging.info("Existing robot data in StatsModel:")
    for level, found in robots_found.items():
        status = "✓ Found" if found else "✗ Not found"
        logging.info(f"  {robot_names[level]} (level {level}): {status}")

    # Confirmation prompt (unless forced or dry run)
    if not dry_run and not force:
        response = input(f"\nProceed with migration of {users_to_migrate} users? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            logging.info("Migration cancelled by user")
            return False

    try:
        # Phase 1: Migrate user Elo data
        logging.info("\nPhase 1: Migrating user Elo data...")
        user_success = True

        for user in iter_q(UserModel.query()):
            if not migrate_user_elo(user, stats, dry_run):
                user_success = False
                # Continue processing other users even if one fails

        # Phase 2: Create robot models
        logging.info("\nPhase 2: Creating robot models...")
        robot_success = True

        # Create robot models for the three Netskrafl robots
        robot_levels = [TOP_SCORE, COMMON, ADAPTIVE]  # Fullsterkur, Miðlungur, Amlóði
        for level in robot_levels:
            if not migrate_robot_elo(level, stats, dry_run):
                robot_success = False
                # Continue with other robot levels

        # Generate final report
        summary = stats.get_summary()

        logging.info("\n" + "=" * 60)
        logging.info("MIGRATION SUMMARY")
        logging.info("=" * 60)
        logging.info(f"Duration: {summary['duration_seconds']:.1f} seconds")
        logging.info(f"Users processed: {summary['users_processed']}")
        logging.info(f"Users migrated: {summary['users_migrated']}")
        logging.info(f"Users skipped: {summary['users_skipped']}")
        logging.info(f"Robot models created: {summary['robots_created']}")
        logging.info(f"Success rate: {summary['success_rate']:.1f}%")
        logging.info(f"Errors encountered: {summary['errors_count']}")

        if stats.errors:
            logging.info("\nFirst few errors:")
            for error in stats.errors[:5]:
                logging.info(f"  - {error}")
            if len(stats.errors) > 5:
                logging.info(f"  ... and {len(stats.errors) - 5} more errors")

        overall_success = user_success and robot_success and len(stats.errors) == 0

        if dry_run:
            logging.info("\n🔍 DRY RUN COMPLETED - No changes were made")
            logging.info("Use without --dry-run to perform actual migration")
        elif overall_success:
            logging.info("\n🎉 MIGRATION COMPLETED SUCCESSFULLY!")
            logging.info("Run verify_elo_migration.py to validate the results")
        else:
            logging.error("\n💥 MIGRATION COMPLETED WITH ERRORS!")
            logging.error("Check the log for details and consider running verification")

        logging.info("=" * 60)

        return overall_success

    except Exception as e:
        logging.error(f"Fatal error during migration: {e}")
        logging.exception("Full error details:")
        return False


def create_backup_info() -> Dict[str, Any]:
    """
    Create backup information for rollback purposes.
    
    Returns:
        Dict[str, Any]: Backup metadata
    """
    return {
        "backup_timestamp": datetime.now(UTC).isoformat(),
        "migration_tool": "migrate_netskrafl_elo.py",
        "default_locale": DEFAULT_LOCALE,
        "default_elo": DEFAULT_ELO,
        "note": "This migration is non-destructive - UserModel data is preserved"
    }


def main() -> int:
    """
    Main entry point for the migration script.
    
    Returns:
        int: 0 if migration succeeds, 1 if it fails
    """
    parser = argparse.ArgumentParser(
        description="Migrate Netskrafl Elo ratings from UserModel to EloModel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python utils/migrate_netskrafl_elo.py --dry-run    # Preview migration
  python utils/migrate_netskrafl_elo.py              # Interactive migration
  python utils/migrate_netskrafl_elo.py --force      # Automated migration
        """
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without making changes"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompts (use with caution)"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    setup_logging(args.verbose)

    try:
        # Initialize NDB client (required for Google Cloud NDB)
        client = ndb.Client()

        with client.context():
            # Create backup info for documentation
            backup_info = create_backup_info()
            logging.info(f"Migration metadata: {backup_info}")

            success = migrate_netskrafl_elo(
                dry_run=args.dry_run,
                force=args.force
            )

        return 0 if success else 1

    except KeyboardInterrupt:
        logging.info("\nMigration interrupted by user")
        return 1

    except Exception as e:
        logging.error(f"Fatal error during migration: {e}")
        logging.exception("Full error details:")
        return 1


if __name__ == "__main__":
    sys.exit(main())
