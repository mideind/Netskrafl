"""

    Decode sweep: load every migrated user and game through the app

    Copyright © 2026 Miðeind ehf.

    Post-migration verification step (see doc/data-migration-design.md,
    "Verification"). Every row of the users and games tables in a
    PostgreSQL database is loaded through the real application loaders
    (User.load_if_exists, Game.load) on the PostgreSQL backend, and any
    row that raises or comes back as None is reported. This catches what
    the migrator's own field comparison cannot: rows that are faithful
    copies of the source but that the app cannot interpret (unsupported
    locale, undecodable move list, inconsistent racks, ...).

    Run it against a *copy* of the migrated database, never the live
    target, with the standard local app environment (PROJECT_ID etc.,
    see CLAUDE.md) plus DATABASE_BACKEND=postgresql and DATABASE_URL:

      DATABASE_BACKEND=postgresql \\
      DATABASE_URL=postgresql://test:test@localhost:5432/explo_live_copy \\
      venv/bin/python scripts/decode_sweep.py [users|games|all] [limit]
          [--shard I/N | --jobs N]

    --shard I/N sweeps only the rows whose id hashes to I modulo N (I is
    0-based), so N processes with I = 0..N-1 cover every row exactly once.
    --jobs N does that for you: it runs the N shards as child processes in
    parallel and fails if any of them fails. A limit applies per shard.

    Reads only. ~600 games/s per process on the development box (2026-09-10).

"""

from __future__ import annotations

from typing import Any, Callable, Iterator, List, Optional, Tuple

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import psycopg2  # noqa: E402

from db.session import init_session_manager  # noqa: E402
from skraflgame import Game  # noqa: E402
from skrafluser import User  # noqa: E402


Shard = Tuple[int, int]  # (index, count): index in 0..count-1


def parse_shard(text: str) -> Shard:
    """Parse "I/N" into (I, N), with 0 <= I < N"""
    try:
        i_text, n_text = text.split("/")
        index, count = int(i_text), int(n_text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected I/N, got {text!r}")
    if count < 1 or not 0 <= index < count:
        raise argparse.ArgumentTypeError(f"need 0 <= I < N, got {text!r}")
    return index, count


def iter_ids(
    url: str, table: str, order: str, limit: int, shard: Optional[Shard]
) -> Iterator[str]:
    """Stream the ids of a table (or of one shard of it) through a
    server-side cursor"""
    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor(name="sweep")
        cur.itersize = 5000
        sql = f'SELECT id FROM "{table}"'
        params: Optional[Tuple[int, int]] = None
        if shard is not None:
            # hashtext() is stable for a given value, so every id lands in
            # exactly one shard; the mask keeps the modulo non-negative
            # (%% is a literal % in a parameterized psycopg2 query)
            sql += " WHERE (hashtext(id) & 2147483647) %% %s = %s"
            params = (shard[1], shard[0])
        sql += f' ORDER BY "{order}"'
        if limit:
            sql += f" LIMIT {int(limit)}"
        cur.execute(sql, params)
        for (i,) in cur:
            yield str(i)
    finally:
        conn.close()


def sweep(
    label: str,
    url: str,
    table: str,
    order: str,
    loader: Callable[[str], Optional[Any]],
    limit: int,
    shard: Optional[Shard],
) -> Tuple[int, List[Tuple[str, str]]]:
    """Load every row of a table through the app; return (count, bad rows)"""
    from db.session import get_session_manager

    manager = get_session_manager()
    t0 = time.time()
    n = 0
    bad: List[Tuple[str, str]] = []
    if shard is not None:
        label = f"{label}[{shard[0]}/{shard[1]}]"
    for i in iter_ids(url, table, order, limit, shard):
        n += 1
        try:
            # One request-scoped session per load, so that a failure
            # cannot poison the session used by the next row
            with manager.request_context():
                obj = loader(i)
            if obj is None:
                bad.append((i, "loader returned None"))
        except Exception as e:  # noqa: BLE001 - every failure is a finding
            bad.append((i, f"{type(e).__name__}: {e}"[:200]))
        if n % 100000 == 0:
            rate = n / (time.time() - t0)
            print(f"{label}: {n:,} loaded, {len(bad)} bad, {rate:.0f}/s", flush=True)
    print(
        f"{label}: DONE {n:,} rows, {len(bad)} bad, {time.time() - t0:.0f}s",
        flush=True,
    )
    for i, msg in bad[:100]:
        print(f"  BAD {label} {i}: {msg}", flush=True)
    if len(bad) > 100:
        print(f"  ... and {len(bad) - 100} more", flush=True)
    return n, bad


def run_jobs(what: str, limit: int, jobs: int) -> int:
    """Run every shard of the sweep as a child process, in parallel.
    The children share this process's stdout; their lines are labelled
    with the shard. Returns 1 if any shard failed."""
    children = [
        subprocess.Popen(
            [sys.executable, __file__, what, str(limit), "--shard", f"{i}/{jobs}"]
        )
        for i in range(jobs)
    ]
    failed = [i for i, child in enumerate(children) if child.wait() != 0]
    if failed:
        print(f"FAILED shards: {', '.join(f'{i}/{jobs}' for i in failed)}", flush=True)
        return 1
    print(f"All {jobs} shards clean", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Load every migrated user and game through the app")
    parser.add_argument("what", nargs="?", choices=("users", "games", "all"), default="all")
    parser.add_argument("limit", nargs="?", type=int, default=0,
                        help="stop after this many rows per table (per shard); 0 = all")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--shard", type=parse_shard, metavar="I/N",
                       help="sweep only shard I (0-based) of N")
    group.add_argument("--jobs", type=int, metavar="N",
                       help="run all N shards in parallel as child processes")
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url or os.environ.get("DATABASE_BACKEND", "").lower() != "postgresql":
        sys.exit("Set DATABASE_BACKEND=postgresql and DATABASE_URL to the copy to sweep")
    if args.jobs is not None:
        if args.jobs < 1:
            sys.exit("--jobs must be at least 1")
        return run_jobs(args.what, args.limit, args.jobs)
    shard: Optional[Shard] = args.shard
    init_session_manager("postgresql", url)
    failures = 0
    if args.what in ("users", "all"):
        _, bad = sweep(
            "users", url, "users", "id",
            lambda uid: User.load_if_exists(uid), args.limit, shard,
        )
        failures += len(bad)
    if args.what in ("games", "all"):
        _, bad = sweep(
            "games", url, "games", "ts_last_move",
            lambda gid: Game.load(gid, use_cache=False), args.limit, shard,
        )
        failures += len(bad)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

