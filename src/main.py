"""

    Web server for Netskrafl and Explo

    Copyright © 2025 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This Python >= 3.11 web server module uses the Flask framework
    to implement a crossword game.

    The actual game logic is found in skraflplayer.py and
    skraflmechanics.py.

    The User and Game classes are found in skrafluser.py and skraflgame.py,
    respectively.

    The web client code is found in static/src/page.ts and static/src/game.ts.

    The responsive web content routes are defined in web.py.

    JSON-based client API entrypoints are defined in api.py.

"""

from __future__ import annotations

from typing import (
    Dict,
    Union,
    Any,
    cast,
)

import os
import re
import logging

from datetime import datetime, timedelta, timezone

from flask import g, request, send_from_directory
from flask.wrappers import Response
from flask.json.provider import DefaultJSONProvider

from config import (
    NETSKRAFL,
    FlaskConfig,
    ResponseType,
    DEFAULT_LOCALE,
    running_local,
    ON_GAE,
    host,
    port,
    PROJECT_ID,
    CLIENT_ID,
    CLIENT_SECRET,
    COOKIE_DOMAIN,
    MEASUREMENT_ID,
    FIREBASE_API_KEY,
    FIREBASE_SENDER_ID,
    FIREBASE_DB_URL,
    FIREBASE_APP_ID,
    FLASK_SESSION_KEY,
    AUTH_SECRET,
    TRANSITION_KEY,
)
from basics import (
    FlaskWithCaching,
    ndb_wsgi_middleware,
    init_oauth,
    check_port_available,
)
from authmanager import auth_manager
from cors import init_cors
from firebase import init_firebase_app, connect_blueprint
from wordbase import Wordbase
from api import api_blueprint
from web import STATIC_FOLDER, web_blueprint
from skraflstats import stats_blueprint
from riddle import riddle_blueprint


# App version used for cache busting in production.
# Priority: GAE_VERSION (App Engine) > APP_VERSION (Docker/Cloud Run) > empty
# GAE_VERSION format is nYYYYMMDD with optional suffix (a, b, c, ...) for same-day deploys.
# APP_VERSION can be set to git commit hash, build timestamp, or image tag.
APP_VERSION: str = (
    ""
    if running_local
    else os.environ.get("GAE_VERSION", "") or os.environ.get("APP_VERSION", "")
)
GAE_INSTANCE: str = "" if running_local else os.environ.get("GAE_INSTANCE", "")


# Configure logging based on environment
if running_local:
    # Local development: logging configured in config.py
    check_port_available(host, int(port))
    logging.info(f"{PROJECT_ID} server running with DEBUG set to True")
    # Disable Werkzeug's default request logging to avoid duplicate logs,
    # since we are logging web requests ourselves
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
elif ON_GAE:
    # Google App Engine: use Google Cloud Logging
    import google.cloud.logging

    logging_client = google.cloud.logging.Client(
        credentials=auth_manager.get_credentials()
    )
    # Connects the logger to the root logging handler;
    # by default this captures all logs at INFO level and higher
    cast(Any, logging_client).setup_logging()
else:
    # Docker/Digital Ocean/Cloud Run: use standard stderr logging
    # This format works well with container log aggregators
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.info(f"{PROJECT_ID} server starting (Docker/container mode)")

# Initialize Firebase
init_firebase_app()

# Initialize Flask using our custom subclass, defined in basics.py
app = FlaskWithCaching(__name__, static_folder=STATIC_FOLDER)

# Wrap the WSGI app to insert the Google App Engine NDB client context
# into each request
app.wsgi_app = ndb_wsgi_middleware(app.wsgi_app)  # type: ignore[assignment]

# When running behind a reverse proxy (Digital Ocean, Cloud Run, etc.),
# trust the X-Forwarded-* headers to get correct scheme (https) and host.
# GAE handles this automatically, so we only apply ProxyFix elsewhere.
if not running_local and not ON_GAE:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(  # type: ignore[assignment]
        app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
    )

# Initialize Cross-Origin Resource Sharing (CORS)
init_cors(app)

# Flask configuration
# Make sure that the Flask session cookie is secure (i.e. only used
# with HTTPS unless we're running on a development server) and
# invisible from JavaScript (HTTPONLY).
# We set SameSite to 'Lax', as it cannot be 'Strict' or 'None'
# due to the user authentication (OAuth2) redirection flow.

