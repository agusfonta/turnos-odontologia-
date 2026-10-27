"""POST /api/turnos: reserva de turno (C-04)."""

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_optional_staff
from app.application.reservas import reservar_turno
from app.core.clock import get_ahora
from app.core.db import get_db
from app.core.settings import get_settings
from app.domain.schemas import TurnoCreado, TurnoCreate
from app.infrastructure.jobs import RecordatorioQueue, get_recordatorio_queue
from app.infrastructure.models import User

router = APIRouter(prefix="/turnos", tags=["turnos"])

DbDep = Annotated[Session, Depends(get_db)]
AhoraDep = Annotated[datetime, Depends(get_ahora)]
StaffDep = Annotated[User | None, Depends(get_optional_staff)]
ColaDep = Annotated[RecordatorioQueue, Depends(get_recordatorio_queue)]


@router.post("", response_model=TurnoCreado, status_code=status.HTTP_201_CREATED)
def crear_turno(
    datos: TurnoCreate, db: DbDep, ahora: AhoraDep, staff: StaffDep, cola: ColaDep
) -> TurnoCreado:
    tz = ZoneInfo(get_settings().CLINIC_TIMEZONE)
    turno = reservar_turno(db, datos, staff=staff, ahora=ahora, tz=tz)  # commit adentro
    cola.encolar(turno.id, turno.inicio)  # post-commit; nunca lanza
    return TurnoCreado(
        id=turno.id,
        profesional_id=turno.profesional_id,
        tratamiento_id=turno.tratamiento_id,
        inicio=turno.inicio.astimezone(tz),
        fin=turno.fin.astimezone(tz),
        estado="reservado",
        origen=turno.origen.value,
        token_publico=turno.token_publico,
    )
