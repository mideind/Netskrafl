"""

    Redirect app for the retired App Engine deployment of Netskrafl

    Copyright © 2026 Miðeind ehf.

    Netskrafl's backend moved from App Engine to a container deployment
    in November 2026. This tiny app is what App Engine serves in its
    place until the App Engine project is closed:

    * A browser that opens the old App Engine address (any page) is
      redirected to Netskrafl's present home, within Málstaður.

    * Every other request is refused with HTTP 503, as the maintenance
      version of the real app did before it (see src/maintenance.py):
      API calls, and requests under the production hostname from clients
      whose DNS still points here. The web clients treat a status of 500
      or above as "the server could not be reached" and offer the user
      to try again, by which time their DNS has usually caught up.

    The app reads and writes no data and has no dependencies beyond the
    Python standard library. It is deployed from this directory with
    its own app.yaml; see deploy-netskrafl.sh.

"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Tuple

import json


# The type of the start_response function that a WSGI server passes in
StartResponse = Callable[[str, List[Tuple[str, str]]], object]

# Where Netskrafl lives now
NEW_HOME = "https://malstadur.mideind.is/netskrafl"

# Hostnames that end like this are App Engine's own, as opposed to the
# production hostname, which only reaches this app through stale DNS
APP_ENGINE_SUFFIX = ".appspot.com"

# Tell clients when to try again, in seconds
RETRY_AFTER = 120

_MESSAGE = "Netskrafl has moved; this server no longer answers requests."


def _hostname(environ: Dict[str, str]) -> str:
    """The hostname that the request was sent to, without a port"""
    host = environ.get("HTTP_HOST", "")
    return host.split(":")[0].lower()


def app(environ: Dict[str, str], start_response: StartResponse) -> Iterable[bytes]:
    """The WSGI application: redirect page loads, refuse everything else"""
    path = environ.get("PATH_INFO", "")
    if path.startswith("/_ah/"):
        # App Engine's own warmup and lifecycle requests
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"OK"]
    is_page_load = environ.get("REQUEST_METHOD") in ("GET", "HEAD")
    if is_page_load and _hostname(environ).endswith(APP_ENGINE_SUFFIX):
        start_response("301 Moved Permanently", [("Location", NEW_HOME)])
        return []
    body = json.dumps({"ok": False, "maintenance": True, "message": _MESSAGE})
    start_response(
        "503 Service Unavailable",
        [
            ("Content-Type", "application/json"),
            ("Retry-After", str(RETRY_AFTER)),
            ("Cache-Control", "no-store"),
        ],
    )
    return [body.encode("utf-8")]