flask_config = FlaskConfig(
    DEBUG=running_local,
    SESSION_COOKIE_DOMAIN=None if running_local else COOKIE_DOMAIN,
    SESSION_COOKIE_SECURE=not running_local,
    SESSION_COOKIE_HTTPONLY=True,
    # Be careful! Setting COOKIE_SAMESITE to "None"
    # disables web login (OAuth2 flow)
    SESSION_COOKIE_SAMESITE="Lax",
    # Allow sessions to last 90 days
    PERMANENT_SESSION_LIFETIME=timedelta(days=90),
    # Add Google OAuth2 client id and secret for web clients (type 'web')
    GOOGLE_CLIENT_ID=CLIENT_ID,
    GOOGLE_CLIENT_SECRET=CLIENT_SECRET,
    # Set the authentication token for anonymous sessions
    AUTH_SECRET=AUTH_SECRET,
    # JSON_AS_ASCII=False,
)

# Set the Flask secret session key
app.secret_key = FLASK_SESSION_KEY

# Load the Flask configuration
app.config.update(flask_config)  # pyright: ignore[reportUnknownMemberType]

# Configure the Flask JSON provider to use UTF-8 encoding and to not sort keys
assert isinstance(app.json, DefaultJSONProvider)
app.json.ensure_ascii = False
app.json.sort_keys = False

# Register the Flask blueprints for the various routes
app.register_blueprint(api_blueprint)
app.register_blueprint(web_blueprint)
app.register_blueprint(stats_blueprint)
app.register_blueprint(riddle_blueprint)
app.register_blueprint(connect_blueprint)

# Initialize the OAuth wrapper
init_oauth(app)


@app.template_filter("stripwhite")
def stripwhite(s: str) -> str:
    """Flask/Jinja2 template filter to strip out consecutive whitespace"""
    # Convert all consecutive runs of whitespace of 1 char or more into a single space
    return re.sub(r"\s+", " ", s)


@app.before_request
def before_request():
    if running_local:
        g.request_start = datetime.now(tz=timezone.utc)


@app.after_request
def after_request(response: Response) -> Response:
    """Post-request processing"""
    if running_local:
        # Note: request_start may not be set if a before_request handler
        # (e.g., CORS preflight) returned a response early
        start = getattr(g, "request_start", None)
        if start is not None:
            duration = (datetime.now(tz=timezone.utc) - start).total_seconds()
            logging.info(
                f'{request.remote_addr} - - [{start.strftime("%d/%b/%Y %H:%M:%S")}] '
                f'"{request.method} {request.full_path.rstrip("?")} {request.environ.get("SERVER_PROTOCOL")}" '
                f'{response.status_code} - {duration:.3f}s'
            )
    else:
        # Add HSTS to enforce HTTPS
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


@app.context_processor
def inject_into_context() -> Dict[str, Union[bool, str]]:
    """Inject variables and functions into all Flask contexts"""
    return dict(
        # Variable dev_server is True if running on a (local) GAE development server
        dev_server=running_local,
        project_id=PROJECT_ID,
        client_id=CLIENT_ID,
        default_locale=DEFAULT_LOCALE,
        firebase_api_key=FIREBASE_API_KEY,
        firebase_sender_id=FIREBASE_SENDER_ID,
        firebase_db_url=FIREBASE_DB_URL,
        firebase_app_id=FIREBASE_APP_ID,
        measurement_id=MEASUREMENT_ID,
        transition_key=TRANSITION_KEY,
    )


# Flask cache busting for static .css and .js files
@app.url_defaults
def versioned_url_for_static_file(endpoint: str, values: Dict[str, Any]) -> None:
    """Add a ?v=XXX parameter to URLs for static .js and .css files.
    In production, XXX is APP_VERSION (from GAE_VERSION or APP_VERSION env var).
    In local development, XXX is the file's mtime for instant refresh."""

    if "static" == endpoint or endpoint.endswith(".static"):
        filename = values.get("filename")
        if filename and filename.endswith((".js", ".css")):
            param_name = "v"
            # Add underscores in front of the param name until it is unique
            while param_name in values:
                param_name = "_" + param_name
            if APP_VERSION:
                # Production: use deployment version for cache busting
                values[param_name] = APP_VERSION
            elif running_local:
                # Local development: use file mtime for instant refresh
                static_folder = web_blueprint.static_folder or "."
                filepath = os.path.join(static_folder, filename)
                try:
                    values[param_name] = int(os.stat(filepath).st_mtime)
                except OSError:
                    values[param_name] = "dev"
            else:
                # Production without APP_VERSION set - use fallback
                values[param_name] = "1"


