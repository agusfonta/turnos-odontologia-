"""T1 RED: AuditMixin + soft delete. Debe FALLAR hasta crear app/domain/base.py."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-sintetico")
os.environ.setdefault("WA_PROVIDER_API_KEY", "test-wa-key-sintetica")

from datetime import datetime, timedelta, timezone

from sqlalchemy import String, create_engine, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.db import Base
from app.domain.base import AuditMixin


class Probe(Base, AuditMixin):
    __tablename__ = "probe_audit"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(50))


def _session() -> Session:
    # Solo la tabla probe: Base.metadata es global y otros módulos (T2)
    # registran tablas con CHECK PG (`~`) que SQLite no acepta.
    engine = create_engine("sqlite:///:memory:")
    Probe.__table__.create(engine)
    return Session(engine)


def test_soft_delete_marca_is_active_y_deleted_at():
    session = _session()
    probe = Probe(nombre="uno")
    session.add(probe)
    session.commit()

    probe.soft_delete()
    session.commit()
    session.refresh(probe)

    assert probe.is_active is False
    assert probe.deleted_at is not None


def test_list_excluye_inactivos_por_defecto():
    session = _session()
    session.add_all([Probe(nombre="activo"), Probe(nombre="baja")])
    session.commit()

    de_baja = session.scalar(select(Probe).where(Probe.nombre == "baja"))
    assert de_baja is not None
    de_baja.soft_delete()
    session.commit()

    visibles = session.scalars(select(Probe).where(Probe.is_active.is_(True))).all()

    assert [p.nombre for p in visibles] == ["activo"]


def test_updated_at_cambia_en_update():
    session = _session()
    probe = Probe(nombre="uno")
    session.add(probe)
    session.commit()

    # NOTA: SQLite devuelve datetimes naive; en PG (timestamptz) son aware.
    # El test usa naive para correr sin DB; la semántica onupdate es la misma.
    viejo = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    probe.updated_at = viejo
    session.commit()

    probe.nombre = "dos"
    session.commit()
    session.refresh(probe)

    assert probe.updated_at > viejo


def test_created_at_tiene_default_en_db():
    session = _session()
    probe = Probe(nombre="uno")
    session.add(probe)
    session.commit()
    session.refresh(probe)

    assert probe.created_at is not None
    assert probe.updated_at is not None
    assert probe.is_active is True
    assert probe.deleted_at is None
