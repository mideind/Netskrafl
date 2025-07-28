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

import logging
from typing import Any, Callable, List, Literal, Optional, Sequence, Dict, TypedDict, cast
from functools import wraps

import requests
from flask import Blueprint, request

from config import PROJECT_ID, MOVES_AUTH_KEY, ResponseType, RouteType
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


# Riddle generator API endpoints
RIDDLE_ENDPOINT_DEV = "https://moves-dot-explo-dev.appspot.com/riddle"
RIDDLE_ENDPOINT_PROD = "https://moves-dot-explo-live.appspot.com/riddle"


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


class BestDict(TypedDict):
    """Dictionary to hold the best-scoring move and its player"""
    score: int
    player: str
    word: str  # Note: may contain '?x' to indicate a blank tile that means 'x'
    coord: str  # Form: "A1" for horizontal move, "1A" for vertical
    timestamp: str  # ISO 8601 format


class RiddleWordDict(TypedDict):
    word: str
    score: int
    coord: str
    timestamp: str


class SubmitMoveDict(TypedDict):
    """Moves submitted from clients"""
    date: str
    locale: str
    userId: str
    groupId: str
    move: RiddleWordDict


# Cache of current global best scores
_GLOBAL_BEST_CACHE: Dict[str, Dict[str, BestDict]] = {}

# Only allow POST requests to API endpoints
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
    max_score: int = 77  # Placeholder for maximum score
    return {
        "rack": rack,
        "board": board,
        "max_score": max_score,
    }


def generate_riddle_2(locale: str, tile_scores: Dict[str, int]) -> RiddleContentDict:
    """Generate a new riddle for the given date and locale"""
    TEST_RACK = "kfojgda"
    rack: RackDetails = [
        (tile, tile_scores.get(tile, 0)) for tile in TEST_RACK
    ]
    # For now, generate a placeholder board
    board: List[str] = [
        ".......n.k....n",
        ".......á.ær...e",
        "..b....m.fénist",
        "..y....a.að...k",
        "..l.a..n..i...e",
        "..talglaðir...p",
        "..u.r.........P",
        "...varmt.......",
        "....u..........",
        "....t..........",
        "....t..........",
        "...............",
        "...............",
        "...............",
        "...............",
    ]
    max_score: int = 108  # Placeholder for maximum score
    return {
        "rack": rack,
        "board": board,
        "max_score": max_score,
    }


def generate_new_riddle(locale: str) -> Optional[RiddleContentDict]:
    """Fetch a new riddle from the GoSkrafl server ('moves' service)
    for the given date and locale. This is served at the
    /riddle endpoint."""
    if not locale:
        logging.error("Missing locale in generate_new_riddle()")
        return None
    if PROJECT_ID == "explo-live":
        endpoint = RIDDLE_ENDPOINT_PROD
    else:
        # For Netskrafl and for development, use the dev endpoint
        endpoint = RIDDLE_ENDPOINT_DEV
    try:
        response = requests.post(
            endpoint,
            # Specify an authorization header with the Moves service key,
            # retrieved from the Secret Manager
            headers={
                "Authorization": f"Bearer {MOVES_AUTH_KEY}",
            },
            json={
                "locale": locale,
            },
            timeout=20,  # 20 seconds timeout
        )
        response.raise_for_status()  # Raise an error for bad responses
        riddle_data: Optional[RiddleContentDict] = response.json()
        if not isinstance(riddle_data, dict):
            logging.error(f"Invalid riddle data format: {riddle_data}")
            return None
        # Ensure the riddle data has the required fields
        if not all(key in riddle_data for key in ["rack", "board", "max_score"]):
            logging.error(f"Riddle data missing required fields: {riddle_data}")
            return None
        # Move the response data to a clean RiddleContentDict instance
        riddle = RiddleContentDict(
            rack=riddle_data["rack"],
            board=riddle_data["board"],
            max_score=riddle_data["max_score"],
        )
        return riddle
    except requests.RequestException as e:
        logging.error(f"Failed to fetch riddle from {endpoint}: {e}")
        return None


def cache_if_not_none(maxsize: int = 128):
    """Cache decorator that only caches successful (non-None) results"""
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        cache: Dict[str, Any] = {}

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = str(args) + str(sorted(kwargs.items()))

            # Return cached result if available
            if key in cache:
                return cache[key]

            # Call function and cache only if not None
            result = func(*args, **kwargs)
            if result is not None:
                # Simple LRU: remove oldest if at capacity
                if len(cache) >= maxsize:
                    cache.pop(next(iter(cache)))
                cache[key] = result

            return result

        return wrapper
    return decorator


