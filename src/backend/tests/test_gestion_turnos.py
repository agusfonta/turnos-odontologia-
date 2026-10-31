"""C-05 5.x: casos de uso de gestion de secretaria sobre la UoW (PG real)."""

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.application import gestion_turnos
from app.application.gestion_turnos import alta_manual_turno
from app.core.exceptions import (
    HuecoOcupadoError,
    InicioInvalidoError,
    ProfesionalNoEncontradoError,
    TratamientoNoEncontradoError,
)
from app.domain.schemas import TurnoManualCreate
from app.infrastructure.models import (
    AuditoriaTurno,
    Bloqueo,
    Paciente,
    Profesional,
    Tratamiento,
    Turno,
    TurnoOrigen,
)
from app.infrastructure.unit_of_work import UnitOfWork
from tests.support_gestion import (
    AHORA,
    LUNES,
    auditorias,
    crear_profesional,
    crear_secretaria,
    crear_turno,
    cuenta,
    inicio,
)

TZ = ZoneInfo("America/Argentina/Buenos_Aires")


@pytest.fixture
def uow_factory(mig_engine: sa.Engine):
    return lambda: UnitOfWork(session_factory=lambda: Session(mig_engine))


@pytest.fixture
def prof(mig_session: Session) -> Profesional:
    return crear_profesional(mig_session)


@pytest.fixture
def sec(mig_session: Session):
    return crear_secretaria(mig_session)


def _datos(prof: Profesional, hhmm: str = "10:00", **extra) -> TurnoManualCreate:
    base = {
        "profesional_id": prof.id,
        "inicio": inicio(hhmm),
        "paciente_nombre": "Paciente Manual",
        "paciente_telefono": "+5491100000001",
    }
    return TurnoManualCreate(**{**base, **extra})


def _alta(uow_factory, datos, sec, ahora=AHORA):
    return alta_manual_turno(uow_factory, datos, staff_id=sec.id, ahora=ahora, tz=TZ)


# --- 5.1 alta manual -----------------------------------------------------------------


def test_alta_manual_crea_paciente_turno_y_auditoria(uow_factory, mig_session, prof, sec):
    dto = _alta(uow_factory, _datos(prof), sec)

    assert not isinstance(dto, Turno)
    mig_session.expire_all()
    turno = mig_session.get(Turno, dto.id)
    paciente = mig_session.get(Paciente, dto.paciente_id)
    assert (turno.estado.value, turno.origen, turno.created_by) == (
        "reservado", TurnoOrigen.SECRETARIA, sec.id
    )
    assert (turno.inicio, turno.fin - turno.inicio) == (inicio("10:00"), timedelta(minutes=30))
    assert (paciente.nombre, paciente.telefono) == ("Paciente Manual", "+5491100000001")
    assert (dto.origen, dto.sobreturno, dto.token_publico) == ("secretaria", False, turno.token_publico)
    (aud,) = auditorias(mig_session, dto.id)
    assert (aud.accion, aud.actor_tipo.value, aud.actor_user_id) == ("crear", "secretaria", sec.id)
    assert aud.detalle == {
        "origen": "secretaria", "sobreturno": False, "paciente_reutilizado": False
    }


def test_alta_manual_usa_la_duracion_del_tratamiento(uow_factory, mig_session, prof, sec):
    trat = Tratamiento(nombre="Limpieza Sintetica", duracion_min=60)
    mig_session.add(trat)
    mig_session.commit()

    dto = _alta(uow_factory, _datos(prof, tratamiento_id=trat.id), sec)

    assert dto.fin - dto.inicio == timedelta(minutes=60) and dto.tratamiento_id == trat.id


def test_alta_manual_reutiliza_paciente_por_telefono(uow_factory, mig_session, prof, sec):
    previo = Paciente(nombre="Nombre Original", telefono="+5491100000001")
    mig_session.add(previo)
    mig_session.commit()

    dto = _alta(uow_factory, _datos(prof, paciente_nombre="Otro Nombre"), sec)

    assert dto.paciente_id == previo.id
    assert cuenta(mig_session, Paciente) == 1
    mig_session.refresh(previo)
    assert previo.nombre == "Nombre Original"
    assert auditorias(mig_session, dto.id)[0].detalle["paciente_reutilizado"] is True


