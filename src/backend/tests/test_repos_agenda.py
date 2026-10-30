"""C-04 2.4: repositorios de agenda (queries de intervalo, una por tabla) contra PG migrada."""

import uuid
from datetime import datetime, time, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
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


# --- alta de turno sin deadlock: INSERT ... ON CONFLICT ON CONSTRAINT ex_turnos_sin_solape DO NOTHING ---
# Un INSERT comun contra la exclusion constraint puede deadlockear (40P01) con otro INSERT
# solapado concurrente; la insercion especulativa de ON CONFLICT no (Postgres evita la espera
# circular). La constraint sigue siendo la garantia: es el arbitro del ON CONFLICT.


def _alta(session: Session, prof, pac, ini: int, fin: int):
    return TurnoRepository(session).insertar_si_no_solapa(
        profesional_id=prof.id,
        paciente_id=pac.id,
        tratamiento_id=None,
        inicio=_h(ini),
        fin=_h(fin),
        origen=TurnoOrigen.ONLINE,
        token_publico=uuid.uuid4().hex,
        created_by=None,
    )


def _turnos_de(session: Session, prof) -> list[Turno]:
    session.expire_all()
    return list(session.scalars(sa.select(Turno).where(Turno.profesional_id == prof.id)))


def test_insertar_si_no_solapa_en_hueco_libre_devuelve_id_y_persiste(ctx):
    session, prof, _, pac = ctx

    turno_id = _alta(session, prof, pac, 0, 30)

    assert isinstance(turno_id, uuid.UUID)
    (fila,) = _turnos_de(session, prof)
    assert fila.id == turno_id
    assert (fila.inicio, fila.fin, fila.estado, fila.sobreturno) == (
        _h(0), _h(30), EstadoTurno.RESERVADO, False
    )


def test_insertar_si_no_solapa_ante_solape_devuelve_none_sin_insertar(ctx):
    session, prof, otro, pac = ctx
    existente = _alta(session, prof, pac, 0, 30)

    assert _alta(session, prof, pac, 15, 45) is None  # pisa [0, 30)
    assert [t.id for t in _turnos_de(session, prof)] == [existente]
    assert _alta(session, otro, pac, 15, 45) is not None  # otro profesional: libre


def test_insertar_si_no_solapa_respeta_el_where_de_la_constraint(ctx):
    session, prof, _, pac = ctx
    session.add(_turno(prof, pac, 0, 30, estado=EstadoTurno.CANCELADO))
    session.add(_turno(prof, pac, 30, 60, sobreturno=True))
    session.flush()

    assert _alta(session, prof, pac, 0, 30) is not None  # el cancelado no ocupa
    assert _alta(session, prof, pac, 30, 60) is not None  # el sobreturno no ocupa
    assert len(_turnos_de(session, prof)) == 4


def test_insertar_si_no_solapa_no_enmascara_otras_violaciones(ctx):
    session, prof, _, pac = ctx

    with pytest.raises(IntegrityError) as info:
        _alta(session, prof, pac, 30, 30)  # fin > inicio (CHECK), no es solape

    assert info.value.orig.sqlstate == "23514"
    session.rollback()


# --- C-05 3.2: excluir_turno_id (D5) --------------------------------------------


def test_ocupados_en_rango_excluye_el_turno_indicado(ctx):
    session, prof, _, pac = ctx
    propio = _turno(prof, pac, 0, 30)
    ajeno = _turno(prof, pac, 60, 90)
    session.add_all([propio, ajeno])
    session.flush()
    repo = TurnoRepository(session)

    assert repo.ocupados_en_rango(prof.id, DESDE, HASTA, excluir_turno_id=propio.id) == [
        (_h(60), _h(90))
    ]
    assert repo.ocupados_en_rango(prof.id, DESDE, HASTA) == [(_h(0), _h(30)), (_h(60), _h(90))]


