"""C-04 2.4: repositorios de agenda (queries de intervalo, una por tabla) contra PG migrada."""

import uuid
from datetime import datetime, time, timedelta, timezone

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.domain.disponibilidad import Franja
from app.domain.turno_estados import EstadoTurno
from app.infrastructure.models import (
    Bloqueo,
    HorarioProfesional,
    Paciente,
    Profesional,
    Turno,
    TurnoOrigen,
)
from app.infrastructure.repositories import BaseRepository
from app.infrastructure.repositories_agenda import (
    BloqueoRepository,
    HorarioRepository,
    TurnoRepository,
)

BASE = datetime(2030, 3, 4, 12, 0, tzinfo=timezone.utc)  # fecha sintetica futura
DESDE, HASTA = BASE, BASE + timedelta(hours=4)  # rango consultado [12:00, 16:00)


def _h(minutos: int) -> datetime:
    return BASE + timedelta(minutes=minutos)


def _profesional(session: Session) -> Profesional:
    prof = Profesional(nombre="Dr. Sintetico", matricula=f"MAT-{uuid.uuid4().hex[:8]}")
    session.add(prof)
    session.flush()
    return prof


@pytest.fixture
def ctx(mig_session: Session):
    prof, otro = _profesional(mig_session), _profesional(mig_session)
    pac = Paciente(nombre="Paciente Sintetico", telefono="+5491100000000")
    mig_session.add(pac)
    mig_session.commit()
    return mig_session, prof, otro, pac


def _turno(prof, pac, ini: int, fin: int, **kw) -> Turno:
    datos = {
        "profesional_id": prof.id,
        "paciente_id": pac.id,
        "inicio": _h(ini),
        "fin": _h(fin),
        "origen": TurnoOrigen.ONLINE,
    }
    datos.update(kw)
    return Turno(**datos)


def test_repos_extienden_base_repository(mig_session: Session):
    assert isinstance(TurnoRepository(mig_session), BaseRepository)
    assert isinstance(BloqueoRepository(mig_session), BaseRepository)
    assert isinstance(HorarioRepository(mig_session), BaseRepository)


# --- TurnoRepository.ocupados_en_rango ---------------------------------------


def test_ocupados_en_rango_excluye_cancelados(ctx):
    session, prof, _, pac = ctx
    session.add_all(
        [
            _turno(prof, pac, 0, 30),
            _turno(prof, pac, 60, 90, estado=EstadoTurno.CANCELADO),
            _turno(prof, pac, 120, 150, estado=EstadoTurno.CONFIRMADO),
        ]
    )
    session.commit()

    ocupados = TurnoRepository(session).ocupados_en_rango(prof.id, DESDE, HASTA)

    assert ocupados == [(_h(0), _h(30)), (_h(120), _h(150))]


def test_ocupados_en_rango_excluye_turno_de_otro_profesional(ctx):
    session, prof, otro, pac = ctx
    session.add_all([_turno(prof, pac, 0, 30), _turno(otro, pac, 60, 90)])
    session.commit()

    assert TurnoRepository(session).ocupados_en_rango(prof.id, DESDE, HASTA) == [(_h(0), _h(30))]


def test_ocupados_en_rango_incluye_turno_que_cruza_el_borde(ctx):
    session, prof, _, pac = ctx
    session.add_all(
        [
            _turno(prof, pac, -30, 15),  # cruza el borde inicial
            _turno(prof, pac, 225, 270),  # cruza el borde final (hasta = +240)
        ]
    )
    session.commit()

    assert TurnoRepository(session).ocupados_en_rango(prof.id, DESDE, HASTA) == [
        (_h(-30), _h(15)),
        (_h(225), _h(270)),
    ]


def test_ocupados_en_rango_excluye_turnos_que_solo_tocan_el_borde(ctx):
    session, prof, _, pac = ctx
    session.add_all([_turno(prof, pac, -30, 0), _turno(prof, pac, 240, 270)])  # [) contiguos
    session.commit()

    assert TurnoRepository(session).ocupados_en_rango(prof.id, DESDE, HASTA) == []


