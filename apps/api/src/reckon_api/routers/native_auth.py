from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator
from sqlalchemy.orm import Session

from reckon_api.dependencies import bearer_scheme, get_authenticated_principal, get_database_session
from reckon_api.native_mail import EmailDeliveryUnavailable, VerificationMailer
from reckon_core.native_auth import (
    InvalidNativeCredentials, InvalidPasswordReset, InvalidVerification, NativeAuthBusy, NativeAuthRepository,
    is_native_token, normalize_email, valid_password,
)
from reckon_core.tenancy import AuthenticatedPrincipal

router = APIRouter(prefix="/api/v1/auth", tags=["native authentication"])


class EmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    email: Annotated[str, StringConstraints(min_length=3, max_length=320)]

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    token: SecretStr
    password: SecretStr

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        if not valid_password(value.get_secret_value()):
            raise ValueError("Invalid password.")
        return value

    @field_validator("token")
    @classmethod
    def validate_token(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) != 43:
            raise ValueError("Invalid verification token.")
        return value


class SignInRequest(EmailRequest):
    password: SecretStr

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        password = value.get_secret_value()
        try:
            valid_encoding = len(password.encode("utf-8")) <= 512
        except UnicodeEncodeError:
            valid_encoding = False
        if len(password) > 128 or not valid_encoding:
            raise ValueError("Invalid password.")
        return value


class NativeMethodsResponse(BaseModel):
    enabled: bool
    signup_available: bool
    recovery_available: bool


class NativeSessionResponse(BaseModel):
    access_token: str = Field(repr=False)
    user_id: str
    expires_in: int


def _require_enabled(request: Request) -> None:
    if not request.app.state.settings.native_auth_enabled:
        raise HTTPException(status_code=503, detail="Native authentication is not enabled.")
    if request.url.scheme != "https":
        local = (
            request.app.state.settings.environment == "local"
            and request.client is not None
            and request.client.host in {"127.0.0.1", "::1"}
        )
        if request.app.state.settings.environment != "test" and not local:
            raise HTTPException(status_code=400, detail="HTTPS is required for authentication.")


def _client_ip(request: Request) -> str:
    if request.client is None:
        raise HTTPException(status_code=503, detail="Authentication is temporarily unavailable.")
    return request.client.host


@router.get("/methods", response_model=NativeMethodsResponse)
def native_methods(request: Request) -> NativeMethodsResponse:
    enabled = request.app.state.settings.native_auth_enabled
    return NativeMethodsResponse(
        enabled=enabled,
        signup_available=enabled and request.app.state.verification_mailer is not None,
        recovery_available=enabled and request.app.state.verification_mailer is not None,
    )


@router.post("/signup", status_code=202)
def native_signup(
    request: Request,
    payload: EmailRequest,
    session: Session = Depends(get_database_session),
) -> dict[str, str]:
    _require_enabled(request)
    mailer: VerificationMailer | None = request.app.state.verification_mailer
    if mailer is None:
        raise HTTPException(status_code=503, detail="Account verification email is not configured.")
    repository = NativeAuthRepository(session)
    ip_allowed = repository.rate_limit("signup-ip", _client_ip(request), 20, timedelta(hours=1))
    email_allowed = repository.rate_limit("signup-email", payload.email, 5, timedelta(hours=1))
    session.commit()
    if not ip_allowed or not email_allowed:
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")
    token = repository.begin_signup(payload.email)
    session.commit()
    try:
        if token is not None:
            mailer.send_verification(payload.email, token)
        else:
            mailer.send_existing_account_notice(payload.email)
    except EmailDeliveryUnavailable as error:
        raise HTTPException(
            status_code=503, detail="Verification email could not be sent. Try again later."
        ) from error
    return {"detail": "If eligible, you will receive a verification email."}


