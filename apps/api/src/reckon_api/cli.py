import argparse
import sys
from pathlib import Path
from typing import Sequence

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from reckon_api.config import Settings
from reckon_core.oidc import (
    IdentityProviderUnavailable,
    InvalidBearerToken,
    OidcTokenVerifier,
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    settings = Settings()

    if settings.database_url is None:
        parser.error("RECKON_DATABASE_URL must be configured.")
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
