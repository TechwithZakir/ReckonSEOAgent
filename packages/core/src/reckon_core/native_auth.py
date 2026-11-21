import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from threading import BoundedSemaphore
from typing import Literal
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from email_validator import EmailNotValidError, validate_email
from sqlalchemy import case, delete, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reckon_core.persistence import (
    NativeAccount, NativeAuthEvent, NativeAuthRateLimit, NativePasswordReset, NativeSession,
    NativeVerification, PlatformAdministrator, User,
)
from reckon_core.tenancy import AuthenticatedPrincipal

_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_SESSION_PREFIX = "rk1_"
_HASHER = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1)
_HASH_SLOTS = BoundedSemaphore(4)
_DUMMY_HASH = _HASHER.hash(secrets.token_urlsafe(32))


class NativeAuthBusy(RuntimeError):
    pass


class InvalidVerification(ValueError):
    pass


class InvalidNativeCredentials(ValueError):
    pass


class InvalidPasswordReset(ValueError):
    pass


class BootstrapConflict(ValueError):
    pass


def normalize_email(email: str) -> str:
    try:
        normalized = validate_email(
            email, check_deliverability=False, allow_smtputf8=False
        ).ascii_email
    except EmailNotValidError:
        raise ValueError("Invalid email address.") from None
    if normalized is None or len(normalized) > 320:
        raise ValueError("Invalid email address.")
    return normalized.lower()


def valid_password(password: str) -> bool:
    try:
        return 12 <= len(password) <= 128 and len(password.encode("utf-8")) <= 512
    except UnicodeEncodeError:
        return False


def hash_password(password: str) -> str:
    if not valid_password(password):
        raise ValueError("Password must contain 12 to 128 characters.")
    if not _HASH_SLOTS.acquire(blocking=False):
        raise NativeAuthBusy("Password processing capacity is unavailable.")
    try:
        return _HASHER.hash(password)
    finally:
        _HASH_SLOTS.release()


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not _HASH_SLOTS.acquire(blocking=False):
        raise NativeAuthBusy("Password processing capacity is unavailable.")
    try:
        try:
            verified = _HASHER.verify(stored_hash or _DUMMY_HASH, password)
        except VerifyMismatchError:
            return False
        except (InvalidHashError, VerificationError):
            raise RuntimeError("Stored password hash is invalid.") from None
        return bool(verified and stored_hash is not None)
    finally:
        _HASH_SLOTS.release()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _valid_token(token: str) -> bool:
    return bool(_TOKEN_PATTERN.fullmatch(token))


