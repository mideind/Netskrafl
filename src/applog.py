"""

    Application logging for Netskrafl and Explo

    Copyright © 2026 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This module holds what the container deployment needs in order to write
    a log that can be searched and aggregated (see doc/logging.md):

    * JsonFormatter writes each log entry as one line of JSON, with the
      structured fields that a logging call attaches via log_fields().
    * RequestLogMiddleware writes one entry per HTTP request, with its
      duration, status, user id and client address. It replaces the access
      log of the web server, which knows none of the last two.
    * note_request() and note_api_outcome() let the application add what it
      knows about a request (the user, a refusal) to that entry.
    * log_job() writes the one-line result of a scheduled job.

    The attribute names follow the conventions of log services (Datadog's
    standard attributes), so that the entries need no parsing rules there.

    The module depends on the standard library and Flask only, since
    config.py sets up logging before any other application module is loaded.

"""

from __future__ import annotations

from typing import (
    Any,
    Callable,
    Collection,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Tuple,
)

import json
import logging
import os
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone

from flask import Response, g, has_request_context, request


# WSGI environment keys, set by RequestLogMiddleware
REQUEST_ID_KEY = "applog.request_id"
REQUEST_NOTES_KEY = "applog.notes"

# JSON responses larger than this are not inspected for a refusal:
# refusals are small, and large responses are lists that were served
_MAX_OUTCOME_LENGTH = 2048

# Requests that are logged only if they fail: CORS preflights, the
# platform's health probes and static files
_QUIET_METHODS = frozenset(("OPTIONS",))
_QUIET_PREFIXES = ("/health/", "/static/")

# Loggers for the entries written by this module
_request_log = logging.getLogger("request")
_job_log = logging.getLogger("job")

# Keys in a JSON log entry that structured fields may not replace
_RESERVED = frozenset(
    ("timestamp", "status", "message", "logger", "service", "version", "env")
)

WsgiApp = Callable[[Dict[str, Any], Callable[..., Any]], Iterable[bytes]]


def log_fields(event: str, **fields: Any) -> Dict[str, Any]:
    """Return an 'extra' argument for a logging call that attaches structured
    fields to the log entry. In a container, the entry is written as JSON with
    these fields next to 'message' (see JsonFormatter); on App Engine, Cloud
    Logging stores it as a jsonPayload with them. One user's entries can then
    be found with a filter on user_id. Locally the fields are not shown, so
    the message text should still carry the essential information.
    Empty fields are left out."""
    json_fields: Dict[str, Any] = {"event": event}
    json_fields.update((k, v) for k, v in fields.items() if v is not None and v != "")
    return {"json_fields": json_fields}


def _request_context() -> Dict[str, Any]:
    """Return the id of the request being handled and of its user, if any,
    for entries that are logged while a request is in progress"""
    ctx: Dict[str, Any] = {}
    if not has_request_context():
        return ctx
    try:
        if request_id := request.environ.get(REQUEST_ID_KEY):
            ctx["request_id"] = request_id
        user = g.get("user")
        user_id = user.id() if user is not None else None
        if not user_id:
            notes = request.environ.get(REQUEST_NOTES_KEY) or {}
            user_id = notes.get("user_id")
        if user_id:
            ctx["usr"] = {"id": user_id}
    except Exception:
        # Logging must never fail because of what it tries to add
        pass
    return ctx


