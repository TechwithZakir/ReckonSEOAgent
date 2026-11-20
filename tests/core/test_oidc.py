from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from jwt.exceptions import PyJWKClientConnectionError

from reckon_core.oidc import (
    IdentityProviderUnavailable,
    InvalidBearerToken,
    OidcTokenVerifier,
)


ISSUER = "https://identity.example.test/"
AUDIENCE = "reckon-seo-api"


class SigningKey:
    def __init__(self, key: Any) -> None:
        self.key = key


class StaticSigningKeyResolver:
    def __init__(self, key: Any) -> None:
        self._key = key

    def get_signing_key_from_jwt(self, token: str) -> SigningKey:
        return SigningKey(self._key)


class UnavailableSigningKeyResolver:
    def get_signing_key_from_jwt(self, token: str) -> SigningKey:
        raise PyJWKClientConnectionError("JWKS unavailable")


@pytest.fixture
def oidc_verifier() -> tuple[OidcTokenVerifier, Any]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = OidcTokenVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_url="https://identity.example.test/.well-known/jwks.json",
        key_resolver=StaticSigningKeyResolver(private_key.public_key()),
    )
    return verifier, private_key


def issue_token(private_key: Any, **claim_overrides: Any) -> str:
    now = datetime.now(timezone.utc)
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": "provider-subject-1",
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(claim_overrides)
    return jwt.encode(claims, private_key, algorithm="RS256")


def test_oidc_verifier_accepts_correctly_signed_access_token(
    oidc_verifier: tuple[OidcTokenVerifier, Any],
) -> None:
    verifier, private_key = oidc_verifier

    assert verifier.verify(issue_token(private_key)) == (
        ISSUER,
        "provider-subject-1",
    )


@pytest.mark.parametrize(
    "claim_overrides",
    [
        {"iss": "https://attacker.example.test/"},
        {"aud": "another-api"},
        {"sub": ""},
        {"exp": datetime.now(timezone.utc) - timedelta(minutes=5)},
        {"iat": None},
    ],
)
def test_oidc_verifier_rejects_invalid_claims(
    oidc_verifier: tuple[OidcTokenVerifier, Any],
    claim_overrides: dict[str, Any],
) -> None:
    verifier, private_key = oidc_verifier

    with pytest.raises(InvalidBearerToken):
        verifier.verify(issue_token(private_key, **claim_overrides))


def test_oidc_verifier_rejects_untrusted_algorithm(
    oidc_verifier: tuple[OidcTokenVerifier, Any],
) -> None:
    verifier, _ = oidc_verifier
    token = jwt.encode(
        {
            "iss": ISSUER,
            "sub": "provider-subject-1",
            "aud": AUDIENCE,
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        "attacker-controlled-key-that-is-at-least-32-bytes",
        algorithm="HS256",
    )

    with pytest.raises(InvalidBearerToken):
        verifier.verify(token)


def test_oidc_verifier_requires_https_urls() -> None:
    with pytest.raises(ValueError, match="must use HTTPS"):
        OidcTokenVerifier(
            issuer=ISSUER,
            audience=AUDIENCE,
            jwks_url="http://identity.example.test/jwks",
            key_resolver=StaticSigningKeyResolver(object()),
        )


def test_oidc_verifier_distinguishes_jwks_outage_from_invalid_token() -> None:
    verifier = OidcTokenVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_url="https://identity.example.test/.well-known/jwks.json",
        key_resolver=UnavailableSigningKeyResolver(),
    )

    with pytest.raises(IdentityProviderUnavailable):
        verifier.verify("token")
