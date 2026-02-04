"""
Skrafldb - persistent data management for the Netskrafl application

Copyright © 2025 Miðeind ehf.
Author: Vilhjálmur Þorsteinsson

The Creative Commons Attribution-NonCommercial 4.0
International Public License (CC-BY-NC 4.0) applies to this software.
For further information, see https://github.com/mideind/Netskrafl

This module is a facade that imports from either the NDB or PostgreSQL
backend implementation based on the DATABASE_BACKEND environment variable.

The backend implementations are:
- skrafldb_ndb.py: Google Cloud NDB (Datastore) - the original implementation
- skrafldb_pg.py: PostgreSQL with SQLAlchemy (migration target)

Usage:
    # Application code imports from skrafldb as before:
    from skrafldb import UserModel, GameModel, Client

    # The actual backend is selected via environment variable:
    # DATABASE_BACKEND=ndb (default) or DATABASE_BACKEND=postgresql
"""

from __future__ import annotations

from src.db.config import get_config

_config = get_config()

if _config.backend == "postgresql":
    from skrafldb_pg import *  # noqa: F401, F403
else:
    from skrafldb_ndb import *  # noqa: F401, F403
