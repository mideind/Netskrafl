"""
Secret Manager module for Google Cloud Secret Manager

Copyright (C) 2024 Miðeind ehf.
Author: Valur Hrafn Einarsson

License: CC-BY-NC 4.0. More info: https://github.com/your-github-account/your-project

This module provides a SecretManager class for interacting with Google Cloud Secret Manager. 
It includes methods to retrieve secrets as bytes or JSON. Errors are logged and exceptions raised.
"""

import json
from google.cloud import secretmanager
from google.api_core.exceptions import GoogleAPICallError
import logging

class SecretManager:
    def __init__(self, project_id):
        """
        Initialize the SecretManager with a Google Cloud project ID.
        A SecretManagerServiceClient is created for interacting with Secret Manager.
        """
        self.client = secretmanager.SecretManagerServiceClient()
        self.project_id = project_id

    def get_secret(self, secret_id, version_id="latest"):
        """
        Retrieve a secret from Secret Manager.
        The secret is returned as bytes.
        If an error occurs, an error message is logged and None is returned.
        """
        try:
            name = f"projects/{self.project_id}/secrets/{secret_id}/versions/latest"
            response = self.client.access_secret_version(request={"name": name})
            return response.payload.data
        except GoogleAPICallError as e:
            logging.error(f"Failed to get secret: {e}")
            raise

    def get_json_secret(self, secret_id, version_id="latest"):
        """
        Retrieve a secret from Secret Manager and return it as a JSON object.
        The secret is decoded from bytes to a string before being loaded as JSON.
        If an error occurs, an error message is logged and None is returned.
        """
        try:
            json_secret = self.get_secret(secret_id, version_id).decode('UTF-8')
            return json.loads(json_secret)
        except json.JSONDecodeError as e:
            logging.error(f"Failed to decode JSON secret: {e}")
            raise