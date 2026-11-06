"""

    Tests for the Realtime Database cleanup (src/rtdb_cleanup.py)
    Copyright © 2026 Miðeind ehf.

    The cleanup runs against an in-memory fake of the Realtime Database,
    so these tests touch no real database instance.

"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import copy
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from flask.testing import FlaskClient

from utils import client  # type: ignore[unused-import]  # noqa: F401

import firebase
import rtdb_cleanup
from rtdb_cleanup import (
    CleanupResult,
    cleanup,
    push_id_time,
    session_time,
    uuid1_time,
    wipe_children,
)


NOW = datetime(2026, 11, 6, 12, 0, 0, tzinfo=UTC)

_PUSH_CHARS = "-0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz"


def make_uuid1(t: datetime, node: int = 0x123456789ABC) -> str:
    """A version 1 UUID with the given creation time"""
    ticks = int(t.timestamp() * 10_000_000) + 0x01B21DD213814000
    return str(
        uuid.UUID(
            fields=(
                ticks & 0xFFFFFFFF,
                (ticks >> 32) & 0xFFFF,
                ((ticks >> 48) & 0x0FFF) | 0x1000,
                0x80 | 0x12,
                0x34,
                node,
            )
        )
    )


def make_push_id(t: datetime, suffix: str = "abcdefghijkl") -> str:
    """A Firebase push id with the given creation time"""
    ms = int(t.timestamp() * 1000)
    chars: List[str] = []
    for _ in range(8):
        chars.append(_PUSH_CHARS[ms % 64])
        ms //= 64
    return "".join(reversed(chars)) + suffix


def days_ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


def js_iso(t: datetime) -> str:
    """A timestamp as written by JavaScript's Date.toISOString()"""
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


class FakeRtdb:
    """An in-memory stand-in for the Realtime Database"""

    def __init__(self, tree: Dict[str, Any]) -> None:
        self.tree = copy.deepcopy(tree)
        self.deletes: List[Tuple[str, List[str]]] = []
        self.fail_on: Optional[str] = None

    def _node(self, path: str) -> Any:
        node: Any = self.tree
        for part in path.split("/"):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def get(self, path: str, shallow: bool = False) -> Any:
        if self.fail_on == path:
            raise RuntimeError(f"Simulated failure reading {path}")
        node = self._node(path)
        if shallow and isinstance(node, dict):
            return {key: True for key in node}
        return copy.deepcopy(node)

    def delete_children(self, path: str, children: List[str]) -> None:
        self.deletes.append((path, list(children)))
        for child in children:
            self._delete(f"{path}/{child}".split("/"))

    def _delete(self, parts: List[str]) -> None:
        # Delete the node, then any parents left empty, like the real thing
        def delete(node: Any, i: int) -> None:
            if not isinstance(node, dict) or parts[i] not in node:
                return
            if i == len(parts) - 1:
                del node[parts[i]]
                return
            delete(node[parts[i]], i + 1)
            if node[parts[i]] == {}:
                del node[parts[i]]

        delete(self.tree, 0)


class FakeClock:
    """A monotonic clock that advances by a fixed step on every reading"""

    def __init__(self, step: float) -> None:
        self.t = 0.0
        self.step = step

    def __call__(self) -> float:
        self.t += self.step
        return self.t


OLD_GAME = make_uuid1(days_ago(31))
OLDER_GAME = make_uuid1(days_ago(400))
NEW_GAME = make_uuid1(days_ago(29))
OLD_PUSH = make_push_id(days_ago(15))
NEW_PUSH = make_push_id(days_ago(1))
OLD_PUSH_EXPLO = make_push_id(days_ago(20), suffix="mnopqrstuvwx")


