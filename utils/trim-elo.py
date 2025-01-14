"""

    trim-elo.py

    Copyright © 2025 Miðeind ehf.
    Author: Vilhjálmur Þorsteinsson

    This script loops over the UserModel entities in the datastore
    and creates a .CSV file with the user identifier, current Elo
    score, and trimmed Elo score for each user with Elo score > 1200.
    The trimmed score is calculated as (current - 1200) * FACTOR + 1200,
    where FACTOR is a constant that can be adjusted.
    A separate loop will then actually perform the Elo updates
    that are described in the .CSV file.

    Before running this script, set the PROJECT_ID and
    GOOGLE_APPLICATION_CREDENTIALS environment variables to
    appropriate values.

"""

from __future__ import annotations

from typing import List, Tuple

import os
import sys
from datetime import UTC, datetime

base_path = os.path.dirname(__file__)  # Assumed to be in the /utils directory
# Add the ../src directory to the Python path
sys.path.append(os.path.join(base_path, "../src"))

from skrafldb import Client, Context, UserModel, iter_q

UserTuple = Tuple[str, int, int, int]

# Cut excess Elo by 10%, and double that if user hasn't logged in for a year
TRIM_FACTOR = 0.1
OUTPUT_FILE = "elo-trim.csv"
BATCH_SIZE = 500

# Obtain the current UTC datetime
NOW = datetime.now(UTC)


def trim(elo: int, old_login: bool) -> int:
    """Trim Elo scores above 1200 by the TRIM_FACTOR. However, if the
    user hasn't logged in for a year, use a double TRIM_FACTOR."""
    if elo <= 1200:
        # No trimming
        return elo
    trim_factor = TRIM_FACTOR * 2 if old_login else TRIM_FACTOR
    return 1200 + int((elo - 1200) * (1 - trim_factor))


def trim_elo(*, show_progress: bool = False) -> None:
    """Read all UserModel entities and write trimmed Elo scores
    for modified entities to the OUTPUT_FILE"""
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        # Loop over all UserModel entities
        query = UserModel.query()
        count = 0
        written = 0
        for um in iter_q(query, chunk_size=250):
            count += 1
            if show_progress:
                # Show a count update every 100 users
                if count % 100 == 0:
                    print(f"Processed {count} users", end="\r")
            # If none of the three Elo scores are above 1200, skip this user
            elo, human_elo, manual_elo = (
                um.elo or 1200,
                um.human_elo or 1200,
                um.manual_elo or 1200,
            )
            if elo <= 1200 and human_elo <= 1200 and manual_elo <= 1200:
                # No change to this entity
                continue
            user_id = um.key.id()
            last_login = um.last_login
            old_login = last_login is None or (NOW - last_login).days >= 365
            new_elo = trim(elo, old_login)
            new_human_elo = trim(human_elo, old_login)
            new_manual_elo = trim(manual_elo, old_login)
            f.write(
                f'"{user_id}","{"yes" if old_login else "no"}",{elo},{new_elo},{human_elo},{new_human_elo},{manual_elo},{new_manual_elo}\n'
            )
            written += 1
        if show_progress:
            print(f"Processed {count} users and wrote {written} to {OUTPUT_FILE}")


def update_batch(batch: List[UserTuple], show_progress: bool = False) -> None:
    """Update the Elo scores of the users in the batch."""
    user_ids = [u[0] for u in batch]
    um_list = UserModel.fetch_multi(user_ids)
    um_output: List[UserModel] = []
    for u, um in zip(batch, um_list):
        if um is None:
            # Should not happen
            if show_progress:
                print(f"User {u[0]} not found")
            continue
        new_elo, new_human_elo, new_manual_elo = u[1], u[2], u[3]
        if show_progress:
            print(
                f"User {u[0]}: {um.elo} -> {new_elo}, {um.human_elo} -> {new_human_elo}, {um.manual_elo} -> {new_manual_elo}"
            )
        um.elo = new_elo
        um.human_elo = new_human_elo
        um.manual_elo = new_manual_elo
        um_output.append(um)
    # Output the updated entities
    UserModel.put_multi(um_output)


def update_elo(*, show_progress: bool = False) -> None:
    """Read the OUTPUT_FILE and update the Elo scores
    of the UserModel entities referred to therein."""
    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        count = 0
        # We do this by batching users, obtaining their information via
        # UserModel.fetch_multi(). We then update each batch and write
        # the results via ndb.put_multi().
        batch: List[UserTuple] = []
        for line in f:
            line = line.strip()
            if not line:
                continue
            user_id, _, _, new_elo_str, _, new_human_elo_str, _, new_manual_elo_str = (
                line.split(",")
            )
            # Trim the quotes from the user_id
            user_id = user_id[1:-1]
            u: UserTuple = (
                user_id,
                int(new_elo_str),
                int(new_human_elo_str),
                int(new_manual_elo_str),
            )
            batch.append(u)
            if len(batch) >= BATCH_SIZE:
                update_batch(batch, show_progress)
                batch = []
            count += 1
            if show_progress:
                if count % 100 == 0:
                    print(f"Updated {count} users", end="\r")
        if batch:
            update_batch(batch, show_progress)
            batch = []
        if show_progress:
            print(f"Updated {count} users")


if __name__ == "__main__":
    with Client.get_context():
        Context.disable_cache()
        Context.disable_global_cache()
        print(f"Reading user data; writing output to {OUTPUT_FILE}")
        trim_elo(show_progress=True)
        print(f"Updating user Elo scores")
        update_elo(show_progress=True)
        print(f"Processing complete")
