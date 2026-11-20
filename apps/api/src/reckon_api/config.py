from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Reckon SEO Autopilot API"
    environment: Literal["local", "test", "staging", "production"] = "local"
    database_url: SecretStr | None = None
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    crawl_daily_limit: int = Field(default=10, ge=1)

    model_config = SettingsConfigDict(
        env_prefix="RECKON_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def require_production_integrations(self) -> "Settings":
        oidc_values = (
            self.oidc_issuer,
            self.oidc_audience,
            self.oidc_jwks_url,
        )
        if any(oidc_values) and not all(oidc_values):
            raise ValueError("OIDC issuer, audience and JWKS URL must be configured together.")
        if self.environment == "production" and (
            self.database_url is None
            or self.oidc_issuer is None
            or self.oidc_audience is None
            or self.oidc_jwks_url is None
        ):
            raise ValueError(
                "Production requires database and OIDC configuration."
            )
        return self
