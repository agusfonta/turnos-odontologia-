"""C-06 4.2/4.3: casos de uso de bloqueos sobre la UoW (PG real, DB clonada migrada)."""

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.bloqueos import BloqueoDTO, crear_bloqueo, dar_de_baja_bloqueo
from app.core.exceptions import (
    BloqueoConTurnosError,
    BloqueoNoEncontradoError,
    ProfesionalNoEncontradoError,
    RangoInvalidoError,
)
from app.domain.schemas import BloqueoCreate
from app.domain.turno_estados import EstadoTurno
from app.infrastructure.models import Bloqueo, Profesional
from app.infrastructure.repositories_agenda import BloqueoRepository, TurnoRepository
from app.infrastructure.unit_of_work import UnitOfWork
from tests.support import factoria_espia
from tests.support_gestion import AHORA, LUNES, crear_profesional, crear_turno, cuenta, inicio

TZ = ZoneInfo("America/Argentina/Buenos_Aires")


@pytest.fixture
def uow_factory(mig_engine: sa.Engine):
    return lambda: UnitOfWork(session_factory=lambda: Session(mig_engine))


@pytest.fixture
def prof(mig_session: Session) -> Profesional:
    return crear_profesional(mig_session)


def _datos(prof, desde: str = "09:00", hasta: str = "13:00", motivo: str = "Capacitacion"):
    return BloqueoCreate(
        profesional_id=prof.id, desde=inicio(desde), hasta=inicio(hasta), motivo=motivo
    )


def _crear(uow_factory, datos, ahora=AHORA) -> BloqueoDTO:
    return crear_bloqueo(uow_factory, datos, ahora=ahora, tz=TZ)


def _filas(session: Session) -> list[Bloqueo]:
    session.expire_all()
    return list(session.scalars(sa.select(Bloqueo)))


# --- 4.2 crear_bloqueo -------------------------------------------------------------------


def test_crear_bloqueo_libre(uow_factory, mig_session, prof):
    dto = _crear(uow_factory, _datos(prof))

    assert isinstance(dto, BloqueoDTO)
    assert (dto.profesional_id, dto.desde, dto.hasta, dto.motivo) == (
        prof.id, inicio("09:00"), inicio("13:00"), "Capacitacion",
    )
    (fila,) = _filas(mig_session)  # commit real: visible desde otra sesion
    assert fila.id == dto.id and fila.is_active and fila.deleted_at is None


def test_crear_bloqueo_con_desde_igual_a_ahora_es_valido(uow_factory, mig_session, prof):
    datos = BloqueoCreate(
        profesional_id=prof.id, desde=AHORA, hasta=AHORA + timedelta(hours=2), motivo="Ahora"
    )
    assert _crear(uow_factory, datos).desde == AHORA


def test_desde_en_el_pasado_es_rango_invalido(uow_factory, mig_session, prof):
    ahora = inicio("09:00") + timedelta(seconds=1)

    with pytest.raises(RangoInvalidoError):
        _crear(uow_factory, _datos(prof), ahora=ahora)

    assert cuenta(mig_session, Bloqueo) == 0


def test_profesional_inexistente_404(uow_factory, mig_session):
    datos = BloqueoCreate(
        profesional_id=uuid.uuid4(), desde=inicio("09:00"), hasta=inicio("13:00"), motivo="X"
    )
    with pytest.raises(ProfesionalNoEncontradoError):
        _crear(uow_factory, datos)
    assert cuenta(mig_session, Bloqueo) == 0


def test_profesional_inactivo_404(uow_factory, mig_session, prof):
    prof.is_active = False
    mig_session.commit()

    with pytest.raises(ProfesionalNoEncontradoError):
        _crear(uow_factory, _datos(prof))
    assert cuenta(mig_session, Bloqueo) == 0


def test_turno_reservado_en_el_rango_409_con_lista_y_sin_bloqueo(uow_factory, mig_session, prof):
    t10 = crear_turno(mig_session, prof, "10:00")
    t11 = crear_turno(mig_session, prof, "11:00", estado=EstadoTurno.CONFIRMADO, telefono="+5491100000098")
    crear_turno(mig_session, prof, "09:00", estado=EstadoTurno.CANCELADO, telefono="+5491100000097")

    with pytest.raises(BloqueoConTurnosError) as exc:
        _crear(uow_factory, _datos(prof))

    assert [(t.id, t.estado) for t in exc.value.turnos] == [
        (t10.id, EstadoTurno.RESERVADO),
        (t11.id, EstadoTurno.CONFIRMADO),
    ]
    assert exc.value.turnos[0].inicio.utcoffset() == timedelta(hours=-3)  # zona de la clinica
    assert cuenta(mig_session, Bloqueo) == 0  # leido desde otra sesion


