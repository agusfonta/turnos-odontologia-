"""GET /api/agenda: agenda interna por profesional (C-06), dia o semana.

Solo staff autenticado (`require_staff`: secretaria u odontologo; 401 sin token/invalido).
Lectura pura (`get_db`, sin UoW ni commit). La secretaria elige el profesional; el
odontologo solo ve el suyo (aislamiento resuelto ANTES de leer nada, ver `application/agenda`).
Todo `def` (las llamadas a la DB son bloqueantes).
"""

import uuid
from datetime import date
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_staff
from app.application.agenda import AgendaDTO, consultar_agenda, resolver_profesional_agenda
from app.core.db import get_db
from app.core.settings import get_settings
from app.domain.agenda import Vista
from app.domain.schemas import (
    AgendaBloqueoOut,
    AgendaOut,
    AgendaPacienteOut,
    AgendaProfesionalOut,
    AgendaTratamientoOut,
    AgendaTurnoOut,
)
from app.infrastructure.models import User

router = APIRouter(prefix="/agenda", tags=["agenda"])

DbDep = Annotated[Session, Depends(get_db)]
StaffDep = Annotated[User, Depends(require_staff)]


def _out(dto: AgendaDTO, tz: ZoneInfo) -> AgendaOut:
    return AgendaOut(
        profesional=AgendaProfesionalOut(id=dto.profesional_id, nombre=dto.profesional_nombre),
        vista=dto.vista,
        desde=dto.desde,
        hasta=dto.hasta,
        turnos=[
            AgendaTurnoOut(
                id=t.id,
                inicio=t.inicio.astimezone(tz),
                fin=t.fin.astimezone(tz),
                estado=t.estado.value,
                origen=t.origen,  # type: ignore[arg-type]
                sobreturno=t.sobreturno,
                paciente=AgendaPacienteOut(
                    id=t.paciente_id, nombre=t.paciente_nombre, telefono=t.paciente_telefono
                ),
                tratamiento=(
                    AgendaTratamientoOut(id=t.tratamiento_id, nombre=t.tratamiento_nombre)
                    if t.tratamiento_id is not None and t.tratamiento_nombre is not None
                    else None
                ),
            )
            for t in dto.turnos
        ],
        bloqueos=[
            AgendaBloqueoOut(
                id=b.id,
                desde=b.desde.astimezone(tz),
                hasta=b.hasta.astimezone(tz),
                motivo=b.motivo,
            )
            for b in dto.bloqueos
        ],
    )


@router.get("", response_model=AgendaOut)
def obtener_agenda(
    db: DbDep,
    usuario: StaffDep,
    dia: Annotated[date, Query(description="Fecha local de la clínica")],
    vista: Annotated[Vista, Query()] = "dia",
    profesional_id: Annotated[uuid.UUID | None, Query()] = None,
) -> AgendaOut:
    tz = ZoneInfo(get_settings().CLINIC_TIMEZONE)
    objetivo = resolver_profesional_agenda(
        db, rol=usuario.rol, user_id=usuario.id, profesional_id=profesional_id
    )
    dto = consultar_agenda(db, profesional_id=objetivo, dia=dia, vista=vista, tz=tz)
    return _out(dto, tz)
