"""T1 RED: settings/timezone + secretos sin default. Debe FALLAR hasta crear core/settings.py."""

import os

import pytest
from pydantic import ValidationError

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-sintetico")
os.environ.setdefault("WA_PROVIDER_API_KEY", "test-wa-key-sintetica")


def test_default_timezone_es_buenos_aires(monkeypatch):
    monkeypatch.delenv("CLINIC_TIMEZONE", raising=False)
    from app.core.settings import Settings

    settings = Settings()
    assert settings.CLINIC_TIMEZONE == "America/Argentina/Buenos_Aires"


def test_missing_jwt_secret_fails_validation(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    from app.core.settings import Settings

    with pytest.raises(ValidationError):
        Settings()
