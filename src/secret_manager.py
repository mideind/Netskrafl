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

from typing import Any, cast

import json
import time
import logging
import requests
import base64

# Import authmanager first to ensure credentials are set up
# before any Google Cloud libraries are imported
from authmanager import auth_manager, running_local

from google.cloud import secretmanager  # type: ignore
from google.api_core.exceptions import GoogleAPICallError, DeadlineExceeded


class SecretManager:

    def __init__(self, project_id: str) -> None:
        """
        Initialize the SecretManager with a Google Cloud project ID.
        A SecretManagerServiceClient is created for interacting with Secret Manager.
        """
        if running_local:
            # Propagate Google Cloud logging to the root logger
            logging.getLogger("google.cloud.secretmanager").propagate = True
            # Use the HTTP client exclusively, not the gRPC client
            # which can be extremely slow in local development environments,
            # for some reason.
            self.client = None
        else:
            # Note: passing credentials=auth_manager.get_credentials() here
            # does not solve the extreme slowness bug, which seems to be
            # related to gRPC - and is avoided by using the HTTP client instead.
            self.client = cast(Any, secretmanager).SecretManagerServiceClient()
        self.project_id = project_id

    def _get_secret_via_client(self, name: str) -> bytes:
        """
        Retrieve a secret from Secret Manager using the client library.
        The secret is returned as bytes.
        If an error occurs, an error message is logged and an exception is raised.
        """
        assert self.client is not None
        response = self.client.access_secret_version(  # type: ignore
            request={"name": name},
            timeout=5 * 60, # 5 minutes
        )
        return response.payload.data

    def _get_secret_via_http(self, name: str) -> bytes:
        """
        Retrieve a secret from Secret Manager using direct HTTP calls instead of the client library.
        This method may perform better in local development environments where the client library 
        can be slow.
        The secret is returned as bytes.
        """
        try:
            url = f"https://secretmanager.googleapis.com/v1/{name}:access"

            # Obtain a valid access token, coded in to an Authorization: Bearer header
            headers = auth_manager.get_auth_headers()
            t0 = time.time()

            response = requests.get(url, headers=headers, timeout=5 * 60)  # 5-minute timeout
            response.raise_for_status()

            logging.info(f"Get secret via HTTP {name}: done in {time.time() - t0:.3f} seconds")

            # Parse the response and extract the payload data
            json_response = response.json()
            return base64.b64decode(json_response["payload"]["data"])

        except requests.exceptions.Timeout:
            logging.error(f"Deadline exceeded when fetching via HTTP. Secret path: {name}")
            raise DeadlineExceeded(f"HTTP request timeout for secret: {name}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to get secret via HTTP: {e}. Secret path: {name}")
            raise GoogleAPICallError(f"HTTP request failed for secret: {name}") from e

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
            if self.client is None:
                return self._get_secret_via_http(name)
            else:
                return self._get_secret_via_client(name)
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
