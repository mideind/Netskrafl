"""

    Remove identical pending challenges from a PostgreSQL database

    Copyright © 2026 Miðeind ehf.

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    A user can have one challenge of each type pending to another user
    (see challenge_type() in src/db/protocols.py). The server has enforced
    that since November 2026. This utility removes what the databases held
    before then: of the challenges that one user has pending to another and
    that are for the same game, it keeps the newest and deletes the others.

    What counts as the same game. Two challenges from the same issuer to
    the same recipient, with the same type (duration, word check, fair
    play, locale) and the same tile bag. The tile bag is not part of the
    type, but it decides which game is created, so challenges that differ
    in it are both kept. With --implicit-locale, a challenge without a
    locale counts as one for that locale (Netskrafl's older challenges
    have none, and were always for Icelandic).

    What it does and does not touch. It deletes rows of the table
    `challenges`, by primary key, and nothing else. No other table refers
    to that table. Nobody is notified. A client that still shows a deleted
    challenge gets an ordinary refusal if it acts on it, until it has read
    its list again. The server keeps no cache of challenges, so no cache
    needs to be flushed afterwards.

    How it is run. Without --apply it is a dry run, on a session that the
    database server itself keeps read-only: it reports what would be
    deleted, as counts, without any user ids. With --apply:

      - the rows are read, and the rows of every affected group are locked,
        in one transaction with a fixed snapshot (REPEATABLE READ). If the
        server changes any of those rows in the meantime, the transaction
        fails and nothing is deleted: run it again;
      - the number of rows to delete must be within --tolerance of
        --expect (the number that the dry run reported), and not more than
        --max-share percent of the table;
      - the rows to delete are written to the --backup file (which must
        not exist; it is created with mode 600) before they are deleted;
      - after the delete and before the commit, it is checked that exactly
        those rows are gone, that every group still has its newest
        challenge, and that no identical challenges are left. Otherwise
        the transaction is rolled back.

    --restore puts the rows of a backup file back (those that are not in
    the table), also as a dry run unless --apply is given.

    Usage, from the repository root. DATABASE_URL is the database to work
    on, and --database its name, which must match (a guard against a
    wrong URL). Neither is kept in this repository.

        DATABASE_URL=... venv/bin/python utils/dedupe_challenges.py
            --database NAME [--implicit-locale LOCALE]
        DATABASE_URL=... venv/bin/python utils/dedupe_challenges.py
            --database NAME [--implicit-locale LOCALE]
            --apply --expect N --backup FILE [--tolerance N] [--max-share PCT]
        DATABASE_URL=... venv/bin/python utils/dedupe_challenges.py
            --database NAME --restore FILE [--apply]

    The backup file holds user ids: keep it out of the repository.

"""

from __future__ import annotations

from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    NamedTuple,
    Optional,
    Sequence,
    Tuple,
)

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import psycopg2
import psycopg2.errors
import psycopg2.extensions

# Make the modules in src/ importable
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from db.protocols import ChallengeType, challenge_type  # noqa: E402

# The preferences that a challenge is known to carry. A challenge with any
# other preference stops the run: it would have to be decided first whether
# that preference makes two challenges different.
KNOWN_PREFS = frozenset(("duration", "manual", "fairplay", "locale", "newbag"))

# Do not wait long for a row that the server has locked
LOCK_TIMEOUT_MS = 10_000
STATEMENT_TIMEOUT_MS = 120_000

# What makes two challenges of one issuer to one recipient the same:
# (issuer, recipient, type, new tile bag)
GroupKey = Tuple[str, str, ChallengeType, bool]

Connection = psycopg2.extensions.connection


class Row(NamedTuple):
    """A row of the challenges table"""

    id: str
    src: str
    dest: str
    prefs: Optional[Dict[str, Any]]
    # The preferences as the database gives them in text form, for the backup
    prefs_text: Optional[str]
    timestamp: datetime


class DedupeError(Exception):
    """The run cannot go on; nothing has been changed"""


@dataclass
class Plan:
    """What a run would do with the rows of the table"""

    # Number of rows in the table
    total: int = 0
    # The key of every group, with the id of its newest challenge
    newest: Dict[GroupKey, str] = field(default_factory=lambda: dict())
    # Number of groups with more than one challenge
    dup_groups: int = 0
    # The rows to delete, each with the id of the challenge kept in its place
    delete: List[Tuple[Row, str]] = field(default_factory=lambda: list())
    # Number of challenges whose locale is the implicit one
    implicit: int = 0
    # Number of (issuer, recipient, type) with challenges for both tile bags
    both_bags: int = 0

    @property
    def delete_ids(self) -> List[str]:
        return [row.id for row, _ in self.delete]

    @property
    def keep_ids(self) -> List[str]:
        """The ids of the challenges kept in the groups that lose rows"""
        return sorted({kept for _, kept in self.delete})


