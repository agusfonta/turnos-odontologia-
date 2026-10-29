"""POST /api/turnos: reserva de turno (C-04, C-04b).

Patron de efectos post-commit (copiar en C-05/C-07): el caso de uso es el limite
de la transaccion (si retorna, ya hubo commit); los efectos externos (encolar en
Redis) se ejecutan aca, DESPUES de que retorno, con el DTO. Cualquier excepcion
del caso de uso sale antes del efecto, asi que nunca se encola sin commit.
"""

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, status

from app.api.deps import get_optional_staff
from app.application.reservas import reservar_turno
from app.core.clock import get_ahora
from app.core.settings import get_settings
from app.domain.schemas import TurnoCreado, TurnoCreate
from app.infrastructure.jobs import RecordatorioQueue, get_recordatorio_queue
from app.infrastructure.models import User
from app.infrastructure.unit_of_work import UowFactory, get_uow_factory

router = APIRouter(prefix="/turnos", tags=["turnos"])

UowDep = Annotated[UowFactory, Depends(get_uow_factory)]
AhoraDep = Annotated[datetime, Depends(get_ahora)]
StaffDep = Annotated[User | None, Depends(get_optional_staff)]
ColaDep = Annotated[RecordatorioQueue, Depends(get_recordatorio_queue)]


@router.post("", response_model=TurnoCreado, status_code=status.HTTP_201_CREATED)
def crear_turno(
    datos: TurnoCreate, uow_factory: UowDep, ahora: AhoraDep, staff: StaffDep, cola: ColaDep
) -> TurnoCreado:
    tz = ZoneInfo(get_settings().CLINIC_TIMEZONE)
    reservado = reservar_turno(
        uow_factory, datos, staff_id=staff.id if staff else None, ahora=ahora, tz=tz
    )  # el commit ocurre dentro de la UoW del caso de uso
    cola.encolar(reservado.id, reservado.inicio)  # post-commit; nunca lanza
    return TurnoCreado(
        id=reservado.id,
        profesional_id=reservado.profesional_id,
        tratamiento_id=reservado.tratamiento_id,
        inicio=reservado.inicio.astimezone(tz),
        fin=reservado.fin.astimezone(tz),
        estado="reservado",
        origen=reservado.origen,
        token_publico=reservado.token_publico,
    )
