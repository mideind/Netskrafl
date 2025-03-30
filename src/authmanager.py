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

"""

from typing import Any, cast, Self

import os
import time
import logging
import threading

import google.auth
from google.auth.credentials import Credentials
import google.auth.transport.requests
from google.auth.exceptions import RefreshError


# Google Cloud project ID
PROJECT_ID = os.environ.get("PROJECT_ID", "")
assert PROJECT_ID, "PROJECT_ID environment variable not set"


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
                        self._credentials, project_id = cast(Any, google.auth).default(
                            scopes=["https://www.googleapis.com/auth/cloud-platform"]
                        )
                        assert project_id == PROJECT_ID, f"Credentials do not match project ID: {project_id} != {PROJECT_ID}"
                    auth_req = google.auth.transport.requests.Request()
                    logging.info("Refreshing Google Cloud credentials")
                    self._credentials.refresh(auth_req)

                    # Set expiry time to 55 minutes (standard token lasts 60 minutes)
                    self._token_expiry = current_time + (55 * 60)
                    logging.info("Google Cloud credentials refreshed successfully")

                except RefreshError as e:
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
