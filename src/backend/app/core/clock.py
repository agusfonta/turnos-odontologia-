"""Reloj inyectable: dependencia FastAPI que los tests sobreescriben (`dependency_overrides`)."""

from datetime import datetime, timezone


def get_ahora() -> datetime:
    return datetime.now(timezone.utc)
