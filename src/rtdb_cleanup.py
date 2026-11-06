"""

    Realtime Database cleanup for Netskrafl and Explo

    Copyright © 2026 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    The Firebase Realtime Database carries notifications to clients; the
    database of record holds the real state. The Realtime Database has no
    time-to-live mechanism, so without cleanup it keeps every notification
    ever sent (the original Netskrafl instance grew to over 1 GB, mostly
    game/ nodes going back years). This module deletes nodes that no client
    will read again:

    - game/{game_id}: move and chat notifications, once the game id (a
      version 1 UUID, which carries its creation time) is older than
      GAME_RETENTION_DAYS. This is safe even for a game still in progress:
      every client ignores the value it receives when it attaches to a
      path, and acts only on later changes, and every client ignores a null
      value. The next move simply writes the node again.
    - connection/.../{push_id}: presence entries whose push id (which also
      carries its creation time) is older than PRESENCE_RETENTION_DAYS.
      Live entries are normally removed by the client's onDisconnect
      handler; this catches the ones that were left behind, which would
      otherwise count their users as online. The only side effect: a
      client that has been connected without a break for longer than that
      shows its user as offline until it reconnects. Entries set to false
      (written by older clients instead of removing the entry) are deleted
      whatever their age: they never mean that a user is online, but
      get_connected_users() counts every user key under connection/.
    - session/{user_id}/{token}: push notification tokens (Explo) whose
      utc timestamp is older than SESSION_RETENTION_DAYS. push_to_user()
      already ignores tokens older than 14 days, and the app writes its
      token again each time it starts, so this changes no behaviour.
      Tokens without a readable timestamp are also deleted, since
      push_to_user() never uses them either.

    gatadagsins/ (lasting Gáta dagsins data) and user/ (one small node per
    user) are never touched.

    Deletions are made in batches of a few hundred paths per request,
    oldest first, with a short pause in between: a single delete of a large
    subtree would lock the database for a long time. A time budget limits
    each run; whatever is left over is picked up by the next run, so the
    cleanup is idempotent and a backlog simply takes several runs.

    The module only depends on the firebase_admin SDK (not on the app
    configuration), so that utils/rtdb-cleanup.py can run it against any
    database instance.

"""

from __future__ import annotations

from typing import (
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Protocol,
    Tuple,
    cast,
)

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from firebase_admin import App, db  # type: ignore


# Retention periods, in days
GAME_RETENTION_DAYS = 30
PRESENCE_RETENTION_DAYS = 14
SESSION_RETENTION_DAYS = 60

# Number of paths deleted per request
BATCH_SIZE = 500
# Pause between delete requests, in seconds, to leave room for live traffic
BATCH_PAUSE = 0.2
# Default time budget of a cleanup run, in seconds
DEFAULT_TIME_BUDGET = 180.0

# The character set of Firebase push ids; the first 8 characters encode
# the creation time in milliseconds since the Unix epoch, in base 64
_PUSH_CHARS = "-0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz"
_PUSH_CHAR_VALUE: Dict[str, int] = {c: i for i, c in enumerate(_PUSH_CHARS)}
_PUSH_ID_LENGTH = 20
_PUSH_TIME_CHARS = 8

# Offset between the UUID epoch (1582-10-15) and the Unix epoch, in 100 ns units
_UUID_EPOCH_OFFSET = 0x01B21DD213814000

# Timestamps before this are not plausible for our ids
_EARLIEST = datetime(2012, 1, 1, tzinfo=UTC)

# Presence entries are at connection/{user_id}/{push_id} (Netskrafl) or
# at connection/{locale}/{user_id}/{push_id} (Explo)
_MAX_PRESENCE_DEPTH = 3


def _plausible(t: datetime) -> Optional[datetime]:
    """Return the timestamp if it is plausible for one of our ids, else None"""
    if _EARLIEST <= t <= datetime.now(UTC) + timedelta(days=1):
        return t
    return None


def uuid1_time(key: str) -> Optional[datetime]:
    """Return the creation time of a version 1 UUID, such as a game id,
    or None if the key is not a version 1 UUID"""
    try:
        u = uuid.UUID(key)
    except ValueError:
        return None
    if u.variant != uuid.RFC_4122 or u.version != 1 or str(u) != key.lower():
        return None
    seconds = (u.time - _UUID_EPOCH_OFFSET) / 1e7
    return _plausible(datetime.fromtimestamp(seconds, UTC))


def push_id_time(key: str) -> Optional[datetime]:
    """Return the creation time of a Firebase push id, or None if the key
    is not a push id"""
    if len(key) != _PUSH_ID_LENGTH or any(c not in _PUSH_CHAR_VALUE for c in key):
        return None
    ms = 0
    for c in key[:_PUSH_TIME_CHARS]:
        ms = ms * 64 + _PUSH_CHAR_VALUE[c]
    return _plausible(datetime.fromtimestamp(ms / 1000, UTC))


