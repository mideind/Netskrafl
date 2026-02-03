"""
NDB (Google Cloud Datastore) backend implementation.

This package wraps the existing skrafldb.py models to implement
the database protocol interface.
"""

from __future__ import annotations

from .backend import NDBBackend

__all__ = ["NDBBackend"]
