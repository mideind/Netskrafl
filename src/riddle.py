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

import logging
from datetime import date, datetime, timezone
from functools import wraps

from flask.typing import ResponseReturnValue
import requests
from flask import Blueprint, request

from config import PROJECT_ID, MOVES_AUTH_KEY, ResponseType, RouteType
from basics import current_user_id, jsonify, auth_required, RequestData
import firebase
from languages import (
    set_locale,
    to_supported_locale,
    current_alphabet,
    current_tileset,
)
from skraflgame import TwoLetterGroupTuple, two_letter_words
from skraflmechanics import (
    RackDetails,
    BOARD_SIZE,
    State,
    Board,
    Move,
    Error,
)
from skrafldb import RiddleModel


T = TypeVar("T")


# Riddle generator API endpoints
RIDDLE_ENDPOINT_DEV = "https://moves-dot-explo-dev.appspot.com/riddle"
RIDDLE_ENDPOINT_PROD = "https://moves-dot-explo-live.appspot.com/riddle"

# How many entries (max) in the leaderboard?
LEADERBOARD_ENTRIES = 50


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


class SolutionDict(TypedDict):
    """A riddle solution, as sent to the client"""

    word: str
    coord: str


class RiddleDict(RiddleContentDict, total=False):
    """The entire information about today's riddle that is
    sent to the client, including static metadata"""

    alphabet: str
    tile_scores: Dict[str, int]
    two_letter_words: TwoLetterGroupTuple
    board_type: Literal["standard"] | Literal["explo"]
    solution: SolutionDict


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


class LeaderboardEntry(TypedDict):
    """A leaderboard entry for a user's best score on a riddle"""

    userId: str
    displayName: str
    score: int
    timestamp: str


LeaderboardDict = Dict[str, LeaderboardEntry]


class RiddleAchievement(TypedDict):
    """A user's achievement for a specific riddle"""

    score: int
    word: str
    coord: str
    timestamp: str
    isTopScore: bool


class UserRiddleStats(TypedDict):
    """A user's streak statistics for Gáta Dagsins"""

    currentStreak: int
    longestStreak: int
    topScoreStreak: int
    lastPlayedDate: str
    totalDaysPlayed: int
    totalTopScores: int


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
        def wrapper(*args: Any, **kwargs: Any) -> ResponseReturnValue:
            return f(*args, **kwargs)

        return wrapper

    return decorator


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
def riddle_max_score(date: str, locale: str) -> Optional[int]:
    """Get the max possible score for the riddle on the given date and locale"""
    path = f"gatadagsins/{date}/{locale}/riddle/max_score"
    max_score: Optional[int] = firebase.get_data(path)
    return max_score


