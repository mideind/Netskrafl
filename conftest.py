"""
Root pytest configuration.

This conftest.py is discovered by pytest and ensures the src/ directory
is on the Python path for all tests.
"""

from __future__ import annotations

import sys
import os

# Add src/ to Python path so tests can import from it
SRC_PATH = os.path.join(os.path.dirname(__file__), "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

# Also add the project root for imports like 'src.db.protocols'
PROJECT_ROOT = os.path.dirname(__file__)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# When pytest registers 'src' as a namespace package (via 'from src.db...'
# imports in test conftest files), bare imports like 'from db.config import ...'
# inside src/ modules fail because Python resolves 'db' relative to the 'src'
# package but doesn't find it in sys.modules under that name.
# Additionally, 'src.db' and 'db' must be the same module object so that
# module-level state (e.g. the session manager singleton) is shared.
# Fix this by pre-importing 'db' as a top-level module and aliasing it.
import importlib

_db_mod = importlib.import_module("db")
sys.modules.setdefault("db", _db_mod)
# Ensure src.db and db refer to the same module object
sys.modules["src.db"] = _db_mod
