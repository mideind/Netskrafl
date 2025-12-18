"""

    Elo Migration Verification Utility for Netskrafl

    Copyright © 2025 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson (with help from Claude Code ;-))

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This utility verifies the successful migration of Elo ratings from
    UserModel entities to the new EloModel entity structure used by Explo.

    Usage:
        python utils/verify_elo_migration.py

    The script performs comprehensive verification including:
    - Data consistency between UserModel and EloModel entities
    - Entity count verification
    - Robot model validation
    - Parent-child relationship checks
    - Sample data spot checks

"""

from __future__ import annotations

from typing import List, Set, Tuple, Callable

import logging
import sys
import os
from datetime import datetime, UTC

from skrafldb import StatsDict

# Dynamically determine the absolute path to the src directory for imports
base_path = os.path.abspath(os.path.dirname(__file__))
src_path = os.path.abspath(os.path.join(base_path, "..", "src"))
sys.path.append(src_path)

try:
    from google.cloud import ndb
    from skrafldb import UserModel, EloModel, RobotModel, StatsModel, iter_q
    from config import DEFAULT_ELO, DEFAULT_LOCALE
    from autoplayers import TOP_SCORE, COMMON, ADAPTIVE
except ImportError as e:
    print(f"Error importing required modules: {e}")
    print("Make sure you're running this from the Netskrafl utils directory")
    print("and that all dependencies are installed.")
    sys.exit(1)


