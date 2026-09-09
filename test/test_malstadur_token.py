"""

    Tests for Málstaður JWT verification in skrafluser.py
    Copyright © 2026 Miðeind ehf.

    Verifies the classification of Málstaður login tokens into
    valid / recently expired ("expired", client should refresh) /
    long-expired or malformed ("invalid", client must log in again).

"""

from datetime import UTC, datetime, timedelta
from typing import Any, Dict, Iterable, Optional

import jwt
import pytest

import skrafluser
from skrafluser import (
    JWT_ALGORITHM,
    MALSTADUR_KID,
    MALSTADUR_TOKEN_EXPIRY_GRACE,
    verify_malstadur_token,
)
from config import TOKEN_SECRET


@pytest.fixture(autouse=True)
def accept_malstadur_kid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Accept the Málstaður KID regardless of the PROJECT_ID
    that the test suite runs under"""
    monkeypatch.setattr(
        skrafluser, "ACCEPTED_KIDS", frozenset((MALSTADUR_KID,))
    )


def make_token(
    *,
    expired_for: Optional[timedelta] = None,
    secret: str = TOKEN_SECRET,
    kid: str = MALSTADUR_KID,
    overrides: Optional[Dict[str, Any]] = None,
    drop: Iterable[str] = (),
) -> str:
    """Create a Málstaður-style login JWT, optionally one that
    expired expired_for ago, with claims overridden or dropped"""
    now = datetime.now(UTC)
    exp = now - expired_for if expired_for else now + timedelta(days=1)
    payload: Dict[str, Any] = {
        "sub": "1234567890",
        "email": "user@example.com",
        "plan": "friend",
        "iss": "malstadur",
        "aud": "netskrafl",
        "exp": exp,
    }
    if overrides:
        payload.update(overrides)
    for key in drop:
        del payload[key]
    return jwt.encode(
        payload, secret, algorithm=JWT_ALGORITHM, headers={"kid": kid}
    )


def test_valid_token() -> None:
    expired, claims = verify_malstadur_token(make_token())
    assert not expired
    assert claims is not None
    assert claims.get("email") == "user@example.com"
    assert claims.get("plan") == "friend"


def test_recently_expired_token_reports_expired() -> None:
    token = make_token(expired_for=timedelta(minutes=5))
    expired, claims = verify_malstadur_token(token)
    assert expired
    assert claims is None


def test_long_expired_token_reports_invalid() -> None:
    token = make_token(
        expired_for=MALSTADUR_TOKEN_EXPIRY_GRACE + timedelta(hours=1)
    )
    expired, claims = verify_malstadur_token(token)
    assert not expired
    assert claims is None


def test_wrong_signature_reports_invalid() -> None:
    token = make_token(secret="wrong-secret")
    expired, claims = verify_malstadur_token(token)
    assert not expired
    assert claims is None


def test_expired_token_with_wrong_signature_reports_invalid() -> None:
    # The grace-window re-decode must still verify the signature
    token = make_token(expired_for=timedelta(minutes=5), secret="wrong-secret")
    expired, claims = verify_malstadur_token(token)
    assert not expired
    assert claims is None


def test_unknown_kid_reports_invalid() -> None:
    token = make_token(kid="bogus-kid")
    expired, claims = verify_malstadur_token(token)
    assert not expired
    assert claims is None


@pytest.mark.parametrize(
    "claim,value",
    [("email", None), ("email", 42), ("plan", {"tier": "friend"}), ("sub", 123)],
)
def test_wrongly_typed_claim_reports_invalid(claim: str, value: Any) -> None:
    # A correctly signed token whose application-level claims have the
    # wrong type is rejected outright, not passed on to the login logic
    token = make_token(overrides={claim: value})
    expired, claims = verify_malstadur_token(token)
    assert not expired
    assert claims is None


def test_missing_optional_claims_still_valid() -> None:
    # Type checks apply only to claims that are present; a token without
    # the optional application-level claims still verifies
    token = make_token(drop=("email", "plan"))
    expired, claims = verify_malstadur_token(token)
    assert not expired
    assert claims is not None
    assert claims.get("sub") == "1234567890"

