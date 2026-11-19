from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Reckon SEO Autopilot API"
    environment: Literal["local", "test", "staging", "production"] = "local"

    model_config = SettingsConfigDict(
        env_prefix="RECKON_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
