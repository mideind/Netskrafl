"""

    Challenge diagnostic utility for Netskrafl

    Copyright © 2025 Miðeind ehf.

    READ-ONLY diagnostic. Given an e-mail address, this script:
      1. Finds every UserModel entity with that e-mail (there may be
         duplicates) and shows which one UserModel.fetch_email() would
         return (i.e. the account the user actually logs into).
      2. Lists all challenges *issued by* each of those accounts
         (ChallengeModel is a child of the source/challenging user) and
         resolves the destination user for each, flagging cases where the
         destination account is inactive or itself has duplicate e-mails.
      3. Lists all challenges *received by* each of those accounts.

    NOTE: This reads the *production* Datastore directly. It does not write
    anything. (The local Redis cache is irrelevant for a read-only scan, but
    be aware the local cache may be incoherent with production in general.)

    Usage:
        python utils/diagnose-challenges.py <email>

"""

from __future__ import annotations

from typing import Dict, List, Optional

import sys
import os

os.environ["GRPC_DNS_RESOLVER"] = "native"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from google.cloud import ndb  # noqa: E402
from skrafldb import UserModel, ChallengeModel, BlockModel  # noqa: E402


def fmt_user(u: UserModel) -> str:
    ts = u.timestamp.date().isoformat() if u.timestamp else "????-??-??"
    ll = u.last_login.date().isoformat() if u.last_login else "-"
    return (
        f"id={u.key.id()} nick={u.nickname!r} created={ts} last_login={ll} "
        f"inactive={u.inactive} ready={u.ready} ready_timed={u.ready_timed} "
        f"elo={u.elo} games={u.games} locale={u.locale} account={u.account}"
    )


def resolve_dest(dest_key: Optional[ndb.Key], cache: Dict[str, Optional[UserModel]]) -> str:
    if dest_key is None:
        return "<no destuser>"
    did = dest_key.id()
    if did not in cache:
        cache[did] = UserModel.fetch(did)
    du = cache[did]
    if du is None:
        return f"dest_id={did} <DELETED/MISSING USER>"
    # Does this destination user have duplicate accounts under the same email?
    dupes = ""
    if du.email:
        same = UserModel.query(UserModel.email == du.email.lower()).fetch()
        active = [x for x in same if not x.inactive]
        if len(same) > 1:
            picked = UserModel.fetch_email(du.email)
            picked_id = picked.key.id() if picked else None
            dupes = (
                f"  [DUPLICATE EMAIL: {len(same)} accts ({len(active)} active); "
                f"login resolves to id={picked_id}; "
                f"this challenge targets id={did} -> "
                f"{'SAME' if picked_id == did else 'DIFFERENT!'}]"
            )
    flag = " <INACTIVE>" if du.inactive else ""
    return (
        f"dest_id={did} nick={du.nickname!r} email={du.email!r}"
        f" ready={du.ready} ready_timed={du.ready_timed}{flag}{dupes}"
    )


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python utils/diagnose-challenges.py <email>")
        return 1
    email = sys.argv[1].lower().strip()

    client = ndb.Client()
    with client.context():
        all_accts = UserModel.query(UserModel.email == email).fetch()
        print(f"=== Accounts with email {email!r}: {len(all_accts)} found ===")
        if not all_accts:
            print("No accounts found.")
            return 0
        picked = UserModel.fetch_email(email)
        picked_id = picked.key.id() if picked else None
        for u in all_accts:
            marker = "  <-- LOGIN RESOLVES HERE" if u.key.id() == picked_id else ""
            print("  " + fmt_user(u) + marker)
        print()

        dest_cache: Dict[str, Optional[UserModel]] = {}
        for u in all_accts:
            uid = u.key.id()

            # Who has blocked this user? (their challenges are hidden from blockers)
            blocked_by = list(BlockModel.list_blocked_by(uid))
            print(f"=== Users who have BLOCKED id={uid}: {len(blocked_by)} ===")
            for bid in blocked_by:
                bu = UserModel.fetch(bid)
                print(f"    blocker id={bid} nick={bu.nickname!r}" if bu else f"    blocker id={bid} <missing>")
            print()

            print(f"=== Challenges ISSUED BY id={uid} (nick={u.nickname!r}) ===")
            issued = ChallengeModel.query(ancestor=u.key).fetch()
            if not issued:
                print("  (none)")
            for cm in sorted(issued, key=lambda c: c.timestamp or 0):
                ts = cm.timestamp.isoformat() if cm.timestamp else "?"
                prefs = cm.prefs or {}
                print(f"  [{ts}] {resolve_dest(cm.destuser, dest_cache)}")
                # Would the recipient actually SEE this challenge?
                if cm.destuser is not None:
                    did = cm.destuser.id()
                    CAP = 20  # display cap (max_len) for received challenges
                    recv_count = ChallengeModel.query(
                        ChallengeModel.destuser == cm.destuser
                    ).count()
                    # Received challenges are shown newest-first, capped at CAP.
                    # This challenge is visible only if it is among the newest
                    # CAP, i.e. fewer than CAP newer challenges sit ahead of it.
                    newer_count = (
                        ChallengeModel.query(ChallengeModel.destuser == cm.destuser)
                        .filter(ChallengeModel.timestamp > cm.timestamp)
                        .count()
                    )
                    they_block = BlockModel.is_blocking(did, uid)
                    visible = (not they_block) and newer_count < CAP
                    note = []
                    if they_block:
                        note.append("RECIPIENT HAS BLOCKED SENDER")
                    if newer_count >= CAP:
                        note.append(
                            f"{newer_count} newer challenges ahead of this one "
                            f"(>{CAP} cap => hidden)"
                        )
                    print(
                        f"        recipient_received_total={recv_count} "
                        f"newer_than_this={newer_count} "
                        f"recipient_blocks_sender={they_block} "
                        f"=> VISIBLE_TO_RECIPIENT={visible}"
                        + (f"  [{'; '.join(note)}]" if note else "")
                    )
                print(f"        prefs={dict(prefs)}")
            print()

            print(f"=== Challenges RECEIVED BY id={uid} (nick={u.nickname!r}) ===")
            received = ChallengeModel.query(ChallengeModel.destuser == u.key).fetch()
            if not received:
                print("  (none)")
            for cm in sorted(received, key=lambda c: c.timestamp or 0):
                ts = cm.timestamp.isoformat() if cm.timestamp else "?"
                src_id = cm.key.parent().id() if cm.key.parent() else "?"
                src = UserModel.fetch(src_id) if src_id != "?" else None
                src_nick = src.nickname if src else "?"
                print(f"  [{ts}] from id={src_id} nick={src_nick!r}")
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())

