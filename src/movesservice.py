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

from typing import Any, Mapping, Optional

import logging

import requests

from config import MOVES_AUTH_KEY, MOVES_SERVICE_URL


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

