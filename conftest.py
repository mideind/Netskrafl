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
