"""

    Client for the GoSkrafl 'moves' service

    Copyright © 2026 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    The GoSkrafl server (github.com/vthorsteinsson/GoSkrafl) provides
    fast move generation (/moves), word checking (/wordcheck) and riddle
    generation (/riddle). Depending on the deployment, it is reached
    either as an external HTTPS service (the GAE 'moves' service) or as
    a loopback sidecar process within the same container - see the
    MOVES_SERVICE_URL resolution in config.py.

    Requests always carry a bearer token: the GAE service requires it,
    while the loopback sidecar runs without an ACCESS_KEY and ignores it.

"""

from __future__ import annotations

from typing import Any, List, Mapping, Optional, Tuple

import logging

import requests

from config import MOVES_AUTH_KEY, MOVES_SERVICE_URL

# A best-move summary: (coordinate, tiles, score), where the coordinate
# is e.g. "A1" for a horizontal move or "1A" for a vertical one, and the
# tiles string encodes a blank tile as '?' followed by its letter.
# This matches skraflmechanics.SummaryTuple and the JSON returned by
# the moves service ({"co": ..., "w": ..., "sc": ...} per move).
BestMoveSummary = Tuple[str, str, int]


def post_to_moves_service(
    path: str, payload: Mapping[str, Any], *, timeout: float
) -> Optional[requests.Response]:
    """POST a JSON payload to the moves service and return the
    Response object (whose status code may indicate an error),
    or None if the service could not be reached at all."""
    url = MOVES_SERVICE_URL + path
    try:
        return requests.post(
            url,
            headers={"Authorization": f"Bearer {MOVES_AUTH_KEY}"},
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as e:
        logging.error(f"Unable to reach moves service at {url}: {repr(e)}")
    return None


def best_moves_from_service(
    *,
    locale: str,
    board_type: str,
    board: List[str],
    rack: str,
    limit: int,
) -> Optional[List[BestMoveSummary]]:
    """Obtain a list of the best available moves for the given position
    from the moves service, in descending score order. The board is a
    list of 15 strings of 15 characters ('.' for an empty square,
    lowercase for a normal tile, uppercase for a blank tile that has
    been assigned that letter). Returns None if the service could not
    deliver a valid reply, in which case the caller should fall back
    to the in-process move generator."""
    response = post_to_moves_service(
        "/moves",
        {
            "locale": locale,
            "board_type": board_type,
            "board": board,
            "rack": rack,
            "limit": limit,
        },
        timeout=10,
    )
    if response is None:
        return None
    if response.status_code != 200:
        logging.error(
            f"Moves service replied {response.status_code} to /moves: "
            f"{response.text[:200]}"
        )
        return None
    try:
        moves = response.json()["moves"]
        return [(str(m["co"]), str(m["w"]), int(m["sc"])) for m in moves]
    except (KeyError, TypeError, ValueError) as e:
        logging.error(f"Malformed reply from moves service: {repr(e)}")
    return None