def test_alta_manual_telefono_distinto_crea_otro_paciente(uow_factory, mig_session, prof, sec):
    previo = Paciente(nombre="Previo", telefono="+5491100000009")
    mig_session.add(previo)
    mig_session.commit()

    dto = _alta(uow_factory, _datos(prof), sec)

    assert dto.paciente_id != previo.id and cuenta(mig_session, Paciente) == 2


def test_hueco_ocupado_sin_marca_409_sin_residuos(uow_factory, mig_session, prof, sec):
    crear_turno(mig_session, prof, "10:00")
    antes = (cuenta(mig_session, Paciente), cuenta(mig_session, Turno), cuenta(mig_session, AuditoriaTurno))

    with pytest.raises(HuecoOcupadoError) as exc:
        _alta(uow_factory, _datos(prof, "10:00"), sec)

    assert exc.value.huecos and "10:00" not in {h["inicio"][11:16] for h in exc.value.huecos}
    assert (cuenta(mig_session, Paciente), cuenta(mig_session, Turno), cuenta(mig_session, AuditoriaTurno)) == antes


def test_sobreturno_coexiste_con_el_turno_ocupado(uow_factory, mig_session, prof, sec):
    existente = crear_turno(mig_session, prof, "10:00")

    dto = _alta(uow_factory, _datos(prof, "10:00", sobreturno=True), sec)

    assert dto.sobreturno is True and dto.id != existente.id
    mig_session.expire_all()
    assert mig_session.get(Turno, dto.id).sobreturno is True
    assert cuenta(mig_session, Turno) == 2
    assert auditorias(mig_session, dto.id)[0].detalle["sobreturno"] is True


def test_sobreturno_dentro_de_un_bloqueo_409(uow_factory, mig_session, prof, sec):
    mig_session.add(
        Bloqueo(
            profesional_id=prof.id, desde=inicio("09:00"), hasta=inicio("12:00"), motivo="Congreso"
        )
    )
    mig_session.commit()

    with pytest.raises(HuecoOcupadoError):
        _alta(uow_factory, _datos(prof, "10:00", sobreturno=True), sec)

    assert cuenta(mig_session, Turno) == 0 and cuenta(mig_session, Paciente) == 0


def test_sobreturno_fuera_de_grilla_es_inicio_invalido(uow_factory, mig_session, prof, sec):
    crear_turno(mig_session, prof, "10:00")
    with pytest.raises(InicioInvalidoError):
        _alta(uow_factory, _datos(prof, "10:10", sobreturno=True), sec)


def test_profesional_inexistente_404_y_tratamiento_inexistente_404(uow_factory, prof, sec):
    ajeno = Profesional(id=uuid.uuid4(), nombre="X", matricula="Y")
    with pytest.raises(ProfesionalNoEncontradoError):
        _alta(uow_factory, _datos(ajeno), sec)
    with pytest.raises(TratamientoNoEncontradoError):
        _alta(uow_factory, _datos(prof, tratamiento_id=9999), sec)


@pytest.mark.parametrize("hhmm", ["10:10", "08:30", "17:45"])
def test_inicio_invalido_422_sin_residuos(uow_factory, mig_session, prof, sec, hhmm):
    with pytest.raises(InicioInvalidoError):
        _alta(uow_factory, _datos(prof, hhmm), sec)
    assert cuenta(mig_session, Paciente) == 0 and cuenta(mig_session, Turno) == 0


def test_inicio_en_el_pasado_422(uow_factory, mig_session, prof, sec):
    despues = datetime(2030, 3, 5, tzinfo=timezone.utc)
    with pytest.raises(InicioInvalidoError):
        _alta(uow_factory, _datos(prof), sec, ahora=despues)