def sample_tree() -> Dict[str, Any]:
    move = {"move": {"num_moves": 3, "scores": [10, 20]}}
    return {
        "game": {
            OLD_GAME: {"u1": move, "u2": move},
            OLDER_GAME: {"u1": move},
            NEW_GAME: {"u1": move},
            "not-a-uuid": {"u1": move},
            # A version 4 UUID carries no time: never deleted
            str(uuid.UUID(int=0x1234, version=4)): {"u1": move},
        },
        "connection": {
            # Netskrafl: connection/{user_id}/{push_id}
            "u1": {OLD_PUSH: True, NEW_PUSH: True},
            "u2": {OLD_PUSH: True},
            # Explo: connection/{locale}/{user_id}/{push_id}
            "en_US": {"u3": {OLD_PUSH_EXPLO: True, NEW_PUSH: True}},
        },
        "session": {
            "u1": {
                "token-old": {"utc": js_iso(days_ago(61)), "os": "ios"},
                "token-new": {"utc": js_iso(days_ago(5)), "os": "android"},
            },
            "u2": {"token-no-utc": {"os": "ios"}},
        },
        "gatadagsins": {"2024-01-01": {"is_IS": {"count": 5}}},
        "user": {"u1": {"challenge": "2020-01-01T00:00:00"}},
    }


def run(fake: FakeRtdb, **kwargs: Any) -> CleanupResult:
    kwargs.setdefault("now", NOW)
    kwargs.setdefault("pause", 0.0)
    return cleanup(fake, **kwargs)


class TestAges:
    def test_uuid1_time(self) -> None:
        t = datetime(2025, 3, 4, 5, 6, 7, tzinfo=UTC)
        decoded = uuid1_time(make_uuid1(t))
        assert decoded is not None
        assert abs((decoded - t).total_seconds()) < 0.001
        # A freshly made game id is from now
        fresh = uuid1_time(str(uuid.uuid1()))
        assert fresh is not None
        assert abs((fresh - datetime.now(UTC)).total_seconds()) < 60

    def test_uuid1_time_rejects_other_keys(self) -> None:
        assert uuid1_time(str(uuid.uuid4())) is None
        assert uuid1_time("not-a-uuid") is None
        assert uuid1_time("") is None
        # Other spellings of a UUID are not game ids
        assert uuid1_time(make_uuid1(NOW).replace("-", "")) is None
        # Implausibly old (the UUID epoch)
        assert uuid1_time("00000000-0000-1000-8000-000000000000") is None

    def test_push_id_time(self) -> None:
        t = datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)
        assert push_id_time(make_push_id(t)) == t
        # A real push id from 2019, from the original Netskrafl instance
        real = push_id_time("-Lbp0z5C1eQIXb8hosFi")
        assert real is not None and real.year == 2019

    def test_push_id_time_rejects_other_keys(self) -> None:
        assert push_id_time("short") is None
        assert push_id_time("-Lbp0z5C1eQIXb8hosF!") is None
        # A user id of the right length is not plausible as a push id
        assert push_id_time("10489323499583111235") is None

    def test_session_time(self) -> None:
        assert session_time({"utc": "2026-11-06T12:34:56.789Z"}) == datetime(
            2026, 11, 6, 12, 34, 56, tzinfo=UTC
        )
        assert session_time({"os": "ios"}) is None
        assert session_time({"utc": "yesterday"}) is None
        assert session_time({"utc": 12345}) is None
        assert session_time("2026-11-06T12:34:56.789Z") is None


