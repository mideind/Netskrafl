"""
Tests of the application log (src/applog.py) and of what the application
writes to it: the JSON format, the entry for each request, the entries for
refusals at the paywall and for logins, and the results of scheduled jobs.

The request log is a WSGI middleware that is only installed in a container;
the tests that need it install it around the Flask test app.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask, jsonify
from flask.testing import FlaskClient

from tests.api_e2e.conftest import AuthHelper

UTC = timezone.utc


def events(caplog: pytest.LogCaptureFixture, event: str) -> List[Dict[str, Any]]:
    """Return the structured fields of the logged entries of one kind"""
    fields = [getattr(r, "json_fields", None) for r in caplog.records]
    return [f for f in fields if f and f.get("event") == event]


def records(caplog: pytest.LogCaptureFixture, event: str) -> List[logging.LogRecord]:
    """Return the log records of one kind"""
    return [
        r
        for r in caplog.records
        if (getattr(r, "json_fields", None) or {}).get("event") == event
    ]


# =============================================================================
# The JSON format
# =============================================================================


def format_record(
    message: str,
    *,
    level: int = logging.INFO,
    name: str = "root",
    extra: Optional[Dict[str, Any]] = None,
    exc_info: Any = None,
) -> Dict[str, Any]:
    """Format a log record with JsonFormatter and parse the result"""
    from applog import JsonFormatter

    record = logging.LogRecord(
        name, level, "/app/src/skraflstats.py", 1, message, None, exc_info
    )
    for k, v in (extra or {}).items():
        setattr(record, k, v)
    line = JsonFormatter().format(record)
    assert "\n" not in line
    return json.loads(line)


class TestJsonFormatter:
    """Each log entry is one line of JSON that a log service can index."""

    def test_basic_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROJECT_ID", "netskrafl")
        monkeypatch.setenv("APP_VERSION", "n20261115")
        entry = format_record("Halló, þetta er færsla", level=logging.WARNING)
        assert entry["message"] == "Halló, þetta er færsla"
        assert entry["status"] == "warning"
        assert entry["service"] == "netskrafl"
        assert entry["version"] == "n20261115"
        # An entry from the root logger is named after the module it is in
        assert entry["logger"] == {"name": "skraflstats"}
        # ISO 8601 in UTC, with milliseconds
        ts = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
        assert ts.tzinfo is not None
        assert entry["timestamp"].endswith("Z")

    def test_structured_fields(self) -> None:
        from applog import log_fields

        extra = log_fields("paywall", user_id="u1", has_paid=False, plan="", n=0)
        entry = format_record("Paywall", extra=extra)
        assert entry["event"] == "paywall"
        assert entry["user_id"] == "u1"
        # False and zero are values; empty strings and None are left out
        assert entry["has_paid"] is False
        assert entry["n"] == 0
        assert "plan" not in entry

    def test_fields_cannot_replace_reserved_keys(self) -> None:
        extra = {"json_fields": {"message": "x", "status": "y", "service": "z"}}
        entry = format_record("The real message", extra=extra)
        assert entry["message"] == "The real message"
        assert entry["status"] == "info"
        assert entry.get("service") != "z"

    def test_named_loggers_keep_their_name(self) -> None:
        assert format_record("m", name="request")["logger"] == {"name": "request"}
        assert format_record("m", name="gunicorn.error")["logger"] == {
            "name": "gunicorn"
        }

    def test_exception(self) -> None:
        try:
            raise ValueError("Þetta fór illa")
        except ValueError:
            import sys

            entry = format_record(
                "Villa", level=logging.ERROR, exc_info=sys.exc_info()
            )
        assert entry["status"] == "error"
        assert entry["error"]["kind"] == "ValueError"
        assert entry["error"]["message"] == "Þetta fór illa"
        assert "Traceback" in entry["error"]["stack"]

    def test_values_that_json_does_not_know(self) -> None:
        when = datetime(2026, 11, 15, 3, 0, tzinfo=UTC)
        entry = format_record("m", extra={"json_fields": {"when": when}})
        assert entry["when"].startswith("2026-11-15 03:00")


# =============================================================================
# The request log, around a minimal WSGI app
# =============================================================================


def call_wsgi(
    status: str = "200 OK",
    *,
    method: str = "POST",
    path: str = "/submitmove",
    headers: Optional[Dict[str, str]] = None,
    fail: bool = False,
) -> Tuple[List[Tuple[str, str]], bytes]:
    """Send one request through RequestLogMiddleware around an app that
    answers with the given status; return the response headers and body"""
    from applog import REQUEST_NOTES_KEY, RequestLogMiddleware

    def inner(environ: Dict[str, Any], start_response: Callable[..., Any]) -> Iterable[bytes]:
        if fail:
            raise RuntimeError("The application failed")
        environ[REQUEST_NOTES_KEY]["user_id"] = "user-17"
        start_response(status, [("Content-Type", "text/plain"), ("Content-Length", "2")])
        return [b"ok"]

    environ: Dict[str, Any] = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "token=secret",
        "REMOTE_ADDR": "10.0.0.1",
        "HTTP_USER_AGENT": "TestAgent/1.0",
    }
    for k, v in (headers or {}).items():
        environ["HTTP_" + k.upper().replace("-", "_")] = v
    sent: List[Tuple[str, str]] = []

    def start_response(status: str, headers: List[Tuple[str, str]], *args: Any) -> None:
        sent.extend(headers)

    body = b"".join(RequestLogMiddleware(inner)(environ, start_response))
    return sent, body


class TestRequestLogMiddleware:
    """One entry per request, with what is needed to trace a user's session."""

    def test_entry(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO):
            sent, body = call_wsgi(headers={"do-connecting-ip": "203.0.113.9"})
        assert body == b"ok"
        [entry] = events(caplog, "request")
        assert entry["http"]["method"] == "POST"
        assert entry["http"]["status_code"] == 200
        # The path only: a query string can hold secrets
        assert entry["http"]["url_details"] == {"path": "/submitmove"}
        assert entry["http"]["useragent"] == "TestAgent/1.0"
        assert entry["usr"] == {"id": "user-17"}
        # The client's address, not the proxy's
        assert entry["network"]["client"]["ip"] == "203.0.113.9"
        assert entry["network"]["bytes_written"] == 2
        assert entry["duration"] >= 0
        assert entry["duration_ms"] >= 0
        # The request id is also sent to the client
        assert ("X-Request-Id", entry["request_id"]) in sent
        [record] = records(caplog, "request")
        assert record.levelno == logging.INFO
        assert record.getMessage().startswith("POST /submitmove 200 ")
        assert "user user-17" in record.getMessage()
        assert "secret" not in record.getMessage()

    def test_client_address(self) -> None:
        from applog import client_address

        assert client_address({"REMOTE_ADDR": "10.0.0.1"}) == "10.0.0.1"
        assert (
            client_address(
                {"REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": "198.51.100.7, 10.0.0.2"}
            )
            == "198.51.100.7"
        )
        assert (
            client_address(
                {"HTTP_X_FORWARDED_FOR": "198.51.100.7", "HTTP_DO_CONNECTING_IP": "203.0.113.9"}
            )
            == "203.0.113.9"
        )

    @pytest.mark.parametrize(
        "method,path",
        [("OPTIONS", "/submitmove"), ("GET", "/health/ready"), ("GET", "/static/a.js")],
    )
    def test_quiet_requests_are_not_logged(
        self, caplog: pytest.LogCaptureFixture, method: str, path: str
    ) -> None:
        with caplog.at_level(logging.INFO):
            call_wsgi(method=method, path=path)
        assert events(caplog, "request") == []

    def test_quiet_requests_are_logged_when_they_fail(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO):
            call_wsgi("503 Service Unavailable", method="GET", path="/health/ready")
        [record] = records(caplog, "request")
        assert record.levelno == logging.ERROR

    def test_exception_in_the_application(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO), pytest.raises(RuntimeError):
            call_wsgi(fail=True)
        [entry] = events(caplog, "request")
        assert entry["http"]["status_code"] == 500


