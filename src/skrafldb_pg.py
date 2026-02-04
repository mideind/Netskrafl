"""
Skrafldb PostgreSQL implementation - STUB

Copyright © 2025 Miðeind ehf.

This module will contain the PostgreSQL implementation of the skrafldb API.
Currently a stub that re-exports shared types from the NDB implementation
and raises NotImplementedError for operations that haven't been migrated yet.

The PostgreSQL backend uses SQLAlchemy ORM and the implementation in
src/db/postgresql/ for the actual database operations.
"""

from __future__ import annotations

# Re-export all shared type definitions from the NDB module
# These TypedDicts and dataclasses are backend-agnostic
from skrafldb_ndb import (
    # Type definitions (shared across backends)
    PrefsDict,
    ChallengeTuple,
    StatsDict,
    StatsResults,
    LiveGameDict,
    FinishedGameDict,
    ZombieGameDict,
    ChatModelHistoryDict,
    ListPrefixDict,
    RatingDict,
    RatingForLocaleDict,
    EloDict,
    DEFAULT_ELO_DICT,
    # Helper functions (can be shared)
    interleave,
)

# TODO: The following need PostgreSQL implementations:
# - Client, Context (session management)
# - Query, Future, Key, Model (ORM abstractions)
# - iter_q, put_multi, delete_multi (batch operations)
# - All *Model classes (UserModel, GameModel, etc.)


class _NotImplementedMeta(type):
    """Metaclass that raises NotImplementedError on any access."""

    def __getattr__(cls, name: str):
        raise NotImplementedError(
            f"PostgreSQL backend: {cls.__name__}.{name} not yet implemented. "
            "Set DATABASE_BACKEND=ndb to use the NDB backend."
        )

    def __call__(cls, *args, **kwargs):
        raise NotImplementedError(
            f"PostgreSQL backend: {cls.__name__} not yet implemented. "
            "Set DATABASE_BACKEND=ndb to use the NDB backend."
        )


class Client(metaclass=_NotImplementedMeta):
    """PostgreSQL Client - not yet implemented."""

    pass


class Context(metaclass=_NotImplementedMeta):
    """PostgreSQL Context - not yet implemented."""

    pass


class Unique(metaclass=_NotImplementedMeta):
    """PostgreSQL Unique ID generator - not yet implemented."""

    pass


class Query(metaclass=_NotImplementedMeta):
    """PostgreSQL Query - not yet implemented."""

    pass


class Future(metaclass=_NotImplementedMeta):
    """PostgreSQL Future - not yet implemented."""

    pass


class Key(metaclass=_NotImplementedMeta):
    """PostgreSQL Key - not yet implemented."""

    pass


class Model(metaclass=_NotImplementedMeta):
    """PostgreSQL Model base - not yet implemented."""

    pass


class UserModel(metaclass=_NotImplementedMeta):
    """PostgreSQL UserModel - not yet implemented."""

    pass


class EloModel(metaclass=_NotImplementedMeta):
    """PostgreSQL EloModel - not yet implemented."""

    pass


class EloModelFuture(metaclass=_NotImplementedMeta):
    """PostgreSQL EloModelFuture - not yet implemented."""

    pass


class RobotModel(metaclass=_NotImplementedMeta):
    """PostgreSQL RobotModel - not yet implemented."""

    pass


class MoveModel(metaclass=_NotImplementedMeta):
    """PostgreSQL MoveModel - not yet implemented."""

    pass


class ImageModel(metaclass=_NotImplementedMeta):
    """PostgreSQL ImageModel - not yet implemented."""

    pass


class GameModel(metaclass=_NotImplementedMeta):
    """PostgreSQL GameModel - not yet implemented."""

    pass


class GameModelFuture(metaclass=_NotImplementedMeta):
    """PostgreSQL GameModelFuture - not yet implemented."""

    pass


class FavoriteModel(metaclass=_NotImplementedMeta):
    """PostgreSQL FavoriteModel - not yet implemented."""

    pass


class ChallengeModel(metaclass=_NotImplementedMeta):
    """PostgreSQL ChallengeModel - not yet implemented."""

    pass


class StatsModel(metaclass=_NotImplementedMeta):
    """PostgreSQL StatsModel - not yet implemented."""

    pass


class RatingModel(metaclass=_NotImplementedMeta):
    """PostgreSQL RatingModel - not yet implemented."""

    pass


class ChatModel(metaclass=_NotImplementedMeta):
    """PostgreSQL ChatModel - not yet implemented."""

    pass


class ChatModelFuture(metaclass=_NotImplementedMeta):
    """PostgreSQL ChatModelFuture - not yet implemented."""

    pass


class ZombieModel(metaclass=_NotImplementedMeta):
    """PostgreSQL ZombieModel - not yet implemented."""

    pass


class PromoModel(metaclass=_NotImplementedMeta):
    """PostgreSQL PromoModel - not yet implemented."""

    pass


class CompletionModel(metaclass=_NotImplementedMeta):
    """PostgreSQL CompletionModel - not yet implemented."""

    pass


class BlockModel(metaclass=_NotImplementedMeta):
    """PostgreSQL BlockModel - not yet implemented."""

    pass


class ReportModel(metaclass=_NotImplementedMeta):
    """PostgreSQL ReportModel - not yet implemented."""

    pass


class TransactionModel(metaclass=_NotImplementedMeta):
    """PostgreSQL TransactionModel - not yet implemented."""

    pass


class SubmissionModel(metaclass=_NotImplementedMeta):
    """PostgreSQL SubmissionModel - not yet implemented."""

    pass


class RiddleModel(metaclass=_NotImplementedMeta):
    """PostgreSQL RiddleModel - not yet implemented."""

    pass


def iter_q(*args, **kwargs):
    """PostgreSQL iter_q - not yet implemented."""
    raise NotImplementedError(
        "PostgreSQL backend: iter_q not yet implemented. "
        "Set DATABASE_BACKEND=ndb to use the NDB backend."
    )


def put_multi(*args, **kwargs):
    """PostgreSQL put_multi - not yet implemented."""
    raise NotImplementedError(
        "PostgreSQL backend: put_multi not yet implemented. "
        "Set DATABASE_BACKEND=ndb to use the NDB backend."
    )


def delete_multi(*args, **kwargs):
    """PostgreSQL delete_multi - not yet implemented."""
    raise NotImplementedError(
        "PostgreSQL backend: delete_multi not yet implemented. "
        "Set DATABASE_BACKEND=ndb to use the NDB backend."
    )
