"""
Entity wrappers for PostgreSQL models.

These classes wrap SQLAlchemy model instances to implement
the entity protocols defined in src/db/protocols.py.
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any, cast
from datetime import datetime
import json

from .models import (
    User as UserModel,
    Game as GameModel,
    EloRating as EloRatingModel,
    Stats as StatsModel,
    Chat as ChatModel,
    Riddle as RiddleModel,
)

from ..protocols import MoveDict, PrefsDict


class UserEntity:
    """Wrapper around PostgreSQL User model implementing UserEntityProtocol."""

    __slots__ = ("_model",)

    def __init__(self, model: UserModel) -> None:
        self._model = model

    @property
    def key_id(self) -> str:
        return self._model.id

    @property
    def nickname(self) -> str:
        return self._model.nickname

    @property
    def email(self) -> str:
        return self._model.email

    @property
    def image(self) -> str:
        return self._model.image

    @property
    def account(self) -> Optional[str]:
        return self._model.account

    @property
    def plan(self) -> Optional[str]:
        return self._model.plan

    @property
    def nick_lc(self) -> Optional[str]:
        return self._model.nick_lc

    @property
    def name_lc(self) -> Optional[str]:
        return self._model.name_lc

    @property
    def inactive(self) -> bool:
        return self._model.inactive

    @property
    def locale(self) -> Optional[str]:
        return self._model.locale

    @property
    def location(self) -> Optional[str]:
        return self._model.location

    @property
    def prefs(self) -> PrefsDict:
        return cast(PrefsDict, self._model.prefs or {})

    @property
    def timestamp(self) -> datetime:
        return self._model.timestamp

    @property
    def last_login(self) -> Optional[datetime]:
        return self._model.last_login

    @property
    def ready(self) -> bool:
        return self._model.ready

    @property
    def ready_timed(self) -> bool:
        return self._model.ready_timed

    @property
    def chat_disabled(self) -> bool:
        return self._model.chat_disabled

    @property
    def elo(self) -> int:
        return self._model.elo

    @property
    def human_elo(self) -> int:
        return self._model.human_elo

    @property
    def manual_elo(self) -> int:
        return self._model.manual_elo

    @property
    def highest_score(self) -> int:
        return self._model.highest_score

    @property
    def highest_score_game(self) -> Optional[str]:
        return self._model.highest_score_game

    @property
    def best_word(self) -> Optional[str]:
        return self._model.best_word

    @property
    def best_word_score(self) -> int:
        return self._model.best_word_score

    @property
    def best_word_game(self) -> Optional[str]:
        return self._model.best_word_game

    @property
    def games(self) -> int:
        return self._model.games

    # Access to underlying model for repository operations
    @property
    def _pg_model(self) -> UserModel:
        return self._model


class GameEntity:
    """Wrapper around PostgreSQL Game model implementing GameEntityProtocol."""

    __slots__ = ("_model", "_moves_cache")

    def __init__(self, model: GameModel) -> None:
        self._model = model
        self._moves_cache: Optional[List[MoveDict]] = None

    @property
    def key_id(self) -> str:
        return self._model.id

    @property
    def player0_id(self) -> Optional[str]:
        return self._model.player0_id

    @property
    def player1_id(self) -> Optional[str]:
        return self._model.player1_id

    @property
    def locale(self) -> Optional[str]:
        return self._model.locale

    @property
    def rack0(self) -> str:
        return self._model.rack0

    @property
    def rack1(self) -> str:
        return self._model.rack1

    @property
    def score0(self) -> int:
        return self._model.score0

    @property
    def score1(self) -> int:
        return self._model.score1

    @property
    def to_move(self) -> int:
        return self._model.to_move

    @property
    def robot_level(self) -> int:
        return self._model.robot_level

    @property
    def over(self) -> bool:
        return self._model.over

    @property
    def timestamp(self) -> datetime:
        return self._model.timestamp

    @property
    def ts_last_move(self) -> Optional[datetime]:
        return self._model.ts_last_move

    @property
    def moves(self) -> List[MoveDict]:
        """Convert JSONB moves to MoveDict list."""
        if self._moves_cache is not None:
            return self._moves_cache
        self._moves_cache = [
            MoveDict(
                coord=m.get("coord", ""),
                tiles=m.get("tiles", ""),
                score=m.get("score", 0),
                rack=m.get("rack"),
                timestamp=m.get("timestamp"),
            )
            for m in (self._model.moves or [])
        ]
        return self._moves_cache

    @property
    def irack0(self) -> Optional[str]:
        return self._model.irack0

    @property
    def irack1(self) -> Optional[str]:
        return self._model.irack1

    @property
    def prefs(self) -> Optional[PrefsDict]:
        return cast(Optional[PrefsDict], self._model.prefs)

    @property
    def tile_count(self) -> Optional[int]:
        return self._model.tile_count

    @property
    def elo0(self) -> Optional[int]:
        return self._model.elo0

    @property
    def elo1(self) -> Optional[int]:
        return self._model.elo1

    @property
    def elo0_adj(self) -> Optional[int]:
        return self._model.elo0_adj

    @property
    def elo1_adj(self) -> Optional[int]:
        return self._model.elo1_adj

    @property
    def human_elo0(self) -> Optional[int]:
        return self._model.human_elo0

    @property
    def human_elo1(self) -> Optional[int]:
        return self._model.human_elo1

    @property
    def human_elo0_adj(self) -> Optional[int]:
        return self._model.human_elo0_adj

    @property
    def human_elo1_adj(self) -> Optional[int]:
        return self._model.human_elo1_adj

    @property
    def manual_elo0(self) -> Optional[int]:
        return self._model.manual_elo0

    @property
    def manual_elo1(self) -> Optional[int]:
        return self._model.manual_elo1

    @property
    def manual_elo0_adj(self) -> Optional[int]:
        return self._model.manual_elo0_adj

    @property
    def manual_elo1_adj(self) -> Optional[int]:
        return self._model.manual_elo1_adj

    def manual_wordcheck(self) -> bool:
        """Check if manual wordcheck is enabled for this game."""
        prefs = self._model.prefs or {}
        return prefs.get("manual", False)

    # Access to underlying model for repository operations
    @property
    def _pg_model(self) -> GameModel:
        return self._model


class EloEntity:
    """Wrapper around PostgreSQL EloRating model implementing EloEntityProtocol."""

    __slots__ = ("_model",)

    def __init__(self, model: EloRatingModel) -> None:
        self._model = model

    @property
    def key_id(self) -> str:
        return f"{self._model.user_id}:{self._model.locale}"

    @property
    def locale(self) -> str:
        return self._model.locale

    @property
    def user_id(self) -> str:
        return self._model.user_id

    @property
    def timestamp(self) -> datetime:
        return self._model.timestamp

    @property
    def elo(self) -> int:
        return self._model.elo

    @property
    def human_elo(self) -> int:
        return self._model.human_elo

    @property
    def manual_elo(self) -> int:
        return self._model.manual_elo

    # Access to underlying model for repository operations
    @property
    def _pg_model(self) -> EloRatingModel:
        return self._model


class StatsEntity:
    """Wrapper around PostgreSQL Stats model implementing StatsEntityProtocol."""

    __slots__ = ("_model",)

    def __init__(self, model: StatsModel) -> None:
        self._model = model

    @property
    def key_id(self) -> str:
        return str(self._model.id)

    @property
    def user_id(self) -> Optional[str]:
        return self._model.user_id

    @property
    def robot_level(self) -> int:
        return self._model.robot_level

    @property
    def timestamp(self) -> datetime:
        return self._model.timestamp

    @property
    def games(self) -> int:
        return self._model.games

    @property
    def human_games(self) -> int:
        return self._model.human_games

    @property
    def manual_games(self) -> int:
        return self._model.manual_games

    @property
    def elo(self) -> int:
        return self._model.elo

    @property
    def human_elo(self) -> int:
        return self._model.human_elo

    @property
    def manual_elo(self) -> int:
        return self._model.manual_elo

    @property
    def score(self) -> int:
        return self._model.score

    @property
    def human_score(self) -> int:
        return self._model.human_score

    @property
    def manual_score(self) -> int:
        return self._model.manual_score

    @property
    def score_against(self) -> int:
        return self._model.score_against

    @property
    def human_score_against(self) -> int:
        return self._model.human_score_against

    @property
    def manual_score_against(self) -> int:
        return self._model.manual_score_against

    @property
    def wins(self) -> int:
        return self._model.wins

    @property
    def losses(self) -> int:
        return self._model.losses

    @property
    def human_wins(self) -> int:
        return self._model.human_wins

    @property
    def human_losses(self) -> int:
        return self._model.human_losses

    @property
    def manual_wins(self) -> int:
        return self._model.manual_wins

    @property
    def manual_losses(self) -> int:
        return self._model.manual_losses

    # Access to underlying model for repository operations
    @property
    def _pg_model(self) -> StatsModel:
        return self._model


class ChatEntity:
    """Wrapper around PostgreSQL Chat model implementing ChatEntityProtocol."""

    __slots__ = ("_model",)

    def __init__(self, model: ChatModel) -> None:
        self._model = model

    @property
    def key_id(self) -> str:
        return str(self._model.id)

    @property
    def channel(self) -> str:
        return self._model.channel

    @property
    def user_id(self) -> str:
        return self._model.user_id

    @property
    def recipient_id(self) -> Optional[str]:
        return self._model.recipient_id

    @property
    def timestamp(self) -> datetime:
        return self._model.timestamp

    @property
    def msg(self) -> str:
        return self._model.msg

    # Access to underlying model for repository operations
    @property
    def _pg_model(self) -> ChatModel:
        return self._model


class RiddleEntity:
    """Wrapper around PostgreSQL Riddle model implementing RiddleEntityProtocol."""

    __slots__ = ("_model", "_riddle_cache")

    def __init__(self, model: RiddleModel) -> None:
        self._model = model
        self._riddle_cache: Optional[Dict[str, Any]] = None

    @property
    def key_id(self) -> str:
        return f"{self._model.date}:{self._model.locale}"

    @property
    def date(self) -> str:
        return self._model.date

    @property
    def locale(self) -> str:
        return self._model.locale

    @property
    def riddle_json(self) -> str:
        return self._model.riddle_json

    @property
    def riddle(self) -> Optional[Dict[str, Any]]:
        """Parse riddle_json and return as dict."""
        if self._riddle_cache is not None:
            return self._riddle_cache
        try:
            self._riddle_cache = json.loads(self._model.riddle_json)
        except (json.JSONDecodeError, TypeError):
            self._riddle_cache = None
        return self._riddle_cache

    @property
    def created(self) -> datetime:
        return self._model.created

    @property
    def version(self) -> int:
        return self._model.version

    # Access to underlying model for repository operations
    @property
    def _pg_model(self) -> RiddleModel:
        return self._model