def test_ocupados_en_rango_es_una_sola_query_con_solo_inicio_y_fin(ctx):
    session, prof, _, pac = ctx
    session.add_all([_turno(prof, pac, i * 30, i * 30 + 30) for i in range(5)])
    session.commit()
    prof_id = prof.id  # evita el refresh de atributos expirados dentro de la captura
    sentencias: list[str] = []

    def _capturar(conn, cursor, statement, *args):
        sentencias.append(statement)

    event.listen(session.get_bind(), "before_cursor_execute", _capturar)
    try:
        TurnoRepository(session).ocupados_en_rango(prof_id, DESDE, HASTA)
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", _capturar)

    assert len(sentencias) == 1
    select_cols = sentencias[0].split("FROM")[0]
    assert "inicio" in select_cols and "fin" in select_cols
    assert "token_publico" not in select_cols and "paciente_id" not in select_cols


# --- BloqueoRepository.ocupados_en_rango -------------------------------------


def test_bloqueo_ocupados_excluye_inactivo_y_otro_profesional(ctx):
    session, prof, otro, _ = ctx
    session.add_all(
        [
            Bloqueo(profesional_id=prof.id, desde=_h(0), hasta=_h(60), motivo="Activo"),
            Bloqueo(
                profesional_id=prof.id, desde=_h(90), hasta=_h(120), motivo="Baja", is_active=False
            ),
            Bloqueo(profesional_id=otro.id, desde=_h(0), hasta=_h(60), motivo="Ajeno"),
        ]
    )
    session.commit()

    assert BloqueoRepository(session).ocupados_en_rango(prof.id, DESDE, HASTA) == [
        (_h(0), _h(60))
    ]


def test_bloqueo_ocupados_incluye_el_que_cruza_el_borde(ctx):
    session, prof, _, _ = ctx
    session.add(Bloqueo(profesional_id=prof.id, desde=_h(-600), hasta=_h(30), motivo="Cruza"))
    session.commit()

    assert BloqueoRepository(session).ocupados_en_rango(prof.id, DESDE, HASTA) == [
        (_h(-600), _h(30))
    ]


def test_bloqueo_fuera_del_rango_excluido(ctx):
    session, prof, _, _ = ctx
    session.add(Bloqueo(profesional_id=prof.id, desde=_h(300), hasta=_h(360), motivo="Despues"))
    session.commit()

    assert BloqueoRepository(session).ocupados_en_rango(prof.id, DESDE, HASTA) == []


# --- HorarioRepository.activas_por_profesional --------------------------------


def _franja(prof, dia: int, ini: time, fin: time, **kw) -> HorarioProfesional:
    return HorarioProfesional(
        profesional_id=prof.id, dia_semana=dia, hora_inicio=ini, hora_fin=fin, **kw
    )


def test_activas_por_profesional_devuelve_franjas_de_dominio_ordenadas(ctx):
    session, prof, _, _ = ctx
    session.add_all(
        [
            _franja(prof, 1, time(9), time(13)),
            _franja(prof, 0, time(15), time(19)),
            _franja(prof, 0, time(9), time(13)),
        ]
    )
    session.commit()

    assert HorarioRepository(session).activas_por_profesional(prof.id) == [
        Franja(0, time(9), time(13)),
        Franja(0, time(15), time(19)),
        Franja(1, time(9), time(13)),
    ]


def test_activas_por_profesional_excluye_inactivas_y_de_otro_profesional(ctx):
    session, prof, otro, _ = ctx
    session.add_all(
        [
            _franja(prof, 0, time(9), time(13)),
            _franja(prof, 0, time(15), time(19), is_active=False),
            _franja(otro, 0, time(9), time(13)),
        ]
    )
    session.commit()

    assert HorarioRepository(session).activas_por_profesional(prof.id) == [
        Franja(0, time(9), time(13))
    ]


def test_activas_por_profesional_sin_franjas_devuelve_vacio(ctx):
    session, prof, _, _ = ctx

    assert HorarioRepository(session).activas_por_profesional(prof.id) == []