def test_insercion_sin_fila_409_sin_paciente_nuevo(uow_factory, mig_session, prof, sec, monkeypatch):
    """`hay_ocupacion` ciego: decide la constraint (ON CONFLICT -> None) y se revierte todo."""
    crear_turno(mig_session, prof, "10:00")
    monkeypatch.setattr("app.application.reservas.hay_ocupacion", lambda *a, **k: False)
    pacientes = cuenta(mig_session, Paciente)

    with pytest.raises(HuecoOcupadoError):
        _alta(uow_factory, _datos(prof, "10:00"), sec)

    assert cuenta(mig_session, Paciente) == pacientes
    assert cuenta(mig_session, Turno) == 1


# --- 5.2 cancelar --------------------------------------------------------------------

from app.application.disponibilidad import consultar_disponibilidad  # noqa: E402
from app.application.gestion_turnos import Actor, cancelar_turno  # noqa: E402
from app.core.exceptions import (  # noqa: E402
    AnticipacionInsuficienteError,
    TransicionNoPermitidaError,
    TurnoNoEncontradoError,
)
from app.domain.turno_estados import EstadoTurno  # noqa: E402
from app.infrastructure.models import AuditoriaActor  # noqa: E402

CERCA = datetime(2030, 3, 4, 11, 0, tzinfo=timezone.utc)  # el turno de las 10:00 (13:00 UTC) empieza en 2 h
TARDE = datetime(2030, 3, 4, 14, 0, tzinfo=timezone.utc)  # el turno de las 10:00 ya empezo


def _secretaria(sec) -> Actor:
    return Actor(AuditoriaActor.SECRETARIA, sec.id)


PACIENTE = Actor(AuditoriaActor.PACIENTE, None)


def _estado(session: Session, turno_id) -> EstadoTurno:
    session.expire_all()
    return session.get(Turno, turno_id).estado


def test_cancelar_turno_reservado_por_secretaria(uow_factory, mig_session, prof, sec):
    turno = crear_turno(mig_session, prof, "10:00")

    dto = cancelar_turno(uow_factory, turno.id, actor=_secretaria(sec), ahora=AHORA)

    assert dto.estado is EstadoTurno.CANCELADO and dto.id == turno.id
    assert _estado(mig_session, turno.id) is EstadoTurno.CANCELADO  # la fila se conserva
    (aud,) = auditorias(mig_session, turno.id, "cancelar")
    assert (aud.actor_tipo.value, aud.actor_user_id) == ("secretaria", sec.id)
    assert aud.detalle == {"estado_anterior": "reservado", "exento_anticipacion": False}


def test_cancelar_turno_confirmado(uow_factory, mig_session, prof, sec):
    turno = crear_turno(mig_session, prof, "10:00", estado=EstadoTurno.CONFIRMADO)

    cancelar_turno(uow_factory, turno.id, actor=_secretaria(sec), ahora=AHORA)

    assert _estado(mig_session, turno.id) is EstadoTurno.CANCELADO
    assert auditorias(mig_session, turno.id, "cancelar")[0].detalle["estado_anterior"] == "confirmado"


@pytest.mark.parametrize(
    "terminal", [EstadoTurno.CANCELADO, EstadoTurno.ATENDIDO, EstadoTurno.AUSENTE]
)
def test_cancelar_terminal_422_sin_auditoria(uow_factory, mig_session, prof, sec, terminal):
    turno = crear_turno(mig_session, prof, "10:00", estado=terminal)

    with pytest.raises(TransicionNoPermitidaError) as exc:
        cancelar_turno(uow_factory, turno.id, actor=_secretaria(sec), ahora=AHORA)

    assert exc.value.estado_actual == terminal.value
    assert auditorias(mig_session, turno.id) == []
    assert _estado(mig_session, turno.id) is terminal


def test_cancelar_inexistente_404(uow_factory, sec):
    with pytest.raises(TurnoNoEncontradoError):
        cancelar_turno(uow_factory, uuid.uuid4(), actor=_secretaria(sec), ahora=AHORA)


def test_secretaria_dentro_de_la_ventana_cancela_y_audita_exencion(uow_factory, mig_session, prof, sec):
    turno = crear_turno(mig_session, prof, "10:00")

    cancelar_turno(uow_factory, turno.id, actor=_secretaria(sec), ahora=CERCA)

    assert _estado(mig_session, turno.id) is EstadoTurno.CANCELADO
    assert auditorias(mig_session, turno.id, "cancelar")[0].detalle["exento_anticipacion"] is True


