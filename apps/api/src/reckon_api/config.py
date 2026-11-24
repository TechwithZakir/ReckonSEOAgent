from typing import Literal
from urllib.parse import urlsplit

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
    # Free, unauthenticated website audit (rate-limited per client address).
    public_audit_enabled: bool = True
    public_audit_hourly_limit: int = Field(default=5, ge=1, le=1000)
    mcp_daily_tool_call_limit: int = Field(default=500, ge=1)
    crawl_history_retention_days: int = Field(default=365, ge=30, le=3650)
    crawl_worker_enabled: bool = False
    crawl_broker_url: str | None = None
    ai_test_daily_token_limit: int = Field(default=10000, ge=640)
    # Daily model-token ceiling per organization for specialist agent runs (e.g. fix drafting).
    ai_agent_daily_token_limit: int = Field(default=200_000, ge=640)
    credential_encryption_key: SecretStr | None = None
    native_auth_enabled: bool = False
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_tls: Literal["starttls", "implicit"] = "starttls"
    web_public_origin: str | None = None
    cms_wordpress_enabled: bool = False
    cms_wordpress_base_url: str | None = None
    cms_wordpress_username: str | None = None
    cms_wordpress_app_password: SecretStr | None = None
    cms_wordpress_execution_enabled: bool = False
    # The site runs the Reckon SEO Connector plugin, enabling meta title/description,
    # canonical and schema writes through the REST API.
    cms_wordpress_seo_connector: bool = False
    # Read-only verification of externally applied changes by fetching the public page.
    cms_public_verification_enabled: bool = True

    model_config = SettingsConfigDict(
        env_prefix="RECKON_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def require_production_integrations(self) -> "Settings":
        cms_values = (
            self.cms_wordpress_base_url,
            self.cms_wordpress_username,
            self.cms_wordpress_app_password,
        )
        if self.cms_wordpress_enabled and not all(
            value is not None and (
                not isinstance(value, SecretStr)
                or bool(value.get_secret_value())
            )
            for value in cms_values
        ):
            raise ValueError("WordPress CMS URL, username and application password must be configured together.")
        if self.cms_wordpress_execution_enabled and (
            not self.cms_wordpress_enabled or self.environment in {"production", "test"}
        ):
            raise ValueError(
                "WordPress execution requires configured WordPress credentials "
                "and a local or staging environment."
            )
        if self.crawl_worker_enabled and not self.crawl_broker_url:
            raise ValueError("A Redis/Celery broker is required when crawl workers are enabled.")
        oidc_values = (
            self.oidc_issuer,
            self.oidc_audience,
            self.oidc_jwks_url,
        )
        if any(oidc_values) and not all(oidc_values):
            raise ValueError("OIDC issuer, audience and JWKS URL must be configured together.")
        smtp_values = (self.smtp_host, self.smtp_from, self.web_public_origin)
        if any(smtp_values) and not all(smtp_values):
            raise ValueError("SMTP host, sender and web origin must be configured together.")
        if bool(self.smtp_username) != bool(self.smtp_password and self.smtp_password.get_secret_value()):
            raise ValueError("SMTP username and password must be configured together.")
        if self.web_public_origin:
            origin = urlsplit(self.web_public_origin)
            local = origin.hostname in {"localhost", "127.0.0.1", "::1"}
            if (
                not origin.hostname or origin.username or origin.password or origin.query
                or origin.fragment or origin.path not in ("", "/")
                or (origin.scheme != "https" and not (
                    self.environment in {"local", "test"} and local and origin.scheme == "http"
                ))
            ):
                raise ValueError("The public web origin must be HTTPS outside local development.")
        if self.environment == "production" and (
            self.database_url is None
            or (not self.native_auth_enabled and self.oidc_issuer is None)
            or (self.native_auth_enabled and not all(smtp_values))
        ):
            raise ValueError(
                "Production requires a database and configured OIDC or native authentication."
            )
        return self
