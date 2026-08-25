"""
    Secret provider module

    Copyright © 2025 Miðeind ehf.
    Original author: Valur Hrafn Einarsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This module defines an abstract SecretProvider interface for obtaining
    application secrets, with two concrete implementations:

    * GoogleSecretProvider fetches secrets from Google Cloud Secret Manager
      (the default, used on GAE and wherever GCP credentials are available).
    * EnvSecretProvider fetches secrets from environment variables, allowing
      containerized deployments to run without access to GCP Secret Manager.

    The provider is selected via the SECRETS_PROVIDER environment variable
    ("google" is the default; "env" selects the environment-based provider).

"""

from __future__ import annotations

from typing import Any

import os
import json
import base64
import logging
from abc import ABC, abstractmethod


class SecretProvider(ABC):
    """Abstract interface for obtaining application secrets"""

    @abstractmethod
    def get_secret(self, secret_id: str, version_id: str = "latest") -> bytes:
        """Retrieve a secret as bytes. Raises an exception if the
        secret is not available."""
        ...

    def get_json_secret(self, secret_id: str, version_id: str = "latest") -> Any:
        """Retrieve a secret and return it as a parsed JSON object.
        If an error occurs, an error message is logged and an exception
        is raised."""
        try:
            json_secret = self.get_secret(secret_id, version_id).decode("utf-8")
            return json.loads(json_secret)
        except json.JSONDecodeError as e:
            logging.error(
                f"Failed to decode JSON secret: {e}. "
                f"Secret ID: {secret_id}, Version ID: {version_id}"
            )
            raise


class EnvSecretProvider(SecretProvider):
    """Secret provider that reads secrets from environment variables.

    For a secret id such as MOVES_AUTH_KEY, the provider first looks for
    an environment variable of the same name, whose value is used directly
    (UTF-8 encoded). If not found, it looks for MOVES_AUTH_KEY_BASE64,
    whose value is base64-decoded; this form is required for binary
    secrets such as SECRET_KEY_BIN. Secret versions are not supported;
    only the current environment value is available."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id

    def get_secret(self, secret_id: str, version_id: str = "latest") -> bytes:
        if version_id != "latest":
            logging.warning(
                f"EnvSecretProvider does not support secret versions; "
                f"ignoring version '{version_id}' for secret {secret_id}"
            )
        value = os.environ.get(secret_id)
        if value is not None:
            return value.encode("utf-8")
        value = os.environ.get(f"{secret_id}_BASE64")
        if value is not None:
            try:
                return base64.b64decode(value, validate=True)
            except Exception as e:
                logging.error(f"Failed to decode {secret_id}_BASE64: {e}")
                raise
        raise KeyError(
            f"Secret {secret_id} not found in environment "
            f"(checked {secret_id} and {secret_id}_BASE64)"
        )


class GoogleSecretProvider(SecretProvider):
    """Secret provider that fetches secrets from Google Cloud Secret Manager"""

    def __init__(self, project_id: str) -> None:
        """
        Initialize the GoogleSecretProvider with a Google Cloud project ID.
        A SecretManagerServiceClient is created for interacting with Secret Manager.
        """
        # Import authmanager first to ensure credentials are set up
        # before any Google Cloud libraries are imported. These imports
        # are done lazily here so that the module can be imported (and
        # EnvSecretProvider used) without Google Cloud dependencies.
        from authmanager import running_local
        from google.cloud import secretmanager  # type: ignore

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
            self.client = secretmanager.SecretManagerServiceClient()
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
            timeout=5 * 60,  # 5 minutes
        )
        return response.payload.data

    def _get_secret_via_http(self, name: str) -> bytes:
        """
        Retrieve a secret from Secret Manager using direct HTTP calls instead of the client library.
        This method may perform better in local development environments where the client library
        can be slow.
        The secret is returned as bytes.
        """
        import time
        import requests
        from authmanager import auth_manager
        from google.api_core.exceptions import GoogleAPICallError, DeadlineExceeded

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
        from google.api_core.exceptions import GoogleAPICallError, DeadlineExceeded

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


def get_secret_provider(project_id: str) -> SecretProvider:
    """Return the secret provider selected by the SECRETS_PROVIDER
    environment variable: 'google' (the default) for Google Cloud
    Secret Manager, or 'env' for environment-variable-based secrets."""
    provider = os.environ.get("SECRETS_PROVIDER", "google").lower()
    if provider == "env":
        logging.info("Using environment-based secret provider")
        return EnvSecretProvider(project_id)
    if provider != "google":
        raise ValueError(
            f"Unknown SECRETS_PROVIDER '{provider}'; expected 'google' or 'env'"
        )
    return GoogleSecretProvider(project_id)