def test_cancelar_turno_ya_iniciado_422_sin_cambios(uow_factory, mig_session, prof, sec):
    turno = crear_turno(mig_session, prof, "10:00")

    with pytest.raises(AnticipacionInsuficienteError):
        cancelar_turno(uow_factory, turno.id, actor=_secretaria(sec), ahora=TARDE)

    assert _estado(mig_session, turno.id) is EstadoTurno.RESERVADO
    assert auditorias(mig_session, turno.id) == []


def test_paciente_dentro_de_la_ventana_no_cancela(uow_factory, mig_session, prof):
    turno = crear_turno(mig_session, prof, "10:00")

    with pytest.raises(AnticipacionInsuficienteError) as exc:
        cancelar_turno(uow_factory, turno.id, actor=PACIENTE, ahora=CERCA)

    assert exc.value.min_horas == 24
    assert _estado(mig_session, turno.id) is EstadoTurno.RESERVADO
    assert auditorias(mig_session, turno.id) == []


def test_paciente_fuera_de_la_ventana_cancela_con_actor_paciente(uow_factory, mig_session, prof):
    turno = crear_turno(mig_session, prof, "10:00")

    cancelar_turno(uow_factory, turno.id, actor=PACIENTE, ahora=AHORA)

    (aud,) = auditorias(mig_session, turno.id, "cancelar")
    assert (aud.actor_tipo.value, aud.actor_user_id) == ("paciente", None)


def test_paciente_respeta_cancel_min_hours_configurable(uow_factory, mig_session, prof, monkeypatch):
    from app.core.settings import get_settings

    monkeypatch.setenv("CANCEL_MIN_HOURS", "3")
    get_settings.cache_clear()
    try:
        turno = crear_turno(mig_session, prof, "10:00")  # 13:00 UTC
        ahora = datetime(2030, 3, 4, 9, 0, tzinfo=timezone.utc)  # faltan 4 h
        cancelar_turno(uow_factory, turno.id, actor=PACIENTE, ahora=ahora)
        assert _estado(mig_session, turno.id) is EstadoTurno.CANCELADO
    finally:
        get_settings.cache_clear()


def test_el_hueco_liberado_vuelve_a_la_disponibilidad(uow_factory, mig_session, prof, sec):
    turno = crear_turno(mig_session, prof, "10:00")
    dia = inicio("10:00").date()

    def _horas():
        huecos = consultar_disponibilidad(
            mig_session, profesional_id=prof.id, desde=dia, hasta=dia,
            tratamiento_id=None, ahora=AHORA, tz=TZ, max_dias=7,
        )
        return {h.inicio.astimezone(TZ).strftime("%H:%M") for h in huecos}

    assert "10:00" not in _horas()
    cancelar_turno(uow_factory, turno.id, actor=_secretaria(sec), ahora=AHORA)
    mig_session.expire_all()
    assert "10:00" in _horas()


# --- 5.3 reprogramar -----------------------------------------------------------------

from sqlalchemy.exc import IntegrityError, OperationalError  # noqa: E402

from app.application.gestion_turnos import reprogramar_turno  # noqa: E402
from app.domain.schemas import TurnoReprogramar  # noqa: E402
from tests.support import factoria_espia  # noqa: E402


def _reprog(uow_factory, turno, hhmm, actor, *, ahora=AHORA, **extra):
    return reprogramar_turno(
        uow_factory,
        turno.id,
        TurnoReprogramar(inicio=inicio(hhmm), **extra),
        actor=actor,
        ahora=ahora,
        tz=TZ,
    )


def _fila(session: Session, turno_id) -> Turno:
    session.expire_all()
    return session.get(Turno, turno_id)