def group_key(row: Row, implicit_locale: str) -> GroupKey:
    """The group that a challenge belongs to"""
    prefs: Mapping[str, Any] = row.prefs or {}
    unknown = set(prefs) - KNOWN_PREFS
    if unknown:
        raise DedupeError(
            f"a challenge has preferences that this utility does not know: "
            f"{', '.join(sorted(unknown))}"
        )
    duration, manual, fairplay, locale = challenge_type(prefs)
    # As Game.new_bag() reads it: absent means the old bag
    newbag = bool(prefs.get("newbag", False))
    return (
        row.src,
        row.dest,
        (duration, manual, fairplay, locale or implicit_locale),
        newbag,
    )


def make_plan(rows: Iterable[Row], implicit_locale: str = "") -> Plan:
    """Decide what to keep and what to delete: in each group, the newest
    challenge is kept (of two with the same timestamp, the one with the
    higher id) and the others are deleted."""
    plan = Plan()
    groups: Dict[GroupKey, List[Row]] = {}
    for row in rows:
        plan.total += 1
        key = group_key(row, implicit_locale)
        groups.setdefault(key, []).append(row)
        if implicit_locale and not challenge_type(row.prefs)[3]:
            plan.implicit += 1
    bags: Counter[Tuple[str, str, ChallengeType]] = Counter()
    for key in sorted(groups):
        members = sorted(groups[key], key=lambda r: (r.timestamp, r.id))
        kept = members[-1]
        plan.newest[key] = kept.id
        bags[key[:3]] += 1
        if len(members) > 1:
            plan.dup_groups += 1
            plan.delete.extend((row, kept.id) for row in members[:-1])
    plan.both_bags = sum(1 for n in bags.values() if n > 1)
    return plan


def connect(url: str, *, read_only: bool) -> Connection:
    """Connect to the database, for one transaction with a fixed snapshot.
    A read-only session is read-only on the server: it refuses any write."""
    # Accept an SQLAlchemy-style URL as well
    url = url.replace("postgresql+psycopg2://", "postgresql://", 1)
    options = f"-c statement_timeout={STATEMENT_TIMEOUT_MS} -c lock_timeout={LOCK_TIMEOUT_MS}"
    if read_only:
        options += " -c default_transaction_read_only=on"
    conn: Connection = psycopg2.connect(
        url, options=options, application_name="dedupe_challenges"
    )
    conn.set_session(isolation_level="REPEATABLE READ", readonly=read_only)
    return conn


def check_database(conn: Connection, database: str) -> datetime:
    """Verify that this is the database that was asked for. Returns the
    time of the transaction, i.e. of the snapshot."""
    with conn.cursor() as cur:
        cur.execute("select current_database(), now()")
        row = cur.fetchone()
        assert row is not None
        name: str = row[0]
        now: datetime = row[1]
    if name != database:
        raise DedupeError(
            f"the database is '{name}', not '{database}': is DATABASE_URL right?"
        )
    return now


def read_rows(conn: Connection) -> List[Row]:
    """All rows of the challenges table"""
    with conn.cursor() as cur:
        cur.execute(
            "select id::text, src_user_id, dest_user_id, prefs, prefs::text, "
            "timestamp from challenges"
        )
        return [Row(*r) for r in cur.fetchall()]


def age_buckets(ages: Sequence[timedelta]) -> str:
    """A summary of ages, as counts"""
    edges: List[Tuple[str, timedelta]] = [
        ("< 1 day", timedelta(days=1)),
        ("1-30 days", timedelta(days=30)),
        ("30-365 days", timedelta(days=365)),
        ("1-3 years", timedelta(days=3 * 365)),
    ]
    last = "> 3 years"
    counts: Counter[str] = Counter()
    for age in ages:
        counts[next((name for name, edge in edges if age < edge), last)] += 1
    return ", ".join(f"{name}: {counts[name]}" for name in [n for n, _ in edges] + [last])


