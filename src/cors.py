"""

    Cross-Origin Resource Sharing (CORS) support for Netskrafl/Explo

    Copyright © 2025 Miðeind ehf.

    This module provides CORS handling that supports two authentication modes:
    1. Bearer token auth: Any origin allowed, no credentials (cookies) needed
    2. Legacy cookie auth: Specific whitelisted origins, credentials required

    The mode is detected based on the Authorization header (for actual requests)
    or Access-Control-Request-Headers (for preflight OPTIONS requests).
    Same-origin requests bypass CORS entirely.

"""

from __future__ import annotations

from typing import Dict, List, Mapping

from flask import Flask, request, Response

from config import CORS_ORIGINS, running_local


# Origins allowed for cookie-based authentication
if running_local:
    # For local development
    _cors_cookie_origins: List[str] = [
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:6006",
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:6006",
    ]
else:
    # Production - use CORS origins from Secret Manager
    _cors_cookie_origins = CORS_ORIGINS


# Static CORS headers shared by both auth modes
_CORS_STATIC_HEADERS: Mapping[str, str] = {
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Max-Age": "86400",
}

# Public endpoints that allow any origin (no auth required)
_PUBLIC_ENDPOINTS: frozenset[str] = frozenset({"/login_malstadur"})


def _get_cors_headers(origin: str, uses_bearer_auth: bool) -> Dict[str, str] | None:
    """Return CORS headers dict based on auth method, or None if not allowed."""
    # Public endpoints allow any origin (like Bearer auth mode)
    if uses_bearer_auth or request.path in _PUBLIC_ENDPOINTS:
        # Bearer token mode or public endpoint: allow any origin, no credentials
        return {"Access-Control-Allow-Origin": origin, **_CORS_STATIC_HEADERS}
    if origin in _cors_cookie_origins:
        # Cookie mode: only whitelisted origins, with credentials
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            **_CORS_STATIC_HEADERS,
        }
    # Origin not in whitelist and not using Bearer auth
    return None


def _handle_cors_preflight() -> Response | None:
    """Handle CORS preflight OPTIONS requests."""
    if request.method != "OPTIONS":
        return None

    origin = request.headers.get("Origin")
    if not origin:
        return None

    # Check if preflight requests Authorization header
    preflight_wants_auth = "authorization" in request.headers.get(
        "Access-Control-Request-Headers", ""
    ).lower()

    cors_headers = _get_cors_headers(origin, preflight_wants_auth)
    if cors_headers:
        # Return 200 OK with CORS headers for preflight
        return Response(status=200, headers=cors_headers)

    # Origin not allowed - let request fail naturally
    return None


def _apply_cors(response: Response) -> Response:
    """Apply CORS headers to actual (non-preflight) responses."""
    origin = request.headers.get("Origin")
    if not origin or request.method == "OPTIONS":
        # Same-origin request or preflight (handled by before_request)
        return response

    # Check if this is a Bearer token request
    uses_bearer_auth = "Authorization" in request.headers

    cors_headers = _get_cors_headers(origin, uses_bearer_auth)
    if cors_headers:
        response.headers.update(cors_headers)

    return response


def init_cors(app: Flask) -> None:
    """Initialize CORS handling for the Flask app.

    Registers before_request and after_request handlers to manage CORS
    headers dynamically based on the authentication method used.
    """
    app.before_request(_handle_cors_preflight)
    app.after_request(_apply_cors)
