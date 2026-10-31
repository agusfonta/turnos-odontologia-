"""C-07 5.x: capa de token (resolver, consultar y operar por token) sobre la UoW (PG real)."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.application import autogestion
from app.application.autogestion import (
    cancelar_por_token,
    confirmar_por_token,
    consultar_por_token,
    reprogramar_por_token,
    resolver_token,
)
from app.core.exceptions import (
    AnticipacionInsuficienteError,
    HuecoOcupadoError,
    TurnoNoEncontradoError,
)
from app.core.settings import get_settings
from app.domain.schemas import TurnoReprogramarPublico
from app.domain.turno_estados import EstadoTurno
from app.infrastructure.models import AuditoriaTurno, Tratamiento, Turno
from app.infrastructure.unit_of_work import UnitOfWork
from tests.support import factoria_espia
from tests.support_gestion import (
    AHORA,
    auditorias,
    crear_profesional,
    crear_turno,
    cuenta,
    inicio,
)

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
CERCA = datetime(2030, 3, 4, 11, 0, tzinfo=timezone.utc)  # el turno de las 10:00 empieza en 2 h


@pytest.fixture
def uow_factory(mig_engine: sa.Engine):
    return lambda: UnitOfWork(session_factory=lambda: Session(mig_engine))


@pytest.fixture
def prof(mig_session: Session):
    return crear_profesional(mig_session)


def _estado(session: Session, turno_id) -> EstadoTurno:
    session.expire_all()
    return session.get(Turno, turno_id).estado


# --- 5.1 resolver_token ---------------------------------------------------------------


def test_resolver_token_valido_devuelve_id(uow_factory, mig_session, prof):
    turno = crear_turno(mig_session, prof)

    assert resolver_token(uow_factory, turno.token_publico) == turno.id


def test_resolver_token_con_dos_turnos_devuelve_el_correcto(uow_factory, mig_session, prof):
    uno = crear_turno(mig_session, prof, "10:00", telefono="+5491100000001")
    dos = crear_turno(mig_session, prof, "11:00", telefono="+5491100000002")

    assert resolver_token(uow_factory, dos.token_publico) == dos.id
    assert resolver_token(uow_factory, uno.token_publico) == uno.id


def test_resolver_token_inexistente_404(uow_factory, mig_session, prof):
    crear_turno(mig_session, prof)

    with pytest.raises(TurnoNoEncontradoError):
        resolver_token(uow_factory, "a" * 43)


@pytest.mark.parametrize(
    "malformado",
    ["con/barra", "con espacio", "100%", "con.punto", "a" * 65, "", "..", "a\nb"],
)
def test_resolver_token_malformado_404_sin_abrir_uow(mig_engine, malformado):
    bitacora: list[str] = []

    with pytest.raises(TurnoNoEncontradoError):
        resolver_token(factoria_espia(mig_engine, bitacora), malformado)

    assert bitacora == []


def test_resolver_token_acepta_borde_de_64_caracteres(uow_factory, mig_session, prof):
    turno = crear_turno(mig_session, prof)
    token = "A-_" + "b" * 61
    mig_session.execute(sa.update(Turno).where(Turno.id == turno.id).values(token_publico=token))
    mig_session.commit()

    assert resolver_token(uow_factory, token) == turno.id


# --- 5.2 consultar_por_token ----------------------------------------------------------


def test_consultar_por_token_devuelve_detalle_publico(uow_factory, mig_session, prof):
    trat = Tratamiento(nombre="Limpieza Sintetica", duracion_min=30)
    mig_session.add(trat)
    mig_session.flush()
    turno = crear_turno(mig_session, prof, "10:00")
    mig_session.execute(sa.update(Turno).where(Turno.id == turno.id).values(tratamiento_id=trat.id))
    mig_session.commit()

    dto = consultar_por_token(uow_factory, turno.token_publico)

    assert dto.inicio == inicio("10:00") and dto.fin == inicio("10:30")
    assert dto.estado is EstadoTurno.RESERVADO
    assert (dto.profesional_id, dto.profesional_nombre) == (prof.id, prof.nombre)
    assert (dto.tratamiento_id, dto.tratamiento_nombre) == (trat.id, "Limpieza Sintetica")
    assert dto.gestionable_hasta == inicio("10:00") - timedelta(hours=24)
    with pytest.raises(FrozenInstanceError):
        dto.estado = EstadoTurno.CANCELADO  # type: ignore[misc]


def test_consultar_gestionable_hasta_sigue_cancel_min_hours(uow_factory, mig_session, prof, monkeypatch):
    turno = crear_turno(mig_session, prof, "10:00")
    monkeypatch.setenv("CANCEL_MIN_HOURS", "3")
    get_settings.cache_clear()
    try:
        dto = consultar_por_token(uow_factory, turno.token_publico)
    finally:
        get_settings.cache_clear()

    assert dto.gestionable_hasta == inicio("10:00") - timedelta(hours=3)


def test_consultar_token_invalido_404(uow_factory):
    with pytest.raises(TurnoNoEncontradoError):
        consultar_por_token(uow_factory, "no-existe")
    with pytest.raises(TurnoNoEncontradoError):
        consultar_por_token(uow_factory, "mal/formado")


def test_consultar_turno_cancelado_se_devuelve_y_no_audita(uow_factory, mig_session, prof):
    turno = crear_turno(mig_session, prof, estado=EstadoTurno.CANCELADO)

    dto = consultar_por_token(uow_factory, turno.token_publico)

    assert dto.estado is EstadoTurno.CANCELADO
    assert cuenta(mig_session, AuditoriaTurno) == 0


# --- 5.3 operaciones por token --------------------------------------------------------


def test_cancelar_por_token_usa_actor_paciente(uow_factory, mig_session, prof):
    turno = crear_turno(mig_session, prof)

    dto = cancelar_por_token(uow_factory, turno.token_publico, ahora=AHORA)

    assert dto.id == turno.id and dto.estado is EstadoTurno.CANCELADO
    (aud,) = auditorias(mig_session, turno.id, "cancelar")
    assert (aud.actor_tipo.value, aud.actor_user_id) == ("paciente", None)


def test_cancelar_por_token_dentro_de_la_ventana_422_sin_cambios(uow_factory, mig_session, prof):
    turno = crear_turno(mig_session, prof)

    with pytest.raises(AnticipacionInsuficienteError) as exc:
        cancelar_por_token(uow_factory, turno.token_publico, ahora=CERCA)

    assert exc.value.min_horas == 24
    assert _estado(mig_session, turno.id) is EstadoTurno.RESERVADO
    assert auditorias(mig_session, turno.id) == []


def test_cancelar_por_token_en_el_borde_exacto_acepta_y_un_segundo_despues_no(
    uow_factory, mig_session, prof
):
    turno = crear_turno(mig_session, prof)
    borde = inicio("10:00") - timedelta(hours=get_settings().CANCEL_MIN_HOURS)

    cancelar_por_token(uow_factory, turno.token_publico, ahora=borde)
    assert _estado(mig_session, turno.id) is EstadoTurno.CANCELADO

    otro = crear_turno(mig_session, prof, "11:00", telefono="+5491100000002")
    pasado = inicio("11:00") - timedelta(hours=24) + timedelta(seconds=1)
    with pytest.raises(AnticipacionInsuficienteError):
        cancelar_por_token(uow_factory, otro.token_publico, ahora=pasado)


def test_confirmar_por_token_usa_actor_paciente(uow_factory, mig_session, prof):
    turno = crear_turno(mig_session, prof)

    dto = confirmar_por_token(uow_factory, turno.token_publico, ahora=AHORA)

    assert dto.estado is EstadoTurno.CONFIRMADO
    (aud,) = auditorias(mig_session, turno.id, "confirmar")
    assert (aud.actor_tipo.value, aud.actor_user_id) == ("paciente", None)


def test_reprogramar_por_token_a_hueco_libre(uow_factory, mig_session, prof):
    turno = crear_turno(mig_session, prof, "10:00", estado=EstadoTurno.CONFIRMADO)
    datos = TurnoReprogramarPublico(inicio=inicio("14:00"))

    dto = reprogramar_por_token(uow_factory, turno.token_publico, datos, ahora=AHORA, tz=TZ)

    assert dto.estado is EstadoTurno.RESERVADO  # confirmado vuelve a reservado
    assert (dto.inicio, dto.fin) == (inicio("14:00"), inicio("14:30"))
    mig_session.expire_all()
    fila = mig_session.get(Turno, turno.id)
    assert (fila.inicio, fila.sobreturno) == (inicio("14:00"), False)
    (aud,) = auditorias(mig_session, turno.id, "reprogramar")
    assert (aud.actor_tipo.value, aud.actor_user_id) == ("paciente", None)
    assert aud.detalle["sobreturno"] is False and aud.detalle["exento_anticipacion"] is False


def test_reprogramar_por_token_a_hueco_ocupado_409_con_huecos(uow_factory, mig_session, prof):
    turno = crear_turno(mig_session, prof, "10:00")
    crear_turno(mig_session, prof, "14:00", telefono="+5491100000002")
    datos = TurnoReprogramarPublico(inicio=inicio("14:00"))

    with pytest.raises(HuecoOcupadoError) as exc:
        reprogramar_por_token(uow_factory, turno.token_publico, datos, ahora=AHORA, tz=TZ)

    assert exc.value.huecos  # hay otros huecos ese dia
    assert all("T14:00" not in h["inicio"] for h in exc.value.huecos)
    mig_session.expire_all()
    fila = mig_session.get(Turno, turno.id)
    assert (fila.estado, fila.inicio) == (EstadoTurno.RESERVADO, inicio("10:00"))
    assert auditorias(mig_session, turno.id) == []


def test_reprogramar_por_token_fuera_de_plazo_422_sin_cambios(uow_factory, mig_session, prof):
    turno = crear_turno(mig_session, prof, "10:00")
    datos = TurnoReprogramarPublico(inicio=inicio("14:00"))

    with pytest.raises(AnticipacionInsuficienteError):
        reprogramar_por_token(uow_factory, turno.token_publico, datos, ahora=CERCA, tz=TZ)

    mig_session.expire_all()
    assert mig_session.get(Turno, turno.id).inicio == inicio("10:00")
    assert auditorias(mig_session, turno.id) == []


@pytest.mark.parametrize("operacion", ["cancelar", "confirmar", "reprogramar"])
@pytest.mark.parametrize("token", ["a" * 43, "mal/formado"])
def test_token_invalido_en_cada_operacion_404_sin_tocar_la_base(
    uow_factory, mig_session, prof, operacion, token
):
    turno = crear_turno(mig_session, prof)
    datos = TurnoReprogramarPublico(inicio=inicio("14:00"))
    llamadas = {
        "cancelar": lambda: cancelar_por_token(uow_factory, token, ahora=AHORA),
        "confirmar": lambda: confirmar_por_token(uow_factory, token, ahora=AHORA),
        "reprogramar": lambda: reprogramar_por_token(uow_factory, token, datos, ahora=AHORA, tz=TZ),
    }

    with pytest.raises(TurnoNoEncontradoError):
        llamadas[operacion]()

    assert _estado(mig_session, turno.id) is EstadoTurno.RESERVADO
    assert cuenta(mig_session, AuditoriaTurno) == 0


def test_ninguna_operacion_por_token_cambia_el_token_publico(uow_factory, mig_session, prof):
    t1 = crear_turno(mig_session, prof, "10:00", telefono="+5491100000001")
    t2 = crear_turno(mig_session, prof, "11:00", telefono="+5491100000002")
    t3 = crear_turno(mig_session, prof, "12:00", telefono="+5491100000003")
    tokens = {t.id: t.token_publico for t in (t1, t2, t3)}

    confirmar_por_token(uow_factory, t1.token_publico, ahora=AHORA)
    reprogramar_por_token(
        uow_factory,
        t2.token_publico,
        TurnoReprogramarPublico(inicio=inicio("15:00")),
        ahora=AHORA,
        tz=TZ,
    )
    cancelar_por_token(uow_factory, t3.token_publico, ahora=AHORA)

    mig_session.expire_all()
    assert {i: mig_session.get(Turno, i).token_publico for i in tokens} == tokens


def test_el_modulo_no_usa_commit_ni_async():
    import inspect

    fuente = inspect.getsource(autogestion)
    assert "async def" not in fuente
    assert ".commit(" not in fuente and ".rollback(" not in fuente
