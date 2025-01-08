"""

    Tests for Netskrafl / Explo Word Game
    Copyright © 2025 Miðeind ehf.

    This module tests several APIs by submitting HTTP requests
    to the Netskrafl / Explo server.

"""

import base64

from utils import CustomClient, login_user
from utils import client, u1, u2, u3_gb  # type: ignore


# Create a minimal JPEG image directly from bytes
# (Credit: StackOverflow answer by 'matja',
# https://stackoverflow.com/a/2349470/6335727)

MINIMAL_JPEG_HEX = (
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
MINIMAL_JPEG_BYTES = bytes.fromhex(MINIMAL_JPEG_HEX)


def test_locale_assets(client: CustomClient, u1: str, u3_gb: str) -> None:

    # Test default en_US user
    resp = login_user(client, 1)
    resp = client.post("/locale_asset", data=dict(asset="test_english.html"))
    assert resp.status_code == 200
    assert resp.content_type == "text/html; charset=utf-8"
    assert "American English" in resp.data.decode("utf-8")
    resp = client.post("/logout")

    # Test en_GB user
    resp = login_user(client, 3)
    resp = client.post("/locale_asset", data=dict(asset="test_english.html"))
    assert resp.status_code == 200
    assert resp.content_type == "text/html; charset=utf-8"
    assert "generic English" in resp.data.decode("utf-8")
    resp = client.post("/logout")
    assert resp.status_code == 200


def test_image(client: CustomClient, u1: str) -> None:
    """Test image setting and getting"""
    resp = login_user(client, 1)

    # Set the image by POSTing the JPEG or PNG content (BLOB) directly
    image_blob = MINIMAL_JPEG_BYTES
    # Encode the image_blob as base64
    image_b64 = base64.b64encode(image_blob)
    resp = client.post(
        "/image", data=image_b64, content_type="image/jpeg; charset=utf-8"
    )
    assert resp.status_code == 200

    # Retrieve the image of the currently logged-in user
    resp = client.get("/image")
    assert resp.status_code == 200
    assert resp.mimetype == "image/jpeg"
    assert resp.content_length == len(image_blob)
    # Retrieve the original BLOB
    assert resp.get_data(as_text=False) == image_blob

    # Set an image URL: note the text/plain MIME type
    image_url = "https://lh3.googleusercontent.com/a/AATXAJxmLaM_8c61i_EeyptXynOG1SL7b-BSt7uBz8Hg=s96-c"
    resp = client.post(
        "/image", data=image_url, content_type="text/plain; charset=utf-8"
    )
    assert resp.status_code == 200

    # Get the image (follow_redirects specified for emphasis, it
    # is False by default)
    resp = client.get("/image", follow_redirects=False)
    assert resp.status_code == 302
    # Retrieve the URL from the Location header
    assert resp.location == image_url

    resp = client.post("/logout")
    assert resp.status_code == 200
