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


def test_disponibilidad_max_dias_default_31(monkeypatch):
    monkeypatch.delenv("DISPONIBILIDAD_MAX_DIAS", raising=False)
    from app.core.settings import Settings

    assert Settings().DISPONIBILIDAD_MAX_DIAS == 31


@pytest.mark.parametrize("valor", ["0", "-5"])
def test_disponibilidad_max_dias_no_positivo_rechazado(monkeypatch, valor):
    monkeypatch.setenv("DISPONIBILIDAD_MAX_DIAS", valor)
    from app.core.settings import Settings

    with pytest.raises(ValidationError):
        Settings()


def test_disponibilidad_max_dias_override_por_env(monkeypatch):
    monkeypatch.setenv("DISPONIBILIDAD_MAX_DIAS", "14")
    from app.core.settings import Settings

    assert Settings().DISPONIBILIDAD_MAX_DIAS == 14
