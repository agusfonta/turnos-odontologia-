"""Fixtures compartidas de C-04: PG real con esquema aplicado por Alembic."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-sintetico")
os.environ.setdefault("WA_PROVIDER_API_KEY", "test-wa-key-sintetica")

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
import sqlalchemy as sa
from sqlalchemy.orm import Session

from tests.support import alembic, db_clonada, db_temporal

@pytest.fixture(scope="session")
def pg_migrado_url() -> Iterator[str]:
    """DB plantilla en `head` (migraciones reales, no `create_all`). Nadie se conecta a ella."""
    with db_temporal() as url:
        res = alembic(url, "upgrade", "head")
        assert res.returncode == 0, res.stderr
        yield url


@pytest.fixture
def mig_engine(pg_migrado_url: str) -> Iterator[sa.Engine]:
    """Una DB clonada de la plantilla por test (rápido; sin TRUNCATE de limpieza)."""
    with db_clonada(pg_migrado_url) as url:
        engine = sa.create_engine(url)
        yield engine
        engine.dispose()


@pytest.fixture
def mig_session(mig_engine: sa.Engine) -> Iterator[Session]:
    session = Session(mig_engine)
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def api_client(mig_engine: sa.Engine) -> Iterator[TestClient]:
    """TestClient con `get_db` apuntando a la DB clonada migrada (PG real)."""

    import fakeredis

    from app.core.db import get_db
    from app.infrastructure.jobs import RecordatorioQueue, get_recordatorio_queue
    from app.main import app

    def _get_db() -> Iterator[Session]:
        session = Session(mig_engine)
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _get_db
    # Por defecto la cola va a un fakeredis (nunca al Redis real); los tests la pisan si hace falta.
    cola = RecordatorioQueue(fakeredis.FakeRedis(), sleep=lambda _s: None)
    app.dependency_overrides[get_recordatorio_queue] = lambda: cola
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
