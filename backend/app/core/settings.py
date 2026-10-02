"""Settings centralizados (pydantic-settings estricto).

Lee 6 vars + CORS_ORIGINS opcional. CLINIC_TIMEZONE y CANCEL_MIN_HOURS tienen
default no-sensible; los 4 secretos son requeridos (sin default) y fallan si
faltan. CORS_ORIGINS acepta lista separada por comas (default: dev local).
"""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = Field(min_length=1)
    REDIS_URL: str = Field(min_length=1)
    JWT_SECRET: SecretStr = Field(min_length=1)
    WA_PROVIDER_API_KEY: SecretStr = Field(min_length=1)
    CLINIC_TIMEZONE: str = "America/Argentina/Buenos_Aires"
    CANCEL_MIN_HOURS: int = Field(default=24, ge=0)
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