@app.route("/_ah/start")
def start() -> ResponseType:
    """App Engine is starting a fresh instance"""
    version = APP_VERSION or "N/A"
    instance = GAE_INSTANCE or os.environ.get("HOSTNAME", "N/A")
    logging.info(f"Start: project {PROJECT_ID}, version {version}, instance {instance}")
    return "", 200


@app.route("/_ah/warmup")
def warmup() -> ResponseType:
    """App Engine is starting a fresh instance - warm it up
    by loading all vocabularies"""
    ok = Wordbase.warmup()
    instance = GAE_INSTANCE or os.environ.get("HOSTNAME", "N/A")
    logging.info(f"Warmup, instance {instance}, ok is {ok}")
    return "", 200


@app.route("/_ah/stop")
def stop() -> ResponseType:
    """App Engine is shutting down an instance"""
    try:
        instance = GAE_INSTANCE or os.environ.get("HOSTNAME", "N/A")
        logging.info(f"Stop: instance {instance}")
    except Exception:
        # The logging module may not be functional at this point,
        # as the server is being shut down
        pass
    return "", 200


# Health check endpoints for Kubernetes/Cloud Run deployments
# These complement the GAE-specific /_ah/* handlers above


@app.route("/health/live")
def health_live() -> ResponseType:
    """Liveness probe - is the process running and responsive?
    Used by Kubernetes/Cloud Run to determine if container should be restarted."""
    return "OK", 200


@app.route("/health/ready")
def health_ready() -> ResponseType:
    """Readiness probe - is the app ready to serve traffic?
    Checks that vocabularies are loaded and Redis is reachable."""
    # Check that vocabularies are loaded
    if not Wordbase.is_initialized():
        return "Warming up - vocabularies not loaded", 503
    # Check Redis connectivity
    try:
        from cache import memcache
        memcache.get_redis_client().ping()
    except Exception as e:
        logging.warning(f"Health check: Redis unavailable - {repr(e)}")
        return "Redis unavailable", 503
    return "OK", 200


# Root-level static files that GAE serves via handlers in app.yaml
# In Docker/Cloud Run deployments, Flask serves these directly
_ROOT_STATIC_FILES: frozenset[str] = frozenset({
    "robots.txt",
    "favicon.ico",
    "favicon-32x32.png",
    "favicon-16x16.png",
    "browserconfig.xml",
    "mstile-150x150.png",
    "netskrafl.webmanifest",
    "safari-pinned-tab.svg",
    "touch-icon-ipad.png",
    "touch-icon-ipad-retina.png",
    "touch-icon-iphone-retina.png",
})


@app.route("/<filename>")
def root_static_files(filename: str) -> ResponseType:
    """Serve root-level static files (favicon, robots.txt, etc.)
    This mirrors GAE's static file handlers from app.yaml for Docker deployments.
    Uses <filename> (not <path:filename>) to only match single path segments."""
    # Handle alias: apple-touch-icon.png -> touch-icon-ipad-retina.png
    if filename == "apple-touch-icon.png":
        filename = "touch-icon-ipad-retina.png"
    if filename in _ROOT_STATIC_FILES:
        return send_from_directory(STATIC_FOLDER, filename, max_age=86400)
    # Not a known root static file - return 404
    return "Not found", 404


@app.errorhandler(500)
def server_error(e: Union[int, Exception]) -> ResponseType:
    """Return a custom 500 error"""
    logging.error(f"Server error: {e}")
    if NETSKRAFL:
        return f"<html><body><p>Villa kom upp í netþjóni: {e}</p></body></html>", 500
    return f"<html><body><p>An error occurred in the server: {e}</p></body></html>", 500


# Run a default Flask web server for testing if invoked directly as a main program
if __name__ == "__main__":
    app.run(
        debug=True,
        port=int(port),
        use_debugger=True,
        threaded=False,
        processes=1,
        host=host,  # Set by default to "127.0.0.1" in basics.py
    )
