"""C-04 2.2: invariantes de turnos/bloqueos/auditoria_turno en la DB (PG real, migrada)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.domain.turno_estados import EstadoTurno
from app.infrastructure.models import (
    AuditoriaActor,
    AuditoriaTurno,
    Bloqueo,
    Paciente,
    Profesional,
    Turno,
    TurnoOrigen,
)

EXCLUSION_VIOLATION = "23P01"
UNIQUE_VIOLATION = "23505"
CHECK_VIOLATION = "23514"
RESTRICT_VIOLATION = "23001"

BASE = datetime(2030, 3, 4, 12, 0, tzinfo=timezone.utc)  # fecha sintetica futura


def _hora(offset_min: int) -> datetime:
    return BASE + timedelta(minutes=offset_min)


def _profesional(session: Session) -> Profesional:
    prof = Profesional(nombre="Dr. Sintetico", matricula=f"MAT-{uuid.uuid4().hex[:8]}")
    session.add(prof)
    session.flush()
    return prof


def _paciente(session: Session) -> Paciente:
    pac = Paciente(nombre="Paciente Sintetico", telefono="+5491100000000")
    session.add(pac)
    session.flush()
    return pac


def _turno(prof, pac, ini: int, fin: int, **kw) -> Turno:
    datos = {
        "profesional_id": prof.id,
        "paciente_id": pac.id,
        "inicio": _hora(ini),
        "fin": _hora(fin),
        "origen": TurnoOrigen.ONLINE,
    }
    datos.update(kw)
    return Turno(**datos)


def _sqlstate(exc: DBAPIError) -> str:
    return exc.orig.sqlstate  # type: ignore[union-attr]


def _rechaza(session: Session, entidad, sqlstate: str) -> None:
    session.add(entidad)
    with pytest.raises(IntegrityError) as info:
        session.flush()
    assert _sqlstate(info.value) == sqlstate
    session.rollback()


def _cuenta(session: Session, modelo) -> int:
    return session.scalar(sa.select(sa.func.count()).select_from(modelo))


@pytest.fixture
def base(mig_session: Session):
    prof, pac = _profesional(mig_session), _paciente(mig_session)
    mig_session.commit()
    return mig_session, prof, pac


def test_insert_solapado_mismo_profesional_rechazado(base):
    session, prof, pac = base
    session.add(_turno(prof, pac, 0, 30))
    session.commit()

    _rechaza(session, _turno(prof, pac, 15, 45), EXCLUSION_VIOLATION)


def test_turnos_contiguos_semiabierto_aceptados(base):
    session, prof, pac = base
    session.add_all([_turno(prof, pac, 0, 30), _turno(prof, pac, 30, 60)])
    session.commit()

    assert _cuenta(session, Turno) == 2


def test_mismo_horario_otro_profesional_aceptado(base):
    session, prof, pac = base
    otro = _profesional(session)
    session.add_all([_turno(prof, pac, 0, 30), _turno(otro, pac, 0, 30)])
    session.commit()

    assert _cuenta(session, Turno) == 2


def test_solape_con_turno_cancelado_aceptado(base):
    session, prof, pac = base
    session.add(_turno(prof, pac, 0, 30, estado=EstadoTurno.CANCELADO))
    session.commit()
    session.add(_turno(prof, pac, 0, 30))
    session.commit()

    assert _cuenta(session, Turno) == 2


def test_solape_con_sobreturno_aceptado(base):
    session, prof, pac = base
    session.add(_turno(prof, pac, 0, 30))
    session.commit()
    session.add(_turno(prof, pac, 0, 30, sobreturno=True))
    session.commit()

    assert _cuenta(session, Turno) == 2


def test_turno_fin_menor_o_igual_a_inicio_rechazado(base):
    session, prof, pac = base
    _rechaza(session, _turno(prof, pac, 30, 30), CHECK_VIOLATION)
    _rechaza(session, _turno(prof, pac, 30, 0), CHECK_VIOLATION)


def test_token_publico_duplicado_rechazado(base):
    session, prof, pac = base
    session.add(_turno(prof, pac, 0, 30, token_publico="tok-sintetico-1"))
    session.commit()

    _rechaza(session, _turno(prof, pac, 60, 90, token_publico="tok-sintetico-1"), UNIQUE_VIOLATION)


def test_token_publico_nulo_repetido_aceptado(base):
    session, prof, pac = base
    session.add_all([_turno(prof, pac, 0, 30), _turno(prof, pac, 60, 90)])
    session.commit()

    assert _cuenta(session, Turno) == 2


def _turno_con_auditoria(session: Session, prof, pac) -> AuditoriaTurno:
    turno = _turno(prof, pac, 0, 30)
    session.add(turno)
    session.flush()
    aud = AuditoriaTurno(turno_id=turno.id, accion="crear", actor_tipo=AuditoriaActor.PACIENTE)
    session.add(aud)
    session.commit()
    return aud


def test_auditoria_insert_permitido_con_detalle_default(base):
    session, prof, pac = base
    aud = _turno_con_auditoria(session, prof, pac)

    assert session.get(AuditoriaTurno, aud.id).detalle == {}


def test_auditoria_update_rechazado_por_trigger(base):
    session, prof, pac = base
    aud = _turno_con_auditoria(session, prof, pac)

    with pytest.raises(IntegrityError) as info:
        session.execute(
            sa.text("UPDATE auditoria_turno SET accion='editada' WHERE id=:i"), {"i": aud.id}
        )
    assert _sqlstate(info.value) == RESTRICT_VIOLATION
    assert "append-only" in str(info.value)


def test_auditoria_delete_rechazado_por_trigger(base):
    session, prof, pac = base
    aud = _turno_con_auditoria(session, prof, pac)

    with pytest.raises(IntegrityError) as info:
        session.execute(sa.text("DELETE FROM auditoria_turno WHERE id=:i"), {"i": aud.id})
    assert _sqlstate(info.value) == RESTRICT_VIOLATION
    session.rollback()
    assert session.get(AuditoriaTurno, aud.id) is not None


def test_bloqueo_hasta_menor_o_igual_a_desde_rechazado(base):
    session, prof, _ = base
    _rechaza(
        session,
        Bloqueo(profesional_id=prof.id, desde=_hora(60), hasta=_hora(60), motivo="x"),
        CHECK_VIOLATION,
    )
    _rechaza(
        session,
        Bloqueo(profesional_id=prof.id, desde=_hora(60), hasta=_hora(30), motivo="x"),
        CHECK_VIOLATION,
    )


def test_bloqueo_valido_aceptado(base):
    session, prof, _ = base
    session.add(Bloqueo(profesional_id=prof.id, desde=_hora(0), hasta=_hora(240), motivo="Curso"))
    session.commit()

    assert _cuenta(session, Bloqueo) == 1


def test_auditoria_truncate_rechazado_por_trigger(base):
    session, prof, pac = base
    aud = _turno_con_auditoria(session, prof, pac)

    with pytest.raises(DBAPIError) as info:
        session.execute(sa.text("TRUNCATE auditoria_turno"))
    assert _sqlstate(info.value) == RESTRICT_VIOLATION
    assert "append-only" in str(info.value)
    session.rollback()
    assert session.get(AuditoriaTurno, aud.id) is not None


def test_auditoria_truncate_en_cascada_desde_turnos_rechazado(base):
    session, prof, pac = base
    _turno_con_auditoria(session, prof, pac)

    with pytest.raises(DBAPIError) as info:
        session.execute(sa.text("TRUNCATE turnos CASCADE"))
    assert _sqlstate(info.value) == RESTRICT_VIOLATION
