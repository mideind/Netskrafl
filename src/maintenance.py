"""

    Maintenance mode for Netskrafl/Explo

    Copyright © 2026 Miðeind ehf.

    When the MAINTENANCE environment variable is set (to "1", "true" or
    "yes"), the server answers every request with HTTP 503 (Service
    Unavailable) instead of handling it. Nothing is read from or written
    to the database, and scheduled jobs are refused like everything else.

    This is how the backend is frozen while its data is being moved, for
    instance from Cloud Datastore to PostgreSQL: a version of the app with
    the variable set is deployed beforehand without traffic, and the freeze
    is then a matter of routing all traffic to it. The freeze is undone by
    routing the traffic back.

    The status code matters: the web clients treat a response with status
    500 or above (and a request that fails altogether) as "the server could
    not be reached", and offer the user to try again. Any other response
    would be interpreted as a reply from the API.

    Exempt from the freeze are the health and lifecycle endpoints that the
    hosting platform uses to decide whether an instance is alive
    (/health/..., /_ah/...), and CORS preflight requests, which are answered
    by the CORS module before this one sees them (the browser then gets to
    see the 503 response to the actual request, with its CORS headers).

"""

from __future__ import annotations

from typing import Optional

import os

from flask import Flask, Response, current_app, jsonify, request

from config import NETSKRAFL


# The name of the Flask configuration key (and of the environment variable)
MAINTENANCE_KEY = "MAINTENANCE"

# Tell clients (and schedulers that honor it) when to try again, in seconds
RETRY_AFTER = 120

# Path prefixes that are served as usual during maintenance
_EXEMPT_PREFIXES = ("/health/", "/_ah/")

if NETSKRAFL:
    _TITLE = "Netskrafl"
    _MESSAGE = (
        "Unnið er að viðhaldi á Netskrafli. "
        "Það verður aðgengilegt aftur eftir stutta stund."
    )
else:
    _TITLE = "Explo"
    _MESSAGE = "The server is undergoing maintenance and will be back shortly."

_HTML = (
    '<!DOCTYPE html><html><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    "<title>{title}</title></head>"
    '<body style="font-family: sans-serif; text-align: center; margin-top: 4em">'
    "<h1>{title}</h1><p>{message}</p></body></html>"
).format(title=_TITLE, message=_MESSAGE)


def maintenance_from_env() -> bool:
    """Return True if the environment asks for maintenance mode"""
    return os.environ.get(MAINTENANCE_KEY, "").lower() in ("1", "true", "yes")


def _refuse_during_maintenance() -> Optional[Response]:
    """A before_request handler that answers 503 in maintenance mode"""
    if not current_app.config.get(MAINTENANCE_KEY):
        return None
    if request.path.startswith(_EXEMPT_PREFIXES):
        return None
    # Send a web page to a browser that is navigating to the site,
    # and JSON to everything else (API clients, schedulers, curl)
    wants_html = (
        request.method == "GET"
        and request.accept_mimetypes.best_match(["application/json", "text/html"])
        == "text/html"
    )
    response: Response
    if wants_html:
        response = Response(_HTML, mimetype="text/html")
    else:
        response = jsonify(ok=False, maintenance=True, message=_MESSAGE)
    response.status_code = 503
    response.headers["Retry-After"] = str(RETRY_AFTER)
    response.headers["Cache-Control"] = "no-store"
    return response


def init_maintenance(app: Flask) -> None:
    """Initialize maintenance mode handling for the Flask app. This must
    be called after init_cors(), so that CORS preflight requests are
    answered before the maintenance check."""
    app.config[MAINTENANCE_KEY] = maintenance_from_env()
    app.before_request(_refuse_during_maintenance)

