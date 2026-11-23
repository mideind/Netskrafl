"""
Tests of utils/dedupe_challenges.py, the utility that removes identical
pending challenges from a PostgreSQL database.

The utility reads the whole challenges table, so these tests empty that
table of the throwaway test database before each test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Optional, Tuple

import importlib.util
import json
import os
import stat
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg2
import pytest

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol

_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "utils", "dedupe_challenges.py"
)
_spec = importlib.util.spec_from_file_location("dedupe_challenges", _PATH)
assert _spec is not None and _spec.loader is not None
dedupe: Any = importlib.util.module_from_spec(_spec)
sys.modules["dedupe_challenges"] = dedupe
_spec.loader.exec_module(dedupe)

A, B, C = "dedupe-a", "dedupe-b", "dedupe-c"
NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=UTC)

Prefs = Optional[Dict[str, Any]]


def row(
    src: str, dest: str, prefs: Prefs, days_old: float, id: Optional[str] = None
) -> Any:
    """A row as the utility reads it"""
    return dedupe.Row(
        id or str(uuid.uuid4()),
        src,
        dest,
        prefs,
        None if prefs is None else json.dumps(prefs),
        NOW - timedelta(days=days_old),
    )


class TestPlan:
    """What is kept and what is deleted"""

    def test_newest_of_each_group_is_kept(self) -> None:
        rows = [
            row(A, B, {"duration": 0}, 300, id="00000000-0000-0000-0000-000000000001"),
            row(A, B, {"duration": 0}, 5, id="00000000-0000-0000-0000-000000000002"),
            row(A, B, {"duration": 0}, 40, id="00000000-0000-0000-0000-000000000003"),
        ]
        plan = dedupe.make_plan(rows)
        assert plan.total == 3
        assert plan.dup_groups == 1
        assert sorted(plan.delete_ids) == [rows[0].id, rows[2].id]
        assert plan.keep_ids == [rows[1].id]

    def test_same_timestamp_keeps_the_higher_id(self) -> None:
        rows = [
            row(A, B, {}, 10, id="00000000-0000-0000-0000-00000000000b"),
            row(A, B, {}, 10, id="00000000-0000-0000-0000-00000000000a"),
        ]
        plan = dedupe.make_plan(rows)
        assert plan.delete_ids == [rows[1].id]
        assert plan.keep_ids == [rows[0].id]

    def test_different_challenges_are_all_kept(self) -> None:
        rows = [
            row(A, B, {"duration": 0}, 10),
            row(A, B, {"duration": 10}, 10),
            row(A, B, {"duration": 0, "manual": True}, 10),
            row(A, B, {"duration": 0, "fairplay": True}, 10),
            row(A, B, {"duration": 0, "locale": "en_US"}, 10),
            row(A, C, {"duration": 0}, 10),
            row(B, A, {"duration": 0}, 10),
        ]
        plan = dedupe.make_plan(rows)
        assert plan.delete == []
        assert plan.dup_groups == 0
        assert len(plan.newest) == 7

    def test_options_that_are_off_or_absent_are_the_same(self) -> None:
        rows = [
            row(A, B, None, 50),
            row(A, B, {}, 40),
            row(A, B, {"duration": 0, "manual": False, "fairplay": None}, 30),
            row(A, B, {"manual": False, "newbag": False}, 20),
        ]
        plan = dedupe.make_plan(rows)
        assert len(plan.delete) == 3
        assert plan.keep_ids == [rows[3].id]

    def test_a_missing_locale_is_not_a_given_one(self) -> None:
        rows = [
            row(A, B, {"duration": 0}, 500),
            row(A, B, {"duration": 0, "locale": "is_IS"}, 20),
        ]
        plan = dedupe.make_plan(rows)
        assert plan.delete == []
        assert plan.implicit == 0

    def test_implicit_locale(self) -> None:
        """With an implicit locale, a challenge without a locale is one
        for that locale, and not for any other"""
        rows = [
            row(A, B, {"duration": 0}, 500),
            row(A, B, {"duration": 0, "locale": "is_IS"}, 20),
            row(A, B, {"duration": 0, "locale": "en_US"}, 10),
            row(A, C, {"duration": 0}, 500),
            row(A, C, {"duration": 0}, 400),
        ]
        plan = dedupe.make_plan(rows, "is_IS")
        assert sorted(plan.delete_ids) == sorted([rows[0].id, rows[3].id])
        assert plan.keep_ids == sorted([rows[1].id, rows[4].id])
        assert plan.implicit == 3

    def test_tile_bags_are_not_the_same_game(self) -> None:
        """Challenges for the old and the new tile bag are both kept; an
        absent tile bag preference means the old bag"""
        rows = [
            row(A, B, {"duration": 0, "newbag": True}, 50),
            row(A, B, {"duration": 0, "newbag": False}, 40),
            row(A, B, {"duration": 0}, 30),
            row(A, B, {"duration": 0, "newbag": True}, 20),
        ]
        plan = dedupe.make_plan(rows)
        assert sorted(plan.delete_ids) == sorted([rows[0].id, rows[1].id])
        assert plan.keep_ids == sorted([rows[2].id, rows[3].id])
        assert plan.both_bags == 1

    def test_unknown_preference_stops_the_run(self) -> None:
        rows = [row(A, B, {"duration": 0, "board_type": "explo"}, 10)]
        with pytest.raises(dedupe.DedupeError, match="board_type"):
            dedupe.make_plan(rows)


Stored = Tuple[str, str, str, Optional[str], datetime]


class Database:
    """The challenges table of the test database, read and written directly"""

    def __init__(self, url: str) -> None:
        self.url = url
        self.conn = psycopg2.connect(url)
        self.conn.autocommit = True
        with self.conn.cursor() as cur:
            cur.execute("select current_database()")
            r = cur.fetchone()
            assert r is not None
            self.name: str = r[0]
        # Never empty the challenges of anything but a test database
        assert self.name.endswith("_test"), self.name

    def clear(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute("delete from challenges")

    def add(self, src: str, dest: str, prefs: Prefs, days_old: float) -> str:
        cid = str(uuid.uuid4())
        with self.conn.cursor() as cur:
            cur.execute(
                "insert into challenges "
                "(id, src_user_id, dest_user_id, prefs, timestamp) "
                "values (%s::uuid, %s, %s, %s::jsonb, now() - %s * interval '1 day')",
                (cid, src, dest, None if prefs is None else json.dumps(prefs), days_old),
            )
        return cid

    def delete(self, cid: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute("delete from challenges where id = %s::uuid", (cid,))

    def rows(self) -> List[Stored]:
        with self.conn.cursor() as cur:
            cur.execute(
                "select id::text, src_user_id, dest_user_id, prefs::text, timestamp "
                "from challenges order by id"
            )
            return list(cur.fetchall())

    def ids(self) -> List[str]:
        return [r[0] for r in self.rows()]

    def close(self) -> None:
        self.conn.close()


@pytest.fixture
def database(pg_backend: "DatabaseBackendProtocol") -> Iterator[Database]:
    """The test database with the test users and no challenges"""
    from src.db.config import DEFAULT_TEST_DATABASE_URL, get_config

    for user_id in (A, B, C):
        if pg_backend.users.get_by_id(user_id) is None:
            pg_backend.users.create(
                user_id=user_id,
                account=f"test:{user_id}",
                email=None,
                nickname=user_id,
                locale="is_IS",
            )
    pg_backend.commit()
    url = get_config().get_database_url(DEFAULT_TEST_DATABASE_URL)
    assert url is not None
    db = Database(url)
    db.clear()
    yield db
    db.clear()
    db.close()


def fill(db: Database) -> Dict[str, str]:
    """Eleven challenges, of which four are to be deleted. Returns their
    ids by name."""
    return {
        # Three identical ones: the newest stays
        "old1": db.add(A, B, {"duration": 0, "newbag": True}, 400),
        "old2": db.add(A, B, {"duration": 0, "newbag": True}, 90),
        "new": db.add(A, B, {"duration": 0, "newbag": True}, 3),
        # Another type, twice
        "timed1": db.add(A, B, {"duration": 10, "newbag": True}, 20),
        "timed2": db.add(A, B, {"duration": 10, "newbag": True}, 10),
        # No preferences at all, twice
        "bare1": db.add(B, C, None, 700),
        "bare2": db.add(B, C, {}, 600),
        # Single ones
        "other": db.add(A, C, {"duration": 0, "newbag": True}, 50),
        "back": db.add(B, A, {"duration": 0, "newbag": True}, 50),
        "single1": db.add(C, A, {"duration": 0, "newbag": True}, 2),
        "single2": db.add(C, B, {"duration": 15, "newbag": True}, 1000),
    }


DELETED = ("old1", "old2", "timed1", "bare1")


class TestRun:
    """The utility against a database"""

    def test_dry_run_changes_nothing(self, database: Database) -> None:
        fill(database)
        before = database.rows()
        plan = dedupe.dry_run(database.url, database.name)
        assert len(plan.delete) == 4
        assert plan.total == 11
        assert database.rows() == before

    def test_dry_run_session_cannot_write(self, database: Database) -> None:
        fill(database)
        conn = dedupe.connect(database.url, read_only=True)
        try:
            with conn.cursor() as cur:
                with pytest.raises(psycopg2.errors.ReadOnlySqlTransaction):
                    cur.execute("delete from challenges")
        finally:
            conn.rollback()
            conn.close()
        assert len(database.rows()) == 11

    def test_wrong_database_name(self, database: Database, tmp_path: Path) -> None:
        fill(database)
        with pytest.raises(dedupe.DedupeError, match="not 'production'"):
            dedupe.dry_run(database.url, "production")
        with pytest.raises(dedupe.DedupeError, match="not 'production'"):
            dedupe.apply(
                database.url, "production", expect=4, backup=str(tmp_path / "b.jsonl")
            )
        assert len(database.rows()) == 11

    def test_apply(self, database: Database, tmp_path: Path) -> None:
        ids = fill(database)
        before = {r[0]: r for r in database.rows()}
        backup = tmp_path / "backup.jsonl"
        dedupe.apply(database.url, database.name, expect=4, backup=str(backup))
        gone = {ids[name] for name in DELETED}
        assert set(database.ids()) == set(ids.values()) - gone
        # The rows that are left are unchanged
        for r in database.rows():
            assert r == before[r[0]]
        # The backup holds the deleted rows, and only its owner can read it
        assert stat.S_IMODE(backup.stat().st_mode) == 0o600
        lines = [json.loads(line) for line in backup.read_text().splitlines()]
        assert lines[0]["database"] == database.name
        assert lines[0]["rows"] == 4
        assert {line["id"] for line in lines[1:]} == gone
        kept = {line["id"]: line["kept"] for line in lines[1:]}
        assert kept[ids["old1"]] == ids["new"]
        assert kept[ids["old2"]] == ids["new"]
        assert kept[ids["timed1"]] == ids["timed2"]
        assert kept[ids["bare1"]] == ids["bare2"]
        # A second run finds nothing to do
        again = dedupe.apply(
            database.url, database.name, expect=0, backup=str(tmp_path / "second.jsonl")
        )
        assert again.delete == []
        assert not (tmp_path / "second.jsonl").exists()

    def test_apply_with_implicit_locale(
        self, database: Database, tmp_path: Path
    ) -> None:
        old = database.add(A, B, {"duration": 0, "newbag": True}, 500)
        new = database.add(A, B, {"duration": 0, "newbag": True, "locale": "is_IS"}, 5)
        english = database.add(
            A, B, {"duration": 0, "newbag": True, "locale": "en_US"}, 5
        )
        assert dedupe.dry_run(database.url, database.name).delete == []
        dedupe.apply(
            database.url,
            database.name,
            expect=1,
            backup=str(tmp_path / "backup.jsonl"),
            implicit_locale="is_IS",
        )
        assert sorted(database.ids()) == sorted([new, english])
        assert old not in database.ids()

    def test_unexpected_number_stops_the_run(
        self, database: Database, tmp_path: Path
    ) -> None:
        fill(database)
        before = database.rows()
        backup = tmp_path / "backup.jsonl"
        with pytest.raises(dedupe.DedupeError, match="4 challenges to delete, but 7"):
            dedupe.apply(database.url, database.name, expect=7, backup=str(backup))
        assert database.rows() == before
        assert not backup.exists()
        # Within the tolerance, it goes ahead
        dedupe.apply(
            database.url, database.name, expect=6, tolerance=2, backup=str(backup)
        )
        assert len(database.rows()) == 7

    def test_too_large_a_share_stops_the_run(
        self, database: Database, tmp_path: Path
    ) -> None:
        fill(database)
        before = database.rows()
        backup = tmp_path / "backup.jsonl"
        with pytest.raises(dedupe.DedupeError, match="more than 10% of the table"):
            dedupe.apply(
                database.url, database.name, expect=4, backup=str(backup), max_share=10
            )
        assert database.rows() == before
        assert not backup.exists()

    def test_existing_backup_file_stops_the_run(
        self, database: Database, tmp_path: Path
    ) -> None:
        fill(database)
        before = database.rows()
        backup = tmp_path / "backup.jsonl"
        backup.write_text("something else\n")
        with pytest.raises(dedupe.DedupeError, match="exists already"):
            dedupe.apply(
                database.url, database.name, expect=4, backup=str(backup)
            )
        assert database.rows() == before
        assert backup.read_text() == "something else\n"

    def test_restore(self, database: Database, tmp_path: Path) -> None:
        fill(database)
        before = database.rows()
        backup = tmp_path / "backup.jsonl"
        dedupe.apply(
            database.url, database.name, expect=4, backup=str(backup)
        )
        after = database.rows()
        assert len(after) == 7
        # A dry run of the restore inserts nothing
        assert dedupe.restore(database.url, database.name, str(backup), do_apply=False) == 4
        assert database.rows() == after
        with pytest.raises(dedupe.DedupeError, match="not 'production'"):
            dedupe.restore(database.url, "production", str(backup), do_apply=True)
        # The restore gives back exactly what was there
        assert dedupe.restore(database.url, database.name, str(backup), do_apply=True) == 4
        assert database.rows() == before
        # And it can be repeated
        assert dedupe.restore(database.url, database.name, str(backup), do_apply=True) == 0
        assert database.rows() == before

    @pytest.mark.parametrize("which", ["new", "old1"])
    def test_change_by_the_server_in_the_meantime(
        self,
        database: Database,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        which: str,
    ) -> None:
        """If the server deletes a challenge of an affected group after the
        utility has read the table (the kept one, or one of those to
        delete), nothing is deleted by the utility"""
        ids = fill(database)
        backup = tmp_path / "backup.jsonl"
        read_rows = dedupe.read_rows
        calls: List[int] = []

        def read_then_interfere(conn: Any) -> Any:
            rows = read_rows(conn)
            if not calls:
                # As the server does when a challenge is accepted
                database.delete(ids[which])
            calls.append(1)
            return rows

        monkeypatch.setattr(dedupe, "read_rows", read_then_interfere)
        with pytest.raises(dedupe.DedupeError, match="run it again"):
            dedupe.apply(
                database.url, database.name, expect=4, backup=str(backup)
            )
        assert set(database.ids()) == set(ids.values()) - {ids[which]}
        assert not backup.exists()
        # Run again, it deletes what is still to delete
        monkeypatch.setattr(dedupe, "read_rows", read_rows)
        dedupe.apply(database.url, database.name, expect=3, backup=str(backup))
        left = set(ids.values()) - {ids[which]} - {ids[n] for n in DELETED}
        if which == "new":
            # The newest of the two that were left is kept in its place
            left.add(ids["old2"])
        assert set(database.ids()) == left