class JsonFormatter(logging.Formatter):
    """Format a log record as one line of JSON"""

    def __init__(self) -> None:
        super().__init__()
        # Unified service tags; the DD_* variables override the defaults
        env = os.environ
        self._service = env.get("DD_SERVICE") or env.get("PROJECT_ID", "")
        self._version = env.get("DD_VERSION") or env.get("APP_VERSION", "")
        self._env = env.get("DD_ENV", "")

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, timezone.utc)
        # Most of the application logs through the root logger;
        # name the module instead, which says where an entry comes from
        name = record.module if record.name == "root" else record.name
        if name == "gunicorn.error":
            # gunicorn's log for everything that is not a request
            name = "gunicorn"
        # The entry starts with what a person reading the raw log looks for
        entry: Dict[str, Any] = {
            "timestamp": ts.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "status": record.levelname.lower(),
            "message": record.getMessage(),
            "logger": {"name": name},
        }
        if self._service:
            entry["service"] = self._service
        if self._version:
            entry["version"] = self._version
        if self._env:
            entry["env"] = self._env
        fields = getattr(record, "json_fields", None)
        if isinstance(fields, dict):
            entry.update((k, v) for k, v in fields.items() if k not in _RESERVED)
        for k, v in _request_context().items():
            entry.setdefault(k, v)
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, exc, tb = record.exc_info
            entry["error"] = {
                "kind": exc_type.__name__,
                "message": str(exc),
                "stack": "".join(traceback.format_exception(exc_type, exc, tb)),
            }
        return json.dumps(entry, ensure_ascii=False, default=str)


def configure_container_logging() -> None:
    """Log INFO and above to stderr, where the container platform collects
    it: as JSON, or as plain text if LOG_FORMAT is 'text'. Replaces any
    handler that the root logger has."""
    handler = logging.StreamHandler(sys.stderr)
    if os.environ.get("LOG_FORMAT", "json").lower() == "text":
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    else:
        handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def note_request(**fields: Any) -> None:
    """Add fields to the log entry of the request being handled.
    Does nothing if requests are not being logged by RequestLogMiddleware."""
    if not has_request_context():
        return
    notes: Optional[Dict[str, Any]] = request.environ.get(REQUEST_NOTES_KEY)
    if notes is not None:
        notes.update((k, v) for k, v in fields.items() if v is not None and v != "")


def note_api_outcome(
    response: Response,
    *,
    ok_results: Collection[int] = (0,),
    result_name: Optional[Callable[[int], Optional[str]]] = None,
) -> None:
    """If a JSON response tells the client that the request was refused,
    note the reason in the log entry of the request. The API answers such
    requests with HTTP 200 and ok=false, a result code or a status string,
    so the refusal would otherwise be invisible in the log. The result
    codes in ok_results are not refusals (a legal move, a move that ends
    the game); result_name gives the name of a result code, if it has one."""
    if not has_request_context():
        return
    if request.environ.get(REQUEST_NOTES_KEY) is None:
        return
    if response.mimetype != "application/json" or response.direct_passthrough:
        return
    length = response.content_length
    if length is None or length > _MAX_OUTCOME_LENGTH:
        return
    data: Any = response.get_json(silent=True)
    if not isinstance(data, dict):
        return
    api: Dict[str, Any] = {}
    if data.get("ok") is False:
        api["ok"] = False
        err = data.get("err")
        if isinstance(err, (str, int)) and not isinstance(err, bool):
            api["err"] = err
    result = data.get("result")
    if (
        isinstance(result, int)
        and not isinstance(result, bool)
        and result not in ok_results
    ):
        api["result"] = result
        if result_name is not None and (name := result_name(result)):
            api["reason"] = name
    status = data.get("status")
    if status in ("invalid", "expired"):
        api["status"] = status
    if api:
        note_request(api=api)


def client_address(environ: Mapping[str, Any]) -> str:
    """Return the address of the client that made a request. Behind the
    platform's proxies, the peer address is the proxy's; the client's is in
    a header that the proxy sets."""
    for key in ("HTTP_DO_CONNECTING_IP", "HTTP_CF_CONNECTING_IP"):
        if value := environ.get(key):
            return str(value).strip()
    if forwarded := environ.get("HTTP_X_FORWARDED_FOR"):
        return str(forwarded).split(",")[0].strip()
    return str(environ.get("REMOTE_ADDR", ""))


def _is_quiet(method: str, path: str, status: int) -> bool:
    """Requests that say nothing when they succeed are not logged"""
    if status >= 400 or status == 0:
        return False
    return method in _QUIET_METHODS or path.startswith(_QUIET_PREFIXES)