@cache_if_not_none(maxsize=3)
def get_or_create_riddle(
    date: str, locale: str, is_today: bool
) -> Optional[RiddleDict]:
    """Get existing riddle or create a new one, with caching"""
    # Check if riddle already exists in Firebase
    path = f"gatadagsins/{date}/{locale}/riddle"
    tile_scores = current_tileset().scores
    riddle: Optional[RiddleContentDict] = None
    solution: Optional[MovesServiceSolutionDict] = None
    riddle_from_database: Optional[RiddleModel] = None

    if is_today:
        # Today's riddle is likely to be already in Firebase: check there first
        riddle = firebase.get_data(path)
    else:
        # For previous days, always fetch from the database, since we need
        # to return the solution as well
        riddle_from_database = RiddleModel.get_riddle(
            date, locale
        )
        if riddle_from_database:
            riddle = riddle_from_moves_service(riddle_from_database.riddle, tile_scores)
            solution = riddle_from_database.riddle["solution"]
        if riddle is None:
            logging.error(f"Riddle for {date}:{locale} not found in database")
            return None

    if not riddle:
        # Not found in Firebase: attempt to fetch the riddle from the database
        riddle_from_database = RiddleModel.get_riddle(
            date, locale
        )
        if not riddle_from_database or not (
            riddle := riddle_from_moves_service(
                riddle_from_database.riddle, tile_scores
            )
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
    if solution is not None:
        # Translate to the solution format expected by the client
        full_riddle["solution"] = SolutionDict(
            word=solution["move"], coord=solution["coord"]
        )
    return full_riddle


def update_user_achievement(
    user_id: str,
    date: str,
    locale: str,
    score: int,
    word: str,
    coord: str,
    timestamp: str,
    is_top_score: bool,
) -> tuple[bool, bool]:
    """Update user's achievement for this riddle.
    Returns a tuple (updated, newly_achieved_top_score):
    - updated: True if the user's score improved
    - newly_achieved_top_score: True if the user achieved top score for the first time
    """
    achievement_path = f"gatadagsins/{date}/{locale}/achievements/{user_id}"
    updated = False
    newly_achieved_top = False

    def transaction_update(
        current_data: Optional[RiddleAchievement],
    ) -> RiddleAchievement:
        """Transaction function to update achievement atomically"""
        nonlocal updated, newly_achieved_top
        achievement: RiddleAchievement = current_data or RiddleAchievement(
            score=0, word="", coord="", timestamp="", isTopScore=False
        )
        if score > achievement.get("score", 0):
            # Only update if the new score is better
            # Check if this is a new top score achievement
            if is_top_score and not achievement.get("isTopScore", False):
                newly_achieved_top = True
            achievement = RiddleAchievement(
                score=score,
                word=word,
                coord=coord,
                timestamp=timestamp,
                isTopScore=is_top_score,
            )
            # Note that this is a significant update, i.e. improving the user's best
            updated = True
        return achievement

    firebase.run_transaction(achievement_path, transaction_update)
    return updated, newly_achieved_top


def update_user_streak_stats(
    user_id: str, locale: str, date_str: str, achieved_top_score: bool
) -> None:
    """Update user's streak statistics using a Firebase transaction"""
    stats_path = f"gatadagsins/users/{locale}/{user_id}/stats"

    def transaction_update(current_data: Optional[UserRiddleStats]) -> UserRiddleStats:
        """Transaction function to update streak stats atomically"""
        stats: UserRiddleStats = current_data or UserRiddleStats(
            currentStreak=0,
            longestStreak=0,
            topScoreStreak=0,
            lastPlayedDate="",
            totalDaysPlayed=0,
            totalTopScores=0,
        )

        # Check if this is a new day
        last_date_str = stats.get("lastPlayedDate", "")
        if last_date_str != date_str:
            # Yes, new day: update streak info
            if last_date_str:
                last_date = date.fromisoformat(last_date_str)
                ref_date = date.fromisoformat(date_str)
                days_diff = (ref_date - last_date).days

                if days_diff == 1:
                    # Consecutive day
                    stats["currentStreak"] = stats.get("currentStreak", 0) + 1
                else:
                    # Streak broken
                    stats["currentStreak"] = 1
                    stats["topScoreStreak"] = 0
            else:
                # First time playing
                stats["currentStreak"] = 1

            # Update longest streak
            stats["longestStreak"] = max(
                stats.get("longestStreak", 0), stats["currentStreak"]
            )

            # Update total days played
            stats["totalDaysPlayed"] = stats.get("totalDaysPlayed", 0) + 1

            # Update last played date
            stats["lastPlayedDate"] = date_str

        # Update top score stats
        if achieved_top_score:
            # We assume that this does not happen more than once per day
            stats["topScoreStreak"] = stats.get("topScoreStreak", 0) + 1
            stats["totalTopScores"] = stats.get("totalTopScores", 0) + 1

        return stats

    firebase.run_transaction(stats_path, transaction_update)


def update_global_best_score(
    riddle_date: str,
    locale: str,
    user_id: str,
    score: int,
    word: str,
    coord: str,
    timestamp: str,
) -> bool:
    """Update global best score using a Firebase transaction.
    Returns [updated, best_score_so_far]. 'updated' is True if
    the global best was updated, False otherwise."""
    path = f"gatadagsins/{riddle_date}/{locale}/best"
    updated = False
    best_score_so_far = 0

    def transaction_update(current_data: Optional[BestDict]) -> BestDict:
        """Transaction function to update global best atomically"""
        nonlocal updated, best_score_so_far
        best_so_far: BestDict = current_data or BestDict(
            score=0, player="", word="", coord="", timestamp=""
        )
        best_score_so_far = best_so_far.get("score", 0)
        if score > best_score_so_far:
            # Update global best
            updated = True
            new_best = BestDict(
                score=score,
                player=user_id,
                word=word,
                coord=coord,
                timestamp=timestamp,
            )
            # Update cache
            _GLOBAL_BEST_CACHE.setdefault(riddle_date, {})[locale] = new_best
            # Update the best score
            best_score_so_far = score
            return new_best
        return best_so_far

    firebase.run_transaction(path, transaction_update)
    return updated


def update_group_best_score(
    riddle_date: str,
    locale: str,
    group_id: str,
    user_id: str,
    score: int,
    word: str,
    coord: str,
    timestamp: str,
) -> bool:
    """Update group best score using a Firebase transaction.
    Returns True if the group best was updated, False otherwise."""
    path = f"gatadagsins/{riddle_date}/{locale}/group/{group_id}/best"
    updated = False

    def transaction_update(current_data: Optional[BestDict]) -> BestDict:
        """Transaction function to update group best atomically"""
        nonlocal updated
        group_best: BestDict = current_data or BestDict(
            score=0, player="", word="", coord="", timestamp=""
        )
        if score > group_best.get("score", 0):
            # Update group best
            updated = True
            new_best = BestDict(
                score=score,
                player=user_id,
                word=word,
                coord=coord,
                timestamp=timestamp,
            )
            return new_best
        return group_best

    firebase.run_transaction(path, transaction_update)
    return updated


def increment_top_score_count(riddle_date: str, locale: str) -> None:
    """Increment the count of players who have achieved the top score.
    Uses a Firebase transaction to ensure atomicity."""
    path = f"gatadagsins/{riddle_date}/{locale}/count"

    def transaction_update(current_data: Optional[int]) -> int:
        """Transaction function to increment count atomically"""
        return (current_data or 0) + 1

    firebase.run_transaction(path, transaction_update)


def update_leaderboard_entry(
    riddle_date: str,
    locale: str,
    user_id: str,
    user_display_name: str,
    score: int,
    timestamp: str,
) -> bool:
    """Update leaderboard, maintaining top {LEADERBOARD_ENTRIES} entries sorted by score (desc)
    then timestamp (asc). Returns True if the entry made it into the top list."""
    path = f"gatadagsins/{riddle_date}/{locale}/leaders"
    made_leaderboard = False

    def transaction_update(current_data: Optional[LeaderboardDict]) -> LeaderboardDict:
        """Transaction function to update leaderboard atomically"""
        nonlocal made_leaderboard

        # Get current leaderboard as a dict of user_id -> LeaderboardEntry
        leaderboard: LeaderboardDict = current_data or {}

        # Check if user already has an entry
        existing_entry = leaderboard.get(user_id)

        if existing_entry:
            # If better score than existing entry, keep it
            # (We don't need to think about timestamps in the case of equal scores,
            # since the new entry is by definition later than the existing one)
            assert current_data is not None
            if score > existing_entry["score"]:
                user_entry = LeaderboardEntry(
                    userId=user_id,
                    displayName=user_display_name
                    or existing_entry.get("displayName", user_id),
                    score=score,
                    timestamp=timestamp,
                )
                new_data = current_data.copy()
                new_data[user_id] = user_entry
                made_leaderboard = True
                return new_data
            # Not better than existing entry: we're done
            return current_data  # No change

        # Potential new entry
        user_entry = LeaderboardEntry(
            userId=user_id,
            displayName=user_display_name or user_id,
            score=score,
            timestamp=timestamp,
        )

        # Build list of all current entries
        all_entries = list(leaderboard.items())

        # Add current user's entry
        all_entries.append((user_id, user_entry))

        # Sort by score (descending) then timestamp (ascending)
        all_entries.sort(key=lambda x: (-x[1]["score"], x[1]["timestamp"]))

        # Keep only top ones
        top_entries = all_entries[:LEADERBOARD_ENTRIES]

        # Check if our user made it into the top list
        if all(uid != user_id for uid, _ in top_entries):
            # User didn't make it into top list: no change
            assert current_data is not None
            return current_data

        # Return new leaderboard
        made_leaderboard = True
        return {uid: entry for uid, entry in top_entries}

    firebase.run_transaction(path, transaction_update)
    return made_leaderboard


@riddle_route("/gatadagsins/riddle")
@auth_required(ok=False)
def riddle_api() -> ResponseType:
    """Handle requests for the daily riddle"""
    rq = RequestData(request)

    # Decode POST parameters
    riddle_date = rq.get("date", "")
    locale = rq.get("locale", "")

    if not locale:
        return jsonify(ok=False, error="Invalid parameter: locale")

    # Validate date, which should be in YYYY-MM-DD format
    # and be an actually valid date
    # Validate required parameters
    if len(riddle_date) != 10 or riddle_date[4] != "-" or riddle_date[7] != "-":
        # The date format is expected to be YYYY-MM-DD
        return jsonify(ok=False, error="Invalid parameter: date")
    try:
        riddle_iso_date = date.fromisoformat(riddle_date)
    except ValueError:
        return jsonify(ok=False, error="Invalid parameter: date")

    # Select the correct locale for the current thread
    lc = to_supported_locale(locale)
    set_locale(lc)

    # Is this a query for today's riddle, or a previous one?
    todays_iso_date = datetime.now(tz=timezone.utc).date()
    if riddle_iso_date > todays_iso_date:
        return jsonify(ok=False, error="Riddle for future date not available")
    is_today = riddle_iso_date == todays_iso_date

    # Get or create riddle using a cached function. Note that it is important
    # to pass the is_today parameter as a 'cache buster', since today's riddle
    # and previous days' riddles are retrieved and returned differently.
    riddle_data = get_or_create_riddle(riddle_date, lc, is_today)

    if riddle_data is None:
        # If riddle generation failed, return an error
        return jsonify(ok=False, error="Failed to fetch or generate riddle")

    # Return the riddle
    return jsonify(ok=True, riddle=riddle_data)


def create_state_from_riddle(
    board_rows: Sequence[str], rack_str: str, locale: str
) -> State:
    """Create a State object from riddle board and rack data.

    This utility function creates a State object configured for riddle validation,
    loading the board position and rack tiles.

    Args:
        board_rows: List of 15 strings representing the board (15 chars each).
                   Letters are tiles on board, uppercase = blanks, '.' or ' ' = empty.
        rack_str: String of rack tiles (e.g., "uaenrrk", may contain '?' for blanks)
        locale: Language locale for the riddle

    Returns:
        A State object with the riddle's board and rack loaded
    """
    # Create a State object for riddle validation
    state = State(
        tileset=current_tileset(),
        manual_wordcheck=False,  # Use automatic dictionary checking
        drawtiles=False,  # Don't draw tiles, we'll set the rack manually
        locale=locale,
        board_type="standard",
    )

    # Load the board from the riddle
    board = state.board()
    for row_idx, row_str in enumerate(board_rows):
        for col_idx, letter in enumerate(row_str):
            if letter != " " and letter != ".":
                # There's a tile already on the board
                # Tiles that were originally blanks are represented in uppercase
                if letter.isupper():
                    board.set_tile(row_idx, col_idx, "?")
                else:
                    board.set_tile(row_idx, col_idx, letter)
                board.set_letter(row_idx, col_idx, letter.lower())

    # Set the rack from the riddle
    state.set_rack(0, rack_str)

    return state


@cache_if_not_none(maxsize=10)
def get_riddle_state(date: str, locale: str) -> Optional[State]:
    """Get a cached State object for a riddle, ready for move validation.

    This creates and caches the initial board state for a riddle,
    so we don't need to reconstruct it for every submission.
    The State can be copied cheaply for each validation.

    Args:
        date: ISO format date (YYYY-MM-DD)
        locale: Language locale

    Returns:
        A State object with the riddle's board and rack loaded, or None if riddle not found
    """
    # Fetch the riddle data (this is also cached)
    riddle_data = get_or_create_riddle(date, locale, is_today=True)
    if not riddle_data:
        return None

    # Extract rack string from RackDetails
    rack_str = "".join(tile for tile, _ in riddle_data["rack"])

    # Create and return the State using the utility function
    return create_state_from_riddle(riddle_data["board"], rack_str, locale)


def validate_riddle_move(
    date: str, locale: str, word: str, coord: str
) -> tuple[bool, int, str]:
    """Validate a move on a riddle board and calculate its score.

    Returns a tuple of (is_valid, calculated_score, error_message).
    If is_valid is True, calculated_score contains the actual score and error_message is empty.
    If is_valid is False, calculated_score is 0 and error_message explains why.

    Args:
        date: ISO format date (YYYY-MM-DD)
        locale: Language locale
        word: The word being played (may contain ?x for blanks)
        coord: The starting coordinate (e.g., "A1" or "1A")
    """
    # Parse the coordinate to determine row, col, and direction
    # Format: "A1" = horizontal at row A, col 1 (0-indexed)
    #         "1A" = vertical at col 1, row A
    if len(coord) < 2 or len(coord) > 3:
        return False, 0, "Invalid coordinate format"

    # Determine if horizontal or vertical based on first character
    if coord[0].isalpha():
        # Horizontal: "A1", "B2", etc.
        horiz = True
        try:
            row = Board.ROWIDS.index(coord[0].upper())
            col = int(coord[1:]) - 1
        except ValueError:
            return False, 0, "Invalid coordinate"
    else:
        # Vertical: "1A", "2B", etc.
        horiz = False
        try:
            row = Board.ROWIDS.index(coord[-1].upper())
            col = int(coord[:-1]) - 1
        except ValueError:
            return False, 0, "Invalid coordinate"

    if not (0 <= row < BOARD_SIZE) or not (0 <= col < BOARD_SIZE):
        return False, 0, "Invalid coordinate"

    # Get the cached base state for this riddle
    riddle_state = get_riddle_state(date, locale)
    if riddle_state is None:
        return False, 0, "Failed to load riddle state"

    # Create a Move object from the submitted word and coordinate
    move = Move(word, row, col, horiz)

    # Use make_covers to set up the move based on the current board state
    # This will figure out which tiles are being placed vs already on board
    try:
        move.make_covers(riddle_state.board(), word)
    except Exception as e:
        return False, 0, f"Failed to construct move: {str(e)}"

    # Check if the move is legal
    legality = move.check_legality(riddle_state, validate=True, ignore_game_over=True)
    if legality != Error.LEGAL:
        if isinstance(legality, tuple):
            error_code, error_word = legality
            return False, 0, f"Invalid move: error {error_code}, word '{error_word}'"
        return False, 0, f"Invalid move: error code {legality}"

    # Calculate the score
    calculated_score = move.score(riddle_state)

    return True, calculated_score, ""


@riddle_route("/gatadagsins/submit")
@auth_required(ok=False)
def submit_api() -> ResponseType:
    """Handle a (presumably improved) move from a player who is working on the riddle"""
    rq = RequestData(request)
    # The request should contain the following:
    # date: str
    # locale: str
    # userId: str
    # groupId: str
    # userDisplayName: str
    # move: {
    #   word: str
    #   score: int
    #   coord: str
    #   timestamp: str
    # }
    now = datetime.now(tz=timezone.utc)
    timestamp = now.isoformat()
    today = now.date().isoformat()

    riddle_date = rq.get("date", "")
    # The date should be in ISO format: YYYY-MM-DD
    if riddle_date != today:
        # Submissions are only accepted for today's riddle
        return jsonify(ok=True, update=False, message="Not today's riddle")

    user_id = current_user_id()
    locale = to_supported_locale(rq.get("locale", ""))
    # user_id = rq.get("userId", "")  # This is not currently used
    group_id = rq.get("groupId", "")
    user_display_name = rq.get("userDisplayName", "")
    move = cast(RiddleWordDict, rq.get("move", {}))
    if not user_id or not move:
        return jsonify(ok=False, error="Missing required parameters")

    # Validate the move data
    word = move.get("word", "")
    if not (2 <= len(word) <= BOARD_SIZE):
        return jsonify(ok=False, error="Invalid word")
    score = move.get("score", 0)
    if score <= 0:
        return jsonify(ok=False, error="Invalid score")
    coord = move.get("coord", "")
    if not (2 <= len(coord) <= 3):
        return jsonify(ok=False, error="Invalid coordinate")

    # Set the locale for this thread
    set_locale(locale)

    # Validate the move against the actual riddle board and rack
    try:
        is_valid, calculated_score, error_msg = validate_riddle_move(
            riddle_date, locale, word, coord
        )
    except Exception as e:
        is_valid = False
        calculated_score = 0
        error_msg = repr(e)

    if not is_valid:
        logging.warning(
            f"Invalid move submission from user {user_id}: {error_msg} "
            f"(word='{word}', coord={coord}, claimed_score={score})"
        )
        return jsonify(ok=False, error=f"Invalid move")

    # Verify the score matches what we calculated
    if calculated_score != score:
        logging.warning(
            f"Score mismatch from user {user_id}: claimed {score}, "
            f"calculated {calculated_score} (word='{word}', coord={coord})"
        )
        return jsonify(ok=False, error=f"Score mismatch")

    update = False
    message = ""

    try:
        # Update global best score using transaction
        updated = update_global_best_score(
            riddle_date=riddle_date,
            locale=locale,
            user_id=user_id,
            score=score,
            word=word,
            coord=coord,
            timestamp=timestamp,
        )
        if updated:
            message = "Global best score updated"
            update = True

        # Always update the leaderboard
        # (top {LEADERBOARD_ENTRIES} regardless of global best)
        update_leaderboard_entry(
            riddle_date=riddle_date,
            locale=locale,
            user_id=user_id,
            user_display_name=user_display_name,
            score=score,
            timestamp=timestamp,
        )

        # Update the user's personal achievement status
        # Determine if this is a top score by comparing to max_score
        max_score = riddle_max_score(riddle_date, locale) or 0
        is_top_score = (score >= max_score) if max_score > 0 else False

        achievement_updated, newly_achieved_top = update_user_achievement(
            user_id=user_id,
            date=riddle_date,
            locale=locale,
            score=score,
            word=word,
            coord=coord,
            timestamp=timestamp,
            is_top_score=is_top_score,
        )

        if achievement_updated:
            # This is a significant update, so it might affect the user's streak stats
            update_user_streak_stats(
                user_id=user_id,
                locale=locale,
                date_str=riddle_date,
                achieved_top_score=is_top_score,
            )
            update = True
            if not message:
                message = "User achievement updated"

        if newly_achieved_top:
            # User achieved the top score for the first time: increment count
            increment_top_score_count(riddle_date, locale)

        # If the user belongs to a group, also update the group's best using transaction
        if group_id:
            if update_group_best_score(
                riddle_date=riddle_date,
                locale=locale,
                group_id=group_id,
                user_id=user_id,
                score=score,
                word=word,
                coord=coord,
                timestamp=timestamp,
            ):
                if not message:
                    message = "Group best score updated"
                update = True

    except Exception as e:
        logging.warning(f"Exception while processing submission from user {user_id}: {repr(e)}")
        # If something goes wrong, return an error
        return jsonify(ok=False, error="Submission failed")
    # If we reach here, the submission was successful,
    # but may not have updated anything
    return jsonify(ok=True, update=update, message=message or "No update")
