"""

    Logger class for gunicorn in the container deployment

    Copyright © 2026 Miðeind ehf.

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    gunicorn writes its own log entries (start-up, worker boots, worker
    timeouts) in a text format of its own. This class, given to gunicorn
    with --logger-class gunicorn_logger.JsonLogger, makes it write them as
    JSON instead, like the application does (see applog.py), so that a
    worker timeout is as easy to find and to alert on as an application
    error. Requests are logged by the application, not by gunicorn.

"""

from __future__ import annotations

from typing import Any

import os

from gunicorn.glogging import Logger  # type: ignore[import-untyped]

from applog import JsonFormatter


class JsonLogger(Logger):  # type: ignore[misc]
    """gunicorn logger that formats the error log as JSON"""

    def setup(self, cfg: Any) -> None:
        super().setup(cfg)  # pyright: ignore[reportUnknownMemberType]
        if os.environ.get("LOG_FORMAT", "json").lower() == "text":
            return
        formatter = JsonFormatter()
        for handler in self.error_log.handlers:  # pyright: ignore
            handler.setFormatter(formatter)