def test_excluir_un_id_ajeno_no_cambia_el_resultado(ctx):
    session, prof, _, pac = ctx
    session.add(_turno(prof, pac, 0, 30))
    session.flush()
    repo = TurnoRepository(session)

    assert repo.ocupados_en_rango(
        prof.id, DESDE, HASTA, excluir_turno_id=uuid.uuid4()
    ) == repo.ocupados_en_rango(prof.id, DESDE, HASTA)


def test_con_dos_turnos_solapados_se_excluye_solo_el_indicado(ctx):
    session, prof, _, pac = ctx
    base = _turno(prof, pac, 0, 30)
    sobre = _turno(prof, pac, 0, 30, sobreturno=True)
    session.add_all([base, sobre])
    session.flush()

    assert TurnoRepository(session).ocupados_en_rango(
        prof.id, DESDE, HASTA, excluir_turno_id=base.id
    ) == [(_h(0), _h(30))]


def test_hay_ocupacion_propaga_excluir_turno_id_solo_a_turnos(ctx):
    from app.application.reservas import hay_ocupacion

    session, prof, _, pac = ctx
    propio = _turno(prof, pac, 0, 30)
    session.add(propio)
    session.add(Bloqueo(profesional_id=prof.id, desde=_h(60), hasta=_h(90), motivo="x"))
    session.flush()

    assert hay_ocupacion(session, prof.id, _h(0), _h(30)) is True
    assert hay_ocupacion(session, prof.id, _h(0), _h(30), excluir_turno_id=propio.id) is False
    # el bloqueo sigue contando aunque se excluya un turno
    assert hay_ocupacion(session, prof.id, _h(60), _h(90), excluir_turno_id=propio.id) is True


# --- C-05 3.3: insertar_si_no_solapa(sobreturno=...) (D2) -------------------------


def _alta_sobre(session: Session, prof, pac, ini: int, fin: int, **kw):
    return TurnoRepository(session).insertar_si_no_solapa(
        profesional_id=prof.id,
        paciente_id=pac.id,
        tratamiento_id=None,
        inicio=_h(ini),
        fin=_h(fin),
        origen=TurnoOrigen.SECRETARIA,
        token_publico=uuid.uuid4().hex,
        created_by=None,
        **kw,
    )


def test_insertar_sobreturno_coexiste_con_turno_solapado(ctx):
    session, prof, _, pac = ctx
    existente = _alta_sobre(session, prof, pac, 0, 30)

    sobre = _alta_sobre(session, prof, pac, 0, 30, sobreturno=True)

    assert sobre is not None and sobre != existente
    filas = {t.id: t for t in _turnos_de(session, prof)}
    assert filas[sobre].sobreturno is True and filas[existente].sobreturno is False


def test_insertar_sin_marca_sobre_hueco_ocupado_devuelve_none(ctx):
    session, prof, _, pac = ctx
    _alta_sobre(session, prof, pac, 0, 30)

    assert _alta_sobre(session, prof, pac, 0, 30) is None
    assert len(_turnos_de(session, prof)) == 1


def test_insertar_por_defecto_persiste_sobreturno_false(ctx):
    session, prof, _, pac = ctx
    _alta_sobre(session, prof, pac, 0, 30, sobreturno=False)
    (fila,) = _turnos_de(session, prof)
    assert fila.sobreturno is False


# --- C-05 3.4: lecturas y lock de agenda (D4) --------------------------------------


def _lock_corto(session: Session) -> None:
    session.execute(sa.text("SET LOCAL lock_timeout = '300ms'"))


def test_bloquear_agenda_serializa_por_profesional(ctx):
    from sqlalchemy.exc import OperationalError

    session, prof, _, _ = ctx
    engine = session.get_bind()
    primera, segunda = Session(engine), Session(engine)
    try:
        TurnoRepository(primera).bloquear_agenda(prof.id)
        _lock_corto(segunda)
        with pytest.raises(OperationalError) as info:
            TurnoRepository(segunda).bloquear_agenda(prof.id)
        assert info.value.orig.sqlstate == "55P03"  # lock_not_available
    finally:
        segunda.rollback()
        segunda.close()
        primera.rollback()
        primera.close()


