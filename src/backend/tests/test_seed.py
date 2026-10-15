"""T5 RED: seed idempotente + hash_password. Debe FALLAR (módulos inexistentes)."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-sintetico")
os.environ.setdefault("WA_PROVIDER_API_KEY", "test-wa-key-sintetica")

import pytest
from sqlalchemy.orm import Session

from app.core.db import Base
from app.core.security import hash_password
from app.infrastructure import seed as seed_module
from app.infrastructure.models import Profesional, Tratamiento, User
from tests.support import require_pg

_SEED_TABLES = (User.__table__, Profesional.__table__, Tratamiento.__table__)


@pytest.fixture
def pg_session() -> Session:
    engine = require_pg()
    Base.metadata.create_all(engine, checkfirst=True)
    with engine.begin() as conn:
        for table in _SEED_TABLES:
            conn.execute(table.delete())
    session = Session(engine)
    yield session
    session.close()
    # Limpieza posterior: la suite debe ser repetible (sin filas residuales
    # que rompan los conteos de test_repositories en la próxima corrida).
    with engine.begin() as conn:
        for table in _SEED_TABLES:
            conn.execute(table.delete())
    engine.dispose()


def _conteos(session: Session) -> tuple[int, int, int]:
    return (
        session.query(User).count(),
        session.query(Profesional).count(),
        session.query(Tratamiento).count(),
    )


def test_seed_doble_corrida_mismos_conteos(pg_session: Session):
    session = pg_session
    seed_module.run_seed(session)
    session.rollback()
    primer = _conteos(session)
    seed_module.run_seed(session)
    session.rollback()
    segundo = _conteos(session)

    assert primer == segundo == (1, 1, 3)


def test_seed_respeta_cancel_min_hours_de_settings(monkeypatch, pg_session: Session):
    from types import SimpleNamespace

    session = pg_session
    monkeypatch.setattr(
        seed_module, "get_settings", lambda: SimpleNamespace(CANCEL_MIN_HOURS=48)
    )
    resultado = seed_module.run_seed(session)

    assert resultado["cancel_min_hours"] == 48


def test_seed_no_duplica_por_clave_natural(pg_session: Session):
    session = pg_session
    pre = User(
        email=seed_module.SEED_SECRETARIA_EMAIL,
        password_hash=hash_password("PreExistente123"),
        rol=seed_module.UserRole.SECRETARIA,
    )
    session.add(pre)
    session.commit()
    hash_previo = pre.password_hash

    seed_module.run_seed(session)
    session.rollback()

    assert session.query(User).count() == 1
    conservada = session.query(User).one()
    assert conservada.password_hash == hash_previo


def test_seed_sin_datos_reales():
    assert seed_module.SEED_SECRETARIA_EMAIL.endswith("@example.test")
    assert "gmail" not in seed_module.SEED_SECRETARIA_EMAIL
    assert seed_module.SEED_PROFESIONAL_MATRICULA.startswith("MAT-EJ-")
    nombres = [nombre for nombre, _ in seed_module.SEED_TRATAMIENTOS]
    assert sorted(nombres) == sorted(["Limpieza", "Consulta", "Tratamiento de conducto"])


def test_hash_password_no_devuelve_plano():
    plano = "SecretoSintetico123"
    hashed = hash_password(plano)

    assert hashed != plano
    assert hashed.startswith("$2b$")
    assert hash_password(plano) != hashed  # salt aleatorio
