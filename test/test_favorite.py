"""
Favorite-relation tests.

User.add_favorite must not create a duplicate favorite relation when invoked
for a pair that is already a favorite, even across separate requests (i.e.
fresh User instances whose in-memory favorites set is reloaded from the DB).
The NDB FavoriteModel has no uniqueness guard, so the guard lives in
User.add_favorite; this test exercises that path on the NDB backend.
"""

from __future__ import annotations

from skrafldb import Client, FavoriteModel
from skrafluser import User

from utils import client, u1, u2  # type: ignore  # noqa: F401


def test_add_favorite_is_idempotent(client, u1: str, u2: str) -> None:  # type: ignore
    with Client.get_context():
        # Clean slate for this user pair
        FavoriteModel.del_relation(u1, u2)

        # First add, via one User instance
        user_a = User.load_if_exists(u1)
        assert user_a is not None
        user_a.add_favorite(u2)

        # Second add, via a FRESH instance — simulates a separate request, so
        # the in-memory favorites set is reloaded from the DB and must reflect
        # the existing relation, preventing a duplicate write.
        user_b = User.load_if_exists(u1)
        assert user_b is not None
        user_b.add_favorite(u2)

        # Exactly one relation must exist (no duplicate FavoriteModel entity)
        favs = [f for f in FavoriteModel.list_favorites(u1) if f == u2]
        assert len(favs) == 1

        # Cleanup
        FavoriteModel.del_relation(u1, u2)