def test_reprogramar_a_hueco_libre(uow_factory, mig_session, prof, sec):
    turno = crear_turno(mig_session, prof, "10:00")

    dto = _reprog(uow_factory, turno, "14:00", _secretaria(sec))

    assert (dto.inicio, dto.fin) == (inicio("14:00"), inicio("14:30"))  # misma duracion
    fila = _fila(mig_session, turno.id)
    assert (fila.inicio, fila.fin, fila.estado) == (inicio("14:00"), inicio("14:30"), EstadoTurno.RESERVADO)
    assert (fila.profesional_id, fila.paciente_id) == (turno.profesional_id, turno.paciente_id)
    (aud,) = auditorias(mig_session, turno.id, "reprogramar")
    assert (aud.actor_tipo.value, aud.actor_user_id) == ("secretaria", sec.id)
    assert aud.detalle == {
        "inicio_anterior": "2030-03-04T13:00:00+00:00",
        "fin_anterior": "2030-03-04T13:30:00+00:00",
        "inicio_nuevo": "2030-03-04T17:00:00+00:00",
        "fin_nuevo": "2030-03-04T17:30:00+00:00",
        "estado_anterior": "reservado",
        "estado_nuevo": "reservado",
        "sobreturno": False,
        "exento_anticipacion": False,
    }
    # el horario anterior queda libre para otro turno
    otro = crear_turno(mig_session, prof, "10:00", telefono="+5491100000098")
    assert otro.id != turno.id


def test_reprogramar_pisando_su_propio_horario_es_ok(uow_factory, mig_session, prof, sec):
    turno = crear_turno(mig_session, prof, "10:00", minutos=60)

    dto = _reprog(uow_factory, turno, "10:30", _secretaria(sec))

    assert (dto.inicio, dto.fin) == (inicio("10:30"), inicio("11:30"))


def test_reprogramar_a_hueco_ocupado_409_y_conserva_horario(uow_factory, mig_session, prof, sec):
    turno = crear_turno(mig_session, prof, "10:00")
    crear_turno(mig_session, prof, "14:00", telefono="+5491100000097")

    with pytest.raises(HuecoOcupadoError) as exc:
        _reprog(uow_factory, turno, "14:00", _secretaria(sec))

    assert exc.value.huecos
    fila = _fila(mig_session, turno.id)
    assert (fila.inicio, fila.estado) == (inicio("10:00"), EstadoTurno.RESERVADO)
    assert auditorias(mig_session, turno.id) == []


def test_reprogramar_sobre_un_bloqueo_409(uow_factory, mig_session, prof, sec):
    turno = crear_turno(mig_session, prof, "10:00")
    mig_session.add(
        Bloqueo(profesional_id=prof.id, desde=inicio("14:00"), hasta=inicio("15:00"), motivo="Cursos")
    )
    mig_session.commit()

    with pytest.raises(HuecoOcupadoError):
        _reprog(uow_factory, turno, "14:00", _secretaria(sec))
    with pytest.raises(HuecoOcupadoError):  # el sobreturno tampoco atraviesa un bloqueo
        _reprog(uow_factory, turno, "14:00", _secretaria(sec), sobreturno=True)

    assert _fila(mig_session, turno.id).inicio == inicio("10:00")


def test_reprogramar_confirmado_vuelve_a_reservado(uow_factory, mig_session, prof, sec):
    turno = crear_turno(mig_session, prof, "10:00", estado=EstadoTurno.CONFIRMADO)

    dto = _reprog(uow_factory, turno, "14:00", _secretaria(sec))

    assert dto.estado is EstadoTurno.RESERVADO
    detalle = auditorias(mig_session, turno.id, "reprogramar")[0].detalle
    assert (detalle["estado_anterior"], detalle["estado_nuevo"]) == ("confirmado", "reservado")


@pytest.mark.parametrize(
    "terminal", [EstadoTurno.CANCELADO, EstadoTurno.ATENDIDO, EstadoTurno.AUSENTE]
)
def test_reprogramar_terminal_422(uow_factory, mig_session, prof, sec, terminal):
    turno = crear_turno(mig_session, prof, "10:00", estado=terminal)

    with pytest.raises(TransicionNoPermitidaError):
        _reprog(uow_factory, turno, "14:00", _secretaria(sec))

    assert auditorias(mig_session, turno.id) == []
    assert _fila(mig_session, turno.id).inicio == inicio("10:00")