def setup_logging() -> None:
    """Configure logging for the verification process"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('elo_migration_verification.log')
        ]
    )


def check_data_consistency() -> bool:
    """
    Verify all UserModel Elo data was correctly migrated to EloModel.
    
    Returns:
        bool: True if all data is consistent, False otherwise
    """
    inconsistencies: List[str] = []
    processed_count = 0

    logging.info("Checking data consistency between UserModel and EloModel...")

    # Query all users and check their Elo data
    for user in iter_q(UserModel.query()):
        user_id = user.user_id()
        processed_count += 1

        # Skip users with no Elo data
        if not (user.elo or user.human_elo or user.manual_elo):
            continue

        # Retrieve corresponding EloModel
        elo_model = EloModel.user_elo(DEFAULT_LOCALE, user_id)

        if elo_model is None:
            inconsistencies.append(f"Missing EloModel for user {user_id}")
            continue

        # Compare each Elo field, using DEFAULT_ELO for None/0 values
        user_elo = user.elo or DEFAULT_ELO
        user_human_elo = user.human_elo or DEFAULT_ELO
        user_manual_elo = user.manual_elo or DEFAULT_ELO

        if elo_model.elo != user_elo:
            inconsistencies.append(
                f"User {user_id}: UserModel.elo={user_elo} != EloModel.elo={elo_model.elo}"
            )
        if elo_model.human_elo != user_human_elo:
            inconsistencies.append(
                f"User {user_id}: UserModel.human_elo={user_human_elo} != "
                f"EloModel.human_elo={elo_model.human_elo}"
            )
        if elo_model.manual_elo != user_manual_elo:
            inconsistencies.append(
                f"User {user_id}: UserModel.manual_elo={user_manual_elo} != "
                f"EloModel.manual_elo={elo_model.manual_elo}"
            )

        # Log progress for large datasets
        if processed_count % 1000 == 0:
            logging.info(f"Processed {processed_count} users...")

    if inconsistencies:
        logging.error(f"Data consistency check failed: {len(inconsistencies)} issues found")
        # Log first 10 issues to avoid log spam
        for issue in inconsistencies[:10]:
            logging.error(f"  - {issue}")
        if len(inconsistencies) > 10:
            logging.error(f"  ... and {len(inconsistencies) - 10} more issues")
        return False

    logging.info(f"✓ Data consistency check passed ({processed_count} users processed)")
    return True


def check_entity_counts() -> bool:
    """
    Verify expected number of EloModel entities were created.
    
    Returns:
        bool: True if counts match, False otherwise
    """
    logging.info("Checking entity counts...")

    # Count users with Elo data in UserModel
    users_with_elo_query = UserModel.query().filter(
        ndb.OR(
            UserModel.elo > 0,
            UserModel.human_elo > 0,
            UserModel.manual_elo > 0
        )
    )
    user_count = users_with_elo_query.count()

    # Count EloModel entities for the default locale
    elo_models_query = EloModel.query().filter(EloModel.locale == DEFAULT_LOCALE)
    elo_count = elo_models_query.count()

    if user_count != elo_count:
        logging.error(
            f"Entity count mismatch: {user_count} users with Elo data, "
            f"{elo_count} EloModel entities"
        )
        return False

    logging.info(f"✓ Entity count verification passed: {elo_count} EloModel entities created")
    return True


def check_robot_models() -> bool:
    """
    Verify RobotModel entities were created correctly for all robot types.
    
    Returns:
        bool: True if all robot models exist, False otherwise
    """
    logging.info("Checking robot model entities...")

    # Netskrafl has three robots: Fullsterkur, Miðlungur, and Amlóði
    expected_levels = [TOP_SCORE, COMMON, ADAPTIVE]
    robot_names = ["Fullsterkur", "Miðlungur", "Amlóði"]
    missing_levels: List[Tuple[int, str]] = []
    inconsistencies: List[str] = []

    for level, name in zip(expected_levels, robot_names):
        robot = RobotModel.robot_elo(DEFAULT_LOCALE, level)
        if robot is None:
            missing_levels.append((level, name))
            continue

        # Check if RobotModel Elo matches StatsModel data
        original_stats = None
        for stats_entry in iter_q(StatsModel.query().filter(
            StatsModel.user == None,  # noqa: E711
            StatsModel.robot_level == level
        )):
            original_stats = stats_entry
            break

        if original_stats and robot.elo != original_stats.elo:
            inconsistencies.append(
                f"{name} (level {level}): RobotModel.elo={robot.elo} != StatsModel.elo={original_stats.elo}"
            )

    if missing_levels:
        missing_info = [f"{name} (level {level})" for level, name in missing_levels]
        logging.error(f"Missing RobotModel entities: {missing_info}")
        return False

    if inconsistencies:
        logging.error("Robot Elo inconsistencies found:")
        for inconsistency in inconsistencies:
            logging.error(f"  - {inconsistency}")
        return False

    logging.info(f"✓ Robot model verification passed ({robot_names})")
    return True


def check_entity_relationships() -> bool:
    """
    Verify EloModel entities have correct parent-child relationships with UserModel.
    
    Returns:
        bool: True if all relationships are correct, False otherwise
    """
    logging.info("Checking entity parent-child relationships...")

    relationship_errors: List[str] = []
    checked_count = 0

    for elo_model in iter_q(EloModel.query().filter(EloModel.locale == DEFAULT_LOCALE)):
        checked_count += 1

        # Check parent relationship exists
        parent_key = elo_model.key.parent()
        if parent_key is None:
            relationship_errors.append(f"EloModel {elo_model.key.id()} has no parent")
            continue

        # Verify parent is UserModel
        if parent_key.kind() != "UserModel":
            relationship_errors.append(
                f"EloModel {elo_model.key.id()} parent is {parent_key.kind()}, not UserModel"
            )
            continue

        # Verify parent entity exists
        parent_user = parent_key.get()
        if parent_user is None:
            relationship_errors.append(
                f"EloModel {elo_model.key.id()} parent UserModel does not exist"
            )
            continue

        # Verify key format is correct (should be "userid:locale")
        expected_key_id = EloModel.id(DEFAULT_LOCALE, parent_key.id())
        if elo_model.key.id() != expected_key_id:
            relationship_errors.append(
                f"EloModel key format incorrect: got {elo_model.key.id()}, "
                f"expected {expected_key_id}"
            )

    if relationship_errors:
        logging.error(f"Entity relationship check failed: {len(relationship_errors)} issues")
        # Log first 5 errors to avoid spam
        for error in relationship_errors[:5]:
            logging.error(f"  - {error}")
        if len(relationship_errors) > 5:
            logging.error(f"  ... and {len(relationship_errors) - 5} more issues")
        return False

    logging.info(f"✓ Entity relationship verification passed ({checked_count} entities checked)")
    return True


def spot_check_sample_data() -> bool:
    """
    Perform detailed verification on a sample of migrated data.
    
    Returns:
        bool: True if spot checks pass, False otherwise
    """
    logging.info("Performing sample data spot checks...")

    # Get sample of users with Elo data (limit to 20 for reasonable runtime)
    sample_users = list(
        UserModel.query()
        .filter(UserModel.elo > 0)
        .fetch(20)
    )

    if not sample_users:
        logging.warning("No users with Elo > 0 found for spot checking")
        return True

    spot_check_errors: List[str] = []

    for user in sample_users:
        user_id = user.user_id()
        elo_model = EloModel.user_elo(DEFAULT_LOCALE, user_id)

        # Verify EloModel exists
        if not elo_model:
            spot_check_errors.append(f"No EloModel found for user {user_id}")
            continue

        # Verify locale is correct
        if elo_model.locale != DEFAULT_LOCALE:
            spot_check_errors.append(
                f"Wrong locale for user {user_id}: got {elo_model.locale}, "
                f"expected {DEFAULT_LOCALE}"
            )

        # Verify timestamp is recent (should be from migration time)
        time_diff = datetime.now(UTC) - elo_model.timestamp
        if time_diff.total_seconds() > 7200:  # More than 2 hours old
            logging.warning(
                f"EloModel timestamp for user {user_id} is {time_diff.total_seconds():.0f} "
                f"seconds old (may not be from recent migration)"
            )

        # Verify all Elo values are reasonable (between 500 and 3000)
        for elo_type, elo_value in [
            ("elo", elo_model.elo),
            ("human_elo", elo_model.human_elo),
            ("manual_elo", elo_model.manual_elo)
        ]:
            if elo_value < 500 or elo_value > 3000:
                logging.warning(
                    f"User {user_id} has unusual {elo_type} value: {elo_value}"
                )

    if spot_check_errors:
        logging.error(f"Spot check failed: {len(spot_check_errors)} issues")
        for error in spot_check_errors:
            logging.error(f"  - {error}")
        return False

    logging.info(f"✓ Sample data spot check passed ({len(sample_users)} users checked)")
    return True


def check_robot_stats_migration() -> bool:
    """
    Verify that robot data was properly migrated from StatsModel to RobotModel.
    
    Returns:
        bool: True if robot migration is consistent, False otherwise
    """
    logging.info("Checking robot stats migration consistency...")

    robot_levels = [TOP_SCORE, COMMON, ADAPTIVE]
    robot_names = ["Fullsterkur", "Miðlungur", "Amlóði"]
    migration_errors: List[str] = []

    for level, name in zip(robot_levels, robot_names):
        # Check StatsModel data
        stats_entries = list(iter_q(StatsModel.query().filter(
            StatsModel.user == None,  # noqa: E711
            StatsModel.robot_level == level
        )))

        # Check RobotModel data  
        robot_model = RobotModel.robot_elo(DEFAULT_LOCALE, level)

        if not stats_entries:
            logging.warning(f"No StatsModel entries found for {name} (level {level})")
            # This might be okay if robot hasn't played games yet
            continue

        if not robot_model:
            migration_errors.append(f"RobotModel missing for {name} (level {level}) but StatsModel data exists")
            continue

        # Compare the most recent StatsModel entry with RobotModel
        latest_stats = max(stats_entries, key=lambda x: x.timestamp)
        if robot_model.elo != latest_stats.elo:
            migration_errors.append(
                f"{name} (level {level}): RobotModel.elo={robot_model.elo} != "
                f"latest StatsModel.elo={latest_stats.elo}"
            )

        # Verify robot key format consistency
        expected_key = f"robot-{level}"
        # Create a placeholder StatsDict for key generation
        sd = StatsDict(
            user=None,
            robot_level=level,
            timestamp=datetime.now(UTC),
            games=0,
            elo=0,
            score=0,
            score_against=0,
            wins=0,
            losses=0,
            rank=0,
        )
        stats_dict_key = StatsModel.dict_key(sd)
        if stats_dict_key != expected_key:
            migration_errors.append(
                f"Robot key format inconsistent for {name}: got {stats_dict_key}, expected {expected_key}"
            )

    if migration_errors:
        logging.error(f"Robot stats migration check failed: {len(migration_errors)} issues")
        for error in migration_errors:
            logging.error(f"  - {error}")
        return False

    logging.info("✓ Robot stats migration consistency check passed")
    return True


def check_database_integrity() -> bool:
    """
    Perform basic database integrity checks on the new EloModel entities.
    
    Returns:
        bool: True if integrity checks pass, False otherwise
    """
    logging.info("Checking database integrity...")

    integrity_errors: List[str] = []

    # Check for duplicate EloModel entities (same user + locale)
    seen_keys: Set[str] = set()
    duplicate_count = 0

    for elo_model in iter_q(EloModel.query().filter(EloModel.locale == DEFAULT_LOCALE)):
        key_id = elo_model.key.id()
        if key_id in seen_keys:
            duplicate_count += 1
            if duplicate_count <= 5:  # Only log first 5 duplicates
                integrity_errors.append(f"Duplicate EloModel entity: {key_id}")
        else:
            seen_keys.add(key_id)

    if duplicate_count > 5:
        integrity_errors.append(f"... and {duplicate_count - 5} more duplicates")

    # Check for orphaned EloModel entities (no corresponding UserModel)
    orphaned_count = 0
    for elo_model in iter_q(EloModel.query().filter(EloModel.locale == DEFAULT_LOCALE)):
        parent_key = elo_model.key.parent()
        if parent_key and not parent_key.get():
            orphaned_count += 1
            if orphaned_count <= 5:
                integrity_errors.append(f"Orphaned EloModel: {elo_model.key.id()}")

    if orphaned_count > 5:
        integrity_errors.append(f"... and {orphaned_count - 5} more orphaned entities")

    if integrity_errors:
        logging.error(f"Database integrity check failed: {len(integrity_errors)} issues")
        for error in integrity_errors:
            logging.error(f"  - {error}")
        return False

    logging.info("✓ Database integrity check passed")
    return True


def verify_migration_success() -> bool:
    """
    Main verification function that runs all checks.
    
    Returns:
        bool: True if all verification checks pass, False otherwise
    """
    logging.info("=" * 60)
    logging.info("Starting Elo migration verification...")
    logging.info(f"Default locale: {DEFAULT_LOCALE}")
    logging.info(f"Default Elo rating: {DEFAULT_ELO}")
    logging.info("=" * 60)

    # Define all verification checks
    checks: List[Tuple[str, Callable[[], bool]]] = [
        ("Data Consistency", check_data_consistency),
        ("Entity Counts", check_entity_counts),
        ("Robot Models", check_robot_models),
        ("Robot Stats Migration", check_robot_stats_migration),
        ("Entity Relationships", check_entity_relationships),
        ("Sample Data", spot_check_sample_data),
        ("Database Integrity", check_database_integrity),
    ]

    all_passed = True
    passed_checks = 0
    total_checks = len(checks)

    for check_name, check_func in checks:
        logging.info(f"\n[{passed_checks + 1}/{total_checks}] Running {check_name} check...")
        try:
            if check_func():
                logging.info(f"✅ {check_name} check PASSED")
                passed_checks += 1
            else:
                logging.error(f"❌ {check_name} check FAILED")
                all_passed = False
        except Exception as e:
            logging.error(f"❌ {check_name} check ERROR: {e}")
            logging.exception("Full error details:")
            all_passed = False

    # Final summary
    logging.info("\n" + "=" * 60)
    if all_passed:
        logging.info("🎉 ALL VERIFICATION CHECKS PASSED!")
        logging.info("Migration was successful - safe to switch to EloModel system")
    else:
        logging.error("💥 VERIFICATION FAILED!")
        logging.error(f"Passed: {passed_checks}/{total_checks} checks")
        logging.error("Migration has issues that must be resolved before proceeding")
    logging.info("=" * 60)

    return all_passed


def main() -> int:
    """
    Main entry point for the verification script.
    
    Returns:
        int: 0 if verification passes, 1 if it fails
    """
    setup_logging()

    try:
        # Initialize NDB client (required for Google Cloud NDB)
        client = ndb.Client()

        with client.context():
            success = verify_migration_success()

        return 0 if success else 1

    except Exception as e:
        logging.error(f"Fatal error during verification: {e}")
        logging.exception("Full error details:")
        return 1


if __name__ == "__main__":
    sys.exit(main())

