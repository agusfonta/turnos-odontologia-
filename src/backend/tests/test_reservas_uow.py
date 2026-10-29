"""C-04b: la reserva escribe via Unit of Work (DTO, conflictos, atomicidad). PG real."""

import uuid
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.application.reservas import TurnoReservado, reservar_turno
from app.domain.schemas import TurnoCreate
from app.infrastructure.models import (
    AuditoriaTurno,
    HorarioProfesional,
    Paciente,
    Profesional,
    Turno,
    User,
    UserRole,
)
from tests.support import factoria_espia

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
AHORA = datetime(2030, 3, 1, 12, 0, tzinfo=timezone.utc)
LUNES = "2030-03-04"


@pytest.fixture
def prof(mig_session: Session) -> Profesional:
    p = Profesional(nombre="Dra. Sintetica", matricula=f"MAT-{uuid.uuid4().hex[:8]}")
    mig_session.add(p)
    mig_session.flush()
    mig_session.add(
        HorarioProfesional(profesional_id=p.id, dia_semana=0, hora_inicio=time(9), hora_fin=time(18))
    )
    mig_session.commit()
    return p


def _datos(prof: Profesional, hhmm: str = "10:00") -> TurnoCreate:
    return TurnoCreate(
        profesional_id=prof.id,
        inicio=datetime.fromisoformat(f"{LUNES}T{hhmm}:00-03:00"),
        paciente_nombre="Paciente Sintetico",
        paciente_telefono="+5491100000000",
    )


def test_reservar_turno_devuelve_dto_y_confirma_por_uow(
    mig_engine: sa.Engine, mig_session: Session, prof: Profesional
):
    bitacora: list[str] = []
    factoria = factoria_espia(mig_engine, bitacora)

    reservado = reservar_turno(factoria, _datos(prof), staff_id=None, ahora=AHORA, tz=TZ)

    assert isinstance(reservado, TurnoReservado) and not isinstance(reservado, Turno)
    assert bitacora == ["enter", "commit", "close"]  # la UoW cerro y confirmo
    mig_session.expire_all()
    fila = mig_session.get(Turno, reservado.id)  # otra sesion: ya es visible
    assert fila is not None
    assert (reservado.profesional_id, reservado.tratamiento_id) == (fila.profesional_id, fila.tratamiento_id)
    assert (reservado.inicio, reservado.fin) == (fila.inicio, fila.fin)
    assert reservado.origen == fila.origen.value == "online"
    assert reservado.token_publico == fila.token_publico


def _usuario_secretaria(session: Session) -> User:
    user = User(
        email=f"secretaria-{uuid.uuid4().hex[:6]}@example.test",
        password_hash="x",
        rol=UserRole.SECRETARIA,
    )
    session.add(user)
    session.commit()
    return user


def test_staff_id_marca_origen_secretaria_y_created_by(
    mig_engine: sa.Engine, mig_session: Session, prof: Profesional
):
    sec = _usuario_secretaria(mig_session)
    factoria = factoria_espia(mig_engine, [])

    reservado = reservar_turno(factoria, _datos(prof), staff_id=sec.id, ahora=AHORA, tz=TZ)

    mig_session.expire_all()
    fila = mig_session.get(Turno, reservado.id)
    assert reservado.origen == "secretaria" and fila.origen.value == "secretaria"
    assert fila.created_by == sec.id
    (aud,) = mig_session.scalars(sa.select(AuditoriaTurno)).all()
    assert aud.actor_tipo.value == "secretaria" and aud.actor_user_id == sec.id


# --- 3.3 conflictos y errores con la UoW --------------------------------------

from app.core.exceptions import HuecoOcupadoError  # noqa: E402
from sqlalchemy.exc import IntegrityError, OperationalError  # noqa: E402

# Escritura fallida: se cierra con rollback ANTES de abrir la UoW de lectura de huecos.
BITACORA_CONFLICTO = ["enter", "rollback", "close", "enter", "commit", "close"]


def _pg_error(sqlstate: str) -> IntegrityError:
    orig = type("PgError", (Exception,), {"sqlstate": sqlstate})("violacion sintetica")
    return IntegrityError("INSERT sintetico", {}, orig)


def _reservar_ok(mig_engine: sa.Engine, prof: Profesional, hhmm: str = "10:00") -> TurnoReservado:
    return reservar_turno(
        factoria_espia(mig_engine, []), _datos(prof, hhmm), staff_id=None, ahora=AHORA, tz=TZ
    )


def _hhmm(huecos: list[dict[str, str]]) -> set[str]:
    return {h["inicio"][11:16] for h in huecos}


def test_chequeo_de_aplicacion_cierra_escritura_antes_de_releer_huecos(
    mig_engine: sa.Engine, mig_session: Session, prof: Profesional
):
    _reservar_ok(mig_engine, prof)
    bitacora: list[str] = []

    with pytest.raises(HuecoOcupadoError) as info:
        reservar_turno(
            factoria_espia(mig_engine, bitacora), _datos(prof), staff_id=None, ahora=AHORA, tz=TZ
        )

    assert bitacora == BITACORA_CONFLICTO
    assert "10:00" not in _hhmm(info.value.huecos) and "09:30" in _hhmm(info.value.huecos)


