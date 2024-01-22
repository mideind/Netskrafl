"""

    Web server for netskrafl.is

    Copyright (C) 2024 Miðeind ehf.
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

from datetime import timedelta
from logging.config import dictConfig

from flask import Flask
from flask.wrappers import Response
from flask_cors import CORS

from config import (
    FlaskConfig,
    DEFAULT_LOCALE,
    running_local,
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
)
from basics import (
    ndb_wsgi_middleware,
    init_oauth,
    ResponseType,
)
from firebase import init_firebase_app
from dawgdictionary import Wordbase
from api import api_blueprint
from web import STATIC_FOLDER, web_blueprint


if running_local:
    # Configure logging
    dictConfig(
        {
            "version": 1,
            "formatters": {
                "default": {
                    "format": "[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
                }
            },
            "handlers": {
                "wsgi": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://flask.logging.wsgi_errors_stream",
                    "formatter": "default",
                }
            },
            "root": {"level": "INFO", "handlers": ["wsgi"]},
        }
    )

if running_local:
    logging.info("Netskrafl app running with DEBUG set to True")
    # flask_config["SERVER_NAME"] = "127.0.0.1"
else:
    # Import the Google Cloud client library
    import google.cloud.logging

    # Instantiate a logging client
    logging_client = google.cloud.logging.Client()
    # Connects the logger to the root logging handler;
    # by default this captures all logs at INFO level and higher
    cast(Any, logging_client).setup_logging()

# Initialize Firebase
init_firebase_app()

# Initialize Flask
app = Flask(__name__, static_folder=STATIC_FOLDER)
# The following cast to Any can be removed once Flask typing becomes
# more robust and/or compatible with Pylance
cast_app = cast(Any, app)

# Wrap the WSGI app to insert the Google App Engine NDB client context
# into each request
setattr(app, "wsgi_app", ndb_wsgi_middleware(cast_app.wsgi_app))

# Initialize Cross-Origin Resource Sharing (CORS) Flask plug-in
if running_local:
    CORS(
        app,
        supports_credentials=True,
        origins=[
            "http://127.0.0.1:3000",
        ],
    )

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
    PERMANENT_SESSION_LIFETIME=timedelta(days=31),
    # Add Google OAuth2 client id and secret for web clients (type 'web')
    GOOGLE_CLIENT_ID=CLIENT_ID,
    GOOGLE_CLIENT_SECRET=CLIENT_SECRET,
    JSON_AS_ASCII=False,
)

# Set the Flask secret session key
app.secret_key = FLASK_SESSION_KEY

# Load the Flask configuration
cast_app.config.update(**flask_config)

# Register the Flask blueprints for the api and web routes
app.register_blueprint(api_blueprint)
app.register_blueprint(web_blueprint)

# Initialize the OAuth wrapper
init_oauth(app)


@app.template_filter("stripwhite")
def stripwhite(s: str) -> str:
    """Flask/Jinja2 template filter to strip out consecutive whitespace"""
    # Convert all consecutive runs of whitespace of 1 char or more into a single space
    return re.sub(r"\s+", " ", s)


@app.after_request
def add_headers(response: Response) -> Response:
    """Inject additional headers into responses"""
    if not running_local:
        # Add HSTS to enforce HTTPS
        response.headers[
            "Strict-Transport-Security"
        ] = "max-age=31536000; includeSubDomains"
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
    )


# Flask cache busting for static .css and .js files
@cast_app.url_defaults
def hashed_url_for_static_file(endpoint: str, values: Dict[str, Any]) -> None:
    """Add a ?h=XXX parameter to URLs for static .js and .css files,
    where XXX is calculated from the file timestamp"""

    def static_file_hash(filename: str) -> int:
        """Obtain a timestamp for the given file"""
        return int(os.stat(filename).st_mtime)

    if "static" == endpoint or endpoint.endswith(".static"):
        filename = values.get("filename")
        if (
            filename
            and filename.endswith((".js", ".css"))
            and not filename.startswith("built/")
        ):
            static_folder = web_blueprint.static_folder or "."
            param_name = "h"
            # Add underscores in front of the param name until it is unique
            while param_name in values:
                param_name = "_" + param_name
            values[param_name] = static_file_hash(os.path.join(static_folder, filename))


@cast_app.route("/_ah/start")
def start() -> ResponseType:
    """App Engine is starting a fresh instance"""
    version = os.environ.get("GAE_VERSION", "N/A")
    instance = os.environ.get("GAE_INSTANCE", "N/A")
    logging.info(f"Start: project {PROJECT_ID}, version {version}, instance {instance}")
    return "", 200


@cast_app.route("/_ah/warmup")
def warmup() -> ResponseType:
    """App Engine is starting a fresh instance - warm it up
    by loading all vocabularies"""
    ok = Wordbase.warmup()
    instance = os.environ.get("GAE_INSTANCE", "N/A")
    logging.info(
        f"Warmup, instance {instance}, ok is {ok}"
    )
    return "", 200


@cast_app.route("/_ah/stop")
def stop() -> ResponseType:
    """App Engine is shutting down an instance"""
    instance = os.environ.get("GAE_INSTANCE", "N/A")
    logging.info(f"Stop: instance {instance}")
    return "", 200


@app.errorhandler(500)  # type: ignore
def server_error(e: Union[int, Exception]) -> ResponseType:
    """Return a custom 500 error"""
    logging.error(f"Server error: {e}")
    if PROJECT_ID == "netskrafl":
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
