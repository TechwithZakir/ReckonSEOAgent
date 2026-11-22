from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from reckon_core.oidc import (
    IdentityProviderUnavailable,
    InvalidBearerToken,
    OidcTokenVerifier,
)
from reckon_core.native_auth import NativeAuthRepository, is_native_token
from reckon_core.repositories import SqlAlchemyIdentityRepository
from reckon_core.plugin_tokens import PluginTokenRepository, is_plugin_token
from reckon_core.tenancy import AuthenticatedPrincipal

bearer_scheme = HTTPBearer(auto_error=False)


def get_database_session(request: Request) -> Iterator[Session]:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not configured.",
        )

    with session_factory() as session:
        yield session


def get_authenticated_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_database_session),
) -> AuthenticatedPrincipal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid bearer authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if is_plugin_token(credentials.credentials):
        principal = PluginTokenRepository(session).authenticate(
            credentials.credentials, request.url.path
        )
        if principal is not None:
            session.commit()  # records last_used_at
            return principal
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid bearer authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if is_native_token(credentials.credentials):
        if request.app.state.settings.native_auth_enabled:
            principal = NativeAuthRepository(session).authenticate(credentials.credentials)
            if principal is not None:
                return principal
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid bearer authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    verifier: OidcTokenVerifier | None = getattr(
        request.app.state,
        "token_verifier",
        None,
    )
    if verifier is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Identity provider is not configured.",
        )

    try:
        issuer, subject = verifier.verify(credentials.credentials)
    except IdentityProviderUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Identity provider is unavailable.",
        ) from error
    except InvalidBearerToken as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid bearer authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error

    user_id = SqlAlchemyIdentityRepository(session).user_id_for_identity(
        issuer,
        subject,
    )
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid bearer authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return AuthenticatedPrincipal(user_id=user_id, issuer=issuer, subject=subject)