def report(plan: Plan, now: datetime, implicit_locale: str) -> None:
    """Describe a plan, in counts only"""
    n = len(plan.delete)
    share = 100.0 * n / plan.total if plan.total else 0.0
    print(f"Pending challenges: {plan.total}")
    print(f"Groups (issuer, recipient, type, tile bag): {len(plan.newest)}")
    print(f"Groups with more than one challenge: {plan.dup_groups}")
    print(f"Challenges to delete: {n} ({share:.1f}% of the table)")
    print(f"Challenges left afterwards: {plan.total - n}")
    if implicit_locale:
        print(
            f"Challenges without a locale, counted as {implicit_locale}: "
            f"{plan.implicit}"
        )
    print(
        "Issuer, recipient and type with challenges for both tile bags "
        f"(both kept): {plan.both_bags}"
    )
    if n:
        print(
            "Age of the challenges to delete: "
            f"{age_buckets([now - row.timestamp for row, _ in plan.delete])}"
        )
        issuers = Counter(row.src for row, _ in plan.delete)
        recipients = {row.dest for row, _ in plan.delete}
        print(
            f"Issuers affected: {len(issuers)}, recipients: {len(recipients)}; "
            f"most deleted for one issuer: {max(issuers.values())}"
        )


def write_backup(
    path: str, plan: Plan, database: str, now: datetime, implicit_locale: str
) -> None:
    """Write the rows to delete to a new file, readable by its owner only,
    and make sure that it is on disk"""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        header = {
            "database": database,
            "snapshot": now.isoformat(),
            "implicit_locale": implicit_locale,
            "rows": len(plan.delete),
        }
        f.write(json.dumps(header) + "\n")
        for row, kept in plan.delete:
            f.write(
                json.dumps(
                    {
                        "id": row.id,
                        "src_user_id": row.src,
                        "dest_user_id": row.dest,
                        "prefs": row.prefs_text,
                        "timestamp": row.timestamp.isoformat(),
                        "kept": kept,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        f.flush()
        os.fsync(f.fileno())


def read_backup(path: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """The header and the rows of a backup file"""
    with open(path, encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]
    if not lines or "database" not in lines[0]:
        raise DedupeError(f"{path} is not a backup file of this utility")
    header: Dict[str, Any] = lines[0]
    rows: List[Dict[str, Any]] = lines[1:]
    if header.get("rows") != len(rows):
        raise DedupeError(
            f"{path} is incomplete: {len(rows)} rows, {header.get('rows')} expected"
        )
    return header, rows


def dry_run(url: str, database: str, implicit_locale: str = "") -> Plan:
    """Report what a run would delete. Changes nothing."""
    conn = connect(url, read_only=True)
    try:
        now = check_database(conn, database)
        print(f"Database {database}, snapshot at {now:%Y-%m-%d %H:%M:%S %Z}")
        plan = make_plan(read_rows(conn), implicit_locale)
        report(plan, now, implicit_locale)
        return plan
    finally:
        conn.rollback()
        conn.close()


def apply(
    url: str,
    database: str,
    *,
    expect: int,
    backup: str,
    implicit_locale: str = "",
    tolerance: int = 0,
    max_share: float = 40.0,
) -> Plan:
    """Delete the identical challenges, in one transaction. Raises
    DedupeError, with nothing changed, if any check fails."""
    if os.path.exists(backup):
        raise DedupeError(f"the backup file {backup} exists already")
    conn = connect(url, read_only=False)
    written = False
    try:
        now = check_database(conn, database)
        print(f"Database {database}, snapshot at {now:%Y-%m-%d %H:%M:%S %Z}")
        before = read_rows(conn)
        plan = make_plan(before, implicit_locale)
        report(plan, now, implicit_locale)
        n = len(plan.delete)
        if abs(n - expect) > tolerance:
            raise DedupeError(
                f"{n} challenges to delete, but {expect} expected "
                f"(tolerance {tolerance}): do a dry run again"
            )
        if n > plan.total * max_share / 100.0:
            raise DedupeError(
                f"{n} challenges to delete is more than {max_share:g}% of the table"
            )
        if n == 0:
            print("Nothing to delete")
            return plan
        delete_ids = plan.delete_ids
        keep_ids = plan.keep_ids
        with conn.cursor() as cur:
            # Lock the rows of every affected group: those to delete and
            # the one that is kept. If the server has changed or deleted
            # any of them since the snapshot, this fails (a serialization
            # failure), and so does the whole run. While the locks are
            # held, the server cannot delete the kept challenge of a group.
            cur.execute(
                "select id::text from challenges where id = any(%s::uuid[]) "
                "order by id for update",
                (delete_ids + keep_ids,),
            )
            locked = {r[0] for r in cur.fetchall()}
            if locked != set(delete_ids) | set(keep_ids):
                raise DedupeError("could not lock every row of the affected groups")
            # The rows are safe on disk before they are deleted
            write_backup(backup, plan, database, now, implicit_locale)
            written = True
            cur.execute(
                "delete from challenges where id = any(%s::uuid[])", (delete_ids,)
            )
            if cur.rowcount != n:
                raise DedupeError(f"{cur.rowcount} rows deleted, {n} expected")
        # Verify the result before it is committed
        after = read_rows(conn)
        gone = {r.id for r in before} - {r.id for r in after}
        if gone != set(delete_ids) or len(after) != len(before) - n:
            raise DedupeError("the rows that are gone are not those to delete")
        check = make_plan(after, implicit_locale)
        if check.delete:
            raise DedupeError("identical challenges are left after the delete")
        if check.newest != plan.newest:
            raise DedupeError("a group has lost its newest challenge")
        conn.commit()
        print(f"Deleted {n} challenges; {len(after)} are left")
        print(f"The deleted rows are in {backup}")
        return plan
    except BaseException as e:
        conn.rollback()
        if written:
            # The file describes a delete that did not happen
            os.replace(backup, backup + ".not-applied")
        if isinstance(e, psycopg2.errors.SerializationFailure):
            raise DedupeError(
                "the server changed a challenge of an affected group in the "
                "meantime; nothing was deleted, run it again"
            ) from e
        if isinstance(e, psycopg2.errors.LockNotAvailable):
            raise DedupeError(
                "a challenge of an affected group stayed locked by the server; "
                "nothing was deleted, run it again"
            ) from e
        raise
    finally:
        conn.close()


def restore(url: str, database: str, path: str, *, do_apply: bool) -> int:
    """Put the rows of a backup file back into the table, except those
    that are there. Returns the number of rows that were (or would be)
    inserted."""
    header, rows = read_backup(path)
    if header["database"] != database:
        raise DedupeError(
            f"{path} is from the database '{header['database']}', not '{database}'"
        )
    conn = connect(url, read_only=not do_apply)
    try:
        check_database(conn, database)
        ids = [r["id"] for r in rows]
        with conn.cursor() as cur:
            cur.execute(
                "select id::text from challenges where id = any(%s::uuid[])", (ids,)
            )
            present = {r[0] for r in cur.fetchall()}
            missing = [r for r in rows if r["id"] not in present]
            print(
                f"{path}: {len(rows)} rows, of which {len(present)} are in the "
                f"table and {len(missing)} are not"
            )
            if not do_apply:
                print("Dry run: nothing was inserted")
                return len(missing)
            for r in missing:
                cur.execute(
                    "insert into challenges "
                    "(id, src_user_id, dest_user_id, prefs, timestamp) "
                    "values (%s::uuid, %s, %s, %s::jsonb, %s::timestamptz)",
                    (
                        r["id"],
                        r["src_user_id"],
                        r["dest_user_id"],
                        r["prefs"],
                        r["timestamp"],
                    ),
                )
            cur.execute(
                "select count(*) from challenges where id = any(%s::uuid[])", (ids,)
            )
            count = cur.fetchone()
            if count is None or count[0] != len(rows):
                raise DedupeError("not every row of the file is in the table")
        conn.commit()
        print(f"Inserted {len(missing)} challenges")
        return len(missing)
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove identical pending challenges from a PostgreSQL database"
    )
    parser.add_argument(
        "--database", required=True, help="name of the database that DATABASE_URL is for"
    )
    parser.add_argument(
        "--implicit-locale",
        default="",
        metavar="LOCALE",
        help="the locale of a challenge that has none (is_IS for Netskrafl)",
    )
    parser.add_argument(
        "--apply", action="store_true", help="make the change (the default is a dry run)"
    )
    parser.add_argument(
        "--expect",
        type=int,
        metavar="N",
        help="with --apply: the number of challenges to delete, from the dry run",
    )
    parser.add_argument(
        "--tolerance",
        type=int,
        default=0,
        metavar="N",
        help="with --apply: how far the number may be from --expect (default 0)",
    )
    parser.add_argument(
        "--max-share",
        type=float,
        default=40.0,
        metavar="PCT",
        help="with --apply: refuse to delete more than this share of the table "
        "(default 40)",
    )
    parser.add_argument(
        "--backup",
        metavar="FILE",
        help="with --apply: new file that the deleted rows are written to",
    )
    parser.add_argument(
        "--restore", metavar="FILE", help="put the rows of a backup file back"
    )
    args = parser.parse_args()

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        parser.error("set DATABASE_URL to the database to work on")
    try:
        if args.restore:
            restore(url, args.database, args.restore, do_apply=args.apply)
        elif args.apply:
            if args.expect is None or not args.backup:
                parser.error("--apply needs --expect and --backup")
            apply(
                url,
                args.database,
                expect=args.expect,
                backup=args.backup,
                implicit_locale=args.implicit_locale,
                tolerance=args.tolerance,
                max_share=args.max_share,
            )
        else:
            dry_run(url, args.database, args.implicit_locale)
            print("Dry run: nothing was changed")
    except DedupeError as e:
        print(f"Stopped: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

