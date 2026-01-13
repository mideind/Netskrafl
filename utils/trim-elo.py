"""

    trim-elo.py

    Copyright © 2025 Miðeind ehf.
    Author: Vilhjálmur Þorsteinsson

    This file contains three utility functions to trim player Elo scores,
    especially those of inactive players.

    The first function, trim_elo(), loops over the UserModel entities in
    the datastore and creates a .CSV file with the user identifier, current
    Elo score, and trimmed Elo score for each user with Elo score > 1200.
    The trimmed score is calculated as (current - 1200) * (1 - FACTOR) + 1200,
    where FACTOR is a constant that can be adjusted.

    A second function, update_elo(), actually perform the Elo updates
    that are described in the .CSV file, by modifying UserModel entities.

    A third function, update_stats(), updates the newest StatsModel entities
    corresponding to the users whose Elo scores have been modified.

    After running the second and/or third functions, it is advisable to
    clear the Redis cache for the App Engine project. There is
    an API endpoint, /cacheflush, that can be used for this purpose. It
    can be invoked e.g. via a Cloud Scheduler job.

    Before running the scripts herein, set the PROJECT_ID and
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

from skrafldb import Client, Context, UserModel, StatsModel, iter_q  # noqa: E402

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


def update_stats(*, show_progress: bool = False) -> None:
    """Read the OUTPUT_FILE and update the StatsModel entities
    corresponding to users that were modified by trim_elo()"""
    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        count = 0
        batch: List[StatsModel] = []
        for line in f:
            line = line.strip()
            if not line:
                continue
            user_id, _, elo_str, new_elo_str, human_elo_str, new_human_elo_str, manual_elo_str, new_manual_elo_str = (
                line.split(",")
            )
            # Trim the quotes from the user_id
            user_id = user_id[1:-1]
            sm = StatsModel.newest_for_user(user_id)
            if not sm:
                # Should not happen
                if show_progress:
                    print(f"StatsModel not found for user {user_id}")
                continue
            elo = int(elo_str)
            human_elo = int(human_elo_str)
            manual_elo = int(manual_elo_str)
            new_elo = int(new_elo_str)
            new_human_elo = int(new_human_elo_str)
            new_manual_elo = int(new_manual_elo_str)
            # The following delta adjustment is only necessary if the
            # StatsModel entity has been updated (by way of players finishing games)
            # since the OUTPUT_FILE was created. Ideally, these functions should be
            # run in quick succession.
            delta_elo = sm.elo - elo
            delta_human_elo = sm.human_elo - human_elo
            delta_manual_elo = sm.manual_elo - manual_elo
            # Debug: print out the change that would happen
            # Print previous Elo stats, the delta, and the final Elo stats
            print(
                f"{user_id}:"
                f" {sm.elo} -> {new_elo} ({delta_elo:+}),"
                f" {sm.human_elo} -> {new_human_elo} ({delta_human_elo:+}),"
                f" {sm.manual_elo} -> {new_manual_elo} ({delta_manual_elo:+})"
            )
            sm.elo = new_elo + delta_elo
            sm.human_elo = new_human_elo + delta_human_elo
            sm.manual_elo = new_manual_elo + delta_manual_elo
            batch.append(sm)
            if len(batch) >= BATCH_SIZE:
                StatsModel.put_multi(batch)
                batch = []
            count += 1
            if show_progress:
                if count % 100 == 0:
                    print(f"Updated {count} users", end="\r")
        if batch:
            StatsModel.put_multi(batch)
            batch = []
        if show_progress:
            print(f"Updated {count} users")


def check_stats() -> None:
    """Read the OUTPUT_FILE and compare the Elo scores in the
    associated UserModel entities with the ones in the StatsModel
    entities (i.e. the most recent entity for each user)"""
    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        count = 0
        discrepancies = 0
        add_backs = 0
        for line in f:
            line = line.strip()
            if not line:
                continue
            user_id, old_login_str, elo_str, new_elo_str, human_elo_str, new_human_elo_str, manual_elo_str, new_manual_elo_str = (
                line.split(",")
            )
            # Trim the quotes from the user_id
            user_id = user_id[1:-1]
            old_login = old_login_str == "\"yes\""
            # Obtain the UserModel entity
            um = UserModel.get_by_id(user_id)
            if not um:
                print(f"UserModel not found for user {user_id}")
                continue
            # Obtain the StatsModel entity
            sm = StatsModel.newest_for_user(user_id)
            if not sm:
                print(f"StatsModel not found for user {user_id}")
                continue
            # Find out whether the StatsModel entry is newer than 365 days,
            # in which case the old_login flag was wrong
            old_login_sm = (NOW - sm.timestamp).days >= 365
            if old_login and not old_login_sm:
                # We probably lowered the Elo score too much, i.e. by
                # 20% instead of 10%, due to the last_login field in the
                # UserModel being wrong (for some obscure reason):
                # Add back the extra 10% that were subtracted
                elo_diff = (int(elo_str) - int(new_elo_str)) // 2
                human_elo_diff = (int(human_elo_str) - int(new_human_elo_str)) // 2
                manual_elo_diff = (int(manual_elo_str) - int(new_manual_elo_str)) // 2
                sm.elo += elo_diff
                sm.human_elo += human_elo_diff
                sm.manual_elo += manual_elo_diff
                print(
                    f"#{add_backs+1} "
                    f"User {user_id}:"
                    f" Added back {elo_diff}, {human_elo_diff}, {manual_elo_diff}"
                )
                add_backs += 1
                sm.put()

            # Compare the StatsModel scores with the UserModel
            # score and report users with discrepancies
            if (
                sm.elo != um.elo
                or sm.human_elo != um.human_elo
                or sm.manual_elo != um.manual_elo
            ):
                print(
                    f"#{discrepancies+1} "
                    f"User {user_id}:"
                    f" UserModel: {um.elo}, {um.human_elo}, {um.manual_elo},"
                    f" StatsModel: {sm.elo}, {sm.human_elo}, {sm.manual_elo}"
                )
                discrepancies += 1
                # Correct the discrepancy
                um.elo = sm.elo
                um.human_elo = sm.human_elo
                um.manual_elo = sm.manual_elo
                um.put()
            count += 1
        print(
            f"Checked {count} users, "
            f"discrepancies were {discrepancies}, "
            f"Elo points added back for {add_backs} users"
        )


if __name__ == "__main__":
    with Client.get_context():
        Context.disable_cache()
        Context.disable_global_cache()
        # The trim_elo() function is nondestructive
        #print(f"Reading user data; writing output to {OUTPUT_FILE}")
        #trim_elo(show_progress=True)
        # The update_elo() and update_stats() functions are destructive,
        # so be careful when invoking them
        #print(f"Updating user Elo scores")
        #update_elo(show_progress=True)
        #print(f"Updating user stats")
        #update_stats(show_progress=True)
        #print(f"Checking user stats")
        #check_stats()
        print("Processing complete")
