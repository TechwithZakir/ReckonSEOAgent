import hashlib
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from reckon_api.dependencies import bearer_scheme, get_authenticated_principal, get_database_session
from reckon_api.native_mail import EmailDeliveryUnavailable, VerificationMailer
from reckon_core.native_auth import (
    InvalidNativeCredentials, InvalidPasswordReset, InvalidVerification, InvalidMfa,
    NativeAuthBusy, NativeAuthRepository, generate_mfa_secret, verify_totp,
    is_native_token, normalize_email, valid_password,
)
from reckon_core.model_settings import CredentialCipher, CredentialEncryptionUnavailable
from reckon_core.tenancy import AuthenticatedPrincipal
from reckon_core.persistence import NativeAccount, NativeAuthEvent, NativeMfaChallenge

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


class MfaChallengeResponse(BaseModel):
    mfa_required: Literal[True] = True
    challenge: str = Field(repr=False)
    expires_in: int


class MfaStatusResponse(BaseModel):
    enabled: bool


class MfaEnrollResponse(BaseModel):
    secret: str = Field(repr=False)
    otpauth_uri: str = Field(repr=False)


class MfaCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: Annotated[
        str,
        StringConstraints(pattern=r"^[0-9]{6}$"),
    ]


class MfaChallengeRequest(MfaCodeRequest):
    challenge: Annotated[
        str,
        StringConstraints(pattern=r"^rk1_[A-Za-z0-9_-]{43}$"),
    ]


class AccountSessionSummary(BaseModel):
    session_id: str
    expires_at: datetime
    is_current: bool


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


@router.post("/signin", response_model=NativeSessionResponse | MfaChallengeResponse)
def native_signin(
    request: Request,
    payload: SignInRequest,
    session: Session = Depends(get_database_session),
) -> NativeSessionResponse | MfaChallengeResponse:
    _require_enabled(request)
    repository = NativeAuthRepository(session)
    ip_allowed = repository.rate_limit("login-ip", _client_ip(request), 30, timedelta(minutes=10))
    email_allowed = repository.rate_limit("login-email", payload.email, 10, timedelta(minutes=10))
    session.commit()
    if not ip_allowed or not email_allowed:
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")
    try:
        challenge = repository.begin_mfa_signin(
            payload.email, payload.password.get_secret_value(), request.state.request_id
        )
        session.commit()
        if challenge is not None:
            challenge_token, _ = challenge
            return MfaChallengeResponse(
                mfa_required=True,
                challenge=challenge_token,
                expires_in=300,
            )
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


@router.post("/signin/mfa", response_model=NativeSessionResponse)
def native_signin_mfa(
    request: Request,
    payload: MfaChallengeRequest,
    session: Session = Depends(get_database_session),
) -> NativeSessionResponse:
    _require_enabled(request)
    challenge_hash = hashlib.sha256(payload.challenge.encode()).hexdigest()
    challenge = session.scalar(
        select(NativeMfaChallenge).where(
            NativeMfaChallenge.challenge_hash == challenge_hash
        )
    )
    if challenge is None:
        raise HTTPException(status_code=400, detail="MFA challenge is invalid or expired.")
    account = session.get(NativeAccount, challenge.user_id)
    if account is None or not account.mfa_enabled or account.mfa_secret_cipher is None:
        raise HTTPException(status_code=400, detail="MFA challenge is invalid or expired.")
    try:
        secret = CredentialCipher(request.app.state.settings.credential_encryption_key).decrypt(
            account.mfa_secret_cipher,
            challenge.user_id,
            "native-mfa",
        ).get_secret_value()
    except CredentialEncryptionUnavailable as error:
        raise HTTPException(status_code=503, detail="MFA is temporarily unavailable.") from error
    try:
        token, user_id = NativeAuthRepository(session).confirm_mfa_signin(
            payload.challenge,
            payload.code,
            secret,
            request.state.request_id,
        )
        session.commit()
    except InvalidMfa as error:
        session.rollback()
        raise HTTPException(status_code=400, detail="MFA code or challenge is invalid.") from error
    return NativeSessionResponse(
        access_token=token,
        user_id=str(user_id),
        expires_in=3600,
    )