def session_time(info: object) -> Optional[datetime]:
    """Return the timestamp of a push notification session, which is a
    dictionary { utc, os, locale } written by the Explo app, or None if
    it has no readable timestamp. The utc string comes from JavaScript's
    Date.toISOString() (e.g. '2026-11-06T12:34:56.789Z'), which Python's
    fromisoformat() does not accept in full, so only its first 19
    characters are parsed."""
    if not isinstance(info, dict):
        return None
    utc = cast(Mapping[str, object], info).get("utc")
    if not isinstance(utc, str) or len(utc) < 19:
        return None
    try:
        return datetime.fromisoformat(utc[:19]).replace(tzinfo=UTC)
    except ValueError:
        return None


class RtdbAccess(Protocol):
    """The Realtime Database operations needed by the cleanup"""

    def get(self, path: str, shallow: bool = False) -> Any:
        """Return the data at the path (keys only, if shallow), or None"""
        ...

    def delete_children(self, path: str, children: List[str]) -> None:
        """Delete the given children (relative paths) of the path,
        in a single request"""
        ...


class FirebaseAdminAccess:
    """RtdbAccess via the firebase_admin SDK"""

    def __init__(self, app: Optional[App] = None) -> None:
        # None means the default firebase_admin app
        self._app = app

    def get(self, path: str, shallow: bool = False) -> Any:
        ref = cast(Any, db).reference(path, app=self._app)
        return ref.get(shallow=shallow)

    def delete_children(self, path: str, children: List[str]) -> None:
        # A multi-path update with null values deletes all the paths at once
        ref = cast(Any, db).reference(path, app=self._app)
        ref.update({child: None for child in children})


@dataclass
class PathStats:
    """Counts for one top-level path"""

    scanned: int = 0
    expired: int = 0
    deleted: int = 0
    # Entries whose age could not be determined
    unknown_age: int = 0
    error: Optional[str] = None

    def __str__(self) -> str:
        s = (
            f"scanned {self.scanned}, expired {self.expired}, "
            f"deleted {self.deleted}, unknown age {self.unknown_age}"
        )
        if self.error:
            s += f", error: {self.error}"
        return s


@dataclass
class CleanupResult:
    """The outcome of a cleanup run"""

    dry_run: bool
    stats: Dict[str, PathStats] = field(default_factory=dict)
    # False if the time budget ran out before all expired entries were deleted
    complete: bool = True
    elapsed: float = 0.0

    @property
    def ok(self) -> bool:
        return not any(s.error for s in self.stats.values())

    def summary(self) -> str:
        parts = "; ".join(f"{name}: {s}" for name, s in self.stats.items())
        mode = "dry run, nothing deleted" if self.dry_run else (
            "complete" if self.complete else "time budget used up, continues next run"
        )
        return f"RTDB cleanup ({mode}, {self.elapsed:.1f} s): {parts}"


class _Budget:
    """A time budget, measured by a monotonic clock"""

    def __init__(self, seconds: Optional[float], clock: Callable[[], float]) -> None:
        self._clock = clock
        self._deadline = None if seconds is None else clock() + seconds

    def exhausted(self) -> bool:
        return self._deadline is not None and self._clock() >= self._deadline


def _delete(
    access: RtdbAccess,
    base: str,
    paths: List[str],
    stats: PathStats,
    budget: _Budget,
    batch_size: int,
    pause: float,
    sleep: Callable[[float], None],
) -> bool:
    """Delete the paths under base in batches; return False if the time
    budget ran out before all of them were deleted"""
    for i in range(0, len(paths), batch_size):
        if budget.exhausted():
            return False
        chunk = paths[i : i + batch_size]
        access.delete_children(base, chunk)
        stats.deleted += len(chunk)
        if pause > 0 and i + batch_size < len(paths):
            sleep(pause)
    return True


def _oldest_first(aged: List[Tuple[datetime, str]]) -> List[str]:
    aged.sort()
    return [path for _, path in aged]


def expired_games(access: RtdbAccess, cutoff: datetime, stats: PathStats) -> List[str]:
    """Return the ids of game/ nodes created before the cutoff, oldest first"""
    keys = access.get("game", shallow=True)
    aged: List[Tuple[datetime, str]] = []
    if isinstance(keys, dict):
        for key in cast(Dict[str, Any], keys):
            stats.scanned += 1
            t = uuid1_time(key)
            if t is None:
                stats.unknown_age += 1
            elif t < cutoff:
                aged.append((t, key))
    stats.expired = len(aged)
    return _oldest_first(aged)


