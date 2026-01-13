#!/usr/bin/env python3
"""
Migration script to fix malformed UserModel keys containing 'google-oauth2|'

This script:
1. Finds UserModel entities with keys in range ["malstadur:google-oauth2", "malstadur:h")
2. Creates new entities with corrected keys (google-oauth2| removed)
3. Copies all properties, especially preserving email
4. Deletes old malformed entities

Usage:
    python migrate_malformed_users.py
"""

import logging
import sys
import os
from typing import Any, Iterable, cast
from google.cloud import ndb

base_path = os.path.dirname(__file__)  # Assumed to be in the /utils directory

# Add the ../src directory to the Python path
sys.path.append(os.path.join(base_path, "../src"))

from skrafldb import UserModel  # noqa: E402

# Configure logging - force reconfiguration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout,
    force=True,  # Force reconfiguration even if logging was already configured
)

# Also create a logger that writes directly to stdout as backup
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

def migrate_malformed_users(dry_run: bool = True) -> int:
    """Migrate users with malformed account keys in the specified range"""

    client = ndb.Client()

    with client.context():
        logging.info(f"Starting {'dry run' if dry_run else 'migration'} of malformed user accounts...")

        # Query for users in the specific key range
        start_key = ndb.Key(UserModel, "malstadur:google-oauth2")
        end_key = ndb.Key(UserModel, "malstadur:h")

        # Fetch all users in this range
        query = UserModel.query()
        query = query.filter(UserModel._key >= start_key)  # type: ignore
        query = query.filter(UserModel._key < end_key)  # type: ignore

        malformed_users = list(query.fetch())

        if not malformed_users:
            logging.info("No users found in range [malstadur:google-oauth2, malstadur:h)")
            return 0

        logging.info(f"Found {len(malformed_users)} user(s) to migrate:")
        for user in malformed_users:
            logging.info(f"  - {user.key.id()}")

        # Confirm before proceeding
        if len(malformed_users) > 5:
            response = input(f"\nFound {len(malformed_users)} users. This seems like more than expected. Continue? [y/N]: ")
            if response.lower() != 'y':
                logging.info("Migration cancelled by user")
                return 0

        migrated_count = 0
        failed_count = 0

        for old_user in malformed_users:
            old_key = old_user.key
            old_account = old_key.id()

            # Remove 'google-oauth2|' from the account string
            if "google-oauth2|" not in old_account:
                logging.warning(f"Skipping {old_account} - does not contain 'google-oauth2|'")
                continue

            new_account = old_account.replace("google-oauth2|", "")

            logging.info(f"\nMigrating: {old_account} → {new_account}")

            # Create new entity with corrected key
            new_key = ndb.Key(UserModel, new_account)

            # Check if new key already exists
            if new_key.get() is not None:  # type: ignore
                logging.error(f"  ERROR: New key already exists: {new_account}")
                logging.error("  Skipping migration to avoid overwriting existing user")
                failed_count += 1
                continue

            # Create new entity and copy all properties
            new_user = UserModel(key=new_key)
            old_properties = cast(Iterable[str], iter(cast(Any, old_user)._properties))

            # Copy all properties from old to new
            for prop_name in old_properties:
                value = getattr(old_user, prop_name, None)
                if value is not None:
                    setattr(new_user, prop_name, value)
                    logging.info(f"  Copied {prop_name}: {value}")

            # Ensure account property is set to new value
            if hasattr(new_user, 'account'):
                new_user.account = new_account
                logging.info(f"  Set account property: {new_account}")

            # Verify email is preserved
            email = getattr(old_user, 'email', None)
            if email and new_user.email == email:
                logging.info(f"  Email preserved: {email}")
            else:
                logging.warning("  WARNING: No email found on user!")

            # Use transaction to ensure atomicity
            @ndb.transactional()  # type: ignore
            def migrate_user_atomic():
                # Put new entity
                new_user.put()
                logging.info(f"  ✓ Created new entity: {new_account}")

                # Delete old entity
                old_key.delete()
                logging.info(f"  ✓ Deleted old entity: {old_account}")

            try:
                if not dry_run:
                    migrate_user_atomic()
                migrated_count += 1
                logging.info("  ✓ Migration complete")
            except Exception as e:
                logging.error(f"  ✗ Failed to migrate {old_account}: {e}")
                failed_count += 1

        logging.info(f"\n{'='*60}")
        logging.info(f"{'Dry run' if dry_run else 'Migration'} complete:")
        logging.info(f"  Successfully migrated: {migrated_count}")
        logging.info(f"  Failed: {failed_count}")
        logging.info(f"{'='*60}")

        return migrated_count


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Migrate malformed user accounts')
    parser.add_argument('--execute', action='store_true', help='Execute migration (default is dry-run)')
    args = parser.parse_args()

    try:
        count = migrate_malformed_users(dry_run=not args.execute)
        sys.exit(0 if count >= 0 else 1)
    except Exception as e:
        logging.error(f"Migration failed with error: {e}", exc_info=True)
        sys.exit(1)
