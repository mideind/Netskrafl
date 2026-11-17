"""
API tests for the users' pictures on the PostgreSQL backend.

A user's picture is stored with the user but read from the database only
when it is asked for (see the image_blob column in
src/db/postgresql/models.py); everything else gets by on knowing whether a
picture exists. These tests go through the API as a client does: a picture
that is uploaded comes back unchanged, a thumbnail can be had, and other
users are shown the right address for it in lists of users.
"""

from __future__ import annotations

from typing import Any, Dict, List

import base64
import uuid

import pytest
from flask.testing import FlaskClient

from tests.api_e2e.conftest import AuthHelper


# The smallest JPEG image (one grey pixel)
# (Credit: StackOverflow answer by 'matja',
# https://stackoverflow.com/a/2349470/6335727)
MINIMAL_JPEG_BYTES = bytes.fromhex(
    "ffd8ffe000104a4649460001010100"
    "4800480000ffdb0043000302020202"
    "020302020203030303040604040404"
    "04080606050609080a0a090809090a"
    "0c0f0c0a0b0e0b09090d110d0e0f10"
    "1011100a0c12131210130f101010ff"
    "c9000b080001000101011100ffcc00"
    "0600101005ffda0008010100003f00"
    "d2cf20ffd9"
)

PICTURE_URL = "https://example.com/pictures/qqurl.jpg"


def _search(client: FlaskClient, prefix: str) -> List[Dict[str, Any]]:
    """Search for users by the start of their nickname"""
    response = client.post("/userlist", json={"query": "search", "spec": prefix})
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    return data.get("userlist") or []


@pytest.mark.api_e2e
class TestUserPicture:
    """Uploading, fetching and listing users' pictures"""

    def test_uploaded_picture_comes_back(
        self, client: FlaskClient, auth: AuthHelper
    ) -> None:
        """A picture that is uploaded is returned byte for byte, both to
        the user and to another user asking for it by user id."""
        login = auth.login_user(
            sub="picture-own-001", name="Qqownpicture", email="qqown@example.com"
        )
        user_id = login["user_id"]
        # A new user has the picture address that came with the login,
        # and asking for the picture redirects there
        assert client.get("/image").status_code == 302

        response = client.post(
            "/image",
            data=base64.b64encode(MINIMAL_JPEG_BYTES),
            content_type="image/jpeg; charset=utf-8",
        )
        assert response.status_code == 200

        response = client.get("/image")
        assert response.status_code == 200
        assert response.mimetype == "image/jpeg"
        assert response.get_data(as_text=False) == MINIMAL_JPEG_BYTES
        auth.logout()

        # Another user fetches the picture and its thumbnail
        auth.login_user(
            sub="picture-other-001", name="Qqother", email="qqother@example.com"
        )
        response = client.get(f"/image?uid={user_id}")
        assert response.status_code == 200
        assert response.get_data(as_text=False) == MINIMAL_JPEG_BYTES
        response = client.get(f"/thumbnail?uid={user_id}")
        assert response.status_code == 200
        assert response.mimetype == "image/jpeg"
        # A JPEG image starts with these two bytes
        assert response.get_data(as_text=False)[:2] == b"\xff\xd8"
        auth.logout()

    def test_user_lists_point_at_the_picture(
        self, client: FlaskClient, auth: AuthHelper
    ) -> None:
        """In a list of users, a user with an uploaded picture is shown
        with the address of the thumbnail endpoint, and a user whose
        picture is elsewhere (set by the user, or as it came with the
        login) with that address."""
        # Search results are cached for a couple of minutes, in a cache that
        # outlives the test database: use names that no earlier run has used
        tag = uuid.uuid4().hex[:8]
        ids: Dict[str, str] = {}
        for key in ("uploaded", "url", "login"):
            name = f"Qq{tag}{key}"
            login = auth.login_user(
                sub=f"picture-list-{key}-{tag}",
                name=name,
                email=f"{name.lower()}@example.com",
            )
            ids[key] = login["user_id"]
            if key == "uploaded":
                response = client.post(
                    "/image",
                    data=base64.b64encode(MINIMAL_JPEG_BYTES),
                    content_type="image/jpeg",
                )
                assert response.status_code == 200
            elif key == "url":
                response = client.post(
                    "/image", data=PICTURE_URL, content_type="text/plain"
                )
                assert response.status_code == 200
            auth.logout()

        auth.login_user(
            sub="picture-list-viewer-001", name="Qqviewer", email="qqviewer@example.com"
        )
        found = {u["userid"]: u for u in _search(client, f"Qq{tag}")}
        for key in ("uploaded", "url", "login"):
            assert ids[key] in found, f"user '{key}' not found by the search"
        uploaded = found[ids["uploaded"]]["image"]
        assert uploaded.endswith(f"/thumbnail?uid={ids['uploaded']}"), uploaded
        assert found[ids["url"]]["image"] == PICTURE_URL
        from_login = found[ids["login"]]["image"]
        assert from_login.startswith("https://"), from_login
        assert "/thumbnail" not in from_login and from_login != PICTURE_URL
        auth.logout()

    def test_login_after_upload_reports_the_picture(
        self, client: FlaskClient, auth: AuthHelper
    ) -> None:
        """A user who has uploaded a picture, and logs in again, is given
        the address of the picture in the user's own statistics."""
        login = auth.login_user(
            sub="picture-relogin-001", name="Qqrelogin", email="qqrelogin@example.com"
        )
        user_id = login["user_id"]
        response = client.post(
            "/image",
            data=base64.b64encode(MINIMAL_JPEG_BYTES),
            content_type="image/jpeg",
        )
        assert response.status_code == 200
        auth.logout()

        auth.login_user(
            sub="picture-relogin-001", name="Qqrelogin", email="qqrelogin@example.com"
        )
        response = client.post("/userstats", json={})
        assert response.status_code == 200
        stats = response.get_json()
        assert stats is not None
        assert stats.get("image", "").endswith(f"/image?uid={user_id}"), stats.get("image")
        auth.logout()