@router.post("/password-reset", status_code=202)
def native_password_reset(
    request: Request,
    payload: EmailRequest,
    session: Session = Depends(get_database_session),
) -> dict[str, str]:
    _require_enabled(request)
    mailer: VerificationMailer | None = request.app.state.verification_mailer
    if mailer is None:
        raise HTTPException(status_code=503, detail="Account recovery email is not configured.")
    repository = NativeAuthRepository(session)
    ip_allowed = repository.rate_limit("reset-ip", _client_ip(request), 20, timedelta(hours=1))
    email_allowed = repository.rate_limit("reset-email", payload.email, 5, timedelta(hours=1))
    session.commit()
    if not ip_allowed or not email_allowed:
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")
    token = repository.begin_password_reset(payload.email)
    session.commit()
    try:
        if token is not None:
            mailer.send_password_reset(payload.email, token)
        else:
            mailer.send_password_reset_notice(payload.email)
    except EmailDeliveryUnavailable as error:
        raise HTTPException(status_code=503, detail="Recovery email could not be sent. Try again later.") from error
    return {"detail": "If eligible, you will receive a recovery email."}


@router.post("/password-reset/confirm", status_code=204)
def native_password_reset_confirm(
    request: Request,
    payload: VerifyRequest,
    session: Session = Depends(get_database_session),
) -> Response:
    _require_enabled(request)
    repository = NativeAuthRepository(session)
    allowed = repository.rate_limit("reset-confirm-ip", _client_ip(request), 30, timedelta(minutes=10))
    session.commit()
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")
    try:
        repository.complete_password_reset(
            payload.token.get_secret_value(), payload.password.get_secret_value(), request.state.request_id
        )
        session.commit()
    except InvalidPasswordReset as error:
        session.rollback()
        raise HTTPException(status_code=400, detail="Recovery link is invalid or expired.") from error
    except NativeAuthBusy as error:
        session.rollback()
        raise HTTPException(status_code=503, detail="Authentication is temporarily busy.") from error
    return Response(status_code=204)


@router.post("/verify", status_code=204)
def native_verify(
    request: Request,
    payload: VerifyRequest,
    session: Session = Depends(get_database_session),
) -> Response:
    _require_enabled(request)
    repository = NativeAuthRepository(session)
    allowed = repository.rate_limit("verify-ip", _client_ip(request), 30, timedelta(minutes=10))
    session.commit()
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")
    try:
        repository.complete_signup(
            payload.token.get_secret_value(), payload.password.get_secret_value(), request.state.request_id
        )
        session.commit()
    except InvalidVerification as error:
        session.rollback()
        raise HTTPException(status_code=400, detail="Verification link is invalid or expired.") from error
    except NativeAuthBusy as error:
        session.rollback()
        raise HTTPException(status_code=503, detail="Authentication is temporarily busy.") from error
    return Response(status_code=204)


@router.post("/signin", response_model=NativeSessionResponse)
def native_signin(
    request: Request,
    payload: SignInRequest,
    session: Session = Depends(get_database_session),
) -> NativeSessionResponse:
    _require_enabled(request)
    repository = NativeAuthRepository(session)
    ip_allowed = repository.rate_limit("login-ip", _client_ip(request), 30, timedelta(minutes=10))
    email_allowed = repository.rate_limit("login-email", payload.email, 10, timedelta(minutes=10))
    session.commit()
    if not ip_allowed or not email_allowed:
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")
    try:
        token, user_id = repository.sign_in(
            payload.email, payload.password.get_secret_value(), request.state.request_id
        )
        session.commit()
    except InvalidNativeCredentials as error:
        raise HTTPException(status_code=401, detail="Email or password is incorrect.") from error
    except NativeAuthBusy as error:
        raise HTTPException(status_code=503, detail="Authentication is temporarily busy.") from error
    return NativeSessionResponse(
        access_token=token, user_id=str(user_id), expires_in=3600
    )


@router.post("/signout", status_code=204)
def native_signout(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> Response:
    _require_enabled(request)
    if credentials is None or not is_native_token(credentials.credentials):
        raise HTTPException(status_code=400, detail="A native session is required.")
    try:
        NativeAuthRepository(session).revoke(
            credentials.credentials, principal.user_id, request.state.request_id
        )
        session.commit()
    except InvalidNativeCredentials as error:
        raise HTTPException(status_code=401, detail="The session is invalid.") from error
    return Response(status_code=204)