class RequestLogMiddleware:
    """WSGI middleware that logs each request as one entry when it has been
    answered. Installed outermost, so that the duration covers everything
    that happens in the application, including the database commit at the
    end of a request."""

    def __init__(self, wsgi_app: WsgiApp) -> None:
        self._app = wsgi_app

    def __call__(
        self, environ: Dict[str, Any], start_response: Callable[..., Any]
    ) -> Iterable[bytes]:
        t0 = time.perf_counter()
        request_id = uuid.uuid4().hex
        notes: Dict[str, Any] = {}
        environ[REQUEST_ID_KEY] = request_id
        environ[REQUEST_NOTES_KEY] = notes
        answer: Dict[str, Any] = {}

        def _start_response(
            status: str, headers: List[Tuple[str, str]], *args: Any
        ) -> Any:
            try:
                answer["status"] = int(status.split(" ", 1)[0])
            except ValueError:
                answer["status"] = 0
            for name, value in headers:
                if name.lower() == "content-length" and value.isdigit():
                    answer["length"] = int(value)
            headers = list(headers) + [("X-Request-Id", request_id)]
            return start_response(status, headers, *args)

        try:
            result = self._app(environ, _start_response)
        except Exception:
            self._log(environ, request_id, 500, None, t0, notes)
            raise
        self._log(
            environ,
            request_id,
            answer.get("status", 0),
            answer.get("length"),
            t0,
            notes,
        )
        return result

    @staticmethod
    def _log(
        environ: Mapping[str, Any],
        request_id: str,
        status: int,
        length: Optional[int],
        t0: float,
        notes: Dict[str, Any],
    ) -> None:
        """Write the log entry of a request"""
        try:
            method = str(environ.get("REQUEST_METHOD", ""))
            path = str(environ.get("PATH_INFO", ""))
            if _is_quiet(method, path, status):
                return
            seconds = time.perf_counter() - t0
            ms = seconds * 1000.0
            notes = dict(notes)
            user_id = notes.pop("user_id", None)
            api: Dict[str, Any] = notes.get("api") or {}
            http: Dict[str, Any] = {
                "method": method,
                "status_code": status,
                "url_details": {"path": path},
            }
            if agent := environ.get("HTTP_USER_AGENT"):
                http["useragent"] = agent
            network: Dict[str, Any] = {"client": {"ip": client_address(environ)}}
            if length is not None:
                network["bytes_written"] = length
            fields: Dict[str, Any] = dict(
                request_id=request_id,
                http=http,
                network=network,
                # The standard duration attribute is in nanoseconds
                duration=int(seconds * 1e9),
                duration_ms=round(ms, 1),
                **notes,
            )
            if user_id:
                fields["usr"] = {"id": user_id}
            message = f"{method} {path} {status} {ms:.0f} ms"
            if user_id:
                message += f" user {user_id}"
            if api:
                reason = api.get("err") or api.get("reason") or api.get("status")
                if reason is None:
                    reason = api.get("result", "")
                message += f" refused: {reason}" if reason != "" else " refused"
            level = logging.ERROR if status >= 500 or status == 0 else logging.INFO
            _request_log.log(level, message, extra=log_fields("request", **fields))
        except Exception:
            # Never let the logging of a request disturb the request itself
            logging.exception("Could not log a request")


def log_job(
    job: str, ok: bool, seconds: float, summary: str = "", **fields: Any
) -> None:
    """Log the result of a scheduled job as one entry, readable on its own:
    'Job ratings: OK in 4.2 s; all 100/100, human 100/100, manual 100/100'.
    The fields make the same facts available to queries and monitors."""
    message = f"Job {job}: {'OK' if ok else 'FAILED'} in {seconds:.1f} s"
    if summary:
        message += f"; {summary}"
    _job_log.log(
        logging.INFO if ok else logging.ERROR,
        message,
        extra=log_fields("job", job=job, ok=ok, seconds=round(seconds, 2), **fields),
    )

