"""

    Mobile app version and client configuration

    Copyright © 2026 Miðeind ehf.
    Author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl


    This module manages the singleton app version / client configuration
    record, which tells mobile clients (via /inituser) which app versions
    are supported and, optionally, which backend endpoints they should use.

    The record is a JSON document (see AppVersionDict) stored in the
    database as the ConfigModel document with id APP_VERSION_ID, and
    cached in Redis for a short time, since /inituser is a hot path.
    New fields only require changes to AppVersionDict and validate_config()
    below - no database schema changes. All reads fail open: if the record
    is missing or cannot be read, no constraints are reported to the client.

"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple, cast

import logging
import re

from cache import memcache
from db.protocols import APP_VERSION_ID, AppVersionDict
from skrafldb import ConfigModel


# Cache namespace and key for the configuration record
_CACHE_NAMESPACE = "appversion"
_CACHE_KEY = "config"
# Cache lifetime in seconds. Updates via the /appversion endpoint
# invalidate the cache immediately; this only bounds staleness across
# other instances/processes.
_CACHE_TTL = 60

# Sentinel stored in the cache when no record exists
_NOT_CONFIGURED: Dict[str, Any] = {}

# Accepted version strings: 1-4 dot-separated numeric components
_VERSION_RE = re.compile(r"^\d+(\.\d+){0,3}$")

# Fields of the configuration record
VERSION_FIELDS = frozenset(
    (
        "min_supported_version",
        "latest_version",
        "ios_min_supported_version",
        "android_min_supported_version",
        "ios_latest_version",
        "android_latest_version",
    )
)
URL_FIELDS = frozenset(("api_url", "moves_url"))
TEXT_FIELDS = frozenset(("update_message",))
ALL_FIELDS = VERSION_FIELDS | URL_FIELDS | TEXT_FIELDS

# Client types that have per-platform overrides
_PLATFORMS = frozenset(("ios", "android"))


def load_config() -> Optional[AppVersionDict]:
    """Return the stored configuration, or None if not configured.
    Fails open (returns None) on database errors."""
    cached = memcache.get(_CACHE_KEY, namespace=_CACHE_NAMESPACE)
    if cached is not None:
        return None if not cached else AppVersionDict(**cached)
    try:
        doc = ConfigModel.get_doc(APP_VERSION_ID)
    except Exception as e:
        logging.warning(f"Unable to load app version config: {e}")
        return None
    d: Optional[AppVersionDict] = None if doc is None else cast(AppVersionDict, doc)
    memcache.set(
        _CACHE_KEY,
        _NOT_CONFIGURED if d is None else dict(d),
        time=_CACHE_TTL,
        namespace=_CACHE_NAMESPACE,
    )
    return d


def validate_config(values: Mapping[str, Any]) -> Tuple[Optional[AppVersionDict], str]:
    """Validate a candidate configuration, returning (config, "")
    if valid, or (None, error_message) otherwise"""
    d = AppVersionDict()
    for key, val in values.items():
        if key not in ALL_FIELDS:
            return None, f"Unknown field: {key}"
        if val is None or val == "":
            continue
        if not isinstance(val, str):
            return None, f"Field {key} must be a string"
        val = val.strip()
        if key in VERSION_FIELDS:
            if not _VERSION_RE.match(val):
                return None, f"Field {key} is not a valid version: {val}"
        elif key in URL_FIELDS:
            if not val.startswith("https://") or len(val) > 256:
                return None, f"Field {key} must be an https:// URL"
        elif len(val) > 1000:
            return None, f"Field {key} is too long"
        d[key] = val  # type: ignore[literal-required]
    if not d.get("min_supported_version") or not d.get("latest_version"):
        return None, "min_supported_version and latest_version are required"
    return d, ""


def save_config(values: AppVersionDict) -> None:
    """Store a (validated) configuration and invalidate the cache"""
    ConfigModel.set_doc(APP_VERSION_ID, dict(values))
    memcache.delete(_CACHE_KEY, namespace=_CACHE_NAMESPACE)


def delete_config() -> None:
    """Remove the configuration and invalidate the cache"""
    ConfigModel.delete_doc(APP_VERSION_ID)
    memcache.delete(_CACHE_KEY, namespace=_CACHE_NAMESPACE)


def client_config(
    client_type: str,
) -> Tuple[Optional[Dict[str, str]], Optional[Dict[str, str]]]:
    """Resolve the configuration for a client of the given type
    ('ios', 'android' or 'web'). Returns a tuple of (app_version, endpoints),
    either of which may be None if not applicable. The app_version
    dictionary has the keys min_supported_version, latest_version and
    optionally update_message; the endpoints dictionary has api_url
    and/or moves_url."""
    d = load_config()
    if d is None:
        return None, None
    platform = client_type if client_type in _PLATFORMS else ""
    min_v = d.get("min_supported_version") or ""
    latest_v = d.get("latest_version") or ""
    if platform:
        min_v = d.get(f"{platform}_min_supported_version") or min_v  # type: ignore[misc]
        latest_v = d.get(f"{platform}_latest_version") or latest_v  # type: ignore[misc]
    app_version: Optional[Dict[str, str]] = None
    if min_v and latest_v:
        app_version = {
            "min_supported_version": min_v,
            "latest_version": latest_v,
        }
        if msg := d.get("update_message"):
            app_version["update_message"] = msg
    endpoints: Dict[str, str] = {}
    if api_url := d.get("api_url"):
        endpoints["api_url"] = api_url
    if moves_url := d.get("moves_url"):
        endpoints["moves_url"] = moves_url
    return app_version, endpoints or None

