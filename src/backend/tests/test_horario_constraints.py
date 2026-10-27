"""C-04 2.3: invariantes de franjas (horario_profesional) en la DB (PG real, migrada)."""

import uuid
from datetime import time

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.models import HorarioProfesional, Profesional

EXCLUSION_VIOLATION = "23P01"
CHECK_VIOLATION = "23514"


def _profesional(session: Session) -> Profesional:
    prof = Profesional(nombre="Dra. Sintetica", matricula=f"MAT-{uuid.uuid4().hex[:8]}")
    session.add(prof)
    session.flush()
    return prof


def _franja(prof: Profesional, dia: int, ini: time, fin: time, **kw) -> HorarioProfesional:
    return HorarioProfesional(
        profesional_id=prof.id, dia_semana=dia, hora_inicio=ini, hora_fin=fin, **kw
    )


def _rechaza(session: Session, franja: HorarioProfesional, sqlstate: str) -> None:
    session.add(franja)
    with pytest.raises(IntegrityError) as info:
        session.flush()
    assert info.value.orig.sqlstate == sqlstate  # type: ignore[union-attr]
    session.rollback()


def _cuenta(session: Session) -> int:
    return session.scalar(sa.select(sa.func.count()).select_from(HorarioProfesional))


@pytest.fixture
def prof(mig_session: Session) -> Profesional:
    p = _profesional(mig_session)
    mig_session.commit()
    return p


def test_franjas_solapadas_mismo_profesional_dia_rechazadas(mig_session: Session, prof):
    mig_session.add(_franja(prof, 0, time(9), time(13)))
    mig_session.commit()

    _rechaza(mig_session, _franja(prof, 0, time(12), time(14)), EXCLUSION_VIOLATION)


def test_franjas_contiguas_aceptadas(mig_session: Session, prof):
    mig_session.add_all([_franja(prof, 0, time(9), time(13)), _franja(prof, 0, time(13), time(17))])
    mig_session.commit()

    assert _cuenta(mig_session) == 2


def test_mismo_horario_otro_dia_aceptado(mig_session: Session, prof):
    mig_session.add_all([_franja(prof, 0, time(9), time(13)), _franja(prof, 1, time(9), time(13))])
    mig_session.commit()

    assert _cuenta(mig_session) == 2


def test_mismo_horario_otro_profesional_aceptado(mig_session: Session, prof):
    otro = _profesional(mig_session)
    mig_session.add_all([_franja(prof, 0, time(9), time(13)), _franja(otro, 0, time(9), time(13))])
    mig_session.commit()

    assert _cuenta(mig_session) == 2


def test_solape_con_franja_inactiva_aceptado(mig_session: Session, prof):
    mig_session.add(_franja(prof, 0, time(9), time(13), is_active=False))
    mig_session.commit()
    mig_session.add(_franja(prof, 0, time(12), time(14)))
    mig_session.commit()

    assert _cuenta(mig_session) == 2


@pytest.mark.parametrize("dia", [7, -1])
def test_dia_semana_fuera_de_rango_rechazado(mig_session: Session, prof, dia):
    _rechaza(mig_session, _franja(prof, dia, time(9), time(13)), CHECK_VIOLATION)


@pytest.mark.parametrize("ini,fin", [(time(13), time(13)), (time(13), time(9))])
def test_hora_fin_menor_o_igual_a_inicio_rechazada(mig_session: Session, prof, ini, fin):
    _rechaza(mig_session, _franja(prof, 0, ini, fin), CHECK_VIOLATION)
