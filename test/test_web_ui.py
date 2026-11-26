"""

    Tests for the web routes (src/web.py)
    Copyright © 2026 Miðeind ehf.

    The built-in web UI is a development client: it is served only in a
    deployment where the SINGLE_PAGE environment variable is TRUE (the
    staging app and local development servers). Elsewhere its routes do
    not exist, and the root and greeting pages redirect to the product's
    home on the web, if HOME_REDIRECT_URL is set.

    The settings are read from the environment at startup; these tests
    flip the corresponding module variables instead, which the routes
    consult on every request.

"""

from __future__ import annotations

import pytest

from utils import CustomClient, login_user

import web
from logic import game_url


HOME = "https://home.example/game"

# The routes of the web UI, which exist only where the UI is served
UI_PAGES = ("/page", "/login", "/login_error", "/rawhelp", "/friend")

# Pages of the former server-rendered web UI, which exist nowhere
REMOVED_PAGES = (
    "/help",
    "/twoletter",
    "/newbag",
    "/board",
    "/review",
    "/wait",
    "/newgame",
    "/userprefs",
    "/signup",
    "/skilmalar",
    "/transition",
    "/transition-go",
    "/admin/main",
    "/service-worker.js",
    "/billing",
)


@pytest.fixture
def ui_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment that does not serve the web UI and has no home to
    redirect to"""
    monkeypatch.setattr(web, "SINGLE_PAGE_UI", False)
    monkeypatch.setattr(web, "HOME_REDIRECT_URL", "")


@pytest.fixture
def ui_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment that serves the web UI"""
    monkeypatch.setattr(web, "SINGLE_PAGE_UI", True)
    monkeypatch.setattr(web, "HOME_REDIRECT_URL", "")


def test_root_and_greeting_redirect_home(
    client: CustomClient, ui_off: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the web UI, the root and the greeting page send the
    browser to the configured home"""
    monkeypatch.setattr(web, "HOME_REDIRECT_URL", HOME)
    for path in ("/", "/greet", "/greet?fromlogin=1"):
        resp = client.get(path)
        assert resp.status_code == 302, path
        assert resp.headers["Location"] == HOME, path
    resp = client.head("/")
    assert resp.status_code == 302
    assert resp.headers["Location"] == HOME
    # Logging out ends on the greeting page, and so at home
    resp = client.get("/logout")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/greet"


def test_root_and_greeting_without_home(client: CustomClient, ui_off: None) -> None:
    """Without the web UI and without a home to redirect to, the root
    and the greeting page are unknown URLs"""
    for path in ("/", "/greet"):
        assert client.get(path).status_code == 404, path


def test_ui_routes_do_not_exist_without_ui(
    client: CustomClient, ui_off: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the web UI, its routes answer 404 (and neither redirect to
    a login page nor to the configured home)"""
    monkeypatch.setattr(web, "HOME_REDIRECT_URL", HOME)
    for path in UI_PAGES:
        assert client.get(path).status_code == 404, path
    assert client.get("/oauth2callback").status_code == 404
    assert client.post("/promo", json={"key": "friend"}).status_code == 404


def test_api_routes_in_web_module_are_always_there(
    client: CustomClient, ui_off: None
) -> None:
    """The JSON entry points that live in the web module serve the users'
    clients, and do not depend on the web UI"""
    resp = client.post("/initgame", json={"opp": "robot-0"})
    assert resp.status_code == 401
    assert resp.get_json() == {"ok": False}
    resp = client.post("/gameover", json={"game": "x", "player": "y"})
    assert resp.status_code == 401
    assert resp.is_json
    # The login from Málstaður refuses a request without an e-mail by itself
    resp = client.post("/login_malstadur", json={})
    assert resp.status_code == 401
    assert resp.get_json()["status"] == "invalid"


@pytest.mark.parametrize("serve_ui", [False, True])
def test_removed_pages_are_gone(
    client: CustomClient, monkeypatch: pytest.MonkeyPatch, serve_ui: bool
) -> None:
    """The pages of the former server-rendered UI exist in no deployment"""
    monkeypatch.setattr(web, "SINGLE_PAGE_UI", serve_ui)
    monkeypatch.setattr(web, "HOME_REDIRECT_URL", HOME)
    for path in REMOVED_PAGES:
        assert client.get(path).status_code == 404, path
    # The former billing integration took POSTs. They are now answered
    # like a POST to any other unknown path (405, since the route that
    # serves files from the root takes GETs only), not by a handler.
    unknown = client.post("/no-such-endpoint", json={})
    assert unknown.status_code in (404, 405)
    for path in ("/billing", "/cancelplan"):
        resp = client.post(path, json={})
        assert resp.status_code == unknown.status_code, path
        assert not resp.is_json, path


def test_ui_login_sequence_pages(client: CustomClient, ui_on: None) -> None:
    """With the web UI, a browser without a session is led to the login
    page, and the pages of the login sequence render"""
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/page"
    resp = client.get("/page")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/greet"
    resp = client.get("/greet")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'loginUrl: "/login"' in html
    assert "built/explo" in html
    resp = client.get("/login_error")
    assert resp.status_code == 200
    assert "try-again" in resp.get_data(as_text=True)


def test_ui_wins_over_home_redirect(
    client: CustomClient, ui_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Where the web UI is served, a configured home is not used"""
    monkeypatch.setattr(web, "HOME_REDIRECT_URL", HOME)
    assert client.get("/").headers["Location"] == "/page"
    assert client.get("/greet").status_code == 200


def test_ui_pages_render_for_a_logged_in_user(
    client: CustomClient, ui_on: None, u1: str
) -> None:
    """The single page of the UI, and the HTML fragments that it fetches,
    render for a logged-in user"""
    resp = login_user(client, 1)
    assert resp.status_code == 200
    resp = client.get("/page")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert f'userId: "{u1}"' in html
    assert "drag-drop-touch.esm.js" in html
    # Nothing of the removed UI is referenced
    for gone in ("jquery", "mousetrap", "netskrafl.js", "skrafl-curry"):
        assert gone not in html.lower(), gone
    # The help text, in a locale that has its own and in one that falls
    # back to English
    for locale in ("is_IS", "en_US", "pl_PL"):
        resp = client.get(f"/rawhelp?locale={locale}")
        assert resp.status_code == 200, locale
        # Links to the preferences are tokens that the client acts on
        assert "$$userprefs$$" in resp.get_data(as_text=True), locale
    # The friend promotion, likewise
    for locale in ("is_IS", "pl_PL"):
        resp = client.get(f"/friend?locale={locale}")
        assert resp.status_code == 200, locale
        html = resp.get_data(as_text=True)
        assert "btn-promo-no" in html, locale
        assert "salescloud" not in html, locale
    # The promotion dialog's content
    resp = client.post("/promo", json={"key": "explo"})
    assert resp.status_code == 200
    resp = client.post("/logout")
    assert resp.status_code == 200


def test_game_url_keeps_its_form() -> None:
    """The 'url' field of the game lists has the form that the clients
    parse the game id from, although no such page exists any more"""
    uuid = "ed27b9f0-d429-11eb-8bc7-d43d7ee303b2"
    assert game_url(uuid) == f"/board?game={uuid}"
    assert game_url(uuid, zombie=True) == f"/board?game={uuid}&zombie=1"