def test_bloquear_agenda_otro_profesional_no_espera(ctx):
    session, prof, otro, _ = ctx
    engine = session.get_bind()
    primera, segunda = Session(engine), Session(engine)
    try:
        TurnoRepository(primera).bloquear_agenda(prof.id)
        _lock_corto(segunda)
        TurnoRepository(segunda).bloquear_agenda(otro.id)  # no lanza
    finally:
        segunda.rollback()
        segunda.close()
        primera.rollback()
        primera.close()


def test_bloquear_agenda_se_libera_al_cerrar_la_transaccion(ctx):
    session, prof, _, _ = ctx
    engine = session.get_bind()
    primera, segunda = Session(engine), Session(engine)
    try:
        TurnoRepository(primera).bloquear_agenda(prof.id)
        primera.commit()  # libera el lock xact
        _lock_corto(segunda)
        TurnoRepository(segunda).bloquear_agenda(prof.id)  # no lanza
    finally:
        segunda.rollback()
        segunda.close()
        primera.close()


def test_profesional_de_devuelve_el_profesional_o_none(ctx):
    session, prof, otro, pac = ctx
    turno = _turno(otro, pac, 0, 30)
    session.add(turno)
    session.flush()
    repo = TurnoRepository(session)

    assert repo.profesional_de(turno.id) == otro.id
    assert repo.profesional_de(uuid.uuid4()) is None


def test_obtener_para_actualizar_devuelve_el_turno_con_for_update(ctx):
    session, prof, _, pac = ctx
    turno = _turno(prof, pac, 0, 30)
    session.add(turno)
    session.commit()
    repo = TurnoRepository(session)

    obtenido = repo.obtener_para_actualizar(turno.id)
    assert obtenido is not None and obtenido.id == turno.id
    assert repo.obtener_para_actualizar(uuid.uuid4()) is None

    otra = Session(session.get_bind())
    try:
        _lock_corto(otra)
        with pytest.raises(sa.exc.OperationalError):
            TurnoRepository(otra).obtener_para_actualizar(turno.id)
    finally:
        otra.rollback()
        otra.close()
        session.rollback()


# --- C-05 3.5: PacienteRepository.buscar_por_telefono (D2) -------------------------


def test_buscar_por_telefono_devuelve_el_mas_antiguo(mig_session: Session):
    from app.infrastructure.repositories import PacienteRepository

    nuevo = Paciente(nombre="Nuevo Sintetico", telefono="+5491100000001")
    viejo = Paciente(nombre="Viejo Sintetico", telefono="+5491100000001")
    mig_session.add_all([nuevo, viejo])
    mig_session.flush()
    nuevo.created_at = BASE
    viejo.created_at = BASE - timedelta(days=1)
    mig_session.flush()

    assert PacienteRepository(mig_session).buscar_por_telefono("+5491100000001").id == viejo.id


def test_buscar_por_telefono_sin_pacientes_devuelve_none(mig_session: Session):
    from app.infrastructure.repositories import PacienteRepository

    mig_session.add(Paciente(nombre="Otro Sintetico", telefono="+5491100000002"))
    mig_session.flush()

    assert PacienteRepository(mig_session).buscar_por_telefono("+5491100000003") is None


def test_buscar_por_telefono_ignora_inactivos(mig_session: Session):
    from app.infrastructure.repositories import PacienteRepository

    inactivo = Paciente(nombre="Baja Sintetica", telefono="+5491100000004")
    mig_session.add(inactivo)
    mig_session.flush()
    inactivo.soft_delete()
    mig_session.flush()
    repo = PacienteRepository(mig_session)
    assert repo.buscar_por_telefono("+5491100000004") is None

    activo = Paciente(nombre="Alta Sintetica", telefono="+5491100000004")
    mig_session.add(activo)
    mig_session.flush()
    assert repo.buscar_por_telefono("+5491100000004").id == activo.id
