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

    Reads only. ~600 games/s on the development box (2026-09-10).

"""

from __future__ import annotations

from typing import Any, Callable, Iterator, List, Optional, Tuple

import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import psycopg2  # noqa: E402

from db.session import init_session_manager  # noqa: E402
from skraflgame import Game  # noqa: E402
from skrafluser import User  # noqa: E402


def iter_ids(url: str, table: str, order: str, limit: int) -> Iterator[str]:
    """Stream the ids of a table through a server-side cursor"""
    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor(name="sweep")
        cur.itersize = 5000
        sql = f'SELECT id FROM "{table}" ORDER BY "{order}"'
        if limit:
            sql += f" LIMIT {int(limit)}"
        cur.execute(sql)
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
) -> Tuple[int, List[Tuple[str, str]]]:
    """Load every row of a table through the app; return (count, bad rows)"""
    from db.session import get_session_manager

    manager = get_session_manager()
    t0 = time.time()
    n = 0
    bad: List[Tuple[str, str]] = []
    for i in iter_ids(url, table, order, limit):
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


def main() -> int:
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    url = os.environ.get("DATABASE_URL")
    if not url or os.environ.get("DATABASE_BACKEND", "").lower() != "postgresql":
        sys.exit("Set DATABASE_BACKEND=postgresql and DATABASE_URL to the copy to sweep")
    init_session_manager("postgresql", url)
    failures = 0
    if what in ("users", "all"):
        _, bad = sweep(
            "users", url, "users", "id",
            lambda uid: User.load_if_exists(uid), limit,
        )
        failures += len(bad)
    if what in ("games", "all"):
        _, bad = sweep(
            "games", url, "games", "ts_last_move",
            lambda gid: Game.load(gid, use_cache=False), limit,
        )
        failures += len(bad)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

