import argparse
import getpass
import sys
import warnings
from pathlib import Path
from typing import Sequence
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from reckon_api.config import Settings
from reckon_core.oidc import (
    IdentityProviderUnavailable,
    InvalidBearerToken,
    OidcTokenVerifier,
)
from reckon_core.native_auth import (
    BootstrapConflict, NativeAuthBusy, NativeAuthRepository, normalize_email, valid_password,
)
from reckon_core.repositories import SqlAlchemyIdentityProvisioningRepository

MAX_ACCESS_TOKEN_LENGTH = 64 * 1024


def read_access_token(token_file: Path) -> str:
    if not token_file.is_file():
        raise FileNotFoundError("The token file does not exist.")
    if token_file.stat().st_size > MAX_ACCESS_TOKEN_LENGTH:
        raise ValueError("The token file exceeds the maximum supported size.")
    token = token_file.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("The token file is empty.")
    if len(token) > MAX_ACCESS_TOKEN_LENGTH:
        raise ValueError("The token file exceeds the maximum supported size.")
    return token


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reckon-api")
    commands = parser.add_subparsers(dest="command", required=True)
    provision = commands.add_parser(
        "provision-identity",
        help="Create an internal user for a verified OIDC access token.",
    )
    provision.add_argument(
        "--token-file",
        required=True,
        type=Path,
        help="Path to a local file containing a short-lived API access token.",
    )
    bootstrap = commands.add_parser(
        "bootstrap-admin",
        help="Create the initial local platform administrator using a private password prompt.",
    )
    bootstrap.add_argument("--email", required=True, help="Administrator email address.")
    return parser


def bootstrap_admin(email: str, settings: Settings) -> int:
    if settings.environment != "local":
        print("Administrator bootstrap is available only in the local environment.", file=sys.stderr)
        return 1
    if not sys.stdin.isatty():
        print("Administrator bootstrap requires an interactive terminal.", file=sys.stderr)
        return 1
    try:
        normalized = normalize_email(email)
    except ValueError:
        print("The administrator email address is invalid.", file=sys.stderr)
        return 1
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Administrator password: ")
            confirmation = getpass.getpass("Confirm password: ")
    except (EOFError, KeyboardInterrupt, OSError, getpass.GetPassWarning):
        print("\nAdministrator bootstrap was cancelled or secure input is unavailable.", file=sys.stderr)
        return 1
    if password != confirmation or not valid_password(password):
        print("Passwords must match and contain 12 to 128 characters.", file=sys.stderr)
        return 1
    if settings.database_url is None:
        print("RECKON_DATABASE_URL must be configured.", file=sys.stderr)
        return 1
    engine = create_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    try:
        with session_factory.begin() as session:
            user_id = NativeAuthRepository(session).bootstrap_platform_administrator(
                normalized, password, uuid4()
            )
    except (BootstrapConflict, NativeAuthBusy) as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(f"Created the initial platform administrator {user_id}.")
    if not settings.native_auth_enabled:
        print("Native authentication is disabled; enable it before signing in.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    settings = Settings()

    if settings.database_url is None:
        parser.error("RECKON_DATABASE_URL must be configured.")
    if arguments.command == "bootstrap-admin":
        return bootstrap_admin(arguments.email, settings)
    if (
        settings.oidc_issuer is None
        or settings.oidc_audience is None
        or settings.oidc_jwks_url is None
    ):
        parser.error(
            "RECKON_OIDC_ISSUER, RECKON_OIDC_AUDIENCE and "
            "RECKON_OIDC_JWKS_URL must be configured."
        )

    try:
        token = read_access_token(arguments.token_file)
    except (FileNotFoundError, ValueError) as error:
        parser.error(str(error))

    verifier = OidcTokenVerifier(
        issuer=settings.oidc_issuer,
        audience=settings.oidc_audience,
        jwks_url=settings.oidc_jwks_url,
    )
    try:
        issuer, subject = verifier.verify(token)
    except InvalidBearerToken:
        print("The access token is invalid or expired.", file=sys.stderr)
        return 1
    except IdentityProviderUnavailable:
        print("The identity provider is unavailable.", file=sys.stderr)
        return 1

    engine = create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
    )
    session_factory = sessionmaker(engine, expire_on_commit=False)
    try:
        with session_factory.begin() as session:
            user_id, created = SqlAlchemyIdentityProvisioningRepository(
                session
            ).provision(issuer, subject)
    finally:
        engine.dispose()

    if created:
        print(f"Provisioned internal user {user_id}.")
    else:
        print(f"Identity is already provisioned for internal user {user_id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