# =============================================================================
# The request log, around the real application
# =============================================================================


@pytest.fixture
def request_log(app: Flask, caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Install the request log around the Flask test app,
    as main.py does in a container"""
    from applog import RequestLogMiddleware

    original = app.wsgi_app
    app.wsgi_app = RequestLogMiddleware(original)  # type: ignore[assignment,arg-type]
    caplog.set_level(logging.INFO)
    try:
        yield
    finally:
        app.wsgi_app = original  # type: ignore[method-assign]


def request_entry(caplog: pytest.LogCaptureFixture, path: str) -> Dict[str, Any]:
    """Return the entry of the last request for the given path"""
    found = [
        e for e in events(caplog, "request") if e["http"]["url_details"]["path"] == path
    ]
    assert found, f"No request entry for {path}"
    return found[-1]


@pytest.mark.api_e2e
class TestApplicationRequestLog:
    """What the application adds to the entry of a request."""

    def test_user_of_a_request(
        self,
        client: FlaskClient,
        auth: AuthHelper,
        request_log: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        login = auth.login_user(
            sub=f"log-user-{uuid.uuid4().hex[:8]}",
            name="Log User",
            email=f"log-{uuid.uuid4().hex[:8]}@example.com",
        )
        client.post("/userlist", json={"query": "robots"})
        entry = request_entry(caplog, "/userlist")
        assert entry["usr"] == {"id": login["user_id"]}
        assert entry["http"]["status_code"] == 200
        # A request that is served has nothing to say about a refusal
        assert "api" not in entry
        auth.logout()

    def test_refusal_at_the_paywall(
        self,
        client: FlaskClient,
        auth: AuthHelper,
        request_log: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A free user who asks for a premium robot is refused with HTTP 200.
        The log says so twice: in the request's entry, and in an entry of
        its own with the user's subscription state."""
        login = auth.login_user(
            sub=f"log-free-{uuid.uuid4().hex[:8]}",
            name="Free Logger",
            email=f"logfree-{uuid.uuid4().hex[:8]}@example.com",
        )
        response = client.post("/initgame", json={"opp": "robot-0"})
        assert response.get_json() == {"ok": False, "err": "premium_required"}

        entry = request_entry(caplog, "/initgame")
        assert entry["api"] == {"ok": False, "err": "premium_required"}
        assert entry["usr"] == {"id": login["user_id"]}
        [record] = [
            r for r in records(caplog, "request") if "/initgame" in r.getMessage()
        ]
        assert record.getMessage().endswith("refused: premium_required")

        [paywall] = events(caplog, "paywall")
        assert paywall["reason"] == "premium_required"
        assert paywall["user_id"] == login["user_id"]
        assert paywall["plan"] == "none"
        assert paywall["has_paid"] is False
        assert paywall["inconsistent"] is False
        # The paywall entry is logged during the request, and carries its id
        [paywall_record] = records(caplog, "paywall")
        assert paywall_record.levelno == logging.INFO
        auth.logout()

    def test_inconsistent_subscription_state_is_a_warning(
        self,
        client: FlaskClient,
        auth: AuthHelper,
        request_log: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A user whose plan says subscriber but who is refused as unpaid
        (the state left by the PostgreSQL login bug of November 2026)
        must stand out in the log."""
        from skrafluser import User

        login = auth.login_user(
            sub=f"log-odd-{uuid.uuid4().hex[:8]}",
            name="Odd State",
            email=f"logodd-{uuid.uuid4().hex[:8]}@example.com",
        )
        user = User.load_if_exists(login["user_id"])
        assert user is not None
        user._plan = "friend"  # pyright: ignore[reportPrivateUsage]
        user.set_friend(False)
        user.set_has_paid(False)
        user.update()

        client.post("/initgame", json={"opp": "robot-0"})
        [paywall] = events(caplog, "paywall")
        assert paywall["plan"] == "friend"
        assert paywall["has_paid"] is False
        assert paywall["inconsistent"] is True
        [record] = records(caplog, "paywall")
        assert record.levelno == logging.WARNING
        auth.logout()

    def test_malstadur_login_entry(
        self,
        client: FlaskClient,
        request_log: None,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The login entry says what the host's token claimed and what the
        user ended up with; the request's entry names the user."""
        import web

        email = f"log-sub-{uuid.uuid4().hex[:8]}@example.com"
        claims = {"sub": f"sub-{email}", "email": email, "plan": "friend"}
        monkeypatch.setattr(web, "verify_malstadur_token", lambda token: (False, claims))
        response = client.post(
            "/login_malstadur", json=dict(email=email, token="t", bearer_auth=True)
        )
        data = response.get_json()
        assert data is not None and data["status"] == "success"

        [login] = [
            e for e in events(caplog, "malstadur_login") if e["outcome"] == "success"
        ]
        assert login["user_id"] == data["user_id"]
        assert login["token_plan"] == "friend"
        assert login["friend"] is True
        assert login["has_paid"] is True
        entry = request_entry(caplog, "/login_malstadur")
        assert entry["usr"] == {"id": data["user_id"]}

    def test_result_codes(
        self,
        client: FlaskClient,
        request_log: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A result code that is a refusal is named in the request's entry;
        a move that ends the game (GAME_OVER) is not a refusal."""
        from applog import note_api_outcome
        from config import Error
        from main import _RESULTS_NOT_REFUSALS, _result_name, app  # pyright: ignore[reportPrivateUsage]

        # An API call without a login is refused with LOGIN_REQUIRED
        client.post("/gamelist", json={})
        entry = request_entry(caplog, "/gamelist")
        assert entry["api"] == {"result": Error.LOGIN_REQUIRED, "reason": "LOGIN_REQUIRED"}
        [record] = [r for r in records(caplog, "request") if "/gamelist" in r.getMessage()]
        assert record.getMessage().endswith("refused: LOGIN_REQUIRED")

        assert Error.GAME_OVER in _RESULTS_NOT_REFUSALS
        assert Error.LEGAL in _RESULTS_NOT_REFUSALS
        assert _result_name(Error.WORD_NOT_IN_DICTIONARY) == "WORD_NOT_IN_DICTIONARY"
        assert _result_name(Error.GAME_OVER) == "GAME_OVER"
        # Not result codes of the API
        assert _result_name(57) is None
        assert _result_name(-1) is None

        # What the hook notes for each kind of answer
        def noted(result: int) -> Dict[str, Any]:
            from applog import REQUEST_NOTES_KEY

            notes: Dict[str, Any] = {}
            with app.test_request_context(
                "/submitmove", method="POST", environ_base={REQUEST_NOTES_KEY: notes}
            ):
                note_api_outcome(
                    jsonify(result=result),
                    ok_results=_RESULTS_NOT_REFUSALS,
                    result_name=_result_name,
                )
            return notes

        assert noted(Error.LEGAL) == {}
        assert noted(Error.GAME_OVER) == {}
        assert noted(Error.WORD_NOT_IN_DICTIONARY) == {
            "api": {"result": 7, "reason": "WORD_NOT_IN_DICTIONARY"}
        }
        assert noted(57) == {"api": {"result": 57}}

    def test_refused_login(
        self,
        client: FlaskClient,
        request_log: None,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import web

        monkeypatch.setattr(web, "verify_malstadur_token", lambda token: (True, None))
        response = client.post(
            "/login_malstadur",
            json=dict(email="someone@example.com", token="t", bearer_auth=True),
        )
        assert response.get_json()["status"] == "expired"
        entry = request_entry(caplog, "/login_malstadur")
        assert entry["api"] == {"status": "expired"}


# =============================================================================
# Results of scheduled jobs
# =============================================================================


class TestJobEntries:
    """A scheduled job ends with one entry that can be read on its own."""

    def test_log_job(self, caplog: pytest.LogCaptureFixture) -> None:
        from applog import log_job

        with caplog.at_level(logging.INFO):
            log_job("ratings", True, 4.23, "all 100/100", rows={"all": 100})
            log_job("stats", False, 61.0, "Gave up after two retries")
        ok, failed = records(caplog, "job")
        assert ok.getMessage() == "Job ratings: OK in 4.2 s; all 100/100"
        assert ok.levelno == logging.INFO
        assert failed.getMessage() == "Job stats: FAILED in 61.0 s; Gave up after two retries"
        assert failed.levelno == logging.ERROR
        first, second = events(caplog, "job")
        assert first == dict(
            event="job", job="ratings", ok=True, seconds=4.23, rows={"all": 100}
        )
        assert second["ok"] is False

    def test_ratings_table_info(self) -> None:
        from skraflstats import RatingsTableInfo

        # A full table whose candidates reach below the cutoff
        info = RatingsTableInfo(
            "human", rows=100, elo_top=1784, elo_cutoff=1564,
            candidates=152, weakest_candidate=1498,
        )
        assert info.full and info.complete and info.ok
        assert info.summary() == (
            "Ratings table 'human': 100 of 100 rows, Elo 1784 to 1564, "
            "152 candidates, weakest 1498"
        )
        # The old App Engine problem: a truncated table
        short = RatingsTableInfo(
            "all", rows=83, elo_top=2100, elo_cutoff=1700,
            candidates=150, weakest_candidate=1650,
        )
        assert not short.full and not short.ok
        assert "NOT FULL" in short.summary()
        # No candidate below the cutoff: somebody outside may belong in it
        tight = RatingsTableInfo(
            "all", rows=100, elo_top=2100, elo_cutoff=1700,
            candidates=150, weakest_candidate=1705,
        )
        assert tight.full and not tight.complete
        assert "POSSIBLY INCOMPLETE" in tight.summary()
        # A small database: every user is a candidate
        small = RatingsTableInfo(
            "manual", rows=7, elo_top=1300, elo_cutoff=1200,
            candidates=7, weakest_candidate=1200, all_users=True,
        )
        assert small.ok

    @pytest.mark.api_e2e
    def test_ratings_job(
        self, client: FlaskClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The ratings task reports each table and ends with a job entry."""
        from skraflstats import MAX_RATINGS, RATING_KINDS, deferred_ratings

        with caplog.at_level(logging.INFO):
            assert deferred_ratings(wait=True)
        tables = events(caplog, "ratings_table")
        assert [t["kind"] for t in tables] == list(RATING_KINDS)
        for t in tables:
            assert 0 <= t["rows"] <= MAX_RATINGS
            assert t["full"] is True
            assert t["complete"] is True
            assert t["elo_top"] >= t["elo_cutoff"]
        [job] = events(caplog, "job")
        assert job["job"] == "ratings"
        assert job["ok"] is True
        assert job["tables_ok"] is True
        assert set(job["rows"]) == set(RATING_KINDS)
        [record] = records(caplog, "job")
        assert record.getMessage().startswith("Job ratings: OK in ")
        assert "human " in record.getMessage()

    @pytest.mark.api_e2e
    def test_stats_job(
        self, client: FlaskClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The stats task ends with a job entry that has its counts."""
        from skraflstats import deferred_stats

        # A day long before any game in the test database
        from_time = datetime(2001, 1, 1, tzinfo=UTC)
        with caplog.at_level(logging.INFO):
            assert deferred_stats(from_time, from_time + timedelta(days=1), wait=True)
        [job] = events(caplog, "job")
        assert job["job"] == "stats"
        assert job["ok"] is True
        assert job["games"] == 0
        assert job["users"] == 0
        assert job["period"] == "2001-01-01"
        [record] = records(caplog, "job")
        assert "0 games and 0 users, played on 2001-01-01" in record.getMessage()

    @pytest.mark.api_e2e
    def test_cleanup_job(
        self,
        client: FlaskClient,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The Firebase cleanup ends with a job entry, and records its run
        in the database like the stats and ratings tasks do."""
        import firebase
        import rtdb_cleanup
        from skrafldb import CompletionModel

        recorded: List[Tuple[str, bool]] = []
        monkeypatch.setattr(
            CompletionModel,
            "add_completion",
            classmethod(lambda cls, proctype, ts_from, ts_to: recorded.append((proctype, True))),
        )
        monkeypatch.setattr(
            CompletionModel,
            "add_failure",
            classmethod(
                lambda cls, proctype, ts_from, ts_to, reason: recorded.append((proctype, False))
            ),
        )

        def fake_cleanup(access: Any, *, dry_run: bool = False, **kwargs: Any) -> Any:
            # Nothing is read from or deleted in a real database
            result = rtdb_cleanup.CleanupResult(dry_run=dry_run, elapsed=1.5)
            result.stats["connection"] = rtdb_cleanup.PathStats(scanned=183)
            result.stats["game"] = rtdb_cleanup.PathStats(
                scanned=4124, expired=42, deleted=0 if dry_run else 42
            )
            return result

        monkeypatch.setattr(firebase.rtdb_cleanup, "cleanup", fake_cleanup)

        with caplog.at_level(logging.INFO):
            response = client.get("/connect/cleanup")
        assert response.status_code == 200
        [job] = events(caplog, "job")
        assert job["job"] == "cleanup"
        assert job["ok"] is True
        assert job["deleted"] == {"connection": 0, "game": 42}
        assert job["expired"] == {"connection": 0, "game": 42}
        [record] = records(caplog, "job")
        assert record.getMessage() == (
            "Job cleanup: OK in 1.5 s; connection/ 0 deleted of 0 expired; "
            "game/ 42 deleted of 42 expired"
        )
        assert recorded == [("cleanup", True)]

        # A dry run is logged, but not recorded as a run
        caplog.clear()
        recorded.clear()
        with caplog.at_level(logging.INFO):
            client.get("/connect/cleanup?dry_run=1")
        [job] = events(caplog, "job")
        assert job["dry_run"] is True
        assert recorded == []

