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

import json
from google.cloud import secretmanager  # type: ignore
from google.api_core.exceptions import GoogleAPICallError
import logging
from typing import Any


class SecretManager:

    def __init__(self, project_id: str) -> None:
        """
        Initialize the SecretManager with a Google Cloud project ID.
        A SecretManagerServiceClient is created for interacting with Secret Manager.
        """
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
            response = self.client.access_secret_version(request={"name": name})  # type: ignore
            return response.payload.data
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
