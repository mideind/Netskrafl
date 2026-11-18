"""
Tests for the users' pictures (the image_blob of a user).

A picture is a few hundred kilobytes. Almost everything that loads a user
only needs to know WHETHER the user has a picture, in order to hand out the
right image address; the picture itself is only needed by the image
endpoints. On PostgreSQL, the picture column is therefore loaded on demand,
and the has_image_blob attribute is computed in the database. These tests
check that the answer is right, on both backends, and that the picture is
not read from PostgreSQL unless asked for.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

import pytest

if TYPE_CHECKING:
    from src.db.protocols import DatabaseBackendProtocol


# A stand-in for a base64-encoded picture; the content is of no concern here
PICTURE = b"/9j/4AAQSkZJRgABAQEASABIAAD/" * 64


def _make_user(backend: "DatabaseBackendProtocol", user_id: str, nickname: str) -> Any:
    """Create a user (unless a previous run on this backend left it behind)
    and return it without a picture"""
    user = backend.users.get_by_id(user_id)
    if user is None:
        backend.users.create(
            user_id=user_id,
            account=f"test:{user_id}",
            email=None,
            nickname=nickname,
            locale="is_IS",
        )
        user = backend.users.get_by_id(user_id)
    assert user is not None
    backend.users.update(user, image="", image_blob=None)
    return user


def _get(backend: "DatabaseBackendProtocol", user_id: str) -> Any:
    """Load a user, as the backend's own entity type (the tests below look
    at attributes that are not part of the common entity protocol)"""
    user = backend.users.get_by_id(user_id)
    assert user is not None
    return user


def _found(backend: "DatabaseBackendProtocol", prefix: str, user_id: str) -> Any:
    """Find a user through the nickname search, which is how lists of users
    learn whether each of them has a picture"""
    matches = [
        u for u in backend.users.list_prefix(prefix, locale="is_IS") if u.id == user_id
    ]
    assert len(matches) == 1, f"user {user_id} not found by prefix {prefix!r}"
    return matches[0]


class TestHasPicture:
    """Whether a user has a picture, as seen in lists of users"""

    def test_search_tells_whether_user_has_picture(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """The answer follows the picture as it is set and removed."""
        user = _make_user(backend, "picture-user-001", "Qqpictureone")
        assert _found(backend, "Qqpictureo", "picture-user-001").has_image_blob is False

        backend.users.update(user, image="image/jpeg", image_blob=PICTURE)
        found = _found(backend, "Qqpictureo", "picture-user-001")
        assert found.has_image_blob is True
        assert found.image == "image/jpeg"

        backend.users.update(user, image="", image_blob=None)
        assert _found(backend, "Qqpictureo", "picture-user-001").has_image_blob is False

    def test_empty_picture_is_no_picture(
        self, backend: "DatabaseBackendProtocol"
    ) -> None:
        """A picture of no bytes counts as no picture, on both backends."""
        user = _make_user(backend, "picture-user-002", "Qqpicturetwo")
        backend.users.update(user, image="image/jpeg", image_blob=b"")
        assert _found(backend, "Qqpicturet", "picture-user-002").has_image_blob is False


class TestPictureIsLoadedOnDemand:
    """PostgreSQL only: the picture stays in the database until asked for"""

    @staticmethod
    def _reload(backend: "DatabaseBackendProtocol", user: Any) -> None:
        """Forget what the session knows about the user, so that the next
        access reads it from the database as a new request would"""
        from sqlalchemy import inspect

        session = inspect(user).session
        assert session is not None
        session.expire_all()

    @staticmethod
    def _unloaded(user: Any) -> set[str]:
        from sqlalchemy import inspect

        return set(inspect(user).unloaded)

    def test_loading_a_user_does_not_load_the_picture(
        self, pg_backend: "DatabaseBackendProtocol"
    ) -> None:
        user = _make_user(pg_backend, "picture-user-010", "Qqpictureten")
        pg_backend.users.update(user, image="image/jpeg", image_blob=PICTURE)
        self._reload(pg_backend, user)

        loaded = _get(pg_backend, "picture-user-010")
        # Reading ordinary attributes loads the row, but not the picture
        assert loaded.nickname == "Qqpictureten"
        assert loaded.has_image_blob is True
        assert "image_blob" in self._unloaded(loaded)

        # Asking for the picture reads it
        assert loaded.image_blob == PICTURE
        assert "image_blob" not in self._unloaded(loaded)

    def test_loading_many_users_does_not_load_their_pictures(
        self, pg_backend: "DatabaseBackendProtocol"
    ) -> None:
        ids = [f"picture-user-02{i}" for i in range(3)]
        users = [_make_user(pg_backend, uid, f"Qqpicturemany{i}") for i, uid in enumerate(ids)]
        for i, user in enumerate(users):
            # The middle one has no picture
            picture: Optional[bytes] = None if i == 1 else PICTURE
            pg_backend.users.update(user, image="image/jpeg", image_blob=picture)
        self._reload(pg_backend, users[0])

        loaded: list[Any] = list(pg_backend.users.get_multi(ids))
        assert all(u is not None for u in loaded)
        assert [u.has_image_blob for u in loaded] == [True, False, True]
        for u in loaded:
            assert "image_blob" in self._unloaded(u)

    def test_answer_follows_changes_within_a_session(
        self, pg_backend: "DatabaseBackendProtocol"
    ) -> None:
        """The same user object answers correctly after its picture has
        been set, replaced by an empty one and removed."""
        user = _make_user(pg_backend, "picture-user-030", "Qqpicturethirty")
        assert user.has_image_blob is False
        pg_backend.users.update(user, image="image/jpeg", image_blob=PICTURE)
        assert user.has_image_blob is True
        pg_backend.users.update(user, image_blob=b"")
        assert user.has_image_blob is False
        pg_backend.users.update(user, image_blob=PICTURE)
        assert user.has_image_blob is True
        pg_backend.users.update(user, image="", image_blob=None)
        assert user.has_image_blob is False

    def test_setting_a_picture_does_not_read_the_old_one(
        self, pg_backend: "DatabaseBackendProtocol"
    ) -> None:
        """Replacing a picture writes the new one without first fetching
        the one that is being replaced."""
        from sqlalchemy import event, inspect

        user = _make_user(pg_backend, "picture-user-040", "Qqpictureforty")
        pg_backend.users.update(user, image="image/jpeg", image_blob=PICTURE)
        self._reload(pg_backend, user)
        user = _get(pg_backend, "picture-user-040")
        assert user.nickname == "Qqpictureforty"

        session = inspect(user).session
        assert session is not None
        statements: list[str] = []

        def note(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
            statements.append(statement)

        engine = session.get_bind()
        event.listen(engine, "before_cursor_execute", note)
        try:
            pg_backend.users.update(user, image_blob=PICTURE + b"AAAA")
        finally:
            event.remove(engine, "before_cursor_execute", note)
        selects_of_picture = [
            s for s in statements
            if s.lstrip().upper().startswith("SELECT") and "image_blob AS" in s
        ]
        assert not selects_of_picture, f"the old picture was read: {selects_of_picture}"
        assert any(s.lstrip().upper().startswith("UPDATE") for s in statements)


@pytest.mark.parametrize("picture, expected", [(None, False), (b"", False), (PICTURE, True)])
def test_facade_has_image_blob(
    pg_backend: "DatabaseBackendProtocol", picture: Optional[bytes], expected: bool
) -> None:
    """The UserModel facade, which the application code uses, answers
    has_image_blob from the database, and get_image() returns the picture."""
    import src.skrafldb_pg as skrafldb_pg

    user = _make_user(pg_backend, "picture-user-050", "Qqpicturefifty")
    pg_backend.users.update(user, image="image/jpeg", image_blob=picture)
    um = skrafldb_pg.UserModel._from_entity(user)
    assert um.has_image_blob is expected
    assert um.get_image() == ("image/jpeg", picture)
