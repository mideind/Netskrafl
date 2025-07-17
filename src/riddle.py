"""

    Riddle API for Gáta Dagsins (Riddle of the Day) functionality

    Copyright © 2025 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl


    This module contains the API entry points for the Gáta Dagsins feature.

"""

from __future__ import annotations

from typing import Any, List, Literal, Sequence, Dict, TypedDict
from functools import wraps, lru_cache

from flask import Blueprint, request
from config import ResponseType, RouteType
from basics import jsonify, auth_required, RequestData
import firebase
from languages import (
    set_locale,
    to_supported_locale,
    current_alphabet,
    current_tileset,
)
from skraflgame import TwoLetterGroupTuple, two_letter_words
from skraflmechanics import RackDetails


class RiddleContentDict(TypedDict):
    """The meat of the riddle"""
    board: List[str]
    rack: RackDetails
    max_score: int


class RiddleDict(RiddleContentDict, total=False):
    """The entire information about today's riddle that is
    sent to the client, including static metadata"""
    alphabet: str
    tile_scores: Dict[str, int]
    two_letter_words: TwoLetterGroupTuple
    board_type: Literal["standard"] | Literal["explo"]


# Only allow POST requests to the API endpoints
_ONLY_POST: Sequence[str] = ["POST"]

# Register the Flask blueprint for the riddle APIs
riddle = riddle_blueprint = Blueprint("riddle", __name__)


def riddle_route(route: str, methods: Sequence[str] = _ONLY_POST) -> Any:
    """Decorator for riddle API routes; checks that the name of the route function ends with '_api'"""

    def decorator(f: RouteType) -> RouteType:

        assert f.__name__.endswith(
            "_api"
        ), f"Name of riddle API function '{f.__name__}' must end with '_api'"

        @riddle.route(route, methods=methods)
        @wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> ResponseType:
            return f(*args, **kwargs)

        return wrapper

    return decorator


def generate_riddle(locale: str, tile_scores: Dict[str, int]) -> RiddleContentDict:
    """Generate a new riddle for the given date and locale"""
    # TODO: Implement riddle generation logic here
    # For now, return a placeholder riddle
    TEST_RACK = "iiarðu?"
    rack: RackDetails = [
        (tile, tile_scores.get(tile, 0)) for tile in TEST_RACK
    ]
    # For now, generate a placeholder board
    board: List[str] = [
        ".......léttirðu",
        ".......y.......",
        ".......k.bóla..",
        ".....klif.salan",
        "....rauðar.n...",
        "...sálm..eggs..",
        ".......föx.tó..",
        "....vafa....m..",
        "...né.j.....i..",
        ".....þú........",
        "...drekum......",
        "..ná.kara......",
        "..ei.s.tí......",
        "hringt.u.......",
        "...s...r.......",
    ]
    max_score: int = 50  # Placeholder for maximum score
    return {
        "rack": rack,
        "board": board,
        "max_score": max_score,
    }


@lru_cache(maxsize=3)
def get_or_create_riddle(date: str, locale: str) -> RiddleDict:
    """Get existing riddle or create a new one, with caching"""
    # Check if riddle already exists in Firebase
    path = f"gatadagsins/{date}/{locale}/riddle"
    existing_riddle = firebase.get_data(path)

    if False and existing_riddle:  # TODO: Development only, remove later
        # Riddle already exists, return it
        return existing_riddle

    # Riddle doesn't exist, generate a new one
    tile_scores = current_tileset().scores
    riddle = RiddleDict(**generate_riddle(locale, tile_scores))

    # Store the new riddle in Firebase
    if not firebase.put_message(riddle, path):
        # If Firebase storage fails, still return the generated riddle
        # but it won't be persisted
        pass

    # Augment the riddle data with static locale-specific information
    # required by the client, but which does not need to be stored in Firebase
    riddle["alphabet"] = current_alphabet().order
    riddle["tile_scores"] = tile_scores
    riddle["board_type"] = "standard"
    riddle["two_letter_words"] = two_letter_words(locale)
    return riddle


@riddle_route("/gatadagsins/riddle")
@auth_required(ok=False)
def riddle_api() -> ResponseType:
    """Handle requests for the daily riddle"""
    rq = RequestData(request)

    # Decode POST parameters
    date = rq.get("date", "")
    locale = rq.get("locale", "")

    # Validate required parameters
    if not date:
        return jsonify(ok=False, error="Missing required parameter: date")
    if not locale:
        return jsonify(ok=False, error="Missing required parameter: locale")

    # Select the correct locale for the current thread
    lc = to_supported_locale(locale)
    set_locale(lc)

    # Get or create riddle using cached function
    riddle_data = get_or_create_riddle(date, locale)

    # Return the riddle
    return jsonify(ok=True, riddle=riddle_data)


@riddle_route("/gatadagsins/submit")
@auth_required(ok=False)
def submit_api() -> ResponseType:
    """Handle an improved move from a player who is working on the riddle"""
    _ = RequestData(request)

    # TODO: Add move submission logic here
    # For now, return a placeholder response
    return jsonify(ok=True, message="Submit move endpoint ready")
