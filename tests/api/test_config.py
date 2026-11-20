import pytest
from pydantic import ValidationError

from reckon_api.config import Settings


def test_production_settings_require_database_and_oidc() -> None:
    with pytest.raises(ValidationError, match="Production requires"):
        Settings(_env_file=None, environment="production")


def test_oidc_configuration_must_be_complete() -> None:
    with pytest.raises(ValidationError, match="must be configured together"):
        Settings(
            _env_file=None,
            oidc_issuer="https://identity.example.test/",
            environment="test",
        )


def test_production_settings_accept_complete_integration_configuration() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        database_url="postgresql+psycopg://app:secret@localhost/reckon",
        oidc_issuer="https://identity.example.test/",
        oidc_audience="reckon-api",
        oidc_jwks_url="https://identity.example.test/.well-known/jwks.json",
    )

    assert settings.environment == "production"
    assert settings.database_url is not None