def test_reprogramar_inexistente_404(uow_factory, sec):
    with pytest.raises(TurnoNoEncontradoError):
        reprogramar_turno(
            uow_factory,
            uuid.uuid4(),
            TurnoReprogramar(inicio=inicio("14:00")),
            actor=_secretaria(sec),
            ahora=AHORA,
            tz=TZ,
        )


@pytest.mark.parametrize("hhmm", ["14:10", "08:00", "17:45"])
def test_reprogramar_inicio_invalido_422(uow_factory, mig_session, prof, sec, hhmm):
    turno = crear_turno(mig_session, prof, "10:00")

    with pytest.raises(InicioInvalidoError):
        _reprog(uow_factory, turno, hhmm, _secretaria(sec))

    assert _fila(mig_session, turno.id).inicio == inicio("10:00")


def test_reprogramar_a_un_horario_pasado_422(uow_factory, mig_session, prof, sec):
    turno = crear_turno(mig_session, prof, "10:00", dia="2030-03-11")  # lunes siguiente
    ahora = datetime(2030, 3, 4, 20, 0, tzinfo=timezone.utc)  # 17:00 local del 04/03

    with pytest.raises(InicioInvalidoError):  # 14:00 del 04/03 ya paso
        _reprog(uow_factory, turno, "14:00", _secretaria(sec), ahora=ahora)

    assert _fila(mig_session, turno.id).inicio == inicio("10:00", "2030-03-11")


def test_reprogramar_turno_ya_iniciado_422_anticipacion(uow_factory, mig_session, prof, sec):
    turno = crear_turno(mig_session, prof, "10:00")

    with pytest.raises(AnticipacionInsuficienteError):  # el horario que se libera ya empezo (D7)
        _reprog(uow_factory, turno, "14:00", _secretaria(sec), ahora=TARDE)

    assert _fila(mig_session, turno.id).inicio == inicio("10:00")


def test_sobreturno_sobre_turno_ocupado_ok_y_persistido(uow_factory, mig_session, prof, sec):
    turno = crear_turno(mig_session, prof, "10:00")
    crear_turno(mig_session, prof, "14:00", telefono="+5491100000097")

    dto = _reprog(uow_factory, turno, "14:00", _secretaria(sec), sobreturno=True)

    assert dto.sobreturno is True
    assert _fila(mig_session, turno.id).sobreturno is True
    assert auditorias(mig_session, turno.id, "reprogramar")[0].detalle["sobreturno"] is True


def test_el_valor_de_sobreturno_del_body_reemplaza_al_del_turno(uow_factory, mig_session, prof, sec):
    turno = crear_turno(mig_session, prof, "10:00", sobreturno=True)

    dto = _reprog(uow_factory, turno, "14:00", _secretaria(sec))  # hueco libre, sin marca

    assert dto.sobreturno is False and _fila(mig_session, turno.id).sobreturno is False


def test_sobreturno_con_actor_paciente_es_value_error(uow_factory, mig_session, prof):
    turno = crear_turno(mig_session, prof, "10:00")

    with pytest.raises(ValueError):
        _reprog(uow_factory, turno, "14:00", PACIENTE, sobreturno=True)

    assert _fila(mig_session, turno.id).inicio == inicio("10:00")


def test_secretaria_dentro_de_la_ventana_reprograma_y_audita_exencion(uow_factory, mig_session, prof, sec):
    turno = crear_turno(mig_session, prof, "10:00")

    _reprog(uow_factory, turno, "14:00", _secretaria(sec), ahora=CERCA)

    assert auditorias(mig_session, turno.id, "reprogramar")[0].detalle["exento_anticipacion"] is True


def test_paciente_dentro_de_la_ventana_no_reprograma(uow_factory, mig_session, prof):
    turno = crear_turno(mig_session, prof, "10:00")

    with pytest.raises(AnticipacionInsuficienteError):
        _reprog(uow_factory, turno, "14:00", PACIENTE, ahora=CERCA)

    assert _fila(mig_session, turno.id).inicio == inicio("10:00")
    assert auditorias(mig_session, turno.id) == []


