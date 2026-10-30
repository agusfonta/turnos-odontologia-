"""Casos de uso de lectura de la agenda interna (C-06 D6). Todo `def`, sin UoW ni commit.

`consultar_agenda` recibe la sesion de `get_db` (lectura pura): una query de turnos
(`turnos JOIN pacientes LEFT JOIN tratamientos`, sin N+1) y una de bloqueos activos.
`resolver_profesional_agenda` aplica el aislamiento por rol (US-003 CA-2) ANTES de leer
nada del profesional pedido:
  * secretaria: `profesional_id` obligatorio (422), puede ver cualquiera;
  * odontologo: solo el profesional vinculado a su usuario (`profesionales.user_id`);
    sin vinculo 403 `sin_profesional_asociado`; otro profesional 403 `agenda_ajena`
    (tambien si el id no existe: no se revela la existencia).
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.exceptions import (
    AgendaAjenaError,
    ProfesionalNoEncontradoError,
    ProfesionalRequeridoError,
    SinProfesionalAsociadoError,
)
from app.domain.agenda import AgendaTurno, Vista, limites_instantes, rango_agenda
from app.infrastructure.models import Profesional, UserRole
from app.infrastructure.repositories import BaseRepository, ProfesionalRepository
from app.infrastructure.repositories_agenda import BloqueoRepository, TurnoRepository


@dataclass(frozen=True, slots=True)
class BloqueoAgenda:
    id: uuid.UUID
    desde: datetime
    hasta: datetime
    motivo: str


@dataclass(frozen=True, slots=True)
class AgendaDTO:
    profesional_id: uuid.UUID
    profesional_nombre: str
    vista: Vista
    desde: date
    hasta: date
    turnos: list[AgendaTurno]
    bloqueos: list[BloqueoAgenda]


def resolver_profesional_agenda(
    session: Session,
    *,
    rol: UserRole,
    user_id: uuid.UUID,
    profesional_id: uuid.UUID | None,
) -> uuid.UUID:
    """Profesional cuya agenda puede ver el usuario (levanta 422/403 segun la regla de rol)."""
    if rol is UserRole.SECRETARIA:
        if profesional_id is None:
            raise ProfesionalRequeridoError()
        return profesional_id
    propio = ProfesionalRepository(session).por_user_id(user_id)
    if propio is None:
        raise SinProfesionalAsociadoError()
    if profesional_id is not None and profesional_id != propio.id:
        raise AgendaAjenaError()
    return propio.id


def consultar_agenda(
    session: Session, *, profesional_id: uuid.UUID, dia: date, vista: Vista, tz: ZoneInfo
) -> AgendaDTO:
    """Agenda del dia o de la semana (lunes..domingo) del profesional; 404 si no existe.

    El profesional inactivo se muestra (la agenda es historica para el staff).
    """
    profesional = BaseRepository(session, Profesional).get(profesional_id)
    if profesional is None:
        raise ProfesionalNoEncontradoError()
    desde, hasta = rango_agenda(dia, vista)
    ini, fin = limites_instantes(desde, hasta, tz)
    turnos = TurnoRepository(session).agenda_en_rango(profesional_id, ini, fin)
    bloqueos = [
        BloqueoAgenda(id=b.id, desde=b.desde, hasta=b.hasta, motivo=b.motivo)
        for b in BloqueoRepository(session).activos_en_rango(profesional_id, ini, fin)
    ]
    return AgendaDTO(
        profesional_id=profesional.id,
        profesional_nombre=profesional.nombre,
        vista=vista,
        desde=desde,
        hasta=hasta,
        turnos=turnos,
        bloqueos=bloqueos,
    )
