"""Soporte de tests con DB (C-02).

Los tests de constraints necesitan Postgres real (CHECK regex `~`, enums
nativos y UniqueViolation tienen semántica distinta en SQLite). Si no hay
PG accesible: skip explícito, nunca verde silencioso.
"""

import os

import pytest
import sqlalchemy as sa

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://turnos:turnos@localhost:5432/turnos_test",
)


def pg_engine() -> sa.Engine:
    return sa.create_engine(TEST_DATABASE_URL, connect_args={"connect_timeout": 3})


def require_pg() -> sa.Engine:
    """Devuelve engine PG verificado o hace skip explícito."""
    engine = pg_engine()
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
    except Exception as exc:
        engine.dispose()
        pytest.skip(f"sin Postgres accesible en {TEST_DATABASE_URL} ({exc.__class__.__name__})")
    return engine