def test_reprogramar_via_constraint_23p01_es_409(uow_factory, mig_session, prof, sec, monkeypatch):
    """`hay_ocupacion` ciego: el UPDATE choca con la exclusion y se traduce a 409."""
    turno = crear_turno(mig_session, prof, "10:00")
    crear_turno(mig_session, prof, "14:00", telefono="+5491100000097")
    monkeypatch.setattr("app.application.reservas.hay_ocupacion", lambda *a, **k: False)

    with pytest.raises(HuecoOcupadoError) as exc:
        _reprog(uow_factory, turno, "14:00", _secretaria(sec))

    assert exc.value.huecos
    assert _fila(mig_session, turno.id).inicio == inicio("10:00")
    assert auditorias(mig_session, turno.id) == []


class _OrigConSqlstate(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def _factoria_con_flush_que_falla(engine, error: BaseException):
    """UoW de test cuyo primer `flush` lanza `error` (simula un fallo de la base al UPDATE)."""
    from tests.support import UowEspia

    pendiente = [error]

    class Uow(UowEspia):
        def __enter__(self):
            session = super().__enter__()
            if pendiente:
                err = pendiente.pop()
                original = session.flush

                def flush(*a, **k):
                    if session.dirty or session.new:  # el flush del UPDATE, no un autoflush vacio
                        session.flush = original  # type: ignore[method-assign]
                        raise err
                    return original(*a, **k)

                session.flush = flush  # type: ignore[method-assign]
            return session

    return lambda: Uow([], lambda: Session(engine))


def test_deadlock_40p01_es_409(mig_engine, mig_session, prof, sec):
    turno = crear_turno(mig_session, prof, "10:00")
    error = OperationalError("UPDATE turnos", {}, _OrigConSqlstate("40P01"))

    with pytest.raises(HuecoOcupadoError):
        _reprog(_factoria_con_flush_que_falla(mig_engine, error), turno, "14:00", _secretaria(sec))

    assert _fila(mig_session, turno.id).inicio == inicio("10:00")


def test_otro_sqlstate_se_propaga(mig_engine, mig_session, prof, sec):
    turno = crear_turno(mig_session, prof, "10:00")
    error = IntegrityError("UPDATE turnos", {}, _OrigConSqlstate("23505"))

    with pytest.raises(IntegrityError):
        _reprog(_factoria_con_flush_que_falla(mig_engine, error), turno, "14:00", _secretaria(sec))

    assert _fila(mig_session, turno.id).inicio == inicio("10:00")


def test_la_uow_de_escritura_cierra_antes_de_abrir_la_de_lectura_del_409(
    mig_engine, mig_session, prof, sec
):
    turno = crear_turno(mig_session, prof, "10:00")
    crear_turno(mig_session, prof, "14:00", telefono="+5491100000097")
    bitacora: list[str] = []

    with pytest.raises(HuecoOcupadoError):
        _reprog(factoria_espia(mig_engine, bitacora), turno, "14:00", _secretaria(sec))

    assert bitacora == ["enter", "rollback", "close", "enter", "commit", "close"]


# --- C-07 3.1 confirmar --------------------------------------------------------------

from app.application.gestion_turnos import confirmar_turno  # noqa: E402


def test_confirmar_reservado_pasa_a_confirmado_y_audita(uow_factory, mig_session, prof):
    turno = crear_turno(mig_session, prof, "10:00")

    dto = confirmar_turno(uow_factory, turno.id, actor=PACIENTE, ahora=AHORA)

    assert dto.estado is EstadoTurno.CONFIRMADO and dto.id == turno.id
    assert _estado(mig_session, turno.id) is EstadoTurno.CONFIRMADO
    (aud,) = auditorias(mig_session, turno.id, "confirmar")
    assert (aud.actor_tipo.value, aud.actor_user_id) == ("paciente", None)
    assert aud.detalle == {"estado_anterior": "reservado"}


def test_confirmar_con_actor_secretaria_audita_el_usuario(uow_factory, mig_session, prof, sec):
    turno = crear_turno(mig_session, prof, "10:00")

    confirmar_turno(uow_factory, turno.id, actor=_secretaria(sec), ahora=AHORA)

    (aud,) = auditorias(mig_session, turno.id, "confirmar")
    assert (aud.actor_tipo.value, aud.actor_user_id) == ("secretaria", sec.id)


def test_reconfirmar_es_noop_idempotente_sin_auditoria(uow_factory, mig_session, prof):
    turno = crear_turno(mig_session, prof, "10:00", estado=EstadoTurno.CONFIRMADO)

    dto = confirmar_turno(uow_factory, turno.id, actor=PACIENTE, ahora=AHORA)

    assert dto.estado is EstadoTurno.CONFIRMADO and dto.id == turno.id
    assert auditorias(mig_session, turno.id) == []
    assert _estado(mig_session, turno.id) is EstadoTurno.CONFIRMADO


def test_reconfirmar_un_confirmado_ya_pasado_sigue_siendo_noop(uow_factory, mig_session, prof):
    turno = crear_turno(mig_session, prof, "10:00", estado=EstadoTurno.CONFIRMADO)

    dto = confirmar_turno(uow_factory, turno.id, actor=PACIENTE, ahora=TARDE)

    assert dto.estado is EstadoTurno.CONFIRMADO
    assert auditorias(mig_session, turno.id) == []


@pytest.mark.parametrize(
    "terminal", [EstadoTurno.CANCELADO, EstadoTurno.ATENDIDO, EstadoTurno.AUSENTE]
)
def test_confirmar_terminal_422_sin_auditoria(uow_factory, mig_session, prof, terminal):
    turno = crear_turno(mig_session, prof, "10:00", estado=terminal)

    with pytest.raises(TransicionNoPermitidaError) as exc:
        confirmar_turno(uow_factory, turno.id, actor=PACIENTE, ahora=AHORA)

    assert exc.value.estado_actual == terminal.value
    assert auditorias(mig_session, turno.id) == []
    assert _estado(mig_session, turno.id) is terminal


def test_confirmar_cancelado_ya_pasado_responde_transicion_no_anticipacion(uow_factory, mig_session, prof):
    turno = crear_turno(mig_session, prof, "10:00", estado=EstadoTurno.CANCELADO)

    with pytest.raises(TransicionNoPermitidaError):
        confirmar_turno(uow_factory, turno.id, actor=PACIENTE, ahora=TARDE)


@pytest.mark.parametrize("ahora", [TARDE, datetime(2030, 3, 4, 13, 0, tzinfo=timezone.utc)])
def test_confirmar_turno_ya_iniciado_422_sin_cambios(uow_factory, mig_session, prof, ahora):
    turno = crear_turno(mig_session, prof, "10:00")  # empieza 13:00 UTC; `ahora == inicio` cuenta

    with pytest.raises(AnticipacionInsuficienteError) as exc:
        confirmar_turno(uow_factory, turno.id, actor=PACIENTE, ahora=ahora)

    assert exc.value.min_horas == 0
    assert _estado(mig_session, turno.id) is EstadoTurno.RESERVADO
    assert auditorias(mig_session, turno.id) == []


def test_confirmar_dentro_de_la_ventana_de_cancelacion_se_acepta(uow_factory, mig_session, prof):
    turno = crear_turno(mig_session, prof, "10:00")

    confirmar_turno(uow_factory, turno.id, actor=PACIENTE, ahora=CERCA)  # faltan 2 h (< 24 h)

    assert _estado(mig_session, turno.id) is EstadoTurno.CONFIRMADO


def test_confirmar_inexistente_404(uow_factory):
    with pytest.raises(TurnoNoEncontradoError):
        confirmar_turno(uow_factory, uuid.uuid4(), actor=PACIENTE, ahora=AHORA)


def test_confirmar_no_cambia_el_token_publico(uow_factory, mig_session, prof):
    turno = crear_turno(mig_session, prof, "10:00")
    token = turno.token_publico

    confirmar_turno(uow_factory, turno.id, actor=PACIENTE, ahora=AHORA)

    mig_session.expire_all()
    assert mig_session.get(Turno, turno.id).token_publico == token