@cache_if_not_none(maxsize=3)
def get_or_create_riddle(date: str, locale: str) -> RiddleDict:
    """Get existing riddle or create a new one, with caching"""
    # Check if riddle already exists in Firebase
    path = f"gatadagsins/{date}/{locale}/riddle"
    existing_riddle = firebase.get_data(path)

    if False and existing_riddle:  # TODO: Development only, remove later
        # Riddle already exists, return it
        return existing_riddle

    tile_scores = current_tileset().scores

    # Riddle doesn't exist, generate a new one
    riddle = generate_new_riddle(locale)
    if riddle is None:
        # If fetching the riddle fails, generate a placeholder riddle
        # !!! TODO: This is temporary; eventually retry and/or return None
        logging.warning(f"Failed to fetch riddle for {date}/{locale}, generating placeholder")
        riddle = generate_riddle_2(locale, tile_scores)

    # Store the new riddle in Firebase
    if not firebase.put_message(riddle, path):
        # If Firebase storage fails, still return the generated riddle
        # but it won't be persisted
        logging.error(f"Failed to store riddle for {date}/{locale} in Firebase")

    # Augment the riddle data with static locale-specific information
    # required by the client, but which does not need to be stored in Firebase
    full_riddle = RiddleDict(**riddle)
    full_riddle["alphabet"] = current_alphabet().order
    full_riddle["tile_scores"] = tile_scores
    full_riddle["board_type"] = "standard"
    full_riddle["two_letter_words"] = two_letter_words(locale)
    return full_riddle


@riddle_route("/gatadagsins/riddle")
@auth_required(ok=False)
def riddle_api() -> ResponseType:
    """Handle requests for the daily riddle"""
    rq = RequestData(request)

    # Decode POST parameters
    date = rq.get("date", "")
    locale = rq.get("locale", "")

    # Validate required parameters
    if len(date) != 10 or date[4] != "-" or date[7] != "-":
        # The date format is expected to be YYYY-MM-DD
        return jsonify(ok=False, error="Invalid parameter: date")
    if not locale:
        return jsonify(ok=False, error="Invalid parameter: locale")

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
    """Handle a (presumably improved) move from a player
    who is working on the riddle"""
    rq = RequestData(request)
    # The request should contain the following:
    # date: str
    # locale: str
    # userId: str
    # groupId: str
    # move: {
    #   word: str
    #   score: int
    #   coord: str
    #   timestamp: str
    # }
    date = rq.get("date", "")
    locale = to_supported_locale(rq.get("locale", "is_IS"))
    userId = rq.get("userId", "")
    groupId = rq.get("groupId", "")
    move: RiddleWordDict = cast(RiddleWordDict, rq.get("move", {}))
    if not date or not userId or not move or not move.get("word"):
        return jsonify(ok=False, error="Missing required parameters")

    # Validate the move data
    score = move.get("score", 0)
    if score <= 0:
        return jsonify(ok=False, error="Invalid score")
    word = move.get("word", "")
    if not (2 <= len(word) <= 15):
        return jsonify(ok=False, error="Invalid word")
    coord = move.get("coord", "")
    if not (2 <= len(coord) <= 3):
        return jsonify(ok=False, error="Invalid coordinate")
    timestamp = move.get("timestamp", "")
    if not timestamp:
        return jsonify(ok=False, error="Missing timestamp")

    update = False
    message = ""
    try:
        path = f"gatadagsins/{date}/{locale}/best"
        best: Optional[BestDict] = _GLOBAL_BEST_CACHE.get(date, {}).get(locale)
        if not best:
            # If we don't have the global best cached, fetch it from Firebase
            best = firebase.get_data(path)
            if not best:
                # If no global best already exists, assign a null default
                best = BestDict(score=0, player="", word="", coord="", timestamp="")
        if score > best.get("score", 0):
            # If the submitted move is better than the current global best,
            # update the global best
            best = BestDict(
                score=score,
                player=userId,
                word=word,
                coord=coord,
                timestamp=timestamp,
            )
            _GLOBAL_BEST_CACHE.setdefault(date, {})[locale] = best
            firebase.put_message(best, path)
            message = "Global best score updated"
            update = True
        # If the user belongs to a group, also update the group's best.
        # Since there can be many groups, we don't cache the best scores
        # for groups, but fetch them directly from Firebase.
        if groupId:
            group_path = f"gatadagsins/{date}/{locale}/group/{groupId}/best"
            group_best: Optional[BestDict] = firebase.get_data(group_path)
            if not group_best:
                # If no group best already exists, assign a null default
                group_best = BestDict(score=0, player="", word="", coord="", timestamp="")
            if score > group_best.get("score", 0):
                # If the submitted move is better than the current group best,
                # update the group's best
                group_best = BestDict(
                    score=score,
                    player=userId,
                    word=word,
                    coord=coord,
                    timestamp=timestamp,
                )
                firebase.put_message(group_best, group_path)
                if not message:
                    message = "Group best score updated"
                update = True
    except Exception:
        # If something goes wrong, return an error
        return jsonify(ok=False, error="Submission failed")
    # If we reach here, the submission was successful,
    # but may not have updated anything
    return jsonify(ok=True, update=update, message=message or "No update")
