"""T3 RED: BaseRepository[T] + UnitOfWork. Debe FALLAR (módulos inexistentes)."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-sintetico")
os.environ.setdefault("WA_PROVIDER_API_KEY", "test-wa-key-sintetica")

import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy import String, create_engine, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.db import Base
from app.domain.base import AuditMixin
from app.infrastructure.models import Tratamiento
from app.infrastructure.repositories import BaseRepository
from app.infrastructure.unit_of_work import UnitOfWork
from tests.support import TEST_DATABASE_URL


class ProbeRepo(Base, AuditMixin):
    __tablename__ = "probe_repo"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(50))


def _pg_engine_or_none() -> sa.Engine | None:
    try:
        engine = sa.create_engine(TEST_DATABASE_URL, connect_args={"connect_timeout": 3})
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
        return engine
    except Exception:
        return None


@pytest.fixture
def store() -> Iterator[tuple[Session, type, object]]:
    """(session, model, factory). PG con modelos reales si hay; si no,
    SQLite + probe (NOTA: capa genérica, los constraints se prueban en T2/PG)."""
    pg_engine = _pg_engine_or_none()
    if pg_engine is not None:
        Base.metadata.create_all(pg_engine, checkfirst=True)
        session = Session(pg_engine)
        tag = uuid.uuid4().hex[:8]

        def factory(i: int) -> Tratamiento:
            return Tratamiento(nombre=f"T3-{tag}-{i}", duracion_min=20 + i)

        yield session, Tratamiento, factory
        session.execute(
            Tratamiento.__table__.delete().where(
                Tratamiento.nombre.like(f"T3-{tag}-%")
            )
        )
        session.commit()
        session.close()
    else:
        engine = create_engine("sqlite:///:memory:")
        ProbeRepo.__table__.create(engine)
        session = Session(engine)
        yield session, ProbeRepo, lambda i: ProbeRepo(nombre=f"P3-{i}")
        session.close()


def _nombres(session: Session, model: type, **kwargs: object) -> list[str]:
    repo = BaseRepository(session, model)
    return [e.nombre for e in repo.list(**kwargs)]  # type: ignore[attr-defined]


def test_add_y_get_roundtrip(store: tuple[Session, type, object]) -> None:
    session, model, factory = store
    repo = BaseRepository(session, model)
    entity = repo.add(factory(1))
    session.commit()
    session.refresh(entity)

    recuperada = repo.get(entity.id)

    assert recuperada is not None
    assert recuperada.id == entity.id
    assert recuperada.nombre == entity.nombre


def test_uow_rollback_no_persiste(store: tuple[Session, type, object]) -> None:
    session, model, factory = store
    engine = session.get_bind()
    nombre = getattr(factory(99), "nombre")

    with pytest.raises(RuntimeError, match="boom"):
        with UnitOfWork(session_factory=lambda: Session(engine)) as uow_session:
            BaseRepository(uow_session, model).add(factory(99))
            uow_session.flush()
            raise RuntimeError("boom")

    session.rollback()
    assert session.scalar(select(model).where(model.nombre == nombre)) is None  # type: ignore[attr-defined]


def test_uow_commit_persiste(store: tuple[Session, type, object]) -> None:
    session, model, factory = store
    engine = session.get_bind()
    nombre = getattr(factory(7), "nombre")

    with UnitOfWork(session_factory=lambda: Session(engine)) as uow_session:
        BaseRepository(uow_session, model).add(factory(7))

    session.rollback()
    assert session.scalar(select(model).where(model.nombre == nombre)) is not None  # type: ignore[attr-defined]


def test_soft_delete_excluye_de_list_e_incluye_con_flag(
    store: tuple[Session, type, object],
) -> None:
    session, model, factory = store
    repo = BaseRepository(session, model)
    repo.add(factory(1))
    dados_de_baja = repo.add(factory(2))
    session.commit()

    repo.soft_delete(dados_de_baja)
    session.commit()

    assert len(repo.list()) == 1
    assert len(repo.list(include_inactive=True)) == 2


def test_list_paginado_limit_offset(store: tuple[Session, type, object]) -> None:
    session, model, factory = store
    repo = BaseRepository(session, model)
    for i in range(5):
        repo.add(factory(i))
    session.commit()

    pagina = repo.list(limit=2, offset=1)

    assert [e.nombre for e in pagina] == _nombres(session, model)[1:3]
    assert len(repo.list(limit=2, offset=0)) == 2
    assert len(repo.list(limit=10, offset=4)) == 1
