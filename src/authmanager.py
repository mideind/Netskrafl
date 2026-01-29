"""

    Google Cloud Authentication Manager

    Copyright © 2025 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This module provides centralized handling of Google Cloud
    authentication, credentials management and token refreshing
    for the Netskrafl/Explo backend.

    Credentials can be provided via (checked in order):
    1. Metadata service (automatic on GAE, Cloud Run, GKE)
    2. GOOGLE_APPLICATION_CREDENTIALS - path to JSON file (existing standard)
    3. GOOGLE_CREDENTIALS_BASE64 - base64-encoded JSON (for Docker/K8s secrets)
    4. GOOGLE_CREDENTIALS_JSON - raw JSON string (for CI/CD systems)

"""

from typing import Any, cast, Self

import os
import base64
import json
import time
import logging
import threading
import tempfile
import atexit

import google.auth
from google.auth.credentials import Credentials
import google.auth.transport.requests
from google.auth.exceptions import RefreshError, DefaultCredentialsError


# Track temp credentials file for cleanup
_temp_credentials_file: str | None = None


def _setup_credentials_from_env() -> None:
    """Set up Google Cloud credentials from environment variables.

    This function checks for credentials in environment variables and,
    if found, writes them to a temporary file and sets
    GOOGLE_APPLICATION_CREDENTIALS to point to it.

    Supports two formats:
    - GOOGLE_CREDENTIALS_BASE64: base64-encoded service account JSON
    - GOOGLE_CREDENTIALS_JSON: raw service account JSON string

    This enables passing credentials without mounting files, which is
    useful for Docker, Kubernetes secrets, and CI/CD systems.
    """
    global _temp_credentials_file

    # Skip if GOOGLE_APPLICATION_CREDENTIALS is already set
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return

    credentials_json: str | None = None
    source: str = ""

    # Check for base64-encoded credentials
    base64_creds = os.environ.get("GOOGLE_CREDENTIALS_BASE64", "").strip()
    if base64_creds:
        try:
            credentials_json = base64.b64decode(base64_creds).decode("utf-8")
            source = "GOOGLE_CREDENTIALS_BASE64"
        except Exception as e:
            logging.error(f"Failed to decode GOOGLE_CREDENTIALS_BASE64: {e}")
            return

    # Check for raw JSON credentials
    if not credentials_json:
        raw_creds = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
        if raw_creds:
            credentials_json = raw_creds
            source = "GOOGLE_CREDENTIALS_JSON"

    if not credentials_json:
        return

    # Validate JSON structure
    try:
        creds_dict = json.loads(credentials_json)
        if "type" not in creds_dict:
            logging.error(f"Invalid credentials from {source}: missing 'type' field")
            return
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in {source}: {e}")
        return

    # Write to a secure temporary file
    try:
        # Create temp file that won't be automatically deleted
        fd, temp_path = tempfile.mkstemp(
            prefix="gcp_credentials_",
            suffix=".json",
        )
        with os.fdopen(fd, "w") as f:
            f.write(credentials_json)

        # Set restrictive permissions (owner read/write only)
        os.chmod(temp_path, 0o600)

        # Set the environment variable
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_path
        _temp_credentials_file = temp_path

        logging.info(f"Configured credentials from {source}")

    except Exception as e:
        logging.error(f"Failed to write credentials from {source}: {e}")


def _cleanup_temp_credentials() -> None:
    """Remove temporary credentials file on exit."""
    global _temp_credentials_file
    if _temp_credentials_file and os.path.exists(_temp_credentials_file):
        try:
            os.unlink(_temp_credentials_file)
        except Exception:
            pass  # Best effort cleanup


# Set up credentials from environment variables at module load time
# This runs before any Google Cloud clients are initialized
_setup_credentials_from_env()

# Register cleanup handler
atexit.register(_cleanup_temp_credentials)


# Google Cloud project ID
PROJECT_ID = os.environ.get("PROJECT_ID", "")
assert PROJECT_ID, "PROJECT_ID environment variable not set"

# Are we running in a local development environment or on a GAE server?
# We allow the SERVER_SOFTWARE environment variable to be overridden using
# RUNNING_LOCAL, since running gunicorn locally will set SERVER_SOFTWARE to
# "gunicorn/NN.n.n" rather than "Development".
running_local: bool = (
    os.environ.get("SERVER_SOFTWARE", "").startswith("Development")
    or os.environ.get("RUNNING_LOCAL", "").lower() in ("1", "true", "yes")
)


class CloudAuthManager:

    _instance: Self | None = None
    _lock = threading.Lock()

    def __new__(cls):
        """Singleton pattern to ensure only one instance of CloudAuthManager exists."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(CloudAuthManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._credentials = None
        self._token_expiry = 0
        self._refresh_lock = threading.Lock()
        self._initialized = True

    def get_credentials(self, force_refresh: bool = False) -> Credentials:
        """Get valid Google Cloud credentials, refreshing if necessary."""
        with self._refresh_lock:
            current_time = time.time()

            # Initialize or refresh credentials if needed
            if (
                self._credentials is None
                or force_refresh
                or current_time >= self._token_expiry
            ):

                try:
                    if self._credentials is None:
                        logging.info("Obtaining Google Cloud credentials")
                        # When running locally, configure Google Cloud gRPC to
                        # use the native client OS DNS resolution. This saves ~20
                        # seconds of blocking calls/timeouts upon first use of gRPC.
                        if running_local:
                            os.environ["GRPC_DNS_RESOLVER"] = "native"
                        self._credentials, project_id = cast(
                            Any, google.auth
                        ).default(
                            scopes=[
                                "https://www.googleapis.com/auth/cloud-platform"
                            ]
                        )
                        assert project_id == PROJECT_ID, (
                            f"Credentials do not match project ID: "
                            f"{project_id} != {PROJECT_ID}"
                        )
                    auth_req = google.auth.transport.requests.Request()
                    logging.info("Refreshing Google Cloud credentials")
                    self._credentials.refresh(auth_req)

                    # Set expiry time to 55 minutes (standard token lasts 60 minutes)
                    self._token_expiry = current_time + (55 * 60)
                    logging.info("Google Cloud credentials refreshed successfully")

                except (RefreshError, DefaultCredentialsError) as e:
                    if running_local:
                        logging.error(
                            "Failed to obtain or refresh Google Cloud credentials."
                        )
                        logging.error(
                            "Options to provide credentials:\n"
                            "  1. Run 'gcloud auth application-default login'\n"
                            "  2. Set GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json\n"
                            "  3. Set GOOGLE_CREDENTIALS_BASE64=<base64-encoded-json>\n"
                            "  4. Set GOOGLE_CREDENTIALS_JSON=<raw-json-string>"
                        )
                    logging.error(f"Failed to refresh credentials: {e}")
                    # Re-raise to let caller handle the error
                    raise

            return self._credentials

    def get_auth_headers(self) -> dict[str, str]:
        """Get authorization headers for direct Google Cloud HTTP
        calls using the current token."""
        credentials = self.get_credentials()
        return {"Authorization": f"Bearer {credentials.token}"}


# Singleton instance for easy import
auth_manager = CloudAuthManager()