@router.get("/mfa", response_model=MfaStatusResponse)
def get_mfa_status(
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> MfaStatusResponse:
    account = session.get(NativeAccount, principal.user_id)
    return MfaStatusResponse(enabled=bool(account is not None and account.mfa_enabled))


@router.post("/mfa/enroll", response_model=MfaEnrollResponse)
def enroll_mfa(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> MfaEnrollResponse:
    _require_enabled(request)
    account = session.get(NativeAccount, principal.user_id)
    if account is None:
        raise HTTPException(status_code=401, detail="A native account is required.")
    secret = generate_mfa_secret()
    try:
        encrypted = CredentialCipher(request.app.state.settings.credential_encryption_key).encrypt(
            SecretStr(secret),
            principal.user_id,
            "native-mfa",
        )
    except CredentialEncryptionUnavailable as error:
        raise HTTPException(status_code=503, detail="MFA encryption is unavailable.") from error
    NativeAuthRepository(session).set_mfa_secret(
        principal.user_id,
        encrypted,
        False,
    )
    session.add(NativeAuthEvent(
        user_id=principal.user_id,
        request_id=request.state.request_id,
        action="mfa.enrollment_started",
    ))
    session.commit()
    uri = (
        "otpauth://totp/Reckon:"
        f"{account.email}?secret={secret}&issuer=Reckon&digits=6&period=30"
    )
    return MfaEnrollResponse(secret=secret, otpauth_uri=uri)


@router.post("/mfa/confirm", status_code=204)
def confirm_mfa(
    request: Request,
    payload: MfaCodeRequest,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> Response:
    _require_enabled(request)
    account = session.get(NativeAccount, principal.user_id)
    if account is None or account.mfa_secret_cipher is None:
        raise HTTPException(status_code=409, detail="Start MFA enrollment before confirmation.")
    try:
        secret = CredentialCipher(request.app.state.settings.credential_encryption_key).decrypt(
            account.mfa_secret_cipher,
            principal.user_id,
            "native-mfa",
        ).get_secret_value()
    except CredentialEncryptionUnavailable as error:
        raise HTTPException(status_code=503, detail="MFA is temporarily unavailable.") from error
    if not verify_totp(secret, payload.code):
        raise HTTPException(status_code=400, detail="MFA code is invalid.")
    NativeAuthRepository(session).set_mfa_secret(
        principal.user_id,
        account.mfa_secret_cipher,
        True,
    )
    session.add(NativeAuthEvent(
        user_id=principal.user_id,
        request_id=request.state.request_id,
        action="mfa.enabled",
    ))
    session.commit()
    return Response(status_code=204)


@router.post("/mfa/disable", status_code=204)
def disable_mfa(
    request: Request,
    payload: MfaCodeRequest,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> Response:
    _require_enabled(request)
    account = session.get(NativeAccount, principal.user_id)
    if account is None or not account.mfa_enabled or account.mfa_secret_cipher is None:
        raise HTTPException(status_code=409, detail="MFA is not enabled.")
    try:
        secret = CredentialCipher(request.app.state.settings.credential_encryption_key).decrypt(
            account.mfa_secret_cipher,
            principal.user_id,
            "native-mfa",
        ).get_secret_value()
    except CredentialEncryptionUnavailable as error:
        raise HTTPException(status_code=503, detail="MFA is temporarily unavailable.") from error
    if not verify_totp(secret, payload.code):
        raise HTTPException(status_code=400, detail="MFA code is invalid.")
    account.mfa_enabled = False
    account.mfa_secret_cipher = None
    session.add(NativeAuthEvent(
        user_id=principal.user_id,
        request_id=request.state.request_id,
        action="mfa.disabled",
    ))
    session.commit()
    return Response(status_code=204)


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


@router.get("/sessions", response_model=list[AccountSessionSummary])
def list_native_sessions(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> list[AccountSessionSummary]:
    _require_enabled(request)
    if credentials is None or not is_native_token(credentials.credentials):
        raise HTTPException(status_code=400, detail="A native session is required.")
    rows = NativeAuthRepository(session).list_sessions(
        principal.user_id,
        credentials.credentials,
    )
    return [
        AccountSessionSummary(
            session_id=session_id,
            expires_at=expires_at,
            is_current=is_current,
        )
        for session_id, expires_at, is_current in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_native_session(
    session_id: str,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> Response:
    _require_enabled(request)
    if credentials is None or not is_native_token(credentials.credentials):
        raise HTTPException(status_code=400, detail="A native session is required.")
    try:
        NativeAuthRepository(session).revoke_session(
            principal.user_id,
            session_id,
            request.state.request_id,
        )
        session.commit()
    except InvalidNativeCredentials as error:
        raise HTTPException(status_code=404, detail="The account session was not found.") from error
    return Response(status_code=204)