def expired_presence(
    access: RtdbAccess, cutoff: datetime, stats: PathStats
) -> List[str]:
    """Return the paths (relative to connection/) of presence entries
    created before the cutoff, and of entries set to false, oldest first.
    Other unexpected values are left alone and counted as of unknown age."""
    tree = access.get("connection")
    aged: List[Tuple[datetime, str]] = []

    def walk(node: Mapping[str, Any], prefix: str, depth: int) -> None:
        for key, value in node.items():
            path = f"{prefix}/{key}" if prefix else key
            if value is True:
                # A presence entry: {push_id}: true
                stats.scanned += 1
                t = push_id_time(key)
                if t is None:
                    stats.unknown_age += 1
                elif t < cutoff:
                    aged.append((t, path))
            elif value is False:
                # Left behind by an older client: delete it first
                stats.scanned += 1
                aged.append((_EARLIEST, path))
            elif isinstance(value, dict):
                if depth < _MAX_PRESENCE_DEPTH:
                    walk(cast(Mapping[str, Any], value), path, depth + 1)
            else:
                # Not a presence entry: leave it, but make it visible
                stats.scanned += 1
                stats.unknown_age += 1

    if isinstance(tree, dict):
        walk(cast(Mapping[str, Any], tree), "", 1)
    stats.expired = len(aged)
    return _oldest_first(aged)


def expired_sessions(
    access: RtdbAccess, cutoff: datetime, stats: PathStats
) -> List[str]:
    """Return the paths (relative to session/) of push notification
    tokens last refreshed before the cutoff, or without a readable
    timestamp, oldest first"""
    tree = access.get("session")
    aged: List[Tuple[datetime, str]] = []
    if isinstance(tree, dict):
        for user_id, tokens in cast(Dict[str, Any], tree).items():
            if not isinstance(tokens, dict):
                continue
            for token, info in cast(Dict[str, Any], tokens).items():
                stats.scanned += 1
                t = session_time(info)
                if t is None:
                    stats.unknown_age += 1
                    # Unusable for push_to_user(): delete it first
                    aged.append((_EARLIEST, f"{user_id}/{token}"))
                elif t < cutoff:
                    aged.append((t, f"{user_id}/{token}"))
    stats.expired = len(aged)
    return _oldest_first(aged)


# A function returning the expired paths under a top-level path
_Collector = Callable[[RtdbAccess, datetime, PathStats], List[str]]


def cleanup(
    access: RtdbAccess,
    *,
    dry_run: bool = False,
    now: Optional[datetime] = None,
    game_days: float = GAME_RETENTION_DAYS,
    presence_days: float = PRESENCE_RETENTION_DAYS,
    session_days: float = SESSION_RETENTION_DAYS,
    time_budget: Optional[float] = DEFAULT_TIME_BUDGET,
    batch_size: int = BATCH_SIZE,
    pause: float = BATCH_PAUSE,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> CleanupResult:
    """Delete expired entries under connection/, session/ and game/.
    With dry_run, only count them. A time_budget of None means no limit.
    An error in one path is recorded in its stats and does not stop the
    others."""
    t0 = clock()
    now = now or datetime.now(UTC)
    budget = _Budget(time_budget, clock)
    result = CleanupResult(dry_run=dry_run)
    # The small paths go first, so that a large game/ backlog cannot
    # use up the time budget before they get their turn
    steps: List[Tuple[str, float, _Collector]] = [
        ("connection", presence_days, expired_presence),
        ("session", session_days, expired_sessions),
        ("game", game_days, expired_games),
    ]
    for base, days, collect in steps:
        stats = PathStats()
        result.stats[base] = stats
        if budget.exhausted():
            result.complete = False
            continue
        try:
            paths = collect(access, now - timedelta(days=days), stats)
            if not dry_run and paths:
                if not _delete(
                    access, base, paths, stats, budget, batch_size, pause, sleep
                ):
                    result.complete = False
        except Exception as e:
            logging.warning(f"Exception [{repr(e)}] in rtdb_cleanup for {base}/")
            stats.error = repr(e)
    result.elapsed = clock() - t0
    return result


def wipe_children(
    access: RtdbAccess,
    path: str,
    *,
    dry_run: bool = False,
    time_budget: Optional[float] = None,
    batch_size: int = BATCH_SIZE,
    pause: float = BATCH_PAUSE,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> PathStats:
    """Delete every child of the path, in batches, regardless of age.
    For decommissioning an instance that no longer has any clients
    (utils/rtdb-cleanup.py --wipe); never called by the app."""
    stats = PathStats()
    keys = access.get(path, shallow=True)
    if not isinstance(keys, dict):
        return stats
    children = sorted(cast(Dict[str, Any], keys))
    stats.scanned = stats.expired = len(children)
    if not dry_run:
        _delete(
            access,
            path,
            children,
            stats,
            _Budget(time_budget, clock),
            batch_size,
            pause,
            sleep,
        )
    return stats

