"""T2 RED: modelos core + constraints. Debe FALLAR (no existen los modelos)."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-sintetico")
os.environ.setdefault("WA_PROVIDER_API_KEY", "test-wa-key-sintetica")

import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.db import Base
from app.domain.phone import E164_PATTERN
from app.domain.schemas import PacienteCreate, TratamientoCreate, UserCreate
from app.infrastructure.models import Paciente, Profesional, Tratamiento, User, UserRole
from tests.support import require_pg


def _pg_session() -> Session:
    engine = require_pg()
    Base.metadata.create_all(engine, checkfirst=True)
    return Session(engine)


def _unique_suffix() -> str:
    return uuid.uuid4().hex[:8]


def test_matricula_duplicada_rechazada():
    session = _pg_session()
    suf = _unique_suffix()
    try:
        session.add(Profesional(nombre="A", matricula=f"MAT-{suf}", slot_default_min=30))
        session.commit()
        session.add(Profesional(nombre="B", matricula=f"MAT-{suf}", slot_default_min=30))
        with pytest.raises(DBAPIError):
            session.commit()
    finally:
        session.rollback()
        session.execute(
            Profesional.__table__.delete().where(Profesional.matricula == f"MAT-{suf}")
        )
        session.commit()
        session.close()


def test_telefono_no_e164_rechazado():
    session = _pg_session()
    try:
        session.add(Paciente(nombre="SinFormato", telefono="123456"))
        with pytest.raises(DBAPIError):
            session.commit()
    finally:
        session.rollback()
        session.close()


def test_duracion_min_lte_cero_rechazada():
    session = _pg_session()
    try:
        session.add(Tratamiento(nombre=f"Bad-{_unique_suffix()}", duracion_min=0))
        with pytest.raises(DBAPIError):
            session.commit()
    finally:
        session.rollback()
        session.close()


def test_email_case_insensitive_unico():
    session = _pg_session()
    suf = _unique_suffix()
    try:
        session.add(
            User(
                email=f"Staff-{suf}@Example.test",
                password_hash="hash-sintetico",
                rol=UserRole.SECRETARIA,
            )
        )
        session.commit()
        # El normalizador baja a minúsculas → viola el unique.
        session.add(
            User(
                email=f"staff-{suf}@example.test",
                password_hash="hash-sintetico",
                rol=UserRole.SECRETARIA,
            )
        )
        with pytest.raises(DBAPIError):
            session.commit()
        session.rollback()
        guardado = session.scalar(
            select(User).where(User.email == f"staff-{suf}@example.test")
        )
        assert guardado is not None
        assert guardado.email == f"staff-{suf}@example.test"
    finally:
        session.rollback()
        session.execute(User.__table__.delete().where(User.email == f"staff-{suf}@example.test"))
        session.commit()
        session.close()


def test_slot_default_min_lte_cero_rechazado():
    session = _pg_session()
    try:
        session.add(
            Profesional(nombre="X", matricula=f"MAT-{_unique_suffix()}", slot_default_min=0)
        )
        with pytest.raises(DBAPIError):
            session.commit()
    finally:
        session.rollback()
        session.close()


def test_user_rol_paciente_rechazado():
    session = _pg_session()
    try:
        session.add(
            User(
                email=f"pac-{_unique_suffix()}@example.test",
                password_hash="hash-sintetico",
                rol="paciente",  # type: ignore[arg-type]
            )
        )
        with pytest.raises(DBAPIError):
            session.commit()
    finally:
        session.rollback()
        session.close()
    with pytest.raises(ValidationError):
        UserCreate(email="pac@example.test", password="secreto123", rol="paciente")


@pytest.mark.parametrize(
    "telefono",
    [
        "+5491101234567",
        "+541100000000",
        "+12345678",
        "+123456789012345",
        "+34910000000",
        "+810901234567",
    ],
)
def test_validador_pydantic_e164_acepta_validos(telefono: str):
    obj = PacienteCreate(nombre="Ok", telefono=telefono)
    assert obj.telefono == telefono


@pytest.mark.parametrize(
    "telefono",
    [
        "123456",
        "+",
        "++5411000000",
        "+054110000000",
        "+5411",
        "+541100000000000000",
        "+54 11 0000 0000",
    ],
)
def test_validador_pydantic_e164_rechaza_invalidos(telefono: str):
    with pytest.raises(ValidationError):
        PacienteCreate(nombre="Mal", telefono=telefono)


def test_validador_pydantic_e164_recorta_espacios():
    obj = PacienteCreate(nombre="Ok", telefono="  +541100000000 ")
    assert obj.telefono == "+541100000000"


def test_app_y_db_comparten_regex_e164():
    from sqlalchemy import CheckConstraint

    assert E164_PATTERN == r"^\+[1-9][0-9]{7,14}$"
    checks = [
        c.sqltext.text
        for c in Paciente.__table__.constraints
        if isinstance(c, CheckConstraint)
    ]
    assert any(E164_PATTERN in sql for sql in checks)


def test_activo_es_alias_de_is_active_sin_columna_duplicada():
    assert "activo" not in Profesional.__table__.c
    assert "activo" not in Tratamiento.__table__.c
    prof = Profesional(nombre="A", matricula="MAT-X", slot_default_min=30)
    prof.activo = False
    assert prof.is_active is False
    prof.activo = True
    assert prof.is_active is True
    trat = Tratamiento(nombre="T", duracion_min=30)
    trat.activo = False
    assert trat.is_active is False


def test_tratamiento_create_rechaza_duracion_no_positiva():
    with pytest.raises(ValidationError):
        TratamientoCreate(nombre="Limpieza", duracion_min=0)
    with pytest.raises(ValidationError):
        TratamientoCreate(nombre="Limpieza", duracion_min=-5)
    assert TratamientoCreate(nombre="Limpieza", duracion_min=30).duracion_min == 30
