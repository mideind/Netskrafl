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
from typing import (
    Any,
    Callable,
    List,
    Literal,
    Mapping,
    Optional,
    Sequence,
    Dict,
    TypeVar,
    TypedDict,
    cast,
)
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
from skraflmechanics import RackDetails, BOARD_SIZE
from skrafldb import RiddleModel


T = TypeVar("T")


# Riddle generator API endpoints
RIDDLE_ENDPOINT_DEV = "https://moves-dot-explo-dev.appspot.com/riddle"
RIDDLE_ENDPOINT_PROD = "https://moves-dot-explo-live.appspot.com/riddle"


class MovesServiceSolutionDict(TypedDict):
    """A riddle solution as it arrives from the Moves service"""

    move: str  # May contain '?x' to indicate a blank tile that means 'x'
    coord: str  # Form: "A1" for horizontal move, "1A" for vertical
    score: int
    description: str


class RiddleFromMovesServiceDict(TypedDict):
    """A riddle as it arrives from the Moves service"""

    board: List[str]  # 15 strings of 15 characters each
    rack: str  # May contain '?' to indicate a blank tile
    solution: MovesServiceSolutionDict


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


def generate_placeholder_riddle(
    locale: str, tile_scores: Dict[str, int]
) -> RiddleContentDict:
    """Generate a new riddle for the given date and locale"""
    TEST_RACK = "kfojgda"
    rack: RackDetails = [(tile, tile_scores.get(tile, 0)) for tile in TEST_RACK]
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


def riddle_from_moves_service(
    riddle_data: Optional[RiddleFromMovesServiceDict],
    tile_scores: Mapping[str, int],
) -> Optional[RiddleContentDict]:
    """Convert a riddle as received from the Moves service
    into the internal RiddleContentDict format."""
    if not riddle_data:
        return None
    try:
        board = riddle_data["board"]
        if len(board) != BOARD_SIZE or any(len(row) != BOARD_SIZE for row in board):
            raise ValueError("Invalid board size from Moves service")
        rack_str = riddle_data["rack"]
        if not (1 <= len(rack_str) <= 7):
            raise ValueError("Invalid rack size from Moves service")
        rack: RackDetails = [(tile, tile_scores.get(tile, 0)) for tile in rack_str]
        solution = riddle_data["solution"]
        max_score = solution["score"]
        if max_score <= 0:
            raise ValueError("Invalid max score from Moves service")
        return {
            "board": board,
            "rack": rack,
            "max_score": max_score,
        }
    except (KeyError, ValueError) as e:
        logging.error(f"Error processing riddle data from Moves service: {e}")
    return None


def generate_new_riddle(
    locale: str, tile_scores: Mapping[str, int]
) -> Optional[RiddleContentDict]:
    """Fetch a new riddle from the GoSkrafl server ('moves' service)
    for the given date and locale. This is served at the
    /riddle endpoint."""
    if not locale:
        logging.error("Missing locale in generate_new_riddle()")
        return None
    if PROJECT_ID == "explo-live":
        # TODO: Consider using the production endpoint for Netskrafl
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
            # Currently the moves service may take up to 20 seconds to generate a riddle,
            # so we need a longer timeout than that
            timeout=30,
        )
        response.raise_for_status()  # Raise an error for bad responses
        riddle_data: Optional[RiddleFromMovesServiceDict] = response.json()
        return riddle_from_moves_service(riddle_data, tile_scores)
    except (requests.RequestException, KeyError, ValueError) as e:
        logging.error(f"Failed to fetch riddle from {endpoint}: {e}")
    return None


def cache_if_not_none(maxsize: int = 128):
    """Cache decorator that only caches successful (non-None) results"""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
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
def get_or_create_riddle(date: str, locale: str) -> Optional[RiddleDict]:
    """Get existing riddle or create a new one, with caching"""
    # Check if riddle already exists in Firebase
    path = f"gatadagsins/{date}/{locale}/riddle"
    existing_riddle = firebase.get_data(path)
    if existing_riddle:
        # Riddle already exists, return it
        return existing_riddle

    # Not found in Firebase: attempt to fetch the riddle from the database
    tile_scores = current_tileset().scores
    riddle_from_database = RiddleModel.get_riddle(date, locale)
    if not riddle_from_database or not (
        riddle := riddle_from_moves_service(riddle_from_database.riddle, tile_scores)
    ):
        # Riddle doesn't exist, generate a new one
        # (This is an emergency fallback!)
        logging.warning(
            f"Riddle for {date}:{locale} not found in database, generating it on-the-fly"
        )
        riddle = generate_new_riddle(locale, tile_scores)
        if riddle is None:
            # All avenues exhausted, return None
            return None

    # Store the new riddle in Firebase
    if firebase.put_message(riddle, path):
        # Delete the /best path if it exists, since we have a new riddle
        firebase.put_message(None, f"gatadagsins/{date}/{locale}/best")
    else:
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
    riddle_data = get_or_create_riddle(date, lc)

    if riddle_data is None:
        # If riddle generation failed, return an error
        return jsonify(ok=False, error="Failed to fetch or generate riddle")

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
    locale = to_supported_locale(rq.get("locale", ""))
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
    if not (2 <= len(word) <= BOARD_SIZE):
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
                group_best = BestDict(
                    score=0, player="", word="", coord="", timestamp=""
                )
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
