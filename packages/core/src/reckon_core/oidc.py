from typing import Any, Protocol
from urllib.parse import urlparse

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWTError


class InvalidBearerToken(ValueError):
    def __init__(self) -> None:
        super().__init__("Bearer token is invalid.")


class IdentityProviderUnavailable(ConnectionError):
    def __init__(self) -> None:
        super().__init__("Identity provider is unavailable.")


class SigningKeyResolver(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> Any:
        ...


class OidcTokenVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str,
        key_resolver: SigningKeyResolver | None = None,
    ) -> None:
        issuer_url = urlparse(issuer)
        jwks_endpoint = urlparse(jwks_url)
        if not issuer.strip() or not audience.strip():
            raise ValueError("OIDC issuer and audience must be configured.")
        if (
            issuer_url.scheme != "https"
            or not issuer_url.netloc
            or jwks_endpoint.scheme != "https"
            or not jwks_endpoint.netloc
        ):
            raise ValueError("OIDC issuer and JWKS URL must use HTTPS.")

        self._issuer = issuer
        self._audience = audience
        self._key_resolver = key_resolver or PyJWKClient(
            jwks_url,
            cache_jwk_set=True,
            cache_keys=True,
            timeout=5,
        )

    def verify(self, token: str) -> tuple[str, str]:
        try:
            signing_key = self._key_resolver.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                leeway=30,
                options={
                    "require": ["exp", "iat", "iss", "aud", "sub"],
                },
            )
            issuer = claims["iss"]
            subject = claims["sub"]
            if not isinstance(issuer, str) or not issuer or len(issuer) > 512:
                raise InvalidBearerToken
            if not isinstance(subject, str) or not subject or len(subject) > 512:
                raise InvalidBearerToken
            return issuer, subject
        except PyJWKClientConnectionError as error:
            raise IdentityProviderUnavailable from error
        except (PyJWTError, KeyError, TypeError, ValueError) as error:
            raise InvalidBearerToken from error