def test_turno_contiguo_cancelado_o_de_otro_profesional_no_impide(uow_factory, mig_session, prof):
    otro = crear_profesional(mig_session)
    crear_turno(mig_session, prof, "08:30")  # termina en 09:00 = desde
    crear_turno(mig_session, prof, "13:00", telefono="+5491100000098")  # empieza en hasta
    crear_turno(mig_session, prof, "10:00", estado=EstadoTurno.CANCELADO, telefono="+5491100000097")
    crear_turno(mig_session, otro, "10:00", telefono="+5491100000096")

    assert _crear(uow_factory, _datos(prof)).id is not None


def test_toma_el_advisory_lock_del_profesional(uow_factory, mig_session, prof, monkeypatch):
    pedidos: list[uuid.UUID] = []
    original = TurnoRepository.bloquear_agenda

    def espia(self, profesional_id):
        pedidos.append(profesional_id)
        return original(self, profesional_id)

    monkeypatch.setattr(TurnoRepository, "bloquear_agenda", espia)

    _crear(uow_factory, _datos(prof))

    assert pedidos == [prof.id]


def test_trigger_23p01_se_traduce_a_409_con_lista_releida_en_uow_nueva(
    mig_engine, mig_session, prof, monkeypatch
):
    """Red de seguridad: el chequeo de aplicacion no ve el turno; el trigger frena el INSERT."""
    turno = crear_turno(mig_session, prof, "10:00")
    original = BloqueoRepository.turnos_activos_en_rango
    llamadas = {"n": 0}

    def ciego_la_primera_vez(self, *args, **kwargs):
        llamadas["n"] += 1
        return [] if llamadas["n"] == 1 else original(self, *args, **kwargs)

    monkeypatch.setattr(BloqueoRepository, "turnos_activos_en_rango", ciego_la_primera_vez)
    bitacora: list[str] = []

    with pytest.raises(BloqueoConTurnosError) as exc:
        _crear(factoria_espia(mig_engine, bitacora), _datos(prof))

    assert [t.id for t in exc.value.turnos] == [turno.id]
    assert bitacora == ["enter", "rollback", "close", "enter", "commit", "close"]
    assert cuenta(mig_session, Bloqueo) == 0


def test_otro_sqlstate_se_propaga_sin_enmascarar_como_409(uow_factory, mig_session, prof, monkeypatch):
    class _Orig(Exception):
        sqlstate = "23505"

    def falla(self, *args, **kwargs):
        raise IntegrityError("INSERT", {}, _Orig("duplicado sintetico"))

    monkeypatch.setattr(BloqueoRepository, "turnos_activos_en_rango", falla)

    with pytest.raises(IntegrityError):
        _crear(uow_factory, _datos(prof))
    assert cuenta(mig_session, Bloqueo) == 0


def test_bloqueos_superpuestos_entre_si_se_aceptan(uow_factory, mig_session, prof):
    _crear(uow_factory, _datos(prof, "09:00", "13:00"))
    _crear(uow_factory, _datos(prof, "12:00", "18:00"))

    assert cuenta(mig_session, Bloqueo) == 2


# --- 4.3 dar_de_baja_bloqueo -------------------------------------------------------------


def _baja(uow_factory, bloqueo_id, ahora=AHORA) -> BloqueoDTO:
    return dar_de_baja_bloqueo(uow_factory, bloqueo_id, ahora=ahora)


def test_baja_logica_libera_disponibilidad(uow_factory, mig_session, prof):
    dto = _crear(uow_factory, _datos(prof))
    ahora_baja = AHORA + timedelta(hours=1)

    baja = _baja(uow_factory, dto.id, ahora=ahora_baja)

    assert baja.id == dto.id
    (fila,) = _filas(mig_session)  # la fila sigue existiendo
    assert fila.is_active is False and fila.deleted_at == ahora_baja
    # ya no ocupa agenda: un turno nuevo en el rango entra sin trigger
    crear_turno(mig_session, prof, "10:00")
    assert BloqueoRepository(mig_session).ocupados_en_rango(
        prof.id, inicio("00:00"), inicio("23:59")
    ) == []


def test_baja_de_inexistente_404(uow_factory, mig_session):
    with pytest.raises(BloqueoNoEncontradoError):
        _baja(uow_factory, uuid.uuid4())


def test_baja_de_ya_inactivo_404_y_no_pisa_deleted_at(uow_factory, mig_session, prof):
    dto = _crear(uow_factory, _datos(prof))
    primera = AHORA + timedelta(hours=1)
    _baja(uow_factory, dto.id, ahora=primera)

    with pytest.raises(BloqueoNoEncontradoError):
        _baja(uow_factory, dto.id, ahora=primera + timedelta(days=1))

    assert _filas(mig_session)[0].deleted_at == primera


def test_baja_tras_error_hace_rollback_sin_cambios(uow_factory, mig_session, prof):
    dto = _crear(uow_factory, _datos(prof))
    with pytest.raises(BloqueoNoEncontradoError):
        _baja(uow_factory, uuid.uuid4())
    assert _filas(mig_session)[0].is_active is True and dto.id == _filas(mig_session)[0].id