class NativeAuthRepository:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._dialect = session.get_bind().dialect.name

    def bootstrap_platform_administrator(self, email: str, password: str, request_id: UUID) -> UUID:
        normalized = normalize_email(email)
        if self._session.get(PlatformAdministrator, 1) is not None:
            raise BootstrapConflict("The initial platform administrator already exists.")
        if self._session.scalar(select(NativeAccount.user_id).where(NativeAccount.email == normalized)):
            raise BootstrapConflict("The email already belongs to an existing account.")
        password_hash = hash_password(password)
        user = User()
        self._session.add(user)
        self._session.flush()
        self._session.add(NativeAccount(user_id=user.id, email=normalized, password_hash=password_hash))
        self._session.add(PlatformAdministrator(slot=1, user_id=user.id))
        self._session.add(NativeAuthEvent(
            user_id=user.id, request_id=request_id, action="platform.bootstrap"
        ))
        try:
            self._session.flush()
        except IntegrityError:
            raise BootstrapConflict("The administrator bootstrap conflicted with an existing account.") from None
        return user.id

    def rate_limit(
        self, action: Literal[
            "signup-ip", "signup-email", "login-ip", "login-email", "verify-ip",
            "reset-ip", "reset-email", "reset-confirm-ip",
        ],
        identity: str, limit: int, duration: timedelta,
    ) -> bool:
        now = datetime.now(timezone.utc)
        bucket = _digest(f"{action}:{identity}")
        if self._dialect == "postgresql":
            insert = postgres_insert
        elif self._dialect == "sqlite":
            insert = sqlite_insert
        else:
            raise RuntimeError("Native authentication requires PostgreSQL or SQLite.")
        statement = insert(NativeAuthRateLimit).values(
            bucket_hash=bucket, attempts=1, expires_at=now + duration
        )
        expired = NativeAuthRateLimit.expires_at <= now
        statement = statement.on_conflict_do_update(
            index_elements=[NativeAuthRateLimit.bucket_hash],
            set_={
                "attempts": case((expired, 1), else_=NativeAuthRateLimit.attempts + 1),
                "expires_at": case((expired, now + duration), else_=NativeAuthRateLimit.expires_at),
            },
        ).returning(NativeAuthRateLimit.attempts)
        attempts = self._session.scalar(statement)
        if attempts is None:
            raise RuntimeError("Authentication rate limit could not be calculated.")
        expired_buckets = (
            select(NativeAuthRateLimit.bucket_hash)
            .where(NativeAuthRateLimit.expires_at < now - timedelta(days=1))
            .limit(32)
        )
        self._session.execute(
            delete(NativeAuthRateLimit).where(NativeAuthRateLimit.bucket_hash.in_(expired_buckets))
        )
        return attempts <= limit

    def begin_signup(self, email: str) -> str | None:
        if self._session.scalar(select(NativeAccount.user_id).where(NativeAccount.email == email)):
            return None
        now = datetime.now(timezone.utc)
        expired_tokens = (
            select(NativeVerification.token_hash)
            .where(NativeVerification.expires_at < now - timedelta(days=1))
            .limit(32)
        )
        self._session.execute(
            delete(NativeVerification).where(NativeVerification.token_hash.in_(expired_tokens))
        )
        token = secrets.token_urlsafe(32)
        self._session.add(NativeVerification(
            token_hash=_digest(token), email=email, expires_at=now + timedelta(minutes=30)
        ))
        self._session.flush()
        return token

    def complete_signup(self, token: str, password: str, request_id: UUID) -> None:
        if not _valid_token(token):
            raise InvalidVerification
        now = datetime.now(timezone.utc)
        verification = self._session.scalar(
            select(NativeVerification)
            .where(
                NativeVerification.token_hash == _digest(token),
                NativeVerification.consumed_at.is_(None),
                NativeVerification.expires_at > now,
            )
            .with_for_update()
        )
        if verification is None:
            raise InvalidVerification
        password_hash = hash_password(password)
        user = User()
        self._session.add(user)
        self._session.flush()
        self._session.add(NativeAccount(
            user_id=user.id, email=verification.email, password_hash=password_hash, email_verified=True
        ))
        self._session.add(NativeAuthEvent(
            user_id=user.id, request_id=request_id, action="account.created"
        ))
        verification.consumed_at = now
        try:
            self._session.flush()
        except IntegrityError:
            raise InvalidVerification from None

    def sign_in(self, email: str, password: str, request_id: UUID) -> tuple[str, UUID]:
        account = self._session.scalar(
            select(NativeAccount).where(NativeAccount.email == email).with_for_update()
        )
        if not verify_password(password, account.password_hash if account else None) or account is None:
            raise InvalidNativeCredentials
        now = datetime.now(timezone.utc)
        expired_sessions = (
            select(NativeSession.token_hash)
            .where(NativeSession.expires_at < now - timedelta(days=1))
            .limit(32)
        )
        self._session.execute(
            delete(NativeSession).where(NativeSession.token_hash.in_(expired_sessions))
        )
        token = _SESSION_PREFIX + secrets.token_urlsafe(32)
        self._session.add(NativeSession(
            token_hash=_digest(token), user_id=account.user_id, expires_at=now + timedelta(hours=1)
        ))
        self._session.add(NativeAuthEvent(
            user_id=account.user_id, request_id=request_id, action="session.created"
        ))
        self._session.flush()
        return token, account.user_id

    def begin_password_reset(self, email: str) -> str | None:
        account = self._session.scalar(select(NativeAccount).where(NativeAccount.email == email))
        if account is None:
            return None
        now = datetime.now(timezone.utc)
        expired = select(NativePasswordReset.token_hash).where(
            NativePasswordReset.expires_at < now - timedelta(days=1)
        ).limit(32)
        self._session.execute(
            delete(NativePasswordReset).where(NativePasswordReset.token_hash.in_(expired))
        )
        token = secrets.token_urlsafe(32)
        self._session.add(NativePasswordReset(
            token_hash=_digest(token), user_id=account.user_id, expires_at=now + timedelta(minutes=30)
        ))
        self._session.flush()
        return token

    def complete_password_reset(self, token: str, password: str, request_id: UUID) -> None:
        if not _valid_token(token):
            raise InvalidPasswordReset
        token_hash = _digest(token)
        user_id = self._session.scalar(
            select(NativePasswordReset.user_id).where(NativePasswordReset.token_hash == token_hash)
        )
        if user_id is None:
            raise InvalidPasswordReset
        account = self._session.scalar(
            select(NativeAccount).where(NativeAccount.user_id == user_id).with_for_update()
        )
        now = datetime.now(timezone.utc)
        reset = self._session.scalar(
            select(NativePasswordReset).where(
                NativePasswordReset.token_hash == token_hash,
                NativePasswordReset.consumed_at.is_(None),
                NativePasswordReset.expires_at > now,
            ).with_for_update()
        )
        if account is None or reset is None:
            raise InvalidPasswordReset
        account.password_hash = hash_password(password)
        self._session.execute(
            update(NativePasswordReset).where(
                NativePasswordReset.user_id == user_id,
                NativePasswordReset.consumed_at.is_(None),
            ).values(consumed_at=now)
        )
        self._session.execute(
            update(NativeSession).where(
                NativeSession.user_id == user_id, NativeSession.revoked_at.is_(None),
            ).values(revoked_at=now)
        )
        self._session.add(NativeAuthEvent(
            user_id=user_id, request_id=request_id, action="password.reset"
        ))
        self._session.flush()

    def authenticate(self, token: str) -> AuthenticatedPrincipal | None:
        if not token.startswith(_SESSION_PREFIX) or not _valid_token(token[len(_SESSION_PREFIX):]):
            return None
        user_id = self._session.scalar(
            select(NativeSession.user_id)
            .join(NativeAccount, NativeAccount.user_id == NativeSession.user_id)
            .where(
                NativeSession.token_hash == _digest(token),
                NativeSession.expires_at > datetime.now(timezone.utc),
                NativeSession.revoked_at.is_(None),
            )
        )
        if user_id is None:
            return None
        return AuthenticatedPrincipal(user_id, "reckon-native", str(user_id))

    def revoke(self, token: str, user_id: UUID, request_id: UUID) -> None:
        entry = self._session.scalar(
            select(NativeSession)
            .where(NativeSession.token_hash == _digest(token), NativeSession.user_id == user_id)
            .with_for_update()
        )
        if entry is None:
            raise InvalidNativeCredentials
        if entry.revoked_at is None:
            entry.revoked_at = datetime.now(timezone.utc)
            self._session.add(NativeAuthEvent(
                user_id=user_id, request_id=request_id, action="session.revoked"
            ))
        self._session.flush()


def is_native_token(token: str) -> bool:
    return token.startswith(_SESSION_PREFIX)