def test_23p01_en_el_flush_cierra_escritura_antes_de_releer_huecos(
    mig_engine: sa.Engine, mig_session: Session, prof: Profesional, monkeypatch
):
    _reservar_ok(mig_engine, prof)
    monkeypatch.setattr("app.application.reservas.hay_ocupacion", lambda *a, **k: False)
    bitacora: list[str] = []

    with pytest.raises(HuecoOcupadoError) as info:
        reservar_turno(
            factoria_espia(mig_engine, bitacora), _datos(prof), staff_id=None, ahora=AHORA, tz=TZ
        )

    assert bitacora == BITACORA_CONFLICTO
    assert "10:00" not in _hhmm(info.value.huecos)
    mig_session.expire_all()  # el perdedor no dejo paciente ni auditoria
    assert mig_session.scalar(sa.select(sa.func.count()).select_from(Paciente)) == 1
    assert mig_session.scalar(sa.select(sa.func.count()).select_from(AuditoriaTurno)) == 1


def test_23p01_en_el_commit_se_mapea_a_hueco_ocupado(
    mig_engine: sa.Engine, mig_session: Session, prof: Profesional
):
    """Defensa ante una constraint DEFERRABLE futura: el error sale del COMMIT de __exit__."""
    _reservar_ok(mig_engine, prof)
    bitacora: list[str] = []
    factoria = factoria_espia(mig_engine, bitacora, commit_error=_pg_error("23P01"))

    with pytest.raises(HuecoOcupadoError) as info:
        reservar_turno(factoria, _datos(prof, "11:00"), staff_id=None, ahora=AHORA, tz=TZ)

    assert bitacora[:3] == ["enter", "commit", "close"]  # el commit fallo; la UoW igual cerro
    assert bitacora[3:] == ["enter", "commit", "close"]  # releyo huecos en UoW nueva
    assert "10:00" not in _hhmm(info.value.huecos)
    mig_session.expire_all()
    assert mig_session.scalar(sa.select(sa.func.count()).select_from(Turno)) == 1  # sin residuo de 11:00


def test_otra_violacion_de_integridad_se_propaga_sin_enmascarar(
    mig_engine: sa.Engine, mig_session: Session, prof: Profesional
):
    bitacora: list[str] = []
    factoria = factoria_espia(mig_engine, bitacora, commit_error=_pg_error("23505"))

    with pytest.raises(IntegrityError):
        reservar_turno(factoria, _datos(prof), staff_id=None, ahora=AHORA, tz=TZ)

    assert bitacora == ["enter", "commit", "close"]  # no hubo relectura de huecos
    mig_session.expire_all()
    assert mig_session.scalar(sa.select(sa.func.count()).select_from(Turno)) == 0


# --- 4.2 atomicidad ante commit fallido (via API) ------------------------------

import fakeredis  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.clock import get_ahora  # noqa: E402
from app.infrastructure.jobs import RECORDATORIOS_KEY, RecordatorioQueue, get_recordatorio_queue  # noqa: E402
from app.infrastructure.unit_of_work import get_uow_factory  # noqa: E402
from app.main import app  # noqa: E402


def _body(prof: Profesional, hhmm: str = "10:00") -> dict:
    return {
        "profesional_id": str(prof.id),
        "inicio": f"{LUNES}T{hhmm}:00-03:00",
        "paciente_nombre": "Paciente Sintetico",
        "paciente_telefono": "+5491100000000",
    }


@pytest.fixture
def entorno_api(api_client, mig_engine: sa.Engine):
    app.dependency_overrides[get_ahora] = lambda: AHORA
    redis_falso = fakeredis.FakeRedis(decode_responses=True)
    app.dependency_overrides[get_recordatorio_queue] = lambda: RecordatorioQueue(
        redis_falso, sleep=lambda _s: None
    )
    return redis_falso


def _cuenta(session: Session, modelo) -> int:
    session.expire_all()
    return session.scalar(sa.select(sa.func.count()).select_from(modelo))


def test_commit_fallido_500_sin_filas_ni_job(
    entorno_api, mig_engine: sa.Engine, mig_session: Session, prof: Profesional
):
    falla = OperationalError("COMMIT", {}, Exception("conexion perdida (sintetica)"))
    app.dependency_overrides[get_uow_factory] = lambda: factoria_espia(
        mig_engine, [], commit_error=falla
    )
    cliente = TestClient(app, raise_server_exceptions=False)

    resp = cliente.post("/api/turnos", json=_body(prof))

    assert resp.status_code == 500
    assert _cuenta(mig_session, Turno) == 0
    assert _cuenta(mig_session, Paciente) == 0
    assert _cuenta(mig_session, AuditoriaTurno) == 0
    assert entorno_api.zcard(RECORDATORIOS_KEY) == 0


def test_carrera_23p01_da_409_y_solo_filas_del_ganador(
    entorno_api, mig_engine: sa.Engine, mig_session: Session, prof: Profesional, monkeypatch
):
    assert TestClient(app).post("/api/turnos", json=_body(prof)).status_code == 201
    entorno_api.delete(RECORDATORIOS_KEY)
    monkeypatch.setattr("app.application.reservas.hay_ocupacion", lambda *a, **k: False)

    resp = TestClient(app).post("/api/turnos", json=_body(prof))

    assert resp.status_code == 409 and resp.json()["code"] == "hueco_ocupado"
    assert "10:00" not in _hhmm(resp.json()["huecos"])
    assert _cuenta(mig_session, Turno) == 1
    assert _cuenta(mig_session, Paciente) == 1
    assert _cuenta(mig_session, AuditoriaTurno) == 1
    assert entorno_api.zcard(RECORDATORIOS_KEY) == 0
