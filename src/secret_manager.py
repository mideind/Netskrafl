"""
    Secret Manager module for Google Cloud Secret Manager

    Copyright © 2025 Miðeind ehf.
    Author: Valur Hrafn Einarsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This module provides a SecretManager class for interacting with Google Cloud Secret Manager. 
    It includes methods to retrieve secrets as bytes or JSON. Errors are logged and exceptions raised.

"""

from typing import Any

import os
import json
import time
import logging

from google.cloud import secretmanager  # type: ignore
from google.api_core.exceptions import GoogleAPICallError, DeadlineExceeded


# We cannot use the variable from config.py here, as that would create a circular import
running_local: bool = (
    os.environ.get("SERVER_SOFTWARE", "").startswith("Development")
    or os.environ.get("RUNNING_LOCAL", "").lower() in ("1", "true", "yes")
)


class SecretManager:

    def __init__(self, project_id: str) -> None:
        """
        Initialize the SecretManager with a Google Cloud project ID.
        A SecretManagerServiceClient is created for interacting with Secret Manager.
        """
        if running_local:
            # Propagate Google Cloud logging to the root logger
            logging.getLogger("google.cloud.secretmanager").propagate = True
        self.client = secretmanager.SecretManagerServiceClient()
        self.project_id = project_id

    def get_secret(self, secret_id: str, version_id: str = "latest") -> bytes:
        """
        Retrieve a secret from Secret Manager.
        The secret is returned as bytes.
        If an error occurs, an error message is logged and an exception is raised.
        """
        name = ""
        try:
            name = (
                f"projects/{self.project_id}/secrets/{secret_id}/versions/{version_id}"
            )
            t0 = 0.0
            if running_local:
                t0 = time.time()
                logging.info(f"Get secret {name}: start")
            response = self.client.access_secret_version(  # type: ignore
                request={"name": name},
                timeout=5*60, # 5 minutes
            )
            if running_local:
                logging.info(f"Get secret {name}: done in {time.time() - t0:.3f} seconds")
            return response.payload.data
        except DeadlineExceeded as e:
            logging.error(f"Deadline exceeded: {e}. Secret path: {name}")
            raise
        except GoogleAPICallError as e:
            logging.error(f"Failed to get secret: {e}. Secret path: {name}")
            raise

    def get_json_secret(self, secret_id: str, version_id: str = "latest") -> Any:
        """
        Retrieve a secret from Secret Manager and return it as a JSON object.
        The secret is decoded from bytes to a string before being loaded as JSON.
        If an error occurs, an error message is logged and an exception is raised.
        """
        try:
            json_secret = self.get_secret(secret_id, version_id).decode("utf-8")
            return json.loads(json_secret)
        except json.JSONDecodeError as e:
            logging.error(
                f"Failed to decode JSON secret: {e}. Secret ID: {secret_id}, Version ID: {version_id}"
            )
            raise
