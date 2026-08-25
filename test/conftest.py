"""
Pytest fixtures for the test/ suite.

The shared fixtures (Flask test clients and pre-created test users) are defined
in test/utils.py. Re-exporting them here makes them available to every test
module in this directory without each module having to import them explicitly,
which is easy to forget (and previously left several test modules unable to run
standalone with a "fixture 'client' not found" error).

Modules that still import these fixtures directly from utils (e.g. for type
checkers) continue to work: a module-level fixture of the same name simply
shadows the one provided here.
"""

from __future__ import annotations

from utils import (  # type: ignore  # noqa: F401
    client,
    client1,
    client2,
    u1,
    u2,
    u3_gb,
)

