"""

    Tests for maintenance mode (src/maintenance.py)
    Copyright © 2026 Miðeind ehf.

    In maintenance mode the server answers every request with HTTP 503,
    except for the health and lifecycle endpoints that the hosting platform
    relies on. The mode is normally switched on by the MAINTENANCE
    environment variable at startup; these tests flip the corresponding
    Flask configuration key instead, which the request handler consults
    on every request.

    None of these tests read from or write to the database.

"""

from __future__ import annotations

from typing import Iterator

import pytest

from utils import CustomClient

import main
from maintenance import MAINTENANCE_KEY, RETRY_AFTER, maintenance_from_env


@pytest.fixture
def maintenance() -> Iterator[None]:
    """Switch maintenance mode on for the duration of a test"""
    previous = main.app.config.get(MAINTENANCE_KEY)
    main.app.config[MAINTENANCE_KEY] = True
    try:
        yield
    finally:
        main.app.config[MAINTENANCE_KEY] = previous


def test_off_by_default(client: CustomClient) -> None:
    """Without the environment variable, requests are handled as usual"""
    assert main.app.config[MAINTENANCE_KEY] is False
    assert client.get("/health/live").status_code == 200
    # An API call without a session is refused, but by the API itself
    resp = client.post("/gamestate", json={"game": "no-such-game"})
    assert resp.status_code != 503
    assert "Retry-After" not in resp.headers


def test_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The MAINTENANCE environment variable is read as a boolean"""
    monkeypatch.delenv(MAINTENANCE_KEY, raising=False)
    assert maintenance_from_env() is False
    for value in ("1", "true", "TRUE", "yes"):
        monkeypatch.setenv(MAINTENANCE_KEY, value)
        assert maintenance_from_env() is True
    for value in ("", "0", "false", "no"):
        monkeypatch.setenv(MAINTENANCE_KEY, value)
        assert maintenance_from_env() is False


def test_api_requests_get_503_json(client: CustomClient, maintenance: None) -> None:
    """API calls are answered with 503 and a JSON body, whether or not
    they would otherwise have required a login"""
    for path in ("/submitmove", "/allgamelists", "/login_malstadur", "/inituser"):
        resp = client.post(path, json={})
        assert resp.status_code == 503, path
        assert resp.headers["Retry-After"] == str(RETRY_AFTER)
        assert resp.headers["Cache-Control"] == "no-store"
        data = resp.get_json()
        assert data["ok"] is False
        assert data["maintenance"] is True
        assert data["message"]
    # A GET from a script (no preference for HTML) gets JSON, too
    resp = client.get("/rating?kind=human")
    assert resp.status_code == 503
    assert resp.is_json


def test_browser_navigation_gets_503_page(
    client: CustomClient, maintenance: None
) -> None:
    """A browser navigating to the site gets a small web page, still
    with status 503"""
    accept = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    for path in ("/", "/page", "/no-such-page"):
        resp = client.get(path, headers={"Accept": accept})
        assert resp.status_code == 503, path
        assert resp.mimetype == "text/html"
        assert resp.headers["Retry-After"] == str(RETRY_AFTER)
        assert "<h1>" in resp.get_data(as_text=True)


def test_scheduled_jobs_are_refused(client: CustomClient, maintenance: None) -> None:
    """Scheduled jobs must not run on a frozen backend. (The test server
    runs locally, where these routes would otherwise be open.)"""
    for path in ("/stats/run", "/stats/ratings", "/connect/update", "/connect/cleanup"):
        resp = client.get(path)
        assert resp.status_code == 503, path


def test_platform_endpoints_stay_up(client: CustomClient, maintenance: None) -> None:
    """The hosting platform must still see a live instance, or it would
    restart it or refuse to route traffic to it"""
    assert client.get("/health/live").status_code == 200
    # The readiness probe may itself answer 503 while vocabularies are being
    # loaded, but never the maintenance response
    resp = client.get("/health/ready")
    assert "Retry-After" not in resp.headers
    assert not resp.is_json
    assert client.get("/_ah/start").status_code == 200
    assert client.get("/_ah/warmup").status_code == 200


def test_cross_origin_client_sees_the_503(
    client: CustomClient, maintenance: None
) -> None:
    """A cross-origin web client (bearer token authentication) gets its
    preflight request answered as usual, and CORS headers on the 503
    response. Without them the browser would hide the status code and
    report a network error instead."""
    origin = "https://some-host.example.com"
    resp = client.options(
        "/allgamelists",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["Access-Control-Allow-Origin"] == origin
    resp = client.post(
        "/allgamelists",
        json={},
        headers={"Origin": origin, "Authorization": "Bearer some-token"},
    )
    assert resp.status_code == 503
    assert resp.headers["Access-Control-Allow-Origin"] == origin
    assert resp.get_json()["maintenance"] is True

