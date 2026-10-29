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


# --- C-04: DB temporal migrada con Alembic (002) -----------------------------

import subprocess
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def alembic(db_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Corre `alembic <args>` en subproceso apuntando a `db_url` (settings lee env)."""
    env = {
        **os.environ,
        "DATABASE_URL": db_url,
        "REDIS_URL": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        "JWT_SECRET": os.environ.get("JWT_SECRET", "test-jwt-secret-sintetico"),
        "WA_PROVIDER_API_KEY": os.environ.get("WA_PROVIDER_API_KEY", "test-wa-key-sintetica"),
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _url_con_db(nombre: str) -> str:
    return (
        sa.engine.make_url(TEST_DATABASE_URL)
        .set(database=nombre)
        .render_as_string(hide_password=False)
    )


@contextmanager
def db_clonada(url_plantilla: str) -> Iterator[str]:
    """Clona una DB migrada (CREATE DATABASE ... TEMPLATE) y la descarta al salir.

    Aislamiento por test sin back doors: `auditoria_turno` es append-only
    (incluso TRUNCATE), así que la limpieza es tirar la DB entera, no borrar filas.
    La plantilla no debe tener conexiones abiertas mientras se clona.
    """
    admin = require_pg()
    plantilla = sa.engine.make_url(url_plantilla).database
    nombre = f"turnos_mig_{uuid.uuid4().hex[:10]}"
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{nombre}" TEMPLATE "{plantilla}"'))
    try:
        yield _url_con_db(nombre)
    finally:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)'))
        admin.dispose()


@contextmanager
def db_temporal() -> Iterator[str]:
    """Crea una DB vacía descartable en el mismo servidor y devuelve su URL.

    Aislada de `turnos_test` (que los tests de C-02 llenan con `create_all`):
    las migraciones se prueban siempre desde cero.
    """
    admin = require_pg()
    nombre = f"turnos_mig_{uuid.uuid4().hex[:10]}"
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{nombre}"'))
    url = sa.engine.make_url(TEST_DATABASE_URL).set(database=nombre).render_as_string(
        hide_password=False
    )
    try:
        yield url
    finally:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)'))
        admin.dispose()


def snapshot_esquema(engine: sa.Engine) -> dict[str, list[tuple]]:
    """Foto comparable del esquema public: tablas/columnas, constraints,
    índices, tipos propios y triggers (para probar el ciclo up/down/up)."""
    consultas = {
        "columnas": "SELECT table_name, column_name, data_type, udt_name, is_nullable, "
        "column_default FROM information_schema.columns WHERE table_schema='public' "
        "ORDER BY 1, 2",
        "constraints": "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) "
        "FROM pg_constraint WHERE connamespace='public'::regnamespace ORDER BY 1, 2",
        "indices": "SELECT tablename, indexname, indexdef FROM pg_indexes "
        "WHERE schemaname='public' ORDER BY 1, 2",
        "tipos": "SELECT typname, typtype FROM pg_type WHERE typnamespace='public'::regnamespace "
        "AND typtype IN ('e','r') ORDER BY 1",
        "triggers": "SELECT tgrelid::regclass::text, tgname FROM pg_trigger "
        "WHERE NOT tgisinternal ORDER BY 1, 2",
    }
    with engine.connect() as conn:
        return {k: [tuple(r) for r in conn.execute(sa.text(q))] for k, q in consultas.items()}


# --- C-04b: UoW espia (bitacora de enter/commit/rollback/close) ----------------

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.infrastructure.unit_of_work import UnitOfWork


class UowEspia(UnitOfWork):
    """UoW que registra enter/commit/rollback/close en una bitacora compartida.

    `commit_error`: si se pasa, el `commit()` de la sesion lanza esa excepcion
    (despues de anotarlo) en vez de confirmar; el `rollback`/`close` siguen reales.
    """

    def __init__(
        self,
        bitacora: list[str],
        session_factory: Callable[[], Session],
        commit_error: BaseException | None = None,
    ) -> None:
        super().__init__(session_factory=session_factory)
        self._bitacora = bitacora
        self._commit_error = commit_error

    def __enter__(self) -> Session:
        self._bitacora.append("enter")
        session = super().__enter__()
        original_commit, original_rollback, original_close = (
            session.commit,
            session.rollback,
            session.close,
        )

        def commit() -> None:
            self._bitacora.append("commit")
            if self._commit_error is not None:
                raise self._commit_error
            original_commit()

        def rollback() -> None:
            self._bitacora.append("rollback")
            original_rollback()

        def close() -> None:
            self._bitacora.append("close")
            original_close()

        session.commit, session.rollback, session.close = commit, rollback, close  # type: ignore[method-assign]
        return session


def factoria_espia(
    engine: sa.Engine,
    bitacora: list[str],
    *,
    commit_error: BaseException | None = None,
) -> Callable[[], UowEspia]:
    """Factoria de UoW espia sobre `engine`. `commit_error` aplica solo a la PRIMERA UoW
    (la de escritura); las siguientes (relectura de huecos) confirman normal."""
    pendiente = [commit_error]

    def crear() -> UowEspia:
        error = pendiente.pop(0) if pendiente else None
        return UowEspia(bitacora, lambda: Session(engine), commit_error=error)

    return crear