class TestCleanup:
    def test_deletes_expired_entries_only(self) -> None:
        fake = FakeRtdb(sample_tree())
        result = run(fake)
        assert result.ok and result.complete and not result.dry_run
        tree = fake.tree
        assert set(tree["game"]) == {
            NEW_GAME,
            "not-a-uuid",
            str(uuid.UUID(int=0x1234, version=4)),
        }
        # u2's only entry was stale, so u2 is gone entirely
        assert tree["connection"] == {
            "u1": {NEW_PUSH: True},
            "en_US": {"u3": {NEW_PUSH: True}},
        }
        assert tree["session"] == {"u1": {"token-new": sample_tree()["session"]["u1"]["token-new"]}}
        # Never touched
        assert tree["gatadagsins"] == sample_tree()["gatadagsins"]
        assert tree["user"] == sample_tree()["user"]

        game = result.stats["game"]
        assert (game.scanned, game.expired, game.deleted, game.unknown_age) == (5, 2, 2, 2)
        presence = result.stats["connection"]
        assert (presence.scanned, presence.expired, presence.deleted) == (5, 3, 3)
        session = result.stats["session"]
        assert (session.scanned, session.expired, session.deleted, session.unknown_age) == (3, 2, 2, 1)
        assert "game: scanned 5, expired 2, deleted 2" in result.summary()

    def test_oldest_games_go_first(self) -> None:
        fake = FakeRtdb(sample_tree())
        run(fake)
        game_deletes = [children for path, children in fake.deletes if path == "game"]
        assert game_deletes == [[OLDER_GAME, OLD_GAME]]

    def test_dry_run_deletes_nothing(self) -> None:
        fake = FakeRtdb(sample_tree())
        result = run(fake, dry_run=True)
        assert fake.tree == sample_tree()
        assert fake.deletes == []
        assert result.stats["game"].expired == 2
        assert result.stats["game"].deleted == 0
        assert "dry run" in result.summary()

    def test_nothing_to_do(self) -> None:
        fake = FakeRtdb({})
        result = run(fake)
        assert result.ok and result.complete
        assert fake.deletes == []
        assert all(s.scanned == 0 for s in result.stats.values())

    def test_batches(self) -> None:
        games = {make_uuid1(days_ago(31 + i)): {"u": {"move": 1}} for i in range(7)}
        fake = FakeRtdb({"game": games})
        sleeps: List[float] = []
        result = run(fake, batch_size=3, pause=0.5, sleep=sleeps.append)
        assert [len(children) for _, children in fake.deletes] == [3, 3, 1]
        # Pauses between batches only, not after the last one
        assert sleeps == [0.5, 0.5]
        assert "game" not in fake.tree
        assert result.stats["game"].deleted == 7

    def test_time_budget_carries_over(self) -> None:
        games = {make_uuid1(days_ago(31 + i)): {"u": {"move": 1}} for i in range(10)}
        fake = FakeRtdb({"game": games})
        # Every clock reading takes one second: the budget runs out mid-way
        result = run(fake, batch_size=2, time_budget=5.0, clock=FakeClock(1.0))
        assert not result.complete and result.ok
        left = len(fake.tree["game"])
        assert 0 < left < 10
        assert result.stats["game"].deleted == 10 - left
        assert "continues next run" in result.summary()
        # The next run finishes the job
        result = run(fake, batch_size=2)
        assert result.complete
        assert "game" not in fake.tree

    def test_error_in_one_path_does_not_stop_the_others(self) -> None:
        fake = FakeRtdb(sample_tree())
        fake.fail_on = "session"
        result = run(fake)
        assert not result.ok
        assert result.stats["session"].error is not None
        assert result.stats["game"].deleted == 2
        assert result.stats["connection"].deleted == 3
        assert "error" in result.summary()

    def test_custom_retention(self) -> None:
        fake = FakeRtdb(sample_tree())
        result = run(fake, game_days=1000, presence_days=1000, session_days=1000)
        assert result.stats["game"].expired == 0
        assert result.stats["connection"].expired == 0
        # The token without a timestamp is useless at any retention
        assert result.stats["session"].expired == 1


class TestWipe:
    def test_wipe_children(self) -> None:
        fake = FakeRtdb(sample_tree())
        stats = wipe_children(fake, "game", batch_size=2, pause=0.0)
        assert "game" not in fake.tree
        assert (stats.scanned, stats.deleted) == (5, 5)
        assert fake.tree["user"] == sample_tree()["user"]

    def test_wipe_dry_run(self) -> None:
        fake = FakeRtdb(sample_tree())
        stats = wipe_children(fake, "user", dry_run=True)
        assert fake.tree == sample_tree()
        assert (stats.scanned, stats.deleted) == (1, 0)


class TestEndpoint:
    def test_cleanup_endpoint(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch  # noqa: F811
    ) -> None:
        calls: List[bool] = []

        def fake_cleanup(access: Any, *, dry_run: bool = False) -> CleanupResult:
            calls.append(dry_run)
            return CleanupResult(dry_run=dry_run)

        # Never run against a real database instance from the tests
        monkeypatch.setattr(rtdb_cleanup, "cleanup", fake_cleanup)
        # Local development counts as an authorized scheduler (synchronous)
        resp = client.get("/connect/cleanup?dry_run=1")
        assert resp.status_code == 200
        assert calls == [True]
        resp = client.get("/connect/cleanup")
        assert resp.status_code == 200
        assert calls == [True, False]
        assert firebase.rtdb_cleanup is rtdb_cleanup

